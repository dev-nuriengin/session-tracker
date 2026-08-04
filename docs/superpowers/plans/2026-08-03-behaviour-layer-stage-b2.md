# Behaviour layer — Stage B2 (the hybrid file story) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a finding attach to the bug it belongs to instead of the whole project — item-scoped memory and logs, a `file` memory kind that points at a real file on disk without Trackden ever touching it, and `get_history(item_id=…)` to read one item's whole story back.

**Architecture:** Two nullable columns (`memory.path`, `session_logs.item_id`) via the existing idempotent-`ALTER` pattern. `add_memory` and `add_session_log` gain optional item/folder scoping, validate that a supplied id belongs to *this* project (the ownership rule B1 established), and move onto the outcome-dict shape their siblings use. `get_history` gains an optional `item_id` that narrows every part of its payload to one item. Trackden stores *where* a file is; it never creates, moves or reads one.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (sync, typed `Mapped[]`) · Postgres · FastMCP · Typer · pytest

**Spec:** `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` — the Stage B2 rows. The playbook, `get_playbook` and the `overview` digest are **B3 and out of scope here**.

## Global Constraints

- **No new dependencies.** Everything uses what `pyproject.toml` already declares.
- **Sync SQLAlchemy 2.0**, typed `Mapped[]` columns matching `models.py`.
- **Nobody opens a SQLAlchemy session except `repository.py`.** Test files may.
- **No exception may cross the MCP boundary.** Outcomes travel as a `status` string in a returned dict.
- **MCP tools and CLI commands are thin wrappers.** No business logic.
- **Trackden never touches the user's files.** It stores a path. It does not create, move, delete, or read the file at that path. This is the product's core promise about the user's folders being theirs.
- **Ownership, not existence.** Any caller-supplied `item_id`/`folder_id` must be validated against THIS project. A ForeignKey proves a row exists, never that it belongs here — B1 fixed exactly this in `create_folder` and `add_item`; the same rule applies here.
- **`create_all` never alters an existing table.** Every new column needs an `IF NOT EXISTS` line in `db.py`'s `_migrate()`. The onboarding branch shipped a bug for exactly this reason.
- **DB tests carry `@pytest.mark.db`.** `tests/conftest.py` hard-fails unless the resolved test database name ends in `_test` or `_smoke`; that guard protects six real user projects. Never weaken it.
- **Every CLI write command exits non-zero on failure.**
- **Run tests from `backend/`:** `cd backend && uv run pytest`
- **Baseline: 284 tests passing** at `2c1a3b2`. Report the actual count after every task.
- **Git:** personal account `dev-nuriengin`. Commit per task. **Never push** — the user says yes separately.

## A live bug this stage must fix

`add_session_log` (`repository.py:532`) resolves the session with:

```python
session = db.scalar(select(models.Session).where(models.Session.thread_id == thread_id))
```

**No project filter.** `Session` has a `project_id`, but the lookup ignores it. The CLI's `--thread` defaults to `"cli"` for every project, so:

```
trackden log project-a "note about A"     # creates session thread_id="cli" under project-a
trackden log project-b "note about B"     # FINDS project-a's session -> logs into project-a
```

The second note lands in the wrong project's history, and `get_history project-b` never shows it. This is the same cross-project family as the two bugs B1 fixed, it is on the default code path, and item scoping is meaningless while a log can attach to the wrong project entirely. Task 3 fixes it.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/models.py` | Schema. | `Memory.path`; `SessionLog.item_id`. |
| `backend/app/db.py` | Engine + idempotent migration. | Two `ALTER … IF NOT EXISTS` lines. |
| `backend/app/repository.py` | DB state. | `MEMORY_KINDS` gains `file`; `add_memory` gains `item_id`/`folder_id`/`path` + outcome dict; `add_session_log` gains `item_id`, a project-scoped session lookup, + outcome dict; `get_history` gains `item_id`; `list_memory` returns `path`; `_next_position` extracted. |
| `backend/app/cli.py` | Human door. | `remember` gains `--item`/`--folder`/`--path`; `log` gains `--item`; `show` gains `--item`. |
| `backend/app/mcp_server.py` | Agent door. | `add_memory`, `save_progress`, `get_history` gain the new parameters. No new tools. |
| `backend/tests/test_item_scoping.py` | **Create.** Item-scoped memory, logs, and history. |
| `backend/tests/test_file_kind.py` | **Create.** The `file` kind and path handling. |
| `backend/tests/test_migration_b2.py` | **Create.** The two columns reach an existing database. |

**Not touched:** `statuses.py`, `tracker_md.py`, `guidance.py`, `workspace.py`, `onboard.py`, `graph.py`, `eval.py`, `embeddings.py`, the frontend, Docker.

---

### Task 1: schema, migration, and one cleanup

