"""Brief 1 Step 3: search for professional critical reviews of the test film.

Effort: ultrathink, per the brief. This is the first real Parallel call in
this project, and the objective/query phrasing matters more here than most
other steps. Must not call client.search() more than once per test run at
this stage: we are checking result quality, not tuning against live cost.

Logs the full raw response (URLs, titles and excerpts) to logs/search_reviews.json
rather than only printing it, since Nate reviews the raw output before Step 4
(extract) starts.
"""

from pathlib import Path

from dotenv import load_dotenv
from parallel import Parallel

from test_film import TEST_FILM

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "search_reviews.json"


def build_objective() -> str:
    return (
        f'Find professional film critic reviews of the {TEST_FILM.year} film "'
        f'{TEST_FILM.title}", directed by {TEST_FILM.director}. Only reviews '
        "written by professional critics at recognised publications (newspapers, "
        "magazines, or established film review outlets) count. Exclude fan forum "
        "posts, message board discussions, plot summary or synopsis pages, ticket "
        "or showtime listings, and general news coverage about the film's box "
        "office or production. The film received a genuinely divided critical "
        "reception on release, so prioritise sources giving a substantive, "
        "opinionated critical assessment of the film's quality, whether positive "
        "or negative, rather than a neutral plot description."
    )


def build_queries() -> list[str]:
    title = TEST_FILM.title
    return [
        f"{title} {TEST_FILM.year} movie review",
        f"{title} film critic review",
        f"{title} {TEST_FILM.director} review reception",
    ]


def main() -> None:
    load_dotenv()

    client = Parallel()

    response = client.search(
        objective=build_objective(),
        search_queries=build_queries(),
    )

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    print(f"search_id: {response.search_id}")
    print(f"session_id: {response.session_id}")
    print(f"{len(response.results)} result(s), logged to {LOG_PATH}")
    for result in response.results:
        print(f"- {result.title!r} ({result.url})")

    if response.warnings:
        print("warnings:")
        for warning in response.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
