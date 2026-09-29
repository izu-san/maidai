"""Rino policy enforcement at the last point before a MAF tool invocation."""
from __future__ import annotations

import json

from agent_framework import FunctionInvocationContext, FunctionMiddleware, MiddlewareFailure

from .audit import redact
from .config import ToolPolicy
from .policy import PolicyDecision, PolicyInput, decide_policy


def result_text(result) -> str:
    if isinstance(result, list):
        return "\n".join(str(getattr(item, "text", "")) for item in result)
    return str(getattr(result, "text", result))


def safe_result(result):
    text = result_text(result)
    try:
        return redact(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        return text[:4_096]


def verification_status(result) -> str:
    text = result_text(result)
    if "VERIFIED" in text:
        return "VERIFIED"
    if "UNAVAILABLE" in text:
        return "UNAVAILABLE"
    return "NOT_REPORTED"


class RinoPolicyMiddleware(FunctionMiddleware):
    def __init__(self, policies: dict[str, ToolPolicy], audit, sessions=None):
        self.policies = policies
        self.audit = audit
        self.sessions = sessions

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        policy = self.policies.get(context.function.name)
        if policy is None:
            raise MiddlewareFailure(f"Tool is not in Rino policy: {context.function.name}")
        mode = str(context.kwargs.get("rino_mode", "ASSIST"))
        source = str(context.kwargs.get("rino_goal_source", "user_request"))
        decision = decide_policy(PolicyInput(policy.risk, mode, source, source == "user_request", policy.autonomous))
        if decision is PolicyDecision.DENY:
            self.audit.write("tool.denied", tool=context.function.name, risk=policy.risk.value, mode=mode, goal_source=source)
            raise MiddlewareFailure(f"Rino policy denied {context.function.name}")
        await call_next()
        self.audit.write(
            "tool.executed",
            tool=context.function.name,
            arguments=dict(context.arguments) if hasattr(context.arguments, "items") else str(context.arguments),
            risk=policy.risk.value,
            decision=decision.value,
            result_present=context.result is not None,
            result=safe_result(context.result),
            verification=verification_status(context.result),
        )
        session_id = context.kwargs.get("rino_session_id")
        if self.sessions is not None and isinstance(session_id, str):
            self.sessions.record_tool_execution(session_id, {
                "tool": context.function.name,
                "arguments": redact(dict(context.arguments) if hasattr(context.arguments, "items") else str(context.arguments)),
                "verification": verification_status(context.result),
            })
