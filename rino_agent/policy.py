"""Rino risk policy.  This is deliberately independent of MAF approval mechanics."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    BLOCKED = "BLOCKED"


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


@dataclass(frozen=True)
class PolicyInput:
    risk: RiskLevel
    mode: str
    goal_source: str
    explicit_user_request: bool
    autonomous_allowed: bool = True


def decide_policy(request: PolicyInput) -> PolicyDecision:
    if request.risk is RiskLevel.BLOCKED or request.mode.upper() == "PASSIVE" and not request.explicit_user_request:
        return PolicyDecision.DENY
    if request.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        return PolicyDecision.REQUIRE_APPROVAL
    if not request.explicit_user_request and not request.autonomous_allowed:
        return PolicyDecision.REQUIRE_APPROVAL
    if request.risk is RiskLevel.MEDIUM:
        return PolicyDecision.REQUIRE_APPROVAL
    if request.goal_source != "user_request" and request.risk not in {RiskLevel.READ_ONLY, RiskLevel.LOW}:
        return PolicyDecision.REQUIRE_APPROVAL
    return PolicyDecision.ALLOW
