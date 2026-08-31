TONI Build Handover - MVP Implementation Contract

Purpose: Builder-facing implementation contract derived from the approved Task 04 MVP decision record. If an implementation question is answered here or in the Task 04 product contract, do not invent a different product rule. Escalate only genuine contradictions or missing behaviour.

1. Non-negotiable product outcome

Build a working film-first TONI experience that can:

understand a user's tonight context with variable intake depth

use persistent taste context for returning users

research film evidence live through Parallel at runtime

build/use the six-dimension Film Profile

apply hard constraints and contextual weighting

verify live UK/US availability against confirmed service access

return Top 3 for tonight, with seven total recommendations available

support bounded guided and free-text refinement

save useful persistent taste/access/history after value has been demonstrated

2. Build dependency order

Priority 1: anonymous end-to-end recommendation loop.

Priority 2: save/sign-in layer that preserves useful state.

Priority 3: returning-user memory applied to recommendations.

Priority 4: editable My taste controls and memory refinement.

Do not let authentication/profile work delay a qualifying runtime recommendation path.

3. Intake contract

Entry offers three effort levels:

Just give me something

A couple of questions is fine

Get to know what I want

The pace choice controls intake length only, not output quality.

Fast mode may ask one essential clarification maximum. After that, recommend.

Taste anchor is adaptive. Do not force one in fast mode when the user's request is already sufficient. In deeper modes, seek or derive one when it improves personalisation.

Conversation is for subjective/contextual input. Structured controls are preferred for country, services and rent/buy.

4. Context parsing

The system should be able to extract, when present:

mood

energy

tone

runtime/time constraint

genre

pacing appetite

demandingness

explicit exclusions

taste anchors

watched/repeat preference

Represent whether each signal is a hard constraint, soft session preference or possible persistent preference. Do not collapse all user statements into one undifferentiated prompt.

5. Persistent memory boundary

Persist structured useful memory rather than relying on full historical chats.

Minimum persistent domains:

service access

enduring taste signals

recommended titles

confirmed watched titles where known

likes

dislikes

rejections/corrections

Every durable taste signal should retain enough provenance to distinguish explicit statement, repeated behaviour and inferred preference. One-off tonight context must not automatically become persistent taste.

High-confidence inference is allowed. Exact confidence thresholds can be tuned during implementation.

Memory must be editable by the user through a lightweight My taste/profile surface.

6. First-use and account contract

Do not place an account wall in front of the first recommendation.

Anonymous user gets the full core recommendation experience.

After value is demonstrated, offer a lightweight save/sign-in step, for example Save your taste and recommendations?

Authenticated return visits may use saved taste, services and history as context, while still treating tonight's request separately.

7. Country contract

Supported hackathon markets: UK and US only.

The UI may detect a likely country but must ask for confirmation before availability eligibility is applied.

Outside UK/US, show the supported-market limitation. Do not substitute another market's data.

8. Service-access contract

Show a country-specific service list.

Include relevant paid and free services.

No service is preselected.

The user confirms what they can access, not what they personally pay for.

Use fast tap/select controls. Do not require service-name typing or a detailed subscription form.

Never infer service access because a provider is free, popular or present in the country.

9. Rent/buy contract

Ask separately whether additional-payment rental/purchase can count as available.

No means only selected included-access routes qualify.

Yes means verified rent/buy routes may also qualify.

Treat this as a hard eligibility setting.

10. Availability eligibility

For every candidate that can be exposed as a recommendation:

supported country

+ verified live availability

+ provider/service matches confirmed user access OR allowed rent/buy route

= eligible

No qualifying match = ineligible.

Unable to verify = ineligible.

Unverified and confirmed-unavailable should remain distinct internal states for explanation/debugging.

Approved unverified copy:

Couldn't find reliable availability information for this title.

Availability rules apply to all seven exposed recommendations, not only the Top 3.

11. Availability provider boundary

Provider selection is engineering-owned, provided it supports:

UK and US

title-level country availability

included/free versus rent/buy distinction adequate for TONI

acceptable attribution and terms

sufficient request limits/reliability

sample-title testing before demo lock

Do not weaken product eligibility because a selected provider cannot support the contract. Change provider or implementation.

12. Parallel runtime contract

Parallel Search must execute live as part of submitted user-session behaviour.

Do not satisfy this by expanding a development-time batch job whose cached output is the only evidence used at runtime.

Caching may optimise live behaviour but cannot replace the required runtime call.

Parallel evidence search and streaming availability are separate product functions.

13. Film Profile contract

Use six dimensions:

Story and writing

Pacing and structure

Performances

Tone and emotional character

Craft and execution

Accessibility and demandingness

Evidence State remains separate:

strong agreement

meaningful disagreement

sparse evidence

mainly official/factual evidence

Do not continue the Brief 1 seven-dimension rubric as the post-Task-02 product model.

14. Scoring/ranking contract

Architecture:

Evidence -> Film Profile -> contextual weighting -> Personal Fit Score -> shortlist role.

Hard constraints filter before final ranking.

Soft preferences affect ranking.

Weights must genuinely change results.

