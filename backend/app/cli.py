"""trackden — Trackden CLI (Phase 6). Your main hand-driven door into the core.

Talks to the SAME `repository` the MCP server and the API use — one core, three
doors. Data is read from / written to the local Postgres, never a hardcoded list.

Run:  `uv run trackden <command>`   (or `uv run python -m app.cli <command>`)
"""

from pathlib import Path

import typer

from . import onboard as onboard_mod
from . import repository

app = typer.Typer(
    help="Trackden — one door into all your work.",
    no_args_is_help=True,
)


@app.command("list")
def list_projects():
    """List all projects."""
    projects = repository.list_projects()
    if not projects:
        typer.echo("No projects yet. Add one:  trackden add-project <slug>")
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


@app.command("eval")
def eval_cmd(project: str = typer.Argument(None, help="Project to eval (default: all)")):
    """LLM-as-judge: score the brain's summary for a project (or all)."""
    from . import eval as _eval  # lazy — don't load the judge unless used

    rows = _eval.evaluate([project] if project else None)
    if not rows:
        typer.echo("Nothing to eval.")
        raise typer.Exit()
    for r in rows:
        typer.echo(
            f"  {r['project']}: faithfulness={r['faithfulness']} "
            f"conciseness={r['conciseness']} — {r['reason']}"
        )


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


_GATE_PREVIEW = 10  # show at most this many items before asking


def _prompt_matches(answer: str, word: str) -> bool:
    """Is `answer` a (non-empty) prefix of `word`? — lets "y"/"ye"/"yes" all count."""
    return bool(answer) and word.startswith(answer)


def _review_gate(hit: onboard_mod.ScanHit) -> list[onboard_mod.ParsedItem] | None:
    """Interactive review gate — nothing is imported without a yes.

    y    → import everything found in this file (also what a blank answer means)
    n    → skip this file
    edit → pick which numbered items to import (blank = all)

    The gate always errs toward NOT importing: an answer that isn't y/n/edit, or an
    `edit` selection containing so much as one unparseable or out-of-range number,
    skips the whole file rather than guessing at what the user meant.
    """
    items = list(hit.parsed.items)
    typer.echo(f"\nFound {len(items)} items in {hit.relpath}")
    for number, item in enumerate(items[:_GATE_PREVIEW], 1):
        typer.echo(f"   {number:>2}. [{item.status}] {item.title}")
    if len(items) > _GATE_PREVIEW:
        typer.echo(f"   … and {len(items) - _GATE_PREVIEW} more")

    answer = typer.prompt("Import? (y / n / edit)", default="y").strip().lower()

    if not answer or _prompt_matches(answer, "yes"):
        return items

    if _prompt_matches(answer, "no"):
        typer.echo("  skipped")
        return None

    if _prompt_matches(answer, "edit"):
        picked = typer.prompt(
            "Numbers to import (comma-separated, blank = all)", default=""
        ).strip()
        if not picked:
            return items
        valid: list[int] = []
        invalid: list[str] = []
        for token in (part.strip() for part in picked.split(",")):
            if token.isdigit() and 1 <= int(token) <= len(items):
                valid.append(int(token))
            else:
                invalid.append(token)
        if invalid:
            typer.echo(
                f"  not a valid item number: {', '.join(invalid)} — skipping this file"
            )
            return None
        wanted = set(valid)
        return [item for number, item in enumerate(items, 1) if number in wanted]

    typer.echo(f"  '{answer}' not understood — skipping this file")
    return None


@app.command()
def onboard(
    slug: str = typer.Argument(None, help="Project slug (omit for the interactive wizard)"),
    name: str = typer.Option(None, help="Display name"),
    kind: str = typer.Option("personal", help="personal | client"),
    client: str = typer.Option(None, help="Client name (for client projects)"),
    repo: str = typer.Option(None, help="Repo path to scan (default: the current directory)"),
    no_import: bool = typer.Option(False, "--no-import", help="Skip auto-detect entirely"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Import everything found, no prompts"),
):
    """Bring a project into Trackden: import what exists, scaffold the rest.

    Reads the repo (never writes to it), asks before importing anything, then creates
    the project in the DB and its guidance folder under ~/.trackden.
    """
    wizard = slug is None
    if wizard:
        name = name or typer.prompt("Project name")
        slug = typer.prompt("Slug", default=onboard_mod.slugify(name))
        kind = typer.prompt("Kind (personal | client)", default=kind)
        if kind == "client" and not client:
            client = typer.prompt("Client name", default="") or None
        repo = repo or typer.prompt("Repo path to scan", default=str(Path.cwd()))

    if repo is None and not no_import:
        cwd = Path.cwd()
        repo = str(cwd) if (cwd / ".git").exists() else None

    try:
        result = onboard_mod.run_onboard(
            slug=slug,
            name=name,
            kind=kind,
            client=client,
            repo=repo,
            import_items=not no_import,
            confirm=None if yes else _review_gate,
        )
    except ValueError as exc:
        typer.echo(f"cannot onboard: {exc}")
        raise typer.Exit(1)

    typer.echo("")
    typer.echo(f"✓ project '{result.slug}' — {'created' if result.created else 'already existed, updated'}")
    typer.echo(f"  items imported : {result.imported}" + (
        f"  (from {', '.join(result.sources)})" if result.sources else ""
    ))
    typer.echo("  guidance       :")
    for path in result.files:
        typer.echo(f"      • {path}")
    if not result.git_ready:
        typer.echo("  ⚠ workspace is not a git repo (git unavailable) — guidance is unversioned")
    typer.echo(f"\nNext:  trackden show {result.slug}")


if __name__ == "__main__":
    app()
