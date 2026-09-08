"""
TONI - Tonight's Options, Narrowed Intelligently
FastAPI HTTP Backend Service Wrapper

Exposes production-ready REST API endpoints to serve recommendation requests,
streaming availability lookups, and progressive review analysis.
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
import hashlib
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
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

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
    SIGNAL_PREFERRED_GENRES,
    SIGNAL_REFERENCE_FILMS,
)
from gemini_client import get_gemini_client, EXTRACTION_MODEL, VOICE_MODEL
from fastapi.openapi.utils import get_openapi
from ranking import rank_movies
from availability import SERVICE_NAME_MAP
from review_updates import ReviewRequest, stream_review_updates

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
        {"id": "sky_go", "name": "Sky Go", "tier": "subscription"},
        {"id": "now_cinema", "name": "NOW Cinema", "tier": "subscription"},
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

CONVERSATIONS_LOG_PATH = Path("logs") / "conversations.jsonl"


def join_transcript_chunks(chunks: List[str]) -> str:
    """Preserve upstream text deltas; whitespace is part of each delta."""
    return "".join(chunk for chunk in chunks if chunk).strip()


from build_provenance import source_manifest, verify_manifest


def compute_source_fingerprint() -> str:
    return source_manifest()["source_fingerprint"]


BASE_GIT_SHA = "e1b14c748273bf309b1790571ecf768cd96c3103"


@app.get("/api/health", summary="Health Check")
def health_check() -> Dict[str, Any]:
    """Check API health, revision metadata, and status of external integrations."""
    parallel_key = os.environ.get("PARALLEL_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    provenance = verify_manifest()
    source_fp = provenance["source_fingerprint"]
    configured_git_sha = os.environ.get("GIT_SHA")
    effective_git_sha = configured_git_sha if configured_git_sha and configured_git_sha not in ("unknown", "prod") else BASE_GIT_SHA

    return {
        "status": "healthy",
        "service": "TONI Recommendation Engine",
        "version": "1.0.0",
        "base_git_sha": provenance["base_git_sha"],
        "git_sha": effective_git_sha,
        "is_dirty": provenance["is_dirty"],
        "source_fingerprint": source_fp,
        "source_provenance": {
            "base_commit": provenance["base_git_sha"],
            "manifest_verified": provenance["manifest_verified"],
            "source_fingerprint": source_fp,
            "status": "repaired_uncommitted"
        },
        "revision": os.environ.get("K_REVISION", "local"),
        "gemini_backend": "Gemini Developer API (vertexai=False)",
        "integrations": {
            "parallel_web": bool(parallel_key),
            "gemini_developer_api": bool(gemini_key),
            "google_genai_use_vertexai": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "False"),
            "google_cloud_project": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
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
    """Enforce brand name lock and speaker identity contract:
    - Assistant persona refers to itself as TONI (never Charon or Gemini).
    - Assistant NEVER addresses the viewer as TONI, Tony, or Charon.
    """
    if not text:
        return ""

    # 1. Strip vocative addressing of the viewer as TONI, Tony, or Charon
    # e.g., "I'm here, TONI." -> "I'm here."
    # e.g., "I'm right here, Charon." -> "I'm right here."
    # e.g., "Hello, TONI!" -> "Hello!"
    # e.g., "Sure, TONI, what can I do?" -> "Sure, what can I do?"
    cleaned = re.sub(
        r',\s*(?:TONI|Tony|Charon)\s*,',
        ',',
        text,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r',\s*(?:TONI|Tony|Charon)(?=[.!?,;]|$)',
        '',
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r'\b(I[\'’]m(?:\s+right)?\s+here|hello|hi|hey|sure thing|sure|no problem|understood|got it)[,\s]+(?:TONI|Tony|Charon)\b',
        r'\1',
        cleaned,
        flags=re.IGNORECASE
    )

    # 2. Assistant self-identification: replace leaked internal engine names with TONI
    cleaned = re.sub(r'\b(?:I am|I[\'’]m|This is|call me)\s+Charon\b', r"I am TONI", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bCharon\b', 'TONI', cleaned, flags=re.IGNORECASE)

    # Clean up duplicate punctuation or trailing spaces
    cleaned = re.sub(r'\s+([.!?])', r'\1', cleaned)
    cleaned = re.sub(r'([.!?]){2,}', r'\1', cleaned)

    return cleaned.strip()


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
    clear_max_runtime: bool = Field(default=False, description="True if user explicitly cleared runtime constraints, e.g. 'any length is fine' or 'no limit'")
    exclude_genres: Optional[List[str]] = Field(default=None, description="genres to exclude")
    clear_exclusions: bool = Field(default=False, description="True if user explicitly cleared genre exclusions")
    remove_exclusions: Optional[List[str]] = Field(default=None, description="specific genres to remove from exclusions")
    preferred_genres: Optional[List[str]] = Field(default=None, description="genres the user positively desires")
    reference_films: Optional[List[str]] = Field(default=None, description="specific film titles mentioned as positive reference favourites")
    country: Optional[str] = Field(default=None, description="UK or US if mentioned")
    services: Optional[List[str]] = Field(default=None, description="streaming services mentioned")
    replace_services: Optional[List[str]] = Field(default=None, description="streaming services if user specifies exclusive list e.g. 'Netflix only'")
    remove_services: Optional[List[str]] = Field(default=None, description="streaming services to remove e.g. 'remove Disney+'")
    ready_to_recommend: bool = Field(default=False, description="True if user wants recommendations now or sufficient taste details have been shared")


class ContextExtractionLLMOutput(BaseModel):
    """Schema for extracting structured context signals and readiness without conversational reply."""
    pacing: Optional[str] = Field(default=None, description="pacing preference e.g. brisk, steady, leisurely, measured")
    tone: Optional[str] = Field(default=None, description="tone preference e.g. funny, intense, magical, dark, warm, satirical")
    demandingness: Optional[float] = Field(default=None, description="score 1.0 to 5.0")
    max_runtime: Optional[int] = Field(default=None, description="runtime limit in minutes")
    clear_max_runtime: bool = Field(default=False, description="True if user explicitly cleared runtime constraints, e.g. 'any length is fine' or 'no limit'")
    exclude_genres: Optional[List[str]] = Field(default=None, description="genres to exclude")
    clear_exclusions: bool = Field(default=False, description="True if user explicitly cleared genre exclusions")
    remove_exclusions: Optional[List[str]] = Field(default=None, description="specific genres to remove from exclusions")
    preferred_genres: Optional[List[str]] = Field(default=None, description="genres the user positively desires")
    reference_films: Optional[List[str]] = Field(default=None, description="specific film titles mentioned as positive reference favourites")
    country: Optional[str] = Field(default=None, description="UK or US if mentioned")
    services: Optional[List[str]] = Field(default=None, description="streaming services mentioned")
    replace_services: Optional[List[str]] = Field(default=None, description="streaming services if user specifies exclusive list e.g. 'Netflix only'")
    remove_services: Optional[List[str]] = Field(default=None, description="streaming services to remove e.g. 'remove Disney+'")
    ready_to_recommend: bool = Field(default=False, description="True if user explicitly requests recommendations or confirms they are ready")


def _apply_explicit_service_access(ctx: UserContext, user_input: str) -> UserContext:
    """Expand an explicit all-platform declaration to this market's supported services."""
    text = user_input.lower().replace("’", "'")
    all_platforms = re.search(r"\b(?:all|every)\s+(?:the\s+)?(?:streaming\s+)?(?:platforms?|services?|channels?)\b", text)
    if not all_platforms:
        all_platforms = re.search(r"\b(?:access\s+to|subscribe\s+to)\s+(?:everything|all(?:\s+of\s+them)?)\b", text)
    if not all_platforms:
        # A possessive answer to the service question, including natural speech fillers.
        # Do not interpret unrelated uses such as "I want to watch all of them".
        all_platforms = re.search(r"\b(?:have|got|use)\s+(?:access\s+to\s+)?(?:all\s+of\s+them|them\s+all)\b", text)
    prefix = text[:all_platforms.start()] if all_platforms else ""
    negated = re.search(r"\b(?:not|don't|dont|haven't|can't|cannot|no|without)\s+(?:(?:have|got|access|to|use|subscribe|really|currently)\s+)*$", prefix)
    access = re.search(r"\b(?:have|got|access\s+to|subscribe\s+to|use)\b", text)
    if all_platforms and access and not negated:
        ctx.service_access = [p['name'] for p in PROVIDER_PRESETS.get(ctx.country, [])]
    return ctx


