"""Transactional Phase 2 consumable domain service.

Only this module writes consumable state; callers supply validated event envelopes.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json, os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml

from .contracts import LifeEventEnvelope, validate_event

LIFE_EVENTS = {"life.laundry.completed.v1", "life.consumable.purchased.v1", "life.consumable.opened.v1", "life.consumable.adjusted.v1", "life.consumable.registered.v1", "life.consumable.deactivated.v1"}

@dataclass(frozen=True)
class Consumable:
    id: str; name: str; category: str; unit: str; capacity: float; remaining: float; stock_unopened: int; estimated: bool; usage_model: dict[str, Any]; reminder: dict[str, Any]; version: int = 1
    def snapshot(self) -> dict[str, Any]:
        return {"remaining": self.remaining, "stock_unopened": self.stock_unopened, "estimated": self.estimated, "version": self.version}

def load_seed(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path) if path else Path(__file__).with_name("config") / "consumables.yaml"
    return [{"id": item_id, **value} for item_id, value in yaml.safe_load(source.read_text(encoding="utf-8"))["consumables"].items()]

class ConsumableService:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            # Keep API/MCP module importable before optional runtime dependencies
            # are installed; the clear dependency error occurs only on first DB use.
            def connect(*args: Any, **kwargs: Any) -> Any:
                import psycopg
                return psycopg.connect(*args, **kwargs)
        self.connect = connect

    def seed(self, items: list[dict[str, Any]] | None = None) -> None:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            for item in items or load_seed():
                cursor.execute("""INSERT INTO consumables (id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder)
                VALUES (%(id)s,%(name)s,%(category)s,%(unit)s,%(capacity)s,%(remaining)s,%(stock_unopened)s,false,%(usage)s::jsonb,%(reminder)s::jsonb) ON CONFLICT (id) DO NOTHING""", {**item, "usage": json.dumps(item["usage"]), "reminder": json.dumps(item["reminder"])})

    def get(self, item_id: str) -> Consumable | None:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,version FROM consumables WHERE id=%s AND active=true", (item_id,))
            row = cursor.fetchone()
        return self._row(row) if row else None

    def list_low_stock(self) -> list[Consumable]:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,version FROM consumables WHERE active=true")
            return [item for row in cursor.fetchall() if (item := self._row(row)).remaining <= float(item.reminder.get("remaining_below", -1))]

    def list_active(self) -> list[Consumable]:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,version FROM consumables WHERE active=true ORDER BY name")
            return [self._row(row) for row in cursor.fetchall()]

    def apply(self, subject: str, event: dict[str, Any] | LifeEventEnvelope) -> list[Consumable]:
        envelope = validate_event(subject, event)
        if envelope.type not in LIFE_EVENTS: raise ValueError(f"Unsupported consumable event: {envelope.type}")
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id FROM life_events WHERE id=%s", (envelope.id,))
            if cursor.fetchone(): return []
            cursor.execute("INSERT INTO life_events (id,type,occurred_at,source,actor,confidence,correlation_id,causation_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", (envelope.id,envelope.type,envelope.occurred_at,envelope.source,envelope.actor,envelope.confidence,envelope.correlation_id,envelope.causation_id,json.dumps(envelope.payload)))
            if envelope.type == "life.consumable.registered.v1":
                self._register(cursor, envelope)
                cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(),envelope.type,json.dumps(envelope.model_dump(mode="json"))))
                return []
            if envelope.type == "life.consumable.deactivated.v1":
                cursor.execute("UPDATE consumables SET active=false,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND active=true", (envelope.payload["item_id"],))
                if cursor.rowcount != 1: raise ValueError(f"Unknown or inactive consumable: {envelope.payload['item_id']}")
                cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(),envelope.type,json.dumps(envelope.model_dump(mode="json"))))
                return []
            targets = self._targets(cursor, envelope)
            updated = []
            for before, after in targets:
                cursor.execute("UPDATE consumables SET remaining=%s,stock_unopened=%s,estimated=%s,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (after.remaining,after.stock_unopened,after.estimated,before.id))
                cursor.execute("INSERT INTO consumable_history (id,consumable_id,event_id,before,after,reason) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s)", (uuid4(),before.id,envelope.id,json.dumps(before.snapshot()),json.dumps(after.snapshot()),envelope.type))
                updated.append(after)
            cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(),envelope.type,json.dumps(envelope.model_dump(mode="json"))))
            # A low-stock candidate is a fact derived from the committed snapshot.  It is
            # intentionally emitted for every qualifying update; Phase 3's durable router
            # owns cooldown/deduplication and therefore makes replay safe.
            for item in updated:
                threshold = float(item.reminder.get("remaining_below", -1))
                if threshold >= 0 and item.remaining <= threshold:
                    low = LifeEventEnvelope(id=uuid4(), type="life.consumable.low.v1", occurred_at=datetime.now(timezone.utc), source="life-service", actor=None, confidence=1.0, correlation_id=envelope.correlation_id, causation_id=envelope.id, payload={"item_id": item.id, "remaining": item.remaining, "threshold": threshold, "name": item.name, "unit": item.unit})
                    cursor.execute("INSERT INTO life_events (id,type,occurred_at,source,actor,confidence,correlation_id,causation_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", (low.id,low.type,low.occurred_at,low.source,low.actor,low.confidence,low.correlation_id,low.causation_id,json.dumps(low.payload)))
                    cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(),low.type,json.dumps(low.model_dump(mode="json"))))
            return updated

    def _targets(self, cursor: Any, event: LifeEventEnvelope) -> list[tuple[Consumable, Consumable]]:
        if event.type == "life.laundry.completed.v1":
            cursor.execute("SELECT id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,version FROM consumables WHERE active=true FOR UPDATE")
            items = [self._row(row) for row in cursor.fetchall()]
            count = event.payload["count"]
            return [(item, self._changed(item, remaining=max(0, item.remaining - float(item.usage_model.get("amount", 0)) * count), estimated=item.estimated)) for item in items if item.usage_model.get("event") == "laundry.completed"]
        item = self._locked(cursor, event.payload["item_id"])
        if event.type == "life.consumable.purchased.v1": return [(item, self._changed(item, stock_unopened=item.stock_unopened + event.payload["quantity"]))]
        if event.type == "life.consumable.opened.v1":
            if item.stock_unopened < 1: raise ValueError("Cannot open an item with no unopened stock")
            return [(item, self._changed(item, remaining=item.capacity, stock_unopened=item.stock_unopened - 1, estimated=False))]
        remaining = float(event.payload["remaining"])
        if remaining > item.capacity: raise ValueError("remaining cannot exceed capacity")
        return [(item, self._changed(item, remaining=remaining, estimated=event.payload["estimated"]))]

    def _locked(self, cursor: Any, item_id: str) -> Consumable:
        cursor.execute("SELECT id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,version FROM consumables WHERE id=%s AND active=true FOR UPDATE", (item_id,))
        row = cursor.fetchone()
        if row is None: raise ValueError(f"Unknown consumable: {item_id}")
        return self._row(row)
    @staticmethod
    def _register(cursor: Any, event: LifeEventEnvelope) -> None:
        p = event.payload; remaining = float(p.get("remaining", p["capacity"]))
        if remaining > float(p["capacity"]): raise ValueError("remaining cannot exceed capacity")
        cursor.execute("INSERT INTO consumables (id,name,category,unit,capacity,remaining,stock_unopened,estimated,usage_model,reminder,active) VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s::jsonb,%s::jsonb,true)", (p["item_id"],p["name"],p["category"],p["unit"],p["capacity"],remaining,p.get("stock_unopened", 0),json.dumps(p.get("usage_model", {})),json.dumps(p.get("reminder", {}))))
    @staticmethod
    def _changed(item: Consumable, **changes: Any) -> Consumable: return Consumable(**{**item.__dict__, **changes, "version": item.version + 1})
    @staticmethod
    def _row(row: Any) -> Consumable:
        values = list(row); values[4] = float(values[4]); values[5] = float(values[5]); values[8] = values[8] if isinstance(values[8], dict) else json.loads(values[8]); values[9] = values[9] if isinstance(values[9], dict) else json.loads(values[9]); return Consumable(*values)
