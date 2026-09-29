import asyncio, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from rino_life import agent_notifier
from rino_life.contracts import validate_event
from rino_life.notifications import NotificationRouter, evaluate_switchbot
from rino_life.switchbot_monitor import SwitchBotMonitor

def sb_event(subject, payload):
    return validate_event(subject, {"id": str(uuid4()), "type": subject, "occurred_at": "2026-09-29T12:00:00+09:00", "source": "switchbot_poller", "confidence": 1.0,
                                    "payload": {"device_id": "environment", **payload, "observed_at": "2026-09-29T12:00:00+09:00"}})

class Adapter:
    def __init__(self): self.env = {"temperature": 24.5, "humidity": 45, "CO2": 900}; self.lock = {"lockState": "LOCKED", "doorState": "CLOSED"}
    def status(self, device_id): return self.env if device_id == "env-id" else self.lock

class Registry:
    def __init__(self, missing=()): self.missing = missing
    def get(self, name):
        if name in self.missing: raise KeyError(name)
        return type("Device", (), {"device_id": {"environment": "env-id", "entrance": "door-id"}[name]})()

def monitor(adapter=None, now=None, **kwargs):
    clock = now if now is not None else [datetime(2026, 9, 29, 12, tzinfo=timezone.utc)]
    return SwitchBotMonitor(adapter or Adapter(), kwargs.pop("registry", Registry()), interval_seconds=300, clock=lambda: clock[0], **kwargs), clock

def test_environment_observations_validate_and_use_registry_keys_not_device_ids():
    events = monitor()[0].observe_environment()
    assert [e["type"] for e in events] == ["switchbot.temperature_changed.v1", "switchbot.humidity_changed.v1", "switchbot.co2_changed.v1"]
    assert all(validate_event(e["type"], e) and e["payload"]["device_id"] == "environment" for e in events)
    assert "env-id" not in json.dumps(events)

def test_unconfigured_or_missing_readings_emit_nothing_and_failures_are_isolated():
    assert monitor(registry=Registry(missing=("environment", "entrance")))[0].observe() == []
    adapter = Adapter(); adapter.env = {"temperature": 20}
    assert [e["type"] for e in monitor(adapter)[0].observe_environment()] == ["switchbot.temperature_changed.v1"]
    class Broken(Adapter):
        def status(self, device_id):
            if device_id == "env-id": raise RuntimeError("network")
            return super().status(device_id)
    assert [e["type"] for e in monitor(Broken())[0].observe()] == ["switchbot.device_state_changed.v1"]  # the failed environment poll does not block the lock

def test_entrance_emits_on_change_and_once_after_alert_threshold():
    m, clock = monitor(alert_after_minutes=30)
    first = m.observe_entrance(); assert first[0]["payload"]["state"] == {"lock_state": "LOCKED", "door_state": "CLOSED"}
    assert m.observe_entrance() == []
    m.adapter.lock = {"lockState": "UNLOCKED", "doorState": "CLOSED"}
    assert m.observe_entrance()[0]["payload"]["state"]["unlocked_minutes"] == 0
    clock[0] += timedelta(minutes=10); assert m.observe_entrance() == []
    clock[0] += timedelta(minutes=25)
    event = m.observe_entrance()[0]; assert event["payload"]["state"]["unlocked_minutes"] == 35
    assert validate_event(event["type"], event)
    clock[0] += timedelta(minutes=5); assert m.observe_entrance() == []
    m.adapter.lock = {"lockState": "LOCKED", "doorState": "CLOSED"}; assert m.observe_entrance()

