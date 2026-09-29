"""MAF-owned lifecycle for trusted private stdio MCP child processes."""
from __future__ import annotations

import sys
import os
from contextlib import AsyncExitStack

from agent_framework import MCPStdioTool

_COMMANDS = {
    "switchbot": "rino_mcp.switchbot.server",
    "life": "rino_life.mcp_server",
    "obs": "rino_mcp.obs.server",
    "comfyui": "rino_mcp.comfyui.server",
    "windows": "rino_mcp.windows.server",
}
_LIFE_TOOLS = {
    "life.get_consumable_state", "life.list_low_stock_items", "life.list_consumables",
    "life.record_laundry_completed", "life.record_purchase", "life.record_opened_item",
    "life.adjust_consumable", "life.register_consumable", "life.deactivate_consumable",
    "life.record_finance_transaction", "life.correct_finance_transaction", "life.cancel_finance_transaction",
    "life.get_monthly_finance_summary", "life.list_finance_transactions",
}
_SWITCHBOT_TOOLS = {
    "home.get_environment", "home.light_on", "home.light_off", "home.aircon_on", "home.aircon_off",
    "home.set_temperature", "home.tv_on", "home.tv_off", "home.get_door_status", "home.lock_door",
}
_APPROVAL_POLICIES = {
    "obs": {
        "always_require_approval": ["obs.start_stream", "obs.stop_stream", "obs.start_recording", "obs.stop_recording"],
        "never_require_approval": ["obs.get_status", "obs.set_scene"],
    },
    "comfyui": {
        "always_require_approval": ["comfyui.queue_prompt", "comfyui.cancel_prompt"],
        "never_require_approval": ["comfyui.get_status", "comfyui.list_workflows", "comfyui.open_workflow", "comfyui.get_history"],
    },
    "windows": {
        "always_require_approval": ["app.launch", "app.close", "file.open"],
        "never_require_approval": ["process.check", "system.get_volume", "system.set_volume", "screenshot.capture", "file.exists"],
    },
}
_BASE_CHILD_ENV = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE")
_SERVER_ENV = {
    "switchbot": ("SWITCHBOT_TOKEN", "SWITCHBOT_SECRET", "SWITCHBOT_CO2_DEVICE_ID", "SWITCHBOT_LIGHT_DEVICE_ID", "SWITCHBOT_AIRCON_DEVICE_ID", "SWITCHBOT_TV_DEVICE_ID", "SWITCHBOT_LOCK_DEVICE_ID"),
    "life": ("RINO_LIFE_API_URL",),
    "obs": ("RINO_OBS_HOST", "RINO_OBS_PORT", "RINO_OBS_PASSWORD"),
    "comfyui": ("RINO_COMFYUI_URL", "RINO_COMFYUI_WORKFLOW_DIR"),
    "windows": ("RINO_WINDOWS_ALLOWED_APPS", "RINO_WINDOWS_ALLOWED_ROOTS", "RINO_SCREENSHOT_DIR"),
}


def child_environment(server_name: str) -> dict[str, str]:
    """Do not leak Agent/API credentials to unrelated MCP child processes."""
    names = (*_BASE_CHILD_ENV, *_SERVER_ENV[server_name])
    return {name: os.environ[name] for name in names if name in os.environ}


async def connect_servers(servers: dict[str, dict]) -> tuple[AsyncExitStack, dict[str, MCPStdioTool]]:
    stack = AsyncExitStack()
    tools: dict[str, MCPStdioTool] = {}
    try:
        for name in servers:
            module = _COMMANDS.get(name)
            if module is None:
                raise ValueError(f"Unsupported MCP server: {name}")
            if name == "switchbot":
                tool = MCPStdioTool(
                    name, command=sys.executable, args=["-m", module], allowed_tools=_SWITCHBOT_TOOLS,
                    env=child_environment(name),
                    approval_mode={
                        "always_require_approval": ["home.lock_door", "home.set_temperature", "home.tv_on"],
                        "never_require_approval": sorted(_SWITCHBOT_TOOLS - {"home.lock_door", "home.set_temperature", "home.tv_on"}),
                    },
                )
            elif name == "life":
                tool = MCPStdioTool(
                    name, command=sys.executable, args=["-m", module], allowed_tools=_LIFE_TOOLS,
                    env=child_environment(name),
                    approval_mode={
                        "always_require_approval": ["life.register_consumable", "life.deactivate_consumable", "life.record_finance_transaction", "life.correct_finance_transaction", "life.cancel_finance_transaction"],
                        "never_require_approval": sorted(_LIFE_TOOLS - {"life.register_consumable", "life.deactivate_consumable", "life.record_finance_transaction", "life.correct_finance_transaction", "life.cancel_finance_transaction"}),
                    },
                )
            else:
                tool = MCPStdioTool(name, command=sys.executable, args=["-m", module], env=child_environment(name), approval_mode=_APPROVAL_POLICIES[name])
            tools[name] = await stack.enter_async_context(tool)
        return stack, tools
    except Exception:
        await stack.aclose()
        raise
