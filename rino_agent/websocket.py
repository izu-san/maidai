"""Authenticated local WebSocket fan-out for Agent lifecycle events."""
from __future__ import annotations

import asyncio
import hmac
import os

from fastapi import WebSocket


class AgentEventHub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> bool:
        await websocket.accept()
        try:
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except (TimeoutError, ValueError):
            await websocket.close(code=1008)
            return False
        expected = os.environ.get("RINO_AGENT_API_TOKEN", "")
        if not expected or not hmac.compare_digest(str(hello.get("token", "")), expected):
            await websocket.close(code=1008)
            return False
        self.clients.add(websocket)
        return True

    async def publish(self, event: dict) -> None:
        for client in list(self.clients):
            try:
                await client.send_json(event)
            except Exception:
                self.clients.discard(client)

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)
