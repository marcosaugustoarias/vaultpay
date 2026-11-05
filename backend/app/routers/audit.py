"""Audit trail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import DB, AdminUser, CurrentUser
from app.models import AuditLog
from app.schemas import AuditEventOut, ChainReportOut
from app.services import audit

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit/me", response_model=list[AuditEventOut])
def my_security_events(user: CurrentUser, db: DB, limit: int = Query(25, ge=1, le=100)):
    """Customers can review the security-relevant activity on *their own* account
    (logins, failed attempts, transfers) - so they can spot intrusions themselves."""
    return db.execute(
        select(AuditLog).where(AuditLog.actor_user_id == user.id).order_by(AuditLog.seq.desc()).limit(limit)
    ).scalars().all()


@router.get("/admin/audit/verify", response_model=ChainReportOut)
def verify_audit_chain(_admin: AdminUser, db: DB, anchor: str | None = Query(None, pattern=r"^[0-9a-f]{64}$")):
    """SEC-AUTHZ-02 + SEC-AUDIT-01: only admins can run the integrity check.

    `head_hash` should be copied to external write-once storage (the "anchor"); pass it
    back as `?anchor=` later to also detect truncation of the newest records."""
    report = audit.verify_chain(db, anchor_hash=anchor)
    return ChainReportOut(
        valid=report.valid, checked=report.checked,
        first_broken_seq=report.first_broken_seq, head_hash=report.head_hash,
    )
