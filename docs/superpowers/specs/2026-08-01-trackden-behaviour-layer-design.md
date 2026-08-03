# The behaviour layer — design

**Status:** approved 2026-08-01 · **Parent spec:** `BUILD_NOTES.md` → "LOCKED DESIGN — Storage model (hybrid)"

## Why this exists

Trackden can hold work and serve it to agents. It cannot track work through to finished, and
it cannot teach an arriving agent how to use it.

Three concrete gaps, verified in the code on 2026-08-01:

1. **Nothing can change an item's status.** No `set_status` / `mark_done` exists in
   `repository.py`, `cli.py` or `mcp_server.py`. An item is created `todo` and stays `todo`
   for ever, so `whats_next` returns the same item indefinitely and the generated
   `_tracker.md` mirror never moves. This is the core loop.
2. **No agent can create work.** The eleven MCP tools are all reads plus three narrow
   writes (`save_progress`, `add_memory`, `add_decision`). There is no `add_item` or
   `add_folder`, so only a human at the CLI can put work into the tracker.
3. **Nothing tells an agent how to use any of it.** `_WAY_OF_WORK_TEMPLATE` in
   `workspace.py` is a blank skeleton the human fills in. Trackden ships a container for
   guidance and no guidance of its own. An arriving agent has tool descriptions and nothing
   else — no rule for when to save, when to ask, or how to pick a status.

The product's thesis is that Trackden is a **blueprint, not a manual**: it says what a status
*does*, never what your project must call it; it says where a finding belongs, never where
your folders live. This increment builds the behaviour layer that thesis needs, while keeping
the rule that Trackden **remembers work and never decides it**.

## Scope

**In:**

- A fixed set of four status **classes** in code, with a growable set of **names** in the DB.
- `set_status` on every door (repository · MCP · CLI).
- Write-side MCP tools: `add_item`, `add_folder`, `add_status`.
- A shipped, read-only **playbook** — Trackden's own rules for using Trackden — reachable as
  `get_playbook()`, with a short digest riding inside every `overview` response.
- Item-scoped memory and logs, so a finding attaches to the bug it belongs to.
- A `file` memory kind, so a local artifact (meeting recording, `findings.md`, an HTML
  output) can be pointed at without Trackden touching the disk.
- `get_history` gains an optional `item_id`, so the write side above has a read side.
- Fixing the `exit 0`-on-failure bug in `add-folder`, `add-item` and `log`.

**Out, deliberately:**

- **The launcher/alias hook.** A `SessionStart` hook running `trackden overview` is the only
  mechanical guarantee that an agent reads the rules; everything in this increment is
  steering, not guarantee. It needs its own design (which shell, which agents, per-repo
  opt-in) and is the natural next increment.
- **`update_guidance`.** Letting an agent rewrite a human's rules file still needs its own
  safety thinking. Unchanged from the guidance increment.
- **A transition state machine.** See "Two things Trackden deliberately does not do".
- **Deleting a status name.** Nothing in this increment removes a name from a project's
  vocabulary; an unused name is harmless. Needs a rule for items still holding it.
- **`trackden delete`** (removing a project) and indexing guidance in `search`. Both still
  open, both unrelated to this layer.

## Staging — one spec, four shippable stages

This increment is larger than the guidance one, so it splits at natural seams. Each stage
ends green and is independently useful; none leaves the tracker in a worse state than today.

| Stage | Contents | Why it stands alone |
|---|---|---|
| **A — unblock the loop** | `statuses.py` · `item_statuses` table · `set_status` on all three doors · `add_status` (repository + CLI) · the open-semantics change · the `_tracker.md` render rule | Fixes the blocker by itself. After Stage A the core loop works: items move, `whats_next` advances, the mirror tracks. Nothing here depends on the playbook. |
| **B1 — an agent can create work ✅ delivered 2026-08-03** | `add_item` · `add_folder` (wraps repository `create_folder`) · the MCP `add_status` tool, plus the hardening each needed: `add_status` closes a check-then-insert race, `create_folder`/`add_item` validate that `parent_id`/`folder_id` belong to the same project, and `add_item` takes an optional starting `status` validated against the project's vocabulary | Needs only Stage A's vocabulary (`unknown_status`/`unknown_class`) — not item scoping, not the playbook. An agent can put work into the tracker with nothing else in Stage B built yet. |
| **B2 — item scoping ✅ delivered 2026-08-03** | the `file` memory kind (`memory.path`) · item-scoped memory and logs (`memory.item_id`, `session_logs.item_id`) · `get_history(item_id=…)` · CLI flags `--item`/`--path` · fixed a real cross-project bug found along the way (`add_session_log` resolved its session by `thread_id` alone, with no project filter) | Independent of B1 and B3 — wires a finding to the item it belongs to, and needs neither the write-side tools nor the playbook to work. |
| **B3 — teach the agent** | `playbook.py` · `get_playbook` + the digest in `overview` · `trackden playbook` · the onboard print | Comes last on purpose: rules 8 and 9 tell an agent to use `add_memory(kind="file")` and to attach work to the item it belongs to — both B2 deliverables. Writing those rules before B1 and B2 ship would document tools that don't exist yet. |

