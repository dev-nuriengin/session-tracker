# Session Tracker — build progress + living example

> This file is TWO things at once:
> 1. The **build log** for making Session Tracker (phases + checkboxes below).
> 2. A **living example of the product itself** — the exact pattern Session Tracker
>    formalizes: an agent reads status at session start, ticks items at session end.
>
> Rules: mark done with `[x]`, not-done with `[ ]`. The **first `[ ]` item is NEXT**.

## What we're building (locked design — 2026-07-17)

**Session Tracker = a structured system-of-record for everything you're working on**
(your company's 3 clients + your personal projects), that **AI agents use in a
standard way** to know where each project stands and to save session progress.

- **Primary user = AI agents (Option A).** Claude Code (and any MCP-capable agent)
  uses the tracker *while it works* — reads status, saves steps — with **no per-agent
  config**. That standard door is **MCP → MCP is the heart of the product.**
- **One core, three doors:**
  - **Core / single source of truth:** **Postgres (+pgvector)**. Holds projects →
    tracking items/steps/status → session logs. **No local .md/.ai files as data.**
  - **MCP server** → agents (primary consumer).
  - **CLI (`sess`)** → your main hand-driven door.
  - **Web** → a read view.
- **The LangGraph brain** (summarize → plan → approve) = an **optional helper on top**,
  not the product.
- **Deployment (auth, local→public) is NOT a product feature** — it's optional config
  if you ever expose it. Session Tracker is a **local tool** by default.

## ▸ Resume here (next session)

**Status:** 10 / 30 done. Design pivoted to **MCP-primary + Postgres core** (above).
Phases reordered: **Core DB → MCP → CLI → Web** now lead.

**NEXT:** Phase 4 — build the **core data model in Postgres**: tables for projects,
tracking items/steps, sessions + session logs; a thin repository layer; replace the
stub `TRACKERS` dict with real DB reads/writes. This unblocks MCP (Phase 5, the heart).

**Also open (Phase 3):** real approve gate (`interrupt`); persistence swap
MemorySaver → PostgresSaver once the DB exists. **Dropped:** "auto-save to local .md"
(wrong — data lives in the tracker's DB, not local files).

**Code so far (learning + helper brain, all under `backend/app/`):**
- `main.py` — FastAPI. `/chat` (SSE stream), `/agent` (hand-built tool loop — Phase 1),
  `/graph` (LangGraph pipeline — Phase 2).
- `graph.py` — `StateGraph`: load → summarize → plan → approve (+ conditional edge),
  Pydantic `Summary`/`Plan`, provider in one `init_chat_model` line, `MemorySaver` + `thread_id`.
- `tools.py` — LangChain `@tool` `list_projects` / `read_tracker`.
- `data.py` — **stub** `PROJECTS`/`TRACKERS` → to be replaced by Postgres in Phase 4.

**Run:** `docker compose up -d` · `cd backend && uv run uvicorn app.main:app --reload`
· `cd frontend && npm run dev`. **Env:** `.env` (gitignored) → `ANTHROPIC_API_KEY`;
model `claude-opus-4-8`.

**Git:** Phase 0–2 pushed (`dev-nuriengin`). Phase 3 checkpointing + this pivot uncommitted.

**Known follow-up:** LangGraph warns Pydantic `Summary`/`Plan` are "unregistered msgpack
types" — fix by storing `.model_dump()` dicts (do it when wiring DB persistence).

---

## Phase 0 — Scaffold & method
- [x] .ai/ workspace + _tracker.md spec (index-vs-detail, plan-before-code)
- [x] docker-compose: Postgres+pgvector · FastAPI · Next.js skeleton
- [x] sess CLI skeleton (Python · Typer): picker · start · ask stubs

## Phase 1 — First agent, from scratch (learning: how tool-calling works)
- [x] One end-to-end Claude call from FastAPI, streamed over SSE
- [x] Build the agent loop by hand: tool-calling while-loop (no framework)
- [x] First tools: list_projects · read_tracker

## Phase 2 — LangGraph brain (the optional helper)
- [x] Model the state graph: load → summarize → plan → approve
- [x] Structured outputs (Pydantic) for summary + plan
- [x] Wire tools as graph nodes & edges

## Phase 3 — State, memory, human-in-the-loop
- [x] Checkpointing: session resumes in-process (MemorySaver)
- [ ] Real human-in-the-loop approve gate (interrupt → Command resume)
- [ ] Persist sessions to Postgres (MemorySaver → PostgresSaver) [after Phase 4]

## Phase 4 — Core data model (Postgres) ← THE STORE, next up
- [ ] Schema: projects · tracking_items/steps · sessions · session_logs
- [ ] Repository/data layer over the schema (async SQLAlchemy or similar)
- [ ] Replace stub TRACKERS/PROJECTS with real DB reads/writes

## Phase 5 — MCP server ← THE HEART (agents' door)
- [ ] Build the MCP server (FastMCP) over the core: list_projects · get_status · save_step · whats_next
- [ ] Claude Code discovers & calls the tools (no per-agent config)
- [ ] Local + remote server config

## Phase 6 — CLI (`sess`) — your main door
- [ ] sess: list/query projects + tracking items from the core
- [ ] sess: start/resume a session; save steps
- [ ] Retire the ad-hoc aliases

## Phase 7 — Web — a read view
- [ ] Next.js status board: projects · items · session history
- [ ] Agent traces view

## Phase 8 — RAG over session logs
- [ ] pgvector embeddings + chunking of logs
- [ ] Retrieval: ask across all trackers
- [ ] Hybrid search + rerank

## Phase 9 — Eval, safety, observability
- [ ] Langfuse tracing end-to-end
- [ ] LLM-as-judge eval on summaries
- [ ] Guardrails + PII redaction

## Phase 10 — Ship
- [ ] Dockerize + deploy (auth/config only if going public)
