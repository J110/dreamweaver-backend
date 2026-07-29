"""Pure RevenueCat webhook event -> entitlement source mapping. No app imports."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

_STORE = {"APP_STORE": "apple", "MAC_APP_STORE": "apple", "PLAY_STORE": "google"}
_ACTIVE = {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE",
           "NON_RENEWING_PURCHASE", "REFUND_REVERSED"}


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def map_event_to_source(event: dict) -> Optional[dict]:
    if not isinstance(event, dict):
        return None
    etype = event.get("type")
    store = _STORE.get(event.get("store"))
    if store is None:
        return None
    if etype in _ACTIVE:
        status = "trialing" if event.get("period_type") == "TRIAL" else "active"
        return {"store": store, "status": status, "expires": _iso(event.get("expiration_at_ms"))}
    if etype in ("CANCELLATION", "SUBSCRIPTION_PAUSED"):
        # Keep ACTIVE, KEEP the existing expires; expiry drives the downgrade.
        # CANCELLATION = auto-renew off. SUBSCRIPTION_PAUSED = Google pause, which
        # takes effect at period end — keep access until expires either way.
        return {"store": store, "status": "active", "expires": _iso(event.get("expiration_at_ms"))}
    if etype == "BILLING_ISSUE":
        # grace period: expires is the GRACE end, not the sub end
        return {"store": store, "status": "grace", "expires": _iso(event.get("grace_period_expiration_at_ms")) or _iso(event.get("expiration_at_ms"))}
    if etype == "EXPIRATION":
        return {"store": store, "status": "expired", "expires": _iso(event.get("expiration_at_ms"))}
    if etype == "REFUND":
        # actual refund: terminal. (REFUND_REVERSED is in _ACTIVE — a reversed refund re-grants.)
        return {"store": store, "status": "refunded", "expires": _iso(event.get("expiration_at_ms"))}
    return None  # TEST, TRANSFER, etc. -> ignored
