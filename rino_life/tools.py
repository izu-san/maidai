"""Narrow tool facade for an LLM integration; it never exposes DB or NATS handles."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from .consumables import ConsumableService
from .contracts import LifeEventEnvelope

class LifeTools:
    def __init__(self, service: ConsumableService): self._service = service
    def emit_life_event(self, type: str, payload: dict, confidence: float = 1.0, source: str = "chat") -> list[dict]:
        event = LifeEventEnvelope(id=uuid4(), type=type, occurred_at=datetime.now(timezone.utc), source=source, confidence=confidence, payload=payload)
        return [item.snapshot() | {"id": item.id} for item in self._service.apply(type, event)]
    def get_consumable_state(self, item_id: str):
        item = self._service.get(item_id)
        return None if not item else item.snapshot() | {"id":item.id,"capacity":item.capacity,"unit":item.unit}
    def list_low_stock_items(self): return [self.get_consumable_state(item.id) for item in self._service.list_low_stock()]
    def list_consumables(self): return [item.snapshot() | {"id":item.id,"name":item.name,"category":item.category,"capacity":item.capacity,"unit":item.unit} for item in self._service.list_active()]
    def adjust_consumable(self, item_id: str, remaining: float, estimated: bool = True): return self.emit_life_event("life.consumable.adjusted.v1", {"item_id":item_id,"remaining":remaining,"estimated":estimated})
    def record_purchase(self, item_id: str, quantity: int): return self.emit_life_event("life.consumable.purchased.v1", {"item_id":item_id,"quantity":quantity})
    def record_opened_item(self, item_id: str): return self.emit_life_event("life.consumable.opened.v1", {"item_id":item_id})
    def register_consumable(self, item_id: str, name: str, category: str, unit: str, capacity: float, remaining: float | None = None, stock_unopened: int = 0, usage_model: dict | None = None, reminder: dict | None = None):
        payload = {"item_id":item_id,"name":name,"category":category,"unit":unit,"capacity":capacity,"stock_unopened":stock_unopened,"usage_model":usage_model or {},"reminder":reminder or {}}
        if remaining is not None: payload["remaining"] = remaining
        return self.emit_life_event("life.consumable.registered.v1", payload)
    def deactivate_consumable(self, item_id: str, reason: str | None = None):
        payload = {"item_id":item_id}
        if reason: payload["reason"] = reason
        return self.emit_life_event("life.consumable.deactivated.v1", payload)
