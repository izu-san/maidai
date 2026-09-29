"""Phase 3 notification routing: durable, explainable, and deliberately quiet."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import json, logging, os
from typing import Any, Callable
from uuid import uuid4

from .contracts import LifeEventEnvelope, validate_event

LOG = logging.getLogger(__name__)
CONSUMER_NAME = "life-notification-router-v1"

@dataclass(frozen=True)
class NotificationDecision:
    action: str                 # send, aggregate, suppress, or ignore
    reason: dict[str, Any]

def in_quiet_hours(now: datetime, start: time = time(23), end: time = time(7)) -> bool:
    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo("Asia/Tokyo")).time()
    return local >= start or local < end if start > end else start <= local < end

def decide_notification(existing: dict[str, Any] | None, *, now: datetime, priority: int,
                        quiet: bool, confidence: float | None, cooldown: timedelta) -> NotificationDecision:
    """Pure policy function; its output is persisted as the user-visible audit reason."""
    if confidence is not None and confidence < 0.5:
        return NotificationDecision("suppress", {"rule": "low_confidence", "confidence": confidence})
    if quiet and priority < 3:
        return NotificationDecision("suppress", {"rule": "quiet_hours", "priority": priority})
    if existing and existing.get("status") in {"sent", "acknowledged"}:
        return NotificationDecision("aggregate", {"rule": "already_unresolved", "status": existing["status"]})
    until = existing.get("cooldown_until") if existing else None
    if until and now < until:
        return NotificationDecision("suppress", {"rule": "cooldown", "cooldown_until": until.isoformat()})
    return NotificationDecision("send", {"rule": "eligible", "cooldown_seconds": int(cooldown.total_seconds())})

class NotificationRouter:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None,
                 *, cooldown: timedelta = timedelta(hours=12), notifier: Callable[[dict[str, Any]], None] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            def connect(*args: Any, **kwargs: Any) -> Any:
                import psycopg
                return psycopg.connect(*args, **kwargs)
        self.connect, self.cooldown, self.notifier = connect, cooldown, notifier or (lambda _: None)

    def route(self, event: LifeEventEnvelope, *, now: datetime | None = None) -> NotificationDecision:
        priorities = {"life.consumable.low.v1": 2, "pc.storage_low.v1": 3, "pc.hardware_error.v1": 4, "pc.service_failed.v1": 3}
        if event.type not in priorities:
            return NotificationDecision("ignore", {"rule": "unsupported_subject"})
        now = now or datetime.now(timezone.utc)
        payload = event.payload
        key = f"consumable-low:{payload['item_id']}" if event.type == "life.consumable.low.v1" else f"{event.type}:{payload['device_id']}:{payload.get('path', payload.get('code', payload.get('service', 'default')))}"
        priority = priorities[event.type]
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO processed_events (consumer_name,event_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_id", (CONSUMER_NAME, event.id))
            if cursor.fetchone() is None:
                return NotificationDecision("suppress", {"rule": "duplicate_event"})
            cursor.execute("SELECT id,status,cooldown_until,candidate_count FROM notification_history WHERE dedupe_key=%s FOR UPDATE", (key,))
            row = cursor.fetchone()
            existing = None if row is None else {"id": row[0], "status": row[1], "cooldown_until": row[2], "candidate_count": row[3]}
            decision = decide_notification(existing, now=now, priority=priority, quiet=in_quiet_hours(now), confidence=event.confidence, cooldown=self.cooldown)
            reason = {**decision.reason, "event_id": str(event.id), "subject": event.type}
            if event.type == "life.consumable.low.v1": reason.update(remaining=payload["remaining"], threshold=payload["threshold"])
            # Suppressed candidates remain eligible after quiet hours/confidence changes;
            # only an actual delivery starts the cooldown clock.
            cooldown_until = now + self.cooldown if decision.action == "send" else (existing.get("cooldown_until") if existing else None)
            if existing is None:
                cursor.execute("INSERT INTO notification_history (id,dedupe_key,event_id,priority,status,sent_at,cooldown_until,candidate_count,last_event_at,reason) VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s::jsonb)", (uuid4(), key, event.id, priority, "sent" if decision.action == "send" else "suppressed", now if decision.action == "send" else None, cooldown_until, now, json.dumps(reason)))
            else:
                cursor.execute("UPDATE notification_history SET event_id=%s, priority=%s, status=%s, sent_at=CASE WHEN %s='send' THEN %s ELSE sent_at END, cooldown_until=%s, candidate_count=candidate_count+1, last_event_at=%s, reason=%s::jsonb WHERE id=%s", (event.id, priority, "sent" if decision.action == "send" else existing["status"], decision.action, now, cooldown_until, now, json.dumps(reason), existing["id"]))
        if decision.action == "send":
            self.notifier({"dedupe_key": key, "priority": priority, "payload": payload, "reason": reason})
        return decision

    def acknowledge(self, dedupe_key: str, *, now: datetime | None = None) -> bool:
        return self._set_status(dedupe_key, "acknowledged", "acknowledged_at", now)

    def resolve(self, dedupe_key: str, *, now: datetime | None = None) -> bool:
        return self._set_status(dedupe_key, "resolved", "resolved_at", now)

    def _set_status(self, key: str, status: str, timestamp: str, now: datetime | None) -> bool:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(f"UPDATE notification_history SET status=%s,{timestamp}=%s WHERE dedupe_key=%s AND status <> 'resolved' RETURNING id", (status, now or datetime.now(timezone.utc), key))
            return cursor.fetchone() is not None

async def run_notification_router(router: NotificationRouter | None = None, url: str | None = None) -> None:
    import nats
    from .agent_notifier import agent_chat_notifier
    router = router or NotificationRouter(notifier=agent_chat_notifier)
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        sub = await nc.jetstream().pull_subscribe("life.consumable.low.v1", durable=CONSUMER_NAME, stream="RINO_LIFE")
        while True:
            for message in await sub.fetch(10, timeout=1):
                try:
                    router.route(validate_event(message.subject, json.loads(message.data)))
                    await message.ack()
                except Exception:
                    LOG.exception("notification consumer failed", extra={"subject": message.subject})
    finally:
        await nc.drain()

if __name__ == "__main__": asyncio.run(run_notification_router())
