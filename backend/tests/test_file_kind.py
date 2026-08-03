"""The `file` memory kind: Trackden stores WHERE a thing is, and never touches it."""

import pytest

from app import repository

pytestmark = pytest.mark.db


@pytest.fixture
def project(temp_slug):
    repository.create_project(temp_slug, name="File Kind")
    return temp_slug


def test_file_is_a_valid_kind(project, tmp_path):
    real = tmp_path / "findings.md"
    real.write_text("Safari only", encoding="utf-8")
    assert repository.add_memory(
        project, "First findings", kind="file", path=str(real)
    ) == {"status": "saved"}


def test_a_file_without_a_path_is_refused(project):
    assert repository.add_memory(project, "x", kind="file") == {"status": "missing_path"}


def test_a_missing_path_is_stored_with_a_warning(project, tmp_path):
    """Stored anyway: the user may be recording where something is ABOUT to go."""
    result = repository.add_memory(
        project, "not yet", kind="file", path=str(tmp_path / "later.md")
    )
    assert result["status"] == "saved"
    assert result["warning"] == "path not found"


def test_a_path_is_stored_absolute(project, tmp_path, monkeypatch):
    """A relative path must survive a different working directory."""
    real = tmp_path / "findings.md"
    real.write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    repository.add_memory(project, "rel", kind="file", path="findings.md")

    stored = [m for m in repository.list_memory(project) if m["kind"] == "file"][0]
    assert stored["path"] == str(real.resolve())


def test_a_tilde_path_is_expanded(project):
    result = repository.add_memory(project, "home", kind="file", path="~/nope-xyz.md")
    assert result["status"] == "saved"
    stored = [m for m in repository.list_memory(project) if m["kind"] == "file"][0]
    assert "~" not in stored["path"]


def test_trackden_never_creates_the_file(project, tmp_path):
    """The product promise: the user's folders are theirs."""
    target = tmp_path / "must-not-exist.md"
    repository.add_memory(project, "pointer only", kind="file", path=str(target))
    assert not target.exists()


def test_an_unsupported_kind_is_refused_without_raising(project):
    result = repository.add_memory(project, "x", kind="nonsense")
    assert result["status"] == "rejected_kind"
    assert "file" in result["valid"]


def test_a_decision_is_still_pointed_at_add_decision(project):
    """The hint that kept decisions out of the memory table must survive the reshape."""
    result = repository.add_memory(project, "we chose X", kind="decision")
    assert result["status"] == "rejected_kind"
    assert "add_decision" in result["message"]


def test_the_three_original_kinds_still_work(project):
    for kind in ("link", "note", "transcript"):
        assert repository.add_memory(project, f"a {kind}", kind=kind)["status"] == "saved"


def test_a_link_without_a_url_is_still_accepted(project):
    """Deliberately NOT newly enforced — it works today and rows like it may exist."""
    assert repository.add_memory(project, "bare link", kind="link")["status"] == "saved"


# ---- item scoping ----

def test_memory_attaches_to_an_item(project):
    item_id = repository.add_item(project, "Fix the login redirect")["item_id"]
    assert repository.add_memory(project, "a finding", item_id=item_id)["status"] == "saved"
    stored = repository.list_memory(project)[0]
    assert stored["item_id"] == item_id


def test_memory_rejects_an_item_from_another_project(project, temp_slug_b):
    """Ownership, not existence — the rule B1 established for folders and items."""
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.add_item(temp_slug_b, "theirs")["item_id"]
    assert repository.add_memory(project, "mine", item_id=foreign) == {
        "status": "unknown_item"
    }


def test_memory_rejects_a_nonexistent_item(project):
    assert repository.add_memory(project, "x", item_id=999_999_999) == {
        "status": "unknown_item"
    }


def test_memory_rejects_a_folder_from_another_project(project, temp_slug_b):
    repository.create_project(temp_slug_b, name="Other")
    foreign = repository.create_folder(temp_slug_b, "Theirs")["folder_id"]
    assert repository.add_memory(project, "mine", folder_id=foreign) == {
        "status": "unknown_folder"
    }


def test_project_level_memory_still_works(project):
    """Most memory is not about one item; omitting item_id must stay valid."""
    assert repository.add_memory(project, "a project note")["status"] == "saved"
    assert repository.list_memory(project)[0]["item_id"] is None


# ---- path length guard ----

def test_a_path_longer_than_the_column_is_refused(project):
    """Unguarded, this reached Postgres as a raw DataError — over MCP, a traceback."""
    long_path = "/" + "x" * (repository.MAX_PATH + 10)
    assert repository.add_memory(project, "deep", kind="file", path=long_path) == {
        "status": "invalid_path"
    }


def test_a_path_at_the_length_limit_is_accepted(project):
    at_limit = "/" + "x" * (repository.MAX_PATH - 1)
    assert repository.add_memory(project, "edge", kind="file", path=at_limit)["status"] == "saved"
