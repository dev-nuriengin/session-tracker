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
| `trackden add-item <p> "…" [--status]` · `add-folder <p> "…" [--parent]` · `log [--item]` · `remember [--kind --path --item --folder]` | Add work (items, folders), save progress, store a link/note/transcript/file. `--item` on `log`/`remember` scopes an entry to one item instead of the whole project; `remember --kind file --path <file>` points at a local artifact (Trackden never touches it). `add-item` / `add-folder` / `add-status` are now available to an agent over MCP too. |
| `trackden show <p> --item <id>` | The whole story of one item: its status, its memory (with file paths), its logs — narrowed to just that item. |
| `trackden set-status <p> <item> <status>` · `add-status` · `statuses` | Move an item to a new status; add a project-specific status name; list what's valid. |
| `trackden guidance <p> [--doc]` | Read a project's rules · architecture · decisions. |
| `trackden playbook` | Print Trackden's own rules for using Trackden — the full text (seven sections). The short digest rides inside the **MCP** `overview` response, so agents get it without asking. Needs no project — works before any project exists. |
| `trackden decide <p> "…" --because "…"` | Record a decision **and why**. Appends to `_decisions.md`. |
| `trackden ask "…"` | Semantic search across every project's session logs. |

**What agents get over MCP:** `overview` (call first — cheap), `get_history`, `list_items`,
`set_status`, `list_statuses`, `list_memory`, `get_guidance`, `whats_next`, `search`,
`save_progress`, `add_memory`, `add_decision`, `list_projects`, `add_item`, `add_folder`,
`add_status`, `get_playbook`. Tool count stayed 16 through Stage B2 — B2 added parameters,
not tools: `add_memory` gained `path`/`item_id`/`folder_id` (a `file` kind, and scoping to
the item/folder it belongs to), `save_progress` gained `item_id`, and `get_history` gained
`item_id` (pass it when resuming one item instead of the whole project — its logs, its
memory including file paths, its status). **Stage B3 adds one genuinely new tool: 16 → 17.**
`get_playbook()` takes no arguments and works before any project exists — it serves
Trackden's own rules, not project data.

**Where things live — one home per fact.** DB owns *state* (projects, items, statuses,
session logs). Files under `~/.trackden/projects/<slug>/` own *guidance* (way-of-work,
architecture, decisions). `_tracker.md` in that folder is a **generated mirror** of the DB —
never hand-edit it. pgvector is a derived index, never a source.

**Five behaviours worth knowing** (they were deliberate decisions, not accidents):

1. **Declining an import is safe.** Say `n` at the gate, read the file yourself, run
   `onboard` again — it offers the same items again. Import only happens while a project
   has no items, so re-running can never duplicate them.
2. **Guidance files are never a source of items.** Your repo's `CLAUDE.md` seeds
   `_way-of-work.md` and nothing else, so the same checklist can't land in two places.
3. **Decisions go to a file, not the DB.** `add_memory` accepts `link | note | transcript |
   file` and *rejects* `decision`, pointing you at `add_decision` / `trackden decide` — as an
   outcome dict (`rejected_kind`, with `valid` and a `message`), not an exception; `add_memory`
   was the last write function that raised for an expected outcome, fixed in Stage B2.
4. **A session log used to be looked up by `thread_id` alone, with no project filter —
   fixed in Stage B2.** The CLI's `--thread` defaults to `"cli"` for every project, so
   `trackden log project-a "…"` then `trackden log project-b "…"` (both on the default
   thread) filed project B's note into project A's session — a real cross-project bug, not
   hypothetical. `add_session_log` now looks up the session by `thread_id` AND `project_id`
   together. Verified by hand at the CLI, not just in pytest: two throwaway projects, both
   logging on the default `--thread cli`, each `show --full` afterwards showed only its own
   note.
