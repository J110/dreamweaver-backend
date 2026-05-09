"""Backlog window gating per subscription tier.

Phase 0 step 1.4e — the one user-visible enforcement that ships with
the credit machinery. Free users see the last 3 days of content;
Premium users see the last 30 days. Anonymous (logged-out) users
default to the Free window.

Usage in a list endpoint:

    items, cutoff = filter_by_backlog(items, current_user)
    return ContentListResponse(
        success=True,
        data={
            "items": paginated_items,
            "total": len(items),
            "tier_window_cutoff_at": cutoff,  # None if no cutoff applied
            ...
        },
    )

The cutoff is the ISO timestamp BEFORE which content is hidden by the
tier window. Frontend can use it to render a "Upgrade to see older
stories" CTA at the boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


FREE_BACKLOG_DAYS = 3
PREMIUM_BACKLOG_DAYS = 30


def _tier_for_user(current_user: Optional[dict]) -> str:
    """Resolve the effective tier from current_user dict (or anonymous default)."""
    if not current_user:
        return "free"
    return current_user.get("subscription_tier") or "free"


def backlog_window_days(current_user: Optional[dict]) -> int:
    """Return the backlog window in days for this user's tier."""
    if _tier_for_user(current_user) == "premium":
        return PREMIUM_BACKLOG_DAYS
    return FREE_BACKLOG_DAYS


def filter_by_backlog(
    items: list[dict],
    current_user: Optional[dict],
    bypass: bool = False,
) -> tuple[list[dict], Optional[str]]:
    """Filter items by tier backlog window, return (filtered_items, cutoff_iso).

    cutoff_iso is non-null when the window actually clipped at least one
    item — meaning the user has older content available behind the
    paywall. Frontend renders the upgrade CTA when this is non-null.

    Items must have a `created_at` field (ISO string). Items missing or
    with unparseable created_at are kept (defensive — never lose content
    to a bad timestamp).

    bypass=True returns the full unfiltered list with cutoff=None. Used
    by ops tooling (e.g. scripts/deploy_guard.py) that needs the full
    catalog count regardless of caller tier.
    """
    if bypass:
        return list(items), None

    days = backlog_window_days(current_user)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat()

    kept: list[dict] = []
    clipped = False
    for item in items:
        ca = item.get("created_at")
        if not ca:
            kept.append(item)
            continue
        try:
            item_dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
        except Exception:
            kept.append(item)
            continue
        # Naive timestamps (some legacy items lack a tz suffix) — assume UTC.
        # Comparing aware to naive raises TypeError; normalise both to aware.
        if item_dt.tzinfo is None:
            item_dt = item_dt.replace(tzinfo=timezone.utc)
        if item_dt >= cutoff_dt:
            kept.append(item)
        else:
            clipped = True

    return kept, (cutoff_iso if clipped else None)
