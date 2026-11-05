"""Tamper-evident audit trail (SEC-AUDIT-01).

Every row stores  hash = SHA-256(prev_hash || canonical_json(row)).  Changing,
deleting or re-ordering any historical row breaks every hash after it, which
`verify_chain` detects. The DB also rejects UPDATE/DELETE (see database.py).

Rows are written in the *same* DB transaction as the business change they
describe: either both exist or neither does.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS = "0" * 64


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _compute_hash(prev_hash: str, row: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(row)).encode()).hexdigest()


def _row_payload(entry: AuditLog) -> dict:
    return {
        "ts": entry.ts.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor": entry.actor_user_id,
        "action": entry.action,
        "outcome": entry.outcome,
        "ip": entry.ip,
        "details": entry.details,
    }


def record(
    db: Session,
    action: str,
    *,
    outcome: str = "success",
    actor_user_id: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Append an audit event. Never put secrets or full PII in `details`."""
    # Appends must be serialised or two concurrent writers would fork the chain.
    #  * PostgreSQL: transaction-scoped advisory lock (released on commit/rollback).
    #  * SQLite: every transaction starts with BEGIN IMMEDIATE (see database.py).
    # No in-process lock on purpose: mixing it with a DB lock can deadlock.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(727274)"))
    last = db.execute(select(AuditLog.hash).order_by(AuditLog.seq.desc()).limit(1)).scalar()
    entry = AuditLog(
        ts=datetime.now(UTC),
        actor_user_id=actor_user_id,
        action=action,
        outcome=outcome,
        ip=ip,
        details=details or {},
        prev_hash=last or GENESIS,
        hash="",
    )
    entry.hash = _compute_hash(entry.prev_hash, _row_payload(entry))
    db.add(entry)
    db.flush()
    return entry


@dataclass
class ChainReport:
    valid: bool
    checked: int
    first_broken_seq: int | None = None
    head_hash: str = GENESIS  # publish this to external, write-once storage ("anchor")


def verify_chain(db: Session, *, anchor_hash: str | None = None) -> ChainReport:
    """Re-compute the whole chain.

    A hash chain alone cannot notice that the *newest* rows were deleted (nothing
    points back at them). Passing a previously published `anchor_hash` closes that
    gap: it must still appear in the chain, otherwise history was truncated/rewritten.
    """
    prev = GENESIS
    checked = 0
    anchor_seen = anchor_hash is None
    for entry in db.execute(select(AuditLog).order_by(AuditLog.seq)).scalars():
        expected = _compute_hash(prev, _row_payload(entry))
        if entry.prev_hash != prev or entry.hash != expected:
            return ChainReport(False, checked, entry.seq, prev)
        prev = entry.hash
        checked += 1
        anchor_seen = anchor_seen or entry.hash == anchor_hash
    return ChainReport(anchor_seen, checked, None, prev)
