from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import HomeError


@dataclass(frozen=True)
class Device:
    name: str
    alias: str
    device_id: str
    permissions: dict[str, bool]


class DeviceRegistry:
    def __init__(self, devices: dict[str, Device]):
        self._devices = devices

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DeviceRegistry":
        with open(path, encoding="utf-8") as file:
            config: dict[str, Any] = yaml.safe_load(file) or {}
        devices = {}
        for name, entry in (config.get("devices") or {}).items():
            env_name = entry.get("device_id_env")
            device_id = os.getenv(env_name or "")
            if not device_id:
                # Fail when actually used; this permits configuring only the devices owned.
                device_id = ""
            devices[name] = Device(name, entry.get("alias", name), device_id, entry.get("permissions") or {})
        return cls(devices)

    def get(self, name: str) -> Device:
        try:
            device = self._devices[name]
        except KeyError as exc:
            raise HomeError("DEVICE_NOT_FOUND", "Configured device is not available.") from exc
        if not device.device_id:
            raise HomeError("DEVICE_NOT_FOUND", "Device is not configured. Set its device ID environment variable.")
        return device
