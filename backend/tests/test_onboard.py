import pytest

from app.onboard import scan_repo, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My Project", "my-project"),
        ("  Spaced  Out  ", "spaced-out"),
        ("Hînbûna Kurdî", "hinbuna-kurdi"),
        ("weird__chars!!", "weird-chars"),
        ("already-fine", "already-fine"),
        ("---", ""),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


@pytest.fixture
def fake_repo(tmp_path):
    # Its own subdirectory, not `tmp_path` itself — so it's a SIBLING of the
    # `~/.trackden` workspace the `home` fixture points at (also under `tmp_path`),
    # never an ancestor of it. Onboarding a repo writes to the workspace; a test that
    # scans the repo root for changes must not see the workspace's own files as if
    # they were changes to the repo.
    root = tmp_path / "repo"
    root.mkdir()
    (root / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").write_text("# rules\n\nBe careful.\n", encoding="utf-8")
    (root / "main-plans").mkdir()
    (root / "main-plans" / "_tracker.md").write_text(
        "- [ ] planned thing\n", encoding="utf-8"
    )
    noisy = root / "node_modules" / "pkg"
    noisy.mkdir(parents=True)
    (noisy / "_tracker.md").write_text("- [ ] vendored junk\n", encoding="utf-8")
    (root / "README.md").write_text("- [ ] not scanned\n", encoding="utf-8")
    return root


def test_scan_finds_tracker_files_and_guidance(fake_repo):
    hits = scan_repo(fake_repo)
    assert [hit.relpath for hit in hits] == [
        "_tracker.md",
        "main-plans/_tracker.md",
        "CLAUDE.md",
    ]


def test_scan_skips_vendored_directories(fake_repo):
    assert all("node_modules" not in hit.relpath for hit in scan_repo(fake_repo))


def test_scan_ignores_files_not_on_the_scan_list(fake_repo):
    assert all(hit.relpath != "README.md" for hit in scan_repo(fake_repo))


def test_scan_parses_items_and_flags_guidance(fake_repo):
    hits = {hit.relpath: hit for hit in scan_repo(fake_repo)}
    assert [item.title for item in hits["_tracker.md"].parsed.items] == [
        "done thing",
        "open thing",
    ]
    assert hits["CLAUDE.md"].is_guidance is True
    assert hits["_tracker.md"].is_guidance is False
    assert hits["CLAUDE.md"].text == "# rules\n\nBe careful.\n"


def test_scan_of_a_bare_repo_returns_nothing(tmp_path):
    assert scan_repo(tmp_path) == []


def test_scan_of_a_missing_path_returns_nothing(tmp_path):
    assert scan_repo(tmp_path / "does-not-exist") == []


from pathlib import Path

from app import onboard as onboard_mod
from app.onboard import run_onboard
from app.workspace import project_dir


@pytest.fixture
def fake_db(monkeypatch):
    """Stand in for the repository so the orchestrator tests need no Postgres."""

    state = {"projects": {}, "items": [], "repo_paths": {}}

    def create_project(slug, name=None, kind="personal", client=None, repo_path=None):
        if slug in state["projects"]:
            return False
        state["projects"][slug] = {"name": name or slug, "kind": kind, "client": client}
        state["repo_paths"][slug] = repo_path
        return True

    def set_repo_path(slug, repo_path):
        if slug not in state["projects"]:
            return False
        state["repo_paths"][slug] = repo_path
        return True

    def import_items(slug, items):
        if slug not in state["projects"]:
            return 0
        state["items"].extend(items)
        return len(items)

    def items_with_folders(slug):
        return list(state["items"]) if slug in state["projects"] else []

    for name, func in [
        ("create_project", create_project),
        ("set_repo_path", set_repo_path),
        ("import_items", import_items),
        ("items_with_folders", items_with_folders),
    ]:
        monkeypatch.setattr(onboard_mod.repository, name, func)
    return state


def test_onboard_creates_the_project_and_scaffolds_guidance(home, fake_db, tmp_path):
    result = run_onboard(slug="my-proj", name="My Proj", repo=None)
    assert result.created is True
    assert result.slug == "my-proj"
    assert (project_dir("my-proj") / "_way-of-work.md").exists()
    assert (project_dir("my-proj") / "_tracker.md").exists()


def test_onboard_slugifies_whatever_it_is_given(home, fake_db):
    assert run_onboard(slug="My Proj!").slug == "my-proj"


def test_onboard_imports_every_found_item_when_nothing_gates_it(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo)
    assert result.imported == 3  # 2 from _tracker.md + 1 from main-plans/_tracker.md
    assert sorted(result.sources) == ["_tracker.md", "main-plans/_tracker.md"]


def test_onboard_respects_a_gate_that_declines(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo, confirm=lambda hit: None)
    assert result.imported == 0
    assert result.sources == []


def test_onboard_respects_a_gate_that_edits_the_selection(home, fake_db, fake_repo):
    result = run_onboard(
        slug="p", repo=fake_repo, confirm=lambda hit: list(hit.parsed.items)[:1]
    )
    assert result.imported == 2  # one kept from each of the two tracker files


def test_onboard_can_skip_importing_entirely(home, fake_db, fake_repo):
    result = run_onboard(slug="p", repo=fake_repo, import_items=False)
    assert result.imported == 0


def test_onboard_seeds_way_of_work_from_the_repos_guidance_file(home, fake_db, fake_repo):
    run_onboard(slug="p", repo=fake_repo)
    assert (project_dir("p") / "_way-of-work.md").read_text() == "# rules\n\nBe careful.\n"


def test_onboard_writes_the_generated_mirror_from_db_state(home, fake_db, fake_repo):
    run_onboard(slug="p", name="P", repo=fake_repo)
    mirror = (project_dir("p") / "_tracker.md").read_text()
    assert "# P — tracker (GENERATED)" in mirror
    assert "- [ ] open thing" in mirror


def test_onboard_never_touches_the_users_repo(home, fake_db, fake_repo):
    before = {path: path.read_bytes() for path in fake_repo.rglob("*") if path.is_file()}
    run_onboard(slug="p", repo=fake_repo)
    after = {path: path.read_bytes() for path in fake_repo.rglob("*") if path.is_file()}
    assert before == after


def test_onboard_updates_repo_path_when_the_project_already_exists(home, fake_db, fake_repo):
    run_onboard(slug="p", repo=None)
    result = run_onboard(slug="p", repo=fake_repo)
    assert result.created is False
    assert fake_db["repo_paths"]["p"] == str(Path(fake_repo).resolve())


def test_onboard_does_not_reimport_items_when_the_project_already_exists(home, fake_db, fake_repo):
    run_onboard(slug="p", repo=fake_repo)
    after_first = len(fake_db["items"])
    assert after_first == 3
    result = run_onboard(slug="p", repo=fake_repo)
    assert result.created is False
    assert result.imported == 0
    assert result.sources == []  # nothing was imported, so nothing sourced it
    assert len(fake_db["items"]) == after_first  # no duplicate items or folders


def test_onboard_does_not_call_the_gate_on_a_re_run(home, fake_db, fake_repo):
    calls = []

    def spy(hit):
        calls.append(hit)
        return list(hit.parsed.items)

    run_onboard(slug="p", repo=fake_repo, confirm=spy)
    after_first = len(calls)
    assert after_first > 0  # sanity: the gate really did run on first onboard

    run_onboard(slug="p", repo=fake_repo, confirm=spy)
    assert len(calls) == after_first  # no new invocations — the gate did not run again


def test_onboard_initialises_the_workspace_git_repo(home, fake_db):
    assert run_onboard(slug="p").git_ready is True
    assert (home / ".git").exists()


def test_onboard_rejects_a_name_that_slugifies_to_empty(home, fake_db):
    with pytest.raises(ValueError):
        run_onboard(slug="---")
    assert fake_db["projects"] == {}  # rejected before any DB write


def test_onboard_rejects_a_non_ascii_only_name_that_slugifies_to_empty(home, fake_db):
    with pytest.raises(ValueError):
        run_onboard(slug="日本語プロジェクト")
    assert fake_db["projects"] == {}


def test_onboard_seeds_way_of_work_from_a_later_guidance_file_when_an_earlier_one_is_empty(
    home, fake_db, tmp_path
):
    repo = tmp_path / "empty-guidance-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# rules\n\nBe populated.\n", encoding="utf-8")
    run_onboard(slug="p3", repo=repo)
    assert (
        project_dir("p3") / "_way-of-work.md"
    ).read_text() == "# rules\n\nBe populated.\n"
