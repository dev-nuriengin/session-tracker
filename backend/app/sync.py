"""Keep the generated `_tracker.md` mirror true to the database.

`~/.trackden/projects/<slug>/_tracker.md` is derived output — a human-readable
snapshot of the DB's items, carrying a banner that says so. Until this module
existed, `render_tracker_md` had exactly one caller (`run_onboard`), so the file
was correct at onboard time and stale from the next write onward.

Why a status and never an exception: the auto-refresh call sites run AFTER a DB
write has committed. An exception escaping `sync` would abort a command whose real
work had already succeeded, and the user would see a traceback with no way to tell
whether their item was saved. Same contract as `guidance.py`, for the same reason.

`repository` stays filesystem-free — this module is the seam between the DB and the
workspace, which is what keeps a `chmod` from failing a `set_status`.
"""

from __future__ import annotations

from pathlib import Path

from . import repository, workspace
from .tracker_md import is_generated, render_tracker_md

_HAND_EDITED = "skipped: not a generated file, refusing to overwrite your edits"


def sync(slug: str) -> dict:
    """Rewrite one project's generated `_tracker.md` from the DB. Never raises.

    Outcomes — always `project`, `status`, `path`, `message`:

    - `synced` (+ `items`) — written. `items: 0` is a legitimate success.
    - `unknown_project` — no such project in the DB.
    - `not_scaffolded` — in the DB, but no `~/.trackden/projects/<slug>/`.
    - `hand_edited` (+ `path`) — a `_tracker.md` without the generated banner.
      Refused, never overwritten.
    - `write_failed` (+ `reason`) — the render succeeded; the filesystem refused.
    """
    result: dict = {"project": slug, "status": "", "path": None, "message": ""}

    # FIRST, and it must stay first. `items_with_folders` returns [] for an unknown
    # project and `closed_names` falls back to the shipped defaults for one —
    # neither can tell "no such project" from "a project with zero items", and both
    # are correct for their own callers. Rendering straight from them would write a
    # valid, empty mirror for `trackden sync typo-slug`. `get_project` is the only
    # read here that tells the truth about existence, and it carries `name`, so the
    # existence check and the display-name lookup are one call.
    project = repository.get_project(slug)
    if project is None:
        result["status"] = "unknown_project"
        result["message"] = f"unknown project {slug!r}"
        return result

    # The DB's own slug, not the caller's: `get_project` lowercases before it
    # queries, so `sync("ACME")` finds the project — but `workspace._SAFE_SLUG`
    # rejects uppercase outright. Same choice `guidance.py` makes with `row.slug`,
    # and the same defect `trackden delete ACME` had before it normalised.
    canonical = project.slug
    result["project"] = canonical
    mirror: Path | None = None

    try:
        directory = workspace.project_dir(canonical)
    except ValueError:
        # `project_dir` is the ONLY call below that can raise `ValueError`, and it
        # does no I/O — it just validates the slug and joins paths. Giving it its
        # own try means the `except ValueError` this raises can only ever mean one
        # thing, instead of also catching a `ValueError` from somewhere else in the
        # block below and mislabelling it with this message.
        #
        # The DB holds a slug `_SAFE_SLUG` rejects: `add-project` only lowercases
        # and strips, it never validates. The spec's outcome set has no
        # `invalid_slug`, so this is reported as `not_scaffolded` — but with an
        # honest message, because telling someone to `onboard` a slug that cannot
        # be a folder name would send them in a circle.
        result["status"] = "not_scaffolded"
        result["message"] = (
            f"project slug {canonical!r} cannot be a workspace folder — a usable "
            "slug is lowercase letters, digits, and hyphens only (e.g. 'my-project')"
        )
        return result

    try:
        # `.exists()` sits INSIDE the try: on an over-long path *component* it
        # raises OSError itself, which a length check alone would not catch.
        if not directory.exists():
            result["status"] = "not_scaffolded"
            result["message"] = (
                f"no guidance folder for {canonical!r} yet — run "
                f"`trackden onboard {canonical}` (safe to re-run) to scaffold it"
            )
            return result

        mirror = directory / workspace.TRACKER_FILE
        if mirror.exists() and not is_generated(mirror.read_text(encoding="utf-8")):
            result["status"] = "hand_edited"
            result["path"] = str(mirror)
            result["message"] = _HAND_EDITED
            return result

        items = repository.items_with_folders(canonical)
        text = render_tracker_md(
            project.name, items, closed=repository.closed_names(canonical)
        )
        written = workspace.write_mirror(canonical, text)
    except UnicodeDecodeError:
        # MUST precede any `except ValueError` in this block — UnicodeDecodeError is
        # a subclass of it, and Python takes the first matching clause. A mirror
        # that is not valid UTF-8 certainly did not come from us, so it gets a
        # hand-edited file's protection rather than being mislabelled
        # `not_scaffolded`. (There is no `except ValueError` left in this block to
        # race with — `project_dir`, above, is the only raiser, and it is already
        # handled — but this clause still has to come first on principle.)
        result["status"] = "hand_edited"
        result["path"] = str(mirror) if mirror is not None else None
        result["message"] = _HAND_EDITED
        return result
    except OSError as exc:
        result["status"] = "write_failed"
        result["reason"] = str(exc)
        # `message` repeats `reason` for this one outcome on purpose: the doors
        # print `message` inside their own framing ("mirror not refreshed: …"), so
        # a prefix here would read as "could not write the mirror: could not …".
        result["message"] = str(exc)
        return result

    result["status"] = "synced"
    result["items"] = len(items)
    result["path"] = str(written)
    return result
