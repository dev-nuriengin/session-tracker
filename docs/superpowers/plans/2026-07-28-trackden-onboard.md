# `trackden onboard` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `trackden onboard` — a wizard that pulls an existing repo's checklist/guidance files into Trackden (DB items + central guidance folder) behind a review gate, so no project has to be hand-built command by command.

**Architecture:** Three pure layers plus one orchestrator, so almost everything tests without Postgres. `tracker_md.py` owns the `_tracker.md` file format in both directions (parse + render, no I/O). `workspace.py` owns the central `~/.trackden` tree (filesystem only, base path injectable). `onboard.py` scans a repo, applies the review gate, and orchestrates DB + files. `cli.py` stays a thin Typer shell that supplies the interactive prompts. The DB gains one column (`projects.repo_path`) plus bulk-import and read-back helpers in `repository.py`.

**Tech Stack:** Python 3.12+, Typer (CLI), SQLAlchemy 2.0 sync + Postgres/pgvector, uv, pytest (new — dev-only dependency). No new runtime dependencies: parsing and scaffolding are stdlib (`re`, `pathlib`, `subprocess`).

## Global Constraints

- **Spec of record:** `BUILD_NOTES.md` → section **"LOCKED DESIGN — Onboarding (`trackden onboard`)" [DECIDED 2026-07-28]**. Read it before starting.
- **Product name is `Trackden`** — CLI verb `trackden`, MCP server `trackden`. Do not reintroduce `sess` or `session-tracker` in user-facing text (the GitHub repo slug stays `session-tracker`; that is expected).
- **Repos stay untouched.** `onboard` must never create, modify, or delete a file inside the user's repo. It reads only. All writes go to `~/.trackden/` and the DB.
- **Wrapper home is central:** `~/.trackden/projects/<slug>/`, overridable via the `TRACKDEN_HOME` env var (that override exists so tests never touch the real home).
- **Vendor-neutral filenames only** for guidance: `_way-of-work.md`, `_arch.md`, `_decisions.md`, `_tracker.md`. A repo's `CLAUDE.md` / `AGENTS.md` are *inputs to read*, never the source of truth.
- **Domain-agnostic terminology.** The work unit is an **item**. Never "ticket", "task", "issue", or "bill" in code, schema, or CLI output.
- **Nothing is written blind.** Every import passes a review gate; declining must leave the DB unchanged.
- **Statuses inferred from markdown are only `todo` and `done`.** Never guess `doing`/`blocked`/`parked`.
- **Python 3.12+**, sync SQLAlchemy (no async/await), `str | None` union syntax to match the codebase.
- **`_tracker.md` in the central workspace is GENERATED** from the DB and may be overwritten. Guidance files are human-owned and must never be overwritten once they exist.
- **Zero LLM calls.** Onboarding is core, so it stays keyless — no `anthropic`, no `langchain` imports anywhere in this feature.
- **Never commit tracker DATA, only app code.** **Never `git commit`/`git push` without an explicit "yes" from Nuri** (account `dev-nuriengin`). The `git commit` steps below are the plan's intent; ask before running them.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/tracker_md.py` | **Create.** The `_tracker.md` format, both directions: `parse_tracker_md` (text→items) and `render_tracker_md` (items→text). Pure — no DB, no filesystem. |
| `backend/app/workspace.py` | **Create.** The central `~/.trackden` tree: path resolution, project scaffolding, `git init` of the home. Filesystem only. |
| `backend/app/onboard.py` | **Create.** `slugify`, `scan_repo` (auto-detect), and `run_onboard` (the orchestrator: scan → gate → DB → scaffold). The only new module that touches `repository`. |
| `backend/app/models.py` | **Modify.** Add `Project.repo_path`. |
| `backend/app/db.py` | **Modify.** Add an idempotent `ALTER TABLE` step to `init_db()` — `create_all` never alters an existing table. |
| `backend/app/repository.py` | **Modify.** `create_project(..., repo_path=)`, `set_repo_path`, `get_project_by_repo_path`, `import_items`, `items_with_folders`. |
| `backend/app/cli.py` | **Modify.** The `onboard` Typer command: wizard prompts + flags + the review-gate callback. |
| `backend/pyproject.toml` | **Modify.** pytest as a dev dependency group + pytest config. |
| `backend/tests/conftest.py` | **Create.** Isolated-`TRACKDEN_HOME` fixture, DB-cleanup fixture, and auto-skip for `@pytest.mark.db` when Postgres is down. |
| `backend/tests/test_tracker_md.py` | **Create.** Parser + renderer + round-trip. |
| `backend/tests/test_workspace.py` | **Create.** Scaffolding, idempotency, git init. |
| `backend/tests/test_onboard.py` | **Create.** `slugify`, `scan_repo`, `run_onboard` (fake repository — no DB). |
| `backend/tests/test_repository_onboard.py` | **Create.** `@pytest.mark.db` — the real DB round-trip. |
| `backend/tests/test_cli_onboard.py` | **Create.** Typer `CliRunner` — flags, wizard, review gate. |
| `QUICKSTART.md`, `README.md`, `_tracker.md` | **Modify.** Onboarding becomes the documented step 2; tick the build log. |

**Why parse and render share one file:** it is one file format. Splitting the reader from the writer is how the two drift apart.

---

### Task 1: Test harness + `_tracker.md` parser

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/conftest.py`
- Create: `backend/app/tracker_md.py`
- Test: `backend/tests/test_tracker_md.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `tracker_md.TODO = "todo"`, `tracker_md.DONE = "done"`
  - `tracker_md.ParsedItem` — dataclass with `title: str`, `status: str`, `folder: str | None = None`
  - `tracker_md.ParsedTracker` — dataclass with `items: list[ParsedItem]` and a `folders -> list[str]` property (first-seen order, de-duplicated)
  - `tracker_md.parse_tracker_md(text: str) -> ParsedTracker`
  - pytest fixtures `home` (isolated `TRACKDEN_HOME`, returns `Path`) and the `db` marker auto-skip

- [ ] **Step 1: Add pytest as a dev dependency group + pytest config**

In `backend/pyproject.toml`, after the `[project.scripts]` block:

```toml
[dependency-groups]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "db: needs a running Postgres (auto-skipped when it is not reachable)",
]
```

- [ ] **Step 2: Create the shared test fixtures**

Create `backend/tests/conftest.py`:

```python
"""Shared test fixtures.

Onboarding's logic is deliberately pure — text in/out, and a filesystem layer whose
base path is injectable — so nearly all of it tests with no Postgres. The few tests
that DO need the DB are marked `@pytest.mark.db` and auto-skip when it is unreachable,
so `uv run pytest` stays green with docker down.
"""

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated ~/.trackden for one test. Never touches the real home."""
    workspace = tmp_path / ".trackden"
    monkeypatch.setenv("TRACKDEN_HOME", str(workspace))
    return workspace


@pytest.fixture
def temp_slug():
    """A project slug that is deleted from the real DB afterwards (db-marked tests)."""
    slug = "pytest-onboard-tmp"
    yield slug
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug))
        if project is not None:
            db.delete(project)  # cascades to folders / items / sessions / memory
            db.commit()


def _db_reachable() -> bool:
    try:
        from app.db import engine

        with engine.connect():
            return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if _db_reachable():
        return
    skip = pytest.mark.skip(reason="Postgres not reachable — run `docker compose up -d`")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 3: Confirm the harness resolves**

Run: `cd backend && uv run pytest --collect-only`
Expected: exits cleanly having collected 0 tests. (`testpaths = ["tests"]` requires the
directory to exist — which is why the fixtures file is written first. Pointing pytest at a
missing `tests/` errors out instead of reporting an empty run.)

- [ ] **Step 4: Write the failing parser tests**

Create `backend/tests/test_tracker_md.py`:

```python
from app.tracker_md import parse_tracker_md

