from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .adapters.switchbot import SwitchBotAdapter
from .audit import AuditLog
from .errors import HomeError, result_error
from .models import DeviceRegistry


class HomeTool:
    """The only home API exposed to Rino. It deliberately has no unlock method."""
    def __init__(self, adapter: SwitchBotAdapter, registry: DeviceRegistry, audit_log: AuditLog,
                 *, sleep: Callable[[float], None] = time.sleep):
        self.adapter, self.registry, self.audit = adapter, registry, audit_log
        self._environment_cache: tuple[float, dict] | None = None
        self._sleep = sleep
        # IR remotes cannot reliably report their current settings. These are
        # the settings used when a fresh process changes only mode or fan speed.
        self._aircon_state = {"temperature": 26, "mode": 1, "fan_speed": 3, "power": "on"}

    def _run(self, action: str, target: str, operation: Callable[[], dict], *, reason: str | None = None,
             confirmed: bool = False) -> dict:
        try:
            data = operation()
            self.audit.write(action, target, "success", reason=reason, confirmed_by_user=confirmed)
            return {"success": True, "data": data, "error": None}
        except HomeError as error:
            self.audit.write(action, target, "failure", reason=reason, confirmed_by_user=confirmed)
            return result_error(error)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def get_environment(self) -> dict:
        if self._environment_cache and time.monotonic() - self._environment_cache[0] < 45:
            return {"success": True, "data": self._environment_cache[1], "error": None}
        def operation():
            device = self.registry.get("environment")
            status = self.adapter.status(device.device_id)
            data = {"temperature_c": status.get("temperature"), "humidity_percent": status.get("humidity"),
                    "co2_ppm": status.get("CO2", status.get("co2")), "updated_at": self._now(),
                    "verification": {"status": "VERIFIED", "source": "switchbot.status"}}
            self._environment_cache = (time.monotonic(), data)
            return data
        return self._run("get_environment", "co2_meter", operation)

    def _command(self, target: str, action: str, command: str, parameter: str = "default", *, reason: str | None = None,
                 expected_power: str | None = None) -> dict:
        def operation():
            self.adapter.command(self.registry.get(target).device_id, command, parameter)
            if expected_power is not None:
                device = self.registry.get(target)
                for delay in (1, 2, 4):
                    self._sleep(delay)
                    status = self.adapter.status(device.device_id)
                    power = str(status.get("power", "")).upper()
                    if power == expected_power:
                        return {
                            "device": target,
                            "verification": {"status": "VERIFIED", "source": "switchbot.status"},
                        }
            return {
                "device": target,
                "verification": {
                    "status": "UNAVAILABLE",
                    "reason": "The configured device does not expose authoritative state for this command.",
                },
            }
        return self._run(action, target, operation, reason=reason)

    def light_on(self, *, reason: str | None = None) -> dict: return self._command("light", "light_on", "turnOn", reason=reason, expected_power="ON")
    def light_off(self, *, reason: str | None = None) -> dict: return self._command("light", "light_off", "turnOff", reason=reason, expected_power="OFF")
    def aircon_on(self, *, reason: str | None = None) -> dict: return self._command("aircon", "aircon_on", "turnOn", reason=reason)
    def aircon_off(self, *, reason: str | None = None) -> dict: return self._command("aircon", "aircon_off", "turnOff", reason=reason)
    def tv_on(self, *, reason: str | None = None) -> dict: return self._command("tv", "tv_on", "turnOn", reason=reason)
    def tv_off(self, *, reason: str | None = None) -> dict: return self._command("tv", "tv_off", "turnOff", reason=reason)

    def set_temperature(self, celsius: float, *, reason: str | None = None) -> dict:
        if not isinstance(celsius, (int, float)) or not 16 <= celsius <= 30:
            return result_error(HomeError("INVALID_ARGUMENT", "Temperature must be between 16 and 30 Celsius."))
        def operation():
            self.adapter.command(self.registry.get("aircon").device_id, "setAll",
                                 f"{celsius:g},1,3,on")
            self._aircon_state["temperature"] = celsius
            return {"device": "air_conditioner", "temperature": celsius,
                    "verification": {"status": "UNAVAILABLE", "reason": "Infrared state cannot be read authoritatively."}}
        return self._run("set_temperature", "aircon", operation, reason=reason)

    def set_aircon_mode(self, mode: str, *, reason: str | None = None) -> dict:
        codes = {"auto": 1, "cool": 2, "dry": 3, "fan": 4, "heat": 5}
        if mode not in codes: return result_error(HomeError("INVALID_ARGUMENT", "Unsupported air conditioner mode."))
        def operation():
            state = self._aircon_state
            self.adapter.command(self.registry.get("aircon").device_id, "setAll",
                                 f"{state['temperature']:g},{codes[mode]},{state['fan_speed']},{state['power']}")
            state["mode"] = codes[mode]
            return {"device": "air_conditioner", "mode": mode,
                    "verification": {"status": "UNAVAILABLE", "reason": "Infrared state cannot be read authoritatively."}}
        return self._run("set_aircon_mode", "aircon", operation, reason=reason)

    def set_aircon_fan(self, speed: str, *, reason: str | None = None) -> dict:
        codes = {"auto": 1, "low": 2, "medium": 3, "high": 4}
        if speed not in codes: return result_error(HomeError("INVALID_ARGUMENT", "Unsupported fan speed."))
        def operation():
            state = self._aircon_state
            self.adapter.command(self.registry.get("aircon").device_id, "setAll",
                                 f"{state['temperature']:g},{state['mode']},{codes[speed]},{state['power']}")
            state["fan_speed"] = codes[speed]
            return {"device": "air_conditioner", "fan_speed": speed,
                    "verification": {"status": "UNAVAILABLE", "reason": "Infrared state cannot be read authoritatively."}}
        return self._run("set_aircon_fan", "aircon", operation, reason=reason)

    def get_door_status(self) -> dict:
        def operation():
            status = self.adapter.status(self.registry.get("entrance").device_id)
            lock = str(status.get("lockState", status.get("lock_state", "UNKNOWN"))).upper()
            door = str(status.get("doorState", status.get("door_state", "UNKNOWN"))).upper()
            return {"lock_state": lock if lock in {"LOCKED", "UNLOCKED", "JAMMED"} else "UNKNOWN",
                    "door_state": door if door in {"OPEN", "CLOSED"} else "UNKNOWN",
                    "battery_percent": status.get("battery"), "updated_at": self._now(),
                    "verification": {"status": "VERIFIED", "source": "switchbot.status"}}
        return self._run("get_door_status", "entrance_lock", operation)

    def lock_door_after_approval(self, *, reason: str | None = None) -> dict:
        """Execute only after the owning Agent Service completed a MAF approval flow.

        This method is intentionally not registered by the legacy HTTP bridge.
        Its sole caller after migration is the private stdio MCP child process.
        """
        def operation():
            device = self.registry.get("entrance")
            if not device.permissions.get("lock", False): raise HomeError("PERMISSION_DENIED", "Door locking is disabled by configuration.")
            self.adapter.command(device.device_id, "lock")
            # Never resend a security command. Cloud state can lag behind the
            # command response, so only poll status with exponential backoff.
            verified = None
            for delay in (1, 2, 4):
                self._sleep(delay)
                verified = self.get_door_status()
                if verified["success"] and verified["data"]["lock_state"] == "LOCKED":
                    return {**verified["data"], "verification": {"status": "VERIFIED", "source": "switchbot.status"}}
            raise HomeError("COMMAND_FAILED", "Door lock could not be verified.")
        return self._run("lock_door", "entrance_lock", operation, reason=reason, confirmed=True)
