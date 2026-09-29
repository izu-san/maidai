"""Loopback API boundary for the Rino Agent Service.

External actions are intentionally not wired until switchbot-mcp is available.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import os
from pathlib import Path
import secrets
import json

from agent_framework import Agent, Message
from agent_framework import FileCheckpointStorage
from agent_framework.openai import OpenAIChatCompletionClient
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .policy import PolicyDecision, PolicyInput, RiskLevel, decide_policy
from .audit import create_audit_log, redact
from .security import require_local_api_token
from .sessions import ApprovalError, SessionStore, normalize_arguments
from .events import Event, create_event_gateway
from .config import load_settings
from .context import build_context
from .workflows import create_event_notification_workflow, create_sleep_workflow
from .websocket import AgentEventHub
from .notifications import NotificationInbox
from .approval_text import describe_approval
from .mcp import connect_servers
from .storage import ensure_private_directory
from .middleware import RinoPolicyMiddleware
from .image_generation import ImageGenerationConfig, ImageGenerationService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the only stdio connection to the private SwitchBot MCP process."""
    settings = load_settings()
    if "switchbot" not in settings.servers:
        raise RuntimeError("switchbot MCP is required for the current Rino Agent Service.")
    stack, mcp_servers = await connect_servers(settings.servers)
    try:
        switchbot_mcp = mcp_servers["switchbot"]
        app.state.switchbot_mcp = switchbot_mcp
        app.state.mcp_servers = mcp_servers
        app.state.sessions = SessionStore()
        app.state.audit = create_audit_log()
        app.state.agent = Agent(
            client=OpenAIChatCompletionClient(
                base_url=settings.base_url,
                api_key="local-not-used",
                model=settings.model,
            ),
            name="Rino",
            instructions=("You are Rino. Use home and life tools only when the user explicitly requests the related action or information. "
                          "Life tools record or retrieve consumable, laundry, and household-finance information; they never control devices. "
                          "Before calling life.register_consumable, convert units yourself so capacity, remaining and thresholds share one unit (2 kg of food is capacity 2000 with unit g; 1 L is 1000 ml), then collect and confirm: the name, capacity and unit, current remaining amount, the remaining amount at which to notify (reminder.remaining_below), and how it decreases (a fixed daily amount, per laundry, or manual only). Ask for any that are missing, one short question list at a time. Deduction models: for an item consumed a fixed amount every day (e.g. pet food), register usage_model {type: PER_DAY, amount: <per-day amount in the item's unit>} so it is deducted daily starting today; ask the daily amount. Laundry items use {type: PER_EVENT, event: laundry.completed, amount} and are deducted only when the user reports finishing laundry. Otherwise omit usage_model and tell the user the remaining amount is updated only when they report it (life.adjust_consumable, opening, or purchase). Never claim a registration succeeded unless the tool result confirms it.For a finance request, identify the amount, income or expense, category, and transaction date; ask when any are ambiguous, then use the approved finance tool. "
                          "Explain results concisely in Japanese. Never claim a real-world action succeeded when a tool result says verification is UNAVAILABLE; say the command was sent but could not be verified."),
            tools=list(mcp_servers.values()),
            middleware=[RinoPolicyMiddleware(settings.tools, app.state.audit, app.state.sessions)],
        )
        event_key = os.environ.get("RINO_AGENT_AUDIT_KEY") or os.environ.get("RINO_AGENT_API_TOKEN")
        if not event_key:
            raise RuntimeError("RINO_AGENT_API_TOKEN must be configured before event task persistence is available.")
        data_root = Path(os.environ.get("RINO_AGENT_DATA_DIR", str(Path(__file__).parent / "data"))).resolve()
        app.state.events = create_event_gateway(data_root / "events", event_key)
        app.state.settings = settings
        checkpoints = ensure_private_directory((Path(__file__).parent / settings.checkpoint_path).resolve())
        app.state.checkpoint_storage = FileCheckpointStorage(checkpoints)
        app.state.sleep_workflow = create_sleep_workflow(switchbot_mcp, str(checkpoints))
        app.state.event_notification_workflow = create_event_notification_workflow(str(checkpoints))
        app.state.event_hub = AgentEventHub()
        app.state.notifications = NotificationInbox()
        image_enabled = os.environ.get("RINO_IMAGE_GENERATION_ENABLED", "false").lower() == "true"
        app.state.image_generation = ImageGenerationService(ImageGenerationConfig.from_environment(), app.state.event_hub, app.state.audit) if image_enabled else None
        yield
    finally:
        await stack.aclose()


