"""Field-level encryption for PII / secrets at rest (SEC-DATA-01).

* AES-256-GCM (authenticated encryption: tampering is detected on decrypt).
* Random 96-bit nonce per value.
* `purpose` is bound as AAD, so a ciphertext copied from `users.phone` into
  `users.totp_secret` fails to decrypt.
* Keyring with key ids -> rotation without downtime: encrypt with the current
  key, decrypt with whichever key the ciphertext names.

Wire format:  v1.<key_id>.<base64url(nonce || ciphertext||tag)>
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

_VERSION = "v1"


class DecryptionError(Exception):
    pass


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"kid:" + key).hexdigest()[:8]


def _load_key(b64: str) -> bytes:
    key = base64.b64decode(b64)
    if len(key) != 32:
        raise ValueError("Encryption keys must be exactly 32 bytes (AES-256)")
    return key


class Keyring:
    def __init__(self, current_b64: str, previous_b64: list[str]):
        current = _load_key(current_b64)
        self.current_id = _key_id(current)
        self._keys = {self.current_id: current}
        for p in previous_b64:
            k = _load_key(p)
            self._keys[_key_id(k)] = k

    def encrypt(self, plaintext: str, purpose: str) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self.current_id]).encrypt(
            nonce, plaintext.encode(), purpose.encode()
        )
        blob = base64.urlsafe_b64encode(nonce + ct).decode()
        return f"{_VERSION}.{self.current_id}.{blob}"

    def decrypt(self, token: str, purpose: str) -> str:
        try:
            version, kid, blob = token.split(".", 2)
            if version != _VERSION:
                raise DecryptionError("unsupported version")
            raw = base64.urlsafe_b64decode(blob)
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(self._keys[kid]).decrypt(nonce, ct, purpose.encode()).decode()
        except DecryptionError:
            raise
        except Exception as exc:  # bad key id, tampering, wrong purpose, truncated...
            raise DecryptionError("cannot decrypt value") from exc

    def needs_rotation(self, token: str) -> bool:
        return token.split(".", 2)[1] != self.current_id


@lru_cache
def get_keyring() -> Keyring:
    s = get_settings()
    return Keyring(s.encryption_key, s.encryption_keys_previous)


class EncryptedString(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts strings."""

    impl = Text
    cache_ok = True

    def __init__(self, purpose: str):
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value, dialect):
        return None if value is None else get_keyring().encrypt(value, self.purpose)

    def process_result_value(self, value, dialect):
        return None if value is None else get_keyring().decrypt(value, self.purpose)
