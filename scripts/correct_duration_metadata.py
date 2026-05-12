#!/usr/bin/env python3
"""Bulk metadata correction for duration_seconds drift.

For every item in seed_output/content.json with audio_variants (or
top-level legacy audio_url/audio_file), ffprobe the on-disk file and
update the claimed duration_seconds to match if it differs by more than
DURATION_TOLERANCE_SEC.

For long stories with multiple variants, the item-level duration_seconds
is also set to the median of the corrected variant durations.

Modes:
  --dry-run  (default)  Print what would change, write nothing
  --apply               Write corrections back to seed_output/content.json
                        and data/content.json (the API serving copy).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
SEED_PATH = BASE_DIR / "seed_output" / "content.json"
DATA_PATH = BASE_DIR / "data" / "content.json"
WEB_AUDIO_DIR = Path("/opt/dreamweaver-web/public/audio")
AUDIO_STORE_DIR = Path("/opt/audio-store")
DURATION_TOLERANCE_SEC = 5.0

AUDIO_SUBDIRS = ("pre-gen", "silly-songs", "funny-shorts", "poems", "poems-hi", "lullabies", "story_music")


def _legacy_subdir_for(item: dict) -> str:
    subtype = item.get("subtype")
    if subtype == "silly_song":
        return "silly-songs"
    if subtype == "funny_short":
        return "funny-shorts"
    if subtype == "lullaby":
        return "lullabies"
    if item.get("type") == "poem":
        return "poems-hi" if item.get("lang") == "hi" else "poems"
    return "pre-gen"


def resolve_disk_path(url: str) -> Path | None:
    if not url:
        return None
    if url.startswith("/audio/"):
        rel = url[len("/audio/"):]
    elif url.startswith("audio/"):
        rel = url[len("audio/"):]
    else:
        rel = url.lstrip("/")
    for root in (WEB_AUDIO_DIR, AUDIO_STORE_DIR):
        cand = root / rel
        if cand.exists():
            return cand
    return None


def ffprobe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return float(out.stdout.strip())
    except Exception:
        return None


def legacy_url_from_item(item: dict) -> str | None:
    """Derive a URL for legacy bare-filename audio_file."""
    legacy = item.get("audio_url") or item.get("audio_file")
    if not legacy:
        return None
    s = str(legacy)
    if s.startswith("/audio/") or s.startswith("audio/"):
        return s if s.startswith("/") else "/" + s
    if "/" in s:
        return s if s.startswith("/") else "/" + s
    return f"/audio/{_legacy_subdir_for(item)}/{s}"


def correct_item(item: dict, log: list) -> int:
    """Mutate item in place. Returns count of variant durations changed."""
    changes = 0
    sid = item.get("id", "")
    title = item.get("title", "")
    corrected_variant_durs: list[float] = []

    variants = item.get("audio_variants") or []
    for v in variants:
        if not isinstance(v, dict):
            continue
        url = v.get("url", "")
        disk = resolve_disk_path(url)
        if not disk:
            log.append(f"  SKIP {sid} [{v.get('voice')}]: file not found ({url})")
            continue
        actual = ffprobe_duration(disk)
        if actual is None:
            log.append(f"  SKIP {sid} [{v.get('voice')}]: ffprobe failed ({disk})")
            continue
        actual = round(actual, 2)
        claimed = v.get("duration_seconds")
        if claimed is not None and abs(float(claimed) - actual) <= DURATION_TOLERANCE_SEC:
            corrected_variant_durs.append(actual)
            continue
        log.append(
            f"  FIX  {sid:28} [{v.get('voice','?'):14}] "
            f"claimed={claimed} → actual={actual}"
        )
        v["duration_seconds"] = actual
        changes += 1
        corrected_variant_durs.append(actual)

    # Legacy top-level audio_url/audio_file path (only when no variants).
    if not variants:
        url = legacy_url_from_item(item)
        if url:
            disk = resolve_disk_path(url)
            if disk:
                actual = ffprobe_duration(disk)
                if actual is not None:
                    actual = round(actual, 2)
                    claimed = item.get("duration_seconds")
                    if claimed is None or abs(float(claimed) - actual) > DURATION_TOLERANCE_SEC:
                        log.append(
                            f"  FIX  {sid:28} [legacy            ] "
                            f"claimed={claimed} → actual={actual}"
                        )
                        item["duration_seconds"] = actual
                        changes += 1
                    corrected_variant_durs.append(actual)

    # Long story item-level duration_seconds = median of variants.
    is_long = item.get("type") == "long_story" or str(item.get("length", "")).upper() == "LONG"
    if is_long and corrected_variant_durs:
        median_dur = round(statistics.median(corrected_variant_durs), 2)
        old_item_dur = item.get("duration_seconds")
        if old_item_dur is None or abs(float(old_item_dur) - median_dur) > DURATION_TOLERANCE_SEC:
            log.append(
                f"  ITEM {sid:28} long_story duration_seconds "
                f"{old_item_dur} → {median_dur} (median of {len(corrected_variant_durs)} variants)"
            )
            item["duration_seconds"] = median_dur
            changes += 1

    return changes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="Write corrections back to content.json. Default is dry-run.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print changes without writing. Default behavior.")
    args = p.parse_args()
    do_write = args.apply and not args.dry_run

    if not SEED_PATH.exists():
        print(f"ERROR: {SEED_PATH} missing", file=sys.stderr)
        return 1

    content = json.loads(SEED_PATH.read_text())
    if not isinstance(content, list):
        print("ERROR: content.json is not a list", file=sys.stderr)
        return 1

    log: list[str] = []
    items_changed = 0
    variant_changes = 0
    for item in content:
        if not isinstance(item, dict):
            continue
        before = sum(1 for line in log if line.startswith("  FIX") or line.startswith("  ITEM"))
        n = correct_item(item, log)
        if n:
            items_changed += 1
            variant_changes += n

    mode = "APPLY" if do_write else "DRY-RUN"
    print(f"=== Duration metadata correction — {mode} ===")
    print(f"Items in content.json: {len(content)}")
    for line in log:
        print(line)
    print()
    print(f"Items changed:    {items_changed}")
    print(f"Field-level updates: {variant_changes}")

    if not do_write:
        print("\nDry-run only. Re-run with --apply to write changes.")
        return 0

    # Write back to seed_output/content.json.
    SEED_PATH.write_text(json.dumps(content, indent=2, ensure_ascii=False))
    print(f"\nWrote: {SEED_PATH}")

    # Mirror to data/content.json (API serving copy) if present.
    if DATA_PATH.exists():
        try:
            api_content = json.loads(DATA_PATH.read_text())
            api_index = {it.get("id"): it for it in api_content if isinstance(it, dict)}
            api_changes = 0
            for item in content:
                sid = item.get("id")
                if sid in api_index:
                    target = api_index[sid]
                    # Sync variant durations + item-level duration_seconds.
                    if item.get("audio_variants"):
                        target["audio_variants"] = item["audio_variants"]
                    if "duration_seconds" in item:
                        target["duration_seconds"] = item["duration_seconds"]
                    api_changes += 1
            DATA_PATH.write_text(json.dumps(api_content, indent=2, ensure_ascii=False))
            print(f"Mirrored to: {DATA_PATH} ({api_changes} item references touched)")
        except Exception as e:
            print(f"WARNING: failed to mirror to data/content.json: {e}", file=sys.stderr)

    print(f"\nDone at {datetime.now(timezone.utc).isoformat()}.")
    print("Remember to trigger admin reload so the live API picks up the new durations:")
    print('  curl -X POST -H "X-Admin-Key: $ADMIN_KEY" https://api.dreamvalley.app/api/v1/admin/reload')
    return 0


if __name__ == "__main__":
    sys.exit(main())