5. **An agent's `overview` call now carries Trackden's own playbook digest — Stage B3, shipped
   2026-08-03.** `repository.overview(slug, include_playbook=False)` adds a ninth key,
   `playbook: {version, digest}`, **only when asked** — the MCP tool passes `True`, so an
   agent gets steering rules without a second tool call, while `trackden show` and the
   FastAPI endpoint keep the original eight-key shape. Steering belongs at the agent door,
   and the web UI has no use for 1.5 KB of agent instructions on every poll. An unknown
   project still returns exactly `{}` either way. The full text (seven sections) is
   `get_playbook()` / `trackden playbook`.
   `trackden onboard` prints a paste-ready snippet for the user's own `CLAUDE.md`/`AGENTS.md`
   pointing at `overview()` and the playbook — it is only ever **printed**, never written;
   the repo stays untouched (proved by a recursive, directory-safe before/after snapshot of
   every file in the scanned repo).

**What's still open after Stage B3 — know this before you rely on it:** the playbook now
ships (`playbook.py`, `get_playbook`, the digest inside the MCP `overview`, `trackden
playbook`, the onboard paste-snippet — all Stage B3, shipped 2026-08-03), and everything it
teaches is steering, not a guarantee — nothing forces an agent to read `overview`'s response
or act on what it says. **The only mechanical guarantee is still unbuilt: the `SessionStart`
launcher/hook** that would run `trackden overview` automatically at the start of a session.
Until it exists, continuity depends on the agent (or the user) remembering to call it. See
"▸ NEXT" below.

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

**▸ NEXT — the `SessionStart` launcher.**

Stage A unblocked the loop. Stage B1 shipped 2026-08-03: an agent can now create work itself
— `add_item`, `add_folder`, the MCP `add_status` tool — instead of needing a human at the
CLI. **Stage B2 shipped 2026-08-03 too:** a finding now attaches to the item it belongs to,
not just the whole project — the `file` memory kind (`memory.path`), `session_logs.item_id`,
`get_history(item_id=…)`, and the CLI's `--item` / `--path` flags. Verified end-to-end
against the real database, not just pytest (see Phase 13 below): a file kind saves with the
path expanded and absolute; `show --item` narrows to one item's logs and memory; a
`parked` status (behaves as `waiting`) is counted but never offered as NEXT; a missing
`--path` saves with a warning, no `--path` at all exits 1; and the session-lookup bug (below)
is fixed. See Phase 13 below for exactly what shipped.

**Stage B3 shipped 2026-08-03 too — the playbook.** `playbook.py` (pure, product-owned:
`VERSION = 1`, an eleven-rule `DIGEST` at 1521 of a 1700-character budget, and a
seven-section `TEXT`), `get_playbook()` (MCP tool count 16 → 17; needs no project, works
before any project exists), `trackden playbook` (CLI command count 16 → 17), the digest
riding inside the **MCP** `overview` response (`playbook: {version, digest}`, a ninth key
added only when `include_playbook=True`, which the MCP tool passes and the CLI and FastAPI
endpoint do not — an unknown project still returns exactly `{}`), and
`trackden onboard` printing a paste-ready snippet for the user's own `CLAUDE.md`/`AGENTS.md`
— printed only, never written, proved by a recursive before/after snapshot of the whole
scanned repo. B3 came last on purpose: its rules tell an agent to use `add_memory(kind=
"file")` and to attach work to the item it belongs to — both B2 deliverables — so writing
those rules before B2 shipped would have been instructions that lied. One of its own tests
asks the real MCP tool manager whether every tool the text names actually exists, so the
playbook cannot drift from the tools it instructs an agent to call. See Phase 13 below and
the Stage B1/B2/B3 rows of the design spec.

**This closes out Stage B — nothing else in the behaviour-layer spec remains except the
launcher.** Every layer built across A/B1/B2/B3 is *steering*: docstrings that point back at
the playbook, a digest that rides along for free, a version number that tells a returning
agent to re-read. None of it is a *guarantee* — nothing forces an agent to call `overview`
at all, or to act on what it returns. **The `SessionStart` hook/launcher is the only
mechanical guarantee: a hook that runs `trackden overview` automatically at the start of a
session**, so continuity stops depending on an agent (or a human) remembering to ask. It is
unbuilt and needs its own design — which shell, which agents, per-repo opt-in — see the
design spec's "Open, and deliberately next".

