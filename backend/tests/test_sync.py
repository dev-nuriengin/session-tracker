"""`sync` — the generated `_tracker.md` mirror, kept true to the DB.

No Postgres: `repository` is faked, so these tests pin the gate ORDER and the
outcome vocabulary, which is where this design's whole risk sits. The one test that
proves the doors are really wired is the `@pytest.mark.db` walkthrough in
`test_sync_e2e.py`.
"""

from types import SimpleNamespace

import pytest

from app import sync as sync_mod
from app import workspace


@pytest.fixture
def fake_repo(monkeypatch):
    """A `repository` stand-in. Mirrors the real reads' behaviour for an UNKNOWN
    project deliberately — `items_with_folders` returns [] and `closed_names` falls
    back to the defaults — because that is exactly the trap the gate order exists
    to survive. A fake that raised instead would hide it."""
    state = SimpleNamespace(projects={}, items={}, closed=frozenset({"done"}))

    monkeypatch.setattr(
        sync_mod.repository, "get_project",
        lambda slug: state.projects.get(slug.strip().lower()),
    )
    monkeypatch.setattr(
        sync_mod.repository, "items_with_folders",
        lambda slug: state.items.get(slug.strip().lower(), []),
    )
    monkeypatch.setattr(sync_mod.repository, "closed_names", lambda slug: state.closed)
    return state


def add_project(state, slug, name=None, items=None):
    state.projects[slug] = SimpleNamespace(slug=slug, name=name or slug)
    state.items[slug] = items or []


def item(title, status="todo", folder=None):
    return {"title": title, "status": status, "folder": folder}


def scaffolded(slug):
    directory = workspace.project_dir(slug)
    directory.mkdir(parents=True)
    return directory


# ---- synced ----

