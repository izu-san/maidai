"""Private ComfyUI HTTP API adapter with bounded workflow access."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rino-comfyui", instructions="Private ComfyUI API adapter.")
BASE_URL = os.environ.get("RINO_COMFYUI_URL", "http://127.0.0.1:8188")
WORKFLOW_DIR = Path(os.environ.get("RINO_COMFYUI_WORKFLOW_DIR", "D:/AI/ComfyUI_windows_portable/ComfyUI/user/default/workflows"))
_PROMPT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validated_base_url() -> str:
    parsed = urlparse(BASE_URL)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ComfyUI endpoint must use loopback HTTP.")
    return BASE_URL.rstrip("/")


def request(path: str, data: dict | None = None) -> dict:
    body = None if data is None else json.dumps(data).encode()
    req = Request(f"{validated_base_url()}{path}", data=body, headers={"Content-Type": "application/json"} if body else {})
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read())


@mcp.tool(name="comfyui.get_status")
def get_status() -> dict:
    return request("/system_stats")


@mcp.tool(name="comfyui.list_workflows")
def list_workflows() -> dict:
    return {"workflows": sorted(path.stem for path in WORKFLOW_DIR.glob("*.json"))}


@mcp.tool(name="comfyui.open_workflow")
def open_workflow(name: str) -> dict:
    path = (WORKFLOW_DIR / f"{name}.json").resolve()
    if path.parent != WORKFLOW_DIR.resolve() or not path.is_file():
        raise ValueError("Workflow not found.")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Workflow exceeds the 2 MiB safety limit.")
    return {"name": name, "workflow": json.loads(path.read_text(encoding="utf-8")), "verification": {"status": "VERIFIED", "source": "local-file"}}


@mcp.tool(name="comfyui.queue_prompt")
def queue_prompt(prompt: dict) -> dict:
    if len(json.dumps(prompt, ensure_ascii=False).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Prompt exceeds the 2 MiB safety limit.")
    result = request("/prompt", {"prompt": prompt, "client_id": "rino-agent"})
    if not result.get("prompt_id"):
        raise RuntimeError("ComfyUI did not return a prompt ID for the queued prompt.")
    return {**result, "verification": {"status": "VERIFIED", "source": "comfyui.api"}}


@mcp.tool(name="comfyui.cancel_prompt")
def cancel_prompt(prompt_id: str) -> dict:
    if not _PROMPT_ID.fullmatch(prompt_id):
        raise ValueError("Invalid prompt ID.")
    return request("/queue", {"delete": [prompt_id]})


@mcp.tool(name="comfyui.get_history")
def get_history(prompt_id: str) -> dict:
    if not _PROMPT_ID.fullmatch(prompt_id):
        raise ValueError("Invalid prompt ID.")
    return request(f"/history/{prompt_id}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
