"""
TONI Availability Service

This module handles live streaming availability verification for movies in the
UK (GB) and US markets, utilizing Watchmode as the primary provider (for direct deep links)
and TMDB as the fallback provider. It also supports a local high-fidelity mock adapter
for our seed films when API keys are absent or for local testing.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Import our contract types
sys.path.append(str(Path(__file__).resolve().parent))
from contracts import (
    AvailabilityResult,
    AvailabilityStatus,
    UserContext,
)

load_dotenv()

def _watchmode_api_key():
    """Retrieve WATCHMODE_API_KEY from environment lazily."""
    return os.environ.get("WATCHMODE_API_KEY")

def _tmdb_api_key():
    """Retrieve TMDB_API_KEY from environment lazily."""
    return os.environ.get("TMDB_API_KEY")

# --- SERVICE NAME NORMALIZATION MAP ---
# Standardizes provider names and IDs from API presets and external lookups
SERVICE_NAME_MAP = {
    # Disney
    "disney plus": "disney+",
    "disney+": "disney+",
    "disney": "disney+",
    "disney_plus": "disney+",

    # Netflix
    "netflix": "netflix",

    # Prime Video / Amazon
    "amazon prime video": "prime video",
    "amazon prime": "prime video",
    "prime video": "prime video",
    "prime_video": "prime video",
    "amazon video": "prime video",
    "amazon": "prime video",

    # Max / HBO
    "hbo max": "max",
    "hbo max amazon channel": "max",
    "max": "max",
    "hbo": "max",

    # Hulu
    "hulu": "hulu",

    # BBC
    "bbc iplayer": "bbc iplayer",
    "bbc_iplayer": "bbc iplayer",
    "iplayer": "bbc iplayer",
    "bbc": "bbc iplayer",

    # ITV
    "itvx": "itvx",
    "itv hub": "itvx",
    "itv": "itvx",

    # Channel 4
    "channel 4": "channel 4",
    "channel_4": "channel 4",
    "all 4": "channel 4",
    "all4": "channel 4",
    "4od": "channel 4",

    # My5
    "my5": "my5",
    "channel 5": "my5",

    # Peacock
    "peacock": "peacock",
    "peacock premium": "peacock",
    "peacock_premium": "peacock",

    # Apple TV
    "apple tv plus": "apple tv+",
    "apple tv+": "apple tv+",
    "apple_tv+": "apple tv+",
    "apple_tv_plus": "apple tv+",
    "apple tv": "apple tv+",
    "appletv+": "apple tv+",

    # Paramount
    "paramount plus": "paramount+",
    "paramount+": "paramount+",
    "paramount+ amazon channel": "paramount+",
    "paramount_plus": "paramount+",
    "paramount": "paramount+",

    # Pluto TV
    "pluto tv": "pluto tv",
    "pluto_tv": "pluto tv",
    "pluto": "pluto tv",
}


def normalize_service_name(name: str) -> str:
    """Normalize a streaming service name or ID to a lowercase, clean canonical format."""
    if not name:
        return ""
    name_clean = name.lower().strip()
    if name_clean in SERVICE_NAME_MAP:
        return SERVICE_NAME_MAP[name_clean]
    # Check alternate format replacing underscores and dashes with spaces
    alt = name_clean.replace("_", " ").replace("-", " ")
    return SERVICE_NAME_MAP.get(alt, alt)


def make_request(url: str, headers: dict = None) -> tuple[int, dict]:
    """Perform a safe HTTP GET request and parse JSON."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}
    except Exception as e:
        return 500, {"error": str(e)}


# --- WATCHMODE CLIENT ---

def watchmode_search(title: str, year: int) -> Optional[str]:
    """Search Watchmode for a movie and return its title_id."""
    if not _watchmode_api_key():
        return None
    safe_title = urllib.parse.quote(title)
    url = f"https://api.watchmode.com/v1/search/?apiKey={_watchmode_api_key()}&search_field=name&search_value={safe_title}&types=movie"
    code, res = make_request(url)
    if code != 200 or "error" in res:
        return None
    results = res.get("title_results", [])
    for r in results:
        if r.get("name", "").lower() == title.lower():
            if abs(r.get("year", 0) - year) <= 1:
                return str(r.get("id"))
    return None


