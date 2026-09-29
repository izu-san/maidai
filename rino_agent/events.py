"""Registered event routing; events never create arbitrary autonomous goals."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .storage import ensure_private_directory


@dataclass(frozen=True)
class Event:
    type: str
    source: str
    timestamp: datetime
    data: dict[str, Any]


@dataclass
class WaitingTask:
    task_id: str
    event_type: str
    payload: dict[str, Any]
    expires_at: float
    status: str = "WAITING"


class TaskStore:
    """Small tamper-evident store for notification-only event waiters."""

    def __init__(self, path, key: str):
        self.path = path
        self.key = key.encode("utf-8")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        payload = envelope.get("payload")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(self.key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(envelope.get("hmac", "")), expected):
            raise ValueError("Event task store integrity check failed.")
        return payload if isinstance(payload, list) else []

    def save(self, tasks: dict[str, WaitingTask]) -> None:
        payload = [
            {"task_id": task.task_id, "event_type": task.event_type, "payload": task.payload,
             "expires_at": task.expires_at, "status": task.status}
            for task in tasks.values()
        ]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        envelope = {"payload": payload, "hmac": hmac.new(self.key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.path)


class EventGateway:
    def __init__(self, cooldowns: dict[str, int] | None = None, store: TaskStore | None = None):
        self.cooldowns = cooldowns or {"vision.idle_detected": 600}
        self.last_seen: dict[str, float] = {}
        self.tasks: dict[str, WaitingTask] = {}
        self.store = store
        if store:
            self.tasks = {
                item["task_id"]: WaitingTask(**item)
                for item in store.load()
                if item.get("status") == "WAITING" and float(item.get("expires_at", 0)) > time.time()
            }
            self._save()

    def _save(self) -> None:
        if self.store:
            self.store.save(self.tasks)

    def publish(self, event: Event) -> list[WaitingTask]:
        monotonic_now = time.monotonic()
        now = time.time()
        cooldown = self.cooldowns.get(event.type, 0)
        if monotonic_now - self.last_seen.get(event.type, float("-inf")) < cooldown:
            return []
        self.last_seen[event.type] = monotonic_now
        triggered = []
        for task in self.tasks.values():
            if task.status == "WAITING" and task.event_type == event.type and task.expires_at > now:
                task.status = "TRIGGERED"
                triggered.append(task)
        self.expire(now)
        self._save()
        return triggered

    def add_task(self, event_type: str, payload: dict[str, Any], ttl_seconds: int) -> WaitingTask:
        task = WaitingTask(uuid.uuid4().hex, event_type, payload, time.time() + ttl_seconds)
        self.tasks[task.task_id] = task
        self._save()
        return task

    def expire(self, now: float | None = None) -> None:
        now = now or time.time()
        for task in self.tasks.values():
            if task.status == "WAITING" and task.expires_at <= now:
                task.status = "EXPIRED"
        self._save()


def create_event_gateway(data_path, key: str) -> EventGateway:
    root = ensure_private_directory(data_path)
    return EventGateway(store=TaskStore(root / "waiting-tasks.json", key))