def test_synced_writes_the_mirror(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert result["items"] == 1
    assert result["path"] == str(directory / "_tracker.md")
    text = (directory / "_tracker.md").read_text(encoding="utf-8")
    assert "ship it" in text
    assert "Acme" in text


def test_synced_reflects_a_closed_status_as_a_ticked_box(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it", status="done")])
    directory = scaffolded("acme")

    sync_mod.sync("acme")

    assert "- [x] ship it" in (directory / "_tracker.md").read_text(encoding="utf-8")


def test_synced_with_zero_items_is_a_success(home, fake_repo):
    """An onboarded project with nothing in it yet is an empty mirror, not an error."""
    add_project(fake_repo, "acme", name="Acme", items=[])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert result["items"] == 0
    assert (directory / "_tracker.md").exists()


def test_sync_is_idempotent(home, fake_repo):
    """Two runs with no DB change between them must be byte-identical, or every
    sync shows a spurious diff in the git repo `ensure_home_git` maintains."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    sync_mod.sync("acme")
    first = (directory / "_tracker.md").read_bytes()
    sync_mod.sync("acme")

    assert (directory / "_tracker.md").read_bytes() == first


def test_sync_uses_the_db_slug_not_the_callers(home, fake_repo):
    """`get_project` lowercases before it queries, so an uppercase argument finds
    the project — but `workspace._SAFE_SLUG` rejects uppercase outright. Downstream
    calls must use `project.slug`, or the two layers disagree about which project
    they are working on. Same defect `trackden delete ACME` had."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("ACME")

    assert result["status"] == "synced"
    assert (directory / "_tracker.md").exists()


# ---- unknown_project — the trap gate ----

def test_unknown_project_creates_no_file_at_all(home, fake_repo):
    """THE trap. `items_with_folders` returns [] for an unknown project and
    `closed_names` falls back to the defaults, so rendering straight from them
    would write a valid, empty mirror for a project that does not exist. The bug
    this prevents is "a file appeared", not "a wrong string came back" — so assert
    the filesystem, not just the status."""
    result = sync_mod.sync("typo-slug")

    assert result["status"] == "unknown_project"
    assert "typo-slug" in result["message"]
    assert not (workspace.trackden_home() / "projects" / "typo-slug").exists()


# ---- not_scaffolded ----

def test_not_scaffolded_when_the_folder_is_missing(home, fake_repo):
    add_project(fake_repo, "acme", name="Acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "not_scaffolded"
    assert "onboard" in result["message"]
    assert not workspace.project_dir("acme").exists()


def test_an_unusable_stored_slug_is_reported_not_raised(home, fake_repo):
    """`trackden add-project my_project` only lowercases and strips — it never
    validates — so the DB can hold a slug `_SAFE_SLUG` rejects. `sync` promises
    never to raise, and that promise is its own to keep."""
    add_project(fake_repo, "my_project", name="My Project")

    result = sync_mod.sync("my_project")

    assert result["status"] == "not_scaffolded"
    assert "lowercase letters" in result["message"]


def test_a_later_valueerror_does_not_wear_the_slug_guard_message(
    home, fake_repo, monkeypatch
):
    """`workspace.project_dir` is the only call in `sync` that can raise
    `ValueError`, and it now has its own dedicated `except`. Proving the narrowing
    means showing the opposite: a `ValueError` raised by anything AFTER that call
    must not come back labelled `not_scaffolded` with the "cannot be a workspace
    folder" wording — that would send someone chasing a slug problem that was
    never the actual cause. With no `except ValueError` left downstream, it must
    propagate instead of being mislabelled."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    scaffolded("acme")

    def explode(slug):
        raise ValueError("boom from somewhere else entirely")

    monkeypatch.setattr(sync_mod.repository, "items_with_folders", explode)

    with pytest.raises(ValueError, match="boom from somewhere else entirely"):
        sync_mod.sync("acme")


# ---- hand_edited ----

def test_hand_edited_leaves_the_file_byte_identical(home, fake_repo):
    """The discriminating one. Asserting the STATUS alone passes against an
    implementation that returns `hand_edited` and overwrites the file anyway."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")
    mirror = directory / "_tracker.md"
    mirror.write_text("# my own notes\n- [ ] hand written\n", encoding="utf-8")
    before = mirror.read_bytes()

    result = sync_mod.sync("acme")

    assert result["status"] == "hand_edited"
    assert result["path"] == str(mirror)
    assert mirror.read_bytes() == before


def test_a_missing_mirror_is_written_not_called_hand_edited(home, fake_repo):
    """Absent is not edited. A scaffolded project whose mirror was deleted gets one."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")

    result = sync_mod.sync("acme")

    assert result["status"] == "synced"
    assert (directory / "_tracker.md").exists()


def test_a_non_utf8_mirror_is_refused_not_overwritten(home, fake_repo):
    """`UnicodeDecodeError` IS a `ValueError`, so without its own clause ahead of
    the slug guard this file would be reported as `not_scaffolded` — a confusing
    lie about a project that is scaffolded. Bytes we cannot read certainly did not
    come from us, so they get a hand-edited file's protection."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    directory = scaffolded("acme")
    mirror = directory / "_tracker.md"
    mirror.write_bytes(b"\xff\xfe\x00not text")
    before = mirror.read_bytes()

    result = sync_mod.sync("acme")

    assert result["status"] == "hand_edited"
    assert mirror.read_bytes() == before


# ---- write_failed ----

def test_write_failed_carries_the_reason(home, fake_repo, monkeypatch):
    """Monkeypatched rather than chmod-based: a chmod test does nothing when the
    suite runs as root (CI containers often do), and would then pass green against
    a `sync` that never catches `OSError` at all."""
    add_project(fake_repo, "acme", name="Acme", items=[item("ship it")])
    scaffolded("acme")

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(sync_mod.workspace, "write_mirror", refuse)

    result = sync_mod.sync("acme")

    assert result["status"] == "write_failed"
    assert "Permission denied" in result["reason"]
    assert "Permission denied" in result["message"]


# ---- the contract ----

@pytest.mark.parametrize(
    "setup",
    ["synced", "unknown_project", "not_scaffolded", "hand_edited"],
)
def test_every_outcome_carries_the_four_common_keys(home, fake_repo, setup):
    """Both doors read `message` and print it verbatim; a `None` or a missing key
    would reach a user as the string "None"."""
    if setup != "unknown_project":
        add_project(fake_repo, "acme", name="Acme")
    if setup in ("synced", "hand_edited"):
        directory = scaffolded("acme")
        if setup == "hand_edited":
            (directory / "_tracker.md").write_text("mine\n", encoding="utf-8")

    result = sync_mod.sync("acme")

    assert result["status"] == setup
    assert set(result) >= {"project", "status", "path", "message"}
    assert isinstance(result["message"], str)
