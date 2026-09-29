"""Durable, idempotent consumer for versioned SwitchBot observations."""
from __future__ import annotations
import asyncio, json, logging, os
from collections.abc import Callable
from typing import Any
from .contracts import LifeEventEnvelope, validate_event

LOG = logging.getLogger(__name__)
CONSUMER_NAME = "life-environment-state-v1"

class EnvironmentStateStore:
    """Writes the processed marker, history, and snapshot in one transaction."""
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self.connect = connect
    def apply(self, envelope: LifeEventEnvelope) -> bool:
        payload, device_id = envelope.payload, envelope.payload.get("device_id") or "switchbot-default"
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO processed_events (consumer_name, event_id) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING event_id", (CONSUMER_NAME, envelope.id))
            if cursor.fetchone() is None: return False
            cursor.execute("INSERT INTO environment_history (event_id, device_id, type, observed_at, payload) VALUES (%s, %s, %s, %s, %s)", (envelope.id, device_id, envelope.type, payload["observed_at"], json.dumps(payload)))
            field, value = _snapshot_field(envelope.type, payload)
            cursor.execute(f"INSERT INTO environment_state (device_id, {field}, observed_at) VALUES (%s, %s, %s) ON CONFLICT (device_id) DO UPDATE SET {field}=EXCLUDED.{field}, observed_at=EXCLUDED.observed_at, updated_at=CURRENT_TIMESTAMP WHERE EXCLUDED.observed_at >= environment_state.observed_at", (device_id, json.dumps(value) if field == "device_state" else value, payload["observed_at"]))
        return True

def _snapshot_field(event_type: str, payload: dict[str, Any]) -> tuple[str, Any]:
    if event_type == "switchbot.temperature_changed.v1": return "temperature_c", payload["temperature_c"]
    if event_type == "switchbot.humidity_changed.v1": return "humidity_percent", payload["humidity_percent"]
    if event_type == "switchbot.co2_changed.v1": return "co2_ppm", payload["co2_ppm"]
    if event_type == "switchbot.device_state_changed.v1": return "device_state", payload["state"]
    raise ValueError(f"Unsupported SwitchBot subject: {event_type}")

async def run_environment_consumer(store: EnvironmentStateStore | None = None, url: str | None = None) -> None:
    import nats
    store = store or EnvironmentStateStore()
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        subscription = await nc.jetstream().pull_subscribe("switchbot.>", durable=CONSUMER_NAME, stream="RINO_DEVICE")
        while True:
            for message in await subscription.fetch(10, timeout=1):
                try:
                    store.apply(validate_event(message.subject, json.loads(message.data)))
                    await message.ack()
                except Exception:
                    LOG.exception("environment consumer failed", extra={"subject": message.subject})
    finally: await nc.drain()

if __name__ == "__main__": asyncio.run(run_environment_consumer())
