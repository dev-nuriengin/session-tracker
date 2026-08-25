# `trackden sync` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `~/.trackden/projects/<slug>/_tracker.md` true to the database — with a `trackden sync` command and an automatic refresh on the two write paths that can actually change it.

**Architecture:** Two new units, following `guidance.py`'s existing shape. `workspace.write_mirror` is a narrow writer for one file. `sync.sync(slug)` is a thin orchestrator over `repository` + `workspace` that gates, renders and writes, returning an outcome dict and never raising. `repository.py` stays filesystem-free, so a `chmod` can never make a `set_status` fail. The CLI and MCP doors are thin wrappers over `sync`, so the two cannot drift.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, Typer, FastMCP, pytest (`uv run pytest -q`).

**Spec:** `docs/superpowers/specs/2026-08-05-trackden-sync-design.md` — read it alongside this plan. Every design argument lives there; this plan does not repeat them.

## Global Constraints

- **`sync` never raises.** Every outcome is a dict with a `status` key, matching the ~12 write functions already in `repository`. This is load-bearing, not stylistic: auto-refresh runs *after* a DB write has committed, so an escaping exception would show a traceback for a command whose real work already succeeded.
- **`repository.py` stays filesystem-free.** Do not import `workspace` into it.
- **Five outcomes only:** `synced` · `unknown_project` · `not_scaffolded` · `hand_edited` · `write_failed`. Do not invent a sixth.
- **This plan adds a `message` key** to every outcome, which the spec's table does not list. Reason: both doors print it verbatim, exactly as `guidance.py` does, so the CLI and MCP wordings cannot drift. `message` is always a `str`, never `None`, and `""` on success.
- **No new MCP tool.** Tool count stays **17**. CLI commands go **18 → 19**.
- **Never run ad-hoc scripts against the database.** `uv run python -c …` loads the real `.env` `DATABASE_URL`; one did exactly that during Stage B3 and wrote a stray row into the owner's real database. `conftest.py`'s `_test`/`_smoke` guard only protects pytest runs. Verify through pytest, or with pure reads.
- **Every module gets `from __future__ import annotations`** as its first import, matching every other file in `app/`.
- **Ask of every test: would this fail if the code were wrong?** The check is to break the implementation, watch the test fail, then restore it — not to reason about it.
- **Commits:** one per task, conventional-commit style (`feat(sync): …`, `test(sync): …`, `docs: …`). **Pushing is a separate, explicit "yes" from the owner — never push as part of executing this plan.**
- Run the suite from `backend/`: `uv run pytest -q`. DB-marked tests need `docker compose up -d db`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/workspace.py` (modify) | Gains `write_mirror(slug, text, home=None) -> Path` — writes `_tracker.md` and nothing else, never creates the folder. |
| `backend/app/sync.py` (create) | `sync(slug) -> dict`. Gate, render, write. The only place that catches `OSError`. |
| `backend/app/cli.py` (modify) | `trackden sync [project]`, plus a `_refresh_mirror` helper called by `add-item` and `set-status`. |
| `backend/app/mcp_server.py` (modify) | `add_item` and `set_status` gain a `mirror` key in their result. |
| `backend/tests/test_workspace.py` (modify) | `write_mirror`'s five behaviours. |
| `backend/tests/test_sync.py` (create) | Every outcome, with a faked `repository` — no Postgres. |
| `backend/tests/test_cli_sync.py` (create) | The `sync` command, and CLI auto-refresh on all six write commands. |
| `backend/tests/test_mcp_server.py` (modify) | MCP auto-refresh wiring, and the absence of a `sync` tool. |
| `backend/tests/test_sync_e2e.py` (create) | One `@pytest.mark.db` walkthrough — real DB, real filesystem, real CLI. |
| `README.md`, `QUICKSTART.md`, `AGENTS.md`, `_tracker.md` (modify) | The mirror is no longer stale; `sync` exists; the queue moves on to the launcher. |

**Why `write_mirror` and not `scaffold_project`:** `scaffold_project` also `mkdir(parents=True)`s the folder and tops up `_way-of-work.md` / `_arch.md` / `_decisions.md`. Calling it from `sync` would mean a command named "refresh this file" silently inventing three guidance documents for a project that was never onboarded.

---

## Task 1: `workspace.write_mirror`

**Files:**
- Modify: `backend/app/workspace.py` — append after `scaffold_project` (currently ends at line 137, just before `ensure_home_git`)
- Test: `backend/tests/test_workspace.py`

**Interfaces:**
- Consumes: `project_dir(slug, home)` and the module constant `TRACKER_FILE = "_tracker.md"`, both already in `workspace.py`.
- Produces: `workspace.write_mirror(slug: str, text: str, home: Path | None = None) -> Path` — returns the path written. Raises `ValueError` on an unsafe slug (from `project_dir`) and `OSError` (including `FileNotFoundError`) when the folder does not exist or the write is refused. Task 2 is the only caller that catches those.

- [ ] **Step 1: Write the failing tests**

Add to the import line at the top of `backend/tests/test_workspace.py` (it currently reads `from app.workspace import ensure_home_git, project_dir, scaffold_project, trackden_home`):

```python
from app.workspace import (
    ensure_home_git,
    project_dir,
    scaffold_project,
    trackden_home,
    write_mirror,
)
```

Append these tests to the end of the file:

```python
def test_write_mirror_writes_only_the_tracker_file(home):
    directory = project_dir("my-proj")
    directory.mkdir(parents=True)

    path = write_mirror("my-proj", "# mirror\n")

    assert path == directory / "_tracker.md"
    assert path.read_text(encoding="utf-8") == "# mirror\n"
    assert {p.name for p in directory.iterdir()} == {"_tracker.md"}


def test_write_mirror_overwrites_an_existing_mirror(home):
    directory = project_dir("my-proj")
    directory.mkdir(parents=True)
    (directory / "_tracker.md").write_text("old\n", encoding="utf-8")

    write_mirror("my-proj", "new\n")

    assert (directory / "_tracker.md").read_text(encoding="utf-8") == "new\n"


def test_write_mirror_never_creates_the_project_folder(home):
    """The whole difference from `scaffold_project`, asserted: a refresh must not
    conjure a folder — and three guidance templates — for an un-onboarded project."""
    with pytest.raises(OSError):
        write_mirror("never-onboarded", "# mirror\n")

    assert not project_dir("never-onboarded").exists()


def test_write_mirror_leaves_guidance_files_untouched(home):
    scaffold_project("my-proj", name="My Proj", tracker_md="# old\n")
    way_of_work = project_dir("my-proj") / "_way-of-work.md"
    before = way_of_work.read_bytes()

    write_mirror("my-proj", "# new\n")

    assert way_of_work.read_bytes() == before


