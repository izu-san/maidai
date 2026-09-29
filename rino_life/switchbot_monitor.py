"""SwitchBot observation producer: read-only polling published as versioned events.

It never sends device commands.  Device IDs stay inside the SwitchBot adapter; events carry the
registry key ("environment", "entrance") as ``device_id``.
"""
from __future__ import annotations
import asyncio, json, logging, os
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4
from .contracts import validate_event

LOG = logging.getLogger(__name__)
# Minutes an unlocked / open entrance must persist before a device_state_changed event carries the duration.
DEFAULT_ALERT_AFTER_MINUTES = 30

def _interval() -> int:
    return max(60, int(os.environ.get("RINO_SWITCHBOT_POLL_SECONDS", "300")))

class SwitchBotMonitor:
    def __init__(self, adapter: Any, registry: Any, *, interval_seconds: int | None = None,
                 alert_after_minutes: int = DEFAULT_ALERT_AFTER_MINUTES, clock: Callable[[], datetime] | None = None):
        self.adapter, self.registry = adapter, registry
        self.interval_seconds = interval_seconds or _interval()
        self.alert_after_minutes = alert_after_minutes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._entrance: tuple[str, str] | None = None
        self._since: dict[str, datetime] = {}
        self._alerted: set[str] = set()

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        return {"id": str(uuid4()), "type": event_type, "occurred_at": now.isoformat(), "source": "switchbot_poller", "actor": None,
                "confidence": 1.0, "correlation_id": None, "causation_id": None,
                "payload": {**payload, "observed_at": now.isoformat()}}

    def _device_id(self, key: str) -> str | None:
        try: return self.registry.get(key).device_id
        except Exception: return None  # not configured: nothing to observe

    def observe_environment(self) -> list[dict[str, Any]]:
        device_id = self._device_id("environment")
        if device_id is None: return []
        status = self.adapter.status(device_id)
        co2 = status.get("CO2", status.get("co2"))
        wanted = (("switchbot.temperature_changed.v1", "temperature_c", status.get("temperature")),
                  ("switchbot.humidity_changed.v1", "humidity_percent", status.get("humidity")),
                  ("switchbot.co2_changed.v1", "co2_ppm", int(co2) if isinstance(co2, (int, float)) else None))
        events = []
        for subject, field, value in wanted:
            if value is None: continue
            event = self._event(subject, {"device_id": "environment", field: value})
            try: validate_event(subject, event)
            except Exception: LOG.warning("dropping out-of-contract SwitchBot reading", extra={"subject": subject}); continue
            events.append(event)
        return events

    def observe_entrance(self) -> list[dict[str, Any]]:
        """Emit on lock/door change, and once when unlocked/open has lasted ``alert_after_minutes``."""
        device_id = self._device_id("entrance")
        if device_id is None: return []
        status = self.adapter.status(device_id)
        lock = str(status.get("lockState", status.get("lock_state", "UNKNOWN"))).upper()
        door = str(status.get("doorState", status.get("door_state", "UNKNOWN"))).upper()
        lock = lock if lock in {"LOCKED", "UNLOCKED", "JAMMED"} else "UNKNOWN"
        door = door if door in {"OPEN", "CLOSED"} else "UNKNOWN"
        now, state, changed = self._clock(), {"lock_state": lock, "door_state": door}, self._entrance != (lock, door)
        self._entrance = (lock, door)
        for name, active, field in (("unlocked", lock == "UNLOCKED", "unlocked_minutes"), ("open", door == "OPEN", "open_minutes")):
            if not active:
                self._since.pop(name, None); self._alerted.discard(name); continue
            since = self._since.setdefault(name, now)
            minutes = int((now - since).total_seconds() // 60)
            state[field] = minutes
            if minutes >= self.alert_after_minutes and name not in self._alerted:
                self._alerted.add(name); changed = True
        if not changed: return []
        return [self._event("switchbot.device_state_changed.v1", {"device_id": "entrance", "device_type": "lock", "state": state})]

    def observe(self) -> list[dict[str, Any]]:
        events = []
        for observe in (self.observe_environment, self.observe_entrance):
            try: events.extend(observe())
            except Exception as error: LOG.warning("SwitchBot poll failed", extra={"observer": observe.__name__, "error": str(error)})
        return events

    async def run(self, publish: Callable[[str, bytes], Any]) -> None:
        while True:
            for event in await asyncio.to_thread(self.observe):
                await publish(event["type"], json.dumps(event).encode())
            await asyncio.sleep(self.interval_seconds)

def create_monitor() -> SwitchBotMonitor:
    from pathlib import Path
    from rino.home.adapters.switchbot import SwitchBotAdapter
    from rino.home.models import DeviceRegistry
    return SwitchBotMonitor(SwitchBotAdapter(), DeviceRegistry.from_yaml(Path(__file__).resolve().parent.parent / "rino" / "home" / "config" / "devices.yaml"))

async def run_switchbot_monitor(monitor: SwitchBotMonitor | None = None, url: str | None = None) -> None:
    """Production JetStream producer; without SwitchBot credentials the observers simply find nothing."""
    import nats
    nc = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        await (monitor or create_monitor()).run(nc.jetstream().publish)
    finally: await nc.drain()

if __name__ == "__main__": asyncio.run(run_switchbot_monitor())
