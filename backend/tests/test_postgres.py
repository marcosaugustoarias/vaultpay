"""Integration tests against a REAL PostgreSQL (row locks, triggers, advisory locks).

Skipped unless VAULTPAY_TEST_POSTGRES_URL is set, e.g.
    postgresql+psycopg://user:pass@localhost:5432/vaultpay_test
CI runs these against a postgres service container.
"""

import os
import threading
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database import Base, init_db, make_engine
from app.models import Account, LedgerEntry, User
from app.services import audit, ledger
from app.services.errors import DomainError

PG_URL = os.environ.get("VAULTPAY_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="VAULTPAY_TEST_POSTGRES_URL not set")


@pytest.fixture
def pg():
    engine = make_engine(PG_URL)
    Base.metadata.drop_all(engine)
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as s:
        ledger.ensure_treasury(s)
    yield Session
    engine.dispose()


def _user_with_account(Session, email: str, funds: int = 0):
    with Session() as s:
        u = User(email=email, password_hash="x", full_name="T")
        s.add(u)
        s.flush()
        acct = ledger.open_account(s, u)
        s.commit()
        if funds:
            ledger.demo_fund(s, user=u, account=acct, amount_cents=funds, ip=None)
        s.expunge_all()
        return u, acct


def _run(threads):
    [t.start() for t in threads]
    [t.join() for t in threads]


def test_append_only_triggers(pg):
    _user_with_account(pg, "a@example.com", 100)
    with pg() as s:
        for stmt in ("UPDATE ledger_entries SET amount_cents = 1", "DELETE FROM ledger_entries",
                     "UPDATE audit_log SET outcome = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(DBAPIError, match="append-only"):
                s.execute(text(stmt))
            s.rollback()


def test_check_constraints(pg):
    _user_with_account(pg, "a@example.com", 100)
    with pg() as s:
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE accounts SET balance_cents = -1 WHERE is_system = false"))
        s.rollback()


def test_concurrent_transfers_cannot_double_spend(pg):
    alice, a_acct = _user_with_account(pg, "alice@example.com", 100)
    _, b_acct = _user_with_account(pg, "bob@example.com")
    results = []

    def worker():
        with pg() as s:
            try:
                ledger.transfer(s, user=s.merge(alice, load=False), from_account_id=a_acct.id,
                                to_account_number=b_acct.account_number, amount_cents=40, description="",
                                idempotency_key=str(uuid.uuid4()), otp_code=None, ip=None)
                results.append("ok")
            except DomainError as e:
                results.append(e.code)

    _run([threading.Thread(target=worker) for _ in range(12)])
    assert results.count("ok") == 2 and results.count("insufficient_funds") == 10
    with pg() as s:
        assert s.get(Account, a_acct.id).balance_cents == 20 and s.get(Account, b_acct.id).balance_cents == 80


def test_opposite_direction_transfers_do_not_deadlock(pg):
    alice, a_acct = _user_with_account(pg, "alice@example.com", 10_000)
    bob, b_acct = _user_with_account(pg, "bob@example.com")
    with pg() as s:  # give Bob money through the ledger as well
        ledger.demo_fund(s, user=bob, account=s.get(Account, b_acct.id), amount_cents=10_000, ip=None)
    errors = []

    def worker(user, src, dst):
        with pg() as s:
            try:
                ledger.transfer(s, user=s.merge(user, load=False), from_account_id=src.id,
                                to_account_number=dst.account_number, amount_cents=10, description="",
                                idempotency_key=str(uuid.uuid4()), otp_code=None, ip=None)
            except Exception as e:  # noqa: BLE001 - we want to see *any* failure (e.g. deadlock)
                errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(alice, a_acct, b_acct)) for _ in range(15)]
    threads += [threading.Thread(target=worker, args=(bob, b_acct, a_acct)) for _ in range(15)]
    _run(threads)
    assert errors == []
    with pg() as s:
        total = s.execute(select(func.sum(Account.balance_cents)).where(Account.is_system.is_(False))).scalar()
        assert total == 20_000  # money is conserved
        debits = s.execute(select(func.sum(LedgerEntry.amount_cents)).where(LedgerEntry.direction == "debit")).scalar()
        credits = s.execute(select(func.sum(LedgerEntry.amount_cents)).where(LedgerEntry.direction == "credit")).scalar()
        assert debits == credits


def test_audit_chain_survives_concurrent_writers(pg):
    def worker(i):
        with pg() as s:
            audit.record(s, "test.event", details={"i": i})
            audit.record(s, "test.event2", details={"i": i})  # two appends in ONE transaction
            s.commit()

    _run([threading.Thread(target=worker, args=(i,)) for i in range(20)])
    with pg() as s:
        report = audit.verify_chain(s)
        assert report.valid and report.checked >= 40
