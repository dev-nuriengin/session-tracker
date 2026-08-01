# Trackden — build progress (TEMPORARY scaffold)

> ⚠️ **This file is a temporary bootstrap.** It's the manual build log used *while*
> building Trackden. Once the product works, it **tracks itself** (dogfood) and
> this file is retired — the build status moves into the tracker's own DB.
>
> While it exists it doubles as a **living example** of the tracking pattern: read at
> session start, tick items at the end.
>
> Rules: `[x]` done, `[ ]` not. The **first `[ ]` item is NEXT.**

## ▸ Start here — 30-second orientation

**What Trackden is:** a local, private memory of your work. It does not do work. AI agents
plug into it over MCP so they know where everything stands without you re-explaining.

**What works today, as commands you can actually type:**

| | |
|---|---|
| `trackden onboard` | Bring a project in. Reads a repo, offers to import its checklist behind a y/n/edit gate, scaffolds guidance in `~/.trackden`. Never writes to your repo. |
| `trackden list` · `show <p>` · `status <p>` | See what you have and what's next. |
| `trackden add-item <p> "…"` · `log` · `remember` | Add work, save progress, store a link or note. |
| `trackden set-status <p> <item> <status>` · `add-status` · `statuses` | Move an item to a new status; add a project-specific status name; list what's valid. |
| `trackden guidance <p> [--doc]` | Read a project's rules · architecture · decisions. |
| `trackden decide <p> "…" --because "…"` | Record a decision **and why**. Appends to `_decisions.md`. |
| `trackden ask "…"` | Semantic search across every project's session logs. |

**What agents get over MCP:** `overview` (call first — cheap), `get_history`, `list_items`,
`set_status`, `list_statuses`, `list_memory`, `get_guidance`, `whats_next`, `search`,
`save_progress`, `add_memory`, `add_decision`, `list_projects`.

**Where things live — one home per fact.** DB owns *state* (projects, items, statuses,
session logs). Files under `~/.trackden/projects/<slug>/` own *guidance* (way-of-work,
architecture, decisions). `_tracker.md` in that folder is a **generated mirror** of the DB —
never hand-edit it. pgvector is a derived index, never a source.

**Three behaviours worth knowing** (they were deliberate decisions, not accidents):

1. **Declining an import is safe.** Say `n` at the gate, read the file yourself, run
   `onboard` again — it offers the same items again. Import only happens while a project
   has no items, so re-running can never duplicate them.
2. **Guidance files are never a source of items.** Your repo's `CLAUDE.md` seeds
   `_way-of-work.md` and nothing else, so the same checklist can't land in two places.
3. **Decisions go to a file, not the DB.** `add_memory` accepts `link | note | transcript`
   and *rejects* `decision`, pointing you at `add_decision` / `trackden decide`.

**What Stage A still leaves open — know this before you rely on it:** an agent cannot yet
**create** work — there is no `add_item` / `add_folder` over MCP, so only a human at the
CLI can put new work into the tracker. And there is no shipped **playbook** yet — an
arriving agent has tool descriptions and nothing else, no rule for when to save or how to
pick a status. Both are Stage B; see "▸ NEXT" below.

**Settled:** an item whose stored status is in no vocabulary (a legacy row, or one set by
hand in `psql`) is offered as NEXT. A queue query offers anything that is not `waiting`
and not `closed` — a complement, not an allowlist — so an unclassified status is offered
on purpose rather than hidden, and a human notices it and fixes it. It also shows up in
`list_items` and `get_history` (inventory: everything not closed), and is never counted
in `waiting_items` (that stays a positive match on the waiting class only).

**What still needs a human:** editing `_way-of-work.md` / `_arch.md` (no `update_guidance`
tool yet — agents can read them, not write them) · removing a project (no `trackden delete`)
· anything in "NEXT (optional / future)".

**Run it:** `docker compose up -d` · then `cd backend && uv run trackden …`. The core makes
**zero LLM calls** — no API key needed. Only the optional brain (`eval`, `/graph`) uses one.

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
  *(Where that memory lives was settled later: decisions → `_decisions.md`; links, notes
  and transcripts → the DB `memory` table. See "Start here" above.)*
- **One core, three doors:** core = **local Postgres (+pgvector)** (single source of
  truth); doors = **MCP** (agents — the heart) · **CLI** (`trackden`) · **web** (local view).
