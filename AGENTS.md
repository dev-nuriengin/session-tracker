# AGENTS.md — read this first

You are an AI agent working on **Session Tracker**. This orients you fast.
(Codex, Cursor, and most agents read `AGENTS.md` automatically; Claude Code reads it too.)

## What this project is (1 minute)

Session Tracker is a **brain / memory** for everything the user works on (a company's
clients + personal projects). It **holds structure + progress + decisions** and lets AI
agents plug in — primarily via **MCP** — so they always have continuity. **It is NOT an
agent**: it does not do work and does **not** gate or approve anyone's coding. It
*remembers* work.

**All its DATA is local and private — never public** (a future optional cloud store is
opt-in only).

Full design → [`README.md`](./README.md). Current build status → [`_tracker.md`](./_tracker.md)
— a **temporary build scaffold** that gets retired once the product tracks itself.

## The mental model (don't get this wrong)

- **Brain/memory, not an agent.** It stores and serves; it does not act, plan, or approve.
- **Structure (the user configures it interactively):** **Project → sub-folders → items.**
  Terminology is **domain-agnostic** — an "item" is a *ticket* (IT), a *bill* (accounting),
  a *deliverable* (design). Never bake domain jargon into schema/API/UI.
- **One core, three doors.** Core = **local Postgres (+pgvector)**, single source of truth.
  Doors = **MCP** (agents, primary — the heart), **CLI** (`sess`), **web** (local view).
- **Continuity is the point:** a new session/CLI **pulls the item's history first** —
  the agent never says *"I don't know this item's history."*
- **Progressive disclosure (token discipline):** always return/read a **summary first**
  (a limited overview/table); drill deeper only on demand. **NEVER dump everything at once**
  — it burns tokens. `overview()` = cheap first look; `get_history()` = heavy drill-down.
- **Captures progress behind the scenes** and stores **concrete memory** (decisions, repo
  links, meeting/decision notes).
- **Data is LOCAL & PRIVATE** — never committed, pushed, or cloud-synced (cloud = future,
  opt-in). App *code* is public on GitHub; app *data* stays on the machine.
- The **LangGraph brain** (`backend/app/graph.py`) is an *optional helper*, not the product.
  It (and `/agent`, `/chat`, `sess eval`) is the only part that calls Claude — built **lazily**,
  so the core (MCP/CLI/web/DB/search) runs with **no API key or credits**. The brain is for
  when a human uses CLI/web **without** an agent (on-demand summaries) or for background jobs.

## How to work in THIS repo (our build workflow — not product features)

1. **At session start:** read `_tracker.md` (temporary). The first `[ ]` item is NEXT.
2. **Plan before code** — propose the plan, get approval before editing. *(This is how we
   build the repo. It is NOT a tracker feature — the tracker is memory, not a code-gate.)*
3. **At session end:** tick `_tracker.md` and update the "Resume here" block.
4. **Git:** never commit/push without an explicit "yes" (account `dev-nuriengin`). Never
   commit tracker DATA — only app code.

## Where things are

- `backend/app/main.py` — FastAPI: `/chat`, `/agent`, `/graph`.
- `backend/app/db.py` · `models.py` · `repository.py` — the Postgres core (Phase 4).
- `backend/app/graph.py` — the LangGraph brain (optional helper).
- `backend/app/tools.py` — LangChain tools.
- `cli/` — the `sess` CLI · `frontend/` — Next.js web view · `docker-compose.yml` — Postgres+pgvector.

## Run

`docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload` ·
`cd frontend && npm run dev`. Env: `.env` (gitignored) → `ANTHROPIC_API_KEY`, `DATABASE_URL`.