**Found while building Stage B2 — worth knowing on its own:** a session log used to be
looked up by `thread_id` alone, with no project filter. The CLI's `--thread` defaults to
`"cli"` for every project, so `trackden log project-a "…"` then `trackden log project-b
"…"` (both on the default thread) filed project B's note into project A's session — a real
cross-project bug anyone using `trackden log` on two projects had already hit, not a
hypothetical. Fixed: the session is now looked up by `thread_id` AND `project_id` together.

**Then, in order:** launcher/alias so agents call MCP *first* without being told (Phase 11)
— today continuity depends on you remembering to say "check Trackden" · `trackden delete`
(no way to remove a project; worth knowing before building it — two hazards, not one:
`Project`'s `cascade="all, delete-orphan"` is ORM-level only, there's no DB-level `ON DELETE
CASCADE`, so a raw `DELETE FROM projects` fails on foreign keys; **and**, confirmed by hand
while cleaning up this stage's own smoke-test projects, even `db.delete(project)` through
the ORM fails on a `ForeignKeyViolation` from `memory`/`session_logs` once either holds an
`item_id` — neither `Memory` nor `SessionLog` has a declared ORM relationship to `Item`
(only a plain FK column), so the unit of work has no way to know those rows must be deleted
before the item they point at. The fix already lives in `tests/conftest.py`
(`_delete_project_cascading`): bulk-delete `SessionLog` and `Memory` rows explicitly first,
then `db.delete(project)`. A future `trackden delete` needs the same explicit bulk-delete,
not just `db.delete(project)`) · then dogfooding becomes real: onboard this repo into
itself, tick items through the tool instead of by hand, retire this file.

**Safety hazard, worth flagging beside `trackden delete` above — it is real and it recurred
during this stage.** `tests/conftest.py`'s test-database guard (the `_test`/`_smoke` name
check) protects **pytest runs only**. Any ad-hoc script — `uv run python -c "..."`, a
throwaway shell one-liner — loads `.env`'s real `DATABASE_URL` like any other code path, and
nothing stops it writing to the real database. During this stage, exactly that happened: an
ad-hoc verification script wrote a stray project row into the real Postgres, which holds six
real projects; it was cleaned up by hand, but the lesson is the guard does not generalise.
The real fix is a supported `trackden delete` (and, more broadly, never reaching for a raw
script against a real DB when a read-only path — CLI or `repository` call on an *existing*
project — will answer the same question). A shipped `delete` command would remove the main
reason anyone writes such a script in the first place.

**Also open, carried forward:** a folder-scoped reader should derive `folder_id` from the
item when only `item_id` is given, rather than requiring both — today `add_memory` and
`add_session_log` accept `item_id` and `folder_id` as two independent optional parameters,
so a caller who supplies an item but not its folder gets no folder scoping for free.

---

**Status:** 67 / 74 — all phases 0–13 have shipped their Stage A, Stage B1, Stage B2 and
Stage B3 core. **But "phases done" ≠ "usable day to day":** of the 7 open items, **none are
life-support blockers** — the one gap that used to stop daily use (`set_status`) shipped in
Stage A, an agent can now create work itself, unprompted (Stage B1, 2026-08-03), a finding
now attaches to the item it belongs to instead of just the whole project (Stage B2,
2026-08-03), and an arriving agent now gets Trackden's own rules inside the first call it
makes (Stage B3, 2026-08-03). **This is the whole behaviour-layer spec, done, except one
thing: the `SessionStart` launcher is the only mechanical guarantee any of it gets read.**
Do not read this line as "finished".

