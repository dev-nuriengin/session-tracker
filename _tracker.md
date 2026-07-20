# Trackden — build progress (TEMPORARY scaffold)

> ⚠️ **This file is a temporary bootstrap.** It's the manual build log used *while*
> building Trackden. Once the product works, it **tracks itself** (dogfood) and
> this file is retired — the build status moves into the tracker's own DB.
>
> While it exists it doubles as a **living example** of the tracking pattern: read at
> session start, tick items at the end.
>
> Rules: `[x]` done, `[ ]` not. The **first `[ ]` item is NEXT.**

## What we're building (locked idea — 2026-07-17)

**Trackden = a local, private brain / memory for all your work.** It holds the
structure and progress of everything you work on (a company's clients + personal
projects); AI agents plug into it — primarily via **MCP** — so they always have
continuity. **It is NOT an agent:** it doesn't do work and doesn't gate/approve coding.
It *remembers* work.

- **Structure (user sets up interactively):** **Project → sub-folders → items.**
- **Behavior:** captures progress behind the scenes (pulls *"what's your progress?"* and
  saves it) · holds **concrete memory** (decisions, repo links, meeting/decision notes) ·
  guarantees **continuity** (a new session/CLI pulls the item's history first).
- **One core, three doors:** core = **local Postgres (+pgvector)** (single source of
  truth); doors = **MCP** (agents — the heart) · **CLI** (`trackden`) · **web** (local view).
- **Privacy:** all DATA is **local & private, never public.** Optional cloud store later,
  **opt-in only** (for a hosted UI). App *code* is public on GitHub; app *data* is not.
- The **LangGraph brain** (summarize/plan) is an **optional helper**, not the product.

## ▸ Resume here (next session)

**Status:** 26 / 28 — **ALL CORE PHASES DONE (0–10).** The 2 open items are
explicitly-deferred future refinements: Phase 7 optional cloud store, Phase 8 hybrid+rerank.

**Build complete.** The whole product exists: local Postgres core → three doors (MCP · CLI
· web), summary-first, private, provider-swappable, with RAG + eval + opt-in observability,
dockerized for local run.

**Cost/keys:** the core (MCP/CLI/web/DB/local search) makes **zero LLM calls → runs with no
API key or credits** (LLM clients are lazy). The **brain** (`/graph`, `/agent`, `/chat`,
`trackden eval`) is **optional** — reads the key only when actually used (value: human at CLI/web
without an agent, or background jobs). Security follow-up done: eval redacts at its LLM
boundary; `redact()` is best-effort defense-in-depth.

**NEXT (optional / future):** hybrid search + rerank (Phase 8) · folder grouping in the web
UI · optional cloud store + hosted UI (opt-in) · remove the superseded `cli/` skeleton ·
start dogfooding (retire `_tracker.md` into the product itself).

**Ship (Phase 10) in place:** `backend/Dockerfile` (uv) + `docker compose up --build`
(db healthcheck → backend, `ANTHROPIC_API_KEY` from `.env`) + `.dockerignore` + README run
docs. Cloud/UI + auth are opt-in only.

**Git:** all phases (0–10) committed & pushed to `dev-nuriengin/session-tracker`.

**MCP (Phase 5) in place:** `backend/app/mcp_server.py` — FastMCP `trackden`
server exposing `list_projects` · `get_history` · `whats_next` · `save_progress` ·
`add_memory` over the repository. Discovery: `.mcp.json` at repo root (stdio). **To use
it in Claude Code: approve/restart so it loads the server.** Deps: `mcp`.

**Core (Phase 4):** `db.py`, `models.py` (Project · Folder[nestable] · Item · Session ·
SessionLog · Memory), `repository.py` (+ `get_history` continuity). `tools.py` + `/agent`
+ `/graph` read the real DB; `GET /projects`, `GET /projects/{slug}`. `data.py` seed-only.

**Run:** `docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload`.
**Env:** `.env` (gitignored) → `ANTHROPIC_API_KEY`, `DATABASE_URL`. Model `claude-opus-4-8`.

**Git:** Phase 0–3 + design pivot pushed (`dev-nuriengin`). Phase 4 core code uncommitted.

---

## Phase 0 — Scaffold & method
- [x] docker-compose: Postgres+pgvector · FastAPI · Next.js skeleton
- [x] trackden CLI skeleton (Python · Typer): picker · start · ask stubs
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

## Phase 5 — MCP server ← THE HEART (agents' door) ✅
- [x] FastMCP server over the core: list_projects · get_history · whats_next · save_progress · add_memory
- [x] Continuity: get_history = pull-history-first payload; save_progress/add_memory = capture behind the scenes (tool descriptions steer the agent to call get_history first)
- [x] Discovery via `.mcp.json` (stdio: `uv --directory backend run python -m app.mcp_server`) — user restarts/approves Claude Code to activate

## Phase 6 — CLI (`trackden`) — your main door ✅
- [x] Interactively add projects · folders · items (add-project / add-folder / add-item) — builds the map in the DB
- [x] Query status/history (list · status · show) + save progress (log · remember)
- [x] `trackden` console script on the shared repository (`uv run trackden …`); old `cli/` skeleton superseded (remove later)

## Phase 7 — Web — a local read view ✅ (core)
- [x] Next.js status board: projects sidebar → compact overview → "Show full" (items · memory · logs). Reads `GET /projects` + `/projects/{slug}` (+ `/history`); backend CORS added. Summary-first.
- [ ] (later, opt-in) optional cloud store so a hosted UI can retrieve data

## Phase 8 — RAG over session logs ✅ (core)
- [x] LOCAL embeddings (fastembed, bge-small) + pgvector column; embed on write (chunking deferred — log entries are short)
- [x] Retrieval: ask across ALL projects — `repository.search_logs`; MCP `search`, `trackden ask`, `GET /search`
- [ ] Hybrid search + rerank (future refinement; pure vector for now)

## Phase 9 — Eval, safety, observability ✅
- [x] Langfuse tracing — `observability.callbacks()`, OPT-IN via env (off by default = local-first); wired into the graph
- [x] LLM-as-judge eval on summaries — `eval.py` (faithfulness + conciseness), `trackden eval [project]`
- [x] Guardrails: PII/secret redaction at the LLM boundary (`guardrails.redact`), not on local storage

## Phase 10 — Ship ✅
- [x] Dockerize for local run: `backend/Dockerfile` (uv) + `docker compose up --build` (db healthcheck → backend); `.dockerignore`; README run docs. Cloud/UI + auth remain opt-in only.
