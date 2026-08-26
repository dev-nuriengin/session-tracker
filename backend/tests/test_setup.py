"""`trackden setup` — the one command that makes a fresh machine ready.

No Docker and no agent CLI are needed here: every external process goes through an
injected `run` callable, and every config file is written under a tmp `home`. What is
NOT faked is the merge logic — a config file that already holds someone else's MCP
servers is the case that must never regress, so those tests use real files on disk.
"""

import json
from types import SimpleNamespace

import pytest

from app import setup as setup_mod


# ---- a fake process runner ----

def runner(responses):
    """Build a `run` stand-in. `responses` maps a command's first two words to
    (returncode, stdout). Anything unlisted comes back as "command not found"."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        key = " ".join(cmd[:2])
        code, out = responses.get(key, (127, ""))
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    run.calls = calls
    return run


# ---- docker ----

def test_docker_missing_is_reported_not_raised():
    result = setup_mod.check_docker(run=runner({}))
    assert result["status"] == "missing"
    assert "docker" in result["message"].lower()


def test_docker_installed_but_daemon_down():
    run = runner({"docker version": (1, "")})
    result = setup_mod.check_docker(run=run)
    assert result["status"] == "not_running"


def test_docker_ready():
    run = runner({"docker version": (0, "27.0.0")})
    assert setup_mod.check_docker(run=run)["status"] == "ok"


# ---- the database container ----

def test_an_existing_running_container_is_left_alone():
    run = runner({
        "docker version": (0, "27.0.0"),
        "docker inspect": (0, "true"),
    })
    result = setup_mod.ensure_database(run=run)
    assert result["status"] == "already_running"
    assert not any("run" == c[1] for c in run.calls), "must not create a second container"


def test_a_stopped_container_is_started_not_recreated():
    """Re-creating would orphan the volume holding the user's data."""
    run = runner({
        "docker version": (0, "27.0.0"),
        "docker inspect": (0, "false"),
        "docker start": (0, ""),
    })
    result = setup_mod.ensure_database(run=run)
    assert result["status"] == "started"
    assert any(c[:2] == ["docker", "start"] for c in run.calls)
    assert not any(c[:2] == ["docker", "run"] for c in run.calls)


def test_a_missing_container_is_created_with_the_compose_identity():
    """The container name must match docker-compose.yml's `container_name`, or a user
    who later runs compose gets a second, conflicting database."""
    run = runner({
        "docker version": (0, "27.0.0"),
        "docker run": (0, "abc123"),
    })
    result = setup_mod.ensure_database(run=run)
    assert result["status"] == "created"
    created = next(c for c in run.calls if c[:2] == ["docker", "run"])
    assert setup_mod.DB_CONTAINER in created
    assert f"{setup_mod.DB_PORT}:5432" in created
    assert setup_mod.DB_IMAGE in created


def test_database_reports_docker_missing_without_trying_to_run_anything():
    run = runner({})
    result = setup_mod.ensure_database(run=run)
    assert result["status"] == "docker_missing"
    assert not any(c[:2] == ["docker", "run"] for c in run.calls)


# ---- the MCP command ----

def test_the_mcp_command_is_absolute():
    """Setup writes this into config files that are read from any directory, so a
    relative path — like the repo's own .mcp.json uses — would simply not resolve."""
    command = setup_mod.mcp_command()
    assert command[0] == "uv"
    directory = command[command.index("--directory") + 1]
    assert directory.startswith("/"), f"not absolute: {directory}"
    assert directory.endswith("backend")


# ---- agent detection ----

def test_only_present_agents_are_detected(tmp_path):
    (tmp_path / ".codex").mkdir()
    found = {t["key"] for t in setup_mod.detect_agents(home=tmp_path, run=runner({}))}
    assert "codex" in found
    assert "cursor" not in found


def test_claude_is_detected_through_its_cli(tmp_path):
    run = runner({"claude --version": (0, "1.0.0")})
    found = {t["key"] for t in setup_mod.detect_agents(home=tmp_path, run=run)}
    assert "claude" in found


# ---- writing config: the part that must never eat someone's data ----

