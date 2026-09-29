from datetime import datetime, timedelta, timezone
from uuid import uuid4

from rino_life.context import build_life_context
from rino_life.consumables import Consumable
from rino_life.contracts import validate_event
from rino_life.notifications import NotificationRouter, decide_notification, in_quiet_hours

def low_event():
    return validate_event("life.consumable.low.v1", {"id": str(uuid4()), "type": "life.consumable.low.v1", "occurred_at": "2026-09-29T12:00:00+09:00", "source": "test", "confidence": 1.0, "payload": {"item_id": "detergent", "remaining": 20, "threshold": 150}})

def test_phase3_policy_aggregates_unresolved_and_respects_cooldown_and_quiet_hours():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    assert decide_notification({"status": "sent", "cooldown_until": None}, now=now, priority=2, quiet=False, confidence=1, cooldown=timedelta(hours=1)).action == "aggregate"
    assert decide_notification({"status": "resolved", "cooldown_until": now + timedelta(minutes=1)}, now=now, priority=2, quiet=False, confidence=1, cooldown=timedelta(hours=1)).reason["rule"] == "cooldown"
    assert decide_notification(None, now=now, priority=2, quiet=True, confidence=1, cooldown=timedelta(hours=1)).reason["rule"] == "quiet_hours"
    assert in_quiet_hours(datetime(2026, 9, 29, 15, tzinfo=timezone.utc))  # midnight JST

def test_router_marks_replayed_event_without_notifying_twice():
    class Cursor:
        def __init__(self): self.calls=[]; self.marker=True
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, sql, values=None): self.calls.append((sql, values))
        def fetchone(self):
            if self.marker:
                self.marker=False; return (uuid4(),)
            return None
    class Connection:
        def __init__(self): self.cursor_value=Cursor()
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def cursor(self): return self.cursor_value
    connection, delivered = Connection(), []
    router = NotificationRouter(connect=lambda _: connection, notifier=delivered.append)
    assert router.route(low_event(), now=datetime(2026, 9, 29, 12, tzinfo=timezone.utc)).action == "send"
    assert router.route(low_event(), now=datetime(2026, 9, 29, 12, tzinfo=timezone.utc)).reason["rule"] == "duplicate_event"
    assert len(delivered) == 1

def test_life_context_contains_only_current_state_and_unresolved_candidates():
    item = Consumable("detergent", "洗剤", "household", "ml", 900, 100, 0, False, {}, {})
    context = build_life_context([item], [{"dedupe_key": "x", "priority": 2, "status": "sent", "reason": {"rule": "eligible"}}, {"dedupe_key": "y", "priority": 2, "status": "resolved"}])
    assert context["consumables"][0]["remaining"] == 100
    assert [x["dedupe_key"] for x in context["notification_candidates"]] == ["x"]
