#!/usr/bin/env python3
"""Backfill per-source entitlement state. Tier-preserving.

  --dry-run   report each user's bucket (incl. AMBIGUOUS context); no writes
  --verify    assert post-backfill projected tier == current cached tier for
              ALL users + no unresolved AMBIGUOUS + premium_in==premium_out;
              exit 1 on any failure
  --apply     write entitlements.comp for comp-bucket users; HALT on AMBIGUOUS

Run on prod from /opt/dreamweaver-backend with .env sourced. Snapshot first.
"""
from __future__ import annotations
import argparse, os, sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT); sys.path.insert(0, str(REPO_ROOT))

from app.utils.entitlements import stripe_active, compute_tier  # noqa: E402

REASON = "backfill-comp-2026-06-19"


def classify(user: dict, now: datetime) -> str:
    if (user.get("subscription_tier") or "free") != "premium":
        return "free"
    if stripe_active(user, now):
        return "stripe"
    if not user.get("stripe_customer_id"):
        return "comp"
    return "ambiguous"


def plan_backfill(users: dict, now: datetime, halt_on_ambiguous: bool = False) -> dict:
    updates, ambiguous = {}, []
    for uid, u in users.items():
        bucket = classify(u, now)
        if bucket == "comp":
            updates[uid] = {"entitlements": {**(u.get("entitlements") or {}),
                "comp": {"status": "active", "expires": None,
                         "reason": REASON, "granted_at": now.isoformat()}}}
        elif bucket == "ambiguous":
            ambiguous.append(uid)
    if ambiguous and halt_on_ambiguous:
        print(f"HALT: {len(ambiguous)} AMBIGUOUS users need hand-review: {ambiguous}")
        raise SystemExit(2)
    return updates


def assert_tier_preserved(users: dict, now: datetime) -> None:
    bad = [uid for uid, u in users.items()
           if compute_tier(u, now) != (u.get("subscription_tier") or "free")]
    if bad:
        raise AssertionError(f"tier changed for {len(bad)} users: {bad[:20]}")


def verify_report(users: dict, now: datetime):
    """Pure equivalence check. Returns (ok: bool, reasons: list[str])."""
    reasons = []
    sim = {uid: dict(u) for uid, u in users.items()}
    for uid, upd in plan_backfill(sim, now).items():
        sim[uid].update(upd)
    changed = [uid for uid, u in sim.items()
               if compute_tier(u, now) != (users[uid].get("subscription_tier") or "free")]
    if changed:
        reasons.append(f"tier changed for {len(changed)}: {changed[:20]}")
    amb = [uid for uid, u in users.items() if classify(u, now) == "ambiguous"]
    if amb:
        reasons.append(f"{len(amb)} AMBIGUOUS unresolved: {amb[:20]}")
    premium_in = sum(1 for u in users.values() if (u.get("subscription_tier") or "free") == "premium")
    premium_out = sum(1 for u in sim.values() if compute_tier(u, now) == "premium")
    if premium_in != premium_out:
        reasons.append(f"premium_in={premium_in} premium_out={premium_out}")
    return (len(reasons) == 0, reasons)


def _load_users():
    from app.services.local_store import get_local_store
    store = get_local_store()
    out = {}
    for doc in store.collection("users").get():
        d = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if isinstance(d, dict):
            out[d.get("uid") or d.get("id")] = d
    return out, store


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    users, store = _load_users()

    buckets = {}
    for uid, u in users.items():
        buckets.setdefault(classify(u, now), []).append(uid)
    premium_in = sum(1 for u in users.values() if (u.get("subscription_tier") or "free") == "premium")

    if args.dry_run:
        for b in ("free", "stripe", "comp", "ambiguous"):
            print(f"{b}: {len(buckets.get(b, []))}")
        for uid in buckets.get("ambiguous", []):
            u = users[uid]
            print(f"  AMBIGUOUS uid={uid} username={u.get('username')} "
                  f"status={u.get('subscription_status')} period_end={u.get('current_period_end')} "
                  f"customer={u.get('stripe_customer_id')}")
        for uid in buckets.get("comp", []):
            print(f"  COMP uid={uid} username={users[uid].get('username')} -> perpetual")
        print(f"premium_in={premium_in}")
        return 0

    if args.verify:
        ok, reasons = verify_report(users, now)
        if not ok:
            for r in reasons:
                print(f"VERIFY FAILED: {r}")
            return 1
        print(f"VERIFY OK: tier preserved for all {len(users)} users; premium={premium_in}")
        return 0

    if args.apply:
        updates = plan_backfill(users, now, halt_on_ambiguous=True)
        for uid, upd in updates.items():
            store.collection("users").document(uid).update(upd)
            from app.dependencies import _local_users
            if uid in _local_users:
                _local_users[uid].update(upd)
        for uid, upd in updates.items():
            users[uid].update(upd)
        assert_tier_preserved(users, now)
        print(f"APPLIED comp source to {len(updates)} users; tier preserved.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
