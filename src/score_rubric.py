"""Brief 1 Step 5: rubric synthesis. The step the brief calls "the step the whole
concept's credibility rests on" — take the Step 4 extracted review text and produce a
score plus a source-traceable, paraphrased rationale for each of the seven fixed
rubric dimensions.

No new Parallel API calls happen here; this only reads logs/extract_reviews.json.

Design decisions (see the approved plan for full reasoning):
- Score scale is integer 1-5, nullable, paired with an evidence_sufficiency flag.
  Forcing a number with no real supporting text would be a hallucination by another
  name, and only 4 review texts exist, so a 1-10 or 0-100 scale would claim precision
  the source material can't support.
- "Critical consensus vs divergence" measures divergence, not quality: 1 = critics
  unanimous, 5 = sharply split.
- "Tone and mood match" is scored here as internal tonal coherence (does the film
  achieve the tone it's reaching for) — there's no user taste profile yet in Brief 1
  for it to match against. Brief 2 will need a differently-defined number once a real
  user mood profile exists.
- Outlet names, critic identities and expected polarity labels (from
  src/extract_reviews.py's SOURCES) are deliberately withheld from the prompt, along
  with the Rotten Tomatoes/Metacritic scores in src/test_film.py's docstring — all of
  that would leak the answer. Sources are labelled source_1..source_n in the prompt,
  mapped back to real outlets only for logging and console display afterwards.
- Extracted text is trimmed of page chrome (nav bars, share widgets, "Recommended for
  You" blocks, footers) before scoring — the raw extracts genuinely contain other
  films' content (verified directly against logs/extract_reviews.json), which would
  make it impossible to tell a real hallucination from the model faithfully reading a
  sidebar.
- One ablation run (the two rave sources removed) is the actual grounding test: if
  divergence and the affected rationales don't shift when the raves disappear, that's
  a signal the model is drawing on its own prior knowledge of this well-known film
  rather than the supplied text.
- Structured output is built from RUBRIC_DIMENSIONS as the single source of truth,
  with seven explicitly named required fields (never a list), so an eighth invented
  dimension or a dropped one is structurally impossible, not just prompt-discouraged.
"""

import json
import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, create_model

from extract_reviews import MIN_CONTENT_CHARS, SOURCES
from rubric import RUBRIC_DIMENSIONS
from test_film import TEST_FILM

MODEL = "gemini-2.5-pro"

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_LOG_PATH = REPO_ROOT / "logs" / "extract_reviews.json"
LOG_PATH = REPO_ROOT / "logs" / "score_rubric.json"

# Roughly $ per 1M tokens, gemini-2.5-pro list pricing. For Step 6's cost note only —
# not an exact billing query, thinking tokens are counted at the output rate since
# they bill as output.
PRICE_PER_M_INPUT = 1.25
PRICE_PER_M_OUTPUT = 10.00

