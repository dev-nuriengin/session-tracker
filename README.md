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

> **The product is the tracker, not an agent.** It's a **brain / memory** — it holds
> data (which projects exist, where each stands, what the items are) and remembers the
> work. It does **not** do the work itself, and it does **not** gate or approve what an
> agent does. We're shipping the structured memory that *any* agent (Claude Code, Codex,
> Grok, …) plugs into — over the CLI or the browser.

- **Primary user = AI agents.** As an agent works, the tracker (behind the scenes)
  pulls its progress — *"what did you do, where are you?"* — and saves the work and
  item updates into itself. The standard door for this is **MCP → the MCP server is
  the heart of the product.**
- **It holds concrete memory:** decisions, repo links (GitLab/GitHub), meeting/decision
  notes — durable facts that survive across sessions.
- **It guarantees continuity:** when a new CLI/session opens, the agent first pulls the
  project's history from the tracker. It never starts blind (*"I don't know this item's
  history"*).
- Humans use it too, mainly via the **CLI**, sometimes the **web** view.

## Structure (you set it up interactively)

You build the map of your work in the tracker (via CLI/web); it's stored in the DB:

- **Project** — a high-level thing you work on (a client, or a personal project)
- **Sub-folders** — grouping inside a project
- **Items** — the actual work units. **Domain-agnostic:** an "item" is a *ticket* in IT,
  a *bill* in accounting, a *deliverable* in design — those are just labels.

→ **Project → sub-folders → items.** (More "way-of-working" config comes later.)

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
  propose next steps). Useful, but not the product.

## How an agent uses it (the flow)

1. **New session / CLI opens** → the agent **first pulls a SUMMARY** of the item (status,
   a few open items, counts) — a cheap overview, **never a full dump**. It never starts
   blind (*"I don't know this item's history"*).
2. **Drill down only as needed** → if the summary isn't enough, the agent asks for more
   (full memory, all items, session history). **Progressive disclosure**, not one big load.
3. **While working** → the tracker **captures progress behind the scenes** — it pulls
   *"what's your progress?"* and saves the work + item updates into itself.
4. **Durable memory** → decisions, repo links, and meeting/decision notes persist across
   sessions and agents.
5. **Continuity** → the next session (any agent, any CLI) resumes — again from the summary
   first, drilling deeper only when required.

> **Token discipline (core principle):** the tracker **never dumps everything at once** —
> that burns tokens. It always returns a **summarized entry point first** (like a table),
> and the agent goes **deeper on demand.**

## Privacy — local-first (hard default)

- **All data is LOCAL and PRIVATE by default** — projects, items, decisions, and the
  **conversations / progress you had with an agent** live only in your **local Postgres**.
  Not committed, not pushed, not synced.
- The **web view is local** (localhost); the **MCP server runs locally**.
- **Later (not now): an optional cloud store**, so a hosted UI can retrieve your data —
  but **only if you explicitly enable it in config**. Off by default; opt-in only.
- The app *code* (this repo) is public on GitHub; the app *data* stays private.
- Auth / going public is **deployment config, not a product feature.**

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
