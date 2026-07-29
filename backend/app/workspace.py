"""The central Trackden workspace — `~/.trackden`.

The user's repos stay untouched: guidance lives here and reaches agents over MCP.
One folder per project, and the home itself is a git repo, so a single `git push`
backs up every project's guidance. `TRACKDEN_HOME` overrides the location — that is
what lets tests (and multiple profiles) run without touching the real home.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

HOME_ENV = "TRACKDEN_HOME"
TRACKER_FILE = "_tracker.md"

# The public document names agents and the CLI use, mapped to the vendor-neutral
# filenames on disk. One mapping, used by both the write path (scaffolding) and the
# read path — so the two can never disagree about what a document is called.
GUIDANCE_DOCS = {
    "way-of-work": "_way-of-work.md",
    "arch": "_arch.md",
    "decisions": "_decisions.md",
}

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
    """The workspace root — `$TRACKDEN_HOME`, else `~/.trackden`.

    An override is expanded (`~`) and resolved (relative → absolute) so a relative
    `TRACKDEN_HOME` can never land inside the current directory — i.e. inside
    whatever repo the caller happens to be standing in. An empty override falls
    back to the default, same as before.
    """
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser().resolve() if override else Path.home() / ".trackden"


_SAFE_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")


def project_dir(slug: str, home: Path | None = None) -> Path:
    """Resolve a project's guidance folder. Validates the slug to prevent path escapes.

    This module owns the "never write outside the workspace" promise. A caller
    bypassing the CLI (e.g., an agent-driven onboarding path) must not be able to
    break it. Path-traversal attempts are caught here rather than silently sanitised.

    A whitelist, not a blacklist: `slug` must fully match lowercase alphanumerics
    and hyphens (after a lowercase-alphanumeric first character). That one rule
    covers empty, absolute, separator-containing, `..`-containing, bare-`.`, and
    Windows-drive-relative (`D:evil`) slugs alike — `slugify` only ever emits
    lowercase alphanumerics and hyphens, so the happy path is unaffected.
    """
    if not re.fullmatch(_SAFE_SLUG, slug):
        raise ValueError(f"unsafe project slug: {slug!r}")

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
        GUIDANCE_DOCS["way-of-work"]: way_of_work
        or _WAY_OF_WORK_TEMPLATE.format(name=display),
        GUIDANCE_DOCS["arch"]: _ARCH_TEMPLATE.format(name=display),
        GUIDANCE_DOCS["decisions"]: _DECISIONS_TEMPLATE.format(name=display),
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
