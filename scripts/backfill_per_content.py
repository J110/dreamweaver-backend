#!/usr/bin/env python3
"""Backfill per-content JSON files from a master content.json.

Implements spec §2d, §3.1, and §3.1d. After this script runs, every entry
in `seed_output/content.json` has a corresponding per-content file at
`data/<type>[_hi]/<id>.json`, and every orphan per-content file (not in
the master) is moved to `data/_quarantine/<type>[_hi]/<id>.json` for
human triage via `scripts/triage_quarantine.py`.

Behavior:
  - Reads the source content.json (default: seed_output/content.json)
  - For each entry, routes to the target per-(type, lang) directory using
    the same logic the LocalStore walker uses (PER_CONTENT_DIRS in
    app.services.local_store)
  - Strips the `subtype` field before writing — per Open Question 3
    decision, subtype is walker-stamped from directory placement
  - Atomic writes: tempfile + os.fsync + os.replace (spec §2e.1)
  - Idempotent: existing per-content files are skipped unless --overwrite
  - Hard-error gates: per-bucket count match + per-item presence check
  - Orphan handling: per-content files not in source → moved to
    data/_quarantine/<type>[_hi]/<id>.json (gate 4 per §3.1d)

Usage:
  python3 scripts/backfill_per_content.py                     # default run
  python3 scripts/backfill_per_content.py --dry-run           # report only
  python3 scripts/backfill_per_content.py --overwrite         # force-rewrite
  python3 scripts/backfill_per_content.py --source ./snap.json --data-dir /tmp/test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.local_store import (  # noqa: E402
    PER_CONTENT_DIRS,
    _atomic_write_json,
    _content_target_dir,
)


# ── Routing & counts ───────────────────────────────────────────────────────


def _bucket_for_item(data_dir: Path, item: dict) -> Optional[str]:
    """Return the bucket name (e.g. 'stories', 'lullabies_hi') for an item.

    None if no PER_CONTENT_DIRS rule matches the item's (type, subtype, lang).
    """
    target = _content_target_dir(data_dir, item)
    if target is None:
        return None
    return target.name


def _expected_per_bucket(items: list[dict], data_dir: Path) -> tuple[Counter, list[dict]]:
    """Categorize source items into expected buckets.

    Returns (Counter of bucket → count, list of unrouted items).
    """
    counts: Counter = Counter()
    unrouted: list[dict] = []
    for item in items:
        bucket = _bucket_for_item(data_dir, item)
        if bucket is None:
            unrouted.append(item)
        else:
            counts[bucket] += 1
    return counts, unrouted


def _on_disk_per_bucket(data_dir: Path) -> Counter:
    """Count *.json files per bucket directory (ignoring _quarantine)."""
    counts: Counter = Counter()
    for subdir, _, _, _ in PER_CONTENT_DIRS:
        d = data_dir / subdir
        if d.is_dir():
            counts[subdir] = sum(
                1 for _ in d.glob("*.json") if not _.name.endswith(".json.tmp")
            )
    return counts


# ── Backfill loop ──────────────────────────────────────────────────────────


def backfill(
    source: Path,
    data_dir: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run the backfill. Returns a summary dict.

    summary keys:
      created: int (files written)
      skipped_exists: int (already present, --overwrite=False)
      skipped_overwritten: int (already present, --overwrite=True, rewritten)
      errors: list[(item_id, str)]
      unrouted: list[item_id]
      orphans_moved: list[(src_path, dst_quarantine_path)]
      bucket_counts_expected: dict[str, int]
      bucket_counts_actual: dict[str, int]
      gate1_pass: bool   (per-bucket + total count match)
      gate2_pass: bool   (every source item has a per-content file)
      gate2_misses: list[item_id]
    """
    if not source.exists():
        raise FileNotFoundError(f"source content.json not found at {source}")

    items = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        # Some legacy snapshots wrap items in {"items": [...]}; tolerate that
        if isinstance(items, dict) and "items" in items:
            items = items["items"]
        else:
            raise ValueError(
                f"unexpected content.json shape; expected list, got {type(items).__name__}"
            )

    summary = {
        "created": 0,
        "skipped_exists": 0,
        "skipped_overwritten": 0,
        "errors": [],
        "unrouted": [],
        "orphans_moved": [],
        "bucket_counts_expected": {},
        "bucket_counts_actual": {},
        "gate1_pass": False,
        "gate2_pass": False,
        "gate2_misses": [],
    }

    # ── Pre-pass: route all items, identify unroutable upfront ────────────
    expected_counts, unrouted = _expected_per_bucket(items, data_dir)
    summary["bucket_counts_expected"] = dict(expected_counts)
    summary["unrouted"] = [item.get("id", "<no id>") for item in unrouted]

    if unrouted and not dry_run:
        # We still continue to write the routable items, but the report
        # surfaces unrouted as errors (gate 1 will fail anyway).
        for item in unrouted:
            summary["errors"].append(
                (item.get("id", "<no id>"),
                 f"no PER_CONTENT_DIRS rule for type={item.get('type')!r} "
                 f"subtype={item.get('subtype')!r} lang={item.get('lang')!r}")
            )

    # ── Backfill loop ──────────────────────────────────────────────────────
    for item in items:
        item_id = item.get("id")
        if not item_id:
            summary["errors"].append(("<no id>", "item missing 'id' field"))
            continue

        target_dir = _content_target_dir(data_dir, item)
        if target_dir is None:
            # Already counted in unrouted; skip
            continue

        path = target_dir / f"{item_id}.json"
        exists = path.exists()

        if exists and not overwrite:
            summary["skipped_exists"] += 1
            continue

        if dry_run:
            if exists:
                summary["skipped_overwritten"] += 1
            else:
                summary["created"] += 1
            continue

        # Strip subtype before writing — Open Question 3 (walker-stamped).
        # _atomic_write_json with strip_subtype=True does this.
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(path, item, strip_subtype=True)
            if exists:
                summary["skipped_overwritten"] += 1
            else:
                summary["created"] += 1
        except Exception as e:
            summary["errors"].append((item_id, f"write failed: {e}"))

    # ── Gate 1: per-bucket + total count match ─────────────────────────────
    # In dry-run mode the gates evaluate against the pre-run disk state,
    # which would always FAIL when fresh per-content dirs are empty.
    # Mark gates as None so the report displays N/A instead of misleading FAIL.
    actual_counts = _on_disk_per_bucket(data_dir)
    summary["bucket_counts_actual"] = dict(actual_counts)
    summary["dry_run"] = dry_run

    if dry_run:
        summary["gate1_pass"] = None  # not evaluated
        summary["gate2_pass"] = None
        summary["gate2_misses"] = []
    else:
        gate1_pass = True
        for subdir, _, _, _ in PER_CONTENT_DIRS:
            if expected_counts.get(subdir, 0) != actual_counts.get(subdir, 0):
                gate1_pass = False
                break
        if sum(expected_counts.values()) != sum(actual_counts.values()):
            gate1_pass = False
        summary["gate1_pass"] = gate1_pass

        # ── Gate 2: per-item presence check ────────────────────────────────
        misses: list[str] = []
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            target_dir = _content_target_dir(data_dir, item)
            if target_dir is None:
                misses.append(item_id)
                continue
            if not (target_dir / f"{item_id}.json").exists():
                misses.append(item_id)
        summary["gate2_pass"] = not misses
        summary["gate2_misses"] = misses

    # ── Gate 4: orphan quarantine ──────────────────────────────────────────
    source_ids = {item.get("id") for item in items if item.get("id")}
    quarantine_root = data_dir / "_quarantine"
    for subdir, _, _, _ in PER_CONTENT_DIRS:
        d = data_dir / subdir
        if not d.is_dir():
            continue
        for fp in d.glob("*.json"):
            if fp.name.endswith(".json.tmp"):
                continue
            file_id = fp.stem
            # Try to read the embedded id; tolerant of malformed JSON
            try:
                body = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(body, dict) and body.get("id"):
                    file_id = body["id"]
            except Exception:
                pass
            if file_id in source_ids:
                continue
            # Orphan: not in source. Move to quarantine.
            dst_dir = quarantine_root / subdir
            dst = dst_dir / fp.name
            if dry_run:
                summary["orphans_moved"].append((str(fp), str(dst)))
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(str(fp), str(dst))
                summary["orphans_moved"].append((str(fp), str(dst)))
            except OSError as e:
                summary["errors"].append((file_id, f"orphan move failed: {e}"))

    return summary


