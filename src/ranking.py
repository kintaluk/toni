"""
TONI Scoring and Ranking Engine

This module implements the core ranking logic for Tonight's Options, Narrowed Intelligently (TONI).
It filters candidates based on live streaming availability and other hard constraints,
applies contextual weighting to Film Profiles, calculates Personal Fit Scores,
and maps the final pool into presentation-ready recommendation roles (Best Fit, Strong Alternative, Worth a Stretch).
"""

import sys
import time
from typing import List, Dict, Any, Optional
from pathlib import Path

# Ensure local imports work
sys.path.append(str(Path(__file__).resolve().parent))
from contracts import (
    UserContext,
    Recommendation,
    RecommendationResponse,
    FilmMetadata,
    FilmProfile,
    EvidenceState,
    OutputRole,
    SignalType,
    SIGNAL_MAX_RUNTIME,
    SIGNAL_EXCLUDE_GENRE,
)
from availability import get_film_availability, AvailabilityStatus
from evidence import get_film_evidence


# --- CANONICAL FILM SEED POOL ---
# Full high-fidelity metadata, stable 6-dimension profiles, and consensus states for the 10 seed films
SEED_FILMS = [
    {
        "metadata": {
            "title": "Inception",
            "year": 2010,
            "director": "Christopher Nolan",
            "runtime_minutes": 148,
            "age_rating": "PG-13",
            "genres": ["Sci-Fi", "Thriller", "Action"]
        },
        "profile": {
            "story_and_writing": 4.5,
            "pacing_and_structure": 4.5,
            "performances": 4.3,
            "tone_and_emotional_character": ["mind-bending", "tense", "thrilling", "intellectual"],
            "craft_and_execution": 4.8,
            "accessibility_and_demandingness": 4.0
        },
        "evidence_state": "strong_agreement",
        "rationale": "Critics unanimously praised the exceptional direction, visuals, and complex plotting of Nolan's sci-fi epic."
    },
    {
        "metadata": {
            "title": "Babylon",
            "year": 2022,
            "director": "Damien Chazelle",
            "runtime_minutes": 189,
            "age_rating": "R",
            "genres": ["Drama", "Comedy"]
        },
        "profile": {
            "story_and_writing": 3.2,
            "pacing_and_structure": 2.8,
            "performances": 4.2,
            "tone_and_emotional_character": ["exhausting", "hedonistic", "chaotic", "unsettling"],
            "craft_and_execution": 4.6,
            "accessibility_and_demandingness": 4.2
        },
        "evidence_state": "meaningful_disagreement",
        "rationale": "Critics were sharply split, calling the film a chaotic masterpiece of craft but a bloated, exhausting narrative mess."
    },
    {
        "metadata": {
            "title": "The Godfather",
            "year": 1972,
            "director": "Francis Ford Coppola",
            "runtime_minutes": 175,
            "age_rating": "R",
            "genres": ["Crime", "Drama"]
        },
        "profile": {
            "story_and_writing": 5.0,
            "pacing_and_structure": 4.2,
            "performances": 5.0,
            "tone_and_emotional_character": ["majestic", "bleak", "intense", "dramatic"],
            "craft_and_execution": 4.9,
            "accessibility_and_demandingness": 3.8
        },
        "evidence_state": "strong_agreement",
        "rationale": "An undisputed landmark of cinema, lauded universally for masterclass writing, directing, and career-defining performances."
    },
    {
        "metadata": {
            "title": "Everything Everywhere All at Once",
            "year": 2022,
            "director": "Daniel Kwan, Daniel Scheinert",
            "runtime_minutes": 139,
            "age_rating": "R",
            "genres": ["Sci-Fi", "Comedy", "Adventure"]
        },
        "profile": {
            "story_and_writing": 4.4,
            "pacing_and_structure": 4.6,
            "performances": 4.8,
            "tone_and_emotional_character": ["absurdist", "warm", "frenetic", "emotional"],
            "craft_and_execution": 4.7,
            "accessibility_and_demandingness": 3.5
        },
        "evidence_state": "strong_agreement",
        "rationale": "Acclaimed as a wildly original multiverse adventure grounded in deeply touching family drama and stellar performances."
    },
    {
        "metadata": {
            "title": "Spirited Away",
            "year": 2001,
            "director": "Hayao Miyazaki",
            "runtime_minutes": 125,
            "age_rating": "PG",
            "genres": ["Anime", "Fantasy", "Adventure"]
        },
        "profile": {
            "story_and_writing": 4.8,
            "pacing_and_structure": 4.3,
            "performances": 4.6,
            "tone_and_emotional_character": ["magical", "warm", "wondrous", "gentle"],
            "craft_and_execution": 5.0,
            "accessibility_and_demandingness": 2.5
        },
        "evidence_state": "strong_agreement",
        "rationale": "Universally cherished for its breathtaking hand-drawn animation, profound fairytale mythology, and compassionate storytelling."
    },
    {
        "metadata": {
            "title": "Pulp Fiction",
            "year": 1994,
            "director": "Quentin Tarantino",
            "runtime_minutes": 154,
            "age_rating": "R",
            "genres": ["Crime", "Drama", "Thriller"]
        },
        "profile": {
            "story_and_writing": 4.9,
            "pacing_and_structure": 4.4,
            "performances": 4.8,
            "tone_and_emotional_character": ["stylized", "funny", "cool", "violent"],
            "craft_and_execution": 4.6,
            "accessibility_and_demandingness": 3.6
        },
        "evidence_state": "strong_agreement",
        "rationale": "Hailed as a highly influential post-modern classic, praised for its brilliant non-linear screenplay and iconic pop dialogue."
    },
    {
        "metadata": {
            "title": "Parasite",
            "year": 2019,
            "director": "Bong Joon-ho",
            "runtime_minutes": 132,
            "age_rating": "R",
            "genres": ["Thriller", "Drama", "Comedy"]
        },
        "profile": {
            "story_and_writing": 4.9,
            "pacing_and_structure": 4.7,
            "performances": 4.7,
            "tone_and_emotional_character": ["tense", "satirical", "unsettling", "tragic"],
            "craft_and_execution": 4.8,
            "accessibility_and_demandingness": 3.5
        },
        "evidence_state": "strong_agreement",
        "rationale": "A thriller masterpiece universally lauded for sharp social satire, unpredictable pacing, and impeccable directorial design."
    },
    {
        "metadata": {
            "title": "The Dark Knight",
            "year": 2008,
            "director": "Christopher Nolan",
            "runtime_minutes": 152,
            "age_rating": "PG-13",
            "genres": ["Action", "Crime", "Drama"]
        },
        "profile": {
            "story_and_writing": 4.6,
            "pacing_and_structure": 4.5,
            "performances": 4.9,
            "tone_and_emotional_character": ["bleak", "tense", "gritty", "intense"],
            "craft_and_execution": 4.7,
            "accessibility_and_demandingness": 3.2
        },
        "evidence_state": "strong_agreement",
        "rationale": "Acclaimed as a genre-defining crime drama, singled out for Heath Ledger's legendary performance and its intense, tragic realism."
    },
    {
        "metadata": {
            "title": "Barbie",
            "year": 2023,
            "director": "Greta Gerwig",
            "runtime_minutes": 114,
            "age_rating": "PG-13",
            "genres": ["Comedy", "Fantasy"]
        },
        "profile": {
            "story_and_writing": 4.1,
            "pacing_and_structure": 4.2,
            "performances": 4.5,
            "tone_and_emotional_character": ["funny", "colorful", "warm", "satirical"],
            "craft_and_execution": 4.5,
            "accessibility_and_demandingness": 2.2
        },
        "evidence_state": "strong_agreement",
        "rationale": "Acclaimed for its witty satirical screenplay, dazzling colorful production design, and engaging performances."
    },
    {
        "metadata": {
            "title": "Nosferatu",
            "year": 1922,
            "director": "F.W. Murnau",
            "runtime_minutes": 94,
            "age_rating": "PG",
            "genres": ["Horror", "Fantasy"]
        },
        "profile": {
            "story_and_writing": 4.0,
            "pacing_and_structure": 3.5,
            "performances": 4.1,
            "tone_and_emotional_character": ["unsettling", "bleak", "eerie", "historic"],
            "craft_and_execution": 4.7,
            "accessibility_and_demandingness": 4.5
        },
        "evidence_state": "strong_agreement",
        "rationale": "A legendary silent horror pioneer, universally studied and respected for its eerie expressionist atmosphere and shadow craft."
    }
]


