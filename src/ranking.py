"""
TONI Scoring and Ranking Engine

This module implements the core ranking logic for Tonight's Options, Narrowed Intelligently (TONI).
It filters candidates based on live streaming availability and other hard constraints,
applies contextual weighting to Film Profiles, calculates Personal Fit Scores,
and maps the final pool into presentation-ready recommendation roles (Best Fit, Strong Alternative, Worth a Stretch).
"""

import os
import sys
import time
from datetime import date
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure environment variables are loaded
load_dotenv(override=True)
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("false", "0"):
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

# Ensure local imports work
sys.path.append(str(Path(__file__).resolve().parent))
from gemini_client import get_gemini_client, DISCOVERY_MODEL
from contracts import (
    UserContext,
    Recommendation,
    RecommendationResponse,
    FilmMetadata,
    FilmProfile,
    EvidenceState,
    AvailabilityResult,
    OutputRole,
    SignalType,
    SIGNAL_MAX_RUNTIME,
    SIGNAL_EXCLUDE_GENRE,
)
from availability import (
    get_film_availability,
    AvailabilityStatus,
    get_film_poster_url,
    get_film_trailer_url,
)
from evidence import get_film_evidence
from profiling import generate_film_profile
from runtime_budget import UPSTREAM_EXECUTOR, completed_until, call_until, remaining


class DiscoveredCandidate(BaseModel):
    """Schema for candidate films generated dynamically via Gemini Flash."""
    title: str = Field(description="Exact movie title")
    year: int = Field(description="Release year as integer (e.g. 2019)")
    director: str = Field(description="Director name")
    runtime_minutes: int = Field(description="Runtime in minutes as integer")
    age_rating: str = Field(default="15", description="Age rating, e.g., PG, PG-13, R, 15")
    genres: List[str] = Field(description="List of genre strings, e.g., ['Drama', 'Thriller']")


