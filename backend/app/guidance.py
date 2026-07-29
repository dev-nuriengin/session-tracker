"""The guidance layer's read path and its one write — decisions.

Guidance (way-of-work, architecture, decisions) lives in vendor-neutral files under
`~/.trackden/projects/<slug>/`, because it is durable knowledge a human writes and
edits. The DB owns state; these files own guidance. This module is the seam between
them: it asks the DB whether a project is real, asks the workspace for the file, and
translates both into a `status` a caller can act on.

Why a status and never an exception: an exception reaching an agent over MCP is an
opaque tool error it cannot reason about, whereas `not_scaffolded` tells it exactly
what to do next. The MCP and CLI doors are both thin wrappers over this module, so
neither can drift from the other's behaviour.

Return contract: `get` always returns six keys — `project`, `doc`, `path`, `status`,
`text`, `message`. `add_decision` always returns four — `project`, `path`, `status`,
`message`. `text` is the document's content and *only* that: `None` whenever there is
no document to show, including `unknown_doc`. `message` is a short, human-readable
explanation of the outcome — always a `str`, never `None`, and `""` when there is
nothing to explain (`filled`, `template`, `appended`). The two are kept apart because
both doors print `message` verbatim: overloading `text` to sometimes hold a document
and sometimes hold an explanation would make "the document said nothing"
indistinguishable from "there was no document" — and a caller that has to tell those
apart by inspecting content is a caller that will eventually get it wrong.
"""

from __future__ import annotations

from . import repository, workspace

DEFAULT_DOC = "way-of-work"


def get(project: str, doc: str = DEFAULT_DOC) -> dict:
    """Read one guidance document. Never writes, never raises.

    Defaults to the way-of-work because reading the rules at the start of a session
    is the common case.
    """
    result = {
        "project": project,
        "doc": doc,
        "path": None,
        "status": "",
        "text": None,
        "message": "",
    }

    if doc not in workspace.GUIDANCE_DOCS:
        result["status"] = "unknown_doc"
        result["message"] = (
            f"unknown doc {doc!r} — try one of: {', '.join(workspace.GUIDANCE_DOCS)}"
        )
        return result

    row = repository.get_project(project)
    if row is None:
        result["status"] = "unknown_project"
        result["message"] = f"unknown project {project!r}"
        return result

    result["path"] = str(workspace.guidance_path(row.slug, doc))
    text = workspace.read_guidance(row.slug, doc)
    if text is None:
        result["status"] = "not_scaffolded"
        result["message"] = (
            f"no guidance folder for {row.slug!r} yet — run `trackden onboard {row.slug}` "
            "(safe to re-run) to scaffold it"
        )
        return result

    result["text"] = text
    result["status"] = "template" if workspace.is_template(doc, text, name=row.name) else "filled"
    return result


def add_decision(
    project: str, decision: str, because: str, rejected: str | None = None
) -> dict:
    """Append a decision — with its reasoning — to the project's `_decisions.md`.

    `because` is required by the signature: a decisions log that records what changed
    without why is the failure mode the file exists to prevent. Refuses to scaffold a
    missing workspace, so onboarding stays the only thing that creates those files.
    """
    result = {"project": project, "path": None, "status": "", "message": ""}

    row = repository.get_project(project)
    if row is None:
        result["status"] = "unknown_project"
        result["message"] = f"unknown project {project!r}"
        return result

    path = workspace.append_decision(row.slug, decision, because, rejected)
    if path is None:
        result["path"] = str(workspace.guidance_path(row.slug, "decisions"))
        result["status"] = "not_scaffolded"
        result["message"] = (
            f"no guidance folder for {row.slug!r} yet — run `trackden onboard {row.slug}` "
            "(safe to re-run) to scaffold it"
        )
        return result

    result["path"] = str(path)
    result["status"] = "appended"
    return result
