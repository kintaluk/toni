"""
TONI API Contracts and Enums

This module defines the shared typed API contracts (Pydantic models) representing
the canonical product contract for the Tonight’s Own Next Indulgence (TONI) discovery engine.
These types serve as the single source of truth for both the backend agent runtime and Tina's front end.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# --- STATE & CATEGORIZATION ENUMS ---

class SignalType(str, Enum):
    """Categorization of intake signal impact."""
    HARD_CONSTRAINT = "hard_constraint"
    SOFT_SESSION_PREFERENCE = "soft_session_preference"
    POSSIBLE_PERSISTENT_PREFERENCE = "possible_persistent_preference"


class SignalProvenance(str, Enum):
    """Source of a persistent taste signal, ensuring transparency."""
    EXPLICIT_STATEMENT = "explicit_statement"
    REPEATED_BEHAVIOR = "repeated_behavior"
    INFERENCE = "inference"


class AvailabilityStatus(str, Enum):
    """Tri-state availability model, preventing recommendation of unwatchable titles."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"


class EvidenceState(str, Enum):
    """Description of critical review consensus or lack thereof."""
    STRONG_AGREEMENT = "strong_agreement"
    MEANINGFUL_DISAGREEMENT = "meaningful_disagreement"
    SPARSE_EVIDENCE = "sparse_evidence"
    MAINLY_OFFICIAL_FACTUAL = "mainly_official_factual"


class OutputRole(str, Enum):
    """Assigned recommendation roles to reduce user choice fatigue."""
    BEST_FIT = "best_fit"
    STRONG_ALTERNATIVE = "strong_alternative"
    WORTH_A_STRETCH = "worth_a_stretch"
    RANKED_ADDITIONAL = "ranked_additional"


class RefinementIntent(str, Enum):
    """Refinement routes mapped to specific technical actions."""
    MORE_LIKE_THIS = "more_like_this"
    BOUNDED_CHANGE = "bounded_change"  # Shorter / lighter / less intense
    NONE_OF_THESE = "none_of_these"
    FREE_TEXT = "free_text"


class InteractionState(str, Enum):
    """Fine-grained tracking of recommended items."""
    RECOMMENDED = "recommended"
    SELECTED_INTENDED = "selected_intended"
    CONFIRMED_WATCHED = "confirmed_watched"
    LIKED_DISLIKED_REJECTED = "liked_disliked_rejected"


class IntakeDepth(str, Enum):
    """User-controlled effort level at entry, controlling dialogue length only."""
    JUST_GIVE_ME_SOMETHING = "just_give_me_something"  # Fast mode
    A_COUPLE_OF_QUESTIONS = "a_couple_of_questions"    # Medium mode
    GET_TO_KNOW_ME = "get_to_know_me"                  # Deep mode


# --- DATA MODELS ---

class TasteSignal(BaseModel):
    """Represents a single parsed signal from the intake conversation."""
    name: str = Field(description="The name or key of the taste signal (e.g., 'horror', 'under-two-hours').")
    value: Any = Field(description="The parsed value of the signal (e.g., True, False, 120, 'slow').")
    signal_type: SignalType = Field(description="The dynamic category determining eligibility or ranking weight.")
    provenance: Optional[SignalProvenance] = Field(
        default=None,
        description="The source of the preference, required if this is a persistent preference."
    )


class AvailabilityResult(BaseModel):
    """Structured result of live UK/US streaming availability checks."""
    status: AvailabilityStatus = Field(description="Tri-state watchability status.")
    provider: str = Field(description="The data provider (e.g., 'Watchmode', 'TMDB').")
    country: str = Field(description="Confirmed country ('UK' or 'US' only).")
    matched_services: List[str] = Field(
        default_factory=list,
        description="List of included-access services showing this title (empty if unavailable or rent/buy excluded)."
    )