# Written anchors per dimension, 1-5, so the model has a fixed referent for what each
# level means rather than free-interpreting the scale each run.
ANCHORS: dict[str, list[str]] = {
    "Story and plot coherence": [
        "Reviewers describe the plot/narrative as incoherent, confused or poorly constructed.",
        "Reviewers note real structural or narrative weaknesses.",
        "Mixed or unremarkable; reviewers neither praise nor criticise the plot's coherence much.",
        "Reviewers find the narrative generally coherent and well-constructed, with minor caveats.",
        "Reviewers explicitly praise a tightly coherent, well-constructed story or plot.",
    ],
    "Pacing": [
        "Reviewers describe pacing as a serious problem (dragging, bloated, exhausting).",
        "Reviewers note pacing issues, but not fatally.",
        "Mixed or unremarkable pacing commentary.",
        "Reviewers find pacing generally effective.",
        "Reviewers explicitly praise the pacing as a standout strength.",
    ],
    "Performance quality": [
        "Reviewers criticise performances as weak or unconvincing.",
        "Reviewers note some weak performances alongside adequate ones.",
        "Mixed or unremarkable performance commentary.",
        "Reviewers generally praise the performances.",
        "Reviewers explicitly single out performances as a career-best or standout strength.",
    ],
    "Tone and mood match": [
        "Reviewers say the film's tone is muddled or doesn't land as intended.",
        "Reviewers note tonal inconsistency or missteps.",
        "Mixed or unremarkable tonal commentary.",
        "Reviewers find the tone generally well-achieved.",
        "Reviewers explicitly praise the film for confidently achieving a distinctive, well-executed tone.",
    ],
    "Craft (direction, cinematography, score)": [
        "Reviewers criticise the technical filmmaking craft.",
        "Reviewers note some technical shortcomings.",
        "Mixed or unremarkable craft commentary.",
        "Reviewers generally praise the technical craft.",
        "Reviewers explicitly single out direction, cinematography or score as exceptional, a standout strength even amid other criticism.",
    ],
    "Rewatch value": [
        "Reviewers explicitly say the film doesn't hold up to, or invite, a rewatch.",
        "Reviewers suggest limited rewatch appeal, or only a single passing remark about the film's legacy exists.",
        "Mixed or unremarkable rewatch commentary, or no real basis to judge this dimension at all.",
        "Multiple reviewers, or one reviewer at length, explicitly say the film itself rewards or invites rewatching (not just that it will be remembered or discussed).",
        "Reviewers explicitly frame the film as a future rewatch favourite or cult item, on the strength of more than one passing remark.",
    ],
    "Critical consensus vs divergence": [
        "All provided sources broadly agree in their overall assessment.",
        "Sources mostly agree, with minor differences of emphasis.",
        "Sources show a moderate split in overall assessment.",
        "Sources show a clear split, with real disagreement on overall quality.",
        "Sources are sharply and fundamentally divided, from rave to pan — this anchor requires at least one cited source with an overall rave verdict and at least one with an overall pan verdict.",
    ],
}

