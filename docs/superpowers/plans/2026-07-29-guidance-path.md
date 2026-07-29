# Guidance read/write path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the guidance files onboarding creates readable by agents (`get_guidance`) and let agents record decisions into `_decisions.md` (`add_decision`), through both the MCP and CLI doors — so the guidance layer stops being write-only.

**Architecture:** `workspace.py` gains the filesystem read path it lacks (guidance filenames become a module constant, plus read/append/template-detect helpers). A new thin `guidance.py` orchestrates `repository` + `workspace` and owns the `status` vocabulary, so the MCP and CLI doors stay thin and cannot drift. `repository.add_memory` starts rejecting `kind="decision"` so a decision has exactly one home.

**Tech Stack:** Python 3.12+, sync SQLAlchemy 2.0, FastMCP, Typer, pytest. No new dependencies.

## Global Constraints

- **Spec of record:** `docs/superpowers/specs/2026-07-29-get-guidance-design.md`. Read it first.
- **No exceptions cross the MCP boundary.** Every failure is a `status` string the agent can act on. An exception reaches an agent as an opaque tool error it cannot reason about.
- **Neither tool scaffolds anything.** Reading must not write; `add_decision` refuses a missing workspace rather than creating one. Scaffolding stays onboarding's single job.
- **`because` is required** on `add_decision`. A decisions log recording what changed without why is the failure mode the file exists to prevent.
- **Status vocabulary is fixed:** `filled` · `template` · `not_scaffolded` · `unknown_project` · `unknown_doc` (get only) · `appended` (add only).
- **Document names are the public API:** `way-of-work` · `arch` · `decisions`. Filenames (`_way-of-work.md` …) stay internal.
- **Python 3.12+**, `str | None` unions, sync SQLAlchemy. Match the voice of `workspace.py` and `repository.py` — docstrings explain *why*, briefly.
- The work unit is an **item** — never "ticket"/"task"/"issue"/"bill".
- **Zero LLM calls** — no `anthropic`/`langchain` imports anywhere in this feature.
- **Never commit tracker DATA, only app code. Never `git commit`/`git push` without an explicit "yes" from Nuri** (personal account `dev-nuriengin`). Local commits per task are pre-authorised; **pushing is not**.
- Tests must not touch the real database. `conftest.py` already redirects to `session_tracker_test`; db-marked tests use `@pytest.mark.db` and the `temp_slug` fixture.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/workspace.py` | **Modify.** Add `GUIDANCE_DOCS`, `guidance_path`, `read_guidance`, `is_template`, `append_decision`. Filesystem only, base path injectable. |
| `backend/app/guidance.py` | **Create.** Orchestrates `repository` + `workspace`; owns the `status` vocabulary. The only new module. |
| `backend/app/repository.py` | **Modify.** `add_memory` rejects `kind="decision"`. |
| `backend/app/models.py` | **Modify.** Docstring + `kind` comment stop advertising `decision`. |
| `backend/app/mcp_server.py` | **Modify.** Add `get_guidance`, `add_decision`; narrow `add_memory`'s description and return. |
| `backend/app/cli.py` | **Modify.** Add `guidance` and `decide`; narrow `remember`. |
| `backend/tests/test_workspace.py` | **Modify.** Append guidance read/append tests. |
| `backend/tests/test_guidance.py` | **Create.** Orchestrator statuses, no DB. |
| `backend/tests/test_repository_onboard.py` | **Modify.** Append the `add_memory` rejection test. |
| `backend/tests/test_mcp_server.py` | **Modify.** Append tool registration + delegation tests. |
| `backend/tests/test_cli_guidance.py` | **Create.** CLI doors via `CliRunner`. |
| `QUICKSTART.md`, `AGENTS.md`, `BUILD_NOTES.md`, `_tracker.md` | **Modify.** Tool tables, routing table, build log. |

---

### Task 1: `workspace.py` — the guidance filesystem layer

**Files:**
- Modify: `backend/app/workspace.py`
- Test: `backend/tests/test_workspace.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `workspace.GUIDANCE_DOCS: dict[str, str]` — `{"way-of-work": "_way-of-work.md", "arch": "_arch.md", "decisions": "_decisions.md"}`
  - `workspace.guidance_path(slug: str, doc: str, home: Path | None = None) -> Path` — raises `ValueError` on an unknown doc
  - `workspace.read_guidance(slug: str, doc: str, home: Path | None = None) -> str | None` — `None` when the file does not exist
  - `workspace.is_template(doc: str, text: str, *, name: str) -> bool`
  - `workspace.append_decision(slug: str, decision: str, because: str, rejected: str | None = None, *, today: date | None = None, home: Path | None = None) -> Path | None` — `None` when the decisions file does not exist

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_workspace.py`:

```python
from datetime import date

from app.workspace import (
    GUIDANCE_DOCS,
    append_decision,
    guidance_path,
    is_template,
    read_guidance,
)


