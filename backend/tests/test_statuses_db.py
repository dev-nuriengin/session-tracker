"""A project's extra status names, against the real (test) database."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="Status Test")
    return temp_slug


def test_a_fresh_project_already_has_the_shipped_defaults(project):
    names = [row["name"] for row in repository.list_statuses(project)]
    assert names == ["todo", "doing", "blocked", "done"]


def test_list_statuses_reports_the_class_of_each_name(project):
    by_name = {row["name"]: row["behaves_as"] for row in repository.list_statuses(project)}
    assert by_name["blocked"] == "waiting"
    assert by_name["done"] == "closed"


def test_list_statuses_on_an_unknown_project_is_empty():
    assert repository.list_statuses("no-such-project-xyz") == []


def test_adding_a_name_appends_it_and_keeps_the_defaults(project):
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}
    names = [row["name"] for row in repository.list_statuses(project)]
    assert names == ["todo", "doing", "blocked", "done", "parked"]


def test_a_name_that_is_already_a_default_is_a_duplicate(project):
    assert repository.add_status(project, "done", "open") == {"status": "duplicate_name"}
    # and the default is untouched
    by_name = {r["name"]: r["behaves_as"] for r in repository.list_statuses(project)}
    assert by_name["done"] == "closed"


def test_adding_the_same_extra_twice_is_a_duplicate(project):
    assert repository.add_status(project, "parked", "waiting") == {"status": "added"}
    assert repository.add_status(project, "parked", "waiting") == {"status": "duplicate_name"}


def test_an_unrecognised_class_is_rejected(project):
    assert repository.add_status(project, "sideways", "diagonal")["status"] == "unknown_class"
    assert "sideways" not in [r["name"] for r in repository.list_statuses(project)]


def test_a_blank_name_is_rejected(project):
    assert repository.add_status(project, "   ", "waiting") == {"status": "invalid_name"}


def test_a_name_longer_than_the_column_is_rejected(project):
    assert repository.add_status(project, "waiting-on-vendor-legal", "waiting") == {"status": "invalid_name"}


def test_a_name_at_the_length_limit_is_accepted(project):
    name = "x" * repository.MAX_STATUS_NAME
    assert repository.add_status(project, name, "waiting") == {"status": "added"}


def test_a_name_is_stored_normalised(project):
    assert repository.add_status(project, "  Parked  ", "waiting") == {"status": "added"}
    assert "parked" in [r["name"] for r in repository.list_statuses(project)]


def test_adding_to_an_unknown_project_reports_it():
    assert repository.add_status("no-such-project-xyz", "parked", "waiting") == {"status": "unknown_project"}


def test_closed_names_starts_as_just_done(project):
    assert repository.closed_names(project) == {"done"}


def test_closed_names_grows_with_a_closed_extra(project):
    repository.add_status(project, "dropped", "closed")
    assert repository.closed_names(project) == {"done", "dropped"}


def test_closed_names_ignores_a_waiting_extra(project):
    repository.add_status(project, "parked", "waiting")
    assert repository.closed_names(project) == {"done"}


def test_closed_names_on_an_unknown_project_falls_back_to_the_defaults():
    # a caller must never get an EMPTY closed set by accident: that would make
    # every finished item look open again
    assert repository.closed_names("no-such-project-xyz") == {"done"}


def test_two_projects_keep_separate_vocabularies(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    repository.add_status(project, "parked", "waiting")
    assert "parked" not in [r["name"] for r in repository.list_statuses(temp_slug_b)]


def test_init_db_is_idempotent_and_keeps_extras(project):
    """`create_all` creates the new table; running it again must not wipe a row.

    The onboarding branch shipped a migration bug for the neighbouring reason, so
    this asserts the DATA survives, not merely that the call does not raise.
    """
    from app.db import init_db

    repository.add_status(project, "parked", "waiting")
    init_db()
    init_db()
    assert "parked" in [r["name"] for r in repository.list_statuses(project)]
