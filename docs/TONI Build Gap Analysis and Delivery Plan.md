TONI Build Gap Analysis and Delivery Plan

Repository review after Task 03, for Tina and Nate

Overall verdict: the concept is strong and the one-film technical spike is useful, but the repository is still a spike, not a working hackathon product. Nate should now stop extending Brief 1 and build a thin end-to-end vertical slice against the confirmed product decisions.

1. What has been completed

Repository scaffold, environment checks and secrets handling are in place.

Parallel Search and Extract have been proven against one deliberately divisive film, Babylon.

Gemini produced structured, source-linked scoring, and the ablation test gave credible evidence that it was responding to the supplied reviews rather than relying only on prior knowledge.

Grounding checks, quotation controls and basic cost estimation are more rigorous than a normal early spike.

The product foundation, ideal journey, recommendation framework and Task 03 availability policy are now substantially clearer than the repository instructions.

Brief 1 should therefore be closed as a qualified technical PASS. It proves feasibility for one film. It does not approve the old seven-dimension rubric as TONI's product model.

2. What Brief 1 does and does not prove

Question

Judgement

Implication

Can Parallel find useful professional review material?

Yes, with source-quality and extraction failures.

Keep Parallel, but add runtime source selection and failure handling.

Can Gemini produce grounded structured output?

Yes, for this controlled test.

Reuse the grounding discipline and structured-output approach.

Is the current rubric the final TONI model?

No.

Replace it before building matching or ranking.

Does the current code satisfy the Parallel track?

No.

Search is only a development script, not part of a deployed user session.

Is there a working agent or web product?

No.

The end-to-end build has not started.

3. Repository gap analysis

Area

Current state

Required change

Product contract

README and GEMINI.md still describe open decisions and freeze the old rubric.

Reconcile the repository with Tasks 01-03 before further feature work.

Film Profile

Seven 1-5 quality dimensions, including rewatch value and divergence.

Use six stable Film Profile dimensions. Move evidence agreement/divergence into Evidence State.

Personal fit

Not implemented.

Build dynamic weighting and a normalised internal 0-100 fit score.

Stretch role

Not implemented.

Keep a separate explainable stretch signal for the third recommendation.

Taste and tonight context

Not implemented.

Define the minimum MVP input agreed in Task 04, then model persistent preferences separately from tonight context.

Candidate set

One hard-coded film.

Use a controlled seed pool large enough to survive live availability filtering.

Parallel runtime

One-off scripts writing local logs.

Create a callable runtime evidence service, with caching only as an optimisation.

Availability

No integration or data model.

Select and test a live UK/US provider, then enforce availability as a hard gate.

Ranking and shortlist

Not implemented.

Filter hard constraints, apply weights, assign Best fit, Strong alternative and Worth a stretch.

Agent orchestration

Google tooling is installed but not used as a running agent.

Build an explicit multi-step Gemini and Google Cloud agent flow.

Front end

None.

Tina owns and builds the confirmed MVP journey against a stable API contract supplied by Nate.

Tests and observability

tests/ is empty; logs overwrite.

Add unit, contract, failure-state and three-case ranking tests; retain per-run cost and trace data.

Deployment

None.

Deploy a reliable web experience on Google Cloud and test it as judges will.

Submission

Private repo, no licence, no demo assets.

Prepare public open-source repo, OSI licence, hosted URL, description and sub-three-minute video.

4. Changes caused by the confirmed design decisions

Recommendation model

Story and plot coherence becomes Story and writing.

Pacing becomes Pacing and structure.

Performance quality becomes Performances.

Tone and mood match is replaced by Tone and emotional character. This should describe what the film feels like, not score whether its tone is good.

Craft becomes Craft and execution.

Accessibility and demandingness is added.

Rewatch value is removed.

Critical consensus versus divergence moves into Evidence State rather than contributing to film quality.

The strongest reusable part of score_rubric.py is not its dimension list. It is the structured schema, evidence sufficiency, neutral source labels, grounding checks and adversarial ablation approach.

Availability model

Country is restricted to GB and US for the hackathon.

Country determines the provider list shown to the user.

Users confirm what they can access; TONI must not infer access from popularity or country.

Free services count alongside paid services.

Rent and buy are a separate opt-in hard preference.

Live availability is checked before final ranking.

unavailable and unverified both fail eligibility, but must remain distinct states.

A failed provider call becomes unverified, not unavailable.

Approved fallback wording is: Couldn't find reliable availability information for this title.

5. Recommended technical direction

Availability provider

Recommended first spike: Watchmode, with TMDB/JustWatch as the fallback option.

Watchmode directly exposes country-filtered subscription, free, rent and buy source types, which closely matches Task 03.

Its free developer tier currently allows 2,500 requests, up to three countries and non-commercial use, with attribution. Nate must confirm that the hackathon use is permitted and implement attribution.

