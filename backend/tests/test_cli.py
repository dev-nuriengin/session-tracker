"""CLI-wide behavior — not specific to any one command.

No Postgres needed here: init_db and the repository call are both faked, so
these tests never touch a database, real or test.
"""

from unittest.mock import Mock

from typer.testing import CliRunner

from app import cli as cli_mod

runner = CliRunner()


def test_cli_ensures_the_schema_before_running_any_command(monkeypatch):
    """FIX 1: cli.py never called init_db() before — only repository.setup() did
    (from FastAPI startup / the MCP server's __main__), and cli.py calls neither.
    Against a database whose `projects` table predates a column like `repo_path`,
    the first query raised a raw UndefinedColumn traceback, for every command, not
    just `onboard`. Spy on init_db as imported into app.cli and confirm it runs."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.repository, "list_projects", lambda: [])

    result = runner.invoke(cli_mod.app, ["list"])

    assert result.exit_code == 0, result.output
    spy.assert_called_once()


def test_cli_ensures_the_schema_before_a_different_command_too(monkeypatch):
    """The fix is a Typer app-level callback, not a per-command patch — confirm it
    fires for a second, unrelated command as well."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)
    monkeypatch.setattr(cli_mod.repository, "get_status", lambda project: "")

    result = runner.invoke(cli_mod.app, ["status", "some-project"])

    assert result.exit_code == 0, result.output
    spy.assert_called_once()


def test_cli_help_does_not_require_the_schema_check(monkeypatch):
    """`--help` must stay safe to run against any database (or none) — Click
    handles --help eagerly and never invokes the app callback."""
    spy = Mock()
    monkeypatch.setattr(cli_mod, "init_db", spy)

    result = runner.invoke(cli_mod.app, ["--help"])

    assert result.exit_code == 0, result.output
    spy.assert_not_called()


