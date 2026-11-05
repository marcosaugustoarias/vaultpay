"""TOTP (RFC 6238) second factor.

SEC-AUTH-08: constant-time comparison, +-1 step clock-drift window, and replay
protection: a time-step that was already accepted can never be used again, so a
shoulder-surfed / phished code is worthless a second time.
"""

from __future__ import annotations

import hmac
import time

import pyotp

STEP_SECONDS = 30
ISSUER = "VaultPay"


def generate_secret() -> str:
    return pyotp.random_base32()  # 160 bits


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret, interval=STEP_SECONDS).provisioning_uri(name=email, issuer_name=ISSUER)


def current_code(secret: str, *, at: float | None = None) -> str:  # used by tests
    return pyotp.TOTP(secret, interval=STEP_SECONDS).at(at if at is not None else time.time())


def verify(secret: str, code: str, last_used_step: int | None, *, at: float | None = None) -> int | None:
    """Return the accepted time-step, or None. Caller must persist the step."""
    if not (len(code) == 6 and code.isdigit()):
        return None
    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    now_step = int((at if at is not None else time.time()) // STEP_SECONDS)
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            if last_used_step is not None and step <= last_used_step:
                return None  # replay
            return step
    return None