def calculate_personal_fit_score(profile: FilmProfile, metadata: FilmMetadata, context: UserContext) -> int:
    """Calculates a personalized compatibility score (0-100) for a movie,

    matching the Film Profile dimensions against soft preferences in the UserContext.
    """
    score = 50  # Lower baseline to allow preferences to drive results
    signals = context.tonight_signals + context.persistent_taste

    user_has_tones = False
    tone_matched = False

    for sig in signals:
        if sig.signal_type == SignalType.HARD_CONSTRAINT:
            continue

        name = sig.name.lower().strip()
        val = sig.value

        # 1. Pacing Appetite
        if name == "pacing":
            pacing_score = profile.pacing_and_structure
            if val == "slow":
                if pacing_score <= 2.5:
                    score += 20
                elif pacing_score >= 4.0:
                    score -= 20
            elif val == "brisk":
                if pacing_score >= 4.0:
                    score += 20
                elif pacing_score <= 2.5:
                    score -= 20
            elif val == "measured":
                if 2.5 < pacing_score < 4.0:
                    score += 15

        # 2. Demandingness Appetite
        elif name == "demandingness":
            try:
                target_dem = float(val)
                diff = abs(profile.accessibility_and_demandingness - target_dem)
                # Max 20 points, deduct 15 points per unit of difference
                score += int(20 - (diff * 15))
            except (ValueError, TypeError):
                pass

        # 3. Tone Matching
        elif name == "tone":
            user_has_tones = True
            user_tones = [val] if isinstance(val, str) else list(val)
            tone_bonus = 0
            for tone in user_tones:
                if tone.lower().strip() in [t.lower() for t in profile.tone_and_emotional_character]:
                    tone_bonus += 25
                    tone_matched = True
            score += min(30, tone_bonus)

        # 4. Preferred Genres
        elif name == "preferred_genres":
            user_genres = [val] if isinstance(val, str) else list(val)
            for g in user_genres:
                if g.lower().strip() in [m_g.lower() for m_g in metadata.genres]:
                    score += 15

    # Tone mismatch penalty
    if user_has_tones and not tone_matched:
        score -= 25

    # Artistic bonuses (Max +10 total)
    craft_bonus = max(0, int((profile.craft_and_execution - 3.0) * 3))  # Max 6
    story_bonus = max(0, int((profile.story_and_writing - 3.0) * 2))    # Max 4
    score += (craft_bonus + story_bonus)

    return max(0, min(100, score))


