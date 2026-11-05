"""Transaction risk rules (SEC-RISK-01, SEC-AUTH-09).

A deliberately simple, explainable rules engine - the seam where an ML/fraud
service would plug in. Outcomes: ALLOW, STEP_UP (fresh TOTP needed) or deny
(raises DomainError).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Account, Transaction
from app.services.errors import DomainError


class Decision(StrEnum):
    ALLOW = "allow"
    STEP_UP = "step_up"


def evaluate(db: Session, from_account: Account, user_id: str, amount_cents: int) -> Decision:
    s = get_settings()
    now = datetime.now(UTC)

    if amount_cents > s.max_transfer_cents:
        raise DomainError(422, "limit_exceeded", "Amount exceeds the per-transfer limit.")

    last_hour = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.user_id == user_id,
            Transaction.kind == "transfer",
            Transaction.created_at >= now - timedelta(hours=1),
        )
    ).scalar_one()
    if last_hour >= s.max_transfers_per_hour:
        raise DomainError(429, "velocity_exceeded", "Too many transfers. Try again later.")

    sent_24h = db.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.from_account_id == from_account.id,
            Transaction.kind == "transfer",
            Transaction.created_at >= now - timedelta(hours=24),
        )
    ).scalar_one()
    if sent_24h + amount_cents > s.daily_outbound_limit_cents:
        raise DomainError(422, "daily_limit_exceeded", "Daily outbound limit exceeded.")

    if amount_cents >= s.step_up_threshold_cents:
        return Decision.STEP_UP
    return Decision.ALLOW
