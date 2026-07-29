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
