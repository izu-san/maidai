import json
from pathlib import Path

from rino.home.audit import AuditLog
from rino.home.models import Device, DeviceRegistry
from rino.home.tool import HomeTool


class FakeAdapter:
    def __init__(self): self.commands = []; self.locked = False
    def status(self, device_id):
        if device_id == "env": return {"temperature": 25.8, "humidity": 48, "CO2": 823}
        return {"lockState": "LOCKED" if self.locked else "UNLOCKED", "doorState": "CLOSED", "battery": 100}
    def command(self, device_id, command, parameter="default"):
        self.commands.append((device_id, command, parameter))
        if command == "lock": self.locked = True
        return {}


def home(tmp_path):
    registry = DeviceRegistry({"environment": Device("environment", "co2", "env", {}), "light": Device("light", "light", "light", {}),
        "aircon": Device("aircon", "aircon", "air", {}), "tv": Device("tv", "tv", "tv", {}),
        "entrance": Device("entrance", "lock", "door", {"lock": True})})
    return HomeTool(FakeAdapter(), registry, AuditLog(tmp_path / "audit.jsonl"), sleep=lambda _: None)


def test_environment_and_commands_are_normalized(tmp_path):
    tool = home(tmp_path)
    assert tool.get_environment()["data"]["co2_ppm"] == 823
    assert tool.get_environment()["data"]["verification"]["status"] == "VERIFIED"
    assert tool.set_temperature(26)["success"] is True
    assert tool.set_temperature(26)["data"]["verification"]["status"] == "UNAVAILABLE"
    assert tool.adapter.commands[-1] == ("air", "setAll", "26,1,3,on")
    assert tool.set_aircon_mode("cool")["success"] is True
    assert tool.adapter.commands[-1] == ("air", "setAll", "26,2,3,on")
    assert tool.set_aircon_fan("low")["success"] is True
    assert tool.adapter.commands[-1] == ("air", "setAll", "26,2,2,on")
    assert tool.set_temperature(40)["error"]["code"] == "INVALID_ARGUMENT"


def test_light_is_verified_when_the_device_exposes_power_state(tmp_path):
    tool = home(tmp_path)
    original_status = tool.adapter.status

    def status(device_id):
        if device_id == "light": return {"power": "on"}
        return original_status(device_id)

    tool.adapter.status = status
    assert tool.light_on()["data"]["verification"]["status"] == "VERIFIED"


def test_lock_is_only_available_through_the_approved_internal_path(tmp_path):
    tool = home(tmp_path)
    assert not hasattr(tool, "lock_door")
    assert not hasattr(tool, "issue_lock_confirmation")
    assert tool.lock_door_after_approval()["data"]["verification"]["status"] == "VERIFIED"
    assert any(json.loads(line)["action"] == "lock_door" for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines())


def test_approved_lock_path_verifies_without_exposing_unlock(tmp_path):
    tool = home(tmp_path)
    assert tool.lock_door_after_approval()["data"]["lock_state"] == "LOCKED"


def test_unlock_is_not_exposed():
    assert not hasattr(HomeTool, "unlock_door")
