"""Versioned event-envelope validation shared by producers and consumers."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from jsonschema import Draft202012Validator, FormatChecker


class LifeEventEnvelope(BaseModel):
    """The Phase 0 wire contract. The NATS subject is the authoritative type."""
    model_config = ConfigDict(extra="forbid")
    id: UUID
    type: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+\.v[1-9][0-9]*$")
    occurred_at: datetime
    source: str = Field(min_length=1, max_length=64)
    actor: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    correlation_id: str | None = Field(default=None, max_length=128)
    causation_id: UUID | None = None
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @field_validator("payload")
    @classmethod
    def payload_must_be_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 16_384:
            raise ValueError("payload exceeds 16 KiB")
        return value


def validate_event(subject: str, event: dict[str, Any] | LifeEventEnvelope) -> LifeEventEnvelope:
    envelope = event if isinstance(event, LifeEventEnvelope) else LifeEventEnvelope.model_validate(event)
    if subject != envelope.type:
        raise ValueError("NATS subject and event type must match")
    schema = _payload_schema(subject)
    if schema:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(envelope.payload)
    return envelope


def _payload_schema(subject: str) -> dict[str, Any] | None:
    if not (subject.startswith("switchbot.") or subject.startswith("life.") or subject.startswith("pc.") or subject.startswith("vision.") or subject.startswith("mqtt.") or subject.startswith("home_assistant.") or subject.startswith("calendar.")) or not subject.endswith(".v1"):
        return None
    domain, action = subject.split(".", 1)
    action = action.removesuffix(".v1").replace(".", "-").replace("_", "-")
    path = Path(__file__).resolve().parent.parent / "contracts" / domain / f"{action}.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
