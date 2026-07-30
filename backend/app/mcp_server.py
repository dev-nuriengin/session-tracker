"""Phase 5 — the MCP server: THE HEART of the product.

Exposes the tracker's core to ANY MCP-capable agent (Claude Code, Codex, …) in a
standard way, with no per-agent configuration. Each tool is a thin wrapper over the
repository — the same core the CLI and web use.

Run (stdio transport): `uv run python -m app.mcp_server`
Wire into Claude Code via the repo's `.mcp.json`.
"""

from mcp.server.fastmcp import FastMCP

from . import guidance, repository

mcp = FastMCP("trackden")


@mcp.tool()
def list_projects() -> list[str]:
    """List all of the user's projects (slugs)."""
    return repository.list_projects()


@mcp.tool()
def overview(project: str) -> dict:
    """Call this FIRST when you start on a project. A COMPACT summary — next step,
    open-item count + a few titles, memory count, last activity. It is cheap and does
    NOT dump everything. Drill deeper with list_items / list_memory only if you need to."""
    return repository.overview(project)


@mcp.tool()
def list_items(project: str, include_done: bool = False) -> list[dict]:
    """Drill-down: the project's items (open only unless include_done=true).
    Use AFTER overview, only when you need the full list."""
    return repository.list_items(project, include_done=include_done)


@mcp.tool()
def list_memory(project: str) -> list[dict]:
    """Drill-down: the project's durable memory (decisions, links, notes).
    Use AFTER overview, only when you need the details."""
    return repository.list_memory(project)


@mcp.tool()
def get_guidance(project: str, doc: str = "way-of-work") -> dict:
    """The project's durable GUIDANCE — how it is worked on, its architecture, its
    decisions. Read `way-of-work` FIRST when you start on a project: it is the human's
    rules for this codebase. One document per call, so you never pay for what you are
    not using. doc: way-of-work | arch | decisions.
    `status` tells you what you got: filled (real content) · template (untouched
    boilerplate, don't over-read it) · not_scaffolded · unknown_project · unknown_doc."""
    return guidance.get(project, doc)


@mcp.tool()
def add_decision(
    project: str, decision: str, because: str, rejected: str | None = None
) -> dict:
    """Record a DECISION and its reasoning into the project's decisions log — use this
    whenever a choice gets made ("we decided X because Y"). `because` is required: a
    decision without its reason is worthless to the next session. `rejected` is the
    alternative you turned down, if there was one. This writes to the guidance file,
    NOT the memory table — for links and notes use add_memory instead."""
    return guidance.add_decision(project, decision, because, rejected)


@mcp.tool()
def get_history(project: str, limit: int = 10) -> dict:
    """Use AFTER overview, when you are RESUMING work and need the full continuity
    payload in one call: open items + memory + the last `limit` session logs. Heavier
    than overview — call it when you need the whole picture, not just a status check."""
    return repository.get_history(project, limit=limit)


@mcp.tool()
def search(query: str, limit: int = 5) -> list[dict]:
    """Semantic search across ALL projects' session logs (RAG). Use this to answer
    "have I done/seen X before?" across your whole history, not just one project."""
    return repository.search_logs(query, limit=limit)


@mcp.tool()
def whats_next(project: str) -> str:
    """The single next step for a project (its first not-done item)."""
    return repository.get_status(project)


@mcp.tool()
def save_progress(project: str, thread_id: str, note: str, kind: str = "step") -> bool:
    """Save what you just did into the tracker (progress capture).
    kind: step | note | summary | plan. thread_id names this work session."""
    return repository.add_session_log(project, thread_id, note, kind)


@mcp.tool()
def add_memory(
    project: str,
    content: str,
    kind: str = "note",
    title: str | None = None,
    url: str | None = None,
) -> dict:
    """Save a durable fact to the project's memory — a repo link, a note, a meeting
    transcript. kind: link | note | transcript.
    NOT for decisions: those go to add_decision, which writes them to the project's
    decisions guidance file so each fact has exactly one home."""
    try:
        saved = repository.add_memory(project, content, kind=kind, title=title, url=url)
    except ValueError as exc:
        return {"status": "rejected_kind", "message": str(exc)}
    return {"status": "saved" if saved else "unknown_project"}


if __name__ == "__main__":
    repository.setup()  # ensure tables exist + seeded when run standalone
    mcp.run()  # stdio transport
