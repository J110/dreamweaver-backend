import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import pytest

import app.dependencies as deps
import app.api.v1.billing as billing


NOW = datetime.now(timezone.utc)
FUTURE_MS = int((NOW + timedelta(days=30)).timestamp() * 1000)
SECRET = "rc_test_secret"


# ── A1: the idempotency table dedups on event_id ───────────────


def test_revenuecat_events_table_dedups(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr("app.api.v1.billing.BILLING_DB_PATH", Path(tmp_path) / "billing.db")
    from app.api.v1.billing import _open_billing_db
    conn = _open_billing_db()
    ins = ("INSERT OR IGNORE INTO revenuecat_webhook_events (event_id, event_type, received_at, status) VALUES (?,?,?,?)",
           ("evt_1", "INITIAL_PURCHASE", "2026-06-25T00:00:00Z", "received"))
    conn.execute(*ins); first = conn.total_changes
    conn.execute(*ins); second = conn.total_changes
    assert first == 1 and second == 1   # duplicate event_id ignored (idempotent)
    rows = conn.execute("SELECT COUNT(*) FROM revenuecat_webhook_events").fetchone()[0]
    assert rows == 1   # exactly one row survives the duplicate — A3's webhook relies on this


# ── Fake LocalStore (in-memory; no disk) — mirrors test_billing_projection ──


class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


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


# ── Harness ────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Hermetic harness: fake db_client wired into the endpoint via the
    FastAPI dependency override, seeded _local_users, isolated billing.db,
    REVENUECAT_WEBHOOK_SECRET set, no PostHog. Returns (client, db, seed)."""
    from pathlib import Path
    monkeypatch.setattr(billing, "BILLING_DB_PATH", Path(tmp_path) / "billing.db")
    monkeypatch.setenv("REVENUECAT_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(billing, "ph_emit", lambda *a, **k: None)

    db = _FakeDb()

    saved_users = dict(deps._local_users)
    saved_tokens_flag = deps._tokens_loaded
    saved_users_flag = deps._users_loaded
    deps._local_users.clear()
    deps._tokens_loaded = True
    deps._users_loaded = True

    from app.main import app
    from app.dependencies import get_db_client
    app.dependency_overrides[get_db_client] = lambda: db

    from fastapi.testclient import TestClient
    client = TestClient(app)

    def seed(uid, record):
        rec = dict(record)
        rec.setdefault("uid", uid)
        deps._local_users[uid] = dict(rec)
        db.users[uid] = dict(rec)
        return rec

    try:
        yield client, db, seed
    finally:
        app.dependency_overrides.pop(get_db_client, None)
        deps._local_users.clear()
        deps._local_users.update(saved_users)
        deps._tokens_loaded = saved_tokens_flag
        deps._users_loaded = saved_users_flag


def _event(etype, app_user_id, store="APP_STORE", expiration_at_ms=FUTURE_MS,
           period_type="NORMAL", grace=None, env_name="PRODUCTION",
           product_id="dv_monthly", event_id="evt_rc_1"):
    return {
        "event": {
            "id": event_id,
            "type": etype,
            "app_user_id": app_user_id,
            "store": store,
            "period_type": period_type,
            "expiration_at_ms": expiration_at_ms,
            "grace_period_expiration_at_ms": grace,
            "product_id": product_id,
            "environment": env_name,
        }
    }


def _post(client, body, auth=SECRET):
    headers = {} if auth is None else {"Authorization": auth}
    return client.post("/api/v1/billing/revenuecat/webhook", json=body, headers=headers)


# ── 1. AUTH boundary — forged/missing webhook must NOT write ───


def test_missing_authorization_rejected_401_no_write(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("INITIAL_PURCHASE", "u1"), auth=None)
    assert r.status_code == 401
    assert "entitlements" not in db.users["u1"]
    assert db.users["u1"]["subscription_tier"] == "free"


def test_wrong_authorization_rejected_401_no_write(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("INITIAL_PURCHASE", "u1"), auth="wrong_secret")
    assert r.status_code == 401
    assert "entitlements" not in db.users["u1"]
    assert db.users["u1"]["subscription_tier"] == "free"


def test_unset_secret_env_rejects_even_with_header(env, monkeypatch):
    client, db, seed = env
    monkeypatch.delenv("REVENUECAT_WEBHOOK_SECRET", raising=False)
    seed("u1", {"subscription_tier": "free"})
    # Empty/correct-looking header must still 401 when the server secret is unset.
    r = _post(client, _event("INITIAL_PURCHASE", "u1"), auth="")
    assert r.status_code == 401
    assert "entitlements" not in db.users["u1"]


# ── 2. Idempotency — same event.id processed once ──────────────


def test_duplicate_event_id_processed_once(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    body = _event("INITIAL_PURCHASE", "u1", event_id="evt_dup")
    r1 = _post(client, body)
    written_at = db.users["u1"]["entitlements"]["apple"]["updated_at"]
    # Mutate the stored source; a re-processed duplicate would overwrite it.
    db.users["u1"]["entitlements"]["apple"]["status"] = "sentinel"
    r2 = _post(client, body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json().get("deduped") is True          # second POST short-circuited
    assert db.users["u1"]["entitlements"]["apple"]["status"] == "sentinel"  # not rewritten
    assert db.users["u1"]["entitlements"]["apple"]["updated_at"] == written_at
    assert db.users["u1"]["subscription_tier"] == "premium"


# ── 3. Unknown uid — must NOT 500/crash; ack + skip ────────────


def test_unknown_uid_acked_no_write_no_crash(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("INITIAL_PURCHASE", "ghost"))
    assert r.status_code == 200
    assert "ghost" not in db.users
    assert "entitlements" not in db.users["u1"]


def test_missing_app_user_id_acked_no_crash(env):
    client, db, seed = env
    body = _event("INITIAL_PURCHASE", "u1")
    del body["event"]["app_user_id"]
    r = _post(client, body)
    assert r.status_code == 200


# ── 4. Malformed body / ignorable event ────────────────────────


def test_missing_event_key_400(env):
    client, db, seed = env
    r = _post(client, {"not_event": {}})
    assert r.status_code == 400


def test_test_event_acked_no_write(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("TEST", "u1"))
    assert r.status_code == 200
    assert "entitlements" not in db.users["u1"]
    assert db.users["u1"]["subscription_tier"] == "free"


def test_transfer_moves_native_entitlement_to_destination_user(env):
    client, db, seed = env
    seed("old-user", {
        "subscription_tier": "premium",
        "entitlements": {
            "apple": {
                "status": "trialing",
                "expires": "2099-01-01T00:00:00+00:00",
                "store": "apple",
                "product_id": "dv_monthly",
            },
            "comp": {"status": "active", "expires": None},
        },
    })
    seed("new-user", {"subscription_tier": "free"})
    body = {
        "event": {
            "id": "evt_transfer",
            "type": "TRANSFER",
            "transferred_from": ["$RCAnonymousID:old", "old-user"],
            "transferred_to": ["$RCAnonymousID:new", "new-user"],
            "store": "APP_STORE",
            "environment": "SANDBOX",
        }
    }

    r = _post(client, body)

    assert r.status_code == 200
    assert db.users["new-user"]["entitlements"]["apple"]["status"] == "trialing"
    assert db.users["new-user"]["subscription_tier"] == "premium"
    assert db.users["new-user"]["credits_remaining"] == 30
    assert "apple" not in db.users["old-user"]["entitlements"]
    assert db.users["old-user"]["entitlements"]["comp"]["status"] == "active"


# ── 5. Full round-trip — write + projection + sibling preservation ──


def test_initial_purchase_apple_writes_source_and_projects_premium(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("INITIAL_PURCHASE", "u1", store="APP_STORE"))
    assert r.status_code == 200
    ent = db.users["u1"]["entitlements"]["apple"]
    assert ent["status"] == "active"
    assert ent["store"] == "apple"
    assert ent["product_id"] == "dv_monthly"
    assert ent["environment"] == "PRODUCTION"
    assert ent.get("updated_at")
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_play_store_event_writes_google_source(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    r = _post(client, _event("INITIAL_PURCHASE", "u1", store="PLAY_STORE"))
    assert r.status_code == 200
    assert db.users["u1"]["entitlements"]["google"]["status"] == "active"
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_apple_write_does_not_clobber_comp_or_google_sibling(env):
    client, db, seed = env
    seed("u1", {
        "subscription_tier": "premium",
        "entitlements": {
            "comp": {"status": "active", "expires": None},
            "google": {"status": "active", "expires": "2099-01-01T00:00:00+00:00", "store": "google"},
        },
    })
    r = _post(client, _event("INITIAL_PURCHASE", "u1", store="APP_STORE"))
    assert r.status_code == 200
    ent = db.users["u1"]["entitlements"]
    assert ent["apple"]["status"] == "active"      # new source written
    assert ent["comp"] == {"status": "active", "expires": None}        # sibling survives
    assert ent["google"]["expires"] == "2099-01-01T00:00:00+00:00"     # sibling survives
    assert db.users["u1"]["subscription_tier"] == "premium"


# ── 6. Retry + lifecycle close (review follow-ups) ─────────────


def test_failed_event_is_retried_not_dedup_skipped(env, monkeypatch):
    client, db, seed = env
    seed("u1", {"subscription_tier": "free"})
    import app.api.v1.revenuecat as rc
    real_apply = rc._apply_tier
    calls = {"n": 0}
    def flaky(db_client, uid, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_apply(db_client, uid, now)
    monkeypatch.setattr(rc, "_apply_tier", flaky)
    body = _event("INITIAL_PURCHASE", "u1", event_id="evt_retry")
    r1 = _post(client, body)
    assert r1.status_code == 500                      # handler failed -> 500 (RevenueCat retries)
    r2 = _post(client, body)                          # same event_id, status='failed' -> NOT dedup-skipped
    assert r2.status_code == 200 and calls["n"] == 2  # re-processed on retry
    assert db.users["u1"]["subscription_tier"] == "premium"


def test_expiration_event_downgrades_premium_to_free(env):
    client, db, seed = env
    seed("u1", {"subscription_tier": "premium",
                "entitlements": {"apple": {"status": "active", "expires": "2099-01-01T00:00:00+00:00", "store": "apple"}}})
    r = _post(client, _event("EXPIRATION", "u1", store="APP_STORE", event_id="evt_exp"))
    assert r.status_code == 200
    assert db.users["u1"]["entitlements"]["apple"]["status"] == "expired"
    assert db.users["u1"]["subscription_tier"] == "free"   # projection flips premium -> free


def test_malformed_json_body_400(env):
    client, db, seed = env
    r = client.post("/api/v1/billing/revenuecat/webhook", data="not json",
                    headers={"Authorization": SECRET, "Content-Type": "application/json"})
    assert r.status_code == 400
