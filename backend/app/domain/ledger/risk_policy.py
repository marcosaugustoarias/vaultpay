"""Risk policy (SEC-RISK-01, SEC-AUTH-09) as a pure function.

Before the DDD refactor this logic was mixed with SQL queries in ``services/risk.py``.
Now the application layer gathers the facts (``RecentActivity``) and the domain decides.
That makes every limit testable in microseconds, with no database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger.money import Money


class Decision(StrEnum):
    ALLOW = "allow"
    STEP_UP = "step_up"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_transfer: Money
    daily_outbound: Money
    step_up_threshold: Money
    max_transfers_per_hour: int


@dataclass(frozen=True, slots=True)
class RecentActivity:
    transfers_last_hour: int
    sent_last_24h: Money


def assess_risk(amount: Money, activity: RecentActivity, limits: RiskLimits) -> Decision:
    """ALLOW, STEP_UP (fresh TOTP needed) or raise ``BusinessRuleViolation`` (deny)."""
    if amount > limits.max_transfer:
        raise BusinessRuleViolation("limit_exceeded", "Amount exceeds the per-transfer limit.")
    if activity.transfers_last_hour >= limits.max_transfers_per_hour:
        raise BusinessRuleViolation("velocity_exceeded", "Too many transfers. Try again later.")
    if activity.sent_last_24h + amount > limits.daily_outbound:
        raise BusinessRuleViolation("daily_limit_exceeded", "Daily outbound limit exceeded.")
    if amount >= limits.step_up_threshold:
        return Decision.STEP_UP
    return Decision.ALLOW
