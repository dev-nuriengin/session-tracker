"""The `trackden setup` door.

No Postgres, no Docker, no agent CLI: `setup_mod.setup` and `detect_agents` are faked,
so these tests pin the door's behaviour — the confirmation gate, the exit codes, and
the one thing that is easy to get wrong and impossible to notice: that `setup` does not
inherit the app-level `init_db()` callback.
"""

from unittest.mock import Mock

from typer.testing import CliRunner

from app import cli as cli_mod

runner = CliRunner()


def _fake_setup(monkeypatch, result, calls=None):
    def fake(check_only=False, home=None, run=None, sleep=None, agents=None):
        if calls is not None:
            calls.append({"check_only": check_only, "agents": agents})
        return result

    monkeypatch.setattr(cli_mod.setup_mod, "setup", fake)


def _ok_result(**overrides):
    result = {
        "check_only": False,
        "ok": True,
        "snippet": '{"mcpServers": {"trackden": {}}}',
        "steps": [
            {"name": "docker", "status": "ok", "message": ""},
            {"name": "database", "status": "started", "message": ""},
            {"name": "schema", "status": "ready", "message": ""},
            {"name": "mcp", "status": "registered", "message": "",
             "agents": [{"agent": "Claude Code", "status": "registered", "message": ""}]},
        ],
    }
    result.update(overrides)
    return result


# ---- the callback exemption ----

def test_setup_does_not_run_init_db(monkeypatch):
    """`setup` is the command that CREATES the database. If the app-level callback ran
    first, a fresh machine would traceback out of the only command able to fix it."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.setup_mod, "detect_agents", lambda: [])
    _fake_setup(monkeypatch, _ok_result())

    result = runner.invoke(cli_mod.app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    spy.assert_not_called()


def test_other_commands_still_run_init_db(monkeypatch):
    """The exemption must be for `setup` alone, not a hole for everything."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: [])

    result = runner.invoke(cli_mod.app, ["list"])

    assert result.exit_code == 0, result.output
    spy.assert_called_once()


# ---- the confirmation gate ----

def test_declining_the_prompt_registers_nothing_and_prints_the_snippet(monkeypatch):
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    monkeypatch.setattr(
        cli_mod.setup_mod, "detect_agents",
        lambda: [{"key": "cursor", "label": "Cursor", "kind": "json",
                  "config": ".cursor/mcp.json", "doc": ""}],
    )
    calls = []
    _fake_setup(monkeypatch, _ok_result(steps=[
        {"name": "docker", "status": "ok", "message": ""},
        {"name": "database", "status": "started", "message": ""},
        {"name": "schema", "status": "ready", "message": ""},
        {"name": "mcp", "status": "no_agents", "message": "", "agents": []},
    ]), calls)

    result = runner.invoke(cli_mod.app, ["setup"], input="n\n")

    assert result.exit_code == 0, result.output
    assert calls[0]["agents"] == [], "declining must pass an empty target list"
    assert "mcpServers" in result.output, "a declined user still needs the block"


def test_the_prompt_names_every_file_it_will_touch(monkeypatch):
    """These are the user's own configs. Setup does not get to write one unannounced."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    monkeypatch.setattr(
        cli_mod.setup_mod, "detect_agents",
        lambda: [{"key": "codex", "label": "Codex", "kind": "toml",
                  "config": ".codex/config.toml", "doc": ""}],
    )
    _fake_setup(monkeypatch, _ok_result())

    result = runner.invoke(cli_mod.app, ["setup"], input="y\n")

    assert ".codex/config.toml" in result.output
    assert "backed up" in result.output


def test_yes_skips_the_prompt(monkeypatch):
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    detected = [{"key": "cursor", "label": "Cursor", "kind": "json",
                 "config": ".cursor/mcp.json", "doc": ""}]
    monkeypatch.setattr(cli_mod.setup_mod, "detect_agents", lambda: detected)
    calls = []
    _fake_setup(monkeypatch, _ok_result(), calls)

    result = runner.invoke(cli_mod.app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Register with them?" not in result.output
    assert calls[0]["agents"] == detected


# ---- --check ----

def test_check_never_detects_or_registers(monkeypatch):
    monkeypatch.setattr(cli_mod, "init_db", Mock())

    def explode():
        raise AssertionError("--check must not go looking for agents to write to")

    monkeypatch.setattr(cli_mod.setup_mod, "detect_agents", explode)
    calls = []
    _fake_setup(monkeypatch, _ok_result(check_only=True, ok=False, steps=[
        {"name": "docker", "status": "missing", "message": "docker is not installed"},
        {"name": "database", "status": "skipped", "message": "not checked"},
        {"name": "schema", "status": "skipped", "message": "not checked"},
        {"name": "mcp", "status": "skipped", "message": "not checked", "agents": []},
    ]), calls)

    result = runner.invoke(cli_mod.app, ["setup", "--check"])

    assert result.exit_code == 0, result.output
    assert calls[0]["check_only"] is True
    assert calls[0]["agents"] is None
    assert "docker is not installed" in result.output
    assert "Re-run without --check" in result.output


# ---- exit codes ----

def test_a_failed_setup_exits_non_zero(monkeypatch):
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    monkeypatch.setattr(cli_mod.setup_mod, "detect_agents", lambda: [])
    _fake_setup(monkeypatch, _ok_result(ok=False, steps=[
        {"name": "docker", "status": "not_running", "message": "daemon is not running"},
        {"name": "database", "status": "docker_missing", "message": "daemon is not running"},
        {"name": "schema", "status": "skipped", "message": "no database"},
        {"name": "mcp", "status": "no_agents", "message": "", "agents": []},
    ]))

    result = runner.invoke(cli_mod.app, ["setup", "--yes"])

    assert result.exit_code == 1, result.output
    assert "daemon is not running" in result.output


def test_a_failing_agent_is_reported_without_failing_setup(monkeypatch):
    """The database is the product; one agent's config refusing to be written is worth
    a line, not a failed install."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    monkeypatch.setattr(cli_mod.setup_mod, "detect_agents", lambda: [])
    _fake_setup(monkeypatch, _ok_result(steps=[
        {"name": "docker", "status": "ok", "message": ""},
        {"name": "database", "status": "already_running", "message": ""},
        {"name": "schema", "status": "ready", "message": ""},
        {"name": "mcp", "status": "registered", "message": "", "agents": [
            {"agent": "Cursor", "status": "registered", "message": ""},
            {"agent": "Codex", "status": "unparseable", "message": "not valid TOML — left untouched"},
        ]},
    ]))

    result = runner.invoke(cli_mod.app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Cursor" in result.output
    assert "left untouched" in result.output
    assert "Ready" in result.output