def test_guidance_docs_maps_public_names_to_filenames():
    assert GUIDANCE_DOCS == {
        "way-of-work": "_way-of-work.md",
        "arch": "_arch.md",
        "decisions": "_decisions.md",
    }


def test_guidance_path_is_inside_the_project_folder(home):
    assert guidance_path("p", "arch") == project_dir("p") / "_arch.md"


def test_guidance_path_rejects_an_unknown_doc(home):
    with pytest.raises(ValueError):
        guidance_path("p", "not-a-doc")


def test_guidance_path_still_rejects_an_unsafe_slug(home):
    with pytest.raises(ValueError):
        guidance_path("../escape", "arch")


def test_read_guidance_returns_none_when_not_scaffolded(home):
    assert read_guidance("p", "way-of-work") is None


def test_read_guidance_returns_the_file_text(home):
    scaffold_project("p", name="P")
    text = read_guidance("p", "arch")
    assert text is not None and "Architecture — P" in text


def test_is_template_recognises_untouched_scaffolding(home):
    scaffold_project("p", name="P")
    for doc in GUIDANCE_DOCS:
        text = read_guidance("p", doc)
        assert is_template(doc, text, name="P") is True


def test_is_template_is_false_once_edited(home):
    scaffold_project("p", name="P")
    path = guidance_path("p", "arch")
    path.write_text(path.read_text() + "\n- the real architecture\n", encoding="utf-8")
    assert is_template("arch", read_guidance("p", "arch"), name="P") is False


def test_is_template_is_false_for_a_seeded_way_of_work(home):
    scaffold_project("p", name="P", way_of_work="# rules from the repo\n")
    assert is_template("way-of-work", read_guidance("p", "way-of-work"), name="P") is False


def test_append_decision_returns_none_when_not_scaffolded(home):
    assert append_decision("p", "d", "b") is None


def test_append_decision_writes_the_template_shape(home):
    scaffold_project("p", name="P")
    path = append_decision(
        "p", "Use fastembed", "keeps the core keyless", "OpenAI (needs a key)",
        today=date(2026, 7, 29),
    )
    assert path == guidance_path("p", "decisions")
    text = path.read_text()
    assert "## 2026-07-29 — Use fastembed" in text
    assert "- **Chose:** Use fastembed" in text
    assert "- **Because:** keeps the core keyless" in text
    assert "- **Rejected:** OpenAI (needs a key)" in text


def test_append_decision_omits_rejected_when_absent(home):
    scaffold_project("p", name="P")
    text = append_decision("p", "d", "b", today=date(2026, 7, 29)).read_text()
    assert "- **Rejected:**" not in text.split("## 2026-07-29")[1]


def test_append_decision_keeps_earlier_entries_and_order(home):
    scaffold_project("p", name="P")
    append_decision("p", "first", "b1", today=date(2026, 7, 29))
    text = append_decision("p", "second", "b2", today=date(2026, 7, 30)).read_text()
    assert text.index("first") < text.index("second")


def test_append_decision_preserves_the_scaffolded_header(home):
    scaffold_project("p", name="P")
    text = append_decision("p", "d", "b", today=date(2026, 7, 29)).read_text()
    assert text.startswith("# Decisions — P")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_workspace.py -v`
Expected: FAIL — `ImportError: cannot import name 'GUIDANCE_DOCS' from 'app.workspace'`.

- [ ] **Step 3: Add the constant and rewire `scaffold_project` to use it**

In `backend/app/workspace.py`, add `from datetime import date` to the imports, and after `TRACKER_FILE`:

```python
# The public document names agents and the CLI use, mapped to the vendor-neutral
# filenames on disk. One mapping, used by both the write path (scaffolding) and the
# read path — so the two can never disagree about what a document is called.
GUIDANCE_DOCS = {
    "way-of-work": "_way-of-work.md",
    "arch": "_arch.md",
    "decisions": "_decisions.md",
}
```

Then replace `scaffold_project`'s `guidance` dict so it is keyed off the same constant:

```python
    guidance = {
        GUIDANCE_DOCS["way-of-work"]: way_of_work
        or _WAY_OF_WORK_TEMPLATE.format(name=display),
        GUIDANCE_DOCS["arch"]: _ARCH_TEMPLATE.format(name=display),
        GUIDANCE_DOCS["decisions"]: _DECISIONS_TEMPLATE.format(name=display),
    }
```

- [ ] **Step 4: Implement the read path**

Append to `backend/app/workspace.py`:

```python
_TEMPLATES = {
    "way-of-work": _WAY_OF_WORK_TEMPLATE,
    "arch": _ARCH_TEMPLATE,
    "decisions": _DECISIONS_TEMPLATE,
}


def guidance_path(slug: str, doc: str, home: Path | None = None) -> Path:
    """Where one guidance document lives. Validates both slug and document name."""
    if doc not in GUIDANCE_DOCS:
        raise ValueError(f"unknown guidance doc: {doc!r}")
    return project_dir(slug, home) / GUIDANCE_DOCS[doc]


