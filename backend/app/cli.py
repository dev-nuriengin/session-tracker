"""trackden — Trackden CLI (Phase 6). Your main hand-driven door into the core.

Talks to the SAME `repository` the MCP server and the API use — one core, three
doors. Data is read from / written to the local Postgres, never a hardcoded list.

Run:  `uv run trackden <command>`   (or `uv run python -m app.cli <command>`)
"""

from pathlib import Path

import typer

from . import guidance as guidance_mod
from . import onboard as onboard_mod
from . import playbook as playbook_mod
from . import repository
from . import workspace as workspace_mod
from .db import init_db

app = typer.Typer(
    help="Trackden — one door into all your work.",
    no_args_is_help=True,
)


@app.callback()
def _ensure_schema() -> None:
    """Run before every command: make sure the schema exists.

    `cli.py` never called `init_db()` before — only `repository.setup()` did (from
    FastAPI startup / the MCP server's `__main__`), which `cli.py` calls neither.
    Against any database whose `projects` table predates a column this branch adds
    (e.g. `repo_path`), the first query would raise a raw `UndefinedColumn` — and
    since `cli.py` only catches `ValueError`, every command broke, not just `onboard`.

    `init_db()` only tops up missing tables/columns (idempotent) and never touches
    data. It used to matter that this was NOT `repository.setup()`, because `setup()`
    also seeded six stub projects into whatever database it found; that seeding is
    gone, so the two are equivalent now and either would be safe here.
    """
    init_db()


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
def show(
    project: str,
    full: bool = typer.Option(False, "--full", help="Deep view: all items, memory, logs"),
    item: int = typer.Option(
        None, "--item", help="Resume one item: its status, its memory (with paths), its logs"
    ),
):
    """Show a project — compact overview by default; --full for everything; --item for one thing."""
    if item is not None:
        h = repository.get_history(project, item_id=item)
        if not h:
            typer.echo(f"Unknown project '{project}'.")
            raise typer.Exit(1)
        if h.get("status") == "unknown_item":
            typer.echo(f"Unknown item #{item} in '{project}'.")
            raise typer.Exit(1)
        it = h["item"]
        typer.echo(f"# {it['title']}  [{it['status']}]\n")
        typer.echo("Memory:")
        for m in h["memory"]:
            line = f"  • [{m['kind']}] {m['content']}"
            if m.get("url"):
                line += f"  ({m['url']})"
            if m.get("path"):
                line += f"  ({m['path']})"
            typer.echo(line)
        if not h["memory"]:
            typer.echo("  (none)")
        typer.echo("\nSession logs:")
        for log_ in h["recent_logs"]:
            typer.echo(f"  • [{log_['kind']}] {log_['content']}")
        if not h["recent_logs"]:
            typer.echo("  (none)")
        return
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
        typer.echo(f"  waiting       : {ov['waiting_items']}")
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
        if m.get("path"):
            line += f"  ({m['path']})"
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
def add_folder(
    project: str,
    name: str,
    parent: int = typer.Option(None, help="Parent folder id (nest inside it)"),
):
    """Add a folder to a project, optionally nested inside another folder."""
    result = repository.create_folder(project, name, parent_id=parent)
    if result["status"] == "added":
        typer.echo(f"✓ folder #{result['folder_id']} added to {project}")
        return
    messages = {
        "invalid_name": (
            f"a folder name cannot be blank or longer than "
            f"{repository.MAX_FOLDER_NAME} characters"
        ),
        "unknown_parent": f"unknown parent folder #{parent} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[result["status"]])
    raise typer.Exit(1)


@app.command("add-item")
def add_item(
    project: str,
    title: str,
    folder: int = typer.Option(None, help="Folder id"),
    status: str = typer.Option(None, help="Starting status (default: todo)"),
):
    """Add a work item to a project (optionally inside a folder, at a given status)."""
    result = repository.add_item(project, title, folder_id=folder, status=status)
    outcome = result["status"]
    if outcome == "added":
        typer.echo(f"✓ item #{result['item_id']} added to {project}")
        return
    if outcome == "unknown_status":
        typer.echo(f"unknown status '{status}'. valid: {', '.join(result['valid'])}")
        raise typer.Exit(1)
    messages = {
        "unknown_folder": f"unknown folder #{folder} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)


@app.command("set-status")
def set_status(project: str, item_id: int, status: str):
    """Move an item to a new status (see `trackden statuses <project>` for the valid names)."""
    result = repository.set_status(project, item_id, status)
    outcome = result["status"]
    if outcome == "set":
        typer.echo(f"✓ item #{item_id}: {result['from']} → {result['to']}")
        return
    if outcome == "unchanged":
        typer.echo(f"item #{item_id} is already '{result['to']}'")
        return
    if outcome == "unknown_status":
        typer.echo(f"unknown status '{status}'. valid: {', '.join(result['valid'])}")
    elif outcome == "unknown_item":
        typer.echo(f"unknown item #{item_id} in '{project}'")
    else:
        typer.echo(f"unknown project '{project}'")
    raise typer.Exit(1)


@app.command("add-status")
def add_status(
    project: str,
    name: str,
    behaves_as: str = typer.Option(..., "--behaves-as", help="open | active | waiting | closed"),
):
    """Add a status name to a project. The four shipped names always stay valid."""
    result = repository.add_status(project, name, behaves_as)
    outcome = result["status"]
    if outcome == "added":
        typer.echo(f"✓ '{name}' added to {project} (behaves as {behaves_as})")
        return
    if outcome == "unknown_class":
        typer.echo(f"unknown class '{behaves_as}'. valid: {', '.join(result['valid'])}")
        raise typer.Exit(1)
    messages = {
        "duplicate_name": f"'{name}' is already a status in {project}",
        "invalid_name": (
            f"a status name cannot be blank or longer than "
            f"{repository.MAX_STATUS_NAME} characters"
        ),
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)


@app.command()
def statuses(project: str):
    """List the status names a project accepts, with the class each behaves as."""
    rows = repository.list_statuses(project)
    if not rows:
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)
    typer.echo(f"# {project} — statuses")
    for row in rows:
        typer.echo(f"  {row['name']:<12} {row['behaves_as']}")


@app.command()
def remember(
    project: str,
    content: str,
    kind: str = typer.Option("note", help="link | note | transcript | file"),
    url: str = typer.Option(None, help="Link (e.g. GitLab/GitHub)"),
    path: str = typer.Option(None, help="Local file path (required for --kind file)"),
    item: int = typer.Option(None, help="Attach to this item id"),
    folder: int = typer.Option(None, help="Attach to this folder id"),
    title: str = typer.Option(None),
):
    """Save a durable fact (link / note / transcript / file) to a project's memory.
    For a decision use `trackden decide`."""
    result = repository.add_memory(
        project, content, kind=kind, title=title, url=url,
        path=path, item_id=item, folder_id=folder,
    )
    outcome = result["status"]
    if outcome == "saved":
        typer.echo("✓ saved to memory")
        if result.get("warning"):
            typer.echo(f"  note: {result['warning']}")
        return
    if outcome == "rejected_kind":
        typer.echo(result["message"])
        raise typer.Exit(1)
    messages = {
        "missing_path": "--path is required for --kind file",
        "invalid_path": (
            f"path is too long once resolved to an absolute path — must be at most "
            f"{repository.MAX_PATH} characters"
        ),
        "unknown_item": f"unknown item #{item} in '{project}'",
        "unknown_folder": f"unknown folder #{folder} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)


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
    item: int = typer.Option(None, help="Attach to this item id"),
):
    """Save session progress (a step/note) for a project."""
    result = repository.add_session_log(project, thread, note, kind, item_id=item)
    outcome = result["status"]
    if outcome == "saved":
        typer.echo("✓ logged")
        return
    messages = {
        "unknown_item": f"unknown item #{item} in '{project}'",
        "unknown_project": f"unknown project '{project}'",
    }
    typer.echo(messages[outcome])
    raise typer.Exit(1)


_COUNT_LABELS = ("items", "folders", "memory", "sessions", "logs", "statuses")


def _echo_counts(counts: dict, empty_message: str) -> None:
    """Print the nonzero rows of a counts dict, one per line — shared by the
    delete preview and the post-delete "what actually went" echo, so the two
    always render in the same shape."""
    nonzero = [label for label in _COUNT_LABELS if counts.get(label)]
    if nonzero:
        for label in nonzero:
            typer.echo(f"  {label:<10} {counts[label]}")
    else:
        typer.echo(f"  {empty_message}")


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
    if result.guidance_reused:
        # `scaffold_project` never overwrites an existing guidance file — correct,
        # since delete keeps a project's `_way-of-work.md` / `_arch.md` /
        # `_decisions.md` on purpose. But that means onboarding a slug that was used
        # before (deleted, then re-onboarded — same or different client) silently
        # inherits whatever the previous project wrote there. Say so, so a human
        # checks it rather than trusting it as this project's own.
        typer.echo(
            f"  ⚠ guidance files from a previous project with slug '{result.slug}' "
            f"were reused: {workspace_mod.project_dir(result.slug)}\n"
            "    check them — they may describe a different project"
        )
    typer.echo(f"\nNext:  trackden show {result.slug}")

    typer.echo(
        "\n  Paste into this repo's CLAUDE.md / AGENTS.md if you want agents to find it:\n"
        "\n"
        f'    This project is tracked in Trackden. Call `overview("{result.slug}")` first —\n'
        "    it carries the next step, the valid statuses, and Trackden's playbook digest.\n"
        "\n"
        "  (Trackden never writes to your repo. Copy it yourself, or don't.)"
    )


@app.command()
def guidance(
    project: str,
    doc: str = typer.Option("way-of-work", help="way-of-work | arch | decisions"),
):
    """Print one of a project's guidance documents."""
    result = guidance_mod.get(project, doc)
    if result["status"] in ("unknown_project", "not_scaffolded", "unknown_doc", "invalid_slug"):
        typer.echo(result["message"])  # `text` is None on every failure — see Task 2's amendment
        raise typer.Exit(1)
    if result["status"] == "template":
        typer.echo(f"({doc} is still the untouched template — {result['path']})\n")
    typer.echo(result["text"])


@app.command()
def decide(
    project: str,
    decision: str,
    because: str = typer.Option(..., help="Why this was chosen"),
    rejected: str = typer.Option(None, help="The alternative you turned down"),
):
    """Record a decision, and its reasoning, in the project's decisions log."""
    result = guidance_mod.add_decision(project, decision, because, rejected)
    if result["status"] in ("unknown_project", "not_scaffolded", "invalid_slug"):
        typer.echo(result["message"])
        raise typer.Exit(1)
    typer.echo(f"✓ decision recorded in {result['path']}")


@app.command()
def playbook():
    """Print Trackden's own rules for using Trackden (what agents read)."""
    typer.echo(playbook_mod.TEXT)


@app.command()
def delete(
    project: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
):
    """Remove a project and everything under it. Guidance files are kept.

    This is the only irreversible command, so it shows what will go and asks first.
    """
    # Normalise ONCE, here, so every downstream call (repository, workspace) agrees
    # on the same slug. `repository` already lowercases internally, but
    # `workspace.project_dir`'s `_SAFE_SLUG` guard rejects uppercase outright — so
    # `trackden delete ACME` used to delete the (lowercased) project, print success,
    # then silently lose the "kept your guidance files" notice when `project_dir`
    # raised on the un-normalised "ACME". Normalising here makes that unreachable
    # for ordinary input; the ValueError guard below now only protects against a
    # genuinely unsafe slug (e.g. one containing "..").
    project = project.strip().lower()

    counts = repository.project_counts(project)
    if counts["status"] == "unknown_project":
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)

    if not yes:
        typer.echo(f"About to delete '{project}' and everything under it:")
        _echo_counts(counts, "(nothing attached — just the project record itself)")
        typer.echo("  This cannot be undone.")
        if not typer.confirm("Delete it?"):
            typer.echo("aborted — nothing was deleted")
            raise typer.Exit(1)

    result = repository.delete_project(project)
    if result["status"] != "deleted":
        typer.echo(f"unknown project '{project}'")
        raise typer.Exit(1)

    typer.echo(f"✓ deleted '{project}'")
    # The preview ran in a separate transaction from the delete itself, so the two
    # can legitimately differ — an MCP-connected agent can add rows while the human
    # reads the prompt. Echoing the actual removed counts makes that divergence
    # visible instead of silently trusting the (possibly stale) preview.
    _echo_counts(result.get("removed", {}), "(nothing was attached)")
    try:
        kept = workspace_mod.project_dir(project)
    except ValueError:
        kept = None
    if kept is not None and kept.exists():
        typer.echo(f"  kept your guidance files (way-of-work, arch, decisions): {kept}")
        typer.echo("  delete that folder yourself if you really want it gone")


if __name__ == "__main__":
    app()
