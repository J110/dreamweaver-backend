import pytest

from app.utils.credits import (
    available_credit_total,
    debit_reserved_credit_fields,
    release_credit_fields,
    reserve_credit_fields,
)


def test_reserved_credits_are_not_available():
    user = {"credits_remaining": 3, "topup_credits_remaining": 4, "credits_reserved": 0}
    user.update(reserve_credit_fields(user, 2))
    assert user["credits_reserved"] == 2
    assert available_credit_total(user) == 5


def test_success_debits_monthly_first_and_releases_reservation():
    user = {"credits_remaining": 1, "topup_credits_remaining": 4, "credits_reserved": 2}
    user.update(debit_reserved_credit_fields(user, 2))
    assert user == {
        "credits_remaining": 0,
        "topup_credits_remaining": 3,
        "credits_reserved": 0,
    }


def test_failure_only_releases_reservation():
    user = {"credits_remaining": 3, "topup_credits_remaining": 4, "credits_reserved": 2}
    user.update(release_credit_fields(user, 2))
    assert user["credits_remaining"] == 3
    assert user["topup_credits_remaining"] == 4
    assert user["credits_reserved"] == 0


def test_debit_without_reservation_does_not_charge_credits():
    user = {"credits_remaining": 3, "topup_credits_remaining": 4, "credits_reserved": 0}

    with pytest.raises(ValueError, match="reserved_credit_missing"):
        debit_reserved_credit_fields(user, 2)

    assert user == {
        "credits_remaining": 3,
        "topup_credits_remaining": 4,
        "credits_reserved": 0,
    }


def test_replayed_debit_does_not_charge_credits_twice():
    user = {"credits_remaining": 1, "topup_credits_remaining": 4, "credits_reserved": 2}
    user.update(debit_reserved_credit_fields(user, 2))

    with pytest.raises(ValueError, match="reserved_credit_missing"):
        debit_reserved_credit_fields(user, 2)

    assert user == {
        "credits_remaining": 0,
        "topup_credits_remaining": 3,
        "credits_reserved": 0,
    }