def generate_concise_reason(title: str, score: int, profile: FilmProfile, context: UserContext) -> str:
    """Generates a warm, natural, and highly specific explanation of why a film matches tonight's context."""
    signals = context.tonight_signals + context.persistent_taste
    pacing_req = next((s.value for s in signals if s.name == "pacing"), None)
    tone_req = next((s.value for s in signals if s.name == "tone"), None)

    reasons = []
    tone_matched = False

    if tone_req:
        tone_str = tone_req if isinstance(tone_req, str) else tone_req[0]
        if tone_str.lower() in [t.lower() for t in profile.tone_and_emotional_character]:
            reasons.append(f"perfectly captures the {tone_str.lower()} vibe you are looking for")
            tone_matched = True

    if pacing_req:
        if pacing_req == "brisk" and profile.pacing_and_structure >= 4.0:
            reasons.append("offers a briskly paced, highly engaging structure")
        elif pacing_req == "slow" and profile.pacing_and_structure <= 2.5:
            reasons.append("delivers a beautifully measured, slow-burning narrative space")

    if not reasons:
        # Fallback reasons based on peak dimensions
        if profile.craft_and_execution >= 4.5:
            reasons.append("boasts incredible directorial craft and gorgeous cinematography")
        if profile.performances >= 4.5:
            reasons.append("presents standout, emotionally resonant actor performances")

    # Construct reason prefix
    if reasons:
        reason_suffix = " and ".join(reasons)
        start_phrase = f"This film {reason_suffix}"
    else:
        start_phrase = f"{title} stands as a well-rounded and crafted cinematic option"

    # Decide fit description based on score and tone matching
    if tone_req and not tone_matched:
        # Tone mismatch
        if score >= 60:
            fit_phrase = "making it a highly compelling alternative despite not matching your exact mood preferences tonight."
        else:
            fit_phrase = "offering a different cinematic flavor if you are open to shifting your mood tonight."
    else:
        if score >= 80:
            fit_phrase = "making it an exceptional, top-tier fit for your evening!"
        elif score >= 60:
            fit_phrase = "making it a highly promising option for your evening."
        elif score >= 40:
            fit_phrase = "representing a solid alternative choice for tonight."
        else:
            fit_phrase = "offering a more casual, unexpected option if you're in the mood for a detour."

    return f"{start_phrase}, {fit_phrase}"


