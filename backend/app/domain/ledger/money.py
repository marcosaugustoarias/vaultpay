"""Money value object: integer minor units + currency, immutable, compared by value."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import BusinessRuleViolation

SUPPORTED_CURRENCIES = frozenset({"USD"})


@dataclass(frozen=True, slots=True)
class Money:
    cents: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        # bool is a subclass of int: reject it explicitly so Money(True) is not "1 cent".
        if not isinstance(self.cents, int) or isinstance(self.cents, bool):
            raise BusinessRuleViolation("invalid_amount", "Amount must be an integer number of cents.")
        if self.currency not in SUPPORTED_CURRENCIES:
            raise BusinessRuleViolation("unsupported_currency", f"Unsupported currency: {self.currency}.")

    # ------------------------------------------------------------ factories
    @classmethod
    def positive(cls, cents: int, currency: str = "USD") -> Money:
        """An amount that can be moved: strictly greater than zero."""
        money = cls(cents, currency)
        if money.cents <= 0:
            raise BusinessRuleViolation("invalid_amount", "Amount must be greater than zero.")
        return money

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls(0, currency)

    # ----------------------------------------------------------- arithmetic
    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise BusinessRuleViolation("currency_mismatch", "Currency mismatch.")

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.cents < other.cents

    def __le__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.cents <= other.cents

    def __gt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.cents > other.cents

    def __ge__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.cents >= other.cents

    def __str__(self) -> str:
        sign = "-" if self.cents < 0 else ""
        whole, frac = divmod(abs(self.cents), 100)
        return f"{sign}{whole:,}.{frac:02d} {self.currency}"