Stage B was split into B1/B2/B3 during planning because the three are independent of one
another — B1 and B2 share no code and can ship in either order — while B3 is sequenced last
because its own rules reference what B1 and B2 provide; shipping it earlier would mean
telling an agent to call tools that don't exist.

`add_status` (repository + CLI) moved from Stage B to Stage A on review: `item_statuses` is a
table nothing could write to until it shipped, and an untestable table is dead weight. The
*MCP* `add_status` tool stayed in Stage B, and landed in **B1**: it still leans on the
playbook's rule 6 (how a new name gets offered) to make sense to an agent without a human
prompting it, even though the playbook's own text does not ship until B3.

Recommended as one spec and multiple implementation plans, so the blocker can ship without
waiting on the playbook's text.

## Architecture

Two new modules, both pure, plus extensions to the three existing layers.

```
  statuses.py         playbook.py            repository.py
  ───────────         ───────────            ─────────────
  4 fixed CLASSES     the shipped rules      set_status()
  open · active       + short digest         list_statuses()
  waiting · closed    + version number       add_status()
        │                    │                     │
        │  default names     │  full text          │  validates a name
        │  todo→open         │  via get_playbook   │  against the project's
        │  doing→active      │  digest rides       │  vocabulary
        │  blocked→waiting   │  inside overview    │
        │  done→closed       │                     │
        ▼                    ▼                     ▼
  ┌──────────────────────────────────────────────────────┐
  │  item_statuses table  (per project, DB owns names)    │
  │  rows ADD to the shipped defaults, never replace them │
  └──────────────────────────────────────────────────────┘
```

**The defaults are always valid.** A project's `item_statuses` rows are *additions*, so the
valid set is `shipped defaults ∪ project rows`. An earlier draft said "a project with no rows
falls back to the defaults", which implied that adding `parked` would drop `todo` and `done` —
silently invalidating every existing item. Adding a name that is already a default returns
`duplicate_name`.

| Layer | Responsibility | Change |
|---|---|---|
| `statuses.py` **(new)** | Owns the four classes and the shipped default names. Pure — no DB, no filesystem. | New module, ~60 lines. |
| `playbook.py` **(new)** | Owns Trackden's own rules: the full text, the digest, the version. Pure. | New module. |
| `repository.py` | DB state. | Adds `set_status`, `list_statuses`, `add_status`. Extends `add_memory` and `add_session_log` with optional item scoping. Four existing queries change their definition of "open". |
| `mcp_server.py` | Agent-facing door. Thin wrappers, no logic. | Five new tools. `overview` gains two response fields. `get_history` gains one optional parameter. |
| `cli.py` | Human-facing door. Thin Typer commands. | Three new commands, two new flags (`--item`, `--path`), three exit-code fixes. |
| `models.py` | Schema. | One new table, two new nullable columns. |
| `tracker_md.py` | The `_tracker.md` format, both ways. | Render gains a status suffix. Parser unchanged. |

**Untouched:** `graph.py`, `eval.py`, `guardrails.py`, `observability.py`, `embeddings.py`,
`db.py`, `guidance.py`, `workspace.py`, the frontend, Docker. `onboard.py` gains one `print`
and no logic.

### Why classes in code and names in the DB

`whats_next` has to answer "is this item something to offer next?" A name alone cannot tell
it: `blocked`, `parked` and `postponed` are three names for one behaviour. So behaviour is
fixed in code as four classes, and names are data:

| Class | Meaning | `whats_next` |
|---|---|---|
| `open` | not started | can return it |
| `active` | someone is on it | reports it |
| `waiting` | started, not actionable now | skips it, counts it |
| `closed` | finished or abandoned | hidden by default |