def _no_schema(monkeypatch):
    """Neutralise the app-level init_db callback — these tests never touch Postgres."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())


def test_set_status_reports_the_move(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "set", "from": "todo", "to": "doing"},
    )
    # The "set" branch now auto-refreshes the mirror — stub sync so this stays a
    # pure-unit test (the file's own header contract), not a live Postgres query.
    monkeypatch.setattr(cli_mod.sync_mod, "sync", lambda slug: {"status": "synced"})
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"])
    assert result.exit_code == 0, result.output
    assert "todo → doing" in result.output


def test_set_status_exits_non_zero_on_an_unknown_status(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "parked"])
    assert result.exit_code == 1
    assert "todo" in result.output and "done" in result.output


def test_set_status_exits_non_zero_on_an_unknown_item(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "set_status", lambda *a, **k: {"status": "unknown_item"}
    )
    assert runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"]).exit_code == 1


def test_unchanged_is_reported_and_succeeds(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "set_status",
        lambda *a, **k: {"status": "unchanged", "from": "doing", "to": "doing"},
    )
    result = runner.invoke(cli_mod.app, ["set-status", "acme", "42", "doing"])
    assert result.exit_code == 0, result.output
    assert "already" in result.output


def test_add_status_succeeds(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: {"status": "added"})
    result = runner.invoke(
        cli_mod.app, ["add-status", "acme", "parked", "--behaves-as", "waiting"]
    )
    assert result.exit_code == 0, result.output
    assert "parked" in result.output


def test_add_status_exits_non_zero_on_a_duplicate(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "add_status", lambda *a, **k: {"status": "duplicate_name"})
    assert runner.invoke(
        cli_mod.app, ["add-status", "acme", "done", "--behaves-as", "open"]
    ).exit_code == 1


def test_statuses_lists_names_with_their_class(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "list_statuses",
        lambda slug: [{"name": "todo", "behaves_as": "open"}],
    )
    result = runner.invoke(cli_mod.app, ["statuses", "acme"])
    assert result.exit_code == 0, result.output
    assert "todo" in result.output and "open" in result.output


def test_statuses_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "list_statuses", lambda slug: [])
    assert runner.invoke(cli_mod.app, ["statuses", "nope"]).exit_code == 1


# ---- the exit-code bug: these printed an error and still exited 0 ----

def test_add_folder_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "unknown_project"}
    )
    assert runner.invoke(cli_mod.app, ["add-folder", "nope", "Bugs"]).exit_code == 1


def test_add_folder_reports_the_new_id(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "added", "folder_id": 7}
    )
    result = runner.invoke(cli_mod.app, ["add-folder", "acme", "Bugs"])
    assert result.exit_code == 0, result.output
    assert "#7" in result.output


def test_add_folder_exits_non_zero_for_an_unknown_parent(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "create_folder", lambda *a, **k: {"status": "unknown_parent"}
    )
    result = runner.invoke(cli_mod.app, ["add-folder", "acme", "Bugs", "--parent", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_add_item_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "unknown_project"}
    )
    assert runner.invoke(cli_mod.app, ["add-item", "nope", "Fix it"]).exit_code == 1


def test_add_item_reports_the_new_id(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "added", "item_id": 42}
    )
    # The "added" branch now auto-refreshes the mirror — stub sync so this stays a
    # pure-unit test (the file's own header contract), not a live Postgres query.
    monkeypatch.setattr(cli_mod.sync_mod, "sync", lambda slug: {"status": "synced"})
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it"])
    assert result.exit_code == 0, result.output
    assert "#42" in result.output


def test_add_item_exits_non_zero_for_an_unknown_folder(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_item", lambda *a, **k: {"status": "unknown_folder"}
    )
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it", "--folder", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_add_item_exits_non_zero_for_an_unknown_status(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "add_item",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    result = runner.invoke(cli_mod.app, ["add-item", "acme", "Fix it", "--status", "nope"])
    assert result.exit_code == 1
    assert "todo" in result.output


def test_log_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_session_log", lambda *a, **k: {"status": "unknown_project"}
    )
    assert runner.invoke(cli_mod.app, ["log", "nope", "did a thing"]).exit_code == 1


def test_log_exits_non_zero_for_an_unknown_item(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_session_log", lambda *a, **k: {"status": "unknown_item"}
    )
    result = runner.invoke(cli_mod.app, ["log", "acme", "did a thing", "--item", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_log_prints_confirmation_on_success(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_session_log", lambda *a, **k: {"status": "saved"}
    )
    result = runner.invoke(cli_mod.app, ["log", "acme", "did a thing"])
    assert result.exit_code == 0, result.output
    assert "✓" in result.output


def test_remember_reports_saved_with_the_warning_line(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "add_memory",
        lambda *a, **k: {"status": "saved", "warning": "path not found"},
    )
    result = runner.invoke(
        cli_mod.app, ["remember", "acme", "not yet", "--kind", "file", "--path", "later.md"]
    )
    assert result.exit_code == 0, result.output
    assert "✓" in result.output
    assert "path not found" in result.output


def test_remember_kind_file_without_a_path_exits_non_zero(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_memory", lambda *a, **k: {"status": "missing_path"}
    )
    result = runner.invoke(cli_mod.app, ["remember", "acme", "x", "--kind", "file"])
    assert result.exit_code == 1
    assert "--path" in result.output


def test_remember_with_an_invalid_path_exits_non_zero(monkeypatch):
    """Without an `invalid_path` key, this outcome raised a KeyError in `remember`."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_memory", lambda *a, **k: {"status": "invalid_path"}
    )
    result = runner.invoke(
        cli_mod.app, ["remember", "acme", "x", "--kind", "file", "--path", "x"]
    )
    assert result.exit_code == 1
    assert str(cli_mod.repository.MAX_PATH) in result.output