Personal Fit Score is an internal normalised ranking/comparison score. Do not show raw score by default.

Maintain a separate stretch signal for Worth a stretch.

15. Candidate pool contract

Generate/research enough candidate depth to support seven eligible recommendations where practical and to make refinement useful.

Do not interpret Top 3 as an internal candidate limit.

Exact candidate count is an optimisation variable based on evidence cost, Parallel latency, availability attrition and ranking quality.

A sensible implementation should expect some candidates to fail availability and therefore search more than seven before final selection.

16. Output contract

First view heading: Top 3 for tonight.

Role 1: Best fit.

Role 2: Strong alternative.

Role 3: Worth a stretch.

Top cards contain:

title

artwork

specific concise fit reason

runtime

where to watch

Deeper evidence is optional, for example Why this?

Do not show raw rubric machinery by default.

Spoiler-free by default.

17. Full recommendations contract

Secondary action: Show my full recommendations.

Expanded view contains seven total ranked recommendations where enough eligible options exist.

Only the first three require role labels. Four additional results remain ranked without forced labels.

Do not make the user request four completely new recommendations from scratch merely because they opened the full list. Prepare enough ranked depth up front for this interaction to feel responsive.

18. Refinement routing

More like this:

expand around the selected result; retain existing user/session model; fetch additional related candidates when needed.

Something shorter/lighter/less intense:

re-filter/re-rank existing pool first; fetch new candidates only if needed.

None of these:

record meaningful negative signal for the session; reassess pool and interpretation; use re-ranking plus fresh research where useful.

Free text:

classify whether the user is requesting re-ranking, expansion or a wider reset; choose the appropriate route.

Do not wire all refinements to identical search behaviour.

19. Refinement acknowledgement

Briefly tell the user what TONI changed. Do not expose exact internal weights unless a later product decision adds such a diagnostic mode.

Keep copy warm, concise, specific and non-chatty.

20. Memory update after sessions

Potential durable update inputs:

explicit enduring preference statements

repeated preference patterns

confirmed watches

explicit likes/dislikes

rejections/corrections

service-access corrections

Do not equate recommendation selection with confirmed viewing or liking.

Where state exists, distinguish:

recommended

selected/intended

confirmed watched

liked/disliked/rejected

21. Explicit non-MVP scope

Do not build unless separately authorised:

group viewing

TV recommendation coverage

WhatsApp/Messenger channels

avatar/animated TONI

household/shared profiles

Letterboxd/Trakt connectors

streaming-platform account login

bundle/tier entitlement automation

universal markets

deep cinema integration

live TV schedules

social/sharing platform

price comparison

live cultural-event intelligence

unrestricted general chatbot experience

22. Required failure states

At minimum preserve meaningful internal/user-safe handling for:

unsupported market

availability unavailable/no match

availability unverified/provider failure

insufficient recommendation candidates after filtering

Parallel/evidence retrieval failure

user session with minimal context

account save failure without losing anonymous result

A failure in an optional persistence layer must not destroy an otherwise valid recommendation result.

23. Validation matrix

Recommendation logic:

- same film candidate set, challenging-viewer context

- same set, tired/easy context

- same set, contextual/seasonal case

Expected: rankings change for traceable reasons; Film Profiles do not.

Availability:

- UK paid-service example

- UK free-service example with no assumed access

- US service mix

- rent/buy off and on

- provider returns no match

- provider cannot verify

Expected: only verified permitted routes survive.

Intake:

- fast request already sufficient

- fast request requiring one clarification

- medium/deep request using taste anchor

Expected: question budget respected and output quality maintained.

Refinement:

- More like this

- Something shorter

- None of these

- free-text mixed change

Expected: different routing behaviours, not identical search.

Memory:

- explicit enduring dislike

- one-off session request

- repeated behavioural signal

- user edits/removes memory

Expected: durable versus temporary state remains distinct.

24. Builder acceptance criteria

The MVP product contract is met when:

- first-time user can get recommendations without signing in

- user can choose intake depth

- fast mode never exceeds one essential clarification

- country is confirmed before availability filtering

- service access is explicit and nothing is preselected

- rent/buy is explicit

- Parallel is called live at runtime

- six-dimension Film Profile is used

- hard constraints remove ineligible films

- weights materially influence ranking

- Top 3 roles render correctly

- Show my full recommendations reveals up to seven total eligible results

- all exposed recommendations satisfy availability eligibility

- guided and free-text refinement work with intent-dependent routing

- user can save/create an account after receiving value

- returning user context can influence a later recommendation

- tonight context does not automatically overwrite durable taste

- user can inspect/edit persistent taste memory

- group mode and other future scope are absent from the MVP

25. Escalation rule

Do not reopen a settled product choice because an implementation shortcut would be easier.

Escalate only when:

a required third-party capability makes the contract impossible

hackathon rules conflict with the product contract

latency/cost evidence makes an agreed behaviour non-viable

testing exposes a real user contradiction

or the documents contain two genuinely incompatible current decisions.

Otherwise, make the narrowest implementation choice that preserves the product behaviour.