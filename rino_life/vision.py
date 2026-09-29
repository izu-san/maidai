"""Vision observations are stored as candidates and cannot trigger actions."""
from __future__ import annotations
import json, os
import asyncio, logging
from typing import Any, Callable
from .contracts import LifeEventEnvelope

CONSUMER_NAME = "life-vision-candidates-v1"
LOG = logging.getLogger(__name__)

def requires_confirmation(event: LifeEventEnvelope) -> bool:
    """Every Vision observation is a candidate; it can never be auto-applied."""
    return event.source == "vision" or event.source.endswith("vision") or bool(event.payload.get("confirmation_required"))

class VisionCandidateStore:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            import psycopg; connect = psycopg.connect
        self.connect = connect
    def apply(self, event: LifeEventEnvelope) -> bool:
        if event.type != "vision.observation_detected.v1" or not requires_confirmation(event): raise ValueError("Vision events must be confirmation-required candidates")
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO processed_events (consumer_name,event_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_id", (CONSUMER_NAME,event.id))
            if cursor.fetchone() is None: return False
            cursor.execute("INSERT INTO vision_candidates (event_id,observation_type,confidence,confirmation_required,status,payload,observed_at) VALUES (%s,%s,%s,true,'pending',%s::jsonb,%s)", (event.id,event.payload["observation_type"],event.confidence or 0.0,json.dumps(event.payload),event.payload["observed_at"]))
        return True

async def run_vision_consumer(store: VisionCandidateStore | None = None, url: str | None = None) -> None:
    import nats
    from .contracts import validate_event
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222")); store = store or VisionCandidateStore()
    try:
        sub = await nc.jetstream().pull_subscribe("vision.>", durable=CONSUMER_NAME, stream="RINO_DEVICE")
        while True:
            for message in await sub.fetch(10, timeout=1):
                try: store.apply(validate_event(message.subject, json.loads(message.data))); await message.ack()
                except Exception: LOG.exception("Vision consumer failed", extra={"subject": message.subject})
    finally: await nc.drain()

if __name__ == "__main__": asyncio.run(run_vision_consumer())
