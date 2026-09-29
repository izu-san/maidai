import json

from rino_life import mcp_server


def test_life_mcp_posts_only_through_loopback_api(monkeypatch):
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"event_id":"event-1","updated":[]}'

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method(), json.loads(request.data)))
        return Response()

    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)
    assert mcp_server.record_laundry_completed(2)["event_id"] == "event-1"
    assert calls == [("http://127.0.0.1:54330/events", "POST", {"type": "life.laundry.completed.v1", "payload": {"count": 2}, "source": "rino-agent"})]
