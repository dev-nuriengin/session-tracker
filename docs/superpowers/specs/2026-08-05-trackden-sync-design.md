# `trackden sync` — design

Approved 2026-08-05. Implements the first item of the post-behaviour-layer work queue.

## Why this exists

`~/.trackden/projects/<slug>/_tracker.md` is a **generated mirror** of the DB. It carries a
banner saying so, and `workspace.scaffold_project` rewrites it unconditionally because it holds
nothing a human authored.

But `render_tracker_md` has exactly one caller in the whole application — `run_onboard`
(`onboard.py`, at the `mirror = render_tracker_md(...)` assignment). Onboarding is the only
moment the mirror is ever written. So it is correct once, at onboard time, and **stale from the
next write onward**: add an item, move a status, and the file on disk still describes the
project as it was when you onboarded it.

That is the last thing that makes the tool feel stale between sessions. A human who opens
`~/.trackden` to see where a project stands is reading history, not state.

## Scope

**In:**

- `workspace.write_mirror(...)` — a narrow writer for `_tracker.md` alone
- `sync.py` — a `sync(slug)` orchestrator returning an outcome dict
- `trackden sync [project]` — one project, or all of them
- Auto-refresh on the two write paths that can actually change the mirror, at both doors

**Out (with reasons, so nobody reads these as oversights):**

- **A `sync` MCP tool.** The mirror is a human-facing artifact; an agent reads state through
  `overview` / `list_items`, which query the DB directly and are never stale. An agent has
  nothing to gain from asking Trackden to rewrite a file the agent does not read.
- **Refreshing after `delete`.** The project is gone from the DB; its guidance folder is kept
  on purpose, and the mirror inside it is deliberately left as the last known state. Rewriting
  it would mean rendering a project that no longer exists.
- **Making the mirror a source of truth.** It stays derived output. `is_generated()` exists so
  the onboard scanner skips it rather than re-importing its own output; this spec adds a second
  use for the same guard.

## Architecture

Two new units. The split follows `guidance.py`, already in the repo: a thin orchestrator over
`repository` + `workspace`, with a status vocabulary instead of exceptions.

| Unit | Responsibility | Depends on |
|---|---|---|
| `workspace.write_mirror(slug, text, home=None) -> Path` | Write `_tracker.md` and nothing else. Never creates the project folder. Never touches guidance files. | filesystem |
| `sync.sync(slug) -> dict` | Gate, render, write. Never raises. | `repository`, `workspace`, `tracker_md` |

`repository.py` stays filesystem-free. Every other module in the app treats it as the DB layer,
and a mirror write inside it would make a DB call fail for a cosmetic reason.

### Why a narrow `write_mirror` instead of reusing `scaffold_project`

`scaffold_project` does write the mirror unconditionally — but it also creates
`_way-of-work.md`, `_arch.md` and `_decisions.md` when they are absent, and `mkdir(parents=True)`
the folder. Calling it from `sync` would mean a command named "refresh this file" silently
invents three guidance documents for a project that was never onboarded. `write_mirror` can be
called with no side effect beyond the one file.

## The trap this design is built around

`items_with_folders(slug)` returns `[]` for an unknown project. `closed_names(slug)` falls back
to the shipped defaults for an unknown project. **Neither read distinguishes "no such project"
from "a project with zero items"** — both were written that way deliberately (an empty closed set
would make every finished item look open), and both are correct for their own callers.

For `sync` they are a trap: rendering straight from them would write a valid, empty mirror for
`trackden sync typo-slug`, creating a file for a project that does not exist.

`repository.get_project(slug)` returns `None` for an unknown slug and is the only read here that
tells the truth about existence. It must be the first gate. It also carries `project.name`, which
is the display name `render_tracker_md` wants as its first argument — so the existence check and
the name lookup are the same call, not two.

## Data flow

`sync(slug)` in order. Each gate catches something the gate before it cannot:

1. `repository.get_project(slug)` is `None` → `unknown_project`. **First**, per the trap above.
2. `workspace.project_dir(slug)` does not exist → `not_scaffolded`. A `ValueError` from the
   `_SAFE_SLUG` guard is caught here and reported the same way, as `delete` does. This gate sits
   **inside** the same `try` block as the write in step 5, not before it — see Error handling for
   why `.exists()` is itself a call that can raise.
3. The mirror exists and `tracker_md.is_generated(text)` is `False` → `hand_edited`. Nothing is
   written. A missing mirror is not hand-edited — it is simply absent, and gets written.
4. `render_tracker_md(project.name, repository.items_with_folders(slug), closed=repository.closed_names(slug))`
   → `workspace.write_mirror` → `synced`, reporting `items` and `path`.
5. An `OSError` from the write (permissions, a read-only volume, an over-long path component)
   → `write_failed`, carrying the reason string.

The slug is normalised once, at the CLI boundary, exactly as `delete` does it and for the same
reason: `repository` lowercases internally but `workspace._SAFE_SLUG` rejects uppercase outright,
so an un-normalised slug makes the two layers disagree about which project they are working on.

## Outcomes

Every one is a dict with a `status` key. `sync` never raises.

| `status` | Also carries | Means |
|---|---|---|
| `synced` | `items`, `path` | Written. `items: 0` is a legitimate success — an onboarded project with no items yet. |
| `unknown_project` | — | No such project in the DB. |
| `not_scaffolded` | — | In the DB, but no `~/.trackden/projects/<slug>/`. Points at `trackden onboard`. |
| `hand_edited` | `path` | A `_tracker.md` without the generated banner. Refused, not overwritten. |
| `write_failed` | `reason` | The render succeeded; the filesystem refused. |

## The CLI door