SAMPLE = """# Trackden — build progress

> Rules: `[x]` done, `[ ]` not. The first `[ ]` item is NEXT.

## Phase 0 — Scaffold & method
- [x] docker-compose: Postgres+pgvector
- [ ] Repo bootstrap

## Phase 4 — Core data model ← THE STORE ✅
- [X] DB engine/session
"""


def test_parse_extracts_title_status_and_folder():
    parsed = parse_tracker_md(SAMPLE)
    assert [(i.title, i.status, i.folder) for i in parsed.items] == [
        ("docker-compose: Postgres+pgvector", "done", "Phase 0 — Scaffold & method"),
        ("Repo bootstrap", "todo", "Phase 0 — Scaffold & method"),
        ("DB engine/session", "done", "Phase 4 — Core data model"),
    ]


def test_parse_lists_folders_in_first_seen_order_without_duplicates():
    assert parse_tracker_md(SAMPLE).folders == [
        "Phase 0 — Scaffold & method",
        "Phase 4 — Core data model",
    ]


def test_parse_ignores_blockquoted_examples_and_prose():
    assert parse_tracker_md("> - [ ] not a real item\njust prose\n").items == []


def test_parse_keeps_items_that_appear_before_any_heading_unfiled():
    parsed = parse_tracker_md("- [ ] loose item\n")
    assert (parsed.items[0].title, parsed.items[0].folder) == ("loose item", None)


def test_parse_accepts_asterisk_bullets():
    assert parse_tracker_md("* [ ] star bullet\n").items[0].title == "star bullet"
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_tracker_md.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tracker_md'` (collection error).

- [ ] **Step 6: Implement the parser**

Create `backend/app/tracker_md.py`:

```python
"""The `_tracker.md` format — parsed one way, rendered the other.

Both directions live here on purpose: it is a single file format, and a reader kept
apart from its writer is a format that drifts. Pure functions — no DB, no filesystem —
which is what makes onboarding's import path cheap to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TODO = "todo"
DONE = "done"

_HEADING = re.compile(r"^\s{0,3}#{2,3}\s+(.*?)\s*$")
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s+(.*?)\s*$")
# hand-written headings trail pointers/markers: "Phase 4 — Core data model ← THE STORE ✅"
_HEADING_NOISE = re.compile(r"\s*(←.*|✅|🔴|⚠️)\s*$")


@dataclass
class ParsedItem:
    """One work item recovered from a markdown checklist."""

    title: str
    status: str
    folder: str | None = None


@dataclass
class ParsedTracker:
    items: list[ParsedItem] = field(default_factory=list)

    @property
    def folders(self) -> list[str]:
        """Folder names in first-seen order, de-duplicated."""
        seen: dict[str, None] = {}
        for item in self.items:
            if item.folder:
                seen.setdefault(item.folder, None)
        return list(seen)


def _clean_heading(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _HEADING_NOISE.sub("", text)
    return text.strip()


def parse_tracker_md(text: str) -> ParsedTracker:
    """Recover items from a hand-written checklist/guidance markdown file.

    `##`/`###` headings become folder names; `- [ ]` / `- [x]` lines become items.
    Blockquotes are skipped so a file's own "Rules: `[x]` done" preamble is not
    imported as work. Only `todo`/`done` are inferred — richer statuses are the
    user's to set, never guessed.
    """
    parsed = ParsedTracker()
    folder: str | None = None
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            continue
        heading = _HEADING.match(line)
        if heading:
            folder = _clean_heading(heading.group(1)) or None
            continue
        box = _CHECKBOX.match(line)
        if box:
            status = DONE if box.group(1).lower() == "x" else TODO
            parsed.items.append(ParsedItem(title=box.group(2), status=status, folder=folder))
    return parsed
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tracker_md.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/tests/conftest.py backend/app/tracker_md.py backend/tests/test_tracker_md.py
git commit -m "feat(onboard): parse markdown checklists into items + add pytest harness"
```

---

### Task 2: `_tracker.md` renderer (the generated mirror)

**Files:**
- Modify: `backend/app/tracker_md.py`
- Test: `backend/tests/test_tracker_md.py` (append)

**Interfaces:**
- Consumes: `tracker_md.parse_tracker_md`, `tracker_md.DONE`, `tracker_md.TODO` (Task 1).
- Produces:
  - `tracker_md.UNFILED = "Items"` — heading used for items with no folder
  - `tracker_md.render_tracker_md(project_name: str, items: list[dict]) -> str` — each dict has keys `title: str`, `status: str`, `folder: str | None`

- [ ] **Step 1: Write the failing renderer tests**

Append to `backend/tests/test_tracker_md.py`:

```python
from app.tracker_md import render_tracker_md

ITEMS = [
    {"title": "Set up the repo", "status": "done", "folder": "Setup"},
    {"title": "Write the parser", "status": "todo", "folder": "Setup"},
    {"title": "Loose end", "status": "todo", "folder": None},
]


def test_render_groups_by_folder_and_marks_status():
    out = render_tracker_md("My Project", ITEMS)
    assert "# My Project — tracker (GENERATED)" in out
    assert "## Setup\n- [x] Set up the repo\n- [ ] Write the parser" in out
    assert "## Items\n- [ ] Loose end" in out


def test_render_reports_progress():
    assert "**Progress:** 1 / 3 done." in render_tracker_md("My Project", ITEMS)


def test_render_warns_against_hand_editing():
    assert "Do not edit by hand" in render_tracker_md("Empty", [])


def test_render_handles_no_items():
    out = render_tracker_md("Empty", [])
    assert "**Progress:** 0 / 0 done." in out


def test_render_round_trips_through_the_parser():
    reparsed = parse_tracker_md(render_tracker_md("P", ITEMS))
    assert [(i.title, i.status, i.folder) for i in reparsed.items] == [
        ("Set up the repo", "done", "Setup"),
        ("Write the parser", "todo", "Setup"),
        ("Loose end", "todo", "Items"),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_tracker_md.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_tracker_md' from 'app.tracker_md'`.

- [ ] **Step 3: Implement the renderer**

Append to `backend/app/tracker_md.py`:

```python
UNFILED = "Items"

_GENERATED_BANNER = (
    "<!-- Generated by `trackden` from the database. Do not edit by hand:\n"
    "     your edits will be overwritten. Change state via the CLI or the MCP tools. -->"
)


def render_tracker_md(project_name: str, items: list[dict]) -> str:
    """Render the DB's items as the generated `_tracker.md` mirror.

    Derived output, never a source of truth — the banner says so to whoever opens it.
    Items are grouped under their folder name; unfiled items go under `UNFILED`.
    """
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item.get("folder") or UNFILED, []).append(item)

    done = sum(1 for item in items if item.get("status") == DONE)
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
            box = "x" if item.get("status") == DONE else " "
            lines.append(f"- [{box}] {item['title']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tracker_md.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tracker_md.py backend/tests/test_tracker_md.py
git commit -m "feat(onboard): render the generated _tracker.md mirror from DB items"
```

---

### Task 3: The central `~/.trackden` workspace

**Files:**
- Create: `backend/app/workspace.py`
- Test: `backend/tests/test_workspace.py`

**Interfaces:**
- Consumes: the `home` fixture from `tests/conftest.py` (Task 1).
- Produces:
  - `workspace.HOME_ENV = "TRACKDEN_HOME"`, `workspace.TRACKER_FILE = "_tracker.md"`
  - `workspace.trackden_home() -> Path`
  - `workspace.project_dir(slug: str, home: Path | None = None) -> Path`
  - `workspace.scaffold_project(slug: str, *, name: str | None = None, way_of_work: str | None = None, tracker_md: str = "", home: Path | None = None) -> list[Path]`
  - `workspace.ensure_home_git(home: Path | None = None) -> bool`

- [ ] **Step 1: Write the failing workspace tests**

Create `backend/tests/test_workspace.py`:

```python
from app.workspace import ensure_home_git, project_dir, scaffold_project, trackden_home


def test_trackden_home_honours_the_env_override(home):
    assert trackden_home() == home


def test_project_dir_is_projects_slash_slug(home):
    assert project_dir("my-proj") == home / "projects" / "my-proj"


def test_scaffold_creates_three_guidance_files_plus_the_mirror(home):
    written = scaffold_project("my-proj", name="My Proj", tracker_md="# mirror\n")
    assert {path.name for path in written} == {
        "_way-of-work.md",
        "_arch.md",
        "_decisions.md",
        "_tracker.md",
    }
    for name in ("_way-of-work.md", "_arch.md", "_decisions.md", "_tracker.md"):
        assert (project_dir("my-proj") / name).exists()


def test_scaffold_seeds_way_of_work_from_supplied_text(home):
    scaffold_project("p", way_of_work="# rules lifted from the repo\n")
    assert (project_dir("p") / "_way-of-work.md").read_text() == "# rules lifted from the repo\n"


def test_scaffold_never_overwrites_human_owned_guidance(home):
    scaffold_project("p", way_of_work="original\n")
    scaffold_project("p", way_of_work="SHOULD NOT WIN\n")
    assert (project_dir("p") / "_way-of-work.md").read_text() == "original\n"


def test_scaffold_does_regenerate_the_tracker_mirror(home):
    scaffold_project("p", tracker_md="v1\n")
    scaffold_project("p", tracker_md="v2\n")
    assert (project_dir("p") / "_tracker.md").read_text() == "v2\n"


def test_scaffold_reports_only_newly_written_guidance_on_a_rerun(home):
    scaffold_project("p")
    written = scaffold_project("p")
    assert [path.name for path in written] == ["_tracker.md"]


def test_ensure_home_git_initialises_the_workspace_repo(home):
    assert ensure_home_git() is True
    assert (home / ".git").exists()


def test_ensure_home_git_is_idempotent(home):
    ensure_home_git()
    assert ensure_home_git() is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.workspace'`.

- [ ] **Step 3: Implement the workspace layer**

Create `backend/app/workspace.py`:

```python
"""The central Trackden workspace — `~/.trackden`.

