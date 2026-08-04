"""Removing a project — the only irreversible operation in the product.

The ordering these tests pin was reproduced as a real FK violation during Stage B2,
not theorised: Memory and SessionLog carry FK columns to items/folders with NO ORM
relationship, so `db.delete(project)` alone can delete a referenced item first.
"""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def loaded(temp_slug):
    """A project carrying one of everything, so the delete has to order itself."""
    repository.create_project(temp_slug, name="Delete Me")
    repository.add_status(temp_slug, "parked", "waiting")
    folder_id = repository.create_folder(temp_slug, "Bugs")["folder_id"]
    item_id = repository.add_item(temp_slug, "BUG-1", folder_id=folder_id)["item_id"]
    repository.add_memory(temp_slug, "a finding", item_id=item_id)
    repository.add_memory(temp_slug, "a folder note", folder_id=folder_id)
    repository.add_memory(temp_slug, "a project note")
    repository.add_session_log(temp_slug, "t1", "worked on the bug", item_id=item_id)
    repository.add_session_log(temp_slug, "t1", "general progress")
    return temp_slug, item_id, folder_id


# ---- project_counts ----

def test_counts_report_everything_attached(loaded):
    slug, _, _ = loaded
    counts = repository.project_counts(slug)
    assert counts["status"] == "counted"
    assert counts["items"] == 1
    assert counts["folders"] == 1
    assert counts["memory"] == 3
    assert counts["sessions"] == 1
    assert counts["logs"] == 2
    assert counts["statuses"] == 1


def test_counts_on_an_unknown_project(loaded):
    assert repository.project_counts("no-such-project-xyz") == {"status": "unknown_project"}


def test_counts_are_zero_for_an_empty_project(temp_slug):
    repository.create_project(temp_slug, name="Empty")
    counts = repository.project_counts(temp_slug)
    assert counts["status"] == "counted"
    assert (counts["items"], counts["folders"], counts["memory"]) == (0, 0, 0)


# ---- delete_project ----

def test_delete_removes_the_project(loaded):
    slug, _, _ = loaded
    assert repository.delete_project(slug)["status"] == "deleted"
    assert slug not in repository.list_projects()


def test_delete_reports_what_it_removed(loaded):
    slug, _, _ = loaded
    removed = repository.delete_project(slug)["removed"]
    assert removed["items"] == 1
    assert removed["memory"] == 3
    assert removed["logs"] == 2


def test_delete_leaves_no_orphans(loaded):
    """The FK ordering, pinned. Without it this raises IntegrityError."""
    from sqlalchemy import func, select

    from app import models
    from app.db import SessionLocal

    slug, item_id, folder_id = loaded
    repository.delete_project(slug)

    with SessionLocal() as db:
        for model, column, value in (
            (models.Memory, models.Memory.item_id, item_id),
            (models.Memory, models.Memory.folder_id, folder_id),
            (models.SessionLog, models.SessionLog.item_id, item_id),
            (models.Item, models.Item.id, item_id),
            (models.Folder, models.Folder.id, folder_id),
        ):
            leftover = db.scalar(
                select(func.count()).select_from(model).where(column == value)
            )
            assert leftover == 0, f"{model.__name__} rows survived the delete"


def test_delete_an_unknown_project_reports_it():
    assert repository.delete_project("no-such-project-xyz") == {"status": "unknown_project"}


def test_delete_is_idempotent_in_effect(loaded):
    """A second delete is an honest miss, not a crash."""
    slug, _, _ = loaded
    assert repository.delete_project(slug)["status"] == "deleted"
    assert repository.delete_project(slug) == {"status": "unknown_project"}


def test_delete_does_not_touch_another_project(loaded, temp_slug_b):
    slug, _, _ = loaded
    repository.create_project(temp_slug_b, name="Survivor")
    survivor_item = repository.add_item(temp_slug_b, "keep me")["item_id"]
    repository.add_memory(temp_slug_b, "keep this too", item_id=survivor_item)

    repository.delete_project(slug)

    assert temp_slug_b in repository.list_projects()
    assert repository.project_counts(temp_slug_b)["memory"] == 1
