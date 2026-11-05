"""Double-entry ledger and atomic money movement.

SEC-DATA-04  Every movement is two ledger legs (debit + credit) of the same amount
             inside ONE database transaction together with its audit record.
             Debits use a *conditional* UPDATE (`... WHERE balance >= :amount`), so
             two concurrent transfers can never double-spend, regardless of DB or
             isolation level. Accounts are always touched in sorted-id order to
             prevent deadlocks between A->B and B->A.
SEC-DATA-05  Idempotency: a retried request (network flake, double click) returns the
             original result instead of moving money twice; reusing a key with a
             different payload is rejected.
SEC-AUTHZ-01 The source account must belong to the caller (404 otherwise: we do not
             reveal whether someone else's account id exists).

DDD role: this is the *application service* of the Ledger context. It orchestrates
repositories (SQLAlchemy), the domain model (``app.domain.ledger``), MFA and audit in
one unit of work. Business rules themselves live in the domain package.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger import AccountNumber, Money, check_transfer
from app.domain.ledger.account_number import mask
from app.models import Account, LedgerEntry, Transaction, User
from app.services import audit, risk
from app.services.errors import DomainError
from app.services.mfa import check_totp, is_locked

TREASURY_EMAIL = "treasury@vaultpay.internal"

__all__ = ["generate_account_number", "luhn_valid", "mask", "open_account", "transfer", "demo_fund"]


# ------------------------------------------------------------- account numbers
# Thin wrappers kept for callers that predate the domain layer (routers, tests).
def generate_account_number() -> str:
    return AccountNumber.generate().value


def luhn_valid(number: str) -> bool:
    return AccountNumber.is_valid(number)


def open_account(db: Session, user: User, *, system: bool = False) -> Account:
    for _ in range(5):
        acct = Account(user_id=user.id, account_number=generate_account_number(), is_system=system)
        try:
            with db.begin_nested():
                db.add(acct)
        except IntegrityError:  # astronomically rare number collision
            continue
        return acct
    raise RuntimeError("could not allocate an account number")


def ensure_treasury(db: Session) -> Account:
    """Internal counter-party for deposits so that the ledger always balances."""
    user = db.execute(select(User).where(User.email == TREASURY_EMAIL)).scalar_one_or_none()
    if user is None:
        user = User(
            email=TREASURY_EMAIL,
            # Sentinel, not a valid argon2 hash -> this user can never authenticate.
            password_hash="!",  # noqa: S106  # nosec B106
            full_name="VaultPay Treasury",
            is_active=False,
            role="admin",
        )
        db.add(user)
        db.flush()
    acct = db.execute(
        select(Account).where(Account.user_id == user.id, Account.is_system.is_(True))
    ).scalar_one_or_none()
    if acct is None:
        acct = open_account(db, user, system=True)
    db.commit()
    return acct


# ---------------------------------------------------------------- core move
def _request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _move(
    db: Session,
    *,
    initiator_id: str,
    kind: str,
    source: Account,
    dest: Account,
    amount_cents: int,
    description: str,
    idempotency_key: str,
    request_hash: str,
) -> Transaction:
    # Debit/credit in deterministic order (deadlock avoidance).
    legs = sorted(
        [(source, "debit"), (dest, "credit")],
        key=lambda leg: leg[0].id,
    )
    balances: dict[str, int] = {}
    for acct, direction in legs:
        if direction == "debit":
            guard = True if source.is_system else Account.balance_cents >= amount_cents
            stmt = (
                update(Account)
                .where(Account.id == acct.id, guard)
                .values(balance_cents=Account.balance_cents - amount_cents)
            )
        else:
            stmt = (
                update(Account)
                .where(Account.id == acct.id)
                .values(balance_cents=Account.balance_cents + amount_cents)
            )
        result = db.execute(stmt)
        if result.rowcount != 1:
            raise DomainError(422, "insufficient_funds", "Insufficient funds.")
        balances[acct.id] = db.execute(
            select(Account.balance_cents).where(Account.id == acct.id)
        ).scalar_one()

    tx = Transaction(
        user_id=initiator_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        kind=kind,
        from_account_id=source.id,
        to_account_id=dest.id,
        amount_cents=amount_cents,
        currency=source.currency,
        description=description,
    )
    db.add(tx)
    db.flush()
    for acct, direction in legs:
        db.add(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=acct.id,
                direction=direction,
                amount_cents=amount_cents,
                balance_after_cents=balances[acct.id],
            )
        )
    db.flush()
    return tx


def _find_existing(db: Session, user_id: str, key: str, req_hash: str) -> Transaction | None:
    existing = db.execute(
        select(Transaction).where(
            Transaction.user_id == user_id, Transaction.idempotency_key == key
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.request_hash != req_hash:
        raise DomainError(
            422, "idempotency_key_reused", "Idempotency-Key was already used with a different request."
        )
    return existing


def _fail(db: Session, err: DomainError, *, action: str, user: User, ip: str | None, details: dict):
    """Roll back any partial work, persist the denial in the audit log, then raise."""
    db.rollback()
    audit.record(
        db,
        action,
        outcome="denied",
        actor_user_id=user.id,
        ip=ip,
        details={**details, "reason": err.code},
    )
    db.commit()
    raise err


# ---------------------------------------------------------------- transfers
def transfer(
    db: Session,
    *,
    user: User,
    from_account_id: str,
    to_account_number: str,
    amount_cents: int,
    description: str,
    idempotency_key: str,
    otp_code: str | None,
    ip: str | None,
) -> tuple[Transaction, Account, Account]:
    req_hash = _request_hash(
        {
            "from": from_account_id,
            "to": to_account_number,
            "amount": amount_cents,
            "description": description,
        }
    )
    audit_ctx = {"amount_cents": amount_cents, "to": mask(to_account_number)}

    try:
        existing = _find_existing(db, user.id, idempotency_key, req_hash)
        if existing:
            return existing, *_accounts(db, existing)

        # SEC-AUTHZ-01: scope the lookup by owner -> foreign ids look like "not found".
        source = db.execute(
            select(Account).where(
                Account.id == from_account_id,
                Account.user_id == user.id,
                Account.is_system.is_(False),
            )
        ).scalar_one_or_none()
        if source is None:
            raise DomainError(404, "account_not_found", "Account not found.")

        # Domain rules: typo-safe account number (before any lookup), then the transfer spec.
        dest_number = AccountNumber(to_account_number)
        amount = Money.positive(amount_cents, source.currency)
        dest = db.execute(
            select(Account).where(
                Account.account_number == dest_number.value, Account.is_system.is_(False)
            )
        ).scalar_one_or_none()
        if dest is None:
            raise DomainError(404, "destination_not_found", "Destination account not found.")
        check_transfer(source, dest, amount)

        decision = risk.evaluate(db, source, user.id, amount.cents)
        if decision is risk.Decision.STEP_UP:
            # SEC-AUTH-09: high-value transfers need a *fresh* second factor.
            if not user.mfa_enabled:
                raise DomainError(
                    403, "mfa_required", "Enable two-factor authentication to send this amount."
                )
            if is_locked(user):
                raise DomainError(423, "account_locked", "Account temporarily locked.")
            if otp_code is None:
                raise DomainError(401, "otp_required", "A verification code is required.")
            if not check_totp(db, user, otp_code):
                db.commit()  # persist failure counter / lock *before* denying
                raise DomainError(401, "invalid_otp", "Invalid verification code.")

        tx = _move(
            db,
            initiator_id=user.id,
            kind="transfer",
            source=source,
            dest=dest,
            amount_cents=amount_cents,
            description=description,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )
        audit.record(
            db,
            "transfer.created",
            actor_user_id=user.id,
            ip=ip,
            details={**audit_ctx, "tx": tx.id, "step_up": decision is risk.Decision.STEP_UP},
        )
        db.commit()
        return tx, source, dest

    except BusinessRuleViolation as violation:
        _fail(db, DomainError.from_violation(violation), action="transfer.denied", user=user, ip=ip, details=audit_ctx)
        raise  # pragma: no cover - _fail always raises
    except DomainError as err:
        _fail(db, err, action="transfer.denied", user=user, ip=ip, details=audit_ctx)
        raise  # pragma: no cover - _fail always raises
    except IntegrityError:
        # Lost an idempotency race against a concurrent identical request.
        db.rollback()
        existing = _find_existing(db, user.id, idempotency_key, req_hash)
        if existing is None:
            raise
        return existing, *_accounts(db, existing)


def _accounts(db: Session, tx: Transaction) -> tuple[Account, Account]:
    src = db.get(Account, tx.from_account_id)
    dst = db.get(Account, tx.to_account_id)
    if src is None or dst is None:
        raise RuntimeError("transaction references a missing account")
    return src, dst


def demo_fund(
    db: Session, *, user: User, account: Account, amount_cents: int, ip: str | None
) -> Transaction:
    """Sandbox deposit: treasury -> account (still a balanced double entry)."""
    treasury = ensure_treasury(db)
    key = "fund-" + secrets.token_hex(16)
    tx = _move(
        db,
        initiator_id=user.id,
        kind="deposit",
        source=treasury,
        dest=account,
        amount_cents=amount_cents,
        description="Sandbox funding",
        idempotency_key=key,
        request_hash=_request_hash({"fund": account.id, "amount": amount_cents, "k": key}),
    )
    audit.record(
        db,
        "account.funded",
        actor_user_id=user.id,
        ip=ip,
        details={"amount_cents": amount_cents, "tx": tx.id},
    )
    db.commit()
    return tx
