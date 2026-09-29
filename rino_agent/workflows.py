"""MAF workflows for deterministic multi-step Rino actions."""
from __future__ import annotations

from agent_framework import FileCheckpointStorage, workflow


def verification_status(result) -> str:
    if isinstance(result, dict):
        verification = result.get("verification")
        if not isinstance(verification, dict) and isinstance(result.get("data"), dict):
            verification = result["data"].get("verification")
        if isinstance(verification, dict):
            return str(verification.get("status", "NOT_REPORTED"))
    return "NOT_REPORTED"


def create_sleep_workflow(home, checkpoint_path: str):
    """TV off then light off. Door locking is intentionally excluded."""
    @workflow(name="rino_sleep")
    async def sleep(_: str) -> dict:
        tv = await home.call_tool("home.tv_off")
        light = await home.call_tool("home.light_off")
        verification = {"tv": verification_status(tv), "light": verification_status(light)}
        return {
            "tv": tv,
            "light": light,
            "verification": verification,
            "verified": all(status == "VERIFIED" for status in verification.values()),
        }

    return sleep.build(checkpoint_storage=FileCheckpointStorage(checkpoint_path))


def create_event_notification_workflow(checkpoint_path: str):
    """Checkpointed, deterministic completion path for registered event waiters."""
    @workflow(name="rino_event_notification")
    async def notify(payload: dict) -> dict:
        message = str(payload.get("message", "登録タスクのイベントを受信しました。"))[:500]
        return {"message": message, "verification": "NOT_APPLICABLE"}

    return notify.build(checkpoint_storage=FileCheckpointStorage(checkpoint_path))