- 🟡 **Phase 11 launcher/alias / `SessionStart` hook — the one real gap left.** Everything
  shipped through Stage B3 steers an agent toward the rules (docstrings, the `overview`
  digest, a version number); none of it *guarantees* an agent reads or acts on any of it.
  A `SessionStart` hook running `trackden overview` automatically would be the guarantee.
  Needs its own design (which shell, which agents, per-repo opt-in). See "▸ NEXT" above.
- 🟡 **`trackden delete`** — no way to remove a project yet. Two ORM/FK hazards documented
  above (`Then, in order`), plus the safety hazard beside it: a supported `delete` would
  remove the main reason anyone reaches for an ad-hoc script against the real database.
- 🟡 **Folder-scoped reads don't derive `folder_id` from `item_id`** — carried forward, see
  "Also open, carried forward" above.
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
- [x] pytest enters the repo for the first time (81 tests then; 357 now, after the guidance, Stage A, Stage B1, Stage B2 and Stage B3 branches added more); DB-marked tests auto-skip when Postgres is unreachable
- [ ] Deferred: launcher/alias so agents "call MCP first" without touching repos (needs its own design)
- [ ] Deferred: agent-driven onboard exposed as an MCP tool (CLI-first for now)

## Phase 12 — Guidance path: read + one write, over every door ✅
- [x] `workspace.py`: `GUIDANCE_DOCS` (the one mapping read and write share) + the read path — `guidance_path`, `read_guidance` (`None` when not scaffolded, never creates), `is_template` (untouched-scaffolding check), `append_decision` (append-only, refuses to scaffold a missing folder)
- [x] `guidance.py` orchestrator: `get(project, doc="way-of-work")` and `add_decision(project, decision, because, rejected=None)` — a `status` vocabulary (`filled` · `template` · `not_scaffolded` · `unknown_project` · `unknown_doc` · `appended` · `invalid_slug`) instead of exceptions crossing the MCP boundary
- [x] MCP tools `get_guidance` and `add_decision` (`mcp_server.py`)
- [x] CLI commands `trackden guidance <project> [--doc]` and `trackden decide <project> <decision> --because [--rejected]` (`cli.py`)
- [x] `repository.MEMORY_KINDS` narrows the `memory` table to `link | note | transcript`; `add_memory` raises `ValueError` outside it — `remember` (CLI) and `add_memory` (MCP) both catch it and exit/return non-success rather than crash. *(Stage B2, 2026-08-03: widened to `link | note | transcript | file`, and `add_memory` moved off the exception onto an outcome dict — see Stage B2 below.)*
- [x] One real end-to-end test (`@pytest.mark.db`, `test_guidance.py`) against the actual repository and workspace, no fakes — closes the gap the onboarding branch's migration bug exposed
- [ ] Deferred: `update_guidance` (editing rules/architecture from an agent) — still a human action on the file
- [x] **`set_status`, on every door — SHIPPED (Stage A, 2026-08-01, see Phase 13).** An item can move: `repository.set_status` (any valid name to any other, no state machine, always reports `from`/`to`), MCP `set_status`, CLI `set-status`. Status is now a fixed behaviour **class** (`open` · `active` · `waiting` · `closed`) in `statuses.py` with a growable set of **names** in the `item_statuses` table.
- [ ] Deferred: `search` does not index guidance files yet — semantic search still covers session logs only
- [ ] Deferred: cwd→project resolution — every door still takes an explicit project/slug

## Phase 13 — Behaviour layer: Stage A unblocks the loop, Stage B teaches the agent

Spec: `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` (approved
2026-08-01). Split into shippable stages on purpose — Stage A fixes the blocker by itself;
Stage B needs Stage A's vocabulary to reference, so it comes second. Stage B was itself
split into B1/B2/B3 during planning, because the three are independent of each other — B1
(write-side MCP tools) and B2 (item scoping) don't depend on one another, and B3 (the
playbook) is written last on purpose: its rules tell an agent to use tools B1 and B2
provide, so writing them earlier would ship instructions that lie.

