#!/usr/bin/env python3
"""Daily downgrade sweep — the projection's downgrade-side safety net.

Generalized (Deploy 2 Task 4). This is the cache-correcting half of the
entitlement projection: it downgrades ANY user whose cached
subscription_tier == 'premium' but whose entitlement projection
(compute_tier) is now 'free'. The candidate set is computed by
app.utils.entitlements.compute_downgrades — this script no longer
hand-rolls the canceled-past-period filter.

Cases swept (anything compute_tier scores as free while cache says premium):
    - canceled subscription past current_period_end (the primary, original case)
    - expired comp/apple/google entitlement (active but past its `expires`)
    - disputed/unpaid/incomplete stripe status with no active comp
    - signal-less premium orphans (tier=premium, no status, no entitlements)

NEVER swept (project premium, so cache is correct):
    - perpetual comp (entitlements.comp = active, expires=None)
    - healthy payers (status active/trialing/past_due)
    - canceled still within current_period_end
    - disputed BUT comp-active (comp is independent of the stripe dispute)

This generalization is SAFE because Deploy 1's backfill gave every legit
premium user an entitlement source; Deploy 2's dry-run against real data
gates the rollout. The downgrade WRITE is unchanged:

Set per swept user:
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
            "Downgrade any premium-cached user whose entitlement projection "
            "is now free (canceled-past-period, expired comp/apple/google, "
            "disputed-without-comp, signal-less orphans). Sets tier=free, "
            "zeros monthly credits, preserves top-up credits. Idempotent."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which premium-cached users project free without writing.",
    )
    args = parser.parse_args()

    from app.services.local_store import get_local_store
    from app.utils.entitlements import compute_downgrades

    store = get_local_store()
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        print(f"ERROR: cannot enumerate users: {e}")
        return 1

    now = datetime.now(timezone.utc)
    users_dicts = [
        doc.to_dict() if hasattr(doc, "to_dict") else doc for doc in users
    ]
    candidates = compute_downgrades(users_dicts, now)

    if not candidates:
        print("No premium-cached users project free. Nothing to do.")
        return 0

    print(
        f"Found {len(candidates)} premium-cached user(s) projecting free "
        f"(stale-high cache):"
    )
    for data in candidates:
        username = data.get("username", "?")
        uid = data.get("uid") or data.get("id", "?")
        period_end = data.get("current_period_end") or "n/a"
        status = data.get("subscription_status") or "none"
        topup = data.get("topup_credits_remaining") or 0
        print(
            f"  - {username} (uid={uid}) status={status} "
            f"period_end={period_end} topup_credits_preserved={topup}"
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
