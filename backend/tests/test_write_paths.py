"""The write paths, hardened before they are exposed over MCP.

Each test here pins a way an exception could otherwise escape a function whose
docstring promises an outcome — which, across the MCP boundary, means a traceback
reaching an agent instead of a `status` string it can act on.
"""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Write Paths")
    return temp_slug


# ---- add_status ----

def test_add_status_reports_added_as_a_dict(project):
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}


def test_add_status_reports_duplicate_as_a_dict(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.add_status(project, "parked", "waiting") == {"status": "duplicate_name"}


def test_add_status_hands_back_the_valid_classes(project):
    result = repository.add_status(project, "sideways", "diagonal")
    assert result["status"] == "unknown_class"
    assert result["valid"] == ["open", "active", "waiting", "closed"]


def test_add_status_reports_a_blank_name_as_a_dict(project):
    assert repository.add_status(project, "   ", "waiting") == {"status": "invalid_name"}


def test_add_status_reports_an_unknown_project_as_a_dict():
    assert repository.add_status("no-such-project-xyz", "parked", "waiting") == {
        "status": "unknown_project"
    }


def test_a_lost_race_still_reports_duplicate_name(project, monkeypatch):
    """Simulate the check-then-insert window: the pre-check passes, the insert collides.

    `add_status` checks the vocabulary and then inserts. Two concurrent callers can
    both pass the check, and the second insert then violates the UniqueConstraint.
    Here the window is forced deterministically by making the check blind to a name
    that really is present. Without the guard this raises IntegrityError — which,
    over MCP, is a traceback rather than an outcome.
    """
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}

    real_vocabulary = repository._vocabulary

    def blind_to_parked(db, project_id):
        vocabulary = dict(real_vocabulary(db, project_id))
        vocabulary.pop("parked", None)  # pretend the pre-check has not seen it
        return vocabulary

    monkeypatch.setattr(repository, "_vocabulary", blind_to_parked)

    assert repository.add_status(project, "parked", "waiting") == {"status": "duplicate_name"}


def test_the_session_is_usable_after_a_lost_race(project, monkeypatch):
    """The rollback must leave the database working, not a poisoned transaction."""
    repository.add_status(project, "parked", "waiting")
    real_vocabulary = repository._vocabulary
    monkeypatch.setattr(
        repository,
        "_vocabulary",
        lambda db, pid: {k: v for k, v in real_vocabulary(db, pid).items() if k != "parked"},
    )
    repository.add_status(project, "parked", "waiting")  # loses the race
    monkeypatch.undo()

    # a normal write still succeeds afterwards
    assert repository.add_status(project, "postponed", "waiting") == {"status": "added"}
    names = [row["name"] for row in repository.list_statuses(project)]
    assert "postponed" in names


# ---- create_folder ----

def test_create_folder_returns_the_new_id(project):
    result = repository.create_folder(project, "Bugs")
    assert result["status"] == "added"
    assert isinstance(result["folder_id"], int)


def test_create_folder_nests_under_a_parent_in_the_same_project(project):
    parent = repository.create_folder(project, "Bugs")["folder_id"]
    child = repository.create_folder(project, "Login", parent_id=parent)
    assert child["status"] == "added"


def test_create_folder_rejects_a_nonexistent_parent(project):
    """Unvalidated, this reached Postgres as a raw IntegrityError."""
    assert repository.create_folder(project, "Orphan", parent_id=999_999_999) == {
        "status": "unknown_parent"
    }


def test_create_folder_rejects_a_parent_from_another_project(project, temp_slug_b):
    """The FK proves the row EXISTS, never that it belongs here.

    Unvalidated, this silently nested a folder inside another project's tree —
    worse than a crash, because no error would ever reveal it.
    """
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Their Folder")["folder_id"]
    assert repository.create_folder(project, "Mine", parent_id=foreign) == {
        "status": "unknown_parent"
    }


def test_create_folder_reports_an_unknown_project():
    assert repository.create_folder("no-such-project-xyz", "Bugs") == {
        "status": "unknown_project"
    }


