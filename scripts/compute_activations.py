#!/usr/bin/env python3
"""Daily activation computation.

Reads SQLite events from data/analytics.db and computes which families
have activated. A family is activated when both of these are true:

  1. They have at least one play_complete event ("first personalized
     story" proxy — see semantic note below).
  2. They have a separate-day return event within 7 days, restricted
     to play_start / play_complete / play_resume. Page navigation
     alone does not qualify — we want "family came back and played
     something", not "page loaded on day 2".

Idempotent via the activated_families table — re-running never
double-fires. Failed PostHog emissions leave fired_to_posthog=0
for retry on the next run.

Activation criterion semantic note: until Phase 1 creator stream
ships, "first personalized story" uses first play_complete as proxy.
When real generation endpoints exist (kid submits prompt -> server
generates), this script's first-event query graduates to
personalized_story_requested + day-2 return.
"""

from __future__ import annotations

import os
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

# Make the app package importable when run from cron.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from app.utils.logger import get_logger  # noqa: E402
from app.services.analytics_posthog import emit_event, flush  # noqa: E402

logger = get_logger("compute_activations")

DB_PATH = REPO_ROOT / "data" / "analytics.db"
RETURN_EVENTS = ("play_start", "play_complete", "play_resume")
WINDOW_DAYS = 7


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activated_families (
            family_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            first_play_complete_at TEXT NOT NULL,
            return_event_at TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            fired_to_posthog INTEGER DEFAULT 0,
            fired_at TEXT
        )
        """
    )
    conn.commit()


def _load_username_to_family_id() -> Dict[str, str]:
    """Read username -> family_id mapping from LocalStore."""
    try:
        from app.services.local_store import get_local_store
    except Exception as e:
        logger.error("Failed to import LocalStore: %s", e)
        return {}

    try:
        store = get_local_store()
        coll = store.collection("users")
    except Exception as e:
        logger.error("Failed to open LocalStore users collection: %s", e)
        return {}

    docs = None
    for method in ("stream", "get", "list_documents"):
        if hasattr(coll, method):
            try:
                docs = list(getattr(coll, method)())
                break
            except Exception:
                continue

    if docs is None:
        logger.error("LocalStore users collection has no usable read method")
        return {}

    mapping: Dict[str, str] = {}
    for d in docs:
        data = d.to_dict() if hasattr(d, "to_dict") else d
        if not isinstance(data, dict):
            continue
        uname = data.get("username")
        fid = data.get("family_id")
        if uname and fid:
            mapping[uname] = fid
    logger.info("Loaded %d username->family_id mappings", len(mapping))
    return mapping


def _candidate_families(conn: sqlite3.Connection) -> Iterable[Tuple[str, str]]:
    cur = conn.execute(
        """
        SELECT username, MIN(timestamp) AS first_complete
        FROM events
        WHERE event = 'play_complete'
          AND username IS NOT NULL AND username <> ''
        GROUP BY username
        """
    )
    for row in cur.fetchall():
        yield row["username"], row["first_complete"]


def _find_return_event(
    conn: sqlite3.Connection, username: str, first_complete_iso: str
) -> Optional[str]:
    placeholders = ",".join("?" for _ in RETURN_EVENTS)
    cur = conn.execute(
        f"""
        SELECT MIN(timestamp) AS return_ts
        FROM events
        WHERE username = ?
          AND event IN ({placeholders})
          AND date(timestamp) > date(?)
          AND date(timestamp) <= date(?, '+{WINDOW_DAYS} days')
        """,
        (username, *RETURN_EVENTS, first_complete_iso, first_complete_iso),
    )
    row = cur.fetchone()
    return row["return_ts"] if row and row["return_ts"] else None


def main() -> int:
    if not DB_PATH.exists():
        logger.warning("Analytics DB not found at %s — nothing to do", DB_PATH)
        return 0

    user_to_fid = _load_username_to_family_id()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_table(conn)

        new_activations = 0
        skipped_no_fid = 0
        skipped_already_fired = 0

        for username, first_complete in _candidate_families(conn):
            fid = user_to_fid.get(username)

            existing = conn.execute(
                "SELECT fired_to_posthog FROM activated_families "
                "WHERE family_id = ? OR username = ?",
                (fid or "", username),
            ).fetchone()
            if existing and existing["fired_to_posthog"]:
                skipped_already_fired += 1
                continue

            return_ts = _find_return_event(conn, username, first_complete)
            if not return_ts:
                continue

            if not fid:
                logger.warning(
                    "username=%s qualifies but has no family_id "
                    "(skipping; will retry once backfilled)",
                    username,
                )
                skipped_no_fid += 1
                continue

            try:
                first_dt = datetime.fromisoformat(first_complete.replace("Z", "+00:00"))
                return_dt = datetime.fromisoformat(return_ts.replace("Z", "+00:00"))
                days_to_activate = (return_dt - first_dt).days
            except Exception:
                days_to_activate = None

            emit_event(
                fid,
                "activated_family",
                {
                    "first_play_complete_at": first_complete,
                    "return_event_at": return_ts,
                    "days_to_activate": days_to_activate,
                },
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO activated_families
                  (family_id, username, first_play_complete_at, return_event_at,
                   activated_at, fired_to_posthog, fired_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(family_id) DO UPDATE SET
                  fired_to_posthog = 1,
                  fired_at = excluded.fired_at,
                  return_event_at = excluded.return_event_at,
                  activated_at = excluded.activated_at
                """,
                (fid, username, first_complete, return_ts, return_ts, now_iso),
            )
            conn.commit()
            new_activations += 1
            logger.info(
                "Activated: family_id=%s username=%s days=%s",
                fid, username, days_to_activate,
            )

        flush()

        logger.info(
            "compute_activations done — new=%d skipped_no_fid=%d already_fired=%d",
            new_activations, skipped_no_fid, skipped_already_fired,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
