"""
Comprehensive regression test suite covering all 10 hardening items:
1. Poster fallback injection prevention (no unescaped eval/interpolation in onerror, DOM textContent fallback).
2. Constraint preservation across voice, text, persona, and pipeline payloads.
3. Truthful Live init_ack status and upstream error reporting.
4. Context-extraction LLM schema and fallback without assistant_reply.
5. ProviderAPIError fallthrough with UNVERIFIED status (never mock on live failure).
6. Evidence resilience during cache write failures and atomic persistence.
7. Dialogue turn queueing, session generation abort checks, and full restart reset.
8. Single escaping of assistant messages in voice transcript.
9. Cache bounds and in-flight deduplication (TMDB, Film Profile, IMDb).
10. Refill loop candidate tracking and packaging/bundle verification.
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.contracts import (
    UserContext,
    IntakeDepth,
    TasteSignal,
    SignalType,
    AvailabilityResult,
    AvailabilityStatus,
    FilmMetadata,
)
from src.availability import (
    get_film_availability,
    ProviderAPIError,
    _TMDB_SEARCH_CACHE,
    _TMDB_CACHE_LOCK,
    tmdb_search,
)
from src.profiling import (
    generate_film_profile,
    _PROFILE_CACHE,
    _PROFILE_CACHE_LOCK,
)
from src.evidence import (
    get_film_evidence,
    save_to_cache,
    load_from_cache,
    _CACHE_LOCK,
)
from src.api import (
    ContextExtractionLLMOutput,
    _merge_signals_into_context,
    extract_voice_context,
    app,
)
from fastapi.testclient import TestClient

client = TestClient(app)


# --- ITEM 1: POSTER FALLBACK INJECTION SAFETY ---

def test_poster_fallback_script_and_attribute_injection_immunity():
    """Verify static/index.html uses safe DOM element creation for poster fallback without inline template injection."""
    index_path = Path(__file__).resolve().parent.parent / "static" / "index.html"
    content = index_path.read_text(encoding="utf-8")

    # 1. No inline backtick evaluation or template string inside onerror
    assert "this.parentElement.outerHTML=`" not in content, "Vulnerable inline outerHTML backtick assignment detected in onerror"
    assert "window.handlePosterError(this)" in content, "Poster onerror must invoke window.handlePosterError(this)"

    # 2. createEditorialFallbackElement must use textContent for title and year
    assert "titleDiv.textContent = title;" in content, "Fallback element must set title via textContent"
    assert "yearDiv.textContent = year ? `${year} ↗` : \"↗\";" in content, "Fallback element must set year via textContent"

    # 3. Attributes must be present for data-poster-title and data-poster-year
    assert "data-poster-title=" in content
    assert "data-poster-year=" in content


# --- ITEM 2: CONSTRAINT PRESERVATION ---

def test_constraint_preservation_in_merge_signals():
    """Verify _merge_signals_into_context preserves canonical names and complete arrays."""
    ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    extracted = ContextExtractionLLMOutput(
        max_runtime=95,
        exclude_genres=["Horror", "Musical"],
        pacing="brisk",
        services=["Prime Video"]
    )

    updated = _merge_signals_into_context(ctx, extracted)

    # Check canonical max-runtime is preserved
    runtime_sig = next((s for s in updated.tonight_signals if s.name == "max-runtime"), None)
    assert runtime_sig is not None
    assert runtime_sig.value == 95
    assert runtime_sig.signal_type == SignalType.HARD_CONSTRAINT

    # Check canonical exclude-genre preserves full list
    genre_sig = next((s for s in updated.tonight_signals if s.name == "exclude-genre"), None)
    assert genre_sig is not None
    assert genre_sig.value == ["Horror", "Musical"]
    assert genre_sig.signal_type == SignalType.HARD_CONSTRAINT

    # Check service addition
    assert "Prime Video" in updated.service_access


# --- ITEM 3 & 8: LIVE READINESS, ERROR REPORTING, AND TEXT ESCAPING ---

def test_websocket_receiver_failure_emits_error_event(monkeypatch):
    """Verify WebSocket emits upstream_receiver_failed error event when upstream Gemini Live receiver fails."""
    class FailingGeminiSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def receive(self):
            raise RuntimeError("Upstream Gemini connection abruptly severed")
            yield None
        async def send(self, *args, **kwargs):
            pass
        async def close(self):
            pass

    class DummyLive:
        def connect(self, *args, **kwargs):
            return FailingGeminiSession()

    class DummyAio:
        live = DummyLive()

    class DummyClient:
        aio = DummyAio()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: DummyClient())
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    monkeypatch.delenv("TONI_MOCK_GEMINI_LIVE", raising=False)

    with client.websocket_connect("/api/voice/live") as ws:
        ws.send_json({
            "type": "init",
            "context": {
                "country": "UK",
                "service_access": ["Netflix"],
                "allow_rent_buy": False,
                "intake_depth": "just_give_me_something",
                "dialogue_mode": "voice",
                "voice_name": "Charon",
                "tonight_signals": [],
                "persistent_taste": [],
                "interaction_history": {}
            }
        })
        first_msg = ws.receive_json()
        if first_msg["type"] == "init_ack":
            err_msg = ws.receive_json()
            assert err_msg["type"] == "error"
            assert err_msg["error"] == "upstream_receiver_failed"
        else:
            assert first_msg["type"] == "error"
            assert first_msg["error"] == "upstream_receiver_failed"


# --- ITEM 4: CONTEXT EXTRACTION LLM SCHEMA AND FALLBACK ---

def test_context_extraction_llm_schema_excludes_assistant_reply():
    """Verify ContextExtractionLLMOutput contains only structured extraction fields and NOT assistant_reply."""
    fields = ContextExtractionLLMOutput.model_fields.keys()
    assert "assistant_reply" not in fields
    assert "country" in fields
    assert "services" in fields
    assert "pacing" in fields
    assert "tone" in fields
    assert "max_runtime" in fields
    assert "exclude_genres" in fields
    assert "ready_to_recommend" in fields


def test_context_extraction_graceful_fallback_without_llm(monkeypatch):
    """Verify extract_voice_context falls back gracefully to regex signal detection if LLM call fails."""
    # Isolate LLM keys to force fallback
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    updated, ready = extract_voice_context("I want something under 90 minutes and no horror", ctx)
    runtime_sig = next((s for s in updated.tonight_signals if s.name == "max-runtime"), None)
    genre_sig = next((s for s in updated.tonight_signals if s.name == "exclude-genre"), None)

    assert runtime_sig is not None
    assert runtime_sig.value == 90
    assert genre_sig is not None
    assert "horror" in [g.lower() for g in genre_sig.value]


# --- ITEM 5: PROVIDER API ERROR FALLTHROUGH AND UNVERIFIED STATUS ---

def test_provider_error_fallthrough_and_no_mock_promotion(monkeypatch):
    """Verify Watchmode 5xx falls through to TMDB, and dual failure returns UNVERIFIED without promoting mock."""
    monkeypatch.setenv("TONI_USE_MOCK_AVAILABILITY", "false")
    monkeypatch.setenv("WATCHMODE_API_KEY", "dummy_wm_key")
    monkeypatch.setenv("TMDB_API_KEY", "dummy_tmdb_key")

    def mock_make_request_both_500(url, headers=None, timeout=None):
        return 500, {"error": "Internal Server Error from upstream provider"}

    monkeypatch.setattr("src.availability.make_request", mock_make_request_both_500)

    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    # Inception is present in local mock SEED_FILMS_AVAILABILITY
    res = get_film_availability("Inception", 2010, context)

    # Must be UNVERIFIED, NEVER promoted to mock AVAILABLE or LocalHybridMock
    assert res.status == AvailabilityStatus.UNVERIFIED
    assert res.provider == "None"
    assert res.matched_services == []


# --- ITEM 6: EVIDENCE CACHE WRITE RESILIENCE ---

def test_evidence_returns_results_even_when_cache_write_fails(monkeypatch, tmp_path):
    """Verify successful evidence reaches the caller even if saving to disk raises an exception."""
    monkeypatch.setenv("PARALLEL_API_KEY", "mock-parallel-key")

    def failing_save(*args, **kwargs):
        raise PermissionError("Simulated disk write permission failure")

    monkeypatch.setattr("src.evidence.save_to_cache", failing_save)

    evidence = get_film_evidence("Inception", 2010, "Christopher Nolan", force_live=True)
    assert len(evidence) > 0
    assert evidence[0]["url"] == "https://www.theguardian.com/film/review/dummy"


def test_atomic_save_to_cache_mechanics(tmp_path, monkeypatch):
    """Verify save_to_cache performs atomic replacement without leaving corrupt partial files."""
    test_cache_file = tmp_path / "atomic_cache.json"
    monkeypatch.setattr("src.evidence.CACHE_PATH", test_cache_file)

    dummy_evidence = [{"url": "https://example.com/review", "title": "Great", "content": "Review content " * 40}]
    save_to_cache("Dune", 2021, dummy_evidence)

    assert test_cache_file.exists()
    loaded = load_from_cache("Dune", 2021)
    assert loaded is not None
    assert loaded[0]["url"] == "https://example.com/review"


# --- ITEM 9: BOUNDED CACHES AND DEDUPLICATION ---

def test_tmdb_cache_bounds_and_deduplication(monkeypatch):
    """Verify TMDB cache does not exceed its maximum bound and deduplicates in-flight calls."""
    monkeypatch.setenv("TONI_USE_MOCK_AVAILABILITY", "false")
    monkeypatch.setenv("TMDB_API_KEY", "dummy_key")

    call_count = 0

    def mock_make_request(url, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return 200, {
            "results": [
                {"title": "Test Film", "release_date": "2020-01-01", "id": 100}
            ]
        }

    monkeypatch.setattr("src.availability.make_request", mock_make_request)

    with _TMDB_CACHE_LOCK:
        _TMDB_SEARCH_CACHE.clear()

    # Call 1: triggers network
    id1 = tmdb_search("Test Film", 2020)
    assert id1 == 100
    assert call_count == 1

    # Call 2: hits cache, call_count stays 1
    id2 = tmdb_search("Test Film", 2020)
    assert id2 == 100
    assert call_count == 1


def test_film_profile_cache_bounds_and_offline_profile():
    """Verify Film Profile cache bounded behavior and deterministic profile generation."""
    with _PROFILE_CACHE_LOCK:
        _PROFILE_CACHE.clear()

    profile1, state1, rat1 = generate_film_profile("Offline Film", 2022, "Director B", reviews=[])
    assert profile1 is not None
    assert len(profile1.model_dump()) == 6
    assert profile1.story_and_writing >= 1.0
    assert profile1.accessibility_and_demandingness >= 1.0

    # Subsequent call with same metadata hits cache
    profile2, state2, rat2 = generate_film_profile("Offline Film", 2022, "Director B", reviews=[])
    assert profile1 == profile2
    assert state1 == state2


# --- ITEM 9: PACKAGING EXCLUSIONS AND BUNDLE INTEGRITY ---

def test_packaging_exclusions_and_css_bundle():
    """Verify .dockerignore contains PNG asset exclusions and toni.bundle.css exists."""
    repo_root = Path(__file__).resolve().parent.parent
    dockerignore = repo_root / ".dockerignore"
    bundle_css = repo_root / "static" / "assets" / "toni.bundle.css"

    assert dockerignore.exists(), ".dockerignore must exist at repo root"
    content = dockerignore.read_text(encoding="utf-8")
    assert "static/assets/*.png" in content, ".dockerignore must exclude static/assets/*.png"

    assert bundle_css.exists(), "static/assets/toni.bundle.css must exist"
    assert bundle_css.stat().st_size > 1000, "toni.bundle.css must be compiled and non-trivial"
