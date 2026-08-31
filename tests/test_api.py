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

    response = client.post("/api/recommend", json=payload)
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
