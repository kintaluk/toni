"""
TONI Film Profiling Service

This module leverages the Gemini 2.5 Pro model to generate evidence-led
six-dimension Film Profiles and Evidence State metadata from extracted review content,
complying with the canonical TONI product contract.
"""

import json
import os
import sys
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure local imports work
sys.path.append(str(Path(__file__).resolve().parent))
from contracts import FilmProfile, EvidenceState
from gemini_client import get_gemini_client, PROFILING_MODEL_PRIMARY

load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

class GeminiProfileSchema(BaseModel):
    """Temporary structured output schema for Gemini's profile generation."""
    story_and_writing: float = Field(
        description="Score from 1.0 to 5.0 reflecting narrative coherence, screenplay, dialogue, and characters."
    )
    pacing_and_structure: float = Field(
        description="Score from 1.0 to 5.0 reflecting rhythm, momentum, editing, and whether brisk or slow/uneven."
    )
    performances: float = Field(
        description="Score from 1.0 to 5.0 reflecting acting quality, chemistry, and credibility."
    )
    tone_and_emotional_character: List[str] = Field(
        description="3-6 precise descriptive adjectives capturing what the film feels like (e.g., warm, tense, bleak)."
    )
    craft_and_execution: float = Field(
        description="Score from 1.0 to 5.0 reflecting direction, cinematography, production design, and music."
    )
    accessibility_and_demandingness: float = Field(
        description="Score from 1.0 to 5.0 reflecting attention, patience, or emotional commitment asked of the viewer."
    )
    evidence_state: str = Field(
        description="Must be exactly one of: strong_agreement, meaningful_disagreement, sparse_evidence, mainly_official_factual."
    )
    consensus_rationale: str = Field(
        description="One-sentence paraphrased explanation of the critical consensus and any notable disagreement (~6 words exact-match limit)."
    )


def build_profiling_prompt(title: str, year: int, director: str, reviews: List[Dict[str, Any]]) -> str:
    """Constructs the prompt for Gemini, containing raw reviews and anchoring definitions."""
    reviews_block = ""
    for i, r in enumerate(reviews):
        coverage = "partial review excerpts" if r.get("retrieval_kind") == "extract_excerpts" else "extracted review content"
        reviews_block += f"### Review Source {i+1}\nURL: {r['url']}\nCoverage: {coverage}\nContent: {r['content']}\n\n"

    return f"""You are creating a canonical Film Profile and Evidence State for the {year} movie "{title}" directed by {director}.
Base your evaluation ONLY on the following extracted critical reviews. Paraphrase all evaluations in your own words, maintaining copyright constraints (~6 words max exact-match limit).

### EXCLUSION DIRECTIVE
Do not use prior training knowledge or outside details (such as box office, awards, or other reviews). If the reviews provided do not touch upon a dimension, evaluate it as a neutral 3.0.
Partial excerpts do not establish the full review's verdict. Judge only what they actually say. A single independent review must be sparse_evidence, not strong_agreement.

### 6-DIMENSION FILMPROFILE REFERENCE ANCHORS:
1. Story and writing (1.0 = incoherent, confused; 3.0 = average, mixed; 5.0 = exceptional narrative coherence and characters).
2. Pacing and structure (1.0 = serious drag, bloated; 3.0 = moderate pacing; 5.0 = exceptionally effective rhythm and momentum).
3. Performances (1.0 = weak, unconvincing acting; 3.0 = adequate; 5.0 = career-best or standout ensemble chemistry).
4. Tone and emotional character: List 3 to 6 descriptive adjectives (e.g., warm, bleak, funny, tense, unsettling, majestic).
5. Craft and execution (1.0 = poor technical execution; 3.0 = standard craft; 5.0 = exceptional cinematography, music, or direction).
6. Accessibility and demandingness (1.0 = very easy, light viewing; 3.0 = moderate commitment; 5.0 = highly demanding, slow-paced, or emotionally heavy).

### EVIDENCE STATE CRITERIA:
- strong_agreement: Critics broadly agree on overall film quality and style.
- meaningful_disagreement: Critics are split, showing a clear division in opinions.
- sparse_evidence: Very few reviews are available to judge consensus.
- mainly_official_factual: Reviews are primarily factual/promotional rather than critical.

Reviews:
{reviews_block}
"""


