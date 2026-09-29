"""Start-MaidAI.ps1 との入出力（Qt 非依存）。

サービスのポート・起動ファイル等の定義は持たない。名前は `-Status -Json` の結果だけを信頼する。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "Start-MaidAI.ps1"
LOG_DIR = ROOT / "logs" / "services"
PROFILES = ("chat", "voice", "full", "docker")
ACTIONS = ("start", "stop", "restart", "log")
STATES = ("running", "loading", "stopped", "missing", "unavailable")
HEALTHS = ("ok", "fail")
GPU_ARGS = [
    "--query-gpu=name,memory.used,memory.total,utilization.gpu",
    "--format=csv,noheader,nounits",
]

_BASE = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)]


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    kind: str
    port: int
    state: str
    pid: int | None = None
    process: str | None = None
    started_at: datetime | None = None  # 最終起動時刻（タイムゾーン付き）。不明は None
    health: str | None = None  # 稼働中の応答確認。"ok" / "fail"、確認手段がなければ None
    open_url: str | None = None  # ブラウザで開ける loopback URL
    profiles: tuple[str, ...] = field(default_factory=tuple)  # このコンポーネントを起動するプロファイル


@dataclass(frozen=True)
class GpuInfo:
    name: str
    used_mb: int
    total_mb: int
    util_percent: int


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_elapsed(started_at: datetime, now: datetime | None = None) -> str:
    """経過時間を短く表す（例: 45秒 / 12分 / 3時間5分 / 2日4時間）。未来時刻は 0秒。"""
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - started_at).total_seconds()))
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if days:
        return f"{days}日{hours % 24}時間"
    if hours:
        return f"{hours}時間{minutes % 60}分"
    if minutes:
        return f"{minutes}分"
    return f"{seconds}秒"


def _safe_url(value: object) -> str | None:
    """ウィジェットが開いてよいのは loopback の http URL だけ。"""
    if isinstance(value, str) and (value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")):
        return value
    return None


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
        health = item.get("health")
        pid = item.get("pid")
        profiles = item.get("profiles")
        result.append(
            ServiceStatus(
                name=item["name"],
                kind=str(item.get("kind") or "process"),
                port=int(item.get("port") or 0),
                state=state if state in STATES else "unavailable",
                pid=pid if isinstance(pid, int) else None,
                process=item.get("process"),
                started_at=_parse_time(item.get("started_at")),
                health=health if health in HEALTHS else None,
                open_url=_safe_url(item.get("open_url")),
                profiles=tuple(p for p in profiles if p in PROFILES) if isinstance(profiles, list) else (),
            )
        )
    return result


def profile_states(statuses: list[ServiceStatus]) -> dict[str, str]:
    """プロファイルごとの充足状態。ready=全て稼働（応答異常なし）、partial=一部稼働、off=なし。"""
    result: dict[str, str] = {}
    for profile in PROFILES:
        members = [s for s in statuses if profile in s.profiles and s.kind != "project"]
        running = [s for s in members if s.state == "running"]
        if not members or not running:
            result[profile] = "off"
        elif len(running) == len(members) and not any(s.health == "fail" for s in running):
            result[profile] = "ready"
        else:
            result[profile] = "partial"
    return result


def detect_problems(previous: dict[str, ServiceStatus] | None, current: dict[str, ServiceStatus]) -> list[str]:
    """前回の状態と比べ、新たに停止した／応答しなくなったサービスの通知文を返す。

    初回（previous が None）は基準にするだけで何も返さない。Compose プロジェクト行は
    メンバーコンテナと重複するため対象外。
    """
    if previous is None:
        return []
    messages: list[str] = []
    for name, now in current.items():
        before = previous.get(name)
        if before is None or now.kind == "project":
            continue
        if before.state in ("running", "loading") and now.state in ("stopped", "missing", "unavailable"):
            messages.append(f"{name} が停止しました")
        elif now.state == "running" and now.health == "fail" and before.health != "fail" and before.state == "running":
            messages.append(f"{name} が応答しません")
    return messages


def parse_gpu(text: str) -> GpuInfo | None:
    """`nvidia-smi` の csv 出力（先頭の GPU）を解釈する。解釈できなければ None。"""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        return GpuInfo(parts[0], int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def parse_log_path(output: str) -> Path | None:
    """`-Action log` の出力の最終行を、ログ用ディレクトリ配下のパスとして検証して返す。"""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        path = Path(lines[-1]).resolve()
        path.relative_to(LOG_DIR.resolve())
    except (ValueError, OSError):
        return None
    return path


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
