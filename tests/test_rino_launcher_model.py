import json
import shutil
import subprocess

import pytest

from rino_launcher import status_model as sm


def test_parse_status_accepts_list_and_single_object():
    text = json.dumps([{"name": "A", "kind": "process", "port": 1, "state": "running", "pid": 5}])
    [status] = sm.parse_status(text)
    assert (status.name, status.port, status.state, status.pid) == ("A", 1, "running", 5)
    assert sm.parse_status(json.dumps({"name": "B", "state": "stopped"}))[0].name == "B"


def test_parse_status_normalizes_unknown_state():
    assert sm.parse_status('[{"name":"A","state":"weird"}]')[0].state == "unavailable"


@pytest.mark.parametrize("text", ["", "not json", "3", '[{"state":"running"}]'])
def test_parse_status_rejects_bad_input(text):
    with pytest.raises(ValueError):
        sm.parse_status(text)


def test_action_args_use_allowlist_only():
    known = {"SillyTavern"}
    args = sm.build_action_args("SillyTavern", "restart", known)
    assert args[-4:] == ["-Component", "SillyTavern", "-Action", "restart"]
    with pytest.raises(ValueError):
        sm.build_action_args("calc.exe", "start", known)
    with pytest.raises(ValueError):
        sm.build_action_args("SillyTavern", "format", known)


def test_profile_args_validate():
    assert sm.build_profile_args("chat")[-2:] == ["-Profile", "chat"]
    with pytest.raises(ValueError):
        sm.build_profile_args("evil")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="powershell not available")
def test_status_json_from_script_matches_schema():
    result = subprocess.run(
        ["powershell", *sm.build_status_args()], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    statuses = sm.parse_status(result.stdout)
    names = {s.name for s in statuses}
    assert {"SillyTavern", "Rino Agent Service", "Rino Life"} <= names
    assert all(s.state in sm.STATES for s in statuses)
