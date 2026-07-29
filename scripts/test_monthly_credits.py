from datetime import datetime, timezone

import pytest

from app.utils.credits import (
    CreditRefreshError,
    available_credit_total,
    refresh_credit_period,
)


class FakeDocument:
    def __init__(self, store, uid, fail=False):
        self.store = store
        self.uid = uid
        self.fail = fail

    def update(self, fields):
        if self.fail:
            raise RuntimeError("write failed")
        self.store[self.uid].update(fields)

    def get(self):
        return FakeSnapshot(self.store[self.uid])


class FakeSnapshot:
    exists = True

    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return dict(self.data)


class FakeCollection:
    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail

    def document(self, uid):
        return FakeDocument(self.store, uid, self.fail)


class FakeDb:
    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail

    def collection(self, name):
        assert name == "users"
        return FakeCollection(self.store, self.fail)


NOW = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)


def test_free_user_migrates_to_three_credit_calendar_period():
    users = {"u1": {"subscription_tier": "free", "lifetime_free_remaining": 1}}
    refreshed = refresh_credit_period(FakeDb(users), "u1", users["u1"], NOW)
    assert refreshed["credits_remaining"] == 3
    assert refreshed["lifetime_free_remaining"] == 0
    assert refreshed["credits_period_start"] == "2026-07-01T00:00:00+00:00"
    assert refreshed["credits_period_end"] == "2026-08-01T00:00:00+00:00"


def test_free_user_does_not_refresh_inside_current_period():
    users = {"u1": {
        "subscription_tier": "free",
        "credits_remaining": 1,
        "credits_period_start": "2026-07-01T00:00:00+00:00",
        "credits_period_end": "2026-08-01T00:00:00+00:00",
    }}
    refreshed = refresh_credit_period(FakeDb(users), "u1", users["u1"], NOW)
    assert refreshed["credits_remaining"] == 1


def test_free_user_resets_without_rollover_and_preserves_topups():
    users = {"u1": {
        "subscription_tier": "free",
        "credits_remaining": 2,
        "topup_credits_remaining": 7,
        "credits_period_end": "2026-07-01T00:00:00+00:00",
    }}
    refreshed = refresh_credit_period(FakeDb(users), "u1", users["u1"], NOW)
    assert refreshed["credits_remaining"] == 3
    assert refreshed["topup_credits_remaining"] == 7
    assert available_credit_total(refreshed) == 10


def test_premium_period_is_owned_by_stripe():
    users = {"u1": {
        "subscription_tier": "premium",
        "credits_remaining": 4,
        "credits_period_end": "2026-07-01T00:00:00+00:00",
    }}
    refreshed = refresh_credit_period(FakeDb(users), "u1", users["u1"], NOW)
    assert refreshed["credits_remaining"] == 4


def test_free_refresh_re_reads_current_premium_tier_before_reset():
    stale_free_snapshot = {
        "subscription_tier": "free",
        "credits_remaining": 1,
        "credits_period_end": "2026-07-01T00:00:00+00:00",
    }
    users = {"u1": {
        "subscription_tier": "premium",
        "credits_remaining": 30,
        "credits_period_start": "2026-07-29T00:00:00+00:00",
        "credits_period_end": "2026-08-29T00:00:00+00:00",
    }}

    refreshed = refresh_credit_period(
        FakeDb(users),
        "u1",
        stale_free_snapshot,
        NOW,
    )

    assert refreshed["subscription_tier"] == "premium"
    assert refreshed["credits_remaining"] == 30
    assert users["u1"]["credits_remaining"] == 30


def test_premium_renewal_fields_reset_monthly_pool_without_touching_topups():
    from app.utils.credits import premium_period_credit_fields
    fields = premium_period_credit_fields(
        "2026-07-10T00:00:00+00:00",
        "2026-08-10T00:00:00+00:00",
    )
    assert fields == {
        "credits_remaining": 30,
        "credits_period_start": "2026-07-10T00:00:00+00:00",
        "credits_period_end": "2026-08-10T00:00:00+00:00",
        "credits_frozen": False,
    }
    assert "topup_credits_remaining" not in fields


def test_frozen_credits_are_not_spendable():
    assert available_credit_total({
        "credits_remaining": 8,
        "topup_credits_remaining": 2,
        "credits_frozen": True,
    }) == 0


def test_refresh_write_failure_does_not_return_invented_balance():
    users = {"u1": {"subscription_tier": "free"}}
    with pytest.raises(CreditRefreshError):
        refresh_credit_period(FakeDb(users, fail=True), "u1", users["u1"], NOW)
