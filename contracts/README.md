# Event contracts

Each filename includes the immutable major schema version. Breaking payload changes require a new subject and schema filename (for example, `*.v2.schema.json`); existing versions are never edited semantically.

All event bodies must validate against `life-envelope.v1.schema.json`. Producers must set `type` to exactly the NATS subject. Payload schemas are selected by that type. Payloads must not contain credentials, raw conversation text, or unprocessed screenshots, and are capped at 16 KiB by `rino_life.contracts`.

Run `pytest tests/test_life_phase0.py` to validate the checked-in contracts and Pydantic boundary.
