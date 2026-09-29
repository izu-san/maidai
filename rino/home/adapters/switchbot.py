from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from ..errors import HomeError


class SwitchBotAdapter:
    """Small SwitchBot OpenAPI v1.1 adapter; credentials never leave this class."""

    base_url = "https://api.switch-bot.com/v1.1"

    def __init__(self, token: str | None = None, secret: str | None = None, *, timeout: float = 10):
        self._token = token or os.getenv("SWITCHBOT_TOKEN")
        self._secret = secret or os.getenv("SWITCHBOT_SECRET")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self._token or not self._secret:
            raise HomeError("AUTH_ERROR", "SwitchBot credentials are not configured.")
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        raw = f"{self._token}{timestamp}{nonce}".encode()
        signature = base64.b64encode(hmac.new(self._secret.encode(), raw, hashlib.sha256).digest()).decode()
        return {"Authorization": self._token, "sign": signature, "t": timestamp, "nonce": nonce,
                "Content-Type": "application/json"}

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=payload, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                decoded = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise HomeError("AUTH_ERROR", "SwitchBot authentication failed.") from exc
            if exc.code == 429:
                raise HomeError("RATE_LIMITED", "SwitchBot rate limit reached.") from exc
            raise HomeError("NETWORK_ERROR", "SwitchBot request failed.") from exc
        except urllib.error.URLError as exc:
            raise HomeError("NETWORK_ERROR", "Cannot reach SwitchBot.") from exc
        except TimeoutError as exc:
            raise HomeError("TIMEOUT", "SwitchBot request timed out.") from exc
        if decoded.get("statusCode") not in (100, 200):
            raise HomeError("COMMAND_FAILED" if method == "POST" else "STATUS_UNAVAILABLE",
                            "SwitchBot did not complete the request.")
        return decoded.get("body") or {}

    def status(self, device_id: str) -> dict[str, Any]:
        return self._request("GET", f"/devices/{device_id}/status")

    def command(self, device_id: str, command: str, parameter: str = "default") -> dict[str, Any]:
        return self._request("POST", f"/devices/{device_id}/commands",
                             {"command": command, "parameter": parameter, "commandType": "command"})
