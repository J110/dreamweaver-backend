"""Sync content.json → seedData.js.

Two operations:
  1. UPDATE: Refresh audio_variants/cover/addedAt/etc. for entries that already
             exist in seedData.js. Matched STRICTLY by id, never by title.
  2. ADD:    Append brand-new stories/poems whose id is not yet in seedData.js.

Why id-only matching: the pipeline historically matched by title, which caused
a hybrid-entry bug — when a new lullaby had the same title as an existing seed
entry but a fresh id, the script overwrote the old entry's cover/audio/addedAt
in place while preserving the OLD id. The frontend then merged this corrupted
seed entry into the API item via title fallback, surfacing stale dates and
broken audio paths. Always match by id; let same-titled new items be added as
fresh entries (the homepage dedupes by id).

Usage:
    python3 scripts/sync_seed_data.py
    python3 scripts/sync_seed_data.py --add-only     # Only add new entries
    python3 scripts/sync_seed_data.py --update-only   # Only update existing audio
"""

import json
import re
import sys
from datetime import date
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
            f'duration_seconds: {v.get("duration_seconds", 0)} }},'
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
    duration = story.get("duration")
    if not duration:
        # Compute from audio_variants average
        avs = story.get("audio_variants", [])
        durs = [v.get("duration_seconds") for v in avs if v.get("duration_seconds")]
        if durs:
            import math
            duration = max(1, math.ceil(sum(durs) / len(durs) / 60))
        else:
            duration = 5  # fallback default
    categories = story.get("categories", [])
    theme = story.get("theme", "fantasy")
    music_params = story.get("musicParams", {})
    musical_brief = story.get("musicalBrief", {})
    audio_variants = story.get("audio_variants", [])
    cover = story.get("cover", "/covers/default.svg")

    # Build categories JS array
    cats_js = "[" + ", ".join(f'"{c}"' for c in categories) + "]"

    # Build musicParams
    mp_js = _build_music_params_js(music_params) if music_params else "{}"

    # Build musicalBrief (v3 music system — compact JSON composed client-side)
    mb_js = json.dumps(musical_brief, ensure_ascii=False) if musical_brief else ""

    # Build audio_variants
    av_js = _build_audio_variants_js(audio_variants) if audio_variants else "[]"

    added_at = (story.get("addedAt") or story.get("created_at", date.today().isoformat()))[:10]

    # Optional lullaby_lyrics (for long stories with lullaby)
    lullaby_lyrics = story.get("lullaby_lyrics", "")
    lullaby_line = f'\n      lullaby_lyrics: "{_js_escape(lullaby_lyrics)}",' if lullaby_lyrics else ""

    # Character card for About tab
    character = story.get("character", {})
    if character and character.get("name"):
        char_js = json.dumps(character, ensure_ascii=False)
        character_line = f"\n      character: {char_js},"
    else:
        character_line = ""

    # musicalBrief line (v3 music system — preferred over musicParams)
    musical_brief_line = f"\n      musicalBrief: {mb_js}," if mb_js else ""

    # Mood classification
    mood = story.get("mood", "")
    mood_line = f'\n      mood: "{mood}",' if mood else ""

    # Story type (narrative tradition)
    story_type = story.get("story_type", "")
    story_type_line = f'\n      story_type: "{story_type}",' if story_type else ""

    # experimental_v2: bed music baked into audio — disables client-side ambient music
    experimental_v2 = story.get("experimental_v2", False)
    experimental_v2_line = "\n      experimental_v2: true," if experimental_v2 else ""

    # has_baked_music: audio file already contains background music — disables client-side ambient music
    has_baked_music = story.get("has_baked_music", False)
    has_baked_music_line = "\n      has_baked_music: true," if has_baked_music else ""

    entry = f"""    {{
      id: "{_js_escape(sid)}",
      type: "{stype}",
      title: "{_js_escape(title)}",
      description: "{_js_escape(desc)}",
      cover: "{cover}",
      addedAt: "{added_at}",{mood_line}{story_type_line}{experimental_v2_line}{has_baked_music_line}
      text: "{_js_escape(text)}",{lullaby_line}{character_line}
      target_age: {target_age},
      duration: {duration},
      like_count: 0,
      save_count: 0,
      view_count: 0,
      categories: {cats_js},
      theme: "{theme}",
      musicParams: {mp_js},{musical_brief_line}
      audio_variants: {av_js},
    }}"""
    return entry


