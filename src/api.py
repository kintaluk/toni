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

load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

from fastapi import FastAPI, Query, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

# Ensure local module imports work
sys.path.append(str(Path(__file__).resolve().parent))

from contracts import (
    UserContext,
    RecommendationResponse,
    IntakeDepth,
    TasteSignal,
    SignalType,
    VoiceTurnRequest,
    VoiceTurnResponse,
    SIGNAL_PACING,
    SIGNAL_TONE,
    SIGNAL_DEMANDINGNESS,
    SIGNAL_MAX_RUNTIME,
    SIGNAL_EXCLUDE_GENRE,
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
    # Extract client IP, prioritizing Cloud Run's X-Forwarded-For header
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # Trust only the first entry since subsequent entries are proxy hop info
        client_ip = x_forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
        
    now = time.time()
    
    # Clean and sweep all entries to prevent memory leak/unbounded growth
    to_delete = []
    for ip, timestamps in list(_rate_limit_db.items()):
        cleaned = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        if not cleaned:
            to_delete.append(ip)
        else:
            _rate_limit_db[ip] = cleaned
            
    for ip in to_delete:
        if ip in _rate_limit_db:
            del _rate_limit_db[ip]
            
    # Enforce rate limiting
    if len(_rate_limit_db[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum of 10 requests per minute allowed.")
    
    _rate_limit_db[client_ip].append(now)

# Enable restricted CORS for actual frontend origins
allowed_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if allowed_origins_env:
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://toni-app-38088879709.us-central1.run.app",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
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


# --- VOICE & SINGLE-BRAIN DIALOGUE SERVICE ---

class VoiceTurnLLMOutput(BaseModel):
    assistant_reply: str = Field(description="Conversational response from TONI as a knowledgeable cinema guide (1-3 sentences max).")
    pacing: Optional[str] = Field(default=None, description="pacing preference e.g. brisk, steady, leisurely")
    tone: Optional[str] = Field(default=None, description="tone preference e.g. funny, intense, magical, dark, warm, satirical")
    demandingness: Optional[float] = Field(default=None, description="score 1.0 to 5.0")
    max_runtime: Optional[int] = Field(default=None, description="runtime limit in minutes")
    exclude_genres: Optional[List[str]] = Field(default=None, description="genres to exclude")
    country: Optional[str] = Field(default=None, description="UK or US if mentioned")
    services: Optional[List[str]] = Field(default=None, description="streaming services mentioned")
    ready_to_recommend: bool = Field(default=False, description="True if user wants recommendations now or sufficient taste details have been shared")


def _process_voice_turn_fallback(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    user_text = turn_req.user_input.strip()
    lower = user_text.lower()
    ctx = turn_req.current_context.model_copy(deep=True)
    ctx.dialogue_mode = turn_req.mode

    extracted_signals = []

    # Ready to recommend keywords
    ready = any(kw in lower for kw in ["recommend", "show me", "ready", "fits tonight", "let's see", "find", "suggest", "shortlist", "give me", "what to watch", "surprise me", "hit me", "let's go", "synthesize"])

    # Pacing
    if any(kw in lower for kw in ["brisk", "fast", "quick", "rapid", "snappy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_PACING, value="brisk", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["leisurely", "slow", "patient", "unhurried"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_PACING, value="leisurely", signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # Tone
    if any(kw in lower for kw in ["funny", "laugh", "hilarious", "comedy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="funny", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["dark", "bleak", "gritty", "unsettling"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="bleak", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["intense", "tense", "thrilling", "action", "suspense"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="intense", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["magical", "wondrous", "whimsical", "fairytale"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="magical", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["warm", "heartwarming", "feel-good", "wholesome", "gentle"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="warm", signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # Demandingness
    if any(kw in lower for kw in ["easy", "light", "relaxing", "unwind", "turn my brain off", "not demanding"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=2.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in lower for kw in ["deep", "challenging", "thought-provoking", "intellectual", "demanding", "heavy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=4.2, signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # Max Runtime
    if "under 2 hours" in lower or "under two hours" in lower or "under 120" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=120, signal_type=SignalType.HARD_CONSTRAINT))
    elif "under 90" in lower or "under an hour and a half" in lower or "short" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=100, signal_type=SignalType.HARD_CONSTRAINT))

    # Exclude genres
    if "no horror" in lower or "hate horror" in lower or "not horror" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=["Horror"], signal_type=SignalType.HARD_CONSTRAINT))
    if "no sci-fi" in lower or "hate sci-fi" in lower or "not sci-fi" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=["Sci-Fi"], signal_type=SignalType.HARD_CONSTRAINT))

    # Services
    for s_id, s_name in [("netflix", "Netflix"), ("prime", "Prime Video"), ("disney", "Disney+"), ("iplayer", "BBC iPlayer"), ("paramount", "Paramount+"), ("max", "Max"), ("apple", "Apple TV+")]:
        if s_id in lower and s_name not in ctx.service_access:
            ctx.service_access.append(s_name)

    # Country
    if "uk" in lower or "british" in lower:
        ctx.country = "UK"
    elif "us" in lower or "american" in lower:
        ctx.country = "US"

    # Merge signals
    existing_names = {s.name for s in extracted_signals}
    updated_tonight = [s for s in ctx.tonight_signals if s.name not in existing_names]
    updated_tonight.extend(extracted_signals)
    ctx.tonight_signals = updated_tonight

    if len(ctx.tonight_signals) >= 2 or ready:
        ready = True

    if ready:
        reply = "I've locked into your viewing mood. Let's find what fits tonight across your available services!"
    elif extracted_signals:
        summary_parts = [f"{s.name} as {s.value}" for s in extracted_signals]
        reply = f"Noted: {', '.join(summary_parts)}. Any runtime limit or genres you'd like to steer clear of tonight?"
    else:
        reply = "I'm listening. Tell me what kind of emotional tone, pacing, or storytelling feels right for tonight."

    return VoiceTurnResponse(
        assistant_reply=reply,
        updated_context=ctx,
        ready_to_recommend=ready,
        mode=turn_req.mode
    )


def process_voice_turn(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    """Processes a dialogue turn using Gemini Flash if available, with structured fallback."""
    has_gemini_key = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not has_gemini_key:
        return _process_voice_turn_fallback(turn_req)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        history_lines = [f"{m.get('role', 'user').title()}: {m.get('content', '')}" for m in turn_req.conversation_history[-6:]]
        history_block = "\n".join(history_lines) if history_lines else "None"

        ctx_summary = (
            f"Country: {turn_req.current_context.country}, "
            f"Services: {turn_req.current_context.service_access}, "
            f"Allow Rent/Buy: {turn_req.current_context.allow_rent_buy}, "
            f"Existing Signals: {[(s.name, s.value) for s in turn_req.current_context.tonight_signals]}"
        )

        prompt = f"""You are TONI (Tonight's Options, Narrowed Intelligently), an agentic cinema guide helping a viewer choose what movie to watch tonight.
The viewer is speaking or texting with you in mode: '{turn_req.mode}'.

Current Viewer Context:
{ctx_summary}

Recent Conversation History:
{history_block}

Latest Viewer Utterance:
"{turn_req.user_input}"

Your task:
1. Formulate a natural, warm, cinematic assistant reply (1-3 sentences maximum). Sound like a thoughtful film festival programmer and curator. Never lecture or quote long text.
2. Extract any newly stated or implied taste signals:
   - pacing: "brisk", "steady", or "leisurely" (if mentioned)
   - tone: descriptive adjective like "funny", "intense", "magical", "dark", "warm", "satirical", "tense" (if mentioned)
   - demandingness: float 1.0 (light/easy) to 5.0 (heavy/demanding) (if mentioned)
   - max_runtime: integer minutes, e.g. 100, 120 (if mentioned)
   - exclude_genres: list of genres to avoid (e.g. ["Horror", "Sci-Fi"])
   - country: "UK" or "US" (if explicitly mentioned)
   - services: list of streaming service names if mentioned (e.g. ["Netflix", "Prime Video", "BBC iPlayer", "Disney+"])
3. Determine ready_to_recommend: set to true if the user explicitly asks to see films / shortlist / recommendations, OR if enough signals (at least 2 distinct taste signals) have been identified to present a confident shortlist.
"""

        response = None
        for model_candidate in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-pro-latest"]:
            try:
                response = client.models.generate_content(
                    model=model_candidate,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json",
                        response_schema=VoiceTurnLLMOutput,
                    ),
                )
                if response and response.parsed:
                    break
            except Exception:
                continue

        if not response or not response.parsed:
            return _process_voice_turn_fallback(turn_req)

        data: VoiceTurnLLMOutput = response.parsed
        ctx = turn_req.current_context.model_copy(deep=True)
        ctx.dialogue_mode = turn_req.mode

        # Update fields
        if data.country and data.country.upper() in ("UK", "US"):
            ctx.country = data.country.upper()
        if data.services:
            for s in data.services:
                if s not in ctx.service_access:
                    ctx.service_access.append(s)

        # Update signals
        new_signals = []
        if data.pacing:
            new_signals.append(TasteSignal(name=SIGNAL_PACING, value=data.pacing, signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        if data.tone:
            new_signals.append(TasteSignal(name=SIGNAL_TONE, value=data.tone, signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        if data.demandingness is not None:
            new_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=float(data.demandingness), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        if data.max_runtime is not None:
            new_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=int(data.max_runtime), signal_type=SignalType.HARD_CONSTRAINT))
        if data.exclude_genres:
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=data.exclude_genres, signal_type=SignalType.HARD_CONSTRAINT))

        new_names = {s.name for s in new_signals}
        merged_signals = [s for s in ctx.tonight_signals if s.name not in new_names]
        merged_signals.extend(new_signals)
        ctx.tonight_signals = merged_signals

        return VoiceTurnResponse(
            assistant_reply=data.assistant_reply,
            updated_context=ctx,
            ready_to_recommend=data.ready_to_recommend,
            mode=turn_req.mode
        )

    except Exception as e:
        print(f"[!] Live Voice Turn error: {e}. Falling back to rule parser.", file=sys.stderr)
        return _process_voice_turn_fallback(turn_req)


@app.get("/api/voice/config", summary="Get Gemini Voice Configuration")
def get_voice_config() -> Dict[str, Any]:
    """Return runtime configuration for Gemini Live voice and audio interfaces."""
    return {
        "model": "gemini-3.1-flash-live-preview",
        "voice_name": "Aoede",
        "sample_rate_hz": 16000,
        "supported_modes": ["voice", "text"]
    }


@app.post("/api/voice/turn", response_model=VoiceTurnResponse, summary="Process Unified Voice/Text Dialogue Turn")
def voice_turn(
    request_data: VoiceTurnRequest,
    _rate_limit: None = Depends(check_rate_limit)
) -> VoiceTurnResponse:
    """Processes a unified dialogue turn for either typed text or spoken voice.

    Extracts tonight's taste signals, updates the shared UserContext, and generates
    editorial conversational replies while detecting shortlist readiness.
    """
    try:
        return process_voice_turn(request_data)
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while processing dialogue turn."
        )


@app.post("/api/recommend", response_model=RecommendationResponse, summary="Generate Movie Recommendations")
def recommend_movies(
    context: UserContext,
    request: Request,
    force_live_evidence: bool = Query(True, description="Whether to bypass local cache and force live Parallel Search calls"),
    live: Optional[bool] = Query(True, description="Enable live runtime candidate discovery and Gemini profiling"),
    _rate_limit: None = Depends(check_rate_limit)
) -> RecommendationResponse:
    """Generate personalized movie recommendations.
    
    Orchestrates live streaming availability, Parallel review search/extract,
    and dynamic fit scoring using canonical Film Profiles.
    """
    try:
        response = rank_movies(
            context,
            force_live_evidence=force_live_evidence,
            use_live_pipeline=live
        )
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
