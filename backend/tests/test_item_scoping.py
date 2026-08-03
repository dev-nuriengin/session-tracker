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


# ---- get_history(item_id=...) ----

@pytest.fixture
def bug(project):
    """One bug with its own findings, beside an unrelated item with its own."""
    bug_id = repository.add_item(project, "BUG-431 login redirect loops")["item_id"]
    other_id = repository.add_item(project, "unrelated chore")["item_id"]

    repository.add_session_log(project, "t1", "reproduced on Safari", item_id=bug_id)
    repository.add_session_log(project, "t1", "cookie SameSite is the cause", item_id=bug_id)
    repository.add_session_log(project, "t1", "swept the logs", item_id=other_id)
    repository.add_session_log(project, "t1", "project-level note")

    repository.add_memory(project, "First findings", kind="file",
                          path="/tmp/trackden-b2-findings.md", item_id=bug_id)
    repository.add_memory(project, "unrelated link", kind="link", item_id=other_id)
    return project, bug_id, other_id


def test_item_history_holds_only_that_items_logs(bug):
    slug, bug_id, _ = bug
    contents = [e["content"] for e in repository.get_history(slug, item_id=bug_id)["recent_logs"]]
    assert "reproduced on Safari" in contents
    assert "cookie SameSite is the cause" in contents
    assert "swept the logs" not in contents
    assert "project-level note" not in contents


def test_item_history_holds_only_that_items_memory(bug):
    slug, bug_id, _ = bug
    memory = repository.get_history(slug, item_id=bug_id)["memory"]
    assert [m["content"] for m in memory] == ["First findings"]
    assert memory[0]["path"].endswith("trackden-b2-findings.md")


def test_item_history_names_the_item_it_is_about(bug):
    slug, bug_id, _ = bug
    payload = repository.get_history(slug, item_id=bug_id)
    assert payload["item"]["title"] == "BUG-431 login redirect loops"
    assert payload["item"]["status"] == "todo"


def test_project_history_is_unchanged_without_an_item_id(bug):
    slug, _, _ = bug
    contents = [e["content"] for e in repository.get_history(slug)["recent_logs"]]
    assert "project-level note" in contents
    assert "swept the logs" in contents


def test_item_history_rejects_an_item_from_another_project(bug, temp_slug_b):
    slug, _, _ = bug
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.get_history(slug, item_id=foreign) == {"status": "unknown_item"}


def test_a_closed_item_still_returns_its_history(bug):
    """Resuming a finished bug must still show what happened."""
    slug, bug_id, _ = bug
    repository.set_status(slug, bug_id, "done")
    payload = repository.get_history(slug, item_id=bug_id)
    assert payload["item"]["status"] == "done"
    assert len(payload["recent_logs"]) == 2
