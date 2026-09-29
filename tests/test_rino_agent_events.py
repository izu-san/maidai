from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rino_agent.main import EventRequest, WaitingTaskRequest

from rino_agent.events import Event, EventGateway, TaskStore


def test_registered_task_triggers_once_and_unregistered_event_cannot_create_goal():
    gateway = EventGateway()
    task = gateway.add_task("comfyui.generation_completed", {"message": "done"}, 60)
    event = Event("comfyui.generation_completed", "comfyui", datetime.now(timezone.utc), {})
    assert [item.task_id for item in gateway.publish(event)] == [task.task_id]
    assert gateway.publish(event) == []


def test_cooldown_drops_repeated_idle_event():
    gateway = EventGateway({"vision.idle_detected": 600})
    event = Event("vision.idle_detected", "vision", datetime.now(timezone.utc), {})
    assert gateway.publish(event) == []
    assert gateway.publish(event) == []


def test_waiting_task_survives_restart_with_integrity_protection(tmp_path):
    store = TaskStore(tmp_path / "tasks.json", "test-key")
    first = EventGateway(store=store)
    task = first.add_task("comfyui.generation_completed", {"message": "done"}, 60)
    restored = EventGateway(store=store)
    assert restored.tasks[task.task_id].status == "WAITING"


def test_event_input_requires_timezone_and_bounds_untrusted_data():
    with pytest.raises(ValidationError):
        EventRequest(type="vision.idle_detected", source="vision", timestamp="2026-09-28T12:00:00")
    with pytest.raises(ValidationError):
        WaitingTaskRequest(event_type="vision.idle_detected", payload={"text": "x" * 20_000}, ttl_seconds=60)