def _find_entry_bounds(seed_js: str, story_id: str):
    """Locate the seedData.js entry for a given story id.

    Returns (start, end) into seed_js for the entry slice (the substring
    starting at the entry's `id:` line up to — but not including — the next
    entry's opening `{` or the end of the array). Returns None if no entry
    with that id exists.

    The entry boundary is `\\n    {` which is the indentation pattern used
    inside both the en: and hi: arrays.
    """
    pattern = re.compile(r'id:\s*"' + re.escape(story_id) + r'"')
    m = pattern.search(seed_js)
    if not m:
        return None
    start = m.start()
    # Find the next entry boundary (opening of next entry) or array close
    next_open = seed_js.find('\n    {', m.end())
    if next_open == -1:
        next_open = len(seed_js)
    return (start, next_open)


def _replace_in_entry(seed_js: str, bounds, pattern: str, replacement: str) -> str:
    """Replace a pattern, but only within the given entry bounds."""
    start, end = bounds
    entry = seed_js[start:end]
    new_entry = re.sub(pattern, replacement, entry, count=1)
    if new_entry == entry:
        return seed_js
    return seed_js[:start] + new_entry + seed_js[end:]


def _entry_has_field(seed_js: str, bounds, field_pattern: str) -> bool:
    start, end = bounds
    return re.search(field_pattern, seed_js[start:end]) is not None


