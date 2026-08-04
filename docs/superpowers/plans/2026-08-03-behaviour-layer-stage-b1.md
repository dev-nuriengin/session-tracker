# Behaviour layer — Stage B1 (write-side MCP tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent create work in Trackden — `add_item`, `add_folder` and `add_status` over MCP — after hardening those write paths so no exception can cross the tool boundary and no item can land in another project's folder.

**Architecture:** All three repository write functions are normalised onto the outcome-dict shape the read/write layer already uses (`{"status": "<outcome>", …payload}`), gaining the validation they lack: `add_status` closes a check-then-insert race, `create_folder` and `add_item` validate that a supplied `parent_id`/`folder_id` belongs to *this* project. Only then are they exposed as three thin MCP tools. The CLI's two existing commands move to the new shapes and gain the flags the MCP tools expose, so neither door is weaker than the other.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (sync, typed `Mapped[]`) · Postgres · FastMCP · Typer · pytest

**Spec:** `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` — the Stage B rows for `add_item`, `add_folder` and the MCP `add_status` tool. Everything else in Stage B (the playbook, the `file` memory kind, item scoping, `get_history(item_id=…)`) belongs to plans B2 and B3 and is **out of scope here**.

## Global Constraints

- **No new dependencies.** Everything uses what `pyproject.toml` already declares.
- **Sync SQLAlchemy 2.0 only**, typed `Mapped[]` columns, matching `models.py`.
- **Nobody opens a SQLAlchemy session except `repository.py`.** Test files may (`conftest.py` already does).
- **No exception may cross the MCP boundary.** Every outcome travels as a `status` string inside a returned dict — the pattern `guidance.py`, `set_status` and `add_status` already established. This plan's entire reason for existing is that three write paths currently violate it.
- **MCP tools and CLI commands are thin wrappers.** No business logic, no session handling, no validation of their own. If a tool needs to enrich a result, that enrichment belongs in `repository.py`.
- **Every CLI write command exits non-zero on failure.**
- **Trackden never gates work.** No transition state machine, no approval flow. It records; the user decides.
- **The shipped default status names are always valid**; `item_statuses` rows are additions that can never invalidate `todo` or `done`.
- **A queue query offers anything not `waiting` and not `closed`** — including a status in no vocabulary, deliberately, so it surfaces. Do not reintroduce a positive allowlist.
- **DB tests carry `@pytest.mark.db`.** `tests/conftest.py` hard-fails unless the resolved test database name ends in `_test` or `_smoke`; that guard protects six real user projects. Never weaken it.
- **Run tests from `backend/`:** `cd backend && uv run pytest`
- **Baseline: 242 tests passing** at `9547fc5`. Report the actual count after every task.
- **Git:** personal account `dev-nuriengin` (already configured). Commit per task. **Never push** — the user says yes separately.

## The outcome-dict shape

Five functions already return it. This plan brings the last three onto it, so all eight agree:

| Function | Returns |
|---|---|
| `set_status` | `set`+`from`/`to` · `unchanged`+`from`/`to` · `unknown_status`+`valid` · `unknown_item` · `unknown_project` |
| `guidance.get` / `add_decision` | `filled` · `template` · `not_scaffolded` · `appended` · `unknown_*` · `invalid_slug` |
| `add_memory` (MCP layer) | `saved` · `unknown_project` · `rejected_kind` |
| **`add_status`** *(this plan)* | `added` · `duplicate_name` · `unknown_class`+`valid` · `invalid_name` · `unknown_project` |
| **`create_folder`** *(this plan)* | `added`+`folder_id` · `unknown_project` · `unknown_parent` |
| **`add_item`** *(this plan)* | `added`+`item_id` · `unknown_project` · `unknown_folder` · `unknown_status`+`valid` |

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/repository.py` | DB state. | `add_status` gains a race guard and returns a dict; `create_folder` and `add_item` gain FK-ownership validation and return dicts; `add_item` gains an optional `status`. |
| `backend/app/cli.py` | Human door. Thin Typer commands. | `add-status`, `add-folder`, `add-item` move to the dict shape; `add-folder` gains `--parent`, `add-item` gains `--status`. |
| `backend/app/mcp_server.py` | Agent door. Thin wrappers. | Three new tools (13 → 16). |
| `backend/tests/test_write_paths.py` | **Create.** The FK-ownership and race tests. |
| `backend/tests/test_statuses_db.py` | Existing `add_status` assertions move to the dict shape. |
| `backend/tests/test_repository_onboard.py` | One `create_folder` call site (line 97). |
| `backend/tests/test_set_status.py`, `test_open_semantics.py` | Five `add_item` call sites. |
| `backend/tests/test_cli.py`, `test_mcp_server.py` | New command/tool tests. |

**Not touched:** `statuses.py`, `models.py` (no schema change in B1), `db.py`, `tracker_md.py`, `guidance.py`, `workspace.py`, `onboard.py`, `graph.py`, `eval.py`, the frontend, Docker.

## Why the hardening comes first, in one paragraph

`create_folder` and `add_item` accept a `parent_id`/`folder_id` and pass it straight into a `ForeignKey` column without checking it. Two consequences, both currently reachable: a nonexistent id raises a raw `IntegrityError` — `trackden add-item acme "x" --folder 999` is a traceback today — and an id belonging to a **different project** is accepted silently, filing an item into another project's folder. The FK only proves the row exists, never that it belongs here. Exposed as MCP tools, the first becomes an exception crossing the boundary and the second becomes silent cross-project contamination that no error message would ever reveal. `add_status` has the third variant: a check-then-insert race whose `IntegrityError` would surface the same way.

---

### Task 1: `add_status` — close the race, return a dict

**Files:**
- Modify: `backend/app/repository.py` — `add_status` (currently line 325)
- Modify: `backend/app/cli.py` — the `add-status` command (currently line 152)
- Modify: `backend/tests/test_statuses_db.py` — existing assertions move to the dict shape
- Modify: `backend/tests/test_cli.py` — the two `add-status` tests
- Test: `backend/tests/test_write_paths.py` (**create**)

**Interfaces:**
- Consumes: `repository._vocabulary(db, project_id)` (takes an already-open session), `statuses.CLASSES`, `MAX_STATUS_NAME`.
- Produces: `repository.add_status(slug, name, behaves_as) -> dict` returning `{"status": "added"}` · `{"status": "duplicate_name"}` · `{"status": "unknown_class", "valid": ["active","closed","open","waiting"]}` · `{"status": "invalid_name"}` · `{"status": "unknown_project"}`. The `valid` list is sorted, so it is stable to assert.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_write_paths.py`:

```python
"""The write paths, hardened before they are exposed over MCP.

Each test here pins a way an exception could otherwise escape a function whose
docstring promises an outcome — which, across the MCP boundary, means a traceback
reaching an agent instead of a `status` string it can act on.
"""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Write Paths")
    return temp_slug


# ---- add_status ----

def test_add_status_reports_added_as_a_dict(project):
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}


def test_add_status_reports_duplicate_as_a_dict(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.add_status(project, "parked", "waiting") == {"status": "duplicate_name"}


def test_add_status_hands_back_the_valid_classes(project):
    result = repository.add_status(project, "sideways", "diagonal")
    assert result["status"] == "unknown_class"
    assert result["valid"] == ["active", "closed", "open", "waiting"]


def test_add_status_reports_a_blank_name_as_a_dict(project):
    assert repository.add_status(project, "   ", "waiting") == {"status": "invalid_name"}


def test_add_status_reports_an_unknown_project_as_a_dict():
    assert repository.add_status("no-such-project-xyz", "parked", "waiting") == {
        "status": "unknown_project"
    }


def test_a_lost_race_still_reports_duplicate_name(project, monkeypatch):
    """Simulate the check-then-insert window: the pre-check passes, the insert collides.

    `add_status` checks the vocabulary and then inserts. Two concurrent callers can
    both pass the check, and the second insert then violates the UniqueConstraint.
    Here the window is forced deterministically by making the check blind to a name
    that really is present. Without the guard this raises IntegrityError — which,
    over MCP, is a traceback rather than an outcome.
    """
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}

    real_vocabulary = repository._vocabulary

    def blind_to_parked(db, project_id):
        vocabulary = dict(real_vocabulary(db, project_id))
        vocabulary.pop("parked", None)  # pretend the pre-check has not seen it
        return vocabulary

    monkeypatch.setattr(repository, "_vocabulary", blind_to_parked)

    assert repository.add_status(project, "parked", "waiting") == {"status": "duplicate_name"}


def test_the_session_is_usable_after_a_lost_race(project, monkeypatch):
    """The rollback must leave the database working, not a poisoned transaction."""
    repository.add_status(project, "parked", "waiting")
    real_vocabulary = repository._vocabulary
    monkeypatch.setattr(
        repository,
        "_vocabulary",
        lambda db, pid: {k: v for k, v in real_vocabulary(db, pid).items() if k != "parked"},
    )
    repository.add_status(project, "parked", "waiting")  # loses the race
    monkeypatch.undo()

    # a normal write still succeeds afterwards
    assert repository.add_status(project, "postponed", "waiting") == {"status": "added"}
    names = [row["name"] for row in repository.list_statuses(project)]
    assert "postponed" in names
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_write_paths.py -v`
Expected: FAIL — the dict tests fail with `AssertionError: 'added' == {'status': 'added'}` (a bare string is returned today); the two race tests fail with `sqlalchemy.exc.IntegrityError`.
If Postgres is down the tests SKIP, which is not a pass — start it with `docker compose up -d db`.

- [ ] **Step 3: Rewrite `add_status`**