def test_switchbot_rules_flag_breaches_and_report_recovery():
    assert evaluate_switchbot(sb_event("switchbot.co2_changed.v1", {"co2_ppm": 1600}))[0] == {"co2_high": True}
    assert evaluate_switchbot(sb_event("switchbot.co2_changed.v1", {"co2_ppm": 800}))[0] == {"co2_high": False}
    assert evaluate_switchbot(sb_event("switchbot.temperature_changed.v1", {"temperature_c": 31.0}))[0] == {"temperature_high": True, "temperature_low": False}
    assert evaluate_switchbot(sb_event("switchbot.humidity_changed.v1", {"humidity_percent": 25}))[0] == {"humidity_low": True, "humidity_high": False}
    state = {"lock_state": "UNLOCKED", "door_state": "OPEN", "unlocked_minutes": 31, "open_minutes": 5}
    door = sb_event("switchbot.device_state_changed.v1", {"device_id": "entrance", "device_type": "lock", "state": state})
    assert evaluate_switchbot(door)[0] == {"door_unlocked": True, "door_open": False, "lock_jammed": False}
    other = sb_event("switchbot.device_state_changed.v1", {"device_id": "lamp", "device_type": "light", "state": {}})
    assert evaluate_switchbot(other)[0] == {}

def test_router_routes_breaches_per_kind_and_resolves_recovered_alerts():
    router = NotificationRouter(connect=lambda _: None, notifier=lambda _: None)
    routed, resolved = [], []
    router._route = lambda event, **kw: routed.append(kw) or type("D", (), {"action": "send"})()
    router.resolve = lambda key, now=None: resolved.append(key)
    router.route(sb_event("switchbot.temperature_changed.v1", {"temperature_c": 32}))
    assert routed[0]["key"] == "switchbot.temperature_high:environment" and routed[0]["priority"] == 3
    assert routed[0]["payload"]["kind"] == "temperature_high" and routed[0]["payload"]["value"] == 32 and resolved == ["switchbot.temperature_low:environment"]
    routed.clear(); resolved.clear()
    assert router.route(sb_event("switchbot.co2_changed.v1", {"co2_ppm": 700})).reason["rule"] == "within_range"
    assert routed == [] and resolved == ["switchbot.co2_high:environment"]
    state = {"lock_state": "UNLOCKED", "door_state": "OPEN", "unlocked_minutes": 40, "open_minutes": 40}
    router.route(sb_event("switchbot.device_state_changed.v1", {"device_id": "entrance", "device_type": "lock", "state": state}))
    assert {kw["key"] for kw in routed} == {"switchbot.door_unlocked:entrance", "switchbot.door_open:entrance"}
    assert len({kw["marker"] for kw in routed}) == 2  # one event, two alerts: separate idempotency markers

def test_switchbot_messages_and_delivery(monkeypatch):
    assert "1600ppm" in agent_notifier.switchbot_message({"kind": "co2_high", "value": 1600, "limit": 1500})
    assert "31.5℃" in agent_notifier.switchbot_message({"kind": "temperature_high", "value": 31.5, "limit": 30})
    assert "35分" in agent_notifier.switchbot_message({"kind": "door_unlocked", "state": {"unlocked_minutes": 35}, "limit": 30})
    assert "ジャム" in agent_notifier.switchbot_message({"kind": "lock_jammed", "state": {}})
    sent = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b"{}"
    monkeypatch.setattr(agent_notifier, "urlopen", lambda request, timeout: sent.update(body=json.loads(request.data)) or Response())
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t"); monkeypatch.delenv("RINO_AGENT_URL", raising=False)
    agent_notifier.agent_chat_notifier({"dedupe_key": "switchbot.co2_high:environment", "priority": 2, "payload": {"kind": "co2_high", "value": 1600, "limit": 1500}})
    assert sent["body"]["dedupe_key"] == "switchbot.co2_high:environment" and "換気" in sent["body"]["message"]

def test_monitor_is_hosted_by_the_api_and_has_a_notification_consumer():
    root = Path(__file__).parent.parent / "rino_life"
    assert "run_switchbot_monitor" in (root / "api.py").read_text(encoding="utf-8")
    assert "life-notification-switchbot-v1" in (root / "nats_setup.py").read_text(encoding="utf-8")
