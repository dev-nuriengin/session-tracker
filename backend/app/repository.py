"""Phase 4 — data-access layer over the core schema.

The rest of the app (tools, graph, endpoints, later the MCP server) calls these
functions; nobody else opens a SQLAlchemy session. This is the seam that makes
the tracker "do all the job" — real DB reads/writes live here, not a stub dict.
"""

from sqlalchemy import func, select

from . import models
from .data import PROJECTS, TRACKERS  # stub — used ONLY to seed the DB once
from .db import SessionLocal, init_db
from .embeddings import embed


# ---- projects ----

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


def create_project(slug: str, name: str | None = None, kind: str = "personal",
                   client: str | None = None) -> bool:
    """Create a project. Returns False if the slug already exists."""
    slug = slug.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(models.Project).where(models.Project.slug == slug)):
            return False
        db.add(models.Project(slug=slug, name=name or slug, kind=kind, client=client))
        db.commit()
        return True


def get_status(slug: str) -> str:
    """Short status string for a project (built from its first not-done item).
    Returns '' if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return ""
        nxt = db.scalar(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status != "done")
            .order_by(models.Item.position)
        )
        if nxt is None:
            return f"{project.name}: all items done."
        return f"{project.name}: NEXT — {nxt.title}"


def overview(slug: str) -> dict:
    """The cheap FIRST look — a compact summary, not a full dump. Counts + a few
    titles + last activity. Drill deeper with list_items / list_memory / get_history."""
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {}
        open_titles = db.scalars(
            select(models.Item.title)
            .where(models.Item.project_id == project.id, models.Item.status != "done")
            .order_by(models.Item.position)
        ).all()
        mem_count = db.scalar(
            select(func.count()).select_from(models.Memory)
            .where(models.Memory.project_id == project.id)
        )
        last_log = db.scalar(
            select(models.SessionLog.content)
            .join(models.Session)
            .where(models.Session.project_id == project.id)
            .order_by(models.SessionLog.created_at.desc())
        )
        return {
            "project": project.slug,
            "next": open_titles[0] if open_titles else None,
            "open_items": len(open_titles),
            "open_preview": list(open_titles[:3]),  # a taste, not all of them
            "memory_entries": mem_count or 0,
            "last_activity": last_log,
        }


def list_items(slug: str, include_done: bool = False) -> list[dict]:
    """Drill-down: all items for a project (open only unless include_done)."""
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        q = select(models.Item).where(models.Item.project_id == project.id)
        if not include_done:
            q = q.where(models.Item.status != "done")
        rows = db.scalars(q.order_by(models.Item.position)).all()
        return [{"id": i.id, "title": i.title, "status": i.status, "folder_id": i.folder_id} for i in rows]


# ---- folders & items ----

def create_folder(slug: str, name: str, parent_id: int | None = None) -> int | None:
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return None
        folder = models.Folder(project_id=project.id, name=name, parent_id=parent_id)
        db.add(folder)
        db.commit()
        return folder.id


def add_item(slug: str, title: str, folder_id: int | None = None) -> int | None:
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return None
        item = models.Item(project_id=project.id, title=title, folder_id=folder_id)
        db.add(item)
        db.commit()
        return item.id


# ---- durable memory (decisions, links, notes) ----

def add_memory(slug: str, content: str, kind: str = "note", title: str | None = None,
               url: str | None = None) -> bool:
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return False
        db.add(models.Memory(project_id=project.id, content=content, kind=kind, title=title, url=url))
        db.commit()
        return True


def list_memory(slug: str) -> list[dict]:
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        rows = db.scalars(
            select(models.Memory)
            .where(models.Memory.project_id == project.id)
            .order_by(models.Memory.created_at.desc())
        ).all()
        return [{"kind": m.kind, "title": m.title, "content": m.content, "url": m.url} for m in rows]


# ---- sessions & continuity ----

def add_session_log(slug: str, thread_id: str, content: str, kind: str = "note") -> bool:
    """Save a session log entry for a project (creating the session on first use).
    Returns False if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return False
        session = db.scalar(select(models.Session).where(models.Session.thread_id == thread_id))
        if session is None:
            session = models.Session(project_id=project.id, thread_id=thread_id)
            db.add(session)
            db.flush()
        db.add(models.SessionLog(
            session_id=session.id, content=content, kind=kind, embedding=embed(content)
        ))
        db.commit()
        return True


def search_logs(query: str, limit: int = 5) -> list[dict]:
    """Semantic search across ALL projects' session logs (local embeddings + pgvector).
    Returns the closest log entries with their project + a similarity score."""
    qv = embed(query)
    with SessionLocal() as db:
        rows = db.execute(
            select(
                models.SessionLog,
                models.Project.slug,
                models.SessionLog.embedding.cosine_distance(qv).label("dist"),
            )
            .join(models.Session, models.SessionLog.session_id == models.Session.id)
            .join(models.Project, models.Session.project_id == models.Project.id)
            .where(models.SessionLog.embedding.is_not(None))
            .order_by("dist")
            .limit(limit)
        ).all()
        return [
            {"project": slug, "kind": log.kind, "content": log.content, "score": round(1 - dist, 3)}
            for log, slug, dist in rows
        ]


def get_history(slug: str, limit: int = 10) -> dict:
    """Continuity payload for a new session — 'pull the history first'.
    Returns the project's open items, recent memory, and recent session logs."""
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {}
        open_items = db.scalars(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status != "done")
            .order_by(models.Item.position)
        ).all()
        recent_logs = db.scalars(
            select(models.SessionLog)
            .join(models.Session)
            .where(models.Session.project_id == project.id)
            .order_by(models.SessionLog.created_at.desc())
            .limit(limit)
        ).all()
        return {
            "project": project.slug,
            "open_items": [i.title for i in open_items],
            "memory": list_memory(slug),
            "recent_logs": [{"kind": l.kind, "content": l.content} for l in recent_logs],
        }


# ---- seed & setup ----

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
            title = (
                status.split("NEXT:", 1)[-1].strip()
                if "NEXT:" in status
                else (status or "Set up project")
            )
            db.add(models.Item(project_id=project.id, title=title, status="todo", position=0))
        db.commit()


def setup() -> None:
    """Create tables + seed once. Called on app startup."""
    init_db()
    seed()
