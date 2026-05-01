#!/usr/bin/env python3
"""
migrate_strip_language_level.py — one-shot migration to remove the
language_level field from all content items.

Phase 1 step 1.7 of language_level field removal. Continues fff7269
(stop populating). Strips the field from existing items so the
catalog matches the no-populating-going-forward behavior.

Idempotent: re-running after success produces zero diffs.

Usage:
    python3 scripts/migrate_strip_language_level.py --dry-run
    python3 scripts/migrate_strip_language_level.py
"""
import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR))
from app.services.local_store import _atomic_write_json  # type: ignore

# All 12 per-content directories.
PER_CONTENT_DIRS = [
    "stories", "stories_hi",
    "long_stories", "long_stories_hi",
    "lullabies", "lullabies_hi",
    "silly_songs", "silly_songs_hi",
    "poems", "poems_hi",
    "funny_shorts", "funny_shorts_hi",
]

SNAPSHOT_PATHS = [
    "seed_output/content.json",
]

FIELD = "language_level"


def strip_per_content(data_dir: Path, dry_run: bool) -> tuple[int, int, int]:
    """Walk all 12 per-content dirs. Returns (checked, modified, errors)."""
    checked = 0
    modified = 0
    errors = 0
    for sub in PER_CONTENT_DIRS:
        d = data_dir / sub
        if not d.exists():
            continue
        sub_modified = 0
        for jpath in sorted(d.glob("*.json")):
            checked += 1
            try:
                with open(jpath, "r", encoding="utf-8") as f:
                    item = json.load(f)
            except Exception as e:
                print(f"  ERROR loading {jpath}: {e}")
                errors += 1
                continue
            if FIELD not in item:
                continue
            modified += 1
            sub_modified += 1
            if dry_run:
                continue
            item.pop(FIELD, None)
            try:
                _atomic_write_json(jpath, item)
            except Exception as e:
                print(f"  ERROR writing {jpath}: {e}")
                errors += 1
        if sub_modified > 0:
            label = "WOULD STRIP" if dry_run else "STRIPPED"
            print(f"  {sub}: {label} {sub_modified}")
    return checked, modified, errors


def strip_snapshot(snap_path: Path, dry_run: bool) -> tuple[int, int, int]:
    """Returns (checked, modified, errors)."""
    if not snap_path.exists():
        print(f"  Snapshot not found: {snap_path}")
        return 0, 0, 0
    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception as e:
        print(f"  ERROR loading {snap_path}: {e}")
        return 0, 0, 1
    if not isinstance(items, list):
        print(f"  ERROR: {snap_path} is not a list")
        return 0, 0, 1
    checked = len(items)
    modified = sum(1 for item in items if FIELD in item)
    if dry_run:
        label = "WOULD STRIP"
    elif modified > 0:
        for item in items:
            item.pop(FIELD, None)
        try:
            _atomic_write_json(snap_path, items)
            label = "STRIPPED"
        except Exception as e:
            print(f"  ERROR writing {snap_path}: {e}")
            return checked, modified, 1
    else:
        label = "ALREADY CLEAN — skipped write"
    print(f"  {snap_path.name}: {label} {modified}/{checked}")
    return checked, modified, 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip language_level from all content items")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change, write nothing")
    ap.add_argument("--data-dir", default=str(BASE_DIR / "data"),
                    help="Per-content data root (default: ./data)")
    args = ap.parse_args()

    print(f"=== Phase 1 step 1.7: strip {FIELD!r} from all items ===")
    print(f"  Mode:     {'DRY-RUN (no writes)' if args.dry_run else 'LIVE'}")
    print(f"  Data dir: {args.data_dir}")
    print()

    print("[1/2] Per-content files (12 buckets):")
    pc_checked, pc_modified, pc_errors = strip_per_content(Path(args.data_dir), args.dry_run)
    print(f"      {pc_checked} files checked, {pc_modified} modified, {pc_errors} errors")
    print()

    print("[2/2] Master snapshots:")
    snap_total_checked = 0
    snap_total_modified = 0
    snap_total_errors = 0
    for snap_rel in SNAPSHOT_PATHS:
        s_checked, s_modified, s_errors = strip_snapshot(BASE_DIR / snap_rel, args.dry_run)
        snap_total_checked += s_checked
        snap_total_modified += s_modified
        snap_total_errors += s_errors
    print()

    print("=== Summary ===")
    print(f"  Per-content: {pc_modified}/{pc_checked} stripped"
          + (f", {pc_errors} errors" if pc_errors else ""))
    print(f"  Snapshots:   {snap_total_modified}/{snap_total_checked} stripped"
          + (f", {snap_total_errors} errors" if snap_total_errors else ""))
    print(f"  Mode:        {'DRY-RUN — no writes' if args.dry_run else 'LIVE — writes applied'}")

    return 0 if (pc_errors == 0 and snap_total_errors == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