def read_guidance(slug: str, doc: str, home: Path | None = None) -> str | None:
    """One guidance document's text, or None when it has not been scaffolded.

    Read-only on purpose: a missing file is reported, never created. Scaffolding is
    onboarding's job, and a folder holding one guidance file and no others would be
    worse than an honest "not scaffolded".
    """
    path = guidance_path(slug, doc, home)
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None


def is_template(doc: str, text: str, *, name: str) -> bool:
    """Is this document still untouched scaffolding?

    Compared against the rendered template rather than marked with a machine
    sentinel, so the files stay clean for a human to edit. The trade-off: renaming a
    project after scaffolding makes an untouched file look edited. The cost of that
    is an agent reading boilerplate once.
    """
    if doc not in _TEMPLATES:
        raise ValueError(f"unknown guidance doc: {doc!r}")
    return text == _TEMPLATES[doc].format(name=name)


def append_decision(
    slug: str,
    decision: str,
    because: str,
    rejected: str | None = None,
    *,
    today: date | None = None,
    home: Path | None = None,
) -> Path | None:
    """Append one decision to `_decisions.md`. Returns the path, or None if absent.

    `today` is injectable so tests are deterministic; production passes nothing.
    Append-only by design — the file's own header says "never rewrite history".
    """
    path = guidance_path(slug, "decisions", home)
    if not path.exists():
        return None

    stamp = (today or datetime.now(timezone.utc).date()).isoformat()
    lines = [
        "",
        f"## {stamp} — {decision}",
        "",
        f"- **Chose:** {decision}",
        f"- **Because:** {because}",
    ]
    if rejected:
        lines.append(f"- **Rejected:** {rejected}")
    lines.append("")

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path
```

Add `from datetime import date, datetime, timezone` to the imports (replacing the `date`-only import from Step 3).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workspace.py -v`
Expected: all pass (the 18 existing plus the 14 new).

- [ ] **Step 6: Run the full suite**

Run: `cd backend && uv run pytest -q`
Expected: 104 existing + 14 new = 118 passed. `scaffold_project` changed, so the onboarding tests are the ones to watch.

- [ ] **Step 7: Commit**

```bash
git add backend/app/workspace.py backend/tests/test_workspace.py
git commit -m "feat(guidance): add the workspace read path and decision append"
```

---

### Task 2: `guidance.py` — the orchestrator that owns the statuses

**Files:**
- Create: `backend/app/guidance.py`
- Test: `backend/tests/test_guidance.py`

**Interfaces:**
- Consumes: `workspace.GUIDANCE_DOCS`, `read_guidance`, `is_template`, `append_decision`, `guidance_path` (Task 1); `repository.get_project`.
- Produces:
  - `guidance.get(project: str, doc: str = "way-of-work") -> dict` — keys `project`, `doc`, `path`, `status`, `text`
  - `guidance.add_decision(project: str, decision: str, because: str, rejected: str | None = None) -> dict` — keys `project`, `path`, `status`, `message`

