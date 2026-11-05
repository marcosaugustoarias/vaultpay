"""Shared second-factor verification with brute-force accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.security import totp


def register_failed_attempt(user: User) -> bool:
    """Increment the failure counter; lock the account when the threshold is hit.
    Returns True if the account just became locked (SEC-AUTH-03)."""
    s = get_settings()
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= s.max_failed_logins:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=s.lockout_minutes)
        user.failed_login_attempts = 0
        return True
    return False


def is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > datetime.now(UTC)


def check_totp(db: Session, user: User, code: str) -> bool:
    """Verify a code for `user`, persist replay-protection state and failure counters.
    The caller commits."""
    if not user.mfa_enabled or not user.totp_secret:
        return False
    step = totp.verify(user.totp_secret, code, user.totp_last_step)
    if step is None:
        register_failed_attempt(user)
        return False
    user.totp_last_step = step
    user.failed_login_attempts = 0
    return True
