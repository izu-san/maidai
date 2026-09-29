import asyncio

from rino_mcp.comfyui.server import mcp as comfyui
from rino_mcp.obs.server import mcp as obs
from rino_mcp.windows.server import mcp as windows
from rino_mcp.comfyui import server as comfyui_server
import pytest


def names(server):
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_obs_uses_only_websocket_operations():
    assert names(obs) == {"obs.get_status", "obs.start_stream", "obs.stop_stream", "obs.start_recording", "obs.stop_recording", "obs.set_scene"}


def test_comfyui_uses_only_documented_api_operations():
    assert names(comfyui) == {"comfyui.get_status", "comfyui.list_workflows", "comfyui.open_workflow", "comfyui.queue_prompt", "comfyui.cancel_prompt", "comfyui.get_history"}


def test_windows_has_no_arbitrary_execution_tool():
    published = names(windows)
    assert {"shell.run_arbitrary", "powershell.run_arbitrary", "cmd.run_arbitrary", "registry.write_arbitrary"}.isdisjoint(published)
    assert {"process.check", "app.launch", "app.close", "system.get_volume", "system.set_volume", "screenshot.capture", "file.exists", "file.open"}.issubset(published)


def test_comfyui_rejects_invalid_prompt_ids_and_marks_accepted_queue(monkeypatch):
    with pytest.raises(ValueError):
        comfyui_server.cancel_prompt("../not-an-id")
    monkeypatch.setattr(comfyui_server, "request", lambda path, data=None: {"prompt_id": "safe-id"})
    assert comfyui_server.queue_prompt({"1": {}})["verification"]["status"] == "VERIFIED"
