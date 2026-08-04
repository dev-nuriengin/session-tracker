# Behaviour layer — Stage B3 (the playbook) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Trackden's own rules for using Trackden, so an arriving agent knows how to behave without the user explaining it — a full text served by `get_playbook()`, and a short digest that rides inside every `overview` response.

**Architecture:** A new pure module `playbook.py` owns the text, a digest, and a version. `get_playbook()` serves the full text as an MCP tool; `trackden playbook` serves it to a human. The digest is embedded in `overview`'s response, because `overview` is both the documented first call and the one an agent actually wants — putting the rules in a payload it already fetches beats hoping it calls a second tool. `trackden onboard` prints a paste-ready snippet for the user's own repo instructions; it never writes to the repo.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (sync) · Postgres · FastMCP · Typer · pytest

**Spec:** `docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md` — the Stage B3 rows. The `SessionStart` launcher/hook remains **out of scope**; it is the next increment and the only mechanical guarantee an agent reads any of this.

## Global Constraints

- **No new dependencies.**
- **`playbook.py` must be PURE** — no DB, no filesystem, no `app.*` imports. Same rule `statuses.py` and `tracker_md.py` follow.
- **The playbook is product-owned and READ-ONLY.** No tool or command writes it. If a user wants different behaviour, that belongs in their `_way-of-work.md`, which the playbook itself says outranks it.
- **No exception may cross the MCP boundary**; outcomes travel as a `status` string in a returned dict.
- **MCP tools and CLI commands are thin wrappers.** No business logic.
- **Every rule in the playbook must be TRUE of the shipped code.** A rule instructing an agent to call something that does not exist, or that behaves differently, is worse than no rule. Task 1's tests check the tools named in the text actually exist.
- **`overview`'s existing response keys keep their names.** A Next.js frontend consumes that shape via `GET /projects/{slug}`; the digest is additive.
- DB tests carry `@pytest.mark.db`; `conftest.py`'s guard refusing any test database whose name does not end in `_test`/`_smoke` protects six real user projects. Never weaken it.
- **Run tests from `backend/`:** `cd backend && uv run pytest`
- **Baseline: 334 tests passing** at `c07e19c`. Report the actual count after every task.
- **Git:** personal account `dev-nuriengin`. Commit per task. **Never push** — the user says yes separately.

## Two corrections to the spec, made while planning

**1. The spec's draft digest is partly false now.** It was written before Stages A, B1 and B2 shipped. Three changes:

- Its rule 5 said only "never invent a status name". Incomplete: the repo owner later ruled that an item whose status is in **no** vocabulary is deliberately offered as the next step, so it surfaces and gets fixed. An agent will be handed such an item, and the playbook must say that is intentional and tell it to offer a correction.
- It had **no rule about creating work**, because `add_item`/`add_folder`/`add_status` did not exist. They do now, and an agent that does not know it can create an item will keep asking the user to.
- Its rules 8 and 9 described the `file` kind and item scoping as things to do; both are real now and can name the actual tools and parameters.

**2. The digest size budget rises from 1200 to 1500 characters.** I set 1200 in the spec before writing the rules; the eleven rules below come to roughly 1250. 1500 characters is about 375 tokens riding on every `overview` call — acceptable for the payload that replaces an agent guessing. Task 5 amends the spec.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/playbook.py` | **Create.** Trackden's own rules: `VERSION`, `DIGEST`, `TEXT`. Pure. |
| `backend/app/mcp_server.py` | Agent door. | One new tool, `get_playbook` (16 → 17). |
| `backend/app/cli.py` | Human door. | One new command, `playbook` (16 → 17). |
| `backend/app/repository.py` | DB state. | `overview` gains a `playbook` key. |
| `backend/app/onboard.py` | Onboarding. | Prints a paste-ready snippet. No logic change. |
| `backend/tests/test_playbook.py` | **Create.** Pure tests: version, size budget, every rule present, every named tool exists. |

**Not touched:** `statuses.py`, `tracker_md.py`, `guidance.py`, `workspace.py`, `models.py`, `db.py`, the frontend, Docker.

---

### Task 1: `playbook.py` — the rules, pure

**Files:**
- Create: `backend/app/playbook.py`
- Test: `backend/tests/test_playbook.py`

**Interfaces:**
- Produces: `playbook.VERSION: int` · `playbook.DIGEST: str` · `playbook.TEXT: str` · `playbook.MAX_DIGEST = 1500`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_playbook.py`:

