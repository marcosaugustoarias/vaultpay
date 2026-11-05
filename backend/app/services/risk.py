"""Transaction risk rules (SEC-RISK-01, SEC-AUTH-09) - application side.

This module only *gathers facts* (recent activity from the database, limits from
settings). The decision itself is the pure domain policy
``app.domain.ledger.risk_policy.assess_risk`` - the seam where an ML/fraud service
would plug in. Outcomes: ALLOW, STEP_UP (fresh TOTP needed) or deny (DomainError).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.errors import BusinessRuleViolation
from app.domain.ledger import Decision, Money, RecentActivity, RiskLimits, assess_risk
from app.models import Account, Transaction
from app.services.errors import DomainError

__all__ = ["Decision", "current_limits", "evaluate", "recent_activity"]


def current_limits(currency: str = "USD") -> RiskLimits:
    s = get_settings()
    return RiskLimits(
        max_transfer=Money(s.max_transfer_cents, currency),
        daily_outbound=Money(s.daily_outbound_limit_cents, currency),
        step_up_threshold=Money(s.step_up_threshold_cents, currency),
        max_transfers_per_hour=s.max_transfers_per_hour,
    )


def recent_activity(db: Session, from_account: Account, user_id: str) -> RecentActivity:
    now = datetime.now(UTC)
    last_hour = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user_id,
            Transaction.kind == "transfer",
            Transaction.created_at >= now - timedelta(hours=1),
        )
    ).scalar_one()
    sent_24h = db.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.from_account_id == from_account.id,
            Transaction.kind == "transfer",
            Transaction.created_at >= now - timedelta(hours=24),
        )
    ).scalar_one()
    return RecentActivity(transfers_last_hour=int(last_hour), sent_last_24h=Money(int(sent_24h), from_account.currency))


def evaluate(db: Session, from_account: Account, user_id: str, amount_cents: int) -> Decision:
    try:
        amount = Money.positive(amount_cents, from_account.currency)
        return assess_risk(amount, recent_activity(db, from_account, user_id), current_limits(from_account.currency))
    except BusinessRuleViolation as violation:
        raise DomainError.from_violation(violation) from None
