"""Phase 4 — data-access layer over the core schema.

The rest of the app (tools, graph, endpoints, later the MCP server) calls these
functions; nobody else opens a SQLAlchemy session. This is the seam that makes
the tracker "do all the job" — real DB reads/writes live here, not a stub dict.
"""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import models, playbook, statuses as st
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
    """Short status string for a project: its next offerable item.

    Queue: "what should I do next", not "what exists". A queue offers anything
    that is not `waiting` and not `closed` — so an item someone is already on
    counts as the next step, and so does a status this vocabulary cannot
    classify (offered on purpose, so a human notices and fixes it). Waiting
    items (blocked, parked, …) are skipped but reported — that is what stops a
    stalled item from blocking the queue for ever.
    Returns '' if the project is unknown.
    """
    with SessionLocal() as db:
        project = db.scalar(
            select(models.Project).where(models.Project.slug == slug.strip().lower())
        )
        if project is None:
            return ""
        vocabulary = _vocabulary(db, project.id)
        not_offerable = st.names_in(st.WAITING, st.CLOSED, extra=vocabulary)
        waiting = st.names_in(st.WAITING, extra=vocabulary)

        nxt = db.scalar(
            select(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.notin_(not_offerable))
            .order_by(models.Item.position, models.Item.id)
        )
        waiting_count = db.scalar(
            select(func.count()).select_from(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(waiting))
        ) or 0
        tail = f"  ({waiting_count} waiting)" if waiting_count else ""

        if nxt is None:
            return f"{project.name}: all items done.{tail}"
        return f"{project.name}: NEXT — {nxt.title}{tail}"


def overview(slug: str, include_playbook: bool = False) -> dict:
    """The cheap FIRST look — a compact summary, not a full dump. Counts + a few
    titles + last activity + the valid status vocabulary. Drill deeper with
    list_items / list_memory / get_history.

    Queue: its `next`/`open_preview` are "what to do next", not an inventory of
    everything on the list — anything not `waiting` and not `closed` qualifies,
    including a status this vocabulary cannot classify (offered on purpose).

    `include_playbook` gates the `playbook` key. It defaults to False because the
    CLI and the FastAPI endpoint (`GET /projects/{slug}`) share this payload with
    the web UI, which has no use for agent-steering prose — the digest is meant
    for the agent door only. The MCP `overview` tool passes True.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {}
        vocabulary = _vocabulary(db, project.id)
        not_offerable = st.names_in(st.WAITING, st.CLOSED, extra=vocabulary)
        waiting = st.names_in(st.WAITING, extra=vocabulary)

        open_titles = db.scalars(
            select(models.Item.title)
            .where(models.Item.project_id == project.id, models.Item.status.notin_(not_offerable))
            .order_by(models.Item.position, models.Item.id)
        ).all()
        waiting_count = db.scalar(
            select(func.count()).select_from(models.Item)
            .where(models.Item.project_id == project.id, models.Item.status.in_(waiting))
        )
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
        result = {
            "project": project.slug,
            "next": open_titles[0] if open_titles else None,
            "open_items": len(open_titles),
            "open_preview": list(open_titles[:3]),  # a taste, not all of them
            "waiting_items": waiting_count or 0,
            "memory_entries": mem_count or 0,
            "last_activity": last_log,
            # the valid vocabulary travels with the summary, so a caller never has
            # to guess a status name — and never needs a second round trip to check
            "statuses": [{"name": n, "behaves_as": c} for n, c in vocabulary.items()],
        }
        if include_playbook:
            # The rules ride in the payload an agent already fetches: it cannot be relied
            # on to call get_playbook() for them. Steering, not a guarantee — the
            # guarantee is a SessionStart hook, which is a separate increment. Opt-in
            # only: the web UI polls this same shape and has no use for agent prose.
            result["playbook"] = {"version": playbook.VERSION, "digest": playbook.DIGEST}
        return result


def list_items(slug: str, include_done: bool = False) -> list[dict]:
    """Drill-down: all items for a project (open only unless include_done).

    Inventory: everything not closed, so stalled work stays discoverable. "Open"
    here means "not in the closed class" — so `waiting` items still show up (you
    need to see what stalled), and a project's own closed name like `dropped` is
    hidden just as `done` is. An unrecognised stored status counts as open: an
    item we cannot classify must stay visible rather than vanish.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return []
        q = select(models.Item).where(models.Item.project_id == project.id)
        if not include_done:
            closed = st.names_in(st.CLOSED, extra=_vocabulary(db, project.id))
            q = q.where(models.Item.status.notin_(closed))
        rows = db.scalars(q.order_by(models.Item.position, models.Item.id)).all()
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

