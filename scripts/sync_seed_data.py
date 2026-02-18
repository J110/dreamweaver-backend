"""Sync content.json → seedData.js.

Two operations:
  1. UPDATE: Refresh audio_variants for existing entries (match by title).
  2. ADD:    Append brand-new stories/poems that don't exist yet in seedData.js.

Usage:
    python3 scripts/sync_seed_data.py
    python3 scripts/sync_seed_data.py --add-only     # Only add new entries
    python3 scripts/sync_seed_data.py --update-only   # Only update existing audio
"""

import json
import re
import sys
from pathlib import Path

CONTENT_PATH = Path(__file__).parent.parent / "seed_output" / "content.json"
SEED_DATA_PATH = Path(__file__).parent.parent.parent / "dreamweaver-web" / "src" / "utils" / "seedData.js"


def _js_escape(s: str) -> str:
    """Escape a string for safe embedding inside JS double-quoted strings."""
    return (s
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", ""))


def _build_audio_variants_js(variants: list) -> str:
    """Build the JS audio_variants array string."""
    sorted_variants = sorted(variants, key=lambda v: (
        0 if 'female' in v['voice'] else 1,
        v['voice']
    ))
    lines = []
    for v in sorted_variants:
        lines.append(
            f'        {{ voice: "{v["voice"]}", '
            f'url: "{v["url"]}", '
            f'duration_seconds: {v["duration_seconds"]} }},'
        )
    return "[\n" + "\n".join(lines) + "\n      ]"


def _build_music_params_js(mp: dict) -> str:
    """Build compact JS object literal for musicParams."""
    return json.dumps(mp, ensure_ascii=False)


def _build_new_entry_js(story: dict) -> str:
    """Build a complete JS object literal for a new seedData entry."""
    sid = story["id"]
    stype = story.get("type", "story")
    title = story["title"]
    desc = story.get("description", "")
    text = story.get("text", "")
    target_age = story.get("target_age", 5)
    duration = story.get("duration", 5)
    categories = story.get("categories", [])
    theme = story.get("theme", "fantasy")
    music_params = story.get("musicParams", {})
    audio_variants = story.get("audio_variants", [])

    # Build categories JS array
    cats_js = "[" + ", ".join(f'"{c}"' for c in categories) + "]"

    # Build musicParams
    mp_js = _build_music_params_js(music_params) if music_params else "{}"

    # Build audio_variants
    av_js = _build_audio_variants_js(audio_variants) if audio_variants else "[]"

    entry = f"""    {{
      id: "{_js_escape(sid)}",
      type: "{stype}",
      title: "{_js_escape(title)}",
      description: "{_js_escape(desc)}",
      cover: "/covers/default.svg",
      text: "{_js_escape(text)}",
      target_age: {target_age},
      duration: {duration},
      like_count: 0,
      save_count: 0,
      view_count: 0,
      categories: {cats_js},
      theme: "{theme}",
      musicParams: {mp_js},
      audio_variants: {av_js},
    }}"""
    return entry


def update_existing(seed_js: str, stories: list) -> tuple:
    """Update audio_variants for stories that already exist in seedData.js.
    Returns (updated_seed_js, update_count).
    """
    title_map = {}
    for story in stories:
        title = story["title"]
        variants = story.get("audio_variants", [])
        if variants:
            title_map[title] = variants

    replacements = 0

    for title, variants in title_map.items():
        if not variants:
            continue

        av_block = "audio_variants: " + _build_audio_variants_js(variants) + ","
        escaped_title = re.escape(title)

        pattern = (
            r'(title:\s*"' + escaped_title + r'".*?)'
            r'audio_variants:\s*\[.*?\],'
        )

        match = re.search(pattern, seed_js, re.DOTALL)
        if match:
            old_full = match.group(0)
            prefix_part = match.group(1)
            new_full = prefix_part + av_block
            seed_js = seed_js.replace(old_full, new_full)
            replacements += 1
            print(f"  Updated: {title} ({len(variants)} variants)")

    return seed_js, replacements


def add_new_entries(seed_js: str, stories: list, lang_filter: str = "en") -> tuple:
    """Add stories that don't exist in seedData.js yet.
    Returns (updated_seed_js, add_count).

    Args:
        lang_filter: Only add entries for this language ("en", "hi", or "all").
    """
    # Collect all titles already in seedData.js
    existing_titles = set(re.findall(r'title:\s*"([^"]+)"', seed_js))

    # Group new stories by language
    new_en = []
    new_hi = []
    for story in stories:
        title = story["title"]
        if title in existing_titles:
            continue
        # Only add stories that have audio_variants (ready to publish)
        if not story.get("audio_variants"):
            continue
        lang = story.get("lang", "en")
        if lang == "hi":
            if lang_filter in ("hi", "all"):
                new_hi.append(story)
        else:
            if lang_filter in ("en", "all"):
                new_en.append(story)

    added = 0

    # Add English entries before the `],` that closes `en: [`
    if new_en:
        # Find the closing of the en array: `  ],\n  hi: [`
        en_close = re.search(r'(\n\s*\},?\s*\n\s*)\],\s*\n\s*hi:\s*\[', seed_js)
        if en_close:
            insert_pos = en_close.start() + len(en_close.group(1))
            new_entries_js = ""
            for story in new_en:
                new_entries_js += "\n" + _build_new_entry_js(story) + ","
                print(f"  Added (en): {story['title']}")
                added += 1
            seed_js = seed_js[:insert_pos] + new_entries_js + seed_js[insert_pos:]

    # Add Hindi entries before the closing `],` of the hi array
    if new_hi:
        # Find the closing of the hi array: last `],\n};` pattern
        hi_close = re.search(r'(\n\s*\},?\s*\n\s*)\],\s*\n\};', seed_js)
        if hi_close:
            insert_pos = hi_close.start() + len(hi_close.group(1))
            new_entries_js = ""
            for story in new_hi:
                new_entries_js += "\n" + _build_new_entry_js(story) + ","
                print(f"  Added (hi): {story['title']}")
                added += 1
            seed_js = seed_js[:insert_pos] + new_entries_js + seed_js[insert_pos:]

    return seed_js, added


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync content.json → seedData.js")
    parser.add_argument("--add-only", action="store_true", help="Only add new entries")
    parser.add_argument("--update-only", action="store_true", help="Only update existing audio")
    parser.add_argument("--lang", default="en", choices=["en", "hi", "all"],
                        help="Language filter for adding new entries (default: en)")
    args = parser.parse_args()

    # Load content.json
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        stories = json.load(f)

    variants_count = sum(1 for s in stories if s.get("audio_variants"))
    print(f"Loaded {len(stories)} stories ({variants_count} with audio) from content.json")

    # Read seedData.js
    seed_js = SEED_DATA_PATH.read_text(encoding="utf-8")
    changed = False

    # Step 1: Update existing entries
    if not args.add_only:
        seed_js, update_count = update_existing(seed_js, stories)
        if update_count:
            changed = True
            print(f"\n  Updated {update_count} existing entries")

    # Step 2: Add new entries
    if not args.update_only:
        seed_js, add_count = add_new_entries(seed_js, stories, lang_filter=args.lang)
        if add_count:
            changed = True
            print(f"\n  Added {add_count} new entries")

    if changed:
        SEED_DATA_PATH.write_text(seed_js, encoding="utf-8")
        print(f"\nseedData.js updated successfully")
    else:
        print("\nNo updates needed.")


if __name__ == "__main__":
    main()
