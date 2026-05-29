"""Backlog window gating per subscription tier.

Two regimes:

- Paywall OFF (PAYWALL_ENABLED=false): legacy behavior — items older
  than LEGACY_BACKLOG_DAYS (30) are clipped for everyone. Detail
  endpoints return items unchanged. No `premium_locked` field, no
  audio scrubbing. Byte-identical to pre-paywall responses.

- Paywall ON: Reading-B — free users see the full library browsable,
  with old items (> FREE_BACKLOG_DAYS) and premium-only content types
  marked `premium_locked=true` and audio fields scrubbed. Premium users
  see the full library unlocked (PREMIUM_BACKLOG_DAYS=None).

The two regimes are gated by `settings.paywall_enabled` inside the
public helpers, so callers don't have to know which mode they're in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings
from app.utils.gating import is_premium, is_premium_content_item


# Paywall-active windows.
FREE_BACKLOG_DAYS = 7
PREMIUM_BACKLOG_DAYS: Optional[int] = None

# Pre-paywall window — applied to everyone when PAYWALL_ENABLED=false.
# Matches the value the codebase has been shipping; keep this until
# the paywall flips on so flag-off is byte-identical to today.
LEGACY_BACKLOG_DAYS = 30


def _paywall_active() -> bool:
    return get_settings().paywall_enabled


def _is_premium_user(current_user: Optional[dict]) -> bool:
    return is_premium(current_user)


def backlog_window_days(current_user: Optional[dict]) -> Optional[int]:
    """Return the backlog window in days, or None for unlimited.

    Flag-off: 30 days for everyone (legacy). Flag-on: 7 / None per tier.
    """
    if not _paywall_active():
        return LEGACY_BACKLOG_DAYS
    if _is_premium_user(current_user):
        return PREMIUM_BACKLOG_DAYS
    return FREE_BACKLOG_DAYS


def _parse_created_at(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_older_than(created_at, cutoff_dt: datetime) -> bool:
    dt = _parse_created_at(created_at)
    if dt is None:
        return False
    return dt < cutoff_dt


def should_lock_for_user(item: dict, current_user: Optional[dict]) -> bool:
    """True iff this item should be premium-locked for this user.

    Always False when the paywall is OFF — no Reading-B annotation, no
    play/replay 403. Inert with flag off.
    """
    if not _paywall_active():
        return False
    if _is_premium_user(current_user):
        return False
    if is_premium_content_item(item):
        return True
    days = FREE_BACKLOG_DAYS
    if days is None:
        return False
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    return _is_older_than(item.get("created_at"), cutoff_dt)


def _scrub_audio(item: dict) -> None:
    item["audio_url"] = None
    item["audio_file"] = None
    item.pop("audio_variants", None)


def apply_premium_lock(item: dict, current_user: Optional[dict]) -> dict:
    """Return an item annotated with premium_locked + scrubbed audio when
    the user shouldn't be able to play it.

    Flag-off: returns the item unchanged (no `premium_locked` key added,
    no audio scrub). Byte-identical to pre-paywall responses.
    """
    if not _paywall_active():
        return item
    out = dict(item)
    locked = should_lock_for_user(out, current_user)
    out["premium_locked"] = locked
    if locked:
        _scrub_audio(out)
    return out


def _legacy_clip(
    items: list[dict],
    days: int,
) -> tuple[list[dict], Optional[str]]:
    """Pre-paywall behavior: drop items older than `days`, return cutoff_iso
    when at least one item was clipped.
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat()
    kept: list[dict] = []
    clipped = False
    for item in items:
        ca = item.get("created_at")
        if not ca:
            kept.append(item)
            continue
        dt = _parse_created_at(ca)
        if dt is None:
            kept.append(item)
            continue
        if dt >= cutoff_dt:
            kept.append(item)
        else:
            clipped = True
    return kept, (cutoff_iso if clipped else None)


def filter_by_backlog(
    items: list[dict],
    current_user: Optional[dict],
    bypass: bool = False,
) -> tuple[list[dict], Optional[str]]:
    """Apply tier-window treatment to a list of items.

    Flag-off → legacy clip at LEGACY_BACKLOG_DAYS for everyone (today's
    behavior). Flag-on → Reading-B mark+scrub.

    Returns (items, cutoff_iso). `cutoff_iso` signals to the frontend
    that older content exists beyond the user's window — used for the
    upgrade-CTA banner. `bypass=True` returns the unmodified list with
    cutoff=None (ops tooling like deploy_guard).
    """
    if bypass:
        return list(items), None

    if not _paywall_active():
        return _legacy_clip(items, LEGACY_BACKLOG_DAYS)

    out: list[dict] = []
    any_locked = False
    for item in items:
        locked_item = apply_premium_lock(item, current_user)
        if locked_item.get("premium_locked"):
            any_locked = True
        out.append(locked_item)

    cutoff_iso: Optional[str] = None
    if any_locked and not _is_premium_user(current_user):
        days = FREE_BACKLOG_DAYS
        if days is not None:
            cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    return out, cutoff_iso
