"""Fixed test film for Brief 1: the search/extract/rubric-scoring spike.

Chosen for a genuinely divided professional critical reception, verified via
Rotten Tomatoes (57% critics' score) and Metacritic (61/100), built from real
raves sitting next to real pans rather than lukewarm consensus. Do not change
without an explicit brief update.
"""

from pydantic import BaseModel


class TestFilm(BaseModel):
    title: str
    year: int
    director: str


TEST_FILM = TestFilm(
    title="Babylon",
    year=2022,
    director="Damien Chazelle",
)


if __name__ == "__main__":
    print(TEST_FILM.title)
