import pytest
from typer.testing import CliRunner

from app import guidance as guidance_mod
from app.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_schema_check(monkeypatch):
    """The CLI ensures the schema on every command; these tests need no database."""
    monkeypatch.setattr("app.cli.init_db", lambda: None)


def test_guidance_prints_the_document(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": "/w/_arch.md",
            "status": "filled", "text": "# Architecture\n\n- a real component\n",
            "message": "",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus", "--doc", "arch"])
    assert result.exit_code == 0, result.output
    assert "a real component" in result.output


def test_guidance_flags_an_untouched_template(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": "/w/_arch.md",
            "status": "template", "text": "# Architecture — K\n", "message": "",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus", "--doc", "arch"])
    assert result.exit_code == 0, result.output
    assert "template" in result.output.lower()


def test_guidance_exits_non_zero_when_not_scaffolded(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": None,
            "status": "not_scaffolded", "text": None,
            "message": "run `trackden onboard korpus` (safe to re-run)",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus"])
    assert result.exit_code == 1
    assert "onboard" in result.output


def test_decide_appends_and_reports_the_path(monkeypatch):
    seen = {}

    def fake_add(project, decision, because, rejected=None):
        seen["args"] = (project, decision, because, rejected)
        return {
            "project": project, "path": "/w/_decisions.md",
            "status": "appended", "message": "",
        }

    monkeypatch.setattr(guidance_mod, "add_decision", fake_add)
    result = runner.invoke(
        app,
        ["decide", "korpus", "Use fastembed", "--because", "keeps it keyless",
         "--rejected", "OpenAI"],
    )
    assert result.exit_code == 0, result.output
    assert seen["args"] == ("korpus", "Use fastembed", "keeps it keyless", "OpenAI")
    assert "_decisions.md" in result.output


def test_decide_requires_because():
    result = runner.invoke(app, ["decide", "korpus", "Use fastembed"])
    assert result.exit_code != 0
    assert "because" in result.output.lower()


def test_decide_exits_non_zero_when_not_scaffolded(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "add_decision",
        lambda project, decision, because, rejected=None: {
            "project": project, "path": "/w/_decisions.md", "status": "not_scaffolded",
        },
    )
    result = runner.invoke(app, ["decide", "korpus", "d", "--because", "b"])
    assert result.exit_code == 1
    assert "onboard" in result.output