### Stage A — unblock the loop ✅ (shipped 2026-08-01)
- [x] `statuses.py` — four fixed behaviour classes in code (`open` · `active` · `waiting` · `closed`); four shipped default names as data (`todo`→open, `doing`→active, `blocked`→waiting, `done`→closed)
- [x] `item_statuses` table + `repository.list_statuses` / `add_status` / `closed_names` — a project ADDS names on top of the shipped defaults, never replaces them; moved here from Stage B in the spec correction (a table nothing can write to is untestable dead weight); new table, so `create_all` covers it, no migration line needed
- [x] `repository.set_status` on all three doors (repository · MCP · CLI) — deliberately not a state machine, any valid name may follow any other (reopening included); always reports `from`/`to`; outcomes `set` · `unchanged` · `unknown_status` (with the valid list) · `unknown_item` · `unknown_project`
- [x] The open-semantics change — four queries (`get_status`, `overview`, `list_items`, `get_history`) now ask "is this item's status in the closed class?" instead of `!= "done"`; `whats_next` returns the first item that is neither `waiting` nor `closed` (an unrecognised status offered too, on purpose), skips `waiting`, and counts it
- [x] `overview` gains `waiting_items` and `statuses`; every pre-existing key kept its name; `trackden show` now prints the waiting count too
- [x] `_tracker.md` mirror — a closed name renders `[x]`; a non-default open status appends its name (`· parked`); parser untouched
- [x] MCP tools `set_status`, `list_statuses` (tool count 11 → 13); CLI commands `set-status`, `add-status`, `statuses` (command count 13 → 16)
- [x] Fixed the exit-0 bug: `add-folder`, `add-item` and `log` now exit non-zero on failure, matching `remember`

### Stage B1 — an agent can create work ✅ (shipped 2026-08-03)
- [x] `repository.add_status` — closes a check-then-insert race (the `UniqueConstraint` is caught, rolled back, and reported as `duplicate_name`); moved to the outcome-dict shape; `unknown_class` now carries the valid classes, so the CLI stopped hardcoding them
- [x] `repository.create_folder` — validates `parent_id` belongs to the same project (a ForeignKey only proves a row exists, never that it's yours — a parent id from another project used to be accepted and the folder silently nested there; a nonexistent id was a raw `IntegrityError`); returns an outcome dict with `folder_id`
- [x] `repository.add_item` — same ownership fix for `folder_id`, plus an optional starting `status` validated against the project's vocabulary (`unknown_status` with `valid`); returns an outcome dict with `item_id`
- [x] MCP tools `add_item`, `add_folder`, `add_status` — thin wrappers (tool count 13 → 16)
- [x] CLI: `add-folder` gained `--parent`, `add-item` gained `--status` (command count stays 16 — new flags, no new commands)

### Stage B2 — item scoping ✅ (shipped 2026-08-03)
- [x] `memory.path` and `session_logs.item_id` columns, each with an idempotent (`IF NOT EXISTS`) line in `db.py`'s `_migrate()` — no `create_all` coverage needed since both tables already existed
- [x] The `file` memory kind (`memory.path`) — `MEMORY_KINDS` widened to `link | note | transcript | file`; a path is expanded and stored absolute (survives a different working directory); a path that doesn't exist is stored WITH `{"warning": "path not found"}` rather than refused; Trackden never creates, moves or reads the file. `add_memory` also moved off raising `ValueError` for a bad kind onto an outcome dict (`rejected_kind`, with `valid` and a `message`) — the last write function using an exception for an expected outcome
- [x] Item-scoped memory and logs — `memory.item_id`/`folder_id` and `session_logs.item_id` wired through `add_memory`/`add_session_log`, each validated as belonging to THIS project (`unknown_item`/`unknown_folder`), not just existing anywhere
- [x] **A real cross-project bug, found while wiring this in and fixed here:** `add_session_log` resolved its session by `thread_id` ALONE, no project filter. The CLI's `--thread` defaults to `"cli"` for every project, so `trackden log project-a` then `trackden log project-b` filed B's note into A's session. Now looked up by `thread_id` AND `project_id` together. Reproduced before the fix, then verified live at the CLI post-fix with two throwaway projects (see "Found while building Stage B2" above)
- [x] `get_history(slug, limit=10, item_id=None)` — with an `item_id`, the payload narrows to that item: its logs, its memory (including file paths), and an `item` block with its title and status. Project-level behaviour (no `item_id`) is unchanged
- [x] CLI: `remember` gained `--path --item --folder`; `log` gained `--item`; `show` gained `--item` (command count stays 16 — flags only). MCP: `add_memory`, `save_progress`, `get_history` gained parameters (tool count stays 16 — no new tools)
- [x] Also extracted a `_next_position` helper (a deferred minor from B1) and extended `tests/conftest.py`'s test-teardown cascade helper — no ORM relationship links `Memory`/`SessionLog` to `Item`, so teardown had to bulk-delete those rows explicitly before the item (see the `trackden delete` cascade hazard in "▸ NEXT" above, confirmed again by hand while cleaning up this task's own smoke-test projects)
- [x] Verified end-to-end against the real database (not just pytest): `remember --kind file --path <file> --item <id>` saves with the path absolute; `show --item <id>` shows only that item's logs/memory; a `parked` status (behaves as `waiting`) is counted by `status` but never offered as NEXT; a missing `--path` file saves with a warning; `--kind file` with no `--path` exits 1; the cross-project fix holds at the CLI

