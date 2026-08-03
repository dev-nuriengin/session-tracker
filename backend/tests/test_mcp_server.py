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
        return {
            "status": "rejected_kind",
            "valid": ["file", "link", "note", "transcript"],
            "message": "unsupported memory kind 'decision' — use `add_decision`",
        }

    monkeypatch.setattr(mcp_server.repository, "add_memory", fake_add_memory)
    result = mcp_server.add_memory("korpus", "we chose X", kind="decision")
    assert result["status"] == "rejected_kind"
    assert "add_decision" in result["message"]


def test_add_memory_reports_saved_as_a_thin_pass_through(monkeypatch):
    monkeypatch.setattr(mcp_server.repository, "add_memory", lambda *a, **k: {"status": "saved"})
    result = mcp_server.add_memory("korpus", "a repo link", kind="link")
    assert result == {"status": "saved"}


def test_add_memory_reports_unknown_project_as_a_thin_pass_through(monkeypatch):
    monkeypatch.setattr(
        mcp_server.repository, "add_memory", lambda *a, **k: {"status": "unknown_project"}
    )
    result = mcp_server.add_memory("bogus-project", "x")
    assert result == {"status": "unknown_project"}


def test_add_memory_delegates_path_and_item_id(monkeypatch):
    seen = {}

    def fake_add_memory(project, content, kind="note", title=None, url=None,
                         path=None, item_id=None, folder_id=None):
        seen.update(
            project=project, content=content, kind=kind, title=title, url=url,
            path=path, item_id=item_id, folder_id=folder_id,
        )
        return {"status": "saved"}

    monkeypatch.setattr(mcp_server.repository, "add_memory", fake_add_memory)
    result = mcp_server.add_memory(
        "korpus", "findings.md has it", kind="file", path="/tmp/findings.md", item_id=42
    )
    assert seen["path"] == "/tmp/findings.md"
    assert seen["item_id"] == 42
    assert result == {"status": "saved"}


def test_set_status_is_registered_as_a_tool():
    assert mcp_server.mcp._tool_manager.get_tool("set_status") is not None


def test_list_statuses_is_registered_as_a_tool():
    assert mcp_server.mcp._tool_manager.get_tool("list_statuses") is not None


def test_set_status_tool_delegates_to_the_repository(monkeypatch):
    seen = {}

    def fake(slug, item_id, status):
        seen.update(slug=slug, item_id=item_id, status=status)
        return {"status": "set", "from": "todo", "to": "doing"}

    monkeypatch.setattr(mcp_server.repository, "set_status", fake)
    result = mcp_server.set_status("acme", 42, "doing")
    assert seen == {"slug": "acme", "item_id": 42, "status": "doing"}
    assert result == {"status": "set", "from": "todo", "to": "doing"}


def test_set_status_passes_an_unknown_status_straight_through(monkeypatch):
    """The valid list must reach the agent so it can self-correct."""
    monkeypatch.setattr(
        mcp_server.repository,
        "set_status",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    assert mcp_server.set_status("acme", 1, "parked")["valid"] == ["todo", "done"]


def test_list_statuses_tool_delegates_to_the_repository(monkeypatch):
    seen = {}

    def fake(slug):
        seen["slug"] = slug
        return [{"name": "todo", "behaves_as": "open"}]

    monkeypatch.setattr(mcp_server.repository, "list_statuses", fake)
    assert mcp_server.list_statuses("acme") == [{"name": "todo", "behaves_as": "open"}]
    assert seen == {"slug": "acme"}


def test_set_status_docstring_tells_the_agent_to_ask_before_closing():
    # the graduated-ask rule has to be visible where the agent actually reads
    text = mcp_server.set_status.__doc__.lower()
    assert "ask" in text
    assert "close" in text or "closing" in text


def test_the_write_side_tools_are_registered():
    for name in ("add_item", "add_folder", "add_status"):
        assert mcp_server.mcp._tool_manager.get_tool(name) is not None


def test_add_item_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, title, folder_id=None, status=None):
        seen.update(slug=slug, title=title, folder_id=folder_id, status=status)
        return {"status": "added", "item_id": 42}

    monkeypatch.setattr(mcp_server.repository, "add_item", fake)
    result = mcp_server.add_item("acme", "Fix it", folder_id=7, status="doing")
    assert seen == {"slug": "acme", "title": "Fix it", "folder_id": 7, "status": "doing"}
    assert result == {"status": "added", "item_id": 42}


def test_add_item_tool_passes_an_unknown_status_straight_through(monkeypatch):
    """The valid list must survive so the agent can correct itself."""
    monkeypatch.setattr(
        mcp_server.repository,
        "add_item",
        lambda *a, **k: {"status": "unknown_status", "valid": ["todo", "done"]},
    )
    assert mcp_server.add_item("acme", "x", status="nope")["valid"] == ["todo", "done"]


def test_add_folder_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, name, parent_id=None):
        seen.update(slug=slug, name=name, parent_id=parent_id)
        return {"status": "added", "folder_id": 7}

    monkeypatch.setattr(mcp_server.repository, "create_folder", fake)
    result = mcp_server.add_folder("acme", "Bugs", parent_id=3)
    assert seen == {"slug": "acme", "name": "Bugs", "parent_id": 3}
    assert result == {"status": "added", "folder_id": 7}


def test_add_status_tool_delegates_with_every_argument(monkeypatch):
    seen = {}

    def fake(slug, name, behaves_as):
        seen.update(slug=slug, name=name, behaves_as=behaves_as)
        return {"status": "added"}

    monkeypatch.setattr(mcp_server.repository, "add_status", fake)
    result = mcp_server.add_status("acme", "parked", "waiting")
    assert seen == {"slug": "acme", "name": "parked", "behaves_as": "waiting"}
    assert result == {"status": "added"}


def test_add_status_tool_hands_back_the_valid_classes(monkeypatch):
    monkeypatch.setattr(
        mcp_server.repository,
        "add_status",
        lambda *a, **k: {"status": "unknown_class", "valid": ["open", "active", "waiting", "closed"]},
    )
    assert mcp_server.add_status("acme", "x", "diagonal")["valid"] == [
        "open", "active", "waiting", "closed"
    ]


def test_add_status_description_tells_the_agent_to_offer_not_impose():
    """Rule 6 of the coming playbook: offer a new name, do not invent one."""
    text = mcp_server.add_status.__doc__.lower()
    assert "offer" in text or "ask" in text
