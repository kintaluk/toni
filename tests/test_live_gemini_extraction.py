"""
Integration and regression tests for Gemini 3.6 Flash structured extraction
and fallback behavior.
"""

import os
import sys
import time
import asyncio
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

import api
from contracts import UserContext, IntakeDepth, SignalType
from fastapi.testclient import TestClient

HAS_LIVE_KEY = os.environ.get("RUN_LIVE_GEMINI_TESTS") == "1"


class MockWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.is_closed = False

    async def send_json(self, data):
        self.sent_messages.append(data)


@pytest.mark.skipif(not HAS_LIVE_KEY, reason="Live GEMINI_API_KEY not configured")
def test_live_sync_structured_extraction_within_deadline():
    """Verify live synchronous structured extraction with gemini-3.6-flash completes within deadline."""
    old_testing = os.environ.pop("TONI_TESTING", None)
    try:
        ctx = UserContext(
            country="UK",
            service_access=["Netflix"],
            intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
        )
        user_input = "I want a brisk funny comedy under 95 minutes, no horror"

        start = time.time()
        updated_ctx, ready = api.extract_voice_context(user_input, ctx, timeout=5.0)
        elapsed = time.time() - start

        # Deadline guarantee: extraction must finish under 5.0s
        assert elapsed < 5.0, f"Extraction exceeded deadline: {elapsed:.2f}s"

        # Verify structured signals parsed by gemini-3.6-flash
        sig_map = {s.name: s.value for s in updated_ctx.tonight_signals}
        assert sig_map.get(api.SIGNAL_PACING) == "brisk"
        assert sig_map.get(api.SIGNAL_TONE) == "funny"
        assert sig_map.get(api.SIGNAL_MAX_RUNTIME) == 95
        assert "horror" in [str(g).lower() for g in sig_map.get(api.SIGNAL_EXCLUDE_GENRE, [])]
    finally:
        if old_testing is not None:
            os.environ["TONI_TESTING"] = old_testing


@pytest.mark.skipif(not HAS_LIVE_KEY, reason="Live GEMINI_API_KEY not configured")
@pytest.mark.anyio
async def test_live_async_structured_extraction_within_deadline():
    """Verify live asynchronous structured extraction with gemini-3.6-flash completes within deadline."""
    old_testing = os.environ.pop("TONI_TESTING", None)
    try:
        ctx = UserContext(
            country="UK",
            service_access=["Netflix"],
            intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
        )
        user_input = "Show me something brisk and funny under 90 minutes"

        start = time.time()
        updated_ctx, ready = await api.extract_voice_context_async(user_input, ctx, timeout=5.0)
        elapsed = time.time() - start

        # Deadline guarantee: extraction must finish under 5.0s
        assert elapsed < 5.0, f"Async extraction exceeded deadline: {elapsed:.2f}s"

        sig_map = {s.name: s.value for s in updated_ctx.tonight_signals}
        assert sig_map.get(api.SIGNAL_PACING) == "brisk"
        assert sig_map.get(api.SIGNAL_TONE) == "funny"
        assert sig_map.get(api.SIGNAL_MAX_RUNTIME) == 90
        assert ready is True  # 'Show me' triggers readiness
    finally:
        if old_testing is not None:
            os.environ["TONI_TESTING"] = old_testing