def test_write_mirror_rejects_an_unsafe_slug(home):
    """The workspace owns the "never write outside ~/.trackden" promise; a second
    writer must not be a second way around it."""
    with pytest.raises(ValueError):
        write_mirror("../escape", "# mirror\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_workspace.py -q`
Expected: FAIL — `ImportError: cannot import name 'write_mirror' from 'app.workspace'`

- [ ] **Step 3: Write the implementation**

In `backend/app/workspace.py`, insert immediately after `scaffold_project` returns (line 137) and before `def ensure_home_git`:

```python
def write_mirror(slug: str, text: str, home: Path | None = None) -> Path:
    """Write a project's generated `_tracker.md`, and nothing else. Returns the path.

    Deliberately narrow. `scaffold_project` writes the mirror too — but it also
    `mkdir`s the folder and tops up the three guidance templates on the way, so
    calling it to refresh one derived file would silently invent a way-of-work, an
    architecture and a decisions log for a project that was never onboarded.

    Never creates the folder: a missing one raises `FileNotFoundError` (an
    `OSError`), which is how `sync` learns the project is not scaffolded. The slug
    is validated by `project_dir`, so this second writer is not a second way around
    the "never write outside the workspace" promise.
    """
    path = project_dir(slug, home) / TRACKER_FILE
    path.write_text(text, encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workspace.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Prove the tests discriminate**

Temporarily change `write_mirror`'s body to `path = project_dir(slug, home) / TRACKER_FILE; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8"); return path`, run the file again, and confirm `test_write_mirror_never_creates_the_project_folder` FAILS. Restore the original body and confirm green.

- [ ] **Step 6: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/workspace.py backend/tests/test_workspace.py
git commit -m "feat(sync): workspace.write_mirror — the mirror alone, no scaffolding"
```

---

## Task 2: `sync.sync(slug)` — the orchestrator

**Files:**
- Create: `backend/app/sync.py`
- Test: `backend/tests/test_sync.py`

**Interfaces:**
- Consumes: `workspace.write_mirror` (Task 1) · `workspace.project_dir` · `workspace.TRACKER_FILE` · `repository.get_project(slug) -> models.Project | None` (has `.slug`, `.name`) · `repository.items_with_folders(slug) -> list[TrackerItem]` · `repository.closed_names(slug) -> frozenset[str]` · `tracker_md.is_generated(text) -> bool` · `tracker_md.render_tracker_md(project_name, items, closed=None) -> str`.
- Produces: `sync.sync(slug: str) -> dict`. Always has `project`, `status`, `path`, `message`. Adds `items: int` on `synced`, and `reason: str` on `write_failed`. Tasks 3, 4 and 5 all call exactly this.

**The gate order is the design.** `items_with_folders` returns `[]` for an unknown project and `closed_names` falls back to the shipped defaults for one — *neither read distinguishes "no such project" from "a project with zero items"*, and both are right for their own callers. Rendering straight from them writes a valid, empty mirror for `trackden sync typo-slug`. `get_project` is the only read here that tells the truth about existence, so it goes first. It also carries `project.name`, the display name `render_tracker_md` wants — existence check and name lookup are one call, not two.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sync.py`:

```python
"""`sync` — the generated `_tracker.md` mirror, kept true to the DB.

No Postgres: `repository` is faked, so these tests pin the gate ORDER and the
outcome vocabulary, which is where this design's whole risk sits. The one test that
proves the doors are really wired is the `@pytest.mark.db` walkthrough in
`test_sync_e2e.py`.
"""

from types import SimpleNamespace

import pytest

from app import sync as sync_mod
from app import workspace


@pytest.fixture
def fake_repo(monkeypatch):
    """A `repository` stand-in. Mirrors the real reads' behaviour for an UNKNOWN
    project deliberately — `items_with_folders` returns [] and `closed_names` falls
    back to the defaults — because that is exactly the trap the gate order exists
    to survive. A fake that raised instead would hide it."""
    state = SimpleNamespace(projects={}, items={}, closed=frozenset({"done"}))

    monkeypatch.setattr(
        sync_mod.repository, "get_project",
        lambda slug: state.projects.get(slug.strip().lower()),
    )
    monkeypatch.setattr(
        sync_mod.repository, "items_with_folders",
        lambda slug: state.items.get(slug.strip().lower(), []),
    )
    monkeypatch.setattr(sync_mod.repository, "closed_names", lambda slug: state.closed)
    return state


def add_project(state, slug, name=None, items=None):
    state.projects[slug] = SimpleNamespace(slug=slug, name=name or slug)
    state.items[slug] = items or []


def item(title, status="todo", folder=None):
    return {"title": title, "status": status, "folder": folder}


def scaffolded(slug):
    directory = workspace.project_dir(slug)
    directory.mkdir(parents=True)
    return directory


# ---- synced ----

def test_synced_writes_the_mirror(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert result["items"] == 1
    assert result["path"] == str(directory / "_tracker.md")
    text = (directory / "_tracker.md").read_text(encoding="utf-8")
    assert "ship it" in text
    assert "Acme" in text


def test_synced_reflects_a_closed_status_as_a_ticked_box(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it", status="done")])
    directory = scaffolded("acme")

    sync_mod.sync("acme")

    assert "- [x] ship it" in (directory / "_tracker.md").read_text(encoding="utf-8")


def test_synced_with_zero_items_is_a_success(home, fake_repo):
    """An onboarded project with nothing in it yet is an empty mirror, not an error."""
    add_project(fake_repo, "acme", name="Acme", items=[])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert result["items"] == 0
    assert (directory / "_tracker.md").exists()


def test_sync_is_idempotent(home, fake_repo):
    """Two runs with no DB change between them must be byte-identical, or every
    sync shows a spurious diff in the git repo `ensure_home_git` maintains."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    sync_mod.sync("acme")
    first = (directory / "_tracker.md").read_bytes()
    sync_mod.sync("acme")

    assert (directory / "_tracker.md").read_bytes() == first


def test_sync_uses_the_db_slug_not_the_callers(home, fake_repo):
    """`get_project` lowercases before it queries, so an uppercase argument finds
    the project — but `workspace._SAFE_SLUG` rejects uppercase outright. Downstream
    calls must use `project.slug`, or the two layers disagree about which project
    they are working on. Same defect `trackden delete ACME` had."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("ACME")

    assert result["status"] == "synced"
    assert (directory / "_tracker.md").exists()


# ---- unknown_project — the trap gate ----

def test_unknown_project_creates_no_file_at_all(home, fake_repo):
    """THE trap. `items_with_folders` returns [] for an unknown project and
    `closed_names` falls back to the defaults, so rendering straight from them
    would write a valid, empty mirror for a project that does not exist. The bug
    this prevents is "a file appeared", not "a wrong string came back" — so assert
    the filesystem, not just the status."""
    result = sync_mod.sync("typo-slug")

    assert result["status"] == "unknown_project"
    assert "typo-slug" in result["message"]
    assert not (workspace.trackden_home() / "projects" / "typo-slug").exists()


# ---- not_scaffolded ----

def test_not_scaffolded_when_the_folder_is_missing(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "not_scaffolded"
    assert "onboard" in result["message"]
    assert not workspace.project_dir("acme").exists()


def test_an_unusable_stored_slug_is_reported_not_raised(home, fake_repo):
    """`trackden add-project my_project` only lowercases and strips — it never
    validates — so the DB can hold a slug `_SAFE_SLUG` rejects. `sync` promises
    never to raise, and that promise is its own to keep."""
    add_project(fake_repo, "my_project", name="My Project")

    result = sync_mod.sync("my_project")

    assert result["status"] == "not_scaffolded"
    assert "lowercase letters" in result["message"]


# ---- hand_edited ----

def test_hand_edited_leaves_the_file_byte_identical(home, fake_repo):
    """The discriminating one. Asserting the STATUS alone passes against an
    implementation that returns `hand_edited` and overwrites the file anyway."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")
    mirror = directory / "_tracker.md"
    mirror.write_text("# my own notes\n- [ ] hand written\n", encoding="utf-8")
    before = mirror.read_bytes()

    result = sync_mod.sync("acme")

    assert result["status"] == "hand_edited"
    assert result["path"] == str(mirror)
    assert mirror.read_bytes() == before


def test_a_missing_mirror_is_written_not_called_hand_edited(home, fake_repo):
    """Absent is not edited. A scaffolded project whose mirror was deleted gets one."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert (directory / "_tracker.md").exists()


def test_a_non_utf8_mirror_is_refused_not_overwritten(home, fake_repo):
    """`UnicodeDecodeError` IS a `ValueError`, so without its own clause ahead of
    the slug guard this file would be reported as `not_scaffolded` — a confusing
    lie about a project that is scaffolded. Bytes we cannot read certainly did not
    come from us, so they get a hand-edited file's protection."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")
    mirror = directory / "_tracker.md"
    mirror.write_bytes(b"\xff\xfe\x00not text")
    before = mirror.read_bytes()

    result = sync_mod.sync("acme")

    assert result["status"] == "hand_edited"
    assert mirror.read_bytes() == before


# ---- write_failed ----

def test_write_failed_carries_the_reason(home, fake_repo, monkeypatch):
    """Monkeypatched rather than chmod-based: a chmod test does nothing when the
    suite runs as root (CI containers often do), and would then pass green against
    a `sync` that never catches `OSError` at all."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    scaffolded("acme")

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(sync_mod.workspace, "write_mirror", refuse)

    result = sync_mod.sync("acme")

    assert result["status"] == "write_failed"
    assert "Permission denied" in result["reason"]
    assert "Permission denied" in result["message"]


# ---- the contract ----

@pytest.mark.parametrize(
    "setup",
    ["synced", "unknown_project", "not_scaffolded", "hand_edited"],
)
def test_every_outcome_carries_the_four_common_keys(home, fake_repo, setup):
    """Both doors read `message` and print it verbatim; a `None` or a missing key
    would reach a user as the string "None"."""
    if setup != "unknown_project":
        add_project(fake_repo, "acme", name="Acme")
    if setup in ("synced", "hand_edited"):
        directory = scaffolded("acme")
        if setup == "hand_edited":
            (directory / "_tracker.md").write_text("mine\n", encoding="utf-8")

    result = sync_mod.sync("acme")

    assert result["status"] == setup
    assert set(result) >= {"project", "status", "path", "message"}
    assert isinstance(result["message"], str)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sync'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/sync.py`:

```python
"""Keep the generated `_tracker.md` mirror true to the database.

`~/.trackden/projects/<slug>/_tracker.md` is derived output — a human-readable
snapshot of the DB's items, carrying a banner that says so. Until this module
existed, `render_tracker_md` had exactly one caller (`run_onboard`), so the file
was correct at onboard time and stale from the next write onward.

Why a status and never an exception: the auto-refresh call sites run AFTER a DB
write has committed. An exception escaping `sync` would abort a command whose real
work had already succeeded, and the user would see a traceback with no way to tell
whether their item was saved. Same contract as `guidance.py`, for the same reason.

`repository` stays filesystem-free — this module is the seam between the DB and the
workspace, which is what keeps a `chmod` from failing a `set_status`.
"""

from __future__ import annotations

from pathlib import Path

from . import repository, workspace
from .tracker_md import is_generated, render_tracker_md

_HAND_EDITED = "skipped: not a generated file, refusing to overwrite your edits"


def sync(slug: str) -> dict:
    """Rewrite one project's generated `_tracker.md` from the DB. Never raises.

    Outcomes — always `project`, `status`, `path`, `message`:

    - `synced` (+ `items`) — written. `items: 0` is a legitimate success.
    - `unknown_project` — no such project in the DB.
    - `not_scaffolded` — in the DB, but no `~/.trackden/projects/<slug>/`.
    - `hand_edited` (+ `path`) — a `_tracker.md` without the generated banner.
      Refused, never overwritten.
    - `write_failed` (+ `reason`) — the render succeeded; the filesystem refused.
    """
    result: dict = {"project": slug, "status": "", "path": None, "message": ""}

    # FIRST, and it must stay first. `items_with_folders` returns [] for an unknown
    # project and `closed_names` falls back to the shipped defaults for one —
    # neither can tell "no such project" from "a project with zero items", and both
    # are correct for their own callers. Rendering straight from them would write a
    # valid, empty mirror for `trackden sync typo-slug`. `get_project` is the only
    # read here that tells the truth about existence, and it carries `name`, so the
    # existence check and the display-name lookup are one call.
    project = repository.get_project(slug)
    if project is None:
        result["status"] = "unknown_project"
        result["message"] = f"unknown project {slug!r}"
        return result

    # The DB's own slug, not the caller's: `get_project` lowercases before it
    # queries, so `sync("ACME")` finds the project — but `workspace._SAFE_SLUG`
    # rejects uppercase outright. Same choice `guidance.py` makes with `row.slug`,
    # and the same defect `trackden delete ACME` had before it normalised.
    canonical = project.slug
    mirror: Path | None = None

    try:
        directory = workspace.project_dir(canonical)
        # `.exists()` sits INSIDE the try: on an over-long path *component* it
        # raises OSError itself, which a length check alone would not catch.
        if not directory.exists():
            result["status"] = "not_scaffolded"
            result["message"] = (
                f"no guidance folder for {canonical!r} yet — run "
                f"`trackden onboard {canonical}` (safe to re-run) to scaffold it"
            )
            return result

        mirror = directory / workspace.TRACKER_FILE
        if mirror.exists() and not is_generated(mirror.read_text(encoding="utf-8")):
            result["status"] = "hand_edited"
            result["path"] = str(mirror)
            result["message"] = _HAND_EDITED
            return result

        items = repository.items_with_folders(canonical)
        text = render_tracker_md(
            project.name, items, closed=repository.closed_names(canonical)
        )
        written = workspace.write_mirror(canonical, text)
    except UnicodeDecodeError:
        # MUST precede `except ValueError` — UnicodeDecodeError is a subclass of it,
        # and Python takes the first matching clause. A mirror that is not valid
        # UTF-8 certainly did not come from us, so it gets a hand-edited file's
        # protection rather than being mislabelled `not_scaffolded`.
        result["status"] = "hand_edited"
        result["path"] = str(mirror) if mirror is not None else None
        result["message"] = _HAND_EDITED
        return result
    except ValueError:
        # The DB holds a slug `_SAFE_SLUG` rejects: `add-project` only lowercases
        # and strips, it never validates. The spec's outcome set has no
        # `invalid_slug`, so this is reported as `not_scaffolded` — but with an
        # honest message, because telling someone to `onboard` a slug that cannot
        # be a folder name would send them in a circle.
        result["status"] = "not_scaffolded"
        result["message"] = (
            f"project slug {canonical!r} cannot be a workspace folder — a usable "
            "slug is lowercase letters, digits, and hyphens only (e.g. 'my-project')"
        )
        return result
    except OSError as exc:
        result["status"] = "write_failed"
        result["reason"] = str(exc)
        # `message` repeats `reason` for this one outcome on purpose: the doors
        # print `message` inside their own framing ("mirror not refreshed: …"), so
        # a prefix here would read as "could not write the mirror: could not …".
        result["message"] = str(exc)
        return result

    result["status"] = "synced"
    result["items"] = len(items)
    result["path"] = str(written)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_sync.py -q`
Expected: PASS

- [ ] **Step 5: Prove the trap test discriminates**

Temporarily move the `get_project` block *below* the `try:` line's `directory.exists()` gate — or simply delete the `if project is None:` early return and hardcode `canonical = slug`, `project = SimpleNamespace(slug=slug, name=slug)`. Run `tests/test_sync.py` and confirm `test_unknown_project_creates_no_file_at_all` FAILS. Restore and confirm green.

Do the same for `hand_edited`: change the branch to set the status but fall through to the write, and confirm `test_hand_edited_leaves_the_file_byte_identical` FAILS.

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS — the previous baseline (376) plus the new tests. Nothing existing should change.

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/sync.py backend/tests/test_sync.py
git commit -m "feat(sync): sync.sync — gate, render, write, never raise"
```

---

## Task 3: `trackden sync [project]`

**Files:**
- Modify: `backend/app/cli.py` — add `from . import sync as sync_mod` to the import block (lines 12-18), and append the command after `delete` (which ends at line 581, just before `if __name__ == "__main__":`)
- Test: `backend/tests/test_cli_sync.py` (create)

**Interfaces:**
- Consumes: `sync_mod.sync(slug) -> dict` (Task 2) · `repository.list_projects() -> list[str]`.
- Produces: the `sync` Typer command. Task 4 adds `_refresh_mirror` to the same file.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cli_sync.py`:

```python
"""The CLI door onto `sync` — the command, and the auto-refresh on write commands.

No Postgres: `init_db`, `repository` and `sync` are all faked, so these tests pin
the wiring and the exit codes. `test_sync_e2e.py` is what proves the wiring is real.
"""

from unittest.mock import Mock

from typer.testing import CliRunner

from app import cli as cli_mod

runner = CliRunner()


def _no_schema(monkeypatch):
    """Neutralise the app-level init_db callback — these tests never touch Postgres."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())


def _fake_sync(monkeypatch, outcomes, calls=None):
    """Stub `sync` with a slug -> outcome mapping, recording the slugs it was given."""

    def fake(slug):
        if calls is not None:
            calls.append(slug)
        return {"project": slug, "path": None, "message": "", **outcomes[slug]}

    monkeypatch.setattr(cli_mod.sync_mod, "sync", fake)


# ---- the command ----

def test_sync_one_project_reports_the_item_count(monkeypatch):
    _no_schema(monkeypatch)
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 14}})

    result = runner.invoke(cli_mod.app, ["sync", "korpus"])

    assert result.exit_code == 0, result.output
    assert "korpus" in result.output
    assert "14 items" in result.output


def test_sync_normalises_the_slug_before_calling_sync(monkeypatch):
    """`repository` lowercases internally but `workspace._SAFE_SLUG` rejects
    uppercase outright, so an un-normalised slug makes the two layers disagree
    about which project they are working on — the defect `delete` already fixed."""
    _no_schema(monkeypatch)
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["sync", "  KORPUS  "])

    assert result.exit_code == 0, result.output
    assert calls == ["korpus"]


def test_bare_sync_covers_every_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: ["alpha", "beta"])
    calls = []
    _fake_sync(
        monkeypatch,
        {"alpha": {"status": "synced", "items": 2}, "beta": {"status": "synced", "items": 0}},
        calls,
    )

    result = runner.invoke(cli_mod.app, ["sync"])

    assert result.exit_code == 0, result.output
    assert calls == ["alpha", "beta"]
    assert "alpha" in result.output
    assert "beta" in result.output


def test_one_bad_project_does_not_hide_the_good_ones(monkeypatch):
    """A single failure must not stop the loop — and must still fail the command,
    because a partial success is a failure for a scripted run."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: ["alpha", "beta", "gamma"])
    _fake_sync(
        monkeypatch,
        {
            "alpha": {"status": "synced", "items": 2},
            "beta": {"status": "hand_edited", "message": "skipped: not a generated file"},
            "gamma": {"status": "synced", "items": 1},
        },
    )

    result = runner.invoke(cli_mod.app, ["sync"])

    assert result.exit_code == 1, result.output
    assert "alpha" in result.output
    assert "gamma" in result.output
    assert "not a generated file" in result.output


def test_sync_of_an_unknown_project_exits_non_zero(monkeypatch):
    _no_schema(monkeypatch)
    _fake_sync(
        monkeypatch,
        {"typo": {"status": "unknown_project", "message": "unknown project 'typo'"}},
    )

    result = runner.invoke(cli_mod.app, ["sync", "typo"])

    assert result.exit_code == 1, result.output
    assert "unknown project" in result.output


def test_bare_sync_with_no_projects_exits_zero(monkeypatch):
    """Nothing was asked for and nothing failed — same guidance `list` gives."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: [])

    result = runner.invoke(cli_mod.app, ["sync"])

    assert result.exit_code == 0, result.output
    assert "No projects yet" in result.output


def test_bare_sync_does_not_consult_the_db_when_given_a_project(monkeypatch):
    """`sync <project>` must not enumerate every project to sync one."""
    _no_schema(monkeypatch)

    def explode():
        raise AssertionError("list_projects must not be called for a single project")

    monkeypatch.setattr(cli_mod.repository, "list_projects", explode)
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}})

    result = runner.invoke(cli_mod.app, ["sync", "korpus"])

    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli_sync.py -q`
Expected: FAIL — `AttributeError: module 'app.cli' has no attribute 'sync_mod'`

- [ ] **Step 3: Write the implementation**

In `backend/app/cli.py`, add to the import block (after `from . import repository`, keeping alphabetical order):

```python
from . import sync as sync_mod
```

Append this command after `delete` (the last command in the file), before `if __name__ == "__main__":`:

```python
@app.command()
def sync(project: str = typer.Argument(None, help="Project to sync (default: all)")):
    """Rewrite a project's generated `_tracker.md` from the database (or every project).

    The mirror under `~/.trackden/projects/<slug>/` is derived output, refreshed
    automatically after the writes that change it. Run this to repair one that
    drifted — after editing the DB by hand, or after a refresh failed.
    """
    # Normalise ONCE, here, exactly as `delete` does: `repository` lowercases
    # internally but `workspace._SAFE_SLUG` rejects uppercase outright, so an
    # un-normalised slug makes the two layers disagree about which project they
    # are working on.
    slugs = [project.strip().lower()] if project else repository.list_projects()
    if not slugs:
        typer.echo("No projects yet. Add one:  trackden add-project <slug>")
        raise typer.Exit()

    width = max(len(slug) for slug in slugs)
    failed = False
    for slug in slugs:
        result = sync_mod.sync(slug)
        if result["status"] == "synced":
            typer.echo(f"✓ {slug:<{width}} — mirror written ({result['items']} items)")
        else:
            # Keep going: one bad project must not hide the ones that worked.
            failed = True
            typer.echo(f"! {slug:<{width}} — {result['message']}")

    if failed:
        # A partial success is still a failure for a scripted run, and Stage A
        # settled that a write command reporting a failure must not exit 0.
        raise typer.Exit(1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli_sync.py -q`
Expected: PASS

- [ ] **Step 5: Check the command by hand**

Run: `cd backend && uv run trackden --help`
Expected: `sync` appears in the command list, and the count is **19**.

Run: `cd backend && uv run trackden sync`
Expected: against an empty DB, `No projects yet. Add one:  trackden add-project <slug>` and `echo $?` → `0`. (This is a pure read plus a possible write under `~/.trackden`; it never writes to the database.)

- [ ] **Step 6: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/cli.py backend/tests/test_cli_sync.py
git commit -m "feat(sync): trackden sync — one project or all, non-zero on any failure"
```

---

## Task 4: CLI auto-refresh on `add-item` and `set-status`

**Files:**
- Modify: `backend/app/cli.py` — `add_item` (lines 172-193) and `set_status` (lines 196-213); add the `_refresh_mirror` helper above them
- Test: `backend/tests/test_cli_sync.py` (append)

**Interfaces:**
- Consumes: `sync_mod.sync` (Task 2), already imported in Task 3.
- Produces: `cli._refresh_mirror(project: str) -> None` — warns and returns; never raises, never changes the exit code.

**Exactly two write paths, not six.** The mirror renders items only — title, status, folder grouping, `done / total`. `add-folder` is out because `groups` is built by iterating items, so a folder with no items renders nothing. `add-status` is out because no existing item can hold a name that was just created. `log` and `remember` are out because neither appears in the mirror. `onboard` already writes it, and `delete` is deliberately out of scope.

**`unchanged` does not refresh.** `set_status` returning `unchanged` means nothing in the DB moved, so nothing in the mirror can have moved either — and the spec's rule is that a refresh runs only after a write reported success. Flag this to the reviewer: it is a judgment call the spec does not spell out.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_cli_sync.py`:

```python
# ---- auto-refresh: the two paths that DO refresh ----

def test_add_item_refreshes_the_mirror(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 42},
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["add-item", "korpus", "ship sync"])

    assert result.exit_code == 0, result.output
    assert calls == ["korpus"]
    assert "item #42" in result.output


def test_set_status_refreshes_on_a_real_move(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "set_status",
        lambda *a, **k: {"status": "set", "from": "todo", "to": "done"},
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["set-status", "korpus", "42", "done"])

    assert result.exit_code == 0, result.output
    assert calls == ["korpus"]


def test_auto_refresh_normalises_the_slug(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 1},
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["add-item", "KORPUS", "ship sync"])

    assert result.exit_code == 0, result.output
    assert calls == ["korpus"]


# ---- auto-refresh: failure must never fail the command ----

def test_a_failed_refresh_warns_but_keeps_exit_zero(monkeypatch):
    """The DB write — the real work — already committed. Failing the command over
    a derived file would make a cosmetic problem look like lost work."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 42},
    )
    _fake_sync(
        monkeypatch,
        {"korpus": {"status": "write_failed", "reason": "permission denied",
                    "message": "permission denied"}},
    )

    result = runner.invoke(cli_mod.app, ["add-item", "korpus", "ship sync"])

    assert result.exit_code == 0, result.output
    assert "item #42" in result.output
    assert "mirror not refreshed" in result.output
    assert "permission denied" in result.output
    assert "trackden sync korpus" in result.output


def test_a_refresh_that_raises_cannot_fail_the_command(monkeypatch):
    """`sync` promises never to raise; this asserts the door does not DEPEND on
    that promise for something as costly as swallowing a committed write."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 42},
    )

    def explode(slug):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod.sync_mod, "sync", explode)

    result = runner.invoke(cli_mod.app, ["add-item", "korpus", "ship sync"])

    assert result.exit_code == 0, result.output
    assert "item #42" in result.output


def test_a_failed_write_does_not_touch_the_mirror(monkeypatch):
    """A refresh runs only after the underlying write reported success."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "unknown_project"}
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 0}}, calls)

    result = runner.invoke(cli_mod.app, ["add-item", "korpus", "ship sync"])

    assert result.exit_code == 1, result.output
    assert calls == []


def test_set_status_does_not_refresh_when_unchanged(monkeypatch):
    """`unchanged` is not a write — nothing in the DB moved, so nothing in the
    mirror can have moved either."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "set_status",
        lambda *a, **k: {"status": "unchanged", "from": "done", "to": "done"},
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["set-status", "korpus", "42", "done"])

    assert result.exit_code == 0, result.output
    assert calls == []


# ---- auto-refresh: the paths that must NOT refresh ----

def test_add_folder_does_not_refresh(monkeypatch):
    """`groups` is built by iterating ITEMS, so a folder with no items renders
    nothing at all — there is nothing in the mirror for this to change."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder",
        lambda *a, **k: {"status": "added", "folder_id": 3},
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["add-folder", "korpus", "Phase 1"])

    assert result.exit_code == 0, result.output
    assert calls == []


def test_add_status_does_not_refresh(monkeypatch):
    """A new NAME in the vocabulary; no existing item can already hold it."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_status", lambda *a, **k: {"status": "added"}
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["add-status", "korpus", "parked", "waiting"])

    assert result.exit_code == 0, result.output
    assert calls == []


def test_log_does_not_refresh(monkeypatch):
    """Session logs are not in the mirror."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_session_log", lambda *a, **k: {"status": "saved"}
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["log", "korpus", "a note"])

    assert result.exit_code == 0, result.output
    assert calls == []


def test_remember_does_not_refresh(monkeypatch):
    """Memory is not in the mirror."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_memory", lambda *a, **k: {"status": "saved", "id": 1}
    )
    calls = []
    _fake_sync(monkeypatch, {"korpus": {"status": "synced", "items": 1}}, calls)

    result = runner.invoke(cli_mod.app, ["remember", "korpus", "a link"])

    assert result.exit_code == 0, result.output
    assert calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli_sync.py -q`
Expected: FAIL — the refresh tests fail with `assert [] == ['korpus']`; the no-refresh tests already pass (nothing calls sync yet), which is expected and fine.

- [ ] **Step 3: Write the implementation**

In `backend/app/cli.py`, add this helper immediately above the `@app.command("add-item")` decorator:

```python
def _refresh_mirror(project: str) -> None:
    """Rewrite the project's generated `_tracker.md` after a successful DB write.

    Warns and returns. It must never raise and never change the exit code: the DB
    write already committed, so failing the command because a derived file could
    not be rewritten would make a cosmetic problem look like lost work.

    `sync` promises never to raise; the bare `except` is deliberate belt-and-braces,
    because the cost of that promise being broken here is a user believing their
    item was not saved.
    """
    slug = project.strip().lower()
    try:
        result = sync_mod.sync(slug)
    except Exception:  # noqa: BLE001 — see the docstring
        result = {"status": "write_failed", "message": "unexpected error"}
    if result["status"] == "synced":
        return
    typer.echo(f"! mirror not refreshed: {result['message']}")
    typer.echo(f"  run `trackden sync {slug}` once that is fixed")
```

In `add_item`, change the success branch:

```python
    if outcome == "added":
        typer.echo(f"✓ item #{result['item_id']} added to {project}")
        _refresh_mirror(project)
        return
```

In `set_status`, change the `set` branch only — `unchanged` moved nothing, so it refreshes nothing:

```python
    if outcome == "set":
        typer.echo(f"✓ item #{item_id}: {result['from']} → {result['to']}")
        _refresh_mirror(project)
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli_sync.py -q`
Expected: PASS

- [ ] **Step 5: Prove the no-refresh tests discriminate**

Temporarily add `_refresh_mirror(project)` to `add_folder`'s success branch, run the file, and confirm `test_add_folder_does_not_refresh` FAILS. Remove it and confirm green.

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS. If an existing `test_cli.py` test for `add-item` or `set-status` now fails on unexpected output, it is because it did not stub `sync` — stub it there rather than weakening this behaviour, and say so in the commit message.

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/cli.py backend/tests/test_cli_sync.py backend/tests/test_cli.py
git commit -m "feat(sync): refresh the mirror after add-item and set-status at the CLI"
```

Stage what you actually changed, and report any difference from this list.

---

## Task 5: MCP auto-refresh on `add_item` and `set_status`

**Files:**
- Modify: `backend/app/mcp_server.py` — the import line (line 13), `set_status` (lines 42-58), `add_item` (lines 85-102)
- Test: `backend/tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `sync.sync(slug) -> dict` (Task 2).
- Produces: `add_item` and `set_status` results gain `mirror: str` — the sync outcome's `status` string, and only that. An agent needs to know whether the human-facing file was refreshed, not a path it never reads. Additive, exactly like `overview` gaining `playbook`: no existing key changes name or meaning, so nothing reading these tools today breaks.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mcp_server.py`:

```python
# ---- the generated mirror, refreshed at the agent door ----

def test_add_item_reports_the_mirror_refresh(monkeypatch):
    """Additive, like `overview`'s `playbook` key — the existing keys are untouched."""
    monkeypatch.setattr(
        mcp_server.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 7},
    )
    monkeypatch.setattr(mcp_server.sync, "sync", lambda slug: {"status": "synced"})

    result = mcp_server.add_item("acme", "ship sync")

    assert result["status"] == "added"
    assert result["item_id"] == 7
    assert result["mirror"] == "synced"


def test_add_item_reports_a_refresh_that_did_not_happen(monkeypatch):
    """`not_scaffolded` is the common case for an agent-only project. Reported,
    not shouted about — the write itself still succeeded."""
    monkeypatch.setattr(
        mcp_server.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 7},
    )
    monkeypatch.setattr(
        mcp_server.sync, "sync", lambda slug: {"status": "not_scaffolded"}
    )

    result = mcp_server.add_item("acme", "ship sync")

    assert result["status"] == "added"
    assert result["mirror"] == "not_scaffolded"


def test_add_item_does_not_refresh_on_a_failed_write(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mcp_server.repository, "add_item", lambda *a, **k: {"status": "unknown_project"}
    )
    monkeypatch.setattr(
        mcp_server.sync, "sync",
        lambda slug: calls.append(slug) or {"status": "synced"},
    )

    result = mcp_server.add_item("acme", "ship sync")

    assert result["status"] == "unknown_project"
    assert calls == []
    assert "mirror" not in result


def test_set_status_reports_the_mirror_refresh(monkeypatch):
    monkeypatch.setattr(
        mcp_server.repository, "set_status",
        lambda *a, **k: {"status": "set", "from": "todo", "to": "done"},
    )
    monkeypatch.setattr(mcp_server.sync, "sync", lambda slug: {"status": "synced"})

    result = mcp_server.set_status("acme", 7, "done")

    assert result["status"] == "set"
    assert result["from"] == "todo"
    assert result["to"] == "done"
    assert result["mirror"] == "synced"


def test_set_status_does_not_refresh_when_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mcp_server.repository, "set_status",
        lambda *a, **k: {"status": "unchanged", "from": "done", "to": "done"},
    )
    monkeypatch.setattr(
        mcp_server.sync, "sync",
        lambda slug: calls.append(slug) or {"status": "synced"},
    )

    result = mcp_server.set_status("acme", 7, "done")

    assert calls == []
    assert "mirror" not in result


def test_a_failed_refresh_cannot_lose_the_write(monkeypatch):
    """The DB write committed. An exception escaping here would reach the agent as
    an opaque tool error for work that actually succeeded."""
    monkeypatch.setattr(
        mcp_server.repository, "add_item",
        lambda *a, **k: {"status": "added", "item_id": 7},
    )

    def explode(slug):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_server.sync, "sync", explode)

    result = mcp_server.add_item("acme", "ship sync")

    assert result["status"] == "added"
    assert result["item_id"] == 7


def test_there_is_no_sync_mcp_tool():
    """The mirror is a human-facing artifact. Agents read state through `overview`
    and `list_items`, which query the DB directly and are never stale — there is
    nothing for an agent to gain by asking Trackden to rewrite a file it does not
    read. The MCP surface stays 17 tools."""
    assert mcp_server.mcp._tool_manager.get_tool("sync") is None
```

`get_tool` returning `None` for an unknown name was verified against the installed FastMCP while this plan was written, so the assertion is safe as-is. Deliberately **not** a tool *count*: a count would break on any legitimate future tool and says nothing this assertion does not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -q`
Expected: FAIL — `AttributeError: module 'app.mcp_server' has no attribute 'sync'`

- [ ] **Step 3: Write the implementation**

In `backend/app/mcp_server.py`, change line 13:

```python
from . import guidance, playbook, repository, sync
```

Add this helper immediately below `mcp = FastMCP("trackden")`:

```python
def _with_mirror(result: dict, project: str) -> dict:
    """Refresh the generated `_tracker.md` and report the outcome as `mirror`.

    Additive, exactly as `overview` gained `playbook`: no existing key changes name
    or meaning, so nothing reading these tools today breaks. The value is the sync
    outcome's status alone — an agent needs to know whether the human-facing file
    was refreshed, not a path it never reads.

    `sync` promises never to raise; the bare `except` is belt-and-braces, because
    the cost of that promise breaking here is an agent seeing an opaque tool error
    for a DB write that actually committed.
    """
    try:
        mirror = sync.sync(project.strip().lower())["status"]
    except Exception:  # noqa: BLE001 — see the docstring
        mirror = "write_failed"
    return {**result, "mirror": mirror}
```

Change `set_status`'s body (line 58) from `return repository.set_status(project, item_id, status)` to:

```python
    result = repository.set_status(project, item_id, status)
    # Only after a real move: `unchanged` means nothing in the DB moved, so nothing
    # in the mirror can have moved either.
    return _with_mirror(result, project) if result["status"] == "set" else result
```

Change `add_item`'s body (line 102) from `return repository.add_item(project, title, folder_id=folder_id, status=status)` to:

```python
    result = repository.add_item(project, title, folder_id=folder_id, status=status)
    return _with_mirror(result, project) if result["status"] == "added" else result
```

Add one line to each docstring's outcome list, so the tool description matches what the tool returns:

- `set_status` — after "…so you can see if someone else moved it.": `` `mirror` reports whether the project's human-readable `_tracker.md` was refreshed. ``
- `add_item` — after "…unknown_project.": `` `mirror` reports whether the project's human-readable `_tracker.md` was refreshed. ``

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -q`
Expected: PASS

- [ ] **Step 5: Prove the additive claim**

Run: `cd backend && uv run pytest tests/test_mcp_server.py tests/test_item_scoping.py tests/test_set_status.py tests/test_statuses.py -q`
Expected: PASS — no existing test that reads `add_item` / `set_status` results should break, because no existing key changed.

- [ ] **Step 6: Run the whole suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/mcp_server.py backend/tests/test_mcp_server.py
git commit -m "feat(sync): MCP add_item/set_status report the mirror refresh"
```

---

## Task 6: The end-to-end walkthrough

**Files:**
- Create: `backend/tests/test_sync_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5, plus `onboard.run_onboard(slug=…, name=…, repo=…, home=…)`, `repository.list_items(slug) -> list[dict]` (each has `id`, `title`, `status`, `folder_id`), and the `home` / `temp_slug` fixtures from `conftest.py`.
- Produces: nothing other tasks consume.

**This is the only test that proves auto-refresh is wired to a door rather than merely implemented.** No fakes: real Postgres (the dedicated test database), real workspace, real CLI. It is the spec's "Success criteria" walkthrough, executed.

**One deliberate deviation from the spec:** the spec's no-refresh proof names `log`. `repository.add_session_log` calls `embed()`, which downloads an ONNX model on first use — a network dependency this test does not need. `add-folder` is used here instead (pure DB, and the more interesting case, since a folder *is* part of the mirror's structure), and `log`'s no-refresh behaviour is covered by `test_log_does_not_refresh` in Task 4. Say this in the commit message.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sync_e2e.py`:

