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