The user's repos stay untouched: guidance lives here and reaches agents over MCP.
One folder per project, and the home itself is a git repo, so a single `git push`
backs up every project's guidance. `TRACKDEN_HOME` overrides the location — that is
what lets tests (and multiple profiles) run without touching the real home.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HOME_ENV = "TRACKDEN_HOME"
TRACKER_FILE = "_tracker.md"

_WAY_OF_WORK_TEMPLATE = """# Way of work — {name}

> How this project is worked on. Human-written; agents read it over MCP.
> Vendor-neutral on purpose — no agent-specific file is the source of truth.

## Conventions

- (naming, branching, review expectations…)

## Definition of done

- (tests, docs, deploy…)
"""

_ARCH_TEMPLATE = """# Architecture — {name}

> The shape of the system: the pieces, and how they talk. Keep it current.

## Components

- (service / module → responsibility)

## Data

- (stores, schemas, ownership)
"""

_DECISIONS_TEMPLATE = """# Decisions — {name}

> One entry per decision: what was chosen, and **why**. Append; never rewrite history.

## (date) — (the decision)

- **Chose:**
- **Because:**
- **Rejected:**
"""


def trackden_home() -> Path:
    """The workspace root — `$TRACKDEN_HOME`, else `~/.trackden`."""
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else Path.home() / ".trackden"


def project_dir(slug: str, home: Path | None = None) -> Path:
    return (home or trackden_home()) / "projects" / slug


def scaffold_project(
    slug: str,
    *,
    name: str | None = None,
    way_of_work: str | None = None,
    tracker_md: str = "",
    home: Path | None = None,
) -> list[Path]:
    """Create (or top up) a project's guidance folder. Returns the paths written.

    Guidance files are human-owned: an existing one is left exactly as it is, so
    re-onboarding can never destroy written knowledge. `_tracker.md` IS rewritten —
    it is generated from the DB and holds nothing a human authored.
    """
    directory = project_dir(slug, home)
    directory.mkdir(parents=True, exist_ok=True)
    display = name or slug

    guidance = {
        "_way-of-work.md": way_of_work or _WAY_OF_WORK_TEMPLATE.format(name=display),
        "_arch.md": _ARCH_TEMPLATE.format(name=display),
        "_decisions.md": _DECISIONS_TEMPLATE.format(name=display),
    }

    written: list[Path] = []
    for filename, content in guidance.items():
        path = directory / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            written.append(path)

    mirror = directory / TRACKER_FILE
    mirror.write_text(tracker_md, encoding="utf-8")
    written.append(mirror)
    return written


