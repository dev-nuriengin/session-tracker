"""`trackden onboard` — how a project gets INTO Trackden.

Two halves, kept apart on purpose:

* `scan_repo` READS a repo and proposes what could be imported. It never writes.
* `run_onboard` (next task) decides and writes — DB items + the central guidance folder.

Between them sits a review gate supplied by the caller, which is what keeps
auto-detection safe: a proposal a human confirmed, not a parse trusted blindly.
The user's repo is never modified.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .tracker_md import ParsedTracker, parse_tracker_md

# Priority order: the most explicit tracker locations first, guidance last.
DEFAULT_SCAN_GLOBS: tuple[str, ...] = (
    "_tracker.md",
    "main-plans/_tracker.md",
    "_tickets-and-status/_tracker.md",
    "**/_tracker.md",
    "CLAUDE.md",
    "AGENTS.md",
)

# Per-vendor files: read as INPUT to seed vendor-neutral guidance, never a source of truth.
GUIDANCE_FILES = frozenset({"CLAUDE.md", "AGENTS.md"})

_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass
class ScanHit:
    """One importable file found in a repo, already parsed."""

    path: Path
    relpath: str
    parsed: ParsedTracker
    is_guidance: bool
    text: str


def slugify(text: str) -> str:
    """A filesystem- and URL-safe project slug. Accents are folded, not dropped."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _SLUG_STRIP.sub("-", folded.lower()).strip("-")


def scan_repo(
    repo: Path | str, globs: tuple[str, ...] = DEFAULT_SCAN_GLOBS
) -> list[ScanHit]:
    """Find checklist/guidance files worth importing. Read-only, best-effort.

    Returns hits in scan-list priority order, de-duplicated by real path. A file is
    a hit if it yielded items, or if it is a guidance file (which can seed the
    project's way-of-work even when it holds no checkboxes).
    """
    root = Path(repo).expanduser()
    if not root.is_dir():
        return []
    root = root.resolve()

    hits: list[ScanHit] = []
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if _SKIP_DIRS & set(relative.parts[:-1]):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # unreadable input is not a reason to fail onboarding
            parsed = parse_tracker_md(text)
            is_guidance = path.name in GUIDANCE_FILES
            if parsed.items or is_guidance:
                hits.append(ScanHit(
                    path=path,
                    relpath=relative.as_posix(),
                    parsed=parsed,
                    is_guidance=is_guidance,
                    text=text,
                ))
    return hits
