"""Password hashing and policy.

SEC-AUTH-01: Argon2id (memory-hard, OWASP/RFC 9106 parameters), transparent
re-hash on login when parameters are upgraded.
SEC-AUTH-02: policy follows NIST SP 800-63B: length over composition rules,
block-list of common passwords, no context-specific words. No forced rotation.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

if get_settings().env == "test":
    # Cheaper parameters only to keep the test-suite fast.
    _ph = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1)
else:
    _ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)  # RFC 9106 low-mem

MIN_LENGTH = 12
MAX_LENGTH = 128  # cap to avoid hashing-DoS with huge inputs

_COMMON = {
    "password", "password1", "password123", "123456789012", "qwertyuiop12", "letmein12345",
    "iloveyou1234", "administrator", "welcome12345", "changeme1234", "passw0rd1234",
    "1234567890123", "qwerty123456", "abc123456789", "monkey123456", "dragon123456",
    "football1234", "baseball1234", "trustno1trustno1", "000000000000", "111111111111",
    "aaaaaaaaaaaa", "vaultpay1234", "vaultpassword", "correcthorsebatterystaple",
}

# Hash used to burn equivalent CPU time when the user does not exist (SEC-AUTH-04).
_DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    """Constant-effort verification against a dummy hash."""
    verify_password(password, _DUMMY_HASH)


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def validate_password_policy(password: str, *, email: str = "", full_name: str = "") -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        errors.append(f"must be at most {MAX_LENGTH} characters")
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) <= 2:
        errors.append("is too common or too repetitive")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        errors.append("must not contain your email name")
    for part in full_name.lower().split():
        if len(part) >= 4 and part in lowered:
            errors.append("must not contain your name")
            break
    return errors
