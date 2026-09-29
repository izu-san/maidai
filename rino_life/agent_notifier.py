"""Deliver Life notification decisions to the chat UI through the Agent Service inbox.

The Agent Service only queues the text for display; nothing here starts an Agent run.
"""
from __future__ import annotations
import json, logging, os
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)

def _amount(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"

def consumable_low_message(payload: dict[str, Any]) -> str:
    unit = payload.get("unit", "")
    return f"{payload['name']}の残りが{_amount(payload['remaining'])}{unit}になりました（通知の目安は{_amount(payload['threshold'])}{unit}）。そろそろ買い足しませんか？"

def _gib(value: Any) -> str:
    return f"{float(value) / 1024 ** 3:.1f}GB"

def pc_storage_low_message(payload: dict[str, Any]) -> str:
    return f"PCの{payload['path']}の空き容量が{_gib(payload['free_bytes'])}まで減っています（目安は{_gib(payload['threshold_bytes'])}）。不要なファイルを整理しませんか？"

def pc_cpu_high_message(payload: dict[str, Any]) -> str:
    return f"PCのCPU使用率が{_amount(payload['usage_percent'])}%の状態が続いています（目安は{_amount(payload['threshold_percent'])}%）。重い処理が動いていないか見てみませんか？"

def pc_memory_high_message(payload: dict[str, Any]) -> str:
    return f"PCのメモリ使用率が{_amount(payload['usage_percent'])}%の状態が続いています（目安は{_amount(payload['threshold_percent'])}%）。使っていないアプリを閉じてみませんか？"

def pc_service_failed_message(payload: dict[str, Any]) -> str:
    return f"PCのWindowsサービス「{payload['service']}」が止まった状態が続いています。PCの状態を確認してみてください。"

def pc_hardware_error_message(payload: dict[str, Any]) -> str:
    return f"PCのシステムログにハードウェア関連のエラーが記録されました（{payload['code']}）。ディスクや電源まわりの不調かもしれないので、早めに確認してください。"

def switchbot_message(payload: dict[str, Any]) -> str:
    kind, value, limit = payload["kind"], payload.get("value"), payload.get("limit")
    if kind == "co2_high": return f"部屋のCO2濃度が{_amount(value)}ppmまで上がっています（目安は{_amount(limit)}ppm）。窓を開けて換気しませんか？"
    if kind == "temperature_high": return f"部屋の温度が{_amount(value)}℃まで上がっています。熱中症に気をつけて、エアコンを使いませんか？"
    if kind == "temperature_low": return f"部屋の温度が{_amount(value)}℃まで下がっています。暖かくして過ごしてくださいね。"
    if kind == "humidity_low": return f"部屋の湿度が{_amount(value)}%まで下がっています。乾燥しているので、加湿しませんか？"
    if kind == "humidity_high": return f"部屋の湿度が{_amount(value)}%まで上がっています。除湿や換気をしませんか？"
    state = payload.get("state", {})
    if kind == "door_unlocked": return f"玄関の鍵が{state.get('unlocked_minutes', _amount(limit))}分以上開いたままです。施錠しますか？"
    if kind == "door_open": return f"玄関のドアが{state.get('open_minutes', _amount(limit))}分以上開いたままです。閉め忘れていませんか？"
    return "玄関の鍵が動作の途中で止まっているようです（ジャム）。手動で状態を確認してください。"

# dedupe_key prefix -> message builder; only these kinds reach the chat inbox.
_MESSAGES = {
    "consumable-low:": consumable_low_message,
    "pc.storage_low.v1:": pc_storage_low_message,
    "pc.cpu_high.v1:": pc_cpu_high_message,
    "pc.memory_high.v1:": pc_memory_high_message,
    "pc.service_failed.v1:": pc_service_failed_message,
    "pc.hardware_error.v1:": pc_hardware_error_message,
    "switchbot.": switchbot_message,
}

def _agent_url() -> str:
    url = os.environ.get("RINO_AGENT_URL", "http://127.0.0.1:8766").rstrip("/")
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}: raise ValueError("RINO_AGENT_URL must use a loopback host")
    return url

def agent_chat_notifier(notification: dict[str, Any]) -> None:
    """Router notifier: queue consumable-low and PC health messages; failures are logged and never raised."""
    key = str(notification.get("dedupe_key", ""))
    build = next((builder for prefix, builder in _MESSAGES.items() if key.startswith(prefix)), None)
    if build is None: return
    try:
        token = os.environ.get("RINO_AGENT_API_TOKEN")
        if not token: raise RuntimeError("RINO_AGENT_API_TOKEN is not configured")
        body = json.dumps({"dedupe_key": notification["dedupe_key"], "message": build(notification["payload"])}, ensure_ascii=False).encode("utf-8")
        request = Request(f"{_agent_url()}/internal/notifications", data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response: response.read()
    except Exception as error:
        LOG.warning("chat notification delivery failed", extra={"dedupe_key": notification.get("dedupe_key"), "error": str(error)})