def _next_position(db, model, project_id: int) -> int:
    """One past the highest `position` in this project, or 0 when it is empty.

    An explicit `is None` check, not `or` — position 0 is falsy, so `max or 0` would
    collapse the second row back onto the first and reintroduce the queue-jumping bug
    this exists to prevent.
    """
    highest = db.scalar(
        select(func.max(model.position)).where(model.project_id == project_id)
    )
    return 0 if highest is None else highest + 1


def _owned(db, model, id_: int, project_id: int):
    """The row with this id IF it belongs to this project, else None.

    A ForeignKey proves a row exists; it never proves the row belongs here. Every
    caller-supplied id goes through this, so a caller cannot reach into another
    project's items or folders — the rule the whole write layer is built on.
    """
    return db.scalar(
        select(model).where(model.id == id_, model.project_id == project_id)
    )


def create_folder(slug: str, name: str, parent_id: int | None = None) -> dict:
    """Create a folder in a project. Returns an outcome, never raises.

    Outcomes: added (with `folder_id`) · invalid_name · unknown_parent · unknown_project

    `invalid_name` covers both a blank name and one longer than the column allows
    (MAX_FOLDER_NAME) — an unvalidated long name would otherwise reach Postgres as a
    raw DataError instead of a reported outcome. Checked FIRST, before opening a
    session, same as `add_status` validates cheaply before touching the database.

    `parent_id` is validated against THIS project. The ForeignKey alone only proves
    the row exists, not that it belongs here, so without this check a caller could
    nest a folder inside another project's tree — silently, with no error to reveal it.

    The new folder is appended after every existing folder in the project (by
    `position`), never inserted at the front — see `add_item` for why that matters.
    """
    name = name.strip()
    if not name or len(name) > MAX_FOLDER_NAME:
        return {"status": "invalid_name"}
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}
        if parent_id is not None:
            if _owned(db, models.Folder, parent_id, project.id) is None:
                return {"status": "unknown_parent"}
        position = _next_position(db, models.Folder, project.id)
        folder = models.Folder(project_id=project.id, name=name, parent_id=parent_id, position=position)
        db.add(folder)
        db.commit()
        return {"status": "added", "folder_id": folder.id}


