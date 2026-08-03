"""The two B2 columns must reach a database that already has the tables.

`create_all` creates missing TABLES but never alters an existing one, so a column
added to a model would silently never arrive. The onboarding branch shipped exactly
that bug; this is the guard.
"""

import pytest

pytestmark = pytest.mark.db


def test_memory_has_a_path_column():
    from sqlalchemy import inspect

    from app.db import engine, init_db

    init_db()
    columns = {c["name"] for c in inspect(engine).get_columns("memory")}
    assert "path" in columns


def test_session_logs_has_an_item_id_column():
    from sqlalchemy import inspect

    from app.db import engine, init_db

    init_db()
    columns = {c["name"] for c in inspect(engine).get_columns("session_logs")}
    assert "item_id" in columns


def test_init_db_twice_keeps_a_stored_row(temp_slug):
    """Idempotency that proves DATA survives, not merely that the call does not raise.

    Uses the `note` kind, which already exists — the `file` kind arrives in Task 2, and
    a task must not end on a known failure.
    """
    from app import repository
    from app.db import init_db

    repository.create_project(temp_slug, name="Migration B2")
    repository.add_memory(temp_slug, "a finding", kind="note")
    init_db()
    init_db()
    assert [m["content"] for m in repository.list_memory(temp_slug)] == ["a finding"]
