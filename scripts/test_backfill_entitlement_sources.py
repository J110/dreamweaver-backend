import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import pytest
from scripts.backfill_entitlement_sources import (
    classify, plan_backfill, assert_tier_preserved, verify_report)

NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=10)).isoformat()
PAST = (NOW - timedelta(days=10)).isoformat()

def test_classify_all_four_buckets():
    assert classify({"subscription_tier": "free"}, NOW) == "free"
    assert classify({"subscription_tier": "premium", "stripe_customer_id": "cus_1",
                     "subscription_status": "active"}, NOW) == "stripe"
    assert classify({"subscription_tier": "premium"}, NOW) == "comp"
    assert classify({"subscription_tier": "premium", "stripe_customer_id": "cus_1",
                     "subscription_status": "canceled", "current_period_end": PAST}, NOW) == "ambiguous"

def test_classify_past_due_with_customer_is_stripe_not_ambiguous():
    assert classify({"subscription_tier": "premium", "stripe_customer_id": "cus_1",
                     "subscription_status": "past_due", "current_period_end": PAST}, NOW) == "stripe"

def test_comp_backfill_writes_perpetual_null_expires():
    users = {"c": {"subscription_tier": "premium"}}
    updates = plan_backfill(users, NOW)
    assert updates["c"]["entitlements"]["comp"]["expires"] is None
    assert updates["c"]["entitlements"]["comp"]["status"] == "active"

def test_backfill_preserves_tier_for_all_buckets():
    users = {
        "u_free": {"subscription_tier": "free"},
        "u_stripe": {"subscription_tier": "premium", "stripe_customer_id": "cus_1", "subscription_status": "active"},
        "u_pastdue": {"subscription_tier": "premium", "stripe_customer_id": "cus_2", "subscription_status": "past_due", "current_period_end": PAST},
        "u_comp": {"subscription_tier": "premium"},
    }
    for uid, upd in plan_backfill(users, NOW).items():
        users[uid].update(upd)
    assert_tier_preserved(users, NOW)

def test_verify_ok_when_preserved():
    users = {"f": {"subscription_tier": "free"},
             "s": {"subscription_tier": "premium", "stripe_customer_id": "c", "subscription_status": "active"},
             "c": {"subscription_tier": "premium"}}
    ok, reasons = verify_report(users, NOW)
    assert ok is True and reasons == []

def test_verify_fails_nonzero_on_ambiguous():
    users = {"a": {"subscription_tier": "premium", "stripe_customer_id": "c", "subscription_status": "unpaid"}}
    ok, reasons = verify_report(users, NOW)
    assert ok is False
    assert any("AMBIGUOUS" in r for r in reasons)

def test_ambiguous_halts_apply():
    users = {"a": {"subscription_tier": "premium", "stripe_customer_id": "c", "subscription_status": "unpaid"}}
    with pytest.raises(SystemExit):
        plan_backfill(users, NOW, halt_on_ambiguous=True)
