from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from jsonschema import ValidationError
from rino_life.contracts import validate_event
from rino_life.notifications import decide_notification
from rino_life.pc import PCMonitor
from rino_life.vision import requires_confirmation

def pc_event(kind="storage_low"):
    payload = {"device_id":"pc-1", "path":"C:/", "free_bytes":10, "total_bytes":100, "threshold_bytes":20, "observed_at":"2026-09-29T10:00:00+09:00"}
    return {"id":str(uuid4()),"type":f"pc.{kind}.v1","occurred_at":"2026-09-29T10:00:00+09:00","source":"pc_monitor","confidence":1,"payload":payload}

def test_pc_storage_schema_and_debounce_emit_only_after_two_low_samples():
    event = pc_event(); assert validate_event(event["type"], event).payload["free_bytes"] == 10
    usage = SimpleNamespace(free=10, total=100)
    monitor = PCMonitor(interval_seconds=10, debounce_samples=2, storage_threshold_bytes=20, disk_usage=lambda _: usage, device_id="pc-1")
    assert monitor.observe_storage("C:/") is None
    assert monitor.observe_storage("C:/")["type"] == "pc.storage_low.v1"
    usage.free = 30; assert monitor.observe_storage("C:/") is None

def test_pc_resource_alerts_are_debounced_and_validate_against_their_contracts():
    class Psutil:
        def cpu_percent(self, interval=None): return 95
        def virtual_memory(self): return SimpleNamespace(percent=91, available=9, total=100)
    monitor = PCMonitor(interval_seconds=10, debounce_samples=2, device_id="pc-1", psutil_module=Psutil())
    assert monitor.observe_resources() == []
    events = {event["type"]: event for event in monitor.observe_resources()}
    assert set(events) == {"pc.cpu_high.v1", "pc.memory_high.v1"}
    for event in events.values():
        assert validate_event(event["type"], event).payload["device_id"] == "pc-1"

def test_vision_is_always_a_confirmation_required_candidate():
    raw = {"id":str(uuid4()),"type":"vision.observation_detected.v1","occurred_at":"2026-09-29T10:00:00+09:00","source":"vision","confidence":0.7,"payload":{"observation_type":"game_detected","summary":"game active","observed_at":"2026-09-29T10:00:00+09:00","confirmation_required":True}}
    assert requires_confirmation(validate_event(raw["type"], raw))
    raw["payload"]["confirmation_required"] = False
    with pytest.raises(ValidationError): validate_event(raw["type"], raw)

def test_urgent_pc_error_bypasses_quiet_hours_but_normal_alert_does_not():
    now = datetime(2026, 9, 29, 15, tzinfo=timezone.utc)
    assert decide_notification(None, now=now, priority=4, quiet=True, confidence=1, cooldown=timedelta(hours=1)).action == "send"
    assert decide_notification(None, now=now, priority=2, quiet=True, confidence=1, cooldown=timedelta(hours=1)).action == "suppress"
