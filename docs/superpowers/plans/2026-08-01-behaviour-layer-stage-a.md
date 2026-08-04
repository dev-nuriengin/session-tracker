# Behaviour layer — Stage A (unblock the loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an item's status changeable on every door, so `whats_next` advances and the tracker can track progress through work instead of only holding it.

**Architecture:** A new pure module `statuses.py` owns four fixed behaviour **classes** (`open · active · waiting · closed`) and the four shipped default **names** (`todo · doing · blocked · done`). A new `item_statuses` table lets a project add extra names, which are *added* to the defaults and never replace them. `repository.py` gains `set_status`, `list_statuses`, `add_status`, and its four "open item" queries stop meaning `status != "done"` and start meaning *"this item's status is not in the closed class"*. MCP and the CLI get thin wrappers.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (sync, typed `Mapped[]`) · Postgres · FastMCP · Typer · pytest

**Spec:** `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md`

## Global Constraints

- **No new dependencies.** Everything here uses what `pyproject.toml` already declares.
- **Sync SQLAlchemy 2.0 only**, typed `Mapped[]` columns, matching `models.py`.
- **Nobody opens a SQLAlchemy session except `repository.py`.** MCP and CLI stay thin wrappers.
- **No exception crosses the MCP boundary.** Every tool returns a dict with a `status` string, following the vocabulary pattern `guidance.py` established.
- **Every CLI write command exits non-zero on failure.**
- **Trackden never gates work.** No transition state machine: any valid status name may follow any other. The ask-before-closing rule is guidance an agent follows, never a check the code enforces.
- **The shipped defaults are always valid.** `item_statuses` rows are additions; a project row can never invalidate `todo` or `done`.
- **DB tests carry `@pytest.mark.db`** and auto-skip when Postgres is unreachable. Pure tests must not import anything that opens a connection.
- **Run tests from `backend/`:** `cd backend && uv run pytest`
- **Git:** personal account `dev-nuriengin` (already configured in this repo). Commit per task. **Never push** — the user says yes separately.

## Correction to the spec, made while planning

The spec says **five** existing queries define "open" as `status != "done"`. Reading the file, there are **four**: `repository.py:71` (`get_status`), `:88` (`overview`), `:119` (`list_items`), `:328` (`get_history`). The spec double-counted `overview`, which is the same site as `:88`.

