"""
Unit & Integration Tests for TONI FastAPI HTTP Service
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure local module imports work
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from api import app
from contracts import UserContext, IntakeDepth, TasteSignal, SignalType, OutputRole

client = TestClient(app)


def test_health_endpoint():
    """Verify /api/health returns 200 and expected status keys."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "integrations" in data
    assert "parallel_web" in data["integrations"]


def test_providers_endpoint():
    """Verify /api/providers returns valid preset providers for UK and US."""
    # Test UK
    res_uk = client.get("/api/providers?country=UK")
    assert res_uk.status_code == 200
    data_uk = res_uk.json()
    assert data_uk["country"] == "UK"
    assert any(p["id"] == "netflix" for p in data_uk["providers"])

    # Test US
    res_us = client.get("/api/providers?country=US")
    assert res_us.status_code == 200
    data_us = res_us.json()
    assert data_us["country"] == "US"
    assert any(p["id"] == "paramount+" for p in data_us["providers"])

    # Test Invalid Country
    res_invalid = client.get("/api/providers?country=FR")
    assert res_invalid.status_code == 400


def test_personas_endpoint():
    """Verify /api/personas returns preconfigured demo personas."""
    response = client.get("/api/personas")
    assert response.status_code == 200
    data = response.json()
    assert "personas" in data
    assert len(data["personas"]) >= 3


