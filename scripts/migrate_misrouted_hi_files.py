#!/usr/bin/env python3
"""One-shot migration: move hi-* per-content files from English dirs to _hi dirs.

Context: deploy_guard.py's json-store backup hardcoded English dirs (silly_songs/,
poems/), so any hi-* file that ever leaked into an English dir was perpetually
restored from the store on every nightly verify+auto-recover. The loader keys by
(source dir, id), so the file appeared once in the English dir and once in the
correct _hi dir — yielding duplicate (id, lang=hi) rows on the Hindi endpoints.

This script:
  1. Walks every English per-content dir (silly_songs, poems, lullabies, stories,
     long_stories, funny_shorts).
  2. For each `hi-*.json` found, locates the canonical `_hi` counterpart.
  3. Merges fields (newer copy wins for populated values; older copy fills gaps).
  4. Writes merged result to the `_hi` dir.
  5. Deletes the English-dir copy.
  6. Also prunes the corresponding entry from /opt/json-store/<en_dir>/ so the
     next verify+auto-recover doesn't re-create the misroute.

Run with --dry-run to preview.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
JSON_STORE = Path("/opt/json-store")

EN_HI_PAIRS = (
    ("stories", "stories_hi"),
    ("long_stories", "long_stories_hi"),
    ("lullabies", "lullabies_hi"),
    ("silly_songs", "silly_songs_hi"),
    ("funny_shorts", "funny_shorts_hi"),
    ("poems", "poems_hi"),
)


def _load(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _merge(newer: dict, older: dict) -> dict:
    """Prefer newer's populated values; fall back to older for missing/empty fields.

    A field is considered 'populated' when its value is not None and not an
    empty string/list/dict. Keeps both files' best information.
    """
    merged = dict(older)
    for k, v in newer.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        merged[k] = v
    return merged


def _migrate_one(en_path: Path, hi_path: Path, dry_run: bool) -> dict:
    en_data = _load(en_path) or {}
    hi_data = _load(hi_path) if hi_path.exists() else None

    en_mtime = en_path.stat().st_mtime if en_path.exists() else 0
    hi_mtime = hi_path.stat().st_mtime if hi_path.exists() else 0
    newer, older = (
        (en_data, hi_data or {}) if en_mtime >= hi_mtime else (hi_data or {}, en_data)
    )
    merged = _merge(newer, older) if older else newer
    # Lang field reflects file location regardless of original tag.
    merged["lang"] = "hi"
    if merged.get("language"):
        merged["language"] = "hi"

    action = {
        "id": en_path.stem,
        "en_path": str(en_path),
        "hi_path": str(hi_path),
        "hi_existed": hi_path.exists(),
        "newer_side": "en" if en_mtime >= hi_mtime else "hi",
        "merged_field_count": len(merged),
    }

    if dry_run:
        action["status"] = "dry-run"
        return action

    hi_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = hi_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(hi_path)

    en_path.unlink()

    # Also prune from json-store so verify+auto-recover does not restore it.
    store_copy = JSON_STORE / en_path.parent.name / en_path.name
    if store_copy.exists():
        store_copy.unlink()
        action["pruned_store"] = str(store_copy)

    action["status"] = "migrated"
    return action


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview, no writes.")
    args = parser.parse_args(argv)

    results = []
    for en_name, hi_name in EN_HI_PAIRS:
        en_dir = DATA_DIR / en_name
        hi_dir = DATA_DIR / hi_name
        if not en_dir.is_dir():
            continue
        for en_path in sorted(en_dir.glob("hi-*.json")):
            hi_path = hi_dir / en_path.name
            results.append(_migrate_one(en_path, hi_path, args.dry_run))

    if not results:
        print("No misrouted hi-* files found. Nothing to migrate.")
        return 0

    print(f"{'=' * 60}")
    print(f"  {'DRY RUN — ' if args.dry_run else ''}{len(results)} file(s)")
    print(f"{'=' * 60}")
    for r in results:
        print(
            f"  {r['status']:9s}  id={r['id']}  "
            f"newer={r['newer_side']}  hi_existed={r['hi_existed']}  "
            f"fields={r['merged_field_count']}"
        )
        if r.get("pruned_store"):
            print(f"             pruned: {r['pruned_store']}")
    if args.dry_run:
        print("\nRe-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
