from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write(self, action: str, target: str, result: str, *, reason: str | None = None,
              confirmed_by_user: bool = False) -> None:
        event = {"timestamp": datetime.now(timezone.utc).astimezone().isoformat(), "source": "rino",
                 "action": action, "target": target, "reason": reason,
                 "confirmed_by_user": confirmed_by_user, "result": result}
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
