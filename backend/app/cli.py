"""sess — Session Tracker CLI (Phase 6). Your main hand-driven door into the core.

Talks to the SAME `repository` the MCP server and the API use — one core, three
doors. Data is read from / written to the local Postgres, never a hardcoded list.

Run:  `uv run sess <command>`   (or `uv run python -m app.cli <command>`)
"""

import typer

from . import repository

app = typer.Typer(
    help="Session Tracker — one door into all your work.",
    no_args_is_help=True,
)


@app.command("list")
def list_projects():
    """List all projects."""
    projects = repository.list_projects()
    if not projects:
        typer.echo("No projects yet. Add one:  sess add-project <slug>")
        raise typer.Exit()
    typer.echo("Projects:")
    for i, name in enumerate(projects, 1):
        typer.echo(f"  {i}. {name}")


@app.command()
def status(project: str):
    """Show a project's next step."""
    typer.echo(repository.get_status(project) or f"Unknown project '{project}'.")


@app.command()
def show(project: str, full: bool = typer.Option(False, "--full", help="Deep view: all items, memory, logs")):
    """Show a project — compact overview by default; --full for everything."""
    if not full:
        ov = repository.overview(project)
        if not ov:
            typer.echo(f"Unknown project '{project}'.")
            raise typer.Exit(1)
        typer.echo(f"# {ov['project']}")
        typer.echo(f"  next          : {ov['next'] or '(none)'}")
        typer.echo(f"  open items    : {ov['open_items']}")
        for t in ov["open_preview"]:
            typer.echo(f"      • {t}")
        typer.echo(f"  memory        : {ov['memory_entries']}")
        typer.echo(f"  last activity : {ov['last_activity'] or '(none)'}")
        typer.echo("  (use --full for all items, memory, logs)")
        return
    h = repository.get_history(project)
    if not h:
        typer.echo(f"Unknown project '{project}'.")
        raise typer.Exit(1)
    typer.echo(f"# {h['project']}\n")
    typer.echo("Open items:")
    for it in h["open_items"] or ["(none)"]:
        typer.echo(f"  • {it}")
    typer.echo("\nMemory:")
    for m in h["memory"]:
        line = f"  • [{m['kind']}] {m['content']}"
        if m.get("url"):
            line += f"  ({m['url']})"
        typer.echo(line)
    if not h["memory"]:
        typer.echo("  (none)")
    typer.echo("\nRecent session logs:")
    for log_ in h["recent_logs"]:
        typer.echo(f"  • [{log_['kind']}] {log_['content']}")
    if not h["recent_logs"]:
        typer.echo("  (none)")


@app.command("add-project")
def add_project(
    slug: str,
    name: str = typer.Option(None, help="Display name (defaults to slug)"),
    kind: str = typer.Option("personal", help="personal | client"),
    client: str = typer.Option(None, help="Client name (for client projects)"),
):
    """Add a new project to the tracker."""
    ok = repository.create_project(slug, name=name, kind=kind, client=client)
    typer.echo(f"✓ created project '{slug}'" if ok else f"project '{slug}' already exists")


@app.command("add-folder")
def add_folder(project: str, name: str):
    """Add a folder to a project."""
    fid = repository.create_folder(project, name)
    typer.echo(f"✓ folder #{fid} added to {project}" if fid else f"unknown project '{project}'")


@app.command("add-item")
def add_item(project: str, title: str, folder: int = typer.Option(None, help="Folder id")):
    """Add a work item to a project (optionally inside a folder)."""
    iid = repository.add_item(project, title, folder_id=folder)
    typer.echo(f"✓ item #{iid} added to {project}" if iid else f"unknown project '{project}'")


@app.command()
def remember(
    project: str,
    content: str,
    kind: str = typer.Option("note", help="decision | link | note | transcript"),
    url: str = typer.Option(None, help="Link (e.g. GitLab/GitHub)"),
    title: str = typer.Option(None),
):
    """Save a durable fact (decision / link / note) to a project's memory."""
    ok = repository.add_memory(project, content, kind=kind, title=title, url=url)
    typer.echo("✓ saved to memory" if ok else f"unknown project '{project}'")


@app.command()
def ask(query: str, limit: int = typer.Option(5, help="Max results")):
    """Semantic search across ALL projects' session logs (RAG)."""
    hits = repository.search_logs(query, limit=limit)
    if not hits:
        typer.echo("No matches (no embedded logs yet?).")
        raise typer.Exit()
    for h in hits:
        typer.echo(f"  [{h['score']}] {h['project']} · {h['kind']}: {h['content']}")


@app.command()
def log(
    project: str,
    note: str,
    thread: str = typer.Option("cli", help="Session/thread id"),
    kind: str = typer.Option("step", help="step | note | summary | plan"),
):
    """Save session progress (a step/note) for a project."""
    ok = repository.add_session_log(project, thread, note, kind)
    typer.echo("✓ logged" if ok else f"unknown project '{project}'")


if __name__ == "__main__":
    app()