Adding `parked → waiting` then needs **zero code**. This is the blueprint thesis applied to
statuses: Trackden says what a status does, the project says what it is called.

The DB owning the names follows the storage model's existing rule — *"DB owns state
(projects, items, statuses, session logs); files own guidance"*. A name must be validated on
write, which a prose guidance file cannot support. The **judgment** for choosing between names
lives in the playbook. One home per fact: names in the DB, judgment in the playbook.

### Why the playbook is its own door, not a guidance doc

`get_guidance` serves **the human's rules for one project**, scaffolded at onboarding and
human-owned. The playbook is **Trackden's rules for using Trackden** — product-wide,
shipped with the code, identical for every user, and read-only. Different owner, so a
different door. Folding it into `get_guidance(doc="playbook")` would put it in a file a human
can edit, and a user silently rewriting the product's own instructions is a failure mode with
no error message.

They are allowed to disagree. When they do, **the project's way-of-work wins** — stated as
rule 10 of the playbook itself.

### Why the playbook text is a Python constant

`playbook.py` holds the text as a module-level string, not a shipped `.md` file.
`pyproject.toml` declares `packages = ["app"]`; a Python constant is guaranteed to land in the
wheel with no packaging configuration, and it is directly assertable in a pure test. The cost
is a long string in a source file, which is acceptable for text that is read far more often
than it is edited.

## The playbook

### Digest — rides inside every `overview` response

```
TRACKDEN PLAYBOOK v1

1.  Read before you work: overview → get_guidance("way-of-work").
2.  Trackden remembers; it never decides. Don't let it gate or approve work.
3.  Save on any of four triggers: a step finished · a decision made ·
    you hold findings that aren't written down yet · the user says save.
4.  Status changes: set `doing` freely when you start. Announce a
    `waiting` change in one line. ASK before you close anything.
5.  Never invent a status name — `statuses` in this payload is the valid set.
6.  The set is meant to grow. If the user's real state has no name
    ("on hold" ≠ "blocked"), offer to add one, with its class.
7.  A decision needs its reason: add_decision(decision, because).
8.  Files stay in the user's folders. Ask where it goes, then record the
    path with add_memory(kind="file"). Never create or move anything.
9.  Attach work to the item, not the project, when it belongs to one item.
10. The project's way-of-work outranks this playbook. Conflict → follow the project.
```

### Why the digest rides in `overview` rather than waiting to be fetched

A tool that exists is not a tool that gets called. Nothing compels an agent to call
`get_playbook()`, and `_tracker.md` already records the same weakness one level up:
continuity depends on the user remembering to say "check Trackden".

The design distinction is between **steering** an agent and **guaranteeing** its behaviour.
Docstrings steer; only a hook guarantees. This increment stacks the cheap layers and leaves
the guarantee to the launcher increment:

| Layer | Strength | Mechanism |
|---|---|---|
| Docstrings point back at the playbook | nudge | every write tool's description ends with a pointer |
| **Digest inside the `overview` response** | strong | `overview` is both the documented first call and the one the agent actually wants; the rules land in context without a second call |
| Version number in the digest | strong | a bumped version tells a returning agent to re-read |
| `trackden onboard` prints a paste-ready snippet | depends on the user | printed for the user's own `CLAUDE.md`; **never written** — the repo stays untouched |
| `SessionStart` hook | guarantee | out of scope, next increment |

The principle: do not rely on an agent remembering to fetch a rule — put the rule inside the
payload it already fetches.

### Rule 3's third trigger must be checkable by the agent

An earlier draft phrased it as "~30 minutes of real work with nothing written". An agent has no
reliable clock, so that trigger could not be evaluated and would simply be skipped. It is
restated as a condition the agent can actually test against its own context: **do I hold
findings that are not written down yet?**

The elapsed-time idea survives as an *observation*, not a rule: `overview` reports last
activity, so a returning agent can see a long gap and mention it. The full text says so; the
digest does not depend on it.

### Rule 4 in full — asking is keyed to reversibility

An agent that asks about everything is noise; one that silently closes work is dangerous. So
the noise level tracks the cost of being wrong:

