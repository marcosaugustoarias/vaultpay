"""AccountNumber value object: 12 random digits, the last one a Luhn check digit.

Random (not sequential) so numbers cannot be enumerated; Luhn so a mistyped digit is
caught before any database lookup. The frontend mirrors the same rule in ``lib/money.ts``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from app.domain.errors import BusinessRuleViolation

LENGTH = 12


def luhn_check_digit(payload: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


@dataclass(frozen=True, slots=True)
class AccountNumber:
    value: str

    def __post_init__(self) -> None:
        if not self.is_valid(self.value):
            raise BusinessRuleViolation("invalid_account_number", "Invalid destination account number.")

    @staticmethod
    def is_valid(raw: str) -> bool:
        return (
            isinstance(raw, str)
            and len(raw) == LENGTH
            and raw.isascii()
            and raw.isdigit()
            and luhn_check_digit(raw[:-1]) == raw[-1]
        )

    @classmethod
    def generate(cls) -> AccountNumber:
        payload = "".join(str(secrets.randbelow(10)) for _ in range(LENGTH - 1))
        return cls(payload + luhn_check_digit(payload))

    def masked(self) -> str:
        return mask(self.value)

    def __str__(self) -> str:
        return self.value


def mask(raw: str) -> str:
    """Display form that never reveals a full account number (works on any string)."""
    return "••••" + raw[-4:]
