from types import SimpleNamespace

import pytest

from rino_agent.sessions import ApprovalError, SessionStore, normalize_arguments


def request(name="home.lock_door", arguments=None):
    return SimpleNamespace(function_call=SimpleNamespace(name=name, arguments=arguments or {}))


def test_approval_is_single_use_and_session_bound():
    store = SessionStore()
    approval = store.add_approval("one", request())
    assert store.consume_approval(approval.approval_id, "one").tool_name == "home.lock_door"
    with pytest.raises(ApprovalError):
        store.consume_approval(approval.approval_id, "one")


def test_approval_cannot_be_used_by_another_session():
    store = SessionStore()
    approval = store.add_approval("one", request())
    with pytest.raises(ApprovalError):
        store.consume_approval(approval.approval_id, "two")


def test_cancelling_a_session_invalidates_its_approvals():
    store = SessionStore()
    approval = store.add_approval("one", request())
    store.invalidate_session_approvals("one")
    assert store.statuses["one"] == "CANCELLED"
    with pytest.raises(ApprovalError):
        store.consume_approval(approval.approval_id, "one")


def test_pending_lookup_requires_one_fresh_approval():
    store = SessionStore()
    approval = store.add_approval("one", request())
    assert store.pending_for_session("one") is approval
    store.add_approval("one", request("home.tv_on"))
    with pytest.raises(ApprovalError):
        store.pending_for_session("one")


def test_normalize_arguments_parses_model_json():
    assert normalize_arguments('{"celsius":26}') == {"celsius": 26}


def test_execution_options_remain_stable_for_approval_continuation():
    store = SessionStore()
    store.set_execution_options("one", mode="AUTO", goal_source="registered_event")
    assert store.get_execution_options("one") == {"mode": "AUTO", "goal_source": "registered_event"}


def test_session_records_structured_tool_execution_for_result_payload():
    store = SessionStore()
    store.begin_goal("one", "テレビを消す")
    store.record_tool_execution("one", {"tool": "home.tv_off", "verification": "UNAVAILABLE"})
    assert store.goals["one"] == "テレビを消す"
    assert store.get_tool_executions("one") == [{"tool": "home.tv_off", "verification": "UNAVAILABLE"}]
