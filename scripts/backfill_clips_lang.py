#!/usr/bin/env python3
"""backfill_clips_lang.py — one-time migration.

Stamps ``lang="en"`` on existing clip metadata JSON files that pre-date
the language-aware clip pipeline (commit introducing
``generate_clips_hi.py`` + ``_clips_common.py``).

Idempotent: files that already have a ``lang`` field are left untouched.
Safe to re-run after deploy or alongside future re-clones.

Usage:
    python3 scripts/backfill_clips_lang.py                  # backfill clips/
    python3 scripts/backfill_clips_lang.py --root /opt/...  # custom root
    python3 scripts/backfill_clips_lang.py --dry-run        # report only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).parent.parent / "clips"


def backfill(root: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """Return (scanned, stamped, skipped) counts."""
    if not root.exists():
        print(f"  No clips directory at {root} — nothing to do.")
        return 0, 0, 0

    scanned = stamped = skipped = 0
    for meta_file in root.rglob("*_clip.json"):
        scanned += 1
        try:
            with open(meta_file) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  ! unreadable: {meta_file} ({e})")
            skipped += 1
            continue

        if meta.get("lang"):
            skipped += 1
            continue

        meta["lang"] = "en"
        if dry_run:
            print(f"  [dry-run] would stamp lang=en on {meta_file.name}")
        else:
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            print(f"  stamped lang=en: {meta_file.name}")
        stamped += 1

    return scanned, stamped, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill lang='en' on legacy clip metadata.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="Clips directory (default: ./clips/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes without writing")
    args = parser.parse_args()

    root = Path(args.root)
    print(f"Scanning {root}…")
    scanned, stamped, skipped = backfill(root, dry_run=args.dry_run)
    print(f"\nScanned: {scanned}   Stamped: {stamped}   Already-tagged or unreadable: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
