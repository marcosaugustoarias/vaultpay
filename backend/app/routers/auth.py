"""Authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser, csrf_guard, ip_of
from app.errors import domain_to_http
from app.models import RefreshToken, User
from app.schemas import (
    ChangePasswordIn,
    LoginIn,
    MessageOut,
    MfaChallengeOut,
    MfaVerifyIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.security import passwords, tokens
from app.security.rate_limit import rate_limit
from app.services import audit
from app.services import auth as auth_service
from app.services.errors import DomainError
from app.services.mfa import check_totp, is_locked

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "vp_refresh"


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=s.refresh_token_ttl_seconds,
        httponly=True,  # JS can never read it -> XSS cannot steal the long-lived token
        secure=s.cookie_secure,
        samesite="strict",  # never sent on cross-site requests
        path="/api/auth",  # only the auth endpoints ever receive it
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


def _clear_cookie_header() -> dict[str, str]:
    """Set-Cookie header that expires the refresh cookie (usable on error responses)."""
    tmp = Response()
    tmp.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"set-cookie": tmp.headers["set-cookie"]}


def _token_out(access: str) -> TokenOut:
    return TokenOut(access_token=access, expires_in=get_settings().access_token_ttl_seconds)


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MessageOut,
    dependencies=[Depends(rate_limit("register", "rate_limit_register_per_hour", 3600))],
)
def register(body: RegisterIn, request: Request, db: DB) -> MessageOut:
    try:
        auth_service.register(
            db, email=body.email, password=body.password, full_name=body.full_name,
            phone=body.phone, ip=ip_of(request),
        )
    except DomainError as err:
        raise_http(err)
    # Same answer whether or not the e-mail already existed (SEC-AUTH-04).
    return MessageOut(message="If the details are valid your account is ready. You can now sign in.")


@router.post(
    "/login",
    response_model=TokenOut | MfaChallengeOut,
    dependencies=[Depends(rate_limit("login", "rate_limit_login_per_minute", 60))],
)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    ip = ip_of(request)
    try:
        user = auth_service.authenticate(db, email=body.email, password=body.password, ip=ip)
    except DomainError as err:
        raise_http(err)

    if user.mfa_enabled:
        # Password OK, but no API access until the second factor is verified.
        audit.record(db, "auth.login_password_ok", actor_user_id=user.id, ip=ip)
        db.commit()
        return MfaChallengeOut(mfa_token=tokens.create_mfa_token(user.id))

    return _complete_login(db, user, response, request, amr=["pwd"])


@router.post(
    "/mfa/verify",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit("mfa", "rate_limit_login_per_minute", 60))],
)
def mfa_verify(body: MfaVerifyIn, request: Request, response: Response, db: DB):
    ip = ip_of(request)
    try:
        claims = tokens.decode_token(body.mfa_token, use="mfa")
    except tokens.TokenError:
        raise_http(auth_service.INVALID_CREDENTIALS)
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active or is_locked(user):
        raise_http(auth_service.INVALID_CREDENTIALS)

    if not check_totp(db, user, body.code):
        audit.record(db, "auth.mfa", outcome="failure", actor_user_id=user.id, ip=ip)
        db.commit()
        raise_http(DomainError(401, "invalid_code", "Invalid verification code."))

    return _complete_login(db, user, response, request, amr=["pwd", "otp"])


def _complete_login(db: DB, user: User, response: Response, request: Request, amr: list[str]):
    ip = ip_of(request)
    user.failed_login_attempts = 0
    user.locked_until = None
    access, raw = auth_service.issue_session(
        db, user, amr=amr, ip=ip, user_agent=request.headers.get("user-agent")
    )
    audit.record(db, "auth.login", actor_user_id=user.id, ip=ip, details={"amr": amr})
    db.commit()
    _set_refresh_cookie(response, raw)
    return _token_out(access)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(csrf_guard)])
def refresh(request: Request, response: Response, db: DB):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise_http(DomainError(401, "invalid_refresh", "Session expired."))
    try:
        _user, access, new_raw = auth_service.rotate_refresh_token(
            db, raw, ip=ip_of(request), user_agent=request.headers.get("user-agent")
        )
    except DomainError as err:
        raise_http(err, headers=_clear_cookie_header())
    _set_refresh_cookie(response, new_raw)
    return _token_out(access)


@router.post("/logout", response_model=MessageOut, dependencies=[Depends(csrf_guard)])
def logout(request: Request, response: Response, db: DB):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        rt = db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == tokens.hash_refresh_token(raw))
        ).scalar_one_or_none()
        if rt:
            auth_service.revoke_family(db, rt.family_id)
            audit.record(db, "auth.logout", actor_user_id=rt.user_id, ip=ip_of(request))
            db.commit()
    _clear_refresh_cookie(response)
    return MessageOut(message="Signed out.")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.post("/change-password", response_model=MessageOut)
def change_password(body: ChangePasswordIn, request: Request, user: CurrentUser, db: DB):
    ip = ip_of(request)
    if is_locked(user) or not passwords.verify_password(body.current_password, user.password_hash):
        audit.record(db, "auth.password_change", outcome="failure", actor_user_id=user.id, ip=ip)
        db.commit()
        raise_http(DomainError(401, "invalid_credentials", "Invalid credentials."))
    errors = passwords.validate_password_policy(
        body.new_password, email=user.email, full_name=user.full_name
    )
    if errors or passwords.verify_password(body.new_password, user.password_hash):
        raise_http(DomainError(422, "weak_password", "New password does not meet the policy."))
    user.password_hash = passwords.hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    # Kill every existing session: refresh tokens (here) and access tokens (iat check).
    auth_service.revoke_all_for_user(db, user.id)
    audit.record(db, "auth.password_change", actor_user_id=user.id, ip=ip)
    db.commit()
    return MessageOut(message="Password changed. Please sign in again.")


def raise_http(err: DomainError, headers: dict[str, str] | None = None):
    raise domain_to_http(err, headers)
