"""Unit tests: AccountNumber value object."""

import pytest

from app.domain.errors import BusinessRuleViolation
from app.domain.ledger import AccountNumber
from app.domain.ledger.account_number import luhn_check_digit


def test_generated_numbers_are_valid_and_random():
    numbers = {AccountNumber.generate().value for _ in range(200)}
    assert len(numbers) == 200
    assert all(AccountNumber.is_valid(n) for n in numbers)


def test_known_luhn_vector():
    # 7992739871 -> check digit 3 is the classic Luhn example.
    assert luhn_check_digit("7992739871") == "3"


def test_single_digit_typo_is_detected():
    good = AccountNumber.generate().value
    last = int(good[-1])
    typo = good[:-1] + str((last + 1) % 10)
    assert not AccountNumber.is_valid(typo)
    with pytest.raises(BusinessRuleViolation) as exc:
        AccountNumber(typo)
    assert exc.value.code == "invalid_account_number"


@pytest.mark.parametrize("raw", ["", "123", "1234567890123", "12345678901a", "１２３４５６７８９０１２"])
def test_rejects_wrong_shape(raw):
    assert not AccountNumber.is_valid(raw)


def test_masked_never_reveals_full_number():
    n = AccountNumber.generate()
    assert n.masked() == "••••" + n.value[-4:]
    assert n.value[:8] not in n.masked()
