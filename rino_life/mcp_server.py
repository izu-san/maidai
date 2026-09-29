"""Private stdio MCP boundary for the Life API domain.

All state changes go through the loopback Life API. This process deliberately
has neither database nor NATS credentials.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
import re
from zoneinfo import ZoneInfo
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
    """Register a consumable. Use one unit throughout: convert kg to g and L to ml before calling (2 kg = capacity 2000, unit g); capacity, remaining, reminder and usage amounts are all in that unit. item_id is lowercase ASCII snake_case (e.g. cat_food). reminder={"remaining_below": N} notifies when remaining <= N (in the item's unit); ask the user for N. usage_model={"type": "PER_DAY", "amount": N} deducts N (in the item's unit) every day starting from the registration day; usage_model={"type": "PER_EVENT", "event": "laundry.completed", "amount": N} deducts N per reported laundry load; omit usage_model for manually tracked items."""
    payload = {"item_id": item_id, "name": name, "category": category, "unit": unit, "capacity": capacity, "stock_unopened": stock_unopened, "usage_model": usage_model or {}, "reminder": reminder or {}}
    if remaining is not None: payload["remaining"] = remaining
    return _event("life.consumable.registered.v1", payload)
@mcp.tool(name="life.deactivate_consumable")
def deactivate_consumable(item_id: str, reason: str | None = None) -> dict:
    payload = {"item_id": item_id}
    if reason: payload["reason"] = reason
    return _event("life.consumable.deactivated.v1", payload)

def _finance_payload(kind: str, amount_yen: int, category: str, occurred_on: str | None, note: str | None) -> dict:
    payload = {"kind": kind, "amount_yen": amount_yen, "category": category, "occurred_on": occurred_on or datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()}
    if note: payload["note"] = note
    return payload

@mcp.tool(name="life.record_finance_transaction")
def record_finance_transaction(kind: str, amount_yen: int, category: str, occurred_on: str | None = None, note: str | None = None) -> dict:
    """Record an approved Japanese-yen expense or income. Expense categories: 食費、日用品、住居、光熱、通信、交通、医療、保険、被服、娯楽、教育、定期購入、贈答、特別支出、その他. Income categories: 給与、賞与、副収入、返金、贈与、その他. Date defaults to today in Japan."""
    return _event("life.finance.transaction_recorded.v1", _finance_payload(kind, amount_yen, category, occurred_on, note))

@mcp.tool(name="life.correct_finance_transaction")
def correct_finance_transaction(transaction_id: str, kind: str, amount_yen: int, category: str, occurred_on: str, note: str | None = None) -> dict:
    """Correct an existing approved ledger transaction using its ID and complete replacement details."""
    payload = {"transaction_id": transaction_id, **_finance_payload(kind, amount_yen, category, occurred_on, note)}
    return _event("life.finance.transaction_corrected.v1", payload)

@mcp.tool(name="life.cancel_finance_transaction")
def cancel_finance_transaction(transaction_id: str, reason: str | None = None) -> dict:
    """Cancel an existing approved ledger transaction while preserving its audit history."""
    payload = {"transaction_id": transaction_id}
    if reason: payload["reason"] = reason
    return _event("life.finance.transaction_cancelled.v1", payload)

def _finance_month(month: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month): raise ValueError("month must be YYYY-MM")
    return month

@mcp.tool(name="life.get_monthly_finance_summary")
def get_monthly_finance_summary(month: str) -> dict: return _request(f"/finance/summary/{_finance_month(month)}")

@mcp.tool(name="life.list_finance_transactions")
def list_finance_transactions(month: str, limit: int = 100) -> list[dict]:
    """List up to 100 ledger transactions in the specified YYYY-MM month."""
    if not 1 <= limit <= 100: raise ValueError("limit must be 1..100")
    return _request(f"/finance/transactions/{_finance_month(month)}?limit={limit}")["items"]

if __name__ == "__main__": mcp.run()