def test_remember_with_an_unknown_item_exits_non_zero(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "add_memory", lambda *a, **k: {"status": "unknown_item"}
    )
    result = runner.invoke(cli_mod.app, ["remember", "acme", "x", "--item", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_remember_rejected_kind_prints_the_add_decision_hint(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "add_memory",
        lambda *a, **k: {
            "status": "rejected_kind",
            "valid": ["file", "link", "note", "transcript"],
            "message": "unsupported memory kind 'decision' — use `add_decision`",
        },
    )
    result = runner.invoke(cli_mod.app, ["remember", "acme", "we chose X", "--kind", "decision"])
    assert result.exit_code == 1
    assert "add_decision" in result.output


def test_show_reports_the_waiting_count(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "overview",
        lambda slug: {
            "project": "acme", "next": "a", "open_items": 1, "open_preview": ["a"],
            "waiting_items": 2, "memory_entries": 0, "last_activity": None,
            "statuses": [{"name": "todo", "behaves_as": "open"}],
        },
    )
    result = runner.invoke(cli_mod.app, ["show", "acme"])
    assert result.exit_code == 0, result.output
    assert "waiting" in result.output and "2" in result.output


def test_show_item_prints_the_item_block_memory_and_logs(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository,
        "get_history",
        lambda *a, **k: {
            "project": "acme",
            "open_items": ["BUG-431 login redirect loops"],
            "item": {"title": "BUG-431 login redirect loops", "status": "todo"},
            "memory": [{"kind": "file", "content": "First findings",
                        "path": "/tmp/trackden-b2-findings.md", "url": None, "item_id": 42}],
            "recent_logs": [{"kind": "note", "content": "reproduced on Safari"}],
        },
    )
    result = runner.invoke(cli_mod.app, ["show", "acme", "--item", "42"])
    assert result.exit_code == 0, result.output
    assert "BUG-431 login redirect loops" in result.output
    assert "todo" in result.output
    assert "trackden-b2-findings.md" in result.output
    assert "reproduced on Safari" in result.output


def test_show_item_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(cli_mod.repository, "get_history", lambda *a, **k: {})
    result = runner.invoke(cli_mod.app, ["show", "nope", "--item", "42"])
    assert result.exit_code == 1
    assert "nope" in result.output


def test_show_item_exits_non_zero_for_an_unknown_item(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "get_history", lambda *a, **k: {"status": "unknown_item"}
    )
    result = runner.invoke(cli_mod.app, ["show", "acme", "--item", "999"])
    assert result.exit_code == 1
    assert "999" in result.output


def test_playbook_prints_the_full_text_not_just_the_digest(monkeypatch):
    _no_schema(monkeypatch)
    result = runner.invoke(cli_mod.app, ["playbook"])
    assert result.exit_code == 0, result.output
    # Section headings exist only in TEXT, never in DIGEST — so this fails if the
    # command ever echoes DIGEST by mistake.
    assert "Precedence and anti-patterns" in result.output
    assert "Files and the hybrid rule" in result.output


def test_playbook_needs_no_project(monkeypatch):
    """Product-wide: it must not require a project argument."""
    _no_schema(monkeypatch)
    assert runner.invoke(cli_mod.app, ["playbook"]).exit_code == 0


def test_delete_shows_a_preview_and_asks_before_deleting(monkeypatch):
    """The only irreversible command: it must not act on one word."""
    _no_schema(monkeypatch)
    called = {}
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 4, "folders": 1, "memory": 2,
                      "sessions": 1, "logs": 7, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project",
        lambda slug: called.update(slug=slug) or {"status": "deleted", "removed": {}},
    )
    result = runner.invoke(cli_mod.app, ["delete", "acme"], input="y\n")
    assert result.exit_code == 0, result.output
    # the preview names the real counts, so the user is not agreeing blind
    assert "4" in result.output and "7" in result.output
    assert called["slug"] == "acme"


def test_delete_aborts_when_the_user_says_no(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 1, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    def refuse(slug):
        raise AssertionError("delete_project must not be called after a refusal")
    monkeypatch.setattr(cli_mod.repository, "delete_project", refuse)
    result = runner.invoke(cli_mod.app, ["delete", "acme"], input="n\n")
    assert result.exit_code == 1
    assert "aborted" in result.output.lower() or "cancelled" in result.output.lower()


def test_delete_yes_skips_the_prompt(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 0, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project",
        lambda slug: {"status": "deleted", "removed": {"items": 0}},
    )
    result = runner.invoke(cli_mod.app, ["delete", "acme", "--yes"])
    assert result.exit_code == 0, result.output


def test_delete_exits_non_zero_for_an_unknown_project(monkeypatch):
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts", lambda slug: {"status": "unknown_project"}
    )
    result = runner.invoke(cli_mod.app, ["delete", "nope", "--yes"])
    assert result.exit_code == 1
    assert "nope" in result.output


def test_delete_says_the_guidance_files_were_kept(monkeypatch, tmp_path):
    """The user must know the hand-written files survived, and where they are."""
    _no_schema(monkeypatch)
    guidance = tmp_path / "projects" / "acme"
    guidance.mkdir(parents=True)
    (guidance / "_decisions.md").write_text("# Decisions", encoding="utf-8")
    monkeypatch.setattr(cli_mod.workspace_mod, "project_dir", lambda slug, home=None: guidance)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 0, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project",
        lambda slug: {"status": "deleted", "removed": {}},
    )
    result = runner.invoke(cli_mod.app, ["delete", "acme", "--yes"])
    assert result.exit_code == 0, result.output
    assert "_decisions.md" in result.output or str(guidance) in result.output
    assert guidance.exists(), "the CLI must not delete the guidance folder"


