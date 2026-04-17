#!/usr/bin/env python3
"""One-shot: regenerate FLUX covers for poems using stored cover_context.

Usage:
  python3 scripts/regen_poem_covers.py question 9-12
  python3 scripts/regen_poem_covers.py --all
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
from generate_experimental_poems import generate_cover  # noqa: E402

DATA_DIR = BASE_DIR / "data" / "poems"


def iter_poems(poem_type_filter, age_filter):
    for f in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        if poem_type_filter and data.get("poem_type") != poem_type_filter:
            continue
        if age_filter and data.get("age_group") != age_filter:
            continue
        yield f, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("poem_type", nargs="?", help="e.g. question, nonsense, sound")
    ap.add_argument("age_group", nargs="?", help="e.g. 9-12, 6-8, 2-5")
    ap.add_argument("--all", action="store_true", help="regen every poem")
    args = ap.parse_args()

    if not args.all and not (args.poem_type and args.age_group):
        ap.error("Specify poem_type + age_group, or --all")

    poems = list(iter_poems(
        None if args.all else args.poem_type,
        None if args.all else args.age_group,
    ))
    if not poems:
        print("No poems matched.")
        return

    print(f"Regenerating covers for {len(poems)} poems...")
    for i, (path, data) in enumerate(poems, 1):
        pid = data.get("id") or path.stem
        ptype = data.get("poem_type", "sound")
        title = data.get("title", "")
        ctx = data.get("cover_context", "")
        print(f"\n[{i}/{len(poems)}] {pid} — {title}")
        print(f"  context: {ctx[:100]}")
        new_cover = generate_cover(ptype, pid, cover_context=ctx, title=title)
        if new_cover:
            # Update the JSON's cover_file if it changed
            if data.get("cover_file") != new_cover:
                data["cover_file"] = new_cover
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                print(f"  Updated {path.name} → cover_file={new_cover}")
        # Small gap to be nice to the API
        if i < len(poems):
            time.sleep(2)

    print("\nDone.")


if __name__ == "__main__":
    main()
