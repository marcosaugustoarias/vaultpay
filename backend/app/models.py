"""ORM models.

Money is ALWAYS an integer number of minor units (cents) - never float/Decimal
in transit (SEC-DATA-02). CHECK constraints make the database the last line of
defence against negative balances or zero/negative amounts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database import Base
from app.security.crypto import EncryptedString


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """Always store UTC, always return timezone-aware datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    # PII / secrets encrypted at rest (SEC-DATA-01)
    phone: Mapped[str | None] = mapped_column(EncryptedString("users.phone"), nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(
        EncryptedString("users.totp_secret"), nullable=True
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # replay guard
    role: Mapped[str] = mapped_column(String(16), default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    accounts: Mapped[list[Account]] = relationship(back_populates="user")

    __table_args__ = (CheckConstraint("role IN ('customer','admin')", name="ck_users_role"),)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # Random (non-sequential) 12 digits with a Luhn check digit: not enumerable, typo-safe.
    account_number: Mapped[str] = mapped_column(String(12), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="accounts")

    __table_args__ = (
        # Customers can never overdraw. Only the internal treasury may go negative.
        CheckConstraint("is_system OR balance_cents >= 0", name="ck_accounts_no_overdraft"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # initiator
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # transfer | deposit
    from_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    to_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(String(140), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_tx_positive_amount"),
        CheckConstraint("from_account_id <> to_account_id", name="ck_tx_distinct_accounts"),
        CheckConstraint("kind IN ('transfer','deposit')", name="ck_tx_kind"),
        # SEC-DATA-05: one logical operation per (user, key)
        UniqueConstraint("user_id", "idempotency_key", name="uq_tx_idempotency"),
    )


class LedgerEntry(Base):
    """One leg of a double-entry transaction. Immutable (SEC-DATA-03)."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(6))  # debit | credit
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_le_positive_amount"),
        CheckConstraint("direction IN ('debit','credit')", name="ck_le_direction"),
    )


class RefreshToken(Base):
    """Server-side record of an opaque refresh token. Only its SHA-256 is stored."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)  # one per login session
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    amr: Mapped[str] = mapped_column(String(32), default="pwd")  # auth methods, e.g. "pwd,otp"
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # rotated
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained security/audit trail (SEC-AUDIT-01)."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure | denied
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


Index("ix_ledger_account_id_desc", LedgerEntry.account_id, LedgerEntry.id.desc())


# ORM-level guard in addition to the DB triggers (defence in depth).
def _forbid(*_args, **_kwargs):
    raise RuntimeError("append-only table: updates and deletes are forbidden")


for _model in (LedgerEntry, AuditLog):
    event.listen(_model, "before_update", _forbid)
    event.listen(_model, "before_delete", _forbid)
