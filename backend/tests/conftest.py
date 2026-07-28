"""Shared test fixtures.

Onboarding's logic is deliberately pure — text in/out, and a filesystem layer whose
base path is injectable — so nearly all of it tests with no Postgres. The few tests
that DO need the DB are marked `@pytest.mark.db` and auto-skip when it is unreachable,
so `uv run pytest` stays green with docker down.
"""

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated ~/.trackden for one test. Never touches the real home."""
    workspace = tmp_path / ".trackden"
    monkeypatch.setenv("TRACKDEN_HOME", str(workspace))
    return workspace


@pytest.fixture
def temp_slug():
    """A project slug that is deleted from the real DB afterwards (db-marked tests)."""
    slug = "pytest-onboard-tmp"
    yield slug
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        project = db.scalar(select(models.Project).where(models.Project.slug == slug))
        if project is not None:
            db.delete(project)  # cascades to folders / items / sessions / memory
            db.commit()


def _db_reachable() -> bool:
    try:
        from app.db import engine

        with engine.connect():
            return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if _db_reachable():
        return
    skip = pytest.mark.skip(reason="Postgres not reachable — run `docker compose up -d`")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)
