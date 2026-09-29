import json

from rino_agent.image_generation import ImageGenerationConfig, ImageGenerationService


def test_queue_prompt_replaces_only_configured_placeholder(tmp_path, monkeypatch):
    workflow = tmp_path / "workflow.json"
    workflow.write_text(json.dumps({"placeholder": {"inputs": {"value": "keep"}}, "other": {"inputs": {"value": "unchanged"}}}), encoding="utf-8")
    config = ImageGenerationConfig(workflow, "placeholder", "value", "http://127.0.0.1:8188", "http://127.0.0.1:5001", tmp_path / "comfy", tmp_path / "public", "/user/images", "koboldcpp.exe", ("kobold",), ("comfy",))
    service = ImageGenerationService(config, None, None)

    captured = {}
    class Response:
        status = 200
        def read(self): return b'{"prompt_id":"prompt-1"}'
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def fake_open(request, timeout):
        captured.update(json.loads(request.data))
        return Response()
    monkeypatch.setattr("rino_agent.image_generation.urlopen", fake_open)

    assert service._queue_prompt("later supplied prompt") == "prompt-1"
    assert captured["prompt"]["placeholder"]["inputs"]["value"] == "later supplied prompt"
    assert captured["prompt"]["other"]["inputs"]["value"] == "unchanged"
