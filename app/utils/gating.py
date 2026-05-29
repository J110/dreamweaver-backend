"""Paywall gating helpers.

Single source of truth for "is this user effectively premium right now".
With PAYWALL_ENABLED=false, returns True for every user — production behaves
exactly as it did before the paywall existed.
"""

from typing import Optional

from app.config import get_settings


def is_premium(user: Optional[dict]) -> bool:
    settings = get_settings()
    if not settings.paywall_enabled:
        return True
    u = user or {}
    if settings.paywall_test_family_ids and (u.get("family_id") or "") not in settings.paywall_test_family_ids:
        return True
    return (u.get("subscription_tier") or "free") == "premium"