| Change | Behaviour | Why |
|---|---|---|
| → `open` or `active` | silent | cheap, obvious, reversible |
| → `waiting` | do it, then say so in one line | the user needs to know something stalled, but it is reversible |
| → `closed` | ask first, unless the user just said it is finished | closing hides an item from `whats_next`; wrong here is expensive |

### Rule 6 in full — how a new status gets offered

The playbook ships the pattern, not a script, so the agent phrases it naturally. It must name
the mismatch rather than force the user's state into a wrong label, and it must explain the
**class**, so the user is choosing behaviour and not vocabulary. Illustrative shape:

> "This isn't blocked — nothing is in your way, you chose to set it aside. Want a `parked`
> status? It would behave as `waiting`, so it stays visible but stops showing up as your next
> step."

### Full text — seven sections, served by `get_playbook()`

1. What Trackden is, and what it is not — memory, not an agent.
2. Opening a session — the read order, and what to do when a project is unknown.
3. The four save triggers, each with a worked example, including: evidence found, nothing
   resolved, session ending — which is trigger 1 *and* trigger 3.
4. Statuses — the class table, the graduated ask rule, why classes are fixed and names are not.
5. Growing the vocabulary — the offer pattern above.
6. Files and the hybrid rule — the user's folder layout is theirs; ask, record the path,
   touch nothing.
7. Precedence and anti-patterns — project rules win; never guess a status; never record a
   decision without its reason; never claim a save that did not happen.

## Schema

One new table and two new nullable columns. Every one is additive, and each follows the
idempotent-`ALTER` pattern `init_db` already uses for `projects.repo_path`, because
`create_all` never alters an existing table.

```python
class ItemStatus(Base):
    """One EXTRA status name a project may use, and the class it behaves as.

    Additive: the shipped defaults are always valid, so a project with no rows
    works unchanged and adding `parked` can never invalidate `todo`. This is also
    why onboarding needs no seeding step.
    """
    __tablename__ = "item_statuses"

    id: Mapped[int]
    project_id: Mapped[int]          # FK projects.id, indexed
    name: Mapped[str]                # String(20); unique per project
    behaves_as: Mapped[str]          # String(10): open | active | waiting | closed
    created_at: Mapped[datetime]
```

| Column added | Table | Why |
|---|---|---|
| `path` (String(500), nullable) | `memory` | A local path is not a URL. `url` is documented as "e.g. GitLab/GitHub link"; overloading it would make one column mean two things. `kind="file"` requires `path`, `kind="link"` requires `url`. |
| `item_id` (FK, nullable) | `session_logs` | `SessionLog` has no item link today, so "tried X, it failed" can only attach to a whole project. This is what makes `get_history(item_id=...)` possible. |

`memory.item_id` and `memory.folder_id` **already exist** (`models.py:145-146`);
`repository.add_memory` simply never set them. They get wired through — no schema change.

`Item.status` stays `String(20)` with no constraint, so no existing row migrates.

### `behaves_as`, not `class`

`class` is a reserved word in Python, so the column, the parameter and the MCP tool argument
are all named `behaves_as`. It also reads better at a call site:
`add_status(project, "parked", behaves_as="waiting")`.

## The five new MCP tools

```python
set_status(project, item_id, status) -> dict
    # {status: "set", from: "todo", to: "doing"}
    # {status: "unchanged"}
    # {status: "unknown_status", valid: ["todo", "doing", "blocked", "done"]}
    # {status: "unknown_item"} · {status: "unknown_project"}

add_item(project, title, folder_id=None, status="todo") -> dict
    # {status: "added", item_id: 42}
    # {status: "unknown_folder"} · {status: "unknown_status", valid: [...]}

add_folder(project, name, parent_id=None) -> dict
    # {status: "added", folder_id: 7} · {status: "unknown_parent"}

add_status(project, name, behaves_as) -> dict
    # {status: "added"} · {status: "duplicate_name"}
    # {status: "unknown_class", valid: ["open", "active", "waiting", "closed"]}

get_playbook() -> dict
    # {version: 1, text: "..."}
```

Every return uses the status-vocabulary pattern `guidance.py` established: a `status` string,
never an exception crossing the MCP boundary.

**`overview` gains two response fields** — `playbook: {version, digest}` and
`statuses: [{name, behaves_as}, ...]`. No etag or caching machinery: the status list is four
to eight short names, so it is cheaper to send than to negotiate.

**`get_history(project, limit=10, item_id=None)`** — with an `item_id`, it returns everything
about that one item: its logs, its memory, its current status. Without the extension we would
ship the write side of item scoping and no read side.

