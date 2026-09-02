import pytest
from src.contracts import UserContext, IntakeDepth, TasteSignal, SignalType, OutputRole
from src.ranking import rank_movies, SEED_FILMS


def test_ranking_case_a_light_and_fun():
    # Persona A: Light, brisk comedy/action viewer in the UK who has access to Netflix
    # Setting allow_rent_buy=True is required because Barbie is rent-buy only in the UK
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[
            TasteSignal(name="pacing", value="brisk", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
            TasteSignal(name="demandingness", value=2.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
            TasteSignal(name="tone", value="funny", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
    assert res.validate_roles() is True

    # Best fit should be something light and fun, e.g., Barbie
    best_fit = res.recommendations[0]
    assert best_fit.role == OutputRole.BEST_FIT
    assert best_fit.metadata.title == "Barbie"


def test_ranking_case_b_heavy_and_demanding():
    # Persona B: Heavy, demanding crime/drama viewer in the US who has access to Pluto TV and Paramount+
    context = UserContext(
        country="US",
        service_access=["Paramount+", "Pluto TV"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name="demandingness", value=4.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
            TasteSignal(name="tone", value="intense", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
    assert res.validate_roles() is True

    # The Godfather is heavy, intense, demanding and matches these services
    best_fit = res.recommendations[0]
    assert best_fit.metadata.title == "The Godfather"


def test_ranking_case_c_genre_exclusions():
    # Persona C: Wants a magical fairytale, but absolutely hates Sci-Fi or Crime
    context = UserContext(
        country="US",
        # Give access to Netflix so Inception would qualify if not excluded by genre
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.GET_TO_KNOW_ME,
        tonight_signals=[
            TasteSignal(name="exclude-genre", value=["Sci-Fi", "Crime"], signal_type=SignalType.HARD_CONSTRAINT),
            TasteSignal(name="tone", value="magical", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
    assert res.validate_roles() is True

    # Ensure no Sci-Fi (Inception) or Crime (The Godfather, Pulp Fiction) entered the results
    for rec in res.recommendations:
        genres = [g.lower() for g in rec.metadata.genres]
        assert "sci-fi" not in genres
        assert "crime" not in genres

    # Spirited Away is magical, has no sci-fi/crime, and matches
    assert res.recommendations[0].metadata.title == "Spirited Away"


def test_runtime_hard_constraint():
    # User wants a film under 100 minutes (Nosferatu is 94m, others are longer)
    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[
            TasteSignal(name="max-runtime", value=100, signal_type=SignalType.HARD_CONSTRAINT),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
    for rec in res.recommendations:
        assert rec.metadata.runtime_minutes <= 100
        assert rec.metadata.title == "Nosferatu"


def test_persistent_taste_hard_constraint():
    # A hard constraint in persistent_taste filters results.
    # Exclude Crime genre in persistent taste
    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[],
        persistent_taste=[
            TasteSignal(name="exclude-genre", value=["Crime"], signal_type=SignalType.HARD_CONSTRAINT),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
    for rec in res.recommendations:
        genres = [g.lower() for g in rec.metadata.genres]
        assert "crime" not in genres


def test_soft_max_runtime_does_not_filter():
    # A soft-typed max-runtime signal does not filter results.
    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[
            TasteSignal(name="max-runtime", value=100, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    # If it didn't filter, we should have long movies recommended (e.g. Inception or The Dark Knight)
    assert len(res.recommendations) > 0
    any_long_movie = any(rec.metadata.runtime_minutes > 100 for rec in res.recommendations)
    assert any_long_movie is True


def test_invalid_demandingness_value_does_not_crash():
    # Verify that a non-numeric demandingness value does not crash the ranking engine
    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[
            TasteSignal(name="demandingness", value="quite a lot", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False)
    assert len(res.recommendations) > 0
