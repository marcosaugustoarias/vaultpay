"""Domain-level failures. They carry a stable ``code`` but know nothing about HTTP.

The application layer (``app.services.errors``) maps each code to a status code, so the
domain stays reusable from a CLI, a worker or a test without dragging transport concerns.
"""

from __future__ import annotations


class BusinessRuleViolation(Exception):
    """An invariant or policy of the domain was broken."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
