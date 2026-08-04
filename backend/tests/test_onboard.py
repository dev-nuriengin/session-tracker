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


# ---- FIX 2: never import a generated mirror as if it were source ----


def test_scan_skips_the_trackden_workspace_entirely(tmp_path):
    """`.trackden/projects/*/_tracker.md` is trackden's OWN generated mirror —
    `**/_tracker.md` must not descend into it, even though it matches the glob."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "_tracker.md").write_text(
        "## Phase 0\n- [ ] real item\n", encoding="utf-8"
    )
    mirror_dir = root / ".trackden" / "projects" / "some-project"
    mirror_dir.mkdir(parents=True)
    (mirror_dir / "_tracker.md").write_text(
        "## Phase 0\n- [ ] mirrored item\n", encoding="utf-8"
    )
    hits = scan_repo(root)
    assert all(".trackden" not in hit.relpath for hit in hits)
    assert any(hit.relpath == "_tracker.md" for hit in hits)


def test_scan_skips_any_file_carrying_the_generated_banner_even_outside_trackden(tmp_path):
    """Belt and braces: even a generated-looking file sitting somewhere other than
    `.trackden` (e.g. a copy-pasted mirror) must not be imported as source.

    Rendered WITH real items on purpose: with zero items the hit would be excluded
    anyway (scan_repo only keeps a hit if it has items or is a guidance file), which
    would make this test pass even if the `is_generated` check were deleted. With a
    real item present, the file would otherwise be a legitimate hit — so this only
    passes because `is_generated` catches it.
    """
    from app.tracker_md import render_tracker_md

    root = tmp_path / "repo"
    root.mkdir()
    content = render_tracker_md(
        "X", [{"title": "a real-looking item", "status": "todo", "folder": None}]
    )
    (root / "_tracker.md").write_text(content, encoding="utf-8")
    assert scan_repo(root) == []


def test_scan_still_returns_a_normal_hand_written_tracker_md(fake_repo):
    """Guard against over-filtering: a real, hand-written _tracker.md (no banner)
    must still come back."""
    hits = {hit.relpath for hit in scan_repo(fake_repo)}
    assert "_tracker.md" in hits


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
    """FIX 3: seeded verbatim would open with the vendor's own "# rules" heading and
    carry no trace of where it came from — a provenance header is prepended instead,
    and the original text is kept intact underneath it."""
    run_onboard(slug="p", name="P", repo=fake_repo)
    content = (project_dir("p") / "_way-of-work.md").read_text()
    assert content.startswith("# Way of work — P")
    assert "Seeded from `CLAUDE.md`" in content
    assert "# rules\n\nBe careful.\n" in content


def test_onboard_a_guidance_files_checklist_seeds_but_never_imports(home, fake_db, tmp_path):
    """FIX A (re-review): CLAUDE.md/AGENTS.md are in the scan set for exactly one
    purpose — seeding way_of_work. A checklist inside one must not ALSO become DB
    items; that would be the same datum living in two homes (a DB row and the
    verbatim text under the provenance header)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text(
        "## TODO\n- [ ] Write docs\n- [x] Setup repo\n", encoding="utf-8"
    )
    result = run_onboard(slug="p", name="P", repo=repo)

    assert result.imported == 0
    assert result.sources == []
    content = (project_dir("p") / "_way-of-work.md").read_text()
    assert "Seeded from `CLAUDE.md`" in content
    assert "## TODO\n- [ ] Write docs\n- [x] Setup repo\n" in content


def test_onboard_a_repo_with_only_a_guidance_checklist_imports_nothing(home, fake_db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "## TODO\n- [ ] Write docs\n- [x] Setup repo\n", encoding="utf-8"
    )
    result = run_onboard(slug="p", repo=repo)
    assert result.imported == 0
    assert result.sources == []