## The CLI door

The human keeps the same reach as the agent — the CLI is the trust surface that proves an
agent actually saved what it claimed.

```
trackden set-status <project> <item_id> <status>
trackden add-status <project> <name> --behaves-as waiting
trackden playbook                                    # read Trackden's own rules

trackden remember <p> "First findings" --kind file --path ./findings.md --item 431
trackden log <p> "Reproduced on staging, not local" --item 431
```

Three new commands (`set-status`, `add-status`, `playbook`) and two new flags (`--item` on
`remember` and `log`; `--path` on `remember`). No existing flag changes meaning.

## The hybrid file story

Trackden stores **where things are**. It never creates, moves or deletes a file.

```
  The user's layout, the user's choice        What Trackden stores
  ───────────────────────────────────        ─────────────────────────
  ~/work/acme/BUG-431/                        memory row:
    ├── findings.md            ────►            kind:    "file"
    ├── call-2026-08-01.mp4                     path:    "/Users/.../findings.md"
    └── heap-dump.html                          item_id: 431
                                                title:   "First findings"
```

`MEMORY_KINDS` becomes `{link, note, transcript, file}` — additive; the existing three stay
valid, and `decision` stays rejected with its existing pointer to `add_decision`.

**Path handling:** expand `~`, resolve to absolute, store that, so the pointer survives a
different working directory. If the path does not exist, **store it and warn**
(`{status: "saved", warning: "path not found"}`) rather than refuse — the user may be
recording where something is about to go. Trackden never creates the file.

## The `_tracker.md` mirror

Markdown checkboxes only express done and not-done. Rule: class `closed` renders `[x]`,
everything else renders `[ ]`, and the status name is appended when it is not the plain
default:

```
- [ ] Fix the login redirect
- [ ] Chase the vendor SLA  · parked
- [x] Ship the health check
```

The parser is unchanged: it already coerces any status it does not recognise back to `todo`,
so a hand-edited file cannot corrupt the DB. The file remains a generated mirror — never
hand-edited.

## The one non-additive change

Four existing queries define "open" as `status != "done"` — `repository.py:71`, `:88`,
`:119`, and `:328` (`get_status`, `overview`, `list_items`, `get_history`). With classes,
the four queries split into two different predicates, because they answer two different
questions:

- **Queue** (`get_status`, `overview` — "what should I do next"): offer anything that is
  NOT `waiting` and NOT `closed`. This is a complement, not an allowlist against `open`/
  `active` — so a status this vocabulary cannot classify (a legacy row, or one set by hand
  in `psql`) is offered too, deliberately, so a human notices and corrects it. `waiting`
  items are skipped here but still counted, via a separate, positive match against the
  waiting class only — an unclassified status is never counted as waiting, or it would be
  permanently unofferable.
- **Inventory** (`list_items`, `get_history` — "what is on the list"): show anything that is
  NOT `closed`. An unrecognised status shows here too, for the same reason.

Each is a one-line change, but it is an edit to working code rather than an addition, and it
is where a regression would actually hurt. It gets a dedicated regression test
(`test_open_semantics.py`). `import_items`'s todo/done coercion and the two `tracker_md.py`
sites (the parser's todo/done inference, the renderer's closed-set check) carry status
semantics too, though neither hard-codes `!= "done"`, so they sit outside this one
non-additive change.

The change also fixes the bug at its root rather than its end: today a stuck item would sit
in `doing` for ever and keep blocking the queue. `whats_next` now returns the first item that
is not `waiting`, skips `waiting`, and reports the waiting count — so a parked item stays
visible without clogging the queue, and an unclassified item stays visible too, as NEXT.

## Error handling

| Situation | Result |
|---|---|
| Unknown status name | `{status: "unknown_status", valid: [...]}` — hands back the vocabulary so the agent self-corrects instead of guessing |
| Unknown project · item · folder · parent | the matching `unknown_*` status |
| `add_status` name already in use | `{status: "duplicate_name"}` |
| `add_status` unrecognised class | `{status: "unknown_class", valid: [...]}` |
| `kind="file"` with no `path` | `{status: "missing_path"}` |
| Path does not exist | `{status: "saved", warning: "path not found"}` — saved anyway |
| Status set to its current value | `{status: "unchanged"}` — honest, not a fake success |

