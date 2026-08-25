"""Brief 1 Step 4: extract full review content from the best 3-5 URLs.

Source set approved by Nate after review of Step 3's raw search output. Only
2 of Step 3's 10 search results were actually extractable professional
reviews (RogerEbert, Guardian, both negative-leaning); Variety, Deadline and
NYT returned page chrome rather than review text (Variety/Deadline are
Tollbit-gated, NYT unfetchable), and Wikipedia/Rotten Tomatoes/IndieWire are
aggregator or news-about-the-film pages the brief's Step 3 objective already
excludes. The 3 remaining URLs below were found and verified as live,
extractable, professional reviews via manual research rather than a second
Parallel search call, to supply the professional rave that set was missing.

advanced_settings={"full_content": True} is required here: without it,
extract returns relevance-compressed excerpts rather than clean page
content, which is what the brief's Step 4 actually asks for.

Failed sources (paywall, bot-blocked) are logged and skipped, not fatal, per
the brief; the Extract API already returns per-URL failures in `errors`
without failing the whole batch. MIN_CONTENT_CHARS is an additional,
pragmatic sanity check (not a documented API guarantee): a source can come
back as an API "success" that is actually just navigation chrome, as
happened with 3 of Step 3's 5 "good" results, so thin content is flagged
rather than silently treated as a usable review.
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from parallel import Parallel

MIN_CONTENT_CHARS = 500

# (url, critic, outlet, expected polarity from Step 3's review discussion)
SOURCES = [
    (
        "https://www.avclub.com/babylon-film-review-chazelle-robbie-calva-pitt-maguire-1849895468",
        "Tomris Laffly",
        "The A.V. Club",
        "rave",
    ),
    (
        "https://loudandclearreviews.com/babylon-2022-movie-review-film-damien-chazelle-margot-robbie/",
        "Branyan Towe",
        "Loud and Clear Reviews",
        "rave",
    ),
    (
        "https://www.rogerebert.com/reviews/babylon-movie-review-2022",
        "Brian Tallerico",
        "RogerEbert.com",
        "mixed",
    ),
    (
        "https://www.theguardian.com/film/2023/jan/22/babylon-review-damien-chazelle-margot-robbie-brad-pitt-messy-exhausting-tale-of-early-hollywood",
        "Mark Kermode",
        "The Guardian / Observer",
        "pan",
    ),
    (
        "https://www.theringer.com/2022/12/21/movies/babylon-movie-review",
        "Adam Nayman",
        "The Ringer",
        "pan (praises craft)",
    ),
]

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_LOG_PATH = REPO_ROOT / "logs" / "search_reviews.json"
LOG_PATH = REPO_ROOT / "logs" / "extract_reviews.json"


def load_search_session_id() -> str | None:
    """Reuse Step 3's session_id, documented to give better contextual
    results for subsequent calls in the same task."""
    if not SEARCH_LOG_PATH.exists():
        return None
    data = json.loads(SEARCH_LOG_PATH.read_text(encoding="utf-8"))
    return data.get("session_id")


def main() -> None:
    load_dotenv()

    client = Parallel()

    response = client.extract(
        urls=[url for url, *_ in SOURCES],
        session_id=load_search_session_id(),
        advanced_settings={"full_content": True},
    )

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    source_by_url = {url: (critic, outlet, polarity) for url, critic, outlet, polarity in SOURCES}

    print(f"extract_id: {response.extract_id}")
    print(f"{len(response.results)} succeeded, {len(response.errors)} failed")
    print(f"logged to {LOG_PATH}")
    print()

    for result in response.results:
        critic, outlet, polarity = source_by_url.get(result.url, ("?", "?", "?"))
        content = result.full_content or ""
        status = "OK" if len(content) >= MIN_CONTENT_CHARS else f"THIN ({len(content)} chars)"
        print(f"[{status}] {outlet} — {critic} (expected: {polarity})")
        print(f"  {result.url}")

    for error in response.errors:
        critic, outlet, polarity = source_by_url.get(error.url, ("?", "?", "?"))
        print(f"[FAILED {error.http_status_code}] {outlet} — {critic}: {error.error_type}")
        print(f"  {error.url}")


if __name__ == "__main__":
    main()