```python
"""Trackden's own rules — pure, so no Postgres is involved.

The sharpest test here is `test_every_tool_the_text_names_actually_exists`: a rule
telling an agent to call something that is not there is worse than no rule at all.
"""

import pytest

from app import playbook


def test_the_version_is_an_integer():
    assert isinstance(playbook.VERSION, int)
    assert playbook.VERSION >= 1


def test_the_digest_names_its_version():
    assert f"v{playbook.VERSION}" in playbook.DIGEST


def test_the_digest_stays_within_its_budget():
    """It rides inside EVERY overview response, so the budget is asserted, not hoped for."""
    assert len(playbook.DIGEST) <= playbook.MAX_DIGEST


def test_the_digest_holds_all_eleven_rules():
    for n in range(1, 12):
        assert f"{n}." in playbook.DIGEST, f"rule {n} missing from the digest"


def test_the_full_text_holds_all_seven_sections():
    for heading in (
        "What Trackden is",
        "Opening a session",
        "When to save",
        "Statuses",
        "Growing the vocabulary",
        "Files and the hybrid rule",
        "Precedence and anti-patterns",
    ):
        assert heading in playbook.TEXT, f"section missing: {heading}"


def test_the_full_text_is_longer_than_the_digest():
    assert len(playbook.TEXT) > len(playbook.DIGEST)


def test_the_text_says_the_project_outranks_the_playbook():
    """The precedence rule is the one that keeps this from overriding a human."""
    lowered = playbook.TEXT.lower()
    assert "way-of-work" in lowered
    assert "outrank" in lowered or "wins" in lowered


def test_the_text_says_trackden_never_touches_files():
    lowered = playbook.TEXT.lower()
    assert "never create" in lowered or "never creates" in lowered


def test_the_text_says_a_decision_needs_its_reason():
    assert "because" in playbook.TEXT.lower()


def test_every_tool_the_text_names_actually_exists():
    """A rule naming a tool that does not exist is worse than no rule.

    Checks the real MCP server's registry, so the playbook cannot drift from the
    tools it instructs an agent to call.
    """
    import re

    from app import mcp_server

    registered = {
        name
        for name in dir(mcp_server)
        if mcp_server.mcp._tool_manager.get_tool(name) is not None
    } if False else set()

    # `dir()` plus the tool manager is awkward; ask the manager directly instead.
    manager = mcp_server.mcp._tool_manager
    named = set(re.findall(r"\b([a-z_]+)\(", playbook.TEXT + playbook.DIGEST))
    # Only check names that look like our tools, not prose like "e.g.(" or python builtins.
    candidates = {
        n for n in named
        if n in {
            "overview", "get_guidance", "add_decision", "add_item", "add_folder",
            "add_status", "set_status", "add_memory", "save_progress", "get_history",
            "list_items", "list_memory", "list_statuses", "whats_next", "search",
            "get_playbook", "list_projects",
        }
    }
    assert candidates, "the text names no tools at all — that cannot be right"
    for name in sorted(candidates):
        assert manager.get_tool(name) is not None, f"playbook names a missing tool: {name}"


def test_the_module_is_pure():
    """No DB, no filesystem, no app imports — same rule statuses.py follows."""
    import pathlib

    source = pathlib.Path(playbook.__file__).read_text(encoding="utf-8")
    for forbidden in ("from .", "import os", "SessionLocal", "open("):
        assert forbidden not in source, f"playbook.py must stay pure; found {forbidden!r}"
```

> **Note on `test_every_tool_the_text_names_actually_exists`:** the first `registered = ...
> if False else set()` expression is dead scaffolding — DELETE it and keep only the
> `manager`-based check below it. It is left visible here so the intent is clear: interrogate
> the real tool manager, not a hand-maintained list of names.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_playbook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.playbook'`

- [ ] **Step 3: Write the module**

Create `backend/app/playbook.py`. **Every rule below must be true of the shipped code** —
the tests check the named tools exist.

