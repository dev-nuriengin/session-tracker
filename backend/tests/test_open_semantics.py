"""What counts as "open" — the four queries that used to hard-code != "done".

The bug this guards: a stuck item sat in a non-done status for ever and kept
blocking the queue, so whats_next returned the same thing indefinitely at BOTH
ends — nothing could be closed, and nothing could be set aside.
"""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    """One project holding one item per class, in a known order."""
    repository.create_project(temp_slug, name="Open Semantics")
    repository.add_status(temp_slug, "parked", "waiting")
    repository.add_status(temp_slug, "dropped", "closed")
    ids = {}
    for name in ("todo", "doing", "blocked", "parked", "done", "dropped"):
        item_id = repository.add_item(temp_slug, f"item-{name}")
        repository.set_status(temp_slug, item_id, name)
        ids[name] = item_id
    return temp_slug, ids


# ---- list_items ----

def test_list_items_hides_every_closed_name_not_just_done(project):
    slug, _ = project
    titles = {i["title"] for i in repository.list_items(slug)}
    assert "item-dropped" not in titles   # the bug: only "done" was hidden
    assert "item-done" not in titles


def test_list_items_still_shows_waiting_items(project):
    slug, _ = project
    titles = {i["title"] for i in repository.list_items(slug)}
    assert {"item-blocked", "item-parked"} <= titles


def test_list_items_with_include_done_shows_everything(project):
    slug, ids = project
    assert len(repository.list_items(slug, include_done=True)) == len(ids)


# ---- get_status / the NEXT step ----

def test_next_is_the_first_actionable_item(project):
    slug, _ = project
    assert "item-todo" in repository.get_status(slug)


def test_next_skips_waiting_items(project):
    slug, ids = project
    for name in ("todo", "doing"):
        repository.set_status(slug, ids[name], "done")
    result = repository.get_status(slug)
    # blocked and parked remain, but neither is offered as the next step
    assert "item-blocked" not in result
    assert "item-parked" not in result


def test_next_reports_how_many_are_waiting(project):
    slug, ids = project
    for name in ("todo", "doing"):
        repository.set_status(slug, ids[name], "done")
    assert "2 waiting" in repository.get_status(slug)


def test_an_active_item_can_be_the_next_step(project):
    slug, ids = project
    repository.set_status(slug, ids["todo"], "done")
    assert "item-doing" in repository.get_status(slug)


def test_all_actionable_items_closed_says_so(temp_slug):
    repository.create_project(temp_slug, name="Tiny")
    item_id = repository.add_item(temp_slug, "only-item")
    repository.set_status(temp_slug, item_id, "done")
    assert "all items done" in repository.get_status(temp_slug)


# ---- overview ----

def test_overview_counts_actionable_and_waiting_separately(project):
    slug, _ = project
    ov = repository.overview(slug)
    assert ov["open_items"] == 2      # todo + doing
    assert ov["waiting_items"] == 2   # blocked + parked


def test_overview_next_matches_get_status(project):
    slug, _ = project
    next_title = repository.overview(slug)["next"]
    assert next_title in repository.get_status(slug)


def test_overview_preview_holds_no_waiting_or_closed_item(project):
    slug, _ = project
    preview = repository.overview(slug)["open_preview"]
    assert all("blocked" not in t and "parked" not in t for t in preview)
    assert all("done" not in t and "dropped" not in t for t in preview)


def test_overview_reports_the_valid_vocabulary(project):
    slug, _ = project
    names = [row["name"] for row in repository.overview(slug)["statuses"]]
    assert names == ["todo", "doing", "blocked", "done", "parked", "dropped"]


def test_overview_on_an_unknown_project_is_still_empty():
    assert repository.overview("no-such-project-xyz") == {}


# ---- get_history ----

def test_history_is_an_inventory_and_keeps_waiting_items(project):
    """A stalled item must stay discoverable — `trackden show --full` reads this."""
    slug, _ = project
    titles = set(repository.get_history(slug)["open_items"])
    assert {"item-blocked", "item-parked"} <= titles
    assert "item-done" not in titles and "item-dropped" not in titles


# ---- the safety default ----

def test_an_unrecognised_stored_status_stays_visible(temp_slug):
    """A legacy or hand-set value must show up, not vanish.

    Hiding an item we don't understand loses work silently; showing it is the
    honest failure mode.
    """
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    repository.create_project(temp_slug, name="Legacy")
    item_id = repository.add_item(temp_slug, "legacy-item")
    with SessionLocal() as db:
        item = db.scalar(select(models.Item).where(models.Item.id == item_id))
        item.status = "whatever-this-is"
        db.commit()
    assert "legacy-item" in {i["title"] for i in repository.list_items(temp_slug)}