def test_fallback_extraction_success_isolated(monkeypatch):
    """Verify deterministic fallback extraction independently succeeds when LLM is unavailable."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
    )
    user_input = "I want a brisk comedy under 90 minutes on Prime Video, no horror"

    start = time.time()
    updated_ctx, ready = api.extract_voice_context(user_input, ctx)
    elapsed = time.time() - start

    # Fallback is local regex: runs sub-millisecond
    assert elapsed < 0.1, f"Fallback took too long: {elapsed:.4f}s"
    assert "Prime Video" in updated_ctx.service_access

    sig_map = {s.name: s.value for s in updated_ctx.tonight_signals}
    assert sig_map.get(api.SIGNAL_PACING) == "brisk"
    assert sig_map.get(api.SIGNAL_TONE) == "funny"
    assert sig_map.get(api.SIGNAL_MAX_RUNTIME) == 90
    assert "Horror" in sig_map.get(api.SIGNAL_EXCLUDE_GENRE, []) or "horror" in [g.lower() for g in sig_map.get(api.SIGNAL_EXCLUDE_GENRE, [])]


@pytest.mark.skipif(not HAS_LIVE_KEY, reason="Live GEMINI_API_KEY not configured")
def test_production_voice_path_live_model_with_actual_timeouts():
    """Verify production voice worker using actual timeout settings with gemini-3.6-flash.
    CRITICAL: This test strictly FAILS if deterministic fallback was used."""
    old_testing = os.environ.pop("TONI_TESTING", None)
    try:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"), vertexai=False)
        ws = MockWebSocket()
        ctx = UserContext(
            country="UK",
            service_access=["Netflix"],
            intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
        )

        async def _run():
            pipeline = api.LiveExtractionPipeline(ws, ctx, [], client=client)

            # Utterance containing nuanced genre exclusion and tone that fallback CANNOT match
            user_input = "I want a satirical comedy under 95 minutes, please skip westerns and musicals"
            accepted = pipeline.enqueue_turn(
                turn_id=1,
                user_text=user_input,
                bot_text="A satirical comedy under 95 minutes, skipping westerns and musicals.",
                history_snapshot=[]
            )
            assert accepted is True

            # Wait for turn_complete with bounded recovery
            t0 = time.perf_counter()
            while not any(m.get("type") == "turn_complete" for m in ws.sent_messages):
                await asyncio.sleep(0.1)
                if time.perf_counter() - t0 > 15.0:
                    break

            turn_complete = next((m for m in ws.sent_messages if m.get("type") == "turn_complete"), None)
            assert turn_complete is not None, "Failed to receive turn_complete from voice pipeline"

            # STRICT ASSERTION: Fails if deterministic fallback was used
            assert turn_complete.get("extraction_mode") == "llm", f"Test failed: deterministic fallback was used! Received: {turn_complete}"
            assert turn_complete.get("extraction_mode") != "fallback"

            # Verify nuanced signals that ONLY LLM can extract
            signals = {s["name"]: s["value"] for s in turn_complete["updated_context"]["tonight_signals"]}
            assert signals.get(api.SIGNAL_TONE) in ["satirical", "funny"] or "satirical" in str(signals.get(api.SIGNAL_TONE))
            assert signals.get(api.SIGNAL_MAX_RUNTIME) == 95
            excluded = [str(g).lower() for g in signals.get(api.SIGNAL_EXCLUDE_GENRE, [])]
            assert any("western" in g or "musical" in g for g in excluded), f"Expected Western/Musical excluded, got: {excluded}"

            await pipeline.shutdown()

        asyncio.run(_run())
    finally:
        if old_testing is not None:
            os.environ["TONI_TESTING"] = old_testing


def test_production_voice_path_fallback_isolated(monkeypatch):
    """Verify fallback handling in the production voice worker in complete isolation when LLM is unavailable."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("TONI_TESTING", "1")

    async def _run():
        ws = MockWebSocket()
        ctx = UserContext(
            country="UK",
            service_access=["Netflix"],
            intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
        )
        pipeline = api.LiveExtractionPipeline(ws, ctx, [], client=None)

        accepted = pipeline.enqueue_turn(
            turn_id=1,
            user_text="I want a brisk comedy under 90 minutes, no horror",
            bot_text="Got it, brisk comedy.",
            history_snapshot=[]
        )
        assert accepted is True

        t0 = time.perf_counter()
        while not any(m.get("type") == "turn_complete" for m in ws.sent_messages):
            await asyncio.sleep(0.05)
            if time.perf_counter() - t0 > 2.0:
                break

        turn_complete = next((m for m in ws.sent_messages if m.get("type") == "turn_complete"), None)
        assert turn_complete is not None

        # Fallback mode verified separately
        assert turn_complete.get("extraction_mode") == "fallback"
        signals = {s["name"]: s["value"] for s in turn_complete["updated_context"]["tonight_signals"]}
        assert signals.get(api.SIGNAL_PACING) == "brisk"
        assert signals.get(api.SIGNAL_TONE) == "funny"

        await pipeline.shutdown()

    asyncio.run(_run())


@pytest.mark.skipif(not HAS_LIVE_KEY, reason="Live GEMINI_API_KEY not configured")
def test_voice_to_visible_results_smoke():
    """Verify complete end-to-end voice intake to visible recommendation shortlist results."""
    old_testing = os.environ.pop("TONI_TESTING", None)
    try:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"), vertexai=False)
        ws = MockWebSocket()
        ctx = UserContext(
            country="UK",
            service_access=["Netflix"],
            intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS
        )

        async def _run():
            pipeline = api.LiveExtractionPipeline(ws, ctx, [], client=client)

            user_utterance = "I want a funny movie under 150 minutes on Netflix, please skip horror"
            pipeline.enqueue_turn(
                turn_id=1,
                user_text=user_utterance,
                bot_text="Understood, a funny movie on Netflix under 150 minutes, skipping horror.",
                history_snapshot=[]
            )

            t0 = time.perf_counter()
            while not any(m.get("type") == "turn_complete" for m in ws.sent_messages):
                await asyncio.sleep(0.1)
                if time.perf_counter() - t0 > 15.0:
                    break

            turn_complete = next((m for m in ws.sent_messages if m.get("type") == "turn_complete"), None)
            assert turn_complete is not None
            assert turn_complete.get("extraction_mode") == "llm"

            committed_ctx_dict = turn_complete["updated_context"]

            # Call recommendations endpoint with committed context
            test_client = TestClient(api.app)
            resp = test_client.post("/api/recommend?force_live_evidence=false&live=false", json=committed_ctx_dict)
            assert resp.status_code == 200

            data = resp.json()
            recs = data.get("recommendations", [])
            assert len(recs) > 0, "No recommendations returned in shortlist"

            # Verify candidate cards contain required display fields
            for r in recs:
                assert "metadata" in r and "title" in r["metadata"]
                assert "role" in r
                assert "personal_fit_score" in r
                assert "concise_reason" in r
                assert "availability" in r
                genres = [g.lower() for g in r["metadata"].get("genres", [])]
                assert "horror" not in genres

            await pipeline.shutdown()

        asyncio.run(_run())
    finally:
        if old_testing is not None:
            os.environ["TONI_TESTING"] = old_testing

