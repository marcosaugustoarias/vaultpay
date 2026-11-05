"""FastAPI dependencies: authentication, authorisation, CSRF guard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.security.rate_limit import client_ip
from app.security.tokens import TokenError, decode_token

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)

# A distinct code lets clients tell "your access token is missing/expired -> refresh"
# apart from business 401s such as a wrong OTP, which must NOT trigger refresh+replay.
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    {"message": "Not authenticated", "code": "not_authenticated"},
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User:
    """Authenticate the bearer access token (SEC-AUTH-05)."""
    if creds is None:
        raise _UNAUTHORIZED
    try:
        claims = decode_token(creds.credentials, use="access")
    except TokenError:
        raise _UNAUTHORIZED from None
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    # Tokens issued before a password change / "log out everywhere" are dead.
    if user.password_changed_at and claims["iat"] < int(user.password_changed_at.timestamp()):
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """SEC-AUTHZ-02: RBAC. Server-side only; the UI hiding a button is not a control."""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def csrf_guard(request: Request) -> None:
    """SEC-AUTH-07: defence in depth for the cookie-authenticated endpoints.

    1. SameSite=Strict on the cookie (set in the router) blocks cross-site sends.
    2. A custom header forces a CORS pre-flight for cross-origin JS, which our
       strict CORS policy rejects.
    3. If the browser sends `Origin`, it must be one we allow.
    """
    if request.headers.get("x-requested-with") != "vaultpay":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing CSRF header")
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")


def ip_of(request: Request) -> str:
    return client_ip(request)


def now() -> datetime:
    return datetime.now(UTC)