Three further places carry status semantics and are handled in this plan: `repository.py:182` (`import_items` coerces to `todo`/`done`) and `tracker_md.py:122` / `:134` (the mirror's progress count and checkbox). Task 8 amends the spec so the count and the site list match the code.

**Also moved into Stage A:** `add_status` at the repository and CLI level. The spec's staging table put it in Stage B, which would leave Stage A shipping a table nothing can write to — untestable dead weight. The *MCP* `add_status` tool and the playbook rules that reference it stay in Stage B. Task 8 amends the staging table.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/statuses.py` | The status vocabulary: four classes, the shipped names, and resolution over a project's extras. Pure — no DB, no filesystem, no `app.*` imports. | **Create** (~70 lines) |
| `backend/app/models.py` | Schema. | **Modify** — add `ItemStatus` |
| `backend/app/repository.py` | DB state. | **Modify** — add `set_status`, `list_statuses`, `add_status`, `closed_names`, internal `_vocabulary`; change 4 queries |
| `backend/app/tracker_md.py` | The `_tracker.md` format, both ways. Pure. | **Modify** — `render_tracker_md` gains a `closed` parameter; import `TODO`/`DONE` from `statuses` |
| `backend/app/onboard.py:252` | The one `render_tracker_md` call site. | **Modify** — pass the project's closed names |
| `backend/app/mcp_server.py` | Agent door. | **Modify** — add `set_status`; `overview` passes through the new fields |
| `backend/app/cli.py` | Human door. | **Modify** — add `set-status`, `add-status`; fix three exit codes |
| `backend/tests/test_statuses.py` | Pure vocabulary tests. | **Create** |
| `backend/tests/test_statuses_db.py` | `add_status` / `list_statuses` against Postgres. | **Create** |
| `backend/tests/test_set_status.py` | Transitions. | **Create** |
| `backend/tests/test_open_semantics.py` | **The regression guard** for the four changed queries. | **Create** |

`item_statuses` is a brand-new table, so `Base.metadata.create_all` creates it. **No `_migrate()` line is needed in Stage A** — the two `ALTER`s the spec describes belong to Stage B's columns.

---

### Task 1: `statuses.py` — the vocabulary, pure

**Files:**
- Create: `backend/app/statuses.py`
- Test: `backend/tests/test_statuses.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `OPEN`, `ACTIVE`, `WAITING`, `CLOSED` (str constants) · `CLASSES: frozenset[str]` · `ACTIONABLE: frozenset[str]` · `TODO`, `DOING`, `BLOCKED`, `DONE` (str constants) · `DEFAULTS: dict[str, str]` · `resolve(extra: dict[str, str] | None) -> dict[str, str]` · `behaves_as(name: str, extra=None) -> str | None` · `is_valid(name: str, extra=None) -> bool` · `names_in(*classes: str, extra=None) -> frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_statuses.py`:

```python
"""The status vocabulary — pure, so no Postgres is involved."""

import pytest

from app import statuses


def test_the_four_classes_are_fixed():
    assert statuses.CLASSES == {"open", "active", "waiting", "closed"}


def test_actionable_is_open_plus_active():
    # what `whats_next` may offer: not started, or already being worked on
    assert statuses.ACTIONABLE == {"open", "active"}


def test_shipped_defaults_map_every_name_to_a_class():
    assert statuses.DEFAULTS == {
        "todo": "open",
        "doing": "active",
        "blocked": "waiting",
        "done": "closed",
    }
    assert set(statuses.DEFAULTS.values()) <= statuses.CLASSES


def test_resolve_with_no_extras_is_the_defaults():
    assert statuses.resolve(None) == statuses.DEFAULTS
    assert statuses.resolve({}) == statuses.DEFAULTS


def test_resolve_adds_extras_on_top_of_the_defaults():
    vocabulary = statuses.resolve({"parked": "waiting"})
    assert vocabulary["parked"] == "waiting"
    # the whole point: adding a name never removes one
    assert vocabulary["todo"] == "open"
    assert vocabulary["done"] == "closed"


def test_an_extra_can_never_override_a_default():
    # a stray row claiming done->open must not be able to un-close every done item
    vocabulary = statuses.resolve({"done": "open"})
    assert vocabulary["done"] == "closed"


def test_resolve_does_not_mutate_defaults():
    statuses.resolve({"parked": "waiting"})
    assert "parked" not in statuses.DEFAULTS


def test_behaves_as_knows_defaults_and_extras():
    assert statuses.behaves_as("blocked") == "waiting"
    assert statuses.behaves_as("parked", {"parked": "waiting"}) == "waiting"


def test_behaves_as_is_none_for_an_unknown_name():
    assert statuses.behaves_as("nonsense") is None


def test_is_valid_follows_the_resolved_vocabulary():
    assert statuses.is_valid("todo") is True
    assert statuses.is_valid("parked") is False
    assert statuses.is_valid("parked", {"parked": "waiting"}) is True


def test_names_in_collects_every_name_of_a_class():
    assert statuses.names_in("closed") == {"done"}
    assert statuses.names_in("waiting", extra={"parked": "waiting"}) == {"blocked", "parked"}


def test_names_in_accepts_several_classes():
    assert statuses.names_in("open", "active") == {"todo", "doing"}


def test_names_in_rejects_an_unknown_class():
    with pytest.raises(ValueError, match="unknown status class"):
        statuses.names_in("sideways")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_statuses.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.statuses'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/statuses.py`:

```python
"""The status vocabulary — four fixed CLASSES, a growable set of NAMES.

`whats_next` has to answer "is this item something to offer next?", and a name
alone cannot tell it: `blocked`, `parked` and `postponed` are three names for one
behaviour. So behaviour is fixed here in code as four classes, and names are data
a project may add to (see `models.ItemStatus`).

The shipped defaults are ALWAYS valid: a project's extra names are added on top,
never substituted, so adding `parked` can never invalidate `todo` or `done` — and
every item already in the database keeps a meaningful status the moment this lands.

Pure by design: no DB, no filesystem, no `app.*` imports. `repository` reads a
project's extras and hands them in.
"""

from __future__ import annotations

# ---- the four classes (code owns these; they never grow) ----

OPEN = "open"          # not started — `whats_next` may return it
ACTIVE = "active"      # someone is on it — `whats_next` reports it
WAITING = "waiting"    # started, not actionable now — skipped, but counted
CLOSED = "closed"      # finished or abandoned — hidden by default

CLASSES = frozenset({OPEN, ACTIVE, WAITING, CLOSED})

# What may be offered as "the next step". `active` is included deliberately: an item
# already being worked on IS the next step, not something to skip past.
ACTIONABLE = frozenset({OPEN, ACTIVE})

# ---- the shipped default names (data owns the rest) ----

TODO = "todo"
DOING = "doing"
BLOCKED = "blocked"
DONE = "done"

DEFAULTS: dict[str, str] = {
    TODO: OPEN,
    DOING: ACTIVE,
    BLOCKED: WAITING,
    DONE: CLOSED,
}


def resolve(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The valid vocabulary: the shipped defaults, plus a project's extra names.

    `setdefault`, not `update` — a row that claimed `done -> open` would otherwise
    un-close every finished item in that project. Defaults win, always.
    """
    vocabulary = dict(DEFAULTS)
    for name, cls in (extra or {}).items():
        vocabulary.setdefault(name, cls)
    return vocabulary


def behaves_as(name: str, extra: dict[str, str] | None = None) -> str | None:
    """Which class this name behaves as, or None when the name is unknown."""
    return resolve(extra).get(name)


def is_valid(name: str, extra: dict[str, str] | None = None) -> bool:
    return name in resolve(extra)


def names_in(*classes: str, extra: dict[str, str] | None = None) -> frozenset[str]:
    """Every status name belonging to the given class(es).

    This is what the repository's queries are written against — they ask for
    "the closed names" or "the actionable names", never for a literal `"done"`.
    """
    unknown = set(classes) - CLASSES
    if unknown:
        raise ValueError(f"unknown status class: {', '.join(sorted(unknown))}")
    wanted = set(classes)
    return frozenset(
        name for name, cls in resolve(extra).items() if cls in wanted
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_statuses.py -v`
Expected: PASS — 13 tests

- [ ] **Step 5: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/statuses.py backend/tests/test_statuses.py
git commit -m "feat(statuses): four fixed classes, a growable set of names

Classes are code because whats_next is written against behaviour, not
vocabulary: blocked/parked/postponed are three names for one thing. Extras
resolve on TOP of the shipped defaults via setdefault, so a project adding
'parked' can never invalidate 'todo' or un-close every 'done' item.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `ItemStatus` — the per-project extra names

**Files:**
- Modify: `backend/app/models.py` (append after the `Item` class, before `Session`)
- Modify: `backend/app/repository.py` (new section after `add_item`, around line 235)
- Test: `backend/tests/test_statuses_db.py`

**Interfaces:**
- Consumes: `statuses.CLASSES`, `statuses.DEFAULTS`, `statuses.resolve` (Task 1).
- Produces:
  - `models.ItemStatus` with columns `id`, `project_id`, `name`, `behaves_as`, `created_at`
  - `repository.list_statuses(slug: str) -> list[dict]` — `[{"name": str, "behaves_as": str}, ...]`, defaults first then extras, `[]` for an unknown project
  - `repository.add_status(slug: str, name: str, behaves_as: str) -> str` — returns one of `"added"`, `"duplicate_name"`, `"unknown_class"`, `"unknown_project"`, `"invalid_name"`
  - `repository.closed_names(slug: str) -> frozenset[str]` — the project's closed-class names
  - `repository._vocabulary(db, project_id) -> dict[str, str]` — internal; the resolved map for one project

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_statuses_db.py`:

```python
"""A project's extra status names, against the real (test) database."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Status Test")
    return temp_slug


def test_a_fresh_project_already_has_the_shipped_defaults(project):
    names = [row["name"] for row in repository.list_statuses(project)]
    assert names == ["todo", "doing", "blocked", "done"]


def test_list_statuses_reports_the_class_of_each_name(project):
    by_name = {row["name"]: row["behaves_as"] for row in repository.list_statuses(project)}
    assert by_name["blocked"] == "waiting"
    assert by_name["done"] == "closed"


def test_list_statuses_on_an_unknown_project_is_empty():
    assert repository.list_statuses("no-such-project-xyz") == []


def test_adding_a_name_appends_it_and_keeps_the_defaults(project):
    assert repository.add_status(project, "parked", "waiting") == "added"
    names = [row["name"] for row in repository.list_statuses(project)]
    assert names == ["todo", "doing", "blocked", "done", "parked"]


def test_a_name_that_is_already_a_default_is_a_duplicate(project):
    assert repository.add_status(project, "done", "open") == "duplicate_name"
    # and the default is untouched
    by_name = {r["name"]: r["behaves_as"] for r in repository.list_statuses(project)}
    assert by_name["done"] == "closed"


def test_adding_the_same_extra_twice_is_a_duplicate(project):
    assert repository.add_status(project, "parked", "waiting") == "added"
    assert repository.add_status(project, "parked", "waiting") == "duplicate_name"


def test_an_unrecognised_class_is_rejected(project):
    assert repository.add_status(project, "sideways", "diagonal") == "unknown_class"
    assert "sideways" not in [r["name"] for r in repository.list_statuses(project)]


def test_a_blank_name_is_rejected(project):
    assert repository.add_status(project, "   ", "waiting") == "invalid_name"


def test_a_name_is_stored_normalised(project):
    assert repository.add_status(project, "  Parked  ", "waiting") == "added"
    assert "parked" in [r["name"] for r in repository.list_statuses(project)]


def test_adding_to_an_unknown_project_reports_it():
    assert repository.add_status("no-such-project-xyz", "parked", "waiting") == "unknown_project"


def test_closed_names_starts_as_just_done(project):
    assert repository.closed_names(project) == {"done"}


def test_closed_names_grows_with_a_closed_extra(project):
    repository.add_status(project, "dropped", "closed")
    assert repository.closed_names(project) == {"done", "dropped"}


def test_closed_names_ignores_a_waiting_extra(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.closed_names(project) == {"done"}


def test_closed_names_on_an_unknown_project_falls_back_to_the_defaults():
    # a caller must never get an EMPTY closed set by accident: that would make
    # every finished item look open again
    assert repository.closed_names("no-such-project-xyz") == {"done"}


def test_two_projects_keep_separate_vocabularies(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    repository.add_status(project, "parked", "waiting")
    assert "parked" not in [r["name"] for r in repository.list_statuses(temp_slug_b)]


def test_init_db_is_idempotent_and_keeps_extras(project):
    """`create_all` creates the new table; running it again must not wipe a row.

    The onboarding branch shipped a migration bug for the neighbouring reason, so
    this asserts the DATA survives, not merely that the call does not raise.
    """
    from app.db import init_db

    repository.add_status(project, "parked", "waiting")
    init_db()
    init_db()
    assert "parked" in [r["name"] for r in repository.list_statuses(project)]
```

- [ ] **Step 2: Add the second temp-slug fixture**

`conftest.py` has `temp_slug` but only one. Add a sibling so the two-project test can clean up after itself. Append to `backend/tests/conftest.py`:

```python
@pytest.fixture
def temp_slug_b():
    """A SECOND disposable project slug, for tests that need two (db-marked)."""
    slug = "pytest-onboard-tmp-b"
    yield slug
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug))
        if project is not None:
            db.delete(project)  # cascades to folders / items / sessions / memory
            db.commit()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_statuses_db.py -v`
Expected: FAIL — `AttributeError: module 'app.repository' has no attribute 'list_statuses'`
(If Postgres is down the tests SKIP, which is not a pass. Start it: `docker compose up -d db`)

- [ ] **Step 4: Add the model**

In `backend/app/models.py`, insert after the `Item` class and before `class Session`:

```python
class ItemStatus(Base):
    """One EXTRA status name a project may use, and the class it behaves as.

    Additive: `statuses.DEFAULTS` is always valid, so a project with no rows works
    unchanged and adding `parked` can never invalidate `todo`. That is also why
    onboarding needs no seeding step — absence of rows is a complete, valid state.
    """

    __tablename__ = "item_statuses"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_item_status_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    # one of statuses.CLASSES — open | active | waiting | closed
    behaves_as: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

Two supporting edits in the same file:

1. Extend the import on line 16 to bring in `UniqueConstraint`:
   ```python
   from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
   ```
2. Add the relationship + cascade to `Project` (so deleting a project drops its
   vocabulary), directly after the `memory` relationship at line 52-54:
   ```python
       statuses: Mapped[list["ItemStatus"]] = relationship(
           cascade="all, delete-orphan"
       )
   ```

Also update the module docstring's schema sketch (lines 3-5) to mention the new table:

```python
    projects → folders (nestable) → items          (the work map)
    projects → sessions → session_logs             (what happened, per session)
    projects → memory                              (durable facts: links, notes)
    projects → item_statuses                       (EXTRA status names, on top of the defaults)
```

- [ ] **Step 5: Add the repository functions**

In `backend/app/repository.py`, add `statuses` to the imports at the top (after `from . import models`):

```python
from . import models, statuses as st
```

Then insert this section immediately after `add_item` (which ends at line 234), before the
`# ---- durable memory ----` comment:

```python
# ---- the status vocabulary ----

def _vocabulary(db, project_id: int) -> dict[str, str]:
    """The resolved status vocabulary for one project: defaults + its extras.

    Takes an open session because every caller already has one — this is the hot
    path for the "open item" queries and must not open a second connection.
    """
    extras = {
        row.name: row.behaves_as
        for row in db.scalars(
            select(models.ItemStatus).where(models.ItemStatus.project_id == project_id)
        ).all()
    }
    return st.resolve(extras)


def list_statuses(slug: str) -> list[dict]:
    """Every status name valid for a project, defaults first then its extras.

    Order is deliberate and stable: the shipped names in their declared order, then
    extras oldest-first. An agent reading this list sees the same thing every time.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        rows = db.scalars(
            select(models.ItemStatus)
            .where(models.ItemStatus.project_id == project.id)
            .order_by(models.ItemStatus.id)
        ).all()
        out = [{"name": name, "behaves_as": cls} for name, cls in st.DEFAULTS.items()]
        out += [{"name": r.name, "behaves_as": r.behaves_as} for r in rows]
        return out


def add_status(slug: str, name: str, behaves_as: str) -> str:
    """Add one extra status name to a project. Returns an outcome, never raises.

    Outcomes: added · duplicate_name · unknown_class · invalid_name · unknown_project
    """
    name = name.strip().lower()
    if not name:
        return "invalid_name"
    if behaves_as not in st.CLASSES:
        return "unknown_class"
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return "unknown_project"
        if name in _vocabulary(db, project.id):
            # covers both "already a shipped default" and "already added here"
            return "duplicate_name"
        db.add(models.ItemStatus(project_id=project.id, name=name, behaves_as=behaves_as))
        db.commit()
        return "added"


def closed_names(slug: str) -> frozenset[str]:
    """The project's closed-class status names.

    Falls back to the shipped defaults for an unknown project rather than returning
    an empty set — an empty closed set would make every finished item look open.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return st.names_in(st.CLOSED)
        return st.names_in(st.CLOSED, extra=_vocabulary(db, project.id))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_statuses_db.py -v`
Expected: PASS — 16 tests

- [ ] **Step 7: Run the whole suite — nothing existing may break**

Run: `cd backend && uv run pytest -q`
Expected: the previous 81 tests still pass, plus the new ones.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/models.py backend/app/repository.py backend/tests/test_statuses_db.py backend/tests/conftest.py
git commit -m "feat(statuses): per-project extra status names in the DB

item_statuses holds names a project ADDS; the shipped defaults stay valid, so
absence of rows is a complete state and onboarding needs no seeding. New table,
so create_all covers it — no _migrate() line needed.

closed_names() falls back to the defaults for an unknown project: an empty
closed set would make every finished item look open again.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `repository.set_status` — the blocker itself

**Files:**
- Modify: `backend/app/repository.py` (add after `closed_names` from Task 2)
- Test: `backend/tests/test_set_status.py`

**Interfaces:**
- Consumes: `_vocabulary` and `statuses` (Task 2).
- Produces: `repository.set_status(slug: str, item_id: int, status: str) -> dict` returning
  `{"status": "set", "from": str, "to": str}` · `{"status": "unchanged", "from": str, "to": str}` ·
  `{"status": "unknown_status", "valid": list[str]}` · `{"status": "unknown_item"}` ·
  `{"status": "unknown_project"}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_set_status.py`:

```python
"""Changing an item's status — the loop this whole stage exists to unblock."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def item(temp_slug):
    repository.create_project(temp_slug, name="Set Status Test")
    item_id = repository.add_item(temp_slug, "Fix the login redirect loop")
    return temp_slug, item_id


def test_a_new_item_starts_as_todo(item):
    slug, item_id = item
    assert [i for i in repository.list_items(slug) if i["id"] == item_id][0]["status"] == "todo"


def test_setting_a_status_reports_from_and_to(item):
    slug, item_id = item
    assert repository.set_status(slug, item_id, "doing") == {
        "status": "set",
        "from": "todo",
        "to": "doing",
    }


def test_the_change_persists(item):
    slug, item_id = item
    repository.set_status(slug, item_id, "doing")
    stored = [i for i in repository.list_items(slug) if i["id"] == item_id][0]
    assert stored["status"] == "doing"


def test_setting_the_same_status_twice_is_unchanged_not_a_fake_success(item):
    slug, item_id = item
    repository.set_status(slug, item_id, "doing")
    assert repository.set_status(slug, item_id, "doing") == {
        "status": "unchanged",
        "from": "doing",
        "to": "doing",
    }


def test_an_unknown_name_is_refused_and_hands_back_the_valid_set(item):
    slug, item_id = item
    result = repository.set_status(slug, item_id, "parked")
    assert result["status"] == "unknown_status"
    assert result["valid"] == ["todo", "doing", "blocked", "done"]


def test_a_name_the_project_added_becomes_usable(item):
    slug, item_id = item
    repository.add_status(slug, "parked", "waiting")
    assert repository.set_status(slug, item_id, "parked")["status"] == "set"


def test_a_name_added_to_ANOTHER_project_stays_unusable(item, temp_slug_b):
    slug, item_id = item
    repository.create_project(temp_slug_b, name="Other")
    repository.add_status(temp_slug_b, "parked", "waiting")
    assert repository.set_status(slug, item_id, "parked")["status"] == "unknown_status"


def test_an_unknown_item_is_reported(item):
    slug, _ = item
    assert repository.set_status(slug, 999_999_999, "doing") == {"status": "unknown_item"}


def test_an_item_belonging_to_another_project_is_not_reachable(item, temp_slug_b):
    slug, item_id = item
    repository.create_project(temp_slug_b, name="Other")
    # the item exists, but not under temp_slug_b
    assert repository.set_status(temp_slug_b, item_id, "doing") == {"status": "unknown_item"}


def test_an_unknown_project_is_reported():
    assert repository.set_status("no-such-project-xyz", 1, "doing") == {"status": "unknown_project"}


def test_a_status_is_normalised_before_matching(item):
    slug, item_id = item
    assert repository.set_status(slug, item_id, "  DOING  ")["status"] == "set"


def test_any_transition_is_allowed_because_trackden_never_gates(item):
    # closing then reopening is the user's business, not the tracker's
    slug, item_id = item
    repository.set_status(slug, item_id, "done")
    assert repository.set_status(slug, item_id, "todo") == {
        "status": "set",
        "from": "done",
        "to": "todo",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_set_status.py -v`
Expected: FAIL — `AttributeError: module 'app.repository' has no attribute 'set_status'`

- [ ] **Step 3: Write the implementation**

In `backend/app/repository.py`, append after `closed_names`:

```python
def set_status(slug: str, item_id: int, status: str) -> dict:
    """Move one item to a new status. Returns an outcome dict, never raises.

    Deliberately NOT a state machine: any valid name may follow any other, including
    reopening a closed item. The moment Trackden refuses a transition it stops being
    memory and starts being an agent. Whether to ASK before closing something is
    guidance for the caller, not a check here.

    Always reports `from` and `to`, so a caller whose item was moved by another
    session sees it instead of assuming.
    """
    status = status.strip().lower()
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        vocabulary = _vocabulary(db, project.id)
        if status not in vocabulary:
            return {"status": "unknown_status", "valid": list(vocabulary)}

        item = db.scalar(
            select(models.Item).where(
                models.Item.id == item_id, models.Item.project_id == project.id
            )
        )
        if item is None:
            return {"status": "unknown_item"}

        previous = item.status
        if previous == status:
            return {"status": "unchanged", "from": previous, "to": status}

        item.status = status
        db.commit()
        return {"status": "set", "from": previous, "to": status}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_set_status.py -v`
Expected: PASS — 12 tests

- [ ] **Step 5: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/tests/test_set_status.py
git commit -m "feat(statuses): set_status — an item can finally move

The blocker: nothing anywhere could change an item's status, so whats_next
returned the same item for ever. Deliberately not a state machine — any valid
name may follow any other, reopening included. Trackden records; the user
decides. Always returns from/to so a concurrent move is visible, not assumed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: "Open" stops meaning `!= "done"` — the regression guard

This is the only task that changes existing behaviour. Write the guard test first.

**Files:**
- Modify: `backend/app/repository.py:71` (`get_status`), `:88` (`overview`), `:119` (`list_items`), `:328` (`get_history`)
- Test: `backend/tests/test_open_semantics.py`

**Interfaces:**
- Consumes: `_vocabulary`, `statuses.ACTIONABLE`, `statuses.WAITING`, `statuses.CLOSED` (Tasks 1-2).
- Produces: unchanged signatures. `overview()`'s returned dict gains two keys —
  `waiting_items: int` and `statuses: list[dict]`. Existing keys keep their names;
  `open_items` now counts **actionable** items (`open` + `active`) rather than
  "everything not done".

**Ordering — read this before writing the queries.** `repository.add_item` never sets
`position`, and `models.Item.position` defaults to `0`. So every item added through
`add_item` shares position `0` and `ORDER BY position` alone is **non-deterministic** —
which item comes back as NEXT would be up to Postgres. Every query touched in this task
must order by `models.Item.position, models.Item.id`, the tiebreaker
`items_with_folders` already uses at line 207. The tests below depend on it.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_open_semantics.py`:

```python
"""What counts as "open" — the four queries that used to hard-code != "done".

The bug this guards: a stuck item sat in a non-done status for ever and kept
blocking the queue, so whats_next returned the same thing indefinitely at BOTH
ends — nothing could be closed, and nothing could be set aside.
"""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    """One project holding one item per class, in a known order."""
    repository.create_project(temp_slug, name="Open Semantics")
    repository.add_status(temp_slug, "parked", "waiting")
    repository.add_status(temp_slug, "dropped", "closed")
    ids = {}
    for name in ("todo", "doing", "blocked", "parked", "done", "dropped"):
        item_id = repository.add_item(temp_slug, f"item-{name}")
        repository.set_status(temp_slug, item_id, name)
        ids[name] = item_id
    return temp_slug, ids


# ---- list_items ----

def test_list_items_hides_every_closed_name_not_just_done(project):
    slug, _ = project
    titles = {i["title"] for i in repository.list_items(slug)}
    assert "item-dropped" not in titles   # the bug: only "done" was hidden
    assert "item-done" not in titles


def test_list_items_still_shows_waiting_items(project):
    slug, _ = project
    titles = {i["title"] for i in repository.list_items(slug)}
    assert {"item-blocked", "item-parked"} <= titles


def test_list_items_with_include_done_shows_everything(project):
    slug, ids = project
    assert len(repository.list_items(slug, include_done=True)) == len(ids)


# ---- get_status / the NEXT step ----

def test_next_is_the_first_actionable_item(project):
    slug, _ = project
    assert "item-todo" in repository.get_status(slug)


def test_next_skips_waiting_items(project):
    slug, ids = project
    for name in ("todo", "doing"):
        repository.set_status(slug, ids[name], "done")
    result = repository.get_status(slug)
    # blocked and parked remain, but neither is offered as the next step
    assert "item-blocked" not in result
    assert "item-parked" not in result


def test_next_reports_how_many_are_waiting(project):
    slug, ids = project
    for name in ("todo", "doing"):
        repository.set_status(slug, ids[name], "done")
    assert "2 waiting" in repository.get_status(slug)


def test_an_active_item_can_be_the_next_step(project):
    slug, ids = project
    repository.set_status(slug, ids["todo"], "done")
    assert "item-doing" in repository.get_status(slug)


def test_all_actionable_items_closed_says_so(temp_slug):
    repository.create_project(temp_slug, name="Tiny")
    item_id = repository.add_item(temp_slug, "only-item")
    repository.set_status(temp_slug, item_id, "done")
    assert "all items done" in repository.get_status(temp_slug)


# ---- overview ----

def test_overview_counts_actionable_and_waiting_separately(project):
    slug, _ = project
    ov = repository.overview(slug)
    assert ov["open_items"] == 2      # todo + doing
    assert ov["waiting_items"] == 2   # blocked + parked


def test_overview_next_matches_get_status(project):
    slug, _ = project
    assert repository.overview(slug)["next"] == "item-todo"


def test_overview_preview_holds_no_waiting_or_closed_item(project):
    slug, _ = project
    preview = repository.overview(slug)["open_preview"]
    assert all("blocked" not in t and "parked" not in t for t in preview)
    assert all("done" not in t and "dropped" not in t for t in preview)


def test_overview_reports_the_valid_vocabulary(project):
    slug, _ = project
    names = [row["name"] for row in repository.overview(slug)["statuses"]]
    assert names == ["todo", "doing", "blocked", "done", "parked", "dropped"]


def test_overview_on_an_unknown_project_is_still_empty():
    assert repository.overview("no-such-project-xyz") == {}


# ---- get_history ----

def test_history_open_items_exclude_waiting_and_closed(project):
    slug, _ = project
    open_items = repository.get_history(slug)["open_items"]
    assert set(open_items) == {"item-todo", "item-doing"}


# ---- the safety default ----

def test_an_unrecognised_stored_status_stays_visible(temp_slug):
    """A legacy or hand-set value must show up, not vanish.

    Hiding an item we don't understand loses work silently; showing it is the
    honest failure mode.
    """
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    repository.create_project(temp_slug, name="Legacy")
    item_id = repository.add_item(temp_slug, "legacy-item")
    with SessionLocal() as db:
        item = db.scalar(select(models.Item).where(models.Item.id == item_id))
        item.status = "whatever-this-is"
        db.commit()
    assert "legacy-item" in {i["title"] for i in repository.list_items(temp_slug)}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_open_semantics.py -v`
Expected: FAIL — several. `test_list_items_hides_every_closed_name_not_just_done` fails
because `dropped` is currently treated as open; `test_overview_counts_actionable_and_waiting_separately`
fails with `KeyError: 'waiting_items'`.

- [ ] **Step 3: Rewrite `get_status` (replaces lines 60-76)**

```python
def get_status(slug: str) -> str:
    """Short status string for a project: its next ACTIONABLE item.

    "Actionable" is open-or-active, so an item someone is already on counts as the
    next step. Waiting items (blocked, parked, …) are skipped but reported — that
    is what stops a stalled item from blocking the queue for ever.
    Returns '' if the project is unknown.
    """
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return ""
        vocabulary = _vocabulary(db, project.id)
        actionable = st.names_in(*st.ACTIONABLE, extra=vocabulary)
        waiting = st.names_in(st.WAITING, extra=vocabulary)

        nxt = db.scalar(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(actionable))
            .order_by(models.Item.position, models.Item.id)
        )
        waiting_count = db.scalar(
            select(func.count()).select_from(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(waiting))
        ) or 0
        tail = f"  ({waiting_count} waiting)" if waiting_count else ""

        if nxt is None:
            return f"{project.name}: all items done.{tail}"
        return f"{project.name}: NEXT — {nxt.title}{tail}"
```

- [ ] **Step 4: Rewrite `overview` (replaces lines 79-108)**

```python
def overview(slug: str) -> dict:
    """The cheap FIRST look — a compact summary, not a full dump. Counts + a few
    titles + last activity + the valid status vocabulary. Drill deeper with
    list_items / list_memory / get_history."""
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {}
        vocabulary = _vocabulary(db, project.id)
        actionable = st.names_in(*st.ACTIONABLE, extra=vocabulary)
        waiting = st.names_in(st.WAITING, extra=vocabulary)

        open_titles = db.scalars(
            select(models.Item.title)
            .where(models.Item.project_id == project.id, models.Item.status.in_(actionable))
            .order_by(models.Item.position, models.Item.id)
        ).all()
        waiting_count = db.scalar(
            select(func.count()).select_from(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(waiting))
        )
        mem_count = db.scalar(
            select(func.count()).select_from(models.Memory)
            .where(models.Memory.project_id == project.id)
        )
        last_log = db.scalar(
            select(models.SessionLog.content)
            .join(models.Session)
            .where(models.Session.project_id == project.id)
            .order_by(models.SessionLog.created_at.desc())
        )
        return {
            "project": project.slug,
            "next": open_titles[0] if open_titles else None,
            "open_items": len(open_titles),
            "open_preview": list(open_titles[:3]),  # a taste, not all of them
            "waiting_items": waiting_count or 0,
            "memory_entries": mem_count or 0,
            "last_activity": last_log,
            # the valid vocabulary travels with the summary, so a caller never has
            # to guess a status name — and never needs a second round trip to check
            "statuses": [{"name": n, "behaves_as": c} for n, c in vocabulary.items()],
        }
```

- [ ] **Step 5: Change `list_items` (replaces lines 111-121)**

```python
def list_items(slug: str, include_done: bool = False) -> list[dict]:
    """Drill-down: all items for a project (open only unless include_done).

    "Open" here means "not in the closed class" — so `waiting` items still show up
    (you need to see what stalled), and a project's own closed name like `dropped`
    is hidden just as `done` is. An unrecognised stored status counts as open: an
    item we cannot classify must stay visible rather than vanish.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        q = select(models.Item).where(models.Item.project_id == project.id)
        if not include_done:
            closed = st.names_in(st.CLOSED, extra=_vocabulary(db, project.id))
            q = q.where(models.Item.status.notin_(closed))
        rows = db.scalars(q.order_by(models.Item.position, models.Item.id)).all()
        return [{"id": i.id, "title": i.title, "status": i.status, "folder_id": i.folder_id} for i in rows]
```

- [ ] **Step 6: Change `get_history` (the query at line 326-330)**

Replace:

```python
        open_items = db.scalars(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status != "done")
            .order_by(models.Item.position)
        ).all()
```

with:

```python
        actionable = st.names_in(*st.ACTIONABLE, extra=_vocabulary(db, project.id))
        open_items = db.scalars(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(actionable))
            .order_by(models.Item.position, models.Item.id)
        ).all()
```

- [ ] **Step 7: Run the guard tests**

Run: `cd backend && uv run pytest tests/test_open_semantics.py -v`
Expected: PASS — 15 tests

- [ ] **Step 8: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: everything passes. If a pre-existing test asserted `overview()`'s exact dict
equality it will now fail on the two new keys — update that test to assert the keys it
cares about rather than the whole dict, and note it in the commit message.

- [ ] **Step 9: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/repository.py backend/tests/test_open_semantics.py
git commit -m "fix(statuses): open means 'not closed', not 'not done'

Four queries hard-coded status != \"done\", which broke at both ends: a
project's own closed name (dropped) stayed visible for ever, and a stalled item
blocked the NEXT queue with no way past it. They now resolve the project's
vocabulary and ask for a CLASS.

NEXT is the first actionable (open|active) item, so an item already being worked
on counts; waiting items are skipped but counted, which is what unblocks the
queue. An unrecognised stored status counts as open on purpose — an item we
cannot classify must stay visible rather than vanish.

overview() gains waiting_items and statuses; existing keys keep their names.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: the `_tracker.md` mirror learns about classes

**Files:**
- Modify: `backend/app/tracker_md.py:14-15` (constants), `:112-137` (`render_tracker_md`)
- Modify: `backend/app/onboard.py:252` (the one call site)
- Test: `backend/tests/test_tracker_md.py` (extend)

**Interfaces:**
- Consumes: `statuses.TODO`, `statuses.DONE`, `repository.closed_names` (Tasks 1-2).
- Produces: `render_tracker_md(project_name: str, items: list[TrackerItem], closed: frozenset[str] | set[str] | None = None) -> str`. `closed=None` means "just `done`", so every existing caller and test keeps its behaviour.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tracker_md.py`:

```python
def test_render_marks_any_closed_name_as_ticked():
    out = render_tracker_md(
        "P",
        [{"title": "abandoned", "status": "dropped", "folder": None}],
        closed={"done", "dropped"},
    )
    assert "- [x] abandoned" in out


def test_render_appends_a_non_default_status_name():
    out = render_tracker_md(
        "P",
        [{"title": "waiting on vendor", "status": "parked", "folder": None}],
    )
    assert "- [ ] waiting on vendor  · parked" in out


def test_render_does_not_annotate_a_plain_todo():
    out = render_tracker_md("P", [{"title": "plain", "status": "todo", "folder": None}])
    assert "- [ ] plain" in out
    assert "· todo" not in out


def test_render_does_not_annotate_a_closed_item():
    # the [x] already says it; the name would be noise
    out = render_tracker_md(
        "P",
        [{"title": "shipped", "status": "dropped", "folder": None}],
        closed={"done", "dropped"},
    )
    assert "· dropped" not in out


def test_render_counts_every_closed_name_as_progress():
    out = render_tracker_md(
        "P",
        [
            {"title": "a", "status": "done", "folder": None},
            {"title": "b", "status": "dropped", "folder": None},
            {"title": "c", "status": "todo", "folder": None},
        ],
        closed={"done", "dropped"},
    )
    assert "**Progress:** 2 / 3 done." in out


def test_render_without_a_closed_set_still_means_just_done():
    # every pre-existing caller relies on this default
    out = render_tracker_md(
        "P",
        [{"title": "a", "status": "dropped", "folder": None}],
    )
    assert "- [ ] a" in out


def test_an_annotated_line_reparses_to_a_todo_item():
    """The parser must survive the annotation the renderer adds."""
    rendered = render_tracker_md(
        "P", [{"title": "waiting on vendor", "status": "parked", "folder": None}]
    )
    reparsed = parse_tracker_md(rendered)
    assert reparsed.items[0].status == "todo"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_tracker_md.py -v`
Expected: FAIL — `TypeError: render_tracker_md() got an unexpected keyword argument 'closed'`

- [ ] **Step 3: Point the constants at `statuses.py`**

In `backend/app/tracker_md.py`, replace lines 14-15:

```python
TODO = "todo"
DONE = "done"
```

with:

```python
# Re-exported from `statuses`, which owns the vocabulary. Kept as names here because
# the parser only ever infers these two, and `repository` imports them from this
# module today. No cycle: `statuses` imports nothing from the app.
from .statuses import DONE, TODO  # noqa: F401 — re-exported for existing callers
```

Move that import up to sit with the other imports at the top of the file (after
`from typing import Literal, TypedDict`), and delete the now-duplicated constants.

- [ ] **Step 4: Rewrite `render_tracker_md` (replaces lines 112-137)**

```python
def render_tracker_md(
    project_name: str,
    items: list[TrackerItem],
    closed: frozenset[str] | set[str] | None = None,
) -> str:
    """Render the DB's items as the generated `_tracker.md` mirror.

    Derived output, never a source of truth — the banner says so to whoever opens it.
    Items are grouped under their folder name; unfiled items go under `UNFILED`.

    Markdown only expresses done and not-done, so: anything in `closed` renders
    `[x]`, everything else `[ ]`, and a non-default open status has its name
    appended so `parked` is visible at a glance. `closed=None` means just `done`,
    which keeps every caller that predates the status vocabulary behaving the same.

    Stays pure: the caller resolves the project's closed names and passes them in.
    """
    closed_names = frozenset(closed) if closed is not None else frozenset({DONE})

    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item.get("folder") or UNFILED, []).append(item)

    done = sum(1 for item in items if item.get("status") in closed_names)
    lines = [
        f"# {project_name} — tracker (GENERATED)",
        "",
        _GENERATED_BANNER,
        "",
        f"**Progress:** {done} / {len(items)} done.",
        "",
    ]
    for folder, group in groups.items():
        lines.append(f"## {folder}")
        for item in group:
            status = item.get("status")
            is_closed = status in closed_names
            box = "x" if is_closed else " "
            # A closed box already says "finished"; naming it too would be noise.
            # An open item that is not plain `todo` gets its name, so a parked or
            # blocked item is readable without opening the CLI.
            suffix = "" if is_closed or status == TODO else f"  · {status}"
            lines.append(f"- [{box}] {item['title']}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 5: Update the one call site**

In `backend/app/onboard.py`, line 252, replace:

```python
    mirror = render_tracker_md(display, repository.items_with_folders(slug))
```

with:

```python
    mirror = render_tracker_md(
        display,
        repository.items_with_folders(slug),
        closed=repository.closed_names(slug),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tracker_md.py tests/test_onboard.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/tracker_md.py backend/app/onboard.py backend/tests/test_tracker_md.py
git commit -m "feat(statuses): the tracker mirror shows more than done/not-done

Markdown has two boxes and the vocabulary now has more than two names, so a
closed name renders [x] and a non-default open status appends its name:
'- [ ] Chase the vendor SLA  · parked'. The parser is untouched — it already
coerces anything unrecognised back to todo, so a hand-edited mirror still
cannot corrupt the DB.

render_tracker_md stays pure: the caller resolves the closed set and passes it
in. closed=None keeps every pre-existing caller identical.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: the MCP door

**Files:**
- Modify: `backend/app/mcp_server.py` (add `set_status` after `list_items`; extend the `overview` docstring)
- Test: `backend/tests/test_mcp_server.py` (extend)

**Interfaces:**
- Consumes: `repository.set_status`, `repository.list_statuses` (Tasks 2-3).
- Produces: MCP tools `set_status(project, item_id, status) -> dict` and `list_statuses(project) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mcp_server.py`:

```python
def test_set_status_is_registered_as_a_tool():
    assert mcp_server.mcp._tool_manager.get_tool("set_status") is not None


def test_list_statuses_is_registered_as_a_tool():
    assert mcp_server.mcp._tool_manager.get_tool("list_statuses") is not None


def test_set_status_tool_delegates_to_the_repository(monkeypatch):
    seen = {}

    def fake(slug, item_id, status):
        seen.update(slug=slug, item_id=item_id, status=status)
        return {"status": "set", "from": "todo", "to": "doing"}

    monkeypatch.setattr(mcp_server.repository, "set_status", fake)
    result = mcp_server.set_status("acme", 42, "doing")
    assert seen == {"slug": "acme", "item_id": 42, "status": "doing"}
    assert result == {"status": "set", "from": "todo", "to": "doing"}


def test_set_status_passes_an_unknown_status_straight_through(monkeypatch):
    """The valid list must reach the agent so it can self-correct."""
    monkeypatch.setattr(
        mcp_server.repository,
        "set_status",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    assert mcp_server.set_status("acme", 1, "parked")["valid"] == ["todo", "done"]


def test_list_statuses_tool_delegates_to_the_repository(monkeypatch):
    monkeypatch.setattr(
        mcp_server.repository,
        "list_statuses",
        lambda slug: [{"name": "todo", "behaves_as": "open"}],
    )
    assert mcp_server.list_statuses("acme") == [{"name": "todo", "behaves_as": "open"}]


def test_set_status_docstring_tells_the_agent_to_ask_before_closing():
    # the graduated-ask rule has to be visible where the agent actually reads
    text = mcp_server.set_status.__doc__.lower()
    assert "ask" in text
    assert "close" in text or "closing" in text
```

> **Convention (verified, do not change it):** this file calls the decorated tools
> **directly** — `mcp_server.get_history("my-first-project", limit=3)` at line 24 — and
> asserts registration separately via
> `mcp_server.mcp._tool_manager.get_tool("<name>")` (lines 31, 35). There is no `.fn`
> anywhere in this file. Match both patterns exactly; do not introduce a third.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: FAIL — `AttributeError: module 'app.mcp_server' has no attribute 'set_status'`

- [ ] **Step 3: Add the tools**

In `backend/app/mcp_server.py`, insert after the `list_items` tool (which ends at line 36):

```python
@mcp.tool()
def set_status(project: str, item_id: int, status: str) -> dict:
    """Move an item to a new status — this is how you record PROGRESS, not just work.

    Set `doing` freely the moment you start on something; no need to ask.
    Announce a `waiting` change (blocked, parked, …) in one line so the user knows
    something stalled. ASK before you close anything (`done`, `dropped`) unless the
    user just told you it is finished — closing hides an item from `whats_next`.

    Only names from `statuses` (in the `overview` payload) are valid; never invent
    one. If the user's real situation has no matching name, offer to add one rather
    than forcing their state into the wrong label.

    `status` tells you what happened: set · unchanged · unknown_status (with the
    `valid` list, so you can correct yourself) · unknown_item · unknown_project.
    `from` and `to` are always reported, so you can see if someone else moved it."""
    return repository.set_status(project, item_id, status)


@mcp.tool()
def list_statuses(project: str) -> list[dict]:
    """The status names this project accepts, each with the class it behaves as:
    open (not started) · active (being worked on) · waiting (stalled, skipped by
    whats_next but still counted) · closed (finished or abandoned, hidden).
    `overview` already includes this — call it only if you need it on its own."""
    return repository.list_statuses(project)
```

- [ ] **Step 4: Extend the `overview` docstring (line 26-28)**

Replace the docstring body with:

```python
    """Call this FIRST when you start on a project. A COMPACT summary — next step,
    open-item count + a few titles, how many are waiting, memory count, last
    activity, and the status names this project accepts. It is cheap and does NOT
    dump everything. Drill deeper with list_items / list_memory only if you need to."""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/mcp_server.py backend/tests/test_mcp_server.py
git commit -m "feat(statuses): set_status and list_statuses over MCP

Thin wrappers, no logic. The set_status description carries the graduated-ask
rule (doing silently, waiting announced, closing asked first) because a tool
description is where an agent actually reads behaviour. unknown_status hands
back the valid list so the agent self-corrects instead of guessing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: the CLI door, and three exit codes

**Files:**
- Modify: `backend/app/cli.py` — add `set-status` and `add-status`; fix `add-folder` (line 111-115), `add-item` (118-122), `log` (172-185)
- Test: `backend/tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `repository.set_status`, `repository.add_status`, `repository.list_statuses` (Tasks 2-3).
- Produces: commands `set-status`, `add-status`, `statuses`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_cli.py`.

> **Conventions (verified, do not change them):** the module imports
> `from app import cli as cli_mod` and creates a **module-level**
> `runner = CliRunner()` at line 13 — `runner` is *not* a fixture, so it must not
> appear in any test signature. `init_db` is faked per-test by patching
> `cli_mod.init_db`; these tests patch only `cli_mod.repository`, and the app-level
> callback's real `init_db()` would then try to reach Postgres. Patch it in each test
> exactly as shown below, so this file stays Postgres-free as its docstring promises.

```python
def _no_schema(monkeypatch):
    """Neutralise the app-level init_db callback — these tests never touch Postgres."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())


def test_set_status_reports_the_move(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "set", "from": "todo", "to": "doing"},
    )
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"])
    assert result.exit_code == 0, result.output
    assert "todo → doing" in result.output


def test_set_status_exits_non_zero_on_an_unknown_status(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "parked"])
    assert result.exit_code == 1
    assert "todo" in result.output and "done" in result.output


def test_set_status_exits_non_zero_on_an_unknown_item(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "set_status", lambda *a, **k: {"status": "unknown_item"}
    )
    assert runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"]).exit_code == 1


def test_unchanged_is_reported_and_succeeds(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "unchanged", "from": "doing", "to": "doing"},
    )
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"])
    assert result.exit_code == 0, result.output
    assert "already" in result.output


def test_add_status_succeeds(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: "added")
    result = runner.invoke(
        cli_mod.app, ["add-status", "acme", "parked", "--behaves-as", "waiting"]
    )
    assert result.exit_code == 0, result.output
    assert "parked" in result.output


def test_add_status_exits_non_zero_on_a_duplicate(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: "duplicate_name")
    assert runner.invoke(
        cli_mod.app, ["add-status", "acme", "done", "--behaves-as", "open"]
    ).exit_code == 1


def test_statuses_lists_names_with_their_class(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "list_statuses",
        lambda slug: [{"name": "todo", "behaves_as": "open"}],
    )
    result = runner.invoke(cli_mod.app, ["statuses", "acme"])
    assert result.exit_code == 0, result.output
    assert "todo" in result.output and "open" in result.output


def test_statuses_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "list_statuses", lambda slug: [])
    assert runner.invoke(cli_mod.app, ["statuses", "nope"]).exit_code == 1


# ---- the exit-code bug: these printed an error and still exited 0 ----

def test_add_folder_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "create_folder", lambda *a, **k: None)
    assert runner.invoke(cli_mod.app, ["add-folder", "nope", "Bugs"]).exit_code == 1


def test_add_item_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_item", lambda *a, **k: None)
    assert runner.invoke(cli_mod.app, ["add-item", "nope", "Fix it"]).exit_code == 1


def test_log_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_session_log", lambda *a, **k: False)
    assert runner.invoke(cli_mod.app, ["log", "nope", "did a thing"]).exit_code == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: FAIL — `No such command 'set-status'`, and the three exit-code tests fail with
`assert 0 == 1`.

- [ ] **Step 3: Add the three commands**

In `backend/app/cli.py`, insert after `add_item` (which ends at line 122):

```python
@app.command("set-status")
def set_status(project: str, item_id: int, status: str):
    """Move an item to a new status (see `trackden statuses <project>` for the valid names)."""
    result = repository.set_status(project, item_id, status)
    outcome = result["status"]
    if outcome == "set":
        typer.echo(f"✓ item #{item_id}: {result['from']} → {result['to']}")
        return
    if outcome == "unchanged":
        typer.echo(f"item #{item_id} is already '{result['to']}'")
        return
    if outcome == "unknown_status":
        typer.echo(f"unknown status '{status}'. valid: {', '.join(result['valid'])}")
    elif outcome == "unknown_item":
        typer.echo(f"unknown item #{item_id} in '{project}'")
    else:
        typer.echo(f"unknown project '{project}'")
    raise typer.Exit(1)


@app.command("add-status")
def add_status(
    project: str,
    name: str,
    behaves_as: str = typer.Option(..., "--behaves-as", help="open | active | waiting | closed"),
):
    """Add a status name to a project. The four shipped names always stay valid."""
    outcome = repository.add_status(project, name, behaves_as)
    if outcome == "added":
        typer.echo(f"✓ '{name}' added to {project} (behaves as {behaves_as})")
        return
    messages = {
        "duplicate_name": f"'{name}' is already a status in {project}",
        "unknown_class": f"unknown class '{behaves_as}'. valid: open, active, waiting, closed",
        "invalid_name": "a status name cannot be blank",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)


@app.command()
def statuses(project: str):
    """List the status names a project accepts, with the class each behaves as."""
    rows = repository.list_statuses(project)
    if not rows:
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)
    typer.echo(f"# {project} — statuses")
    for row in rows:
        typer.echo(f"  {row['name']:<12} {row['behaves_as']}")
```

- [ ] **Step 4: Fix the three exit codes**

`add-folder` (lines 111-115) becomes:

```python
@app.command("add-folder")
def add_folder(project: str, name: str):
    """Add a folder to a project."""
    fid = repository.create_folder(project, name)
    if not fid:
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)
    typer.echo(f"✓ folder #{fid} added to {project}")
```

`add-item` (lines 118-122) becomes:

```python
@app.command("add-item")
def add_item(project: str, title: str, folder: int = typer.Option(None, help="Folder id")):
    """Add a work item to a project (optionally inside a folder)."""
    iid = repository.add_item(project, title, folder_id=folder)
    if not iid:
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)
    typer.echo(f"✓ item #{iid} added to {project}")
