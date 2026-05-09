#!/usr/bin/env python3
"""Prune old processed Stripe webhook event rows.

DELETE FROM stripe_webhook_events
WHERE status='processed' AND received_at < datetime('now', '-N days');

Idempotent. Resolves the TODO comment in app/api/v1/billing.py
(_open_billing_db) from Phase 0 step 1.4b.

Suggested cron entry (anmolmohan crontab, sourcing .env not required —
no env lookups in this script):

    0 5 * * 0 cd /opt/dreamweaver-backend && /usr/bin/python3 scripts/prune_stripe_webhook_events.py >> /opt/dreamweaver-backend/logs/prune_webhook_events.log 2>&1

Phase 0 step 1.4c.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("prune_stripe_webhook_events")

BILLING_DB_PATH = REPO_ROOT / "data" / "billing.db"
DEFAULT_RETENTION_DAYS = 30


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="prune_stripe_webhook_events",
        description=(
            "Delete stripe_webhook_events rows older than N days "
            "(default 30) where status='processed'. Failed and "
            "received-but-not-processed rows are preserved indefinitely "
            "for forensic visibility."
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help="Retention window in days (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows that would be deleted without deleting.",
    )
    args = parser.parse_args()

    if not BILLING_DB_PATH.exists():
        print(f"billing.db not found at {BILLING_DB_PATH} — nothing to prune.")
        return 0

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=args.days)
    ).isoformat()
    conn = sqlite3.connect(str(BILLING_DB_PATH))
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM stripe_webhook_events "
            "WHERE status='processed' AND received_at < ?",
            (cutoff,),
        )
        total = cur.fetchone()[0]

        if args.dry_run:
            print(
                f"DRY RUN: would delete {total} row(s) older than "
                f"{args.days} days (cutoff: {cutoff})."
            )
            return 0

        conn.execute(
            "DELETE FROM stripe_webhook_events "
            "WHERE status='processed' AND received_at < ?",
            (cutoff,),
        )
        conn.commit()
        print(
            f"Pruned {total} row(s) older than {args.days} days "
            f"(cutoff: {cutoff})."
        )
        logger.info(
            "Pruned %d stripe_webhook_events rows older than %d days",
            total, args.days,
        )
    except Exception as e:
        print(f"ERROR: {e}")
        logger.error("prune failed: %s", e)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
