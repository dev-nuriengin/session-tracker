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