- **Privacy:** all DATA is **local & private, never public.** Optional cloud store later,
  **opt-in only** (for a hosted UI). App *code* is public on GitHub; app *data* is not.
- The **LangGraph brain** (summarize/plan) is an **optional helper**, not the product.

## ▸ Resume here (next session)

### ✅ DONE — Stage A: the loop unblocks (shipped 2026-08-01)

An item can finally move. `statuses.py` fixes four behaviour **classes** in code (`open` ·
`active` · `waiting` · `closed`) with a growable set of **names** in the DB
(`item_statuses` — a project's rows ADD to the shipped defaults `todo`/`doing`/`blocked`/
`done`, never replace them, so `todo`/`done` can never be invalidated). `set_status` reaches
every door — `repository.set_status` (returns `set`/`unchanged`/`unknown_status` (with the
valid list)/`unknown_item`/`unknown_project`, always reports `from`/`to`, deliberately not a
state machine), MCP `set_status` + `list_statuses`, CLI `set-status` + `add-status` +
`statuses`. "Open" no longer means `status != "done"`: four queries (`get_status`,
`overview`, `list_items`, `get_history`) now ask "is this in the closed class?", so
`whats_next` returns the first item that is neither `waiting` nor `closed` (an
unrecognised status offered too, on purpose), skips `waiting`, and counts it —
`overview`/`trackden show` both report the waiting count. The `_tracker.md` mirror renders
a closed name as `[x]` and appends a non-default open status name. Also fixed: `add-folder`,
`add-item` and `log` printed a failure and still exited `0`; they now exit non-zero, like
`remember` already did. Spec:
`docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md`. See Phase 13 below
for exactly what shipped and what Stage B still owes.

### ✅ DONE — the guidance path (shipped 2026-07-30)

Guidance (way-of-work / architecture / decisions) is now readable and appendable over
every door, not just from disk: `workspace.py`'s read path → `guidance.py` orchestrator
(status vocabulary, never raises) → MCP tools `get_guidance` / `add_decision` → CLI
`trackden guidance` / `trackden decide`. The DB `memory` table narrowed to
`link | note | transcript` — decisions live in `_decisions.md` only. One real
end-to-end test (`@pytest.mark.db`, no fakes) exercises the whole path against the
actual repository and workspace. Spec: `BUILD_NOTES.md` → "LOCKED DESIGN — Storage
model". See Phase 12 below for exactly what shipped and what's still deliberately
deferred.

### ✅ DONE — `trackden onboard` (shipped 2026-07-29)

Onboarding shipped end-to-end: read-only repo scan → review gate (y/n/edit, defaults to
import) → DB project (+`repo_path`) → central `~/.trackden` scaffold → summary. Spec:
`BUILD_NOTES.md` → "LOCKED DESIGN — Onboarding (`trackden onboard`)". Implementation plan
(8 tasks, TDD) that built it: `docs/superpowers/plans/2026-07-28-trackden-onboard.md`. See
Phase 11 below for exactly what shipped and what's still deliberately deferred.

**▸ NEXT — Stage B: teach the agent.**

Stage A unblocked the loop; Stage B teaches an arriving agent to use it without being told.
Two things are missing: a shipped **playbook** (`playbook.py` + `get_playbook()`, with a
digest riding inside every `overview` response so an agent gets the rules without a second
call) and the **write-side MCP tools** (`add_item`, `add_folder`, `add_status`) so an agent —
not just a human at the CLI — can put work into the tracker. Also in scope: the `file`
memory kind, item-scoped memory/logs, and `get_history(item_id=…)`. See Phase 13 below and
the "Stage B — teach the agent" row of the design spec.

**Then, in order:** launcher/alias so agents call MCP *first* without being told (Phase 11)
— today continuity depends on you remembering to say "check Trackden" · `trackden delete`
(no way to remove a project; three findings in the last two branches were made worse by its
absence — and worth knowing before building it: `Project`'s `cascade="all, delete-orphan"`
is ORM-level only, there's no DB-level `ON DELETE CASCADE`, so a raw `DELETE FROM projects`
fails on foreign keys; a delete command must go through the ORM session, not raw SQL) · then
dogfooding becomes real: onboard this repo into itself, tick items through the tool instead
of by hand, retire this file.

---

