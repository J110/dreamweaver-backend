#!/usr/bin/env python3
"""Merge a username collision group (case-insensitive).

Phase 0 step 1.5e. Targeted manual tool. Run
find_username_collisions.py first to inspect what would be merged.

Usage:
    cd /opt/dreamweaver-backend
    /usr/bin/python3 scripts/merge_username_collisions.py --collision meethi             # dry-run
    /usr/bin/python3 scripts/merge_username_collisions.py --collision meethi --merge     # apply
    /usr/bin/python3 scripts/merge_username_collisions.py --collision meethi --verify    # post-merge check

Canonical heuristic (in order):
    1. Older created_at wins.
    2. Tie → more events wins.
    3. Tie → lower uid wins (deterministic).

Behavior on --merge:
    For each non-canonical (orphan) record in the collision group:
      a. UPDATE analytics.db: events SET username = canonical_username
         WHERE username = orphan_username
      b. UPDATE LocalStore tokens: tokens.uid = canonical_uid
         WHERE tokens.uid = orphan_uid
      c. Field merge into canonical: each field present in orphan and
         null/missing in canonical is copied. Conflicts (both have a
         non-null value) are logged at WARNING; canonical wins.
      d. Tombstone orphan: archived=true, merged_into=canonical_uid,
         merged_at=now_iso. (LocalStore exposes no .delete(); tombstone
         preserves audit trail and is idempotent on re-run.)

Idempotent: re-running with --merge is a no-op once orphans are
tombstoned (archived=true filters them out of the collision group).

--verify post-merge invariants:
    * analytics.db: 0 events where username = orphan_username
    * users: orphan record has archived=true, merged_into=<canonical_uid>
    * tokens: 0 tokens where uid = orphan_uid AND revoked_at IS NULL
    Exit 1 on any FAIL.

Out of scope: Stripe Customer records and PostHog Person profiles
stay distinct. Canonical's stripe_customer_id (if any) becomes the
billing identity going forward; orphan's customer (if any) is
orphaned in Stripe (owner can delete it manually if desired).
PostHog keys events on family_id, which is preserved on canonical.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("merge_username_collisions")

ANALYTICS_DB_PATH = REPO_ROOT / "data" / "analytics.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_count(username: str) -> int:
    if not ANALYTICS_DB_PATH.exists() or not username:
        return 0
    try:
        conn = sqlite3.connect(str(ANALYTICS_DB_PATH))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE username = ?", (username,)
            ).fetchone()
            return int(row[0] if row else 0)
        finally:
            conn.close()
    except Exception:
        return 0


def _gather_collision_group(store, key_lc: str) -> list[dict]:
    """Return all non-tombstoned user records whose username.lower() == key_lc."""
    out: list[dict] = []
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        logger.error("cannot enumerate users: %s", e)
        return out
    for doc in users:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        if data.get("archived"):
            continue
        username = data.get("username") or ""
        if not username:
            continue
        if username.lower() == key_lc:
            out.append(data)
    return out


def _pick_canonical(records: list[dict]) -> dict:
    """older created_at > more events > lower uid (deterministic tiebreak)."""
    def sort_key(r: dict):
        ca = str(r.get("created_at") or "9999-12-31T00:00:00")
        # Negate event count so larger events sort first within the same created_at
        events = -_event_count(r.get("username") or "")
        uid = str(r.get("uid") or r.get("id") or "")
        return (ca, events, uid)
    return sorted(records, key=sort_key)[0]


def _field_merge(canonical: dict, orphan: dict) -> tuple[dict, list[str]]:
    """Compute field updates to apply to canonical from orphan.

    Returns (update_dict, conflict_log).
    For each field in orphan:
      - if canonical's value is None/missing, copy from orphan
      - if both have non-null values that differ, log conflict (canonical wins)
      - skip identity/system fields that must not be overwritten
    """
    SKIP = {"uid", "id", "username", "username_lowercase", "created_at", "archived", "merged_into", "merged_at"}
    update: dict = {}
    conflicts: list[str] = []
    for k, v in (orphan or {}).items():
        if k in SKIP:
            continue
        cv = canonical.get(k) if canonical else None
        if cv in (None, ""):
            if v not in (None, ""):
                update[k] = v
        elif v not in (None, "") and v != cv:
            conflicts.append(f"{k}: canonical={cv!r} orphan={v!r} (canonical wins)")
    return update, conflicts


def _migrate_events(orphan_username: str, canonical_username: str, dry_run: bool) -> int:
    """UPDATE events SET username = canonical WHERE username = orphan. Returns row count."""
    if not ANALYTICS_DB_PATH.exists():
        return 0
    conn = sqlite3.connect(str(ANALYTICS_DB_PATH))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM events WHERE username = ?", (orphan_username,)
        ).fetchone()[0]
        if dry_run:
            return int(n)
        conn.execute(
            "UPDATE events SET username = ? WHERE username = ?",
            (canonical_username, orphan_username),
        )
        conn.commit()
        return int(n)
    finally:
        conn.close()


def _migrate_tokens(store, orphan_uid: str, canonical_uid: str, dry_run: bool) -> int:
    """UPDATE tokens SET uid = canonical_uid WHERE uid = orphan_uid. Returns row count."""
    moved = 0
    try:
        token_docs = list(store.collection("tokens").get())
    except Exception as e:
        logger.warning("cannot enumerate tokens: %s", e)
        return 0
    for doc in token_docs:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        if data.get("uid") != orphan_uid:
            continue
        moved += 1
        if dry_run:
            continue
        token = data.get("token") or data.get("id")
        if not token:
            continue
        try:
            store.collection("tokens").document(token).update({"uid": canonical_uid})
        except Exception as e:
            logger.warning("token re-key failed token=%s: %s", token[:12], e)
    return moved


def _apply_merge(store, canonical: dict, orphan: dict, dry_run: bool) -> dict:
    """Run the merge for a single (canonical, orphan) pair. Return summary."""
    canonical_uid = canonical.get("uid") or canonical.get("id")
    canonical_username = canonical.get("username")
    orphan_uid = orphan.get("uid") or orphan.get("id")
    orphan_username = orphan.get("username")

    print(f"\n  Merging orphan {orphan_username!r} (uid={orphan_uid}) → canonical {canonical_username!r} (uid={canonical_uid})")

    # 1. Events
    events_moved = _migrate_events(orphan_username, canonical_username, dry_run)
    print(f"    {'DRY-RUN: would update' if dry_run else 'Updated'} {events_moved} analytics.db event row(s) (username '{orphan_username}' → '{canonical_username}')")

    # 2. Tokens
    tokens_moved = _migrate_tokens(store, orphan_uid, canonical_uid, dry_run)
    print(f"    {'DRY-RUN: would re-key' if dry_run else 'Re-keyed'} {tokens_moved} tokens row(s) (uid '{orphan_uid}' → '{canonical_uid}')")

    # 3. Field merge
    update, conflicts = _field_merge(canonical, orphan)
    if update:
        print(f"    {'DRY-RUN: would copy' if dry_run else 'Copying'} {len(update)} field(s) into canonical: {sorted(update.keys())}")
    if conflicts:
        print("    ⚠ field conflicts (canonical wins, orphan value lost):")
        for c in conflicts:
            print(f"        {c}")
    if update and not dry_run:
        try:
            store.collection("users").document(canonical_uid).update(update)
        except Exception as e:
            logger.warning("canonical field merge persist failed: %s", e)

    # 4. Tombstone orphan
    tombstone = {
        "archived": True,
        "merged_into": canonical_uid,
        "merged_at": _now_iso(),
    }
    if dry_run:
        print(f"    DRY-RUN: would tombstone orphan with {tombstone}")
    else:
        try:
            store.collection("users").document(orphan_uid).update(tombstone)
            print(f"    Tombstoned orphan: archived=True, merged_into={canonical_uid}")
        except Exception as e:
            logger.warning("orphan tombstone persist failed: %s", e)

    return {
        "events_moved": events_moved,
        "tokens_moved": tokens_moved,
        "fields_copied": len(update),
        "conflicts": len(conflicts),
    }


def _verify(store, key_lc: str) -> int:
    """Post-merge invariants. Exit code: 0 if all PASS, 1 on any FAIL."""
    print(f"\n=== --verify checks for collision '{key_lc}' ===")
    failures = 0

    # Find canonical (sole non-tombstoned record) and orphans (tombstoned)
    canonical = None
    orphans: list[dict] = []
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        print(f"  FAIL: cannot enumerate users: {e}")
        return 1
    for doc in users:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        username = data.get("username") or ""
        if username.lower() != key_lc:
            continue
        if data.get("archived"):
            orphans.append(data)
        else:
            if canonical is not None:
                print(f"  FAIL: multiple non-archived records for '{key_lc}' — merge incomplete")
                failures += 1
            canonical = data

    if canonical is None:
        print(f"  FAIL: no canonical record found for '{key_lc}'")
        return 1
    print(f"  Canonical: username={canonical.get('username')!r} uid={canonical.get('uid')}")

    if not orphans:
        print(f"  No orphans (no merge has been applied for this group).")
        return 0

    canonical_uid = canonical.get("uid")
    for orphan in orphans:
        orphan_username = orphan.get("username")
        orphan_uid = orphan.get("uid")
        print(f"  Orphan: username={orphan_username!r} uid={orphan_uid}")

        # Check 1: orphan tombstone fields
        if orphan.get("merged_into") != canonical_uid:
            print(f"    FAIL: orphan.merged_into={orphan.get('merged_into')!r} != canonical_uid={canonical_uid}")
            failures += 1
        else:
            print(f"    PASS: orphan tombstone correctly points at canonical")

        # Check 2: 0 events under orphan_username
        ev_count = _event_count(orphan_username)
        if ev_count > 0:
            print(f"    FAIL: {ev_count} events still under orphan username '{orphan_username}'")
            failures += 1
        else:
            print(f"    PASS: 0 events under orphan username")

        # Check 3: 0 unrevoked tokens at orphan_uid
        unrevoked = 0
        try:
            for doc in store.collection("tokens").get():
                data = doc.to_dict() if hasattr(doc, "to_dict") else doc
                if not isinstance(data, dict):
                    continue
                if data.get("uid") == orphan_uid and not data.get("revoked_at"):
                    unrevoked += 1
        except Exception as e:
            print(f"    FAIL: tokens enumeration failed: {e}")
            failures += 1
            continue
        if unrevoked > 0:
            print(f"    FAIL: {unrevoked} unrevoked tokens at orphan_uid")
            failures += 1
        else:
            print(f"    PASS: 0 unrevoked tokens at orphan_uid")

    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="merge_username_collisions",
        description=(
            "Merge a username collision group. Dry-run by default; "
            "--merge applies; --verify checks post-merge invariants."
        ),
    )
    parser.add_argument(
        "--collision",
        required=True,
        help="The lowercase collision key (e.g. 'meethi' for the Meethi/meethi pair).",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Apply the merge. Without this flag the script is dry-run.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run post-merge verification only. Mutually exclusive with --merge.",
    )
    args = parser.parse_args()

    if args.merge and args.verify:
        print("ERROR: --merge and --verify are mutually exclusive.")
        return 2

    from app.services.local_store import get_local_store
    store = get_local_store()
    key_lc = args.collision.strip().lower()

    if args.verify:
        return _verify(store, key_lc)

    records = _gather_collision_group(store, key_lc)
    if not records:
        print(f"No non-tombstoned records found for collision '{key_lc}'.")
        return 0
    if len(records) < 2:
        print(f"Only {len(records)} non-tombstoned record(s) for '{key_lc}' — nothing to merge.")
        for r in records:
            print(f"  - username={r.get('username')!r} uid={r.get('uid')}")
        return 0

    canonical = _pick_canonical(records)
    canonical_uid = canonical.get("uid") or canonical.get("id")
    canonical_username = canonical.get("username")
    orphans = [r for r in records if (r.get("uid") or r.get("id")) != canonical_uid]

    print("=" * 60)
    print(f"Collision group: '{key_lc}'  ({len(records)} records)")
    print("=" * 60)
    print(f"\n  Canonical pick: username={canonical_username!r} uid={canonical_uid}")
    print(f"    created_at={canonical.get('created_at')}  events={_event_count(canonical_username)}")
    print(f"    family_id={canonical.get('family_id')}  email={canonical.get('email')}")
    print(f"\n  {len(orphans)} orphan(s) will be merged into canonical:")
    for o in orphans:
        print(f"    - username={o.get('username')!r} uid={o.get('uid')} created_at={o.get('created_at')} events={_event_count(o.get('username') or '')}")

    if not args.merge:
        print("\n  DRY RUN — no changes applied. Re-run with --merge to apply.")

    summaries = []
    for orphan in orphans:
        summaries.append(_apply_merge(store, canonical, orphan, dry_run=not args.merge))

    print("\n--- Summary ---")
    print(f"  Orphans processed:  {len(orphans)}")
    print(f"  Events moved:       {sum(s['events_moved'] for s in summaries)}")
    print(f"  Tokens re-keyed:    {sum(s['tokens_moved'] for s in summaries)}")
    print(f"  Fields copied:      {sum(s['fields_copied'] for s in summaries)}")
    print(f"  Field conflicts:    {sum(s['conflicts'] for s in summaries)}")
    if not args.merge:
        print("\nDRY RUN — re-run with --merge to apply.")
    else:
        print(f"\nMerge applied. Run with --verify to check post-merge invariants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
