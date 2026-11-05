"""SEC-DATA-*, SEC-AUTHZ-01, SEC-RISK-01, SEC-AUTH-09: money movement."""

import threading
import time
import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Account, AuditLog, LedgerEntry
from app.security import totp
from app.services import ledger
from app.services.errors import DomainError


def _tx(cust, to_number, cents, key=None, **extra):
    return cust.client.post(
        "/api/transfers",
        headers={**cust.headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json={"from_account_id": cust.account["id"], "to_account_number": to_number, "amount_cents": cents, **extra},
    )


def _balance(cust) -> int:
    return cust.account["balance_cents"]


def _ledger_is_balanced(db) -> bool:
    """Double-entry invariant: total debits == total credits, and per-account sums match balances."""
    debits = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(LedgerEntry.direction == "debit")).scalar()
    credits = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(LedgerEntry.direction == "credit")).scalar()
    if debits != credits:
        return False
    for acct in db.execute(select(Account)).scalars():
        net = db.execute(
            select(func.coalesce(func.sum(func.iif(LedgerEntry.direction == "credit", LedgerEntry.amount_cents, -LedgerEntry.amount_cents)), 0))
            .where(LedgerEntry.account_id == acct.id)
        ).scalar()
        if net != acct.balance_cents:
            return False
    return True


def test_transfer_moves_money_and_keeps_ledger_balanced(alice, bob, db):
    alice.fund(10_000)
    r = _tx(alice, bob.account["account_number"], 2_500, description="Rent")
    assert r.status_code == 201
    body = r.json()
    assert body["to_account"].startswith("••••") and bob.account["account_number"] not in r.text
    assert _balance(alice) == 7_500 and _balance(bob) == 2_500
    assert _ledger_is_balanced(db)


def test_insufficient_funds_changes_nothing(alice, bob, db):
    alice.fund(1_000)
    r = _tx(alice, bob.account["account_number"], 1_001)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "insufficient_funds"
    assert _balance(alice) == 1_000 and _balance(bob) == 0
    assert _ledger_is_balanced(db)


def test_idempotent_retry_moves_money_once(alice, bob):
    alice.fund(10_000)
    key = str(uuid.uuid4())
    first = _tx(alice, bob.account["account_number"], 3_000, key=key)
    retry = _tx(alice, bob.account["account_number"], 3_000, key=key)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert _balance(alice) == 7_000 and _balance(bob) == 3_000


def test_idempotency_key_reuse_with_other_payload_rejected(alice, bob):
    alice.fund(10_000)
    key = str(uuid.uuid4())
    assert _tx(alice, bob.account["account_number"], 1_000, key=key).status_code == 201
    r = _tx(alice, bob.account["account_number"], 2_000, key=key)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "idempotency_key_reused"
    assert _balance(alice) == 9_000


def test_idempotency_key_is_mandatory(alice, bob):
    alice.fund(1_000)
    r = alice.client.post(
        "/api/transfers", headers=alice.headers,
        json={"from_account_id": alice.account["id"], "to_account_number": bob.account["account_number"], "amount_cents": 100},
    )
    assert r.status_code == 400


def test_cannot_spend_from_someone_elses_account(alice, bob):
    """SEC-AUTHZ-01 (BOLA/IDOR): Bob names Alice's account id as the source."""
    alice.fund(5_000)
    r = bob.client.post(
        "/api/transfers", headers={**bob.headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"from_account_id": alice.account["id"], "to_account_number": bob.account["account_number"], "amount_cents": 100},
    )
    assert r.status_code == 404
    assert _balance(alice) == 5_000


def test_cannot_read_someone_elses_statement(alice, bob):
    alice.fund(1_000)
    r = bob.client.get(f"/api/accounts/{alice.account['id']}/transactions", headers=bob.headers)
    missing = bob.client.get(f"/api/accounts/{uuid.uuid4()}/transactions", headers=bob.headers)
    assert r.status_code == missing.status_code == 404  # existence is not revealed
    assert r.json()["detail"] == missing.json()["detail"]


def test_cannot_fund_someone_elses_account(alice, bob):
    r = bob.client.post(f"/api/accounts/{alice.account['id']}/fund", headers=bob.headers, json={"amount_cents": 100})
    assert r.status_code == 404


def test_money_amounts_must_be_positive_integers(alice, bob):
    """SEC-DATA-02 / SEC-API-01: no floats, negatives, zero, strings."""
    alice.fund(10_000)
    for bad in (-100, 0, 10.5, "100", 1e3, True, None):
        r = _tx(alice, bob.account["account_number"], bad)
        assert r.status_code == 422, bad
    assert _balance(alice) == 10_000


def test_negative_amount_cannot_pull_money_from_victim(alice, bob):
    alice.fund(10_000)
    r = _tx(bob, alice.account["account_number"], -5_000)
    assert r.status_code == 422 and _balance(alice) == 10_000


def test_account_number_checksum_and_unknown_destination(alice):
    alice.fund(1_000)
    assert _tx(alice, "123456789012", 100).status_code in (404, 422)
    bad_luhn = "000000000001"
    assert not ledger.luhn_valid(bad_luhn)
    assert _tx(alice, bad_luhn, 100).json()["detail"]["code"] == "invalid_account_number"


def test_cannot_transfer_to_self(alice):
    alice.fund(1_000)
    r = _tx(alice, alice.account["account_number"], 100)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "same_account"


