"""Unit tests: Money value object (pure domain, no DB, no HTTP)."""

import pytest

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger import Money


def test_equal_by_value_and_immutable():
    assert Money(1050) == Money(1050, "USD")
    with pytest.raises(AttributeError):
        Money(1).cents = 2  # type: ignore[misc]


def test_positive_rejects_zero_and_negative():
    for cents in (0, -1):
        with pytest.raises(BusinessRuleViolation) as exc:
            Money.positive(cents)
        assert exc.value.code == "invalid_amount"


@pytest.mark.parametrize("bad", [1.5, "100", True, None])
def test_rejects_non_integer_amounts(bad):
    with pytest.raises(BusinessRuleViolation) as exc:
        Money(bad)  # type: ignore[arg-type]
    assert exc.value.code == "invalid_amount"


def test_rejects_unsupported_currency():
    with pytest.raises(BusinessRuleViolation) as exc:
        Money(100, "EUR")
    assert exc.value.code == "unsupported_currency"


def test_arithmetic_and_comparison():
    assert Money(700) + Money(300) == Money(1000)
    assert Money(700) - Money(1000) == Money(-300)
    assert Money(1) < Money(2) <= Money(2)
    assert Money(3) > Money(2) >= Money(2)
    assert Money.zero() == Money(0)


def test_str_formats_minor_units():
    assert str(Money(123456)) == "1,234.56 USD"
    assert str(Money(-5)) == "-0.05 USD"