```python
"""Trackden's own rules for using Trackden — product-owned, read-only.

Distinct from `guidance.py`, which serves the HUMAN's rules for ONE project. This is
the same for every user and ships with the code, so it lives here as a module constant
rather than a data file: `pyproject.toml` declares `packages = ["app"]`, and a Python
constant is guaranteed into the wheel with no packaging configuration, and is directly
assertable in a pure test.

The two are allowed to disagree. When they do, the project's way-of-work wins — rule 11
says so, because a product should not overrule the person using it.

Pure by design: no DB, no filesystem, no `app.*` imports.
"""

from __future__ import annotations

VERSION = 1

# The digest rides inside EVERY `overview` response. That is deliberate: an agent cannot
# be relied on to call a second tool for the rules, so the rules travel in the payload it
# already wants. The budget is asserted by a test — see MAX_DIGEST.
MAX_DIGEST = 1500

DIGEST = """TRACKDEN PLAYBOOK v1

1.  Read before you work: overview, then get_guidance("way-of-work").
2.  Trackden remembers; it never decides. Don't let it gate or approve work.
3.  Save on any of four triggers: a step finished; a decision made; you hold
    findings that aren't written down yet; the user says save.
4.  Work not yet tracked? add_item() it before you start. Ask before inventing
    folders - the shape of the user's work is theirs, not yours.
5.  Status: set `doing` freely and silently. Announce a `waiting` change in one
    line. ASK before you close anything.
6.  Never invent a status name - `statuses` in this payload is the valid set. If
    an item comes back with a name that is NOT in it, that is deliberate: an
    unclassifiable status is surfaced so a human can fix it. Offer to fix it.
7.  The set is meant to grow. If the user's real state has no name ("on hold" is
    not "blocked"), offer add_status(), and explain what the CLASS does.
8.  A decision needs its reason: add_decision(decision, because).
9.  Files stay in the user's folders. Ask where it goes, then record the path
    with add_memory(kind="file"). Never create, move or read anything.
10. Attach to the item, not the project: add_memory(item_id=...) and
    save_progress(item_id=...). Resume one item with get_history(item_id=...).
11. The project's way-of-work outranks this playbook. Conflict: follow the project.
"""

TEXT = """# Trackden playbook v1

Trackden's own rules for using Trackden. Read this once per session; the short digest
in every `overview` response is the reminder.

## 1. What Trackden is, and what it is not

A local, private memory of the user's work. It holds structure and progress so a new
session does not start from nothing.

It is NOT an agent. It does no work, and it does not gate, approve or sequence yours.
It never refuses a status change, never enforces an order, never locks anything. When
you find yourself treating it as an authority, you have the relationship backwards: it
records, the user decides.

## 2. Opening a session

Call `overview(project)` first. It is cheap and carries the next step, how many items
are open, how many are waiting, the last activity, this project's valid status names,
and this digest.

Then `get_guidance(project, "way-of-work")` before you change anything — those are the
human's rules for this codebase. If it comes back `template`, it is untouched
boilerplate; do not over-read it.

Resuming one specific item? `get_history(project, item_id=...)` gives that item's whole
story — its logs, its files, its status — instead of the project's last N entries mixed
with every other item's.

If the project is unknown, say so and ask. Do not invent a slug.

## 3. When to save

Four triggers. Any one of them is enough:

- **A step finished.** `save_progress(project, thread_id, note, kind="step")`.
- **A decision was made.** `add_decision(project, decision, because=...)`.
- **You hold findings that are not written down yet.** This is the one that gets
  missed. If the session ended right now, would anything you learned be lost? Then
  save. A cause identified but not fixed is exactly this case.
- **The user says save.**

You cannot reliably tell how much time has passed, so do not try to save "every N
minutes". `overview` reports last activity — if the gap looks long, mention it.

## 4. Statuses

Every status name behaves as one of four CLASSES:

- `open` — not started. Can be offered as the next step.
- `active` — being worked on. Also offered; an item someone is on IS the next step.
- `waiting` — started, stalled. Skipped as the next step, but counted and still listed.
- `closed` — finished or abandoned. Hidden from the queue.

How loudly to speak scales with how expensive being wrong is:

- Setting `doing` — just do it, silently. Cheap and obvious.
- Setting a `waiting` name — do it, then say so in one line. The user needs to know
  something stalled, but it is reversible.
- Closing anything — ASK first, unless the user just told you it is finished. Closing
  hides an item from the queue.

`set_status(project, item_id, status)` returns `unknown_status` with the `valid` list if
you get a name wrong, so correct yourself from that rather than guessing again.

**An item whose status is in no vocabulary at all will be offered to you as the next
step.** That is deliberate, not a bug: a legacy row or one edited by hand surfaces
instead of hiding, so it gets noticed. Tell the user and offer to set a real status.

## 5. Growing the vocabulary

The four shipped names — `todo`, `doing`, `blocked`, `done` — are a starting set, not a
limit. A project can add its own with `add_status(project, name, behaves_as)`.

Offer; do not impose. When the user's real situation has no matching name, name the
mismatch rather than forcing their state into a label that is nearly right:

> "This isn't blocked — nothing is in your way, you chose to set it aside. Want a
> `parked` status? It would behave as `waiting`, so it stays visible but stops showing
> up as your next step."

Explain what the class DOES, not just what the name is. The user is choosing behaviour.

## 6. Files and the hybrid rule

The user's folder layout is theirs. Trackden stores WHERE something is and never
creates, moves, deletes or reads it.

So: ask where a file belongs, let the user answer, then record the path with
`add_memory(project, content, kind="file", path=..., item_id=...)`. The path is stored
absolute, so it survives a different working directory. A path that does not exist yet
is still recorded, with a warning — recording where something is about to go is
legitimate.

Attach memory and progress to the item they belong to (`item_id=...`) whenever the fact
is about one item. Project-level is right for genuinely project-level facts and wrong
for a specific bug's findings.

Decisions do not go here. `add_memory` accepts `link`, `note`, `transcript` and `file`,
and rejects `decision` — use `add_decision`, so a decision has exactly one home.

## 7. Precedence and anti-patterns

**The project's `_way-of-work.md` outranks this playbook.** Where they conflict, follow
the project. This document is a default, not an authority.

Do not:

- guess a status name — `statuses` in the `overview` payload is the valid set;
- record a decision without its reason — `because` is required, and a decision without
  it is worthless to the next session;
- invent a folder structure without asking;
- create, move or read a file the user did not ask you to;
- claim you saved something you did not;
- treat Trackden as an approval step. It is memory.
"""
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_playbook.py -v`
Expected: PASS — 11 tests. If `test_the_digest_stays_within_its_budget` fails, trim the
digest's prose; do NOT raise `MAX_DIGEST` to make it pass.

