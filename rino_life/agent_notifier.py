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

def _agent_url() -> str:
    url = os.environ.get("RINO_AGENT_URL", "http://127.0.0.1:8766").rstrip("/")
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}: raise ValueError("RINO_AGENT_URL must use a loopback host")
    return url

def agent_chat_notifier(notification: dict[str, Any]) -> None:
    """Router notifier: queue consumable-low messages; failures are logged and never raised."""
    if not str(notification.get("dedupe_key", "")).startswith("consumable-low:"): return
    try:
        token = os.environ.get("RINO_AGENT_API_TOKEN")
        if not token: raise RuntimeError("RINO_AGENT_API_TOKEN is not configured")
        body = json.dumps({"dedupe_key": notification["dedupe_key"], "message": consumable_low_message(notification["payload"])}, ensure_ascii=False).encode("utf-8")
        request = Request(f"{_agent_url()}/internal/notifications", data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response: response.read()
    except Exception as error:
        LOG.warning("chat notification delivery failed", extra={"dedupe_key": notification.get("dedupe_key"), "error": str(error)})
