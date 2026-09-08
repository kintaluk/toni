# Unrestricted voice search — 8 September 2026

The browser initialized and reset `min_release_year` to the current year minus
three, which produced 2023 in 2026. The backend already defaulted to `None`.
Both browser paths now use any year, and extracted year changes synchronize
with the same state consumed by voice, text, buttons and recommendation requests.
Restart also resets versions for every preference, including references and year.

Included-only access was a browser/backend default, not an extracted choice.
The offer now states the rental policy and year before requesting consent.
“No restrictions” clears year, runtime and exclusions; it does not add extra
charges. Explicit rental choices update the search setting, and accepting the
offer confirms that setting. The live voice prompt follows the same policy.

Complete affirmations do not run model extraction or change saved preferences.
The browser also protects the current offer against a mis-extracted affirmation.
Consent remains tied to the current session and choices; negative/mixed replies,
unrelated questions and edits cannot authorize search. Duplicate completion
events produce one request. Consent works when the prior extraction commits
after the next transcript arrives, and a completed voice offer survives muting
so it can be answered in text. Audio for a consent response waits for commit.

Discovery now considers all eras when no year limit is set and interprets TV
references as taste for feature films. Local fallback retains named references,
including Ted Lasso. Funny/comedy affects preliminary candidate selection.
The existing all-channels declaration maps to the 11 supported UK services.
TMDB's `free` category now joins `flatrate` and `ads` in included-access checks.
No mapping to rental storefronts was added.

Discovery fallback, year/runtime/genre exclusions, checked unavailability and
unfinished/failed availability checks are reported separately in
`search_diagnostics`. Exceptions and unfinished checks are unverified, not
unavailable. Seed refill avoids repeating already attempted candidates. Empty
results offer retry for incomplete checks; checked non-matches can offer an
applicable year/runtime/genre change or opt-in rentals while preserving all other
choices. The UI describes the films checked, rather than claiming no film exists.

## Validation

The real JavaScript replay covers the UK funny/Ted Lasso/all-channels request,
spoken “Yes, please”, altered extraction output, duplicate completion events,
delayed context commit, text confirmation, muting, restart and targeted recovery.
Backend tests cover sync/async extraction, explicit restrictions, provider
exceptions versus checked non-matches and free-channel availability.
Final regression run: **314 passed, 4 skipped** (opt-in live extraction tests),
in 73.28 seconds. `git diff --check` passed.

`scripts/validate_unrestricted_voice.py` is an opt-in live check with mocks off.
The recorded run used live model extraction, preserved Ted Lasso, selected all
11 UK services, kept any year and included-only access, and retained the exact
context after “Yes, please.” It discovered 17 candidates and returned seven
availability-verified films in 17.35 seconds, including Paddington 2, Cool
Runnings and Hunt for the Wilderpeople. Seven availability checks were
unverified; these were excluded and reported separately, not presented as
matches. The report is `validation/unrestricted_voice/live_acceptance.json`.
This is one local live measurement, not a latency guarantee or proof of the
cause of the original empty shortlist, for which no recording/log was supplied.

These changes are local. Physical microphone/speaker testing and production
deployment are not part of this validation.
