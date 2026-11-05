"""SEC-AUTH-*: registration, login, lockout, tokens, sessions."""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.models import User
from app.security import passwords
from app.security.tokens import ALGORITHM, create_access_token, create_mfa_token
from tests.conftest import CSRF, PASSWORD, make_customer


# ---------------------------------------------------------------- registration
def test_register_then_login(client):
    cust = make_customer(client)
    me = client.get("/api/auth/me", headers=cust.headers).json()
    assert me["email"] == "alice@example.com"
    assert "password_hash" not in me and "totp_secret" not in me  # explicit response allow-list


def test_registration_does_not_reveal_existing_emails(client):
    """SEC-AUTH-04: same status + body for new and already-registered e-mails."""
    body = {"email": "dup@example.com", "password": PASSWORD, "full_name": "Dup User"}
    first = client.post("/api/auth/register", json=body)
    second = client.post("/api/auth/register", json={**body, "password": "another-strong-pass-77"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    # ...and the original password still works (the duplicate did not overwrite it).
    assert client.post("/api/auth/login", json={"email": body["email"], "password": PASSWORD}).status_code == 200


@pytest.mark.parametrize("pw", ["short1!", "password123", "aaaaaaaaaaaaaaaa", "alice-is-my-name"])
def test_weak_passwords_rejected(client, pw):
    """SEC-AUTH-02: length / blocklist / no personal data."""
    r = client.post("/api/auth/register", json={"email": "alice@example.com", "password": pw, "full_name": "Test User"})
    assert r.status_code == 422


def test_password_stored_as_argon2id_not_plaintext(client, db):
    make_customer(client)
    stored = db.query(User).filter_by(email="alice@example.com").one().password_hash
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_validation_errors_never_echo_submitted_values(client):
    """SEC-API-06: FastAPI's default 422 would reflect the password back."""
    secret = "p" * 200  # too long -> validation error
    r = client.post("/api/auth/login", json={"email": "alice@example.com", "password": secret})
    assert r.status_code == 422
    assert secret not in r.text and "input" not in r.json()["detail"]["errors"][0]


def test_mass_assignment_is_rejected(client):
    """SEC-API-01: unknown fields (e.g. role) are an error, not silently ignored."""
    r = client.post(
        "/api/auth/register",
        json={"email": "evil@example.com", "password": PASSWORD, "full_name": "Evil", "role": "admin"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- login
def test_login_failures_are_indistinguishable(client):
    """SEC-AUTH-04: unknown user and wrong password give the same response."""
    make_customer(client)
    wrong_pw = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-123"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


def test_account_lockout_after_repeated_failures(client, settings):
    """SEC-AUTH-03: brute force locks the account - even the right password is refused."""
    make_customer(client)
    for _ in range(settings.max_failed_logins):
        r = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"})
        assert r.status_code == 401
    locked = client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert locked.status_code == 401  # generic: lock state is not revealed


def test_lockout_expires(client, settings, db):
    make_customer(client)
    for _ in range(settings.max_failed_logins):
        client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"})
    user = db.query(User).filter_by(email="alice@example.com").one()
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 200


def test_login_rate_limit_per_ip(client, settings):
    """SEC-API-02: credential stuffing from one IP is throttled."""
    codes = [
        client.post("/api/auth/login", json={"email": f"u{i}@example.com", "password": "wrong-password-123"}).status_code
        for i in range(settings.rate_limit_login_per_minute + 2)
    ]
    assert codes[-1] == 429 and codes[0] == 401


# ---------------------------------------------------------------- JWT hardening
def test_requests_without_token_are_rejected(client):
    r = client.get("/api/accounts")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "not_authenticated"
    assert r.headers["www-authenticate"] == "Bearer"


def test_business_401_is_distinguishable_from_auth_failure(client, alice, bob):
    """A wrong step-up OTP must not look like an expired token (clients would refresh+replay)."""
    import uuid

    alice.enable_mfa()
    alice.fund(100_000)
    r = client.post(
        "/api/transfers", headers={**alice.headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"from_account_id": alice.account["id"], "to_account_number": bob.account["account_number"],
              "amount_cents": 60_000, "otp_code": "000000"},
    )
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_otp"
    assert "www-authenticate" not in r.headers


def test_alg_none_token_rejected(client, alice, db):
    """SEC-AUTH-05: the classic `alg: none` forgery."""
    uid = db.query(User).filter_by(email=alice.email).one().id
    s = get_settings()
    now = int(time.time())
    forged = jwt.encode(
        {"iss": s.jwt_issuer, "aud": s.jwt_audience, "sub": uid, "use": "access", "jti": "x", "iat": now, "exp": now + 600},
        key=None, algorithm="none",
    )
    assert client.get("/api/accounts", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_signed_with_other_secret_rejected(client, alice, db):
    uid = db.query(User).filter_by(email=alice.email).one().id
    s = get_settings()
    now = int(time.time())
    forged = jwt.encode(
        {"iss": s.jwt_issuer, "aud": s.jwt_audience, "sub": uid, "use": "access", "jti": "x", "iat": now, "exp": now + 600},
        "attacker-secret-attacker-secret-1234", algorithm=ALGORITHM,
    )
    assert client.get("/api/accounts", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token_rejected(client, alice, db, monkeypatch):
    uid = db.query(User).filter_by(email=alice.email).one().id
    monkeypatch.setattr(get_settings(), "access_token_ttl_seconds", -10)
    token = create_access_token(uid, ["pwd"])
    assert client.get("/api/accounts", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_mfa_pending_token_cannot_be_used_as_access_token(client, alice, db):
    """The 'password ok, OTP pending' token must not open the API."""
    uid = db.query(User).filter_by(email=alice.email).one().id
    token = create_mfa_token(uid)
    assert client.get("/api/accounts", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_inactive_user_token_rejected(client, alice, db):
    db.query(User).filter_by(email=alice.email).update({"is_active": False})
    db.commit()
    assert client.get("/api/accounts", headers=alice.headers).status_code == 401


# ---------------------------------------------------------------- refresh tokens
def _refresh(client, headers=CSRF):
    return client.post("/api/auth/refresh", headers=headers)


def test_refresh_cookie_flags(client):
    r = client.post("/api/auth/register", json={"email": "c@example.com", "password": PASSWORD, "full_name": "Cookie Monster"})
    r = client.post("/api/auth/login", json={"email": "c@example.com", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/auth" in cookie
    assert "access_token" not in r.headers["set-cookie"]  # access token is never in a cookie


def test_refresh_rotates_and_issues_working_access_token(client, alice):
    first_cookie = client.cookies.get("vp_refresh")
    r = _refresh(client)
    assert r.status_code == 200
    assert client.cookies.get("vp_refresh") != first_cookie  # rotated
    new = r.json()["access_token"]
    assert client.get("/api/accounts", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_refresh_token_reuse_revokes_whole_family(client, alice):
    """SEC-AUTH-06: a replayed (stolen) refresh token burns the session for everyone."""
    stolen = client.cookies.get("vp_refresh")
    assert _refresh(client).status_code == 200  # legitimate rotation
    legit_new = client.cookies.get("vp_refresh")

    client.cookies.set("vp_refresh", stolen, path="/api/auth")  # attacker replays the old token
    assert _refresh(client).status_code == 401

    client.cookies.set("vp_refresh", legit_new, path="/api/auth")  # victim's newer token is dead too
    assert _refresh(client).status_code == 401


def test_refresh_requires_csrf_header_and_allowed_origin(client, alice):
    assert client.post("/api/auth/refresh").status_code == 403  # no custom header
    evil = client.post("/api/auth/refresh", headers={**CSRF, "Origin": "https://evil.example"})
    assert evil.status_code == 403
    ok = client.post("/api/auth/refresh", headers={**CSRF, "Origin": "http://localhost:5173"})
    assert ok.status_code == 200


def test_refresh_without_cookie(client):
    assert _refresh(client).status_code == 401


def test_logout_revokes_refresh_token(client, alice):
    cookie = client.cookies.get("vp_refresh")
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 200
    client.cookies.set("vp_refresh", cookie, path="/api/auth")
    assert _refresh(client).status_code == 401


def test_refresh_token_stored_only_as_hash(client, alice, db):
    from app.models import RefreshToken

    raw = client.cookies.get("vp_refresh")
    rows = db.query(RefreshToken).all()
    assert rows and all(raw not in (r.token_hash or "") and len(r.token_hash) == 64 for r in rows)


def test_password_change_kills_all_sessions(client, alice):
    time.sleep(1.1)  # `iat` has 1-second resolution
    r = client.post(
        "/api/auth/change-password", headers=alice.headers,
        json={"current_password": PASSWORD, "new_password": "brand-new-passphrase-42"},
    )
    assert r.status_code == 200
    assert client.get("/api/accounts", headers=alice.headers).status_code == 401  # old access token
    assert _refresh(client).status_code == 401  # old refresh token
    assert client.post("/api/auth/login", json={"email": alice.email, "password": "brand-new-passphrase-42"}).status_code == 200


def test_change_password_requires_current_password(client, alice):
    r = client.post(
        "/api/auth/change-password", headers=alice.headers,
        json={"current_password": "not-my-password-1", "new_password": "brand-new-passphrase-42"},
    )
    assert r.status_code == 401


def test_dummy_verification_is_used_for_unknown_users(monkeypatch, client):
    calls = []
    monkeypatch.setattr(passwords, "verify_dummy", lambda pw: calls.append(pw))
    client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever-123456"})
    assert calls  # timing equalisation path executed
