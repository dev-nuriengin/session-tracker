"""What happens when an optional extra is not installed.

The base install is the CLI and the MCP server. `fastembed` (semantic search) and the
LangGraph summariser are extras, because between them they were most of a 250 MB
download for features many users never touch.

The rule these tests pin: **saving your work never depends on an optional package.**
Only finding it by meaning does — and when that is unavailable, both doors say so
rather than returning an empty result that reads as "this never happened".
"""

from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from app import cli as cli_mod
from app import embeddings, mcp_server, repository

runner = CliRunner()


@pytest.fixture
def without_fastembed(monkeypatch):
    """Simulate a base install.

    The cache is cleared going IN, not coming out: `monkeypatch` undoes its patch after
    the fixture body finishes, so a `cache_clear()` after the yield would be called on
    the replacement lambda — which has no cache — and blow up. Clearing first is also
    the clear that matters: it drops any `True` an earlier test cached from the real
    function, which is what would otherwise leak into this one.
    """
    embeddings.available.cache_clear()
    monkeypatch.setattr(embeddings, "available", lambda: False)
    yield


# ---- embed itself ----

def test_embed_returns_none_rather_than_raising(without_fastembed):
    assert embeddings.embed("anything") is None


def test_the_hint_names_the_extra_and_how_to_get_it():
    assert "search" in embeddings.INSTALL_HINT
    assert "install" in embeddings.INSTALL_HINT


# ---- the write path must survive ----

def test_search_logs_returns_empty_rather_than_erroring(monkeypatch):
    """The backstop: a direct caller gets [] instead of a SQL error comparing a vector
    against NULL. Both doors check availability before reaching here."""
    monkeypatch.setattr(repository, "embed", lambda text: None)
    assert repository.search_logs("anything") == []


@pytest.mark.db
def test_a_log_is_still_saved_without_the_search_extra(monkeypatch, temp_slug):
    """The load-bearing one. A user on a base install must still be able to record
    progress; the entry simply has no embedding and is skipped by search."""
    monkeypatch.setattr(repository, "embed", lambda text: None)
    repository.create_project(temp_slug, name="No Extras")

    result = repository.add_session_log(temp_slug, "cli", "did a thing")

    assert result["status"] == "saved"
    history = repository.get_history(temp_slug)
    assert any(log["content"] == "did a thing" for log in history["recent_logs"])


# ---- the CLI door ----

def test_ask_says_why_instead_of_implying_no_history(without_fastembed, monkeypatch):
    """"No matches" and "search is not installed" are different facts. Printing the
    first for the second makes a user conclude they never did the thing they asked
    about."""
    monkeypatch.setattr(cli_mod, "init_db", Mock())

    def explode(*args, **kwargs):
        raise AssertionError("must not query before checking availability")

    monkeypatch.setattr(cli_mod.repository, "search_logs", explode)

    result = runner.invoke(cli_mod.app, ["ask", "have I done this"])

    assert result.exit_code == 1, result.output
    assert "search" in result.output
    assert "No matches" not in result.output


def test_ask_still_works_normally_when_the_extra_is_present(monkeypatch):
    monkeypatch.setattr(cli_mod, "init_db", Mock())
    monkeypatch.setattr(cli_mod.embeddings, "available", lambda: True)
    monkeypatch.setattr(
        cli_mod.repository, "search_logs",
        lambda query, limit=5: [
            {"score": 0.9, "project": "acme", "kind": "step", "content": "shipped it"}
        ],
    )

    result = runner.invoke(cli_mod.app, ["ask", "what did I ship"])

    assert result.exit_code == 0, result.output
    assert "shipped it" in result.output


# ---- the MCP door ----

def test_search_tells_the_agent_it_is_unavailable(without_fastembed, monkeypatch):
    """An agent handed [] will confidently tell the user their history is empty. That
    is a factual lie, and the user has no way to know it came from a missing package."""
    def explode(*args, **kwargs):
        raise AssertionError("must not query before checking availability")

    monkeypatch.setattr(mcp_server.repository, "search_logs", explode)

    hits = mcp_server.search("have I done this")

    assert len(hits) == 1
    assert hits[0]["unavailable"] is True
    assert "install" in hits[0]["message"]


def test_search_returns_real_hits_when_the_extra_is_present(monkeypatch):
    monkeypatch.setattr(mcp_server.embeddings, "available", lambda: True)
    monkeypatch.setattr(
        mcp_server.repository, "search_logs",
        lambda query, limit=5: [{"project": "acme", "content": "shipped it"}],
    )

    hits = mcp_server.search("what did I ship")

    assert hits == [{"project": "acme", "content": "shipped it"}]
    assert "unavailable" not in hits[0]


def test_the_search_tool_docstring_warns_against_the_wrong_reading():
    """The docstring is the agent's only instruction here — if it does not say
    "not nothing found", the tool's contract is only in this test file."""
    tool = mcp_server.mcp._tool_manager.get_tool("search")
    assert "unavailable" in tool.description
