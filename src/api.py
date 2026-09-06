"""
TONI - Tonight's Options, Narrowed Intelligently
FastAPI HTTP Backend Service Wrapper

Exposes production-ready REST API endpoints to serve recommendation requests,
streaming availability lookups, and demo personas to Tina's frontend or external callers.
"""

from __future__ import annotations

import os
import sys
import re
import time
import math
import struct
import base64
import json
import secrets
import asyncio
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

from fastapi import FastAPI, Query, Header, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
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

from starlette.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

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
        "description": "Fast and energetic pace, light effort (2.0/5), seeking a funny mood in the UK with Netflix access and rentals included.",
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
        "description": "Steady, absorbing pace with higher attention effort (4.0/5), intense mood in the US with Paramount+ and Pluto TV (included only).",
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
        "description": "Magical mood in the US, ruling out sci-fi and crime, with Netflix access.",
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


CONVERSATIONS_LOG_PATH = Path("logs") / "conversations.jsonl"


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


@app.get("/api/export-logs", summary="Export Conversation Transcript Logs")
def export_conversation_logs(
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Returns the JSON contents of logs/conversations.jsonl for offline analysis and refinement.
    Requires ALLOW_LOG_EXPORT=true AND valid ADMIN_LOG_SECRET.
    """
    allow_export = os.environ.get("ALLOW_LOG_EXPORT", "").lower() in ("true", "1")
    admin_secret = os.environ.get("ADMIN_LOG_SECRET")

    # Both server-side enablement AND matching secret are required
    if not allow_export or not admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden: Log export is disabled on this server.")

    # Check secret via X-Admin-Secret, X-Admin-Key header or Bearer token
    bearer_token = None
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization[7:].strip()

    provided_secret = x_admin_secret or x_admin_key or bearer_token
    if not provided_secret or not secrets.compare_digest(provided_secret, admin_secret):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin secret.")

    if not CONVERSATIONS_LOG_PATH.exists():
        return {"total_turns": 0, "turns": []}

    turns = []
    try:
        with open(CONVERSATIONS_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        turns.append(json.loads(line_str))
                    except json.JSONDecodeError:
                        continue
        # Limit to the most recent 100 turns
        recent_turns = turns[-100:] if len(turns) > 100 else turns
        return {"total_turns": len(turns), "returned_turns": len(recent_turns), "turns": recent_turns}
    except Exception as e:
        print(f"[*] Error reading conversation logs: {e}", file=sys.stderr)
        return {"total_turns": 0, "returned_turns": 0, "turns": [], "error": "Internal read error"}


# --- VOICE & SINGLE-BRAIN DIALOGUE SERVICE ---

def enforce_toni_brand_name(text: str) -> str:
    """Enforce brand name lock: Assistant persona must always refer to itself as TONI."""
    if not text:
        return ""
    return re.sub(r'\bCharon\b', 'TONI', text, flags=re.IGNORECASE)


def log_conversation_turn(
    session_id: Optional[str],
    mode: str,
    user_input: str,
    assistant_reply: str,
    signals: Any,
    context: Any
) -> None:
    """Appends dialogue turn record to logs/conversations.jsonl for offline evaluation."""
    try:
        CONVERSATIONS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if CONVERSATIONS_LOG_PATH.exists() and CONVERSATIONS_LOG_PATH.stat().st_size > 5 * 1024 * 1024:
            try:
                rotated = CONVERSATIONS_LOG_PATH.with_suffix(".jsonl.1")
                if rotated.exists():
                    rotated.unlink()
                CONVERSATIONS_LOG_PATH.rename(rotated)
            except Exception:
                pass

        serialized_signals = []
        if isinstance(signals, list):
            for s in signals:
                if hasattr(s, "model_dump"):
                    serialized_signals.append(s.model_dump())
                elif isinstance(s, dict):
                    serialized_signals.append(s)
                else:
                    serialized_signals.append(str(s))
        elif hasattr(signals, "model_dump"):
            serialized_signals = signals.model_dump()
        else:
            serialized_signals = signals

        serialized_context = context.model_dump() if hasattr(context, "model_dump") else (context if isinstance(context, dict) else str(context))

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "default_session",
            "mode": mode or "text",
            "user_input": user_input or "",
            "assistant_reply": enforce_toni_brand_name(assistant_reply or ""),
            "signals": serialized_signals,
            "context": serialized_context
        }

        with open(CONVERSATIONS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[*] Failed to log conversation turn: {e}", file=sys.stderr)


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


class ContextExtractionLLMOutput(BaseModel):
    """Schema for extracting structured context signals and readiness without conversational reply."""
    pacing: Optional[str] = Field(default=None, description="pacing preference e.g. brisk, steady, leisurely, measured")
    tone: Optional[str] = Field(default=None, description="tone preference e.g. funny, intense, magical, dark, warm, satirical")
    demandingness: Optional[float] = Field(default=None, description="score 1.0 to 5.0")
    max_runtime: Optional[int] = Field(default=None, description="runtime limit in minutes")
    exclude_genres: Optional[List[str]] = Field(default=None, description="genres to exclude")
    country: Optional[str] = Field(default=None, description="UK or US if mentioned")
    services: Optional[List[str]] = Field(default=None, description="streaming services mentioned")
    ready_to_recommend: bool = Field(default=False, description="True if user explicitly requests recommendations or confirms they are ready")


def _merge_signals_into_context(ctx: UserContext, data: Any) -> UserContext:
    """Defensively merges extracted structured signals and metadata into the UserContext."""
    if hasattr(data, "country") and data.country and str(data.country).upper() in ("UK", "US"):
        ctx.country = str(data.country).upper()
    if hasattr(data, "services") and data.services:
        for s in data.services:
            s_str = str(s).strip()
            if s_str and s_str not in ctx.service_access:
                ctx.service_access.append(s_str)

    new_signals = []
    if getattr(data, "pacing", None):
        new_signals.append(TasteSignal(name=SIGNAL_PACING, value=str(data.pacing).lower().strip(), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    if getattr(data, "tone", None):
        new_signals.append(TasteSignal(name=SIGNAL_TONE, value=str(data.tone).lower().strip(), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    if getattr(data, "demandingness", None) is not None:
        try:
            new_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=float(data.demandingness), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        except (ValueError, TypeError):
            pass
    if getattr(data, "max_runtime", None) is not None:
        try:
            digits = re.findall(r'\d+', str(data.max_runtime))
            if digits:
                new_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=int(digits[0]), signal_type=SignalType.HARD_CONSTRAINT))
        except (ValueError, TypeError):
            pass
    if getattr(data, "exclude_genres", None):
        if isinstance(data.exclude_genres, list):
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[str(g) for g in data.exclude_genres], signal_type=SignalType.HARD_CONSTRAINT))
        elif isinstance(data.exclude_genres, str):
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[data.exclude_genres], signal_type=SignalType.HARD_CONSTRAINT))

    new_names = {s.name for s in new_signals}
    merged_signals = [s for s in ctx.tonight_signals if s.name not in new_names]
    merged_signals.extend(new_signals)
    ctx.tonight_signals = merged_signals
    return ctx


def _extract_voice_context_fallback(user_text: str, current_ctx: UserContext) -> Tuple[UserContext, bool]:
    """Local deterministic fallback for extracting signals from user text."""
    ctx = current_ctx.model_copy(deep=True)
    lower = (user_text or "").lower()
    extracted_signals = []

    # Ready to recommend keywords
    ready = any(kw in lower for kw in ["recommend", "show me", "ready", "fits tonight", "let's see", "find movies", "find what fits", "suggest", "shortlist", "what to watch", "surprise me", "hit me", "let's go", "synthesize", "yes please", "bring up", "show shortlist"])

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
    if "under 90" in lower or "under an hour and a half" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=90, signal_type=SignalType.HARD_CONSTRAINT))
    elif "under 2 hours" in lower or "under two hours" in lower or "under 120" in lower:
        extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=120, signal_type=SignalType.HARD_CONSTRAINT))
    elif ("short film" in lower or "keep it short" in lower or re.search(r'\bshort\b', lower)) and "shortlist" not in lower:
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

    return ctx, ready


def _process_voice_turn_fallback(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    try:
        user_text = (turn_req.user_input or "").strip()
        ctx = turn_req.current_context.model_copy(deep=True) if turn_req.current_context else UserContext()
        ctx.dialogue_mode = turn_req.mode or "text"
        ctx.voice_name = getattr(ctx, "voice_name", "Charon") or "Charon"

        ctx, ready = _extract_voice_context_fallback(user_text, ctx)

        if ready:
            reply = "I've got a good sense of what you're after. Let's see what fits."
        elif ctx.tonight_signals:
            summary_parts = [f"{s.value}" for s in ctx.tonight_signals]
            reply = f"Got it — {', '.join(summary_parts)}. Which channels do you have access to?"
        else:
            reply = "Tell me what you're in the mood for. A pace, genre, feeling or even a film you liked is enough to start."

        clean_reply = enforce_toni_brand_name(reply)
        return VoiceTurnResponse(
            assistant_reply=clean_reply,
            updated_context=ctx,
            ready_to_recommend=ready,
            mode=turn_req.mode
        )
    except Exception as ex:
        print(f"[!] Fallback voice turn exception: {ex}", file=sys.stderr)
        safe_ctx = turn_req.current_context.model_copy(deep=True) if turn_req.current_context else UserContext()
        return VoiceTurnResponse(
            assistant_reply=enforce_toni_brand_name("Tell me what you're in the mood for. A pace, genre, feeling or even a film you liked is enough to start."),
            updated_context=safe_ctx,
            ready_to_recommend=False,
            mode=turn_req.mode or "text"
        )


def extract_voice_context(
    user_input: str,
    current_context: UserContext,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 3.5
) -> Tuple[UserContext, bool]:
    """Extracts structured signals and shortlist readiness from spoken input without generating a redundant conversational reply."""
    if not user_input or not user_input.strip():
        return current_context, False

    ctx = current_context.model_copy(deep=True)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_CLOUD_PROJECT"))
    if has_gemini_key and not os.environ.get("TONI_TESTING"):
        try:
            from google import genai
            from google.genai import types

            gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if gemini_api_key:
                client = genai.Client(api_key=gemini_api_key, vertexai=False)
            else:
                client = genai.Client()

            recent_history = ""
            if conversation_history:
                recent_history = "\n".join([f"{t.get('role', 'user')}: {t.get('content', '')}" for t in conversation_history[-4:]])

            prompt = f"""You are TONI's structured conversation intake extractor.
Extract viewer streaming context, taste boundaries, and shortlist readiness. DO NOT generate an assistant reply.

Recent dialogue:
{recent_history}

Latest user input:
"{user_input}"

Rules:
1. Extract pacing ('brisk', 'steady', 'leisurely', 'measured') if indicated.
2. Extract tone keywords (e.g. 'funny', 'intense', 'dark', 'magical', 'warm', 'satirical') if indicated.
3. Extract demandingness score 1.0 to 5.0 if indicated.
4. Extract max_runtime in minutes if viewer states a time limit (e.g. "under 2 hours" -> 120).
5. Extract exclude_genres as a list of strings if viewer wants to rule out specific genres.
6. Extract country ('UK' or 'US') and services (e.g. Netflix, Prime Video, BBC iPlayer, etc.) if mentioned.
7. Set ready_to_recommend to True ONLY if the user explicitly asks to see films / recommendations or confirms they are ready."""

            timeout_ms = int(timeout * 1000) if timeout else 3500
            http_opts = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1)
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ContextExtractionLLMOutput,
                    temperature=0.1,
                    http_options=http_opts,
                )
            )
            if response and response.parsed:
                extracted: ContextExtractionLLMOutput = response.parsed
                ctx = _merge_signals_into_context(ctx, extracted)
                lower_input = user_input.lower()
                explicit_ready = any(kw in lower_input for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                ready = bool(extracted.ready_to_recommend) or explicit_ready
                return ctx, ready
        except Exception as ex:
            print(f"[*] Structured context extraction notice: {ex}", file=sys.stderr)

    return _extract_voice_context_fallback(user_input, ctx)


async def extract_voice_context_async(
    user_input: str,
    current_context: UserContext,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 3.5,
    client: Optional[Any] = None
) -> Tuple[UserContext, bool]:
    """Extracts structured signals and shortlist readiness asynchronously with enforced request deadline."""
    if not user_input or not user_input.strip():
        return current_context, False

    ctx = current_context.model_copy(deep=True)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_CLOUD_PROJECT"))
    if has_gemini_key and not os.environ.get("TONI_TESTING"):
        try:
            from google import genai
            from google.genai import types

            if client is None:
                gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                if gemini_api_key:
                    client = genai.Client(api_key=gemini_api_key, vertexai=False)
                else:
                    client = genai.Client()

            recent_history = ""
            if conversation_history:
                recent_history = "\n".join([f"{t.get('role', 'user')}: {t.get('content', '')}" for t in conversation_history[-4:]])

            prompt = f"""You are TONI's structured conversation intake extractor.
Extract viewer streaming context, taste boundaries, and shortlist readiness. DO NOT generate an assistant reply.

Recent dialogue:
{recent_history}

Latest user input:
"{user_input}"

Rules:
1. Extract pacing ('brisk', 'steady', 'leisurely', 'measured') if indicated.
2. Extract tone keywords (e.g. 'funny', 'intense', 'dark', 'magical', 'warm', 'satirical') if indicated.
3. Extract demandingness score 1.0 to 5.0 if indicated.
4. Extract max_runtime in minutes if viewer states a time limit (e.g. "under 2 hours" -> 120).
5. Extract exclude_genres as a list of strings if viewer wants to rule out specific genres.
6. Extract country ('UK' or 'US') and services (e.g. Netflix, Prime Video, BBC iPlayer, etc.) if mentioned.
7. Set ready_to_recommend to True ONLY if the user explicitly asks to see films / recommendations or confirms they are ready."""

            timeout_ms = int(timeout * 1000) if timeout else 3500
            http_opts = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1)
            )

            overall_deadline = (timeout or 3.5) + 0.5
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ContextExtractionLLMOutput,
                        temperature=0.1,
                        http_options=http_opts,
                    )
                ),
                timeout=overall_deadline
            )
            if response and response.parsed:
                extracted: ContextExtractionLLMOutput = response.parsed
                ctx = _merge_signals_into_context(ctx, extracted)
                lower_input = user_input.lower()
                explicit_ready = any(kw in lower_input for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                ready = bool(extracted.ready_to_recommend) or explicit_ready
                return ctx, ready
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print(f"[*] Async structured context extraction notice: {ex}", file=sys.stderr)

    return _extract_voice_context_fallback(user_input, ctx)


class TurnWorkItem:
    def __init__(
        self,
        turn_id: int,
        user_text: str,
        bot_text: str,
        conversation_history: List[Dict[str, str]],
        force_fallback: bool = False
    ):
        self.turn_id = turn_id
        self.user_text = user_text
        self.bot_text = bot_text
        self.conversation_history = conversation_history
        self.force_fallback = force_fallback


class LiveExtractionPipeline:
    """
    Owned sequential context extraction pipeline for a single WebSocket voice session.
    Decouples extraction from the upstream receive loop, bounds queue/task growth under
    overload by cancelling slow model extraction and substituting deterministic fallback,
    and commits updates strictly in turn order through ONE ordered commit path.
    """
    MAX_PENDING_TURNS = 8

    def __init__(
        self,
        websocket: WebSocket,
        initial_context: UserContext,
        initial_history: List[Dict[str, str]],
        client: Optional[Any] = None
    ):
        self.websocket = websocket
        self.session_ctx = initial_context.model_copy(deep=True)
        self.conversation_history = list(initial_history)
        self.client = client
        self.queue: asyncio.Queue[TurnWorkItem] = asyncio.Queue(maxsize=self.MAX_PENDING_TURNS)
        self.in_flight_task: Optional[asyncio.Task] = None
        self.in_flight_item: Optional[TurnWorkItem] = None
        self.in_flight_cancelled_for_overload: bool = False
        self.is_disconnected: bool = False
        self.worker_task = asyncio.create_task(self._worker_loop())

    def update_context(self, ctx: UserContext):
        self.session_ctx = ctx.model_copy(deep=True)

    def update_history(self, history: List[Dict[str, str]]):
        self.conversation_history = list(history)

    def enqueue_turn(
        self,
        turn_id: int,
        user_text: str,
        bot_text: str,
        history_snapshot: List[Dict[str, str]]
    ) -> bool:
        """Enqueues a turn snapshot for sequential context extraction.
        Enforces a strictly bounded overflow policy: if overloaded, cancels
        the slow in-flight model extraction and drains work using deterministic fallback.
        One ordered commit path in _worker_loop owns all context mutations,
        history updates, and completions."""
        if self.is_disconnected:
            return False

        item = TurnWorkItem(
            turn_id=turn_id,
            user_text=user_text,
            bot_text=bot_text,
            conversation_history=history_snapshot
        )

        # Overload condition: in-flight task is still blocking while 2 or more subsequent turns arrive,
        # or queue is full. Cancel the slow in-flight model task and switch to fast fallback.
        if (self.in_flight_task and not self.in_flight_task.done() and self.queue.qsize() >= 2) or self.queue.full():
            self.in_flight_cancelled_for_overload = True
            self.in_flight_task.cancel()

        try:
            self.queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            print(f"[*] LiveExtractionPipeline queue full (capacity {self.MAX_PENDING_TURNS}), dropping unaccepted turn {turn_id}", file=sys.stderr)
            return False

    async def _worker_loop(self):
        try:
            while not self.is_disconnected:
                item = await self.queue.get()
                if item is None or self.is_disconnected:
                    break

                self.in_flight_item = item
                full_user = item.user_text
                full_bot = item.bot_text
                turn_id = item.turn_id
                history_snapshot = item.conversation_history

                extracted_ctx = self.session_ctx
                ready_flag = False

                # If overload cancelled earlier extraction, or queue has backlog, or forced fallback:
                # Use fast deterministic fallback rather than launching slow model calls
                use_fallback = (
                    self.in_flight_cancelled_for_overload or
                    item.force_fallback or
                    self.queue.qsize() >= self.MAX_PENDING_TURNS - 1 or
                    not full_user
                )

                if full_user:
                    if use_fallback:
                        extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                    else:
                        try:
                            self.in_flight_task = asyncio.create_task(
                                extract_voice_context_async(
                                    user_input=full_user,
                                    current_context=self.session_ctx,
                                    conversation_history=history_snapshot,
                                    timeout=3.5,
                                    client=self.client
                                )
                            )
                            res_ctx, res_ready = await self.in_flight_task
                            if self.in_flight_cancelled_for_overload:
                                # Invalidate late model result! Substitute deterministic fallback
                                extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                            else:
                                extracted_ctx, ready_flag = res_ctx, res_ready
                        except asyncio.CancelledError:
                            if self.is_disconnected:
                                break
                            # Cancelled due to overload: substitute deterministic fallback
                            extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                        except Exception as ex:
                            print(f"[*] Extraction worker error: {ex}", file=sys.stderr)
                            extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                        finally:
                            self.in_flight_task = None

                if self.is_disconnected:
                    break

                # --- ONE ORDERED COMMIT PATH ---
                # Owns all context mutations, history updates, and completion notifications
                self.session_ctx = extracted_ctx
                if full_user:
                    self.conversation_history.append({"role": "user", "content": full_user})
                if full_bot:
                    self.conversation_history.append({"role": "assistant", "content": full_bot})

                # If queue is now empty and not overloaded, reset overload flag
                if self.queue.empty():
                    self.in_flight_cancelled_for_overload = False

                lower_user = full_user.lower() if full_user else ""
                explicit_user_ready = any(kw in lower_user for kw in [
                    "show me", "recommend", "find movies", "yes please", "bring up",
                    "find what fits", "what to watch", "let's see", "shortlist",
                    "show shortlist", "let's go"
                ])
                final_ready = ready_flag or explicit_user_ready

                log_conversation_turn(
                    session_id=f"ws_{id(self.websocket)}",
                    mode="voice",
                    user_input=full_user,
                    assistant_reply=full_bot,
                    signals=self.session_ctx.tonight_signals,
                    context=self.session_ctx
                )

                if not self.is_disconnected:
                    try:
                        await self.websocket.send_json({
                            "type": "turn_complete",
                            "turn_id": turn_id,
                            "user_text": full_user,
                            "assistant_reply": full_bot,
                            "updated_context": self.session_ctx.model_dump(),
                            "ready_to_recommend": final_ready
                        })
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        finally:
            self.in_flight_task = None
            self.in_flight_item = None

    async def shutdown(self):
        """Cleanly tears down extraction pipeline, cancelling background tasks and invalidating pending work."""
        self.is_disconnected = True
        if self.in_flight_task and not self.in_flight_task.done():
            self.in_flight_task.cancel()
            try:
                await self.in_flight_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except (asyncio.CancelledError, Exception):
                pass



def process_voice_turn(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    """Processes a dialogue turn using Gemini Flash if available, with structured fallback."""
    has_gemini_key = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not has_gemini_key or os.environ.get("TONI_MOCK_GEMINI_LIVE") == "true":
        return _process_voice_turn_fallback(turn_req)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()

        # Sanitize conversation_history cleanly into plain text lines ("user: ...", "assistant: ...")
        clean_history = []
        for item in (turn_req.conversation_history or [])[-8:]:
            if isinstance(item, dict):
                role = str(item.get("role", "user")).strip().lower()
                content = item.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content)
                clean_history.append(f"{role}: {str(content).strip()}")
            elif hasattr(item, "role") and hasattr(item, "content"):
                role = str(getattr(item, "role", "user")).strip().lower()
                content = getattr(item, "content", "")
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content)
                clean_history.append(f"{role}: {str(content).strip()}")
            elif isinstance(item, str) and item.strip():
                clean_history.append(f"dialogue: {item.strip()}")
        history_block = "\n".join(clean_history) if clean_history else "None"

        ctx_summary = (
            f"Country: {turn_req.current_context.country}, "
            f"Services: {turn_req.current_context.service_access}, "
            f"Allow Rent/Buy: {turn_req.current_context.allow_rent_buy}, "
            f"Existing Signals: {[(s.name, s.value) for s in turn_req.current_context.tonight_signals]}"
        )

        prompt = f"""You are TONI, a cinema guide helping someone choose what to watch.
Your name is TONI. You must ALWAYS refer to yourself as TONI. NEVER refer to yourself as Charon, Gemini, or any internal voice or model identifier.
The viewer is speaking or texting with you in mode: '{turn_req.mode}'.

Current Viewer Context:
{ctx_summary}

Recent Conversation History:
{history_block}

Latest Viewer Utterance:
"{turn_req.user_input}"

Your task:
1. Formulate a natural, warm, discerning assistant reply (1-3 sentences maximum) in your persona as TONI.
   Gather the minimum missing information naturally. Do not force a fixed question order. Ask only what is still needed to make a useful recommendation:
   - Pace or mood / feeling they are in the mood for
   - Country (UK/US) and channels they have access to, so availability can be guaranteed
   - Any runtime limits or genres they definitely want to rule out
   If the viewer has already answered any of these, adapt smoothly without repeating answered questions.
2. Extract any newly stated or implied taste signals:
   - pacing: "brisk", "steady", or "slow" (if mentioned)
   - tone: descriptive adjective like "funny", "intense", "magical", "dark", "warm", "satirical", "tense" (if mentioned)
   - demandingness: float 1.0 (light/easy) to 5.0 (heavy/demanding) (if mentioned)
   - max_runtime: integer minutes, e.g. 100, 120 (if mentioned)
   - exclude_genres: list of genres to avoid (e.g. ["Horror", "Sci-Fi"])
   - country: "UK" or "US" (if explicitly mentioned)
   - channels / services: list of channel or service names if mentioned (e.g. ["Netflix", "Prime Video", "BBC iPlayer", "Disney+"])
3. Determine ready_to_recommend: set to true ONLY if the user explicitly asks to see films / recommendations or confirms they are ready (e.g., 'show me', 'recommend', 'find movies', 'yes please', 'what should I watch', 'bring up the list', 'let\'s see', 'find what fits'). Do NOT set to true merely because 2 or more taste signals were mentioned without explicit user confirmation to proceed.
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
        ctx.voice_name = getattr(turn_req.current_context, "voice_name", "Charon") or "Charon"

        ctx = _merge_signals_into_context(ctx, data)

        lower_input = turn_req.user_input.lower()
        explicit_user_ready = any(kw in lower_input for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
        ready_flag = bool(data.ready_to_recommend) or explicit_user_ready

        raw_reply = str(data.assistant_reply).strip() if data.assistant_reply else "I've noted what you're in the mood for."
        clean_reply = enforce_toni_brand_name(raw_reply)

        return VoiceTurnResponse(
            assistant_reply=clean_reply,
            updated_context=ctx,
            ready_to_recommend=ready_flag,
            mode=turn_req.mode
        )

    except Exception as e:
        print(f"[*] Live Voice Turn notice: {e}. Falling back to structured rule parser.", file=sys.stderr)
        return _process_voice_turn_fallback(turn_req)


@app.get("/api/voice/config", summary="Get Gemini Voice Configuration")
def get_voice_config() -> Dict[str, Any]:
    """Return runtime configuration for Gemini Live voice and audio interfaces."""
    return {
        "model": "gemini-2.5-flash-native-audio-latest",
        "voice_name": "Charon",
        "sample_rate_hz": 16000,
        "supported_modes": ["voice", "text"],
        "turnDetection": {
            "type": "SERVER_VAD",
            "silenceDurationMs": 700,
            "threshold": 0.5,
        },
        "audio_spec": {
            "input_sample_rate_hz": 16000,
            "output_sample_rate_hz": 24000,
            "encoding": "pcm16",
            "channels": 1,
        },
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
        res = process_voice_turn(request_data)
        log_conversation_turn(
            session_id=request_data.session_id or "web_session",
            mode=request_data.mode,
            user_input=request_data.user_input,
            assistant_reply=res.assistant_reply,
            signals=res.updated_context.tonight_signals,
            context=res.updated_context
        )
        return res
    except Exception as e:
        print(f"[*] voice_turn caught error: {e}. Returning safe fallback response.", file=sys.stderr)
        res = _process_voice_turn_fallback(request_data)
        log_conversation_turn(
            session_id=request_data.session_id or "web_session_fallback",
            mode=request_data.mode,
            user_input=request_data.user_input,
            assistant_reply=res.assistant_reply,
            signals=res.updated_context.tonight_signals,
            context=res.updated_context
        )
        return res


def _generate_pcm16_tones(duration_sec: float = 0.8, sample_rate: int = 24000) -> bytes:
    """Generate subtle warm harmonic chime PCM16 24kHz audio as synthetic fallback."""
    num_samples = int(sample_rate * duration_sec)
    freq1 = 220.0  # Warm A3
    freq2 = 330.0  # Warm E4
    freq3 = 440.0  # Warm A4
    buf = bytearray(num_samples * 2)
    for i in range(num_samples):
        t = i / sample_rate
        env = math.exp(-3.5 * t)
        val = 0.5 * math.sin(2 * math.pi * freq1 * t) + 0.3 * math.sin(2 * math.pi * freq2 * t) + 0.2 * math.sin(2 * math.pi * freq3 * t)
        sample = int(max(-1.0, min(1.0, val * env)) * 28000)
        struct.pack_into("<h", buf, i * 2, sample)
    return bytes(buf)


@app.websocket("/api/voice/live")
@app.websocket("/ws/voice")
async def websocket_voice_live(websocket: WebSocket):
    """Real-time Gemini Live WebSocket audio/text dialogue transport."""
    await websocket.accept()
    session_ctx = UserContext(
        country="UK",
        service_access=["Netflix", "BBC iPlayer"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        dialogue_mode="voice",
        voice_name="Charon",
        tonight_signals=[],
    )
    conversation_history: List[Dict[str, str]] = []

    has_gemini_key = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    client = None
    gemini_session = None
    gemini_recv_task = None
    live_cm = None
    connected_model = None

    user_transcript_buf: List[str] = []
    assistant_transcript_buf: List[str] = []

    turn_counter = 0
    turn_active = False

    extraction_pipeline: Optional[LiveExtractionPipeline] = None

    async def forward_gemini_responses(session):
        nonlocal session_ctx, conversation_history, user_transcript_buf, assistant_transcript_buf, turn_counter, turn_active, extraction_pipeline
        try:
            while True:
                async for response in session.receive():
                    content = response.server_content
                    if not content:
                        continue
                    if content.interrupted:
                        await websocket.send_json({"type": "interrupted"})
                        assistant_transcript_buf.clear()
                        continue
                    if content.input_transcription and content.input_transcription.text:
                        if not turn_active:
                            turn_counter += 1
                            turn_active = True
                        user_chunk = content.input_transcription.text
                        user_transcript_buf.append(user_chunk)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": user_chunk,
                            "role": "user",
                            "turn_id": turn_counter
                        })
                    if content.model_turn:
                        if not turn_active:
                            turn_counter += 1
                            turn_active = True
                        for part in content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                raw_data = part.inline_data.data
                                audio_b64 = raw_data if isinstance(raw_data, str) else base64.b64encode(raw_data).decode("ascii")
                                await websocket.send_json({
                                    "type": "audio",
                                    "data": audio_b64,
                                    "mime_type": "audio/pcm;rate=24000",
                                    "turn_id": turn_counter
                                })
                    if content.output_transcription and content.output_transcription.text:
                        if not turn_active:
                            turn_counter += 1
                            turn_active = True
                        bot_chunk = enforce_toni_brand_name(content.output_transcription.text)
                        assistant_transcript_buf.append(bot_chunk)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": bot_chunk,
                            "role": "assistant",
                            "turn_id": turn_counter
                        })
                    if content.turn_complete:
                        completed_turn_id = turn_counter
                        turn_active = False
                        full_user = "".join(user_transcript_buf).strip()
                        full_bot = enforce_toni_brand_name("".join(assistant_transcript_buf).strip())
                        user_transcript_buf.clear()
                        assistant_transcript_buf.clear()

                        # 1. Distinguish end of streamed speech from completion of context extraction
                        await websocket.send_json({
                            "type": "speech_complete",
                            "turn_id": completed_turn_id
                        })

                        # 2. Snapshot history and enqueue for background extraction without blocking receive loop
                        if extraction_pipeline:
                            history_snapshot = list(conversation_history)
                            extraction_pipeline.enqueue_turn(
                                turn_id=completed_turn_id,
                                user_text=full_user,
                                bot_text=full_bot,
                                history_snapshot=history_snapshot
                            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[!] Gemini Live receiver error: {e}", file=sys.stderr)
            try:
                await websocket.send_json({
                    "type": "error",
                    "error": "upstream_receiver_failed",
                    "message": "Upstream voice connection encountered an error."
                })
            except Exception:
                pass

    if has_gemini_key and not os.environ.get("TONI_MOCK_GEMINI_LIVE"):
        try:
            from google import genai
            from google.genai import types

            gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if gemini_api_key:
                client = genai.Client(api_key=gemini_api_key, vertexai=False)
            else:
                client = genai.Client()

            extraction_pipeline = LiveExtractionPipeline(
                websocket=websocket,
                initial_context=session_ctx,
                initial_history=conversation_history,
                client=client
            )

            config = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Charon"
                        )
                    )
                ),
                system_instruction=types.Content(
                    parts=[types.Part(text="""You are TONI, a cinema guide helping someone choose what to watch. You speak in a warm, thoughtful, discerning persona as TONI (1-3 sentences maximum per turn). Your name is always TONI. Never refer to yourself as Charon, Gemini, or any internal voice or model identifier. Never lecture or recite long lists.

Gather the minimum missing information naturally. Do not force a fixed question order. Ask only what is still needed to make a useful recommendation:
- The pace or mood / feeling they are in the mood for.
- Their country (UK or US) and what channels they have access to (e.g. Netflix, Prime Video, BBC iPlayer, Disney+, etc.) so availability can be guaranteed.
- Any runtime limits or genres they definitely want to rule out, and check if they are ready to see what fits.

Always wait for the viewer to confirm they are ready before offering to reveal recommendations. If the viewer provides multiple details up front, adapt smoothly without repeating answered questions.""")]
                ),
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        silence_duration_ms=700,
                    )
                )
            )
            connected_model = None
            live_models = [
                "gemini-2.5-flash-native-audio-latest",
                "gemini-3.1-flash-live-preview",
                "gemini-live-2.5-flash-native-audio",
            ]
            for m in live_models:
                try:
                    live_cm = client.aio.live.connect(model=m, config=config)
                    gemini_session = await asyncio.wait_for(live_cm.__aenter__(), timeout=4.0)
                    gemini_recv_task = asyncio.create_task(forward_gemini_responses(gemini_session))
                    connected_model = m
                    print(f"[*] Gemini Live session established with model: {m}", file=sys.stderr)
                    break
                except Exception as ex:
                    print(f"[*] Gemini Live model {m} connect attempt failed ({type(ex).__name__}): {repr(ex)}", file=sys.stderr)
        except Exception as e:
            print(f"[*] Gemini Live session setup failed ({type(e).__name__}): {repr(e)}", file=sys.stderr)
            gemini_session = None

    if extraction_pipeline is None:
        extraction_pipeline = LiveExtractionPipeline(
            websocket=websocket,
            initial_context=session_ctx,
            initial_history=conversation_history,
            client=client
        )

    try:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue

            msg_type = data.get("type", "")

            if msg_type == "init":
                if "context" in data:
                    try:
                        session_ctx = UserContext.model_validate(data["context"])
                        if extraction_pipeline:
                            extraction_pipeline.update_context(session_ctx)
                    except Exception:
                        pass
                if "conversation_history" in data and isinstance(data["conversation_history"], list):
                    conversation_history = data["conversation_history"]
                    if extraction_pipeline:
                        extraction_pipeline.update_history(conversation_history)
                is_live_ready = bool(gemini_session is not None and connected_model is not None)
                await websocket.send_json({
                    "type": "init_ack",
                    "status": "ready" if is_live_ready else "fallback",
                    "voice_name": session_ctx.voice_name or "Charon",
                    "live_model": connected_model or "offline-fallback"
                })

            elif msg_type == "interrupt":
                await websocket.send_json({"type": "interrupted"})

            elif msg_type == "audio":
                pcm_b64 = data.get("data", "")
                if gemini_session and pcm_b64:
                    try:
                        pcm_bytes = base64.b64decode(pcm_b64)
                        from google.genai import types
                        await gemini_session.send_realtime_input(
                            audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
                        )
                    except Exception as e:
                        print(f"[*] Audio forward error: {e}", file=sys.stderr)

            elif msg_type in ("text", "utterance"):
                user_text = data.get("text", "") or data.get("user_input", "")
                if gemini_session:
                    try:
                        turn_counter += 1
                        turn_active = True
                        user_transcript_buf.append(user_text)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": user_text,
                            "role": "user",
                            "turn_id": turn_counter
                        })
                        from google.genai import types
                        user_content = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
                        await gemini_session.send_client_content(turns=user_content, turn_complete=True)
                    except Exception as e:
                        print(f"[*] Send client content notice: {e}", file=sys.stderr)
                else:
                    turn_req = VoiceTurnRequest(
                        user_input=user_text,
                        mode="voice",
                        current_context=session_ctx,
                        conversation_history=conversation_history
                    )
                    turn_res = await asyncio.to_thread(process_voice_turn, turn_req)
                    session_ctx = turn_res.updated_context
                    conversation_history.append({"role": "user", "content": user_text})
                    conversation_history.append({"role": "assistant", "content": turn_res.assistant_reply})

                    lower_u = user_text.lower()
                    explicit_ready = any(kw in lower_u for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                    final_ready = turn_res.ready_to_recommend or explicit_ready

                    fallback_pcm = _generate_pcm16_tones(duration_sec=1.2)
                    fallback_b64 = base64.b64encode(fallback_pcm).decode("ascii")

                    await websocket.send_json({
                        "type": "transcript",
                        "text": turn_res.assistant_reply,
                        "role": "assistant"
                    })
                    await websocket.send_json({
                        "type": "audio",
                        "data": fallback_b64,
                        "mime_type": "audio/pcm;rate=24000"
                    })
                    await websocket.send_json({
                        "type": "turn_complete",
                        "turn_id": turn_counter,
                        "user_text": user_text,
                        "assistant_reply": turn_res.assistant_reply,
                        "updated_context": session_ctx.model_dump(),
                        "ready_to_recommend": final_ready
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[!] WebSocket live notice: {e}", file=sys.stderr)
    finally:
        # 1. Cancel and await upstream receiver task
        if gemini_recv_task and not gemini_recv_task.done():
            gemini_recv_task.cancel()
            try:
                await gemini_recv_task
            except (asyncio.CancelledError, Exception):
                pass

        # 2. Shutdown extraction pipeline (cancels in-flight extraction & worker task and awaits them)
        if extraction_pipeline:
            try:
                await extraction_pipeline.shutdown()
            except Exception:
                pass

        # 3. Exit the Live session BEFORE closing client
        if gemini_session and live_cm:
            try:
                await live_cm.__aexit__(None, None, None)
            except Exception:
                pass
            gemini_session = None
            live_cm = None

        # 4. Close client exactly once (if owned)
        if client and hasattr(client, "aio") and hasattr(client.aio, "aclose"):
            try:
                await client.aio.aclose()
            except Exception:
                pass
            client = None


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
            detail="An internal error occurred. Something went wrong while I was finding your films. Try again, or adjust your choices."
        )


# Serve static web demo UI if static directory exists
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def serve_index() -> HTMLResponse:
        index_file = STATIC_DIR / "index.html"
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"), headers=headers)
        return HTMLResponse(content="<h1>TONI API is Running</h1><p>Visit <a href='/docs'>/docs</a> for Swagger UI.</p>", headers=headers)
