from datetime import datetime, timezone
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from rino_life.contracts import validate_event
from rino_life.environment_consumer import EnvironmentStateStore, _snapshot_field


def switchbot_event(kind="temperature_changed"):
    payload = {"temperature_c": 24.5, "observed_at": "2026-09-29T10:00:00+09:00"}
    return {"id": str(uuid4()), "type": f"switchbot.{kind}.v1", "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "switchbot", "confidence": 1, "payload": payload}


def test_switchbot_schema_rejects_invalid_sensor_value():
    event = switchbot_event()
    event["payload"]["temperature_c"] = 999
    with pytest.raises(ValidationError):
        validate_event(event["type"], event)


def test_switchbot_schema_accepts_versioned_observation_and_maps_snapshot():
    event = switchbot_event()
    envelope = validate_event(event["type"], event)
    assert _snapshot_field(envelope.type, envelope.payload) == ("temperature_c", 24.5)


def test_device_state_schema_requires_identifier():
    event = switchbot_event("device_state_changed")
    event["payload"] = {"state": {"power": "on"}, "observed_at": "2026-09-29T10:00:00+09:00"}
    with pytest.raises(ValidationError):
        validate_event(event["type"], event)


def test_replayed_sensor_event_creates_one_history_and_snapshot():
    class Cursor:
        def __init__(self, db): self.db, self.inserted = db, False
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, sql, values=None):
            self.db.calls.append(sql)
            if "processed_events" in sql:
                key = values[1]
                self.inserted = key not in self.db.events
                self.db.events.add(key)
                if self.inserted: self.db.history += 1
        def fetchone(self): return ("event",) if self.inserted else None
    class Connection:
        def __init__(self, db): self.db = db
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def cursor(self): return Cursor(self.db)
    class Database:
        events, history, calls = set(), 0, []
        def connect(self, _): return Connection(self)

    database = Database()
    event = validate_event("switchbot.temperature_changed.v1", switchbot_event())
    store = EnvironmentStateStore("test", database.connect)
    assert store.apply(event) is True
    assert store.apply(event) is False
    assert database.history == 1
    assert sum("environment_history" in call for call in database.calls) == 1
