"""Start-MaidAI.ps1 との入出力（Qt 非依存）。

サービスのポート・起動ファイル等の定義は持たない。名前は `-Status -Json` の結果だけを信頼する。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "Start-MaidAI.ps1"
PROFILES = ("chat", "voice", "full", "docker")
ACTIONS = ("start", "stop", "restart")
STATES = ("running", "loading", "stopped", "missing", "unavailable")

_BASE = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)]


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    kind: str
    port: int
    state: str
    pid: int | None = None
    process: str | None = None


def parse_status(text: str) -> list[ServiceStatus]:
    """`-Status -Json` の出力を解釈する。不正な入力は ValueError。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid status JSON: {exc}") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("status JSON must be a list")
    result: list[ServiceStatus] = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("status entry needs a string 'name'")
        state = item.get("state")
        result.append(
            ServiceStatus(
                name=item["name"],
                kind=str(item.get("kind") or "process"),
                port=int(item.get("port") or 0),
                state=state if state in STATES else "unavailable",
                pid=item.get("pid"),
                process=item.get("process"),
            )
        )
    return result


def build_status_args() -> list[str]:
    return [*_BASE, "-Status", "-Json"]


def build_action_args(name: str, action: str, known: set[str]) -> list[str]:
    """既知のコンポーネント名と許可済み操作のみ受け付ける。"""
    if name not in known:
        raise ValueError(f"unknown component: {name}")
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    return [*_BASE, "-Component", name, "-Action", action]


def build_profile_args(profile: str) -> list[str]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    return [*_BASE, "-Profile", profile]


def build_stop_all_args() -> list[str]:
    return [*_BASE, "-Stop"]
