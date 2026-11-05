"""Transfer specification: the invariants a transfer must satisfy *before* money moves.

The balance invariant ("a customer account never goes below zero") is deliberately NOT
checked here: it is enforced atomically by the conditional UPDATE in the application
layer plus a CHECK constraint in the database. Checking it in memory would be a race
under concurrency (see docs/DDD.md, "Agregado Account y concurrencia").
"""

from __future__ import annotations

from typing import Protocol

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger.money import Money


class AccountView(Protocol):
    """What the rule needs to know about an account (an ORM row satisfies it)."""

    id: str
    currency: str
    is_system: bool


def check_transfer(source: AccountView, dest: AccountView, amount: Money) -> None:
    if source.is_system or dest.is_system:
        # Customers can never move money to/from the treasury directly.
        raise BusinessRuleViolation("destination_not_found", "Destination account not found.")
    if source.id == dest.id:
        raise BusinessRuleViolation("same_account", "Source and destination must differ.")
    if source.currency != dest.currency or amount.currency != source.currency:
        raise BusinessRuleViolation("currency_mismatch", "Currency mismatch.")
