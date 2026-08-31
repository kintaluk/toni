"""
TONI - Tonight's Options, Narrowed Intelligently
FastAPI HTTP Backend Service Wrapper

Exposes production-ready REST API endpoints to serve recommendation requests,
streaming availability lookups, and demo personas to Tina's frontend or external callers.
"""

import os
import sys
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure local module imports work
sys.path.append(str(Path(__file__).resolve().parent))

from contracts import (
    UserContext,
    RecommendationResponse,
    IntakeDepth,
    TasteSignal,
    SignalType,
)
from ranking import rank_movies
from availability import SERVICE_NAME_MAP

load_dotenv()

app = FastAPI(
    title="TONI API",
    description="Tonight's Options, Narrowed Intelligently - Agentic Cinema Discovery Guide",
    version="1.0.0",
)

# Enable CORS for local development and hosted frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supported streaming providers per market
PROVIDER_PRESETS = {
    "UK": [
        {"id": "netflix", "name": "Netflix", "tier": "subscription"},
        {"id": "prime_video", "name": "Prime Video", "tier": "subscription"},
        {"id": "disney+", "name": "Disney+", "tier": "subscription"},
        {"id": "bbc_iplayer", "name": "BBC iPlayer", "tier": "free_licence_gated"},
        {"id": "itvx", "name": "ITVX", "tier": "free"},
        {"id": "channel_4", "name": "Channel 4", "tier": "free"},
        {"id": "my5", "name": "My5", "tier": "free"},
        {"id": "paramount+", "name": "Paramount+", "tier": "subscription"},
        {"id": "apple_tv+", "name": "Apple TV+", "tier": "subscription"},
    ],
    "US": [
        {"id": "netflix", "name": "Netflix", "tier": "subscription"},
        {"id": "prime_video", "name": "Prime Video", "tier": "subscription"},
        {"id": "disney+", "name": "Disney+", "tier": "subscription"},
        {"id": "max", "name": "Max", "tier": "subscription"},
        {"id": "hulu", "name": "Hulu", "tier": "subscription"},
        {"id": "paramount+", "name": "Paramount+", "tier": "subscription"},
        {"id": "peacock", "name": "Peacock", "tier": "subscription"},
        {"id": "pluto_tv", "name": "Pluto TV", "tier": "free"},
        {"id": "apple_tv+", "name": "Apple TV+", "tier": "subscription"},
    ]
}

# Preconfigured Demo Personas for testing & judge evaluation
DEMO_PERSONAS = [
    {
        "id": "persona_a",
        "name": "Persona A: The Comedy & Fun Seeker",
        "description": "Brisk pacing, light attention effort (2.0/5), seeking a funny tone in the UK with Netflix access and rent/buy allowed.",
        "context": {
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
    },
    {
        "id": "persona_b",
        "name": "Persona B: The Classic Drama & Crime Lover",
        "description": "High attention effort (4.0/5), intense mood in the US with Paramount+ and Pluto TV (strictly included, no rent/buy).",
        "context": {
            "country": "US",
            "service_access": ["Paramount+", "Pluto TV"],
            "allow_rent_buy": False,
            "intake_depth": "a_couple_of_questions_is_fine",
            "tonight_signals": [
                {"name": "demandingness", "value": 4.0, "signal_type": "soft_session_preference"},
                {"name": "tone", "value": "intense", "signal_type": "soft_session_preference"}
            ],
            "persistent_taste": []
        }
    },
    {
        "id": "persona_c",
        "name": "Persona C: The Fantasy Adventurer",
        "description": "Wants a magical tone in the US, hard excluding Sci-Fi and Crime genres, with Netflix access.",
        "context": {
            "country": "US",
            "service_access": ["Netflix"],
            "allow_rent_buy": True,
            "intake_depth": "get_to_know_me",
            "tonight_signals": [
                {"name": "exclude-genre", "value": ["Sci-Fi", "Crime"], "signal_type": "hard_constraint"},
                {"name": "tone", "value": "magical", "signal_type": "soft_session_preference"}
            ],
            "persistent_taste": []
        }
    }
]


@app.get("/api/health", summary="Health Check")
def health_check() -> Dict[str, Any]:
    """Check API health and status of external integration configurations."""
    parallel_key = os.environ.get("PARALLEL_API_KEY")
    return {
        "status": "healthy",
        "service": "TONI Recommendation Engine",
        "version": "1.0.0",
        "integrations": {
            "parallel_web": bool(parallel_key),
            "parallel_key_prefix": parallel_key[:6] + "..." if parallel_key else None,
            "google_cloud_project": bool(os.environ.get("GOOGLE_CLOUD_PROJECT")),
            "watchmode_api": bool(os.environ.get("WATCHMODE_API_KEY")),
            "tmdb_api": bool(os.environ.get("TMDB_API_KEY")),
        }
    }


@app.get("/api/providers", summary="Get Supported Streaming Providers")
def get_providers(country: str = Query("UK", description="Target market: 'UK' or 'US'")) -> Dict[str, Any]:
    """Return available streaming platform options for UK and US markets."""
    c_upper = country.upper()
    if c_upper not in PROVIDER_PRESETS:
        raise HTTPException(status_code=400, detail="Country must be either 'UK' or 'US'")
    return {
        "country": c_upper,
        "providers": PROVIDER_PRESETS[c_upper]
    }


@app.get("/api/personas", summary="Get Preconfigured Demo Personas")
def get_personas() -> Dict[str, Any]:
    """Return preconfigured demo personas for fast evaluation and testing."""
    return {"personas": DEMO_PERSONAS}


@app.post("/api/recommend", response_model=RecommendationResponse, summary="Generate Movie Recommendations")
def recommend_movies(
    context: UserContext,
    force_live_evidence: bool = Query(False, description="Whether to bypass local cache and force live Parallel Search calls")
) -> RecommendationResponse:
    """Generate personalized movie recommendations.
    
    Orchestrates live streaming availability, Parallel review search/extract,
    6-dimension Gemini profiling, and dynamic fit scoring.
    """
    try:
        response = rank_movies(context, force_live_evidence=force_live_evidence)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running recommendation pipeline: {str(e)}")


# Serve static web demo UI if static directory exists
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def serve_index() -> HTMLResponse:
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>TONI API is Running</h1><p>Visit <a href='/docs'>/docs</a> for Swagger UI.</p>")
