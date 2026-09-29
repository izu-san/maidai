"""Phase 5 domain writes.  Each write is an audited life event plus an Outbox row."""
from __future__ import annotations
import json, os
from typing import Any, Callable
from uuid import uuid4
from .contracts import LifeEventEnvelope, validate_event

SUPPORTED = {
    "life.maintenance.completed.v1", "life.trash.collected.v1",
    "life.package.updated.v1", "life.subscription.updated.v1",
}

class Phase5Service:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            def connect(*args: Any, **kwargs: Any) -> Any:
                import psycopg
                return psycopg.connect(*args, **kwargs)
        self.connect = connect

    def apply(self, subject: str, event: dict[str, Any] | LifeEventEnvelope) -> bool:
        envelope = validate_event(subject, event)
        if envelope.type not in SUPPORTED: raise ValueError(f"Unsupported Phase 5 event: {envelope.type}")
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM life_events WHERE id=%s", (envelope.id,))
            if cursor.fetchone(): return False
            cursor.execute("INSERT INTO life_events (id,type,occurred_at,source,actor,confidence,correlation_id,causation_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", (envelope.id,envelope.type,envelope.occurred_at,envelope.source,envelope.actor,envelope.confidence,envelope.correlation_id,envelope.causation_id,json.dumps(envelope.payload)))
            p = envelope.payload
            if subject == "life.maintenance.completed.v1":
                cursor.execute("UPDATE maintenance_items SET last_completed_at=%s,next_due_at=%s + interval_days * INTERVAL '1 day' WHERE id=%s", (envelope.occurred_at,envelope.occurred_at,p["item_id"]))
                if cursor.rowcount != 1: raise ValueError(f"Unknown maintenance item: {p['item_id']}")
                cursor.execute("INSERT INTO maintenance_history (id,maintenance_id,event_id,completed_at,notes) VALUES (%s,%s,%s,%s,%s)", (uuid4(),p["item_id"],envelope.id,envelope.occurred_at,p.get("notes")))
            elif subject == "life.trash.collected.v1":
                cursor.execute("UPDATE trash_schedules SET last_collected_at=%s WHERE id=%s", (envelope.occurred_at,p["schedule_id"]))
                if cursor.rowcount != 1: raise ValueError(f"Unknown trash schedule: {p['schedule_id']}")
            elif subject == "life.package.updated.v1":
                cursor.execute("INSERT INTO deliveries (id,carrier,tracking_ref,status,expected_at,metadata) VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (id) DO UPDATE SET carrier=EXCLUDED.carrier,tracking_ref=EXCLUDED.tracking_ref,status=EXCLUDED.status,expected_at=EXCLUDED.expected_at,metadata=EXCLUDED.metadata,updated_at=CURRENT_TIMESTAMP", (p["package_id"],p.get("carrier"),p.get("tracking_ref"),p["status"],p.get("expected_at"),json.dumps(p.get("metadata", {}))))
            else:
                cursor.execute("INSERT INTO subscriptions (id,name,status,renewal_at,amount,currency,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,status=EXCLUDED.status,renewal_at=EXCLUDED.renewal_at,amount=EXCLUDED.amount,currency=EXCLUDED.currency,metadata=EXCLUDED.metadata,updated_at=CURRENT_TIMESTAMP", (p["subscription_id"],p["name"],p["status"],p.get("renewal_at"),p.get("amount"),p.get("currency"),json.dumps(p.get("metadata", {}))))
            cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(),subject,json.dumps(envelope.model_dump(mode="json"))))
            return True
