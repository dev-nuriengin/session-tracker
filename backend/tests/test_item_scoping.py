"""Session logs that attach to an item — and the session lookup that ignored the project."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Item Scoping")
    return temp_slug


def test_a_log_attaches_to_an_item(project):
    item_id = repository.add_item(project, "Fix the login redirect")["item_id"]
    assert repository.add_session_log(
        project, "t1", "Safari only, cookie SameSite", item_id=item_id
    ) == {"status": "saved"}


def test_a_log_rejects_an_item_from_another_project(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.add_session_log(project, "t1", "x", item_id=foreign) == {
        "status": "unknown_item"
    }


def test_a_project_level_log_still_works(project):
    assert repository.add_session_log(project, "t1", "general progress") == {"status": "saved"}


def test_an_unknown_project_is_reported(project):
    assert repository.add_session_log("no-such-project-xyz", "t1", "x") == {
        "status": "unknown_project"
    }


def test_two_projects_sharing_a_thread_id_keep_separate_logs(project, temp_slug_b):
    """THE BUG: the session lookup filtered on thread_id alone, ignoring the project.

    The CLI's --thread defaults to "cli" for every project, so
    `trackden log project-a "..."` then `trackden log project-b "..."` filed B's note
    into A's history, and `get_history project-b` never showed it.
    """
    repository.create_project(temp_slug_b, name="Other")

    repository.add_session_log(project, "cli", "note about A")
    repository.add_session_log(temp_slug_b, "cli", "note about B")

    a_logs = [entry["content"] for entry in repository.get_history(project)["recent_logs"]]
    b_logs = [entry["content"] for entry in repository.get_history(temp_slug_b)["recent_logs"]]

    assert "note about A" in a_logs
    assert "note about B" not in a_logs
    assert "note about B" in b_logs
    assert "note about A" not in b_logs