```

For `log` (lines 172-185): read the command as it stands, then apply the same shape —
on a falsy result from `repository.add_session_log`, `typer.echo` the error and
`raise typer.Exit(1)` instead of falling through to the success line. Match the wording
`remember` uses at line 140: `f"unknown project '{project}'"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: everything green.

- [ ] **Step 7: Try it by hand against a real database**

```bash
cd backend
docker compose -f ../docker-compose.yml up -d db
uv run trackden add-project stage-a-smoke --name "Stage A smoke"
uv run trackden add-item stage-a-smoke "Fix the login redirect loop"
uv run trackden statuses stage-a-smoke
uv run trackden status stage-a-smoke                      # NEXT — Fix the login redirect loop
uv run trackden set-status stage-a-smoke 1 doing          # adjust the id to what add-item printed
uv run trackden add-status stage-a-smoke parked --behaves-as waiting
uv run trackden set-status stage-a-smoke 1 parked
uv run trackden status stage-a-smoke                      # all items done. (1 waiting)
uv run trackden add-folder nope Bugs; echo "exit=$?"      # exit=1
```

Confirm the last `status` line reports the waiting count and no longer offers the parked
item as NEXT.

- [ ] **Step 8: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/cli.py backend/tests/test_cli.py
git commit -m "feat(statuses): set-status, add-status and statuses on the CLI

