from __future__ import annotations

from app.domain.errors import BusinessRuleViolation

# Anti-corruption mapping: domain rule codes -> HTTP status. The domain never sees HTTP.
RULE_STATUS: dict[str, int] = {
    "invalid_amount": 422,
    "unsupported_currency": 422,
    "currency_mismatch": 422,
    "invalid_account_number": 422,
    "destination_not_found": 404,
    "same_account": 422,
    "limit_exceeded": 422,
    "daily_limit_exceeded": 422,
    "velocity_exceeded": 429,
}


class DomainError(Exception):
    """A business-rule failure that maps to a safe, user-facing HTTP error."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    @classmethod
    def from_violation(cls, violation: BusinessRuleViolation) -> DomainError:
        return cls(RULE_STATUS.get(violation.code, 422), violation.code, violation.message)
