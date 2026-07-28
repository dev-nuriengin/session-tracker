"""The `_tracker.md` format — parsed one way, rendered the other.

Both directions live here on purpose: it is a single file format, and a reader kept
apart from its writer is a format that drifts. Pure functions — no DB, no filesystem —
which is what makes onboarding's import path cheap to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TODO = "todo"
DONE = "done"

_HEADING = re.compile(r"^\s{0,3}#{2,3}\s+(.*?)\s*$")
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s+(.*?)\s*$")
# hand-written headings trail pointers/markers: "Phase 4 — Core data model ← THE STORE ✅"
_HEADING_NOISE = re.compile(r"\s*(←.*|✅|🔴|⚠️)\s*$")


@dataclass
class ParsedItem:
    """One work item recovered from a markdown checklist."""

    title: str
    status: str
    folder: str | None = None


@dataclass
class ParsedTracker:
    items: list[ParsedItem] = field(default_factory=list)

    @property
    def folders(self) -> list[str]:
        """Folder names in first-seen order, de-duplicated."""
        seen: dict[str, None] = {}
        for item in self.items:
            if item.folder:
                seen.setdefault(item.folder, None)
        return list(seen)


def _clean_heading(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _HEADING_NOISE.sub("", text)
    return text.strip()


def parse_tracker_md(text: str) -> ParsedTracker:
    """Recover items from a hand-written checklist/guidance markdown file.

    `##`/`###` headings become folder names; `- [ ]` / `- [x]` lines become items.
    Blockquotes are skipped so a file's own "Rules: `[x]` done" preamble is not
    imported as work. Only `todo`/`done` are inferred — richer statuses are the
    user's to set, never guessed.
    """
    parsed = ParsedTracker()
    folder: str | None = None
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            continue
        heading = _HEADING.match(line)
        if heading:
            folder = _clean_heading(heading.group(1)) or None
            continue
        box = _CHECKBOX.match(line)
        if box:
            status = DONE if box.group(1).lower() == "x" else TODO
            parsed.items.append(ParsedItem(title=box.group(2), status=status, folder=folder))
    return parsed