> **Amendment (2026-07-29, during execution) — supersedes the key lists above and the
> `result` shape in Step 3.** As first written this task contradicted itself: Step 3's code
> populated `result["text"]` with an explanatory message for `unknown_project` and
> `not_scaffolded`, while Step 1's tests asserted `text is None` for exactly those statuses.
> Following the tests (the implementer's correct instinct) then broke Task 5, whose CLI does
> `typer.echo(result["text"])` on failure statuses and would have printed the literal string
> `None` to the user.
>
> Neither half was right. `text` and "why you got nothing" are different things and must not
> share a field:
>
> - **`text: str | None`** — the document's content and *only* that. `None` for **every**
>   failure status, including `unknown_doc`.
> - **`message: str`** — the human-readable outcome. **Always a string, never `None`**;
>   `""` for `filled`, `template` and `appended`.
>
> So `get` returns six keys and `add_decision` four. Both doors print `message` verbatim —
> and a caller that must first check whether a key exists or is `None` is a caller that will
> eventually forget to. Rejected: composing the messages inside each wrapper, which would
> duplicate user-facing copy across two doors, the exact drift this module exists to prevent.
>
> Messages: `unknown_project` → `unknown project 'x'` · `not_scaffolded` → names
> `trackden onboard <slug>` as safe to re-run · `unknown_doc` → lists the valid document
> names. Step 1's test list gains assertions that `message` is non-empty on every failure and
> exactly `""` on every success, so chatter cannot leak into the success path.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_guidance.py`:

```python
"""The guidance orchestrator. No Postgres: `repository.get_project` is faked."""

from types import SimpleNamespace

import pytest

from app import guidance as guidance_mod
from app.guidance import add_decision, get
from app.workspace import guidance_path, scaffold_project


@pytest.fixture
def known_project(monkeypatch):
    """`repository.get_project` returns a project for 'p', nothing for anything else."""

    def get_project(slug):
        return SimpleNamespace(slug="p", name="P") if slug == "p" else None

    monkeypatch.setattr(guidance_mod.repository, "get_project", get_project)


def test_get_reports_unknown_project(home, known_project):
    result = get("nope")
    assert result["status"] == "unknown_project"
    assert result["text"] is None


def test_get_reports_not_scaffolded(home, known_project):
    result = get("p")
    assert result["status"] == "not_scaffolded"
    assert result["text"] is None


def test_get_reports_template_for_untouched_scaffolding(home, known_project):
    scaffold_project("p", name="P")
    result = get("p", "arch")
    assert result["status"] == "template"
    assert "Architecture — P" in result["text"]


def test_get_reports_filled_once_edited(home, known_project):
    scaffold_project("p", name="P")
    path = guidance_path("p", "arch")
    path.write_text(path.read_text() + "\n- real content\n", encoding="utf-8")
    result = get("p", "arch")
    assert result["status"] == "filled"
    assert "real content" in result["text"]


def test_get_defaults_to_way_of_work(home, known_project):
    scaffold_project("p", name="P")
    assert get("p")["doc"] == "way-of-work"


def test_get_reports_unknown_doc_without_raising(home, known_project):
    result = get("p", "not-a-doc")
    assert result["status"] == "unknown_doc"
    assert "way-of-work" in result["text"]


def test_get_reports_the_path_when_it_has_one(home, known_project):
    scaffold_project("p", name="P")
    assert result_path(get("p", "arch")) == str(guidance_path("p", "arch"))


def result_path(result):
    return result["path"]


def test_add_decision_reports_unknown_project(home, known_project):
    assert add_decision("nope", "d", "b")["status"] == "unknown_project"


def test_add_decision_reports_not_scaffolded(home, known_project):
    assert add_decision("p", "d", "b")["status"] == "not_scaffolded"


def test_add_decision_appends_and_reports_appended(home, known_project):
    scaffold_project("p", name="P")
    result = add_decision("p", "Use fastembed", "keeps the core keyless")
    assert result["status"] == "appended"
    assert "Use fastembed" in guidance_path("p", "decisions").read_text()


def test_add_decision_never_scaffolds(home, known_project):
    add_decision("p", "d", "b")
    assert not guidance_path("p", "decisions").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_guidance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.guidance'`.

- [ ] **Step 3: Implement the orchestrator**

Create `backend/app/guidance.py`:

```python
"""The guidance layer's read path and its one write — decisions.

Guidance (way-of-work, architecture, decisions) lives in vendor-neutral files under
`~/.trackden/projects/<slug>/`, because it is durable knowledge a human writes and
edits. The DB owns state; these files own guidance. This module is the seam between
them: it asks the DB whether a project is real, asks the workspace for the file, and
translates both into a `status` a caller can act on.

Why a status and never an exception: an exception reaching an agent over MCP is an
opaque tool error it cannot reason about, whereas `not_scaffolded` tells it exactly
what to do next. The MCP and CLI doors are both thin wrappers over this module, so
neither can drift from the other's behaviour.
"""

from __future__ import annotations

from . import repository, workspace

DEFAULT_DOC = "way-of-work"


def get(project: str, doc: str = DEFAULT_DOC) -> dict:
    """Read one guidance document. Never writes, never raises.

    Defaults to the way-of-work because reading the rules at the start of a session
    is the common case.
    """
    result = {"project": project, "doc": doc, "path": None, "status": "", "text": None}

    if doc not in workspace.GUIDANCE_DOCS:
        result["status"] = "unknown_doc"
        result["text"] = f"unknown doc {doc!r} — try one of: {', '.join(workspace.GUIDANCE_DOCS)}"
        return result

    row = repository.get_project(project)
    if row is None:
        result["status"] = "unknown_project"
        result["text"] = f"unknown project {project!r}"
        return result

    result["path"] = str(workspace.guidance_path(row.slug, doc))
    text = workspace.read_guidance(row.slug, doc)
    if text is None:
        result["status"] = "not_scaffolded"
        result["text"] = (
            f"no guidance folder for {row.slug!r} yet — run `trackden onboard {row.slug}` "
            "(safe to re-run) to scaffold it"
        )
        return result

    result["text"] = text
    result["status"] = "template" if workspace.is_template(doc, text, name=row.name) else "filled"
    return result


def add_decision(
    project: str, decision: str, because: str, rejected: str | None = None
) -> dict:
    """Append a decision — with its reasoning — to the project's `_decisions.md`.

    `because` is required by the signature: a decisions log that records what changed
    without why is the failure mode the file exists to prevent. Refuses to scaffold a
    missing workspace, so onboarding stays the only thing that creates those files.
    """
    result = {"project": project, "path": None, "status": ""}

    row = repository.get_project(project)
    if row is None:
        result["status"] = "unknown_project"
        return result

    path = workspace.append_decision(row.slug, decision, because, rejected)
    if path is None:
        result["path"] = str(workspace.guidance_path(row.slug, "decisions"))
        result["status"] = "not_scaffolded"
        return result

    result["path"] = str(path)
    result["status"] = "appended"
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_guidance.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/guidance.py backend/tests/test_guidance.py
git commit -m "feat(guidance): orchestrate guidance reads and decision appends"
```

---

### Task 3: give a decision exactly one home

**Files:**
- Modify: `backend/app/repository.py` (`add_memory`)
- Modify: `backend/app/models.py` (`Memory` docstring + `kind` comment)
- Test: `backend/tests/test_repository_onboard.py` (append)

**Interfaces:**
- Produces: `repository.MEMORY_KINDS: frozenset[str]` — `{"link", "note", "transcript"}`; `repository.add_memory` raises `ValueError` when `kind` is not in it.

**Why rejecting rather than un-advertising:** the storage model routes by intent — the tool *is* the destination. Two tools that both accept "a decision" is the ambiguity that rule exists to prevent, and an agent guessing the old kind must be told, not silently write into the wrong home. Validation sits in the repository so one check covers both doors.

**Safe to do now:** the `memory` table holds **0 rows of any kind** (verified against the live database 2026-07-29), so there is nothing to migrate.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_repository_onboard.py`:

```python
@pytest.mark.db
def test_add_memory_rejects_the_decision_kind(temp_slug):
    repository.create_project(temp_slug)
    with pytest.raises(ValueError) as excinfo:
        repository.add_memory(temp_slug, "we chose X", kind="decision")
    assert "add_decision" in str(excinfo.value)


@pytest.mark.db
def test_add_memory_still_accepts_its_remaining_kinds(temp_slug):
    repository.create_project(temp_slug)
    for kind in ("link", "note", "transcript"):
        assert repository.add_memory(temp_slug, f"a {kind}", kind=kind) is True


@pytest.mark.db
def test_add_memory_rejects_an_unknown_kind(temp_slug):
    repository.create_project(temp_slug)
    with pytest.raises(ValueError):
        repository.add_memory(temp_slug, "x", kind="nonsense")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_repository_onboard.py -v -k memory`
Expected: FAIL — `DID NOT RAISE <class 'ValueError'>`.

- [ ] **Step 3: Narrow `add_memory`**

In `backend/app/repository.py`, above `add_memory`:

```python
# Decisions deliberately absent: they belong in the project's `_decisions.md`, not the
# DB. The storage model routes by intent — the tool IS the destination — so accepting
# a decision here as well would give an agent two homes for one datum.
MEMORY_KINDS = frozenset({"link", "note", "transcript"})
```

Then, as the first statement in `add_memory`:

```python
    if kind not in MEMORY_KINDS:
        hint = " — use `add_decision`, which writes to the project's `_decisions.md`" if kind == "decision" else ""
        raise ValueError(
            f"unsupported memory kind {kind!r}; expected one of "
            f"{', '.join(sorted(MEMORY_KINDS))}{hint}"
        )
```

- [ ] **Step 4: Update the schema's own documentation**

In `backend/app/models.py`, the `Memory` class docstring and its `kind` comment currently advertise `decision`. Change the docstring's first line to read:

```python
    """Durable, concrete memory for a project — repo links, notes, meeting transcripts.

    Decisions are NOT here: they live in the project's `_decisions.md` guidance file
    (see `guidance.add_decision`), so each datum has exactly one home. Optionally
    scoped to a folder or item."""
```

and the column comment to `# link | note | transcript` .

Also update the module docstring's line `projects → memory  (durable facts: decisions, links, notes)` to drop `decisions`.

- [ ] **Step 5: Run to verify passing**

Run: `cd backend && uv run pytest tests/test_repository_onboard.py -v`
Expected: all pass (12 existing + 3 new).

- [ ] **Step 6: Run the full suite — this changes an existing contract**

Run: `cd backend && uv run pytest -q`
Expected: all pass. If an onboarding or CLI test called `add_memory` with `kind="decision"`, it will fail here — fix the test to use a remaining kind, and say so in your report.

- [ ] **Step 7: Commit**

```bash
git add backend/app/repository.py backend/app/models.py backend/tests/test_repository_onboard.py
git commit -m "feat(guidance): route decisions to _decisions.md, not the memory table"
```

---

### Task 4: the MCP door

**Files:**
- Modify: `backend/app/mcp_server.py`
- Test: `backend/tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `guidance.get`, `guidance.add_decision` (Task 2); `repository.MEMORY_KINDS` (Task 3).
- Produces: MCP tools `get_guidance`, `add_decision`; `add_memory` returns `dict` instead of `bool`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mcp_server.py`:

```python
def test_get_guidance_is_registered():
    assert mcp_server.mcp._tool_manager.get_tool("get_guidance") is not None


def test_add_decision_is_registered():
    assert mcp_server.mcp._tool_manager.get_tool("add_decision") is not None


def test_get_guidance_delegates_to_guidance(monkeypatch):
    seen = {}

    def fake_get(project, doc="way-of-work"):
        seen["args"] = (project, doc)
        return {"status": "filled", "text": "rules"}

    monkeypatch.setattr(mcp_server.guidance, "get", fake_get)
    result = mcp_server.get_guidance("korpus", doc="arch")
    assert seen["args"] == ("korpus", "arch")
    assert result["status"] == "filled"


def test_add_decision_delegates_to_guidance(monkeypatch):
    seen = {}

    def fake_add(project, decision, because, rejected=None):
        seen["args"] = (project, decision, because, rejected)
        return {"status": "appended"}

    monkeypatch.setattr(mcp_server.guidance, "add_decision", fake_add)
    result = mcp_server.add_decision("korpus", "chose X", "because Y", "not Z")
    assert seen["args"] == ("korpus", "chose X", "because Y", "not Z")
    assert result["status"] == "appended"


def test_add_memory_reports_a_rejected_kind_instead_of_raising(monkeypatch):
    def fake_add_memory(*args, **kwargs):
        raise ValueError("unsupported memory kind 'decision' — use `add_decision`")

    monkeypatch.setattr(mcp_server.repository, "add_memory", fake_add_memory)
    result = mcp_server.add_memory("korpus", "we chose X", kind="decision")
    assert result["status"] == "rejected_kind"
    assert "add_decision" in result["message"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: FAIL — `AttributeError: module 'app.mcp_server' has no attribute 'get_guidance'`.

- [ ] **Step 3: Add the tools and narrow `add_memory`**

In `backend/app/mcp_server.py`, extend the imports to `from . import guidance, repository`, then add after `list_memory`:

```python
@mcp.tool()
def get_guidance(project: str, doc: str = "way-of-work") -> dict:
    """The project's durable GUIDANCE — how it is worked on, its architecture, its
    decisions. Read `way-of-work` FIRST when you start on a project: it is the human's
    rules for this codebase. One document per call, so you never pay for what you are
    not using. doc: way-of-work | arch | decisions.
    `status` tells you what you got: filled (real content) · template (untouched
    boilerplate, don't over-read it) · not_scaffolded · unknown_project · unknown_doc."""
    return guidance.get(project, doc)


@mcp.tool()
def add_decision(
    project: str, decision: str, because: str, rejected: str | None = None
) -> dict:
    """Record a DECISION and its reasoning into the project's decisions log — use this
    whenever a choice gets made ("we decided X because Y"). `because` is required: a
    decision without its reason is worthless to the next session. `rejected` is the
    alternative you turned down, if there was one. This writes to the guidance file,
    NOT the memory table — for links and notes use add_memory instead."""
    return guidance.add_decision(project, decision, because, rejected)
```

Then replace the existing `add_memory` tool with:

```python
@mcp.tool()
def add_memory(
    project: str,
    content: str,
    kind: str = "note",
    title: str | None = None,
    url: str | None = None,
) -> dict:
    """Save a durable fact to the project's memory — a repo link, a note, a meeting
    transcript. kind: link | note | transcript.
    NOT for decisions: those go to add_decision, which writes them to the project's
    decisions guidance file so each fact has exactly one home."""
    try:
        saved = repository.add_memory(project, content, kind=kind, title=title, url=url)
    except ValueError as exc:
        return {"status": "rejected_kind", "message": str(exc)}
    return {"status": "saved" if saved else "unknown_project"}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd backend && uv run pytest tests/test_mcp_server.py -v`
Expected: all pass (2 existing + 5 new).

- [ ] **Step 5: Run the full suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/mcp_server.py backend/tests/test_mcp_server.py
git commit -m "feat(guidance): expose get_guidance and add_decision over MCP"
```

---

### Task 5: the CLI door

**Files:**
- Modify: `backend/app/cli.py`
- Test: `backend/tests/test_cli_guidance.py` (create)

**Interfaces:**
- Consumes: `guidance.get`, `guidance.add_decision` (Task 2).
- Produces: `trackden guidance <project> [--doc]`, `trackden decide <project> <decision> --because [--rejected]`; `remember`'s `--kind` help narrows.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cli_guidance.py`:

```python
import pytest
from typer.testing import CliRunner

from app import guidance as guidance_mod
from app.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_schema_check(monkeypatch):
    """The CLI ensures the schema on every command; these tests need no database."""
    monkeypatch.setattr("app.cli.init_db", lambda: None)


def test_guidance_prints_the_document(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": "/w/_arch.md",
            "status": "filled", "text": "# Architecture\n\n- a real component\n",
            "message": "",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus", "--doc", "arch"])
    assert result.exit_code == 0, result.output
    assert "a real component" in result.output


def test_guidance_flags_an_untouched_template(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": "/w/_arch.md",
            "status": "template", "text": "# Architecture — K\n", "message": "",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus", "--doc", "arch"])
    assert result.exit_code == 0, result.output
    assert "template" in result.output.lower()


def test_guidance_exits_non_zero_when_not_scaffolded(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": None,
            "status": "not_scaffolded", "text": None,
            "message": "run `trackden onboard korpus` (safe to re-run)",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus"])
    assert result.exit_code == 1
    assert "onboard" in result.output


def test_decide_appends_and_reports_the_path(monkeypatch):
    seen = {}

    def fake_add(project, decision, because, rejected=None):
        seen["args"] = (project, decision, because, rejected)
        return {
            "project": project, "path": "/w/_decisions.md",
            "status": "appended", "message": "",
        }

    monkeypatch.setattr(guidance_mod, "add_decision", fake_add)
    result = runner.invoke(
        app,
        ["decide", "korpus", "Use fastembed", "--because", "keeps it keyless",
         "--rejected", "OpenAI"],
    )
    assert result.exit_code == 0, result.output
    assert seen["args"] == ("korpus", "Use fastembed", "keeps it keyless", "OpenAI")
    assert "_decisions.md" in result.output


def test_decide_requires_because():
    result = runner.invoke(app, ["decide", "korpus", "Use fastembed"])
    assert result.exit_code != 0
    assert "because" in result.output.lower()


def test_decide_exits_non_zero_when_not_scaffolded(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "add_decision",
        lambda project, decision, because, rejected=None: {
            "project": project, "path": "/w/_decisions.md", "status": "not_scaffolded",
        },
    )
    result = runner.invoke(app, ["decide", "korpus", "d", "--because", "b"])
    assert result.exit_code == 1
    assert "onboard" in result.output
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_cli_guidance.py -v`
Expected: FAIL — every test exits non-zero with `No such command 'guidance'`.

- [ ] **Step 3: Add the commands**

In `backend/app/cli.py`, add `from . import guidance as guidance_mod` to the imports and append (before `if __name__ == "__main__":`):

```python
@app.command()
def guidance(
    project: str,
    doc: str = typer.Option("way-of-work", help="way-of-work | arch | decisions"),
):
    """Print one of a project's guidance documents."""
    result = guidance_mod.get(project, doc)
    if result["status"] in ("unknown_project", "not_scaffolded", "unknown_doc"):
        typer.echo(result["message"])  # `text` is None on every failure — see Task 2's amendment
        raise typer.Exit(1)
    if result["status"] == "template":
        typer.echo(f"({doc} is still the untouched template — {result['path']})\n")
    typer.echo(result["text"])


@app.command()
def decide(
    project: str,
    decision: str,
    because: str = typer.Option(..., help="Why this was chosen (required)"),
    rejected: str = typer.Option(None, help="The alternative you turned down"),
):
    """Record a decision, and its reasoning, in the project's decisions log."""
    result = guidance_mod.add_decision(project, decision, because, rejected)
    if result["status"] == "unknown_project":
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)
    if result["status"] == "not_scaffolded":
        typer.echo(
            f"no guidance folder for '{project}' yet — run `trackden onboard {project}` "
            "(safe to re-run) to scaffold it"
        )
        raise typer.Exit(1)
    typer.echo(f"✓ decision recorded in {result['path']}")
```

Then narrow `remember`'s option help and docstring:

```python
    kind: str = typer.Option("note", help="link | note | transcript"),
```

and its docstring to: `"""Save a durable fact (link / note / transcript) to a project's memory. For a decision use `trackden decide`."""`

Finally wrap its call so the rejection is readable rather than a traceback:

```python
    try:
        ok = repository.add_memory(project, content, kind=kind, title=title, url=url)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo("✓ saved to memory" if ok else f"unknown project '{project}'")
```

- [ ] **Step 4: Run to verify passing**

Run: `cd backend && uv run pytest tests/test_cli_guidance.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the full suite, then check the real help output**

Run: `cd backend && uv run pytest -q` — expected: all pass.
Run: `cd backend && uv run trackden guidance --help` and `uv run trackden decide --help`
Expected: the options match what Task 6 will document. (`--help` never touches the database.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli.py backend/tests/test_cli_guidance.py
git commit -m "feat(guidance): add trackden guidance and trackden decide"
```

---

### Task 6: one real end-to-end test, then the docs

**Files:**
- Test: `backend/tests/test_guidance.py` (append one `@pytest.mark.db` test)
- Modify: `QUICKSTART.md`, `AGENTS.md`, `BUILD_NOTES.md`, `_tracker.md`

**Interfaces:**
- Consumes: everything above.

**Why the db test:** every test so far fakes `repository.get_project`. The onboarding branch shipped a Critical bug — the CLI never ran its migration — precisely because nothing exercised the real repository together with the real orchestrator. One honest end-to-end test closes that gap.

- [ ] **Step 1: Write the failing end-to-end test**

Append to `backend/tests/test_guidance.py`:

```python
@pytest.mark.db
def test_guidance_end_to_end_against_the_real_repository(home, temp_slug):
    """No fakes: real DB row, real workspace, real orchestrator."""
    from app import repository

    assert repository.create_project(temp_slug, name="E2E Project") is True
    scaffold_project(temp_slug, name="E2E Project")

    fresh = get(temp_slug, "decisions")
    assert fresh["status"] == "template"

    appended = add_decision(temp_slug, "Use fastembed", "keeps the core keyless")
    assert appended["status"] == "appended"

    after = get(temp_slug, "decisions")
    assert after["status"] == "filled"
    assert "Use fastembed" in after["text"]
    assert "- **Because:** keeps the core keyless" in after["text"]
```

- [ ] **Step 2: Run it**

Run: `cd backend && uv run pytest tests/test_guidance.py -v -m db`
Expected: 1 passed, and **not** skipped. If it skips, Postgres is down — start it (`docker compose up -d db`) and re-run; a skip here means the test proved nothing.

- [ ] **Step 3: Document the two new MCP tools**

In `QUICKSTART.md`, add both to the MCP tool table, keeping its existing style and the ordering convention (cheap reads first, writes after):

```markdown
| `get_guidance` | read the project's rules / architecture / decisions — one doc per call |
| `add_decision` | record a decision **and why**, into the project's decisions log |
```

Update the `add_memory` row so it no longer claims decisions.

- [ ] **Step 4: Correct `AGENTS.md`**

`AGENTS.md` currently states guidance files are not exposed over MCP and that only DB-backed state travels there. That is now false. Rewrite that passage to say guidance is readable via `get_guidance`, that decisions are recorded with `add_decision`, and that `update_guidance` (editing rules/architecture from an agent) is still not available — a human edits those files directly.

- [ ] **Step 5: Update `BUILD_NOTES.md`'s routing table**

In the "LOCKED DESIGN — Storage model" routing table, the rows for `add_decision` and `get_guidance` are now shipped rather than planned. Mark them so, and in the "Implementation delta" list strike `add_decision` and `get_guidance` from "New tools to add", leaving `set_status` and `update_guidance`. Add a line noting the `memory` table narrowed to `link | note | transcript` and that decisions now live in `_decisions.md`.

- [ ] **Step 6: Tick `_tracker.md`**

Add a ticked phase recording what shipped — the workspace read path, the `guidance.py` orchestrator, the two MCP tools, the two CLI commands, and the memory-table narrowing — plus the still-open deferrals (`update_guidance`, `set_status`, indexing guidance in `search`, cwd→project resolution). Update the `**Status:**` counts to match.

- [ ] **Step 7: Full suite and commit**

Run: `cd backend && uv run pytest -q`
Expected: all pass, output pristine.

```bash
git add backend/tests/test_guidance.py QUICKSTART.md AGENTS.md BUILD_NOTES.md _tracker.md
git commit -m "docs(guidance): document get_guidance and add_decision; tick the build log"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| `get_guidance`, one doc per call, default way-of-work | 2 (logic), 4 (MCP), 5 (CLI) |
| `add_decision` with required `because`, template shape, UTC date | 1 (file write), 2 (orchestration) |
| Status vocabulary incl. `unknown_doc` on get only | 2 |
| `GUIDANCE_DOCS` constant shared by read and write paths | 1 |
| Neither tool scaffolds | 1 (`read_guidance`/`append_decision` return None), 2 (statuses), tested in both |
| No exceptions across the MCP boundary | 2 (returns statuses), 4 (`add_memory` catches `ValueError`) |
| `add_memory` narrows and **rejects** `decision`, validated in the repository | 3 |
| CLI doors | 5 |
| Testing conventions (no real DB, `@pytest.mark.db`, `temp_slug`) | 1, 2, 3, 6 |
| Limitations documented | 6 (docs), and `is_template`'s docstring in 1 |

**Placeholder scan:** none — every code step carries real code, every test step real assertions, every run step the exact command and expected result.

**Type consistency:** `GUIDANCE_DOCS` keys (`way-of-work`/`arch`/`decisions`) are the same strings in `guidance_path`, `is_template`, `guidance.get`, both MCP tools and both CLI commands. `read_guidance` returns `str | None` and `append_decision` returns `Path | None` — both consumed as such in Task 2. `guidance.get` always returns the same five keys; `guidance.add_decision` always the same three. `repository.MEMORY_KINDS` is defined in Task 3 and consumed in Tasks 4 and 5.

**One rough edge, flagged deliberately:** Task 4 changes the MCP `add_memory` tool's return type from `bool` to `dict`. Nothing consumes it programmatically — only an LLM reads it — and returning `{"status": "rejected_kind", "message": ...}` is the only way to explain a rejection without raising across the MCP boundary. Called out so the implementer does not treat it as accidental drift.