TONE_MOOD_NOTE = (
    'For "Tone and mood match": no user taste/mood profile exists at this stage, so '
    "score this as internal tonal coherence — does the film achieve the tone it's "
    "reaching for, per what critics say about its tonal execution — not a match "
    "against any external mood."
)
DIVERGENCE_NOTE = (
    'For "Critical consensus vs divergence": this measures divergence, not quality. '
    "1 means the provided sources were unanimous in their overall assessment, 5 means "
    "they were sharply split. Judge this only from the sources provided in this run. "
    "Base this only on each cited source's OVERALL verdict (would this critic broadly "
    "recommend the film or not), not on disagreements about individual scenes, "
    "performances or elements within an otherwise similar overall verdict. If the "
    "sources actually provided in this run are all positive, all negative, or a mix of "
    "only 'mixed' and 'negative' overall verdicts (no source here gives an overall "
    "rave), that is not a rave-to-pan divergence — score the low-to-moderate end of "
    "the scale (1-3) reflecting the real spread of the sources you were given, not the "
    "full spectrum of opinions that might exist elsewhere about this film."
)
EVIDENCE_DISCIPLINE_NOTE = (
    "A score of 1, 2, 4 or 5 on any dimension requires substantive, on-topic evidence: "
    "either more than one source addressing it, or one source addressing it at real "
    "length, not a single incidental or tangential remark. If only one brief remark "
    "touches a dimension and nothing else does, keep the score at 3 (or set it null "
    "with evidence_sufficiency \"insufficient\" if there's truly no basis) rather than "
    "letting one glancing line drive a near-extreme score — evidence_sufficiency "
    "\"thin\" should not be paired with a score of 4 or 5 (or 1 or 2). This applies "
    "especially to \"Rewatch value\": a claim about the film's historical legacy, "
    "prestige or awards prospects is not the same claim as critics saying the film "
    "itself invites or rewards being watched again — don't treat the two as "
    "interchangeable."
)
QUOTING_NOTE = (
    "For every rationale and locating_phrase: paraphrase in your own words. If you "
    "quote a source directly, the quoted text must be copied character-for-character "
    "exactly as it appears in that source, and must be no more than about 6 words. "
    "Never shorten, reword or combine a quotation and still present it in quotation "
    "marks — that misattributes words to the critic that they didn't write. Do not "
    "follow a closed quotation with more of the source's exact wording left unquoted "
    "— if your sentence keeps using the source's own words right after the closing "
    "quotation mark, either bring those words inside the quotation marks too (only if "
    "the combined quote is still ~6 words or fewer) or rephrase them in your own words "
    "instead of letting them run on unmarked."
)
ANCHOR_DISCIPLINE_NOTE = (
    "If the sources genuinely disagree with each other on a dimension, that "
    "disagreement itself means the middle anchor (3), not the floor (1) or ceiling "
    "(5) — the floor and ceiling anchors require the sources to broadly agree. Before "
    "giving a score of 1 or 5, check that no cited source contradicts it; if one "
    "does, either move the score toward the middle or explain the contradiction in "
    "the rationale rather than silently dropping it."
)
CITATION_COMPLETENESS_NOTE = (
    "source_ids must include every source whose view you characterise in the "
    "rationale, including ones that contradict your overall score — do not cite only "
    "the sources that support the score you landed on."
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


CHROME_BLACKLIST = [
    "facebook.com/sharer", "twitter.com/intent", "reddit.com/submit", "bsky.app/intent",
    "copy to clipboard", "join the discussion", "keep scrolling for more",
    "recommended for you", "about the site", "advertise with us", "terms of use",
    "privacy policy", "cookies", "accessibility", "contact us", "contact masthead",
    "newsletter", "archive", "take me there", "just the hits", "keep exploring",
    "latest in movies", "is a film critic", "getty images/paramount pictures",
    "read also", "latest posts", "follow us", "thank you", "donate", "about us",
    "features", "star rating", "now playing", "photo of roger ebert", "in memoriam",
    "ebert co.", "search icon", "movie reviews\n", "chaz's journal", "dvd/blu-ray",
    "video games", "designed with love", "dmca.com", "affiliate partnership",
]
_LINK_RE = re.compile(r"\]\(")
_BARE_LINK_RE = re.compile(r"^\[[^\]\n]+\]\([^)\n]+\)$")
_BOLD_RE = re.compile(r"\*\*([^\n*]+?)\*\*")
_ITALIC_UNDERSCORE_RE = re.compile(r"_([^\n_]+?)_")
_ITALIC_ASTERISK_RE = re.compile(r"(?<!\*)\*([^\n*]+?)\*(?!\*)")


def _strip_markdown_emphasis(text: str) -> str:
    """Drop **bold**/_italic_/*italic* markup, keeping the inner words. The raw
    extracts are markdown, so e.g. "sensational **cinematography**" or "_feels_" would
    otherwise never exact-match a model-quoted "sensational cinematography" or
    "feels" — a formatting artifact, not a real quoting discrepancy."""
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_UNDERSCORE_RE.sub(r"\1", text)
    text = _ITALIC_ASTERISK_RE.sub(r"\1", text)
    return text


def trim_review_text(content: str) -> str:
    """Strip page chrome (nav bars, share widgets, related-content blocks, footers)
    from raw extracted page content, keeping only the review body. The raw extracts
    verifiably contain other films' content (e.g. "Recommended for You" sidebars),
    which would otherwise make it impossible to tell a real hallucination from the
    model faithfully reading a sidebar. Heuristic, tuned against this test film's 4
    actual sources — not a general-purpose production extractor."""
    paragraphs = content.split("\n\n")
    kept: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if not stripped or stripped in seen:
            continue
        if _is_chrome(stripped):
            continue
        seen.add(stripped)
        kept.append(stripped)
    return _strip_markdown_emphasis("\n\n".join(kept))


def _is_chrome(stripped: str) -> bool:
    if len(stripped) < 120:
        return True
    if stripped.startswith("#"):
        return True
    if _BARE_LINK_RE.match(stripped):
        return True
    low = stripped.lower()
    if any(marker in low for marker in CHROME_BLACKLIST):
        return True
    n_links = len(_LINK_RE.findall(stripped))
    if n_links >= 2 and len(stripped) < 200:
        return True
    if n_links >= 3 and len(stripped) < 500:
        return True
    return False


def load_source_metadata() -> dict[str, dict]:
    return {
        url: {"critic": critic, "outlet": outlet, "is_rave": polarity == "rave"}
        for url, critic, outlet, polarity in SOURCES
    }


# Fixed per-URL id, independent of which sources a given run happens to include, so
# e.g. The Ringer is always source_5 whether it's one of 4 sources (main run) or one
# of 2 (ablation run) — ids that shifted with inclusion made cross-run comparison
# manual and wouldn't have survived Brief 2 widening to more titles/sources.
STABLE_SOURCE_ID_BY_URL = {url: f"source_{i + 1}" for i, (url, *_rest) in enumerate(SOURCES)}


def build_sources(exclude_urls: frozenset[str] = frozenset()) -> list[dict]:
    """Load Step 4's extracted content, drop thin/failed/excluded sources, trim page
    chrome, and assign neutral, per-URL-stable source ids. Outlet/critic names and the
    rave/pan labels are kept here for our own logging and console display only — none
    of it is ever placed in the text sent to Gemini."""
    data = json.loads(EXTRACT_LOG_PATH.read_text(encoding="utf-8"))
    metadata = load_source_metadata()
    sources = []
    for result in data["results"]:
        content = result.get("full_content") or ""
        if len(content) < MIN_CONTENT_CHARS or result["url"] in exclude_urls:
            continue
        if result["url"] not in STABLE_SOURCE_ID_BY_URL:
            continue  # not one of the known, curated sources — no stable id to assign
        meta = metadata.get(result["url"], {"critic": "unknown", "outlet": "unknown", "is_rave": False})
        trimmed = trim_review_text(content)
        sources.append({
            "source_id": STABLE_SOURCE_ID_BY_URL[result["url"]],
            "url": result["url"],
            "critic": meta["critic"],
            "outlet": meta["outlet"],
            "is_rave": meta["is_rave"],
            "original_chars": len(content),
            "trimmed_text": trimmed,
            "trimmed_chars": len(trimmed),
        })
    return sources


def build_response_schema(allowed_source_ids: list[str]) -> type[BaseModel]:
    """Build the structured-output schema from RUBRIC_DIMENSIONS as the single source
    of truth: seven explicitly named required fields, never a list, so an eighth
    invented dimension or a dropped one is structurally impossible. The citation
    field is constrained to an enum of only the source ids present in this run, so
    the model cannot cite a source it was never given.

    The parameter is named differently from the `source_ids` field below on purpose:
    a class-body assignment to a name shadows an identically-named enclosing-scope
    variable even within the same annotation expression, which silently turns
    `Literal[tuple(source_ids)]` into `Literal[tuple(<the FieldInfo being assigned>)]`."""

    class DimensionScore(BaseModel):
        score: int | None = Field(
            default=None, ge=1, le=5,
            description="1-5, or null if the provided sources don't give enough basis to judge this dimension.",
        )
        evidence_sufficiency: Literal["sufficient", "thin", "insufficient"]
        rationale: str = Field(
            description=(
                "One to two sentences, paraphrased. Any direct quote must be copied "
                "character-for-character exactly from the source and no more than "
                "~6 words — never a shortened or reworded 'quote'."
            )
        )
        source_ids: list[Literal[tuple(allowed_source_ids)]] = Field(
            description=(
                "Every source id whose view is characterised here, including ones "
                "that contradict the score — not only the ones that support it."
            )
        )
        locating_phrase: str | None = Field(
            default=None,
            description=(
                "A short paraphrase pointing to roughly where in the cited source(s) "
                "this claim comes from. Same quoting rule as rationale: exact and "
                "~6 words max if quoting at all."
            ),
        )

    fields = {_slug(dimension.name): (DimensionScore, ...) for dimension in RUBRIC_DIMENSIONS}
    return create_model("RubricScore", **fields)


def build_prompt(film_title: str, sources: list[dict]) -> str:
    anchor_lines = []
    for dimension in RUBRIC_DIMENSIONS:
        slug = _slug(dimension.name)
        anchors = ANCHORS[dimension.name]
        anchor_text = "\n".join(f"    {level + 1} = {text}" for level, text in enumerate(anchors))
        anchor_lines.append(f'  "{slug}" ({dimension.name}):\n{anchor_text}')
    dimensions_block = "\n".join(anchor_lines)

    source_blocks = "\n\n".join(
        f"### {s['source_id']}\n{s['trimmed_text']}" for s in sources
    )

    return f"""You are scoring the film "{film_title}" across seven fixed rubric
dimensions, based ONLY on the {len(sources)} professional review excerpts below.
Outlet names and critic identities have been deliberately withheld — judge only the
text. Do not use any other knowledge you may have about this film, its cast, its
reception, its awards or its box office. If the provided excerpts don't give you
enough basis to judge a dimension, set score to null and evidence_sufficiency to
"insufficient" rather than guessing from prior knowledge.

{TONE_MOOD_NOTE}

{DIVERGENCE_NOTE}

{QUOTING_NOTE}

{ANCHOR_DISCIPLINE_NOTE}

{EVIDENCE_DISCIPLINE_NOTE}

{CITATION_COMPLETENESS_NOTE}

Dimensions and their score anchors:
{dimensions_block}

Sources:

{source_blocks}
"""


def call_gemini(client: genai.Client, prompt: str, schema: type[BaseModel]):
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    if response.parsed is None:
        # e.g. blocked by a safety filter, or truncated before valid JSON closed —
        # fail clearly here rather than an obscure AttributeError later when
        # print_result/grounding_check try to read fields off None.
        raise RuntimeError(
            f"Gemini returned no parseable structured result. "
            f"finish_reason={response.candidates[0].finish_reason if response.candidates else 'unknown'}, "
            f"prompt_feedback={response.prompt_feedback}"
        )
    return response.parsed, response.usage_metadata


_WORD_RE = re.compile(r"[A-Za-z']+")
NGRAM_SIZE = 5  # lowered from an earlier 8 - short as 5 words still catches a copied
                # phrase, and a fabricated/altered quote (e.g. a dropped word) is
                # invisible to any n-gram check regardless, which is why the separate
                # quoted-span check below exists.
_QUOTE_RE = re.compile(r'"([^"]{4,})"')
_HEDGE_MARKERS = [
    "divided", "split", "however", "though", "but", "some critics", "some reviewers",
    "some sources", "others find", "others describe", "in contrast", "on the other hand",
    "mixed", "disagree",
]
# Word-boundary, not substring — a bare "in" check would match "though" inside
# "although" or "divided" inside "undivided" (the exact opposite meaning).
_HEDGE_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in _HEDGE_MARKERS) + r")\b")