- [ ] **Step 5: Whole suite, then commit**

Run: `cd backend && uv run pytest -q`. Baseline **334**; expect **345**. Report actual.

```bash
cd /Users/nuriengin/Desktop/Dev/_Personal/session-tracker
git add backend/app/playbook.py backend/tests/test_playbook.py
git commit -m "feat(playbook): Trackden's own rules for using Trackden

Product-owned and read-only, distinct from guidance.py which serves the HUMAN's
rules for one project. The two may disagree; rule 11 says the project wins,
because a product should not overrule the person using it.

A module constant rather than a data file: guaranteed into the wheel with no
packaging config, and directly assertable in a pure test. One of those tests
interrogates the real MCP tool manager, so the text cannot drift from the tools
it tells an agent to call.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: the two doors

**Files:**
- Modify: `backend/app/mcp_server.py` — add `get_playbook` (16 → 17 tools)
- Modify: `backend/app/cli.py` — add `playbook` (16 → 17 commands)
- Test: extend `backend/tests/test_mcp_server.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `playbook.VERSION`, `playbook.TEXT` (Task 1).
- Produces: MCP tool `get_playbook() -> dict` returning `{"version": int, "text": str}`; CLI command `trackden playbook`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mcp_server.py` — this file calls tools DIRECTLY (no `.fn`) and
asserts registration via `mcp_server.mcp._tool_manager.get_tool("<name>")`:

```python
def test_get_playbook_is_registered():
    assert mcp_server.mcp._tool_manager.get_tool("get_playbook") is not None


def test_get_playbook_returns_the_version_and_the_text():
    from app import playbook

    result = mcp_server.get_playbook()
    assert result == {"version": playbook.VERSION, "text": playbook.TEXT}


def test_get_playbook_takes_no_arguments():
    """It is product-wide — it must work before any project exists."""
    import inspect

    assert not inspect.signature(mcp_server.get_playbook).parameters