def watchmode_get_sources(title_id: str) -> List[Dict[str, Any]]:
    """Retrieve sources for a specific Watchmode title_id."""
    if not _watchmode_api_key() or not title_id:
        return []
    url = f"https://api.watchmode.com/v1/title/{title_id}/sources/?apiKey={_watchmode_api_key()}"
    code, res = make_request(url)
    if code != 200:
        return []
    return res if isinstance(res, list) else []


# --- TMDB CLIENT ---

def tmdb_search(title: str, year: int) -> Optional[int]:
    """Search TMDB for a movie and return its unique movie ID."""
    if not _tmdb_api_key():
        return None
    safe_title = urllib.parse.quote(title)
    url = f"https://api.themoviedb.org/3/search/movie?api_key={_tmdb_api_key()}&query={safe_title}&primary_release_year={year}"
    code, res = make_request(url)
    if code != 200:
        return None
    results = res.get("results", [])
    for r in results:
        t_match = r.get("title", "").lower() == title.lower() or r.get("original_title", "").lower() == title.lower()
        if t_match:
            release_date = r.get("release_date", "")
            r_year = 0
            if release_date and len(release_date) >= 4:
                try:
                    r_year = int(release_date[:4])
                except ValueError:
                    pass
            if r_year == 0 or abs(r_year - year) <= 1:
                return r.get("id")
    return None


def tmdb_get_watch_providers(movie_id: int) -> Dict[str, Any]:
    """Retrieve watch providers for a TMDB movie ID."""
    if not _tmdb_api_key() or not movie_id:
        return {}
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers?api_key={_tmdb_api_key()}"
    code, res = make_request(url)
    if code != 200:
        return {}
    return res.get("results", {})


