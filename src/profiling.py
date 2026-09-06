"""
TONI Film Profiling Service

This module leverages the Gemini 2.5 Pro model to generate evidence-led
six-dimension Film Profiles and Evidence State metadata from extracted review content,
complying with the canonical TONI product contract.
"""

import json
import os
import sys
from typing import List, Dict, Any, Tuple
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure local imports work
sys.path.append(str(Path(__file__).resolve().parent))
from contracts import FilmProfile, EvidenceState

load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

# We use the recommended gemini-pro-latest model for detailed critical reasoning
MODEL_NAME = "gemini-pro-latest"


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
        reviews_block += f"### Review Source {i+1}\nURL: {r['url']}\nContent: {r['content']}\n\n"

    return f"""You are creating a canonical Film Profile and Evidence State for the {year} movie "{title}" directed by {director}.
Base your evaluation ONLY on the following extracted critical reviews. Paraphrase all evaluations in your own words, maintaining copyright constraints (~6 words max exact-match limit).

### EXCLUSION DIRECTIVE
Do not use prior training knowledge or outside details (such as box office, awards, or other reviews). If the reviews provided do not touch upon a dimension, evaluate it as a neutral 3.0.

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

_PROFILE_CACHE: Dict[str, Tuple[FilmProfile, EvidenceState, str]] = {}
_PROFILE_CACHE_LOCK = threading.RLock()


def _compute_profile_cache_key(title: str, year: int, director: str, reviews: List[Dict[str, Any]]) -> str:
    serialized = json.dumps(reviews, sort_keys=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{title.lower()}:{year}:{director.lower()}:{content_hash}:v1"


def generate_film_profile(
    title: str,
    year: int,
    director: str,
    reviews: List[Dict[str, Any]]
) -> Tuple[FilmProfile, EvidenceState, str]:
    """Generates the FilmProfile, EvidenceState, and consensus rationale for a movie using Gemini 2.5 Pro.

    Falls back to a robust mock generator if reviews list is empty or API keys are missing.
    """
    cache_key = _compute_profile_cache_key(title, year, director, reviews)
    with _PROFILE_CACHE_LOCK:
        if cache_key in _PROFILE_CACHE:
            return _PROFILE_CACHE[cache_key]

    # Fallback/Mock Generator for our seed films if no reviews are supplied or API key is missing
    has_gemini_key = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY"))
    if not reviews or not has_gemini_key or os.environ.get("TONI_MOCK_GEMINI_LIVE") == "true":
        # Local mock profiles for our main seed films to keep integration testing fast and robust
        title_lower = title.lower().strip()
        if "inception" in title_lower:
            return (
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
            return (
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
        else:
            # General fallback profile
            return (
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

    # Live Gemini Call
    from google import genai
    from google.genai import types

    client = genai.Client()
    prompt = build_profiling_prompt(title, year, director, reviews)

    response = None
    last_exception = None
    for model_candidate in ["gemini-pro-latest", "gemini-flash-latest", "gemini-2.5-pro"]:
        try:
            response = client.models.generate_content(
                model=model_candidate,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,  # Temperature 0 for deterministic critical evaluation
                    response_mime_type="application/json",
                    response_schema=GeminiProfileSchema,
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
        _PROFILE_CACHE[cache_key] = result
    return result
