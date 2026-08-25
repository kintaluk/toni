"""Fixed rubric dimensions for the Agentic Cinema scoring pipeline.

Per Brief 1 Step 2 (agentic-cinema-brief-1.md) and the concept brief: these
seven dimensions, and only these, are the contract for rubric scoring. Do not
add, remove or rename any of them without an explicit brief update.
"""

from pydantic import BaseModel


class RubricDimension(BaseModel):
    name: str


RUBRIC_DIMENSIONS: list[RubricDimension] = [
    RubricDimension(name="Story and plot coherence"),
    RubricDimension(name="Pacing"),
    RubricDimension(name="Performance quality"),
    RubricDimension(name="Tone and mood match"),
    RubricDimension(name="Craft (direction, cinematography, score)"),
    RubricDimension(name="Rewatch value"),
    RubricDimension(name="Critical consensus vs divergence"),
]


if __name__ == "__main__":
    for dimension in RUBRIC_DIMENSIONS:
        print(dimension.name)
