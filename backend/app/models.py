"""Phase 4 — the core schema.

    projects → folders (nestable) → items          (the work map)
    projects → sessions → session_logs             (what happened, per session)
    projects → memory                              (durable facts: decisions, links, notes)

This is Trackden's single source of truth. All doors (MCP, CLI, web) read
and write these tables; nothing lives in local files. Terminology is
domain-agnostic — an "item" is a ticket (IT), a bill (accounting), a deliverable
(design); the schema stays generic.
"""

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

EMBED_DIM = 384  # bge-small-en-v1.5 (see embeddings.py)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """A high-level thing the user works on (a client project or a personal one)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="personal")  # personal | client
    client: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    folders: Mapped[list["Folder"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memory: Mapped[list["Memory"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Folder(Base):
    """A grouping inside a project. Nestable via parent_id (folders → sub-folders)."""

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="folders")
    children: Mapped[list["Folder"]] = relationship()
    items: Mapped[list["Item"]] = relationship(back_populates="folder")


class Item(Base):
    """A unit of work in a project — generic: a ticket, a bill, a deliverable, …

    Optionally lives in a folder; otherwise sits directly under the project.
    (Table name kept as `tracking_items` — the generic term stays 'item'.)
    """

    __tablename__ = "tracking_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo | doing | done
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="items")
    folder: Mapped["Folder | None"] = relationship(back_populates="items")


class Session(Base):
    """One work session on a project (keyed by the agent's thread_id)."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="sessions")
    logs: Mapped[list["SessionLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionLog(Base):
    """A single entry in a session — a note, a step taken, a summary, a plan.

    (pgvector embedding column gets added here in Phase 8 for RAG over logs.)
    """

    __tablename__ = "session_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note | step | summary | plan
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["Session"] = relationship(back_populates="logs")


class Memory(Base):
    """Durable, concrete memory for a project — decisions, repo links, notes,
    meeting/decision transcripts. This is what gives agents continuity across
    sessions. Optionally scoped to a folder or item."""

    __tablename__ = "memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("tracking_items.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="note")  # decision | link | note | transcript
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # e.g. GitLab/GitHub link
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="memory")
