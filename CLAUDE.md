# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agentic Cinema: a hackathon project (Parallel track, deadline 9 September 2026, 2pm PDT) testing whether Parallel's search and extract, fed into a Gemini rubric-scoring prompt, produce grounded, non-invented quality scores for a film, before any taste intake, case matching or fan-facing UI gets built on top.

The repo is at an early scaffold stage. Work is specified brief by brief in root-level files named `agentic-cinema-brief-N.md`. Each brief is the authoritative, step-by-step task spec for that phase of work; read the current brief before starting anything, since later briefs will change scope, add files and add constraints that this document does not attempt to duplicate.

## Rules that outlive any single brief

1. The seven rubric dimensions are a fixed contract: Story and plot coherence, Pacing, Performance quality, Tone and mood match, Craft (direction, cinematography, score), Rewatch value, Critical consensus vs divergence. Do not rename them, change the count, or let a model invent an eighth dimension, without an explicit brief update authorising it.
2. Rubric rationale text must paraphrase sourced review content, never quote it at length. This is a copyright constraint from the concept brief, not a style preference.
3. The GitHub repo stays private throughout. The decision to make it public happens explicitly, close to submission; do not make it public by default.
4. Secrets (`PARALLEL_API_KEY`, Google Cloud credentials) live only in a local `.env`, which is gitignored. Never commit `.env` or print a full secret value; verification scripts should only ever echo a short prefix.
5. Keep the standard push-to-main deny rule active. This repo does not touch Supabase, so no Supabase-specific permission rules are needed.
6. New-build work requires plan mode: write and get the plan approved before writing code, per each brief's own instruction.
7. Do not push or commit to GitHub until the person running the session says the relevant brief step has been reviewed; work stays local until then.
8. Parallel's Search API must be actively called at runtime by the deployed/submitted project, not only by a one-off dev-time script whose output then sits in a cache. This is a hackathon eligibility requirement for the Parallel track, not a style preference: referencing Parallel in code that the submitted product never actually executes does not count. As of Brief 1, `src/search_reviews.py` and `src/extract_reviews.py` are dev-time spike scripts (their output, `logs/`, is gitignored), and `src/score_rubric.py` makes no Parallel calls of its own, it only reads the cached extract log. Brief 2 onward must not simply widen this same batch-backfill pattern to more films; the eventual agent (Brief 4) needs to call `client.search()`/`client.extract()` live as part of an actual user session, with caching layered on top as an optimisation, not as the only mechanism. Treat this as a required input to Brief 2's plan, not an optional nice-to-have.

## Stack

Python 3.11+ (3.13.3 is the version available in this environment), run inside a `.venv` virtual environment. Core dependencies:

- `google-cloud-aiplatform[agent_engines,adk]>=1.101.0`, for Vertex AI Agent Engine and Google's Agent Development Kit
- `parallel-web`, the Parallel Python SDK, for `client.search()` and the Extract API

If these two packages hit a dependency conflict, stop and report the exact conflicting version constraints; do not silently downgrade either one.

## Commands

No lint or test tooling exists yet; none is specified by the briefs so far. A `.venv` exists at the repo root (Windows, not activated by default in this environment; call the interpreter directly rather than assuming `source .venv/bin/activate`):

```
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe src/verify_env.py
```

Update this section as soon as real lint, test or run commands are introduced by a later brief; do not invent commands that are not actually wired up.