# ── Reporting ──────────────────────────────────────────────────────────────


def _print_report(summary: dict, source_total: int) -> None:
    print()
    print("=" * 60)
    print("BACKFILL REPORT")
    print("=" * 60)

    print()
    print(f"Source items: {source_total}")
    print(f"  created:             {summary['created']}")
    print(f"  skipped (existing):  {summary['skipped_exists']}")
    print(f"  rewrote (--overwrite): {summary['skipped_overwritten']}")
    print(f"  errors:              {len(summary['errors'])}")
    print(f"  unrouted:            {len(summary['unrouted'])}")

    print()
    print("Per-bucket counts:")
    print(f"  {'bucket':<22} {'expected':>10} {'actual':>10}  status")
    for subdir, _, _, _ in PER_CONTENT_DIRS:
        exp = summary["bucket_counts_expected"].get(subdir, 0)
        act = summary["bucket_counts_actual"].get(subdir, 0)
        status = "ok" if exp == act else "MISMATCH"
        print(f"  {subdir:<22} {exp:>10} {act:>10}  {status}")
    print(f"  {'─' * 22}  {'─' * 10} {'─' * 10}")
    total_exp = sum(summary["bucket_counts_expected"].values())
    total_act = sum(summary["bucket_counts_actual"].values())
    total_status = "ok" if total_exp == total_act else "MISMATCH"
    print(f"  {'TOTAL':<22} {total_exp:>10} {total_act:>10}  {total_status}")

    if summary["unrouted"]:
        print()
        print(f"Unrouted items ({len(summary['unrouted'])}):")
        for iid in summary["unrouted"][:20]:
            print(f"  {iid}")
        if len(summary["unrouted"]) > 20:
            print(f"  ... and {len(summary['unrouted']) - 20} more")

    if summary["errors"]:
        print()
        print(f"Errors ({len(summary['errors'])}):")
        for item_id, msg in summary["errors"][:20]:
            print(f"  {item_id}: {msg}")
        if len(summary["errors"]) > 20:
            print(f"  ... and {len(summary['errors']) - 20} more")

    if summary["orphans_moved"]:
        print()
        print(f"Orphans quarantined: {len(summary['orphans_moved'])}")
        for src, dst in summary["orphans_moved"][:20]:
            print(f"  {src}")
            print(f"    → {dst}")
        if len(summary["orphans_moved"]) > 20:
            print(f"  ... and {len(summary['orphans_moved']) - 20} more")
        print()
        print("Run scripts/triage_quarantine.py --list to review.")

    print()
    print("Validation gates (§3.1d):")

    def _gate_status(val):
        if val is None:
            return "N/A (dry-run)"
        return "PASS" if val else "FAIL"

    print(f"  Gate 1 (per-bucket + total count match): {_gate_status(summary['gate1_pass'])}")
    print(f"  Gate 2 (per-item presence):              {_gate_status(summary['gate2_pass'])}")
    if summary["gate2_pass"] is False:
        print(f"    misses ({len(summary['gate2_misses'])}):")
        for iid in summary["gate2_misses"][:10]:
            print(f"      {iid}")
        if len(summary["gate2_misses"]) > 10:
            print(f"      ... and {len(summary['gate2_misses']) - 10} more")

    print()


# ── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill per-content JSON files from content.json (spec §2d).",
    )
    parser.add_argument(
        "--source", type=Path,
        default=BASE_DIR / "seed_output" / "content.json",
        help="Source content.json (default: seed_output/content.json)",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=BASE_DIR / "data",
        help="Data root directory containing per-content subdirs (default: data/)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Force-rewrite per-content files even if they exist (default: skip)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be done without writing/moving files",
    )
    args = parser.parse_args()

    print(f"Source:    {args.source}")
    print(f"Data dir:  {args.data_dir}")
    print(f"Overwrite: {args.overwrite}")
    print(f"Dry run:   {args.dry_run}")

    summary = backfill(
        source=args.source,
        data_dir=args.data_dir,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    items = json.loads(args.source.read_text(encoding="utf-8"))
    if isinstance(items, dict) and "items" in items:
        items = items["items"]

    _print_report(summary, source_total=len(items))

    # Exit code policy:
    #   0 — no errors, no unrouted; gates pass (live run) or N/A (dry run)
    #   1 — any failure (gate fail, unrouted item, or write error)
    has_errors = bool(summary["unrouted"]) or bool(summary["errors"])
    gates_ok = (
        summary["gate1_pass"] is not False
        and summary["gate2_pass"] is not False
    )

    if not has_errors and gates_ok:
        if args.dry_run:
            print("✓ Dry run complete. No errors or unrouted items.")
            print("  Re-run without --dry-run to perform the backfill.")
        else:
            print("✓ Backfill complete. All validation gates passed.")
        return 0

    print("✗ Backfill failed validation. Review errors above before cutover.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