```

Append to `backend/tests/test_cli.py` (module-level `runner`, `_no_schema(monkeypatch)` in
every test):

```python
def test_playbook_prints_the_rules(monkeypatch):
    _no_schema(monkeypatch)
    result = runner.invoke(cli_mod.app, ["playbook"])
    assert result.exit_code == 0, result.output
    assert "TRACKDEN PLAYBOOK" in result.output or "Trackden playbook" in result.output


def test_playbook_needs_no_project(monkeypatch):
    """Product-wide: it must not require a project argument."""
    _no_schema(monkeypatch)
    assert runner.invoke(cli_mod.app, ["playbook"]).exit_code == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_mcp_server.py tests/test_cli.py -v`
Expected: FAIL — no `get_playbook` attribute; `No such command 'playbook'`.

- [ ] **Step 3: Add the MCP tool**

In `backend/app/mcp_server.py`, import the module alongside the existing
`from . import guidance, repository` and add the tool after `list_statuses`:

```python
@mcp.tool()
def get_playbook() -> dict:
    """Trackden's own rules for using Trackden — read this once per session.

    Covers when to save, how to change a status and when to ask first, how to grow a
    project's status vocabulary, and how files are handled (Trackden stores a path and
    never touches the file). Takes no arguments: it is the same for every project and
    works before any project exists.

    A short digest already rides in every `overview` response; call this when you want
    the reasoning behind it. Note that the project's own way-of-work outranks this
    document — read it with get_guidance(project, "way-of-work")."""
    return {"version": playbook.VERSION, "text": playbook.TEXT}
```

- [ ] **Step 4: Add the CLI command**

```python
@app.command()
def playbook():
    """Print Trackden's own rules for using Trackden (what agents read)."""
    from . import playbook as playbook_mod

    typer.echo(playbook_mod.TEXT)
```

Import it at the top with the other modules rather than inside the function if that matches
the file's existing style — check how `guidance` and `onboard` are imported and follow it.

- [ ] **Step 5: Run the tests, confirm the counts, commit**

Run the two test files, then `cd backend && uv run pytest -q`. Baseline **345**; expect
**350**. Confirm `grep -c "@mcp.tool()" app/mcp_server.py` = **17** and
`grep -c "^@app.command" app/cli.py` = **17**.

```bash
git add backend/app/mcp_server.py backend/app/cli.py backend/tests/test_mcp_server.py backend/tests/test_cli.py
git commit -m "feat(playbook): serve the playbook over MCP and the CLI

get_playbook takes no arguments — it is product-wide and works before any project
exists, unlike get_guidance which needs a project. Tool count 16 -> 17, command
count 16 -> 17.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: the digest rides inside `overview`

**Files:**
- Modify: `backend/app/repository.py` — `overview`
- Modify: `backend/app/mcp_server.py` — the `overview` tool docstring
- Test: `backend/tests/test_open_semantics.py` (extend — it already covers `overview`)

**Interfaces:**
- Produces: `overview()`'s dict gains `playbook: {"version": int, "digest": str}`. Every existing key keeps its name.

**Why this and not a second tool call:** a tool that exists is not a tool that gets called.
`overview` is both the documented first call and the one an agent actually wants, so the
rules travel in the payload it already fetches. This is steering, not a guarantee — the
guarantee is the `SessionStart` launcher, which is the next increment.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_open_semantics.py` (module-level `pytestmark = pytest.mark.db`,
existing `project` fixture):

```python
def test_overview_carries_the_playbook_digest(project):
    """An agent must not have to call a second tool to learn the rules."""
    from app import playbook

    slug, _ = project
    carried = repository.overview(slug)["playbook"]
    assert carried["version"] == playbook.VERSION
    assert carried["digest"] == playbook.DIGEST


def test_overview_keeps_every_pre_existing_key(project):
    """A Next.js frontend consumes this shape — the digest is additive only."""
    slug, _ = project
    keys = set(repository.overview(slug))
    assert {
        "project", "next", "open_items", "open_preview",
        "waiting_items", "memory_entries", "last_activity", "statuses",
    } <= keys


