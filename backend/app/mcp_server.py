"""Phase 5 — the MCP server: THE HEART of the product.

Exposes the tracker's core to ANY MCP-capable agent (Claude Code, Codex, …) in a
standard way, with no per-agent configuration. Each tool is a thin wrapper over the
repository — the same core the CLI and web use.

Run (stdio transport): `uv run python -m app.mcp_server`
Wire into Claude Code via the repo's `.mcp.json`.
"""

from mcp.server.fastmcp import FastMCP

from . import guidance, playbook, repository

mcp = FastMCP("trackden")


@mcp.tool()
def list_projects() -> list[str]:
    """List all of the user's projects (slugs)."""
    return repository.list_projects()


@mcp.tool()
def overview(project: str) -> dict:
    """Call this FIRST when you start on a project. A COMPACT summary — next step,
    open-item count + a few titles, how many are waiting, memory count, last
    activity, and the status names this project accepts. It is cheap and does NOT
    dump everything. Drill deeper with list_items / list_memory only if you need to."""
    return repository.overview(project)


@mcp.tool()
def list_items(project: str, include_done: bool = False) -> list[dict]:
    """Drill-down: the project's items (open only unless include_done=true).
    Use AFTER overview, only when you need the full list."""
    return repository.list_items(project, include_done=include_done)


@mcp.tool()
def set_status(project: str, item_id: int, status: str) -> dict:
    """Move an item to a new status — this is how you record PROGRESS, not just work.

    Set `doing` freely the moment you start on something; no need to ask.
    Announce a `waiting` change (blocked, parked, …) in one line so the user knows
    something stalled. ASK before you close anything (`done`, `dropped`) unless the
    user just told you it is finished — closing hides an item from `whats_next`.

    Only names from `statuses` (in the `overview` payload) are valid; never invent
    one. If the user's real situation has no matching name, offer to add one rather
    than forcing their state into the wrong label.

    `status` tells you what happened: set · unchanged · unknown_status (with the
    `valid` list, so you can correct yourself) · unknown_item · unknown_project.
    `from` and `to` are always reported, so you can see if someone else moved it."""
    return repository.set_status(project, item_id, status)


@mcp.tool()
def list_statuses(project: str) -> list[dict]:
    """The status names this project accepts, each with the class it behaves as:
    open (not started) · active (being worked on) · waiting (stalled, skipped by
    whats_next but still counted) · closed (finished or abandoned, hidden).
    `overview` already includes this — call it only if you need it on its own."""
    return repository.list_statuses(project)


@mcp.tool()
def get_playbook() -> dict:
    """Trackden's own rules for using Trackden — read this once per session.

    Covers when to save, how to change a status and when to ask first, how to grow a
    project's status vocabulary, and how files are handled (Trackden stores a path and
    never touches the file). Takes no arguments: it is the same for every project and
    works before any project exists.

    A short digest already rides in every `overview` response; call this when you want
    the reasoning behind it. Note that the project's own way-of-work outranks this
    document — read it with get_guidance(project, "way-of-work")."""
    return {"version": playbook.VERSION, "text": playbook.TEXT}


@mcp.tool()
def add_item(
    project: str,
    title: str,
    folder_id: int | None = None,
    status: str | None = None,
) -> dict:
    """Create a work item — use this when the user describes work that is not yet
    tracked ("there's a bug in the login redirect"), so it exists before you start.

    `folder_id` files it under a folder of THIS project (see add_folder); omit it to
    put the item directly under the project. `status` sets a starting state and
    defaults to `todo` — pass `doing` when the user is already working on it.

    `status` in the RESULT is the outcome, not the item's state: added (with
    `item_id`) · unknown_folder · unknown_status (with the `valid` list, so you can
    correct yourself) · unknown_project."""
    return repository.add_item(project, title, folder_id=folder_id, status=status)


@mcp.tool()
def add_folder(project: str, name: str, parent_id: int | None = None) -> dict:
    """Create a folder to group a project's items. Ask the user before inventing a
    structure — the shape of their work is theirs, not yours to impose.

    `parent_id` nests this folder inside another folder of the SAME project.
    Outcome: added (with `folder_id`) · invalid_name · unknown_parent · unknown_project."""
    return repository.create_folder(project, name, parent_id=parent_id)


@mcp.tool()
def add_status(project: str, name: str, behaves_as: str) -> dict:
    """Add a status name to this project's vocabulary. OFFER this, do not impose it:
    when the user's real situation has no matching name ("on hold" is not "blocked"),
    say so and ask whether to add one — never quietly force their state into a label
    that is nearly right.

    `behaves_as` is what the new name DOES, which is the part that matters:
    open (not started) · active (being worked on) · waiting (stalled — skipped as the
    next step but still counted) · closed (finished or abandoned). Explain the
    behaviour to the user, not just the word.

    Outcome: added · duplicate_name · unknown_class (with `valid`) · invalid_name ·
    unknown_project."""
    return repository.add_status(project, name, behaves_as)


