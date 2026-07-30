import asyncio
import threading

import pytest
from fastapi import HTTPException

from app.api.v1.subscriptions import SUBSCRIPTION_TIERS
from app.utils.credits import FREE_MONTHLY_CREDITS, PREMIUM_MONTHLY_CREDITS


def tier(tier_id):
    return next(item for item in SUBSCRIPTION_TIERS if item["id"] == tier_id)


def test_tier_metadata_matches_monthly_allocations():
    assert tier("free")["credits_per_period"] == FREE_MONTHLY_CREDITS == 3
    assert tier("free")["lifetime_free_credits"] is None
    assert tier("premium")["credits_per_period"] == PREMIUM_MONTHLY_CREDITS == 30


def test_credit_total_contract_counts_monthly_and_topups():
    from app.utils.credits import available_credit_total

    assert available_credit_total({
        "credits_remaining": 3,
        "topup_credits_remaining": 10,
    }) == 13


def test_authenticated_new_user_receives_credit_schema_backfill(monkeypatch):
    from app import dependencies

    class UserDocument:
        exists = True

        def __init__(self, user_data):
            self.user_data = user_data

        def get(self):
            return self

        def to_dict(self):
            return self.user_data

        def update(self, fields):
            self.user_data.update(fields)

    class UsersCollection:
        def __init__(self, user_data):
            self.user_data = user_data

        def document(self, uid):
            assert uid == "new-user"
            return UserDocument(self.user_data)

    class FakeDb:
        def __init__(self, user_data):
            self.user_data = user_data

        def collection(self, name):
            assert name == "users"
            return UsersCollection(self.user_data)

    user_data = {
        "uid": "new-user",
        "email": "new@example.com",
        "family_id": "family-1",
    }
    monkeypatch.setattr(dependencies, "_check_local_mode", lambda: True)
    monkeypatch.setattr(dependencies, "local_verify_token", lambda token: user_data)
    monkeypatch.setattr(dependencies, "get_db_client", lambda: FakeDb(user_data))
    monkeypatch.setattr(
        dependencies,
        "_ensure_family_id",
        lambda db, uid, data: data["family_id"],
    )
    monkeypatch.setattr(dependencies, "_ensure_subscription_fields", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_email_field", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_username_lowercase", lambda *args: None)
    monkeypatch.setattr(dependencies, "_ensure_onboarding_complete", lambda *args: None)

    asyncio.run(dependencies.get_current_user(authorization="Bearer token"))

    assert user_data["credits_remaining"] == FREE_MONTHLY_CREDITS
    assert user_data["topup_credits_remaining"] == 0
    assert user_data["credits_reserved"] == 0
    assert user_data["credits_period_start"] is None
    assert user_data["credits_period_end"] is None


class StoredSnapshot:
    exists = True

    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return dict(self.data)


class StoredDocument:
    def __init__(self, store, uid):
        self.store = store
        self.uid = uid

    def get(self):
        return StoredSnapshot(self.store[self.uid])

    def update(self, fields):
        self.store[self.uid].update(fields)


class StoredCollection:
    def __init__(self, store):
        self.store = store

    def document(self, uid):
        return StoredDocument(self.store, uid)


class StoredDb:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()

    def collection(self, name):
        assert name == "users"
        return StoredCollection(self.store)


def test_current_subscription_surfaces_reserved_and_spendable_credits(monkeypatch):
    from app.api.v1 import subscriptions

    user_data = {
        "uid": "u1",
        "subscription_tier": "free",
        "credits_remaining": 3,
        "topup_credits_remaining": 4,
        "credits_reserved": 2,
    }
    monkeypatch.setattr(
        subscriptions,
        "refresh_credit_period",
        lambda db, uid, data: data,
    )

    response = asyncio.run(subscriptions.get_current_subscription(
        current_user={"uid": "u1"},
        db_client=StoredDb({"u1": user_data}),
    ))

    assert response.data["credits_reserved"] == 2
    assert response.data["credits_total"] == 5


class BlockingDocument(StoredDocument):
    def __init__(self, store, uid, snapshot_taken, release_snapshot):
        super().__init__(store, uid)
        self.snapshot_taken = snapshot_taken
        self.release_snapshot = release_snapshot

    def get(self):
        snapshot = StoredSnapshot(dict(self.store[self.uid]))
        self.snapshot_taken.set()
        assert self.release_snapshot.wait(timeout=2)
        return snapshot


class BlockingCollection(StoredCollection):
    def __init__(self, store, snapshot_taken, release_snapshot):
        super().__init__(store)
        self.snapshot_taken = snapshot_taken
        self.release_snapshot = release_snapshot

    def document(self, uid):
        return BlockingDocument(
            self.store,
            uid,
            self.snapshot_taken,
            self.release_snapshot,
        )


class BlockingDb(StoredDb):
    def __init__(self, store):
        super().__init__(store)
        self.snapshot_taken = threading.Event()
        self.release_snapshot = threading.Event()

    def collection(self, name):
        assert name == "users"
        return BlockingCollection(
            self.store,
            self.snapshot_taken,
            self.release_snapshot,
        )


def renewal_event(
    invoice_id="in_renewal",
    billing_reason="subscription_cycle",
    period_start=1785283200,
    period_end=1787961600,
):
    return {
        "data": {
            "object": {
                "id": invoice_id,
                "customer": "cus_1",
                "subscription": "sub_1",
                "billing_reason": billing_reason,
                "lines": {
                    "data": [{
                        "period": {
                            "start": period_start,
                            "end": period_end,
                        },
                        "price": {"id": "price_monthly"},
                    }],
                },
            },
        },
    }


