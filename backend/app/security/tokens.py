"""Access / MFA JWTs and opaque refresh tokens.

SEC-AUTH-05: short-lived access tokens; algorithm pinned on decode (no `alg: none`
or algorithm-confusion), `iss`/`aud`/`exp`/`iat`/`sub`/`jti` required, and a
`use` claim so a token minted for one purpose can't be replayed for another.
SEC-AUTH-06: refresh tokens are 256-bit random opaque strings; only their
SHA-256 is persisted, so a database leak doesn't leak usable tokens.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def _encode(sub: str, use: str, ttl: int, extra: dict | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sub": sub,
        "use": use,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: str, amr: list[str]) -> str:
    return _encode(user_id, "access", get_settings().access_token_ttl_seconds, {"amr": amr})


def create_mfa_token(user_id: str) -> str:
    """Short-lived 'password OK, second factor pending' token. Useless for the API."""
    return _encode(user_id, "mfa", get_settings().mfa_token_ttl_seconds)


def decode_token(token: str, *, use: str) -> dict:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[ALGORITHM],  # pinned
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if claims.get("use") != use:
        raise TokenError("wrong token use")
    return claims


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token_for_cookie, sha256_for_database)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
