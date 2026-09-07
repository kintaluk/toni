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


from unittest.mock import MagicMock, patch

@patch("evidence.Parallel")
def test_ranking_force_live_evidence_reaches_parallel(mock_parallel_class, monkeypatch, tmp_path):
    # Set TRACE_LOG_PATH to a temporary file to prevent polluting the real evidence log file.
    # We patch both "src.evidence" and "evidence" since they may be imported differently.
    temp_trace_path = tmp_path / "parallel_traces.jsonl"
    monkeypatch.setattr("src.evidence.TRACE_LOG_PATH", temp_trace_path)
    monkeypatch.setattr("evidence.TRACE_LOG_PATH", temp_trace_path)
    monkeypatch.setenv("PARALLEL_API_KEY", "dummy_key")
    
    mock_client = MagicMock()
    mock_parallel_class.return_value = mock_client
    
    mock_search_response = MagicMock()
    mock_search_response.search_id = "mock_search_id"
    mock_search_response.session_id = "live_session_id"
    
    class StubSearchItem:
        def __init__(self, url):
            self.url = url
            
    mock_search_response.results = [
        StubSearchItem("https://www.theguardian.com/film/review/live_test")
    ]
    mock_client.search.return_value = mock_search_response
    
    class StubExtractItem:
        def __init__(self, url, title, full_content):
            self.url = url
            self.title = title
            self.full_content = full_content
            
    mock_extract_response = MagicMock()
    mock_extract_response.extract_id = "mock_extract_id"
    mock_extract_response.results = [
        StubExtractItem("https://www.theguardian.com/film/review/live_test", "Live Test Review", "Review content here that is long enough to bypass thin check " * 10)
    ]
    mock_extract_response.errors = []
    mock_client.extract.return_value = mock_extract_response

    context = UserContext(
        country="US",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )
    
    # Run rank_movies with force_live_evidence=True
    res = rank_movies(context, force_live_evidence=True)
    
    # Verify that the parallel client was instantiated and search was called
    assert mock_client.search.call_count > 0


