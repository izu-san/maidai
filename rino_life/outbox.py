"""At-least-once JetStream publisher for transactional outbox rows."""
from __future__ import annotations
import asyncio, json, logging, os
from typing import Any, Callable
LOG = logging.getLogger(__name__)

class OutboxPublisher:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None, *, max_attempts: int = 5):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            def connect(*args: Any, **kwargs: Any) -> Any:
                import psycopg
                return psycopg.connect(*args, **kwargs)
        self.connect, self.max_attempts = connect, max_attempts
    async def publish_once(self, js: Any, limit: int = 100) -> int:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id,subject,payload,attempts FROM outbox_events WHERE published_at IS NULL AND attempts < %s ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s", (self.max_attempts, limit))
            rows = cursor.fetchall(); sent = 0
            for event_id, subject, payload, attempts in rows:
                try:
                    await js.publish(subject, json.dumps(payload).encode("utf-8")) # JetStream PubAck is the acknowledgement.
                    cursor.execute("UPDATE outbox_events SET published_at=CURRENT_TIMESTAMP,attempts=attempts+1,last_error=NULL WHERE id=%s", (event_id,)); sent += 1
                except Exception as error:
                    cursor.execute("UPDATE outbox_events SET attempts=attempts+1,last_error=%s WHERE id=%s", (str(error)[:2000], event_id))
                    LOG.warning("outbox publish failed", extra={"event_id":str(event_id),"subject":subject,"error":str(error)})
            return sent

async def run_outbox_publisher() -> None:
    import nats
    publisher = OutboxPublisher(); nc = await nats.connect(os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        while True:
            await publisher.publish_once(nc.jetstream())
            await asyncio.sleep(1)
    finally: await nc.drain()