**Files:**
- Modify: `backend/app/models.py` — `Memory`, `SessionLog`
- Modify: `backend/app/db.py` — `_migrate()`
- Modify: `backend/app/repository.py` — extract `_next_position`
- Test: `backend/tests/test_migration_b2.py` (**create**)

**Interfaces:**
- Produces: `models.Memory.path` (`String(500)`, nullable) · `models.SessionLog.item_id` (FK `tracking_items.id`, nullable, indexed) · `repository._next_position(db, model, project_id) -> int`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_b2.py`:

```python
"""The two B2 columns must reach a database that already has the tables.

`create_all` creates missing TABLES but never alters an existing one, so a column
added to a model would silently never arrive. The onboarding branch shipped exactly
that bug; this is the guard.
"""

import pytest

pytestmark = pytest.mark.db


def test_memory_has_a_path_column():
    from sqlalchemy import inspect

    from app.db import engine, init_db

    init_db()
    columns = {c["name"] for c in inspect(engine).get_columns("memory")}
    assert "path" in columns


def test_session_logs_has_an_item_id_column():
    from sqlalchemy import inspect

    from app.db import engine, init_db

    init_db()
    columns = {c["name"] for c in inspect(engine).get_columns("session_logs")}
    assert "item_id" in columns


def test_init_db_twice_keeps_a_stored_row(temp_slug):
    """Idempotency that proves DATA survives, not merely that the call does not raise.

    Uses the `note` kind, which already exists — the `file` kind arrives in Task 2, and
    a task must not end on a known failure.
    """
    from app import repository
    from app.db import init_db

    repository.create_project(temp_slug, name="Migration B2")
    repository.add_memory(temp_slug, "a finding", kind="note")
    init_db()
    init_db()
    assert [m["content"] for m in repository.list_memory(temp_slug)] == ["a finding"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_migration_b2.py -v`
Expected: FAIL — `path` and `item_id` are not columns yet. The third test may pass already
(it exercises only the existing `note` kind); that is fine, it is the idempotency guard.
If Postgres is down these SKIP, which is not a pass: `docker compose up -d db`.

- [ ] **Step 3: Add the columns**

In `backend/app/models.py`, add to `Memory` after the `url` column:

```python
    # Where a local artifact lives — a findings file, a meeting recording, an HTML dump.
    # A path is not a URL, so it gets its own column rather than overloading `url`:
    # one home per fact. Trackden stores this pointer and NEVER touches the file.
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

And to `SessionLog`, after `kind`:

```python
    # Which item this entry is about, when it is about one. Without this a log can
    # only attach to a whole project, so one bug's findings sit in a pile with every
    # other bug's. Nullable: plenty of progress is project-level.
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracking_items.id"), nullable=True, index=True
    )
```

Update the module docstring's schema sketch to mention that memory and session logs may be item-scoped.

- [ ] **Step 4: Add the migration lines**

In `backend/app/db.py`, extend `_migrate()`'s `statements` tuple:

```python
    statements = (
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_path VARCHAR(500)",
        "ALTER TABLE memory ADD COLUMN IF NOT EXISTS path VARCHAR(500)",
        "ALTER TABLE session_logs ADD COLUMN IF NOT EXISTS item_id INTEGER "
        "REFERENCES tracking_items(id)",
    )
```

- [ ] **Step 5: Extract `_next_position` (cleanup carried from B1)**

`create_folder` and `add_item` now hold near-duplicate three-line blocks computing the next
position. Extract one helper and call it from both:

```python
def _next_position(db, model, project_id: int) -> int:
    """One past the highest `position` in this project, or 0 when it is empty.

    An explicit `is None` check, not `or` — position 0 is falsy, so `max or 0` would
    collapse the second row back onto the first and reintroduce the queue-jumping bug
    this exists to prevent.
    """
    highest = db.scalar(
        select(func.max(model.position)).where(model.project_id == project_id)
    )
    return 0 if highest is None else highest + 1
```

Replace both inline blocks with `_next_position(db, models.Folder, project.id)` and
`_next_position(db, models.Item, project.id)`. Behaviour must not change — the existing
position tests in `tests/test_write_paths.py` are the proof.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/test_migration_b2.py tests/test_write_paths.py -v`
Expected: all three migration tests PASS, and every existing position test still passes —
the `_next_position` extraction must not change behaviour, and those tests are the proof.

- [ ] **Step 7: Whole suite**

Run: `cd backend && uv run pytest -q`
Expected: 284 + 3 new = **287 passed, zero failures**. Report the actual number. This task
must end fully green.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/models.py backend/app/db.py backend/app/repository.py backend/tests/test_migration_b2.py
git commit -m "feat(scope): add memory.path and session_logs.item_id

Two nullable columns, each with an IF NOT EXISTS line in _migrate — create_all
never alters an existing table, which is how the onboarding branch shipped a
column that silently never arrived.

A path is not a URL, so it gets its own column instead of overloading url: one
home per fact. session_logs.item_id is what lets a bug's findings stop sitting in
a pile with every other bug's.

Also extracts _next_position, the near-duplicate block B1's review flagged, with
the explicit is-None check that keeps position 0 from collapsing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: the `file` kind, and memory that attaches to an item

**Files:**
- Modify: `backend/app/repository.py` — `MEMORY_KINDS`, `add_memory`, `list_memory`
- Modify: `backend/app/cli.py` — `remember`
- Modify: `backend/app/mcp_server.py` — the `add_memory` tool
- Test: `backend/tests/test_file_kind.py` (**create**), and the deferred test from Task 1

**Interfaces:**
- Consumes: `models.Memory.path` (Task 1).
- Produces: `MEMORY_KINDS = frozenset({"link", "note", "transcript", "file"})` ·
  `repository.add_memory(slug, content, kind="note", title=None, url=None, path=None, item_id=None, folder_id=None) -> dict` returning
  `{"status": "saved"}` · `{"status": "saved", "warning": "path not found"}` ·
  `{"status": "missing_path"}` · `{"status": "rejected_kind", "valid": [...]}` ·
  `{"status": "unknown_item"}` · `{"status": "unknown_folder"}` · `{"status": "unknown_project"}`.
  `list_memory` gains `path` and `item_id` in each dict.

**Two deliberate decisions, and why:**

1. **`add_memory` stops raising `ValueError` and returns `rejected_kind` instead.** Today it
   raises, and both the MCP tool and the CLI catch it. That is the only write function still
   using exceptions for an expected outcome; moving it onto the dict shape makes all of them
   agree and removes two `try/except` blocks. The `decision` hint (pointing at `add_decision`)
   must survive — carry it in a `message` key.
2. **`kind="file"` requires `path`, but `kind="link"` is NOT newly made to require `url`.**
   The spec pairs them, but `trackden remember <p> "x" --kind link` without `--url` succeeds
   today and rows like that may already exist. Enforcing it now would break a working command
   and could reject existing data on a re-save. `file` is a brand-new kind with no callers, so
   requiring `path` costs nothing. Note this deviation in your report.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_file_kind.py`:

```python
"""The `file` memory kind: Trackden stores WHERE a thing is, and never touches it."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="File Kind")
    return temp_slug


def test_file_is_a_valid_kind(project, tmp_path):
    real = tmp_path / "findings.md"
    real.write_text("Safari only", encoding="utf-8")
    assert repository.add_memory(
        project, "First findings", kind="file", path=str(real)
    ) == {"status": "saved"}


def test_a_file_without_a_path_is_refused(project):
    assert repository.add_memory(project, "x", kind="file") == {"status": "missing_path"}


def test_a_missing_path_is_stored_with_a_warning(project, tmp_path):
    """Stored anyway: the user may be recording where something is ABOUT to go."""
    result = repository.add_memory(
        project, "not yet", kind="file", path=str(tmp_path / "later.md")
    )
    assert result["status"] == "saved"
    assert result["warning"] == "path not found"


def test_a_path_is_stored_absolute(project, tmp_path, monkeypatch):
    """A relative path must survive a different working directory."""
    real = tmp_path / "findings.md"
    real.write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    repository.add_memory(project, "rel", kind="file", path="findings.md")

    stored = [m for m in repository.list_memory(project) if m["kind"] == "file"][0]
    assert stored["path"] == str(real.resolve())


def test_a_tilde_path_is_expanded(project):
    result = repository.add_memory(project, "home", kind="file", path="~/nope-xyz.md")
    assert result["status"] == "saved"
    stored = [m for m in repository.list_memory(project) if m["kind"] == "file"][0]
    assert "~" not in stored["path"]


def test_trackden_never_creates_the_file(project, tmp_path):
    """The product promise: the user's folders are theirs."""
    target = tmp_path / "must-not-exist.md"
    repository.add_memory(project, "pointer only", kind="file", path=str(target))
    assert not target.exists()


def test_an_unsupported_kind_is_refused_without_raising(project):
    result = repository.add_memory(project, "x", kind="nonsense")
    assert result["status"] == "rejected_kind"
    assert "file" in result["valid"]


def test_a_decision_is_still_pointed_at_add_decision(project):
    """The hint that kept decisions out of the memory table must survive the reshape."""
    result = repository.add_memory(project, "we chose X", kind="decision")
    assert result["status"] == "rejected_kind"
    assert "add_decision" in result["message"]


def test_the_three_original_kinds_still_work(project):
    for kind in ("link", "note", "transcript"):
        assert repository.add_memory(project, f"a {kind}", kind=kind)["status"] == "saved"


def test_a_link_without_a_url_is_still_accepted(project):
    """Deliberately NOT newly enforced — it works today and rows like it may exist."""
    assert repository.add_memory(project, "bare link", kind="link")["status"] == "saved"
```

Then append the item-scoping half to the same file:

```python
# ---- item scoping ----

def test_memory_attaches_to_an_item(project):
    item_id = repository.add_item(project, "Fix the login redirect")["item_id"]
    assert repository.add_memory(project, "a finding", item_id=item_id)["status"] == "saved"
    stored = repository.list_memory(project)[0]
    assert stored["item_id"] == item_id


def test_memory_rejects_an_item_from_another_project(project, temp_slug_b):
    """Ownership, not existence — the rule B1 established for folders and items."""
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.add_memory(project, "mine", item_id=foreign) == {
        "status": "unknown_item"
    }


def test_memory_rejects_a_nonexistent_item(project):
    assert repository.add_memory(project, "x", item_id=999_999_999) == {
        "status": "unknown_item"
    }


def test_memory_rejects_a_folder_from_another_project(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Theirs")["folder_id"]
    assert repository.add_memory(project, "mine", folder_id=foreign) == {
        "status": "unknown_folder"
    }


def test_project_level_memory_still_works(project):
    """Most memory is not about one item; omitting item_id must stay valid."""
    assert repository.add_memory(project, "a project note")["status"] == "saved"
    assert repository.list_memory(project)[0]["item_id"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_file_kind.py -v`
Expected: FAIL — `ValueError` on `kind="file"`, `TypeError` on the new keyword arguments.

- [ ] **Step 3: Rewrite `MEMORY_KINDS` and `add_memory`**

```python
# `file` points at a local artifact — a findings file, a meeting recording, an HTML
# dump. Decisions remain deliberately absent: they belong in the project's
# `_decisions.md`, and the storage model routes by intent, so accepting one here
# would give an agent two homes for one datum.
MEMORY_KINDS = frozenset({"link", "note", "transcript", "file"})


def add_memory(slug: str, content: str, kind: str = "note", title: str | None = None,
               url: str | None = None, path: str | None = None,
               item_id: int | None = None, folder_id: int | None = None) -> dict:
    """Save a durable fact to a project's memory. Returns an outcome, never raises.

    Outcomes: saved (optionally with `warning`) · missing_path · rejected_kind (with
    `valid` and a `message`) · unknown_item · unknown_folder · unknown_project

    `item_id` scopes the fact to one item, so a bug's findings stop sitting in a pile
    with every other bug's. It is validated against THIS project: a ForeignKey proves
    a row exists, never that it belongs here.

    `kind="file"` requires `path` and stores it expanded and absolute, so the pointer
    survives a different working directory. A path that does not exist is stored WITH
    a warning rather than refused — the user may be recording where something is about
    to go. Trackden never creates, moves or reads the file.
    """
    if kind not in MEMORY_KINDS:
        hint = (
            " — use `add_decision`, which writes to the project's `_decisions.md`"
            if kind == "decision" else ""
        )
        return {
            "status": "rejected_kind",
            "valid": sorted(MEMORY_KINDS),
            "message": (
                f"unsupported memory kind {kind!r}; expected one of "
                f"{', '.join(sorted(MEMORY_KINDS))}{hint}"
            ),
        }
    if kind == "file" and not path:
        return {"status": "missing_path"}

    resolved = None
    warning = None
    if path:
        candidate = Path(path).expanduser()
        resolved = str(candidate.resolve())
        if not candidate.exists():
            warning = "path not found"

    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if item_id is not None:
            owned = db.scalar(
                select(models.Item).where(
                    models.Item.id == item_id, models.Item.project_id == project.id
                )
            )
            if owned is None:
                return {"status": "unknown_item"}

        if folder_id is not None:
            owned = db.scalar(
                select(models.Folder).where(
                    models.Folder.id == folder_id, models.Folder.project_id == project.id
                )
            )
            if owned is None:
                return {"status": "unknown_folder"}

        db.add(models.Memory(
            project_id=project.id, item_id=item_id, folder_id=folder_id,
            content=content, kind=kind, title=title, url=url, path=resolved,
        ))
        db.commit()
        return {"status": "saved", "warning": warning} if warning else {"status": "saved"}
```

`Path` is already imported at the top of `repository.py` (used by `_norm_path`) — confirm
rather than adding a second import.

- [ ] **Step 4: `list_memory` returns the new fields**

Add `path` and `item_id` to each dict it builds, so a reader can see where an artifact is
and which item it belongs to. Keep every existing key.

- [ ] **Step 5: Update the two callers that caught `ValueError`**

`add_memory` no longer raises, so the `try/except ValueError` in the CLI's `remember`
(`cli.py:219`) and in the MCP `add_memory` tool (`mcp_server.py:184`) is now dead code.
Replace both with outcome handling.

CLI `remember` — add the three flags and read the dict:

```python
@app.command()
def remember(
    project: str,
    content: str,
    kind: str = typer.Option("note", help="link | note | transcript | file"),
    url: str = typer.Option(None, help="Link (e.g. GitLab/GitHub)"),
    path: str = typer.Option(None, help="Local file path (required for --kind file)"),
    item: int = typer.Option(None, help="Attach to this item id"),
    folder: int = typer.Option(None, help="Attach to this folder id"),
    title: str = typer.Option(None),
):
    """Save a durable fact (link / note / transcript / file) to a project's memory.
    For a decision use `trackden decide`."""
    result = repository.add_memory(
        project, content, kind=kind, title=title, url=url,
        path=path, item_id=item, folder_id=folder,
    )
    outcome = result["status"]
    if outcome == "saved":
        typer.echo("✓ saved to memory")
        if result.get("warning"):
            typer.echo(f"  note: {result['warning']}")
        return
    if outcome == "rejected_kind":
        typer.echo(result["message"])
        raise typer.Exit(1)
    messages = {
        "missing_path": "--path is required for --kind file",
        "unknown_item": f"unknown item #{item} in '{project}'",
        "unknown_folder": f"unknown folder #{folder} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)
```

The MCP `add_memory` tool becomes a thin wrapper — delete its `try/except` and its manual
dict-building, pass the new parameters through, and extend its description to cover the
`file` kind, `path`, and `item_id` (say plainly: ask the user where a file goes, record the
path, never create or move anything; attach to the item when the fact is about one item).

- [ ] **Step 6: Add CLI and MCP tests**

Append to `backend/tests/test_cli.py` (module-level `runner`, `_no_schema(monkeypatch)` in
every test) tests covering: a `file` save printing the warning line when `warning` is set;
`--kind file` without `--path` exiting 1; `--item` with an unknown item exiting 1; and a
`rejected_kind` printing the `add_decision` hint. Append to `backend/tests/test_mcp_server.py`
a delegation test capturing `path` and `item_id` via a `seen` dict.

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest tests/test_file_kind.py tests/test_migration_b2.py tests/test_cli.py tests/test_mcp_server.py -v`
Expected: PASS, including Task 1's deferred `test_init_db_twice_keeps_a_stored_path`.

- [ ] **Step 8: Whole suite**

Run: `cd backend && uv run pytest -q`
Expected: no failures. Report the actual count. **Any pre-existing test that asserted
`add_memory` raises `ValueError` or returns a bool must be updated to the dict shape** — say
in your report which you changed and why.

- [ ] **Step 9: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/cli.py backend/app/mcp_server.py backend/tests/test_file_kind.py backend/tests/test_cli.py backend/tests/test_mcp_server.py
git commit -m "feat(scope): a finding can point at a file and attach to an item

add_memory gains the file kind, a path, and item/folder scoping. A path is stored
expanded and absolute so the pointer survives a different working directory, and a
path that does not exist is stored WITH a warning rather than refused — the user
may be recording where something is about to go. Trackden never creates, moves or
reads the file.

item_id and folder_id are validated against THIS project, the ownership rule B1
established: a ForeignKey proves a row exists, never that it belongs here.

add_memory also stops raising ValueError for an unsupported kind and returns
rejected_kind instead — it was the last write function using exceptions for an
expected outcome. The add_decision hint survives in the message key, so decisions
still have exactly one home.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: logs that attach to an item — and the cross-project session bug

**Files:**
- Modify: `backend/app/repository.py` — `add_session_log`
- Modify: `backend/app/cli.py` — `log`
- Modify: `backend/app/mcp_server.py` — `save_progress`
- Test: `backend/tests/test_item_scoping.py` (**create**)

**Interfaces:**
- Consumes: `models.SessionLog.item_id` (Task 1).
- Produces: `repository.add_session_log(slug, thread_id, content, kind="note", item_id=None) -> dict`
  returning `{"status": "saved"}` · `{"status": "unknown_item"}` · `{"status": "unknown_project"}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_item_scoping.py`:

```python
"""Session logs that attach to an item — and the session lookup that ignored the project."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Item Scoping")
    return temp_slug


def test_a_log_attaches_to_an_item(project):
    item_id = repository.add_item(project, "Fix the login redirect")["item_id"]
    assert repository.add_session_log(
        project, "t1", "Safari only, cookie SameSite", item_id=item_id
    ) == {"status": "saved"}


def test_a_log_rejects_an_item_from_another_project(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.add_session_log(project, "t1", "x", item_id=foreign) == {
        "status": "unknown_item"
    }


def test_a_project_level_log_still_works(project):
    assert repository.add_session_log(project, "t1", "general progress") == {"status": "saved"}


def test_an_unknown_project_is_reported(project):
    assert repository.add_session_log("no-such-project-xyz", "t1", "x") == {
        "status": "unknown_project"
    }


def test_two_projects_sharing_a_thread_id_keep_separate_logs(project, temp_slug_b):
    """THE BUG: the session lookup filtered on thread_id alone, ignoring the project.

    The CLI's --thread defaults to "cli" for every project, so
    `trackden log project-a "..."` then `trackden log project-b "..."` filed B's note
    into A's history, and `get_history project-b` never showed it.
    """
    repository.create_project(temp_slug_b, name="Other")

    repository.add_session_log(project, "cli", "note about A")
    repository.add_session_log(temp_slug_b, "cli", "note about B")

    a_logs = [entry["content"] for entry in repository.get_history(project)["recent_logs"]]
    b_logs = [entry["content"] for entry in repository.get_history(temp_slug_b)["recent_logs"]]

    assert "note about A" in a_logs
    assert "note about B" not in a_logs
    assert "note about B" in b_logs
    assert "note about A" not in b_logs
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_item_scoping.py -v`
Expected: FAIL — `TypeError` on `item_id`, bool-vs-dict mismatches, and
`test_two_projects_sharing_a_thread_id_keep_separate_logs` failing because B's note lands in
A's history. **Record that last failure's output verbatim in your report** — it is the proof
the bug was real.

- [ ] **Step 3: Rewrite `add_session_log`**

```python
def add_session_log(slug: str, thread_id: str, content: str, kind: str = "note",
                    item_id: int | None = None) -> dict:
    """Save a session log entry, creating the session on first use. Never raises.

    Outcomes: saved · unknown_item · unknown_project

    The session is looked up by thread_id AND project. It used to be thread_id alone,
    which meant two projects using the same thread id — and the CLI defaults every
    project to "cli" — shared one session, so a log filed into whichever project got
    there first and never appeared in the other's history.

    `item_id` scopes the entry to one item and is validated against THIS project.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if item_id is not None:
            owned = db.scalar(
                select(models.Item).where(
                    models.Item.id == item_id, models.Item.project_id == project.id
                )
            )
            if owned is None:
                return {"status": "unknown_item"}

        session = db.scalar(
            select(models.Session).where(
                models.Session.thread_id == thread_id,
                models.Session.project_id == project.id,
            )
        )
        if session is None:
            session = models.Session(project_id=project.id, thread_id=thread_id)
            db.add(session)
            db.flush()

        db.add(models.SessionLog(
            session_id=session.id, item_id=item_id, content=content,
            kind=kind, embedding=embed(content),
        ))
        db.commit()
        return {"status": "saved"}
```

- [ ] **Step 4: Update the two doors**

CLI `log` gains `--item` and reads the dict, exiting non-zero on failure with a `messages`
dict covering `unknown_item` and `unknown_project`. The MCP `save_progress` tool gains
`item_id`, returns the dict straight through, and its description gains one line telling the
agent to pass `item_id` when the progress is about one item. Both must stop treating the
return as a bool.

- [ ] **Step 5: Add CLI and MCP tests**

Append to `test_cli.py`: `log --item` with an unknown item exits 1; a successful log prints
its confirmation. Append to `test_mcp_server.py`: a `seen`-dict delegation test capturing
`item_id`.

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `cd backend && uv run pytest tests/test_item_scoping.py tests/test_cli.py tests/test_mcp_server.py -v`
then `cd backend && uv run pytest -q`. Any pre-existing test treating `add_session_log`'s
return as a bool must move to the dict shape — name them in your report.

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/cli.py backend/app/mcp_server.py backend/tests/test_item_scoping.py backend/tests/test_cli.py backend/tests/test_mcp_server.py
git commit -m "fix(scope): a session log belongs to one project, and can belong to one item

The session lookup filtered on thread_id ALONE, ignoring project_id. The CLI
defaults --thread to \"cli\" for every project, so logging to project-a and then
project-b filed B's note into A's session: it vanished from
\`get_history project-b\` and polluted A's history. On the default path, not an
edge case.

Also adds item_id, validated against THIS project, so a bug's findings stop
sitting in a pile with every other bug's, and moves the return onto the
outcome-dict shape its siblings use.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: read one item's whole story back

**Files:**
- Modify: `backend/app/repository.py` — `get_history`
- Modify: `backend/app/mcp_server.py` — the `get_history` tool
- Modify: `backend/app/cli.py` — `show` gains `--item`
- Test: `backend/tests/test_item_scoping.py` (extend)

**Interfaces:**
- Produces: `repository.get_history(slug, limit=10, item_id=None) -> dict`. With an
  `item_id`, every part of the payload narrows to that item: `open_items` holds just that
  item's title (or is empty when it is closed), `memory` only its memory, `recent_logs` only
  its logs. Adds `"item"` — the item's title and status — so a caller knows what it is
  looking at. Returns `{}` for an unknown project and `{"status": "unknown_item"}` when the
  item is not in this project.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_item_scoping.py`:

```python
# ---- get_history(item_id=...) ----

@pytest.fixture
def bug(project):
    """One bug with its own findings, beside an unrelated item with its own."""
    bug_id = repository.add_item(project, "BUG-431 login redirect loops")["item_id"]
    other_id = repository.add_item(project, "unrelated chore")["item_id"]

    repository.add_session_log(project, "t1", "reproduced on Safari", item_id=bug_id)
    repository.add_session_log(project, "t1", "cookie SameSite is the cause", item_id=bug_id)
    repository.add_session_log(project, "t1", "swept the logs", item_id=other_id)
    repository.add_session_log(project, "t1", "project-level note")

    repository.add_memory(project, "First findings", kind="file",
                          path="/tmp/trackden-b2-findings.md", item_id=bug_id)
    repository.add_memory(project, "unrelated link", kind="link", item_id=other_id)
    return project, bug_id, other_id


def test_item_history_holds_only_that_items_logs(bug):
    slug, bug_id, _ = bug
    contents = [e["content"] for e in repository.get_history(slug, item_id=bug_id)["recent_logs"]]
    assert "reproduced on Safari" in contents
    assert "cookie SameSite is the cause" in contents
    assert "swept the logs" not in contents
    assert "project-level note" not in contents


def test_item_history_holds_only_that_items_memory(bug):
    slug, bug_id, _ = bug
    memory = repository.get_history(slug, item_id=bug_id)["memory"]
    assert [m["content"] for m in memory] == ["First findings"]
    assert memory[0]["path"].endswith("trackden-b2-findings.md")


def test_item_history_names_the_item_it_is_about(bug):
    slug, bug_id, _ = bug
    payload = repository.get_history(slug, item_id=bug_id)
    assert payload["item"]["title"] == "BUG-431 login redirect loops"
    assert payload["item"]["status"] == "todo"


def test_project_history_is_unchanged_without_an_item_id(bug):
    slug, _, _ = bug
    contents = [e["content"] for e in repository.get_history(slug)["recent_logs"]]
    assert "project-level note" in contents
    assert "swept the logs" in contents


def test_item_history_rejects_an_item_from_another_project(bug, temp_slug_b):
    slug, _, _ = bug
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.get_history(slug, item_id=foreign) == {"status": "unknown_item"}


def test_a_closed_item_still_returns_its_history(bug):
    """Resuming a finished bug must still show what happened."""
    slug, bug_id, _ = bug
    repository.set_status(slug, bug_id, "done")
    payload = repository.get_history(slug, item_id=bug_id)
    assert payload["item"]["status"] == "done"
    assert len(payload["recent_logs"]) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_item_scoping.py -v -k "item_history or closed_item"`
Expected: FAIL — `TypeError` on `item_id`.

- [ ] **Step 3: Rewrite `get_history`**

Keep the existing project-level behaviour byte-for-byte when `item_id is None`. When it is
given: validate ownership, then narrow `open_items`, `memory` and `recent_logs` to that item
and add the `item` block. Note that the item-scoped `memory` needs a query filtered on
`item_id` rather than `list_memory(slug)`, which is project-wide.

- [ ] **Step 4: Update the two doors**

The MCP `get_history` tool gains `item_id` with a description line saying: pass it when
resuming work on one specific item to get that item's whole story — its logs, its files, its
status — instead of the project's last N entries. The CLI's `show` gains
`--item <id>`, printing the item block, its memory (including paths) and its logs.

- [ ] **Step 5: Tests, then the whole suite**

Run the item-scoping file, `test_cli.py` and `test_mcp_server.py`, then
`cd backend && uv run pytest -q`. Report the count.

- [ ] **Step 6: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/mcp_server.py backend/app/cli.py backend/tests/test_item_scoping.py backend/tests/test_cli.py backend/tests/test_mcp_server.py
git commit -m "feat(scope): get_history(item_id=...) reads one item's whole story

Without a read side, B2 would have shipped the ability to attach findings to a
bug and no way to get them back. With an item_id the payload narrows to that
item — its logs, its memory with file paths, its current status — instead of the
project's last N entries, which is what a session resuming a specific bug
actually needs. Project-level behaviour is unchanged when item_id is omitted.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: docs, and an end-to-end run against the real database

**Files:**
- Modify: `_tracker.md`, `QUICKSTART.md`, the spec's staging table

- [ ] **Step 1: Walk the whole scenario by hand**

This is the scenario the stage exists for. Run it against the real database with a throwaway
project, and paste the verbatim terminal output into your report:

```bash
cd backend
uv run trackden add-project b2-smoke --name "B2 smoke"
uv run trackden add-item b2-smoke "BUG-431 login redirect loops"     # note the id
uv run trackden set-status b2-smoke <id> doing
mkdir -p /tmp/b2-smoke && echo "Safari only" > /tmp/b2-smoke/findings.md
uv run trackden remember b2-smoke "First findings" --kind file --path /tmp/b2-smoke/findings.md --item <id>
uv run trackden log b2-smoke "Reproduced on Safari, not Chrome" --item <id>
uv run trackden remember b2-smoke "vendor must patch first" --kind note --item <id>
uv run trackden add-status b2-smoke parked --behaves-as waiting
uv run trackden set-status b2-smoke <id> parked
uv run trackden show b2-smoke --item <id>        # the whole story of one bug
uv run trackden status b2-smoke                  # parked, not offered as NEXT
uv run trackden remember b2-smoke "x" --kind file --path /tmp/b2-smoke/nope.md   # warning, still saved
uv run trackden remember b2-smoke "x" --kind file ; echo "exit=$?"               # exit=1
```

Confirm: the file path came back absolute; `show --item` showed only that bug's logs and
memory; `status` reported the waiting count without offering the parked bug; the missing path
saved with a warning; and `--kind file` without `--path` exited 1.

Then clean up. **A single `DELETE FROM projects` fails on foreign keys** — the cascade is
ORM-level only, there is no `ON DELETE CASCADE` — so delete through the ORM:

```bash
cd backend && uv run python -c "
from sqlalchemy import select
from app import models
from app.db import SessionLocal
with SessionLocal() as db:
    p = db.scalar(select(models.Project).where(models.Project.slug == 'b2-smoke'))
    if p: db.delete(p); db.commit()
    print('deleted' if p else 'not found')
"
```

Confirm it printed `deleted`, and remove `/tmp/b2-smoke`.

- [ ] **Step 2: Update the docs**

- `_tracker.md`: add the new flags (`remember --kind file --path --item --folder`,
  `log --item`, `show --item`) to the command table; note that `add_memory`,
  `save_progress` and `get_history` now take item scoping over MCP; remove the claim that a
  finding attaches only to the whole project; tick B2's items and leave B3's open; recount
  the checkboxes with `grep -cE '^\s*-\s*\[x\]' _tracker.md` and the `[ ]` equivalent,
  reporting both raw numbers; update the test count from a real run.
- Record the session-lookup bug and its fix in the notes — it is the kind of thing worth
  remembering, and anyone with two projects and `trackden log` has already hit it.
- `QUICKSTART.md`: it holds the only genuine MCP tool table (README.md and AGENTS.md do NOT
  — verified previously; do not invent one there). Note the new parameters.
- The spec's staging table: mark B2 delivered, leave B3.

- [ ] **Step 3: Whole suite, then commit**

Run `cd backend && uv run pytest -q` and report the count.

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add _tracker.md QUICKSTART.md docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md
git commit -m "docs: Stage B2 shipped — a finding belongs to the bug it came from

Removes the claim that memory attaches only to the whole project, and records the
session-lookup bug: logs filed by thread_id alone, so two projects sharing the
default \"cli\" thread crossed over. Anyone using trackden log on two projects had
already hit it.

Still open: B3 (the playbook, get_playbook, the overview digest, the onboard
paste-snippet) and the SessionStart launcher, which is the only mechanical
guarantee an agent reads any of this.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage (B2 rows):**

| Requirement | Task |
|---|---|
| `memory.path` column | 1 |
| `session_logs.item_id` column | 1 |
| Idempotent `ALTER` for both | 1 |
| `file` memory kind | 2 |
| Path expanded, absolute, stored-with-warning if missing | 2 |
| Trackden never touches the file | 2 (asserted by test) |
| `memory.item_id`/`folder_id` wired through | 2 |
| `session_logs.item_id` wired through | 3 |
| `get_history(item_id=…)` | 4 |
| CLI `--item` / `--path` | 2, 3, 4 |
| Ownership validation on every caller-supplied id | 2, 3, 4 |

**Beyond the spec, deliberately:** the cross-project session-lookup bug (Task 3) — found
while reading the code, on the default path, and item scoping is meaningless while a log can
attach to the wrong project. `add_memory` moving off `ValueError` onto the outcome dict
(Task 2) — it was the last write function using exceptions for an expected outcome.
`_next_position` extraction (Task 1) — a deferred minor from B1, and Task 1 is already in
that file.

**Deliberately NOT done:** `kind="link"` is not newly required to carry a `url` (would break
a working command and possibly existing rows); `search_logs` does not gain `item_id` in its
results; B3's playbook work.

**Placeholder scan:** none. Task 3 Step 4 and Task 4 Steps 3-4 describe edits by rule rather
than quoting every line, because each is a mechanical repeat of a pattern shown in full
earlier in the same plan; both name the exact file, function and shape to match.

**Type consistency:** `add_memory` and `add_session_log` both return `dict` with a `status`
key, matching the eight functions already on that shape. `item_id` is the parameter name
everywhere — repository, CLI flag `--item`, MCP parameter. `path` likewise. `get_history`
returns `{}` for an unknown project (unchanged) but `{"status": "unknown_item"}` for a bad
item — an asymmetry inherited from its existing contract, called out here so it is a decision
rather than an accident.
