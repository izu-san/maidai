import asyncio

from agent_framework import FileCheckpointStorage

from rino_agent.workflows import create_event_notification_workflow, create_sleep_workflow


class Home:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name):
        self.calls.append(name)
        return name


def test_sleep_workflow_orders_low_risk_actions_and_excludes_door(tmp_path):
    home = Home()
    result = asyncio.run(create_sleep_workflow(home, str(tmp_path)).run("start"))
    assert home.calls == ["home.tv_off", "home.light_off"]
    assert result.get_outputs()[0]["verified"] is False
    assert result.get_outputs()[0]["verification"] == {"tv": "NOT_REPORTED", "light": "NOT_REPORTED"}
    assert asyncio.run(FileCheckpointStorage(tmp_path).list_checkpoint_ids(workflow_name="rino_sleep"))


def test_workflow_recognizes_verification_inside_home_result_wrapper():
    from rino_agent.workflows import verification_status
    assert verification_status({"success": True, "data": {"verification": {"status": "VERIFIED"}}}) == "VERIFIED"


def test_event_notification_workflow_is_checkpointed_and_deterministic(tmp_path):
    result = asyncio.run(create_event_notification_workflow(str(tmp_path)).run({"message": "生成が完了しました"}))
    assert result.get_outputs()[0] == {"message": "生成が完了しました", "verification": "NOT_APPLICABLE"}
    assert asyncio.run(FileCheckpointStorage(tmp_path).list_checkpoint_ids(workflow_name="rino_event_notification"))
