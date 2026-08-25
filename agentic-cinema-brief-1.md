Agentic Cinema Brief 1: Repo scaffold and review pipeline spike
For Claude Code. 25 August 2026.

**In one sentence:** we need to know whether Parallel's search and extract, fed into a
Gemini rubric-scoring prompt, produces grounded, non-invented scores for a real film
before we build taste intake, case matching, or any UI on top of it.

Context: this is Brief 1 of an expected 4 to 5 for the Agentic Cinema hackathon
(Parallel track, deadline 9 September, 2pm PDT). Full concept is in the concept brief
from Tina. This brief does not build the fan-facing product. It builds and tests the
single riskiest piece: search, extract, and rubric scoring for one film, so we know
whether the concept holds up before investing in the rest.

Brief type: new build.

Environment:
- New GitHub repo, kept **private** throughout. Do not make it public. That decision
  gets made explicitly later, close to submission, not by default.
- Python 3.11+, virtual environment.
- Install: `pip install "google-cloud-aiplatform[agent_engines,adk]>=1.101.0"` and
  `pip install parallel-web`. If these two have a dependency conflict, stop and flag
  it, don't silently downgrade either.
- Secrets: `PARALLEL_API_KEY` and Google Cloud credentials go in a local `.env` file.
  Add `.env` to `.gitignore` before the first commit, not after.
- No CLAUDE.md exists yet for this repo. Run `/init` first.
- Plan mode is mandatory, this is a new build. Approve the plan before any code is
  written.
- `settings.json`: keep the standard push-to-main deny rule active. No Supabase ask
  rules needed, this repo doesn't touch Supabase.

---

Step 1: Repo and environment scaffold
Effort: default
Do: create the repo structure (`src/`, `tests/`, `.env.example`, `.gitignore`, a
README stub that states the repo is a work in progress and not yet public). Install
both packages listed above and confirm they import cleanly.
File: repo root, `requirements.txt`
Claude Code must not change: nothing exists yet to change.
If blocked: a dependency conflict between the ADK package and `parallel-web`, stop and
report the exact conflicting version constraints rather than picking one.
Verify: run a short script that imports both packages and prints the first 4
characters only of the loaded `PARALLEL_API_KEY` (never the full key), to confirm
`.env` is wired up correctly.

Step 2: Fixed test film and rubric definition
Effort: default
Do: hardcode one well-known film as the test case for this spike. Pick one with a
genuinely wide critical divide (strong reviews from some outlets, weak from others),
since that's the dimension we most need to see actually work. Write the seven rubric
dimensions from the concept brief as a typed Python structure (Pydantic model or
dataclass), not as prose the model has to reconstruct each run:
1. Story and plot coherence
2. Pacing
3. Performance quality
4. Tone and mood match
5. Craft (direction, cinematography, score)
6. Rewatch value
7. Critical consensus vs divergence
File: `src/rubric.py`, `src/test_film.py`
Claude Code must not change: the rubric dimension names or count. These are fixed per
the concept brief.
If blocked: none expected, this is static data entry.
Verify: print the rubric structure and the test film's title to confirm both load.

Step 3: Wire up Parallel search for the test film
Effort: ultrathink (the objective and query phrasing on this first real call matters
more than most steps here)
Do: using the Parallel Python SDK (`from parallel import Parallel`), call
`client.search()` with an objective aimed specifically at professional critical
reviews of the test film, not fan forum posts or plot summaries. Log the full raw
response (URLs and excerpts) to a local file, don't just print and discard it.
File: `src/search_reviews.py`
Claude Code must not change: don't call `client.search()` more than once per test run
at this stage. We're checking quality, not tuning against live cost yet.
If blocked: if results come back thin or off-topic, try a second, more specific
objective before proceeding. Don't move to Step 4 on weak source material.
Verify: paste the raw logged search output into the session. Nate reviews this before
Step 4 starts, since everything downstream depends on it being good.

Step 4: Extract full review content
Effort: default
Do: for the best 3 to 5 URLs from Step 3, call Parallel's Extract API for clean page
content. Log extracted text per source, tagged with its source URL.
File: `src/extract_reviews.py`
Claude Code must not change: don't extract more than 5 sources for this test film.
If blocked: if a source fails (paywall, bot-blocked), log it as failed and continue
with the remaining sources rather than stopping the whole run.
Verify: paste a short excerpt of each successfully extracted source into the session.
Confirm they're real review content, not error pages.

Step 5: Rubric synthesis
Effort: ultrathink (this is the step the whole concept's credibility rests on)
Do: write the prompt that takes the extracted review content and produces a score
plus a one or two sentence rationale for each of the seven rubric dimensions. The
rationale must reference which source(s) it drew from, paraphrased, never quoted at
length, per the copyright constraint in the concept brief. Run it against the test
film's extracted content from Step 4.
File: `src/score_rubric.py`
Claude Code must not change: don't let the model invent a dimension outside the fixed
list from Step 2.
If blocked: if the output can't trace its scores back to specific extracted content,
that's a signal the prompt needs tightening, not a signal to proceed anyway.
Verify: paste the full seven-dimension scored output into the session. This is the
single most important check in this brief. Nate and Tina sanity-check it against the
actual review content from Step 4 before agreeing to build anything further on top.

Step 6: Session wrap
Do: summarise in plain English what worked, what didn't, and the actual API cost
incurred so far (check the Parallel dashboard request count). Do not commit anything
to GitHub yet, this stays local until reviewed.
Verify: Nate confirms the pipeline quality is good enough to build Brief 2 on top of.

---

What comes after this brief, once Step 5 checks out:

- **Brief 2**: widen from one test film to the full curated set (10 to 15 titles
  across genres), build the taste intake question flow, build the case-matching step
  that reconciles rubric scores against a taste profile.
- **Brief 3**: output formatting (the ranked, reasoned watchlist), a minimal front end
  for the demo.
- **Brief 4**: deploy to Cloud Run or Agent Engine, assemble the pieces into the
  actual ADK agent structure.
- **Brief 5**: demo video, README, a security-auditor pass on the repo before it goes
  public, submission.

Don't write Brief 2 until Step 5 of this brief has been reviewed and approved. If the
rubric scoring doesn't hold up on one film, that's cheaper to discover now than after
the taste intake and case-matching logic are built around it.