def test_an_unknown_project_still_returns_an_empty_dict():
    """The digest must not turn a miss into a hit."""
    assert repository.overview("no-such-project-xyz") == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_open_semantics.py -v -k playbook`
Expected: FAIL — `KeyError: 'playbook'`.

- [ ] **Step 3: Add the key**

Import `playbook` in `repository.py` alongside `from . import models, statuses as st`, and add
to `overview`'s returned dict — **after** the existing keys, changing none of them:

```python
            # The rules ride in the payload an agent already fetches: it cannot be relied
            # on to call get_playbook() for them. Steering, not a guarantee — the
            # guarantee is a SessionStart hook, which is a separate increment.
            "playbook": {"version": playbook.VERSION, "digest": playbook.DIGEST},
```

Do NOT add it to the unknown-project branch — that returns `{}` and must keep doing so.

- [ ] **Step 4: Update the `overview` tool docstring**

`mcp_server.py`'s `overview` description should now mention that the response carries
Trackden's playbook digest, and that `get_playbook()` has the full text. Keep it to the
density of the neighbouring docstrings.

- [ ] **Step 5: Run the tests, then the whole suite, then commit**

Baseline **350**; expect **353**. Report actual.

```bash
git add backend/app/repository.py backend/app/mcp_server.py backend/tests/test_open_semantics.py
git commit -m "feat(playbook): the digest rides inside every overview response

A tool that exists is not a tool that gets called. overview is both the documented
first call and the one an agent actually wants, so the rules travel in the payload
it already fetches rather than waiting on a second call it may never make.

Steering, not a guarantee. The guarantee is a SessionStart hook, and that is the
next increment. Every pre-existing overview key keeps its name — the Next.js
frontend consumes this shape.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `onboard` prints a paste-ready snippet

**Files:**
- Modify: `backend/app/onboard.py` — the summary at the end of `run_onboard`
- Test: extend `backend/tests/test_onboard.py` or `backend/tests/test_cli_onboard.py` — read both and put it wherever the existing summary output is asserted

**Interfaces:** no signature changes. `run_onboard` prints additional lines; `OnboardResult` is unchanged.

**The rule this must not break:** Trackden **never writes to the user's repo**. `workspace.py`'s
header says so and onboarding's whole design depends on it. So this PRINTS a snippet for the
user to paste into their own `CLAUDE.md`/`AGENTS.md` if they want it. It must not create or
modify any file in the repo.

- [ ] **Step 1: Write the failing test**

Read the existing onboarding tests first and match their style. The test must assert that
`run_onboard`'s output contains a paste-ready line mentioning Trackden and the `overview`
call, and — importantly — that no file was created in the scanned repo:

```python
def test_onboard_prints_a_paste_ready_snippet_without_writing_to_the_repo(tmp_path, home, capsys):
    """Trackden never writes to the user's repo — it prints, the user pastes."""
    repo = tmp_path / "some-repo"
    repo.mkdir()
    before = {p.name for p in repo.iterdir()}

    onboard_mod.run_onboard("snippet-demo", name="Snippet Demo", repo=str(repo), no_import=True)

    printed = capsys.readouterr().out
    assert "trackden" in printed.lower()
    assert "overview" in printed
    assert {p.name for p in repo.iterdir()} == before, "onboard must not write to the repo"
```

Adapt the call signature and fixtures to whatever the existing onboarding tests use — read
them rather than assuming. If `run_onboard` needs a DB, mark the test `@pytest.mark.db` and
use the `temp_slug` fixture for cleanup.

- [ ] **Step 2: Run to verify failure**, then add the print.

The snippet should be short and copy-pasteable, e.g.:

```
  Paste into this repo's CLAUDE.md / AGENTS.md if you want agents to find it:

    This project is tracked in Trackden. Call `overview("<slug>")` first —
    it carries the next step, the valid statuses, and Trackden's playbook digest.

  (Trackden never writes to your repo. Copy it yourself, or don't.)
```

- [ ] **Step 3: Run the onboarding tests, the whole suite, then commit**

Baseline **353**; expect **354**. Report actual.

