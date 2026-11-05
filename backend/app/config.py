"""Application settings (12-factor: everything comes from the environment).

SEC-CFG-01: in production the app refuses to start with insecure defaults
(weak/default secrets, insecure cookies, wildcard CORS, public docs, demo funding).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Development-only defaults. They are *deliberately* recognisable so that the
# production validator below can reject them.
# Public development sentinel, rejected in production by the validator below.
_DEV_JWT_SECRET = "dev-only-jwt-secret-do-not-use-in-production-0123456789"  # noqa: S105  # nosec B105
_DEV_ENCRYPTION_KEY = base64.b64encode(b"dev-only-32-byte-key-for-aes-256").decode()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VAULTPAY_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./vaultpay.db"

    # --- Tokens -----------------------------------------------------------
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_issuer: str = "vaultpay"
    jwt_audience: str = "vaultpay-api"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 3600
    mfa_token_ttl_seconds: int = 5 * 60

    # --- Field-level encryption (AES-256-GCM, base64 of 32 bytes) ----------
    encryption_key: str = _DEV_ENCRYPTION_KEY
    # Old keys kept only to decrypt data written before a rotation.
    encryption_keys_previous: list[str] = []

    # --- HTTP surface -------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cookie_secure: bool = False
    docs_enabled: bool = True
    max_body_bytes: int = 64 * 1024
    trusted_proxy_count: int = 0  # how many reverse proxies we trust for X-Forwarded-For

    # --- Brute force / rate limiting -----------------------------------------
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    rate_limit_enabled: bool = True
    rate_limit_login_per_minute: int = 10
    rate_limit_register_per_hour: int = 5
    rate_limit_transfer_per_minute: int = 20

    # --- Risk limits (minor units = cents) ---------------------------------------
    step_up_threshold_cents: int = 50_000  # >= $500 requires a fresh TOTP code
    max_transfer_cents: int = 1_000_000  # $10,000 per transfer
    daily_outbound_limit_cents: int = 2_000_000  # $20,000 per rolling 24h
    max_transfers_per_hour: int = 10

    # Sandbox only: lets a demo user credit their own account from the treasury.
    demo_funding_enabled: bool = True
    demo_funding_max_cents: int = 100_000

    @model_validator(mode="after")
    def _production_guardrails(self) -> Settings:
        if self.env != "production":
            return self
        problems: list[str] = []
        if self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret.encode()) < 32:
            problems.append("VAULTPAY_JWT_SECRET must be a unique secret of >= 32 bytes")
        if self.encryption_key == _DEV_ENCRYPTION_KEY:
            problems.append("VAULTPAY_ENCRYPTION_KEY must not be the development key")
        if not self.cookie_secure:
            problems.append("VAULTPAY_COOKIE_SECURE must be true")
        if "*" in self.cors_origins or any(o.startswith("http://") for o in self.cors_origins):
            problems.append("VAULTPAY_CORS_ORIGINS must be explicit https origins")
        if "*" in self.allowed_hosts:
            problems.append("VAULTPAY_ALLOWED_HOSTS must not contain '*'")
        if self.docs_enabled:
            problems.append("VAULTPAY_DOCS_ENABLED must be false")
        if self.demo_funding_enabled:
            problems.append("VAULTPAY_DEMO_FUNDING_ENABLED must be false")
        if self.database_url.startswith("sqlite"):
            problems.append("SQLite is not allowed in production")
        if problems:
            raise ValueError("Insecure production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
