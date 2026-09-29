from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from rino_life.contracts import validate_event


def event() -> dict:
    return {"id": str(uuid4()), "type": "life.consumable.purchased.v1", "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "test", "confidence": 1.0, "payload": {"item_id": "detergent", "quantity": 1}}


def test_envelope_schema_and_pydantic_boundary_agree() -> None:
    schema = json.loads((Path("contracts") / "life-envelope.v1.schema.json").read_text(encoding="utf-8"))
    body = event()
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(body)
    assert validate_event(body["type"], body).type == body["type"]


def test_subject_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="subject"):
        validate_event("life.consumable.adjusted.v1", event())