In `backend/app/repository.py`, add the exception import to the SQLAlchemy import at the top of the file (it currently imports `func, select` from `sqlalchemy`; `IntegrityError` lives in `sqlalchemy.exc`, so add a separate line beside it):

```python
from sqlalchemy.exc import IntegrityError
```

Then replace `add_status` entirely:

```python
def add_status(slug: str, name: str, behaves_as: str) -> dict:
    """Add one extra status name to a project. Returns an outcome, never raises.

    Outcomes: added · duplicate_name · unknown_class (with `valid`) · invalid_name ·
    unknown_project. `invalid_name` covers both a blank name and one longer than the
    column allows (MAX_STATUS_NAME) — an unvalidated long name would otherwise reach
    Postgres as a raw DataError instead of a reported outcome.

    The duplicate check is belt AND braces: the pre-check gives a clean outcome in the
    normal case, and the UniqueConstraint catches the check-then-insert race two
    concurrent writers can lose. Both report `duplicate_name`, so a caller sees one
    behaviour and never an IntegrityError — which over MCP would be a traceback.
    """
    name = name.strip().lower()
    if not name or len(name) > MAX_STATUS_NAME:
        return {"status": "invalid_name"}
    if behaves_as not in st.CLASSES:
        return {"status": "unknown_class", "valid": sorted(st.CLASSES)}
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}
        if name in _vocabulary(db, project.id):
            # covers both "already a shipped default" and "already added here"
            return {"status": "duplicate_name"}
        db.add(models.ItemStatus(project_id=project.id, name=name, behaves_as=behaves_as))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # leave the session usable, not a poisoned transaction
            return {"status": "duplicate_name"}
        return {"status": "added"}
```

- [ ] **Step 4: Move the existing `add_status` assertions to the dict shape**

`backend/tests/test_statuses_db.py` asserts bare strings in several places, e.g.
`assert repository.add_status(project, "parked", "waiting") == "added"`. Read the file and
update every `add_status` assertion to the dict shape. Two rules:

- An equality on `"added"` / `"duplicate_name"` / `"invalid_name"` / `"unknown_project"`
  becomes an equality on `{"status": "<same>"}`.
- The `unknown_class` assertion becomes `["status"] == "unknown_class"` (it now carries
  `valid` too, so a whole-dict equality would need that key as well).

Calls made for their side effect only — `repository.add_status(project, "dropped", "closed")`
with no assertion — need no change.

- [ ] **Step 5: Move the CLI's `add-status` command to the dict shape**

In `backend/app/cli.py`, the `add-status` command currently reads `outcome = repository.add_status(...)`
and indexes a `messages` dict with that string. Change it to read the dict, and use the
`valid` list the repository now returns instead of a hardcoded class list:

```python
@app.command("add-status")
def add_status(
    project: str,
    name: str,
    behaves_as: str = typer.Option(..., "--behaves-as", help="open | active | waiting | closed"),
):
    """Add a status name to a project. The four shipped names always stay valid."""
    result = repository.add_status(project, name, behaves_as)
    outcome = result["status"]
    if outcome == "added":
        typer.echo(f"✓ '{name}' added to {project} (behaves as {behaves_as})")
        return
    if outcome == "unknown_class":
        typer.echo(f"unknown class '{behaves_as}'. valid: {', '.join(result['valid'])}")
        raise typer.Exit(1)
    messages = {
        "duplicate_name": f"'{name}' is already a status in {project}",
        "invalid_name": (
            f"a status name cannot be blank or longer than "
            f"{repository.MAX_STATUS_NAME} characters"
        ),
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)
```

Then update the two `add-status` tests in `backend/tests/test_cli.py`, whose fakes currently
return bare strings — e.g. `lambda *a, **k: "added"` becomes `lambda *a, **k: {"status": "added"}`.
Keep every existing `_no_schema(monkeypatch)` call and the module-level `runner`.

- [ ] **Step 6: Run the affected tests**

Run: `cd backend && uv run pytest tests/test_write_paths.py tests/test_statuses_db.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: 242 + 7 new = **249 passed**. Report the actual number.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/cli.py backend/tests/test_write_paths.py backend/tests/test_statuses_db.py backend/tests/test_cli.py
git commit -m "fix(write): add_status returns an outcome dict and survives a lost race

Belt and braces on the duplicate check: the pre-check still gives a clean
outcome, and the UniqueConstraint now catches the check-then-insert window two
concurrent writers can lose, rolling back so the session stays usable. Both
paths report duplicate_name.

This matters because add_status is about to be an MCP tool, and an IntegrityError
crossing that boundary is a traceback reaching an agent instead of an outcome it
can act on. Same reason the return moves to the outcome-dict shape the other
write functions already use — and unknown_class now carries the valid classes,
so the CLI stops hardcoding them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `create_folder` — a parent must belong to this project

**Files:**
- Modify: `backend/app/repository.py` — `create_folder` (currently line 259)
- Modify: `backend/app/cli.py` — the `add-folder` command (currently line 112)
- Modify: `backend/tests/test_repository_onboard.py:97` — one call site
- Modify: `backend/tests/test_write_paths.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `repository.create_folder(slug, name, parent_id=None) -> dict` returning
  `{"status": "added", "folder_id": int}` · `{"status": "unknown_parent"}` · `{"status": "unknown_project"}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_write_paths.py`:

```python
# ---- create_folder ----

def test_create_folder_returns_the_new_id(project):
    result = repository.create_folder(project, "Bugs")
    assert result["status"] == "added"
    assert isinstance(result["folder_id"], int)


def test_create_folder_nests_under_a_parent_in_the_same_project(project):
    parent = repository.create_folder(project, "Bugs")["folder_id"]
    child = repository.create_folder(project, "Login", parent_id=parent)
    assert child["status"] == "added"


def test_create_folder_rejects_a_nonexistent_parent(project):
    """Unvalidated, this reached Postgres as a raw IntegrityError."""
    assert repository.create_folder(project, "Orphan", parent_id=999_999_999) == {
        "status": "unknown_parent"
    }


def test_create_folder_rejects_a_parent_from_another_project(project, temp_slug_b):
    """The FK proves the row EXISTS, never that it belongs here.

    Unvalidated, this silently nested a folder inside another project's tree —
    worse than a crash, because no error would ever reveal it.
    """
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Their Folder")["folder_id"]
    assert repository.create_folder(project, "Mine", parent_id=foreign) == {
        "status": "unknown_parent"
    }


def test_create_folder_reports_an_unknown_project():
    assert repository.create_folder("no-such-project-xyz", "Bugs") == {
        "status": "unknown_project"
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_write_paths.py -v -k create_folder`
Expected: FAIL — `test_create_folder_returns_the_new_id` fails because an `int` is returned
today, and the two rejection tests fail with `IntegrityError` / by wrongly succeeding.

- [ ] **Step 3: Rewrite `create_folder`**

```python
def create_folder(slug: str, name: str, parent_id: int | None = None) -> dict:
    """Create a folder in a project. Returns an outcome, never raises.

    Outcomes: added (with `folder_id`) · unknown_parent · unknown_project

    `parent_id` is validated against THIS project. The ForeignKey alone only proves
    the row exists, not that it belongs here, so without this check a caller could
    nest a folder inside another project's tree — silently, with no error to reveal it.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}
        if parent_id is not None:
            parent = db.scalar(
                select(models.Folder).where(
                    models.Folder.id == parent_id,
                    models.Folder.project_id == project.id,
                )
            )
            if parent is None:
                return {"status": "unknown_parent"}
        folder = models.Folder(project_id=project.id, name=name, parent_id=parent_id)
        db.add(folder)
        db.commit()
        return {"status": "added", "folder_id": folder.id}
```

- [ ] **Step 4: Update the one existing call site**

`backend/tests/test_repository_onboard.py:97` reads:

```python
    existing_id = repository.create_folder(temp_slug, "Phase 0")
```

It needs the id out of the dict:

```python
    existing_id = repository.create_folder(temp_slug, "Phase 0")["folder_id"]
```

- [ ] **Step 5: Move the CLI's `add-folder` command, and give it `--parent`**

The MCP tool will expose `parent_id`, so leaving the CLI unable to nest would make the
human door weaker than the agent's. In `backend/app/cli.py`:

```python
@app.command("add-folder")
def add_folder(
    project: str,
    name: str,
    parent: int = typer.Option(None, help="Parent folder id (nest inside it)"),
):
    """Add a folder to a project, optionally nested inside another folder."""
    result = repository.create_folder(project, name, parent_id=parent)
    if result["status"] == "added":
        typer.echo(f"✓ folder #{result['folder_id']} added to {project}")
        return
    messages = {
        "unknown_parent": f"unknown parent folder #{parent} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[result["status"]])
    raise typer.Exit(1)
```

Then in `backend/tests/test_cli.py`, update the existing
`test_add_folder_exits_non_zero_for_an_unknown_project` — its fake returns `None` today and
must return `{"status": "unknown_project"}` — and add two tests:

```python
def test_add_folder_reports_the_new_id(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "added", "folder_id": 7}
    )
    result = runner.invoke(cli_mod.app, ["add-folder", "acme", "Bugs"])
    assert result.exit_code == 0, result.output
    assert "#7" in result.output


def test_add_folder_exits_non_zero_for_an_unknown_parent(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "unknown_parent"}
    )
    result = runner.invoke(cli_mod.app, ["add-folder", "acme", "Bugs", "--parent", "999"])
    assert result.exit_code == 1
    assert "999" in result.output
```

- [ ] **Step 6: Run the affected tests**