def add_item(slug: str, title: str, folder_id: int | None = None,
             status: str | None = None) -> dict:
    """Create a work item in a project. Returns an outcome, never raises.

    Outcomes: added (with `item_id`) · unknown_folder · unknown_status (with `valid`) ·
    unknown_project

    NOTE two senses of one word: the `status` PARAMETER is the item's state, while the
    returned `status` KEY is the outcome of this call. The parameter keeps the domain
    word and the key keeps the shape eight sibling functions share.

    `folder_id` is validated against THIS project. The ForeignKey alone only proves the
    row exists, not that it belongs here, so without this check an item could be filed
    into another project's folder — silently. `status` defaults to the shipped `todo`.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if folder_id is not None:
            if _owned(db, models.Folder, folder_id, project.id) is None:
                return {"status": "unknown_folder"}

        if status is None:
            name = st.TODO
        else:
            name = status.strip().lower()
            vocabulary = _vocabulary(db, project.id)
            if name not in vocabulary:
                return {"status": "unknown_status", "valid": list(vocabulary)}

        # Append, never prepend: `import_items` assigns 0..n and queues order by
        # (position, id), so a new item at position 0 would jump ahead of work the
        # user already sequenced. One past the current max keeps it last; an empty
        # project (no rows yet) yields position 0. Computed across the WHOLE project,
        # not per folder — two folders sharing one position would make ordering
        # ambiguous again.
        position = _next_position(db, models.Item, project.id)

        item = models.Item(
            project_id=project.id, folder_id=folder_id, title=title, status=name, position=position
        )
        db.add(item)
        db.commit()
        return {"status": "added", "item_id": item.id}


# ---- the status vocabulary ----

# Must match models.ItemStatus.name's column width: a name longer than this must
# be rejected as `invalid_name` here, before it ever reaches Postgres as a DataError.
MAX_STATUS_NAME = 20

# Must match models.Folder.name's column width (models.py): a name longer than
# this must be rejected as `invalid_name` here, before it ever reaches Postgres
# as a DataError — same defect class as MAX_STATUS_NAME above, same fix.
MAX_FOLDER_NAME = 200

# Must match models.Memory.path's column width (models.py): a resolved path longer
# than this must be rejected as `invalid_path` here, before it ever reaches Postgres
# as a DataError — same defect class as MAX_STATUS_NAME and MAX_FOLDER_NAME above,
# same fix.
MAX_PATH = 500


def _vocabulary(db, project_id: int) -> dict[str, str]:
    """The resolved status vocabulary for one project: defaults + its extras.

    Takes an open session because every caller already has one — this is the hot
    path for the "open item" queries and must not open a second connection.
    """
    extras = {
        row.name: row.behaves_as
        for row in db.scalars(
            select(models.ItemStatus)
            .where(models.ItemStatus.project_id == project_id)
            .order_by(models.ItemStatus.id)
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


def add_status(slug: str, name: str, behaves_as: str) -> dict:
    """Add one extra status name to a project. Returns an outcome, never raises.

    Outcomes: added · duplicate_name · unknown_class (with `valid`) · invalid_name ·
    unknown_project. `invalid_name` covers both a blank name and one longer than the
    column allows (MAX_STATUS_NAME) — an unvalidated long name would otherwise reach
    Postgres as a raw DataError instead of a reported outcome.

    The duplicate check is belt AND braces: the pre-check gives a clean outcome in the
    normal case, and the UniqueConstraint catches the check-then-insert race two
    concurrent writers can lose. Both report `duplicate_name`, so a caller sees one
    behaviour and never an IntegrityError — which over MCP would be a traceback.
    """
    name = name.strip().lower()
    if not name or len(name) > MAX_STATUS_NAME:
        return {"status": "invalid_name"}
    if behaves_as not in st.CLASSES:
        return {"status": "unknown_class", "valid": list(st.CLASS_ORDER)}
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}
        if name in _vocabulary(db, project.id):
            # covers both "already a shipped default" and "already added here"
            return {"status": "duplicate_name"}
        db.add(models.ItemStatus(project_id=project.id, name=name, behaves_as=behaves_as))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # leave the session usable, not a poisoned transaction
            return {"status": "duplicate_name"}
        return {"status": "added"}


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


def set_status(slug: str, item_id: int, status: str) -> dict:
    """Move one item to a new status. Returns an outcome dict, never raises.

    Deliberately NOT a state machine: any valid name may follow any other, including
    reopening a closed item. The moment Trackden refuses a transition it stops being
    memory and starts being an agent. Whether to ASK before closing something is
    guidance for the caller, not a check here.

    Always reports `from` and `to`, so a caller whose item was moved by another
    session sees it instead of assuming.
    """
    status = status.strip().lower()
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        vocabulary = _vocabulary(db, project.id)
        if status not in vocabulary:
            return {"status": "unknown_status", "valid": list(vocabulary)}

        item = db.scalar(
            select(models.Item).where(
                models.Item.id == item_id, models.Item.project_id == project.id
            )
        )
        if item is None:
            return {"status": "unknown_item"}

        previous = item.status
        if previous == status:
            return {"status": "unchanged", "from": previous, "to": status}

        item.status = status
        db.commit()
        return {"status": "set", "from": previous, "to": status}


# ---- durable memory (links, notes, transcripts, files) ----

# `file` points at a local artifact — a findings file, a meeting recording, an HTML
# dump. Decisions remain deliberately absent: they belong in the project's
# `_decisions.md`, and the storage model routes by intent, so accepting one here
# would give an agent two homes for one datum.
MEMORY_KINDS = frozenset({"link", "note", "transcript", "file"})


def add_memory(slug: str, content: str, kind: str = "note", title: str | None = None,
               url: str | None = None, path: str | None = None,
               item_id: int | None = None, folder_id: int | None = None) -> dict:
    """Save a durable fact to a project's memory. Returns an outcome, never raises.

    Outcomes: saved (optionally with `warning`) · invalid_path · missing_path ·
    rejected_kind (with `valid` and a `message`) · unknown_item · unknown_folder ·
    unknown_project

    `item_id` scopes the fact to one item, so a bug's findings stop sitting in a pile
    with every other bug's. It is validated against THIS project: a ForeignKey proves
    a row exists, never that it belongs here.

    `kind="file"` requires `path` and stores it expanded and absolute, so the pointer
    survives a different working directory. A path that does not exist is stored WITH
    a warning rather than refused — the user may be recording where something is about
    to go. Trackden never creates, moves or reads the file. A resolved path longer
    than the column allows (MAX_PATH) is rejected as `invalid_path`, checked before
    the session opens — same defect class MAX_STATUS_NAME/MAX_FOLDER_NAME guard
    against elsewhere.
    """
    if kind not in MEMORY_KINDS:
        hint = (
            " — use `add_decision`, which writes to the project's `_decisions.md`"
            if kind == "decision" else ""
        )
        return {
            "status": "rejected_kind",
            "valid": sorted(MEMORY_KINDS),
            "message": (
                f"unsupported memory kind {kind!r}; expected one of "
                f"{', '.join(sorted(MEMORY_KINDS))}{hint}"
            ),
        }
    if kind == "file" and not path:
        return {"status": "missing_path"}

    resolved = None
    warning = None
    if path:
        candidate = Path(path).expanduser()
        resolved = str(candidate.resolve())
        if len(resolved) > MAX_PATH:
            return {"status": "invalid_path"}
        try:
            # Path.exists() only swallows ENOENT/ENOTDIR/EBADF/ELOOP itself; a path
            # with an over-length component (ENAMETOOLONG) or one this process
            # cannot traverse (EACCES) still raises straight through it. Both are
            # "can't confirm it exists", not a reason for add_memory to raise past
            # the MCP boundary — treat either the same as "not found".
            found = candidate.exists()
        except OSError:
            found = False
        if not found:
            warning = "path not found"

    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if item_id is not None:
            if _owned(db, models.Item, item_id, project.id) is None:
                return {"status": "unknown_item"}

        if folder_id is not None:
            if _owned(db, models.Folder, folder_id, project.id) is None:
                return {"status": "unknown_folder"}

        db.add(models.Memory(
            project_id=project.id, item_id=item_id, folder_id=folder_id,
            content=content, kind=kind, title=title, url=url, path=resolved,
        ))
        db.commit()
        return {"status": "saved", "warning": warning} if warning else {"status": "saved"}


def _memory_row(m: models.Memory) -> dict:
    """One memory row, shaped the way every caller gets it.

    `list_memory` and `get_history`'s item-scoped branch both hand-built this same
    dict; extracted so the next key (as `path`/`item_id` were) is added once, not
    twice.
    """
    return {
        "kind": m.kind, "title": m.title, "content": m.content, "url": m.url,
        "path": m.path, "item_id": m.item_id,
    }


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
        return [_memory_row(m) for m in rows]


# ---- sessions & continuity ----

def add_session_log(slug: str, thread_id: str, content: str, kind: str = "note",
                    item_id: int | None = None) -> dict:
    """Save a session log entry, creating the session on first use. Never raises.

    Outcomes: saved · unknown_item · unknown_project

    The session is looked up by thread_id AND project. It used to be thread_id alone,
    which meant two projects using the same thread id — and the CLI defaults every
    project to "cli" — shared one session, so a log filed into whichever project got
    there first and never appeared in the other's history.

    `item_id` scopes the entry to one item and is validated against THIS project.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {"status": "unknown_project"}

        if item_id is not None:
            if _owned(db, models.Item, item_id, project.id) is None:
                return {"status": "unknown_item"}

        session = db.scalar(
            select(models.Session).where(
                models.Session.thread_id == thread_id,
                models.Session.project_id == project.id,
            )
        )
        if session is None:
            session = models.Session(project_id=project.id, thread_id=thread_id)
            db.add(session)
            db.flush()

        db.add(models.SessionLog(
            session_id=session.id, item_id=item_id, content=content,
            kind=kind, embedding=embed(content),
        ))
        db.commit()
        return {"status": "saved"}


