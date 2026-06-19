import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
from app.utils.entitlements import stripe_active, source_active, compute_tier

NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=10)).isoformat()

def test_stripe_premium_statuses_active_regardless_of_period_end():
    for status in ("active", "trialing", "past_due"):
        assert stripe_active({"subscription_status": status, "current_period_end": PAST}, NOW) is True
        assert stripe_active({"subscription_status": status, "current_period_end": FUTURE}, NOW) is True

def test_stripe_canceled_future_period_active():
    assert stripe_active({"subscription_status": "canceled", "current_period_end": FUTURE}, NOW) is True

def test_stripe_canceled_past_period_inactive():
    assert stripe_active({"subscription_status": "canceled", "current_period_end": PAST}, NOW) is False

def test_stripe_disputed_unpaid_incomplete_none_inactive():
    for status in ("disputed", "unpaid", "incomplete", "incomplete_expired", None):
        assert stripe_active({"subscription_status": status, "current_period_end": FUTURE}, NOW) is False

def test_comp_null_expires_perpetual():
    assert source_active({"status": "active", "expires": None}, NOW) is True

def test_terminal_negative_beats_future_expires():
    for status in ("revoked", "refunded", "expired"):
        assert source_active({"status": status, "expires": FUTURE}, NOW) is False

def test_source_expiry_boundary():
    assert source_active({"status": "active", "expires": PAST}, NOW) is False
    assert source_active({"status": "active", "expires": FUTURE}, NOW) is True
    assert source_active(None, NOW) is False

def test_compute_tier_any_source():
    assert compute_tier({"subscription_status": "active"}, NOW) == "premium"
    assert compute_tier({"entitlements": {"comp": {"status": "active", "expires": None}}}, NOW) == "premium"
    assert compute_tier({"entitlements": {"apple": {"status": "active", "expires": FUTURE}}}, NOW) == "premium"
    assert compute_tier({"subscription_status": "canceled", "current_period_end": PAST}, NOW) == "free"
    assert compute_tier({}, NOW) == "free"
