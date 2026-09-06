"""
TONI - Tonight's Options, Narrowed Intelligently
FastAPI HTTP Backend Service Wrapper

Exposes production-ready REST API endpoints to serve recommendation requests,
streaming availability lookups, and demo personas to Tina's frontend or external callers.
"""

import os
import sys
import re
import time
import math
import struct
import base64
import json
import asyncio
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

from fastapi import FastAPI, Query, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
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


@app.get("/api/export-logs", summary="Export Conversation Transcript Logs")
def export_conversation_logs() -> Dict[str, Any]:
    """Returns the JSON contents of logs/conversations.jsonl for offline analysis and refinement."""
    log_file = Path("logs") / "conversations.jsonl"
    if not log_file.exists():
        return {"total_turns": 0, "turns": []}
    turns = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        turns.append(json.loads(line_str))
                    except json.JSONDecodeError:
                        continue
        return {"total_turns": len(turns), "turns": turns}
    except Exception as e:
        print(f"[*] Error reading conversation logs: {e}", file=sys.stderr)
        return {"total_turns": 0, "turns": [], "error": str(e)}


# --- VOICE & SINGLE-BRAIN DIALOGUE SERVICE ---

def enforce_toni_brand_name(text: str) -> str:
    """Enforce brand name lock: Assistant persona must always refer to itself as TONI."""
    if not text:
        return ""
    cleaned = re.sub(r'\bCharon\b', 'TONI', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bI am Charon\b', 'I am TONI', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bMy name is Charon\b', 'My name is TONI', cleaned, flags=re.IGNORECASE)
    return cleaned


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
        os.makedirs("logs", exist_ok=True)
        log_file = Path("logs") / "conversations.jsonl"

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
        with open(log_file, "a", encoding="utf-8") as f:
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


