"""Construction of the provider-backed Home Tool for private service processes."""
from pathlib import Path

from .adapters.switchbot import SwitchBotAdapter
from .audit import AuditLog
from .models import DeviceRegistry
from .tool import HomeTool


def create_home_tool(config_dir: Path | None = None) -> HomeTool:
    config_dir = config_dir or Path(__file__).parent / "config"
    return HomeTool(
        SwitchBotAdapter(),
        DeviceRegistry.from_yaml(config_dir / "devices.yaml"),
        AuditLog(Path(__file__).parents[2] / "logs" / "home-actions.jsonl"),
    )
