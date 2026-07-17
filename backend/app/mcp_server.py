"""Phase 5 — the MCP server: THE HEART of the product.

Exposes the tracker's core to ANY MCP-capable agent (Claude Code, Codex, …) in a
standard way, with no per-agent configuration. Each tool is a thin wrapper over the
repository — the same core the CLI and web use.

Run (stdio transport): `uv run python -m app.mcp_server`
Wire into Claude Code via the repo's `.mcp.json`.
"""

from mcp.server.fastmcp import FastMCP

from . import repository

mcp = FastMCP("session-tracker")


@mcp.tool()
def list_projects() -> list[str]:
    """List all of the user's projects (slugs)."""
    return repository.list_projects()


@mcp.tool()
def get_history(project: str) -> dict:
    """Pull a project's history FIRST when you start working on it: open items,
    durable memory (decisions, repo links, notes), and recent session logs.
    Call this at the start of every session so you never work without context."""
    return repository.get_history(project)


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
