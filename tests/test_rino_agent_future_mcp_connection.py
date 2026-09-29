import asyncio

from rino_agent.mcp import connect_servers


def test_future_private_mcp_servers_connect_without_touching_external_services():
    async def check():
        stack, servers = await connect_servers({
            "obs": {"enabled": True, "transport": "stdio", "trust": "internal"},
            "comfyui": {"enabled": True, "transport": "stdio", "trust": "internal"},
            "windows": {"enabled": True, "transport": "stdio", "trust": "internal"},
        })
        try:
            assert {tool.name for tool in servers["obs"].functions} >= {"obs.get_status", "obs.set_scene"}
            assert {tool.name for tool in servers["comfyui"].functions} >= {"comfyui.get_status", "comfyui.queue_prompt"}
            assert {tool.name for tool in servers["windows"].functions} >= {"process.check", "file.exists"}
        finally:
            await stack.aclose()
    asyncio.run(check())
