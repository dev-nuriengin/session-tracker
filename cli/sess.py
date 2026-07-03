"""sess — Session Tracker CLI (skeleton).

Stubs only. Real logic (read .ai/_tracker.md, summarize, launch the agent)
comes in later phases.
"""
import typer

app = typer.Typer(
    help="Session Tracker — one entry point to every project.",
    no_args_is_help=True,
)

# Stub data — later this comes from the DB / each project's .ai/_tracker.md
PROJECTS = ["korpus", "visionbank", "hinbunakurdi", "growthhq", "integral", "resho-hub"]


@app.command("list")
def list_projects():
    """Show all projects (the picker)."""
    typer.echo("Projects:")
    for i, name in enumerate(PROJECTS, 1):
        typer.echo(f"  {i}. {name}")


@app.command()
def start(project: str):
    """Boot a project's context and start a session."""
    typer.echo(f"→ booting {project} … (stub)")
    typer.echo("  next: load .ai/_tracker.md → summarize → launch Claude")


@app.command()
def ask(question: str):
    """Ask a question across all project trackers."""
    typer.echo(f"Q: {question}")
    typer.echo("→ (stub) next: retrieve from all trackers and answer")


if __name__ == "__main__":
    app()