def search_logs(query: str, limit: int = 5) -> list[dict]:
    """Semantic search across ALL projects' session logs (local embeddings + pgvector).
    Returns the closest log entries with their project + a similarity score.
    Each hit carries `item_id` (None for a project-level log) so a hit can be
    followed into `get_history(item_id=...)` for that item's whole story."""
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
            {
                "project": slug, "kind": log.kind, "content": log.content,
                "score": round(1 - dist, 3), "item_id": log.item_id,
            }
            for log, slug, dist in rows
        ]


def get_history(slug: str, limit: int = 10, item_id: int | None = None) -> dict:
    """Continuity payload for a new session — 'pull the history first'.

    Inventory: everything not closed, so stalled work stays discoverable — a
    `waiting` item still appears here even though it would never be offered as
    NEXT. Returns the project's not-closed items, recent memory, and recent
    session logs.

    Pass `item_id` when resuming work on ONE item (a bug, a ticket) instead of the
    whole project: every part of the payload narrows to that item — `open_items`
    holds just its title (or is empty when it is closed), `memory` only its memory,
    `recent_logs` only its logs — and an `item` block names its title and current
    status, so a caller knows what it is looking at. `item_id` is validated
    against THIS project (ownership, not mere existence).

    Returns `{}` for an unknown project (unchanged) and `{"status": "unknown_item"}`
    when `item_id` does not belong here — a deliberate asymmetry: the unknown-project
    contract is relied on by every existing caller and stays as-is.
    """
    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug.strip().lower()))
        if project is None:
            return {}

        item = None
        if item_id is not None:
            item = _owned(db, models.Item, item_id, project.id)
            if item is None:
                return {"status": "unknown_item"}

        closed = st.names_in(st.CLOSED, extra=_vocabulary(db, project.id))

        if item is not None:
            open_items = [item.title] if item.status not in closed else []
            memory_rows = db.scalars(
                select(models.Memory)
                .where(models.Memory.project_id == project.id, models.Memory.item_id == item_id)
                .order_by(models.Memory.created_at.desc())
            ).all()
            memory = [_memory_row(m) for m in memory_rows]
        else:
            open_items_rows = db.scalars(
                select(models.Item)
                .where(models.Item.project_id == project.id, models.Item.status.notin_(closed))
                .order_by(models.Item.position, models.Item.id)
            ).all()
            open_items = [i.title for i in open_items_rows]
            memory = list_memory(slug)

        logs_query = (
            select(models.SessionLog)
            .join(models.Session)
            .where(models.Session.project_id == project.id)
        )
        if item is not None:
            logs_query = logs_query.where(models.SessionLog.item_id == item_id)
        recent_logs = db.scalars(
            logs_query.order_by(models.SessionLog.created_at.desc()).limit(limit)
        ).all()

        payload = {
            "project": project.slug,
            "open_items": open_items,
            "memory": memory,
            "recent_logs": [{"kind": l.kind, "content": l.content} for l in recent_logs],
        }
        if item is not None:
            payload["item"] = {"title": item.title, "status": item.status}
        return payload


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
