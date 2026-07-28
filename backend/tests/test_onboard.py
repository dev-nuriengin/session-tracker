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
    (tmp_path / "_tracker.md").write_text(
        "## Phase 0\n- [x] done thing\n- [ ] open thing\n", encoding="utf-8"
    )
    (tmp_path / "CLAUDE.md").write_text("# rules\n\nBe careful.\n", encoding="utf-8")
    (tmp_path / "main-plans").mkdir()
    (tmp_path / "main-plans" / "_tracker.md").write_text(
        "- [ ] planned thing\n", encoding="utf-8"
    )
    noisy = tmp_path / "node_modules" / "pkg"
    noisy.mkdir(parents=True)
    (noisy / "_tracker.md").write_text("- [ ] vendored junk\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("- [ ] not scanned\n", encoding="utf-8")
    return tmp_path


def test_scan_finds_tracker_files_and_guidance(fake_repo):
    hits = scan_repo(fake_repo)
    assert {hit.relpath for hit in hits} == {
        "_tracker.md",
        "main-plans/_tracker.md",
        "CLAUDE.md",
    }


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