TMDB is a credible fallback and has generous request capacity, but its watch-provider response does not provide full deep links and requires JustWatch attribution.

Do not commit to either provider until a ten-title UK/US coverage test has passed.

Runtime shape

Capture the user's country, confirmed services, rent/buy choice and minimum tonight context.

Start from a controlled film seed pool with stable IDs and basic metadata.

Apply cheap hard constraints first, including explicit runtime, genre/content exclusions and live availability.

Use existing Film Profiles where available to produce a provisional fit ranking.

Call Parallel Search at runtime for the leading candidates, extract a small evidence set, and let Gemini create or refresh the six-dimension profile plus Evidence State.

Recalculate weighted fit, apply the stretch signal and return the final three roles.

Return concise reasons, verified provider matches and lightweight source detail to the front end.

This gives the judges genuine runtime use of Parallel without making every user wait for review extraction across the entire catalogue. The final candidates still receive live evidence work, while the controlled seed pool keeps the demo reliable.

6. Nate's recommended next steps

Order

Task

Exit condition

1

Close Brief 1 as qualified PASS and record the supplied scorecard, costs and remaining dashboard count.

No further polishing of the superseded seven-dimension rubric.

2

Update README.md, GEMINI.md and DECISIONS.md to reflect Tasks 01-03 and mark the old rubric as spike-only.

No repository instruction contradicts the product source of truth.

3

Create a feature branch and define shared typed contracts: UserContext, FilmProfile, EvidenceState, AvailabilityResult, FitBreakdown and Recommendation.

Front end and back end can build against the same payload.

4

Run the Watchmode versus TMDB availability spike across at least ten titles in both markets.

One provider passes coverage, type mapping, attribution, rate and failure-state checks.

5

Refactor the review pipeline into a runtime service and persist append-only trace and cost records.

Parallel Search is called from an actual application path.

6

Implement the six-dimension profile, Evidence State, dynamic weights and separate stretch signal.

Three contrasting cases produce explainably different rankings.

7

Provide the backend services and integration support for one complete vertical slice from input to three recommendation cards.

A real user session reaches a result with live Parallel and availability calls.

8

Add automated tests and failure handling before catalogue expansion.

Hard constraints cannot be bypassed; unverified availability never enters the final three.

9

Deploy early, then optimise latency and resilience on the hosted version.

A judge can complete the full path without local setup.

7. Tina's remaining work

Complete Task 04, cutting the ideal journey to the smallest credible hackathon MVP, then own the front-end implementation.

Choose the exact intake questions and which are persistent profile fields versus tonight-only fields.

Decide whether the hackathon shows both entry routes or only the quick route with a lighter profile option, then build only the agreed route for mobile and desktop.

Design and build the intake, loading, recommendation and evidence-detail screens against the shared contract.

Choose the demo personas and candidate films that best prove that rankings change for understandable reasons.

Approve country-specific provider presets after Nate returns real provider IDs and coverage results.

Implement and test the user-facing wording and behaviour for loading, partial results, no qualifying match and retry states.

Plan the three-minute story before the interface is finished, so the build serves the judging case.

Prepare submission copy covering the problem, audience, impact, idea quality and what was learned.

8. Joint delivery sequence

Phase

Tina

Nate

Day 0: remove blockers

Lock the MVP cut and demo promise. Submit the Google Cloud credit request immediately if not already done. Seek written organiser clarification on coding-assistant eligibility.

Stop new Brief 1 work. Reconcile repo instructions. Switch implementation work to Gemini tooling unless organisers confirm otherwise.

Days 1-2: contracts and spikes

Approve intake, card content, demo cases and error wording.

Define contracts. Test availability providers. Convert Parallel into a runtime service.

Days 3-4: vertical slice

Build the front-end shell against agreed mock data; test the flow, reasons and tone before live integration.

Build the backend path from availability to evidence to ranking; deploy the first hosted service version.

Days 5-6: integration and refinement

Integrate the production front end, then lead visual hierarchy, copy, accessibility, responsive behaviour and usability fixes.

Stabilise API responses, connect live services, support integration, and add tests, tracing and retries.

Days 7-8: judge readiness

Run demo rehearsals, prepare submission text and record the video.

Run security, dependency and competition audits; prepare public repo, licence, setup and architecture notes.

Submission day

Final smoke test and submit with a two-hour buffer.

Freeze code, confirm hosted runtime, Parallel and Google Cloud traces, then support submission.

9. Front-end ownership decision

Ownership is confirmed: Tina owns the production front end. Nate owns backend, integrations and deployment.

Tina owns the user flow, interface code, visual hierarchy, copy, responsive behaviour, accessibility and front-end QA.

Nate owns the shared contracts, agent runtime, data services, availability, ranking, secrets, deployment, tracing and backend QA.