# --- LOCAL HIGH-FIDELITY MOCK ADAPTER ---
# Seed movie offline streaming metadata for GB and US
SEED_FILMS_AVAILABILITY = {
    "inception": {
        "GB": {
            "flatrate": ["Netflix", "Max"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        },
        "US": {
            "flatrate": ["Netflix", "Max"],
            "rent": ["Apple TV", "Google Play", "Prime Video"],
            "buy": ["Apple TV", "Google Play", "Prime Video"],
        }
    },
    "babylon": {
        "GB": {
            "flatrate": ["Channel 4"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        },
        "US": {
            "flatrate": ["Paramount+", "MGM+"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
    "the godfather": {
        "GB": {
            "flatrate": ["Paramount+"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        },
        "US": {
            "flatrate": ["Paramount+", "Pluto TV"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        }
    },
    "everything everywhere all at once": {
        "GB": {
            "flatrate": ["Netflix", "Prime Video"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        },
        "US": {
            "flatrate": ["Netflix", "Prime Video"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        }
    },
    "spirited away": {
        "GB": {
            "flatrate": ["Netflix"],
            "rent": ["Apple TV"],
            "buy": ["Apple TV"],
        },
        "US": {
            "flatrate": ["Netflix"],
            "rent": ["Apple TV", "Google Play"],
            "buy": ["Apple TV", "Google Play"],
        }
    },
    "pulp fiction": {
        "GB": {
            "flatrate": ["Netflix", "Paramount+"],
            "rent": ["Apple TV"],
            "buy": ["Apple TV"],
        },
        "US": {
            "flatrate": ["Paramount+", "Pluto TV"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
    "parasite": {
        "GB": {
            "flatrate": ["Netflix"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        },
        "US": {
            "flatrate": ["Max"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
    "the dark knight": {
        "GB": {
            "flatrate": ["Netflix", "Max"],
            "rent": ["Apple TV"],
            "buy": ["Apple TV"],
        },
        "US": {
            "flatrate": ["Max", "Netflix"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
    "barbie": {
        "GB": {
            "flatrate": [],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        },
        "US": {
            "flatrate": ["Max"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
    "nosferatu": {
        "GB": {
            "flatrate": ["Pluto TV"],
            "rent": ["Apple TV"],
            "buy": ["Apple TV"],
        },
        "US": {
            "flatrate": ["Netflix"],
            "rent": ["Apple TV", "Prime Video"],
            "buy": ["Apple TV", "Prime Video"],
        }
    },
}


# Canonical release years for the 10 seed films
SEED_FILMS_YEARS = {
    "inception": 2010,
    "babylon": 2022,
    "the godfather": 1972,
    "everything everywhere all at once": 2022,
    "spirited away": 2001,
    "pulp fiction": 1994,
    "parasite": 2019,
    "the dark knight": 2008,
    "barbie": 2023,
    "nosferatu": 1922,
}


def get_mock_availability(title: str, year: int, country: str, context: UserContext) -> Optional[AvailabilityResult]:
    """Get high-fidelity mock streaming availability for seed pool titles."""
    title_lower = title.lower().strip()
    if title_lower not in SEED_FILMS_AVAILABILITY:
        return None

    # Check release year mismatch to avoid wrong-film match on seed pool
    if title_lower in SEED_FILMS_YEARS:
        if abs(SEED_FILMS_YEARS[title_lower] - year) > 1:
            return None

    film_data = SEED_FILMS_AVAILABILITY[title_lower]
    market_data = film_data.get(country, {})

    matched_services = []

    # 1. Flatrate/Subscription
    flat_services = market_data.get("flatrate", [])
    for s in flat_services:
        norm_s = normalize_service_name(s)
        if any(normalize_service_name(u_s) == norm_s for u_s in context.service_access):
            matched_services.append(s)

    # 2. Rent and Buy
    if context.allow_rent_buy:
        rent_services = market_data.get("rent", [])
        buy_services = market_data.get("buy", [])
        matched_services.extend(rent_services)
        matched_services.extend(buy_services)

    matched_services = list(set(matched_services))  # De-duplicate

    status = AvailabilityStatus.AVAILABLE if matched_services else AvailabilityStatus.UNAVAILABLE

    return AvailabilityResult(
        status=status,
        provider="LocalHybridMock",
        country=country,
        matched_services=matched_services,
    )


# --- MAIN ENDPOINT ---

def get_film_availability(title: str, year: int, context: UserContext) -> AvailabilityResult:
    """Check a film's availability in the user's country using active keys,

    falling back to the local hybrid mock for seed films or returning unverified on failure.
    """
    user_country = "UK" if context.country.upper() in ("UK", "GB") else "US"
    api_country = "GB" if user_country == "UK" else "US"

    # Evaluate TONI_USE_MOCK_AVAILABILITY flag
    env_use_mock = os.environ.get("TONI_USE_MOCK_AVAILABILITY")
    has_live_keys = bool(_watchmode_api_key() or _tmdb_api_key())
    
    if env_use_mock is not None:
        use_mock = env_use_mock.lower() in ("true", "1")
    else:
        # Default to live when keys are present, and to mock when they are not
        use_mock = not has_live_keys

    if use_mock:
        # Try local mock first to ensure rapid, credentials-free evaluation of seed pool
        mock_res = get_mock_availability(title, year, api_country, context)
        if mock_res:
            mock_res.country = user_country
            return mock_res

    # Fallback to Live Watchmode API
    if _watchmode_api_key():
        try:
            title_id = watchmode_search(title, year)
            if title_id:
                sources = watchmode_get_sources(title_id)
                matched_services = []
                for s in sources:
                    if s.get("region") != api_country:
                        continue

                    source_name = s.get("name", "")
                    source_type = s.get("type", "")

                    if source_type in ("sub", "free"):
                        norm_s = normalize_service_name(source_name)
                        if any(normalize_service_name(u_s) == norm_s for u_s in context.service_access):
                            matched_services.append(source_name)
                    elif source_type in ("purchase", "rent") and context.allow_rent_buy:
                        matched_services.append(source_name)

                matched_services = list(set(matched_services))
                status = AvailabilityStatus.AVAILABLE if matched_services else AvailabilityStatus.UNAVAILABLE
                return AvailabilityResult(
                    status=status,
                    provider="Watchmode",
                    country=user_country,
                    matched_services=matched_services,
                )
        except Exception:
            # Fall through to TMDB on failure or unverified
            pass

    # Fallback to Live TMDB API
    if _tmdb_api_key():
        try:
            movie_id = tmdb_search(title, year)
            if movie_id:
                providers = tmdb_get_watch_providers(movie_id)
                market_providers = providers.get(api_country, {})
                matched_services = []

                # flatrate / subscription
                flat_list = market_providers.get("flatrate", [])
                for p in flat_list:
                    p_name = p.get("provider_name", "")
                    norm_s = normalize_service_name(p_name)
                    if any(normalize_service_name(u_s) == norm_s for u_s in context.service_access):
                        matched_services.append(p_name)

                # free / ads
                ads_list = market_providers.get("ads", [])
                for p in ads_list:
                    p_name = p.get("provider_name", "")
                    norm_s = normalize_service_name(p_name)
                    if any(normalize_service_name(u_s) == norm_s for u_s in context.service_access):
                        matched_services.append(p_name)

                # rent and buy
                if context.allow_rent_buy:
                    for category in ("rent", "buy"):
                        cat_list = market_providers.get(category, [])
                        for p in cat_list:
                            matched_services.append(p.get("provider_name", ""))

                matched_services = list(set(matched_services))
                status = AvailabilityStatus.AVAILABLE if matched_services else AvailabilityStatus.UNAVAILABLE
                return AvailabilityResult(
                    status=status,
                    provider="TMDB",
                    country=user_country,
                    matched_services=matched_services,
                )
        except Exception:
            pass

    # If keys are missing and it is not in the mock seed database, return unverified
    return AvailabilityResult(
        status=AvailabilityStatus.UNVERIFIED,
        provider="None",
        country=user_country,
        matched_services=[],
    )


# --- CANONICAL SEED POSTER ARTWORK MAP ---
SEED_POSTERS: Dict[str, str] = {
    "inception": "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    "babylon": "https://image.tmdb.org/t/p/w500/wjOHjWCUE0YzDiEzKv8AfqHj3ir.jpg",
    "the godfather": "https://image.tmdb.org/t/p/w500/3bhkrj58Vtu7enYsRolD1fZdja1.jpg",
    "everything everywhere all at once": "https://image.tmdb.org/t/p/w500/w3LxiVYPqrlxqPYSUTNNZNaPnBv.jpg",
    "spirited away": "https://image.tmdb.org/t/p/w500/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
    "pulp fiction": "https://image.tmdb.org/t/p/w500/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
    "parasite": "https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg",
    "the dark knight": "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    "whiplash": "https://image.tmdb.org/t/p/w500/7fn624j5lj3xTme2SgiLCeuedmO.jpg",
    "barbie": "https://image.tmdb.org/t/p/w500/iuFNMS8U5cb6xfzi51Dbkovj7vM.jpg",
    "nosferatu": "https://image.tmdb.org/t/p/w500/1pDjhU3kvdG31i5b4b1a3oWkCsh.jpg",
    "paddington 2": "https://image.tmdb.org/t/p/w500/ebd57Xh84O8q1e8cQ6Q4i6zP4bA.jpg",
}

_POSTER_CACHE: Dict[str, Optional[str]] = {}


def get_film_poster_url(title: str, year: int) -> Optional[str]:
    """Retrieve poster image URL for a film using TMDB or Watchmode, with canonical seed fallback.

    Returns full-resolution image URL e.g. 'https://image.tmdb.org/t/p/w500/...' or None.
    """
    key = f"{title.lower().strip()}_{year}"
    if key in _POSTER_CACHE:
        return _POSTER_CACHE[key]

    clean_title = title.lower().strip()
    if clean_title in SEED_POSTERS:
        _POSTER_CACHE[key] = SEED_POSTERS[clean_title]
        return SEED_POSTERS[clean_title]

    # 1. Try TMDB search for poster_path
    if _tmdb_api_key():
        try:
            safe_title = urllib.parse.quote(title)
            url = f"https://api.themoviedb.org/3/search/movie?api_key={_tmdb_api_key()}&query={safe_title}&primary_release_year={year}"
            code, res = make_request(url)
            if code == 200:
                results = res.get("results", [])
                for r in results:
                    poster_path = r.get("poster_path")
                    if poster_path:
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                        _POSTER_CACHE[key] = poster_url
                        return poster_url
        except Exception:
            pass

    # 2. Try Watchmode search for poster / image_url
    if _watchmode_api_key():
        try:
            safe_title = urllib.parse.quote(title)
            url = f"https://api.watchmode.com/v1/search/?apiKey={_watchmode_api_key()}&search_field=name&search_value={safe_title}&types=movie"
            code, res = make_request(url)
            if code == 200:
                results = res.get("title_results", [])
                for r in results:
                    poster = r.get("poster") or r.get("image_url")
                    if poster:
                        _POSTER_CACHE[key] = poster
                        return poster
        except Exception:
            pass

    _POSTER_CACHE[key] = None
    return None


# --- CANONICAL SEED TRAILER MAP ---
SEED_TRAILERS: Dict[str, str] = {
    "inception": "https://www.youtube.com/watch?v=YoHD9XEInc0",
    "babylon": "https://www.youtube.com/watch?v=5muIQDEmXkU",
    "the godfather": "https://www.youtube.com/watch?v=UaVTIH8mujA",
    "everything everywhere all at once": "https://www.youtube.com/watch?v=wxN1T1uxQ2g",
    "spirited away": "https://www.youtube.com/watch?v=ByXuk9QqQkk",
    "pulp fiction": "https://www.youtube.com/watch?v=s7EdQ4FqbhY",
    "parasite": "https://www.youtube.com/watch?v=5xH0hhMbQW9",
    "the dark knight": "https://www.youtube.com/watch?v=EXeTwQWrcwY",
    "whiplash": "https://www.youtube.com/watch?v=7d_jQycdQGo",
    "barbie": "https://www.youtube.com/watch?v=pBk4NYhWNMM",
    "nosferatu": "https://www.youtube.com/watch?v=d_k8qF82XyE",
    "paddington 2": "https://www.youtube.com/watch?v=52x5HJ9PBvM",
}

_TRAILER_CACHE: Dict[str, Optional[str]] = {}


def get_film_trailer_url(title: str, year: int) -> Optional[str]:
    """Retrieve trailer URL for a film using canonical seed fallback or external lookups."""
    key = f"{title.lower().strip()}_{year}"
    if key in _TRAILER_CACHE:
        return _TRAILER_CACHE[key]

    clean_title = title.lower().strip()
    if clean_title in SEED_TRAILERS:
        _TRAILER_CACHE[key] = SEED_TRAILERS[clean_title]
        return SEED_TRAILERS[clean_title]

    # Try TMDB for video / trailer key
    if _tmdb_api_key():
        try:
            safe_title = urllib.parse.quote(title)
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={_tmdb_api_key()}&query={safe_title}&primary_release_year={year}"
            code, res = make_request(search_url)
            if code == 200 and res.get("results"):
                movie_id = res["results"][0].get("id")
                if movie_id:
                    videos_url = f"https://api.themoviedb.org/3/movie/{movie_id}/videos?api_key={_tmdb_api_key()}"
                    v_code, v_res = make_request(videos_url)
                    if v_code == 200 and v_res.get("results"):
                        for vid in v_res["results"]:
                            if vid.get("site") == "YouTube" and vid.get("type") in ("Trailer", "Teaser") and vid.get("key"):
                                trailer_url = f"https://www.youtube.com/watch?v={vid['key']}"
                                _TRAILER_CACHE[key] = trailer_url
                                return trailer_url
        except Exception:
            pass

    _TRAILER_CACHE[key] = None
    return None