def test_create_folder_rejects_a_blank_name(project):
    assert repository.create_folder(project, "   ") == {"status": "invalid_name"}


def test_create_folder_rejects_a_name_longer_than_the_column(project):
    """Unguarded, this reached Postgres as a raw DataError — over MCP, a traceback."""
    assert repository.create_folder(project, "x" * (repository.MAX_FOLDER_NAME + 1)) == {
        "status": "invalid_name"
    }


def test_create_folder_accepts_a_name_at_the_length_limit(project):
    result = repository.create_folder(project, "x" * repository.MAX_FOLDER_NAME)
    assert result["status"] == "added"


def test_create_folder_appends_rather_than_prepending(project):
    first = repository.create_folder(project, "First")["folder_id"]
    second = repository.create_folder(project, "Second")["folder_id"]
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        a = db.scalar(select(models.Folder).where(models.Folder.id == first))
        b = db.scalar(select(models.Folder).where(models.Folder.id == second))
        assert a.position < b.position


# ---- add_item ----

def test_add_item_returns_the_new_id(project):
    result = repository.add_item(project, "Fix the login redirect loop")
    assert result["status"] == "added"
    assert isinstance(result["item_id"], int)


def test_add_item_defaults_to_todo(project):
    item_id = repository.add_item(project, "untouched")["item_id"]
    stored = [i for i in repository.list_items(project) if i["id"] == item_id][0]
    assert stored["status"] == "todo"


def test_add_item_accepts_a_starting_status(project):
    item_id = repository.add_item(project, "already going", status="doing")["item_id"]
    stored = [i for i in repository.list_items(project) if i["id"] == item_id][0]
    assert stored["status"] == "doing"


def test_add_item_accepts_a_status_the_project_added(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.add_item(project, "on hold", status="parked")["status"] == "added"


def test_add_item_rejects_an_unknown_status_and_hands_back_the_valid_set(project):
    result = repository.add_item(project, "bad", status="nonsense")
    assert result["status"] == "unknown_status"
    assert result["valid"] == ["todo", "doing", "blocked", "done"]


def test_add_item_files_into_a_folder_of_the_same_project(project):
    folder_id = repository.create_folder(project, "Bugs")["folder_id"]
    result = repository.add_item(project, "in a folder", folder_id=folder_id)
    assert result["status"] == "added"


def test_add_item_rejects_a_nonexistent_folder(project):
    """Unvalidated, this reached Postgres as a raw IntegrityError.

    `trackden add-item <p> "x" --folder 999` was a traceback before this change.
    """
    assert repository.add_item(project, "orphan", folder_id=999_999_999) == {
        "status": "unknown_folder"
    }


def test_add_item_rejects_a_folder_from_another_project(project, temp_slug_b):
    """The FK proves the row EXISTS, never that it belongs here.

    Unvalidated, the item was filed into another project's folder silently.
    """
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Their Folder")["folder_id"]
    assert repository.add_item(project, "mine", folder_id=foreign) == {
        "status": "unknown_folder"
    }


def test_add_item_reports_an_unknown_project():
    assert repository.add_item("no-such-project-xyz", "x") == {"status": "unknown_project"}


def test_add_item_appends_rather_than_prepending(project):
    """A new item must not jump ahead of work the user already ordered."""
    first = repository.add_item(project, "first")["item_id"]
    second = repository.add_item(project, "second")["item_id"]
    titles = [i["title"] for i in repository.list_items(project)]
    assert titles.index("first") < titles.index("second")


def test_the_first_item_in_an_empty_project_is_position_zero(project):
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    item_id = repository.add_item(project, "only")["item_id"]
    with SessionLocal() as db:
        item = db.scalar(select(models.Item).where(models.Item.id == item_id))
        assert item.position == 0


def test_add_item_appends_after_imported_items(project):
    """import_items assigns 0..n; an agent's item must land after them, not among them."""
    repository.import_items(
        project,
        [{"title": f"imported-{n}", "status": "todo", "folder": None} for n in range(3)],
    )
    repository.add_item(project, "agent-added")
    titles = [i["title"] for i in repository.list_items(project)]
    assert titles[-1] == "agent-added"
