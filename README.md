# TONI

**Tonight’s Options, Narrowed Intelligently**

**Your personal guide to what’s worth watching next.**

TONI is an agentic cinema discovery product that helps people decide what to watch with less effort.

Instead of showing an endless catalogue, TONI learns enough about the viewer’s taste and current mood, checks what is available to them, evaluates relevant films using reviews and official information, and returns a focused shortlist with clear reasons for each recommendation.

TONI’s job is simple:

**Do the homework. Give me a clear steer. Tell me why. Leave the choice with me.**

## The Problem

Streaming has created abundance, but not necessarily easier decisions.

People can spend too long scrolling, checking multiple platforms, comparing reviews, or abandoning the choice altogether.

TONI reduces the gap between:

> “There are thousands of things I could watch”

and:

> “This is probably the right one for me tonight.”

**Core promise: Personal fit + less effort.**

---

## How TONI Works

The experience is structured around the complete reasoning loop:

### 1. Taste Intake
TONI asks a short, useful set of questions about factors such as:
- Genre, pacing, tone, and mood
- Recent likes, dislikes, and specific exclusions
- **Intake Depth Options:** User selects their effort budget at entry (`Just give me something`, `A couple of questions is fine`, or `Get to know me`).

### 2. Live Availability Checking
Recommendations are dynamically filtered using live, country-specific (UK/US) streaming availability data (powered by Watchmode and TMDB) against the user's explicit service list and extra-cost rent/buy preferences.

### 3. Live Evidence Gathering (Parallel Search & Extract)
The web app shows available films and factual details first, then streams review analysis into the existing cards. It checks cached evidence before searching professional review outlets, including RogerEbert.com, Empire, The Guardian, BFI, Variety and The Hollywood Reporter. When coverage is insufficient, it announces a broader search and tries other sources. Failed analysis retains usable source links and leaves unassessed dimensions clearly labelled.

### 4. Personal Matching & Scoring
The initial web shortlist is matched using preferences, metadata and verified availability. Review enrichment adds the six-dimension critical profile without changing the displayed order. The synchronous API also supports evidence-led ranking. Internal fit scores are not displayed to viewers.

### 5. Focused Output
TONI returns a clean, focused ranked shortlist:
- **Top 3 for Tonight:** `Best fit`, `Strong alternative`, and another eligible option. An evidence-led `Worth a stretch` role is reserved for the synchronous ranking path.
- **Expanded Watchlist:** Up to 7 total eligible recommendations upon tapping *Show my full recommendations*.

---

## Recommendation Principles

TONI should:
- Put personal fit first
- Reduce choice rather than increase it
- Explain recommendations clearly and in a spoiler-free manner
- Distinguish between mixed evidence and limited evidence
- Use reviews and official information as evidence without blindly following popularity
- Keep the user in control of the final decision

---

## What Makes TONI Different

TONI is not a review aggregator, nor is it another infinite catalogue. Its core difference is:

**Personalized decision support with transparent, evidence-based reasoning.**

Traditional viewing guides answered: *"What’s on?"*  
TONI answers: *"What’s worth watching for me?"*

---

## Audience Contracts

- **Primary (Film-aware but time-poor viewers):** They understand their taste but don't want to research every viewing decision. We optimize the default experience for them.
- **Secondary (Choice-overloaded mainstream streamers):** They want a useful recommendation quickly, with deeper reasoning available on demand.
- **Tertiary (Film enthusiasts and cinephiles):** They want deep, source-level reasoning, critical disagreement, and adventurous discovery, available via *Why this?*

---

## Brand Voice

TONI is intended to feel:
- **Warm**, not clinical
- **Lightly witty**, not jokey
- **Film-aware**, not snobbish
- **Confident**, but reasoned
- **Specific** rather than generic
- **Helpful** without becoming over-chatty

TONI sounds comfortable making a recommendation without pretending to have personal taste or first-hand viewing experience.

---

## Hackathon MVP Scope

The hackathon prototype is focused on proving the complete, end-to-end live reasoning loop for a controlled pool of seed films.

