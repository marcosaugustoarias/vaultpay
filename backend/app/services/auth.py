"""Authentication use-cases: registration, login, session (refresh-token) lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshToken, User, new_id
from app.security import passwords, tokens
from app.services import audit, ledger
from app.services.errors import DomainError
from app.services.mfa import is_locked, register_failed_attempt

# SEC-AUTH-04: one message for every failure mode (unknown user, wrong password, locked).
INVALID_CREDENTIALS = DomainError(401, "invalid_credentials", "Invalid credentials.")


def register(
    db: Session, *, email: str, password: str, full_name: str, phone: str | None, ip: str | None
) -> None:
    """Create a user + checking account.

    SEC-AUTH-04: callers get an identical response whether or not the e-mail was
    already registered (no account enumeration). We always pay the hashing cost so
    timing doesn't leak it either. In production the real owner would be e-mailed.
    """
    errors = passwords.validate_password_policy(password, email=email, full_name=full_name)
    if errors:
        raise DomainError(422, "weak_password", "Password " + "; ".join(errors) + ".")

    password_hash = passwords.hash_password(password)  # always, even for duplicates
    exists = db.execute(select(User.id).where(User.email == email)).scalar_one_or_none()
    if exists:
        audit.record(db, "auth.register", outcome="denied", ip=ip, details={"reason": "duplicate"})
        db.commit()
        return
    try:
        user = User(email=email, password_hash=password_hash, full_name=full_name, phone=phone)
        db.add(user)
        db.flush()
        ledger.open_account(db, user)
        audit.record(db, "auth.register", actor_user_id=user.id, ip=ip)
        db.commit()
    except IntegrityError:  # concurrent duplicate registration
        db.rollback()


def authenticate(db: Session, *, email: str, password: str, ip: str | None) -> User:
    """Verify the password. Raises the generic INVALID_CREDENTIALS on any failure."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None or not user.is_active:
        passwords.verify_dummy(password)  # equalise timing
        audit.record(db, "auth.login", outcome="failure", ip=ip, details={"reason": "unknown"})
        db.commit()
        raise INVALID_CREDENTIALS

    if is_locked(user):
        passwords.verify_dummy(password)
        audit.record(
            db, "auth.login", outcome="denied", actor_user_id=user.id, ip=ip, details={"reason": "locked"}
        )
        db.commit()
        raise INVALID_CREDENTIALS

    if not passwords.verify_password(password, user.password_hash):
        locked_now = register_failed_attempt(user)
        audit.record(
            db, "auth.login", outcome="failure", actor_user_id=user.id, ip=ip, details={"reason": "bad_password"}
        )
        if locked_now:
            audit.record(db, "auth.lockout", outcome="denied", actor_user_id=user.id, ip=ip)
        db.commit()
        raise INVALID_CREDENTIALS

    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    return user


# ------------------------------------------------------------- sessions
def issue_session(
    db: Session, user: User, *, amr: list[str], ip: str | None, user_agent: str | None,
    family_id: str | None = None,
) -> tuple[str, str]:
    """Create an access token + a new refresh token in `family_id` (or a new family)."""
    s = get_settings()
    raw, digest = tokens.new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or new_id(),
            token_hash=digest,
            amr=",".join(amr),
            expires_at=datetime.now(UTC) + timedelta(seconds=s.refresh_token_ttl_seconds),
            ip=ip,
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    return tokens.create_access_token(user.id, amr), raw


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def revoke_all_for_user(db: Session, user_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def rotate_refresh_token(
    db: Session, raw_token: str, *, ip: str | None, user_agent: str | None
) -> tuple[User, str, str]:
    """SEC-AUTH-06: single-use refresh tokens with reuse detection.

    Every refresh returns a *new* token and marks the old one used. If an already-
    used token shows up again, somebody (attacker or victim) holds a stolen copy:
    the whole token family is revoked and both must log in again.
    """
    rt = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == tokens.hash_refresh_token(raw_token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if rt is None:
        raise DomainError(401, "invalid_refresh", "Session expired.")

    if rt.used_at is not None or rt.revoked_at is not None:
        revoke_family(db, rt.family_id)
        audit.record(
            db, "auth.refresh_reuse_detected", outcome="denied", actor_user_id=rt.user_id, ip=ip,
            details={"family": rt.family_id},
        )
        db.commit()
        raise DomainError(401, "invalid_refresh", "Session expired.")

    if rt.expires_at <= now:
        raise DomainError(401, "invalid_refresh", "Session expired.")

    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise DomainError(401, "invalid_refresh", "Session expired.")

    rt.used_at = now
    access, new_raw = issue_session(
        db, user, amr=rt.amr.split(","), ip=ip, user_agent=user_agent, family_id=rt.family_id
    )
    db.commit()
    return user, access, new_raw
