import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
from app.utils.entitlements import compute_downgrades, compute_tier

NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=10)).isoformat()


def _uids(users):
    return {u.get("uid") for u in users}


def test_sweep_skips_perpetual_comp():
    user = {
        "uid": "comp1",
        "subscription_tier": "premium",
        "entitlements": {"comp": {"status": "active", "expires": None}},
    }
    assert compute_tier(user, NOW) == "premium"
    assert compute_downgrades([user], NOW) == []


def test_sweep_skips_healthy_active():
    for status in ("active", "trialing", "past_due"):
        user = {"uid": status, "subscription_tier": "premium", "subscription_status": status}
        assert compute_downgrades([user], NOW) == []


def test_sweep_skips_canceled_future_period():
    user = {
        "uid": "cancel_future",
        "subscription_tier": "premium",
        "subscription_status": "canceled",
        "current_period_end": FUTURE,
    }
    assert compute_downgrades([user], NOW) == []


def test_sweep_downgrades_canceled_past_period():
    user = {
        "uid": "cancel_past",
        "subscription_tier": "premium",
        "subscription_status": "canceled",
        "current_period_end": PAST,
    }
    assert compute_downgrades([user], NOW) == [user]


def test_sweep_downgrades_expired_comp():
    user = {
        "uid": "comp_expired",
        "subscription_tier": "premium",
        "entitlements": {"comp": {"status": "active", "expires": PAST}},
    }
    assert compute_tier(user, NOW) == "free"
    assert compute_downgrades([user], NOW) == [user]


def test_sweep_downgrades_disputed_no_comp():
    user = {
        "uid": "disputed",
        "subscription_tier": "premium",
        "subscription_status": "disputed",
    }
    assert compute_tier(user, NOW) == "free"
    assert compute_downgrades([user], NOW) == [user]


def test_sweep_skips_disputed_with_comp():
    user = {
        "uid": "disputed_comp",
        "subscription_tier": "premium",
        "subscription_status": "disputed",
        "entitlements": {"comp": {"status": "active", "expires": None}},
    }
    assert compute_tier(user, NOW) == "premium"
    assert compute_downgrades([user], NOW) == []


def test_sweep_downgrades_orphan_premium():
    user = {"uid": "orphan", "subscription_tier": "premium"}
    assert compute_tier(user, NOW) == "free"
    assert compute_downgrades([user], NOW) == [user]


def test_sweep_ignores_already_free():
    users = [
        {"uid": "free_canceled", "subscription_tier": "free", "subscription_status": "canceled", "current_period_end": PAST},
        {"uid": "free_orphan", "subscription_tier": "free"},
    ]
    assert compute_downgrades(users, NOW) == []


def test_sweep_canceled_boundary_now():
    user = {
        "uid": "boundary",
        "subscription_tier": "premium",
        "subscription_status": "canceled",
        "current_period_end": NOW.isoformat(),
    }
    assert compute_tier(user, NOW) == "free"
    assert compute_downgrades([user], NOW) == [user]


def test_sweep_skips_malformed_records_without_stalling():
    # tz-naive timestamp and list-shaped entitlements each used to raise and
    # abort the whole sweep; they must now be skipped (stay premium) while the
    # valid canceled-past-period user is still swept.
    tz_naive = {"uid": "naive", "subscription_tier": "premium",
                "subscription_status": "canceled",
                "current_period_end": "2026-06-10T00:00:00"}  # no offset
    bad_ent = {"uid": "badent", "subscription_tier": "premium",
               "entitlements": ["comp"]}  # list, not dict
    legit = {"uid": "cancel_past", "subscription_tier": "premium",
             "subscription_status": "canceled", "current_period_end": PAST}
    out = compute_downgrades([tz_naive, bad_ent, legit], NOW)
    assert _uids(out) == {"cancel_past"}


def test_sweep_mixed_returns_only_projected_free_premium():
    perpetual = {"uid": "p", "subscription_tier": "premium", "entitlements": {"comp": {"status": "active", "expires": None}}}
    active = {"uid": "a", "subscription_tier": "premium", "subscription_status": "active"}
    cancel_future = {"uid": "cf", "subscription_tier": "premium", "subscription_status": "canceled", "current_period_end": FUTURE}
    cancel_past = {"uid": "cp", "subscription_tier": "premium", "subscription_status": "canceled", "current_period_end": PAST}
    orphan = {"uid": "o", "subscription_tier": "premium"}
    already_free = {"uid": "f", "subscription_tier": "free"}
    not_a_dict = "not-a-dict"
    users = [perpetual, active, cancel_future, cancel_past, orphan, already_free, not_a_dict]
    swept = compute_downgrades(users, NOW)
    assert _uids(swept) == {"cp", "o"}