`trackden sync [project]` — a bare `sync` covers every project, following the `trackden eval`
precedent (`typer.Argument(None, help="...(default: all)")`). No `--all` flag; the codebase
already has a convention for this and a second one would be noise.

One line per project, so a single bad project cannot hide the ones that worked. **Exit non-zero
if any project returned anything but `synced`** — a partial success is still a failure for a
scripted run, and Stage A established that a write command reporting a failure must not exit 0.

```
$ trackden sync
✓ korpus        — mirror written (14 items)
! hinbunakurdi  — skipped: not a generated file, refusing to overwrite your edits
✓ resho-hub     — mirror written (0 items)
$ echo $?
1
```

Bare `sync` with no projects at all prints the same "No projects yet" guidance `trackden list`
gives, and exits 0 — nothing was asked for and nothing failed.

`sync` iterates `repository.list_projects()` (slugs) and calls `sync(slug)` per project, which
does its own `get_project`. That is one extra read per project. Deliberate: the count is
single-digit in every realistic case, and having one gate order that every caller shares is worth
more than saving a query.

## Auto-refresh — exactly two write paths

The mirror renders **items only**: title, status, folder grouping, and a `done / total` count.
Nothing else in the DB appears in it. So the set of writes that can change it is much smaller
than the set of writes:

| Write | Refresh? | Why |
|---|---|---|
| `add-item` / `add_item` | **yes** | A new line in the mirror, and `total` changes. |
| `set-status` / `set_status` | **yes** | The `[ ]`/`[x]` box, the `· parked` suffix, and `done` all change. |
| `add-folder` / `add_folder` | no | `groups` is built by iterating items, so a folder with no items renders nothing at all. |
| `add-status` / `add_status` | no | Adds a *name* to the vocabulary. No existing item can already hold a name that was just created. |
| `log` / `save_progress` | no | Session logs are not in the mirror. |
| `remember` / `add_memory` | no | Memory is not in the mirror. |
| `onboard` | no | Already writes the mirror as its last step. |
| `delete` | no | See Scope — deliberately out. |

**CLI:** warn on anything but `synced`, then **exit 0**. The DB write — the actual work —
succeeded. Failing the command because a derived file could not be rewritten would make a
cosmetic problem look like lost work.

```
$ trackden add-item korpus "ship sync"
✓ added item 42
! mirror not refreshed: permission denied
  run `trackden sync korpus` once that is fixed
$ echo $?
0
```

**MCP:** the tool's outcome dict gains a `mirror` key. Additive, the same way `overview` gained
`playbook` — no existing key changes name or meaning, so nothing that reads these tools today
breaks. `not_scaffolded` is the common case for an agent-only project and is not an error worth
shouting about.

A refresh runs **only after the underlying write reported success.** A failed `add_item` must not
touch the file.

## Error handling

- `sync` returns outcomes; it never raises. Consistent with the ~12 write functions already in
  the repo, and load-bearing here: the auto-refresh call sites run *after* a DB write has already
  committed, so an exception escaping `sync` would abort a command whose real work had already
  succeeded — the user would see a traceback and have no way to tell whether their item was saved.
- `write_mirror` is allowed to raise `OSError`; `sync` is the single place that catches it. Note
  `Path.exists()` itself raises `OSError` on an over-long path *component*, so the gate at step 2
  is inside the same `try` as the write, not before it.
- An auto-refresh failure can never turn a successful DB write into a failed command.

## Testing

Unit tests with a tmp `home`, one per outcome — `synced`, `unknown_project`, `not_scaffolded`,
`hand_edited`, `write_failed`. Plus:

- **`hand_edited` is the discriminating one.** Assert the file's original bytes are *unchanged*
  after the call, not merely that the status came back `hand_edited`. A test that only checks the
  status string passes against an implementation that returns the right status and overwrites the
  file anyway.
- **`unknown_project` must assert no file was created**, for the same reason — this is the trap
  gate, and the version of the bug it prevents is "a file appeared", not "a wrong string
  returned".
- **`synced` with zero items** — proves an empty mirror is a success, not an error.
- One `@pytest.mark.db` end-to-end: onboard a temp project, read the mirror, `add-item`, read it
  again, assert the file changed on disk. No fakes. This is the only test that proves auto-refresh
  is actually wired to a door rather than merely implemented.
- **Assert the two no-refresh paths do not write** — `log` on a project whose mirror is stale
  leaves it byte-identical. Otherwise "refresh only where it matters" is an unverified claim.

Every test gets §6.3's question asked of it: *would this fail if the code were wrong?* The check
is to break the implementation, watch the test fail, then restore it — not to reason about it.

## Success criteria — the walkthrough that must pass

```bash
trackden onboard …                 # mirror written, as today
trackden add-item <p> "new thing"  # exit 0; mirror now contains "new thing"
trackden set-status <p> <id> done  # mirror shows [x]; the done count went up
trackden sync <p>                  # ✓, idempotent — byte-identical on a second run
trackden sync typo-slug            # unknown project; exit 1; NO file created anywhere
trackden sync                      # every project, one line each
```

Idempotence matters: two `sync` runs with no DB change between them must produce identical bytes,
or the mirror will show spurious diffs in the `~/.trackden` git repo that `ensure_home_git`
maintains.

## Open, and deliberately next

- **Nothing here helps the `SessionStart` launcher.** `sync` makes the mirror true; it does not
  make anyone read it. That remains the one mechanical guarantee still unbuilt.
- **`projects.repo_path` stays unused.** A cwd→project resolution would let `trackden sync` with
  no argument mean "this repo" rather than "all projects". That is the launcher's design problem,
  not this one, and guessing at it now would prejudge it.
