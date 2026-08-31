Agentic Cinema Brief 2: Production-Grade Service Contracts and Backend Core Engine
For Gemini CLI. 31 August 2026.

**In one sentence:** We will define shared typed API contracts, spike and integrate UK/US streaming availability, and refactor our pipeline into a live-calling, six-dimension recommendation engine that ranks results dynamically based on a user's context.

Context: Brief 1 closed as a qualified technical PASS on 2026-08-31, successfully validating that Parallel Search + Extract combined with Gemini structured scoring produces grounded, non-invented film profiles for Babylon (2022). Per hackathon guidelines, development is now handed over to Gemini CLI. The old seven-dimension rubric is superseded by a modern six-dimension Film Profile, and the pipeline must transition from a dev-time batch-caching spike into a live runtime service called within a user session.

Brief type: New architecture and service integration.

Environment:
- Python 3.11+ (running in Windows .venv, calling the interpreter directly).
- Packages: `google-cloud-aiplatform` and `parallel-web` must be imported cleanly.
- Secrets: `PARALLEL_API_KEY` and Google Cloud credentials must remain inside the gitignored `.env` file. Never commit `.env` or print a full secret key.

Ownership Split:
- **Tina (Production Front End):** Owns the user flow, front-end code, visual design, microcopy, responsive layout, front-end QA, and final UX decision-making.
- **Nate / Gemini CLI (Backend & Data Services):** Owns shared typed contracts, agent runtime, availability integration, review retrieval services, ranking, logging, deployment, and backend QA.

---

### Step 1: Shared Typed Contracts Definition
**Effort:** default
**Do:** Define comprehensive typed API contracts (Pydantic models) to represent the expanded product contract. These types must be shared with Tina's front end. They must explicitly express:
1. **Per-signal tagging:** Tagging intake preferences as hard constraints, soft session preferences, or possible persistent preferences.
2. **Taste-signal provenance:** Explicit statement vs. repeated behavior vs. inference, attached to persistent preferences.
3. **Tri-state availability:** A title's status must be represented as `available`, `unavailable`, or `unverified` (never a flat boolean).
4. **Evidence State:** A 4-value enum: `strong agreement`, `meaningful disagreement`, `sparse evidence`, or `mainly official-factual`.
5. **Output Shape:** "Top 3 for tonight" with explicit roles (`Best fit`, `Strong alternative`, `Worth a stretch`) plus up to 7 total ranked results.
6. **Refinement-intent routing:** Distinct types representing `More like this`, `Something shorter/lighter/less intense`, `None of these`, or `Free text`.
7. **Interaction-state tracking:** `recommended`, `selected-intended`, `confirmed-watched`, or `liked-disliked-rejected` states.
8. **Intake-depth options:** Three levels of user effort (`Just give me something`, `A couple of questions is fine`, `Get to know what I want`).
**File:** `src/contracts.py`
**Gemini CLI must not change:** The six-dimension Film Profile names (Story and writing, Pacing and structure, Performances, Tone and emotional character, Craft and execution, Accessibility and demandingness).
**If blocked:** Consult Tina to ensure she approves the contracts before they are locked.
**Verify:** Instantiate and validate Pydantic test cases for each of the core structures.

### Step 2: Availability Model Spike
**Effort:** default
**Do:** Write a spike script to test real-time availability via Watchmode, TMDB, or JustWatch. Test at least 10+ titles across both UK and US markets. The model must support title-level country availability, included-access vs. rent/buy distinction, and return correct tri-state results (available, unavailable, unverified).
**File:** `src/availability_spike.py`
**Gemini CLI must not change:** Unverified titles must stay ineligible but remain distinct internally from confirmed-unavailable. The user's country (UK/US only) must be explicitly confirmed before being used for eligibility. No service may be preselected by default.
**If blocked:** If the primary provider has coverage issues, try TMDB/JustWatch as fallbacks. Do not commit to a provider until 10+ titles are validated in both markets.
**Verify:** Print a clear comparative table in console showing results for the 10+ titles in both countries.

### Step 3: Runtime Review Service Refactoring
**Effort:** default
**Do:** Refactor the Brief 1 spike scripts into a callable runtime service. The service must call `client.search()` and the Extract API live during a user session. Implement append-only trace/cost logging to `logs/`, and use caching strictly as a latency optimization, not as a replacement for live calling.
**File:** `src/review_service.py`
**Gemini CLI must not change:** Parallel Search API must be called dynamically at runtime as part of a real user session. No batch-only caches.
**If blocked:** If search returns thin results, dynamically adjust search objectives.
**Verify:** Run a test execution and confirm that dynamically fetched review data is successfully outputted and logged.

### Step 4: Dynamic Profiling and Scoring Engine
**Effort:** ultrathink
**Do:** Implement the core scoring engine that maps extracted reviews to the six-dimension Film Profile and synthesizes the Evidence State. Build dynamic weighting of soft preferences against user context to compute a Personal Fit Score. Include the separate "stretch signal" to power the "Worth a stretch" recommendation role. Ensure compliance with copyright/quotation guidelines (paraphrasing, max 6-word exact quotes).
**File:** `src/scoring_engine.py`
**Gemini CLI must not change:** The six Film Profile dimensions are fixed. Follow strict evidence discipline (thin evidence should keep a score at 3 or null).
**If blocked:** Tighten prompts if the model hallucinates outside the supplied sources.
**Verify:** Run scoring on Babylon using the new six-dimension contract and verify grounding, evidence sufficiency, and correct Evidence State categorization.

### Step 5: Backend Vertical Slice Simulation
**Effort:** ultrathink
**Do:** Connect the review service, availability checker, and scoring engine into an end-to-end vertical slice simulation. Demonstrate a complete mock user session: intake parsed, country/services confirmed, candidate pool established, availability filtered, dynamic weights applied, final "Top 3 + 4 extra" recommendations generated with warm, concise, natural language explanations.
**File:** `src/vertical_slice.py`
**Gemini CLI must not change:** Respect the anonymous-first rule and the "Top 3" roles (Best fit, Strong alternative, Worth a stretch).
**If blocked:** If performance or token costs are too high, tune candidate pool size and caching strategies.
**Verify:** Execute the simulation and log the entire transaction JSON and final recommended watchcards.

### Step 6: Automated Testing & Validation
**Effort:** default
**Do:** Write automated unit and integration tests to cover contract validation, scoring grounding rules, tri-state availability logic, and ranking calculations. Test failure states such as API timeouts or bad responses.
**File:** `tests/test_contracts.py`, `tests/test_scoring.py`, `tests/test_availability.py`
**Gemini CLI must not change:** Do not skip writing verification tests.
**Verify:** Run tests via pytest (or similar Python test runner) and ensure all tests pass.

### Step 7: Cloud Deployment Prep
**Effort:** default
**Do:** Deploy the vertical slice to Google Cloud (e.g., Vertex AI Agent Engine or Cloud Run). Implement structured logging and cost-tracking.
**File:** `src/deploy.py` or deploy scripts
**Gemini CLI must not change:** No credentials committed to GitHub.
**Verify:** Send a test payload to the hosted endpoint and verify a valid JSON recommendation response.

---

### What comes after this brief, once Step 5 checks out:
- **Brief 3**: Web UI integration and mock integration with Tina's production front end.
- **Brief 4**: Full state persistence, returned-user memory, and editable "My taste" controls.
- **Brief 5**: Demo prep, final security auditing, repo visibility decision, and submission.