**Status:** 48 / 63 — all phases 0–13 have shipped their Stage A core. **But "phases done" ≠
"usable day to day":** of the 15 open items, **none are life-support blockers any more** —
the one gap that used to stop daily use (`set_status`) shipped in Stage A. Stage B (Phase 13)
is what turns a working store into one an agent can use unprompted. Do not read this line
as "finished".

- 🟡 **Phase 13 Stage B — teach the agent.** No playbook ships yet, and an agent still
  cannot create work over MCP (`add_item` / `add_folder` / the MCP `add_status` tool don't
  exist; only the CLI and repository can). See "▸ NEXT" above.
- 🟡 **Phase 11 launcher/alias** — not a blocker, but it is what makes continuity automatic
  instead of dependent on you remembering to mention Trackden.
- Refinements, safe to leave: Phase 7 optional cloud store · Phase 8 hybrid search + rerank
  · Phase 11 agent-driven onboard as an MCP tool · Phase 12 `update_guidance` · Phase 12
  guidance indexed in `search` · Phase 12 cwd→project resolution.
- Settled (no longer open): an unrecognised status is now offered by both queue queries
  (`get_status`, `overview`) as well as showing in both inventory queries (`list_items`,
  `get_history`) — see "Settled" in "▸ Start here" above.

**Build complete.** The whole product exists: local Postgres core → three doors (MCP · CLI
· web), summary-first, private, provider-swappable, with RAG + eval + opt-in observability,
dockerized for local run.

**Cost/keys:** the core (MCP/CLI/web/DB/local search) makes **zero LLM calls → runs with no
API key or credits** (LLM clients are lazy). The **brain** (`/graph`, `/agent`, `/chat`,
`trackden eval`) is **optional** — reads the key only when actually used (value: human at CLI/web
without an agent, or background jobs). Security follow-up done: eval redacts at its LLM
boundary; `redact()` is best-effort defense-in-depth.

**NEXT (optional / future):** hybrid search + rerank (Phase 8) · folder grouping in the web
UI · optional cloud store + hosted UI (opt-in) · launcher/alias so agents "call MCP first"
without touching repos · agent-driven onboard exposed as an MCP tool · remove the
superseded `cli/` skeleton · start dogfooding (retire `_tracker.md` into the product itself,
onboarding onto itself). (`add-folder`, `add-item`, and `log` used to echo a failure message
and still exit 0 — fixed in Stage A, see Phase 13; all four write commands now exit non-zero
on failure.)

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

## Phase 11 — Onboarding (`trackden onboard`) ✅
- [x] `tracker_md.py` — the `_tracker.md` format both ways (parse + render), pure & tested
- [x] `workspace.py` — central `~/.trackden` scaffolding with slug validation; guidance files are never overwritten once written; scaffolds the home as a git repo
- [x] `projects.repo_path` + idempotent `ALTER` in `init_db` (`create_all` never alters an existing table) + `import_items` / `items_with_folders`
- [x] `onboard.py` — read-only repo scan, in priority order: `_tracker.md` · `main-plans/_tracker.md` · `_tickets-and-status/_tracker.md` · `**/_tracker.md` · `CLAUDE.md` · `AGENTS.md` (the last two seed `_way-of-work.md`, never treated as sources of truth)
- [x] `run_onboard` orchestrator: identify → scan+gate → DB project → scaffold → summary; the review gate (y/n/edit, blank = import) only ever runs while a project is itemless, so re-onboarding can't duplicate items
- [x] `trackden onboard` CLI: interactive wizard + flags (`--name --kind --client --repo --no-import --yes/-y`)
- [x] pytest enters the repo for the first time (81 tests then; 240 now, after the guidance and Stage A branches added more); DB-marked tests auto-skip when Postgres is unreachable
- [ ] Deferred: launcher/alias so agents "call MCP first" without touching repos (needs its own design)
- [ ] Deferred: agent-driven onboard exposed as an MCP tool (CLI-first for now)

