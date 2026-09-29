"""PC health producer and durable state consumer.

The monitor samples every 60 seconds.  A threshold must be observed twice
consecutively (the default 120-second debounce) before it is emitted; recovery
resets that counter.  It only observes and publishes facts, never remediates.
"""
from __future__ import annotations
import asyncio, json, logging, os, socket
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4
from .contracts import LifeEventEnvelope, validate_event

LOG = logging.getLogger(__name__)
CONSUMER_NAME = "life-pc-state-v1"

class PCMonitor:
    def __init__(self, *, interval_seconds: int = 60, debounce_samples: int = 2,
                 storage_threshold_bytes: int = 20 * 1024 ** 3,
                 cpu_threshold_percent: float = 90.0,
                 memory_threshold_percent: float = 90.0,
                 device_id: str | None = None, disk_usage: Callable[[str], Any] | None = None,
                 psutil_module: Any | None = None):
        if interval_seconds < 10 or debounce_samples < 1: raise ValueError("interval must be >=10 seconds and debounce >=1")
        self.interval_seconds, self.debounce_samples = interval_seconds, debounce_samples
        if not all(0 <= value <= 100 for value in (cpu_threshold_percent, memory_threshold_percent)):
            raise ValueError("percentage thresholds must be between 0 and 100")
        self.storage_threshold_bytes, self.device_id = storage_threshold_bytes, device_id or socket.gethostname()
        self.cpu_threshold_percent, self.memory_threshold_percent = cpu_threshold_percent, memory_threshold_percent
        self.disk_usage, self.psutil_module, self._low_samples = disk_usage, psutil_module, {}

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        observed_at = now.isoformat()
        return {"id": str(uuid4()), "type": event_type, "occurred_at": observed_at, "source": "pc_monitor", "actor": None,
                "confidence": 1.0, "correlation_id": None, "causation_id": None,
                "payload": {"device_id": self.device_id, **payload, "observed_at": observed_at}}

    def _threshold_event(self, key: str, value: float, threshold: float, event_type: str,
                         payload: dict[str, Any], *, low_is_bad: bool = False) -> dict[str, Any] | None:
        breached = value < threshold if low_is_bad else value >= threshold
        self._low_samples[key] = self._low_samples.get(key, 0) + 1 if breached else 0
        return self._event(event_type, payload) if breached and self._low_samples[key] == self.debounce_samples else None

    def observe_storage(self, path: str) -> dict[str, Any] | None:
        usage = (self.disk_usage or __import__("shutil").disk_usage)(path)
        key = str(path)
        return self._threshold_event(f"storage:{key}", usage.free, self.storage_threshold_bytes, "pc.storage_low.v1",
                                     {"path": key, "free_bytes": usage.free, "total_bytes": usage.total,
                                      "threshold_bytes": self.storage_threshold_bytes}, low_is_bad=True)

    def observe_resources(self) -> list[dict[str, Any]]:
        """Return sustained CPU and memory alerts."""
        psutil = self.psutil_module
        if psutil is None:
            import psutil as psutil_module
            psutil = psutil_module
        events = []
        cpu = float(psutil.cpu_percent(interval=None))
        event = self._threshold_event("cpu", cpu, self.cpu_threshold_percent, "pc.cpu_high.v1",
                                      {"usage_percent": cpu, "threshold_percent": self.cpu_threshold_percent})
        if event: events.append(event)
        memory = psutil.virtual_memory()
        memory_percent = float(memory.percent)
        event = self._threshold_event("memory", memory_percent, self.memory_threshold_percent, "pc.memory_high.v1",
                                      {"usage_percent": memory_percent, "available_bytes": int(memory.available),
                                       "total_bytes": int(memory.total), "threshold_percent": self.memory_threshold_percent})
        if event: events.append(event)
        return events

    def observe(self, path: str) -> list[dict[str, Any]]:
        return [event for event in [self.observe_storage(path), *self.observe_resources()] if event]

    async def run(self, publish: Callable[[str, bytes], Any], path: str = ".") -> None:
        while True:
            for event in self.observe(path):
                await publish(event["type"], json.dumps(event).encode())
            await asyncio.sleep(self.interval_seconds)

class PCStateStore:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            import psycopg; connect = psycopg.connect
        self.connect = connect
    def apply(self, event: LifeEventEnvelope) -> bool:
        payload, device_id = event.payload, event.payload["device_id"]
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO processed_events (consumer_name,event_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_id", (CONSUMER_NAME, event.id))
            if cursor.fetchone() is None: return False
            cursor.execute("INSERT INTO pc_history (event_id,device_id,type,observed_at,payload) VALUES (%s,%s,%s,%s,%s)", (event.id, device_id, event.type, payload["observed_at"], json.dumps(payload)))
            if event.type == "pc.storage_low.v1":
                cursor.execute("INSERT INTO pc_state (device_id,status,storage_free_bytes,storage_total_bytes,observed_at) VALUES (%s,'degraded',%s,%s,%s) ON CONFLICT (device_id) DO UPDATE SET status='degraded',storage_free_bytes=EXCLUDED.storage_free_bytes,storage_total_bytes=EXCLUDED.storage_total_bytes,observed_at=EXCLUDED.observed_at,updated_at=CURRENT_TIMESTAMP WHERE EXCLUDED.observed_at >= pc_state.observed_at", (device_id,payload["free_bytes"],payload["total_bytes"],payload["observed_at"]))
            elif event.type == "pc.started.v1":
                cursor.execute("INSERT INTO pc_state (device_id,status,observed_at) VALUES (%s,'online',%s) ON CONFLICT (device_id) DO UPDATE SET status='online',observed_at=EXCLUDED.observed_at,updated_at=CURRENT_TIMESTAMP WHERE EXCLUDED.observed_at >= pc_state.observed_at", (device_id,payload["observed_at"]))
            else:
                cursor.execute("INSERT INTO pc_state (device_id,status,last_error,observed_at) VALUES (%s,'error',%s::jsonb,%s) ON CONFLICT (device_id) DO UPDATE SET status='error',last_error=EXCLUDED.last_error,observed_at=EXCLUDED.observed_at,updated_at=CURRENT_TIMESTAMP WHERE EXCLUDED.observed_at >= pc_state.observed_at", (device_id,json.dumps(payload),payload["observed_at"]))
        return True

async def run_pc_consumer(store: PCStateStore | None = None, url: str | None = None) -> None:
    import nats
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222")); store = store or PCStateStore()
    try:
        sub = await nc.jetstream().pull_subscribe("pc.>", durable=CONSUMER_NAME, stream="RINO_DEVICE")
        while True:
            for message in await sub.fetch(10, timeout=1):
                try: store.apply(validate_event(message.subject, json.loads(message.data))); await message.ack()
                except Exception: LOG.exception("PC consumer failed", extra={"subject": message.subject})
    finally: await nc.drain()

async def run_pc_monitor(path: str = ".", monitor: PCMonitor | None = None, url: str | None = None) -> None:
    """Run the production JetStream producer; publishing is ACKed by JetStream."""
    import nats
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        js = nc.jetstream()
        await (monitor or PCMonitor()).run(js.publish, path)
    finally: await nc.drain()

if __name__ == "__main__": asyncio.run(run_pc_consumer())