def billing_store():
    return {"u1": {
        "uid": "u1",
        "family_id": "family-1",
        "stripe_customer_id": "cus_1",
        "subscription_tier": "premium",
        "subscription_status": "active",
        "credits_remaining": 8,
        "topup_credits_remaining": 7,
        "credits_period_start": "2026-07-01T00:00:00+00:00",
        "credits_period_end": "2026-07-29T00:00:00+00:00",
    }}


def install_billing_fakes(monkeypatch, store):
    from app.api.v1 import billing

    monkeypatch.setattr(
        billing,
        "_find_user_by_customer",
        lambda db, customer: {**store["u1"], "uid": "u1"},
    )
    monkeypatch.setattr(billing, "ph_emit", lambda *args, **kwargs: None)
    return billing


def test_duplicate_renewal_invoice_does_not_restore_spent_credits(monkeypatch):
    store = billing_store()
    billing = install_billing_fakes(monkeypatch, store)
    db = StoredDb(store)
    event = renewal_event()

    billing._handle_invoice_paid(db, event)
    assert store["u1"]["credits_remaining"] == 30
    assert store["u1"]["topup_credits_remaining"] == 7
    assert store["u1"]["credits_last_applied_invoice_id"] == "in_renewal"

    store["u1"]["credits_remaining"] = 11
    billing._handle_invoice_paid(db, event)

    assert store["u1"]["credits_remaining"] == 11
    assert store["u1"]["topup_credits_remaining"] == 7


def test_non_cycle_invoice_does_not_grant_monthly_credits(monkeypatch):
    store = billing_store()
    billing = install_billing_fakes(monkeypatch, store)

    billing._handle_invoice_paid(
        StoredDb(store),
        renewal_event(invoice_id="in_update", billing_reason="subscription_update"),
    )

    assert store["u1"]["credits_remaining"] == 8
    assert "credits_last_applied_invoice_id" not in store["u1"]


def test_non_advancing_cycle_invoice_does_not_grant_monthly_credits(monkeypatch):
    store = billing_store()
    store["u1"]["credits_period_end"] = "2026-08-29T00:00:00+00:00"
    billing = install_billing_fakes(monkeypatch, store)

    billing._handle_invoice_paid(
        StoredDb(store),
        renewal_event(invoice_id="in_same_period"),
    )

    assert store["u1"]["credits_remaining"] == 8
    assert "credits_last_applied_invoice_id" not in store["u1"]


def test_renewal_upgrade_wins_over_stale_free_refresh(monkeypatch):
    from datetime import datetime, timezone
    from app.utils.credits import refresh_credit_period

    store = billing_store()
    store["u1"].update({
        "subscription_tier": "free",
        "credits_remaining": 1,
        "credits_period_end": "2026-07-01T00:00:00+00:00",
    })
    stale_free = dict(store["u1"])
    billing = install_billing_fakes(monkeypatch, store)
    db = StoredDb(store)

    billing._handle_invoice_paid(db, renewal_event())
    refreshed = refresh_credit_period(
        db,
        "u1",
        stale_free,
        datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc),
    )

    assert refreshed["subscription_tier"] == "premium"
    assert refreshed["credits_remaining"] == 30
    assert refreshed["topup_credits_remaining"] == 7


def test_subscription_grant_serializes_with_in_progress_free_refresh():
    from datetime import datetime, timezone
    from app.api.v1.billing import _persist_user_update
    from app.utils.credits import refresh_credit_period

    store = billing_store()
    store["u1"].update({
        "subscription_tier": "free",
        "credits_remaining": 1,
        "credits_period_end": "2026-07-01T00:00:00+00:00",
    })
    db = BlockingDb(store)
    errors = []
    grant_started = threading.Event()
    grant_finished = threading.Event()

    def refresh():
        try:
            refresh_credit_period(
                db,
                "u1",
                dict(store["u1"]),
                datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc),
            )
        except Exception as exc:
            errors.append(exc)

    def grant():
        grant_started.set()
        _persist_user_update(db, "u1", {
            "subscription_tier": "premium",
            "credits_remaining": 30,
            "credits_period_start": "2026-07-29T00:00:00+00:00",
            "credits_period_end": "2026-08-29T00:00:00+00:00",
        })
        grant_finished.set()

    refresh_thread = threading.Thread(target=refresh)
    refresh_thread.start()
    assert db.snapshot_taken.wait(timeout=2)
    grant_thread = threading.Thread(target=grant)
    grant_thread.start()
    assert grant_started.wait(timeout=2)
    grant_finished.wait(timeout=0.2)
    db.release_snapshot.set()
    refresh_thread.join(timeout=2)
    grant_thread.join(timeout=2)

    assert not refresh_thread.is_alive()
    assert not grant_thread.is_alive()
    assert not errors
    assert store["u1"]["subscription_tier"] == "premium"
    assert store["u1"]["credits_remaining"] == 30


def test_invoice_paid_event_uses_the_renewal_handler():
    from app.api.v1.billing import _HANDLERS, _handle_invoice_paid

    assert _HANDLERS["invoice.paid"] is _handle_invoice_paid


def test_subscription_refresh_failure_returns_generic_detail(monkeypatch):
    from app.api.v1 import subscriptions

    store = {
        "private-user": {
            "uid": "private-user",
            "subscription_tier": "free",
        },
    }
    monkeypatch.setattr(
        subscriptions,
        "refresh_credit_period",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("credit refresh failed for uid=private-user")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(subscriptions.get_current_subscription(
            current_user={"uid": "private-user"},
            db_client=StoredDb(store),
        ))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get subscription"
    assert "private-user" not in exc_info.value.detail
