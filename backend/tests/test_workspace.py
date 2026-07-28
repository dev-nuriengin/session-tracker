from app.workspace import ensure_home_git, project_dir, scaffold_project, trackden_home


def test_trackden_home_honours_the_env_override(home):
    assert trackden_home() == home


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
