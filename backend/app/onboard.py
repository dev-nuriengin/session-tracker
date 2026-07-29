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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import repository, workspace
from .tracker_md import ParsedItem, ParsedTracker, parse_tracker_md, render_tracker_md

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
GUIDANCE_FILES: frozenset[str] = frozenset({"CLAUDE.md", "AGENTS.md"})

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


# The review gate. Given one scanned file, return the items to import — all of them,
# a subset, or None to skip it. The CLI supplies the interactive version; passing None
# means "no gate, take everything", which is what `--yes` and scripted runs use.
Confirm = Callable[[ScanHit], list[ParsedItem] | None]


@dataclass
class OnboardResult:
    """What onboarding actually did — printed as the closing summary."""

    slug: str
    name: str
    created: bool
    imported: int
    sources: list[str]
    files: list[Path]
    git_ready: bool


def run_onboard(
    *,
    slug: str,
    name: str | None = None,
    kind: str = "personal",
    client: str | None = None,
    repo: Path | str | None = None,
    import_items: bool = True,
    confirm: Confirm | None = None,
    home: Path | None = None,
) -> OnboardResult:
    """Identify → DB → scan → gate → scaffold → summarise.

    Writes only to the DB and the central workspace. The repo is read, never written.
    Re-running is safe: an existing project keeps its guidance files, has its
    `repo_path` refreshed and its `_tracker.md` mirror regenerated, and imports
    nothing — items are only ever imported when the project is first created.
    """
    slug = slugify(slug)
    if not slug:
        # Same wording `project_dir` would raise later — checked here, before any
        # write, so a name that folds to nothing (e.g. "---", or a CJK-only name
        # under NFKD + ascii-fold) never commits a DB row it can't then address.
        raise ValueError("Slug cannot be empty")
    display = name or slug
    repo_path = str(Path(repo).expanduser().resolve()) if repo else None

    # `created` must be known before the scan/gate loop below: only a first onboard
    # imports anything, so only a first onboard may prompt for it.
    created = repository.create_project(
        slug, name=display, kind=kind, client=client, repo_path=repo_path
    )
    if not created and repo_path:
        repository.set_repo_path(slug, repo_path)

    hits = scan_repo(repo) if (repo_path and import_items) else []

    chosen: list[ParsedItem] = []
    sources: list[str] = []
    way_of_work: str | None = None
    for hit in hits:
        # Seeding way-of-work costs nothing and the scan is read-only either way, so
        # this still runs on a re-run — an empty placeholder (e.g. a CLAUDE.md the
        # user hasn't filled in) doesn't count as "seeded" and must not block a later,
        # populated guidance file from doing so.
        if hit.is_guidance and not way_of_work:
            way_of_work = hit.text
        # A re-run must not re-prompt: `chosen`/`sources` — and the gate itself —
        # only run when this onboard is the one that created the project.
        if not created or not hit.parsed.items:
            continue
        selected = list(hit.parsed.items) if confirm is None else confirm(hit)
        if selected:
            chosen.extend(selected)
            sources.append(hit.relpath)

    # Items are imported ONLY on first onboard. `import_items` dedupes folder names
    # within a single call but not against rows already in the DB, so re-importing
    # would duplicate both items and folders. After onboarding the DB owns item
    # state — new items arrive via the CLI or an MCP tool, not by re-scanning.
    imported = 0
    if chosen and created:
        imported = repository.import_items(slug, [
            {"title": item.title, "status": item.status, "folder": item.folder}
            for item in chosen
        ])

    mirror = render_tracker_md(display, repository.items_with_folders(slug))
    files = workspace.scaffold_project(
        slug, name=display, way_of_work=way_of_work, tracker_md=mirror, home=home
    )
    git_ready = workspace.ensure_home_git(home)

    return OnboardResult(
        slug=slug,
        name=display,
        created=created,
        imported=imported,
        sources=sources,
        files=files,
        git_ready=git_ready,
    )
