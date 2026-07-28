"""The real Postgres round-trip. Auto-skipped when the DB is down (see conftest)."""

import pytest

from app import repository
from app.db import init_db


@pytest.fixture(autouse=True)
def _schema():
    init_db()


@pytest.mark.db
def test_create_project_stores_the_repo_path(temp_slug, tmp_path):
    assert repository.create_project(temp_slug, repo_path=str(tmp_path)) is True
    assert repository.get_project(temp_slug).repo_path == str(tmp_path.resolve())


@pytest.mark.db
def test_project_is_findable_by_a_denormalised_repo_path(temp_slug, tmp_path):
    repository.create_project(temp_slug, repo_path=str(tmp_path))
    found = repository.get_project_by_repo_path(f"{tmp_path}/")
    assert found is not None and found.slug == temp_slug


@pytest.mark.db
def test_unknown_repo_path_finds_nothing(tmp_path):
    assert repository.get_project_by_repo_path(str(tmp_path / "nope")) is None


@pytest.mark.db
def test_set_repo_path_updates_an_existing_project(temp_slug, tmp_path):
    repository.create_project(temp_slug)
    assert repository.set_repo_path(temp_slug, str(tmp_path)) is True
    assert repository.get_project(temp_slug).repo_path == str(tmp_path.resolve())


@pytest.mark.db
def test_set_repo_path_on_an_unknown_project_returns_false(tmp_path):
    assert repository.set_repo_path("no-such-project-xyz", str(tmp_path)) is False


@pytest.mark.db
def test_import_items_creates_folders_by_name_and_keeps_order(temp_slug):
    repository.create_project(temp_slug)
    count = repository.import_items(
        temp_slug,
        [
            {"title": "first", "status": "done", "folder": "Phase 0"},
            {"title": "second", "status": "todo", "folder": "Phase 0"},
            {"title": "third", "status": "todo", "folder": "Phase 1"},
            {"title": "unfiled", "status": "todo", "folder": None},
        ],
    )
    assert count == 4
    assert repository.items_with_folders(temp_slug) == [
        {"title": "first", "status": "done", "folder": "Phase 0"},
        {"title": "second", "status": "todo", "folder": "Phase 0"},
        {"title": "third", "status": "todo", "folder": "Phase 1"},
        {"title": "unfiled", "status": "todo", "folder": None},
    ]


@pytest.mark.db
def test_import_items_rejects_statuses_it_should_never_invent(temp_slug):
    repository.create_project(temp_slug)
    count = repository.import_items(
        temp_slug, [{"title": "weird", "status": "blocked", "folder": None}]
    )
    assert count == 1
    assert repository.items_with_folders(temp_slug)[0]["status"] == "todo"


@pytest.mark.db
def test_import_items_on_an_unknown_project_writes_nothing(temp_slug):
    assert repository.import_items("no-such-project-xyz", [{"title": "x", "status": "todo", "folder": None}]) == 0


@pytest.mark.db
def test_items_with_folders_on_an_unknown_project_is_empty():
    assert repository.items_with_folders("no-such-project-xyz") == []
