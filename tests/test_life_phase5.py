from datetime import datetime, timezone
from uuid import uuid4
import pytest
from jsonschema import ValidationError
from rino_life.contracts import validate_event
from rino_life.integrations import external_event

def event(kind, payload):
    return {"id": str(uuid4()), "type": kind, "occurred_at": "2026-09-29T10:00:00+09:00", "source": "manual", "confidence": 1, "payload": payload}

@pytest.mark.parametrize(("kind", "payload"), [
    ("life.maintenance.completed.v1", {"item_id": "air-filter"}),
    ("life.trash.collected.v1", {"schedule_id": "burnable"}),
    ("life.package.updated.v1", {"package_id": "pkg-1", "status": "in_transit"}),
    ("life.subscription.updated.v1", {"subscription_id": "svc-1", "name": "Example", "status": "active", "currency": "JPY"}),
])
def test_phase5_life_contracts(kind, payload):
    assert validate_event(kind, event(kind, payload)).type == kind

def test_external_connectors_are_allowlisted_and_schema_validated():
    accepted = external_event("mqtt.device_observed.v1", {"device_id": "sensor-1", "topic": "home/sensor", "state": 1}, source="mqtt")
    assert accepted.type == "mqtt.device_observed.v1"
    with pytest.raises(ValueError): external_event("life.package.updated.v1", {}, source="mqtt")
    with pytest.raises(ValidationError): external_event("calendar.event_changed.v1", {"calendar_event_id": "x", "action": "created"}, source="calendar")
