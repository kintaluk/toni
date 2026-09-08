"""Stream review enrichment independently of discovery and availability.

Updates are keyed by position and film identity. They never replace or rerank the
shortlist. Both transport waiting and actual upstream concurrency are bounded.
"""
import asyncio
import atexit
import logging
import threading
import time
from urllib.parse import urlparse
from typing import List

from pydantic import BaseModel, Field

from contracts import FilmMetadata
from evidence import get_film_evidence
from gemini_client import get_gemini_client
from profiling import generate_film_profile
from runtime_budget import BoundedExecutor

logger = logging.getLogger(__name__)
REVIEW_EXECUTOR = BoundedExecutor(max_workers=8)
_client_lock = threading.Lock()
_review_client = None


def get_review_client():
    """Reuse the connection pool; cold TLS setup must not compete per film."""
    global _review_client
    with _client_lock:
        if _review_client is None:
            _review_client = get_gemini_client()
        return _review_client


@atexit.register
def close_review_client():
    if _review_client is not None:
        _review_client.close()


class ReviewRequest(BaseModel):
    films: List[FilmMetadata] = Field(min_length=1, max_length=7)


async def _call(fn, wait_seconds, **kwargs):
    future = REVIEW_EXECUTOR.submit(fn, **kwargs)
    if future is None:
        raise TimeoutError("Review capacity is busy")
    try:
        return await asyncio.wait_for(asyncio.wrap_future(future), wait_seconds)
    finally:
        future.cancel()


async def stream_review_updates(films):
    queue = asyncio.Queue()
    client_task = None

    async def review_one(index, film):
        nonlocal client_task
        identity = dict(index=index, title=film.title, year=film.year)
        reviews = []
        attempted_urls = set()
        stage = "retrieval"

        async def emit(status, **fields):
            await queue.put(dict(identity, review_status=status, **fields))

        try:
            for expanded, budget in ((False, 8.0), (True, 15.0)):
                if expanded:
                    await emit("searching_more", review_failure="retrieval",
                               evidence_sources=[r["url"] for r in reviews])
                try:
                    found = await _call(
                        get_film_evidence, budget + 0.2, title=film.title,
                        year=film.year, director=film.director,
                        force_live=expanded, timeout=budget, expanded=expanded,
                        attempted_urls=attempted_urls,
                    )
                    by_url = {r["url"]: r for r in reviews + found}
                    reviews = list(by_url.values())
                except Exception:
                    logger.exception("Review retrieval failed for %s (%s)", film.title, film.year)
                if len({urlparse(r["url"]).netloc.removeprefix("www.") for r in reviews}) >= 2:
                    break
            if not reviews:
                await emit("unavailable", review_failure="retrieval", evidence_sources=[])
                return
            stage = "synthesis"
            sources = list(dict.fromkeys(r["url"] for r in reviews))
            if client_task is None:
                client_task = asyncio.create_task(_call(get_review_client, 10.5))
            client = await asyncio.shield(client_task)
            for attempt in range(2):
                try:
                    profile, state, rationale = await _call(
                        generate_film_profile, 11.5, title=film.title,
                        year=film.year, director=film.director, reviews=reviews,
                        client=client, deadline=time.monotonic() + 11.0,
                    )
                    await emit("complete", profile=profile.model_dump(),
                               evidence_state=state.value, consensus_rationale=rationale,
                               evidence_sources=sources, review_failure=None)
                    return
                except Exception:
                    logger.exception("Review synthesis failed for %s (%s)", film.title, film.year)
                    if attempt == 0:
                        await emit("searching_more", review_failure="synthesis", evidence_sources=sources)
            await emit("unavailable", review_failure="synthesis", evidence_sources=sources)
        except Exception:
            logger.exception("Review update failed for %s (%s)", film.title, film.year)
            await emit("unavailable", review_failure=stage,
                       evidence_sources=[r["url"] for r in reviews])
        finally:
            await queue.put(None)

    tasks = [asyncio.create_task(review_one(i, film)) for i, film in enumerate(films)]
    finished = 0
    try:
        # A separate phase budget: slow criticism never holds back usable films.
        async with asyncio.timeout(60):
            while finished < len(tasks):
                update = await queue.get()
                if update is None:
                    finished += 1
                else:
                    yield update
    except TimeoutError:
        yield {"review_status": "interrupted"}
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if client_task:
            client_task.cancel()
            await asyncio.gather(client_task, return_exceptions=True)