Same reach as the agent, because the CLI is the trust surface that proves an
agent saved what it claimed.

Also fixes the long-standing exit-0 bug: add-folder, add-item and log printed a
failure and still exited 0, so a script could not detect that nothing was
saved. remember was fixed in the guidance branch; these three were left, and
this is the branch that touches them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: docs — say what shipped, and correct the spec

**Files:**
- Modify: `_tracker.md` (the "▸ Resume here" block, the Status line, Phase 12's blocker line, the "Start here" table)
- Modify: `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` (the query count, the staging table)
- Modify: `README.md` and `AGENTS.md` (the command tables)

- [ ] **Step 1: Correct the spec's two inaccuracies**

In the spec's "The one non-additive change" section, change "Five existing queries" to
"Four existing queries" and drop `overview` from the trailing list (it *is* `:88`). Add
one line noting that `import_items`'s coercion and the two `tracker_md.py` sites also
carry status semantics.

In the spec's staging table, move `add_status` (repository + CLI) from Stage B to Stage A,
with the reason: a table nothing can write to is untestable dead weight. Leave the *MCP*
`add_status` tool in Stage B.

- [ ] **Step 2: Update `_tracker.md`**

- In the "What works today" table, add rows for `trackden set-status`, `add-status`, `statuses`.
- Delete the "**What does NOT work yet**" paragraph about being unable to mark an item done —
  it is now false. Replace it with what Stage A leaves open: an agent cannot yet create work
  (no `add_item`/`add_folder` over MCP) and there is no shipped playbook.
- In Phase 12, change the 🔴 blocker line to `[x]` and rewrite it to describe what shipped.
- Add a Phase 13 section listing Stage A's items as done and Stage B's as open.
- Update the Status count: 39/47 becomes 45/53 (8 Stage A items ticked, and the Phase 13
  block adds Stage B's 6 open items — recount against the file rather than trusting this
  arithmetic).
- Update the "▸ NEXT" block to point at Stage B (the playbook and the write-side MCP tools),
  and then the launcher/alias.

- [ ] **Step 3: Update `README.md` and `AGENTS.md`**

Add `set-status`, `add-status` and `statuses` to whichever command tables those files carry,
and add `set_status` / `list_statuses` to the MCP tool list. Grep first so nothing is missed:

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
grep -n "add-item\|whats_next" README.md AGENTS.md QUICKSTART.md
```

- [ ] **Step 4: Verify the whole suite one last time**

Run: `cd backend && uv run pytest -q`
Expected: all green. Record the actual test count in the commit message.

- [ ] **Step 5: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add _tracker.md README.md AGENTS.md QUICKSTART.md docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md
git commit -m "docs: Stage A shipped — items can move, and the queue advances

The blocker is closed: set_status exists on all three doors, statuses carry a
behaviour class, and a project can add names without a code change.

Corrects the spec: four queries hard-coded != \"done\", not five (overview was
counted twice), and add_status moves to Stage A because a table nothing can
write to is untestable dead weight.

Still open, and next: no agent can create work (add_item/add_folder over MCP),
and no playbook ships yet — that is Stage B.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage (Stage A rows only):**

| Spec requirement | Task |
|---|---|
| Four fixed classes, shipped default names | 1 |
| Extras add to defaults, never replace | 1 (`resolve` via `setdefault`), 2 (`duplicate_name`) |
| `item_statuses` table | 2 |
| Idempotent migration | 2 — new table, so `create_all` covers it; no `_migrate()` line. Asserted by `test_init_db_is_idempotent_and_keeps_extras` |
| `set_status` on repository | 3 |
| `set_status` on MCP | 6 |
| `set_status` on CLI | 7 |
| Open-semantics change (4 queries) | 4 |
| `whats_next` skips + counts waiting | 4 |
| No transition state machine | 3 (`test_any_transition_is_allowed_because_trackden_never_gates`) |
| No locking; `from`/`to` always reported | 3 |
| `unknown_status` returns the valid set | 3, 6, 7 |
| `unchanged` is honest | 3, 7 |
| `_tracker.md` render rule | 5 |
| CLI exits non-zero on failure | 7 |
| `overview` reports the vocabulary | 4 |

**Deliberately Stage B, not missing:** `playbook.py`, `get_playbook`, the digest in
`overview`, `add_item` / `add_folder` / `add_status` as MCP tools, the `file` memory kind,
`memory.path`, `session_logs.item_id`, `get_history(item_id=…)`, the onboard paste-snippet.

**Placeholder scan:** none. Two steps deliberately say "read the file and follow the
existing pattern" rather than quoting code — Task 6 Step 1 (how FastMCP tools are reached in
tests) and Task 7 Step 4 (`log`'s current body). Both name the exact file, the exact lines,
and the exact shape to match, because inventing a third convention would be worse than
matching the two already there.

**Type consistency:** `behaves_as` is the column, the parameter, the CLI flag
(`--behaves-as`) and the dict key everywhere — never `class` or `cls` in a public name.
`set_status` returns a dict in all three layers. `closed_names` returns `frozenset[str]`
and is the only thing passed to `render_tracker_md(closed=...)`. `list_statuses` returns
`[{"name", "behaves_as"}]` in the repository, MCP, CLI and `overview`'s `statuses` field
identically.
