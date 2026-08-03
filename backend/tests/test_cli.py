"""CLI-wide behavior — not specific to any one command.

No Postgres needed here: init_db and the repository call are both faked, so
these tests never touch a database, real or test.
"""

from unittest.mock import Mock

from typer.testing import CliRunner

from app import cli as cli_mod

runner = CliRunner()


def test_cli_ensures_the_schema_before_running_any_command(monkeypatch):
    """FIX 1: cli.py never called init_db() before — only repository.setup() did
    (from FastAPI startup / the MCP server's __main__), and cli.py calls neither.
    Against a database whose `projects` table predates a column like `repo_path`,
    the first query raised a raw UndefinedColumn traceback, for every command, not
    just `onboard`. Spy on init_db as imported into app.cli and confirm it runs."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: [])

    result = runner.invoke(cli_mod.app, ["list"])

    assert result.exit_code == 0, result.output
    spy.assert_called_once()


def test_cli_ensures_the_schema_before_a_different_command_too(monkeypatch):
    """The fix is a Typer app-level callback, not a per-command patch — confirm it
    fires for a second, unrelated command as well."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.repository, "get_status", lambda project: "")

    result = runner.invoke(cli_mod.app, ["status", "some-project"])

    assert result.exit_code == 0, result.output
    spy.assert_called_once()


def test_cli_help_does_not_require_the_schema_check(monkeypatch):
    """`--help` must stay safe to run against any database (or none) — Click
    handles --help eagerly and never invokes the app callback."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)

    result = runner.invoke(cli_mod.app, ["--help"])

    assert result.exit_code == 0, result.output
    spy.assert_not_called()


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
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: {"status": "added"})
    result = runner.invoke(
        cli_mod.app, ["add-status", "acme", "parked", "--behaves-as", "waiting"]
    )
    assert result.exit_code == 0, result.output
    assert "parked" in result.output


def test_add_status_exits_non_zero_on_a_duplicate(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: {"status": "duplicate_name"})
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
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "unknown_project"}
    )
    assert runner.invoke(cli_mod.app, ["add-folder", "nope", "Bugs"]).exit_code == 1


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


def test_add_item_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "unknown_project"}
    )
    assert runner.invoke(cli_mod.app, ["add-item", "nope", "Fix it"]).exit_code == 1


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


def test_log_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_session_log", lambda *a, **k: False)
    assert runner.invoke(cli_mod.app, ["log", "nope", "did a thing"]).exit_code == 1


def test_show_reports_the_waiting_count(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "overview",
        lambda slug: {
            "project": "acme", "next": "a", "open_items": 1, "open_preview": ["a"],
            "waiting_items": 2, "memory_entries": 0, "last_activity": None,
            "statuses": [{"name": "todo", "behaves_as": "open"}],
        },
    )
    result = runner.invoke(cli_mod.app, ["show", "acme"])
    assert result.exit_code == 0, result.output
    assert "waiting" in result.output and "2" in result.output
