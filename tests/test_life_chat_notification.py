import json
from rino_agent.notifications import MAX_MESSAGES, TTL_SECONDS, NotificationInbox
from rino_life import agent_notifier
from rino_life.agent_notifier import agent_chat_notifier, consumable_low_message

LOW = {"item_id": "cat_food", "name": "猫のご飯", "unit": "g", "remaining": 280.0, "threshold": 300.0}

def test_message_formats_amounts():
    assert consumable_low_message(LOW) == "猫のご飯の残りが280gになりました（通知の目安は300g）。そろそろ買い足しませんか？"
    assert "12.5ml" in consumable_low_message({**LOW, "unit": "ml", "remaining": 12.5})

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
    agent_chat_notifier({"dedupe_key": "pc.storage_low.v1:pc:C", "payload": {}})
    monkeypatch.setattr(agent_notifier, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))); monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t")
    agent_chat_notifier({"dedupe_key": "consumable-low:x", "payload": LOW})

def test_notifier_rejects_non_loopback_agent_url(monkeypatch):
    monkeypatch.setattr(agent_notifier, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setenv("RINO_AGENT_API_TOKEN", "t"); monkeypatch.setenv("RINO_AGENT_URL", "http://example.com:8766")
    agent_chat_notifier({"dedupe_key": "consumable-low:x", "payload": LOW})
