import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

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


def test_parse_status_reads_started_at():
    text = json.dumps([
        {"name": "A", "state": "running", "started_at": "2026-09-29T05:42:42Z"},
        {"name": "B", "state": "stopped", "started_at": None},
        {"name": "C", "state": "running", "started_at": "garbage"},
    ])
    a, b, c = sm.parse_status(text)
    assert a.started_at == datetime(2026, 9, 29, 5, 42, 42, tzinfo=timezone.utc)
    assert b.started_at is None and c.started_at is None


def test_format_elapsed_units():
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
    assert sm.format_elapsed(now - timedelta(seconds=45), now) == "45秒"
    assert sm.format_elapsed(now - timedelta(minutes=12, seconds=5), now) == "12分"
    assert sm.format_elapsed(now - timedelta(hours=3, minutes=5), now) == "3時間5分"
    assert sm.format_elapsed(now - timedelta(days=2, hours=4), now) == "2日4時間"
    assert sm.format_elapsed(now + timedelta(hours=1), now) == "0秒"


def _svc(name, state="running", health=None, kind="process", profiles=()):
    return sm.ServiceStatus(name=name, kind=kind, port=1, state=state, health=health, profiles=tuple(profiles))


def test_parse_status_reads_health_url_profiles_and_sanitizes():
    text = json.dumps([
        {"name": "A", "state": "running", "health": "fail", "open_url": "http://127.0.0.1:8000/",
         "profiles": ["chat", "bogus"], "pid": {}},
        {"name": "B", "state": "running", "health": "weird", "open_url": "file:///C:/Windows/system32/calc.exe"},
        {"name": "C", "state": "running", "open_url": "http://evil.example/"},
    ])
    a, b, c = sm.parse_status(text)
    assert (a.health, a.open_url, a.profiles, a.pid) == ("fail", "http://127.0.0.1:8000/", ("chat",), None)
    assert b.health is None and b.open_url is None and b.profiles == ()
    assert c.open_url is None  # loopback 以外・http 以外の URL はウィジェットで開かない


def test_profile_states():
    statuses = [
        _svc("K", profiles=("chat", "full")),
        _svc("S", "stopped", profiles=("chat", "full")),
        _svc("R", profiles=("voice", "full")),
        _svc("E", health="fail", profiles=("voice",)),
        _svc("P", kind="project", profiles=("docker",)),
    ]
    states = sm.profile_states(statuses)
    assert states["chat"] == "partial"  # 一部のみ稼働
    assert states["voice"] == "partial"  # 全て稼働でも応答異常があれば ready にしない
    assert states["full"] == "partial"
    assert states["docker"] == "off"  # project 行だけでは判定しない
    ready = sm.profile_states([_svc("A", profiles=("chat",)), _svc("B", profiles=("chat",))])
    assert ready["chat"] == "ready"


def test_detect_problems():
    before = {"A": _svc("A"), "B": _svc("B", health="ok"), "C": _svc("C", "stopped"), "P": _svc("P", kind="project")}
    now = {"A": _svc("A", "stopped"), "B": _svc("B", health="fail"), "C": _svc("C", "stopped"),
           "P": _svc("P", "stopped", kind="project"), "N": _svc("N", "stopped")}
    assert sm.detect_problems(None, now) == []  # 初回は基準にするだけ
    assert sm.detect_problems(before, now) == ["A が停止しました", "B が応答しません"]
    assert sm.detect_problems(now, now) == []  # 継続中の異常は繰り返し通知しない
    assert sm.detect_problems({"A": _svc("A", "loading")}, {"A": _svc("A", "stopped")}) == ["A が停止しました"]


def test_parse_gpu():
    info = sm.parse_gpu("NVIDIA GeForce RTX 4070, 9123, 12282, 34\n")
    assert (info.name, info.used_mb, info.total_mb, info.util_percent) == ("NVIDIA GeForce RTX 4070", 9123, 12282, 34)
    assert sm.parse_gpu("") is None
    assert sm.parse_gpu("N/A, [N/A], [N/A]") is None
    assert sm.parse_gpu("gpu, x, y, z") is None


def test_parse_log_path_only_accepts_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "LOG_DIR", tmp_path / "logs" / "services")
    inside = sm.LOG_DIR / "sillytavern.log"
    assert sm.parse_log_path(f"noise\n{inside}\n") == inside.resolve()
    assert sm.parse_log_path(str(tmp_path / "other.log")) is None
    assert sm.parse_log_path(str(sm.LOG_DIR / ".." / ".." / "secret.txt")) is None
    assert sm.parse_log_path("") is None


def test_log_action_is_allowed_only_for_known_components():
    assert sm.build_action_args("SillyTavern", "log", {"SillyTavern"})[-2:] == ["-Action", "log"]
    with pytest.raises(ValueError):
        sm.build_action_args("calc.exe", "log", {"SillyTavern"})


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
