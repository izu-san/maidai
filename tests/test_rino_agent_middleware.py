import asyncio
from types import SimpleNamespace

import pytest
from agent_framework import MiddlewareFailure

from rino_agent.audit import AgentAuditLog
from rino_agent.config import load_settings
from rino_agent.middleware import RinoPolicyMiddleware, verification_status
from rino_agent.sessions import SessionStore


def test_policy_middleware_denies_unknown_tool(tmp_path):
    middleware = RinoPolicyMiddleware(load_settings().tools, AgentAuditLog(tmp_path / "audit.jsonl", "key"))
    context = SimpleNamespace(function=SimpleNamespace(name="shell.run_arbitrary"), kwargs={}, result=None)

    async def next_call():
        raise AssertionError("must not execute")

    with pytest.raises(MiddlewareFailure):
        asyncio.run(middleware.process(context, next_call))


def test_policy_middleware_executes_allowlisted_tool(tmp_path):
    sessions = SessionStore()
    middleware = RinoPolicyMiddleware(load_settings().tools, AgentAuditLog(tmp_path / "audit.jsonl", "key"), sessions)
    context = SimpleNamespace(function=SimpleNamespace(name="home.light_off"), arguments={}, kwargs={"rino_mode": "ASSIST", "rino_goal_source": "user_request", "rino_session_id": "one"}, result=None)

    async def next_call():
        context.result = "ok"

    asyncio.run(middleware.process(context, next_call))
    assert context.result == "ok"
    assert "tool.executed" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert sessions.get_tool_executions("one")[0]["tool"] == "home.light_off"


def test_verification_status_reads_maf_text_content_result():
    content = SimpleNamespace(text='{"verification":{"status":"VERIFIED"}}')
    assert verification_status([content]) == "VERIFIED"
