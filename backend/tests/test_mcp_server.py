"""MCP tool wiring — thin-wrapper tools should just delegate to repository.

No Postgres needed here: these tools have no logic of their own, so we monkeypatch
the repository call and check the wiring, not the DB.
"""

from app import mcp_server


def test_get_history_is_registered_as_an_mcp_tool():
    tool = mcp_server.mcp._tool_manager.get_tool("get_history")
    assert tool is not None


def test_get_history_delegates_to_repository_with_project_and_limit(monkeypatch):
    calls = []

    def fake_get_history(project, limit=10):
        calls.append((project, limit))
        return {"project": project, "open_items": [], "memory": [], "recent_logs": []}

    monkeypatch.setattr(mcp_server.repository, "get_history", fake_get_history)

    result = mcp_server.get_history("my-first-project", limit=3)

    assert calls == [("my-first-project", 3)]
    assert result == {"project": "my-first-project", "open_items": [], "memory": [], "recent_logs": []}
