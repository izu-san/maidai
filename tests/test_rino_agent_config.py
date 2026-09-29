from rino_agent.config import load_settings
from rino_agent.policy import RiskLevel
import pytest


def test_local_config_exposes_only_internal_enabled_mcp_servers():
    settings = load_settings()
    assert settings.servers == {
        "switchbot": {"enabled": True, "transport": "stdio", "trust": "internal"},
        "life": {"enabled": True, "transport": "stdio", "trust": "internal"},
    }
    assert settings.tools["home.lock_door"].risk is RiskLevel.HIGH
    assert settings.tools["obs.start_stream"].risk is RiskLevel.HIGH
    assert "shell.run_arbitrary" not in settings.tools
    assert settings.checkpoint_path == "./data/checkpoints"


def test_config_rejects_network_model_endpoint(tmp_path):
    (tmp_path / "agent.yaml").write_text("agent:\n  model: {base_url: http://192.168.1.2:5001/v1/, model: x}\n  checkpoint: {path: ./x}\n", encoding="utf-8")
    (tmp_path / "policy.yaml").write_text("tools: {}\n", encoding="utf-8")
    (tmp_path / "mcp.yaml").write_text("servers: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="loopback"):
        load_settings(tmp_path)