class DiscoveredCandidateList(BaseModel):
    """Container schema for the candidate list."""
    candidates: List[DiscoveredCandidate] = Field(
        description="List of 15 to 20 well-regarded, acclaimed films matching user criteria"
    )


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
            "genres": ["Sci-Fi", "Thriller", "Action"],
            "poster_url": "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=YoHD9XEInc0"
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
        "rationale": "Critics unanimously praised the exceptional direction, visuals, and complex plotting of Nolan's sci-fi epic.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2010/jul/15/inception-film-review",
            "https://www.rogerebert.com/reviews/inception-2010",
            "https://www.empireonline.com/movies/reviews/inception-review/"
        ]
    },
    {
        "metadata": {
            "title": "Babylon",
            "year": 2022,
            "director": "Damien Chazelle",
            "runtime_minutes": 189,
            "age_rating": "R",
            "genres": ["Drama", "Comedy"],
            "poster_url": "https://image.tmdb.org/t/p/w500/wjOHjWCUE0YzDiEzKv8AfqHj3ir.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=5muIQDEmXkU"
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
        "rationale": "Critics were sharply split, calling the film a chaotic masterpiece of craft but a bloated, exhausting narrative mess.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2023/jan/22/babylon-review-damien-chazelle-brad-pitt-margot-robbie",
            "https://www.rogerebert.com/reviews/babylon-movie-review-2022",
            "https://www.empireonline.com/movies/reviews/babylon/"
        ]
    },
    {
        "metadata": {
            "title": "The Godfather",
            "year": 1972,
            "director": "Francis Ford Coppola",
            "runtime_minutes": 175,
            "age_rating": "R",
            "genres": ["Crime", "Drama"],
            "poster_url": "https://image.tmdb.org/t/p/w500/3bhkrj58Vtu7enYsRolD1fZdja1.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=UaVTIH8mujA"
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
        "rationale": "An undisputed landmark of cinema, lauded universally for masterclass writing, directing, and career-defining performances.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2022/feb/25/the-godfather-review-francis-ford-coppola",
            "https://www.rogerebert.com/reviews/great-movie-the-godfather-1972",
            "https://www.bfi.org.uk/sight-and-sound/reviews/godfather-francis-ford-coppola-50-anniversary"
        ]
    },
    {
        "metadata": {
            "title": "Everything Everywhere All at Once",
            "year": 2022,
            "director": "Daniel Kwan, Daniel Scheinert",
            "runtime_minutes": 139,
            "age_rating": "R",
            "genres": ["Sci-Fi", "Comedy", "Adventure"],
            "poster_url": "https://image.tmdb.org/t/p/w500/w3LxiVYPqrlxqPYSUTNNZNaPnBv.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=wxN1T1uxQ2g"
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
        "rationale": "Acclaimed as a wildly original multiverse adventure grounded in deeply touching family drama and stellar performances.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2022/may/13/everything-everywhere-all-at-once-review-dan-kwan-daniel-scheinert-michelle-yeoh",
            "https://www.rogerebert.com/reviews/everything-everywhere-all-at-once-movie-review-2022",
            "https://www.empireonline.com/movies/reviews/everything-everywhere-all-at-once/"
        ]
    },
    {
        "metadata": {
            "title": "Spirited Away",
            "year": 2001,
            "director": "Hayao Miyazaki",
            "runtime_minutes": 125,
            "age_rating": "PG",
            "genres": ["Anime", "Fantasy", "Adventure"],
            "poster_url": "https://image.tmdb.org/t/p/w500/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=ByXuk9QqQkk"
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
        "rationale": "Universally cherished for its breathtaking hand-drawn animation, profound fairytale mythology, and compassionate storytelling.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2003/sep/12/1",
            "https://www.rogerebert.com/reviews/spirited-away-2002",
            "https://www.empireonline.com/movies/reviews/spirited-away-review/"
        ]
    },
    {
        "metadata": {
            "title": "Pulp Fiction",
            "year": 1994,
            "director": "Quentin Tarantino",
            "runtime_minutes": 154,
            "age_rating": "R",
            "genres": ["Crime", "Drama", "Thriller"],
            "poster_url": "https://image.tmdb.org/t/p/w500/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=s7EdQ4FqbhY"
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
        "rationale": "Hailed as a highly influential post-modern classic, praised for its brilliant non-linear screenplay and iconic pop dialogue.",
        "evidence_sources": [
            "https://www.theguardian.com/film/1994/oct/21/features.derekmalcolm",
            "https://www.rogerebert.com/reviews/great-movie-pulp-fiction-1994",
            "https://www.empireonline.com/movies/reviews/pulp-fiction-review/"
        ]
    },
    {
        "metadata": {
            "title": "Parasite",
            "year": 2019,
            "director": "Bong Joon-ho",
            "runtime_minutes": 132,
            "age_rating": "R",
            "genres": ["Thriller", "Drama", "Comedy"],
            "poster_url": "https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=5xH0hhMbQW9"
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
        "rationale": "A thriller masterpiece universally lauded for sharp social satire, unpredictable pacing, and impeccable directorial design.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2020/feb/07/parasite-review-bong-joon-ho",
            "https://www.rogerebert.com/reviews/parasite-movie-review-2019",
            "https://www.bfi.org.uk/sight-and-sound/reviews/parasite-bong-joon-ho-upstairs-downstairs-black-comedy"
        ]
    },
    {
        "metadata": {
            "title": "The Dark Knight",
            "year": 2008,
            "director": "Christopher Nolan",
            "runtime_minutes": 152,
            "age_rating": "PG-13",
            "genres": ["Action", "Crime", "Drama"],
            "poster_url": "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=EXeTwQWrcwY"
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
        "rationale": "Acclaimed as a genre-defining crime drama, singled out for Heath Ledger's legendary performance and its intense, tragic realism.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2008/jul/25/action.filmreviews",
            "https://www.rogerebert.com/reviews/the-dark-knight-2008",
            "https://www.empireonline.com/movies/reviews/dark-knight-review/"
        ]
    },
    {
        "metadata": {
            "title": "Barbie",
            "year": 2023,
            "director": "Greta Gerwig",
            "runtime_minutes": 114,
            "age_rating": "PG-13",
            "genres": ["Comedy", "Fantasy"],
            "poster_url": "https://image.tmdb.org/t/p/w500/iuFNMS8U5cb6xfzi51Dbkovj7vM.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=pBk4NYhWNMM"
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
        "rationale": "Acclaimed for its witty satirical screenplay, dazzling colorful production design, and engaging performances.",
        "evidence_sources": [
            "https://www.theguardian.com/film/2023/jul/19/barbie-review-greta-gerwig-margot-robbie-ryan-gosling",
            "https://www.rogerebert.com/reviews/barbie-movie-review-2023",
            "https://www.empireonline.com/movies/reviews/barbie/"
        ]
    },
    {
        "metadata": {
            "title": "Nosferatu",
            "year": 1922,
            "director": "F.W. Murnau",
            "runtime_minutes": 94,
            "age_rating": "PG",
            "genres": ["Horror", "Fantasy"],
            "poster_url": "https://image.tmdb.org/t/p/w500/1pDjhU3kvdG31i5b4b1a3oWkCsh.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=d_k8qF82XyE"
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
        "rationale": "A legendary silent horror pioneer, universally studied and respected for its eerie expressionist atmosphere and shadow craft.",
        "evidence_sources": [
            "https://www.theguardian.com/film/1997/nov/28/features1",
            "https://www.rogerebert.com/reviews/great-movie-nosferatu-1922",
            "https://www.bfi.org.uk/sight-and-sound/features/nosferatu-vampire-symphony-horror-fw-murnau"
        ]
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

    # Tone mismatch penalty & polar opposite detection
    if user_has_tones:
        if not tone_matched:
            score -= 25
        # Check for polar-opposite tone clash (e.g. warm/gentle/heartfelt vs tense/bleak/mind-bending/intense)
        warm_user_tones = {"warm", "heartfelt", "gentle", "tender", "light", "feel-good", "soothing"}
        intense_film_tones = {"tense", "bleak", "intense", "mind-bending", "thrilling", "disturbing", "violent", "grim", "dark", "action", "crime", "horror"}
        user_wants_warm = any(t.lower() in warm_user_tones for t in user_tones)
        film_tones_and_genres = set([t.lower() for t in profile.tone_and_emotional_character] + [g.lower() for g in metadata.genres])
        film_is_intense = any(t in intense_film_tones for t in film_tones_and_genres)
        if user_wants_warm and film_is_intense:
            score -= 30

    # Artistic bonuses (Max +10 total)
    craft_bonus = max(0, int((profile.craft_and_execution - 3.0) * 3))  # Max 6
    story_bonus = max(0, int((profile.story_and_writing - 3.0) * 2))    # Max 4
    score += (craft_bonus + story_bonus)

    return max(0, min(100, score))


def generate_concise_reason(title: str, score: int, profile: FilmProfile, context: UserContext) -> str:
    """Generates a warm, natural explanation of why a film fits this user, given what they asked for.
    Follows: film characteristic -> user preference/context -> why that matters.
    Avoids generic superlatives and remains time-neutral.
    """
    signals = context.tonight_signals + context.persistent_taste
    pacing_req = next((s.value for s in signals if s.name == "pacing"), None)
    tone_req = next((s.value for s in signals if s.name == "tone"), None)

    tone_str = tone_req if isinstance(tone_req, str) else (tone_req[0] if isinstance(tone_req, list) and tone_req else None)
    tone_matched = bool(tone_str and any(tone_str.lower() in t.lower() for t in profile.tone_and_emotional_character))

    # Identify key film characteristic matching user preference
    char_phrases = []
    if tone_matched and tone_str:
        char_phrases.append(f"{tone_str.lower()} mood")
    
    if pacing_req:
        p_val = str(pacing_req).lower()
        if p_val in ("brisk", "fast") and profile.pacing_and_structure >= 3.8:
            char_phrases.append("a fast, energetic pace")
        elif p_val in ("slow", "thoughtful") and profile.pacing_and_structure <= 3.0:
            char_phrases.append("a slow, thoughtful build")
        elif p_val in ("measured", "steady"):
            char_phrases.append("a steady, absorbing rhythm")

    if not char_phrases:
        if profile.performances >= 4.0:
            char_phrases.append("strong ensemble acting")
        if profile.craft_and_execution >= 4.0:
            char_phrases.append("focused visual direction")
        if profile.story_and_writing >= 4.0:
            char_phrases.append("tightly structured writing")

    if not char_phrases:
        char_phrases.append("balanced storytelling")

    feature_str = " and ".join(char_phrases)

    # Connect to user preference and why that matters
    if tone_matched and pacing_req:
        return f"A film with {feature_str} directly reflects what you asked for, giving you a focused match without unnecessary drag."
    elif tone_matched:
        return f"A film with {feature_str} matches the feeling you're after, making it a natural choice for your shortlist."
    elif score >= 75:
        return f"With {feature_str}, it provides a well-paced option that fits your selected pace and channels."
    elif score >= 55:
        return f"A film with {feature_str} offers a solid alternative that still respects your boundaries and preferred pace."
    else:
        return f"A film with {feature_str} gives you an interesting alternative if you'd like to explore something different."


def generate_stretch_signal(profile: FilmProfile, context: UserContext) -> Optional[str]:
    """Determines if a film qualifies as a stretch recommendation.
    Explains the trade-off plainly without judging the user's preferences or overpraising the film.
    """
    signals = context.tonight_signals + context.persistent_taste
    demanding_val = None
    for s in signals:
        if s.name == "demandingness":
            try:
                demanding_val = float(s.value)
                break
            except (ValueError, TypeError):
                pass

    tone_val = next((s.value for s in signals if s.name == "tone"), None)
    tone_str = tone_val if isinstance(tone_val, str) else (tone_val[0] if isinstance(tone_val, list) and tone_val else None)

    if demanding_val is not None and demanding_val <= 3.0 and profile.accessibility_and_demandingness >= 4.0:
        if tone_str and any(tone_str.lower() in t.lower() for t in profile.tone_and_emotional_character):
            return f"It's more demanding than your other matches, but it still connects directly with your interest in a {tone_str.lower()} mood."
        elif profile.craft_and_execution >= 4.0:
            return "It's more demanding than your other matches, but its focused direction and performances make it worth considering if you want something bolder."
        else:
            return "It's more demanding than your other matches, but gives you a distinct alternative if you want to branch out."

    return None


def recommendation_order(rec: Recommendation, context: UserContext):
    """Recent-mode results prefer newer suitable genre matches, without inflating fit scores."""
    if context.min_release_year is None:
        return (rec.personal_fit_score, rec.metadata.year)
    genres = set()
    for signal in context.tonight_signals + context.persistent_taste:
        if signal.name == "preferred_genres":
            values = signal.value if isinstance(signal.value, list) else [signal.value]
            genres.update(str(value).lower() for value in values)
    genre_match = not genres or bool(genres.intersection(g.lower() for g in rec.metadata.genres))
    return (rec.personal_fit_score >= 20, genre_match, rec.metadata.year, rec.personal_fit_score)


def recent_role_order(ordered: List[Recommendation]) -> List[Recommendation]:
    """Keep the sorted release order when assigning roles; diversity cannot promote an older film."""
    result = ordered[:7]
    for index, rec in enumerate(result):
        rec.role = OutputRole.RANKED_ADDITIONAL
        if index == 0:
            rec.role = OutputRole.BEST_FIT
        elif index == 1 and rec.personal_fit_score >= 20:
            rec.role = OutputRole.STRONG_ALTERNATIVE
        elif (index == 2 and result[1].role == OutputRole.STRONG_ALTERNATIVE
              and rec.personal_fit_score >= 15 and rec.stretch_signal is not None):
            rec.role = OutputRole.WORTH_A_STRETCH
    return result


def discover_candidates_with_gemini(context: UserContext, deadline: Optional[float] = None) -> List[FilmMetadata]:
    """Uses Gemini Flash to discover 15-20 diverse, acclaimed candidate films up front
    matching user mood, pacing, and constraints.
    """
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not has_gemini_key:
        return [FilmMetadata(**s["metadata"]) for s in SEED_FILMS]

    if deadline and time.monotonic() >= deadline:
        return [FilmMetadata(**s["metadata"]) for s in SEED_FILMS]

    all_signals = context.tonight_signals + context.persistent_taste
    pacing = next((s.value for s in all_signals if s.name == "pacing"), None)
    tone = next((s.value for s in all_signals if s.name == "tone"), None)
    demandingness = next((s.value for s in all_signals if s.name == "demandingness"), None)

    exclude_genres = []
    for s in all_signals:
        if s.name == SIGNAL_EXCLUDE_GENRE and s.signal_type == SignalType.HARD_CONSTRAINT:
            if isinstance(s.value, list):
                exclude_genres.extend(s.value)
            elif isinstance(s.value, str):
                exclude_genres.append(s.value)

    max_runtime_signal = next(
        (s for s in all_signals if s.name == SIGNAL_MAX_RUNTIME and s.signal_type == SignalType.HARD_CONSTRAINT),
        None
    )
    max_runtime = int(max_runtime_signal.value) if max_runtime_signal is not None else None

    prompt = f"""You are TONI, a discerning cinema discovery guide.
Based on the viewer's current preferences, generate a diverse candidate list of 15 to 20 released feature films that fit what the viewer is in the mood for. Start with releases from {date.today().year - 1}–{date.today().year}, then expand backwards only as far as the earliest release year below. Unless older cinema is explicitly requested, avoid repeatedly defaulting to familiar award winners. Prefer a range of recent releases with verified availability over an all-time classics list. Never sacrifice the requested genre or mood merely for recency.

Viewer Preferences:
- Country: {context.country}
- Channels: {', '.join(context.service_access) if context.service_access else 'Any'}
- Allow Rent/Buy: {context.allow_rent_buy}
- Desired pace: {pacing or 'any'}
- Desired mood: {tone or 'any'}
- Demandingness effort: {demandingness or 'any'} / 5.0
- Maximum runtime: {f'{max_runtime} minutes' if max_runtime else 'no strict limit'}
- Earliest release year (inclusive hard limit): {context.min_release_year or 'any year'}
- Excluded genres: {', '.join(exclude_genres) if exclude_genres else 'none'}
- Preferred genres and reference films: {[(s.name, s.value) for s in all_signals if s.name in ('preferred_genres', 'reference_films', 'freeform_mood')]}
The explicit desired mood, runtime and release-year controls above are the viewer's latest refinements and take precedence over conflicting wording in earlier freeform preferences. Keep their genre, country and service access.

Requirements:
1. Provide between 15 and 20 distinct, high-quality feature films.
2. Strictly exclude any titles containing these genres: {', '.join(exclude_genres) if exclude_genres else 'none'}.
3. If maximum runtime is specified ({max_runtime}), only suggest films with runtimes within that limit.
4. Include a balance of top matches, accessible favourites, and 2-3 bolder films (as potential stretch recommendations).
5. For each film, provide accurate title, release year, director, approximate runtime, age rating, and genres.
6. Only include films already released as of {date.today().isoformat()}. If an earliest release year is set, every film must satisfy it. Do not fill the list with older titles when the filter is restrictive.
"""
    if os.environ.get("TONI_MOCK_GEMINI_LIVE") == "true":
        return [FilmMetadata(**s["metadata"]) for s in SEED_FILMS]

    try:
        from google.genai import types

        client = get_gemini_client()
        response = None
        for idx, model_candidate in enumerate([DISCOVERY_MODEL]):
            # Gemini Developer API requires a minimum deadline of 10s (10000ms).
            # If remaining pipeline budget is insufficient to fit a valid 10s call, skip upstream call honestly.
            remaining_for_disc = deadline - time.monotonic() if deadline else 12.0
            if remaining_for_disc <= 0:
                print(f"[*] Insufficient deadline budget for Gemini discovery ({remaining_for_disc:.2f}s < 10.0s). Falling back honestly to seed films.", file=sys.stderr)
                break
            try:
                cur_timeout_ms = 10000
                response = client.models.generate_content(
                    model=model_candidate,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        max_output_tokens=4096,
                        response_mime_type="application/json",
                        response_schema=DiscoveredCandidateList,
                        http_options=types.HttpOptions(
                            timeout=cur_timeout_ms,
                            retry_options=types.HttpRetryOptions(attempts=1)
                        ),
                    ),
                )
                if response and response.parsed:
                    break
            except Exception as e:
                print(f"[!] Candidate discovery candidate {model_candidate} failed: {e}", file=sys.stderr)
                continue
        if response and response.parsed and response.parsed.candidates:
            candidates = [
                FilmMetadata(
                    title=c.title,
                    year=c.year,
                    director=c.director,
                    runtime_minutes=c.runtime_minutes,
                    age_rating=c.age_rating,
                    genres=c.genres,
                    poster_url=None,
                    trailer_url=None,
                )
                for c in response.parsed.candidates
            ]
            if len(candidates) >= 5:
                return candidates
    except Exception as e:
        print(f"[!] Live candidate discovery failed: {e}. Falling back to seed films.", file=sys.stderr)

    return [FilmMetadata(**s["metadata"]) for s in SEED_FILMS]


def _rank_movies_live(
    context: UserContext,
    force_live_evidence: bool = True
) -> RecommendationResponse:
    """Executes the live TONI pipeline:
    1. Candidate Discovery: Gemini Flash generates 15-20 candidates up front.
    2. Availability Gate First: Check streaming availability on all 15-20 candidates BEFORE Parallel search.
    3. Parallel Search & Extract: Run get_film_evidence on top 3-5 candidates surviving availability.
    4. Gemini 2.5 Pro Profiling: Synthesizes 6-dimension profile and Evidence State.
    5. Dynamic Soft Weighting & Presentation Roles (Best Fit, Strong Alternative, Worth a Stretch).
    """
    all_signals = context.tonight_signals + context.persistent_taste
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
    unverified_excluded_titles = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    pipeline_start_time = time.monotonic()
    TOTAL_DEADLINE_SECONDS = 18.0
    pipeline_deadline = pipeline_start_time + TOTAL_DEADLINE_SECONDS

    # 1. Candidate Discovery (15-20 candidates up front, bounded by discovery deadline)
    # Gemini requires at least 10s deadline budget. At pipeline start (t=0), 18s remains.
    try:
        discovery_deadline = min(pipeline_deadline - 3.0, pipeline_start_time + 10.1)
        discovered_candidates = call_until(
            discovery_deadline, discover_candidates_with_gemini,
            context, deadline=discovery_deadline)
    except Exception as exc:
        print(f"[TONI] Discovery unavailable ({type(exc).__name__}); using seed candidates.", file=sys.stderr)
        discovered_candidates = [FilmMetadata(**s["metadata"]) for s in SEED_FILMS]

    discovered_candidates = [c for c in discovered_candidates
                             if context.min_release_year is None or c.year >= context.min_release_year]

    # 2. Availability Gate First: Run get_film_availability concurrently on candidates BEFORE Parallel Search
    surviving_candidates: List[tuple[FilmMetadata, Any]] = []
    unavailable_titles: List[str] = []
    runtime_excluded_titles: List[str] = []
    genre_excluded_titles: List[str] = []

    def check_availability(meta: FilmMetadata):
        try:
            if max_runtime is not None and meta.runtime_minutes > max_runtime:
                return meta, "runtime", None
            if any(g.lower().strip() in exclude_genres_lower for g in meta.genres):
                return meta, "genre", None
            avail = get_film_availability(meta.title, meta.year, context, timeout=min(3.0, remaining(pipeline_deadline)))
            if avail.status == AvailabilityStatus.AVAILABLE:
                return meta, "available", avail
            elif avail.status == AvailabilityStatus.UNVERIFIED:
                return meta, "unverified", avail
            else:
                return meta, "unavailable", avail
        except Exception as e:
            print(f"[!] Error checking availability for {meta.title}: {e}", file=sys.stderr)
            return meta, "unavailable", None

    avail_timeout = min(3.0, max(0.0, remaining(pipeline_deadline) - 2.0))
    avail_executor = UPSTREAM_EXECUTOR
    try:
        future_to_meta = {avail_executor.submit(check_availability, c): c for c in discovered_candidates}
        for future in completed_until(future_to_meta, time.monotonic() + avail_timeout):
            try:
                meta, status_tag, avail_res = future.result()
                if status_tag == "available":
                    surviving_candidates.append((meta, avail_res))
                elif status_tag == "unverified":
                    unverified_excluded_count += 1
                    unverified_excluded_titles.append(f"{meta.title} ({meta.year})")
                elif status_tag == "unavailable":
                    unavailable_titles.append(f"{meta.title} ({meta.year})")
                elif status_tag == "runtime":
                    runtime_excluded_titles.append(f"{meta.title} ({meta.runtime_minutes}m)")
                elif status_tag == "genre":
                    genre_excluded_titles.append(f"{meta.title} ({','.join(meta.genres)})")
            except Exception as e:
                pass
            if len(surviving_candidates) >= 5 and time.monotonic() >= pipeline_deadline - 9.0:
                break
    except Exception:
        # Availability check timeout reached, proceed with available candidates gathered so far
        pass
    finally:
        pass  # Shared bounded pool; completed_until cancels queued work.

    print(
        f"[TONI Live Pipeline] Candidate Discovery & Filtering Audit:\n"
        f"  - Total Discovered: {len(discovered_candidates)}\n"
        f"  - Available (Surviving): {len(surviving_candidates)}\n"
        f"  - Unavailable: {len(unavailable_titles)} -> {unavailable_titles[:5]}\n"
        f"  - Unverified: {unverified_excluded_count} -> {unverified_excluded_titles[:5]}\n"
        f"  - Runtime Excluded: {len(runtime_excluded_titles)} -> {runtime_excluded_titles[:5]}\n"
        f"  - Genre Excluded: {len(genre_excluded_titles)} -> {genre_excluded_titles[:5]}",
        file=sys.stderr
    )

    all_signals = context.tonight_signals + context.persistent_taste
    user_tones = [s.value for s in all_signals if s.name == "tone"]
    pref_genres = [s.value for s in all_signals if s.name == "preferred_genres"]
    flat_user_tones = set()
    for t in user_tones:
        if isinstance(t, list):
            flat_user_tones.update(x.lower() for x in t)
        elif isinstance(t, str):
            flat_user_tones.add(t.lower())

    # 3. Candidate Pool Refill: If availability filtering leaves fewer than 3 eligible candidates,
    # attempt to refill from SEED_FILMS that strictly pass hard constraints, tone alignment, and verified availability.
    if len(surviving_candidates) < 3 and time.monotonic() < pipeline_deadline - 6.0:
        diagnostic_reason = (
            f"Availability filtering left only {len(surviving_candidates)} eligible candidates "
            f"(fewer than target 3 for shortlist). Dropout breakdown: "
            f"{len(unavailable_titles)} unavailable in {context.country} for {context.service_access} (rent_buy={context.allow_rent_buy}), "
            f"{unverified_excluded_count} unverified, {len(runtime_excluded_titles)} exceeded runtime ({max_runtime}m), "
            f"{len(genre_excluded_titles)} excluded by genres ({exclude_genres}). "
            f"Checking SEED_FILMS for verified available candidates passing all hard constraints."
        )
        print(f"[TONI Live Pipeline Diagnostic] {diagnostic_reason}", file=sys.stderr)

        existing_titles = {meta.title.lower().strip() for meta, _ in surviving_candidates}
        checked_titles = set(existing_titles)

        # Refill only with seed films that pass hard constraints, tone alignment, and verified availability
        for seed in SEED_FILMS:
            # Check remaining request budget before entering each refill operation; stop initiating work when it cannot fit
            if time.monotonic() >= pipeline_deadline - 5.5:
                print(f"[TONI Live Pipeline Diagnostic] Pipeline deadline approaching ({pipeline_deadline - time.monotonic():.2f}s remaining); stopping refill initiation.", file=sys.stderr)
                break
            meta = FilmMetadata(**seed["metadata"])
            if context.min_release_year is not None and meta.year < context.min_release_year:
                continue
            norm_title = meta.title.lower().strip()
            if norm_title in checked_titles:
                continue
            checked_titles.add(norm_title)

            if max_runtime is not None and meta.runtime_minutes > max_runtime:
                continue
            if any(g.lower().strip() in exclude_genres_lower for g in meta.genres):
                continue

            # Check tone clash: don't refill dark/bleak/intense films for warm/light requests
            seed_profile_data = seed.get("profile", {})
            seed_tones = [t.lower() for t in seed_profile_data.get("tone_and_emotional_character", [])]
            if flat_user_tones:
                is_warm_req = any(ut in ("warm", "light", "gentle", "heartfelt", "feel-good", "soothing") for ut in flat_user_tones)
                is_dark_film = any(st in ("dark", "intense", "bleak", "haunting", "brooding", "psychological") for st in seed_tones)
                if is_warm_req and is_dark_film:
                    continue

            # Bound the caller even if a provider fails to honour its transport timeout.
            refill_deadline = min(pipeline_deadline - 2.0, time.monotonic() + 2.0)
            try:
                avail = call_until(refill_deadline, get_film_availability,
                    meta.title, meta.year, context, timeout=remaining(refill_deadline))
            except Exception:
                continue
            if avail.status == AvailabilityStatus.AVAILABLE:
                surviving_candidates.append((meta, avail))
                if len(surviving_candidates) >= 3:
                    break
            elif avail.status == AvailabilityStatus.UNVERIFIED:
                unverified_excluded_count += 1
                unverified_excluded_titles.append(f"{meta.title} ({meta.year})")

        print(f"[TONI Live Pipeline] Candidate pool after verified refill has {len(surviving_candidates)} eligible candidates.", file=sys.stderr)

    if not surviving_candidates:
        print(f"[TONI Live Pipeline Diagnostic] 0 candidates survived after all filtering and refill attempts.", file=sys.stderr)
        return RecommendationResponse(
            recommendations=[],
            unverified_excluded_count=unverified_excluded_count,
            unverified_excluded_titles=unverified_excluded_titles
        )

    # 4. Preliminary alignment sorting to select the best 4 candidates for full Parallel evidence & profiling
    def candidate_preliminary_score(item):
        meta, _ = item
        score = 50
        meta_genres = [g.lower() for g in meta.genres]
        for pg in pref_genres:
            pg_list = pg if isinstance(pg, list) else [pg]
            for g in pg_list:
                if g.lower() in meta_genres:
                    score += 15
        # Tone vs genres alignment heuristic
        if any(w in flat_user_tones for w in ["warm", "heartfelt", "gentle", "tender", "light", "feel-good", "soothing"]):
            if any(g in meta_genres for g in ["drama", "comedy", "romance", "family", "animation"]):
                score += 15
            if any(g in meta_genres for g in ["horror", "thriller", "action", "crime", "sci-fi"]):
                score -= 20
        elif any(i in flat_user_tones for i in ["intense", "tense", "thrilling", "dark", "bleak"]):
            if any(g in meta_genres for g in ["thriller", "mystery", "crime", "action", "horror"]):
                score += 15
            if any(g in meta_genres for g in ["romance", "comedy", "family"]):
                score -= 20
        return (score, meta.year) if context.min_release_year is not None else (score, 0)

    surviving_candidates.sort(key=candidate_preliminary_score, reverse=True)
    target_pool = surviving_candidates[:min(4, len(surviving_candidates))]
    additional_pool = surviving_candidates[min(4, len(surviving_candidates)):7]

    def process_candidate_full(item):
        metadata, avail_res = item
        reviews = []
        now = time.monotonic()
        time_left = max(0.0, pipeline_deadline - now)
        evidence_timeout = min(5.0, time_left)
        try:
            reviews = get_film_evidence(
                title=metadata.title,
                year=metadata.year,
                director=metadata.director,
                force_live=force_live_evidence,
                timeout=evidence_timeout
            )
        except Exception as e:
            print(f"[!] Evidence error for {metadata.title}: {e}", file=sys.stderr)

        is_fallback_profile = False
        try:
            rem_for_prof = pipeline_deadline - time.monotonic()
            if rem_for_prof < 0.5:
                raise TimeoutError(f"Pipeline deadline budget ({rem_for_prof:.2f}s remaining) insufficient for Gemini 10s constraint; fast-profiling candidate.")
            profile, ev_state, consensus_rationale = generate_film_profile(
                title=metadata.title,
                year=metadata.year,
                director=metadata.director,
                reviews=reviews,
                deadline=pipeline_deadline - 0.5
            )
        except Exception as e:
            print(f"[!] Profiling error for {metadata.title}: {e}", file=sys.stderr)
            is_fallback_profile = True
            profile = FilmProfile(
                story_and_writing=4.0,
                pacing_and_structure=3.8,
                performances=4.2,
                craft_and_execution=4.0,
                accessibility_and_demandingness=3.0,
                tone_and_emotional_character=metadata.genres or ["unknown"]
            )
            ev_state = EvidenceState.SPARSE_EVIDENCE
            consensus_rationale = "Baseline profile (fallback): critical review consensus could not be synthesized by Gemini."

        fit_score = calculate_personal_fit_score(profile, metadata, context)
        stretch_reason = generate_stretch_signal(profile, context)
        if is_fallback_profile:
            concise_reason = "Baseline match based on film characteristics (live AI review synthesis was unavailable for this title)."
        else:
            concise_reason = generate_concise_reason(metadata.title, fit_score, profile, context)

        return Recommendation(
            metadata=metadata,
            profile=profile,
            evidence_state=ev_state,
            availability=avail_res,
            personal_fit_score=fit_score,
            stretch_signal=stretch_reason,
            role=OutputRole.RANKED_ADDITIONAL,
            concise_reason=concise_reason,
            evidence_sources=[r["url"] for r in reviews if isinstance(r, dict) and "url" in r]
        )

    # Process top candidates concurrently with explicit timeout and non-blocking shutdown
    scored_candidates = []
    profiling_timeout = max(1.5, pipeline_deadline - time.monotonic() - 0.5)
    prof_executor = UPSTREAM_EXECUTOR
    try:
        future_to_cand = {prof_executor.submit(process_candidate_full, item): item for item in target_pool}
        for future in completed_until(future_to_cand, pipeline_deadline - 0.5):
            try:
                rec = future.result()
                if rec:
                    scored_candidates.append(rec)
            except Exception as e:
                print(f"[!] Error processing candidate full: {e}", file=sys.stderr)
    except Exception:
        pass
    finally:
        pass  # Shared bounded pool retains at most its fixed worker limit.

    # For any candidate in target_pool that didn't complete before deadline, populate fallback
    completed_titles = {r.metadata.title for r in scored_candidates}
    for meta, avail in target_pool:
        if meta.title not in completed_titles:
            fallback_prof = FilmProfile(
                story_and_writing=4.0,
                pacing_and_structure=3.8,
                performances=4.0,
                craft_and_execution=3.9,
                accessibility_and_demandingness=3.2,
                tone_and_emotional_character=meta.genres[:2] if meta.genres else ["engaging"]
            )
            fit_score = calculate_personal_fit_score(fallback_prof, meta, context)
            stretch_reason = generate_stretch_signal(fallback_prof, context)
            concise_reason = generate_concise_reason(meta.title, fit_score, fallback_prof, context)
            scored_candidates.append(
                Recommendation(
                    metadata=meta,
                    profile=fallback_prof,
                    evidence_state=EvidenceState.MAINLY_OFFICIAL_FACTUAL,
                    availability=avail,
                    personal_fit_score=fit_score,
                    stretch_signal=stretch_reason,
                    role=OutputRole.RANKED_ADDITIONAL,
                    concise_reason=concise_reason,
                    evidence_sources=[]
                )
            )

    # Fast-profile any remaining candidates up to 7 to populate the expanded shortlist without extra network round-trips
    for metadata, avail_res in additional_pool:
        profile = FilmProfile(
            story_and_writing=4.0,
            pacing_and_structure=3.8,
            performances=4.0,
            craft_and_execution=3.9,
            accessibility_and_demandingness=3.2,
            tone_and_emotional_character=metadata.genres[:2]
        )
        fit_score = calculate_personal_fit_score(profile, metadata, context)
        stretch_reason = generate_stretch_signal(profile, context)
        concise_reason = generate_concise_reason(metadata.title, fit_score, profile, context)
        scored_candidates.append(
            Recommendation(
                metadata=metadata,
                profile=profile,
                evidence_state=EvidenceState.MAINLY_OFFICIAL_FACTUAL,
                availability=avail_res,
                personal_fit_score=fit_score,
                stretch_signal=stretch_reason,
                role=OutputRole.RANKED_ADDITIONAL,
                concise_reason=concise_reason,
                evidence_sources=[]
            )
        )

    # 5. Presentation Roles (Best Fit, Strong Alternative, Worth a Stretch, Ranked Additional)
    warm_requested = bool(flat_user_tones.intersection({"warm", "gentle", "light", "feel-good", "soothing"}))
    if warm_requested:
        opposite = {"intense", "dark", "violent", "bleak", "brooding", "mind-bending", "horror", "crime"}
        scored_candidates = [r for r in scored_candidates if not opposite.intersection(
            t.lower() for t in r.profile.tone_and_emotional_character + r.metadata.genres)]
    scored_candidates = [r for r in scored_candidates if r.personal_fit_score > 0]
    if not scored_candidates:
        return RecommendationResponse(recommendations=[], unverified_excluded_count=unverified_excluded_count,
            unverified_excluded_titles=unverified_excluded_titles)
    scored_candidates.sort(key=lambda r: recommendation_order(r, context), reverse=True)
    final_recs: List[Recommendation] = []

    # Best Fit
    best_fit = scored_candidates[0]
    best_fit.role = OutputRole.BEST_FIT
    final_recs.append(best_fit)

    # Strong Alternative (requires personal_fit_score >= 20 to avoid recommending zero-fit titles)
    strong_alt = None
    best_genres = set(best_fit.metadata.genres)
    for r in scored_candidates[1:]:
        if r.personal_fit_score >= 20 and not set(r.metadata.genres).intersection(best_genres):
            strong_alt = r
            break
    if not strong_alt and len(scored_candidates) > 1 and scored_candidates[1].personal_fit_score >= 20:
        strong_alt = scored_candidates[1]
    if strong_alt:
        strong_alt.role = OutputRole.STRONG_ALTERNATIVE
        final_recs.append(strong_alt)

    # Worth a Stretch (only assigned if strong_alt exists, maintaining canonical role sequence)
    if strong_alt:
        stretch_rec = None
        used = {r.metadata.title for r in final_recs}
        for r in scored_candidates:
            if r.metadata.title not in used and r.personal_fit_score >= 15 and r.stretch_signal is not None:
                stretch_rec = r
                break
        if not stretch_rec:
            for r in scored_candidates:
                if r.metadata.title not in used and r.personal_fit_score >= 15:
                    stretch_rec = r
                    stretch_rec.stretch_signal = "A distinctive stylistic departure that rewards your attention."
                    break
        if stretch_rec:
            stretch_rec.role = OutputRole.WORTH_A_STRETCH
            final_recs.append(stretch_rec)

    # Ranked Additional (up to 7, only positive matches)
    used = {r.metadata.title for r in final_recs}
    for r in scored_candidates:
        if len(final_recs) >= 7:
            break
        if r.metadata.title not in used and r.personal_fit_score > 0:
            r.role = OutputRole.RANKED_ADDITIONAL
            final_recs.append(r)

    # Enrich poster and trailer URLs concurrently for final shortlisted recommendations only
    rem_enrich = pipeline_deadline - time.monotonic()
    if context.min_release_year is not None:
        final_recs = recent_role_order(scored_candidates)
    if final_recs and rem_enrich > 0.5:
        enrich_timeout = min(1.5, rem_enrich)
        enrich_executor = UPSTREAM_EXECUTOR
        try:
            def enrich_media(original: Recommendation):
                rec = original.model_copy(deep=True)
                if not rec.metadata.poster_url:
                    rec.metadata.poster_url = get_film_poster_url(rec.metadata.title, rec.metadata.year)
                if not rec.metadata.trailer_url:
                    rec.metadata.trailer_url = get_film_trailer_url(rec.metadata.title, rec.metadata.year)
                return rec

            futures = [enrich_executor.submit(enrich_media, r) for r in final_recs]
            for future in completed_until(futures, min(pipeline_deadline - 0.1, time.monotonic() + enrich_timeout)):
                try:
                    enriched = future.result()
                    for index, rec in enumerate(final_recs):
                        if rec.metadata.title == enriched.metadata.title:
                            final_recs[index] = enriched
                            break
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            pass

    return RecommendationResponse(
        recommendations=final_recs,
        unverified_excluded_count=unverified_excluded_count,
        unverified_excluded_titles=unverified_excluded_titles
    )


def _rank_movies_seed(context: UserContext, force_live_evidence: bool = True) -> RecommendationResponse:
    """Deterministic recommendation pipeline evaluated against SEED_FILMS."""
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
    unverified_excluded_titles = []

    # Process all seed pool films
    for seed in SEED_FILMS:
        meta_dict = seed["metadata"]
        prof_dict = seed["profile"]

        metadata = FilmMetadata(**meta_dict)
        if context.min_release_year is not None and metadata.year < context.min_release_year:
            continue
        profile = FilmProfile(**prof_dict)

        # --- HARD CONSTRAINT 1: LIVE AVAILABILITY ---
        avail_res = get_film_availability(metadata.title, metadata.year, context)
        if avail_res.status != AvailabilityStatus.AVAILABLE:
            if avail_res.status == AvailabilityStatus.UNVERIFIED:
                unverified_excluded_count += 1
                unverified_excluded_titles.append(f"{metadata.title} ({metadata.year})")
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

    # If no movies are available, report clear structured diagnostics and return response
    if not eligible_recommendations:
        diagnostic_reason = (
            f"[TONI Seed Pipeline Diagnostic] 0 seed films survived availability filtering for country={context.country}, "
            f"services={context.service_access}, allow_rent_buy={context.allow_rent_buy}. "
            f"Diagnostics: unverified_excluded={unverified_excluded_count} ({', '.join(unverified_excluded_titles) if unverified_excluded_titles else 'none'}), "
            f"max_runtime={max_runtime}, excluded_genres={exclude_genres}."
        )
        print(diagnostic_reason, file=sys.stderr)
        return RecommendationResponse(
            recommendations=[],
            unverified_excluded_count=unverified_excluded_count,
            unverified_excluded_titles=unverified_excluded_titles
        )

    # Sort primarily by Personal Fit Score descending
    eligible_recommendations.sort(key=lambda r: recommendation_order(r, context), reverse=True)

    final_recommendations: List[Recommendation] = []

    # 1. BEST FIT (The highest-scoring matching film)
    best_fit_rec = eligible_recommendations[0]
    best_fit_rec.role = OutputRole.BEST_FIT
    final_recommendations.append(best_fit_rec)

    # 2. STRONG ALTERNATIVE (Next highest scoring that is deliberately distinct, fit >= 20)
    strong_alt_rec = None
    best_genres = set(best_fit_rec.metadata.genres)

    for rec in eligible_recommendations[1:]:
        if rec.personal_fit_score >= 20 and not set(rec.metadata.genres).intersection(best_genres):
            strong_alt_rec = rec
            break

    # Fallback to second-highest if no completely distinct genre exists, provided fit score >= 20
    if not strong_alt_rec and len(eligible_recommendations) > 1 and eligible_recommendations[1].personal_fit_score >= 20:
        strong_alt_rec = eligible_recommendations[1]

    if strong_alt_rec:
        strong_alt_rec.role = OutputRole.STRONG_ALTERNATIVE
        final_recommendations.append(strong_alt_rec)

    # 3. WORTH A STRETCH (only assigned if strong_alt_rec exists, maintaining canonical role sequence)
    if strong_alt_rec:
        stretch_rec = None
        used_titles = {r.metadata.title for r in final_recommendations}

        for rec in eligible_recommendations:
            if rec.metadata.title in used_titles:
                continue
            if rec.personal_fit_score >= 15 and rec.stretch_signal is not None:
                stretch_rec = rec
                break

        if not stretch_rec:
            for rec in eligible_recommendations:
                if rec.metadata.title not in used_titles and rec.personal_fit_score >= 15:
                    stretch_rec = rec
                    stretch_rec.stretch_signal = "A distinctive stylistic departure that rewards your attention."
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

    if context.min_release_year is not None:
        final_recommendations = recent_role_order(eligible_recommendations)

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
        unverified_excluded_count=unverified_excluded_count,
        unverified_excluded_titles=unverified_excluded_titles
    )


def rank_movies(
    context: UserContext,
    force_live_evidence: bool = True,
    use_live_pipeline: Optional[bool] = None
) -> RecommendationResponse:
    """Ties the entire TONI pipeline together:

    When use_live_pipeline=True (or when live keys are present and force_live_evidence=True):
    1. Candidate Discovery: Gemini Flash generates 15-20 candidate films up front.
    2. Availability Gate First: Live streaming availability runs on all 15-20 candidates BEFORE Parallel.
    3. Parallel Search & Extract: Runs on top 3-5 surviving candidates.
    4. Gemini 2.5 Pro Profiling: Synthesizes 6-dimension profile and Evidence State.
    5. Personal Fit Scores & Role assignment (Best Fit, Strong Alternative, Worth a Stretch).

    When keys are absent or use_live_pipeline=False, preserves the deterministic SEED_FILMS pool.
    """
    has_live_keys = bool(
        os.environ.get("PARALLEL_API_KEY") and
        (os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY"))
    )

    if use_live_pipeline is False:
        is_live = False
    elif use_live_pipeline is True:
        is_live = True
    else:
        # If not explicitly specified, use live pipeline only when live keys exist and force_live_evidence is enabled
        is_live = has_live_keys and force_live_evidence

    if is_live:
        return _rank_movies_live(context, force_live_evidence=force_live_evidence)
    return _rank_movies_seed(context, force_live_evidence=force_live_evidence)
