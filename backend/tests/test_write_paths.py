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
    assert result["valid"] == ["active", "closed", "open", "waiting"]


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
