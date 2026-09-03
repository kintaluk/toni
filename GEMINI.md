# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

## Project

Agentic Cinema: a hackathon project (Parallel track, deadline 9 September 2026, 2pm PDT) testing and building TONI (Tonight’s Own Next Indulgence), an agentic viewing guide that delivers personalized movie shortlists using Parallel's live search and extract coupled with Gemini-based reasoning and streaming availability verification.

The repo is organized brief-by-brief in root-level files named `agentic-cinema-brief-N.md`. Each brief is the authoritative, step-by-step task spec for that phase of work. **Task 04 / Build Handover** and its corresponding documentation in `agentic-cinema-brief-2.md` represent the current product source of truth, superseding previous experimental briefs.

## Rules that outlive any single brief

1. The six Film Profile dimensions are a fixed contract: Story and writing, Pacing and structure, Performances, Tone and emotional character, Craft and execution, Accessibility and demandingness. Do not rename them, change the count, or let a model invent a seventh dimension without an explicit brief update authorizing it.
   - Note: The old 7-dimension rubric has been superseded. "Rewatch value" is removed, and "Critical consensus vs divergence" has moved to Evidence State.
2. Rubric/evidence rationale text must paraphrase sourced review content, never quote it at length. This is a copyright constraint from the concept brief, not a style preference.
3. The GitHub repo stays private throughout. The decision to make it public happens explicitly, close to submission; do not make it public by default.
4. Secrets (`PARALLEL_API_KEY`, Google Cloud credentials) live only in a local `.env`, which is gitignored. Never commit `.env` or print a full secret value; verification scripts should only ever echo a short prefix.
5. Keep the standard push-to-main deny rule active. This repo does not touch Supabase, so no Supabase-specific permission rules are needed.
6. New-build work requires plan mode: write and get the plan approved before writing code, per each brief's own instruction.
7. Do not push or commit to GitHub without the session runner's explicit go-ahead, and never treat a push itself as proof that a brief step has been reviewed. Pushing to enable a review is a legitimate reason to push before sign-off, but the sign-off is a separate, later event that must still be confirmed explicitly, not inferred from the repo being up to date.
8. Parallel's Search API must be actively called at runtime by the deployed/submitted project as part of a real user session, not only by a one-off dev-time script whose output then sits in a cache. This is a hackathon eligibility requirement for the Parallel track. Caching is permitted only as a performance optimization layered on top of a live runtime call path. All codebase work under Brief 2 and beyond must respect this live-calling requirement.

## Stack

Python 3.11+ (3.13.3 is the version available in this environment), run inside a `.venv` virtual environment. Core dependencies:

- `google-cloud-aiplatform[agent_engines,adk]>=1.101.0`, for Vertex AI Agent Engine and Google's Agent Development Kit
- `parallel-web`, the Parallel Python SDK, for `client.search()` and the Extract API

If these two packages hit a dependency conflict, stop and report the exact conflicting version constraints; do not silently downgrade either one.

## Commands

A `.venv` virtual environment exists at the repo root. Core commands for testing and running the application:

```powershell
# Install dependencies
.venv/Scripts/python.exe -m pip install -r requirements.txt

# Verify imports and key configurations (runs locally with no leakage)
.venv/Scripts/python.exe src/verify_env.py

# Run the test suite (36 unit and integration tests)
.venv/Scripts/python.exe -m pytest

# Run Option A: Start the FastAPI HTTP Server & Interactive Web Demo UI (port 8000)
.venv/Scripts/python.exe -m uvicorn src.api:app --reload --port 8000

# Run Option B: Run the Interactive Terminal CLI Simulation
.venv/Scripts/python.exe src/main.py
```
