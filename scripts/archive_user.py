#!/usr/bin/env python3
"""Soft-archive a user record (tombstone, no hard delete).

Phase 0 step 1.5e helper. Sets archived=true, archived_reason=<str>,
archived_at=<iso> on the user record. Idempotent — re-archiving an
already-archived record is a no-op (preserves the original
archived_reason and archived_at).

Used initially for tonight's 4 test artifacts; reusable for future
cleanups (Vcbshbcbsbebcdvgdx-style keyboard mash, abandoned ghost
records, etc).

Tombstoned records:
  - filtered out of find_username_collisions / merge collision groups
  - filtered out of complete_onboarding's collision check
  - filtered out of magic_link._username_taken's collision check
  - skipped by invalidate_old_tokens.py pre-flight (won't block on
    tombstoned records lacking email)

Usage:
    cd /opt/dreamweaver-backend
    /usr/bin/python3 scripts/archive_user.py --uid <uid> --reason <str>
    /usr/bin/python3 scripts/archive_user.py --uid <uid> --reason <str> --dry-run
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

logger = get_logger("archive_user")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="archive_user",
        description=(
            "Soft-archive a user record. Sets archived=true, "
            "archived_reason, archived_at. Idempotent."
        ),
    )
    parser.add_argument("--uid", required=True, help="User uid to archive.")
    parser.add_argument("--reason", required=True, help="Reason string (e.g. test_artifact_2026_05_09).")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    args = parser.parse_args()

    from app.services.local_store import get_local_store

    # In-memory _local_users cache lives inside the running Docker
    # container; updating it from a host-run script requires importing
    # app.dependencies which transitively pulls fastapi (not installed
    # on host). LocalStore writes hit disk; the container's cache
    # rebuilds from disk on next restart. For an archive operation,
    # that's the right semantic — no urgent live-state update needed.
    store = get_local_store()
    try:
        doc = store.collection("users").document(args.uid).get()
    except Exception as e:
        print(f"ERROR: cannot fetch uid={args.uid}: {e}")
        return 1

    if not doc.exists:
        print(f"ERROR: no user record at uid={args.uid}")
        return 1

    data = doc.to_dict() or {}
    username = data.get("username") or "(none)"
    email = data.get("email") or "(none)"

    if data.get("archived"):
        prior_reason = data.get("archived_reason") or "(none)"
        prior_at = data.get("archived_at") or "(none)"
        print(
            f"NO-OP: uid={args.uid} username={username!r} already archived"
            f" (reason={prior_reason!r} at={prior_at})."
        )
        return 0

    update = {
        "archived": True,
        "archived_reason": args.reason,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"Target: uid={args.uid}")
    print(f"  username={username!r}")
    print(f"  email={email}")
    print(f"  reason={args.reason!r}")

    if args.dry_run:
        print("DRY-RUN: would apply", update)
        return 0

    try:
        store.collection("users").document(args.uid).update(update)
    except Exception as e:
        print(f"ERROR: archive persist failed: {e}")
        logger.warning("archive_user persist failed uid=%s: %s", args.uid, e)
        return 1

    print(f"✓ Archived uid={args.uid}")
    logger.info("Archived uid=%s username=%s reason=%s", args.uid, username, args.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