app = FastAPI(title="Rino Agent Service", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class PolicyCheckRequest(BaseModel):
    risk: RiskLevel
    mode: str = Field(pattern="^(?i:passive|assist|auto)$")
    goal_source: str = Field(pattern="^(user_request|registered_event|registered_task|approved_automation)$")
    explicit_user_request: bool = False


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = None
    context: dict | None = None
    mode: str = Field(default="ASSIST", pattern="^(?i:passive|assist|auto)$")
    goal_source: str = Field(default="user_request", pattern="^(user_request|registered_event|registered_task|approved_automation)$")


class ApprovalResponse(BaseModel):
    session_id: str
    approval_id: str


class LifeNotificationRequest(BaseModel):
    dedupe_key: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)


class CancelRequest(BaseModel):
    session_id: str


class NaturalApprovalRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=80)


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)


_EVENT_TYPE_PATTERN = "^(vision|game|pc|switchbot|memory|context|agent|comfyui|obs|system)\\.[a-z0-9_]+$"


class EventRequest(BaseModel):
    # Keep the existing data/ISO-8601 boundary; the Node bridge translates Bus envelopes here.
    type: str = Field(pattern=_EVENT_TYPE_PATTERN)
    source: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    data: dict = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone.")
        return value

    @field_validator("data")
    @classmethod
    def data_must_be_bounded(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 16_384:
            raise ValueError("Event data exceeds 16 KiB.")
        return value


class WaitingTaskRequest(BaseModel):
    event_type: str = Field(pattern=_EVENT_TYPE_PATTERN)
    payload: dict = Field(default_factory=dict)
    ttl_seconds: int = Field(ge=1, le=86_400)

    @field_validator("payload")
    @classmethod
    def payload_must_be_bounded(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 16_384:
            raise ValueError("Task payload exceeds 16 KiB.")
        return value


def response_payload(response, session_id: str) -> dict:
    requests = response.user_input_requests
    if not requests:
        app.state.sessions.statuses[session_id] = "SUCCEEDED"
        executions = app.state.sessions.get_tool_executions(session_id)
        last_execution = executions[-1] if executions else None
        return {
            "status": "succeeded",
            "session_id": session_id,
            "goal": app.state.sessions.goals.get(session_id),
            "tool": last_execution["tool"] if last_execution else None,
            "verified": last_execution is not None and last_execution["verification"] == "VERIFIED",
            "verification": last_execution["verification"] if last_execution else "NOT_APPLICABLE",
            "summary": response.text,
        }
    approval = app.state.sessions.add_approval(session_id, requests[0])
    policy = app.state.settings.tools.get(approval.tool_name)
    app.state.audit.write(
        "approval.requested",
        session_id=session_id,
        tool=approval.tool_name,
        arguments=approval.request.function_call.arguments,
        risk=policy.risk.value if policy else "BLOCKED",
    )
    return {
        "status": "approval_required",
        "session_id": session_id,
        "approval": {
            "approval_id": approval.approval_id,
            "tool": approval.tool_name,
            "arguments": redact(normalize_arguments(approval.request.function_call.arguments)),
            "description": describe_approval(approval.tool_name, redact(normalize_arguments(approval.request.function_call.arguments))),
            "risk": policy.risk.value if policy else "BLOCKED",
            "expires_in_seconds": app.state.sessions.approval_ttl_seconds,
        },
    }


async def run_agent_safely(input_data, session, session_id: str, *, mode: str = "ASSIST", goal_source: str = "user_request") -> tuple[dict, str | None]:
    try:
        stream = app.state.agent.run(input_data, stream=True, session=session, function_invocation_kwargs={"rino_mode": mode, "rino_goal_source": goal_source, "rino_session_id": session_id})
        async for update in stream:
            if update.text:
                await app.state.event_hub.publish({"type": "agent.stream", "session_id": session_id, "text": update.text})
        response = await stream.get_final_response()
        return response_payload(response, session_id), None
    except Exception as error:
        app.state.sessions.statuses[session_id] = "FAILED"
        return {"status": "failed", "session_id": session_id, "code": "AGENT_EXECUTION_FAILED", "summary": "Agent execution failed; no success was assumed."}, str(error)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "bind": "loopback-only"}


@app.post("/internal/policy/check", dependencies=[Depends(require_local_api_token)])
async def policy_check(request: PolicyCheckRequest) -> dict[str, str]:
    decision = decide_policy(PolicyInput(**request.model_dump()))
    return {"decision": PolicyDecision(decision).value}


@app.get("/internal/audit/verify", dependencies=[Depends(require_local_api_token)])
async def verify_audit() -> dict:
    return {"valid": app.state.audit.verify()}


@app.post("/agent/run", dependencies=[Depends(require_local_api_token)])
async def agent_run(request: AgentRunRequest) -> dict:
    explicit = request.goal_source == "user_request"
    if request.mode.upper() == "PASSIVE" and not explicit:
        return {"status": "failed", "code": "POLICY_DENIED", "summary": "PASSIVE mode accepts explicit user requests only."}
    sessions = app.state.sessions
    session_id = request.session_id or secrets.token_urlsafe(18)
    if sessions.statuses.get(session_id) == "WAITING_APPROVAL":
        return {"status": "failed", "session_id": session_id, "code": "APPROVAL_PENDING", "summary": "Resolve or cancel the pending approval before starting another goal in this session."}
    session = sessions.sessions.get(session_id)
    if session is None:
        session = app.state.agent.create_session(session_id=session_id)
        sessions.sessions[session_id] = session
        sessions.statuses[session_id] = "RUNNING"
    sessions.set_execution_options(session_id, mode=request.mode, goal_source=request.goal_source)
    sessions.begin_goal(session_id, request.goal)
    context = build_context(request.context)
    agent_input = request.goal if not context else f"{request.goal}\n\nRelevant Rino context:\n{context}"
    payload, error = await run_agent_safely(agent_input, session, session_id, mode=request.mode, goal_source=request.goal_source)
    await app.state.event_hub.publish({"type": "agent.result", **payload})
    app.state.audit.write("agent.run", session_id=session_id, goal=request.goal, mode=request.mode, goal_source=request.goal_source, status=payload["status"], execution_error=bool(error))
    return payload


@app.post("/agent/approve", dependencies=[Depends(require_local_api_token)])
async def agent_approve(request: ApprovalResponse) -> dict:
    try:
        approval = app.state.sessions.consume_approval(request.approval_id, request.session_id)
    except ApprovalError as error:
        return {"status": "failed", "code": "APPROVAL_INVALID", "summary": str(error)}
    session = app.state.sessions.sessions[request.session_id]
    options = app.state.sessions.get_execution_options(request.session_id)
    payload, error = await run_agent_safely(
        [
            Message(role="assistant", contents=[approval.request]),
            Message(role="user", contents=[approval.request.to_function_approval_response(True)]),
        ],
        session, request.session_id, **options,
    )
    await app.state.event_hub.publish({"type": "agent.result", **payload})
    app.state.audit.write("agent.approve", session_id=request.session_id, tool=approval.tool_name, status=payload["status"], execution_error=bool(error))
    return payload


@app.post("/agent/reject", dependencies=[Depends(require_local_api_token)])
async def agent_reject(request: ApprovalResponse) -> dict:
    try:
        approval = app.state.sessions.consume_approval(request.approval_id, request.session_id)
    except ApprovalError as error:
        return {"status": "failed", "code": "APPROVAL_INVALID", "summary": str(error)}
    session = app.state.sessions.sessions[request.session_id]
    options = app.state.sessions.get_execution_options(request.session_id)
    payload, error = await run_agent_safely(
        [
            Message(role="assistant", contents=[approval.request]),
            Message(role="user", contents=[approval.request.to_function_approval_response(False)]),
        ],
        session, request.session_id, **options,
    )
    await app.state.event_hub.publish({"type": "agent.result", **payload})
    app.state.audit.write("agent.reject", session_id=request.session_id, tool=approval.tool_name, status=payload["status"], execution_error=bool(error))
    return payload


@app.post("/agent/respond", dependencies=[Depends(require_local_api_token)])
async def agent_respond(request: NaturalApprovalRequest) -> dict:
    normalized = request.text.strip().lower().replace("。", "").replace("！", "")
    approvals = {"はい", "うん", "お願い", "お願いします", "おねがい", "いいよ", "いいです", "いいですよ", "大丈夫", "おっけー", "オッケー", "どうぞ", "承認", "実行して", "登録して", "yes", "ok", "okay"}
    rejections = {"いいえ", "いや", "だめ", "ダメ", "不要", "やめて", "やめる", "キャンセル", "no", "cancel"}
    try:
        approval = app.state.sessions.pending_for_session(request.session_id)
    except ApprovalError as error:
        return {"status": "failed", "code": "APPROVAL_INVALID", "summary": str(error)}
    response = ApprovalResponse(session_id=request.session_id, approval_id=approval.approval_id)
    if normalized in approvals:
        return await agent_approve(response)
    if normalized in rejections:
        return await agent_reject(response)
    return {"status": "failed", "code": "APPROVAL_RESPONSE_UNRECOGNIZED", "summary": "The response was not an explicit approval or rejection."}


@app.post("/agent/cancel", dependencies=[Depends(require_local_api_token)])
async def agent_cancel(request: CancelRequest) -> dict:
    if request.session_id not in app.state.sessions.sessions:
        return {"status": "failed", "code": "SESSION_NOT_FOUND"}
    app.state.sessions.invalidate_session_approvals(request.session_id)
    app.state.audit.write("agent.cancel", session_id=request.session_id)
    await app.state.event_hub.publish({"type": "agent.cancelled", "session_id": request.session_id})
    return {"status": "cancelled", "session_id": request.session_id}


@app.get("/agent/session/{session_id}", dependencies=[Depends(require_local_api_token)])
async def agent_session(session_id: str) -> dict:
    status = app.state.sessions.statuses.get(session_id)
    if status is None:
        return {"status": "failed", "code": "SESSION_NOT_FOUND"}
    return {"status": status, "session_id": session_id}


@app.get("/agent/tools", dependencies=[Depends(require_local_api_token)])
async def agent_tools() -> dict:
    return {"tools": sorted(tool.name for mcp in app.state.mcp_servers.values() for tool in mcp.functions)}


@app.post("/images/generate", dependencies=[Depends(require_local_api_token)])
async def image_generate(request: ImageGenerationRequest) -> dict:
    service = app.state.image_generation
    if service is None:
        return {"status": "failed", "code": "IMAGE_GENERATION_DISABLED"}
    return service.submit(request.prompt)


@app.get("/images/{job_id}", dependencies=[Depends(require_local_api_token)])
async def image_job(job_id: str) -> dict:
    service = app.state.image_generation
    if service is None:
        return {"status": "failed", "code": "IMAGE_GENERATION_DISABLED"}
    return service.jobs.get(job_id, {"status": "failed", "code": "IMAGE_JOB_NOT_FOUND"})


@app.post("/events", dependencies=[Depends(require_local_api_token)])
async def post_event(request: EventRequest) -> dict:
    event = Event(request.type, request.source, request.timestamp, request.data)
    triggered = app.state.events.publish(event)
    app.state.audit.write("event.received", event_type=event.type, source=event.source, triggered_tasks=[task.task_id for task in triggered])
    await app.state.event_hub.publish({"type": "event.received", "event_type": event.type, "triggered_tasks": [task.task_id for task in triggered]})
    for task in triggered:
        result = await app.state.event_notification_workflow.run(task.payload)
        outputs = result.get_outputs()
        notification = outputs[0] if outputs else {"message": "登録タスクが完了しました。", "verification": "NOT_REPORTED"}
        app.state.audit.write("task.completed", task_id=task.task_id, event_type=task.event_type, verification=notification["verification"])
        await app.state.event_hub.publish({"type": "task.completed", "task_id": task.task_id, "payload": notification})
    return {"accepted": True, "triggered_tasks": [task.task_id for task in triggered]}


@app.get("/agent/tasks", dependencies=[Depends(require_local_api_token)])
async def agent_tasks() -> dict:
    app.state.events.expire()
    return {"tasks": [{"task_id": task.task_id, "event_type": task.event_type, "status": task.status} for task in app.state.events.tasks.values()]}


@app.post("/agent/tasks", dependencies=[Depends(require_local_api_token)])
async def create_task(request: WaitingTaskRequest) -> dict:
    task = app.state.events.add_task(request.event_type, request.payload, request.ttl_seconds)
    app.state.audit.write("task.registered", task_id=task.task_id, event_type=task.event_type)
    return {"task_id": task.task_id, "status": task.status}


@app.post("/internal/notifications", dependencies=[Depends(require_local_api_token)])
async def post_life_notification(request: LifeNotificationRequest) -> dict:
    app.state.notifications.add(request.dedupe_key, request.message)
    app.state.audit.write("notification.queued", dedupe_key=request.dedupe_key)
    return {"queued": True}


@app.post("/agent/notifications/drain", dependencies=[Depends(require_local_api_token)])
async def drain_life_notifications() -> dict:
    return {"messages": app.state.notifications.drain()}


@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket) -> None:
    if not await app.state.event_hub.connect(websocket):
        return
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        app.state.event_hub.disconnect(websocket)


@app.post("/workflows/sleep", dependencies=[Depends(require_local_api_token)])
async def run_sleep_workflow() -> dict:
    result = await app.state.sleep_workflow.run("start")
    outputs = result.get_outputs()
    app.state.audit.write("workflow.sleep", status="succeeded")
    return {"status": "succeeded", "workflow": "sleep", "outputs": outputs}


@app.get("/workflows/checkpoints", dependencies=[Depends(require_local_api_token)])
async def workflow_checkpoints() -> dict:
    sleep_ids = await app.state.checkpoint_storage.list_checkpoint_ids(workflow_name="rino_sleep")
    event_ids = await app.state.checkpoint_storage.list_checkpoint_ids(workflow_name="rino_event_notification")
    return {
        "workflows": {
            "rino_sleep": [str(checkpoint_id) for checkpoint_id in sleep_ids],
            "rino_event_notification": [str(checkpoint_id) for checkpoint_id in event_ids],
        },
        "auto_resume": False,
    }
