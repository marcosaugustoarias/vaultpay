from __future__ import annotations


class DomainError(Exception):
    """A business-rule failure that maps to a safe, user-facing HTTP error."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
