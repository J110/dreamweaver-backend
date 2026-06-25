"""Entitlement projection. subscription_tier is a MATERIALIZED CACHE,
written only by recompute. premium = ANY source active.

Stripe source = read-adapter over existing top-level fields; its active()
mirrors billing.py + reconcile_stripe_state._infer_tier +
downgrade_canceled_subscriptions EXACTLY (the Decision-A equivalence).
apple/google/comp = nested under user["entitlements"][key];
generic active(); expires=None => perpetual (comp).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

_STRIPE_PREMIUM_STATUSES = ("active", "trialing", "past_due")
_SOURCE_PREMIUM_STATUSES = ("active", "trialing", "grace", "past_due")
_SOURCE_TERMINAL_STATUSES = ("revoked", "refunded", "expired")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def stripe_active(user: dict, now: datetime) -> bool:
    status = user.get("subscription_status")
    if status in _STRIPE_PREMIUM_STATUSES:
        return True
    if status == "canceled":
        pe = _parse_iso(user.get("current_period_end"))
        return pe is not None and now < pe
    return False


def source_active(source: Optional[dict], now: datetime) -> bool:
    if not source:
        return False
    status = source.get("status")
    if status in _SOURCE_TERMINAL_STATUSES:
        return False
    if status not in _SOURCE_PREMIUM_STATUSES:
        return False
    expires = _parse_iso(source.get("expires"))
    return expires is None or now < expires


def compute_tier(user: dict, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    if stripe_active(user, now):
        return "premium"
    ent = user.get("entitlements") or {}
    for key in ("apple", "google", "comp"):
        if source_active(ent.get(key), now):
            return "premium"
    return "free"


def compute_downgrades(users, now: Optional[datetime] = None) -> list:
    """Premium-cached users whose projection is now free (stale-high cache) —
    the set the downgrade sweep should act on. A user is returned iff
    subscription_tier == "premium" AND compute_tier(user, now) == "free".
    Perpetual comp (active, expires=None) projects premium and is NEVER
    returned (the perpetual-comp safety). Healthy active/trialing/past_due and
    canceled-still-in-period also project premium and are never returned."""
    now = now or datetime.now(timezone.utc)
    result = []
    for user in users:
        if not isinstance(user, dict):
            continue
        if user.get("subscription_tier") != "premium":
            continue
        try:
            projects_free = compute_tier(user, now) == "free"
        except Exception:
            # A record we can't evaluate (tz-naive timestamp, malformed
            # entitlements, etc.) stays premium — never auto-downgrade on data
            # we couldn't assess, and never let one bad record stall the sweep.
            continue
        if projects_free:
            result.append(user)
    return result
