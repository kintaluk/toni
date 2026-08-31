# TONI - Decisions Log

This document tracks active product and technical decisions for **Tonight’s Own Next Indulgence** (TONI), serving as a durable, lightweight record of our architectural choices and product commitments.

---

### Active Decisions

#### [DEC-001] Transition from 7-Dimension Rubric to 6-Dimension Film Profile
* **Decision:** The experimental 7-dimension rubric used in Brief 1 is replaced by a stable 6-dimension Film Profile (`Story and writing`, `Pacing and structure`, `Performances`, `Tone and emotional character`, `Craft and execution`, `Accessibility and demandingness`). 
* **Rationale:** Better represents professional critical assessments without force-fitting consensus or confusing a static film profile with dynamic user contexts. "Rewatch value" was deleted as unreliable; "Critical consensus vs divergence" has moved to a separate Evidence State to avoid flattening disagreement into false consensus.
* **Date:** 2026-08-31
* **Source:** Task 04 (MVP Decision Record)

#### [DEC-002] Separate Evidence State from Film Profile
* **Decision:** Evidence State is tracked separately from the core Film Profile dimensions as a 4-value enum (`strong agreement`, `meaningful disagreement`, `sparse evidence`, `mainly official-factual`).
* **Rationale:** Prevents flattening disagreement into false consensus; when disagreement could materially change the decision, we explain why in concise, taste-relevant language instead of skewing the film's core scores.
* **Date:** 2026-08-31
* **Source:** Task 04 (MVP Decision Record)

#### [DEC-003] Explicit User Country & Service Access Confirmation
* **Decision:** The country of viewing (UK or US only) must be explicitly confirmed by the user before checking streaming eligibility. No streaming services may be pre-selected by default.
* **Rationale:** Avoids misidentifying available streams due to IP mismatch, and respects legal/subscription boundaries (e.g., legally gated but "free" services like BBC iPlayer in the UK require explicit TV Licence confirmation).
* **Date:** 2026-08-31
* **Source:** Task 03 (Availability Approach) & Build Handover

#### [DEC-004] Tri-State Streaming Availability & Ineligibility Logic
* **Decision:** Streaming availability status for any title must be tracked as a tri-state enum: `available`, `unavailable`, or `unverified`. Titles that return `unverified` are treated as ineligible for recommendations but stay internally distinct from confirmed `unavailable`.
* **Rationale:** Guarantees we do not recommend films that cannot be verified as watchable tonight, while maintaining high observability and debugging capabilities.
* **Date:** 2026-08-31
* **Source:** Task 04 & Build Handover

#### [DEC-005] Live-Calling Parallel Search & Extract at Runtime
* **Decision:** Parallel's Search and Extract APIs must be called dynamically at runtime as part of a live user session. Caching may only be implemented as a latency optimization layer on top.
* **Rationale:** A core eligibility requirement for the Parallel track of the Agentic Cinema hackathon. Batch-only caching of search data does not satisfy the rules.
* **Date:** 2026-08-31
* **Source:** Parallel Track Devpost Guidance & CLAUDE.md Rule 8

#### [DEC-006] Movie-First and Anonymous-First MVP Scope
* **Decision:** The hackathon MVP strictly excludes TV/television, group viewing, theatrical listings, and general-purpose chat. It requires an anonymous-first flow allowing a user to obtain recommendations before prompting for saving or sign-in.
* **Rationale:** Limits MVP scope to ensure a polished, visually and technically complete experience within the tight hackathon timeframe.
* **Date:** 2026-08-31
* **Source:** Task 04 / Build Handover