def test_registering_preserves_other_mcp_servers(tmp_path):
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"mcpServers": {"sentry": {"command": "npx", "args": ["sentry"]}}}),
        encoding="utf-8",
    )

    result = setup_mod.register_json_config(config, setup_mod.mcp_command())

    assert result["status"] == "registered"
    written = json.loads(config.read_text(encoding="utf-8"))
    assert "sentry" in written["mcpServers"], "clobbered an unrelated server"
    assert written["mcpServers"]["sentry"]["command"] == "npx"
    assert "trackden" in written["mcpServers"]


def test_registering_backs_up_the_original(tmp_path):
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    original = json.dumps({"mcpServers": {"sentry": {"command": "npx"}}})
    config.write_text(original, encoding="utf-8")

    result = setup_mod.register_json_config(config, setup_mod.mcp_command())

    backup = result["backup"]
    assert backup is not None
    assert json.loads(open(backup, encoding="utf-8").read()) == json.loads(original)


def test_re_registering_updates_rather_than_duplicating(tmp_path):
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    setup_mod.register_json_config(config, ["uv", "--directory", "/old", "run", "x"])
    setup_mod.register_json_config(config, setup_mod.mcp_command())

    servers = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["trackden"], "re-running must not accumulate entries"
    assert "/old" not in json.dumps(servers["trackden"])


def test_a_malformed_config_is_refused_not_overwritten(tmp_path):
    """The whole reason writing someone else's config is defensible: when we cannot
    parse it, we do not get to guess. Their bytes survive untouched."""
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text("{ this is not json", encoding="utf-8")
    before = config.read_bytes()

    result = setup_mod.register_json_config(config, setup_mod.mcp_command())

    assert result["status"] == "unparseable"
    assert config.read_bytes() == before


def test_a_missing_config_file_is_created(tmp_path):
    config = tmp_path / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)

    result = setup_mod.register_json_config(config, setup_mod.mcp_command())

    assert result["status"] == "registered"
    assert "trackden" in json.loads(config.read_text(encoding="utf-8"))["mcpServers"]


def test_toml_registration_preserves_other_servers(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'model = "o3"\n\n[mcp_servers.sentry]\ncommand = "npx"\nargs = ["sentry"]\n',
        encoding="utf-8",
    )

    result = setup_mod.register_toml_config(config, setup_mod.mcp_command())

    assert result["status"] == "registered"
    text = config.read_text(encoding="utf-8")
    assert "[mcp_servers.sentry]" in text, "clobbered an unrelated server"
    assert 'model = "o3"' in text, "clobbered unrelated settings"
    assert "[mcp_servers.trackden]" in text


def test_toml_re_registration_does_not_duplicate(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("", encoding="utf-8")

    setup_mod.register_toml_config(config, setup_mod.mcp_command())
    setup_mod.register_toml_config(config, setup_mod.mcp_command())

    assert config.read_text(encoding="utf-8").count("[mcp_servers.trackden]") == 1


# ---- the copy-paste block, for every agent we do not automate ----

def test_the_snippet_is_valid_json_and_carries_the_absolute_path():
    snippet = setup_mod.render_snippet()
    parsed = json.loads(snippet)
    args = parsed["mcpServers"]["trackden"]["args"]
    assert "--directory" in args
    assert args[args.index("--directory") + 1].startswith("/")


# ---- the orchestrator ----

def test_check_only_never_writes(tmp_path):
    (tmp_path / ".cursor").mkdir()
    config = tmp_path / ".cursor" / "mcp.json"
    run = runner({"docker version": (0, "27.0.0"), "docker inspect": (0, "true")})

    result = setup_mod.setup(check_only=True, home=tmp_path, run=run)

    assert result["check_only"] is True
    assert not config.exists(), "--check must not create a config file"
    assert not any(c[:2] == ["docker", "run"] for c in run.calls)
    assert not any(c[:2] == ["docker", "start"] for c in run.calls)


def test_setup_reports_every_step_even_when_docker_is_missing(tmp_path):
    result = setup_mod.setup(check_only=True, home=tmp_path, run=runner({}))

    assert [step["name"] for step in result["steps"]] == ["docker", "database", "schema", "mcp"]
    assert result["steps"][0]["status"] == "missing"
    assert result["ok"] is False


def test_setup_never_raises_when_everything_is_absent(tmp_path):
    """Same contract as sync/guidance: a first run on a bare machine reports, it does
    not traceback."""
    result = setup_mod.setup(check_only=True, home=tmp_path, run=runner({}))
    assert isinstance(result, dict)
    assert "steps" in result
