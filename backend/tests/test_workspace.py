import subprocess
from pathlib import Path
from unittest import mock

import pytest

from app.workspace import ensure_home_git, project_dir, scaffold_project, trackden_home


def test_trackden_home_honours_the_env_override(home):
    assert trackden_home() == home


def test_trackden_home_expands_and_resolves_a_relative_override(tmp_path, monkeypatch):
    """A relative TRACKDEN_HOME must not land inside the cwd (e.g. the user's repo,
    if a caller cd'd into it) — it must resolve to an absolute path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRACKDEN_HOME", "relative-workspace")
    assert trackden_home() == (tmp_path / "relative-workspace").resolve()
    assert trackden_home().is_absolute()


def test_trackden_home_expands_a_tilde_override(monkeypatch):
    monkeypatch.setenv("TRACKDEN_HOME", "~/.trackden-fix9-test")
    result = trackden_home()
    assert "~" not in str(result)
    assert result == (Path.home() / ".trackden-fix9-test").resolve()


def test_trackden_home_empty_override_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("TRACKDEN_HOME", "")
    assert trackden_home() == Path.home() / ".trackden"


def test_project_dir_is_projects_slash_slug(home):
    assert project_dir("my-proj") == home / "projects" / "my-proj"


def test_scaffold_creates_three_guidance_files_plus_the_mirror(home):
    written = scaffold_project("my-proj", name="My Proj", tracker_md="# mirror\n")
    assert {path.name for path in written} == {
        "_way-of-work.md",
        "_arch.md",
        "_decisions.md",
        "_tracker.md",
    }
    for name in ("_way-of-work.md", "_arch.md", "_decisions.md", "_tracker.md"):
        assert (project_dir("my-proj") / name).exists()


def test_scaffold_seeds_way_of_work_from_supplied_text(home):
    scaffold_project("p", way_of_work="# rules lifted from the repo\n")
    assert (project_dir("p") / "_way-of-work.md").read_text() == "# rules lifted from the repo\n"


def test_scaffold_never_overwrites_human_owned_guidance(home):
    scaffold_project("p", way_of_work="original\n")
    scaffold_project("p", way_of_work="SHOULD NOT WIN\n")
    assert (project_dir("p") / "_way-of-work.md").read_text() == "original\n"


def test_scaffold_does_regenerate_the_tracker_mirror(home):
    scaffold_project("p", tracker_md="v1\n")
    scaffold_project("p", tracker_md="v2\n")
    assert (project_dir("p") / "_tracker.md").read_text() == "v2\n"


def test_scaffold_reports_only_newly_written_guidance_on_a_rerun(home):
    scaffold_project("p")
    written = scaffold_project("p")
    assert [path.name for path in written] == ["_tracker.md"]


def test_ensure_home_git_initialises_the_workspace_repo(home):
    assert ensure_home_git() is True
    assert (home / ".git").exists()


def test_ensure_home_git_is_idempotent(home):
    ensure_home_git()
    assert ensure_home_git() is True


# Slug validation — project_dir guards against path escapes
def test_project_dir_rejects_absolute_slug(home):
    with pytest.raises(ValueError):
        project_dir("/tmp/evil")


def test_project_dir_rejects_dotdot_slug(home):
    with pytest.raises(ValueError):
        project_dir("../../outside")


def test_project_dir_rejects_slug_with_forward_slash(home):
    with pytest.raises(ValueError):
        project_dir("foo/bar")


def test_project_dir_rejects_slug_with_backslash(home):
    with pytest.raises(ValueError):
        project_dir("foo\\bar")


def test_project_dir_rejects_empty_slug(home):
    with pytest.raises(ValueError):
        project_dir("")


def test_project_dir_rejects_bare_dot_slug(home):
    with pytest.raises(ValueError):
        project_dir(".")


def test_project_dir_rejects_windows_drive_relative_slug(home):
    with pytest.raises(ValueError):
        project_dir("D:evil")


def test_project_dir_safe_slug_resolves_correctly(home):
    assert project_dir("my-proj") == home / "projects" / "my-proj"


def test_scaffold_with_unsafe_slug_raises_and_writes_nothing(home):
    with pytest.raises(ValueError):
        scaffold_project("../escape")
    # Verify nothing was written to the workspace
    projects_dir = home / "projects"
    assert not projects_dir.exists() or list(projects_dir.iterdir()) == []


# Git unavailable — ensure_home_git gracefully returns False
def test_ensure_home_git_returns_false_when_git_binary_missing(home):
    with mock.patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        assert ensure_home_git() is False


def test_ensure_home_git_returns_false_when_git_command_fails(home):
    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "git init"),
    ):
        assert ensure_home_git() is False
