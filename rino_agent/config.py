"""Strict local configuration loading for Rino Agent Service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .policy import RiskLevel


@dataclass(frozen=True)
class ToolPolicy:
    risk: RiskLevel
    autonomous: bool = False
    approval: str | None = None


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    checkpoint_path: str
    tools: dict[str, ToolPolicy]
    servers: dict[str, dict]


def load_settings(root: Path | None = None) -> Settings:
    root = root or Path(__file__).parent / "config"
    agent = yaml.safe_load((root / "agent.yaml").read_text(encoding="utf-8"))["agent"]
    policies = yaml.safe_load((root / "policy.yaml").read_text(encoding="utf-8"))["tools"]
    servers = yaml.safe_load((root / "mcp.yaml").read_text(encoding="utf-8"))["servers"]
    enabled = {name: server for name, server in servers.items() if server.get("enabled")}
    if any(server.get("trust") != "internal" for server in enabled.values()):
        raise ValueError("Only explicitly internal MCP servers may be enabled.")
    if any(server.get("transport") != "stdio" for server in enabled.values()):
        raise ValueError("Rino MCP servers must use private stdio transport.")
    endpoint = agent["model"]["base_url"]
    if urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The local model endpoint must bind to loopback.")
    return Settings(
        base_url=endpoint,
        model=agent["model"]["model"],
        checkpoint_path=agent["checkpoint"]["path"],
        tools={name: ToolPolicy(RiskLevel(item["risk"]), item.get("autonomous", False), item.get("approval")) for name, item in policies.items()},
        servers=enabled,
    )
