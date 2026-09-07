"""
TONI Evidence Service

This module handles live movie review search and extraction using the Parallel Web SDK.
It includes dynamic prompt building, domain filtering, trace logging, and cache management.
"""

import json
import os
import sys
import time
import urllib.parse
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from parallel import Parallel

load_dotenv()

def _parallel_api_key():
    """Retrieve PARALLEL_API_KEY from environment lazily."""
    return os.environ.get("PARALLEL_API_KEY")

# Root directory of the repository
REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_LOG_PATH = REPO_ROOT / "logs" / "parallel_traces.jsonl"
CACHE_PATH = REPO_ROOT / "logs" / "evidence_cache.json"

# Substantive minimum character length for valid reviews
MIN_CONTENT_CHARS = 500

# Blocklist of aggregator, news, paywalled, or scrapable-blocking domains
BLOCKED_DOMAINS = [
    "wikipedia.org",            # Aggregator / Encyclopedic
    "imdb.com",                 # Aggregator / Database
    "rottentomatoes.com",       # Aggregator
    "metacritic.com",           # Aggregator
    "nytimes.com",              # Hard paywall
    "variety.com",              # Hard paywall & scrape-blocking
    "deadline.com",             # Industry news / scrape-blocking
    "boxofficemojo.com",        # Box office statistics
    "ticketmaster",             # Ticket listings
    "fandango.com",             # Ticket listings
    "letterboxd.com",           # Social media reviews aggregator
    "trakt.tv",                 # Tracking aggregator
    "rogerebert.com/festivals", # Filter festival diaries/schedules (keep main reviews)
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
        "office or production. Prioritise sources giving a substantive, "
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
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            
            is_blocked = False
            for blocked in BLOCKED_DOMAINS:
                if "/" in blocked:
                    # Specific subpath check (e.g. rogerebert.com/festivals)
                    if blocked in url.lower():
                        is_blocked = True
                        break
                elif "." in blocked:
                    # Precise domain matching
                    if netloc == blocked or netloc.endswith("." + blocked):
                        is_blocked = True
                        break
                else:
                    # Substring check for general keywords (e.g. ticketmaster)
                    if blocked in netloc:
                        is_blocked = True
                        break
            if is_blocked:
                continue
        except Exception:
            # Fallback to simple substring check on url if parsing fails
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
    """Append a JSON line tracking search metrics, latency, and costs to logs/parallel_traces.jsonl and stdout."""
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
    # Write to local ephemeral log file
    try:
        with open(TRACE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_data) + "\n")
    except Exception:
        pass
    # Print to stdout so Cloud Logging captures it
    print(f"[TRACE] {json.dumps(trace_data)}", flush=True)


import builtins
import os
import tempfile
import threading

if not hasattr(builtins, "_TONI_CACHE_LOCKS"):
    builtins._TONI_CACHE_LOCKS = {}

_CACHE_LOCK = builtins._TONI_CACHE_LOCKS.setdefault(str(CACHE_PATH.resolve()), threading.RLock())


def load_from_cache(title: str, year: int) -> Optional[List[Dict[str, Any]]]:
    """Load cached evidence from logs/evidence_cache.json if present and not expired."""
    with _CACHE_LOCK:
        if not CACHE_PATH.exists():
            return None
        try:
            content = CACHE_PATH.read_text(encoding="utf-8").strip()
            if not content:
                return None
            cache = json.loads(content)
            if not isinstance(cache, dict):
                return None
            key = f"{title.lower()}-{year}"
            entry = cache.get(key)
            if not entry:
                return None
            
            # Treat old-style cache entries (which are lists, not dicts with timestamp) as expired
            if isinstance(entry, list):
                return None
                
            if isinstance(entry, dict) and "data" in entry and "timestamp" in entry:
                # TTL is 24 hours (86400 seconds)
                TTL_SEC = 86400
                age = time.time() - entry["timestamp"]
                if age < TTL_SEC:
                    return entry["data"]
                    
            return None
        except Exception:
            return None


