"""Backfill recovery_email on existing user records from Stripe customer.email.

Idempotent. Sets recovery_email only when missing.

Discipline pattern (matches scripts/correct_duration_metadata.py):
  1. --dry-run: log what WOULD be written; no changes
  2. Review the sample (first 5)
  3. Real run (no --dry-run)
  4. Verify: counts before/after

Targets data/users.json on the prod VM directly. The pipeline cron and
prod LocalStore both read users.json on next boot/load; admin reload is
NOT required (users.json is not regenerated from per-content files —
unlike content.json — so direct edits are safe).

Usage:
  python3 scripts/backfill_recovery_email.py --dry-run
  python3 scripts/backfill_recovery_email.py
  python3 scripts/backfill_recovery_email.py --users-path /opt/dreamweaver-backend/data/users.json
"""

import argparse
import json
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what WOULD be written; no changes.")
    parser.add_argument("--users-path", default="data/users.json",
                        help="Path to users.json (default: data/users.json)")
    args = parser.parse_args()

    try:
        import stripe
    except ImportError:
        print("ERROR: stripe library not installed. Run: pip install stripe", file=sys.stderr)
        sys.exit(1)

    # Project convention is STRIPE_API_KEY (see billing.py + stripe_client.py).
    # STRIPE_SECRET_KEY accepted as fallback for Stripe-doc-following users.
    stripe.api_key = os.getenv("STRIPE_API_KEY") or os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        print("ERROR: STRIPE_API_KEY (or STRIPE_SECRET_KEY) env var missing.", file=sys.stderr)
        sys.exit(1)

    users_path = Path(args.users_path)
    if not users_path.exists():
        print(f"ERROR: users.json not found at {users_path}", file=sys.stderr)
        sys.exit(1)

    with open(users_path) as f:
        users_raw = json.load(f)

    # users.json may be a list of user dicts OR a dict of uid→user.
    # Normalize to a list of (uid, user_dict) pairs.
    if isinstance(users_raw, list):
        users_list = [(u.get("uid") or u.get("id"), u) for u in users_raw if isinstance(u, dict)]
    elif isinstance(users_raw, dict):
        users_list = list(users_raw.items())
    else:
        print(f"ERROR: unexpected structure in {users_path}: {type(users_raw).__name__}", file=sys.stderr)
        sys.exit(1)
    users_list = [(uid, u) for uid, u in users_list if uid]

    before_count = sum(1 for _, u in users_list if u.get("recovery_email"))
    with_customer = [(uid, u) for uid, u in users_list if u.get("stripe_customer_id")]

    print(f"Total users: {len(users_list)}")
    print(f"With stripe_customer_id: {len(with_customer)}")
    print(f"With recovery_email (before): {before_count}")
    print()

    changes = []
    skipped = []
    fetch_failed = []
    for uid, u in with_customer:
        if u.get("recovery_email"):
            skipped.append(uid)
            continue
        try:
            customer = stripe.Customer.retrieve(u["stripe_customer_id"])
            email = (customer.get("email") or "").strip().lower()
            if not email:
                continue
            changes.append({
                "uid": uid,
                "stripe_customer_id": u["stripe_customer_id"],
                "recovery_email": email,
                "current_billing_email": (u.get("billing_email") or "").strip().lower(),
            })
        except Exception as e:
            fetch_failed.append((uid, str(e)))

    print(f"Already had recovery_email (skipped): {len(skipped)}")
    print(f"Stripe fetch failed: {len(fetch_failed)}")
    print(f"Will set recovery_email on: {len(changes)} users")
    print()
    print("Sample (first 5):")
    for c in changes[:5]:
        match = " (matches billing_email)" if c["current_billing_email"] == c["recovery_email"] else ""
        print(f"  uid={c['uid'][:8]}... recovery_email={c['recovery_email']}{match}")

    if fetch_failed:
        print()
        print("Fetch failures (first 5):")
        for uid, err in fetch_failed[:5]:
            print(f"  uid={uid[:8]}...: {err}")

    if args.dry_run:
        print()
        print("[DRY RUN] No changes written.")
        return

    print()
    print(f"Applying {len(changes)} changes to {users_path}...")
    changes_by_uid = {c["uid"]: c["recovery_email"] for c in changes}

    # Mutate in place per original on-disk shape (list of dicts OR dict of uid→dict).
    if isinstance(users_raw, list):
        for u in users_raw:
            if not isinstance(u, dict):
                continue
            uid = u.get("uid") or u.get("id")
            if uid in changes_by_uid:
                u["recovery_email"] = changes_by_uid[uid]
        out = users_raw
    else:
        for uid, email in changes_by_uid.items():
            if uid in users_raw:
                users_raw[uid]["recovery_email"] = email
        out = users_raw

    with open(users_path, "w") as f:
        json.dump(out, f, indent=2)

    # Re-count from on-disk shape.
    after_users = (out if isinstance(out, list) else list(out.values()))
    after_count = sum(1 for u in after_users if isinstance(u, dict) and u.get("recovery_email"))
    print(f"With recovery_email (after): {after_count}")
    print(f"Delta: +{after_count - before_count}")


if __name__ == "__main__":
    main()
