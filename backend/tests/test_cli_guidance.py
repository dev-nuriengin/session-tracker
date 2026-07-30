import pytest
from typer.testing import CliRunner

from app import guidance as guidance_mod
from app import repository as repository_mod
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


def test_guidance_exits_non_zero_for_an_unknown_doc(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "get",
        lambda project, doc="way-of-work": {
            "project": project, "doc": doc, "path": None,
            "status": "unknown_doc", "text": None,
            "message": f"unknown doc {doc!r} — try one of: way-of-work, arch, decisions",
        },
    )
    result = runner.invoke(app, ["guidance", "korpus", "--doc", "bogus"])
    assert result.exit_code == 1
    assert "way-of-work" in result.output
    assert "arch" in result.output
    assert "decisions" in result.output


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
            "message": (
                "no guidance folder for 'korpus' yet — run `trackden onboard korpus` "
                "(safe to re-run) to scaffold it"
            ),
        },
    )
    result = runner.invoke(app, ["decide", "korpus", "d", "--because", "b"])
    assert result.exit_code == 1
    assert "onboard" in result.output
    assert "no guidance folder for 'korpus'" in result.output


def test_decide_exits_non_zero_for_an_unknown_project(monkeypatch):
    monkeypatch.setattr(
        guidance_mod, "add_decision",
        lambda project, decision, because, rejected=None: {
            "project": project, "path": None, "status": "unknown_project",
            "message": f"unknown project {project!r}",
        },
    )
    result = runner.invoke(app, ["decide", "bogus-project", "d", "--because", "b"])
    assert result.exit_code == 1
    assert "bogus-project" in result.output


def test_remember_rejects_the_decision_kind_pointing_at_decide(monkeypatch):
    def fake_add_memory(project, content, kind="note", title=None, url=None):
        assert kind == "decision"
        raise ValueError(
            "unsupported memory kind 'decision'; expected one of link, note, transcript"
            " — use `add_decision`, which writes to the project's `_decisions.md`"
        )

    monkeypatch.setattr(repository_mod, "add_memory", fake_add_memory)
    result = runner.invoke(app, ["remember", "korpus", "we chose X", "--kind", "decision"])
    assert result.exit_code == 1
    assert "add_decision" in result.output
    assert not isinstance(result.exception, ValueError)  # caught, not an unhandled traceback


def test_remember_rejects_an_arbitrary_bad_kind(monkeypatch):
    def fake_add_memory(project, content, kind="note", title=None, url=None):
        raise ValueError(
            "unsupported memory kind 'nonsense'; expected one of link, note, transcript"
        )

    monkeypatch.setattr(repository_mod, "add_memory", fake_add_memory)
    result = runner.invoke(app, ["remember", "korpus", "x", "--kind", "nonsense"])
    assert result.exit_code == 1
    assert "unsupported memory kind" in result.output
    assert not isinstance(result.exception, ValueError)  # caught, not an unhandled traceback


def test_remember_exits_non_zero_for_an_unknown_project(monkeypatch):
    monkeypatch.setattr(repository_mod, "add_memory", lambda *a, **k: False)
    result = runner.invoke(app, ["remember", "bogus-project", "x"])
    assert result.exit_code == 1
    assert "bogus-project" in result.output


def test_remember_saves_and_reports_success(monkeypatch):
    monkeypatch.setattr(repository_mod, "add_memory", lambda *a, **k: True)
    result = runner.invoke(app, ["remember", "korpus", "x", "--kind", "link"])
    assert result.exit_code == 0, result.output
    assert "✓" in result.output
