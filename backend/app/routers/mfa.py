"""TOTP enrolment / removal (SEC-AUTH-08)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import DB, CurrentUser, ip_of
from app.errors import domain_to_http
from app.schemas import MessageOut, MfaCodeIn, MfaDisableIn, MfaSetupOut
from app.security import passwords, totp
from app.security.rate_limit import rate_limit
from app.services import audit
from app.services.errors import DomainError
from app.services.mfa import check_totp, is_locked

router = APIRouter(prefix="/api/mfa", tags=["mfa"],
                   dependencies=[Depends(rate_limit("mfa-admin", "rate_limit_login_per_minute", 60))])


@router.post("/setup", response_model=MfaSetupOut)
def setup(user: CurrentUser, db: DB, request: Request) -> MfaSetupOut:
    if user.mfa_enabled:
        raise domain_to_http(DomainError(409, "mfa_already_enabled", "Two-factor is already enabled."))
    user.totp_secret = totp.generate_secret()  # stored encrypted at rest (SEC-DATA-01)
    audit.record(db, "mfa.setup_started", actor_user_id=user.id, ip=ip_of(request))
    db.commit()
    return MfaSetupOut(secret=user.totp_secret, otpauth_uri=totp.provisioning_uri(user.totp_secret, user.email))


@router.post("/enable", response_model=MessageOut)
def enable(body: MfaCodeIn, user: CurrentUser, db: DB, request: Request) -> MessageOut:
    if user.mfa_enabled or not user.totp_secret:
        raise domain_to_http(DomainError(409, "mfa_state", "Start the setup first."))
    step = totp.verify(user.totp_secret, body.code, user.totp_last_step)
    if step is None:
        raise domain_to_http(DomainError(401, "invalid_code", "Invalid verification code."))
    user.mfa_enabled = True
    user.totp_last_step = step
    audit.record(db, "mfa.enabled", actor_user_id=user.id, ip=ip_of(request))
    db.commit()
    return MessageOut(message="Two-factor authentication enabled.")


@router.post("/disable", response_model=MessageOut)
def disable(body: MfaDisableIn, user: CurrentUser, db: DB, request: Request) -> MessageOut:
    """Removing a factor needs BOTH the password and a fresh code (a stolen access
    token alone must not be enough to downgrade the account)."""
    if not user.mfa_enabled:
        raise domain_to_http(DomainError(409, "mfa_state", "Two-factor is not enabled."))
    if is_locked(user):
        raise HTTPException(423, "Account temporarily locked")
    if not passwords.verify_password(body.password, user.password_hash) or not check_totp(db, user, body.code):
        audit.record(db, "mfa.disable", outcome="failure", actor_user_id=user.id, ip=ip_of(request))
        db.commit()
        raise domain_to_http(DomainError(401, "invalid_credentials", "Invalid credentials."))
    user.mfa_enabled = False
    user.totp_secret = None
    user.totp_last_step = None
    audit.record(db, "mfa.disabled", actor_user_id=user.id, ip=ip_of(request))
    db.commit()
    return MessageOut(message="Two-factor authentication disabled.")