### Stage B3 — the playbook ✅ (shipped 2026-08-03)
- [x] `playbook.py` — Trackden's own shipped, read-only rules, pure (no DB, no filesystem, no `app.*` imports): `VERSION = 1`, an eleven-rule `DIGEST` (1521 of a 1700-character budget — the spec's draft said 1200, then 1500; both were too tight and the 1500 ceiling had already forced rule 11 to be golfed, losing the `Conflict:` framing its siblings share, so the ceiling moved to give a normal edit room. See the spec's "Corrections after B3 shipped"), and a seven-section `TEXT` — served by `get_playbook()`. One test asks the real MCP tool manager whether every tool the text names actually exists, so the playbook cannot drift from tools it instructs an agent to call
- [x] The digest riding inside the **MCP** `overview` response — a ninth key, `playbook: {version, digest}`, added only when `include_playbook=True`. The MCP tool passes it; `trackden show` and the FastAPI endpoint do not, so the human-facing shape is unchanged and the web UI doesn't poll 1.5 KB of agent instructions. An unknown project still returns exactly `{}` either way
- [x] MCP tool `get_playbook()` — takes no arguments, works before any project exists (tool count 16 → 17)
- [x] `trackden playbook` CLI command — prints the full text, needs no project (command count 16 → 17)
- [x] `trackden onboard` prints a paste-ready snippet for the user's own `CLAUDE.md`/`AGENTS.md` pointing at `overview()` and the playbook digest — **printed, never written**; a recursive, directory-safe before/after snapshot of every file in the scanned repo proves nothing changed
- [x] **Correction to this plan's own notes:** the B3 plan originally placed the paste-snippet's `print` inside `onboard.py`. That was wrong — `onboard.py` contains no `print` at all; it returns an `OnboardResult` and stays pure I/O-wise. The snippet lives in `cli.py`'s `onboard` command, which already does all the other printing (the summary, the guidance file list) — the better boundary, since `onboard.py` is reused by anything that isn't the CLI

B3 was written last on purpose: its rules tell an agent to use `add_memory(kind="file")` and
to attach work to the item it belongs to — both are B2 deliverables. Writing those rules
before B2 shipped would have told an agent to call tools that didn't exist yet.

**This closes Stage B and the whole behaviour-layer spec except one thing: the
`SessionStart` launcher/hook.** Every layer A/B1/B2/B3 shipped is steering — docstrings,
a digest riding along for free, a version number — none of it is a mechanical guarantee.
See "▸ NEXT" above.
