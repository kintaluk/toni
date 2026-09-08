# Review flow and cleanup — 8 September 2026

The web client requests `/api/recommend?live=true&defer_reviews=true`. This phase
discovers films, checks access and hard constraints, and returns factual cards
with `review_status: pending`. It does not call review search or synthesis.

After displaying the cards, the client posts `{films: [FilmMetadata, ...]}` to
`/api/reviews`. This endpoint accepts one to seven films and streams newline
delimited JSON. Each update carries `index`, `title`, `year` and `review_status`.
Updates may add `profile`, `evidence_state`, `consensus_rationale`,
`evidence_sources` and `review_failure`. They cannot replace a film, change its
availability or reorder the shortlist.

- `searching_more`: wider retrieval is starting, or synthesis is being retried.
- `complete`: review analysis and source links are available.
- `unavailable`: retrieval or synthesis did not complete; known links remain.

Review retrieval uses cached evidence where possible, an initial eight-second
budget, and a broader fifteen-second attempt when fewer than two publications
are available. The broader attempt avoids URLs already attempted. Synthesis has
its own eleven-second budget and one retry. A shared model client is initialized
once before synthesis, with a separate bounded setup wait, and reuses its
connection pool across films and requests. The stream stops within sixty
seconds; the browser also bounds its wait. Eight shared review workers cap actual
upstream concurrency. Cancellation cannot kill a running Python thread, so
provider transport timeouts remain necessary. A new search or conversation
aborts the old stream; request, session and film identities reject stale updates.

Voice confirmation belongs to the current question and saved preferences. A
complete affirmative reply starts a single visual search only after context
commit. Preference edits invalidate the offer. Negative, mixed, unrelated or
echoed question transcripts cannot authorize search. The transition tears down
capture and playback. Natural search-question variants, including “Shall I search
with these choices then?”, are covered by the confirmation tests. Turn detection
now allows 1.2 seconds of silence with low
end-of-speech sensitivity; explicitly unfinished transcripts get a short grace
period. Interruption events also process any input text they contain.

Cleanup removed all production persona presets, API routing, markup, loading and
application code; the obsolete exclusion dropdown and its state/events; duplicate
window exports; an unused voice alias; and unused profiler constants/imports.
The test-key-prefix timeout exception was removed so tests use the production
timeout rule. Tests expecting the old controls were adapted to exclusion buttons;
the persona-loading test was removed and endpoint removal is checked.

Retained: useful regression fixtures, explicit offline integration flags,
diagnostic helpers used by those tests, the documented terminal CLI and seed-film
fallback. Tests and local validation artifacts are not copied into the runtime
image.

Validation includes real JavaScript execution, backend fault injection, a live
Blink Twice review request and the offline regression suite. Blink Twice initially
returned fresh retrieval and synthesis in about seven seconds, with Variety,
The Guardian and RogerEbert.com source links. The full two-phase API check returned
seven availability-checked cards in 9.24 seconds. It exercised expanded retrieval
and exposed repeated client setup as a further cause of synthesis failure. After
connection reuse was implemented, all seven films received fresh Gemini synthesis
in 3.20 seconds using the previously retrieved review cache (zero failures).
These are individual local integration measurements, not production guarantees.
The final regression run passed 248 tests; four opt-in live Gemini extraction
tests were skipped. Source-manifest verification passed, and the served HTML
contains neither the persona panel nor the old exclusion dropdown.
Physical microphone/speaker and rendered-browser checks remain separate manual
acceptance checks. Deployment identity is recorded by the GitHub commit, image
digest and Cloud Run revision; source-manifest verification links the runtime
files to the packaged build.
