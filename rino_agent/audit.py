"""Append-only, secret-redacted audit records with an HMAC hash chain."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import ensure_private_directory

_SENSITIVE = {"authorization", "api_key", "apikey", "secret", "token", "password", "device_id"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower().replace("-", "_") in _SENSITIVE else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class AgentAuditLog:
    def __init__(self, path: Path, key: str):
        self.path = path
        self.key = key.encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_hash = self._read_last_hash()
        self._lock = threading.Lock()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return ""
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            try:
                return str(json.loads(line).get("record_hash", ""))
            except json.JSONDecodeError:
                continue
        return ""

    def write(self, event: str, **data: Any) -> None:
        with self._lock:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "data": redact(data),
                "previous_hash": self.previous_hash,
            }
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            record["record_hash"] = hmac.new(self.key, canonical.encode(), hashlib.sha256).hexdigest()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.previous_hash = record["record_hash"]

    def verify(self) -> bool:
        previous = ""
        if not self.path.exists():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            recorded_hash = record.pop("record_hash", "")
            if record.get("previous_hash") != previous:
                return False
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = hmac.new(self.key, canonical.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(recorded_hash, expected):
                return False
            previous = recorded_hash
        return True


def create_audit_log() -> AgentAuditLog:
    root = ensure_private_directory(Path(__file__).parent / "data" / "audit")
    key = os.environ.get("RINO_AGENT_AUDIT_KEY") or os.environ.get("RINO_AGENT_API_TOKEN")
    if not key:
        raise RuntimeError("RINO_AGENT_API_TOKEN must be configured before audit logging is available.")
    return AgentAuditLog(root / "agent-actions.jsonl", key)
