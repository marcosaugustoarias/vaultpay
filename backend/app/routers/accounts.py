"""Accounts, ledger statements and sandbox funding."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser, ip_of
from app.errors import domain_to_http
from app.models import Account, LedgerEntry, Transaction
from app.schemas import AccountOut, FundIn, LedgerEntryOut, LedgerPageOut, TransactionOut
from app.security.rate_limit import rate_limit
from app.services import ledger
from app.services.errors import DomainError

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def owned_account(db: DB, user: CurrentUser, account_id: str) -> Account:
    """SEC-AUTHZ-01 (OWASP API1 / BOLA): resolve an object id *only* inside the caller's
    own data. Another customer's id and a non-existent id are indistinguishable (404)."""
    acct = db.execute(
        select(Account).where(
            Account.id == account_id, Account.user_id == user.id, Account.is_system.is_(False)
        )
    ).scalar_one_or_none()
    if acct is None:
        raise HTTPException(404, {"message": "Account not found.", "code": "account_not_found"})
    return acct


@router.get("", response_model=list[AccountOut])
def list_accounts(user: CurrentUser, db: DB):
    return db.execute(
        select(Account).where(Account.user_id == user.id, Account.is_system.is_(False))
    ).scalars().all()


@router.get("/{account_id}/transactions", response_model=LedgerPageOut)
def statement(
    account_id: str, user: CurrentUser, db: DB,
    limit: int = Query(20, ge=1, le=100),
    cursor: int | None = Query(None, ge=1),
):
    acct = owned_account(db, user, account_id)
    q = select(LedgerEntry, Transaction).join(
        Transaction, Transaction.id == LedgerEntry.transaction_id
    ).where(LedgerEntry.account_id == acct.id)
    if cursor:
        q = q.where(LedgerEntry.id < cursor)  # keyset pagination: stable and O(log n)
    rows = db.execute(q.order_by(LedgerEntry.id.desc()).limit(limit + 1)).all()

    page, has_more = rows[:limit], len(rows) > limit
    counter_ids = {
        (t.to_account_id if e.direction == "debit" else t.from_account_id) for e, t in page
    }
    numbers = {}
    if counter_ids:
        for a in db.execute(select(Account).where(Account.id.in_(counter_ids))).scalars():
            numbers[a.id] = "Treasury" if a.is_system else ledger.mask(a.account_number)

    items = [
        LedgerEntryOut(
            id=e.id, transaction_id=t.id, kind=t.kind, direction=e.direction,
            amount_cents=e.amount_cents, balance_after_cents=e.balance_after_cents,
            description=t.description,
            counterparty=numbers.get(t.to_account_id if e.direction == "debit" else t.from_account_id, "—"),
            created_at=e.created_at,
        )
        for e, t in page
    ]
    return LedgerPageOut(items=items, next_cursor=page[-1][0].id if has_more else None)


@router.post(
    "/{account_id}/fund", response_model=TransactionOut, status_code=201,
    dependencies=[Depends(rate_limit("fund", "rate_limit_transfer_per_minute", 60))],
)
def fund(account_id: str, body: FundIn, user: CurrentUser, db: DB, request: Request):
    s = get_settings()
    if not s.demo_funding_enabled:
        raise HTTPException(404, "Not found")  # route effectively does not exist in production
    if body.amount_cents > s.demo_funding_max_cents:
        raise domain_to_http(DomainError(422, "limit_exceeded", "Amount exceeds the sandbox funding limit."))
    acct = owned_account(db, user, account_id)
    tx = ledger.demo_fund(db, user=user, account=acct, amount_cents=body.amount_cents, ip=ip_of(request))
    return TransactionOut(
        id=tx.id, kind=tx.kind, amount_cents=tx.amount_cents, currency=tx.currency,
        description=tx.description, from_account="Treasury", to_account=ledger.mask(acct.account_number),
        created_at=tx.created_at,
    )
