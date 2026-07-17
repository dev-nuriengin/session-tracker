# Session Tracker — build progress

> Single source of truth for the build. Terminal Claude reads this at session start
> and ticks items at session end. Browser mirror: GrowthHQ → Projects → 🛠 Build Plan
> (Export copies this format to clipboard; Import pastes it back to re-tick the boxes).
>
> Rules: mark done with `[x]`, not-done with `[ ]`. The **first `[ ]` item is NEXT**.
> Don't rename item text — the browser mirror matches lines by exact text.

## ▸ Resume here (next session)

**Status:** 7 / 24 done. Phase 1 complete; Phase 2 started — state graph modelled & running.

**Decisions (Phase 2):** LLM layer = **LangChain** (`langchain-anthropic`), not raw SDK — so provider swap is one line (`init_chat_model("anthropic:claude-opus-4-8")` → openai/xai). New **`/graph`** endpoint; `/agent` kept as reference.

**NEXT:** Phase 2 continues — (1) structured outputs: make `summarize`/`plan` return **Pydantic** objects via LangChain `.with_structured_output(...)` instead of free text; (2) wire `list_projects` / `read_tracker` in as graph nodes/edges (currently `load` reuses the tracker stub directly).

**Where the Phase 2 code is:**
- `backend/app/graph.py` — `StateGraph` with nodes load → summarize → plan → approve; `SessionState` TypedDict; `run_graph(project)`. Provider set in ONE line (`init_chat_model`).
- `backend/app/data.py` — shared `PROJECTS` + `TRACKERS` (moved out of main.py to avoid circular import).
- `backend/app/main.py` — `/graph` endpoint (thin wrapper over `run_graph`).
- Verified: `run_graph("korpus")` returns context + summary + plan + approved.
- `approve` node auto-approves (real human-in-the-loop pause = Phase 3).

**Where the code is:** `backend/app/main.py`
- `/health`, `/` — basic
- `/chat` — streaming Claude call over SSE (Phase 1.1 ✅)
- `/agent` — manual tool-calling `while`-loop + `TOOLS` list + `run_tool()` (Phase 1.2 ✅)
- Tools: `list_projects` (no params) + `read_tracker(project)` (param; case-insensitive, stubbed via `TRACKERS`). Verified end-to-end — agent picks `read_tracker`, passes `{"project":"korpus"}`, returns the status (Phase 1.3 ✅).

**How to run:**
1. `docker compose up -d` (Postgres+pgvector on :5433)
2. `cd backend && uv run uvicorn app.main:app --reload` → http://localhost:8000
3. `cd frontend && npm run dev` → http://localhost:3000
4. Test: `curl -X POST localhost:8000/agent -H "Content-Type: application/json" -d '{"message":"what am I working on?"}'`

**Env:** `.env` (gitignored) holds `ANTHROPIC_API_KEY`. Model in use: `claude-opus-4-8`.

**Learn-hub (tag `session-tracker`, not yet posted):** streaming LLM calls / SSE; the agent loop (tool-calling while-loop). Both hub-worthy.

**Git:** Phase 0 + Phase 1 committed & pushed (`dev-nuriengin`). Phase 2 code (graph.py, data.py, /graph, deps) is **uncommitted** — commit when ready (needs explicit "yes").

---

## Phase 0 — Scaffold & method
- [x] Write the .ai/ workspace + _tracker.md spec (index-vs-detail, plan-before-code)
- [x] docker-compose: Postgres+pgvector · FastAPI · Next.js skeleton
- [x] sess CLI skeleton (Python · Typer): picker · start · ask stubs

## Phase 1 — First agent, from scratch
- [x] One end-to-end Claude call from FastAPI, streamed over SSE
- [x] Build the agent loop by hand: tool-calling while-loop (no framework)
- [x] First tools: list_projects · read_tracker

## Phase 2 — Port to LangGraph
- [x] Model the state graph: load → summarize → plan → approve
- [ ] Structured outputs (Pydantic) for summary + plan
- [ ] Wire tools as graph nodes & edges

## Phase 3 — State, memory, human-in-the-loop
- [ ] Checkpointing: a session survives a restart (MemorySaver)
- [ ] Human-in-the-loop gate: approve before code
- [ ] Auto-save at the context budget

## Phase 4 — MCP layer
- [ ] Build the MCP server (FastMCP) exposing tracker tools
- [ ] Claude Code discovers & calls the tools
- [ ] Local + remote server config

## Phase 5 — RAG over session logs
- [ ] pgvector schema + embeddings + chunking of logs
- [ ] Retrieval tool: sess ask across all trackers
- [ ] Hybrid search + rerank

## Phase 6 — Eval, safety, observability
- [ ] Langfuse tracing end-to-end
- [ ] LLM-as-judge eval on summaries
- [ ] Guardrails + PII redaction on tracker notes

## Phase 7 — Ship
- [ ] Next.js streaming UI: status board · history · agent traces
- [ ] sess picker → boot context → start (retire every alias)
- [ ] Dockerize + deploy
