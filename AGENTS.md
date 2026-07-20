# AGENTS.md — read this first

You are an AI agent working on **Trackden**. This orients you fast.
(Codex, Cursor, and most agents read `AGENTS.md` automatically; Claude Code reads it too.)

## What this project is (1 minute)

Trackden is a **brain / memory** for everything the user works on (a company's
clients + personal projects). It **holds structure + progress + decisions** and lets AI
agents plug in — primarily via **MCP** — so they always have continuity. **It is NOT an
agent**: it does not do work and does **not** gate or approve anyone's coding. It
*remembers* work.

**All its DATA is local and private — never public** (a future optional cloud store is
opt-in only).

Full design → [`README.md`](./README.md). Current build status → [`_tracker.md`](./_tracker.md)
— a **temporary build scaffold** that gets retired once the product tracks itself.

## The mental model (don't get this wrong)

- **LLM-agnostic (FIRST principle).** Works with ANY agent — no vendor privileged. **MCP is
  the one agnostic contract**; on-disk files use vendor-neutral names; per-vendor files
  (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`…) are thin shims that redirect to the MCP tools.
- **Brain/memory, not an agent.** It stores and serves; it does not act, plan, or approve.
- **Structure (the user configures it interactively):** **Project → sub-folders → items.**
  Terminology is **domain-agnostic** — an "item" is a *ticket* (IT), a *bill* (accounting),
  a *deliverable* (design). Never bake domain jargon into schema/API/UI.
- **Hybrid storage (LOCKED design; files part *planned*).** No-overlap rule:
  **DB** owns *state* (items, status, logs, embeddings); **per-project guidance files**
  (arch/way-of-work/decisions, vendor-neutral names) own *durable human knowledge*;
  **pgvector** is a derived search index over both. Full spec in `BUILD_NOTES.md` →
  "LOCKED DESIGN — Storage model". *(Today's code is DB-only; the files layer is planned.)*
- **One core, three doors.** Doors = **MCP** (agents, primary — the heart), **CLI**
  (`trackden`), **web** (local view).
- **Continuity is the point:** a new session/CLI **pulls the item's history first** —
  the agent never says *"I don't know this item's history."*
- **Progressive disclosure (token discipline):** always return/read a **summary first**
  (a limited overview/table); drill deeper only on demand. **NEVER dump everything at once**
  — it burns tokens. `overview()` = cheap first look; `get_history()` = heavy drill-down.
- **Captures progress behind the scenes** (→ DB logs) and stores **concrete memory**:
  repo links / metadata → DB; **decisions → guidance files** (`_decisions.md`, *planned*).
- **Data is LOCAL & PRIVATE by default.** *State* (DB) stays on the machine (optional
  cloud store = future, opt-in). *Guidance files* may be backed up to a **private** git
  repo at the user's choice (still private, never public). App *code* is public on GitHub.
- The **LangGraph brain** (`backend/app/graph.py`) is an *optional helper*, not the product.
  It (and `/agent`, `/chat`, `trackden eval`) is the only part that calls Claude — built **lazily**,
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
- `cli/` — the `trackden` CLI · `frontend/` — Next.js web view · `docker-compose.yml` — Postgres+pgvector.

## Run

`docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload` ·
`cd frontend && npm run dev`. Env: `.env` (gitignored) → `ANTHROPIC_API_KEY`, `DATABASE_URL`.
