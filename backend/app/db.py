"""Phase 4 — the Postgres core (single source of truth): engine + session + Base.

Sync SQLAlchemy 2.0 to match the rest of the (sync) codebase — FastAPI endpoints
are `def` and graph nodes are sync, so a sync engine plugs in everywhere with no
async/await plumbing.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://session:session@localhost:5433/session_tracker",
)
# ensure the psycopg (v3) driver even if .env uses the bare postgresql:// scheme
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Base class all ORM models inherit from."""


def init_db() -> None:
    """Create tables if they don't exist (dev convenience; real migrations later)."""
    from . import models  # noqa: F401 — import registers the models on Base.metadata

    Base.metadata.create_all(engine)
