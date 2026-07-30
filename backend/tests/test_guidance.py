"""The guidance orchestrator. No Postgres: `repository.get_project` is faked."""

from types import SimpleNamespace

import pytest

from app import guidance as guidance_mod
from app.guidance import add_decision, get
from app.workspace import guidance_path, scaffold_project


@pytest.fixture
def known_project(monkeypatch):
    """`repository.get_project` returns a project for 'p', nothing for anything else."""

    def get_project(slug):
        return SimpleNamespace(slug="p", name="P") if slug == "p" else None

    monkeypatch.setattr(guidance_mod.repository, "get_project", get_project)


def test_get_reports_unknown_project(home, known_project):
    result = get("nope")
    assert result["status"] == "unknown_project"
    assert result["text"] is None
    assert result["message"]


def test_get_reports_not_scaffolded(home, known_project):
    result = get("p")
    assert result["status"] == "not_scaffolded"
    assert result["text"] is None
    assert "trackden onboard p" in result["message"]


def test_get_reports_template_for_untouched_scaffolding(home, known_project):
    scaffold_project("p", name="P")
    result = get("p", "arch")
    assert result["status"] == "template"
    assert "Architecture — P" in result["text"]
    assert result["message"] == ""


def test_get_reports_filled_once_edited(home, known_project):
    scaffold_project("p", name="P")
    path = guidance_path("p", "arch")
    path.write_text(path.read_text() + "\n- real content\n", encoding="utf-8")
    result = get("p", "arch")
    assert result["status"] == "filled"
    assert "real content" in result["text"]
    assert result["message"] == ""


def test_get_defaults_to_way_of_work(home, known_project):
    scaffold_project("p", name="P")
    assert get("p")["doc"] == "way-of-work"


def test_get_reports_unknown_doc_without_raising(home, known_project):
    result = get("p", "not-a-doc")
    assert result["status"] == "unknown_doc"
    assert result["text"] is None
    assert "way-of-work" in result["message"]


def test_get_reports_the_path_when_it_has_one(home, known_project):
    scaffold_project("p", name="P")
    assert get("p", "arch")["path"] == str(guidance_path("p", "arch"))


def test_add_decision_reports_unknown_project(home, known_project):
    result = add_decision("nope", "d", "b")
    assert result["status"] == "unknown_project"
    assert result["message"]


def test_add_decision_reports_not_scaffolded(home, known_project):
    result = add_decision("p", "d", "b")
    assert result["status"] == "not_scaffolded"
    assert "trackden onboard p" in result["message"]


def test_add_decision_appends_and_reports_appended(home, known_project):
    scaffold_project("p", name="P")
    result = add_decision("p", "Use fastembed", "keeps the core keyless")
    assert result["status"] == "appended"
    assert result["message"] == ""
    assert "Use fastembed" in guidance_path("p", "decisions").read_text()


def test_add_decision_never_scaffolds(home, known_project):
    add_decision("p", "d", "b")
    assert not guidance_path("p", "decisions").exists()


@pytest.mark.db
def test_guidance_end_to_end_against_the_real_repository(home, temp_slug):
    """No fakes: real DB row, real workspace, real orchestrator."""
    from app import repository

    assert repository.create_project(temp_slug, name="E2E Project") is True
    scaffold_project(temp_slug, name="E2E Project")

    fresh = get(temp_slug, "decisions")
    assert fresh["status"] == "template"

    appended = add_decision(temp_slug, "Use fastembed", "keeps the core keyless")
    assert appended["status"] == "appended"

    after = get(temp_slug, "decisions")
    assert after["status"] == "filled"
    assert "Use fastembed" in after["text"]
    assert "- **Because:** keeps the core keyless" in after["text"]