def ensure_home_git(home: Path | None = None) -> bool:
    """Make the workspace a git repo so one push backs up all guidance.

    Returns False when git is unavailable — onboarding must still succeed without it.
    """
    root = home or trackden_home()
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".git").exists():
        return True
    try:
        subprocess.run(
            ["git", "init", "--quiet", str(root)], check=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workspace.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workspace.py backend/tests/test_workspace.py
git commit -m "feat(onboard): scaffold the central ~/.trackden guidance workspace"
```

---

### Task 4: DB support — `repo_path`, bulk import, read-back

**Files:**
- Modify: `backend/app/models.py:28-38` (the `Project` class)
- Modify: `backend/app/db.py:32-38` (`init_db`)
- Modify: `backend/app/repository.py:33-42` (`create_project`) and append new functions
- Test: `backend/tests/test_repository_onboard.py`

**Interfaces:**
- Consumes: `tracker_md.TODO`, `tracker_md.DONE` (Task 1); the `temp_slug` fixture (Task 1).
- Produces:
  - `models.Project.repo_path: Mapped[str | None]`
  - `repository.create_project(slug: str, name: str | None = None, kind: str = "personal", client: str | None = None, repo_path: str | None = None) -> bool`
  - `repository.set_repo_path(slug: str, repo_path: str) -> bool`
  - `repository.get_project_by_repo_path(repo_path: str) -> models.Project | None`
  - `repository.import_items(slug: str, items: list[dict]) -> int` — each dict has `title`, `status`, `folder`; creates folders by name; returns the count of items created
  - `repository.items_with_folders(slug: str) -> list[dict]` — `{"title", "status", "folder"}`, ready to hand to `render_tracker_md`

- [ ] **Step 1: Write the failing DB tests**

Create `backend/tests/test_repository_onboard.py`:

```python
"""The real Postgres round-trip. Auto-skipped when the DB is down (see conftest)."""

import pytest

from app import repository
from app.db import init_db


@pytest.fixture(autouse=True)
def _schema():
    init_db()


@pytest.mark.db
def test_create_project_stores_the_repo_path(temp_slug, tmp_path):
    assert repository.create_project(temp_slug, repo_path=str(tmp_path)) is True
    assert repository.get_project(temp_slug).repo_path == str(tmp_path.resolve())


@pytest.mark.db
def test_project_is_findable_by_a_denormalised_repo_path(temp_slug, tmp_path):
    repository.create_project(temp_slug, repo_path=str(tmp_path))
    found = repository.get_project_by_repo_path(f"{tmp_path}/")
    assert found is not None and found.slug == temp_slug


@pytest.mark.db
def test_unknown_repo_path_finds_nothing(tmp_path):
    assert repository.get_project_by_repo_path(str(tmp_path / "nope")) is None


@pytest.mark.db
def test_set_repo_path_updates_an_existing_project(temp_slug, tmp_path):
    repository.create_project(temp_slug)
    assert repository.set_repo_path(temp_slug, str(tmp_path)) is True
    assert repository.get_project(temp_slug).repo_path == str(tmp_path.resolve())


@pytest.mark.db
def test_set_repo_path_on_an_unknown_project_returns_false(tmp_path):
    assert repository.set_repo_path("no-such-project-xyz", str(tmp_path)) is False


@pytest.mark.db
def test_import_items_creates_folders_by_name_and_keeps_order(temp_slug):
    repository.create_project(temp_slug)
    count = repository.import_items(
        temp_slug,
        [
            {"title": "first", "status": "done", "folder": "Phase 0"},
            {"title": "second", "status": "todo", "folder": "Phase 0"},
            {"title": "third", "status": "todo", "folder": "Phase 1"},
            {"title": "unfiled", "status": "todo", "folder": None},
        ],
    )
    assert count == 4
    assert repository.items_with_folders(temp_slug) == [
        {"title": "first", "status": "done", "folder": "Phase 0"},
        {"title": "second", "status": "todo", "folder": "Phase 0"},
        {"title": "third", "status": "todo", "folder": "Phase 1"},
        {"title": "unfiled", "status": "todo", "folder": None},
    ]


@pytest.mark.db
def test_import_items_rejects_statuses_it_should_never_invent(temp_slug):
    repository.create_project(temp_slug)
    count = repository.import_items(
        temp_slug, [{"title": "weird", "status": "blocked", "folder": None}]
    )
    assert count == 1
    assert repository.items_with_folders(temp_slug)[0]["status"] == "todo"


@pytest.mark.db
def test_import_items_on_an_unknown_project_writes_nothing(temp_slug):
    assert repository.import_items("no-such-project-xyz", [{"title": "x", "status": "todo", "folder": None}]) == 0


@pytest.mark.db
def test_items_with_folders_on_an_unknown_project_is_empty():
    assert repository.items_with_folders("no-such-project-xyz") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && docker compose -f ../docker-compose.yml up -d db && uv run pytest tests/test_repository_onboard.py -v`
Expected: FAIL — `AttributeError: module 'app.repository' has no attribute 'get_project_by_repo_path'`.
(If Postgres will not start, the tests SKIP instead — that is the harness working, but you must get the DB up to finish this task.)

- [ ] **Step 3: Add the `repo_path` column to the model**

In `backend/app/models.py`, inside `class Project`, after the `client` column:

```python
    client: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # absolute, resolved path of the repo this project lives in (set by `trackden onboard`);
    # this is what later lets a tool map "the cwd I am in" → "this project".
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 4: Make `init_db` actually add the column on an existing database**

In `backend/app/db.py`, replace the body of `init_db` and add `_migrate` below it:

```python
def init_db() -> None:
    """Create tables if they don't exist (dev convenience; real migrations later)."""
    from . import models  # noqa: F401 — import registers the models on Base.metadata

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))  # pgvector
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Idempotent column top-ups.

    `create_all` creates missing TABLES but never alters an existing one, so a column
    added to a model would silently never reach a database that already has the table.
    Until real migrations land, each additive column gets one `IF NOT EXISTS` line here.
    """
    statements = (
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_path VARCHAR(500)",
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
```

- [ ] **Step 5: Extend the repository**

In `backend/app/repository.py`, add to the imports at the top:

```python
from pathlib import Path

from sqlalchemy import func, select

from . import models
from .data import PROJECTS, TRACKERS  # stub — used ONLY to seed the DB once
from .db import SessionLocal, init_db
from .embeddings import embed
from .tracker_md import DONE, TODO
```

Add the path helper just under the imports (above `# ---- projects ----`):

```python
def _norm_path(raw: str) -> str:
    """One canonical spelling of a filesystem path, so cwd→project lookups match
    regardless of trailing slashes, `~`, or symlinks."""
    return str(Path(raw).expanduser().resolve())
```

Replace `create_project` with:

```python
def create_project(slug: str, name: str | None = None, kind: str = "personal",
                   client: str | None = None, repo_path: str | None = None) -> bool:
    """Create a project. Returns False if the slug already exists."""
    slug = slug.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(models.Project).where(models.Project.slug == slug)):
            return False
        db.add(models.Project(
            slug=slug,
            name=name or slug,
            kind=kind,
            client=client,
            repo_path=_norm_path(repo_path) if repo_path else None,
        ))
        db.commit()
        return True
```

Append these to the end of the `# ---- projects ----` section (after `list_items`):

```python
def set_repo_path(slug: str, repo_path: str) -> bool:
    """Point an existing project at a repo. False if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return False
        project.repo_path = _norm_path(repo_path)
        db.commit()
        return True


def get_project_by_repo_path(repo_path: str) -> models.Project | None:
    """Which project lives in this directory? (Powers cwd→project detection.)"""
    with SessionLocal() as db:
        return db.scalar(
            select(models.Project).where(models.Project.repo_path == _norm_path(repo_path))
        )


def import_items(slug: str, items: list[dict]) -> int:
    """Bulk-create items from parsed markdown, creating folders by name as needed.

    Each dict is `{"title", "status", "folder"}`. Any status other than todo/done is
    coerced to todo — richer statuses are the user's to set, never inferred from a file.
    Returns how many items were created (0 if the project is unknown).
    """
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return 0

        folders: dict[str, int] = {}
        created = 0
        for position, raw in enumerate(items):
            name = raw.get("folder")
            folder_id = None
            if name:
                if name not in folders:
                    folder = models.Folder(
                        project_id=project.id, name=name, position=len(folders)
                    )
                    db.add(folder)
                    db.flush()
                    folders[name] = folder.id
                folder_id = folders[name]
            status = raw.get("status") if raw.get("status") in (TODO, DONE) else TODO
            db.add(models.Item(
                project_id=project.id,
                folder_id=folder_id,
                title=raw["title"],
                status=status,
                position=position,
            ))
            created += 1
        db.commit()
        return created


def items_with_folders(slug: str) -> list[dict]:
    """Every item plus its folder NAME — the shape `render_tracker_md` wants."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return []
        rows = db.execute(
            select(models.Item.title, models.Item.status, models.Folder.name)
            .outerjoin(models.Folder, models.Item.folder_id == models.Folder.id)
            .where(models.Item.project_id == project.id)
            .order_by(models.Item.position, models.Item.id)
        ).all()
        return [{"title": title, "status": status, "folder": folder}
                for title, status, folder in rows]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_repository_onboard.py -v`
Expected: 9 passed.

- [ ] **Step 7: Run the whole suite — the column change touches shared code**

Run: `cd backend && uv run pytest -v`
Expected: all passed (24 tests so far).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/app/repository.py backend/tests/test_repository_onboard.py
git commit -m "feat(onboard): store repo_path on projects, bulk-import items, read back with folders"
```

---

### Task 5: Auto-detect — scan a repo for importable files

**Files:**
- Create: `backend/app/onboard.py`
- Test: `backend/tests/test_onboard.py`

**Interfaces:**
- Consumes: `tracker_md.parse_tracker_md`, `tracker_md.ParsedTracker` (Task 1).
- Produces:
  - `onboard.DEFAULT_SCAN_GLOBS: tuple[str, ...]`
  - `onboard.GUIDANCE_FILES: frozenset[str]` — `{"CLAUDE.md", "AGENTS.md"}`
  - `onboard.ScanHit` — dataclass with `path: Path`, `relpath: str`, `parsed: ParsedTracker`, `is_guidance: bool`, `text: str`
  - `onboard.slugify(text: str) -> str`
  - `onboard.scan_repo(repo: Path | str, globs: tuple[str, ...] = DEFAULT_SCAN_GLOBS) -> list[ScanHit]`

- [ ] **Step 1: Write the failing scan + slugify tests**

Create `backend/tests/test_onboard.py`:

```python
import pytest

from app.onboard import scan_repo, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My Project", "my-project"),
        ("  Spaced  Out  ", "spaced-out"),
        ("Hînbûna Kurdî", "hinbuna-kurdi"),
        ("weird__chars!!", "weird-chars"),
        ("already-fine", "already-fine"),
        ("---", ""),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


@pytest.fixture
def fake_repo(tmp_path):
    (tmp_path / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    (tmp_path / "CLAUDE.md").write_text("# rules\n\nBe careful.\n", encoding="utf-8")
    (tmp_path / "main-plans").mkdir()
    (tmp_path / "main-plans" / "_tracker.md").write_text(
        "- [ ] planned thing\n", encoding="utf-8"
    )
    noisy = tmp_path / "node_modules" / "pkg"
    noisy.mkdir(parents=True)
    (noisy / "_tracker.md").write_text("- [ ] vendored junk\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("- [ ] not scanned\n", encoding="utf-8")
    return tmp_path


def test_scan_finds_tracker_files_and_guidance(fake_repo):
    hits = scan_repo(fake_repo)
    assert {hit.relpath for hit in hits} == {
        "_tracker.md",
        "main-plans/_tracker.md",
        "CLAUDE.md",
    }


def test_scan_skips_vendored_directories(fake_repo):
    assert all("node_modules" not in hit.relpath for hit in scan_repo(fake_repo))


def test_scan_ignores_files_not_on_the_scan_list(fake_repo):
    assert all(hit.relpath != "README.md" for hit in scan_repo(fake_repo))


def test_scan_parses_items_and_flags_guidance(fake_repo):
    hits = {hit.relpath: hit for hit in scan_repo(fake_repo)}
    assert [item.title for item in hits["_tracker.md"].parsed.items] == [
        "done thing",
        "open thing",
    ]
    assert hits["CLAUDE.md"].is_guidance is True
    assert hits["_tracker.md"].is_guidance is False
    assert hits["CLAUDE.md"].text == "# rules\n\nBe careful.\n"


def test_scan_of_a_bare_repo_returns_nothing(tmp_path):
    assert scan_repo(tmp_path) == []


def test_scan_of_a_missing_path_returns_nothing(tmp_path):
    assert scan_repo(tmp_path / "does-not-exist") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_onboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.onboard'`.

- [ ] **Step 3: Implement `slugify` and `scan_repo`**

Create `backend/app/onboard.py`:

```python
"""`trackden onboard` — how a project gets INTO Trackden.

Two halves, kept apart on purpose:

* `scan_repo` READS a repo and proposes what could be imported. It never writes.
* `run_onboard` (next task) decides and writes — DB items + the central guidance folder.

Between them sits a review gate supplied by the caller, which is what keeps
auto-detection safe: a proposal a human confirmed, not a parse trusted blindly.
The user's repo is never modified.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .tracker_md import ParsedTracker, parse_tracker_md

# Priority order: the most explicit tracker locations first, guidance last.
DEFAULT_SCAN_GLOBS: tuple[str, ...] = (
    "_tracker.md",
    "main-plans/_tracker.md",
    "_tickets-and-status/_tracker.md",
    "**/_tracker.md",
    "CLAUDE.md",
    "AGENTS.md",
)

# Per-vendor files: read as INPUT to seed vendor-neutral guidance, never a source of truth.
GUIDANCE_FILES = frozenset({"CLAUDE.md", "AGENTS.md"})

_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass
class ScanHit:
    """One importable file found in a repo, already parsed."""

    path: Path
    relpath: str
    parsed: ParsedTracker
    is_guidance: bool
    text: str


def slugify(text: str) -> str:
    """A filesystem- and URL-safe project slug. Accents are folded, not dropped."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _SLUG_STRIP.sub("-", folded.lower()).strip("-")


def scan_repo(
    repo: Path | str, globs: tuple[str, ...] = DEFAULT_SCAN_GLOBS
) -> list[ScanHit]:
    """Find checklist/guidance files worth importing. Read-only, best-effort.

    Returns hits in scan-list priority order, de-duplicated by real path. A file is
    a hit if it yielded items, or if it is a guidance file (which can seed the
    project's way-of-work even when it holds no checkboxes).
    """
    root = Path(repo).expanduser()
    if not root.is_dir():
        return []
    root = root.resolve()

    hits: list[ScanHit] = []
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if _SKIP_DIRS & set(relative.parts[:-1]):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # unreadable input is not a reason to fail onboarding
            parsed = parse_tracker_md(text)
            is_guidance = path.name in GUIDANCE_FILES
            if parsed.items or is_guidance:
                hits.append(ScanHit(
                    path=path,
                    relpath=relative.as_posix(),
                    parsed=parsed,
                    is_guidance=is_guidance,
                    text=text,
                ))
    return hits
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_onboard.py -v`
Expected: 12 passed (6 parametrized `slugify` cases + 6 scan tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/onboard.py backend/tests/test_onboard.py
git commit -m "feat(onboard): read-only repo scan for tracker and guidance files"
```

---

### Task 6: The orchestrator — `run_onboard`

**Files:**
- Modify: `backend/app/onboard.py` (append)
- Test: `backend/tests/test_onboard.py` (append)

**Interfaces:**
- Consumes: `onboard.scan_repo`, `onboard.slugify`, `onboard.ScanHit` (Task 5); `repository.create_project`, `repository.set_repo_path`, `repository.import_items`, `repository.items_with_folders` (Task 4); `tracker_md.render_tracker_md` (Task 2); `workspace.scaffold_project`, `workspace.ensure_home_git` (Task 3).
- Produces:
  - `onboard.Confirm` — type alias `Callable[[ScanHit], list[ParsedItem] | None]`; return the items to import (possibly a subset), or `None` to skip the file
  - `onboard.OnboardResult` — dataclass with `slug: str`, `name: str`, `created: bool`, `imported: int`, `sources: list[str]`, `files: list[Path]`, `git_ready: bool`
  - `onboard.run_onboard(*, slug: str, name: str | None = None, kind: str = "personal", client: str | None = None, repo: Path | str | None = None, import_items: bool = True, confirm: Confirm | None = None, home: Path | None = None) -> OnboardResult`

- [ ] **Step 1: Write the failing orchestrator tests**

Append to `backend/tests/test_onboard.py`:

```python
from pathlib import Path

from app import onboard as onboard_mod
from app.onboard import run_onboard
from app.workspace import project_dir


@pytest.fixture
def fake_db(monkeypatch):
    """Stand in for the repository so the orchestrator tests need no Postgres."""

    state = {"projects": {}, "items": [], "repo_paths": {}}

    def create_project(slug, name=None, kind="personal", client=None, repo_path=None):
        if slug in state["projects"]:
            return False
        state["projects"][slug] = {"name": name or slug, "kind": kind, "client": client}
        state["repo_paths"][slug] = repo_path
        return True

    def set_repo_path(slug, repo_path):
        if slug not in state["projects"]:
            return False
        state["repo_paths"][slug] = repo_path
        return True

    def import_items(slug, items):
        if slug not in state["projects"]:
            return 0
        state["items"].extend(items)
        return len(items)

    def items_with_folders(slug):
        return list(state["items"]) if slug in state["projects"] else []

    for name, func in [
        ("create_project", create_project),
        ("set_repo_path", set_repo_path),
        ("import_items", import_items),
        ("items_with_folders", items_with_folders),
    ]:
        monkeypatch.setattr(onboard_mod.repository, name, func)
    return state


def test_onboard_creates_the_project_and_scaffolds_guidance(home, fake_db, tmp_path):
    result = run_onboard(slug="my-proj", name="My Proj", repo=None)
    assert result.created is True
    assert result.slug == "my-proj"
    assert (project_dir("my-proj") / "_way-of-work.md").exists()
    assert (project_dir("my-proj") / "_tracker.md").exists()


def test_onboard_slugifies_whatever_it_is_given(home, fake_db):
    assert run_onboard(slug="My Proj!").slug == "my-proj"


def test_onboard_imports_every_found_item_when_nothing_gates_it(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo)
    assert result.imported == 3  # 2 from _tracker.md + 1 from main-plans/_tracker.md
    assert sorted(result.sources) == ["_tracker.md", "main-plans/_tracker.md"]


def test_onboard_respects_a_gate_that_declines(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo, confirm=lambda hit: None)
    assert result.imported == 0
    assert result.sources == []


def test_onboard_respects_a_gate_that_edits_the_selection(home, fake_db, fake_repo):
    result = run_onboard(
        slug="p", repo=fake_repo, confirm=lambda hit: list(hit.parsed.items)[:1]
    )
    assert result.imported == 2  # one kept from each of the two tracker files


def test_onboard_can_skip_importing_entirely(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo, import_items=False)
    assert result.imported == 0


def test_onboard_seeds_way_of_work_from_the_repos_guidance_file(home, fake_db, fake_repo):
    run_onboard(slug="p", repo=fake_repo)
    assert (project_dir("p") / "_way-of-work.md").read_text() == "# rules\n\nBe careful.\n"


def test_onboard_writes_the_generated_mirror_from_db_state(home, fake_db, fake_repo):
    run_onboard(slug="p", name="P", repo=fake_repo)
    mirror = (project_dir("p") / "_tracker.md").read_text()
    assert "# P — tracker (GENERATED)" in mirror
    assert "- [ ] open thing" in mirror


def test_onboard_never_touches_the_users_repo(home, fake_db, fake_repo):
    before = {path: path.read_bytes() for path in fake_repo.rglob("*") if path.is_file()}
    run_onboard(slug="p", repo=fake_repo)
    after = {path: path.read_bytes() for path in fake_repo.rglob("*") if path.is_file()}
    assert before == after


def test_onboard_updates_repo_path_when_the_project_already_exists(home, fake_db, fake_repo):
    run_onboard(slug="p", repo=None)
    result = run_onboard(slug="p", repo=fake_repo)
    assert result.created is False
    assert fake_db["repo_paths"]["p"] == str(Path(fake_repo).resolve())


def test_onboard_initialises_the_workspace_git_repo(home, fake_db):
    assert run_onboard(slug="p").git_ready is True
    assert (home / ".git").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_onboard.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_onboard' from 'app.onboard'`.

- [ ] **Step 3: Implement the orchestrator**

Append to `backend/app/onboard.py` (and extend its imports):

```python
from collections.abc import Callable

from . import repository, workspace
from .tracker_md import ParsedItem, ParsedTracker, parse_tracker_md, render_tracker_md
```

```python
# The review gate. Given one scanned file, return the items to import — all of them,
# a subset, or None to skip it. The CLI supplies the interactive version; passing None
# means "no gate, take everything", which is what `--yes` and scripted runs use.
Confirm = Callable[[ScanHit], list[ParsedItem] | None]


@dataclass
class OnboardResult:
    """What onboarding actually did — printed as the closing summary."""

    slug: str
    name: str
    created: bool
    imported: int
    sources: list[str]
    files: list[Path]
    git_ready: bool


def run_onboard(
    *,
    slug: str,
    name: str | None = None,
    kind: str = "personal",
    client: str | None = None,
    repo: Path | str | None = None,
    import_items: bool = True,
    confirm: Confirm | None = None,
    home: Path | None = None,
) -> OnboardResult:
    """Identify → scan → gate → DB → scaffold → summarise.

    Writes only to the DB and the central workspace. The repo is read, never written.
    Re-running is safe: an existing project keeps its guidance files and simply has
    its `repo_path` refreshed and its `_tracker.md` mirror regenerated.
    """
    slug = slugify(slug)
    display = name or slug
    repo_path = str(Path(repo).expanduser().resolve()) if repo else None

    hits = scan_repo(repo) if (repo_path and import_items) else []

    chosen: list[ParsedItem] = []
    sources: list[str] = []
    way_of_work: str | None = None
    for hit in hits:
        if hit.is_guidance and way_of_work is None:
            way_of_work = hit.text
        if not hit.parsed.items:
            continue
        selected = list(hit.parsed.items) if confirm is None else confirm(hit)
        if selected:
            chosen.extend(selected)
            sources.append(hit.relpath)

    created = repository.create_project(
        slug, name=display, kind=kind, client=client, repo_path=repo_path
    )
    if not created and repo_path:
        repository.set_repo_path(slug, repo_path)

    imported = 0
    if chosen:
        imported = repository.import_items(slug, [
            {"title": item.title, "status": item.status, "folder": item.folder}
            for item in chosen
        ])

    mirror = render_tracker_md(display, repository.items_with_folders(slug))
    files = workspace.scaffold_project(
        slug, name=display, way_of_work=way_of_work, tracker_md=mirror, home=home
    )
    git_ready = workspace.ensure_home_git(home)

    return OnboardResult(
        slug=slug,
        name=display,
        created=created,
        imported=imported,
        sources=sources,
        files=files,
        git_ready=git_ready,
    )
```

Note: `parse_tracker_md` and `ParsedTracker` are already imported by Task 5 — keep one import line, do not duplicate it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_onboard.py -v`
Expected: 23 passed.

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && uv run pytest -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/onboard.py backend/tests/test_onboard.py
git commit -m "feat(onboard): orchestrate scan, review gate, DB import and scaffolding"
```

---

### Task 7: The `trackden onboard` CLI command

**Files:**
- Modify: `backend/app/cli.py` (append the command; extend imports)
- Test: `backend/tests/test_cli_onboard.py`

**Interfaces:**
- Consumes: `onboard.run_onboard`, `onboard.slugify`, `onboard.ScanHit`, `onboard.OnboardResult` (Tasks 5–6).
- Produces: the `trackden onboard` command — `trackden onboard` (wizard) and `trackden onboard <slug> [--name] [--kind] [--client] [--repo] [--no-import] [--yes]`.

- [ ] **Step 1: Write the failing CLI tests**

Create `backend/tests/test_cli_onboard.py`:

```python
import pytest
from typer.testing import CliRunner

from app import onboard as onboard_mod
from app.cli import app

runner = CliRunner()


@pytest.fixture
def fake_repo_with_items(tmp_path):
    (tmp_path / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def fake_db(monkeypatch):
    state = {"projects": set(), "items": []}

    def create_project(slug, name=None, kind="personal", client=None, repo_path=None):
        if slug in state["projects"]:
            return False
        state["projects"].add(slug)
        return True

    def import_items(slug, items):
        state["items"].extend(items)
        return len(items)

    monkeypatch.setattr(onboard_mod.repository, "create_project", create_project)
    monkeypatch.setattr(onboard_mod.repository, "set_repo_path", lambda s, p: True)
    monkeypatch.setattr(onboard_mod.repository, "import_items", import_items)
    monkeypatch.setattr(
        onboard_mod.repository, "items_with_folders", lambda slug: list(state["items"])
    )
    return state


def test_onboard_with_flags_is_non_interactive(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--name", "My Proj", "--repo", str(fake_repo_with_items), "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert "my-proj" in result.output
    assert "2" in result.output  # two items imported
    assert state_has(fake_db, "open thing")


def state_has(state, title):
    return any(item["title"] == title for item in state["items"])


def test_onboard_review_gate_can_decline(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Found 2 items" in result.output
    assert fake_db["items"] == []


def test_onboard_review_gate_can_edit_the_selection(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items)],
        input="edit\n2\n",
    )
    assert result.exit_code == 0, result.output
    assert [item["title"] for item in fake_db["items"]] == ["open thing"]


def test_onboard_no_import_skips_the_scan(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items), "--no-import"],
    )
    assert result.exit_code == 0, result.output
    assert "Found" not in result.output
    assert fake_db["items"] == []


def test_onboard_wizard_prompts_when_no_slug_is_given(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard"],
        input=f"My Proj\n\npersonal\n{fake_repo_with_items}\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert "my-proj" in result.output


def test_onboard_prints_the_next_step(home, fake_db):
    result = runner.invoke(app, ["onboard", "my-proj", "--no-import"])
    assert "trackden show my-proj" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli_onboard.py -v`
Expected: FAIL — every test exits non-zero with `No such command 'onboard'`.

- [ ] **Step 3: Implement the CLI command**

In `backend/app/cli.py`, extend the imports at the top:

```python
from pathlib import Path

import typer

from . import onboard as onboard_mod
from . import repository
```

Append the command (before the `if __name__ == "__main__":` block):

```python
_GATE_PREVIEW = 10  # show at most this many items before asking


def _review_gate(hit: onboard_mod.ScanHit) -> list[onboard_mod.ParsedItem] | None:
    """Interactive review gate — nothing is imported without a yes.

    y    → import everything found in this file
    n    → skip this file
    edit → pick which numbered items to import
    """
    items = list(hit.parsed.items)
    typer.echo(f"\nFound {len(items)} items in {hit.relpath}")
    for number, item in enumerate(items[:_GATE_PREVIEW], 1):
        typer.echo(f"   {number:>2}. [{item.status}] {item.title}")
    if len(items) > _GATE_PREVIEW:
        typer.echo(f"   … and {len(items) - _GATE_PREVIEW} more")

    answer = typer.prompt("Import? (y / n / edit)", default="y").strip().lower()
    if answer.startswith("n"):
        typer.echo("  skipped")
        return None
    if answer.startswith("e"):
        picked = typer.prompt(
            "Numbers to import (comma-separated, blank = all)", default=""
        )
        wanted = {int(part) for part in picked.replace(" ", "").split(",") if part.isdigit()}
        if wanted:
            return [item for number, item in enumerate(items, 1) if number in wanted]
    return items


@app.command()
def onboard(
    slug: str = typer.Argument(None, help="Project slug (omit for the interactive wizard)"),
    name: str = typer.Option(None, help="Display name"),
    kind: str = typer.Option("personal", help="personal | client"),
    client: str = typer.Option(None, help="Client name (for client projects)"),
    repo: str = typer.Option(None, help="Repo path to scan (default: the current directory)"),
    no_import: bool = typer.Option(False, "--no-import", help="Skip auto-detect entirely"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Import everything found, no prompts"),
):
    """Bring a project into Trackden: import what exists, scaffold the rest.

    Reads the repo (never writes to it), asks before importing anything, then creates
    the project in the DB and its guidance folder under ~/.trackden.
    """
    wizard = slug is None
    if wizard:
        name = name or typer.prompt("Project name")
        slug = typer.prompt("Slug", default=onboard_mod.slugify(name))
        kind = typer.prompt("Kind (personal | client)", default=kind)
        if kind == "client" and not client:
            client = typer.prompt("Client name", default="") or None
        repo = repo or typer.prompt("Repo path to scan", default=str(Path.cwd()))

    if repo is None and not no_import:
        cwd = Path.cwd()
        repo = str(cwd) if (cwd / ".git").exists() else None

    result = onboard_mod.run_onboard(
        slug=slug,
        name=name,
        kind=kind,
        client=client,
        repo=repo,
        import_items=not no_import,
        confirm=None if yes else _review_gate,
    )

    typer.echo("")
    typer.echo(f"✓ project '{result.slug}' — {'created' if result.created else 'already existed, updated'}")
    typer.echo(f"  items imported : {result.imported}" + (
        f"  (from {', '.join(result.sources)})" if result.sources else ""
    ))
    typer.echo("  guidance       :")
    for path in result.files:
        typer.echo(f"      • {path}")
    if not result.git_ready:
        typer.echo("  ⚠ workspace is not a git repo (git unavailable) — guidance is unversioned")
    typer.echo(f"\nNext:  trackden show {result.slug}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli_onboard.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the whole suite plus a real smoke test**

Run: `cd backend && uv run pytest -v`
Expected: all passed.

Then, with Postgres up, onboard this very repo and confirm the real output:

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
docker compose up -d db
cd backend && uv run trackden onboard trackden-smoke --name "Smoke Test" --repo .. --no-import
uv run trackden show trackden-smoke
ls ~/.trackden/projects/trackden-smoke/
```
Expected: the project is created, four files exist in the workspace, `~/.trackden/.git` exists, and **nothing in the repo changed** (`git status` is clean apart from the new source files).

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli.py backend/tests/test_cli_onboard.py
git commit -m "feat(onboard): add the trackden onboard command with an interactive review gate"
```

---

### Task 8: Documentation + build log

**Files:**
- Modify: `QUICKSTART.md:29-43` (step 2)
- Modify: `README.md` (the CLI section)
- Modify: `AGENTS.md` (note that guidance lives centrally)
- Modify: `_tracker.md` (new phase, ticked)

**Interfaces:**
- Consumes: the finished `trackden onboard` command (Task 7).
- Produces: no code — documentation only.

- [ ] **Step 1: Rewrite QUICKSTART step 2 around `onboard`**

Replace the body of `## 2 · Add your first project (1 min)` in `QUICKSTART.md` with:

```markdown
## 2 · Onboard your first project (1 min)

One command brings a project in — it reads the repo you point it at, offers to import
any checklist it finds, and scaffolds the rest. **Your repo is never modified.**

```bash
cd backend
uv run trackden onboard                 # interactive wizard
```

Already have a `_tracker.md`, `CLAUDE.md`, or `AGENTS.md`? It finds them and asks
before importing anything:

```
Found 12 items in main-plans/_tracker.md
    1. [done] Scaffold the repo
    2. [todo] Wire the API
   …
Import? (y / n / edit) [y]:
```

Guidance files land centrally in `~/.trackden/projects/<slug>/`
(`_way-of-work.md`, `_arch.md`, `_decisions.md`, plus a generated `_tracker.md` mirror),
and `~/.trackden` is a git repo — one push backs up all of it.

Prefer to build the map by hand? The primitives are still there:

```bash
uv run trackden add-project my-first-project
uv run trackden add-item my-first-project "Set up the repo"
uv run trackden list
```

That's your structure. An "item" is domain-agnostic — a *ticket*, a *bill*, a
*deliverable*; it's just a unit of work.
```

- [ ] **Step 2: Add `onboard` to the README's CLI list**

In `README.md`, find the section listing CLI commands and add `onboard` as the first entry:

```markdown
| `trackden onboard` | Bring a project in: scan a repo (read-only), import its checklist behind a review gate, scaffold central guidance |
```

If the README lists commands as prose or bullets rather than a table, match that format instead — one line, same wording.

- [ ] **Step 3: Note the central workspace in AGENTS.md**

Add to `AGENTS.md`, in the section describing where things live:

```markdown
**Guidance lives centrally, not in the repo.** A project's `_way-of-work.md`, `_arch.md`
and `_decisions.md` live in `~/.trackden/projects/<slug>/` and reach you over MCP —
`trackden onboard` puts them there. Repos are never modified by Trackden. The
`_tracker.md` in that folder is a **generated mirror** of the DB; do not hand-edit it.
```

- [ ] **Step 4: Tick the build log**

In `_tracker.md`, replace the `🔴 IN-FLIGHT THREAD — trackden onboard design` block with a resolved note, and append a new phase section at the end:

```markdown
## Phase 11 — Onboarding (`trackden onboard`) ✅
- [x] Spec locked into BUILD_NOTES ("LOCKED DESIGN — Onboarding", 2026-07-28) + implementation plan at `docs/superpowers/plans/2026-07-28-trackden-onboard.md`
- [x] `tracker_md.py` — the `_tracker.md` format both ways (parse + render), pure & tested
- [x] `workspace.py` — central `~/.trackden` scaffolding, guidance never overwritten, home git-init
- [x] `projects.repo_path` + idempotent `ALTER` in `init_db` (create_all never alters) + `import_items` / `items_with_folders`
- [x] `onboard.py` — read-only repo scan + review gate + orchestration
- [x] `trackden onboard` CLI: wizard + flags + y/n/edit gate
- [x] pytest enters the repo (dev group); DB tests auto-skip when Postgres is down
- [ ] Deferred: launcher/alias for "call MCP first" (needs its own design)
- [ ] Deferred: agent-driven onboard as an MCP tool (CLI-first for now)
```

Also update the `**Status:**` line near the top of `_tracker.md` to reflect the new counts.

- [ ] **Step 5: Verify the docs match reality**

Run: `cd backend && uv run trackden onboard --help`
Expected: the flags shown match what QUICKSTART and README describe. Fix the docs if they drifted.

- [ ] **Step 6: Commit**

```bash
git add QUICKSTART.md README.md AGENTS.md _tracker.md docs/superpowers/plans/2026-07-28-trackden-onboard.md BUILD_NOTES.md
git commit -m "docs(onboard): document trackden onboard, tick the build log"
```

---

## Post-plan cleanup (optional, ask first)

The smoke test in Task 7 leaves a `trackden-smoke` project in the DB and
`~/.trackden/projects/trackden-smoke/` on disk. Remove both when you are done — there is
deliberately no `trackden delete` command yet, so this is a manual `DELETE FROM projects
WHERE slug = 'trackden-smoke'` plus an `rm -rf`. Confirm with Nuri before running either.

## Self-Review

**Spec coverage** — every section of the BUILD_NOTES onboarding spec maps to a task:

| Spec | Task |
|---|---|
| §1 command shape (wizard + flags) | 7 |
| §2 steps: identify → scan+import → DB project (+`repo_path`) → scaffold → summary | 6 (orchestration), 7 (identify prompts + summary output) |
| §3 scan list, checkbox parsing, `CLAUDE.md`→way-of-work, **review gate**, fallback | 1 (parse), 5 (scan + guidance flag), 6 (gate wiring + seeding), 7 (interactive gate) |
| §4 central `~/.trackden/projects/<slug>/` + 4 files + home as git repo | 3 |
| §5 data homes: DB state vs central files vs generated mirror | 2 (render), 4 (DB), 6 (writes both) |
| §6 deferred launcher/alias + agent-driven onboard | 8 (recorded as deferred, not built) |
| §7 `repo_path` needs an idempotent `ALTER`; pure functions; pytest is new | 4, 1 |

**Placeholders:** none — every code step carries the actual code, every test step the actual assertions, every run step the exact command and expected result.

**Type consistency checked:** `ParsedItem(title, status, folder)` and `ParsedTracker.items/.folders` are used identically in Tasks 1, 5, 6. The item dict shape `{"title", "status", "folder"}` is the same in `render_tracker_md` (Task 2), `repository.import_items` / `items_with_folders` (Task 4), and `run_onboard` (Task 6). `TODO`/`DONE` are defined once in `tracker_md` and imported by `repository`. `home: Path | None` is threaded consistently through `workspace` and `run_onboard`. `scan_repo` returns `list[ScanHit]` in both Task 5 and its Task 6 consumer.

**One known rough edge, deliberately left:** `run_onboard` takes both a keyword `import_items: bool` and calls `repository.import_items` — same word, two meanings. It reads fine because the call is always qualified (`repository.import_items`), and renaming either one would fight the spec's own vocabulary. Flagged so the implementer is not surprised.