### Excluded from MVP (Out of Scope)
- Television/TV shows (movie-first focus)
- Group viewing (solo experience only)
- WhatsApp or Messenger companion bots
- Streaming platform account logins
- Universal market coverage (UK and US only)

---

## Development Setup

The backend service is built in Python 3.11+.

### Installation
Clone the repository and set up a `.venv` virtual environment:

```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration
Copy `.env.example` to `.env` and fill in your keys:
- `PARALLEL_API_KEY`: Your Parallel API web key.
- `WATCHMODE_API_KEY`: Watchmode developer key (for streaming checks).
- `TMDB_API_KEY`: TMDB developer key (as fallback).

Never commit `.env` or expose keys in source code.

### Verification & Testing
Run the environment verification tool and tests:

```powershell
# Verify imports and keys
.venv\Scripts\python.exe src/verify_env.py

# Run the regression suite (external integrations are isolated by default)
.venv\Scripts\python.exe -m pytest
```

Voice asks “Shall I search with these choices?” and accepts a complete affirmative
reply only for the current saved choices. It then stops microphone capture and
playback and moves to visual search. The persistent button remains available as
“Review choices” or “Find my results”; recommendations are never narrated.

New chats use any release year. Search offers disclose included access only
(no extra-cost rentals) unless the viewer explicitly allows rentals/purchases.
Voice and text confirmation use the same saved choices. Failed discovery or
availability checks are distinguished from checked non-matches, with retry or
single-constraint adjustments that retain other preferences. See the
[unrestricted voice acceptance notes](docs/UNRESTRICTED_VOICE_20260908.md).

The preset test-persona UI and `/api/personas` endpoint have been removed. Test
fixtures remain under `tests/`; they are excluded from deployment. See
[review flow and cleanup notes](docs/REVIEW_FLOW_20260908.md) for the API protocol,
validation and remaining manual checks.

### Running TONI

```powershell
# Option A: Start the FastAPI HTTP Server & Interactive Web Demo UI (http://localhost:8000)
.venv\Scripts\python.exe -m uvicorn src.api:app --reload --port 8000

# Option B: Run the Interactive Terminal CLI Simulation
.venv\Scripts\python.exe src/main.py
```

---

## Sources of Truth

1. **`docs/TONI Task 04 - Hackathon MVP Decision Record & Product Contract.md`**  
   Authoritative for the hackathon MVP journey, intake, output depth, refinement, and progressive memory.
2. **`docs/TONI Build Handover - MVP Implementation Contract.md`**  
   Detailed builder requirements, non-negotiables, build dependency order, and acceptance criteria.
3. **`DECISIONS.md`**  
   The running record of confirmed technical decisions.

---

## Data Source Attribution

TONI utilizes third-party APIs to deliver live metadata, search indexes, and streaming availability:
- **Streaming Availability:** Powered by [Watchmode](https://www.watchmode.com) API.
- **Watch Providers:** Watch provider details are provided by [JustWatch](https://www.justwatch.com) (integrated via [The Movie Database (TMDB)](https://www.themoviedb.org)). This product uses the TMDB API but is not endorsed or certified by TMDB.
- **Search & Extracts:** Powered by [Parallel Web Systems](https://parallel.life) Search & Extract APIs.

---

## Legal & Copyright

TONI has passed an initial naming scan without an obvious film or television category conflict. It has not been formally legally cleared.

© 2026 KINTAL Ltd.

TONI's original project code is licensed under the **GNU Affero General Public
License, version 3 only** (`AGPL-3.0-only`). See [LICENSE](LICENSE) for the full
terms. You may redistribute and modify it under those terms. It is provided
without warranty, including the implied warranties of merchantability and
fitness for a particular purpose.

Third-party dependencies, fonts and other third-party materials retain their
own licences and notices. In particular, Newsreader retains its SIL Open Font
License in `licenses/Newsreader-OFL.txt` and `static/licenses/Newsreader-OFL.txt`.

The project licence changed from MIT to AGPL-3.0-only on 7 September 2026.
Earlier development notes describing MIT refer to the earlier repository state.
