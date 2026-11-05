"""Unit tests: transfer specification and risk policy (pure functions)."""

from dataclasses import dataclass

import pytest

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger import Decision, Money, RecentActivity, RiskLimits, assess_risk, check_transfer


@dataclass
class Acct:
    id: str
    currency: str = "USD"
    is_system: bool = False


LIMITS = RiskLimits(
    max_transfer=Money(1_000_000),
    daily_outbound=Money(2_000_000),
    step_up_threshold=Money(50_000),
    max_transfers_per_hour=10,
)
QUIET = RecentActivity(transfers_last_hour=0, sent_last_24h=Money(0))


# ------------------------------------------------------------- check_transfer
def test_valid_transfer_passes():
    check_transfer(Acct("a"), Acct("b"), Money(100))


def test_same_account_is_rejected():
    with pytest.raises(BusinessRuleViolation) as exc:
        check_transfer(Acct("a"), Acct("a"), Money(100))
    assert exc.value.code == "same_account"


def test_currency_mismatch_is_rejected():
    with pytest.raises(BusinessRuleViolation) as exc:
        check_transfer(Acct("a"), Acct("b", currency="EUR"), Money(100))
    assert exc.value.code == "currency_mismatch"


@pytest.mark.parametrize("src_sys,dst_sys", [(True, False), (False, True)])
def test_treasury_is_never_a_customer_counterparty(src_sys, dst_sys):
    with pytest.raises(BusinessRuleViolation) as exc:
        check_transfer(Acct("a", is_system=src_sys), Acct("b", is_system=dst_sys), Money(100))
    assert exc.value.code == "destination_not_found"


# ---------------------------------------------------------------- assess_risk
def test_small_amount_is_allowed():
    assert assess_risk(Money(49_999), QUIET, LIMITS) is Decision.ALLOW


def test_threshold_triggers_step_up_inclusive():
    assert assess_risk(Money(50_000), QUIET, LIMITS) is Decision.STEP_UP


def test_per_transfer_limit():
    assert assess_risk(Money(1_000_000), QUIET, LIMITS) is Decision.STEP_UP
    with pytest.raises(BusinessRuleViolation) as exc:
        assess_risk(Money(1_000_001), QUIET, LIMITS)
    assert exc.value.code == "limit_exceeded"


def test_velocity_limit():
    busy = RecentActivity(transfers_last_hour=10, sent_last_24h=Money(0))
    with pytest.raises(BusinessRuleViolation) as exc:
        assess_risk(Money(100), busy, LIMITS)
    assert exc.value.code == "velocity_exceeded"


def test_daily_limit_counts_what_was_already_sent():
    near = RecentActivity(transfers_last_hour=1, sent_last_24h=Money(1_999_900))
    assert assess_risk(Money(100), near, LIMITS) is Decision.ALLOW
    with pytest.raises(BusinessRuleViolation) as exc:
        assess_risk(Money(101), near, LIMITS)
    assert exc.value.code == "daily_limit_exceeded"


def test_rules_are_checked_in_order_per_transfer_first():
    busy = RecentActivity(transfers_last_hour=99, sent_last_24h=Money(9_999_999))
    with pytest.raises(BusinessRuleViolation) as exc:
        assess_risk(Money(5_000_000), busy, LIMITS)
    assert exc.value.code == "limit_exceeded"