Run: `cd backend && uv run pytest tests/test_write_paths.py tests/test_repository_onboard.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: 249 + 5 new + 2 new CLI = **256 passed**. Report the actual number.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/cli.py backend/tests/test_write_paths.py backend/tests/test_repository_onboard.py backend/tests/test_cli.py
git commit -m "fix(write): a folder's parent must belong to the same project

create_folder passed parent_id straight into a ForeignKey column. The FK proves
the row exists, never that it belongs here, so a parent id from another project
was accepted and the folder silently nested inside that project's tree — worse
than a crash, since nothing would ever surface it. A nonexistent id was a raw
IntegrityError.

Returns the outcome-dict shape now, and the CLI gains --parent so the human door
is not weaker than the MCP tool about to expose the same argument.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `add_item` — a folder must belong to this project, and a status must be valid

**Files:**
- Modify: `backend/app/repository.py` — `add_item` (currently line 270)
- Modify: `backend/app/cli.py` — the `add-item` command (currently line 122)
- Modify: 5 call sites — `backend/tests/test_set_status.py:13`, `backend/tests/test_open_semantics.py:23, 81, 142, 162`
- Modify: `backend/tests/test_write_paths.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `repository._vocabulary(db, project_id)`, `statuses.TODO`.
- Produces: `repository.add_item(slug, title, folder_id=None, status=None) -> dict` returning
  `{"status": "added", "item_id": int}` · `{"status": "unknown_folder"}` ·
  `{"status": "unknown_status", "valid": [...]}` · `{"status": "unknown_project"}`.
  `status=None` means the shipped default `todo`.

**One naming collision to be aware of, and to leave alone:** the parameter `status` is the
item's status, while the returned `status` key is the *outcome*. Two senses of one word. The
outcome-dict shape is used by eight functions and the domain word for an item's state is
`status`, so both stay — the docstring must call the ambiguity out explicitly so the next
reader is not caught by it. Do not rename either to avoid it.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_write_paths.py`:

```python
# ---- add_item ----

def test_add_item_returns_the_new_id(project):
    result = repository.add_item(project, "Fix the login redirect loop")
    assert result["status"] == "added"
    assert isinstance(result["item_id"], int)


def test_add_item_defaults_to_todo(project):
    item_id = repository.add_item(project, "untouched")["item_id"]
    stored = [i for i in repository.list_items(project) if i["id"] == item_id][0]
    assert stored["status"] == "todo"


def test_add_item_accepts_a_starting_status(project):
    item_id = repository.add_item(project, "already going", status="doing")["item_id"]
    stored = [i for i in repository.list_items(project) if i["id"] == item_id][0]
    assert stored["status"] == "doing"


