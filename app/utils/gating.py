"""Paywall gating helpers.

Single source of truth for "is this user effectively premium right now".
With PAYWALL_ENABLED=false, returns True for every user — production behaves
exactly as it did before the paywall existed.

Platform gate: requests from the native Flutter wrapper (iOS / Android)
are forced premium until PAYWALL_NATIVE_ENABLED is flipped on alongside
a reviewed App Store build. The native-app flag is set per-request by
PlatformContextMiddleware and read here via a contextvar.
"""

import contextvars
from typing import Optional

from app.config import get_settings


_native_app_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "dreamvalley_is_native_app", default=False
)


def set_native_app_flag(value: bool) -> None:
    _native_app_var.set(bool(value))


def is_native_app_request() -> bool:
    return _native_app_var.get()


def is_premium(user: Optional[dict]) -> bool:
    settings = get_settings()
    if not settings.paywall_enabled:
        return True
    # Compliance: native-app requests stay premium until a reviewed
    # store build flips PAYWALL_NATIVE_ENABLED on.
    if is_native_app_request() and not settings.paywall_native_enabled:
        return True
    u = user or {}
    if settings.paywall_test_family_ids and (u.get("family_id") or "") not in settings.paywall_test_family_ids:
        return True
    return (u.get("subscription_tier") or "free") == "premium"


# Save caps (Step 3). None = unlimited (pre-paywall behavior, flag off).
FREE_SAVE_CAP = 5
PREMIUM_SAVE_CAP = 20


def save_cap(user: Optional[dict]) -> Optional[int]:
    """Max saved items for this user. None = unlimited.

    Flag-off returns None so saves stay unlimited (byte-identical to
    today). Flag-on: premium (incl. native-dormant / outside-allowlist)
    gets 20, gated free users get 5.
    """
    if not get_settings().paywall_enabled:
        return None
    return PREMIUM_SAVE_CAP if is_premium(user) else FREE_SAVE_CAP


def is_premium_content_item(item: dict) -> bool:
    """True if the item belongs to a premium-only content type.

    Premium types (free users see them browsable but playback-locked):
    - type=long_story
    - type=song AND subtype=funny_short
    """
    t = item.get("type")
    if t == "long_story":
        return True
    if t == "song" and item.get("subtype") == "funny_short":
        return True
    return False
