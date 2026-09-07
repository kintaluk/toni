"""
TONI - Centralized Gemini Client Factory
Enforces the Gemini Developer API with AI Studio-managed API key and vertexai=False.
Ensures discovery, profiling, structured preference extraction, and live voice
use consistent, validated configuration and never silently switch backends.
"""

import os
import sys
from typing import Optional
from google import genai

# Canonical Model Identifiers
DISCOVERY_MODEL = "gemini-3.6-flash"
PROFILING_MODEL_PRIMARY = "gemini-3.6-flash"
PROFILING_MODEL_FALLBACK = "gemini-3.1-pro-preview"
EXTRACTION_MODEL = "gemini-3.6-flash"
VOICE_MODEL = "gemini-3.1-flash-live-preview"

# Environment variables that can inadvertently trigger Vertex AI routing
_VERTEX_ENV_VARS = ["GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"]


def get_canonical_gemini_key() -> str:
    """Return the validated AI Studio-managed Gemini API key.

    Prioritizes GEMINI_API_KEY. Falls back to GOOGLE_API_KEY only if
    GEMINI_API_KEY is not set. Raises RuntimeError if neither is present.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not key.strip():
        key = os.environ.get("GOOGLE_API_KEY")
    if not key or not key.strip():
        raise RuntimeError(
            "Missing canonical Gemini API key. Please set GEMINI_API_KEY in your environment."
        )
    return key.strip()


def sanitize_gemini_environment() -> None:
    """Ensure environment flags do not trigger accidental Vertex AI auto-routing."""
    for v in _VERTEX_ENV_VARS:
        val = os.environ.get(v, "")
        if val.lower() in ("true", "1", "yes"):
            print(f"[*] Overriding conflicting {v}='{val}' to 'False' for Gemini Developer API.", file=sys.stderr)
            os.environ[v] = "False"


def get_gemini_client(api_key: Optional[str] = None) -> genai.Client:
    """Create and return a canonical Google GenAI client configured for Gemini Developer API.

    Guarantees:
    1. Direct Gemini Developer API usage (generativelanguage.googleapis.com).
    2. vertexai=False explicitly set.
    3. Conflicting GOOGLE_GENAI_USE_VERTEXAI and GOOGLE_GENAI_USE_ENTERPRISE sanitized.
    4. Explicit canonical API key passed.
    5. Never silently switches backends or falls back to Vertex AI.
    """
    sanitize_gemini_environment()
    canonical_key = api_key.strip() if api_key and api_key.strip() else get_canonical_gemini_key()
    return genai.Client(api_key=canonical_key, vertexai=False)
