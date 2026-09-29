import asyncio

from rino_mcp.switchbot.server import mcp


def test_only_allowlisted_tools_are_published():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert "home.unlock_door" not in names
    assert names == {
        "home.get_environment", "home.light_on", "home.light_off",
        "home.aircon_on", "home.aircon_off", "home.set_temperature",
        "home.tv_on", "home.tv_off", "home.get_door_status", "home.lock_door",
    }