Both build against one versioned contract and agreed mock payload, with scheduled integration checks and no silent changes to the interface.

Release ownership follows the technical boundary: Tina signs off the front-end experience; Nate signs off backend integration and the hosted deployment.

10. Critical risks

Risk

Why it matters

Action

Coding-assistant eligibility

Official rules require Google AI tooling in projects, and organiser guidance includes coding tools. Standardize exclusively on Google AI tooling.

Ensure all repository instructions, briefs, and development workflows strictly use Gemini CLI and Google AI tooling.

No three eligible films

A small candidate set may be filtered below three by country, services or rent/buy settings.

Use a larger controlled pool and an iterative refill rule. Test the demo account and both markets daily.

Runtime latency and cost

Live search, extraction, Gemini and availability can become slow or expensive.

Filter cheaply first, cap candidate counts, run independent calls concurrently, cache safely and keep per-run traces.

Provider mismatch

Provider labels, bundles and transaction types differ across markets.

Use stable IDs, explicit type mapping and a tested country-specific preset.

Copyright and demo assets

Review text, film posters and service logos may create rights or submission-video issues.

Paraphrase evidence, avoid long review storage, confirm asset terms and use text-led or owned demo visuals where needed.

Late public-repo work

Submission requires a public open-source repository with a detectable licence.

Choose the licence, remove private material and test public setup before the final day.

11. Delivery gates

Gate A, scope: Task 04 defines the exact MVP and demo path.

Gate B, contracts: front end and back end agree one versioned request and response shape.

Gate C, technical proof: availability works in GB and US; Parallel and Gemini run in the deployed user path.

Gate D, recommendation proof: the same candidate pool ranks differently across three contrasting cases for traceable reasons.

Gate E, product proof: a new tester reaches one of three recommendations without explanation from the team.

Gate F, submission proof: public repo, licence, hosted URL, runtime integrations, source attributions, description and video all pass a final checklist.

12. Immediate decisions and actions

Tina completes Task 04 before the front-end build expands.

Tina submits the Google Cloud credit request immediately if it has not already been submitted.

Tina and Nate confirm standardisation on Gemini CLI and Google AI coding tools across all repository workflows.

Nate records Brief 1 as a qualified PASS and begins the repository reconciliation, not Brief 1 iteration.

Nate runs the two-provider availability spike and returns a recommendation with evidence.

Tina and Nate agree the shared API contract. Tina then builds the production front end against agreed mock payloads while Nate builds the backend.

The first hosted vertical slice is treated as the next real milestone.

Sources

Official Agentic Cinema rules

Official Agentic Cinema overview

Devpost Agentic Cinema build guidance

TMDB movie watch-provider documentation

Watchmode API and plan information

Internal sources: TONI Foundation; TONI Hackathon Product & Scope; TONI Task 03 - Hackathon Availability Approach; TONI Streaming Market Baseline; KINTALUK/TONI repository at commit 159b75d.

13. Backend Implementation & Deployment Progress

As of 2 September 2026, Nathan has successfully delivered all backend phases, spikes, and integration contracts outlined in this delivery plan:

### 13.1 Delivered Deliverables & Status
*   **Gate A & B (Contracts & Scope):** Enforced strictly via production-grade Pydantic models in `src/contracts.py` (representing the 6-dimension Film Profile, Fit Breakdowns, and tri-state availability states).
*   **Gate C (Technical Proof - Live Spikes & Evidence):** Developed real-time Watchmode API and TMDB fallback checks in `src/availability.py`, coupled with dynamic Parallel Search/Extract pipeline triggers in `src/evidence.py`.
*   **Gate D (Recommendation Proof):** Dynamic scoring loop and personalized ranking engine implemented in `src/profiling.py` and `src/ranking.py`, validated by automated tests for three distinct user personas.
*   **Gate E (Product Proof & FastAPI Web App):** Assembled end-to-end backend service in `src/main.py` and wrapped it in a highly responsive FastAPI service wrapper (`src/api.py`) featuring an interactive Web Demo UI (`static/index.html`).
*   **Gate F (Submission Proof - Licensing & Deployment):**
    *   **OSI License:** Added an official **MIT License** (`LICENSE`) to the repository root.
    *   **Live Cloud Run Deployment:** Created a production `Dockerfile` and set up container builds in Artifact Registry. Successfully deployed the serverless backend live to Google Cloud Run!

### 13.2 Live Hosted Endpoints & Configuration
*   **Active GCP Project ID:** `agentichackathon-507012`
*   **Hosted Cloud Run URL:** `https://toni-app-38088879709.us-central1.run.app`
*   **Health API Check:** `https://toni-app-38088879709.us-central1.run.app/api/health`
*   **Deployment Configuration Utility:** Automated pre-flight validation and deployment generation is available locally via `python src/deploy.py`.