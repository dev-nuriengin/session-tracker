"""The generated mirror, end to end — real DB, real filesystem, real CLI.

Everything else about sync is unit-tested with fakes. This is the only test that
proves the auto-refresh is actually WIRED to a door rather than merely implemented,
which is a different claim and the one that breaks silently.

`_db_ready` (conftest.py) points this at the dedicated TEST database, never the one
`.env` configures.
"""

import pytest
from typer.testing import CliRunner

from app import cli as cli_mod
from app import repository
from app.onboard import run_onboard

runner = CliRunner()


@pytest.mark.db
def test_the_mirror_stays_true_through_the_cli_door(home, temp_slug, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_onboard(slug=temp_slug, name="Sync E2E", repo=repo, home=home)

    mirror = home / "projects" / temp_slug / "_tracker.md"
    assert mirror.exists(), "onboard should have written the mirror"
    assert "new thing" not in mirror.read_text(encoding="utf-8")

    # add-item refreshes it
    result = runner.invoke(cli_mod.app, ["add-item", temp_slug, "new thing"])
    assert result.exit_code == 0, result.output
    assert "new thing" in mirror.read_text(encoding="utf-8")

    # set-status refreshes it
    item_id = repository.list_items(temp_slug)[0]["id"]
    result = runner.invoke(cli_mod.app, ["set-status", temp_slug, str(item_id), "done"])
    assert result.exit_code == 0, result.output
    assert "- [x] new thing" in mirror.read_text(encoding="utf-8")

    # add-folder: NOT proof of no-refresh — `groups` (tracker_md.py) is built by
    # iterating items, so a folder with no items renders nothing at all, and this
    # byte-compare would pass identically whether or not `sync` ran. It only pins
    # that rendering fact. The real wiring-absence proof, with a call-count spy,
    # is `test_add_folder_does_not_refresh` in test_cli_sync.py.
    before = mirror.read_bytes()
    result = runner.invoke(cli_mod.app, ["add-folder", temp_slug, "Phase 1"])
    assert result.exit_code == 0, result.output
    assert mirror.read_bytes() == before, (
        "an empty folder should render nothing in the mirror"
    )

    # `trackden sync` is idempotent
    result = runner.invoke(cli_mod.app, ["sync", temp_slug])
    assert result.exit_code == 0, result.output
    once = mirror.read_bytes()
    result = runner.invoke(cli_mod.app, ["sync", temp_slug])
    assert result.exit_code == 0, result.output
    assert mirror.read_bytes() == once


@pytest.mark.db
def test_sync_of_an_unknown_project_creates_nothing(home, tmp_path):
    """The trap gate, at the real door: exit 1, and no file anywhere."""
    result = runner.invoke(cli_mod.app, ["sync", "definitely-not-a-project"])

    assert result.exit_code == 1, result.output
    assert not (home / "projects" / "definitely-not-a-project").exists()


@pytest.mark.db
def test_sync_repairs_a_mirror_that_drifted(home, temp_slug, tmp_path):
    """The command's whole reason to exist: a mirror made stale out-of-band —
    here by writing through the repository directly, as an agent or a `psql`
    session would — is repaired by one `trackden sync`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_onboard(slug=temp_slug, name="Sync E2E", repo=repo, home=home)
    mirror = home / "projects" / temp_slug / "_tracker.md"

    assert repository.add_item(temp_slug, "added behind the door")["status"] == "added"
    assert "added behind the door" not in mirror.read_text(encoding="utf-8")

    result = runner.invoke(cli_mod.app, ["sync", temp_slug])

    assert result.exit_code == 0, result.output
    assert "added behind the door" in mirror.read_text(encoding="utf-8")
