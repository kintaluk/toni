"""
TONI Evidence Service

This module handles live movie review search and extraction using the Parallel Web SDK.
It includes dynamic prompt building, domain filtering, trace logging, and cache management.
"""

import json
import os
import sys
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from parallel import Parallel

load_dotenv()

PARALLEL_API_KEY = os.environ.get("PARALLEL_API_KEY")

# Root directory of the repository
REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_LOG_PATH = REPO_ROOT / "logs" / "parallel_traces.jsonl"
CACHE_PATH = REPO_ROOT / "logs" / "evidence_cache.json"

# Substantive minimum character length for valid reviews
MIN_CONTENT_CHARS = 500

# Blocklist of aggregator, news, paywalled, or scrapable-blocking domains
BLOCKED_DOMAINS = [
    "wikipedia.org",
    "imdb.com",
    "rottentomatoes.com",
    "metacritic.com",
    "nytimes.com",
    "variety.com",
    "deadline.com",
    "boxofficemojo.com",
    "ticketmaster",
    "fandango.com",
    "letterboxd.com",
    "trakt.tv",
    "rogerebert.com/festivals",  # Keep main RogerEbert reviews but filter festival schedules
]


def build_objective(title: str, year: int, director: str) -> str:
    """Generate the highly specialized search objective used to find professional critical reviews."""
    return (
        f'Find professional film critic reviews of the {year} film "'
        f'{title}", directed by {director}. Only reviews '
        "written by professional critics at recognised publications (newspapers, "
        "magazines, or established film review outlets) count. Exclude fan forum "
        "posts, message board discussions, plot summary or synopsis pages, ticket "
        "or showtime listings, and general news coverage about the film's box "
        "office or production. The film received a genuinely divided critical "
        "reception on release, so prioritise sources giving a substantive, "
        "opinionated critical assessment of the film's quality, whether positive "
        "or negative, rather than a neutral plot description."
    )


def build_queries(title: str, year: int, director: str) -> List[str]:
    """Generate the precise query variations for Parallel Search."""
    return [
        f"{title} {year} movie review",
        f"{title} film critic review",
        f"{title} {director} review reception",
    ]


def filter_search_results(results: List[Any]) -> List[str]:
    """Filter search result URLs to exclude aggregators, ticket listings, and blocked domains."""
    valid_urls = []
    for r in results:
        url = r.url
        # Check if URL matches any blocked domain
        if any(blocked in url.lower() for blocked in BLOCKED_DOMAINS):
            continue
        valid_urls.append(url)
    return valid_urls


def log_trace(
    title: str,
    year: int,
    search_id: Optional[str],
    extract_id: Optional[str],
    latency_sec: float,
    success_count: int,
    error_count: int,
    errors: List[str]
) -> None:
    """Append a JSON line tracking search metrics, latency, and costs to logs/parallel_traces.jsonl."""
    TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    trace_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "year": year,
        "search_id": search_id or "N/A",
        "extract_id": extract_id or "N/A",
        "latency_sec": round(latency_sec, 2),
        "success_count": success_count,
        "error_count": error_count,
        "errors": errors,
        "estimated_credits": 1 + (success_count + error_count)  # 1 search + 1 per extracted URL
    }
    with open(TRACE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(trace_data) + "\n")


def load_from_cache(title: str, year: int) -> Optional[List[Dict[str, Any]]]:
    """Load cached evidence from logs/evidence_cache.json if present."""
    if not CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        key = f"{title.lower()}-{year}"
        return cache.get(key)
    except Exception:
        return None


def save_to_cache(title: str, year: int, data: List[Dict[str, Any]]) -> None:
    """Save extracted evidence to logs/evidence_cache.json."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    key = f"{title.lower()}-{year}"
    cache[key] = data
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_film_evidence(
    title: str,
    year: int,
    director: str,
    force_live: bool = False
) -> List[Dict[str, Any]]:
    """Retrieve extracted review contents for a film.

    Performs dynamic live lookup using Parallel Search & Extract, with trace logging and caching.
    """
    # 1. Try cache if force_live is False
    if not force_live:
        cached = load_from_cache(title, year)
        if cached:
            return cached

    # 2. Check for PARALLEL_API_KEY
    if not PARALLEL_API_KEY:
        print("[!] PARALLEL_API_KEY missing. Returning empty evidence.")
        return []

    # Initialize client
    client = Parallel()
    evidence_results = []
    errors_list = []
    search_id = None
    extract_id = None

    t0 = time.time()

    try:
        # 3. Parallel Search
        response = client.search(
            objective=build_objective(title, year, director),
            search_queries=build_queries(title, year, director)
        )
        search_id = response.search_id
        session_id = response.session_id

        # 4. Filter URLs
        valid_urls = filter_search_results(response.results)
        target_urls = valid_urls[:5]  # Limit to top 5 to optimize credits & performance

        if not target_urls:
            log_trace(title, year, search_id, None, time.time() - t0, 0, 0, ["No valid URLs survived filtering."])
            return []

        # 5. Parallel Extract
        extract_response = client.extract(
            urls=target_urls,
            session_id=session_id,
            advanced_settings={"full_content": True}
        )
        extract_id = extract_response.extract_id

        # Compile successful extractions
        for r in extract_response.results:
            content = r.full_content or ""
            # Filter out thin page-chrome successes
            if len(content) >= MIN_CONTENT_CHARS:
                evidence_results.append({
                    "url": r.url,
                    "title": r.title or "Movie Review",
                    "content": content
                })
            else:
                errors_list.append(f"Excluded thin content from URL: {r.url} ({len(content)} chars)")

        # Compile failed extractions
        for e in extract_response.errors:
            errors_list.append(f"Failed to extract {e.url}: {e.error_type} (HTTP {e.http_status_code})")

        latency = time.time() - t0
        log_trace(
            title=title,
            year=year,
            search_id=search_id,
            extract_id=extract_id,
            latency_sec=latency,
            success_count=len(evidence_results),
            error_count=len(target_urls) - len(evidence_results),
            errors=errors_list
        )

        # Cache the valid results
        if evidence_results:
            save_to_cache(title, year, evidence_results)

        return evidence_results

    except Exception as e:
        latency = time.time() - t0
        log_trace(
            title=title,
            year=year,
            search_id=search_id,
            extract_id=None,
            latency_sec=latency,
            success_count=0,
            error_count=0,
            errors=[f"Unexpected error: {str(e)}"]
        )
        return []