def update_existing(seed_js: str, stories: list) -> tuple:
    """Refresh fields on entries that already exist in seedData.js, matched by id.
    Returns (updated_seed_js, update_count).

    Never matches by title — see module docstring for the hybrid-entry bug.
    """
    replacements = 0

    for story in stories:
        story_id = story.get("id")
        if not story_id:
            continue
        variants = story.get("audio_variants", [])
        if not variants:
            continue

        bounds = _find_entry_bounds(seed_js, story_id)
        if bounds is None:
            # Not in seedData.js — add_new_entries() will handle it.
            continue

        title = story.get("title", story_id)
        duration = story.get("duration")
        cover = story.get("cover")
        character = story.get("character")
        musical_brief = story.get("musicalBrief")
        content_type = story.get("type", "story")
        added_at = (story.get("addedAt") or story.get("created_at", ""))[:10] or None
        mood = story.get("mood")
        story_type = story.get("story_type")

        # ── audio_variants (always replace) ──
        av_block = "audio_variants: " + _build_audio_variants_js(variants) + ","
        seed_js_after = _replace_in_entry(
            seed_js, bounds,
            r'audio_variants:\s*\[.*?\],',
            av_block.replace('\\', r'\\'),
        )
        if seed_js_after != seed_js:
            seed_js = seed_js_after
            # Recompute bounds — substitution can shift offsets
            bounds = _find_entry_bounds(seed_js, story_id)
            replacements += 1
            print(f"  Updated: {title} ({len(variants)} variants)")

        # ── duration ──
        if duration is not None and bounds:
            seed_js_after = _replace_in_entry(
                seed_js, bounds,
                r'duration:\s*\d+,',
                f"duration: {duration},",
            )
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── cover ──
        if cover and bounds:
            seed_js_after = _replace_in_entry(
                seed_js, bounds,
                r'cover:\s*"[^"]*",',
                f'cover: "{cover}",',
            )
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── type ──
        if content_type and bounds:
            seed_js_after = _replace_in_entry(
                seed_js, bounds,
                r'type:\s*"[^"]*",',
                f'type: "{content_type}",',
            )
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── addedAt ──
        if added_at and bounds:
            seed_js_after = _replace_in_entry(
                seed_js, bounds,
                r'addedAt:\s*"[^"]*",',
                f'addedAt: "{added_at}",',
            )
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── mood ──
        if mood and bounds:
            if _entry_has_field(seed_js, bounds, r'mood:\s*"[^"]*",'):
                seed_js_after = _replace_in_entry(
                    seed_js, bounds,
                    r'mood:\s*"[^"]*",',
                    f'mood: "{mood}",',
                )
            else:
                # Insert after addedAt within the entry
                start, end = bounds
                entry = seed_js[start:end]
                added_in_entry = re.search(r'addedAt:\s*"[^"]*",', entry)
                if added_in_entry:
                    abs_pos = start + added_in_entry.end()
                    seed_js_after = seed_js[:abs_pos] + f'\n      mood: "{mood}",' + seed_js[abs_pos:]
                else:
                    seed_js_after = seed_js
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── story_type ──
        if story_type and bounds:
            if _entry_has_field(seed_js, bounds, r'story_type:\s*"[^"]*",'):
                seed_js_after = _replace_in_entry(
                    seed_js, bounds,
                    r'story_type:\s*"[^"]*",',
                    f'story_type: "{story_type}",',
                )
            else:
                start, end = bounds
                entry = seed_js[start:end]
                anchor = re.search(r'mood:\s*"[^"]*",', entry) or re.search(r'addedAt:\s*"[^"]*",', entry)
                if anchor:
                    abs_pos = start + anchor.end()
                    seed_js_after = seed_js[:abs_pos] + f'\n      story_type: "{story_type}",' + seed_js[abs_pos:]
                else:
                    seed_js_after = seed_js
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── character (replace if exists, else insert after cover line) ──
        if character and character.get("name") and bounds:
            char_json = json.dumps(character, ensure_ascii=False)
            if _entry_has_field(seed_js, bounds, r'character:\s*\{[^}]*\},'):
                seed_js_after = _replace_in_entry(
                    seed_js, bounds,
                    r'character:\s*\{[^}]*\},',
                    f"character: {char_json},",
                )
            else:
                start, end = bounds
                entry = seed_js[start:end]
                anchor = re.search(r'cover:\s*(?:"[^"]*"|COVERS\.\w+),', entry)
                if anchor:
                    abs_pos = start + anchor.end()
                    seed_js_after = seed_js[:abs_pos] + f"\n      character: {char_json}," + seed_js[abs_pos:]
                else:
                    seed_js_after = seed_js
            if seed_js_after != seed_js:
                seed_js = seed_js_after
                bounds = _find_entry_bounds(seed_js, story_id)

        # ── musicalBrief (replace whole line if present, else insert after musicParams) ──
        if musical_brief and bounds:
            mb_json = json.dumps(musical_brief, ensure_ascii=False)
            start, end = bounds
            entry = seed_js[start:end]
            mb_pos_rel = entry.find("musicalBrief: {")
            if mb_pos_rel != -1:
                line_end_rel = entry.find('\n', mb_pos_rel)
                if line_end_rel == -1:
                    line_end_rel = len(entry)
                abs_pos = start + mb_pos_rel
                old_line = seed_js[abs_pos:start + line_end_rel]
                new_line = f"musicalBrief: {mb_json},"
                if old_line != new_line:
                    seed_js = seed_js[:abs_pos] + new_line + seed_js[start + line_end_rel:]
                    bounds = _find_entry_bounds(seed_js, story_id)
            else:
                # Insert after the musicParams object literal
                mp_pos_rel = entry.find("musicParams: {")
                if mp_pos_rel != -1:
                    brace_start = start + mp_pos_rel + len("musicParams: ") + 0  # points at '{'
                    # Find matching closing brace
                    depth = 0
                    closing = brace_start
                    for i in range(brace_start, len(seed_js)):
                        ch = seed_js[i]
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                closing = i
                                break
                    insert_point = closing + 1
                    if insert_point < len(seed_js) and seed_js[insert_point] == ',':
                        insert_point += 1
                    seed_js = seed_js[:insert_point] + f"\n      musicalBrief: {mb_json}," + seed_js[insert_point:]
                    bounds = _find_entry_bounds(seed_js, story_id)

    return seed_js, replacements


def add_new_entries(seed_js: str, stories: list, lang_filter: str = "en") -> tuple:
    """Add stories that don't exist in seedData.js yet (matched by id).
    Returns (updated_seed_js, add_count).

    Args:
        lang_filter: Only add entries for this language ("en", "hi", or "all").
    """
    # Collect all ids already in seedData.js. Match by id, not title — same-titled
    # entries with different ids must be added as separate rows.
    existing_ids = set(re.findall(r'id:\s*"([^"]+)"', seed_js))

    # Group new stories by language
    new_en = []
    new_hi = []
    for story in stories:
        sid = story.get("id")
        if not sid or sid in existing_ids:
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
        # Find the closing of the en array before `hi: [`
        # Handles both `},],\n  hi: [` and `},\n  ],\n  hi: [` formats
        en_close = re.search(r'(\},?\s*)\],?\s*\n\s*hi:\s*\[', seed_js)
        if not en_close:
            en_close = re.search(r'(\},?\s*)\],?\s*\n\};', seed_js)
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
        # Find the closing of the hi array: handles `},],\n};` and `},\n  ],\n};`
        hi_close = re.search(r'(\},?\s*)\],?\s*\n\};', seed_js)
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