def generate_stretch_signal(profile: FilmProfile, context: UserContext) -> Optional[str]:
    """Determines if a film qualifies as an artistic stretch recommendation.

    Returns the stretch reasoning if valid, else None.
    """
    if profile.craft_and_execution < 4.5:
        return None

    signals = context.tonight_signals + context.persistent_taste
    demanding_val = None
    for s in signals:
        if s.name == "demandingness":
            try:
                demanding_val = float(s.value)
                break
            except (ValueError, TypeError):
                pass

    if demanding_val is not None:
        # If user wants very easy viewing (demandingness <= 2.5) but the film is highly demanding (demandingness >= 4.0)
        if demanding_val <= 2.5 and profile.accessibility_and_demandingness >= 4.0:
            return f"While more demanding ({profile.accessibility_and_demandingness}/5) than your preferred easy vibe, its masterful directing represents an incredibly rewarding stretch."

    return None


def rank_movies(context: UserContext, force_live_evidence: bool = True) -> RecommendationResponse:
    """Ties the entire TONI pipeline together:

    1. Checks live availability for all seed pool movies.
    2. Filters out ineligible movies (unavailable/unverified, or violating runtime/genre exclusions).
    3. Calculates Personal Fit Scores.
    4. Evaluates stretch suitability.
    5. Assigns presentation roles (Best Fit, Strong Alternative, Worth a Stretch).
    6. Attaches runtime Parallel Search/Extract review evidence and URLs.
    7. Returns up to 7 sorted, validated recommendations.
    """
    eligible_recommendations: List[Recommendation] = []

    # Combine signals from both tonight's session and persistent taste
    all_signals = context.tonight_signals + context.persistent_taste

    # Get hard constraints from combined signals
    max_runtime_signal = next(
        (s for s in all_signals if s.name == SIGNAL_MAX_RUNTIME and s.signal_type == SignalType.HARD_CONSTRAINT),
        None
    )
    max_runtime = int(max_runtime_signal.value) if max_runtime_signal is not None else None

    exclude_genres = []
    for s in all_signals:
        if s.name == SIGNAL_EXCLUDE_GENRE and s.signal_type == SignalType.HARD_CONSTRAINT:
            if isinstance(s.value, list):
                exclude_genres.extend(s.value)
            elif isinstance(s.value, str):
                exclude_genres.append(s.value)
    exclude_genres_lower = [g.lower().strip() for g in exclude_genres]

    unverified_excluded_count = 0

    # Process all seed pool films
    for seed in SEED_FILMS:
        meta_dict = seed["metadata"]
        prof_dict = seed["profile"]

        metadata = FilmMetadata(**meta_dict)
        profile = FilmProfile(**prof_dict)

        # --- HARD CONSTRAINT 1: LIVE AVAILABILITY ---
        avail_res = get_film_availability(metadata.title, metadata.year, context)
        if avail_res.status != AvailabilityStatus.AVAILABLE:
            if avail_res.status == AvailabilityStatus.UNVERIFIED:
                unverified_excluded_count += 1
            continue  # Exclude unavailable or unverified titles

        # --- HARD CONSTRAINT 2: RUNTIME LIMITS ---
        if max_runtime is not None and metadata.runtime_minutes > max_runtime:
            continue

        # --- HARD CONSTRAINT 3: GENRE EXCLUSIONS ---
        if any(g.lower().strip() in exclude_genres_lower for g in metadata.genres):
            continue

        # --- SOFT SCORING & WEIGHTING ---
        fit_score = calculate_personal_fit_score(profile, metadata, context)
        stretch_reason = generate_stretch_signal(profile, context)

        rec = Recommendation(
            metadata=metadata,
            profile=profile,
            evidence_state=EvidenceState(seed["evidence_state"]),
            availability=avail_res,
            personal_fit_score=fit_score,
            stretch_signal=stretch_reason,
            role=OutputRole.RANKED_ADDITIONAL,  # Temporarily assigned, mapped in next step
            concise_reason=generate_concise_reason(metadata.title, fit_score, profile, context)
        )
        eligible_recommendations.append(rec)

    # If no movies are available, return empty response
    if not eligible_recommendations:
        return RecommendationResponse(recommendations=[], unverified_excluded_count=unverified_excluded_count)

    # Sort primarily by Personal Fit Score descending
    eligible_recommendations.sort(key=lambda r: r.personal_fit_score, reverse=True)

    final_recommendations: List[Recommendation] = []

    # 1. BEST FIT (The highest-scoring matching film)
    best_fit_rec = eligible_recommendations[0]
    best_fit_rec.role = OutputRole.BEST_FIT
    final_recommendations.append(best_fit_rec)

    # 2. STRONG ALTERNATIVE (Next highest scoring that is deliberately distinct)
    # To satisfy "deliberately distinct", we seek the next highest-scoring candidate
    # that doesn't share any of the Best Fit's primary genres.
    strong_alt_rec = None
    best_genres = set(best_fit_rec.metadata.genres)

    for rec in eligible_recommendations[1:]:
        if not set(rec.metadata.genres).intersection(best_genres):
            strong_alt_rec = rec
            break

    # Fallback to second-highest if no completely distinct genre exists
    if not strong_alt_rec and len(eligible_recommendations) > 1:
        strong_alt_rec = eligible_recommendations[1]

    if strong_alt_rec:
        strong_alt_rec.role = OutputRole.STRONG_ALTERNATIVE
        final_recommendations.append(strong_alt_rec)

    # 3. WORTH A STRETCH (A high-craft film representing an artistic pivot)
    stretch_rec = None
    used_titles = {r.metadata.title for r in final_recommendations}

    for rec in eligible_recommendations:
        if rec.metadata.title in used_titles:
            continue
        if rec.stretch_signal is not None:
            stretch_rec = rec
            break

    if stretch_rec:
        stretch_rec.role = OutputRole.WORTH_A_STRETCH
        final_recommendations.append(stretch_rec)

    # 4. RANKED ADDITIONAL (Append remaining sorted candidates up to 7 total results)
    used_titles = {r.metadata.title for r in final_recommendations}
    for rec in eligible_recommendations:
        if len(final_recommendations) >= 7:
            break
        if rec.metadata.title in used_titles:
            continue
        rec.role = OutputRole.RANKED_ADDITIONAL
        final_recommendations.append(rec)

    # --- 5. ATTACH RUNTIME PARALLEL SEARCH & EXTRACT EVIDENCE ---
    evidence_start_time = time.time()
    TOTAL_EVIDENCE_BUDGET_SEC = 15.0

    for rec in final_recommendations:
        elapsed = time.time() - evidence_start_time
        if elapsed >= TOTAL_EVIDENCE_BUDGET_SEC:
            print(f"[WARNING] Evidence lookup time budget exceeded. Skipping remaining films.", file=sys.stderr)
            break

        try:
            remaining_budget = TOTAL_EVIDENCE_BUDGET_SEC - elapsed
            film_timeout = min(8.0, remaining_budget)
            if film_timeout <= 1.0:
                print(f"[WARNING] Not enough time budget left for {rec.metadata.title}. Skipping.", file=sys.stderr)
                continue

            evidence = get_film_evidence(
                title=rec.metadata.title,
                year=rec.metadata.year,
                director=rec.metadata.director,
                force_live=force_live_evidence,
                timeout=film_timeout,
            )
            if evidence:
                rec.evidence_sources = [
                    item["url"] for item in evidence if isinstance(item, dict) and "url" in item
                ]
        except Exception as e:
            print(f"[ERROR] Evidence lookup failed for {rec.metadata.title}: {str(e)}", file=sys.stderr)

    return RecommendationResponse(
        recommendations=final_recommendations,
        unverified_excluded_count=unverified_excluded_count
    )
