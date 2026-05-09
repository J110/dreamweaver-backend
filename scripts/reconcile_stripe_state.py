#!/usr/bin/env python3
"""Reconcile Stripe subscription state with local user records.

For every user with a stripe_subscription_id, fetch the current Stripe
state and compare to local. Surfaces drift; optionally applies fixes
with --apply (dry-run by default).

Use case: webhooks can be missed. Stripe retries failed deliveries for
3 days then gives up. This script closes the gap by polling Stripe
directly. Idempotent — safe to run periodically (suggested: daily cron).

Usage (run from /opt/dreamweaver-backend on prod, with .env sourced):

    cd /opt/dreamweaver-backend
    set -a && . ./.env && set +a
    /usr/bin/python3 scripts/reconcile_stripe_state.py [--apply]

Phase 0 step 1.4c.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("reconcile_stripe_state")


def _iso_from_ts(ts: Optional[int]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _infer_tier(status: Optional[str], local_tier: Optional[str]) -> str:
    """Tier inference from Stripe status, mirroring billing.py handler logic."""
    if status in ("trialing", "active", "past_due"):
        return "premium"
    if status == "canceled":
        # Tier remains whatever local says; downgrade happens at period end
        # (a later cron / next webhook). Don't force it here.
        return local_tier or "free"
    return "free"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="reconcile_stripe_state",
        description=(
            "Reconcile local subscription state against Stripe. For every "
            "user with stripe_subscription_id, fetch Stripe's truth and "
            "compare. Dry-run by default; --apply to persist fixes."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes (default: dry-run / report only).",
    )
    args = parser.parse_args()

    # Lazy imports so --help works without env / SDK present.
    from app.services.local_store import get_local_store
    from app.services.stripe_client import _get_client

    stripe = _get_client()
    if stripe is None:
        print("ERROR: Stripe SDK not initialized. Check STRIPE_API_KEY env.")
        return 1

    store = get_local_store()
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        print(f"ERROR: cannot enumerate users: {e}")
        return 1

    print("=" * 60)
    print(f"Reconciling local state vs Stripe ({'APPLY' if args.apply else 'dry-run'})")
    print("=" * 60)

    checked = 0
    drift = 0
    fixed = 0
    errors = 0

    for doc in users:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        sub_id = data.get("stripe_subscription_id")
        if not sub_id:
            continue
        uid = data.get("uid") or data.get("id") or "?"
        username = data.get("username") or "?"
        checked += 1

        try:
            stripe_sub = stripe.Subscription.retrieve(sub_id)
        except Exception as e:
            errors += 1
            logger.warning(
                "Stripe.Subscription.retrieve failed username=%s sub=%s: %s",
                username, sub_id, e,
            )
            print(f"\n  ⚠ {username} (sub={sub_id}): Stripe fetch failed: {e}")
            continue

        local_status = data.get("subscription_status")
        local_period_end = data.get("current_period_end")
        local_tier = data.get("subscription_tier")

        remote_status = stripe_sub.get("status")
        remote_period_end = _iso_from_ts(stripe_sub.get("current_period_end"))
        remote_tier = _infer_tier(remote_status, local_tier)

        diffs = {}
        if local_status != remote_status:
            diffs["subscription_status"] = (local_status, remote_status)
        if local_period_end != remote_period_end:
            diffs["current_period_end"] = (local_period_end, remote_period_end)
        if local_tier != remote_tier:
            diffs["subscription_tier"] = (local_tier, remote_tier)

        if not diffs:
            continue

        drift += 1
        print(f"\nDRIFT username={username} uid={uid} sub={sub_id}")
        for key, (loc, rem) in diffs.items():
            print(f"  {key}: local={loc!r} stripe={rem!r}")

        if args.apply:
            update = {key: rem for key, (_, rem) in diffs.items()}
            try:
                store.collection("users").document(uid).update(update)
                from app.dependencies import _local_users
                if uid in _local_users:
                    _local_users[uid].update(update)
                fixed += 1
                print("  → APPLIED")
            except Exception as e:
                errors += 1
                logger.warning("apply failed username=%s: %s", username, e)
                print(f"  → APPLY FAILED: {e}")

    print("\n--- Reconciliation summary ---")
    print(f"Checked:        {checked}")
    print(f"Drift detected: {drift}")
    if args.apply:
        print(f"Fixes applied:  {fixed}")
    else:
        print("Mode:           dry-run (use --apply to persist fixes)")
    if errors:
        print(f"Errors:         {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
