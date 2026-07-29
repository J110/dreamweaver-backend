"""Tests for pure RevenueCat event -> entitlement-source mapping.

Pure: imports only app.utils.revenuecat_mapping and app.utils.entitlements
(both stdlib-only, no store boot). Runs under system python3, must not
dirty data/content.json or seed_output.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.revenuecat_mapping import map_event_to_source, _iso
from app.utils.entitlements import source_active, _parse_iso

# Deterministic clock + epoch-millis fixtures straddling NOW.
NOW = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
FUTURE_MS = int(datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
PAST_MS = int(datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
GRACE_MS = int(datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _ev(**kw):
    base = {"store": "APP_STORE", "expiration_at_ms": FUTURE_MS}
    base.update(kw)
    return base


def test_non_dict_event_returns_none():
    # A3 feeds untrusted body["event"]; a non-dict must return None, not raise.
    assert map_event_to_source(None) is None
    assert map_event_to_source("REFUND") is None
    assert map_event_to_source(123) is None


# ---------------------------------------------------------------------------
# 1. Full event table
# ---------------------------------------------------------------------------

def test_initial_purchase_active():
    r = map_event_to_source(_ev(type="INITIAL_PURCHASE"))
    assert r == {"store": "apple", "status": "active", "expires": _iso(FUTURE_MS)}


def test_initial_purchase_trial_is_trialing():
    r = map_event_to_source(_ev(type="INITIAL_PURCHASE", period_type="TRIAL"))
    assert r["status"] == "trialing"
    assert r["store"] == "apple"
    assert r["expires"] == _iso(FUTURE_MS)


def test_renewal_active():
    assert map_event_to_source(_ev(type="RENEWAL"))["status"] == "active"


def test_uncancellation_active():
    assert map_event_to_source(_ev(type="UNCANCELLATION"))["status"] == "active"


def test_product_change_active():
    assert map_event_to_source(_ev(type="PRODUCT_CHANGE"))["status"] == "active"


def test_non_renewing_purchase_active():
    assert map_event_to_source(_ev(type="NON_RENEWING_PURCHASE"))["status"] == "active"


def test_cancellation_keeps_active_and_expiry():
    # CANCELLATION = auto-renew off (not refund): stays active, KEEPS the
    # existing expiry. Expiry (future here) drives the eventual downgrade.
    r = map_event_to_source(_ev(type="CANCELLATION"))
    assert r["status"] == "active"
    assert r["expires"] == _iso(FUTURE_MS)
    assert r["expires"] is not None


def test_billing_issue_grace_uses_grace_expiry():
    # Two DIFFERENT timestamps: grace end vs sub end. Must pick the grace one.
    r = map_event_to_source(
        _ev(type="BILLING_ISSUE", grace_period_expiration_at_ms=GRACE_MS,
            expiration_at_ms=PAST_MS)
    )
    assert r["status"] == "grace"
    assert r["expires"] == _iso(GRACE_MS)
    assert r["expires"] != _iso(PAST_MS)


def test_billing_issue_falls_back_to_expiration_when_no_grace():
    r = map_event_to_source(_ev(type="BILLING_ISSUE", expiration_at_ms=FUTURE_MS))
    assert r["status"] == "grace"
    assert r["expires"] == _iso(FUTURE_MS)


def test_expiration_expired():
    r = map_event_to_source(_ev(type="EXPIRATION", expiration_at_ms=PAST_MS))
    assert r["status"] == "expired"
    assert r["expires"] == _iso(PAST_MS)


def test_refund_refunded():
    assert map_event_to_source(_ev(type="REFUND"))["status"] == "refunded"


def test_refund_reversed_re_grants_active():
    # a reversed refund re-entitles the user -> active (not terminal-free)
    s = map_event_to_source(_ev(type="REFUND_REVERSED", expiration_at_ms=FUTURE_MS))
    assert s["status"] == "active"
    assert source_active({"status": s["status"], "expires": s["expires"]}, NOW) is True


def test_subscription_paused_keeps_active_until_expiry():
    # Google pause takes effect at period end -> keep access until expires.
    s = map_event_to_source(_ev(type="SUBSCRIPTION_PAUSED", expiration_at_ms=FUTURE_MS))
    assert s["status"] == "active" and s["expires"] == _iso(FUTURE_MS)
    assert source_active({"status": s["status"], "expires": s["expires"]}, NOW) is True
    # once the paid window ends, expiry drives it free
    s2 = map_event_to_source(_ev(type="SUBSCRIPTION_PAUSED", expiration_at_ms=PAST_MS))
    assert source_active({"status": s2["status"], "expires": s2["expires"]}, NOW) is False


def test_play_store_maps_to_google():
    assert map_event_to_source(_ev(type="INITIAL_PURCHASE", store="PLAY_STORE"))["store"] == "google"


def test_app_store_maps_to_apple():
    assert map_event_to_source(_ev(type="INITIAL_PURCHASE", store="APP_STORE"))["store"] == "apple"


def test_mac_app_store_maps_to_apple():
    assert map_event_to_source(_ev(type="INITIAL_PURCHASE", store="MAC_APP_STORE"))["store"] == "apple"


def test_test_event_ignored():
    assert map_event_to_source(_ev(type="TEST")) is None


def test_transfer_event_ignored():
    assert map_event_to_source(_ev(type="TRANSFER")) is None


def test_unknown_type_ignored():
    assert map_event_to_source(_ev(type="SOMETHING_WEIRD")) is None


def test_unknown_store_returns_none():
    assert map_event_to_source(_ev(type="INITIAL_PURCHASE", store="AMAZON")) is None


def test_missing_store_returns_none():
    assert map_event_to_source({"type": "INITIAL_PURCHASE", "expiration_at_ms": FUTURE_MS}) is None


# ---------------------------------------------------------------------------
# 2. Timestamp round-trip: epoch-ms -> ISO -> datetime == same UTC instant.
#    Proves the format source_active consumes (via _parse_iso) is correct.
# ---------------------------------------------------------------------------

def test_iso_round_trips_through_parse_iso():
    r = map_event_to_source(_ev(type="INITIAL_PURCHASE", expiration_at_ms=FUTURE_MS))
    parsed = _parse_iso(r["expires"])
    assert parsed is not None
    expected = datetime.fromtimestamp(FUTURE_MS / 1000, tz=timezone.utc)
    assert parsed == expected


def test_iso_none_for_missing_ms():
    assert _iso(None) is None


def test_iso_none_for_garbage_ms():
    assert _iso("not-a-number") is None


# ---------------------------------------------------------------------------
# 3. Integration seam (behavioral): the emitted status vocabulary is exactly
#    what the live projection's source_active accepts. Not hand-asserted
#    constants — built via map_event_to_source, judged by the real predicate.
# ---------------------------------------------------------------------------

PREMIUM_INTENT_EVENTS = [
    _ev(type="INITIAL_PURCHASE", expiration_at_ms=FUTURE_MS),
    _ev(type="RENEWAL", expiration_at_ms=FUTURE_MS),
    _ev(type="UNCANCELLATION", expiration_at_ms=FUTURE_MS),
    _ev(type="PRODUCT_CHANGE", expiration_at_ms=FUTURE_MS),
    _ev(type="INITIAL_PURCHASE", period_type="TRIAL", expiration_at_ms=FUTURE_MS),
    _ev(type="CANCELLATION", expiration_at_ms=FUTURE_MS),
    _ev(type="BILLING_ISSUE", grace_period_expiration_at_ms=GRACE_MS, expiration_at_ms=PAST_MS),
]

TERMINAL_EVENTS = [
    _ev(type="EXPIRATION", expiration_at_ms=PAST_MS),
    _ev(type="REFUND", expiration_at_ms=PAST_MS),
    _ev(type="REFUND_REVERSED", expiration_at_ms=PAST_MS),
    _ev(type="SUBSCRIPTION_PAUSED", expiration_at_ms=PAST_MS),
]


def test_premium_intent_events_project_active():
    for ev in PREMIUM_INTENT_EVENTS:
        s = map_event_to_source(ev)
        assert s is not None, ev
        assert source_active({"status": s["status"], "expires": s["expires"]}, NOW) is True, ev


def test_terminal_events_project_inactive():
    for ev in TERMINAL_EVENTS:
        s = map_event_to_source(ev)
        assert s is not None, ev
        assert source_active({"status": s["status"], "expires": s["expires"]}, NOW) is False, ev


def test_cancellation_with_past_expiry_projects_inactive():
    # Same status ("active") but the kept expiry is in the past -> projection
    # downgrades. Proves expiry, not status, drives the CANCELLATION downgrade.
    s = map_event_to_source(_ev(type="CANCELLATION", expiration_at_ms=PAST_MS))
    assert s["status"] == "active"
    assert source_active({"status": s["status"], "expires": s["expires"]}, NOW) is False
