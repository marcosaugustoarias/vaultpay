"""Cross-cutting controls: SEC-API-*, SEC-CFG-01, SEC-DATA-01/03, SEC-AUDIT-*, SEC-AUTHZ-02."""

import base64
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.logging_config import redact
from app.main import app, create_app
from app.models import AuditLog, LedgerEntry
from app.security.crypto import DecryptionError, Keyring
from app.security.rate_limit import RateLimiter
from app.services import audit
from tests.conftest import make_admin


# ---------------------------------------------------------------- headers / CORS / host
def test_security_headers_present(client):
    r = client.get("/healthz")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert h["x-request-id"]
    assert "server" not in {k.lower() for k in h} or "uvicorn" not in h.get("server", "")


def test_hsts_outside_development(client):
    assert "strict-transport-security" in client.get("/healthz").headers  # env=test


def test_cors_only_allows_configured_origins(client):
    ok = client.options("/api/accounts", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    evil = client.options("/api/accounts", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in evil.headers


def test_host_header_attack_rejected(client):
    assert client.get("/healthz", headers={"host": "evil.example"}).status_code == 400


# ---------------------------------------------------------------- DoS / errors
def test_oversized_body_rejected_by_content_length(client, settings):
    r = client.post("/api/auth/login", content=b"x" * (settings.max_body_bytes + 1),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_oversized_streamed_body_rejected(client, settings):
    def chunks():
        for _ in range(settings.max_body_bytes // 1024 + 5):
            yield b"x" * 1024

    r = client.post("/api/auth/login", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_unhandled_errors_do_not_leak_internals():
    @app.get("/__boom", include_in_schema=False)
    def boom():
        raise RuntimeError("secret-db-password=hunter2 at /srv/app/db.py")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__boom")
    assert r.status_code == 500
    assert "hunter2" not in r.text and "Traceback" not in r.text and "/srv/app" not in r.text
    assert r.json()["request_id"]


def test_docs_disabled_when_configured(settings, monkeypatch):
    monkeypatch.setattr(settings, "docs_enabled", False)
    with TestClient(create_app()) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


# ---------------------------------------------------------------- fail-fast production config
def _prod(**overrides) -> Settings:
    base = dict(
        env="production", jwt_secret="x" * 48, encryption_key=base64.b64encode(os.urandom(32)).decode(),
        cookie_secure=True, cors_origins=["https://app.vaultpay.example"], allowed_hosts=["api.vaultpay.example"],
        docs_enabled=False, demo_funding_enabled=False, database_url="postgresql+psycopg://u:p@db/vp",
    )
    return Settings(**{**base, **overrides})


def test_valid_production_config_accepted():
    assert _prod().env == "production"


@pytest.mark.parametrize("override", [
    {"jwt_secret": "short"},
    {"jwt_secret": "dev-only-jwt-secret-do-not-use-in-production-0123456789"},
    {"encryption_key": base64.b64encode(b"dev-only-32-byte-key-for-aes-256").decode()},
    {"cookie_secure": False},
    {"cors_origins": ["*"]},
    {"cors_origins": ["http://app.example"]},
    {"allowed_hosts": ["*"]},
    {"docs_enabled": True},
    {"demo_funding_enabled": True},
    {"database_url": "sqlite:///x.db"},
])
def test_insecure_production_config_refuses_to_start(override):
    """SEC-CFG-01"""
    with pytest.raises(ValueError, match="Insecure production configuration"):
        _prod(**override)


# ---------------------------------------------------------------- encryption at rest
def _ring(*keys: bytes, current: int = 0) -> Keyring:
    b64 = [base64.b64encode(k).decode() for k in keys]
    return Keyring(b64[current], [k for i, k in enumerate(b64) if i != current])


def test_encryption_roundtrip_and_randomised():
    ring = _ring(os.urandom(32))
    a, b = ring.encrypt("+14155550123", "users.phone"), ring.encrypt("+14155550123", "users.phone")
    assert a != b and "4155550123" not in a  # random nonce, no plaintext
    assert ring.decrypt(a, "users.phone") == "+14155550123"


def test_ciphertext_bound_to_its_column():
    ring = _ring(os.urandom(32))
    token = ring.encrypt("secret", "users.phone")
    with pytest.raises(DecryptionError):
        ring.decrypt(token, "users.totp_secret")  # copy/paste between columns fails


def test_tampered_ciphertext_detected():
    ring = _ring(os.urandom(32))
    v, kid, blob = ring.encrypt("secret", "p").split(".")
    raw = bytearray(base64.urlsafe_b64decode(blob))
    raw[-1] ^= 1
    with pytest.raises(DecryptionError):
        ring.decrypt(f"{v}.{kid}.{base64.urlsafe_b64encode(bytes(raw)).decode()}", "p")


def test_key_rotation_keeps_old_data_readable():
    old, new = os.urandom(32), os.urandom(32)
    token = _ring(old).encrypt("pii", "p")
    rotated = Keyring(base64.b64encode(new).decode(), [base64.b64encode(old).decode()])
    assert rotated.decrypt(token, "p") == "pii" and rotated.needs_rotation(token)
    assert not rotated.needs_rotation(rotated.encrypt("pii", "p"))
    with pytest.raises(DecryptionError):
        _ring(new).decrypt(token, "p")  # old key removed -> unreadable


def test_phone_is_encrypted_in_database(client, db):
    client.post("/api/auth/register", json={
        "email": "p@example.com", "password": "correct-horse-battery-9", "full_name": "Phone User", "phone": "+14155550123"})
    raw = db.connection().exec_driver_sql("SELECT phone FROM users WHERE email='p@example.com'").scalar()
    assert raw.startswith("v1.") and "4155550123" not in raw


# ---------------------------------------------------------------- rate limiter
def test_sliding_window_limiter():
    rl = RateLimiter()
    assert all(rl.hit("k", 3, 60) is None for _ in range(3))
    assert rl.hit("k", 3, 60) is not None  # 4th blocked, returns retry-after
    assert rl.hit("other", 3, 60) is None  # independent keys


def test_spoofed_x_forwarded_for_cannot_bypass_rate_limit(client, settings):
    """With no trusted proxy configured, X-Forwarded-For is ignored."""
    codes = [
        client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-123"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(settings.rate_limit_login_per_minute + 1)
    ]
    assert codes[-1] == 429


# ---------------------------------------------------------------- audit chain / immutability
def test_audit_chain_valid_and_detects_tampering(client, db, alice, bob):
    alice.fund(1_000)
    assert audit.verify_chain(db).valid and audit.verify_chain(db).checked >= 4

    # The DB refuses edits outright (SEC-DATA-03)...
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_log SET outcome='success' WHERE seq=1"))
    db.rollback()

    # ...and even a privileged attacker who drops the trigger is caught by the hash chain.
    db.execute(text("DROP TRIGGER audit_log_no_update"))
    db.execute(text("UPDATE audit_log SET ip='6.6.6.6' WHERE seq=2"))
    db.commit()
    report = audit.verify_chain(db)
    assert not report.valid and report.first_broken_seq == 2


def test_audit_chain_detects_deleted_row(client, db, alice):
    alice.fund(100)
    db.execute(text("DROP TRIGGER audit_log_no_delete"))
    db.execute(text("DELETE FROM audit_log WHERE seq=2"))  # a row in the middle of history
    db.commit()
    assert not audit.verify_chain(db).valid


def test_audit_truncation_is_caught_by_external_anchor(client, db, alice):
    """A bare hash chain can't see deleted *tail* rows; a published anchor can."""
    anchor = audit.verify_chain(db).head_hash  # ops copy this to write-once storage
    db.rollback()  # SQLite: release the write lock held by this session before calling the API
    alice.fund(100)
    assert audit.verify_chain(db, anchor_hash=anchor).valid
    db.execute(text("DROP TRIGGER audit_log_no_delete"))
    db.execute(text("DELETE FROM audit_log WHERE seq > 1"))  # attacker truncates the tail
    db.commit()
    assert audit.verify_chain(db).valid  # chain alone is fooled (documented limitation)
    assert not audit.verify_chain(db, anchor_hash=anchor).valid


def test_ledger_is_append_only_at_db_level(client, db, alice):
    alice.fund(1_000)
    for stmt in ("UPDATE ledger_entries SET amount_cents = 999999", "DELETE FROM ledger_entries"):
        with pytest.raises(DBAPIError):
            db.execute(text(stmt))
        db.rollback()


def test_ledger_and_audit_are_append_only_in_orm(client, db, alice):
    alice.fund(1_000)
    entry = db.query(LedgerEntry).first()
    entry.amount_cents = 1
    with pytest.raises(RuntimeError):
        db.flush()
    db.rollback()
    log = db.query(AuditLog).first()
    db.delete(log)
    with pytest.raises(RuntimeError):
        db.flush()
    db.rollback()


def test_database_blocks_overdraft_and_nonpositive_amounts(client, db, alice):
    """SEC-DATA-02: constraints are the last line of defence if app code is wrong."""
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE accounts SET balance_cents = -1 WHERE is_system = 0"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_cents, balance_after_cents, created_at) VALUES ('x','y','debit',-5,0,'2024-01-01')"))
    db.rollback()


def test_user_sees_only_own_security_events(client, alice, bob):
    mine = client.get("/api/audit/me", headers=alice.headers).json()
    assert mine and all(e["action"].startswith("auth.") for e in mine)
    bobs = bob.client.get("/api/audit/me", headers=bob.headers).json()
    assert {e["seq"] for e in mine}.isdisjoint({e["seq"] for e in bobs})


# ---------------------------------------------------------------- RBAC
def test_admin_endpoint_forbidden_for_customers(client, alice):
    """SEC-AUTHZ-02"""
    assert client.get("/api/admin/audit/verify", headers=alice.headers).status_code == 403
    assert client.get("/api/admin/audit/verify").status_code == 401


def test_admin_can_verify_audit_chain(client):
    admin = make_admin(client)
    r = client.get("/api/admin/audit/verify", headers=admin.headers)
    assert r.status_code == 200 and r.json()["valid"] is True


def test_role_cannot_be_self_assigned(client, alice):
    r = client.post("/api/auth/register", json={"email": "x@example.com", "password": "correct-horse-battery-9", "full_name": "Xavier", "role": "admin"})
    assert r.status_code == 422


# ---------------------------------------------------------------- log redaction
def test_log_redaction():
    assert "hunter2" not in redact('login password="hunter2" ok')
    assert "eyJhbGciOi" not in redact("Authorization: Bearer eyJhbGciOi.payload.sig")
    assert "4111111111111111" not in redact("card 4111111111111111 charged")
    assert "alice@example.com" not in redact("user alice@example.com failed")


def test_access_log_contains_no_secrets(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="vaultpay.access"):
        client.post("/api/auth/login?token=SECRETQUERY", json={"email": "a@example.com", "password": "SuperSecret-9999"})
    text_ = " ".join(r.getMessage() for r in caplog.records if r.name == "vaultpay.access")
    assert "/api/auth/login" in text_ and "SuperSecret" not in text_ and "SECRETQUERY" not in text_


def test_public_meta_exposes_only_non_sensitive_limits(client, settings):
    body = client.get("/api/meta").json()
    assert set(body) == {"step_up_threshold_cents", "max_transfer_cents", "demo_funding_enabled", "demo_funding_max_cents"}