def _normalise_quotes(text: str) -> str:
    return (
        text.replace("’", "'").replace("‘", "'")
        .replace("“", '"').replace("”", '"')
    )


_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?]["\'”’])\s+')


def _proper_noun_candidates(text: str) -> set[str]:
    """Heuristic, not full NLP: capitalised words that aren't the first word of their
    sentence (sentence-initial capitalisation isn't informative for spotting a named
    entity), as a cheap proxy for named entities a rationale claims about the film.
    The split allows one closing quote mark between the terminal punctuation and the
    following space (e.g. `polarizing." Two sources...`) — without it, a sentence
    that ends inside a quotation mark hides its boundary, and the next sentence's
    first word (here "Two") gets wrongly treated as sentence-medial."""
    candidates = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        words = sentence.strip().split()
        for i, word in enumerate(words):
            if i == 0:
                continue
            cleaned = word.strip(".,;:!?\"'()")
            if len(cleaned) < 3 or not cleaned[0].isupper():
                continue
            candidates.add(cleaned)
    return candidates


def _word_ngrams(text: str, n: int = NGRAM_SIZE) -> set[str]:
    words = _WORD_RE.findall(text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _check_field(field_name: str, field_label: str, text: str, cited_text: str) -> list[str]:
    flags = []

    candidates = _proper_noun_candidates(text)
    if candidates:
        missing = {c for c in candidates if c not in cited_text}
        if missing and missing == candidates:
            flags.append(f"{field_name}.{field_label}: none of the named terms {sorted(missing)} appear in its cited source(s)")

    # A verbatim run inside quote marks is allowed (checked separately below for
    # exactness) and already expected to overlap the source — only flag a run
    # that's presented as the model's own paraphrase, i.e. outside any quotes,
    # since that's unmarked copying rather than an attributed quote.
    unquoted = _QUOTE_RE.sub(" ", _normalise_quotes(text))
    overlap = _word_ngrams(unquoted) & _word_ngrams(cited_text)
    if overlap:
        flags.append(f"{field_name}.{field_label}: copies a {NGRAM_SIZE}+ word run verbatim from a source without quoting it: \"{min(overlap)}\"")

    normalised_cited = _normalise_quotes(cited_text)
    for quoted in _QUOTE_RE.findall(_normalise_quotes(text)):
        # Trailing/leading punctuation is often the rationale's own sentence
        # punctuation sitting inside the closing quote mark (a style choice), not
        # part of what's being quoted — strip it before the exact-match check so
        # that doesn't produce a false positive.
        core = quoted.strip(".,;:!?")
        if "..." in core or "…" in core:
            # An ellipsis-abbreviated quote is a legitimate way to shorten a quote —
            # check each segment appears (in order), not the ellipsis itself.
            segments = [s.strip(".,;:!? ") for s in re.split(r"\.\.\.|…", core)]
            if all(not seg or seg in normalised_cited for seg in segments):
                continue
            flags.append(f"{field_name}.{field_label}: ellipsis-quoted span has a segment not found verbatim in its cited source(s): \"{quoted}\"")
            continue
        if core and core not in normalised_cited:
            flags.append(f"{field_name}.{field_label}: quoted span not found verbatim in its cited source(s): \"{quoted}\"")

    return flags


def grounding_check(result: BaseModel, sources_by_id: dict[str, dict]) -> list[str]:
    """Not a full separate tool, but no longer just the rationale field either:
    checks rationale AND locating_phrase (the longest verbatim runs, and the
    fabricated-quote risk, were showing up in locating_phrase and going unchecked).
    Flags: named-entity claims absent from the cited source(s); a run of
    NGRAM_SIZE+ words copied verbatim; a quoted span that doesn't match its cited
    source's actual text exactly (catches a shortened/altered "quote" too short for
    the n-gram check); and a floor/ceiling score (1 or 5) alongside the model's own
    hedged or divided-opinion language, which is the shape the ablation run showed
    for real (a cited source's contrary framing acknowledged in locating_phrase but
    omitted from the rationale and the score)."""
    flags = []
    for field_name in type(result).model_fields:
        score_obj = getattr(result, field_name)
        cited_text = " ".join(
            sources_by_id[sid]["trimmed_text"] for sid in score_obj.source_ids if sid in sources_by_id
        )
        if not cited_text:
            if score_obj.source_ids:
                flags.append(f"{field_name}: cited source id(s) {score_obj.source_ids} not found in this run's sources")
            continue

        flags += _check_field(field_name, "rationale", score_obj.rationale, cited_text)
        if score_obj.locating_phrase:
            flags += _check_field(field_name, "locating_phrase", score_obj.locating_phrase, cited_text)

        # Skipped for divergence: "divided"/"mixed" language at score 5 is that
        # dimension working correctly (5 *means* sharply divided), not a skew.
        if score_obj.score in (1, 5) and field_name != _slug("Critical consensus vs divergence"):
            combined = (score_obj.rationale + " " + (score_obj.locating_phrase or "")).lower()
            hedges = sorted(set(_HEDGE_RE.findall(combined)))
            if hedges:
                flags.append(
                    f"{field_name}: score sits at the {'floor' if score_obj.score == 1 else 'ceiling'} "
                    f"(1 or 5) despite hedged/divided language in the model's own explanation ({', '.join(hedges)}) — "
                    "check this isn't the skew where a contradicting source got cited but its contrary framing got dropped"
                )

        # "Thin" evidence paired with a near-extreme score is a single glancing
        # remark being stretched into a strong number — the failure shape Step 5's
        # own plan flagged for Rewatch value specifically, but mechanically checkable
        # for any dimension.
        if score_obj.evidence_sufficiency == "thin" and score_obj.score in (1, 2, 4, 5):
            flags.append(
                f"{field_name}: score {score_obj.score} sits near an extreme despite "
                "evidence_sufficiency \"thin\" — check this isn't one incidental remark "
                "being stretched into a strong score"
            )
    return flags


def estimate_cost(usages: list) -> float:
    total = 0.0
    for usage in usages:
        input_tokens = usage.prompt_token_count or 0
        output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        total += (input_tokens / 1_000_000) * PRICE_PER_M_INPUT
        total += (output_tokens / 1_000_000) * PRICE_PER_M_OUTPUT
    return total


def print_result(label: str, result: BaseModel, sources: list[dict]) -> None:
    outlet_by_id = {s["source_id"]: s["outlet"] for s in sources}
    print(f"\n=== {label} ({len(sources)} sources) ===")
    for dimension in RUBRIC_DIMENSIONS:
        slug = _slug(dimension.name)
        score_obj = getattr(result, slug)
        cited = ", ".join(outlet_by_id.get(sid, sid) for sid in score_obj.source_ids) or "none"
        score_display = score_obj.score if score_obj.score is not None else f"— ({score_obj.evidence_sufficiency})"
        print(f"\n[{dimension.name}] {score_display}")
        print(f"  {score_obj.rationale}")
        print(f"  cited: {cited}")
        if score_obj.locating_phrase:
            print(f"  locating phrase: {score_obj.locating_phrase}")


def main() -> None:
    load_dotenv()
    client = genai.Client()

    main_sources = build_sources()
    rave_urls = frozenset(s["url"] for s in main_sources if s["is_rave"])
    ablation_sources = build_sources(exclude_urls=rave_urls)

    main_schema = build_response_schema([s["source_id"] for s in main_sources])
    ablation_schema = build_response_schema([s["source_id"] for s in ablation_sources])

    main_prompt = build_prompt(TEST_FILM.title, main_sources)
    ablation_prompt = build_prompt(TEST_FILM.title, ablation_sources)

    main_result, main_usage = call_gemini(client, main_prompt, main_schema)
    ablation_result, ablation_usage = call_gemini(client, ablation_prompt, ablation_schema)

    main_sources_by_id = {s["source_id"]: s for s in main_sources}
    ablation_sources_by_id = {s["source_id"]: s for s in ablation_sources}
    main_flags = grounding_check(main_result, main_sources_by_id)
    ablation_flags = grounding_check(ablation_result, ablation_sources_by_id)

    print_result("Main run", main_result, main_sources)
    print_result("Ablation run (raves removed)", ablation_result, ablation_sources)

    print("\n=== Main vs ablation: does the score move when the raves disappear? ===")
    for dimension in RUBRIC_DIMENSIONS:
        slug = _slug(dimension.name)
        main_score = getattr(main_result, slug).score
        ablation_score = getattr(ablation_result, slug).score
        if main_score is None or ablation_score is None:
            delta_display = "n/a (evidence insufficient in at least one run)"
        else:
            delta_display = f"{ablation_score - main_score:+d}"
        print(f"  {dimension.name}: main={main_score} ablation={ablation_score} delta={delta_display}")

    print("\n=== Grounding check flags ===")
    if not main_flags and not ablation_flags:
        print("  none")
    else:
        for flag in main_flags:
            print(f"  [main] {flag}")
        for flag in ablation_flags:
            print(f"  [ablation] {flag}")

    cost = estimate_cost([main_usage, ablation_usage])
    print(f"\nEstimated cost this run: ${cost:.4f} (gemini-2.5-pro list pricing, includes thinking tokens billed as output)")

    log = {
        "film": TEST_FILM.model_dump(),
        "model": MODEL,
        "main_run": {
            "sources": [{k: v for k, v in s.items() if k != "trimmed_text"} for s in main_sources],
            "trimmed_text": {s["source_id"]: s["trimmed_text"] for s in main_sources},
            "result": main_result.model_dump(),
            "usage": main_usage.model_dump(),
            "grounding_flags": main_flags,
        },
        "ablation_run": {
            "sources": [{k: v for k, v in s.items() if k != "trimmed_text"} for s in ablation_sources],
            "trimmed_text": {s["source_id"]: s["trimmed_text"] for s in ablation_sources},
            "result": ablation_result.model_dump(),
            "usage": ablation_usage.model_dump(),
            "grounding_flags": ablation_flags,
        },
        "estimated_cost_usd": cost,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nlogged to {LOG_PATH}")


if __name__ == "__main__":
    main()
