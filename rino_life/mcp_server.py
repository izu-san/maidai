"""Private stdio MCP boundary for the Life API domain.

All state changes go through the loopback Life API. This process deliberately
has neither database nor NATS credentials.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rino-life")
_API_URL = os.environ.get("RINO_LIFE_API_URL", "http://127.0.0.1:54330").rstrip("/")

def _request(path: str, *, body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(f"{_API_URL}{path}", data=payload, headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:1_000]
        raise ValueError(f"Life API rejected the request ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError("Life API is unavailable; start the local Rino Life API before using life tools.") from error

def _event(type: str, payload: dict) -> dict:
    return _request("/events", body={"type": type, "payload": payload, "source": "rino-agent"})

@mcp.tool(name="life.record_laundry_completed")
def record_laundry_completed(count: int = 1) -> dict:
    """Record one or more completed laundry loads."""
    return _event("life.laundry.completed.v1", {"count": count})
@mcp.tool(name="life.get_consumable_state")
def get_consumable_state(item_id: str) -> dict: return _request(f"/consumables/{item_id}")
@mcp.tool(name="life.list_low_stock_items")
def list_low_stock_items() -> list[dict]: return _request("/consumables/low")["items"]
@mcp.tool(name="life.list_consumables")
def list_consumables() -> list[dict]: return _request("/consumables")["items"]
@mcp.tool(name="life.adjust_consumable")
def adjust_consumable(item_id: str, remaining: float, estimated: bool = True) -> dict: return _event("life.consumable.adjusted.v1", {"item_id": item_id, "remaining": remaining, "estimated": estimated})
@mcp.tool(name="life.record_purchase")
def record_purchase(item_id: str, quantity: int) -> dict: return _event("life.consumable.purchased.v1", {"item_id": item_id, "quantity": quantity})
@mcp.tool(name="life.record_opened_item")
def record_opened_item(item_id: str) -> dict: return _event("life.consumable.opened.v1", {"item_id": item_id})
@mcp.tool(name="life.register_consumable")
def register_consumable(item_id: str, name: str, category: str, unit: str, capacity: float, remaining: float | None = None, stock_unopened: int = 0, usage_model: dict | None = None, reminder: dict | None = None) -> dict:
    payload = {"item_id": item_id, "name": name, "category": category, "unit": unit, "capacity": capacity, "stock_unopened": stock_unopened, "usage_model": usage_model or {}, "reminder": reminder or {}}
    if remaining is not None: payload["remaining"] = remaining
    return _event("life.consumable.registered.v1", payload)
@mcp.tool(name="life.deactivate_consumable")
def deactivate_consumable(item_id: str, reason: str | None = None) -> dict:
    payload = {"item_id": item_id}
    if reason: payload["reason"] = reason
    return _event("life.consumable.deactivated.v1", payload)

if __name__ == "__main__": mcp.run()
