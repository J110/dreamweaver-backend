#!/usr/bin/env python3
"""List username collisions in the users collection (case-insensitive).

Phase 0 step 1.5e safety check — read-only. Run BEFORE
merge_username_collisions.py to confirm what would be merged.

A collision group is two or more user records whose usernames differ
only by case (e.g. "Meethi" + "meethi"). Each group is listed with
per-record context (created_at, family_id, stripe_customer_id) so the
operator can pick the canonical record before invoking the merge tool.

Tombstoned records (archived=true, set by the merge tool) are skipped.

Usage:
    cd /opt/dreamweaver-backend
    /usr/bin/python3 scripts/find_username_collisions.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

ANALYTICS_DB_PATH = REPO_ROOT / "data" / "analytics.db"


def _event_count(username: str) -> int:
    """Count events.db rows for an exact-match username (case-sensitive)."""
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


def main() -> int:
    from app.services.local_store import get_local_store

    store = get_local_store()
    by_lc: dict[str, list[dict]] = {}
    try:
        users = list(store.collection("users").get())
    except Exception as e:
        print(f"ERROR: cannot enumerate users: {e}")
        return 1

    for doc in users:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        if data.get("archived"):
            # Skip tombstoned records (already-merged orphans).
            continue
        username = data.get("username") or ""
        if not username:
            continue
        by_lc.setdefault(username.lower(), []).append(data)

    collisions = {lc: rows for lc, rows in by_lc.items() if len(rows) > 1}
    if not collisions:
        print("No username collisions found.")
        return 0

    print(f"Found {len(collisions)} collision group(s):\n")
    for lc, rows in sorted(collisions.items(), key=lambda x: -len(x[1])):
        print(f"  '{lc}' ({len(rows)} records):")
        # Sort by created_at ascending so the operator can eyeball "older first"
        # for the canonical heuristic (older > more events > lower uid).
        rows_sorted = sorted(rows, key=lambda r: (str(r.get("created_at") or ""), r.get("uid") or ""))
        for r in rows_sorted:
            uid = r.get("uid") or r.get("id") or "?"
            ca = r.get("created_at") or "?"
            fam = r.get("family_id") or "(none)"
            stripe = r.get("stripe_customer_id") or "(none)"
            email = r.get("email") or "(none)"
            uname = r.get("username")
            ev = _event_count(uname)
            print(f"    - username={uname!r}  uid={uid}")
            print(f"      created_at={ca}  events={ev}")
            print(f"      family_id={fam}  stripe_customer={stripe}  email={email}")
        print()

    print("Run merge_username_collisions.py --collision <key> to merge a group.")
    print("Pre-merge dry-run is the default; --merge applies; --verify checks post-merge invariants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