def test_add_item_accepts_a_status_the_project_added(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.add_item(project, "on hold", status="parked")["status"] == "added"


def test_add_item_rejects_an_unknown_status_and_hands_back_the_valid_set(project):
    result = repository.add_item(project, "bad", status="nonsense")
    assert result["status"] == "unknown_status"
    assert result["valid"] == ["todo", "doing", "blocked", "done"]


def test_add_item_files_into_a_folder_of_the_same_project(project):
    folder_id = repository.create_folder(project, "Bugs")["folder_id"]
    result = repository.add_item(project, "in a folder", folder_id=folder_id)
    assert result["status"] == "added"


def test_add_item_rejects_a_nonexistent_folder(project):
    """Unvalidated, this reached Postgres as a raw IntegrityError.

    `trackden add-item <p> "x" --folder 999` was a traceback before this change.
    """
    assert repository.add_item(project, "orphan", folder_id=999_999_999) == {
        "status": "unknown_folder"
    }


def test_add_item_rejects_a_folder_from_another_project(project, temp_slug_b):
    """The FK proves the row EXISTS, never that it belongs here.

    Unvalidated, the item was filed into another project's folder silently.
    """
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Their Folder")["folder_id"]
    assert repository.add_item(project, "mine", folder_id=foreign) == {
        "status": "unknown_folder"
    }


def test_add_item_reports_an_unknown_project():
    assert repository.add_item("no-such-project-xyz", "x") == {"status": "unknown_project"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_write_paths.py -v -k add_item`
Expected: FAIL — an `int` is returned today, `status` is not a parameter (`TypeError`), and
the two folder-rejection tests fail with `IntegrityError` / by wrongly succeeding.

- [ ] **Step 3: Rewrite `add_item`**

```python
def add_item(slug: str, title: str, folder_id: int | None = None,
             status: str | None = None) -> dict:
    """Create a work item in a project. Returns an outcome, never raises.

    Outcomes: added (with `item_id`) · unknown_folder · unknown_status (with `valid`) ·
    unknown_project

    NOTE two senses of one word: the `status` PARAMETER is the item's state, while the
    returned `status` KEY is the outcome of this call. The parameter keeps the domain
    word and the key keeps the shape eight sibling functions share.

    `folder_id` is validated against THIS project. The ForeignKey alone only proves the
    row exists, not that it belongs here, so without this check an item could be filed
    into another project's folder — silently. `status` defaults to the shipped `todo`.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if folder_id is not None:
            folder = db.scalar(
                select(models.Folder).where(
                    models.Folder.id == folder_id,
                    models.Folder.project_id == project.id,
                )
            )
            if folder is None:
                return {"status": "unknown_folder"}

        if status is None:
            name = st.TODO
        else:
            name = status.strip().lower()
            vocabulary = _vocabulary(db, project.id)
            if name not in vocabulary:
                return {"status": "unknown_status", "valid": list(vocabulary)}

        item = models.Item(
            project_id=project.id, folder_id=folder_id, title=title, status=name
        )
        db.add(item)
        db.commit()
        return {"status": "added", "item_id": item.id}
```

- [ ] **Step 4: Update the five existing call sites**

Each currently assigns the returned int directly. All five become `[...]["item_id"]`:

- `backend/tests/test_set_status.py:13` — `item_id = repository.add_item(temp_slug, "Fix the login redirect loop")["item_id"]`
- `backend/tests/test_open_semantics.py:23` — inside the `project` fixture's loop: `item_id = repository.add_item(temp_slug, f"item-{name}")["item_id"]`
- `backend/tests/test_open_semantics.py:81` — `item_id = repository.add_item(temp_slug, "only-item")["item_id"]`
- `backend/tests/test_open_semantics.py:142` — `item_id = repository.add_item(temp_slug, "legacy-item")["item_id"]`
- `backend/tests/test_open_semantics.py:162` — `item_id = repository.add_item(temp_slug, "legacy-item")["item_id"]`

Change nothing else in those tests — no assertion, no fixture body. Grep afterwards to be
sure none was missed: `grep -rn "repository.add_item(" backend/tests` should show every
call ending in `["item_id"]`.

- [ ] **Step 5: Move the CLI's `add-item` command, and give it `--status`**

```python
@app.command("add-item")
def add_item(
    project: str,
    title: str,
    folder: int = typer.Option(None, help="Folder id"),
    status: str = typer.Option(None, help="Starting status (default: todo)"),
):
    """Add a work item to a project (optionally inside a folder, at a given status)."""
    result = repository.add_item(project, title, folder_id=folder, status=status)
    outcome = result["status"]
    if outcome == "added":
        typer.echo(f"✓ item #{result['item_id']} added to {project}")
        return
    if outcome == "unknown_status":
        typer.echo(f"unknown status '{status}'. valid: {', '.join(result['valid'])}")
        raise typer.Exit(1)
    messages = {
        "unknown_folder": f"unknown folder #{folder} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)
```

In `backend/tests/test_cli.py`, update `test_add_item_exits_non_zero_for_an_unknown_project`
(its fake returns `None` today → `{"status": "unknown_project"}`) and add:

```python
def test_add_item_reports_the_new_id(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "added", "item_id": 42}
    )
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it"])
    assert result.exit_code == 0, result.output
    assert "#42" in result.output


def test_add_item_exits_non_zero_for_an_unknown_folder(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "unknown_folder"}
    )
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it", "--folder", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_add_item_exits_non_zero_for_an_unknown_status(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "add_item",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it", "--status", "nope"])
    assert result.exit_code == 1
    assert "todo" in result.output
```

- [ ] **Step 6: Run the affected tests**

Run: `cd backend && uv run pytest tests/test_write_paths.py tests/test_set_status.py tests/test_open_semantics.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: 256 + 9 new + 3 new CLI = **268 passed**. Report the actual number.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/app/cli.py backend/tests/test_write_paths.py backend/tests/test_set_status.py backend/tests/test_open_semantics.py backend/tests/test_cli.py
git commit -m "fix(write): an item's folder must belong to the same project

add_item passed folder_id straight into a ForeignKey column, so
\`trackden add-item <p> \"x\" --folder 999\` was a raw IntegrityError traceback, and
a folder id from ANOTHER project was accepted — filing the item into that
project's folder with nothing to reveal it.

Also takes an optional starting status, validated against the project's
vocabulary rather than trusted, and returns the outcome-dict shape. The CLI gains
--status and --folder error reporting to match.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: the three MCP tools

**Files:**
- Modify: `backend/app/mcp_server.py` — three tools inserted after the existing `list_statuses`
- Modify: `backend/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `repository.add_item`, `repository.create_folder`, `repository.add_status` — all
  three now returning outcome dicts (Tasks 1-3).
- Produces: MCP tools `add_item`, `add_folder`, `add_status`. Tool count 13 → 16.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mcp_server.py`. This file calls tools DIRECTLY (e.g.
`mcp_server.get_history("my-first-project", limit=3)`) and asserts registration separately
via `mcp_server.mcp._tool_manager.get_tool("<name>")`. There is no `.fn` anywhere in it —
match both patterns, do not introduce a third.

```python
def test_the_write_side_tools_are_registered():
    for name in ("add_item", "add_folder", "add_status"):
        assert mcp_server.mcp._tool_manager.get_tool(name) is not None


def test_add_item_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, title, folder_id=None, status=None):
        seen.update(slug=slug, title=title, folder_id=folder_id, status=status)
        return {"status": "added", "item_id": 42}

    monkeypatch.setattr(mcp_server.repository, "add_item", fake)
    result = mcp_server.add_item("acme", "Fix it", folder_id=7, status="doing")
    assert seen == {"slug": "acme", "title": "Fix it", "folder_id": 7, "status": "doing"}
    assert result == {"status": "added", "item_id": 42}


def test_add_item_tool_passes_an_unknown_status_straight_through(monkeypatch):
    """The valid list must survive so the agent can correct itself."""
    monkeypatch.setattr(
        mcp_server.repository,
        "add_item",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    assert mcp_server.add_item("acme", "x", status="nope")["valid"] == ["todo", "done"]


def test_add_folder_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, name, parent_id=None):
        seen.update(slug=slug, name=name, parent_id=parent_id)
        return {"status": "added", "folder_id": 7}

    monkeypatch.setattr(mcp_server.repository, "create_folder", fake)
    result = mcp_server.add_folder("acme", "Bugs", parent_id=3)
    assert seen == {"slug": "acme", "name": "Bugs", "parent_id": 3}
    assert result == {"status": "added", "folder_id": 7}


def test_add_status_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, name, behaves_as):
        seen.update(slug=slug, name=name, behaves_as=behaves_as)
        return {"status": "added"}

    monkeypatch.setattr(mcp_server.repository, "add_status", fake)
    result = mcp_server.add_status("acme", "parked", "waiting")
    assert seen == {"slug": "acme", "name": "parked", "behaves_as": "waiting"}
    assert result == {"status": "added"}


def test_add_status_tool_hands_back_the_valid_classes(monkeypatch):
    monkeypatch.setattr(
        mcp_server.repository,
        "add_status",
        lambda *a, **k: {"status": "unknown_class", "valid": ["active", "closed", "open", "waiting"]},
    )
    assert mcp_server.add_status("acme", "x", "diagonal")["valid"] == [
        "active", "closed", "open", "waiting"
    ]


def test_add_status_description_tells_the_agent_to_offer_not_impose():
    """Rule 6 of the coming playbook: offer a new name, do not invent one."""
    text = mcp_server.add_status.__doc__.lower()
    assert "offer" in text or "ask" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: FAIL — `AttributeError: module 'app.mcp_server' has no attribute 'add_item'`

- [ ] **Step 3: Add the three tools**

In `backend/app/mcp_server.py`, insert after the existing `list_statuses` tool. These are
thin — no logic, no enrichment; everything the agent needs is already in the repository's
returned dict.

```python
@mcp.tool()
def add_item(
    project: str,
    title: str,
    folder_id: int | None = None,
    status: str | None = None,
) -> dict:
    """Create a work item — use this when the user describes work that is not yet
    tracked ("there's a bug in the login redirect"), so it exists before you start.

    `folder_id` files it under a folder of THIS project (see add_folder); omit it to
    put the item directly under the project. `status` sets a starting state and
    defaults to `todo` — pass `doing` when the user is already working on it.

    `status` in the RESULT is the outcome, not the item's state: added (with
    `item_id`) · unknown_folder · unknown_status (with the `valid` list, so you can
    correct yourself) · unknown_project."""
    return repository.add_item(project, title, folder_id=folder_id, status=status)


@mcp.tool()
def add_folder(project: str, name: str, parent_id: int | None = None) -> dict:
    """Create a folder to group a project's items. Ask the user before inventing a
    structure — the shape of their work is theirs, not yours to impose.

    `parent_id` nests this folder inside another folder of the SAME project.
    Outcome: added (with `folder_id`) · unknown_parent · unknown_project."""
    return repository.create_folder(project, name, parent_id=parent_id)


@mcp.tool()
def add_status(project: str, name: str, behaves_as: str) -> dict:
    """Add a status name to this project's vocabulary. OFFER this, do not impose it:
    when the user's real situation has no matching name ("on hold" is not "blocked"),
    say so and ask whether to add one — never quietly force their state into a label
    that is nearly right.

    `behaves_as` is what the new name DOES, which is the part that matters:
    open (not started) · active (being worked on) · waiting (stalled — skipped as the
    next step but still counted) · closed (finished or abandoned). Explain the
    behaviour to the user, not just the word.

    Outcome: added · duplicate_name · unknown_class (with `valid`) · invalid_name ·
    unknown_project."""
    return repository.add_status(project, name, behaves_as)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Confirm the tool count**

Run: `cd backend && grep -c "@mcp.tool()" app/mcp_server.py`
Expected: `16`

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: 268 + 7 = **275 passed**. Report the actual number.

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/mcp_server.py backend/tests/test_mcp_server.py
git commit -m "feat(write): an agent can create work — add_item, add_folder, add_status

Closes the gap the spec named second: the eleven original tools were reads plus
three narrow writes, so only a human at the CLI could put work INTO the tracker.
Thin wrappers, no logic — the repository's outcome dicts already carry everything
an agent needs to correct itself.

The descriptions carry the intent as much as the mechanics: offer a status, don't
impose one, and explain what a class DOES rather than what it is called; ask
before inventing a folder structure, because the shape of the user's work is
theirs. Tool count 13 -> 16.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: docs

**Files:**
- Modify: `_tracker.md`, `QUICKSTART.md`
- Modify: `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md`

- [ ] **Step 1: Update `_tracker.md`**

- In the "What works today" command table, add `--parent` to `add-folder` and `--status` to
  `add-item`, and note that `add-item`/`add-folder`/`add-status` are now available to agents
  over MCP too.
- In the MCP tool list, add `add_item`, `add_folder`, `add_status`.
- The open-gaps text says no agent can create work (there is no `add_item`/`add_folder` over
  MCP). That is now false — remove it and leave only what B2 and B3 still owe: no `file`
  memory kind or item scoping yet, and no shipped playbook.
- Add a Phase 14 (or extend Phase 13) with B1's items ticked and B2/B3's open.
- Recount the checkbox totals with `grep -cE '^\s*-\s*\[x\]' _tracker.md` and
  `grep -cE '^\s*-\s*\[ \]' _tracker.md` — report both raw numbers and do not do arithmetic
  from the previous figure.
- Update the test count to the real one from `cd backend && uv run pytest -q`.

- [ ] **Step 2: Update `QUICKSTART.md`**

It carries the only genuine MCP tool table in the repo (README.md and AGENTS.md do not — do
not invent one there). Add the three new tools.

- [ ] **Step 3: Update the spec's staging table**

Move `add_item`, `add_folder` and the MCP `add_status` tool out of the Stage B row into a new
Stage B1 row marked delivered, leaving the playbook in B3 and the file/item-scoping work in
B2. State that Stage B was split into B1/B2/B3 during planning because the three are
independent and B3's rules reference the other two.

- [ ] **Step 4: Verify nothing broke**

Run: `cd backend && uv run pytest -q`
Expected: unchanged from Task 4. Report the count.

- [ ] **Step 5: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add _tracker.md QUICKSTART.md docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md
git commit -m "docs: Stage B1 shipped — an agent can create work

Removes the now-false claim that no agent can put work into the tracker, and
records what B2 (the file kind and item scoping) and B3 (the playbook) still owe.
Notes the B1/B2/B3 split and why B3 comes last: its rules tell an agent to use
tools B1 and B2 provide.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage (B1 rows only):**

| Spec requirement | Task |
|---|---|
| `add_item` as an MCP tool | 4 (repository hardening in 3) |
| `add_folder` as an MCP tool | 4 (repository hardening in 2) |
| MCP `add_status` tool | 4 (race + dict shape in 1) |
| No exception crosses the MCP boundary | 1 (race), 2 (`unknown_parent`), 3 (`unknown_folder`) |
| Outcome-dict shape across the write paths | 1, 2, 3 |
| Thin wrappers, no logic in the tools | 4 |
| CLI exits non-zero on failure | 1, 2, 3 |

**Deliberately out of scope, and why:** `playbook.py`, `get_playbook`, the `overview` digest
and the onboard paste-snippet are B3 — B3's rules 8 and 9 instruct an agent to use the `file`
kind and item scoping, which do not exist until B2, so writing those rules now would ship
instructions that are lies. `memory.path`, the `file` kind, `session_logs.item_id`,
`memory.item_id` wiring, `get_history(item_id=…)` and the CLI's `--item`/`--path` flags are
B2. No schema change belongs in B1 at all.

**Placeholder scan:** none. Task 1 Step 4 and Task 5 Steps 1-3 describe edits by rule rather
than quoting every line, because they touch a variable number of existing assertions and
prose lines; both name the exact file, the exact transformation, and a grep to verify
completeness.

**Type consistency:** every write function returns `dict` with a `status` key.
`create_folder` carries `folder_id`, `add_item` carries `item_id`, and both `unknown_status`
and `unknown_class` carry `valid`. The MCP tool named `add_folder` wraps the repository
function named `create_folder` — deliberate, since the tool name matches its siblings
(`add_item`, `add_status`) while the repository keeps the name its existing callers use.
`add_item`'s `status` parameter and its returned `status` key are two senses of one word,
called out in the docstring and left as-is for consistency with eight sibling functions.
