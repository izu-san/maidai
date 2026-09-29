from rino_agent.policy import PolicyDecision, PolicyInput, RiskLevel, decide_policy


def decision(risk, *, mode="ASSIST", source="user_request", explicit=True):
    return decide_policy(PolicyInput(risk, mode, source, explicit))


def test_blocked_is_never_allowed():
    assert decision(RiskLevel.BLOCKED) is PolicyDecision.DENY


def test_high_always_requires_approval():
    assert decision(RiskLevel.HIGH) is PolicyDecision.REQUIRE_APPROVAL


def test_medium_always_requires_approval():
    assert decision(RiskLevel.MEDIUM, explicit=False, source="registered_event") is PolicyDecision.REQUIRE_APPROVAL
    assert decision(RiskLevel.MEDIUM) is PolicyDecision.REQUIRE_APPROVAL


def test_passive_denies_autonomous_action():
    assert decision(RiskLevel.LOW, mode="PASSIVE", source="registered_event", explicit=False) is PolicyDecision.DENY


def test_auto_mode_keeps_medium_and_high_guardrails():
    assert decision(RiskLevel.MEDIUM, mode="AUTO", source="registered_event", explicit=False) is PolicyDecision.REQUIRE_APPROVAL
    assert decision(RiskLevel.HIGH, mode="AUTO", source="approved_automation", explicit=True) is PolicyDecision.REQUIRE_APPROVAL


def test_disabled_autonomy_requires_approval_even_for_low_risk_tool():
    request = PolicyInput(RiskLevel.LOW, "AUTO", "registered_event", False, autonomous_allowed=False)
    assert decide_policy(request) is PolicyDecision.REQUIRE_APPROVAL
