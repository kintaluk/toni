import pytest
from src.contracts import UserContext, IntakeDepth, AvailabilityStatus
from src.availability import normalize_service_name, get_film_availability

def test_service_normalization():
    assert normalize_service_name("Disney Plus") == "disney+"
    assert normalize_service_name("Disney+") == "disney+"
    assert normalize_service_name("Netflix") == "netflix"
    assert normalize_service_name("Amazon Prime Video") == "prime video"
    assert normalize_service_name("HBO MAX") == "max"
    assert normalize_service_name("Max") == "max"
    assert normalize_service_name("Random Service") == "random service"


def test_mock_availability_matching_service():
    # User has access to Netflix in the UK, Inception is on Netflix
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.AVAILABLE
    assert res.provider == "LocalHybridMock"
    assert "Netflix" in res.matched_services


def test_mock_availability_no_matching_service():
    # User has access to Disney+ in the UK, but Inception is on Netflix
    context = UserContext(
        country="UK",
        service_access=["Disney+"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.UNAVAILABLE
    assert len(res.matched_services) == 0


def test_mock_availability_rent_buy_disabled():
    # Inception rent/buy routes shouldn't qualify if allow_rent_buy is False
    context = UserContext(
        country="US",
        service_access=["SomeNonExistentService"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.UNAVAILABLE
    assert len(res.matched_services) == 0


def test_mock_availability_rent_buy_enabled():
    # Inception rent/buy routes should qualify if allow_rent_buy is True
    context = UserContext(
        country="US",
        service_access=["SomeNonExistentService"],
        allow_rent_buy=True,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.AVAILABLE
    assert len(res.matched_services) > 0
    assert any(s in res.matched_services for s in ["Apple TV", "Google Play", "Prime Video"])


def test_mock_availability_unsupported_film(monkeypatch):
    # Ensure no live keys are detected so we test the unverified fallback
    monkeypatch.delenv("WATCHMODE_API_KEY", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    # Non-seed movie should fall back to live checks or return UNVERIFIED
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Some Random Indie Movie 2026", 2026, context)
    # If live keys aren't active/matching, should return UNVERIFIED (never false AVAILABLE)
    assert res.status == AvailabilityStatus.UNVERIFIED


def test_mock_availability_with_env_flag(monkeypatch):
    # Set TONI_USE_MOCK_AVAILABILITY to "false" to bypass mock path
    monkeypatch.setenv("TONI_USE_MOCK_AVAILABILITY", "false")
    # Ensure no live keys are detected so we test the unverified fallback
    monkeypatch.delenv("WATCHMODE_API_KEY", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    # Inception is a seed film but with mock disabled it should fall through and return UNVERIFIED
    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.UNVERIFIED
    assert res.provider == "None"


def test_mock_availability_with_env_flag_true(monkeypatch):
    # Set TONI_USE_MOCK_AVAILABILITY explicitly to "true"
    monkeypatch.setenv("TONI_USE_MOCK_AVAILABILITY", "true")
    
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    # Inception is a seed film and should use the mock
    res = get_film_availability("Inception", 2010, context)
    assert res.status == AvailabilityStatus.AVAILABLE
    assert res.provider == "LocalHybridMock"


def test_mock_availability_year_mismatch(monkeypatch):
    # Ensure no live keys are detected so we test the unverified fallback
    monkeypatch.delenv("WATCHMODE_API_KEY", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    # Inception (2010) queried with 1999 should bypass mock and yield UNVERIFIED on live fallback (no keys)
    res = get_film_availability("Inception", 1999, context)
    assert res.status == AvailabilityStatus.UNVERIFIED
    assert res.provider == "None"