def test_ranking_unverified_exclusion_count(monkeypatch):
    from contracts import AvailabilityResult, AvailabilityStatus
    
    # Mock get_film_availability to return UNVERIFIED for "Inception" and "Babylon"
    # and AVAILABLE for others.
    def mock_get_film_availability(title, year, context, timeout=6.0):
        if title in ["Inception", "Babylon"]:
            return AvailabilityResult(status=AvailabilityStatus.UNVERIFIED, provider="Watchmode", country="US")
        elif title in ["The Godfather"]:
            return AvailabilityResult(status=AvailabilityStatus.AVAILABLE, provider="Watchmode", country="US", matched_services=["Paramount+"])
        else:
            return AvailabilityResult(status=AvailabilityStatus.UNAVAILABLE, provider="Watchmode", country="US")

    monkeypatch.setattr("src.ranking.get_film_availability", mock_get_film_availability)

    context = UserContext(
        country="US",
        service_access=["Paramount+"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    res = rank_movies(context, force_live_evidence=False)
    # Inception and Babylon should be excluded as unverified
    assert res.unverified_excluded_count == 2
    assert res.unverified_excluded_titles == ["Inception (2010)", "Babylon (2022)"]
    # Only The Godfather is available
    assert len(res.recommendations) == 1
    assert res.recommendations[0].metadata.title == "The Godfather"


def test_discover_candidates_fallback():
    """Verify discover_candidates_with_gemini safely returns fallback metadata if API key is absent."""
    from src.ranking import discover_candidates_with_gemini
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )
    candidates = discover_candidates_with_gemini(context)
    assert len(candidates) >= 5
    assert all(hasattr(c, "title") and hasattr(c, "genres") for c in candidates)


def test_live_pipeline_ranking_execution(monkeypatch):
    """Verify live pipeline candidate discovery, availability gating, evidence lookup, and role assignment."""
    monkeypatch.setenv("PARALLEL_API_KEY", "mock-parallel-key")
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    from contracts import AvailabilityResult, AvailabilityStatus, FilmMetadata, FilmProfile, EvidenceState
    from src.ranking import rank_movies, DiscoveredCandidate

    # Create 15 mock candidate films
    mock_candidates = [
        FilmMetadata(
            title=f"Film {i}",
            year=2020 + (i % 4),
            director=f"Director {i}",
            runtime_minutes=100 + (i * 2),
            age_rating="15",
            genres=["Drama"] if i % 2 == 0 else ["Comedy"]
        )
        for i in range(15)
    ]

    monkeypatch.setattr("src.ranking.discover_candidates_with_gemini", lambda ctx, **kwargs: mock_candidates)

    # Availability gate: only films 0, 1, 2, 3 survive
    def mock_get_film_availability(title, year, context, timeout=6.0):
        if title in ["Film 0", "Film 1", "Film 2", "Film 3"]:
            return AvailabilityResult(
                status=AvailabilityStatus.AVAILABLE,
                provider="Watchmode",
                country=context.country,
                matched_services=["Netflix"]
            )
        return AvailabilityResult(
            status=AvailabilityStatus.UNAVAILABLE,
            provider="Watchmode",
            country=context.country
        )

    monkeypatch.setattr("src.ranking.get_film_availability", mock_get_film_availability)

    # Evidence and Profiling mocks
    monkeypatch.setattr(
        "src.ranking.get_film_evidence",
        lambda title, year, director, force_live, timeout: [{"url": f"https://example.com/reviews/{title.lower().replace(' ', '-')}"}]
    )

    def mock_generate_profile(title, year, director, reviews, deadline=None):
        return (
            FilmProfile(
                story_and_writing=4.2,
                pacing_and_structure=4.0,
                performances=4.5,
                craft_and_execution=4.3,
                accessibility_and_demandingness=2.5,
                tone_and_emotional_character=["engaging"]
            ),
            EvidenceState.STRONG_AGREEMENT,
            f"Paraphrased consensus for {title}."
        )

    monkeypatch.setattr("src.ranking.generate_film_profile", mock_generate_profile)

    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    res = rank_movies(context, force_live_evidence=False, use_live_pipeline=True)

    assert len(res.recommendations) == 4
    roles = [r.role for r in res.recommendations]
    assert OutputRole.BEST_FIT in roles
    assert OutputRole.STRONG_ALTERNATIVE in roles
    # Check that evidence URLs were populated
    assert all(len(r.evidence_sources) > 0 for r in res.recommendations)


def test_live_pipeline_availability_gate_before_parallel(monkeypatch):
    """Verify that get_film_evidence is strictly called ONLY for films that pass availability gating."""
    monkeypatch.setenv("PARALLEL_API_KEY", "mock-parallel-key")
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    from contracts import AvailabilityResult, AvailabilityStatus, FilmMetadata, FilmProfile, EvidenceState
    from src.ranking import rank_movies

    # 15 discovered candidates
    mock_candidates = [
        FilmMetadata(
            title=f"Discovered Movie {i}",
            year=2021,
            director=f"Director {i}",
            runtime_minutes=105,
            age_rating="12",
            genres=["Action"] if i % 2 == 0 else ["Drama"]
        )
        for i in range(15)
    ]
    monkeypatch.setattr("src.ranking.discover_candidates_with_gemini", lambda ctx, **kwargs: mock_candidates)

    checked_availability = []
    # Only movies 2, 4, 6 are available; rest are unavailable
    def mock_get_film_availability(title, year, context, timeout=6.0):
        checked_availability.append(title)
        if title in ["Discovered Movie 2", "Discovered Movie 4", "Discovered Movie 6"]:
            return AvailabilityResult(
                status=AvailabilityStatus.AVAILABLE,
                provider="Watchmode",
                country=context.country,
                matched_services=["Netflix"]
            )
        return AvailabilityResult(status=AvailabilityStatus.UNAVAILABLE, provider="Watchmode", country=context.country)

    monkeypatch.setattr("src.ranking.get_film_availability", mock_get_film_availability)

    searched_parallel = []
    def mock_get_film_evidence(title, year, director, force_live, timeout):
        searched_parallel.append(title)
        return [{"url": f"https://example.com/{title}"}]

    monkeypatch.setattr("src.ranking.get_film_evidence", mock_get_film_evidence)

    def mock_generate_profile(title, year, director, reviews, deadline=None):
        return (
            FilmProfile(
                story_and_writing=4.0,
                pacing_and_structure=4.0,
                performances=4.0,
                craft_and_execution=4.0,
                accessibility_and_demandingness=2.0,
                tone_and_emotional_character=["thrilling"]
            ),
            EvidenceState.STRONG_AGREEMENT,
            f"Consensus for {title}"
        )

    monkeypatch.setattr("src.ranking.generate_film_profile", mock_generate_profile)

    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    res = rank_movies(context, force_live_evidence=True, use_live_pipeline=True)

    # All 15 candidates must have been checked for availability
    assert len(checked_availability) == 15

    # Parallel search must ONLY have been called for the available survivors (Movie 2, 4, 6)
    assert len(searched_parallel) == 3
    assert set(searched_parallel) == {"Discovered Movie 2", "Discovered Movie 4", "Discovered Movie 6"}

    # Final recommendations contain exactly the 3 available films
    assert len(res.recommendations) == 3
    rec_titles = {r.metadata.title for r in res.recommendations}
    assert rec_titles == {"Discovered Movie 2", "Discovered Movie 4", "Discovered Movie 6"}


def test_seed_fallback_when_live_pipeline_disabled():
    """Verify that rank_movies uses deterministic SEED_FILMS when use_live_pipeline=False."""
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )
    res = rank_movies(context, force_live_evidence=False, use_live_pipeline=False)
    # Seed films include Barbie, Paddington 2, etc.
    assert len(res.recommendations) > 0
    seed_titles = {s["metadata"]["title"] for s in SEED_FILMS}
    assert all(r.metadata.title in seed_titles for r in res.recommendations)