@mcp.tool()
def list_memory(project: str) -> list[dict]:
    """Drill-down: the project's durable memory — repo links, notes, meeting
    transcripts. Decisions are NOT here: they live in the project's guidance file —
    read them with get_guidance(project, doc="decisions"). Use AFTER overview, only
    when you need the details."""
    return repository.list_memory(project)


@mcp.tool()
def get_guidance(project: str, doc: str = "way-of-work") -> dict:
    """The project's durable GUIDANCE — how it is worked on, its architecture, its
    decisions. Read `way-of-work` after `overview`, before you change anything: it is
    the human's rules for this codebase. One document per call, so you never pay for
    what you are not using. doc: way-of-work | arch | decisions.
    `status` tells you what you got: filled (real content) · template (untouched
    boilerplate, don't over-read it) · not_scaffolded · unknown_project · unknown_doc ·
    invalid_slug (the project's stored slug isn't usable for guidance)."""
    return guidance.get(project, doc)


@mcp.tool()
def add_decision(
    project: str, decision: str, because: str, rejected: str | None = None
) -> dict:
    """Record a DECISION and its reasoning into the project's decisions log — use this
    whenever a choice gets made ("we decided X because Y"). `because` is required: a
    decision without its reason is worthless to the next session. `rejected` is the
    alternative you turned down, if there was one. This writes to the guidance file,
    NOT the memory table — for links and notes use add_memory instead.
    `status` tells you what you got: appended · not_scaffolded · unknown_project ·
    invalid_slug (the project's stored slug isn't usable for guidance)."""
    return guidance.add_decision(project, decision, because, rejected)


@mcp.tool()
def get_history(project: str, limit: int = 10, item_id: int | None = None) -> dict:
    """Use AFTER overview, when you are RESUMING work and need the full continuity
    payload in one call: open items + memory + the last `limit` session logs. Heavier
    than overview — call it when you need the whole picture, not just a status check.
    Pass `item_id` when resuming work on one specific item to get that item's whole
    story — its logs, its files, its status — instead of the project's last N
    entries. `item_id` is validated against this project: an item from another
    project returns `{"status": "unknown_item"}`. An unknown project still returns
    `{}`, unchanged."""
    return repository.get_history(project, limit=limit, item_id=item_id)


@mcp.tool()
def search(query: str, limit: int = 5) -> list[dict]:
    """Semantic search across ALL projects' session logs (RAG). Use this to answer
    "have I done/seen X before?" across your whole history, not just one project."""
    return repository.search_logs(query, limit=limit)


@mcp.tool()
def whats_next(project: str) -> str:
    """The single next step for a project: its first item that is not `waiting`
    and not `closed` (open, active, or a status this vocabulary does not
    recognise — that's deliberate, so an unclassified value surfaces here and
    you can correct it, instead of hiding). Waiting items (blocked, parked, …)
    are skipped but still reported as a count — use get_history or list_items
    to see which ones."""
    return repository.get_status(project)


@mcp.tool()
def save_progress(
    project: str, thread_id: str, note: str, kind: str = "step", item_id: int | None = None
) -> dict:
    """Save what you just did into the tracker (progress capture).
    kind: step | note | summary | plan. thread_id names this work session.
    Pass `item_id` when the progress is about one specific item, so it doesn't sit
    in a pile with every other item's progress. `item_id` is validated against
    this project. Returns the outcome unchanged: status is one of
    saved · unknown_item · unknown_project."""
    return repository.add_session_log(project, thread_id, note, kind, item_id=item_id)


@mcp.tool()
def add_memory(
    project: str,
    content: str,
    kind: str = "note",
    title: str | None = None,
    url: str | None = None,
    path: str | None = None,
    item_id: int | None = None,
    folder_id: int | None = None,
) -> dict:
    """Save a durable fact to the project's memory — a repo link, a note, a meeting
    transcript, or a pointer to a local file. kind: link | note | transcript | file.

    For `kind="file"`: ask the user where the file is, then pass its path here.
    Trackden only stores the path — it never creates, moves, or reads the file itself.
    `path` is required for `kind="file"`.

    Pass `item_id` when the fact is about one specific item (a bug, a ticket), so it
    doesn't sit in a pile with every other item's memory. Leave it out for a
    project-level fact. `item_id` and `folder_id` are validated against this project.

    NOT for decisions: those go to add_decision, which writes them to the project's
    decisions guidance file so each fact has exactly one home.

    Returns the outcome unchanged: status is one of saved · invalid_path ·
    missing_path · rejected_kind (with `valid` and `message`) · unknown_item ·
    unknown_folder · unknown_project."""
    return repository.add_memory(
        project, content, kind=kind, title=title, url=url,
        path=path, item_id=item_id, folder_id=folder_id,
    )


if __name__ == "__main__":
    repository.setup()  # ensure tables exist + seeded when run standalone
    mcp.run()  # stdio transport
