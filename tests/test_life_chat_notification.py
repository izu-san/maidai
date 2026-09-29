import json
from rino_agent.notifications import MAX_MESSAGES, TTL_SECONDS, NotificationInbox
from rino_life import agent_notifier
from rino_life.agent_notifier import agent_chat_notifier, consumable_low_message

LOW = {"item_id": "cat_food", "name": "猫のご飯", "unit": "g", "remaining": 280.0, "threshold": 300.0}

def test_message_formats_amounts():
    assert consumable_low_message(LOW) == "猫のご飯の残りが280gになりました（通知の目安は300g）。そろそろ買い足しませんか？"
    assert "12.5ml" in consumable_low_message({**LOW, "unit": "ml", "remaining": 12.5})

def test_pc_messages_format():
    gib = 1024 ** 3
    storage = {"path": "C:/", "free_bytes": 10 * gib, "total_bytes": 500 * gib, "threshold_bytes": 20 * gib}
    assert agent_notifier.pc_storage_low_message(storage) == "PCのC:/の空き容量が10.0GBまで減っています（目安は20.0GB）。不要なファイルを整理しませんか？"
    cpu = {"usage_percent": 95.5, "threshold_percent": 90.0}
    assert "95.5%" in agent_notifier.pc_cpu_high_message(cpu) and "90%" in agent_notifier.pc_cpu_high_message(cpu)
    assert "メモリ使用率が95.5%" in agent_notifier.pc_memory_high_message(cpu)

def test_notifier_posts_pc_storage_low(monkeypatch):
    sent = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b"{}"
    monkeypatch.setattr(agent_notifier, "urlopen", lambda request, timeout: sent.update(body=json.loads(request.data)) or Response())
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t"); monkeypatch.delenv("RINO_AGENT_URL", raising=False)
    payload = {"path": "C:/", "free_bytes": 1024 ** 3, "total_bytes": 2 * 1024 ** 3, "threshold_bytes": 2 * 1024 ** 3}
    agent_chat_notifier({"dedupe_key": "pc.storage_low.v1:pc:C:/", "priority": 3, "payload": payload})
    assert sent["body"]["dedupe_key"] == "pc.storage_low.v1:pc:C:/" and "空き容量" in sent["body"]["message"]

def test_inbox_drains_once_and_replaces_same_key():
    inbox = NotificationInbox(); inbox.add("a", "old"); inbox.add("b", "b1"); inbox.add("a", "new")
    assert inbox.drain() == ["b1", "new"] and inbox.drain() == []

def test_inbox_is_bounded_and_expires():
    now = [0.0]; inbox = NotificationInbox(clock=lambda: now[0])
    for index in range(MAX_MESSAGES + 5): inbox.add(str(index), str(index))
    inbox.add("late", "late"); now[0] = TTL_SECONDS + 1; inbox.add("fresh", "fresh")
    assert inbox.drain() == ["fresh"]

def test_notifier_posts_to_loopback_inbox(monkeypatch):
    sent = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b"{}"
    def fake_urlopen(request, timeout): sent.update(url=request.full_url, auth=request.headers["Authorization"], body=json.loads(request.data)); return Response()
    monkeypatch.setattr(agent_notifier, "urlopen", fake_urlopen); monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t"); monkeypatch.delenv("RINO_AGENT_URL", raising=False)
    agent_chat_notifier({"dedupe_key": "consumable-low:cat_food", "priority": 2, "payload": LOW})
    assert sent["url"] == "http://127.0.0.1:8766/internal/notifications" and sent["auth"] == "Bearer t" and sent["body"]["dedupe_key"] == "consumable-low:cat_food"

def test_notifier_ignores_other_kinds_and_never_raises(monkeypatch):
    monkeypatch.setattr(agent_notifier, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    agent_chat_notifier({"dedupe_key": "pc.hardware_error.v1:pc:E1", "payload": {}})
    monkeypatch.setattr(agent_notifier, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))); monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t")
    agent_chat_notifier({"dedupe_key": "consumable-low:x", "payload": LOW})

def test_notifier_rejects_non_loopback_agent_url(monkeypatch):
    monkeypatch.setattr(agent_notifier, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t"); monkeypatch.setenv("RINO_AGENT_URL", "http://example.com:8766")
    agent_chat_notifier({"dedupe_key": "consumable-low:x", "payload": LOW})

def test_pc_service_and_hardware_messages():
    assert "「EventLog」" in agent_notifier.pc_service_failed_message({"service": "EventLog"})
    assert "disk:7" in agent_notifier.pc_hardware_error_message({"code": "disk:7"})
