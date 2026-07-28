"""The central Trackden workspace — `~/.trackden`.

The user's repos stay untouched: guidance lives here and reaches agents over MCP.
One folder per project, and the home itself is a git repo, so a single `git push`
backs up every project's guidance. `TRACKDEN_HOME` overrides the location — that is
what lets tests (and multiple profiles) run without touching the real home.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HOME_ENV = "TRACKDEN_HOME"
TRACKER_FILE = "_tracker.md"

_WAY_OF_WORK_TEMPLATE = """# Way of work — {name}

> How this project is worked on. Human-written; agents read it over MCP.
> Vendor-neutral on purpose — no agent-specific file is the source of truth.

## Conventions

- (naming, branching, review expectations…)

## Definition of done

- (tests, docs, deploy…)
"""

_ARCH_TEMPLATE = """# Architecture — {name}

> The shape of the system: the pieces, and how they talk. Keep it current.

## Components

- (service / module → responsibility)

## Data

- (stores, schemas, ownership)
"""

_DECISIONS_TEMPLATE = """# Decisions — {name}

> One entry per decision: what was chosen, and **why**. Append; never rewrite history.

## (date) — (the decision)

- **Chose:**
- **Because:**
- **Rejected:**
"""


def trackden_home() -> Path:
    """The workspace root — `$TRACKDEN_HOME`, else `~/.trackden`."""
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else Path.home() / ".trackden"


def project_dir(slug: str, home: Path | None = None) -> Path:
    return (home or trackden_home()) / "projects" / slug


def scaffold_project(
    slug: str,
    *,
    name: str | None = None,
    way_of_work: str | None = None,
    tracker_md: str = "",
    home: Path | None = None,
) -> list[Path]:
    """Create (or top up) a project's guidance folder. Returns the paths written.

    Guidance files are human-owned: an existing one is left exactly as it is, so
    re-onboarding can never destroy written knowledge. `_tracker.md` IS rewritten —
    it is generated from the DB and holds nothing a human authored.
    """
    directory = project_dir(slug, home)
    directory.mkdir(parents=True, exist_ok=True)
    display = name or slug

    guidance = {
        "_way-of-work.md": way_of_work or _WAY_OF_WORK_TEMPLATE.format(name=display),
        "_arch.md": _ARCH_TEMPLATE.format(name=display),
        "_decisions.md": _DECISIONS_TEMPLATE.format(name=display),
    }

    written: list[Path] = []
    for filename, content in guidance.items():
        path = directory / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            written.append(path)

    mirror = directory / TRACKER_FILE
    mirror.write_text(tracker_md, encoding="utf-8")
    written.append(mirror)
    return written


def ensure_home_git(home: Path | None = None) -> bool:
    """Make the workspace a git repo so one push backs up all guidance.

    Returns False when git is unavailable — onboarding must still succeed without it.
    """
    root = home or trackden_home()
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".git").exists():
        return True
    try:
        subprocess.run(
            ["git", "init", "--quiet", str(root)], check=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True