def save_to_cache(title: str, year: int, data: List[Dict[str, Any]]) -> None:
    """Save extracted evidence to logs/evidence_cache.json with a timestamp, bounding the cache to 50 items.

    Uses atomic replacement without unsafe direct overwrite fallback.
    """
    with _CACHE_LOCK:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = {}
        if CACHE_PATH.exists():
            try:
                content = CACHE_PATH.read_text(encoding="utf-8").strip()
                if content:
                    loaded = json.loads(content)
                    if isinstance(loaded, dict):
                        cache = loaded
            except Exception:
                cache = {}
        key = f"{title.lower()}-{year}"
        cache[key] = {
            "timestamp": time.time(),
            "data": data
        }
        
        # Bound the cache size to 50 entries
        if len(cache) > 50:
            sorted_keys = sorted(
                cache.keys(),
                key=lambda k: cache[k].get("timestamp", 0) if isinstance(cache[k], dict) else 0
            )
            for old_key in sorted_keys[:(len(cache) - 50)]:
                del cache[old_key]
                
        # Atomic replacement via temporary file in the same directory
        payload = json.dumps(cache, indent=2)
        tmp_fd, tmp_file_path = tempfile.mkstemp(dir=CACHE_PATH.parent, prefix="ev_cache_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
                tmp_f.write(payload)
                tmp_f.flush()
                os.fsync(tmp_f.fileno())
            os.replace(tmp_file_path, CACHE_PATH)
        except Exception:
            try:
                if os.path.exists(tmp_file_path):
                    os.remove(tmp_file_path)
            except Exception:
                pass
            raise


def get_film_evidence(
    title: str,
    year: int,
    director: str,
    force_live: bool = False,
    timeout: Optional[float] = None
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
    api_key = _parallel_api_key()
    if not api_key:
        print("[!] PARALLEL_API_KEY missing. Returning empty evidence.")
        return []

    def _is_transient_error(err: Exception) -> bool:
        status = getattr(err, "status_code", getattr(err, "http_status_code", None))
        if status in (429, 500, 502, 503, 504):
            return True
        err_str = str(err).lower()
        return any(w in err_str for w in ["timeout", "timed out", "connection", "rate limit", "502", "503", "504", "429"])

    # Enforce strict shared deadline across search, retry, and extract
    overall_budget = timeout if timeout is not None else 6.0
    deadline = time.monotonic() + overall_budget
    client = Parallel(api_key=api_key, timeout=overall_budget, max_retries=0)
    evidence_results = []
    errors_list = []
    search_id = None
    extract_id = None

    t0 = time.time()

    try:
        # 3. Parallel Search (with at most 1 bounded retry on transient error if budget permits)
        search_attempts = 0
        response = None
        while search_attempts < 2:
            remaining_for_search = deadline - time.monotonic()
            if remaining_for_search <= 0.5:
                raise TimeoutError(f"Evidence search deadline exceeded ({time.time() - t0:.2f}s elapsed)")
            try:
                response = client.search(
                    objective=build_objective(title, year, director),
                    search_queries=build_queries(title, year, director),
                    timeout=min(remaining_for_search, 3.5)
                )
                break
            except Exception as se:
                search_attempts += 1
                rem_after_err = deadline - time.monotonic()
                if search_attempts >= 2 or rem_after_err < 1.5 or not _is_transient_error(se):
                    raise se
                time.sleep(min(0.5, rem_after_err - 1.0))

        search_id = response.search_id
        session_id = response.session_id

        # 4. Filter URLs
        valid_urls = filter_search_results(response.results)
        target_urls = valid_urls[:3]  # Limit to top 3 to optimize credits & performance

        if not target_urls:
            log_trace(title, year, search_id, None, time.time() - t0, 0, 0, ["No valid URLs survived filtering."])
            return []

        # 5. Parallel Extract consuming remaining budget
        remaining_for_extract = deadline - time.monotonic()
        if remaining_for_extract <= 0.5:
            errors_list.append(f"Evidence extraction skipped: budget exhausted ({time.time() - t0:.2f}s elapsed)")
            log_trace(title, year, search_id, None, time.time() - t0, len(target_urls), 0, errors_list)
            return []

        extract_response = client.extract(
            urls=target_urls,
            session_id=session_id,
            advanced_settings={"full_content": True},
            timeout=remaining_for_extract
        )
        extract_id = extract_response.extract_id

        # Compile successful extractions
        for r in extract_response.results:
            content = r.full_content or ""
            retrieval_kind = "full_content"
            # Extract can return substantive excerpts even when full-page fetching
            # is unavailable. Keep their provenance; never invent missing text.
            if len(content) < MIN_CONTENT_CHARS:
                excerpts = getattr(r, "excerpts", [])
                excerpt_text = "\n\n".join(x for x in excerpts if isinstance(x, str)) if isinstance(excerpts, list) else ""
                if len(excerpt_text) >= MIN_CONTENT_CHARS:
                    content = excerpt_text
                    retrieval_kind = "extract_excerpts"
            # Filter out thin page-chrome successes
            if len(content) >= MIN_CONTENT_CHARS:
                evidence_results.append({
                    "url": r.url,
                    "title": r.title or "Movie Review",
                    "content": content,
                    "retrieval_kind": retrieval_kind
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

        # Cache the valid results safely without failing the extraction
        if evidence_results:
            try:
                save_to_cache(title, year, evidence_results)
            except Exception as ce:
                print(f"[!] Evidence cache save failure for '{title}': {ce}", file=sys.stderr)

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
