# BUILD_NOTES.md — scratch notes for building Trackden

> ⚠️ **TEMPORARY.** Working notes + decisions for us (and any agent) *while building*.
> **Delete once the product is done.** Product-facing truth lives in `README.md`;
> current build status in `_tracker.md`.

## The locked idea (short)

Trackden = a **local, private brain / memory** for all your work. Agents plug in
via **MCP** for continuity. It is **NOT an agent** — it doesn't do work or gate coding.
(Full design: `README.md`.)

## FIRST principle — LLM-agnostic (non-negotiable)

The product works with **ANY** LLM agent — Claude, Codex, Grok, a terminal, an IDE.
**No vendor is privileged.** The agnostic contract is **MCP**: every agent speaks it
identically to read state and guidance. On-disk artifacts use **vendor-neutral names**
(never a Claude-only `CLAUDE.md` as the source); any per-vendor file (`CLAUDE.md`,
`AGENTS.md`, `.cursorrules`…) is just a **thin shim that redirects to the MCP tools.**

## How it's used (the mental model / flow)

1. Open your workspace — **any** LLM, terminal or IDE.
2. **Call MCP first.** Either name a project (agent filters; if not found it says so),
   or call with no project → get **general progress across all projects.**
3. MCP returns a **summary first** — compact status tables per item:
   **in-progress · todo · blocked · parked · done.** Never a full dump.
4. You pick a ticket/work → the agent **drills deeper on demand** (that item's detail +
   guidance) → gains context without burning tokens on everything else.
5. You work; take progress further or finish it.
6. You tell Trackden to **save** the latest state + new knowledge (e.g. "bug half-fixed").
7. Session ends; the agent's context resets — **Trackden's memory does not.**
8. Next session repeats from step 1 — the agent **still knows where everything is.**

→ Heavy data/work stays **local**; the LLM provider's context is spent only on the
slice you're actually working. Extras: on-request **standup/summary** reports; a local
**web dashboard** to view (later: edit) projects & progress.

## LOCKED DESIGN — Storage model (hybrid) [DECIDED 2026-07-20]

**Principle: NO OVERLAP.** Each datum has exactly ONE home, so there is never a sync
conflict. DB owns **state + events**; files own **guidance** (durable human knowledge);
pgvector is a **derived** search index over both — rebuildable, never a source of truth.

**One-line routing test:** *a fact that happened / current state* → **DB**; *durable
knowledge a human writes & edits* → **File**.

### What saves where

| Data | Home | Why |
|---|---|---|
| Projects · folders · items (tickets) | **DB** | query / count |
| Item **status** (todo · in-progress · blocked · parked · done) | **DB** | dashboard, filters |
| **Session logs / progress** (events) | **DB** | timeline |
| Repo links · structured metadata | **DB** | small queryable fields |
| **Decisions** ("chose X because…") | **File** `_decisions.md` | durable knowledge |
| **Architecture** | **File** `_arch.md` | human-editable |
| **Way-of-work / rules** (LLM starting point) | **File** `_way-of-work.md` | human-editable |
| Embeddings of logs **and** guidance files | **pgvector** | derived index (one-way) |

Guidance files live in a **per-project wrapper folder**, **vendor-neutral names** (never
`CLAUDE.md` as source). Per-vendor files are thin shims → redirect to the MCP tools.

### Routing — the TOOL is the destination (the LLM never chooses storage)

The LLM picks a tool by **intent**; the tool knows where to write. Storage stays hidden
behind the tool, so routing can't go wrong and stays agnostic. Tool descriptions steer it.

| Intent | Tool | Writes / reads |
|---|---|---|
| "I made progress" | `save_progress` | → DB log |
| "This item is now blocked" | `set_status` | → DB |
| "New ticket / folder / project" | `add_item` / `add_folder` / `add_project` | → DB |
| "We decided X" | `add_decision` | → file `_decisions.md` |
| "Update the rules / arch" | `update_guidance` | → guidance file |
| "Where are we?" | `overview` / `get_history` | ← DB summary **+ file pointers** (summary-first) |
| "Show the project's rules" | `get_guidance` | ← guidance files (agnostic delivery) |
| "Find where we discussed Y" | `search` | ← pgvector over logs **+** files |

