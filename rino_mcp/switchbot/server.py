"""Private stdio MCP adapter for the safe Rino Home Tool.

This process intentionally has no HTTP listener and no unlock tool.  It is
spawned only by the loopback Agent Service through stdio.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from rino.home.factory import create_home_tool

home = create_home_tool()
mcp = FastMCP("rino-switchbot", instructions="Rino's private SwitchBot adapter.")


@mcp.tool(name="home.get_environment", description="Get current room temperature, humidity, and CO2.")
def get_environment() -> dict:
    return home.get_environment()


@mcp.tool(name="home.light_on", description="Turn on the room light.")
def light_on() -> dict:
    return home.light_on()


@mcp.tool(name="home.light_off", description="Turn off the room light.")
def light_off() -> dict:
    return home.light_off()


@mcp.tool(name="home.aircon_on", description="Turn on the air conditioner.")
def aircon_on() -> dict:
    return home.aircon_on()


@mcp.tool(name="home.aircon_off", description="Turn off the air conditioner.")
def aircon_off() -> dict:
    return home.aircon_off()


@mcp.tool(name="home.set_temperature", description="Set the air conditioner target temperature from 16 to 30 Celsius.")
def set_temperature(celsius: float) -> dict:
    return home.set_temperature(celsius)


@mcp.tool(name="home.tv_on", description="Turn on the TV.")
def tv_on() -> dict:
    return home.tv_on()


@mcp.tool(name="home.tv_off", description="Turn off the TV.")
def tv_off() -> dict:
    return home.tv_off()


@mcp.tool(name="home.get_door_status", description="Get the entrance lock and door state.")
def get_door_status() -> dict:
    return home.get_door_status()


@mcp.tool(name="home.lock_door", description="Lock the entrance. The Agent Service requires fresh user approval before this tool can run.")
def lock_door() -> dict:
    return home.lock_door_after_approval(reason="MAF approval")


if __name__ == "__main__":
    mcp.run(transport="stdio")
