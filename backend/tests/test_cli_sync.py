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

    result = runner.invoke(
        cli_mod.app, ["add-status", "korpus", "parked", "--behaves-as", "waiting"]
    )

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
