"""PC health producer and durable state consumer.

The monitor samples every 60 seconds.  A threshold must be observed twice
consecutively (the default 120-second debounce) before it is emitted; recovery
resets that counter.  It only observes and publishes facts, never remediates.
"""
from __future__ import annotations
import asyncio, json, logging, os, socket, subprocess, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4
from .contracts import LifeEventEnvelope, validate_event

LOG = logging.getLogger(__name__)
CONSUMER_NAME = "life-pc-state-v1"
# Windows services whose sustained absence means the PC is unhealthy; override with RINO_PC_WATCH_SERVICES.
DEFAULT_WATCHED_SERVICES = ("EventLog", "Winmgmt", "Dnscache", "Dhcp", "LanmanWorkstation")
# Only these Windows System-log providers are treated as hardware faults (Critical/Error levels only).
HARDWARE_PROVIDERS = ("disk", "Ntfs", "volmgr", "stornvme", "storahci", "Microsoft-Windows-WHEA-Logger", "nvlddmkm", "Display")
_EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"

def _watched_services() -> tuple[str, ...]:
    raw = os.environ.get("RINO_PC_WATCH_SERVICES")
    names = tuple(name.strip() for name in raw.split(",") if name.strip()) if raw is not None else DEFAULT_WATCHED_SERVICES
    return tuple(name for name in names if len(name) <= 128)

def query_hardware_events(after_record_id: int | None) -> list[dict[str, Any]]:
    """Read new Critical/Error hardware events from the Windows System log (fixed command, no user input)."""
    if sys.platform != "win32": return []
    providers = " or ".join(f"@Name='{name}'" for name in HARDWARE_PROVIDERS)
    condition = f"(Level=1 or Level=2) and Provider[{providers}]"
    if after_record_id is not None: condition += f" and EventRecordID>{int(after_record_id)}"
    completed = subprocess.run(["wevtutil", "qe", "System", f"/q:*[System[{condition}]]", "/c:20", "/rd:false" if after_record_id is not None else "/rd:true", "/f:xml"],
                               capture_output=True, timeout=20, check=False)
    if completed.returncode != 0: raise RuntimeError(f"wevtutil failed with exit code {completed.returncode}")
    root = ET.fromstring("<Events>" + completed.stdout.decode("utf-8", "replace") + "</Events>")
    events = []
    for element in root:
        system = element.find(f"{_EVENT_NS}System")
        if system is None: continue
        provider, event_id, record_id = system.find(f"{_EVENT_NS}Provider"), system.find(f"{_EVENT_NS}EventID"), system.find(f"{_EVENT_NS}EventRecordID")
        if provider is None or event_id is None or record_id is None: continue
        events.append({"provider": provider.get("Name", ""), "event_id": int(event_id.text or 0), "record_id": int(record_id.text or 0)})
    return events

class PCMonitor:
    def __init__(self, *, interval_seconds: int = 60, debounce_samples: int = 2,
                 storage_threshold_bytes: int = 20 * 1024 ** 3,
                 cpu_threshold_percent: float = 90.0,
                 memory_threshold_percent: float = 90.0,
                 device_id: str | None = None, disk_usage: Callable[[str], Any] | None = None,
                 psutil_module: Any | None = None, watched_services: tuple[str, ...] | None = None,
                 hardware_events: Callable[[int | None], list[dict[str, Any]]] | None = None):
        if interval_seconds < 10 or debounce_samples < 1: raise ValueError("interval must be >=10 seconds and debounce >=1")
        self.interval_seconds, self.debounce_samples = interval_seconds, debounce_samples
        if not all(0 <= value <= 100 for value in (cpu_threshold_percent, memory_threshold_percent)):
            raise ValueError("percentage thresholds must be between 0 and 100")
        self.storage_threshold_bytes, self.device_id = storage_threshold_bytes, device_id or socket.gethostname()
        self.cpu_threshold_percent, self.memory_threshold_percent = cpu_threshold_percent, memory_threshold_percent
        self.disk_usage, self.psutil_module, self._low_samples = disk_usage, psutil_module, {}
        self.watched_services = _watched_services() if watched_services is None else watched_services
        self.hardware_events, self._last_record_id = hardware_events or query_hardware_events, None

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

    def observe_services(self) -> list[dict[str, Any]]:
        """Return sustained stopped-service alerts for the watched Windows services."""
        psutil = self.psutil_module
        if psutil is None:
            import psutil as psutil_module
            psutil = psutil_module
        if not hasattr(psutil, "win_service_get"): return []
        events = []
        for name in self.watched_services:
            try: stopped = psutil.win_service_get(name).status() == "stopped"
            except Exception: continue  # service not installed / not readable: nothing to judge
            event = self._threshold_event(f"service:{name}", 1 if stopped else 0, 1, "pc.service_failed.v1", {"service": name})
            if event: events.append(event)
        return events

    def observe_hardware(self) -> list[dict[str, Any]]:
        """Return new hardware fault events from the System log; history before the first poll is not replayed."""
        first_poll = self._last_record_id is None
        found = self.hardware_events(self._last_record_id)
        if found: self._last_record_id = max(self._last_record_id or 0, *(item["record_id"] for item in found))
        elif first_poll: self._last_record_id = 0
        if first_poll:
            # Baseline only: errors already in the log when the monitor starts are old news.
            return []
        return [self._event("pc.hardware_error.v1", {"code": f"{item['provider']}:{item['event_id']}"[:128],
                                                     "message": f"Windows System log reported {item['provider']} event {item['event_id']}"})
                for item in found]

    def observe(self, path: str) -> list[dict[str, Any]]:
        events = [self.observe_storage(path), *self.observe_resources(), *self.observe_services()]
        try: events.extend(self.observe_hardware())
        except Exception: LOG.exception("hardware event query failed")
        return [event for event in events if event]

    async def run(self, publish: Callable[[str, bytes], Any], path: str = ".") -> None:
        await publish("pc.started.v1", json.dumps(self._event("pc.started.v1", {})).encode())
        while True:
            for event in await asyncio.to_thread(self.observe, path):
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

def default_monitor_path() -> str:
    return os.environ.get("RINO_PC_MONITOR_PATH") or (os.environ.get("SystemDrive", "C:") + "\\")

async def run_pc_monitor(path: str | None = None, monitor: PCMonitor | None = None, url: str | None = None) -> None:
    """Run the production JetStream producer; publishing is ACKed by JetStream."""
    import nats
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        js = nc.jetstream()
        await (monitor or PCMonitor()).run(js.publish, path or default_monitor_path())
    finally: await nc.drain()

if __name__ == "__main__": asyncio.run(run_pc_consumer())
