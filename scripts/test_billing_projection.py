import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import pytest

import app.dependencies as deps
import app.api.v1.billing as billing
from app.utils.entitlements import compute_tier

NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=10)).isoformat()
FUTURE_TS = int((NOW + timedelta(days=30)).timestamp())
PAST_TS = int((NOW - timedelta(days=30)).timestamp())


# ── Fake LocalStore (in-memory; no disk) ───────────────────────


class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data

    def get(self, field, default=None):
        if self._data is None:
            return default
        return self._data.get(field, default)


class _FakeDocRef:
    def __init__(self, store, doc_id):
        self._store = store
        self._id = doc_id

    def get(self):
        return _FakeSnapshot(self._id, self._store.get(self._id))

    def set(self, data, merge=False):
        if merge and self._id in self._store:
            self._store[self._id].update(data)
        else:
            self._store[self._id] = data

    def update(self, data):
        if self._id in self._store:
            self._store[self._id].update(data)


class _FakeCollectionRef:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id)


class _FakeDb:
    def __init__(self):
        self.users = {}

    def collection(self, name):
        assert name == "users"
        return _FakeCollectionRef(self.users)


# ── Fixtures / harness ─────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    """Hermetic harness: fake db_client, seeded _local_users, no PostHog,
    no real Stripe. Returns (db, seed) where seed(uid, cid, record)
    installs a user into both _local_users and the fake db."""
    db = _FakeDb()

    saved_users = dict(deps._local_users)
    saved_tokens_flag = deps._tokens_loaded
    saved_users_flag = deps._users_loaded
    deps._local_users.clear()
    # Block the disk loader from touching get_local_store().
    deps._tokens_loaded = True
    deps._users_loaded = True

    monkeypatch.setattr(billing, "ph_emit", lambda *a, **k: None)

    def seed(uid, cid, record):
        rec = dict(record)
        rec.setdefault("uid", uid)
        rec.setdefault("stripe_customer_id", cid)
        deps._local_users[uid] = dict(rec)
        db.users[uid] = dict(rec)
        return rec

    try:
        yield db, seed
    finally:
        deps._local_users.clear()
        deps._local_users.update(saved_users)
        deps._tokens_loaded = saved_tokens_flag
        deps._users_loaded = saved_users_flag


def _patch_stripe_charge(monkeypatch, customer_id):
    class _FakeCharge:
        @staticmethod
        def retrieve(charge_id):
            return {"customer": customer_id}

    class _FakeStripe:
        Charge = _FakeCharge

        class Customer:
            @staticmethod
            def retrieve(cid):
                return {}

    import app.services.stripe_client as sc
    monkeypatch.setattr(sc, "_get_client", lambda: _FakeStripe())


def _sub_event(etype, customer_id, sub_id, status, period_end_ts=None):
    return {
        "id": "evt_" + sub_id,
        "type": etype,
        "data": {
            "object": {
                "id": sub_id,
                "customer": customer_id,
                "status": status,
                "items": {"data": [{"current_period_end": period_end_ts}]},
            }
        },
    }


def _dispute_event(charge_id, dispute_id):
    return {
        "id": "evt_" + dispute_id,
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": dispute_id,
                "charge": charge_id,
                "reason": "fraudulent",
                "amount": 200,
                "currency": "usd",
                "status": "needs_response",
            }
        },
    }


# ── 1. created → premium ───────────────────────────────────────


def test_created_active_projects_premium(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "free"})
    billing._handle_sub_created(db, _sub_event(
        "customer.subscription.created", "cus_1", "sub_1", "active", FUTURE_TS))
    assert db.users["u1"]["subscription_tier"] == "premium"
    assert db.users["u1"]["subscription_status"] == "active"


# ── 2. dispute → free, status preserved ────────────────────────


def test_dispute_projects_free_preserves_status(env, monkeypatch):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "premium",
                         "subscription_status": "active"})
    _patch_stripe_charge(monkeypatch, "cus_1")
    billing._handle_charge_dispute(db, _dispute_event("ch_1", "dp_1"))
    assert db.users["u1"]["subscription_tier"] == "free"
    assert db.users["u1"]["subscription_status"] == "disputed"
    assert db.users["u1"].get("disputed_at")


# ── 3. comp holds premium through a stripe-free event ──────────


def test_comp_holds_premium_through_unpaid(env):
    db, seed = env
    seed("u1", "cus_1", {
        "subscription_tier": "premium",
        "subscription_status": "active",
        "entitlements": {"comp": {"status": "active", "expires": None}},
    })
    billing._handle_sub_updated(db, _sub_event(
        "customer.subscription.updated", "cus_1", "sub_1", "unpaid"))
    assert db.users["u1"]["subscription_status"] == "unpaid"
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_comp_holds_premium_through_dispute(env, monkeypatch):
    db, seed = env
    seed("u1", "cus_1", {
        "subscription_tier": "premium",
        "subscription_status": "active",
        "entitlements": {"comp": {"status": "active", "expires": None}},
    })
    _patch_stripe_charge(monkeypatch, "cus_1")
    billing._handle_charge_dispute(db, _dispute_event("ch_1", "dp_1"))
    assert db.users["u1"]["subscription_status"] == "disputed"
    assert db.users["u1"]["subscription_tier"] == "premium"


# ── 4. sub_updated status matrix ───────────────────────────────


def test_sub_updated_active_premium(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "free"})
    billing._handle_sub_updated(db, _sub_event(
        "customer.subscription.updated", "cus_1", "sub_1", "active", FUTURE_TS))
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_sub_updated_canceled_future_period_keeps_premium(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "premium",
                         "subscription_status": "active"})
    billing._handle_sub_updated(db, _sub_event(
        "customer.subscription.updated", "cus_1", "sub_1", "canceled", FUTURE_TS))
    assert db.users["u1"]["subscription_status"] == "canceled"
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_sub_updated_unpaid_projects_free(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "premium",
                         "subscription_status": "active"})
    billing._handle_sub_updated(db, _sub_event(
        "customer.subscription.updated", "cus_1", "sub_1", "unpaid"))
    assert db.users["u1"]["subscription_tier"] == "free"


# ── 5. invoice_paid → premium ──────────────────────────────────


def test_invoice_paid_projects_premium(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "free"})
    event = {
        "id": "evt_inv1",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": "in_1",
            "customer": "cus_1",
            "lines": {"data": [{"period": {"start": None, "end": FUTURE_TS},
                                "price": {"id": "price_1"}}]},
        }},
    }
    billing._handle_invoice_paid(db, event)
    assert db.users["u1"]["subscription_status"] == "active"
    assert db.users["u1"]["subscription_tier"] == "premium"


# ── 6. direct _apply_tier unit matrix ──────────────────────────


@pytest.mark.parametrize("status,period_end,expected", [
    ("active", None, "premium"),
    ("trialing", None, "premium"),
    ("past_due", None, "premium"),
    ("unpaid", FUTURE, "free"),
    ("incomplete", FUTURE, "free"),
    ("disputed", FUTURE, "free"),
    ("canceled", FUTURE, "premium"),
    ("canceled", PAST, "free"),
])
def test_apply_tier_matches_compute_tier(env, status, period_end, expected):
    db, seed = env
    rec = {"subscription_tier": "free", "subscription_status": status}
    if period_end is not None:
        rec["current_period_end"] = period_end
    seed("u1", "cus_1", rec)
    billing._apply_tier(db, "u1")
    assert db.users["u1"]["subscription_tier"] == expected
    assert db.users["u1"]["subscription_tier"] == compute_tier(db.users["u1"], NOW)


def test_apply_tier_persists_only_on_change(env, monkeypatch):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "premium",
                         "subscription_status": "active"})
    calls = []
    real = billing._persist_user_update

    def spy(db_client, uid, fields):
        calls.append((uid, dict(fields)))
        real(db_client, uid, fields)

    monkeypatch.setattr(billing, "_persist_user_update", spy)
    billing._apply_tier(db, "u1")  # already premium → no write
    assert calls == []
    db.users["u1"]["subscription_status"] = "unpaid"
    billing._apply_tier(db, "u1")  # premium → free → one write
    assert len(calls) == 1
    assert calls[0] == ("u1", {"subscription_tier": "free"})


def test_apply_tier_missing_user_noops(env):
    db, _ = env
    billing._apply_tier(db, "ghost")  # no doc → silent return
    assert "ghost" not in db.users


# ── 7. created with non-premium status → free (Decision-A delta) ───


def test_created_incomplete_projects_free(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "free"})
    billing._handle_sub_created(db, _sub_event(
        "customer.subscription.created", "cus_1", "sub_1", "incomplete", FUTURE_TS))
    assert db.users["u1"]["subscription_tier"] == "free"


# ── 8. Task-4 boundary: deleted/invoice_failed must NOT apply tier ─


def test_sub_deleted_does_not_apply_tier(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "premium", "subscription_status": "active"})
    # period end already PAST: projection would be free, but this handler must
    # leave tier untouched — the Task-4 sweep owns the past-period downgrade.
    billing._handle_sub_deleted(db, _sub_event(
        "customer.subscription.deleted", "cus_1", "sub_1", "canceled", PAST_TS))
    assert db.users["u1"]["subscription_tier"] == "premium"
    assert db.users["u1"]["subscription_status"] == "canceled"


def test_invoice_failed_does_not_apply_tier(env):
    db, seed = env
    seed("u1", "cus_1", {"subscription_tier": "free", "subscription_status": "active"})
    billing._handle_invoice_failed(db, {
        "data": {"object": {"id": "in_1", "customer": "cus_1", "attempt_count": 1, "amount_due": 100}}
    })
    assert db.users["u1"]["subscription_tier"] == "free"
    assert db.users["u1"]["subscription_status"] == "past_due"
