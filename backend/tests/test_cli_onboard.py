import pytest
from typer.testing import CliRunner

from app import onboard as onboard_mod
from app.cli import app

runner = CliRunner()


@pytest.fixture
def fake_repo_with_items(tmp_path):
    (tmp_path / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def fake_db(monkeypatch):
    state = {"projects": set(), "items": []}

    def create_project(slug, name=None, kind="personal", client=None, repo_path=None):
        if slug in state["projects"]:
            return False
        state["projects"].add(slug)
        return True

    def import_items(slug, items):
        state["items"].extend(items)
        return len(items)

    monkeypatch.setattr(onboard_mod.repository, "create_project", create_project)
    monkeypatch.setattr(onboard_mod.repository, "set_repo_path", lambda s, p: True)
    monkeypatch.setattr(onboard_mod.repository, "import_items", import_items)
    monkeypatch.setattr(
        onboard_mod.repository, "items_with_folders", lambda slug: list(state["items"])
    )
    return state


def test_onboard_with_flags_is_non_interactive(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--name", "My Proj", "--repo", str(fake_repo_with_items), "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert "my-proj" in result.output
    assert "2" in result.output  # two items imported
    assert state_has(fake_db, "open thing")


def state_has(state, title):
    return any(item["title"] == title for item in state["items"])


def test_onboard_review_gate_can_decline(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Found 2 items" in result.output
    assert fake_db["items"] == []


def test_onboard_review_gate_can_edit_the_selection(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items)],
        input="edit\n2\n",
    )
    assert result.exit_code == 0, result.output
    assert [item["title"] for item in fake_db["items"]] == ["open thing"]


def test_onboard_no_import_skips_the_scan(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard", "my-proj", "--repo", str(fake_repo_with_items), "--no-import"],
    )
    assert result.exit_code == 0, result.output
    assert "Found" not in result.output
    assert fake_db["items"] == []


def test_onboard_wizard_prompts_when_no_slug_is_given(home, fake_db, fake_repo_with_items):
    result = runner.invoke(
        app,
        ["onboard"],
        input=f"My Proj\n\npersonal\n{fake_repo_with_items}\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert "my-proj" in result.output


def test_onboard_prints_the_next_step(home, fake_db):
    result = runner.invoke(app, ["onboard", "my-proj", "--no-import"])
    assert "trackden show my-proj" in result.output


def test_onboard_empty_slug_exits_cleanly_without_a_traceback(home, fake_db):
    """Deviation from the brief: run_onboard raises ValueError when a slug folds to
    empty (e.g. "...", or a name that is all non-ASCII). The CLI must turn that into
    a clean, non-zero exit with an intelligible message — never a raw traceback —
    and must not have created a project.

    ("..." rather than "---" — a leading "-" is parsed by Click as an option, not
    the positional slug argument, which would fail for an unrelated reason.)
    """
    result = runner.invoke(app, ["onboard", "...", "--no-import"])
    assert result.exit_code != 0
    assert not isinstance(result.exception, ValueError)
    assert result.output.strip() != ""
    assert "Slug cannot be empty" in result.output
    assert fake_db["projects"] == set()
