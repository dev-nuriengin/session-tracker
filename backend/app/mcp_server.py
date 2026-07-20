"""Phase 5 — the MCP server: THE HEART of the product.

Exposes the tracker's core to ANY MCP-capable agent (Claude Code, Codex, …) in a
standard way, with no per-agent configuration. Each tool is a thin wrapper over the
repository — the same core the CLI and web use.

Run (stdio transport): `uv run python -m app.mcp_server`
Wire into Claude Code via the repo's `.mcp.json`.
"""

from mcp.server.fastmcp import FastMCP

from . import repository

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
) -> bool:
    """Save a durable fact to the project's memory — a decision, a repo link, a note,
    a meeting/decision transcript. kind: decision | link | note | transcript."""
    return repository.add_memory(project, content, kind=kind, title=title, url=url)


if __name__ == "__main__":
    repository.setup()  # ensure tables exist + seeded when run standalone
    mcp.run()  # stdio transport
