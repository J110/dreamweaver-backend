#!/usr/bin/env python3
"""Phase 0 magic-link auth migration — token revocation script.

Spec: docs/specs/auth-magic-link-v1.md §12 (migration script).

Pre-flight check (refuses to run if violated):
  Enumerates monthly-active users (any event in data/analytics.db within
  the last 30 days). For each, looks up the user record and verifies the
  `email` field is present and non-null. If any are missing, prints the
  list and exits 1. Override via --override (intentional orphaning).

Revocation:
  Iterates every row in `tokens` collection where revoked_at IS NULL,
  sets revoked_at + revocation_reason="phase0_auth_migration". Prints
  count of rows revoked and (if --override) which usernames were
  intentionally orphaned. Idempotent — re-running revokes nothing new.

Migration marker:
  Writes data/migration_marker.json with migration_started_at and
  migration_window_ends_at (30 days later). Gates the verbose-logging
  branch in app/services/magic_link.py: while the marker is present and
  in-window, login_existing email-mismatches log at WARNING level so
  support can identify stuck legacy users without leaking enumeration
  to clients.

Usage (run from /opt/dreamweaver-backend on prod, with .env sourced):

    cd /opt/dreamweaver-backend
    set -a && . ./.env && set +a
    /usr/bin/python3 scripts/invalidate_old_tokens.py [--override]

The pre-deploy outreach step (spec §3 / Outstanding pre-deploy
decisions) is REQUIRED before this script runs. Each monthly-active
user must have their email pre-populated on their record. Failing to
do so will trigger the pre-flight refusal — by design.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the app package importable when run from cron / systemd / shell.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("invalidate_old_tokens")

ANALYTICS_DB_PATH = REPO_ROOT / "data" / "analytics.db"
MIGRATION_MARKER_PATH = REPO_ROOT / "data" / "migration_marker.json"
MIGRATION_WINDOW_DAYS = 30
ACTIVE_LOOKBACK_DAYS = 30
REVOCATION_REASON = "phase0_auth_migration"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _monthly_active_usernames() -> list[str]:
    """Distinct usernames with at least one event in the last N days."""
    if not ANALYTICS_DB_PATH.exists():
        logger.warning("analytics.db not found at %s — assuming zero actives", ANALYTICS_DB_PATH)
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ACTIVE_LOOKBACK_DAYS)).date().isoformat()
    conn = sqlite3.connect(str(ANALYTICS_DB_PATH))
    try:
        rows = conn.execute(
            "SELECT DISTINCT username FROM events "
            "WHERE username IS NOT NULL AND username <> '' AND date >= ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return sorted({r[0] for r in rows if r[0]})


def _users_missing_email(usernames: list[str]) -> list[tuple[str, str]]:
    """For each active username, check user record for email. Return list of (username, uid) missing it.

    Phase 0 step 1.5e: case-insensitive lookup via username_lowercase
    with case-sensitive fallback for un-backfilled records. Without
    this, an analytics event username 'Meethi' wouldn't match a user
    record stored under 'meethi' — that mismatch was the latent bug
    that motivated the case-insensitive fix.
    """
    from app.services.local_store import get_local_store

    store = get_local_store()
    missing: list[tuple[str, str]] = []
    for username in usernames:
        target = (username or "").lower()
        rows = []
        try:
            rows = list(store.collection("users").where("username_lowercase", "==", target).get())
        except Exception:
            rows = []
        if not rows:
            # Fallback for un-backfilled records.
            try:
                rows = list(store.collection("users").where("username", "==", username).get())
            except Exception as e:
                logger.warning("user lookup failed for %s: %s", username, e)
                continue
        found = False
        for doc in rows:
            data = doc.to_dict() if hasattr(doc, "to_dict") else doc
            if not isinstance(data, dict):
                continue
            # Match on either canonical or display field; either side may be the legacy gap.
            uname = data.get("username") or ""
            ulc = data.get("username_lowercase") or uname.lower()
            if ulc != target and uname != username:
                continue
            # Skip already-tombstoned records (Phase 0 step 1.5e merge tombstones).
            if data.get("archived"):
                continue
            found = True
            email = data.get("email")
            if not email:
                missing.append((username, data.get("uid") or data.get("id") or "?"))
            break
        if not found:
            # Active in analytics but no user record — record-less ghost.
            # Treat as missing-email for safety; --override required to proceed.
            missing.append((username, "<no user record>"))
    return missing


def _revoke_all_tokens() -> tuple[int, int]:
    """Iterate tokens collection, revoke any with revoked_at IS NULL.

    Returns (revoked_now, already_revoked).
    """
    from app.services.local_store import get_local_store

    store = get_local_store()
    revoked_now = 0
    already_revoked = 0
    try:
        token_docs = store.collection("tokens").get()
    except Exception as e:
        logger.error("failed to enumerate tokens: %s", e)
        return (0, 0)

    now_iso = _now_iso()
    for doc in token_docs:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        token = data.get("token") or data.get("id")
        if not token:
            continue
        if data.get("revoked_at"):
            already_revoked += 1
            continue
        try:
            store.collection("tokens").document(token).update({
                "revoked_at": now_iso,
                "revocation_reason": REVOCATION_REASON,
            })
            revoked_now += 1
        except Exception as e:
            logger.warning("failed to revoke token: %s", e)
    return (revoked_now, already_revoked)


def _write_migration_marker() -> None:
    started = datetime.now(timezone.utc)
    ends = started + timedelta(days=MIGRATION_WINDOW_DAYS)
    payload = {
        "migration_started_at": started.isoformat(),
        "migration_window_ends_at": ends.isoformat(),
        "reason": REVOCATION_REASON,
    }
    MIGRATION_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MIGRATION_MARKER_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    logger.info("Wrote migration marker → %s", MIGRATION_MARKER_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="invalidate_old_tokens",
        description=(
            "Phase 0 magic-link auth migration: revoke all bearer tokens, "
            "force /auth/claim flow on next app open. "
            "Pre-deploy outreach REQUIRED. See spec section 3 — Outstanding "
            "pre-deploy decisions. Each monthly-active user needs email "
            "pre-populated on their record before this script runs."
        ),
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help=(
            "Explicit acknowledgment: proceed with revocation even if some "
            "monthly-active users lack email. Those users will be orphaned "
            "(their tokens revoke; on next /login they'll appear as new "
            "users and lose existing data). Required only if pre-flight fails."
        ),
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 0 magic-link auth migration — token revocation")
    print("=" * 60)

    # Pre-flight
    print(f"\nEnumerating monthly-active users (last {ACTIVE_LOOKBACK_DAYS} days)...")
    actives = _monthly_active_usernames()
    print(f"  {len(actives)} distinct usernames active.")

    print("\nChecking email field on each active user record...")
    missing = _users_missing_email(actives)

    if missing:
        print(f"\n  ❌ {len(missing)} monthly-active user(s) lack an email field:")
        for username, uid in missing:
            print(f"     - {username} (uid={uid})")
        if not args.override:
            print(
                "\nREFUSING TO RUN — these users will be orphaned by the migration\n"
                "if their tokens are revoked before email is populated on their\n"
                "user records. Run the pre-deploy outreach + email-population\n"
                "step (spec §3 Outstanding pre-deploy decisions) first, OR\n"
                "re-invoke with --override if you've explicitly decided to\n"
                "orphan these users (e.g., couldn't be reached and accepting\n"
                "the loss).\n"
            )
            return 1
        print("\n  ⚠ --override set — proceeding with intentional orphaning.")
    else:
        print(f"  ✓ All {len(actives)} active users have email pre-populated.")

    # Revocation
    print("\nRevoking bearer tokens...")
    revoked_now, already_revoked = _revoke_all_tokens()
    print(f"  Revoked now:      {revoked_now}")
    print(f"  Already revoked:  {already_revoked}")

    # Migration marker
    print("\nWriting migration marker...")
    _write_migration_marker()
    print(f"  Window: now → +{MIGRATION_WINDOW_DAYS} days")
    print(f"  File:   {MIGRATION_MARKER_PATH}")

    # Post-mortem trail for orphans
    if args.override and missing:
        print("\n--- Intentionally orphaned (--override) ---")
        for username, uid in missing:
            print(f"  - {username} (uid={uid})")
        print("---------------------------------------------")

    print("\nDone. Next step: frontend deploy (Phase 4) — users hit 401 on next request → /login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
