# Session Tracker — build progress (TEMPORARY scaffold)

> ⚠️ **This file is a temporary bootstrap.** It's the manual build log used *while*
> building Session Tracker. Once the product works, it **tracks itself** (dogfood) and
> this file is retired — the build status moves into the tracker's own DB.
>
> While it exists it doubles as a **living example** of the tracking pattern: read at
> session start, tick items at the end.
>
> Rules: `[x]` done, `[ ]` not. The **first `[ ]` item is NEXT.**

## What we're building (locked idea — 2026-07-17)

**Session Tracker = a local, private brain / memory for all your work.** It holds the
structure and progress of everything you work on (a company's clients + personal
projects); AI agents plug into it — primarily via **MCP** — so they always have
continuity. **It is NOT an agent:** it doesn't do work and doesn't gate/approve coding.
It *remembers* work.

- **Structure (user sets up interactively):** **Project → sub-folders → items.**
- **Behavior:** captures progress behind the scenes (pulls *"what's your progress?"* and
  saves it) · holds **concrete memory** (decisions, repo links, meeting/decision notes) ·
  guarantees **continuity** (a new session/CLI pulls the item's history first).
- **One core, three doors:** core = **local Postgres (+pgvector)** (single source of
  truth); doors = **MCP** (agents — the heart) · **CLI** (`sess`) · **web** (local view).
- **Privacy:** all DATA is **local & private, never public.** Optional cloud store later,
  **opt-in only** (for a hosted UI). App *code* is public on GitHub; app *data* is not.
- The **LangGraph brain** (summarize/plan) is an **optional helper**, not the product.

## ▸ Resume here (next session)

**Status:** 13 / 28 done. Idea locked (above). **Phase 4 (Postgres core) complete.**

**NEXT:** Phase 5 — the **MCP server** (the heart). Build a FastMCP server over the
repository so any agent gets: `list_projects` · `get_history` (pull-history-first) ·
`save_progress` · `whats_next`. Then wire Claude Code to discover it (local config).
The continuity payload already exists as `repository.get_history(slug)`.

**Core (Phase 4) in place:** `db.py` (sync SQLAlchemy + `DATABASE_URL`), `models.py`
(Project · Folder[nestable] · Item · Session · SessionLog · Memory), `repository.py`
(projects/folders/items/memory/session-logs + `get_history` continuity payload + seed).
`tools.py` + `/agent` + `/graph` now read the **real DB**. New endpoints: `GET /projects`,
`GET /projects/{slug}` (continuity payload). DB tables auto-created + seeded on startup
(FastAPI lifespan). `data.py` is now seed-only.

**Run:** `docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload`.
**Env:** `.env` (gitignored) → `ANTHROPIC_API_KEY`, `DATABASE_URL`. Model `claude-opus-4-8`.

**Git:** Phase 0–3 + design pivot pushed (`dev-nuriengin`). Phase 4 core code uncommitted.

---

## Phase 0 — Scaffold & method
- [x] docker-compose: Postgres+pgvector · FastAPI · Next.js skeleton
- [x] sess CLI skeleton (Python · Typer): picker · start · ask stubs
- [x] Repo bootstrap + this build scaffold

## Phase 1 — First agent, from scratch (learning: how tool-calling works)
- [x] One end-to-end Claude call from FastAPI, streamed over SSE
- [x] Build the agent loop by hand: tool-calling while-loop (no framework)
- [x] First tools: list_projects · read_tracker

## Phase 2 — LangGraph brain (optional helper)
- [x] Model the state graph: load → summarize → plan → approve
- [x] Structured outputs (Pydantic) for summary + plan
- [x] Wire tools as graph nodes & edges

## Phase 3 — Brain state (optional helper)
- [x] Checkpointing: session resumes in-process (MemorySaver)
> Dropped (not tracker features): "approve-before-code gate" — the tracker does NOT gate
> coding; "auto-save at context budget" — replaced by real progress capture into the DB.

## Phase 4 — Core data model (Postgres) ← THE STORE ✅
- [x] DB engine/session (db.py) + repository layer + schema v1 (projects · items · sessions · session_logs), seeded
- [x] Final schema shape: **folders** (nestable; project → folders → items) + **memory** table (decisions · links · notes · transcripts)
- [x] Wire real DB into tools/graph/endpoints; stub `data.py` demoted to seed-only

## Phase 5 — MCP server ← THE HEART (agents' door)
- [ ] FastMCP server over the core: list_projects · get_item/history · save_progress · whats_next
- [ ] Continuity: on a new session, pull the item's history/decisions FIRST; capture progress behind the scenes
- [ ] Claude Code (and any agent) discovers & uses it — local config, no per-agent setup

## Phase 6 — CLI (`sess`) — your main door
- [ ] Interactively add/edit projects · folders · items (build the map)
- [ ] Query status/history; start/resume a session; save steps
- [ ] Retire the ad-hoc aliases

## Phase 7 — Web — a local read view
- [ ] Next.js status board: projects · folders · items · session history
- [ ] (later, opt-in) optional cloud store so a hosted UI can retrieve data

## Phase 8 — RAG over session logs
- [ ] pgvector embeddings + chunking of logs
- [ ] Retrieval: ask across all projects/items
- [ ] Hybrid search + rerank

## Phase 9 — Eval, safety, observability
- [ ] Langfuse tracing end-to-end
- [ ] LLM-as-judge eval on summaries
- [ ] Guardrails + PII redaction

## Phase 10 — Ship
- [ ] Dockerize for local run; optional cloud/UI + auth only if the user enables it
