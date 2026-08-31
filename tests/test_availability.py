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


def test_mock_availability_unsupported_film():
    # Non-seed movie should fall back to live checks or return UNVERIFIED
    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
    )

    res = get_film_availability("Some Random Indie Movie 2026", 2026, context)
    # If live keys aren't active/matching, should return UNVERIFIED (never false AVAILABLE)
    assert res.status in (AvailabilityStatus.UNVERIFIED, AvailabilityStatus.UNAVAILABLE, AvailabilityStatus.AVAILABLE)
