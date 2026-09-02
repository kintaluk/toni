import pytest
from pydantic import ValidationError
from src.contracts import (
    SignalType,
    SignalProvenance,
    AvailabilityStatus,
    EvidenceState,
    OutputRole,
    RefinementIntent,
    InteractionState,
    IntakeDepth,
    TasteSignal,
    AvailabilityResult,
    FilmProfile,
    FilmMetadata,
    Recommendation,
    RecommendationResponse,
    UserContext,
)


def test_taste_signal():
    # Valid hard constraint taste signal
    ts = TasteSignal(
        name="max-runtime",
        value=120,
        signal_type=SignalType.HARD_CONSTRAINT,
    )
    assert ts.name == "max-runtime"
    assert ts.value == 120
    assert ts.signal_type == SignalType.HARD_CONSTRAINT
    assert ts.provenance is None

    # Valid persistent preference with provenance
    ts_persistent = TasteSignal(
        name="no-horror",
        value=True,
        signal_type=SignalType.POSSIBLE_PERSISTENT_PREFERENCE,
        provenance=SignalProvenance.EXPLICIT_STATEMENT,
    )
    assert ts_persistent.provenance == SignalProvenance.EXPLICIT_STATEMENT


def test_availability_result():
    # Valid UK streaming match
    ar = AvailabilityResult(
        status=AvailabilityStatus.AVAILABLE,
        provider="Watchmode",
        country="UK",
        matched_services=["Netflix", "BBC iPlayer"],
    )
    assert ar.status == AvailabilityStatus.AVAILABLE
    assert "Netflix" in ar.matched_services


def test_film_profile_validation():
    # Valid FilmProfile with 6 dimensions
    fp = FilmProfile(
        story_and_writing=4.5,
        pacing_and_structure=3.0,
        performances=4.0,
        tone_and_emotional_character=["warm", "funny"],
        craft_and_execution=4.2,
        accessibility_and_demandingness=2.0,
    )
    assert fp.story_and_writing == 4.5
    assert fp.tone_and_emotional_character == ["warm", "funny"]

    # Invalid FilmProfile (score out of bounds: 6.0)
    with pytest.raises(ValidationError):
        FilmProfile(
            story_and_writing=6.0,
            pacing_and_structure=3.0,
            performances=4.0,
            tone_and_emotional_character=["warm"],
            craft_and_execution=4.0,
            accessibility_and_demandingness=2.0,
        )


def test_recommendation_roles_validation():
    # Setup standard metadata and profile for testing
    meta = FilmMetadata(
        title="Inception",
        year=2010,
        director="Christopher Nolan",
        runtime_minutes=148,
        age_rating="PG-13",
        genres=["Sci-Fi", "Action"],
    )
    profile = FilmProfile(
        story_and_writing=4.8,
        pacing_and_structure=4.5,
        performances=4.6,
        tone_and_emotional_character=["tense", "thrilling"],
        craft_and_execution=4.9,
        accessibility_and_demandingness=4.0,
    )
    avail = AvailabilityResult(
        status=AvailabilityStatus.AVAILABLE,
        provider="TMDB",
        country="US",
        matched_services=["Max"],
    )

    r1 = Recommendation(
        metadata=meta,
        profile=profile,
        evidence_state=EvidenceState.STRONG_AGREEMENT,
        availability=avail,
        personal_fit_score=95,
        role=OutputRole.BEST_FIT,
        concise_reason="Excellent pacing and high craft perfectly align with Nolan fans.",
    )
    r2 = Recommendation(
        metadata=meta,
        profile=profile,
        evidence_state=EvidenceState.STRONG_AGREEMENT,
        availability=avail,
        personal_fit_score=88,
        role=OutputRole.STRONG_ALTERNATIVE,
        concise_reason="Alternative thought-provoking choice.",
    )
    r3 = Recommendation(
        metadata=meta,
        profile=profile,
        evidence_state=EvidenceState.MEANINGFUL_DISAGREEMENT,
        availability=avail,
        personal_fit_score=80,
        stretch_signal="A stretch choice for mind-bending plots.",
        role=OutputRole.WORTH_A_STRETCH,
        concise_reason="Great stretch choice if you're ready for deep plotting.",
    )
    r4 = Recommendation(
        metadata=meta,
        profile=profile,
        evidence_state=EvidenceState.SPARSE_EVIDENCE,
        availability=avail,
        personal_fit_score=75,
        role=OutputRole.RANKED_ADDITIONAL,
        concise_reason="An extra ranked candidate.",
    )

    # Validate response containing 4 items (correct roles sequence)
    res_correct = RecommendationResponse(recommendations=[r1, r2, r3, r4])
    assert res_correct.validate_roles() is True

    # Validate response with incorrect roles sequence (r4 has RANKED_ADDITIONAL at position 1)
    with pytest.raises(ValidationError):
        RecommendationResponse(recommendations=[r4, r2, r3])

    # Validate response with more than 7 items fails at the boundary
    with pytest.raises(ValidationError):
        RecommendationResponse(recommendations=[r1, r1, r1, r1, r1, r1, r1, r1])