def test_recommend_endpoint_persona_a():
    """Verify /api/recommend generates valid ranked recommendations."""
    payload = {
        "country": "UK",
        "service_access": ["Netflix"],
        "allow_rent_buy": True,
        "intake_depth": "just_give_me_something",
        "tonight_signals": [
            {"name": "pacing", "value": "brisk", "signal_type": "soft_session_preference"},
            {"name": "demandingness", "value": 2.0, "signal_type": "soft_session_preference"},
            {"name": "tone", "value": "funny", "signal_type": "soft_session_preference"}
        ],
        "persistent_taste": []
    }

    response = client.post("/api/recommend?force_live_evidence=false&live=false", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "recommendations" in data
    recs = data["recommendations"]
    assert len(recs) >= 3

    # Verify presentation roles
    roles = [r["role"] for r in recs]
    assert "best_fit" in roles
    assert "strong_alternative" in roles
    assert "worth_a_stretch" in roles

    # Verify best fit structure
    best_fit = recs[0]
    assert best_fit["personal_fit_score"] > 0
    assert best_fit["concise_reason"] != ""
    assert "matched_services" in best_fit["availability"]


def test_serve_index_html():
    """Verify root / serves the HTML web demo UI."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Tonight's Options, Narrowed Intelligently" in response.text


def test_recommend_invalid_payload():
    """Verify /api/recommend returns 422 for bad API payloads."""
    payload = {
        "country": "UK",
        "service_access": ["Netflix"],
        "allow_rent_buy": True,
        "intake_depth": "just_give_me_something",
        "tonight_signals": "invalid-should-be-a-list",
        "persistent_taste": []
    }
    response = client.post("/api/recommend", json=payload)
    assert response.status_code == 422


import api

def test_recommend_rate_limiting():
    """Verify that `/api/recommend` rate limits clients exceeding 10 requests per minute."""
    # Reset rate limit DB
    api._rate_limit_db.clear()
    
    payload = {
        "country": "UK",
        "service_access": ["Netflix"],
        "allow_rent_buy": True,
        "intake_depth": "just_give_me_something",
        "tonight_signals": [],
        "persistent_taste": []
    }
    
    # Send 10 successful requests
    for i in range(10):
        response = client.post("/api/recommend?force_live_evidence=false&live=false", json=payload)
        assert response.status_code == 200
        
    # The 11th request should exceed the rate limit and return 429
    response_limit = client.post("/api/recommend?force_live_evidence=false&live=false", json=payload)
    assert response_limit.status_code == 429
    assert "Rate limit exceeded" in response_limit.json()["detail"]
    
    # Cleanup DB
    api._rate_limit_db.clear()


def test_recommend_sanitized_500_errors(monkeypatch):
    """Verify that internal 500 errors do not leak stack traces or system info to clients."""
    def mock_rank_movies_crash(context, force_live_evidence=True):
        raise ValueError("CRITICAL DATABASE FAILED at line 42 inside /usr/secret/db.py: password='supersecret'")
        
    monkeypatch.setattr("api.rank_movies", mock_rank_movies_crash)
    
    payload = {
        "country": "UK",
        "service_access": ["Netflix"],
        "allow_rent_buy": True,
        "intake_depth": "just_give_me_something",
        "tonight_signals": [],
        "persistent_taste": []
    }
    
    response = client.post("/api/recommend?force_live_evidence=false", json=payload)
    assert response.status_code == 500
    data = response.json()
    assert "An internal error occurred" in data["detail"]
    assert "supersecret" not in data["detail"]
    assert "db.py" not in data["detail"]


def test_recommend_live_parameter(monkeypatch):
    """Verify that /api/recommend correctly accepts and honors the live parameter."""
    called_with = {}
    from contracts import RecommendationResponse

    def mock_rank_movies(context, force_live_evidence=True, use_live_pipeline=None):
        called_with["use_live_pipeline"] = use_live_pipeline
        called_with["force_live_evidence"] = force_live_evidence
        return RecommendationResponse(recommendations=[], unverified_excluded_count=0, unverified_excluded_titles=[])

    monkeypatch.setattr("api.rank_movies", mock_rank_movies)

    payload = {
        "country": "UK",
        "service_access": ["Netflix"],
        "allow_rent_buy": True,
        "intake_depth": "just_give_me_something",
        "tonight_signals": [],
        "persistent_taste": []
    }

    # Call with live=true
    res = client.post("/api/recommend?live=true&force_live_evidence=false", json=payload)
    assert res.status_code == 200
    assert called_with["use_live_pipeline"] is True
    assert called_with["force_live_evidence"] is False

    # Call with live=false
    res = client.post("/api/recommend?live=false&force_live_evidence=true", json=payload)
    assert res.status_code == 200
    assert called_with["use_live_pipeline"] is False
    assert called_with["force_live_evidence"] is True


def test_voice_config_endpoint():
    """Verify /api/voice/config returns expected voice and Gemini live parameters."""
    res = client.get("/api/voice/config")
    assert res.status_code == 200
    data = res.json()
    assert "gemini" in data["model"].lower()
    assert data["voice_name"] == "Aoede"
    assert data["sample_rate_hz"] == 16000
    assert "voice" in data["supported_modes"]
    assert "text" in data["supported_modes"]


def test_voice_turn_endpoint_text_mode():
    """Verify /api/voice/turn processes text turns and updates tonight signals."""
    payload = {
        "user_input": "I want something funny and brisk under 2 hours",
        "mode": "text",
        "current_context": {
            "country": "UK",
            "service_access": ["Netflix"],
            "allow_rent_buy": False,
            "intake_depth": "just_give_me_something",
            "dialogue_mode": "text",
            "tonight_signals": [],
            "persistent_taste": [],
            "interaction_history": {}
        },
        "conversation_history": [
            {"role": "assistant", "content": "Welcome to TONI. What are you in the mood for?"}
        ]
    }
    res = client.post("/api/voice/turn", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "text"
    assert "assistant_reply" in data
    assert len(data["assistant_reply"]) > 0
    signals = data["updated_context"]["tonight_signals"]
    sig_names = {s["name"] for s in signals}
    assert "tone" in sig_names or "pacing" in sig_names


def test_voice_turn_endpoint_voice_mode_ready():
    """Verify /api/voice/turn processes voice turns and detects ready_to_recommend."""
    payload = {
        "user_input": "Find movies that fit tonight please!",
        "mode": "voice",
        "current_context": {
            "country": "US",
            "service_access": ["Paramount+"],
            "allow_rent_buy": True,
            "intake_depth": "just_give_me_something",
            "dialogue_mode": "voice",
            "tonight_signals": [
                {"name": "tone", "value": "intense", "signal_type": "soft_session_preference"}
            ],
            "persistent_taste": [],
            "interaction_history": {}
        },
        "conversation_history": []
    }
    res = client.post("/api/voice/turn", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "voice"
    assert data["ready_to_recommend"] is True
    assert data["updated_context"]["dialogue_mode"] == "voice"


def test_seed_film_trailer_urls():
    """Verify canonical seed films include trailer URLs."""
    from ranking import SEED_FILMS
    for film in SEED_FILMS:
        meta = film["metadata"]
        assert "trailer_url" in meta
        assert meta["trailer_url"] is not None
        assert "youtube.com" in meta["trailer_url"]