## Phase 12 — Guidance path: read + one write, over every door ✅
- [x] `workspace.py`: `GUIDANCE_DOCS` (the one mapping read and write share) + the read path — `guidance_path`, `read_guidance` (`None` when not scaffolded, never creates), `is_template` (untouched-scaffolding check), `append_decision` (append-only, refuses to scaffold a missing folder)
- [x] `guidance.py` orchestrator: `get(project, doc="way-of-work")` and `add_decision(project, decision, because, rejected=None)` — a `status` vocabulary (`filled` · `template` · `not_scaffolded` · `unknown_project` · `unknown_doc` · `appended` · `invalid_slug`) instead of exceptions crossing the MCP boundary
- [x] MCP tools `get_guidance` and `add_decision` (`mcp_server.py`)
- [x] CLI commands `trackden guidance <project> [--doc]` and `trackden decide <project> <decision> --because [--rejected]` (`cli.py`)
- [x] `repository.MEMORY_KINDS` narrows the `memory` table to `link | note | transcript`; `add_memory` raises `ValueError` outside it — `remember` (CLI) and `add_memory` (MCP) both catch it and exit/return non-success rather than crash
- [x] One real end-to-end test (`@pytest.mark.db`, `test_guidance.py`) against the actual repository and workspace, no fakes — closes the gap the onboarding branch's migration bug exposed
- [ ] Deferred: `update_guidance` (editing rules/architecture from an agent) — still a human action on the file
- [x] **`set_status`, on every door — SHIPPED (Stage A, 2026-08-01, see Phase 13).** An item can move: `repository.set_status` (any valid name to any other, no state machine, always reports `from`/`to`), MCP `set_status`, CLI `set-status`. Status is now a fixed behaviour **class** (`open` · `active` · `waiting` · `closed`) in `statuses.py` with a growable set of **names** in the `item_statuses` table.
- [ ] Deferred: `search` does not index guidance files yet — semantic search still covers session logs only
- [ ] Deferred: cwd→project resolution — every door still takes an explicit project/slug

## Phase 13 — Behaviour layer: Stage A unblocks the loop, Stage B teaches the agent

Spec: `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` (approved
2026-08-01). Split into two shippable stages on purpose — Stage A fixes the blocker by
itself; Stage B needs Stage A's vocabulary to reference, so it comes second.

### Stage A — unblock the loop ✅ (shipped 2026-08-01)
- [x] `statuses.py` — four fixed behaviour classes in code (`open` · `active` · `waiting` · `closed`); four shipped default names as data (`todo`→open, `doing`→active, `blocked`→waiting, `done`→closed)
- [x] `item_statuses` table + `repository.list_statuses` / `add_status` / `closed_names` — a project ADDS names on top of the shipped defaults, never replaces them; moved here from Stage B in the spec correction (a table nothing can write to is untestable dead weight); new table, so `create_all` covers it, no migration line needed
- [x] `repository.set_status` on all three doors (repository · MCP · CLI) — deliberately not a state machine, any valid name may follow any other (reopening included); always reports `from`/`to`; outcomes `set` · `unchanged` · `unknown_status` (with the valid list) · `unknown_item` · `unknown_project`
- [x] The open-semantics change — four queries (`get_status`, `overview`, `list_items`, `get_history`) now ask "is this item's status in the closed class?" instead of `!= "done"`; `whats_next` returns the first item that is neither `waiting` nor `closed` (an unrecognised status offered too, on purpose), skips `waiting`, and counts it
- [x] `overview` gains `waiting_items` and `statuses`; every pre-existing key kept its name; `trackden show` now prints the waiting count too
- [x] `_tracker.md` mirror — a closed name renders `[x]`; a non-default open status appends its name (`· parked`); parser untouched
- [x] MCP tools `set_status`, `list_statuses` (tool count 11 → 13); CLI commands `set-status`, `add-status`, `statuses` (command count 13 → 16)
- [x] Fixed the exit-0 bug: `add-folder`, `add-item` and `log` now exit non-zero on failure, matching `remember`

### Stage B — teach the agent (open)
- [ ] `playbook.py` — Trackden's own shipped, read-only rules: full text, a digest, a version — served by `get_playbook()`
- [ ] The digest riding inside every `overview` response, so the rules land in context without a second call
- [ ] Write-side MCP tools: `add_item`, `add_folder`, the MCP `add_status` tool (repository + CLI `add_status` already shipped in Stage A)
- [ ] The `file` memory kind (`memory.path`) — point at a local artifact (recording, `findings.md`, an HTML output) without Trackden touching the disk
- [ ] Item-scoped memory and logs (`memory.item_id` wired through, `session_logs.item_id`) — a finding attaches to the item it belongs to
- [ ] `get_history(item_id=…)` — the read side for item-scoped work
- [ ] CLI flags `--item` (`remember`, `log`), `--path` (`remember`); `trackden playbook`
- [ ] `trackden onboard` prints a paste-ready snippet for the user's own `CLAUDE.md` (never written — the repo stays untouched)
