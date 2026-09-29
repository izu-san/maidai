"""Private Windows adapter. No generic shell, registry, mouse, or keyboard tool."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from subprocess import Popen

import psutil
from PIL import ImageGrab
from pycaw.pycaw import AudioUtilities
from rino_agent.storage import ensure_private_directory
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rino-windows", instructions="Allowlisted local Windows adapter.")
APPS = json.loads(os.environ.get("RINO_WINDOWS_ALLOWED_APPS", "{}"))
ROOTS = [Path(path).resolve() for path in os.environ.get("RINO_WINDOWS_ALLOWED_ROOTS", "D:/AI/MaidAI").split(";")]
SCREENSHOT_DIR = Path(os.environ.get("RINO_SCREENSHOT_DIR", "D:/AI/MaidAI/rino_agent/data/screenshots")).resolve()


def allowed_path(path: str) -> Path:
    candidate = Path(path).resolve()
    if not any(root == candidate or root in candidate.parents for root in ROOTS):
        raise ValueError("Path is outside allowed roots.")
    return candidate


@mcp.tool(name="process.check")
def process_check(name: str) -> dict:
    return {"name": name, "running": any(process.info["name"].lower() == name.lower() for process in psutil.process_iter(["name"]))}


@mcp.tool(name="app.launch")
def app_launch(name: str) -> dict:
    executable = APPS.get(name)
    if not executable or not Path(executable).is_file():
        raise ValueError("Application is not allowlisted.")
    process = Popen([executable], close_fds=True)
    time.sleep(0.1)
    if process.poll() is not None:
        raise RuntimeError("Allowlisted application exited before launch could be verified.")
    return {"name": name, "pid": process.pid, "verification": {"status": "VERIFIED", "source": "child-process"}}


@mcp.tool(name="app.close")
def app_close(name: str) -> dict:
    executable = APPS.get(name)
    if not executable or not Path(executable).is_file():
        raise ValueError("Application is not allowlisted.")
    expected_name = Path(executable).name.lower()
    killed = 0
    for process in psutil.process_iter(["name"]):
        if process.info["name"].lower() == expected_name:
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired as error:
                raise RuntimeError("Allowlisted application did not exit after termination request.") from error
            killed += 1
    still_running = any(process.info["name"].lower() == expected_name for process in psutil.process_iter(["name"]))
    if still_running:
        raise RuntimeError("Allowlisted application close could not be verified.")
    return {"name": name, "terminated": killed, "verification": {"status": "VERIFIED", "source": "process.list"}}


@mcp.tool(name="system.get_volume")
def get_volume() -> dict:
    endpoint = AudioUtilities.GetSpeakers().EndpointVolume
    return {"volume": round(endpoint.GetMasterVolumeLevelScalar() * 100)}


@mcp.tool(name="system.set_volume")
def set_volume(percent: int) -> dict:
    if not 0 <= percent <= 100:
        raise ValueError("Volume must be between 0 and 100.")
    AudioUtilities.GetSpeakers().EndpointVolume.SetMasterVolumeLevelScalar(percent / 100, None)
    result = get_volume()
    if abs(result["volume"] - percent) > 1:
        raise RuntimeError("System volume could not be verified.")
    return {**result, "verification": {"status": "VERIFIED", "source": "windows.audio"}}


@mcp.tool(name="screenshot.capture")
def screenshot_capture() -> dict:
    ensure_private_directory(SCREENSHOT_DIR)
    path = SCREENSHOT_DIR / f"capture-{time.time_ns()}.png"
    ImageGrab.grab().save(path)
    return {"path": str(path), "verified": path.is_file()}


@mcp.tool(name="file.exists")
def file_exists(path: str) -> dict:
    candidate = allowed_path(path)
    return {"exists": candidate.exists()}


@mcp.tool(name="file.open")
def file_open(path: str) -> dict:
    candidate = allowed_path(path)
    if not candidate.is_file():
        raise ValueError("File not found.")
    os.startfile(candidate)
    return {"command_sent": True, "path": str(candidate), "verification": {"status": "UNAVAILABLE", "reason": "Windows does not expose a reliable acknowledgement from the associated application."}}


if __name__ == "__main__":
    mcp.run(transport="stdio")