### Backup

- **Files (guidance) → git** (private remote): free, versioned, off-machine.
- **DB (state) →** nightly `pg_dump` **+** `trackden export` (write items/status to a
  `_tracker.md` snapshot committed to git) **+** docker volume copy.
- Net: **one `git push` backs up everything, all human-readable.**
- **Local by default;** optional **encrypted cloud** later (opt-in only).

### Two "agnostic" mechanisms (don't confuse)

- **External agents** (you working) → agnostic via **MCP**, keyless.
- **Optional brain** (Trackden thinking alone: summaries/standup/eval) → agnostic via
  **LangChain `init_chat_model`** provider-swap; needs a key, lazy-loaded.

### Implementation delta (from current code)

- Current `add_memory` writes decisions/notes to the DB `memory` table. **New:**
  `add_decision` writes to `_decisions.md`; the DB `memory` table narrows to
  **structured links/metadata only** (or is deprecated). Reconcile in the storage phase.
- New tools to add: `set_status`, `add_decision`, `update_guidance`, `get_guidance`.
- New: per-project **wrapper-folder scaffolder** (feeds the onboarding flow, #2).
- `search` must also embed & index **guidance files**, not just logs.

## How to build this (intent & guidance)

- **Builder:** a **senior software engineer learning agentic AI in practice.** Trackden
  is the **first product** of that journey.
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
- **Hybrid storage — LOCKED.** DB owns STATE; vendor-neutral **files** own GUIDANCE;
  pgvector is a derived search index over both. Full spec: **"LOCKED DESIGN — Storage
  model"** section below. (The stub `backend/app/data.py` `TRACKERS` dict is a temporary
  seed — retire it in Phase 4.)
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

## Brain is optional; core is keyless (decided)

- The tracker **core** (MCP/CLI/web/DB/local search) makes **zero LLM calls** → needs **no
  API key or credits**. The LLM (Claude Code / any agent) brings its own intelligence via MCP.
- The **brain** (`/graph`, `/agent`, `/chat`, `trackden eval`) is kept but **optional** — LLM
  clients are built **lazily** (`_anthropic()` / `_get_llm()` / `_get_judge()`), so the app
  boots without a key; the key is read only when the brain/eval is actually invoked.
- **Why keep the brain:** value only when a human uses CLI/web **without** an agent
  (on-demand summary / next steps) or for background jobs. Through an agent it's redundant.

## Dropped / corrected (don't reintroduce)

- ❌ "plan-before-code approve gate" as a PRODUCT feature — the tracker does **not** gate
  coding. (plan-before-code is only *our build workflow*.)
- ❌ "auto-save at context budget" — replaced by real progress capture into the DB.

## Open questions / later

- ✅ **STORAGE MODEL — DECIDED** (hybrid; see "LOCKED DESIGN" section above).
- **Onboarding / configure a project (#2) — design next:** `trackden onboard` scaffolds
  the per-project wrapper folder (vendor-neutral guidance files) + creates the DB project.
  Build on the locked storage model.
- **Standup / summary reports (#7) — design next:** on-request summary across items — via
  the agent (MCP, keyless) or the optional brain (with key). Notes stored as a DB log
  and/or written to a guidance/report file.
- Exact "way-of-working" configuration the user can set (deferred — decide later).
- Optional cloud store + hosted UI (opt-in) — later.
- How the MCP server enforces "pull history first" continuity — Phase 5.

## Known follow-ups (tech debt)

- LangGraph warns Pydantic `Summary`/`Plan` are "unregistered msgpack types" — store
  `.model_dump()` dicts when wiring DB persistence.
- Security scan (local dev, non-blocking): `/agent`, `/chat`, `/graph` have no auth — fine
  locally; auth only matters if ever exposed (deployment config, not a feature).