```python
"""The generated mirror, end to end — real DB, real filesystem, real CLI.

Everything else about sync is unit-tested with fakes. This is the only test that
proves the auto-refresh is actually WIRED to a door rather than merely implemented,
which is a different claim and the one that breaks silently.

`_db_ready` (conftest.py) points this at the dedicated TEST database, never the one
`.env` configures.
"""

import pytest
from typer.testing import CliRunner

from app import cli as cli_mod
from app import repository
from app.onboard import run_onboard

runner = CliRunner()


@pytest.mark.db
def test_the_mirror_stays_true_through_the_cli_door(home, temp_slug, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_onboard(slug=temp_slug, name="Sync E2E", repo=repo, home=home)

    mirror = home / "projects" / temp_slug / "_tracker.md"
    assert mirror.exists(), "onboard should have written the mirror"
    assert "new thing" not in mirror.read_text(encoding="utf-8")

    # add-item refreshes it
    result = runner.invoke(cli_mod.app, ["add-item", temp_slug, "new thing"])
    assert result.exit_code == 0, result.output
    assert "new thing" in mirror.read_text(encoding="utf-8")

    # set-status refreshes it
    item_id = repository.list_items(temp_slug)[0]["id"]
    result = runner.invoke(cli_mod.app, ["set-status", temp_slug, str(item_id), "done"])
    assert result.exit_code == 0, result.output
    assert "- [x] new thing" in mirror.read_text(encoding="utf-8")

    # add-folder does not — `groups` is built by iterating items, so a folder with
    # no items renders nothing at all
    before = mirror.read_bytes()
    result = runner.invoke(cli_mod.app, ["add-folder", temp_slug, "Phase 1"])
    assert result.exit_code == 0, result.output
    assert mirror.read_bytes() == before

    # `trackden sync` is idempotent
    result = runner.invoke(cli_mod.app, ["sync", temp_slug])
    assert result.exit_code == 0, result.output
    once = mirror.read_bytes()
    result = runner.invoke(cli_mod.app, ["sync", temp_slug])
    assert result.exit_code == 0, result.output
    assert mirror.read_bytes() == once


@pytest.mark.db
def test_sync_of_an_unknown_project_creates_nothing(home, tmp_path):
    """The trap gate, at the real door: exit 1, and no file anywhere."""
    result = runner.invoke(cli_mod.app, ["sync", "definitely-not-a-project"])

    assert result.exit_code == 1, result.output
    assert not (home / "projects" / "definitely-not-a-project").exists()


@pytest.mark.db
def test_sync_repairs_a_mirror_that_drifted(home, temp_slug, tmp_path):
    """The command's whole reason to exist: a mirror made stale out-of-band —
    here by writing through the repository directly, as an agent or a `psql`
    session would — is repaired by one `trackden sync`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_onboard(slug=temp_slug, name="Sync E2E", repo=repo, home=home)
    mirror = home / "projects" / temp_slug / "_tracker.md"

    assert repository.add_item(temp_slug, "added behind the door")["status"] == "added"
    assert "added behind the door" not in mirror.read_text(encoding="utf-8")

    result = runner.invoke(cli_mod.app, ["sync", temp_slug])

    assert result.exit_code == 0, result.output
    assert "added behind the door" in mirror.read_text(encoding="utf-8")
```

