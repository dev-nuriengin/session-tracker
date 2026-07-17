# AGENTS.md — read this first

You are an AI agent working on **Session Tracker**. This file gets you oriented fast.
(Codex, Cursor, and most agents read `AGENTS.md` automatically; Claude Code reads this
too. It's the cross-agent onboarding doc.)

## What this project is (1 minute)

Session Tracker is a **structured system-of-record** for everything the user is working
on (a company's multiple clients + personal projects), designed so **AI agents can read
project status and save session progress in a standard way — via MCP**. The product is
the tracker, **not** a standalone assistant.

**Read [`README.md`](./README.md) for the full design** (core idea, architecture, how an
agent uses it). Read [`_tracker.md`](./_tracker.md) for **current build status**.

## The mental model (don't get this wrong)

- **One core, three doors.** Core = **Postgres (+pgvector)**, the single source of truth
  (`projects → tracking items/steps → session logs`). Doors = **MCP** (agents, primary),
  **CLI** (`sess`), **Web** (read view).
- **MCP is the heart** — the whole point is agents use the tracker with no per-agent config.
- **Data lives in the DB, NOT in local `.md`/`.ai` files.** Don't invent local-file
  storage for tracker data.
- The **LangGraph brain** (`backend/app/graph.py`) is an *optional helper*, not the product.
- **Auth / going public = deployment config, not a feature.** It's a local tool by default.

## How to work here

1. **At session start:** read `_tracker.md`. The **first `[ ]` item is NEXT.**
2. **Plan before code.** For any non-trivial change, propose the plan and get approval
   *before* editing. (This is also a product feature — the `approve` gate.)
3. **At session end:** tick completed items in `_tracker.md` and update the "Resume here"
   block so the next agent can continue.
4. **Git:** never commit or push without the user's explicit "yes." Personal account
   `dev-nuriengin`.

## Where things are

- `backend/app/main.py` — FastAPI: `/chat`, `/agent` (hand-built loop), `/graph` (LangGraph).
- `backend/app/graph.py` — the LangGraph brain (helper).
- `backend/app/tools.py` — LangChain tools.
- `backend/app/data.py` — **stub** projects/status → being replaced by the Postgres core.
- `cli/` — the `sess` CLI (skeleton).
- `frontend/` — Next.js web view.
- `docker-compose.yml` — Postgres + pgvector.

## Run

`docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload` ·
`cd frontend && npm run dev`. Env: `.env` (gitignored) holds `ANTHROPIC_API_KEY`.