def _process_voice_turn_fallback(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    try:
        user_text = (turn_req.user_input or "").strip()
        lower = user_text.lower()
        ctx = turn_req.current_context.model_copy(deep=True) if turn_req.current_context else UserContext()
        ctx.dialogue_mode = turn_req.mode or "text"
        ctx.voice_name = getattr(ctx, "voice_name", "Charon") or "Charon"

        extracted_signals = []

        # Ready to recommend keywords (explicit affirmative user intent)
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

        # Strict readiness: only if explicit affirmative user intent is detected
        if ready:
            reply = "I've got a good sense of what you're after. Let's see what fits."
        elif extracted_signals:
            summary_parts = [f"{s.value}" for s in extracted_signals]
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


def process_voice_turn(turn_req: VoiceTurnRequest) -> VoiceTurnResponse:
    """Processes a dialogue turn using Gemini Flash if available, with structured fallback."""
    has_gemini_key = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not has_gemini_key:
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

        # Update fields
        if data.country and str(data.country).upper() in ("UK", "US"):
            ctx.country = str(data.country).upper()
        if data.services:
            for s in data.services:
                s_str = str(s).strip()
                if s_str and s_str not in ctx.service_access:
                    ctx.service_access.append(s_str)

        # Update signals with defensive casting
        new_signals = []
        if data.pacing:
            new_signals.append(TasteSignal(name=SIGNAL_PACING, value=str(data.pacing).lower().strip(), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        if data.tone:
            new_signals.append(TasteSignal(name=SIGNAL_TONE, value=str(data.tone).lower().strip(), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        if data.demandingness is not None:
            try:
                new_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=float(data.demandingness), signal_type=SignalType.SOFT_SESSION_PREFERENCE))
            except (ValueError, TypeError):
                pass
        if data.max_runtime is not None:
            try:
                digits = re.findall(r'\d+', str(data.max_runtime))
                if digits:
                    new_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=int(digits[0]), signal_type=SignalType.HARD_CONSTRAINT))
            except (ValueError, TypeError):
                pass
        if data.exclude_genres:
            if isinstance(data.exclude_genres, list):
                new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[str(g) for g in data.exclude_genres], signal_type=SignalType.HARD_CONSTRAINT))
            elif isinstance(data.exclude_genres, str):
                new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[data.exclude_genres], signal_type=SignalType.HARD_CONSTRAINT))

        new_names = {s.name for s in new_signals}
        merged_signals = [s for s in ctx.tonight_signals if s.name not in new_names]
        merged_signals.extend(new_signals)
        ctx.tonight_signals = merged_signals

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
    gemini_session = None
    gemini_recv_task = None
    live_cm = None

    user_transcript_buf: List[str] = []
    assistant_transcript_buf: List[str] = []

    async def forward_gemini_responses(session):
        nonlocal session_ctx, conversation_history, user_transcript_buf, assistant_transcript_buf
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
                        user_chunk = content.input_transcription.text
                        user_transcript_buf.append(user_chunk)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": user_chunk,
                            "role": "user"
                        })
                    if content.model_turn:
                        for part in content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                raw_data = part.inline_data.data
                                audio_b64 = raw_data if isinstance(raw_data, str) else base64.b64encode(raw_data).decode("ascii")
                                await websocket.send_json({
                                    "type": "audio",
                                    "data": audio_b64,
                                    "mime_type": "audio/pcm;rate=24000"
                                })
                    if content.output_transcription and content.output_transcription.text:
                        bot_chunk = enforce_toni_brand_name(content.output_transcription.text)
                        assistant_transcript_buf.append(bot_chunk)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": bot_chunk,
                            "role": "assistant"
                        })
                    if content.turn_complete:
                        full_user = "".join(user_transcript_buf).strip()
                        full_bot = enforce_toni_brand_name("".join(assistant_transcript_buf).strip())
                        ready_flag = False
                        if full_user:
                            conversation_history.append({"role": "user", "content": full_user})
                            try:
                                turn_req = VoiceTurnRequest(
                                    user_input=full_user,
                                    mode="voice",
                                    current_context=session_ctx,
                                    conversation_history=conversation_history
                                )
                                turn_res = await asyncio.to_thread(process_voice_turn, turn_req)
                                session_ctx = turn_res.updated_context
                                ready_flag = turn_res.ready_to_recommend
                            except Exception as ex:
                                print(f"[*] Voice turn context update notice: {ex}", file=sys.stderr)
                        if full_bot:
                            conversation_history.append({"role": "assistant", "content": full_bot})

                        user_transcript_buf.clear()
                        assistant_transcript_buf.clear()

                        lower_user = full_user.lower() if full_user else ""
                        explicit_user_ready = any(kw in lower_user for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                        final_ready = ready_flag or explicit_user_ready

                        log_conversation_turn(
                            session_id=f"ws_{id(websocket)}",
                            mode="voice",
                            user_input=full_user,
                            assistant_reply=full_bot,
                            signals=session_ctx.tonight_signals,
                            context=session_ctx
                        )

                        await websocket.send_json({
                            "type": "turn_complete",
                            "assistant_reply": full_bot,
                            "updated_context": session_ctx.model_dump(),
                            "ready_to_recommend": final_ready
                        })
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[!] Gemini Live receiver error: {e}", file=sys.stderr)

    if has_gemini_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client()
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
                "gemini-3.1-flash-live-preview"
            ]
            for m in live_models:
                try:
                    live_cm = client.aio.live.connect(model=m, config=config)
                    gemini_session = await live_cm.__aenter__()
                    gemini_recv_task = asyncio.create_task(forward_gemini_responses(gemini_session))
                    connected_model = m
                    print(f"[*] Gemini Live session established with model: {m}", file=sys.stderr)
                    break
                except Exception as ex:
                    print(f"[*] Gemini Live model {m} connect attempt failed ({type(ex).__name__}): {repr(ex)}", file=sys.stderr)
        except Exception as e:
            print(f"[*] Gemini Live session setup failed ({type(e).__name__}): {repr(e)}", file=sys.stderr)
            gemini_session = None

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
                    except Exception:
                        pass
                if "conversation_history" in data and isinstance(data["conversation_history"], list):
                    conversation_history = data["conversation_history"]
                await websocket.send_json({
                    "type": "init_ack",
                    "status": "ready" if gemini_session else "fallback",
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
                        user_transcript_buf.append(user_text)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": user_text,
                            "role": "user"
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
                        "assistant_reply": turn_res.assistant_reply,
                        "updated_context": session_ctx.model_dump(),
                        "ready_to_recommend": final_ready
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[!] WebSocket live notice: {e}", file=sys.stderr)
    finally:
        if gemini_recv_task:
            gemini_recv_task.cancel()
        if gemini_session and live_cm:
            try:
                await live_cm.__aexit__(None, None, None)
            except Exception:
                pass


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
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>TONI API is Running</h1><p>Visit <a href='/docs'>/docs</a> for Swagger UI.</p>")
