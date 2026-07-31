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


def move_native_entitlements(source: dict, destination: dict, store: Optional[str] = None):
    source = dict(source or {})
    destination = dict(destination or {})
    if store:
        mapped = _STORE.get(store)
        keys = (mapped,) if mapped else ()
    else:
        keys = ("apple", "google")
    for key in keys:
        if key in source:
            destination[key] = source.pop(key)
    return source, destination


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def customer_info_to_source(payload: dict, entitlement_id: str = "premium") -> Optional[dict]:
    subscriber = payload.get("subscriber") if isinstance(payload, dict) else None
    if not isinstance(subscriber, dict):
        return None
    entitlement = (subscriber.get("entitlements") or {}).get(entitlement_id)
    if not isinstance(entitlement, dict):
        return None
    product_id = entitlement.get("product_identifier")
    subscription = (subscriber.get("subscriptions") or {}).get(product_id) or {}
    store = _STORE.get(str(subscription.get("store") or "").upper())
    if store is None:
        return None
    expires = _parse_date(entitlement.get("expires_date"))
    grace = _parse_date(entitlement.get("grace_period_expires_date"))
    now = datetime.now(timezone.utc)
    if grace and grace > now:
        status = "grace"
        effective_expires = grace
    elif expires is None or expires > now:
        status = "trialing" if str(subscription.get("period_type") or "").lower() == "trial" else "active"
        effective_expires = expires
    else:
        status = "expired"
        effective_expires = expires
    return {
        "store": store,
        "status": status,
        "expires": effective_expires.isoformat() if effective_expires else None,
        "product_id": product_id,
        "environment": "SANDBOX" if subscription.get("is_sandbox") else "PRODUCTION",
    }


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
    return None  # TEST, TRANSFER, etc. -> handled elsewhere or ignored