Every `set_status` returns `from` and `to`, so a caller whose item was moved by another
session sees it rather than assuming.

**CLI exit codes:** every write command exits non-zero on failure. This fixes the existing bug
in `add-folder`, `add-item` and `log`, which print an error and still exit `0` — leaving a
script unable to detect that nothing was saved. `remember` was already fixed in the guidance
branch; these three were deliberately left, and this is the increment that touches them.

### Two things Trackden deliberately does not do

1. **No transition state machine.** `parked → done` is allowed. `done → todo` is allowed. Any
   valid name to any valid name. The ask-before-closing rule is **guidance the agent follows,
   not a gate the code enforces** — the moment Trackden refuses a transition it has stopped
   being memory and started being an agent.
2. **No locking.** Last write wins. Two sessions on one item is rare for a single-user local
   database, and the `from`/`to` fields make a surprise visible. Locking would be complexity
   without a matching risk.

## Testing

`statuses.py` and `playbook.py` are pure, so most new tests need no Postgres. DB tests carry
`@pytest.mark.db` and auto-skip when Postgres is unreachable, as established.

| File | Kind | Covers |
|---|---|---|
| `test_statuses.py` | pure | class mapping · the four classes are closed · defaults resolve when a project has no rows · name validation |
| `test_playbook.py` | pure | version present · **digest stays under 1200 characters** (it rides in *every* `overview`, so the budget is asserted, not hoped for) · all ten rules present · text importable from the installed package |
| `test_set_status.py` | `@db` | real transitions · `unchanged` · `from`/`to` · unknown item |
| `test_statuses_db.py` | `@db` | `add_status` · duplicate name · a custom name is then usable by `set_status` |
| `test_open_semantics.py` | `@db` | **regression guard** — one item per class, then `whats_next` returns only `open`, skips `waiting`, counts it; `list_items` and `overview` agree |
| `test_migration.py` | `@db` | `init_db` on a pre-existing database adds the table and both columns, and loses no row |
| `test_mcp_server.py` (extend) | mixed | the five new tools · the two new `overview` fields · `get_history(item_id=...)` |
| `test_cli.py` (extend) | mixed | the new commands and flags · non-zero exits on failure |
| `test_bug_scenario.py` | `@db` | the whole walkthrough below, end to end, no fakes — the house style `test_guidance.py` set |

Two tests carry the weight. `test_open_semantics.py` guards the only place existing behaviour
changes. `test_migration.py` exists because `_tracker.md` records that the onboarding branch
shipped a migration bug for exactly this reason — `create_all` never alters an existing table
— and this increment adds one table and two columns into the same trap.

**TDD order:** `statuses.py` → `playbook.py` → schema and migration → repository writes →
the open-semantics change → MCP tools → CLI → the end-to-end scenario. Red then green at each
step.

## Success criteria — the walkthrough that must pass

| The world | The agent calls | What lands |
|---|---|---|
| "Bug 431, login redirect loops" | `overview` → sees the digest and the valid statuses | rules in context, nobody had to prompt for them |
| | `add_item(title="Fix login redirect loop")` → `item_id: 431` | the item exists |
| | `set_status(431, "doing")` — silent, per rule 4 | the user can see it is live |
| user reproduces it, saves a heap dump | agent asks where findings go, user answers | `add_memory(kind="file", path=…, item_id=431)` |
| digging turns up a cause, nothing fixed yet | trigger 3 — unwritten findings exist | `add_session_log("Safari only, cookie SameSite", item_id=431)` |
| "Let's use the redirect allowlist" | `add_decision(…, because=…)` | appended to `_decisions.md` |
| the vendor has to patch first | agent offers `parked`, user agrees | `add_status("parked", "waiting")` then `set_status(431, "parked")` |
| **next day, new session** | `overview` → 431 absent from `whats_next`, counted as waiting | `get_history(item_id=431)` returns every log, both file paths, and the decision |

Nothing is lost, and nothing on the user's disk was touched by Trackden.

## Open, and deliberately next

- **The `SessionStart` hook / launcher.** Every layer in this increment steers; none
  guarantees. This is the guarantee, and it is the next increment.
- **`update_guidance`** — an agent editing the human's rules file, with its own safety design.
- **Removing a status name** — needs a rule for items still holding it.
- **`trackden delete`** — still no way to remove a project.
- **Indexing guidance in `search`** — semantic search still covers session logs only.
