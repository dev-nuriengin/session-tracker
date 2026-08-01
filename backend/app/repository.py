"""Phase 4 — data-access layer over the core schema.

The rest of the app (tools, graph, endpoints, later the MCP server) calls these
functions; nobody else opens a SQLAlchemy session. This is the seam that makes
the tracker "do all the job" — real DB reads/writes live here, not a stub dict.
"""

from pathlib import Path

from sqlalchemy import func, select

from . import models, statuses as st
from .data import PROJECTS, TRACKERS  # stub — used ONLY to seed the DB once
from .db import SessionLocal, init_db
from .embeddings import embed
from .tracker_md import DONE, TODO, TrackerItem


def _norm_path(raw: str) -> str:
    """One canonical spelling of a filesystem path, so cwd→project lookups match
    regardless of trailing slashes, `~`, or symlinks."""
    return str(Path(raw).expanduser().resolve())


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
                   client: str | None = None, repo_path: str | None = None) -> bool:
    """Create a project. Returns False if the slug already exists."""
    slug = slug.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(models.Project).where(models.Project.slug == slug)):
            return False
        db.add(models.Project(
            slug=slug,
            name=name or slug,
            kind=kind,
            client=client,
            repo_path=_norm_path(repo_path) if repo_path else None,
        ))
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


def set_repo_path(slug: str, repo_path: str) -> bool:
    """Point an existing project at a repo. False if the project is unknown."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return False
        project.repo_path = _norm_path(repo_path)
        db.commit()
        return True


def get_project_by_repo_path(repo_path: str) -> models.Project | None:
    """Which project lives in this directory? (Powers cwd→project detection.)"""
    with SessionLocal() as db:
        return db.scalar(
            select(models.Project).where(models.Project.repo_path == _norm_path(repo_path))
        )


def import_items(slug: str, items: list[TrackerItem]) -> int:
    """Bulk-create items from parsed markdown, creating folders by name as needed.

    Each dict is `{"title", "status", "folder"}`. Any status other than todo/done is
    coerced to todo — richer statuses are the user's to set, never inferred from a file.
    Returns how many items were created (0 if the project is unknown).
    """
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return 0

        # Seed the name→id map with folders that ALREADY exist (e.g. created by
        # `add-folder`, or by a prior onboard) so re-running import never creates a
        # second `Folder` row with the same name — this map only dedupes within a
        # single call otherwise.
        folders: dict[str, int] = {
            folder.name: folder.id
            for folder in db.scalars(
                select(models.Folder).where(models.Folder.project_id == project.id)
            ).all()
        }
        created = 0
        for position, raw in enumerate(items):
            name = raw.get("folder")
            folder_id = None
            if name:
                if name not in folders:
                    folder = models.Folder(
                        project_id=project.id, name=name, position=len(folders)
                    )
                    db.add(folder)
                    db.flush()
                    folders[name] = folder.id
                folder_id = folders[name]
            status = raw.get("status") if raw.get("status") in (TODO, DONE) else TODO
            db.add(models.Item(
                project_id=project.id,
                folder_id=folder_id,
                title=raw["title"],
                status=status,
                position=position,
            ))
            created += 1
        db.commit()
        return created


def items_with_folders(slug: str) -> list[TrackerItem]:
    """Every item plus its folder NAME — the shape `render_tracker_md` wants."""
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return []
        rows = db.execute(
            select(models.Item.title, models.Item.status, models.Folder.name)
            .outerjoin(models.Folder, models.Item.folder_id == models.Folder.id)
            .where(models.Item.project_id == project.id)
            .order_by(models.Item.position, models.Item.id)
        ).all()
        return [{"title": title, "status": status, "folder": folder}
                for title, status, folder in rows]


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


# ---- the status vocabulary ----

def _vocabulary(db, project_id: int) -> dict[str, str]:
    """The resolved status vocabulary for one project: defaults + its extras.

    Takes an open session because every caller already has one — this is the hot
    path for the "open item" queries and must not open a second connection.
    """
    extras = {
        row.name: row.behaves_as
        for row in db.scalars(
            select(models.ItemStatus).where(models.ItemStatus.project_id == project_id)
        ).all()
    }
    return st.resolve(extras)


def list_statuses(slug: str) -> list[dict]:
    """Every status name valid for a project, defaults first then its extras.

    Order is deliberate and stable: the shipped names in their declared order, then
    extras oldest-first. An agent reading this list sees the same thing every time.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        rows = db.scalars(
            select(models.ItemStatus)
            .where(models.ItemStatus.project_id == project.id)
            .order_by(models.ItemStatus.id)
        ).all()
        out = [{"name": name, "behaves_as": cls} for name, cls in st.DEFAULTS.items()]
        out += [{"name": r.name, "behaves_as": r.behaves_as} for r in rows]
        return out


def add_status(slug: str, name: str, behaves_as: str) -> str:
    """Add one extra status name to a project. Returns an outcome, never raises.

    Outcomes: added · duplicate_name · unknown_class · invalid_name · unknown_project
    """
    name = name.strip().lower()
    if not name:
        return "invalid_name"
    if behaves_as not in st.CLASSES:
        return "unknown_class"
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return "unknown_project"
        if name in _vocabulary(db, project.id):
            # covers both "already a shipped default" and "already added here"
            return "duplicate_name"
        db.add(models.ItemStatus(project_id=project.id, name=name, behaves_as=behaves_as))
        db.commit()
        return "added"


def closed_names(slug: str) -> frozenset[str]:
    """The project's closed-class status names.

    Falls back to the shipped defaults for an unknown project rather than returning
    an empty set — an empty closed set would make every finished item look open.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return st.names_in(st.CLOSED)
        return st.names_in(st.CLOSED, extra=_vocabulary(db, project.id))


# ---- durable memory (links, notes, transcripts) ----

# Decisions deliberately absent: they belong in the project's `_decisions.md`, not the
# DB. The storage model routes by intent — the tool IS the destination — so accepting
# a decision here as well would give an agent two homes for one datum.
MEMORY_KINDS = frozenset({"link", "note", "transcript"})


def add_memory(slug: str, content: str, kind: str = "note", title: str | None = None,
               url: str | None = None) -> bool:
    if kind not in MEMORY_KINDS:
        hint = " — use `add_decision`, which writes to the project's `_decisions.md`" if kind == "decision" else ""
        raise ValueError(
            f"unsupported memory kind {kind!r}; expected one of "
            f"{', '.join(sorted(MEMORY_KINDS))}{hint}"
        )
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
