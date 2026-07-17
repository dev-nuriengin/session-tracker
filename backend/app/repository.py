"""Phase 4 — data-access layer over the core schema.

The rest of the app (tools, graph, endpoints, later the MCP server) calls these
functions; nobody else opens a SQLAlchemy session. This is the seam that makes
the tracker "do all the job" — swap the stub dict for real DB reads/writes here.
"""

from sqlalchemy import select

from . import models
from .data import PROJECTS, TRACKERS  # stub — used ONLY to seed the DB once
from .db import SessionLocal, init_db


def list_projects() -> list[str]:
    """All project slugs, alphabetical."""
    with SessionLocal() as db:
        return list(
            db.scalars(select(models.Project.slug).order_by(models.Project.slug)).all()
        )


def get_project(slug: str) -> models.Project | None:
    with SessionLocal() as db:
        return db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )


def get_status(slug: str) -> str:
    """Short status string for a project (the read_tracker behavior), built from
    its first not-done tracking item. Returns '' if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return ""
        nxt = db.scalar(
            select(models.TrackingItem)
            .where(
                models.TrackingItem.project_id == project.id,
                models.TrackingItem.status != "done",
            )
            .order_by(models.TrackingItem.position)
        )
        if nxt is None:
            return f"{project.name}: all tracking items done."
        return f"{project.name}: NEXT — {nxt.title}"


def add_session_log(slug: str, thread_id: str, content: str, kind: str = "note") -> bool:
    """Save a session log entry for a project (creating the session on first use).
    Returns False if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return False
        session = db.scalar(
            select(models.Session).where(models.Session.thread_id == thread_id)
        )
        if session is None:
            session = models.Session(project_id=project.id, thread_id=thread_id)
            db.add(session)
            db.flush()
        db.add(models.SessionLog(session_id=session.id, content=content, kind=kind))
        db.commit()
        return True


def seed() -> None:
    """One-time seed from the old stub so there's data to work with."""
    with SessionLocal() as db:
        if db.scalar(select(models.Project).limit(1)) is not None:
            return  # already seeded
        for slug in PROJECTS:
            status = TRACKERS.get(slug, "")
            kind = "client" if slug == "integral" else "personal"
            project = models.Project(slug=slug, name=slug, kind=kind)
            db.add(project)
            db.flush()
            # turn the stub "... NEXT: <x>" string into one tracking item
            title = (
                status.split("NEXT:", 1)[-1].strip()
                if "NEXT:" in status
                else (status or "Set up project")
            )
            db.add(
                models.TrackingItem(
                    project_id=project.id, title=title, status="todo", position=0
                )
            )
        db.commit()


def setup() -> None:
    """Create tables + seed once. Called on app startup."""
    init_db()
    seed()
