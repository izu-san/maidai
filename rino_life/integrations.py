"""Safe ingress adapters for MQTT, Home Assistant, and Calendar.

Adapters only normalize validated observations into event envelopes.  They never
perform device commands or write state; callers must submit them to Life API.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from .contracts import LifeEventEnvelope, validate_event

ALLOWED_EXTERNAL_TYPES = {"mqtt.device_observed.v1", "home_assistant.state_changed.v1", "calendar.event_changed.v1"}

def external_event(kind: str, payload: dict[str, Any], *, source: str, occurred_at: datetime | None = None, correlation_id: str | None = None) -> LifeEventEnvelope:
    if kind not in ALLOWED_EXTERNAL_TYPES: raise ValueError("external event type is not allowlisted")
    event = LifeEventEnvelope(id=uuid4(), type=kind, occurred_at=occurred_at or datetime.now(timezone.utc), source=source, confidence=1.0, correlation_id=correlation_id, payload=payload)
    return validate_event(kind, event)