- [ ] **Step 2: Start Postgres and run the test to verify it fails or passes honestly**

Run: `cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker && docker compose up -d db`
Then: `cd backend && uv run pytest tests/test_sync_e2e.py -q`
Expected: PASS if Tasks 1-5 are correct. If it SKIPS, Postgres is not reachable — fix that before continuing; a skipped e2e proves nothing.

- [ ] **Step 3: Prove it discriminates**

Temporarily remove the `_refresh_mirror(project)` call from `cli.add_item`, run the file, and confirm `test_the_mirror_stays_true_through_the_cli_door` FAILS on the `"new thing" in mirror` assertion. Restore it and confirm green.

- [ ] **Step 4: Run the whole suite with the DB up**

Run: `cd backend && uv run pytest -q`
Expected: PASS, with no skips in the `db`-marked set.

- [ ] **Step 5: Do NOT walk the success criteria by hand**

The spec's walkthrough is what the tests above execute, against the dedicated test database. Running it at a real terminal would mean `uv run trackden …` loading `.env`'s real `DATABASE_URL` — which is exactly how a stray row landed in the owner's real database during Stage B3. The e2e test is the verification; a hand-run adds risk and no evidence.

The one safe hand-check, because it touches no data:

```bash
cd backend && uv run trackden sync --help
```

