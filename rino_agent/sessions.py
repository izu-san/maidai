"""In-memory session and approval state with fail-closed expiry rules."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any


class ApprovalError(ValueError):
    pass


@dataclass
class PendingApproval:
    approval_id: str
    session_id: str
    tool_name: str
    arguments_hash: str
    request: Any
    expires_at: float
    used: bool = False


class SessionStore:
    def __init__(self, *, approval_ttl_seconds: int = 60):
        self.sessions: dict[str, Any] = {}
        self.statuses: dict[str, str] = {}
        self.approvals: dict[str, PendingApproval] = {}
        self.execution_options: dict[str, dict[str, str]] = {}
        self.goals: dict[str, str] = {}
        self.tool_executions: dict[str, list[dict[str, Any]]] = {}
        self.approval_ttl_seconds = approval_ttl_seconds

    def add_approval(self, session_id: str, request: Any) -> PendingApproval:
        function_call = request.function_call
        if function_call is None:
            raise ApprovalError("Approval request has no function call.")
        arguments = json.dumps(function_call.arguments, sort_keys=True, separators=(",", ":"), default=str)
        approval = PendingApproval(
            approval_id=secrets.token_urlsafe(24),
            session_id=session_id,
            tool_name=function_call.name,
            arguments_hash=hashlib.sha256(arguments.encode()).hexdigest(),
            request=request,
            expires_at=time.monotonic() + self.approval_ttl_seconds,
        )
        self.approvals[approval.approval_id] = approval
        self.statuses[session_id] = "WAITING_APPROVAL"
        return approval

    def invalidate_session_approvals(self, session_id: str) -> None:
        for approval_id, approval in list(self.approvals.items()):
            if approval.session_id == session_id:
                del self.approvals[approval_id]
        self.statuses[session_id] = "CANCELLED"

    def set_execution_options(self, session_id: str, *, mode: str, goal_source: str) -> None:
        """Keep policy context stable across a human approval continuation."""
        self.execution_options[session_id] = {"mode": mode, "goal_source": goal_source}

    def get_execution_options(self, session_id: str) -> dict[str, str]:
        return self.execution_options.get(session_id, {"mode": "ASSIST", "goal_source": "user_request"}).copy()

    def begin_goal(self, session_id: str, goal: str) -> None:
        self.goals[session_id] = goal
        self.tool_executions[session_id] = []

    def record_tool_execution(self, session_id: str, record: dict[str, Any]) -> None:
        self.tool_executions.setdefault(session_id, []).append(record)

    def get_tool_executions(self, session_id: str) -> list[dict[str, Any]]:
        return self.tool_executions.get(session_id, []).copy()

    def pending_for_session(self, session_id: str) -> PendingApproval:
        pending = [approval for approval in self.approvals.values() if approval.session_id == session_id and not approval.used and approval.expires_at > time.monotonic()]
        if len(pending) != 1:
            raise ApprovalError("Exactly one unexpired pending approval is required.")
        return pending[0]

    def consume_approval(self, approval_id: str, session_id: str) -> PendingApproval:
        approval = self.approvals.get(approval_id)
        if approval is None or approval.used or approval.session_id != session_id:
            raise ApprovalError("Approval is invalid or already used.")
        if approval.expires_at <= time.monotonic():
            del self.approvals[approval_id]
            raise ApprovalError("Approval has expired.")
        approval.used = True
        return approval


def normalize_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return arguments