import hashlib
import threading
import time

_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}
_PROFILE_CACHE_LOCK = threading.RLock()
_PROFILE_IN_FLIGHT: Dict[str, threading.Event] = {}
_PROFILE_MAX_ENTRIES = 100
_PROFILE_TTL_SEC = 86400  # 24 hours
_PROFILE_SCHEMA_VERSION = "v2"


def _compute_profile_cache_key(title: str, year: int, director: str, reviews: List[Dict[str, Any]]) -> str:
    serialized = json.dumps(reviews, sort_keys=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{title.lower().strip()}:{year}:{director.lower().strip()}:{content_hash}:{_PROFILE_SCHEMA_VERSION}"


def generate_film_profile(
    title: str,
    year: int,
    director: str,
    reviews: List[Dict[str, Any]],
    deadline: Optional[float] = None,
    client: Any = None,
) -> Tuple[FilmProfile, EvidenceState, str]:
    """Generates the FilmProfile, EvidenceState, and consensus rationale for a movie using Gemini 2.5 Pro.

    Synthetic fixtures are enabled only by the explicit offline test flag.
    Results are cached with a 24-hour TTL and bounded size, with in-flight request deduplication.
    """
    cache_key = _compute_profile_cache_key(title, year, director, reviews)
    if os.environ.get("TONI_MOCK_GEMINI_LIVE") != "true":
        if not reviews:
            raise ValueError("No usable review evidence; a live profile cannot be synthesized")
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            raise ValueError("Review synthesis is not configured")
    with _PROFILE_CACHE_LOCK:
        if cache_key in _PROFILE_CACHE:
            entry = _PROFILE_CACHE[cache_key]
            if time.time() - entry.get("timestamp", 0) < _PROFILE_TTL_SEC:
                return entry["result"]
            else:
                del _PROFILE_CACHE[cache_key]

        if cache_key in _PROFILE_IN_FLIGHT:
            evt = _PROFILE_IN_FLIGHT[cache_key]
            is_leader = False
        else:
            evt = threading.Event()
            _PROFILE_IN_FLIGHT[cache_key] = evt
            is_leader = True

    if not is_leader:
        wait_time = min(15.0, max(0.5, deadline - time.monotonic())) if deadline else 15.0
        evt.wait(timeout=wait_time)
        with _PROFILE_CACHE_LOCK:
            if cache_key in _PROFILE_CACHE:
                return _PROFILE_CACHE[cache_key]["result"]
        raise TimeoutError("Profile is still being generated")

    try:
        # Explicit offline test fixtures; unavailable production integrations fail above.
        has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        if not reviews or not has_gemini_key or os.environ.get("TONI_MOCK_GEMINI_LIVE") == "true":
            # Local mock profiles for our main seed films to keep integration testing fast and robust
            title_lower = title.lower().strip()
            if "inception" in title_lower:
                res = (
                    FilmProfile(
                        story_and_writing=4.5,
                        pacing_and_structure=4.5,
                        performances=4.3,
                        tone_and_emotional_character=["mind-bending", "tense", "thrilling", "intellectual"],
                        craft_and_execution=4.8,
                        accessibility_and_demandingness=4.0,
                    ),
                    EvidenceState.STRONG_AGREEMENT,
                    "Critics broadly praised the direction, visual design, and intricate plotting of Nolan's sci-fi film."
                )
            elif "babylon" in title_lower:
                res = (
                    FilmProfile(
                        story_and_writing=3.2,
                        pacing_and_structure=2.8,
                        performances=4.2,
                        tone_and_emotional_character=["exhausting", "hedonistic", "chaotic", "unsettling"],
                        craft_and_execution=4.6,
                        accessibility_and_demandingness=4.2,
                    ),
                    EvidenceState.MEANINGFUL_DISAGREEMENT,
                    "Critics were divided, noting ambitious craft alongside a dense and demanding narrative structure."
                )
            elif "dark knight" in title_lower:
                res = (
                    FilmProfile(
                        story_and_writing=4.8,
                        pacing_and_structure=4.3,
                        performances=4.8,
                        tone_and_emotional_character=["dark", "intense", "brooding", "bleak", "violent"],
                        craft_and_execution=4.9,
                        accessibility_and_demandingness=3.8,
                    ),
                    EvidenceState.STRONG_AGREEMENT,
                    "Critics universally acclaimed the gripping direction, moral complexity, and iconic performances in Nolan's superhero crime drama."
                )
            else:
                res = (
                    FilmProfile(
                        story_and_writing=3.5,
                        pacing_and_structure=3.5,
                        performances=3.5,
                        tone_and_emotional_character=["warm", "engaging"],
                        craft_and_execution=3.5,
                        accessibility_and_demandingness=3.0,
                    ),
                    EvidenceState.SPARSE_EVIDENCE,
                    "Limited critical reviews are available; the film displays standard storytelling and execution."
                )
            with _PROFILE_CACHE_LOCK:
                _PROFILE_CACHE[cache_key] = {"result": res, "timestamp": time.time()}
            return res

        # Live Gemini Call via centralized factory (Gemini Developer API, vertexai=False)
        from google.genai import types

        client = client or get_gemini_client()
        prompt = build_profiling_prompt(title, year, director, reviews)

        response = None
        last_exception = None
        for idx, model_candidate in enumerate([PROFILING_MODEL_PRIMARY]):
            # Gemini Developer API requires a minimum deadline of 10s (10000ms).
            # If remaining allocated deadline cannot accommodate this constraint, skip upstream call.
            rem_sec = deadline - time.monotonic() if deadline else 12.0
            if rem_sec < 10.0:
                print(f"[*] Insufficient deadline budget for Gemini profiling '{title}' ({rem_sec:.2f}s < 10.0s). Skipping upstream call.", file=sys.stderr)
                break
            try:
                cur_timeout_ms = 10000
                response = client.models.generate_content(
                    model=model_candidate,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,  # Temperature 0 for deterministic critical evaluation
                        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        max_output_tokens=2048,
                        response_mime_type="application/json",
                        response_schema=GeminiProfileSchema,
                        http_options=types.HttpOptions(
                            timeout=cur_timeout_ms,
                            retry_options=types.HttpRetryOptions(attempts=1)
                        ),
                    ),
                )
                if response and response.parsed:
                    break
            except Exception as e:
                last_exception = e
                print(f"[!] Profiling candidate {model_candidate} failed for '{title}': {e}", file=sys.stderr)
                continue

        if not response or not response.parsed:
            err_msg = f"Gemini profiling failed to return parseable response schema for '{title}' (last model exception: {last_exception})."
            raise RuntimeError(err_msg)

        data: GeminiProfileSchema = response.parsed

        # Convert the string to the EvidenceState enum safely
        try:
            ev_state = EvidenceState(data.evidence_state)
        except ValueError:
            ev_state = EvidenceState.SPARSE_EVIDENCE

        profile = FilmProfile(
            story_and_writing=max(1.0, min(5.0, data.story_and_writing)),
            pacing_and_structure=max(1.0, min(5.0, data.pacing_and_structure)),
            performances=max(1.0, min(5.0, data.performances)),
            tone_and_emotional_character=data.tone_and_emotional_character,
            craft_and_execution=max(1.0, min(5.0, data.craft_and_execution)),
            accessibility_and_demandingness=max(1.0, min(5.0, data.accessibility_and_demandingness)),
        )

        result = (profile, ev_state, data.consensus_rationale)
        with _PROFILE_CACHE_LOCK:
            _PROFILE_CACHE[cache_key] = {"result": result, "timestamp": time.time()}
            if len(_PROFILE_CACHE) > _PROFILE_MAX_ENTRIES:
                oldest = min(_PROFILE_CACHE.keys(), key=lambda k: _PROFILE_CACHE[k].get("timestamp", 0))
                del _PROFILE_CACHE[oldest]
        return result
    finally:
        if is_leader:
            with _PROFILE_CACHE_LOCK:
                _PROFILE_IN_FLIGHT.pop(cache_key, None)
            evt.set()