Expected: the command's help text renders, and `[PROJECT]` is optional.

- [ ] **Step 6: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/tests/test_sync_e2e.py
git commit -m "test(sync): end-to-end — the mirror stays true through the CLI door

Uses add-folder rather than log for the no-refresh proof: add_session_log calls
embed(), which downloads an ONNX model on first use. log's no-refresh behaviour
is covered with fakes in test_cli_sync.py."
```

---

## Task 7: Documentation

**Files:**
- Modify: `_tracker.md` — the "What works today" table (around line 20), the `▸ NEXT` block (line 164), the session-state block (line 214)
- Modify: `QUICKSTART.md` — near the `trackden delete` paragraph (line 75)
- Modify: `README.md` — the "Architecture — one core, three doors" section (line 56)
- Modify: `AGENTS.md` — the generated-mirror paragraph (line 84)

**Interfaces:**
- Consumes: the shipped behaviour of Tasks 1-6.
- Produces: nothing code depends on.

**Every claim here must be true of the shipped code.** Counts in prose that disagree with the code are a recurring failure in this repo's history — check them against `uv run trackden --help` rather than against this plan.

- [ ] **Step 1: `_tracker.md` — the command table**

Add a row to the "What works today, as commands you can actually type" table, after the `trackden guidance` row:

```markdown
| `trackden sync [project]` | Rewrite a project's generated `_tracker.md` mirror from the DB — one project, or all of them. Runs automatically after `add-item` and `set-status`, so it is only needed to repair a mirror that drifted. Refuses a hand-edited file rather than overwriting it, and exits non-zero if any project could not be synced. |
```

- [ ] **Step 2: `_tracker.md` — move the queue on**

Replace the `▸ NEXT — trackden sync` block (starting line 164) with a `✅ DONE — trackden sync (shipped 2026-08-25)` block, and make the launcher the new `▸ NEXT`. The DONE block should state, in the tracker's existing voice:

- `render_tracker_md` now has three callers, not one: `run_onboard`, `sync.sync`, and through `sync` the two CLI/MCP write paths.
- The gate order and why `get_project` is first (the trap).
- Auto-refresh is exactly `add-item`/`add_item` and `set-status`/`set_status`, and why the other four writes are not.
- A refresh failure warns and exits 0 at the CLI; `trackden sync` itself exits non-zero on any non-`synced` project.
- No MCP `sync` tool — 17 tools unchanged; CLI is now **19** commands.

- [ ] **Step 3: `_tracker.md` — the session-state block**

Line 214 reads `CLI 18 commands, MCP 17 tools`. Update the command count to what `uv run trackden --help` actually prints, and update the suite count to what `uv run pytest -q` actually reports. Do not copy a number from this plan.

- [ ] **Step 4: `AGENTS.md`**

The paragraph at line 84 says the `_tracker.md` in a project's workspace folder is a generated mirror. Add one sentence: it is refreshed automatically after the writes that change it, and `trackden sync` repairs one that drifted. Keep the existing warning that it is never hand-edited.

- [ ] **Step 5: `QUICKSTART.md` and `README.md`**

- `QUICKSTART.md`: one short paragraph near the `trackden delete` note — what `trackden sync` is for, and that you rarely need it.
- `README.md`: in "Architecture — one core, three doors", note that the workspace mirror is derived output kept current by the doors.

- [ ] **Step 6: Verify the counts you wrote**

```bash
cd backend
uv run trackden --help          # confirm the command count in the docs
uv run pytest -q                # confirm the suite count in the docs
```

Expected: both match what you wrote. Fix the docs, not the numbers.

- [ ] **Step 7: Commit**

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add _tracker.md AGENTS.md QUICKSTART.md README.md
git commit -m "docs: trackden sync shipped; the launcher is the only thing left"
```

---

## Not in this plan, and why

So none of these read as oversights:

- **A `sync` MCP tool.** The mirror is human-facing; agents read state through `overview` / `list_items`, which query the DB and are never stale.
- **A `playbook.py` rule about the mirror.** The playbook steers agents, and agents do not read the mirror. No new tool means no playbook change.
- **Refreshing after `delete`.** The project is gone from the DB; its guidance folder is kept on purpose and its mirror is deliberately left as last-known state.
- **The FastAPI door (`main.py`).** It has no write path that changes items.
- **cwd → project resolution**, so a bare `trackden sync` could mean "this repo". `projects.repo_path` exists and stays unused — that is the `SessionStart` launcher's design problem, and guessing at it here would prejudge it.
- **Making the mirror a source of truth.** It stays derived output.

## After this plan

The `SessionStart` launcher is the next item, and the only mechanical guarantee still unbuilt. `sync` makes the mirror true; it does not make anyone read it.
