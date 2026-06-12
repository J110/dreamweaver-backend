#!/usr/bin/env python3
"""Bulk duration_seconds metadata correction (per-content-file SOT).

Per-content files at data/<type-dir>/<id>.json are the source of truth.
seed_output/content.json and data/content.json are derived snapshots
regenerated from per-content files by admin reload. Direct edits to the
snapshots get wiped on the next reload — so this script writes to the
per-content files and instructs the caller to admin-reload.

For each item, ffprobe every audio reference (audio_variants[].url or
legacy audio_url/audio_file). If a claimed duration_seconds differs from
the on-disk truth by more than DURATION_TOLERANCE_SEC, update it.

Item-level duration_seconds is set to the int-rounded median of measured
variant durations for every variant-bearing item (stories, lullabies, long
stories alike) — it is the field the playlist API serves.

Modes:
  --dry-run  (default)  Print what would change, write nothing
  --apply               Write corrections back to data/<type-dir>/<id>.json
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
DATA_DIR = BASE_DIR / "data"
WEB_AUDIO_DIR = Path("/opt/dreamweaver-web/public/audio")
AUDIO_STORE_DIR = Path("/opt/audio-store")
DURATION_TOLERANCE_SEC = 5.0


def per_content_path(item: dict) -> Path | None:
    """Resolve the per-content file path from type + subtype + lang.

    Returns None if the item shape isn't recognised; the caller skips it.
    """
    sid = item.get("id")
    if not sid:
        return None
    t = item.get("type")
    st = item.get("subtype")
    lang = item.get("lang", "en")
    suffix = "_hi" if lang == "hi" else ""

    if t == "story":
        sub = f"stories{suffix}"
    elif t == "long_story":
        sub = f"long_stories{suffix}"
    elif t == "poem":
        sub = f"poems{suffix}"
    elif t == "song" and st == "silly_song":
        sub = f"silly_songs{suffix}"
    elif t == "song" and st == "funny_short":
        sub = f"funny_shorts{suffix}"
    elif t == "song" and (st == "lullaby" or st is None):
        # type=song with no subtype falls back to lullaby (legacy)
        sub = f"lullabies{suffix}"
    else:
        return None

    return DATA_DIR / sub / f"{sid}.json"


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


def legacy_url(item: dict) -> str | None:
    legacy = item.get("audio_url") or item.get("audio_file")
    if not legacy:
        return None
    s = str(legacy)
    if s.startswith("/audio/") or s.startswith("audio/"):
        return s if s.startswith("/") else "/" + s
    if "/" in s:
        return s if s.startswith("/") else "/" + s
    return f"/audio/{_legacy_subdir_for(item)}/{s}"


def correct_item_dict(item: dict, log: list) -> int:
    """Mutate item dict in place. Returns count of field updates applied."""
    changes = 0
    sid = item.get("id", "")
    corrected_variant_durs: list[float] = []

    variants = item.get("audio_variants") or []
    for v in variants:
        if not isinstance(v, dict):
            continue
        url = v.get("url", "")
        disk = resolve_disk_path(url)
        if not disk:
            continue
        actual = ffprobe_duration(disk)
        if actual is None:
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

    if not variants:
        url = legacy_url(item)
        if url:
            disk = resolve_disk_path(url)
            if disk:
                actual = ffprobe_duration(disk)
                if actual is not None:
                    corrected_variant_durs.append(round(actual, 2))

    if corrected_variant_durs:
        median_dur = int(round(statistics.median(corrected_variant_durs)))
        old = item.get("duration_seconds")
        if old is None or abs(float(old) - median_dur) > DURATION_TOLERANCE_SEC:
            log.append(
                f"  ITEM {sid:28} duration_seconds "
                f"{old} → {median_dur} (median of {len(corrected_variant_durs)} measured)"
            )
            item["duration_seconds"] = median_dur
            changes += 1

    return changes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="Write corrections to data/<type>/<id>.json. Default is dry-run.")
    p.add_argument("--dry-run", action="store_true", help="Default behavior — print, no writes.")
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
    field_changes = 0
    skipped_no_path = 0
    skipped_missing_file = 0

    for item in content:
        if not isinstance(item, dict):
            continue
        path = per_content_path(item)
        if path is None:
            skipped_no_path += 1
            continue
        if not path.exists():
            skipped_missing_file += 1
            log.append(f"  SKIP {item.get('id',''):28} per-content file not found: {path}")
            continue

        # Read SOT and apply correction to the SOT dict.
        try:
            sot = json.loads(path.read_text())
        except Exception as e:
            log.append(f"  SKIP {item.get('id',''):28} read failed ({path}): {e}")
            continue

        n = correct_item_dict(sot, log)
        if n == 0:
            continue
        items_changed += 1
        field_changes += n
        if do_write:
            path.write_text(json.dumps(sot, indent=2, ensure_ascii=False))

    mode = "APPLY" if do_write else "DRY-RUN"
    print(f"=== Duration metadata correction (per-content SOT) — {mode} ===")
    print(f"Items scanned: {len(content)}")
    print(f"Skipped (unrecognised type/subtype): {skipped_no_path}")
    print(f"Skipped (per-content file missing):  {skipped_missing_file}")
    for line in log:
        print(line)
    print()
    print(f"Items changed:    {items_changed}")
    print(f"Field-level updates: {field_changes}")

    if not do_write:
        print("\nDry-run only. Re-run with --apply to write per-content files.")
        return 0

    print(f"\nWrote {items_changed} per-content files under {DATA_DIR}/")
    print(f"Done at {datetime.now(timezone.utc).isoformat()}.")
    print("Trigger admin reload so the snapshots regenerate from per-content files:")
    print('  curl -X POST -H "X-Admin-Key: $ADMIN_KEY" https://api.dreamvalley.app/api/v1/admin/reload')
    return 0


if __name__ == "__main__":
    sys.exit(main())
