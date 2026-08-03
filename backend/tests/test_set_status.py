"""Changing an item's status — the loop this whole stage exists to unblock."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def item(temp_slug):
    repository.create_project(temp_slug, name="Set Status Test")
    item_id = repository.add_item(temp_slug, "Fix the login redirect loop")["item_id"]
    return temp_slug, item_id


def test_a_new_item_starts_as_todo(item):
    slug, item_id = item
    assert [i for i in repository.list_items(slug) if i["id"] == item_id][0]["status"] == "todo"


def test_setting_a_status_reports_from_and_to(item):
    slug, item_id = item
    assert repository.set_status(slug, item_id, "doing") == {
        "status": "set",
        "from": "todo",
        "to": "doing",
    }


def test_the_change_persists(item):
    slug, item_id = item
    repository.set_status(slug, item_id, "doing")
    stored = [i for i in repository.list_items(slug) if i["id"] == item_id][0]
    assert stored["status"] == "doing"


def test_setting_the_same_status_twice_is_unchanged_not_a_fake_success(item):
    slug, item_id = item
    repository.set_status(slug, item_id, "doing")
    assert repository.set_status(slug, item_id, "doing") == {
        "status": "unchanged",
        "from": "doing",
        "to": "doing",
    }


def test_an_unknown_name_is_refused_and_hands_back_the_valid_set(item):
    slug, item_id = item
    result = repository.set_status(slug, item_id, "parked")
    assert result["status"] == "unknown_status"
    assert result["valid"] == ["todo", "doing", "blocked", "done"]


def test_a_name_the_project_added_becomes_usable(item):
    slug, item_id = item
    repository.add_status(slug, "parked", "waiting")
    assert repository.set_status(slug, item_id, "parked")["status"] == "set"


def test_a_name_added_to_ANOTHER_project_stays_unusable(item, temp_slug_b):
    slug, item_id = item
    repository.create_project(temp_slug_b, name="Other")
    repository.add_status(temp_slug_b, "parked", "waiting")
    assert repository.set_status(slug, item_id, "parked")["status"] == "unknown_status"


def test_an_unknown_item_is_reported(item):
    slug, _ = item
    assert repository.set_status(slug, 999_999_999, "doing") == {"status": "unknown_item"}


def test_an_item_belonging_to_another_project_is_not_reachable(item, temp_slug_b):
    slug, item_id = item
    repository.create_project(temp_slug_b, name="Other")
    # the item exists, but not under temp_slug_b
    assert repository.set_status(temp_slug_b, item_id, "doing") == {"status": "unknown_item"}


def test_an_unknown_project_is_reported():
    assert repository.set_status("no-such-project-xyz", 1, "doing") == {"status": "unknown_project"}


def test_a_status_is_normalised_before_matching(item):
    slug, item_id = item
    assert repository.set_status(slug, item_id, "  DOING  ")["status"] == "set"


def test_any_transition_is_allowed_because_trackden_never_gates(item):
    # closing then reopening is the user's business, not the tracker's
    slug, item_id = item
    repository.set_status(slug, item_id, "done")
    assert repository.set_status(slug, item_id, "todo") == {
        "status": "set",
        "from": "done",
        "to": "todo",
    }
