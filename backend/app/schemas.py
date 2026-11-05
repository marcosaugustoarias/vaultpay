"""Request/response contracts.

SEC-API-01: `extra="forbid"` (mass-assignment protection), strict types (a JSON
float is never silently coerced to an amount), bounded lengths, patterns.
Responses are explicit allow-lists: a model can never leak `password_hash`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictInt,
    field_validator,
)

from app.security.passwords import MAX_LENGTH

_UUIDISH = r"^[A-Za-z0-9\-]{16,64}$"
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _no_control_chars(value: str) -> str:
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("control characters are not allowed")
    return value


# ---------------------------------------------------------------- auth
class RegisterIn(StrictIn):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH + 1)]
    full_name: Annotated[str, Field(min_length=2, max_length=120)]
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _no_control_chars(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is not None and not _E164.match(v):
            raise ValueError("phone must be in E.164 format, e.g. +14155550123")
        return v


class LoginIn(StrictIn):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH + 1)]

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class MfaVerifyIn(StrictIn):
    mfa_token: Annotated[str, Field(min_length=10, max_length=2048)]
    code: Annotated[str, Field(pattern=r"^\d{6}$")]


class ChangePasswordIn(StrictIn):
    current_password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH + 1)]
    new_password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH + 1)]


class MfaCodeIn(StrictIn):
    code: Annotated[str, Field(pattern=r"^\d{6}$")]


class MfaDisableIn(MfaCodeIn):
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH + 1)]


class MessageOut(BaseModel):
    message: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int


class MfaChallengeOut(BaseModel):
    mfa_required: bool = True
    mfa_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    role: str
    mfa_enabled: bool
    created_at: datetime


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


# ------------------------------------------------------------ accounts
class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_number: str
    currency: str
    balance_cents: int


class LedgerEntryOut(BaseModel):
    id: int
    transaction_id: str
    kind: str
    direction: str
    amount_cents: int
    balance_after_cents: int
    description: str
    counterparty: str  # masked account number
    created_at: datetime


class LedgerPageOut(BaseModel):
    items: list[LedgerEntryOut]
    next_cursor: int | None


class FundIn(StrictIn):
    amount_cents: StrictInt = Field(gt=0, le=10_000_000)


# ------------------------------------------------------------ transfers
class TransferIn(StrictIn):
    from_account_id: Annotated[str, Field(min_length=36, max_length=36)]
    to_account_number: Annotated[str, Field(pattern=r"^\d{12}$")]
    amount_cents: StrictInt = Field(gt=0, le=10_000_000_00)
    description: Annotated[str, Field(max_length=140)] = ""
    otp_code: Annotated[str, Field(pattern=r"^\d{6}$")] | None = None

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str) -> str:
        return _no_control_chars(v)


class TransactionOut(BaseModel):
    id: str
    kind: str
    amount_cents: int
    currency: str
    description: str
    from_account: str  # masked
    to_account: str  # masked
    created_at: datetime


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    ts: datetime
    action: str
    outcome: str
    ip: str | None


class ChainReportOut(BaseModel):
    valid: bool
    checked: int
    first_broken_seq: int | None
    head_hash: str


IDEMPOTENCY_KEY_PATTERN = re.compile(_UUIDISH)
