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


def test_get_guidance_is_registered():
    assert mcp_server.mcp._tool_manager.get_tool("get_guidance") is not None


def test_add_decision_is_registered():
    assert mcp_server.mcp._tool_manager.get_tool("add_decision") is not None


def test_get_guidance_delegates_to_guidance(monkeypatch):
    seen = {}

    def fake_get(project, doc="way-of-work"):
        seen["args"] = (project, doc)
        return {"status": "filled", "text": "rules"}

    monkeypatch.setattr(mcp_server.guidance, "get", fake_get)
    result = mcp_server.get_guidance("korpus", doc="arch")
    assert seen["args"] == ("korpus", "arch")
    assert result["status"] == "filled"


def test_add_decision_delegates_to_guidance(monkeypatch):
    seen = {}

    def fake_add(project, decision, because, rejected=None):
        seen["args"] = (project, decision, because, rejected)
        return {"status": "appended"}

    monkeypatch.setattr(mcp_server.guidance, "add_decision", fake_add)
    result = mcp_server.add_decision("korpus", "chose X", "because Y", "not Z")
    assert seen["args"] == ("korpus", "chose X", "because Y", "not Z")
    assert result["status"] == "appended"


def test_add_memory_reports_a_rejected_kind_instead_of_raising(monkeypatch):
    def fake_add_memory(*args, **kwargs):
        raise ValueError("unsupported memory kind 'decision' — use `add_decision`")

    monkeypatch.setattr(mcp_server.repository, "add_memory", fake_add_memory)
    result = mcp_server.add_memory("korpus", "we chose X", kind="decision")
    assert result["status"] == "rejected_kind"
    assert "add_decision" in result["message"]


def test_add_memory_reports_saved_with_a_message_key(monkeypatch):
    monkeypatch.setattr(mcp_server.repository, "add_memory", lambda *a, **k: True)
    result = mcp_server.add_memory("korpus", "a repo link", kind="link")
    assert result == {"status": "saved", "message": ""}


def test_add_memory_reports_unknown_project_with_a_message_key(monkeypatch):
    monkeypatch.setattr(mcp_server.repository, "add_memory", lambda *a, **k: False)
    result = mcp_server.add_memory("bogus-project", "x")
    assert result["status"] == "unknown_project"
    assert "bogus-project" in result["message"]
