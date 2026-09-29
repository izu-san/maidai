"""Private OBS MCP adapter; uses OBS WebSocket, never GUI automation."""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from obsws_python import ReqClient

mcp = FastMCP("rino-obs", instructions="Private OBS WebSocket adapter.")


def client() -> ReqClient:
    return ReqClient(host=os.environ.get("RINO_OBS_HOST", "127.0.0.1"), port=int(os.environ.get("RINO_OBS_PORT", "4455")), password=os.environ.get("RINO_OBS_PASSWORD", ""), timeout=5)


@mcp.tool(name="obs.get_status")
def get_status() -> dict:
    obs = client()
    stream, recording = obs.get_stream_status(), obs.get_record_status()
    scene = obs.get_current_program_scene()
    return {
        "streaming": bool(stream.output_active),
        "recording": bool(recording.output_active),
        "scene": scene.current_program_scene_name,
        "verification": {"status": "VERIFIED", "source": "obs.websocket"},
    }


def require_status(expected: str, enabled: bool) -> dict:
    status = get_status()
    if status[expected] is not enabled:
        raise RuntimeError(f"OBS {expected} state could not be verified.")
    return status


@mcp.tool(name="obs.start_stream")
def start_stream() -> dict:
    client().start_stream()
    return require_status("streaming", True)


@mcp.tool(name="obs.stop_stream")
def stop_stream() -> dict:
    client().stop_stream()
    return require_status("streaming", False)


@mcp.tool(name="obs.start_recording")
def start_recording() -> dict:
    client().start_record()
    return require_status("recording", True)


@mcp.tool(name="obs.stop_recording")
def stop_recording() -> dict:
    client().stop_record()
    return require_status("recording", False)


@mcp.tool(name="obs.set_scene")
def set_scene(scene: str) -> dict:
    if not scene or len(scene) > 128:
        raise ValueError("Invalid scene name.")
    client().set_current_program_scene(scene_name=scene)
    status = get_status()
    if status["scene"] != scene:
        raise RuntimeError("OBS scene could not be verified.")
    return status


if __name__ == "__main__":
    mcp.run(transport="stdio")