def test_onboard_imports_only_the_tracker_file_not_the_guidance_checklist(
    home, fake_db, tmp_path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text(
        "## TODO\n- [ ] guidance-only item\n", encoding="utf-8"
    )
    (repo / "_tracker.md").write_text(
        "## Phase 0\n- [ ] real item\n", encoding="utf-8"
    )
    result = run_onboard(slug="p", repo=repo)
    assert result.imported == 1
    assert result.sources == ["_tracker.md"]
    assert [item["title"] for item in fake_db["items"]] == ["real item"]


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

    calls = []

    def spy(hit):
        calls.append(hit)
        return list(hit.parsed.items)

    result = run_onboard(slug="p", repo=fake_repo, confirm=spy)
    assert result.created is False
    assert result.imported == 0
    assert result.sources == []  # nothing was imported, so nothing sourced it
    assert len(fake_db["items"]) == after_first  # no duplicate items or folders
    assert calls == []  # the gate must not run once the project already has items


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


def test_onboard_offers_the_gate_again_after_every_file_was_declined(home, fake_db, fake_repo):
    """A declined (or interrupted) first onboard must leave the project itemless,
    so it is NOT locked out of ever importing — there is no `delete` command, so a
    re-run is the only way back in."""
    calls = []

    def decline_everything(hit):
        calls.append(hit)
        return None

    first = run_onboard(slug="p", repo=fake_repo, confirm=decline_everything)
    assert first.imported == 0
    assert len(calls) > 0  # the gate did run on the (declined) first onboard

    calls.clear()

    def accept_everything(hit):
        calls.append(hit)
        return list(hit.parsed.items)

    second = run_onboard(slug="p", repo=fake_repo, confirm=accept_everything)
    assert len(calls) > 0  # the gate runs AGAIN — nothing was imported last time
    assert second.imported == 3  # everything now imports
    assert sorted(second.sources) == ["_tracker.md", "main-plans/_tracker.md"]


def test_onboard_no_import_flag_never_calls_scan_repo(home, fake_db, fake_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(
        onboard_mod, "scan_repo", lambda repo, *a, **kw: calls.append(repo) or []
    )
    result = run_onboard(slug="p", repo=fake_repo, import_items=False)
    assert result.imported == 0
    assert calls == []  # the scan never even ran


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
    content = (project_dir("p3") / "_way-of-work.md").read_text()
    assert "Seeded from `AGENTS.md`" in content
    assert "# rules\n\nBe populated.\n" in content


def test_onboard_with_no_guidance_file_still_gets_the_plain_template(home, fake_db, tmp_path):
    """FIX 3: a project with no CLAUDE.md/AGENTS.md must not get a provenance header
    pointing at nothing — it falls through to workspace.py's own default template."""
    repo = tmp_path / "no-guidance-repo"
    repo.mkdir()
    (repo / "_tracker.md").write_text("- [ ] just an item\n", encoding="utf-8")
    run_onboard(slug="p4", name="P4", repo=repo)
    content = (project_dir("p4") / "_way-of-work.md").read_text()
    assert "Seeded from" not in content
    assert "# Way of work — P4" in content


# ---- FIX 3 (delete re-review): reusing a deleted slug's leftover guidance ----


def test_onboard_flags_reused_guidance_from_a_previous_projects_slug(home, fake_db):
    """`scaffold_project` correctly never overwrites an existing guidance file — but
    combined with `delete` deliberately leaving the folder behind, onboarding the
    SAME slug for a DIFFERENT project silently inherits the old client's
    `_decisions.md` / `_way-of-work.md`. Nobody was told. `guidance_reused` is how
    `run_onboard` surfaces that fact, so the CLI can warn about it."""
    from app.workspace import scaffold_project

    scaffold_project("reused-slug", name="Old Client")  # simulates a leftover folder
    result = run_onboard(slug="reused-slug", name="New Client", repo=None)

    assert result.created is True
    assert result.guidance_reused is True

    # Sanity: a genuinely fresh slug (nothing on disk beforehand) must NOT be flagged.
    fresh = run_onboard(slug="brand-new-slug", repo=None)
    assert fresh.created is True
    assert fresh.guidance_reused is False


# ---- FIX 7: no length validation on slug or name ----

from app import models  # noqa: E402 — mid-file imports match this file's existing style

_SLUG_MAX = models.Project.__table__.c.slug.type.length
_NAME_MAX = models.Project.__table__.c.name.type.length


def test_onboard_rejects_a_slug_over_the_length_limit(home, fake_db):
    """An over-length slug used to reach Postgres, which raises StringDataRightTruncation
    (a DataError) — the CLI's `except ValueError` let that through as a raw traceback,
    the same failure shape explicitly fixed for the empty slug."""
    too_long = "a" * (_SLUG_MAX + 1)
    with pytest.raises(ValueError):
        run_onboard(slug=too_long)
    assert fake_db["projects"] == {}  # rejected before any DB write


def test_onboard_rejects_a_name_over_the_length_limit(home, fake_db):
    with pytest.raises(ValueError):
        run_onboard(slug="ok-slug", name="a" * (_NAME_MAX + 1))
    assert fake_db["projects"] == {}


def test_onboard_accepts_a_slug_exactly_at_the_length_limit(home, fake_db):
    exact = "a" * _SLUG_MAX
    result = run_onboard(slug=exact)
    assert result.slug == exact
    assert exact in fake_db["projects"]


# ---- FIX 6: run_onboard against the REAL repository layer (no monkeypatching) ----
#
# Every other test in this file (and in test_cli_onboard.py) monkeypatches
# onboard_mod.repository — the only proof that run_onboard and the real repository
# actually fit together was a manual smoke test that will never run again. This is
# exactly what would have caught FIX 1 (the missing schema migration on the CLI
# path). `_db_ready` (conftest.py) points this at the dedicated TEST database.


@pytest.mark.db
def test_run_onboard_against_the_real_repository_layer(_db_ready, tmp_path, temp_slug):
    from app import repository

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    workspace_home = tmp_path / ".trackden"

    result = run_onboard(
        slug=temp_slug, name="Pytest Onboard Tmp", repo=repo, home=workspace_home
    )

    assert result.created is True
    assert result.imported == 2

    project = repository.get_project(temp_slug)
    assert project is not None
    assert project.repo_path == str(repo.resolve())

    items = repository.items_with_folders(temp_slug)
    assert sorted((item["title"], item["status"]) for item in items) == [
        ("done thing", "done"),
        ("open thing", "todo"),
    ]

    mirror = (workspace_home / "projects" / temp_slug / "_tracker.md").read_text()
    assert "done thing" in mirror
    assert "open thing" in mirror

    # A second onboard of the same repo must import nothing more — the project
    # already has items.
    second = run_onboard(slug=temp_slug, repo=repo, home=workspace_home)
    assert second.imported == 0
    assert len(repository.items_with_folders(temp_slug)) == 2
