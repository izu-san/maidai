"""Bounded life-context adapter for the Agent prompt boundary."""
from __future__ import annotations
from typing import Any, Callable

def build_life_context(consumables: list[Any], notifications: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose current facts and pending candidates, never raw event payloads or DB handles."""
    return {
        "consumables": [{"id": x.id, "name": x.name, "remaining": x.remaining, "unit": x.unit,
                         "capacity": x.capacity, "estimated": x.estimated} for x in consumables],
        "notification_candidates": [
            {"dedupe_key": n["dedupe_key"], "priority": n["priority"], "status": n["status"],
             "reason": n.get("reason", {})} for n in notifications if n.get("status") in {"sent", "acknowledged"}
        ],
    }

class LifeContextProvider:
    def __init__(self, consumable_service: Any, connect: Callable[..., Any], dsn: str):
        self._consumables, self._connect, self._dsn = consumable_service, connect, dsn

    def get(self) -> dict[str, Any]:
        with self._connect(self._dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT dedupe_key,priority,status,reason FROM notification_history WHERE status IN ('sent','acknowledged') ORDER BY priority DESC,last_event_at DESC LIMIT 20")
            notices = [{"dedupe_key": r[0], "priority": r[1], "status": r[2], "reason": r[3]} for r in cursor.fetchall()]
        return build_life_context(self._consumables.list_low_stock(), notices)
