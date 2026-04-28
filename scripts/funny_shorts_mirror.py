#!/usr/bin/env python3
"""Append/refresh a funny short entry in seed_output/content.json.

Usage:
  python3 scripts/funny_shorts_mirror.py --add <short_id>
  python3 scripts/funny_shorts_mirror.py --rebuild   # rebuild ALL funny short mirrors
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data" / "funny_shorts"
SEED_CONTENT = BASE / "seed_output" / "content.json"


def _entry_to_mirror(short: dict) -> dict:
    lang = short.get("lang", "en")
    audio_dir = "funny-shorts-hi" if lang == "hi" else "funny-shorts"
    return {
        "id": short["id"],
        "type": "song",
        "subtype": "funny_short",
        "lang": lang,
        "language": lang,
        "title": short.get("title", ""),
        "title_en": short.get("title_en", ""),
        "age_group": short.get("age_group", "6-8"),
        "duration_seconds": short.get("duration_seconds", 0),
        "audio_file": short.get("audio_file"),
        "audio_url": short.get("audio_url", f"/audio/{audio_dir}/{short['id']}.mp3"),
        "cover": short.get("cover", f"/covers/{audio_dir}/{short['id']}_cover.webp"),
        "created_at": short.get("created_at", ""),
    }


def _load_content() -> dict:
    if SEED_CONTENT.exists():
        return json.loads(SEED_CONTENT.read_text())
    return {"items": []}


def _save_content(c: dict) -> None:
    SEED_CONTENT.parent.mkdir(parents=True, exist_ok=True)
    SEED_CONTENT.write_text(json.dumps(c, indent=2, ensure_ascii=False))


def add_one(short_id: str) -> int:
    src = DATA_DIR / f"{short_id}.json"
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 1
    short = json.loads(src.read_text())
    mirror = _entry_to_mirror(short)
    content = _load_content()
    items = content.setdefault("items", [])
    items = [i for i in items if i.get("id") != short_id]
    items.append(mirror)
    content["items"] = items
    _save_content(content)
    print(f"✓ Mirrored {short_id} into {SEED_CONTENT}")
    return 0


def rebuild() -> int:
    content = _load_content()
    items = [i for i in content.get("items", []) if i.get("subtype") != "funny_short"]
    if DATA_DIR.exists():
        for f in sorted(DATA_DIR.glob("*.json")):
            items.append(_entry_to_mirror(json.loads(f.read_text())))
    content["items"] = items
    _save_content(content)
    print(f"✓ Rebuilt funny_short mirrors in {SEED_CONTENT}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", help="Add a single short by id")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if args.rebuild:
        return rebuild()
    if args.add:
        return add_one(args.add)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