def _merge_signals_into_context(ctx: UserContext, data: Any) -> UserContext:
    """Defensively merges extracted structured signals and metadata into the UserContext with explicit clearing semantics."""
    if hasattr(data, "country") and data.country and str(data.country).upper() in ("UK", "US"):
        ctx.country = str(data.country).upper()

    # 1. Services: replacement, removal, addition
    replace_services = getattr(data, "replace_services", None)
    remove_services = getattr(data, "remove_services", None)
    if replace_services is not None:
        ctx.service_access = [str(s).strip() for s in replace_services if str(s).strip()]
    else:
        if remove_services:
            rem_set = {str(r).lower().strip() for r in remove_services}
            ctx.service_access = [s for s in ctx.service_access if s.lower().strip() not in rem_set]
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

    # 2. Runtime: clear vs set
    clear_runtime = bool(getattr(data, "clear_max_runtime", False))
    max_rt = getattr(data, "max_runtime", None)
    if max_rt in (0, -1):
        clear_runtime = True

    if clear_runtime:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_MAX_RUNTIME]
    elif max_rt is not None:
        try:
            digits = re.findall(r'\d+', str(max_rt))
            if digits and int(digits[0]) > 0:
                new_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=int(digits[0]), signal_type=SignalType.HARD_CONSTRAINT))
        except (ValueError, TypeError):
            pass

    # 3. Exclusions: clear, remove, or replace
    clear_excl = bool(getattr(data, "clear_exclusions", False))
    rem_excl = getattr(data, "remove_exclusions", None)
    excl_genres = getattr(data, "exclude_genres", None)

    # Find existing exclusions
    existing_excl_sig = next((s for s in ctx.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE), None)
    current_excl = []
    if existing_excl_sig:
        if isinstance(existing_excl_sig.value, list):
            current_excl = list(existing_excl_sig.value)
        elif isinstance(existing_excl_sig.value, str):
            current_excl = [existing_excl_sig.value]

    if clear_excl:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_EXCLUDE_GENRE]
    elif rem_excl:
        rem_set = {str(r).lower().strip() for r in rem_excl}
        current_excl = [g for g in current_excl if g.lower().strip() not in rem_set]
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_EXCLUDE_GENRE]
        if current_excl:
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=current_excl, signal_type=SignalType.HARD_CONSTRAINT))
    elif excl_genres is not None:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_EXCLUDE_GENRE]
        if isinstance(excl_genres, list) and excl_genres:
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[str(g).strip() for g in excl_genres if str(g).strip()], signal_type=SignalType.HARD_CONSTRAINT))
        elif isinstance(excl_genres, str) and excl_genres.strip():
            new_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=[excl_genres.strip()], signal_type=SignalType.HARD_CONSTRAINT))

    # 4. Preferred Genres & Reference Films
    pref_genres = getattr(data, "preferred_genres", None)
    if pref_genres is not None:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_PREFERRED_GENRES]
        if isinstance(pref_genres, list) and pref_genres:
            new_signals.append(TasteSignal(name=SIGNAL_PREFERRED_GENRES, value=[str(g).strip() for g in pref_genres if str(g).strip()], signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        elif isinstance(pref_genres, str) and pref_genres.strip():
            new_signals.append(TasteSignal(name=SIGNAL_PREFERRED_GENRES, value=[pref_genres.strip()], signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    ref_films = getattr(data, "reference_films", None)
    if ref_films is not None:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_REFERENCE_FILMS]
        if isinstance(ref_films, list) and ref_films:
            new_signals.append(TasteSignal(name=SIGNAL_REFERENCE_FILMS, value=[str(f).strip() for f in ref_films if str(f).strip()], signal_type=SignalType.SOFT_SESSION_PREFERENCE))
        elif isinstance(ref_films, str) and ref_films.strip():
            new_signals.append(TasteSignal(name=SIGNAL_REFERENCE_FILMS, value=[ref_films.strip()], signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    new_names = {s.name for s in new_signals}
    merged_signals = [s for s in ctx.tonight_signals if s.name not in new_names]
    merged_signals.extend(new_signals)
    ctx.tonight_signals = merged_signals
    return ctx



def check_explicit_search_intent(user_text: str) -> bool:
    """Evaluates whether the user explicitly gave permission/intent to search for recommendations.
    Decouples 'enough information gathered' from 'permission to search'.
    Negative phrases ('don't recommend yet', 'not yet', 'wait', 'hold on') prevent search.
    Answering service questions ('yes', 'yes please') without explicit search words does not authorize search."""
    if not user_text:
        return False
    lower = user_text.lower()
    negative_intents = [
        "don't recommend", "do not recommend", "not yet", "don't show",
        "wait", "hold on", "stop", "don't start", "not now"
    ]
    if any(neg in lower for neg in negative_intents):
        return False

    search_triggers = [
        "find what fits", "show me", "recommend", "find movies",
        "bring up the shortlist", "bring up the list", "bring up shortlist", "bring up",
        "what should i watch", "show shortlist", "shortlist", "let's see what fits",
        "see what fits", "let's see", "fits tonight", "surprise me", "hit me",
        "let's go", "synthesize", "show me what you got"
    ]
    return any(st in lower for st in search_triggers)


GENRE_CANONICAL = {
    "horror": "Horror",
    "sci-fi": "Sci-Fi",
    "scifi": "Sci-Fi",
    "science fiction": "Sci-Fi",
    "comedy": "Comedy",
    "comedies": "Comedy",
    "romance": "Romance",
    "romantic": "Romance",
    "action": "Action",
    "drama": "Drama",
    "dramas": "Drama",
    "thriller": "Thriller",
    "thrillers": "Thriller",
    "suspense": "Thriller",
    "documentary": "Documentary",
    "documentaries": "Documentary",
    "animation": "Animation",
    "animated": "Animation",
    "cartoon": "Animation",
    "cartoons": "Animation",
    "fantasy": "Fantasy",
    "mystery": "Mystery",
    "mysteries": "Mystery",
    "crime": "Crime",
    "western": "Western",
    "musical": "Musical",
    "adventure": "Adventure",
    "adventures": "Adventure",
    "family": "Family",
    "kids": "Family",
    "children": "Family",
    "children's": "Family",
    "history": "History",
    "historical": "History",
    "war": "War",
}


def _extract_voice_context_fallback(user_text: str, current_ctx: UserContext) -> Tuple[UserContext, bool]:
    """Local deterministic fallback for extracting signals from user text with robust negation, runtime clearing, and service replacement."""
    ctx = current_ctx.model_copy(deep=True)
    raw_lower = (user_text or "").lower()
    extracted_signals = []

    # Ready to recommend via contextual search intent
    ready = check_explicit_search_intent(raw_lower)

    # 1. Parse Negations / Excluded Genres
    excluded = set()
    for s in ctx.tonight_signals:
        if s.name == SIGNAL_EXCLUDE_GENRE:
            if isinstance(s.value, list):
                excluded.update(s.value)
            elif isinstance(s.value, str):
                excluded.add(s.value)

    # Detect clearance of exclusions (e.g. "horror is fine now", "remove that exclusion")
    if any(p in raw_lower for p in ["remove that exclusion", "remove the exclusion", "clear exclusions", "remove exclusions", "no exclusions"]):
        excluded.clear()

    for key, cname in GENRE_CANONICAL.items():
        if any(p in raw_lower for p in [f"{key} is fine", f"allow {key}", f"remove {key}", f"unblock {key}", f"include {key}"]):
            excluded.discard(cname)

    # Parse multi-negation phrases: "no [genre1] or [genre2]"
    masked_text = raw_lower
    multi_neg_patterns = [
        r"\b(?:no|not|without|exclude|avoid|don't want|dont want)\s+([a-z\-]+)\s+or\s+([a-z\-]+)\b",
        r"\b(?:no|not|without|exclude|avoid|don't want|dont want)\s+([a-z\-]+)\s+nor\s+([a-z\-]+)\b",
    ]
    for mpat in multi_neg_patterns:
        for match in re.finditer(mpat, raw_lower):
            g1, g2 = match.group(1), match.group(2)
            if g1 in GENRE_CANONICAL:
                excluded.add(GENRE_CANONICAL[g1])
            if g2 in GENRE_CANONICAL:
                excluded.add(GENRE_CANONICAL[g2])
            masked_text = masked_text.replace(match.group(0), " ")

    # Parse single negation phrases: "no [genre]", "not [genre]", "hate [genre]", "without [genre]", "exclude [genre]"
    for key, cname in GENRE_CANONICAL.items():
        neg_patterns = [
            rf"\b(?:no|not|hate|without|exclude|avoid|don't want|dont want)\s+(?:any\s+)?{key}\b",
            rf"\b{key}\s+is\s+out\b",
            rf"\brule\s+out\s+{key}\b",
        ]
        for pat in neg_patterns:
            if re.search(pat, raw_lower):
                excluded.add(cname)
                masked_text = re.sub(pat, " ", masked_text)
        if f"no {key}" in raw_lower:
            excluded.add(cname)
            masked_text = masked_text.replace(f"no {key}", " ")

    # Always clear existing exclude-genre signal from ctx.tonight_signals
    ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_EXCLUDE_GENRE]
    if excluded:
        extracted_signals.append(TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=sorted(list(excluded)), signal_type=SignalType.HARD_CONSTRAINT))

    # 2. Runtime / Duration handling
    runtime_clear_phrases = [
        "any length", "no time limit", "no length limit", "doesn't matter how long",
        "does not matter how long", "any runtime", "no limit", "as long as it takes",
        "length doesn't matter", "time doesn't matter", "any duration", "no duration limit"
    ]
    clear_runtime = any(p in raw_lower for p in runtime_clear_phrases)

    if clear_runtime:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_MAX_RUNTIME]
    else:
        # Max Runtime (enhanced with flexible phrasing)
        runtime_m = re.search(r'(?:under|less than|nothing over|no more than|max(?:imum)?)\s+(\d+)\s*(?:min|minute|m\b)', raw_lower)
        if runtime_m:
            extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=int(runtime_m.group(1)), signal_type=SignalType.HARD_CONSTRAINT))
        elif any(p in raw_lower for p in ["under 2 hours", "under two hours", "nothing over 2 hours", "nothing over two hours", "no more than 2 hours", "less than 2 hours", "under 120"]):
            extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=120, signal_type=SignalType.HARD_CONSTRAINT))
        elif any(p in raw_lower for p in ["under 90", "under an hour and a half", "nothing over 90", "no more than 90"]):
            extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=90, signal_type=SignalType.HARD_CONSTRAINT))
        elif ("short film" in raw_lower or "keep it short" in raw_lower or re.search(r'\bshort\b', raw_lower)) and "shortlist" not in raw_lower:
            extracted_signals.append(TasteSignal(name=SIGNAL_MAX_RUNTIME, value=100, signal_type=SignalType.HARD_CONSTRAINT))

    # 3. Pacing (on masked_text)
    if any(kw in masked_text for kw in ["brisk", "fast", "quick", "rapid", "snappy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_PACING, value="brisk", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["leisurely", "slow", "patient", "unhurried"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_PACING, value="leisurely", signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # 4. Tone (on masked_text to avoid matching negated words)
    if any(kw in masked_text for kw in ["funny", "laugh", "hilarious", "comedy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="funny", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["dark", "bleak", "gritty", "unsettling"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="bleak", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["intense", "tense", "thrilling", "action", "suspense"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="intense", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["magical", "wondrous", "whimsical", "fairytale"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="magical", signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["warm", "heartwarming", "feel-good", "wholesome", "gentle", "heartfelt"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_TONE, value="warm", signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # 5. Demandingness (on masked_text)
    if any(kw in masked_text for kw in ["easy", "light", "relaxing", "unwind", "turn my brain off", "not demanding"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=2.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    elif any(kw in masked_text for kw in ["deep", "challenging", "thought-provoking", "intellectual", "demanding", "heavy"]):
        extracted_signals.append(TasteSignal(name=SIGNAL_DEMANDINGNESS, value=4.2, signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # 6. Positive Genre Extraction (on masked_text)
    pos_genre_patterns = [
        r"^\s*([a-z\-]+)(?:\s+(?:please|tonight))?[.!?]*\s*$",
        r"\b(?:i want|i'd like|id like|looking for|in the mood for|give me|show me)\s+(?:a\s+|an\s+|some\s+)?(?:good\s+|great\s+)?([a-z\-]+)\b",
        r"\b(?:a|an)\s+([a-z\-]+)\s+(?:film|movie|feature)\b",
        r"\b([a-z\-]+)\s+(?:film|movie)\s+(?:tonight|please)\b",
    ]
    detected_pos_genres = []
    for pat in pos_genre_patterns:
        for match in re.finditer(pat, masked_text):
            candidate_g = match.group(1).lower().strip()
            if candidate_g in GENRE_CANONICAL:
                cname = GENRE_CANONICAL[candidate_g]
                if cname not in excluded and cname not in detected_pos_genres:
                    detected_pos_genres.append(cname)

    if detected_pos_genres:
        ctx.tonight_signals = [s for s in ctx.tonight_signals if s.name != SIGNAL_PREFERRED_GENRES]
        extracted_signals.append(TasteSignal(name=SIGNAL_PREFERRED_GENRES, value=detected_pos_genres, signal_type=SignalType.SOFT_SESSION_PREFERENCE))

    # 7. Services & Country
    all_service_keys = [
        ("netflix", "Netflix"),
        ("prime", "Prime Video"),
        ("disney", "Disney+"),
        ("iplayer", "BBC iPlayer"),
        (r"sky(?:\s+(?:go|cinema))?(?!\s+store)", "Sky Go"),
        (r"now\s+(?:tv(?:\s+cinema)?|cinema)", "NOW Cinema"),
        ("paramount", "Paramount+"),
        ("max", "Max"),
        ("apple", "Apple TV+")
    ]

    is_exclusive_services = False
    exclusive_matches = []
    for s_id, s_name in all_service_keys:
        if re.search(rf"\b(?:only\s+{s_id}|{s_id}\s+only|just\s+{s_id}|only\s+have\s+{s_id})\b", raw_lower):
            is_exclusive_services = True
            exclusive_matches.append(s_name)

    if is_exclusive_services and exclusive_matches:
        ctx.service_access = list(exclusive_matches)
    else:
        for s_id, s_name in all_service_keys:
            if re.search(rf"\b(?:remove|drop|cancel|without|no)\s+(?:the\s+)?{s_id}\b", raw_lower):
                ctx.service_access = [s for s in ctx.service_access if s != s_name]
            elif re.search(rf"\b{s_id}\b", raw_lower) and s_name not in ctx.service_access:
                ctx.service_access.append(s_name)

    if is_exclusive_services:
        for s_id, s_name in all_service_keys:
            if re.search(rf"\b(?:remove|drop|cancel|without|no)\s+(?:the\s+)?{s_id}\b", raw_lower):
                ctx.service_access = [s for s in ctx.service_access if s != s_name]

    if re.search(r"\b(?:uk|united kingdom|british)\b", raw_lower):
        ctx.country = "UK"
    elif re.search(r"\b(?:us|united states|american)\b", raw_lower):
        ctx.country = "US"

    ctx = _apply_explicit_service_access(ctx, user_text)

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
            summary_parts = []
            for s in ctx.tonight_signals:
                if s.name == SIGNAL_EXCLUDE_GENRE:
                    if isinstance(s.value, list):
                        summary_parts.append("no " + " or ".join(s.value))
                    else:
                        summary_parts.append(f"no {s.value}")
                elif s.name == SIGNAL_MAX_RUNTIME:
                    summary_parts.append(f"under {s.value} mins")
                elif isinstance(s.value, list):
                    summary_parts.append(", ".join(str(v) for v in s.value))
                else:
                    summary_parts.append(str(s.value))
            reply = f"Got it — {', '.join(summary_parts)}. Which channels do you have access to?"
        else:
            reply = "Tell me what you're in the mood for. A pace, genre, feeling or even a film you liked is enough to start."

        if turn_req.mode == "voice" and ctx.service_access and ctx.tonight_signals:
            reply = "Shall I search with these choices?"
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
    timeout: float = 6.0,
    return_mode: bool = False
) -> Union[Tuple[UserContext, bool], Tuple[UserContext, bool, str]]:
    """Extracts structured signals and shortlist readiness from spoken input without generating a redundant conversational reply."""
    if not user_input or not user_input.strip():
        if return_mode:
            return current_context, False, "noop"
        return current_context, False

    ctx = current_context.model_copy(deep=True)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if has_gemini_key and not os.environ.get("TONI_TESTING"):
        try:
            from google.genai import types

            client = get_gemini_client()

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
4. Extract max_runtime in minutes if viewer states a time limit (e.g. "under 2 hours" -> 120). If viewer clears or removes time limits (e.g. "any length is fine", "no limit"), set clear_max_runtime=True.
5. Extract exclude_genres as a list of strings if viewer wants to rule out specific genres. If viewer clears or unblocks genre exclusions (e.g. "horror is fine now", "remove that exclusion"), set clear_exclusions=True or populate remove_exclusions.
6. Extract preferred_genres (e.g. ['Comedy']) if viewer explicitly asks for or desires certain genres.
7. Extract reference_films if viewer mentions specific films they like or want films similar to.
8. Extract country ('UK' or 'US') and services. If viewer specifies exclusive services (e.g. 'Netflix only', 'I only have Netflix'), populate replace_services. If viewer asks to remove services (e.g. 'remove Disney+'), populate remove_services.
9. Set ready_to_recommend to True ONLY if the user explicitly asks to see films / recommendations or confirms they are ready."""

            timeout_ms = max(int(timeout * 1000), 10000) if timeout else 10000
            http_opts = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1)
            )

            response = client.models.generate_content(
                model="gemini-3.6-flash",
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
                ctx = _apply_explicit_service_access(ctx, user_input)
                lower_input = user_input.lower()
                explicit_ready = any(kw in lower_input for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                ready = bool(extracted.ready_to_recommend) or explicit_ready
                if return_mode:
                    return ctx, ready, "llm"
                return ctx, ready
        except Exception as ex:
            print(f"[*] Structured context extraction notice: {ex}", file=sys.stderr)

    fallback_ctx, fallback_ready = _extract_voice_context_fallback(user_input, ctx)
    if return_mode:
        return fallback_ctx, fallback_ready, "fallback"
    return fallback_ctx, fallback_ready


async def extract_voice_context_async(
    user_input: str,
    current_context: UserContext,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 6.0,
    client: Optional[Any] = None,
    return_mode: bool = False
) -> Union[Tuple[UserContext, bool], Tuple[UserContext, bool, str]]:
    """Extracts structured signals and shortlist readiness asynchronously with enforced request deadline."""
    if not user_input or not user_input.strip():
        if return_mode:
            return current_context, False, "noop"
        return current_context, False

    ctx = current_context.model_copy(deep=True)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if has_gemini_key and not os.environ.get("TONI_TESTING"):
        try:
            from google.genai import types

            if client is None:
                client = get_gemini_client()

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
4. Extract max_runtime in minutes if viewer states a time limit (e.g. "under 2 hours" -> 120). If viewer clears or removes time limits (e.g. "any length is fine", "no limit"), set clear_max_runtime=True.
5. Extract exclude_genres as a list of strings if viewer wants to rule out specific genres. If viewer clears or unblocks genre exclusions (e.g. "horror is fine now", "remove that exclusion"), set clear_exclusions=True or populate remove_exclusions.
6. Extract preferred_genres (e.g. ['Comedy']) if viewer explicitly asks for or desires certain genres.
7. Extract reference_films if viewer mentions specific films they like or want films similar to.
8. Extract country ('UK' or 'US') and services. If viewer specifies exclusive services (e.g. 'Netflix only', 'I only have Netflix'), populate replace_services. If viewer asks to remove services (e.g. 'remove Disney+'), populate remove_services.
9. Set ready_to_recommend to True ONLY if the user explicitly asks to see films / recommendations or confirms they are ready."""

            timeout_ms = max(int(timeout * 1000), 10000) if timeout else 10000
            http_opts = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1)
            )

            overall_deadline = (timeout or 6.0) + (1.0 if (timeout or 6.0) >= 4.0 else 0.2)
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-3.6-flash",
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
                ctx = _apply_explicit_service_access(ctx, user_input)
                lower_input = user_input.lower()
                explicit_ready = any(kw in lower_input for kw in ["show me", "recommend", "find movies", "yes please", "bring up", "find what fits", "what to watch", "let's see", "shortlist", "show shortlist", "let's go"])
                ready = bool(extracted.ready_to_recommend) or explicit_ready
                if return_mode:
                    return ctx, ready, "llm"
                return ctx, ready
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print(f"[*] Async structured context extraction notice: {ex}", file=sys.stderr)

    fallback_ctx, fallback_ready = _extract_voice_context_fallback(user_input, ctx)
    if return_mode:
        return fallback_ctx, fallback_ready, "fallback"
    return fallback_ctx, fallback_ready


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
        self.last_committed_turn_id: int = 0
        self.context_epoch = 0
        self.context_edits = {}
        self.worker_task = asyncio.create_task(self._worker_loop())

    def update_context(self, ctx: UserContext):
        before = self.session_ctx.model_dump()
        after = ctx.model_dump()
        self.context_epoch += 1
        for field, value in after.items():
            if value != before.get(field):
                self.context_edits[field] = self.context_epoch
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
                extraction_epoch = self.context_epoch
                ready_flag = False
                extraction_mode = "fallback"

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
                        extraction_mode = "fallback"
                    else:
                        try:
                            import inspect
                            sig = inspect.signature(extract_voice_context_async)
                            call_kwargs = {
                                "user_input": full_user,
                                "current_context": self.session_ctx,
                                "conversation_history": history_snapshot,
                                "timeout": 6.0,
                                "client": self.client,
                            }
                            if "return_mode" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                                call_kwargs["return_mode"] = True

                            self.in_flight_task = asyncio.create_task(
                                extract_voice_context_async(**call_kwargs)
                            )
                            raw_res = await self.in_flight_task
                            if isinstance(raw_res, tuple) and len(raw_res) == 3:
                                res_ctx, res_ready, res_mode = raw_res
                            else:
                                res_ctx, res_ready = raw_res
                                res_mode = "llm"

                            if self.in_flight_cancelled_for_overload:
                                # Invalidate late model result! Substitute deterministic fallback
                                extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                                extraction_mode = "fallback"
                            else:
                                extracted_ctx, ready_flag = res_ctx, res_ready
                                extraction_mode = res_mode
                        except asyncio.CancelledError:
                            if self.is_disconnected:
                                break
                            # Cancelled due to overload: substitute deterministic fallback
                            extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                            extraction_mode = "fallback"
                        except Exception as ex:
                            print(f"[*] Extraction worker error: {ex}", file=sys.stderr)
                            extracted_ctx, ready_flag = _extract_voice_context_fallback(full_user, self.session_ctx)
                            extraction_mode = "fallback"
                        finally:
                            self.in_flight_task = None

                if self.is_disconnected:
                    break

                # --- ONE ORDERED COMMIT PATH ---
                # Owns all context mutations, history updates, and completion notifications
                # Explicit UI edits arriving during extraction take precedence over
                # the older model snapshot. Other newly extracted fields still merge.
                preserved = {field: getattr(self.session_ctx, field)
                             for field, epoch in self.context_edits.items()
                             if epoch > extraction_epoch}
                if preserved:
                    extracted_ctx = extracted_ctx.model_copy(update=preserved, deep=True)
                self.session_ctx = extracted_ctx
                if full_user:
                    self.conversation_history.append({"role": "user", "content": full_user})
                if full_bot:
                    self.conversation_history.append({"role": "assistant", "content": full_bot})

                # If queue is now empty and not overloaded, reset overload flag
                if self.queue.empty():
                    self.in_flight_cancelled_for_overload = False

                explicit_user_ready = check_explicit_search_intent(full_user)
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
                        self.last_committed_turn_id = turn_id
                        await self.websocket.send_json({
                            "type": "turn_complete",
                            "turn_id": turn_id,
                            "user_text": full_user,
                            "assistant_reply": full_bot,
                            "updated_context": self.session_ctx.model_dump(),
                            "ready_to_recommend": final_ready,
                            "extraction_mode": extraction_mode
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
        from google.genai import types

        client = get_gemini_client()

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

        prompt = f"""You are TONI, an expert cinema guide helping a viewer choose what to watch tonight.
Your name is TONI. You are the assistant. You must ALWAYS refer to yourself as TONI. NEVER refer to yourself as Charon, Gemini, or any internal voice or model identifier.
SPEAKER IDENTITY CONTRACT:
- The person speaking/texting with you is the VIEWER.
- The viewer's name is completely unknown unless they explicitly say 'My name is [Name]'.
- When the viewer greets you with 'Hi Tony', 'Hello TONI', etc., they are greeting YOU by your name. It does NOT name the viewer.
- You must NEVER address the viewer as 'TONI' or 'Tony'. Never say "I'm here, TONI" or call the viewer TONI.
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
3. Determine ready_to_recommend: set to true ONLY if the user explicitly asks to see films / recommendations or confirms they are ready (e.g., 'show me', 'recommend', 'find movies', 'bring up the list', 'find what fits'). Do NOT set to true merely because 2 or more taste signals were mentioned without explicit user confirmation to proceed. Negative phrases ('don't recommend yet', 'wait', 'not yet') must NEVER trigger ready.
MANDATORY: You must NEVER recommend, pitch, name, or list specific film titles or shortlists to watch tonight. Recommendations are searched live by the application and displayed visually on screen. You may acknowledge films the viewer mentions as reference taste signals (e.g., 'Alien has great dread'), but never propose films for tonight. When the viewer confirms readiness, reply ONLY with a brief transition (e.g. 'I\'ll find what fits.') and conclude your turn.
"""

        response = None
        for model_candidate in [EXTRACTION_MODEL, "gemini-2.5-flash", "gemini-2.5-pro"]:
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
        ctx = _apply_explicit_service_access(ctx, turn_req.user_input)

        explicit_user_ready = check_explicit_search_intent(turn_req.user_input)
        ready_flag = (bool(data.ready_to_recommend) or explicit_user_ready) and not any(
            neg in (turn_req.user_input or "").lower() for neg in ["don't recommend", "not yet", "wait", "hold on", "stop"]
        )

        if ready_flag:
            clean_reply = "I've got a good sense of what you're after. Let's see what fits."
        else:
            raw_reply = str(data.assistant_reply).strip() if data.assistant_reply else "I've noted what you're in the mood for."
            clean_reply = enforce_toni_brand_name(raw_reply)

        if turn_req.mode == "voice" and ctx.service_access and ctx.tonight_signals:
            clean_reply = "Shall I search with these choices?"
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
        "model": VOICE_MODEL,
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
    transcript_commit_task = None
    input_transcription_finished = True

    async def commit_streamed_turn(delay=0):
        nonlocal turn_active
        # Transcription can trail turn_complete. Keep late words on this turn.
        if delay:
            await asyncio.sleep(delay)
        completed_turn_id = turn_counter
        turn_active = False
        full_user = join_transcript_chunks(user_transcript_buf)
        full_bot = enforce_toni_brand_name(join_transcript_chunks(assistant_transcript_buf))
        user_transcript_buf.clear()
        assistant_transcript_buf.clear()
        await websocket.send_json({"type": "speech_complete", "assistant_reply": full_bot,
                                   "turn_id": completed_turn_id})
        if extraction_pipeline:
            extraction_pipeline.enqueue_turn(turn_id=completed_turn_id, user_text=full_user,
                                             bot_text=full_bot, history_snapshot=list(conversation_history))

    async def forward_gemini_responses(session):
        nonlocal session_ctx, conversation_history, user_transcript_buf, assistant_transcript_buf, turn_counter, turn_active, extraction_pipeline, transcript_commit_task, input_transcription_finished
        try:
            while True:
                async for response in session.receive():
                    content = response.server_content
                    if not content:
                        continue
                    if content.interrupted:
                        await websocket.send_json({"type": "interrupted"})
                        assistant_transcript_buf.clear()
                        # Interrupted responses may also carry input transcription.
                    if content.input_transcription and content.input_transcription.text:
                        input_transcription_finished = getattr(content.input_transcription, "finished", None) is not False
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
                        bot_chunk = content.output_transcription.text
                        assistant_transcript_buf.append(bot_chunk)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": bot_chunk,
                            "role": "assistant",
                            "turn_id": turn_counter
                        })
                    if content.turn_complete:
                        if transcript_commit_task and not transcript_commit_task.done():
                            transcript_commit_task.cancel()
                        if input_transcription_finished:
                            await commit_streamed_turn()
                        else:
                            transcript_commit_task = asyncio.create_task(commit_streamed_turn(0.45))
                    elif (content.input_transcription and input_transcription_finished and
                          transcript_commit_task and not transcript_commit_task.done()):
                        transcript_commit_task.cancel()
                        await commit_streamed_turn()
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
            from google.genai import types

            client = get_gemini_client()

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
                    parts=[types.Part(text="""You are TONI, an expert cinema guide helping someone choose what to watch tonight. Your name is always TONI. Never refer to yourself as Charon, Gemini, or any internal voice or model identifier.

VOICE LENGTH CONTRACT: Give ONE short sentence per turn, usually 8-16 words, never more than 25 words. Ask only ONE concise question. Your speech is validated before playback, so long replies make the viewer wait in silence. Do not repeat the viewer's preferences, introduce yourself repeatedly, add preambles, or list all the information you need. Ask the next missing question only. Country and streaming services may be combined in one short question. Examples: "Hi! What are you in the mood for tonight?" / "Which country are you in, and what streaming services do you have?" / "Any runtime limits, or shall we find what fits?"

SPEAKER IDENTITY CONTRACT:
- Your name is TONI. You are the assistant.
- The person speaking to you is the VIEWER. The viewer's name is completely unknown unless they explicitly state "My name is [Name]".
- When the viewer greets you with "Hi Tony", "Hello TONI", or addresses you by name, they are speaking TO YOU. Never assume their name is Tony or TONI.
- You must NEVER address the viewer as "TONI" or "Tony". Never say "I'm here, TONI" or address the viewer as TONI.

Gather the minimum missing information naturally. Do not force a fixed question order. Ask only what is still needed to make a useful recommendation:
- The pace or mood / feeling they are in the mood for.
- Their country (UK or US) and what channels they have access to (e.g. Netflix, Prime Video, BBC iPlayer, Disney+, etc.) so availability can be guaranteed.
- Any runtime limits or genres they definitely want to rule out, and check if they are ready to see what fits.

MANDATORY RULES:
1. You must NEVER recommend, pitch, name, or invent film titles or shortlists to watch tonight. The application performs live search and displays recommendation cards visually on screen.
2. You may acknowledge films the viewer mentions as reference taste signals (e.g., 'Alien has great atmosphere; are you looking for sci-fi suspense, or something lighter?'), but never propose films for tonight.
3. When enough preferences and access details are known, ask exactly "Shall I search with these choices?" The application displays the choices for review. Only the viewer's affirmative reply to this question authorizes the application to search. Never treat yes to another question as search permission.
4. Always wait for the viewer to confirm they are ready before concluding intake. If the viewer provides multiple details up front, adapt smoothly without repeating answered questions.
5. If the viewer confirms the search, stop intake. The application switches to visual search and displays the shortlist. Never speak the results, review analysis, or another intake question after confirmation. If the viewer changes a preference, accept the change and ask "Shall I search with these choices?" again. If country or services are missing, ask for those first.""")]
                ),
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        silence_duration_ms=1200,
                        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    )
                )
            )
            connected_model = None
            live_models = [
                VOICE_MODEL,
                "gemini-2.5-flash-native-audio-latest",
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

            elif msg_type == "context_update":
                try:
                    updated = UserContext.model_validate(data.get("context", {}))
                    extraction_pipeline.update_context(updated)
                    session_ctx = updated
                except Exception:
                    await websocket.send_json({"type": "context_update_rejected"})

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

            elif msg_type == "finalize_turn":
                client_req_id = data.get("request_id", "")
                has_pending_audio = data.get("has_pending_audio", False)
                last_socket_turn_id = data.get("last_socket_turn_id", turn_counter)

                last_committed = extraction_pipeline.last_committed_turn_id if extraction_pipeline else 0

                if not has_pending_audio:
                    await websocket.send_json({
                        "type": "finalize_ack",
                        "request_id": client_req_id,
                        "target_turn_id": last_committed,
                        "status": "already_committed"
                    })
                else:
                    send_failed = False
                    if gemini_session:
                        from google.genai import types
                        try:
                            # Primary supported method: audio_stream_end
                            await gemini_session.send_realtime_input(audio_stream_end=True)
                        except Exception as ex1:
                            print(f"[*] Upstream finalize audio_stream_end notice: {ex1}", file=sys.stderr)
                            try:
                                # Fallback: silent burst to finalize activity detection
                                silent_pcm = bytes(6400)
                                await gemini_session.send_realtime_input(
                                    audio=types.Blob(data=silent_pcm, mime_type="audio/pcm;rate=16000")
                                )
                            except Exception as ex2:
                                print(f"[*] Upstream finalize silent burst failed: {ex2}", file=sys.stderr)
                                send_failed = True
                    else:
                        send_failed = True

                    if send_failed:
                        await websocket.send_json({
                            "type": "finalize_ack",
                            "request_id": client_req_id,
                            "target_turn_id": last_committed,
                            "status": "send_failed",
                            "error": "Upstream session input finalization failed"
                        })
                    else:
                        target_id = max(turn_counter, last_socket_turn_id, last_committed + 1)
                        await websocket.send_json({
                            "type": "finalize_ack",
                            "request_id": client_req_id,
                            "target_turn_id": target_id,
                            "status": "finalizing"
                        })

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

                    explicit_ready = check_explicit_search_intent(user_text)
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

        if transcript_commit_task:
            transcript_commit_task.cancel()
            await asyncio.gather(transcript_commit_task, return_exceptions=True)

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
    force_live_evidence: bool = Query(False, description="Whether to bypass cached review evidence"),
    defer_reviews: bool = Query(False, description="Return films first; enrich using /api/reviews"),
    live: Optional[bool] = Query(True, description="Enable live runtime candidate discovery and Gemini profiling"),
    _rate_limit: None = Depends(check_rate_limit)
) -> RecommendationResponse:
    """Generate personalized movie recommendations.
    
    Orchestrates live streaming availability, Parallel review search/extract,
    and dynamic fit scoring using canonical Film Profiles.
    """
    try:
        options = {"defer_reviews": True} if defer_reviews else {}
        response = rank_movies(
            context,
            force_live_evidence=force_live_evidence,
            use_live_pipeline=live,
            **options,
        )
        return response
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Something went wrong while I was finding your films. Try again, or adjust your choices."
        )


