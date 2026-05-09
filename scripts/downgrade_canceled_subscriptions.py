#!/usr/bin/env python3
"""Daily downgrade of canceled subscriptions past their period end.

Phase 0 step 1.4e. Stripe convention: when a user cancels, their
subscription status flips to 'canceled' but tier stays premium until
current_period_end (they keep what they paid for). After the period
end passes, this script drops them to free.

Behavior per user record where:
    subscription_status == 'canceled'
    AND current_period_end < now()
    AND subscription_tier == 'premium'

Set:
    subscription_tier = 'free'
    credits_remaining = 0      (monthly subscription credits zero out)
    credits_period_end = now() (period closed)
    [topup_credits_remaining UNCHANGED — survives by design]

Idempotent. Safe to run daily. Suggested cron: 03:00 UTC daily,
just before the activation cron at 03:30 UTC.

Usage (run from /opt/dreamweaver-backend on prod, with .env sourced):

    cd /opt/dreamweaver-backend
    set -a && . ./.env && set +a
    /usr/bin/python3 scripts/downgrade_canceled_subscriptions.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("downgrade_canceled_subscriptions")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="downgrade_canceled_subscriptions",
        description=(
            "Downgrade users whose canceled subscription has passed its "
            "current_period_end. Sets tier=free, zeros monthly credits, "
            "preserves top-up credits. Idempotent."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which users would be downgraded without writing.",
    )
    args = parser.parse_args()

    from app.services.local_store import get_local_store

    store = get_local_store()
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        print(f"ERROR: cannot enumerate users: {e}")
        return 1

    now = datetime.now(timezone.utc)
    candidates = []

    for doc in users:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        if data.get("subscription_status") != "canceled":
            continue
        if data.get("subscription_tier") != "premium":
            continue
        period_end_iso = data.get("current_period_end")
        if not period_end_iso:
            continue
        try:
            period_end = datetime.fromisoformat(
                str(period_end_iso).replace("Z", "+00:00")
            )
        except Exception:
            continue
        if period_end >= now:
            # Still within paid window — leave them on premium.
            continue
        candidates.append(data)

    if not candidates:
        print("No canceled subscriptions past period end. Nothing to do.")
        return 0

    print(f"Found {len(candidates)} canceled subscription(s) past period end:")
    for data in candidates:
        username = data.get("username", "?")
        uid = data.get("uid") or data.get("id", "?")
        period_end = data.get("current_period_end")
        topup = data.get("topup_credits_remaining") or 0
        print(
            f"  - {username} (uid={uid}) period_end={period_end} "
            f"topup_credits_preserved={topup}"
        )

    if args.dry_run:
        print("\nDRY RUN: no writes performed.")
        return 0

    now_iso = now.isoformat()
    updated = 0
    failed = 0
    for data in candidates:
        uid = data.get("uid") or data.get("id")
        if not uid:
            continue
        update = {
            "subscription_tier": "free",
            "credits_remaining": 0,
            "credits_period_end": now_iso,
        }
        try:
            store.collection("users").document(uid).update(update)
            from app.dependencies import _local_users
            if uid in _local_users:
                _local_users[uid].update(update)
            updated += 1
        except Exception as e:
            failed += 1
            logger.warning("downgrade failed uid=%s: %s", uid, e)

    print(f"\nDowngraded: {updated}")
    if failed:
        print(f"Failed:     {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
