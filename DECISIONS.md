# TONI Technical Decision Record

This document records material technical decisions made during the TONI build.
Its purpose is to preserve why decisions were made, not just what the current code happens to do.

## Decision Status
- **Proposed**: under consideration
- **Confirmed**: agreed and implemented or ready to implement
- **Superseded**: replaced by a later decision
- **Hackathon-only**: pragmatic choice for the prototype, not assumed to be permanent

---

## Active Decisions

### DEC-001: Transition from 7-Dimension Rubric to 6-Dimension Film Profile
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Recommendation Model
* **Decision:** The experimental 7-dimension rubric used in Brief 1 is replaced by a stable 6-dimension Film Profile (`story_and_writing`, `pacing_and_structure`, `performances`, `tone_and_emotional_character`, `craft_and_execution`, `accessibility_and_demandingness`).
* **Why:** Better represents professional critical assessments without force-fitting consensus or confusing a static film profile with dynamic user contexts. "Rewatch value" has been deleted; "Critical consensus vs divergence" has moved to a separate Evidence State to avoid flattening disagreement into false consensus.

### DEC-002: Separate Evidence State from Film Profile
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Data Model
* **Decision:** Evidence State is tracked separately from the core Film Profile dimensions as a 4-value enum (`strong_agreement`, `meaningful_disagreement`, `sparse_evidence`, `mainly_official_factual`).
* **Why:** Prevents flattening disagreement into false consensus; when disagreement could materially change the decision, we explain why in concise, taste-relevant language instead of skewing the film's core scores.

### DEC-003: Explicit User Country & Service Access Confirmation
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** User Experience & Integration
* **Decision:** The country of viewing (UK or US only) must be explicitly confirmed by the user before checking streaming eligibility. No streaming services may be pre-selected by default.
* **Why:** Avoids misidentifying available streams due to IP mismatch, and respects legal/subscription boundaries (e.g., legally gated but "free" services like BBC iPlayer in the UK require explicit TV Licence confirmation).

### DEC-004: Tri-State Streaming Availability & Ineligibility Logic
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Availability / Integration
* **Decision:** Streaming availability status for any title must be tracked as a tri-state enum: `available`, `unavailable`, or `unverified`. Titles that return `unverified` are treated as ineligible for recommendations but stay internally distinct from confirmed `unavailable`.
* **Why:** Guarantees we do not recommend films that cannot be verified as watchable tonight, while maintaining high observability and debugging capabilities.

### DEC-005: Live-Calling Parallel Search & Extract at Runtime
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Architecture
* **Decision:** Parallel's Search and Extract APIs must be called dynamically at runtime as part of a live user session. Caching may only be implemented as a latency optimization layer on top.
* **Why:** A core eligibility requirement for the Parallel track of the Agentic Cinema hackathon. Batch-only caching of search data does not satisfy the rules.

### DEC-006: Movie-First and Anonymous-First MVP Scope
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Product Scope
* **Decision:** The hackathon MVP strictly excludes TV/television, group viewing, theatrical listings, and general-purpose chat. It requires an anonymous-first flow allowing a user to obtain recommendations before prompting for saving or sign-in.
* **Why:** Limits MVP scope to ensure a polished, visually and technically complete experience within the tight hackathon timeframe.

### DEC-007: FastAPI HTTP Service, Web Demo UI & Runtime Evidence Wiring
* **Date:** 2026-08-31
* **Status:** Confirmed / Hackathon-only
* **Area:** Architecture & Interface
* **Decision:** Wrap the backend recommendation pipeline with a lightweight FastAPI service and provide an interactive single-page web demo UI (`/`). Wire `get_film_evidence()` directly into recommendation generation to ensure Parallel Search and Extract APIs are actively invoked at runtime for every session, attaching verified source URLs to recommendation cards.
* **Why:** Enables frontend integration with Tina's interface, simplifies cloud deployment to Google Cloud Run, and guarantees strict compliance with the Parallel track hackathon eligibility requirements.

### DEC-008: Local Hybrid Mock & CI Isolation Flag
* **Date:** 2026-09-02
* **Status:** Confirmed / Hackathon-only
* **Area:** Availability / Integration / Testing
* **Decision:** We introduce a local hybrid mock adapter for our seed pool movies that activates when API keys are absent, or when the `TONI_USE_MOCK_AVAILABILITY` environment variable is explicitly set to `"true"`.
* **Why:** This ensures credentials-free local evaluation, offline capability, rapid testing, and robust test isolation. In the test suite, we force `TONI_USE_MOCK_AVAILABILITY="true"` and stub the `Parallel` client globally to prevent live API leaks, ensuring unit and integration tests run deterministically in under 1 second without making outbound network queries regardless of the environment.

### DEC-009: Static Film Profiles and Consensus in Hackathon MVP (Hackathon-only)
* **Date:** 2026-09-02
* **Status:** Confirmed / Hackathon-only
* **Area:** Recommendation Model / AI Profiling
* **Decision:** We use high-fidelity, static, pre-calculated 6-dimension Film Profiles and Evidence States for the canonical seed movie pool in the MVP, rather than invoking live Gemini LLM profiling requests on every user session.
* **Why:** This ensures lightning-fast user response times, lower api credit burn, and guaranteed deterministic evaluations during the hackathon judging. The dynamic LLM profiling function (`generate_film_profile` in `src/profiling.py`) is fully designed and contract-compliant, but remains deliberately unwired for this round as a strategic product decision.

---

## Superseded Decisions

### DEC-000: Initial Seven-Dimension Rubric (Brief 1)
* **Date:** 2026-08-25
* **Status:** Superseded by DEC-001
* **Area:** Recommendation Model
* **Decision:** Use a 7-dimension rubric (Story, Pacing, Performances, Tone, Craft, Accessibility, Rewatch value) implemented in `src/score_rubric.py` to evaluate films.
* **Why:** Initial draft of movie profiling from Brief 1. Superseded in Brief 2 to align with professional reviews and separate consensus/divergence evidence state from static film profiles, removing "Rewatch value".

---

## Decision Template (For Reference)

### TD-XXX: Decision Title
* **Date:** YYYY-MM-DD
* **Status:** Proposed / Confirmed / Superseded / Hackathon-only
* **Owner:**
* **Area:** Architecture / Data / AI / Search / Availability / Security / Deployment / Other

**Decision**
What was decided.

**Why**
The reasoning behind the decision.

**Alternatives considered**
What else was considered, if relevant.

**Implications**
What this affects.

**Permanent or prototype?**
Whether this should survive beyond the hackathon.