def test_delete_survives_a_slug_workspace_rejects(monkeypatch):
    """`project_dir` raises ValueError on an unsafe slug; delete must still succeed."""
    _no_schema(monkeypatch)
    def boom(slug, home=None):
        raise ValueError(f"unsafe project slug: {slug!r}")
    monkeypatch.setattr(cli_mod.workspace_mod, "project_dir", boom)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 0, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project",
        lambda slug: {"status": "deleted", "removed": {}},
    )
    result = runner.invoke(cli_mod.app, ["delete", "acme", "--yes"])
    assert result.exit_code == 0, result.output
    assert "kept your guidance files" not in result.output


def test_delete_reports_kept_files_for_a_capitalised_slug(monkeypatch, tmp_path):
    """`repository` lowercases the slug; workspace's guard rejects uppercase. Without
    normalising in the command, this case silently lost the one notice the keep-files
    decision depends on."""
    _no_schema(monkeypatch)
    guidance = tmp_path / "projects" / "acme"
    guidance.mkdir(parents=True)
    (guidance / "_decisions.md").write_text("# Decisions", encoding="utf-8")
    seen = {}
    def project_dir(slug, home=None):
        seen["slug"] = slug
        return guidance
    monkeypatch.setattr(cli_mod.workspace_mod, "project_dir", project_dir)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 0, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project", lambda slug: {"status": "deleted", "removed": {}}
    )
    result = runner.invoke(cli_mod.app, ["delete", "ACME", "--yes"])
    assert result.exit_code == 0, result.output
    assert seen["slug"] == "acme", "the command must normalise before asking workspace"
    assert "_decisions.md" in result.output or str(guidance) in result.output


def test_delete_echoes_the_actual_removed_counts(monkeypatch):
    """FIX 4: the preview and the delete run in separate transactions and can
    legitimately diverge (an MCP-connected agent can add rows while the human reads
    the prompt) — the CLI must echo what was ACTUALLY removed, not just the preview."""
    _no_schema(monkeypatch)
    monkeypatch.setattr(
        cli_mod.repository, "project_counts",
        lambda slug: {"status": "counted", "items": 1, "folders": 0, "memory": 0,
                      "sessions": 0, "logs": 0, "statuses": 0},
    )
    monkeypatch.setattr(
        cli_mod.repository, "delete_project",
        lambda slug: {"status": "deleted", "removed": {
            "items": 3, "folders": 0, "memory": 0, "sessions": 0, "logs": 0, "statuses": 0,
        }},
    )
    result = runner.invoke(cli_mod.app, ["delete", "acme", "--yes"])
    assert result.exit_code == 0, result.output
    assert "✓ deleted 'acme'" in result.output
    assert "items      3" in result.output
