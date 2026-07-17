# BUILD_NOTES.md — scratch notes for building Session Tracker

> ⚠️ **TEMPORARY.** Working notes + decisions for us (and any agent) *while building*.
> **Delete once the product is done.** Product-facing truth lives in `README.md`;
> current build status in `_tracker.md`.

## The locked idea (short)

Session Tracker = a **local, private brain / memory** for all your work. Agents plug in
via **MCP** for continuity. It is **NOT an agent** — it doesn't do work or gate coding.
(Full design: `README.md`.)

## How to build this (intent & guidance)

- **Builder:** a **senior software engineer learning agentic AI in practice.** Session
  Tracker is the **first product** of that journey.
- **Build future-proof and best-practice** — clean architecture, clear seams, tests where
  they matter, sensible abstractions. No throwaway hacks in the product path.
- **Maximize interview showcase value.** Deliberately include the "good things" a senior
  Applied-AI role looks for: MCP server, agentic patterns (LangGraph), structured outputs,
  RAG (pgvector), evals + LLM-as-judge, observability (Langfuse), a provider-agnostic LLM
  layer, a typed data model, a clean CLI + web. Each phase should be something you can talk
  through in an interview.
- **Doc layout:** `README.md` = project info (what we build) → points to `AGENTS.md` for
  *how agents use it*; `_tracker.md` = temporary build status; `BUILD_NOTES.md` (this file)
  = scratch decisions/context, deleted when done.

## Key decisions & why

- **Option A — MCP-primary.** External agents (Claude Code, Codex, Grok) are the primary
  users; **MCP is the heart.** Our LangGraph brain is an *optional helper*, not the product.
- **Postgres = single source of truth.** No local `.md`/`.ai` files as the data model.
  The stub `backend/app/data.py` `TRACKERS` dict is a temporary seed — retire it in Phase 4.
- **Local-first & private.** All DATA stays on the machine. Optional cloud store **later,
  opt-in only** (to power a hosted UI). App *code* is public on GitHub; app *data* is not.
- **LangChain for the LLM layer** (`init_chat_model`) → provider swap = one line
  (`anthropic:` → `openai:`/`xai:`). Model: `claude-opus-4-8`.
- **Sync SQLAlchemy** (not async) to match the sync codebase (def endpoints, sync graph).
- **Generic terminology (IMPORTANT).** The product is **domain-agnostic**. The work unit
  is a generic **"item"** — a "ticket" (IT), a "bill" (accounting), a deliverable (design)
  are just domain labels. **Never bake IT jargon into schema/API/UI.** Hierarchy:
  **Project → sub-folders → items.**
- **Progressive disclosure / token discipline.** Never dump all data to the agent at once
  (it burns tokens). Default read = a compact **summary** (status, counts, a few titles);
  deeper detail (full memory, all items, history) is fetched only on demand. `overview()`
  = the cheap first look; `get_history()` = the heavy drill-down.
- **`_tracker.md` is a temporary scaffold** — the product will track itself (dogfood),
  then it's retired.

## Dropped / corrected (don't reintroduce)

- ❌ "plan-before-code approve gate" as a PRODUCT feature — the tracker does **not** gate
  coding. (plan-before-code is only *our build workflow*.)
- ❌ "auto-save at context budget" — replaced by real progress capture into the DB.

## Open questions / later

- Exact "way-of-working" configuration the user can set (deferred — decide later).
- Optional cloud store + hosted UI (opt-in) — later.
- `decisions/memory` table shape (decisions · repo links · meeting/decision notes) — Phase 4.
- How the MCP server enforces "pull history first" continuity — Phase 5.

## Known follow-ups (tech debt)

- LangGraph warns Pydantic `Summary`/`Plan` are "unregistered msgpack types" — store
  `.model_dump()` dicts when wiring DB persistence.
- Security scan (local dev, non-blocking): `/agent`, `/chat`, `/graph` have no auth — fine
  locally; auth only matters if ever exposed (deployment config, not a feature).
