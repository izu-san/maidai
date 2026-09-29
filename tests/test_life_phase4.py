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

def _service_psutil(status):
    class Service:
        def status(self): return status["value"]
    class Psutil:
        def win_service_get(self, name):
            if name == "missing": raise OSError("not installed")
            return Service()
    return Psutil()

def test_stopped_watched_service_emits_service_failed_after_debounce_and_recovers():
    status = {"value": "stopped"}
    monitor = PCMonitor(device_id="pc-1", psutil_module=_service_psutil(status), watched_services=("EventLog", "missing"))
    assert monitor.observe_services() == []
    event = monitor.observe_services()[0]
    assert event["type"] == "pc.service_failed.v1" and event["payload"]["service"] == "EventLog"
    assert validate_event(event["type"], event).payload["device_id"] == "pc-1"
    assert monitor.observe_services() == []
    status["value"] = "running"; assert monitor.observe_services() == []
    status["value"] = "stopped"; monitor.observe_services(); assert monitor.observe_services()

def test_hardware_errors_skip_startup_history_then_emit_only_new_records():
    log = [{"provider": "disk", "event_id": 7, "record_id": 10}]
    queries = []
    def fake(after):
        queries.append(after); return [item for item in log if after is None or item["record_id"] > after]
    monitor = PCMonitor(device_id="pc-1", hardware_events=fake)
    assert monitor.observe_hardware() == []
    assert monitor.observe_hardware() == []
    log.append({"provider": "Ntfs", "event_id": 55, "record_id": 11})
    events = monitor.observe_hardware()
    assert [e["payload"]["code"] for e in events] == ["Ntfs:55"] and queries == [None, 10, 10]
    assert validate_event(events[0]["type"], events[0]).type == "pc.hardware_error.v1"
    assert monitor.observe_hardware() == []

def test_hardware_query_failure_does_not_stop_other_pc_alerts():
    def broken(_): raise RuntimeError("wevtutil failed")
    class Psutil:
        def cpu_percent(self, interval=None): return 1
        def virtual_memory(self): return SimpleNamespace(percent=1, available=9, total=100)
    monitor = PCMonitor(device_id="pc-1", psutil_module=Psutil(), watched_services=(), hardware_events=broken,
                        disk_usage=lambda _: SimpleNamespace(free=50, total=100), storage_threshold_bytes=20)
    assert monitor.observe("C:/") == []

def test_monitor_publishes_started_first_and_api_hosts_the_monitor():
    import asyncio, json
    published = []
    async def publish(subject, data): published.append((subject, json.loads(data)))
    class Stop(Exception): pass
    async def sleep(_): raise Stop
    monitor = PCMonitor(device_id="pc-1", watched_services=(), hardware_events=lambda _: [],
                        disk_usage=lambda _: SimpleNamespace(free=10, total=100), storage_threshold_bytes=20,
                        psutil_module=SimpleNamespace(cpu_percent=lambda interval=None: 1, virtual_memory=lambda: SimpleNamespace(percent=1, available=9, total=100)))
    import rino_life.pc as pc
    original, pc.asyncio.sleep = pc.asyncio.sleep, sleep
    try:
        with pytest.raises(Stop): asyncio.run(monitor.run(publish, "C:/"))
    finally: pc.asyncio.sleep = original
    assert published[0][0] == "pc.started.v1" and validate_event(*published[0])
    from pathlib import Path
    assert "run_pc_monitor" in (Path(__file__).parent.parent / "rino_life" / "api.py").read_text(encoding="utf-8")
