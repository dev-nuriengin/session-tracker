"""Trackden's own rules — pure, so no Postgres is involved.

The sharpest test here is `test_every_tool_the_text_names_actually_exists`: a rule
telling an agent to call something that is not there is worse than no rule at all.
"""

from app import playbook


def test_the_version_is_an_integer():
    assert isinstance(playbook.VERSION, int)
    assert playbook.VERSION >= 1


def test_the_digest_names_its_version():
    assert f"v{playbook.VERSION}" in playbook.DIGEST


def test_the_digest_stays_within_its_budget():
    """It rides inside EVERY overview response, so the budget is asserted, not hoped for."""
    assert len(playbook.DIGEST) <= playbook.MAX_DIGEST


def test_the_digest_holds_all_eleven_rules():
    for n in range(1, 12):
        assert f"{n}." in playbook.DIGEST, f"rule {n} missing from the digest"


def test_the_full_text_holds_all_seven_sections():
    for heading in (
        "What Trackden is",
        "Opening a session",
        "When to save",
        "Statuses",
        "Growing the vocabulary",
        "Files and the hybrid rule",
        "Precedence and anti-patterns",
    ):
        assert heading in playbook.TEXT, f"section missing: {heading}"


def test_the_full_text_is_longer_than_the_digest():
    assert len(playbook.TEXT) > len(playbook.DIGEST)


def test_the_text_says_the_project_outranks_the_playbook():
    """The precedence rule is the one that keeps this from overriding a human."""
    lowered = playbook.TEXT.lower()
    assert "way-of-work" in lowered
    assert "outrank" in lowered or "wins" in lowered


def test_the_text_says_trackden_never_touches_files():
    lowered = playbook.TEXT.lower()
    assert "never create" in lowered or "never creates" in lowered


def test_the_text_says_a_decision_needs_its_reason():
    assert "because" in playbook.TEXT.lower()


def test_every_tool_the_text_names_actually_exists():
    """A rule naming a tool that does not exist is worse than no rule.

    Checks the real MCP server's registry, so the playbook cannot drift from the
    tools it instructs an agent to call.
    """
    import re

    from app import mcp_server

    # `dir()` plus the tool manager is awkward; ask the manager directly instead.
    manager = mcp_server.mcp._tool_manager
    named = set(re.findall(r"\b([a-z_]+)\(", playbook.TEXT + playbook.DIGEST))
    # Only check names that look like our tools, not prose like "e.g.(" or python builtins.
    candidates = {
        n for n in named
        if n in {
            "overview", "get_guidance", "add_decision", "add_item", "add_folder",
            "add_status", "set_status", "add_memory", "save_progress", "get_history",
            "list_items", "list_memory", "list_statuses", "whats_next", "search",
            "get_playbook", "list_projects",
        }
    }
    assert candidates, "the text names no tools at all — that cannot be right"
    for name in sorted(candidates):
        assert manager.get_tool(name) is not None, f"playbook names a missing tool: {name}"


def test_the_text_says_an_agent_cannot_delete():
    """Delete is CLI-only on purpose — an agent that doesn't know will offer and fail."""
    lowered = playbook.TEXT.lower()
    assert "delete" in lowered
    assert "cannot" in lowered or "no tool" in lowered


def test_the_module_is_pure():
    """No DB, no filesystem, no app imports — same rule statuses.py follows."""
    import pathlib

    source = pathlib.Path(playbook.__file__).read_text(encoding="utf-8")
    for forbidden in ("from .", "import os", "SessionLocal", "open("):
        assert forbidden not in source, f"playbook.py must stay pure; found {forbidden!r}"
