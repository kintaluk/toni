"""
TONI - Tonight's Options, Narrowed Intelligently
FastAPI HTTP Backend Service Wrapper

Exposes production-ready REST API endpoints to serve recommendation requests,
streaming availability lookups, and demo personas to Tina's frontend or external callers.
"""

import os
import sys
import time
import traceback
from collections import defaultdict
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Depends, Request
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

# Lightweight in-memory sliding window rate limiter
_rate_limit_db = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = 10  # requests per minute

def check_rate_limit(request: Request):
    """Simple sliding-window rate limiter for the recommendation API."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    # Remove timestamps older than RATE_LIMIT_WINDOW
    _rate_limit_db[client_ip] = [t for t in _rate_limit_db[client_ip] if now - t < RATE_LIMIT_WINDOW]
    
    if len(_rate_limit_db[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum of 10 requests per minute allowed.")
    
    _rate_limit_db[client_ip].append(now)

# Enable restricted CORS for actual frontend origins
allowed_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if allowed_origins_env:
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "https://toni-app-38088879709.us-central1.run.app",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
            "intake_depth": "a_couple_of_questions",
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
    request: Request,
    force_live_evidence: bool = Query(True, description="Whether to bypass local cache and force live Parallel Search calls"),
    _rate_limit: None = Depends(check_rate_limit)
) -> RecommendationResponse:
    """Generate personalized movie recommendations.
    
    Orchestrates live streaming availability, Parallel review search/extract,
    6-dimension Gemini profiling, and dynamic fit scoring.
    """
    try:
        response = rank_movies(context, force_live_evidence=force_live_evidence)
        return response
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while processing your recommendation request. Please contact support."
        )


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