def test_candidate_pool_refill_guarantees_top_3(monkeypatch):
    """Verify that if live availability filtering leaves < 3 candidates, pool is refilled from SEED_FILMS."""
    from contracts import AvailabilityResult, AvailabilityStatus, FilmMetadata
    from src.ranking import rank_movies

    # 10 discovered mock candidates
    mock_candidates = [
        FilmMetadata(
            title=f"Discovered Film {i}",
            year=2021,
            director="Director A",
            runtime_minutes=110,
            age_rating="12",
            genres=["Drama"]
        )
        for i in range(10)
    ]

    monkeypatch.setenv("PARALLEL_API_KEY", "mock-parallel-key")
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")

    monkeypatch.setattr("src.ranking.discover_candidates_with_gemini", lambda ctx, **kwargs: mock_candidates)

    # Only 1 discovered candidate survives availability
    def mock_availability(title, year, ctx, timeout=6.0):
        if title == "Discovered Film 0":
            return AvailabilityResult(status=AvailabilityStatus.AVAILABLE, provider="Mock", country="UK", matched_services=["Netflix"])
        elif title.startswith("Discovered"):
            return AvailabilityResult(status=AvailabilityStatus.UNAVAILABLE, provider="Mock", country="UK")
        # For seed films, return available for Barbie and Paddington 2
        return AvailabilityResult(status=AvailabilityStatus.AVAILABLE, provider="Mock", country="UK", matched_services=["Netflix"])

    monkeypatch.setattr("src.ranking.get_film_availability", mock_availability)
    monkeypatch.setattr("src.ranking.get_film_evidence", lambda **kwargs: [{"url": "https://theguardian.com/film/review", "text": "Stunning."}])

    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
        tonight_signals=[]
    )

    res = rank_movies(context, force_live_evidence=False, use_live_pipeline=True)
    # Refill must guarantee at least 3 candidates in the shortlist
    assert len(res.recommendations) >= 3
    titles = [r.metadata.title for r in res.recommendations]
    assert "Discovered Film 0" in titles



