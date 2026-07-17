# Session Tracker

**A structured system-of-record for everything you're working on — built for AI agents to use.**

You (and many people) juggle several projects at once: a company's multiple clients
*plus* personal projects, all in progress simultaneously. Session Tracker is one place
that knows, per project, **what it is, where it stands, what the tracking items/steps
are, and what happened in each work session** — and exposes that to AI agents in a
**standard way** so they can read status and save progress *while they work*, with no
per-agent configuration.

It turns a manual way-of-working (a `_tracker.md` per project, read at the start of a
session and ticked at the end — see this repo's own [`_tracker.md`](./_tracker.md) as a
**living example**) into a real product.

## Core idea

> **The product is the tracker, not an agent.** We are **not** shipping a standalone
> assistant. We're shipping the structured system that *any* agent (Claude Code, Codex,
> Grok, …) plugs into to track sessions — over the CLI or the browser.

- **Primary user = AI agents.** As an agent works on a project, it reads the project's
  status from the tracker and writes session progress back, so it knows how to behave
  (resume here, what's next). The standard door for this is **MCP** — which makes **the
  MCP server the heart of the product.**
- Humans use it too, mainly via the **CLI**, sometimes the **web** view.

## Architecture — one core, three doors

```
                         ┌──────────────── doors ────────────────┐
   AI agents  ─────────▶ │  MCP server   (agents — primary)       │
   You (terminal) ─────▶ │  CLI  (sess)  (your main hand door)    │ ─────▶ ┌──────────┐
   You (browser)  ─────▶ │  Web          (read view)              │        │  CORE    │
                         └────────────────────────────────────────┘        │ Postgres │
                                                                            │ +pgvector│
   optional helper: LangGraph "brain" (summarize → plan → approve)  ──────▶ └──────────┘
```

- **Core / single source of truth: Postgres (+pgvector).** Holds `projects →
  tracking items/steps/status → session logs`. **All data lives here — no local
  `.md`/`.ai` files as the data model.** (pgvector powers semantic search over session
  logs later.)
- **MCP server** — the primary door; how agents consume the tracker in a standard way.
- **CLI (`sess`)** — the main human door: query projects/items, start/resume sessions,
  save steps.
- **Web** — a read view (status board, session history, agent traces).
- **LangGraph brain** — an *optional* helper on top of the core (summarize a session,
  propose a plan, pause for human approval). Useful, but not the product.

## How an agent is meant to use it (the flow)

1. **Start of session** → agent asks the tracker: *what projects exist, what's the
   status of the one I'm on, what's next?*
2. **During work** → agent saves steps / session progress back to the tracker.
3. **Before acting on a plan** → the tracker's **plan-before-code** gate: the agent
   proposes a plan and a human approves before it proceeds.
4. **End of session** → status is persisted; the next session (any agent) can resume.

## Not in scope (by design)

- **Auth / making it public** is a **deployment config**, not a product feature.
  Session Tracker is a **local tool** by default; auth only matters *if* you choose to
  expose it.

## Stack
- **Backend:** FastAPI (Python, uv)
- **Core store:** Postgres + pgvector
- **Agent door:** MCP server (FastMCP)
- **CLI:** Python · Typer (`sess`)
- **Web:** Next.js
- **Optional brain:** LangGraph + LangChain (provider-swappable — `init_chat_model`)
- **Model:** `claude-opus-4-8` (swappable to OpenAI/xAI via one line)
- **Observability (later):** Langfuse

## Local dev
1. Start the database: `docker compose up -d`
2. Backend: `cd backend && uv run uvicorn app.main:app --reload` → http://localhost:8000/health
3. Frontend: `cd frontend && npm run dev` → http://localhost:3000

## For AI agents / contributors

Read [`AGENTS.md`](./AGENTS.md) for how to work in this repo, and
[`_tracker.md`](./_tracker.md) for the current build status (read it at session start,
tick items at the end).
