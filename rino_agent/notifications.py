"""In-memory inbox for Life notifications awaiting display in the chat UI.

Notifications are display-only messages; they never start an Agent run.
"""
from __future__ import annotations

import time
from collections import OrderedDict

MAX_MESSAGES = 50
TTL_SECONDS = 24 * 60 * 60


class NotificationInbox:
    def __init__(self, *, clock=time.time):
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._clock = clock

    def add(self, dedupe_key: str, message: str) -> None:
        # A newer notification for the same item replaces the undelivered one.
        self._items.pop(dedupe_key, None)
        self._items[dedupe_key] = (self._clock(), message)
        while len(self._items) > MAX_MESSAGES:
            self._items.popitem(last=False)

    def drain(self) -> list[str]:
        cutoff = self._clock() - TTL_SECONDS
        messages = [message for created, message in self._items.values() if created >= cutoff]
        self._items.clear()
        return messages
