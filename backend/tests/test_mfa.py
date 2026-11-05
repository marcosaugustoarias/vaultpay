"""SEC-AUTH-08/09: TOTP enrolment, login challenge, replay protection."""

import time

from app.security import totp
from tests.conftest import PASSWORD


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


def test_login_with_mfa_requires_second_factor(client, alice):
    secret = alice.enable_mfa()
    r = _login(client, alice.email)
    assert r.status_code == 200 and r.json().get("mfa_required") is True
    assert "access_token" not in r.json() and "vp_refresh" not in r.headers.get("set-cookie", "")

    mfa_token = r.json()["mfa_token"]
    # Use a different time-step than the one consumed during enrolment (replay protection).
    ok = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "code": totp.current_code(secret, at=time.time() + 30)})
    assert ok.status_code == 200 and "access_token" in ok.json()


def test_wrong_code_rejected_and_counts_toward_lockout(client, alice, settings):
    alice.enable_mfa()
    mfa_token = _login(client, alice.email).json()["mfa_token"]
    for _ in range(settings.max_failed_logins):
        r = client.post("/api/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"})
        assert r.status_code == 401
    # Account now locked: even a valid password gets the generic failure.
    assert _login(client, alice.email).status_code == 401


def test_totp_code_cannot_be_replayed(client, alice):
    secret = alice.enable_mfa()
    code = totp.current_code(secret, at=time.time() + 30)
    first = client.post("/api/auth/mfa/verify", json={"mfa_token": _login(client, alice.email).json()["mfa_token"], "code": code})
    assert first.status_code == 200
    replay = client.post("/api/auth/mfa/verify", json={"mfa_token": _login(client, alice.email).json()["mfa_token"], "code": code})
    assert replay.status_code == 401


def test_totp_unit_replay_and_window():
    secret = totp.generate_secret()
    now = 1_700_000_000
    step = totp.verify(secret, totp.current_code(secret, at=now), None, at=now)
    assert step is not None
    assert totp.verify(secret, totp.current_code(secret, at=now), step, at=now) is None  # replay
    assert totp.verify(secret, totp.current_code(secret, at=now - 30), None, at=now) is not None  # drift ok
    assert totp.verify(secret, totp.current_code(secret, at=now - 300), None, at=now) is None  # too old
    assert totp.verify(secret, "12345", None, at=now) is None and totp.verify(secret, "abcdef", None, at=now) is None


def test_secret_is_encrypted_at_rest(client, alice, db):
    secret = alice.enable_mfa()
    raw = db.connection().exec_driver_sql("SELECT totp_secret FROM users WHERE email = ?", (alice.email,)).scalar()
    assert raw.startswith("v1.") and secret not in raw


def test_mfa_token_from_garbage_rejected(client):
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": "not-a-jwt-at-all", "code": "123456"})
    assert r.status_code == 401


def test_disable_requires_password_and_code(client, alice):
    secret = alice.enable_mfa()
    bad = client.post("/api/mfa/disable", headers=alice.headers, json={"password": "wrong-password-1", "code": totp.current_code(secret, at=time.time() + 30)})
    assert bad.status_code == 401
    ok = client.post("/api/mfa/disable", headers=alice.headers, json={"password": PASSWORD, "code": totp.current_code(secret, at=time.time() + 30)})
    assert ok.status_code == 200
    assert _login(client, alice.email).json().get("mfa_required") is None


def test_cannot_start_setup_twice(client, alice):
    alice.enable_mfa()
    assert client.post("/api/mfa/setup", headers=alice.headers).status_code == 409
