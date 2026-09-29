import asyncio

from rino_agent.main import lifespan
from rino_agent.mcp import _APPROVAL_POLICIES, _LIFE_TOOLS, child_environment


class App:
    class State:
        pass

    state = State()


def test_service_connects_only_to_allowlisted_switchbot_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("SWITCHBOT_TOKEN", "test")
    monkeypatch.setenv("SWITCHBOT_SECRET", "test")
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "test")
    monkeypatch.setenv("RINO_AGENT_DATA_DIR", str(tmp_path / "data"))
    app = App()

    async def check():
        async with lifespan(app):
            names = {tool.name for tool in app.state.switchbot_mcp.functions}
            assert "home.unlock_door" not in names
            assert "home.lock_door" in names
            assert "life.record_laundry_completed" in {tool.name for tool in app.state.mcp_servers["life"].functions}

    asyncio.run(check())


def test_future_mcp_approval_maps_keep_read_only_tools_automatic():
    assert "obs.get_status" in _APPROVAL_POLICIES["obs"]["never_require_approval"]
    assert "comfyui.get_status" in _APPROVAL_POLICIES["comfyui"]["never_require_approval"]
    assert "process.check" in _APPROVAL_POLICIES["windows"]["never_require_approval"]
    assert "app.close" in _APPROVAL_POLICIES["windows"]["always_require_approval"]


def test_mcp_children_do_not_receive_agent_secret(monkeypatch):
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "must-not-leak")
    monkeypatch.setenv("SWITCHBOT_TOKEN", "switchbot-only")
    assert "RINO_AGENT_API_TOKEN" not in child_environment("switchbot")
    assert child_environment("switchbot")["SWITCHBOT_TOKEN"] == "switchbot-only"
    assert "SWITCHBOT_TOKEN" not in child_environment("obs")


def test_life_mcp_exposes_only_named_domain_tools():
    assert "life.emit_life_event" not in _LIFE_TOOLS
    assert "life.register_consumable" in _LIFE_TOOLS