def test_description_rejects_control_characters(alice, bob):
    alice.fund(1_000)
    assert _tx(alice, bob.account["account_number"], 100, description="hi\x00there").status_code == 422
    assert _tx(alice, bob.account["account_number"], 100, description="x" * 141).status_code == 422


# ---------------------------------------------------------------- limits & step-up
def test_per_transfer_limit(alice, bob, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_transfer_cents", 5_000)
    alice.fund(100_000)
    r = _tx(alice, bob.account["account_number"], 5_001)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "limit_exceeded"


def test_velocity_limit(alice, bob, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_transfers_per_hour", 3)
    alice.fund(100_000)
    codes = [_tx(alice, bob.account["account_number"], 100).status_code for _ in range(4)]
    assert codes == [201, 201, 201, 429]


def test_daily_limit(alice, bob, settings, monkeypatch):
    monkeypatch.setattr(settings, "daily_outbound_limit_cents", 1_000)
    monkeypatch.setattr(settings, "step_up_threshold_cents", 10**9)
    alice.fund(100_000)
    assert _tx(alice, bob.account["account_number"], 600).status_code == 201
    r = _tx(alice, bob.account["account_number"], 600)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "daily_limit_exceeded"


def test_high_value_transfer_needs_mfa_enrolment(alice, bob, settings):
    alice.fund(100_000)
    r = _tx(alice, bob.account["account_number"], settings.step_up_threshold_cents)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_required"
    assert _balance(alice) == 100_000


def test_high_value_transfer_step_up(alice, bob, settings):
    """SEC-AUTH-09: >= threshold needs a fresh OTP; wrong/replayed codes fail."""
    secret = alice.enable_mfa()
    alice.fund(100_000)
    amount = settings.step_up_threshold_cents
    assert _tx(alice, bob.account["account_number"], amount).json()["detail"]["code"] == "otp_required"
    assert _tx(alice, bob.account["account_number"], amount, otp_code="000000").status_code == 401

    code = totp.current_code(secret, at=time.time() + 30)
    ok = _tx(alice, bob.account["account_number"], amount, otp_code=code)
    assert ok.status_code == 201
    replay = _tx(alice, bob.account["account_number"], amount, otp_code=code)
    assert replay.status_code == 401  # the same code cannot authorise a second transfer
    assert _balance(bob) == amount


def test_small_transfer_does_not_need_otp(alice, bob):
    alice.enable_mfa()
    alice.fund(10_000)
    assert _tx(alice, bob.account["account_number"], 100).status_code == 201


# ---------------------------------------------------------------- concurrency
def test_concurrent_transfers_cannot_double_spend(alice, bob, db):
    """SEC-DATA-04: 10 parallel requests of 40 against a balance of 100 -> exactly 2 succeed."""
    alice.fund(100)
    src_id, dst_number = alice.account["id"], bob.account["account_number"]
    from app.models import User
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.email == alice.email)).scalar_one()
        s.expunge(user)

    results: list[str] = []

    def worker():
        with SessionLocal() as s:
            u = s.merge(user)
            try:
                ledger.transfer(
                    s, user=u, from_account_id=src_id, to_account_number=dst_number, amount_cents=40,
                    description="", idempotency_key=str(uuid.uuid4()), otp_code=None, ip=None,
                )
                results.append("ok")
            except DomainError as e:
                results.append(e.code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count("ok") == 2 and results.count("insufficient_funds") == 8
    assert _balance(alice) == 20 and _balance(bob) == 80
    assert _ledger_is_balanced(db)


def test_concurrent_identical_requests_are_idempotent(alice, bob):
    alice.fund(10_000)
    src_id, dst_number = alice.account["id"], bob.account["account_number"]
    from app.models import User
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.email == alice.email)).scalar_one()
        s.expunge(user)
    key, tx_ids = str(uuid.uuid4()), []

    def worker():
        with SessionLocal() as s:
            tx, *_ = ledger.transfer(
                s, user=s.merge(user), from_account_id=src_id, to_account_number=dst_number,
                amount_cents=1_000, description="", idempotency_key=key, otp_code=None, ip=None,
            )
            tx_ids.append(tx.id)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(tx_ids)) == 1 and _balance(alice) == 9_000


# ---------------------------------------------------------------- history & audit
def test_statement_pagination_and_masking(alice, bob):
    alice.fund(50_000)
    for _ in range(5):
        assert _tx(alice, bob.account["account_number"], 100).status_code == 201
    page1 = alice.client.get(f"/api/accounts/{alice.account['id']}/transactions?limit=3", headers=alice.headers).json()
    assert len(page1["items"]) == 3 and page1["next_cursor"]
    page2 = alice.client.get(
        f"/api/accounts/{alice.account['id']}/transactions?limit=3&cursor={page1['next_cursor']}", headers=alice.headers
    ).json()
    assert len(page2["items"]) == 3 and page2["next_cursor"] is None  # 5 transfers + 1 funding
    assert all(i["counterparty"].startswith("••••") or i["counterparty"] == "Treasury" for i in page1["items"] + page2["items"])
    assert alice.client.get(f"/api/accounts/{alice.account['id']}/transactions?limit=1000", headers=alice.headers).status_code == 422


def test_denied_transfers_are_audited(alice, bob, db):
    alice.fund(100)
    _tx(alice, bob.account["account_number"], 5_000)  # insufficient funds
    events = db.execute(select(AuditLog).where(AuditLog.action == "transfer.denied")).scalars().all()
    assert events and events[-1].details["reason"] == "insufficient_funds"
    assert events[-1].outcome == "denied"