class FilmProfile(BaseModel):
    """Stable, evidence-led profile representing the underlying assessment of a film's qualities."""
    story_and_writing: float = Field(
        ge=1.0, le=5.0,
        description="Narrative coherence, screenplay, dialogue, character development (1-5)."
    )
    pacing_and_structure: float = Field(
        ge=1.0, le=5.0,
        description="Rhythm, momentum, editing, brisk vs. slow/uneven (1-5)."
    )
    performances: float = Field(
        ge=1.0, le=5.0,
        description="Acting quality, chemistry, character credibility (1-5)."
    )
    tone_and_emotional_character: List[str] = Field(
        description="Descriptive adjectives capturing what the film feels like (e.g., 'warm', 'tense', 'bleak')."
    )
    craft_and_execution: float = Field(
        ge=1.0, le=5.0,
        description="Direction, cinematography, production design, music, technical execution (1-5)."
    )
    accessibility_and_demandingness: float = Field(
        ge=1.0, le=5.0,
        description="How much attention, patience, or emotional commitment the film asks of the viewer (1-5)."
    )


class FilmMetadata(BaseModel):
    """General movie metadata."""
    title: str = Field(description="Movie title.")
    year: int = Field(description="Release year.")
    director: str = Field(description="Director.")
    runtime_minutes: int = Field(description="Total runtime in minutes.")
    age_rating: str = Field(description="Age certification (e.g., 'PG-13', '15').")
    genres: List[str] = Field(description="List of associated genres.")


class Recommendation(BaseModel):
    """A personalized recommendation card prepared for the user."""
    metadata: FilmMetadata = Field(description="Core movie details.")
    profile: FilmProfile = Field(description="The stable evidence-led film profile.")
    evidence_state: EvidenceState = Field(description="Summary of critical review consensus or divergence.")
    availability: AvailabilityResult = Field(description="Live confirmed availability information.")
    personal_fit_score: int = Field(
        ge=0, le=100,
        description="Internal normalized fit score (0-100), never shown raw to users by default."
    )
    stretch_signal: Optional[str] = Field(
        default=None,
        description="Evidence-based reasoning justifying 'Worth a stretch' (None if standard fit)."
    )
    role: OutputRole = Field(description="The assigned presentation role.")
    concise_reason: str = Field(
        description="Warm, natural-language explanation of why this specific film fits tonight's context."
    )


class RecommendationResponse(BaseModel):
    """The final structured recommendations payload."""
    recommendations: List[Recommendation] = Field(
        description="The ranked watchlist containing up to 7 recommendations in total."
    )

    def validate_roles(self) -> bool:
        """Validates that the first three recommendations have correct role assignments.

        - First must be 'best_fit'
        - Second must be 'strong_alternative'
        - Third must be 'worth_a_stretch'
        - Suffix must be 'ranked_additional'
        """
        if not self.recommendations:
            return True
        
        # Check first three roles
        roles_sequence = [OutputRole.BEST_FIT, OutputRole.STRONG_ALTERNATIVE, OutputRole.WORTH_A_STRETCH]
        for i, role in enumerate(roles_sequence):
            if len(self.recommendations) > i:
                if self.recommendations[i].role != role:
                    return False
        
        # Check additional roles
        for rec in self.recommendations[3:]:
            if rec.role != OutputRole.RANKED_ADDITIONAL:
                return False
                
        return True


class UserContext(BaseModel):
    """Active user session tracking context, including tonight's context and persistent memory."""
    country: str = Field(description="Confirmed user country ('UK' or 'US').")
    service_access: List[str] = Field(description="User's confirmed included-access streaming services.")
    allow_rent_buy: bool = Field(default=False, description="Whether extra-cost rental/purchase is allowed.")
    intake_depth: IntakeDepth = Field(description="Selected onboarding effort level.")
    tonight_signals: List[TasteSignal] = Field(
        default_factory=list,
        description="Extracted preference signals for the active session."
    )
    persistent_taste: List[TasteSignal] = Field(
        default_factory=list,
        description="Durable taste profile preferences loaded from memory."
    )
    interaction_history: Dict[str, InteractionState] = Field(
        default_factory=dict,
        description="Mapping of movie titles to tracked user interaction states."
    )
