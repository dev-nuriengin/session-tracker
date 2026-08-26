"""One command that makes a fresh machine ready: `trackden setup`.

Everything Trackden needs is local — a Postgres container, a schema, and an MCP entry
in whichever agent the user runs. Before this module those were four manual steps in a
README, and the fourth one silently did not work outside this repo: the shipped
`.mcp.json` points at a *relative* `backend/` directory, so an agent started anywhere
else found no server at all.

Two shapes borrowed from the rest of the app: every function returns an outcome dict
and never raises (as `sync.py` and `guidance.py` do), and every external process goes
through an injected `run`, so the tests need neither Docker nor an agent installed.

Why `docker run` and not `docker compose up -d db`: once `trackden` is installed as a
tool it is invoked from any directory, and there is no compose file outside this repo.
The container is created with the same name `docker-compose.yml` gives it, so the two
paths cannot produce two competing databases.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# Must match docker-compose.yml. A different name here would let `docker compose up`
# and `trackden setup` each create their own database, and the user would silently
# have two — with their work in whichever one they started first.
DB_CONTAINER = "session_tracker_db"
DB_IMAGE = "pgvector/pgvector:pg16"
DB_PORT = 5433
DB_VOLUME = "trackden_db_data"
DB_USER = "session"
DB_PASSWORD = "session"
DB_NAME = "session_tracker"

SERVER_NAME = "trackden"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a process, capturing output. Never raises for a non-zero exit — the caller
    reads `returncode`, because "docker is not installed" is an outcome here, not an
    error."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)
    except (OSError, ValueError) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


# ---- step 1: docker ----

def check_docker(run=_run) -> dict:
    """Is Docker installed, and is its daemon up? Two different problems, two fixes.

    Both answers come from one call, distinguished by exit code: `_run` reports a
    missing executable as 127, the shell's own "command not found". Deliberately not
    `shutil.which` — that reads the real machine and cannot be injected, so a test for
    "docker is absent" would pass or fail depending on the developer's laptop.
    """
    probe = run(["docker", "version"])
    if probe.returncode == 127:
        return {
            "status": "missing",
            "message": "docker is not installed — see https://docs.docker.com/get-docker/",
        }
    if probe.returncode != 0:
        return {
            "status": "not_running",
            "message": "docker is installed but its daemon is not running — start Docker Desktop",
        }
    return {"status": "ok", "message": ""}


# ---- step 2: the database container ----

def ensure_database(run=_run) -> dict:
    """Make sure the Postgres container exists and is running.

    A stopped container is *started*, never re-created: re-creating would leave the
    volume holding the user's projects orphaned behind a fresh, empty database.
    """
    docker = check_docker(run=run)
    if docker["status"] != "ok":
        return {"status": "docker_missing", "message": docker["message"]}

    inspect = run(["docker", "inspect", "-f", "{{.State.Running}}", DB_CONTAINER])
    if inspect.returncode == 0:
        if inspect.stdout.strip() == "true":
            return {"status": "already_running", "message": ""}
        started = run(["docker", "start", DB_CONTAINER])
        if started.returncode != 0:
            return {"status": "start_failed", "message": started.stderr.strip()}
        return {"status": "started", "message": ""}

    created = run([
        "docker", "run", "-d",
        "--name", DB_CONTAINER,
        "-e", f"POSTGRES_USER={DB_USER}",
        "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
        "-e", f"POSTGRES_DB={DB_NAME}",
        "-p", f"{DB_PORT}:5432",
        "-v", f"{DB_VOLUME}:/var/lib/postgresql/data",
        DB_IMAGE,
    ])
    if created.returncode != 0:
        return {"status": "create_failed", "message": created.stderr.strip()}
    return {"status": "created", "message": ""}


def wait_for_database(attempts: int = 30, run=_run, sleep=None) -> dict:
    """Poll until Postgres accepts connections. `pg_isready` inside the container, so
    no Python driver is involved and a half-started server cannot look ready."""
    import time

    sleep = sleep or time.sleep
    for attempt in range(attempts):
        probe = run(["docker", "exec", DB_CONTAINER, "pg_isready", "-U", DB_USER, "-d", DB_NAME])
        if probe.returncode == 0:
            return {"status": "ready", "attempts": attempt + 1, "message": ""}
        sleep(1)
    return {
        "status": "timeout",
        "attempts": attempts,
        "message": f"database did not accept connections within {attempts}s",
    }


# ---- step 3: the schema ----

def ensure_schema() -> dict:
    """Create any missing tables and columns. Idempotent, and never touches data."""
    try:
        from .db import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001 — a first run on a bare machine reports, not tracebacks
        return {"status": "failed", "message": f"{exc.__class__.__name__}: {exc}"}
    return {"status": "ready", "message": ""}


# ---- step 4: the MCP entry ----

def _package_root() -> Path:
    """The `backend/` directory this module was installed from."""
    return Path(__file__).resolve().parent.parent


def mcp_command() -> list[str]:
    """The stdio command an agent runs to reach Trackden.

    Absolute, deliberately. The repo's own `.mcp.json` uses a relative `backend`, which
    resolves only when the agent was started in this repo — the reason Trackden was
    invisible from every other project.
    """
    return [
        "uv", "--directory", str(_package_root()), "run", "python", "-m", "app.mcp_server",
    ]


def render_snippet(command: list[str] | None = None) -> str:
    """The copy-paste block, for any agent this module does not write to itself."""
    command = command or mcp_command()
    return json.dumps(
        {"mcpServers": {SERVER_NAME: {"command": command[0], "args": command[1:]}}},
        indent=2,
    )


# Known agents. `detect` says whether the tool is on this machine; `register` names how
# its config is written. Data-driven so supporting one more is one entry, not a branch.
AGENTS = [
    {
        "key": "claude",
        "label": "Claude Code",
        "kind": "cli",
        "config": None,
        "doc": "https://docs.claude.com/en/docs/claude-code/mcp",
    },
    {
        "key": "codex",
        "label": "Codex",
        "kind": "toml",
        "config": ".codex/config.toml",
        "doc": "https://developers.openai.com/codex/mcp",
    },
    {
        "key": "cursor",
        "label": "Cursor",
        "kind": "json",
        "config": ".cursor/mcp.json",
        "doc": "https://docs.cursor.com/context/model-context-protocol",
    },
]


def detect_agents(home: Path | None = None, run=_run) -> list[dict]:
    """Which known agents are on this machine. Absence is normal, not an error."""
    home = home or Path.home()
    found = []
    for agent in AGENTS:
        if agent["kind"] == "cli":
            # Through the runner, not `shutil.which`, for the same reason as
            # `check_docker`: presence must be injectable or the tests test the laptop.
            if run([agent["key"], "--version"]).returncode == 0:
                found.append(agent)
        elif (home / agent["config"]).parent.exists():
            found.append(agent)
    return found


def _backup(path: Path) -> str | None:
    """Copy a config aside before touching it. Returns the backup path, or None when
    there was nothing to back up."""
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + ".trackden-bak")
    shutil.copy2(path, backup)
    return str(backup)


def register_json_config(path: Path, command: list[str]) -> dict:
    """Merge Trackden into a JSON MCP config, keeping every other server.

    A file we cannot parse is refused, not rewritten. That refusal is the whole reason
    writing into someone else's config is defensible at all: when we do not understand
    the bytes, we do not get to guess at them.
    """
    path = Path(path)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {
                "status": "unparseable",
                "path": str(path),
                "backup": None,
                "message": f"{path} is not valid JSON — left untouched; add the entry by hand",
            }
        if not isinstance(data, dict):
            return {
                "status": "unparseable",
                "path": str(path),
                "backup": None,
                "message": f"{path} is not a JSON object — left untouched",
            }

    backup = _backup(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return {
            "status": "unparseable",
            "path": str(path),
            "backup": backup,
            "message": f"{path}'s mcpServers is not an object — left untouched",
        }

    # Assignment, not append: re-running setup after moving the install must update the
    # entry in place rather than leave a stale second one pointing at the old path.
    servers[SERVER_NAME] = {"command": command[0], "args": command[1:]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"status": "write_failed", "path": str(path), "backup": backup, "message": str(exc)}
    return {"status": "registered", "path": str(path), "backup": backup, "message": ""}


_TOML_HEADER = f"[mcp_servers.{SERVER_NAME}]"


def register_toml_config(path: Path, command: list[str]) -> dict:
    """Append (or replace) Trackden's table in a TOML MCP config.

    Written as text rather than parsed-and-re-emitted on purpose: Python ships a TOML
    reader but no writer, and re-emitting through a third-party writer would reformat
    the user's whole file — dropping their comments — to add four lines.
    """
    path = Path(path)
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {
                "status": "unparseable",
                "path": str(path),
                "backup": None,
                "message": f"{path} could not be read ({exc}) — left untouched",
            }

    backup = _backup(path)
    args = ", ".join(json.dumps(a) for a in command[1:])
    block = f'{_TOML_HEADER}\ncommand = {json.dumps(command[0])}\nargs = [{args}]\n'

    if _TOML_HEADER in existing:
        # Replace our own table only, from its header to the next table or EOF, so
        # neighbouring tables and top-level settings survive untouched.
        lines = existing.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.strip() == _TOML_HEADER)
        end = start + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        updated = "".join(lines[:start]) + block + "".join(lines[end:])
    else:
        separator = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        updated = existing + separator + block

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return {"status": "write_failed", "path": str(path), "backup": backup, "message": str(exc)}
    return {"status": "registered", "path": str(path), "backup": backup, "message": ""}


def register_agent(agent: dict, home: Path | None = None, run=_run) -> dict:
    """Register Trackden with one detected agent, by whatever means that agent offers."""
    home = home or Path.home()
    command = mcp_command()

    if agent["kind"] == "cli":
        # Its own CLI owns its own config format — the one path with no risk of us
        # corrupting a file we only partly understand.
        result = run([agent["key"], "mcp", "add", "--scope", "user", SERVER_NAME, "--", *command])
        if result.returncode != 0:
            return {
                "status": "cli_failed",
                "path": None,
                "backup": None,
                "message": (result.stderr or result.stdout or "").strip(),
            }
        return {"status": "registered", "path": f"{agent['label']} (user scope)", "backup": None, "message": ""}

    path = home / agent["config"]
    if agent["kind"] == "json":
        return register_json_config(path, command)
    return register_toml_config(path, command)


# ---- the orchestrator ----

def setup(
    check_only: bool = False,
    home: Path | None = None,
    run=_run,
    sleep=None,
    agents: list[dict] | None = None,
) -> dict:
    """Bring this machine to a working Trackden. Reports every step; never raises.

    `check_only` diagnoses and changes nothing — no container started, no config
    written — so a user can see what setup would do before letting it do anything.

    `agents` is the list to register with; omit it to detect them. The CLI passes an
    explicit list because it shows the user each file it intends to write and asks
    first — the confirmation belongs at the door, not in here.
    """
    steps: list[dict] = []

    docker = check_docker(run=run)
    steps.append({"name": "docker", **docker})

    if check_only:
        steps.append({"name": "database", "status": "skipped",
                      "message": "not checked — re-run without --check to start it"})
        steps.append({"name": "schema", "status": "skipped",
                      "message": "not checked — re-run without --check to create it"})
        steps.append({"name": "mcp", "status": "skipped", "agents": [],
                      "message": "not checked — re-run without --check to register it"})
        return {
            "check_only": True,
            "ok": docker["status"] == "ok",
            "steps": steps,
            "snippet": render_snippet(),
        }

    database = ensure_database(run=run)
    if database["status"] in ("created", "started"):
        waited = wait_for_database(run=run, sleep=sleep)
        if waited["status"] != "ready":
            database = {"status": "timeout", "message": waited["message"]}
    steps.append({"name": "database", **database})

    if database["status"] in ("already_running", "created", "started"):
        schema = ensure_schema()
    else:
        schema = {"status": "skipped", "message": "no database to create a schema in"}
    steps.append({"name": "schema", **schema})

    targets = detect_agents(home=home, run=run) if agents is None else agents
    registered = [
        {"agent": agent["label"], **register_agent(agent, home=home, run=run)}
        for agent in targets
    ]
    steps.append({
        "name": "mcp",
        "status": "registered" if registered else "no_agents",
        "agents": registered,
        "message": "" if registered else "no known agent found — use the snippet below",
    })

    ok = (
        database["status"] in ("already_running", "created", "started")
        and schema["status"] == "ready"
    )
    return {"check_only": False, "ok": ok, "steps": steps, "snippet": render_snippet()}