@app.post("/api/reviews", summary="Stream review updates for an existing shortlist")
async def review_updates(payload: ReviewRequest, _rate_limit: None = Depends(check_rate_limit)):
    async def lines():
        async for update in stream_review_updates(payload.films):
            yield json.dumps(update, ensure_ascii=False) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class VersionedStaticFiles(StaticFiles):
    """
    Subclass of StaticFiles that enforces immutable caching for verified,
    content-hashed assets, and revalidation headers for mutable/error assets.
    """
    RECOGNISED_HASH_PATTERN = re.compile(
        r"^(toni\.bundle|TONI_Design_Tokens|TONI_Mark_Aperture_Notch_Primary|TONI_Favicon_16px_Deep_Ink|TONI_Favicon|TONI_Apple_Touch_Icon_180px_Deep_Ink)\.[a-f0-9]{8}\.(css|svg|ico|png)$"
    )

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        filename = Path(path).name

        # If it's a 404 or any non-200 response, do NOT set immutable cache headers
        if response.status_code != 200:
            return response

        # If it's an HTML file or root, enforce no-cache
        if filename.endswith(".html") or filename == "":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        # If it is a recognised content-hashed asset, set immutable caching
        if self.RECOGNISED_HASH_PATTERN.match(filename):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"

        return response


# Serve static web demo UI if static directory exists
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"
if STATIC_DIR.exists():
    app.mount("/static", VersionedStaticFiles(directory=str(STATIC_DIR)), name="static")
    if ASSETS_DIR.exists():
        # Mount /assets specifically against static/assets per Amendment 4
        app.mount("/assets", VersionedStaticFiles(directory=str(ASSETS_DIR)), name="assets")

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


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["paths"]["/api/voice/live"] = {
        "get": {
            "summary": "Live Bidirectional Voice & Context WebSocket",
            "description": "WebSocket endpoint supporting real-time streaming audio (PCM 16-bit 16kHz input / 24kHz output), live speech recognition, barge-in detection, and real-time context extraction using Gemini Live.",
            "responses": {
                "101": {
                    "description": "Switching Protocols to WebSocket connection"
                }
            }
        }
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