```bash
git add backend/app/onboard.py backend/tests/<the file you edited>
git commit -m "feat(playbook): onboard prints a paste-ready snippet, and writes nothing

Continuity currently depends on the user remembering to mention Trackden. This
gives them one line to paste into their own repo instructions — printed, never
written, because Trackden not touching the user's repo is the promise onboarding
is built on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: docs, the spec corrections, and a live agent check

- [ ] **Step 1: Verify the digest actually reaches an agent path**

Prove the wiring end to end against the real database with a throwaway project, and paste
verbatim output into your report:

```bash
cd backend
uv run trackden add-project b3-smoke --name "B3 smoke"
uv run trackden playbook | head -20
uv run python -c "
from app import repository
ov = repository.overview('b3-smoke')
print('keys:', sorted(ov))
print('playbook version:', ov['playbook']['version'])
print('digest chars:', len(ov['playbook']['digest']))
print(ov['playbook']['digest'][:200])
"
```

Confirm: `trackden playbook` printed the full text; `overview` carries a `playbook` key with
the version and a digest under 1500 characters; and every pre-existing key is still present.

Then delete the throwaway project through the ORM — a plain `DELETE FROM projects` fails on
foreign keys — using the same approach `tests/conftest.py`'s `_delete_project_cascading` takes,
and confirm it worked.

- [ ] **Step 2: Amend the spec** (`docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md`)

Three corrections, each stated as a correction rather than a silent edit:
1. The draft digest's rule 5 was incomplete — an unclassifiable status is deliberately
   offered as the next step (the owner's ruling), so the playbook must say so and tell the
   agent to offer a fix.
2. The draft had no rule about creating work; `add_item`/`add_folder`/`add_status` did not
   exist when it was written.
3. The digest budget is **1500** characters, not 1200. The eleven rules need ~1250; 1500 is
   about 375 tokens on every `overview` call.

Mark Stage B3 delivered in the staging table, leaving the `SessionStart` launcher open.

- [ ] **Step 3: Update `_tracker.md` and `QUICKSTART.md`**

- Add `trackden playbook` to the command table and `get_playbook` to the MCP tool list.
- Note that `overview` now carries the playbook digest.
- Remove any claim that no playbook ships — grep: `grep -n -i "playbook" _tracker.md`.
- Record what remains: the **`SessionStart` launcher**, the only mechanical guarantee an
  agent reads any of this; everything shipped so far is steering.
- Carry forward the two open notes from B2: a folder-scoped reader should derive `folder_id`
  from the item when `item_id` is given, and `trackden delete` must delete session logs and
  memory explicitly before the project.
- Tick B3's items; recount checkboxes with `grep -cE '^\s*-\s*\[x\]' _tracker.md` and the
  `[ ]` equivalent, reporting both raw numbers; update the test count from a real run.

- [ ] **Step 4: Whole suite, then commit**

```bash
git add _tracker.md QUICKSTART.md docs/superpowers/specs/2026-08-01-trackden-behaviour-layer-design.md
git commit -m "docs: Stage B3 shipped — the playbook, and what still isn't guaranteed

Corrects three things the spec's draft digest got wrong before A/B1/B2 shipped: an
unclassifiable status is deliberately offered (the owner's ruling), there was no
rule about creating work because those tools did not exist, and the digest budget
is 1500 characters rather than 1200.

Records what remains: the SessionStart launcher. Everything shipped so far steers
an agent toward the rules; only a hook guarantees it reads them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage (B3 rows):**

| Requirement | Task |
|---|---|
| `playbook.py`, pure, product-owned | 1 |
| Full text, seven sections | 1 |
| Digest with a version and an asserted budget | 1 |
| `get_playbook` MCP tool | 2 |
| CLI access for the human | 2 |
| Digest inside every `overview` | 3 |
| Onboard prints a paste-snippet, writes nothing | 4 |
| Docstrings point back at the playbook | 2, 3 |

**Deliberately out of scope:** the `SessionStart` launcher/hook — the only mechanical
guarantee, and its own increment (which shell, which agents, per-repo opt-in). Also
`update_guidance`, `trackden delete`, hybrid search, and folder-derived `folder_id` — all
carried forward as open notes.

**Placeholder scan:** one deliberate artefact — Task 1's tool-existence test contains a dead
`if False else set()` expression with an explicit instruction to delete it, shown only to make
the intent legible. Task 4's test must be adapted to the existing onboarding fixtures, which
the step says to read rather than assume; that is a genuine unknown, not a placeholder.

**Type consistency:** `VERSION` is an `int` everywhere — in `playbook.py`, in
`get_playbook`'s `{"version": …}`, and in `overview`'s `{"playbook": {"version": …}}`.
`DIGEST` and `TEXT` are both `str`. `get_playbook` returns `text`; `overview` carries
`digest`. Those are deliberately different keys for deliberately different payloads — the
full document versus the reminder.
