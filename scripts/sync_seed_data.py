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


def update_existing(seed_js: str, stories: list) -> tuple:
    """Update audio_variants and duration for stories that already exist in seedData.js.
    Returns (updated_seed_js, update_count).
    """
    title_map = {}
    for story in stories:
        title = story["title"]
        variants = story.get("audio_variants", [])
        duration = story.get("duration")
        cover = story.get("cover")
        character = story.get("character")
        musical_brief = story.get("musicalBrief")
        content_type = story.get("type", "story")
        added_at = (story.get("addedAt") or story.get("created_at", ""))[:10] or None
        mood = story.get("mood")
        story_type = story.get("story_type")
        if variants:
            title_map[title] = {"variants": variants, "duration": duration, "cover": cover, "character": character, "musicalBrief": musical_brief, "addedAt": added_at, "type": content_type, "mood": mood, "story_type": story_type}

    replacements = 0

    for title, info in title_map.items():
        variants = info["variants"]
        duration = info["duration"]
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

        # Also update duration if available
        if duration is not None:
            dur_pattern = (
                r'(title:\s*"' + escaped_title + r'".*?)'
                r'duration:\s*\d+,'
            )
            dur_match = re.search(dur_pattern, seed_js, re.DOTALL)
            if dur_match:
                old_dur = dur_match.group(0)
                dur_prefix = dur_match.group(1)
                new_dur = dur_prefix + f"duration: {duration},"
                seed_js = seed_js.replace(old_dur, new_dur)

        # Also update cover path if it changed (e.g., from WebP to SVG)
        cover = info.get("cover")
        if cover:
            cover_pattern = (
                r'(title:\s*"' + escaped_title + r'".*?)'
                r'cover:\s*"[^"]*",'
            )
            cover_match = re.search(cover_pattern, seed_js, re.DOTALL)
            if cover_match:
                old_cover_full = cover_match.group(0)
                cover_prefix = cover_match.group(1)
                new_cover_full = cover_prefix + f'cover: "{cover}",'
                if old_cover_full != new_cover_full:
                    seed_js = seed_js.replace(old_cover_full, new_cover_full)

        # Also update content type (e.g., story → long_story)
        content_type = info.get("type")
        if content_type:
            type_pattern = (
                r'(id:\s*"[^"]*",\s*\n\s*)'
                r'type:\s*"[^"]*",'
            )
            # Find the entry by title context to avoid replacing wrong entries
            entry_start_pattern = r'(id:\s*"[^"]*",\s*\n\s*type:\s*")[^"]*(",\s*\n\s*title:\s*"' + re.escape(title) + r'")'
            type_match = re.search(entry_start_pattern, seed_js, re.DOTALL)
            if type_match and type_match.group(1):
                old_type = type_match.group(0)
                new_type = type_match.group(1) + content_type + type_match.group(2)
                if old_type != new_type:
                    seed_js = seed_js.replace(old_type, new_type)

        # Also update character card for About tab
        character = info.get("character")
        if character and character.get("name"):
            char_json = json.dumps(character, ensure_ascii=False)
            # Check if character field already exists for this entry
            char_existing_pattern = (
                r'(title:\s*"' + escaped_title + r'".*?)'
                r'character:\s*\{[^}]*\},'
            )
            char_match = re.search(char_existing_pattern, seed_js, re.DOTALL)
            if char_match:
                old_char = char_match.group(0)
                char_prefix = char_match.group(1)
                new_char = char_prefix + f"character: {char_json},"
                seed_js = seed_js.replace(old_char, new_char)
            else:
                # Insert character field after cover line (handles both "..." and COVERS.xxx formats)
                insert_pattern = (
                    r'(title:\s*"' + escaped_title + r'".*?'
                    r'cover:\s*(?:"[^"]*"|COVERS\.\w+),)'
                )
                insert_match = re.search(insert_pattern, seed_js, re.DOTALL)
                if insert_match:
                    old_block = insert_match.group(0)
                    new_block = old_block + f"\n      character: {char_json},"
                    seed_js = seed_js.replace(old_block, new_block, 1)

        # Also update addedAt if explicitly set in content.json
        explicit_added = info.get("addedAt")
        if explicit_added:
            added_pattern = (
                r'(title:\s*"' + escaped_title + r'".*?)'
                r'addedAt:\s*"[^"]*",'
            )
            added_match = re.search(added_pattern, seed_js, re.DOTALL)
            if added_match:
                old_added = added_match.group(0)
                added_prefix = added_match.group(1)
                new_added = added_prefix + f'addedAt: "{explicit_added}",'
                if old_added != new_added:
                    seed_js = seed_js.replace(old_added, new_added)

        # Also update mood field (entry-bounded to avoid cross-entry matching)
        mood = info.get("mood")
        if mood:
            # Normalize smart quotes for matching
            norm_title = title.replace('\u2018', "'").replace('\u2019', "'")
            # Find title position (try both original and normalized)
            title_pat = re.search(r'title:\s*"' + re.escape(title) + r'"', seed_js)
            if not title_pat and norm_title != title:
                title_pat = re.search(r'title:\s*"' + re.escape(norm_title) + r'"', seed_js)
            if title_pat:
                search_start = title_pat.start()
                # Entry boundary: next entry starts with '\n    {'
                next_entry = seed_js.find('\n    {', search_start + 1)
                if next_entry == -1:
                    next_entry = len(seed_js)
                entry_slice = seed_js[search_start:next_entry]

                mood_in_entry = re.search(r'mood:\s*"[^"]*",', entry_slice)
                if mood_in_entry:
                    # Update existing mood
                    abs_pos = search_start + mood_in_entry.start()
                    old_mood = mood_in_entry.group(0)
                    new_mood = f'mood: "{mood}",'
                    if old_mood != new_mood:
                        seed_js = seed_js[:abs_pos] + new_mood + seed_js[abs_pos + len(old_mood):]
                else:
                    # Insert after addedAt line
                    added_in_entry = re.search(r'addedAt:\s*"[^"]*",', entry_slice)
                    if added_in_entry:
                        abs_pos = search_start + added_in_entry.end()
                        seed_js = seed_js[:abs_pos] + f'\n      mood: "{mood}",' + seed_js[abs_pos:]

        # Also update story_type field (same pattern as mood)
        story_type = info.get("story_type")
        if story_type:
            norm_title = title.replace('\u2018', "'").replace('\u2019', "'")
            title_pat = re.search(r'title:\s*"' + re.escape(title) + r'"', seed_js)
            if not title_pat and norm_title != title:
                title_pat = re.search(r'title:\s*"' + re.escape(norm_title) + r'"', seed_js)
            if title_pat:
                search_start = title_pat.start()
                next_entry = seed_js.find('\n    {', search_start + 1)
                if next_entry == -1:
                    next_entry = len(seed_js)
                entry_slice = seed_js[search_start:next_entry]

                st_in_entry = re.search(r'story_type:\s*"[^"]*",', entry_slice)
                if st_in_entry:
                    abs_pos = search_start + st_in_entry.start()
                    old_st = st_in_entry.group(0)
                    new_st = f'story_type: "{story_type}",'
                    if old_st != new_st:
                        seed_js = seed_js[:abs_pos] + new_st + seed_js[abs_pos + len(old_st):]
                else:
                    # Insert after mood line, or after addedAt if no mood
                    mood_in_entry = re.search(r'mood:\s*"[^"]*",', entry_slice)
                    if mood_in_entry:
                        abs_pos = search_start + mood_in_entry.end()
                        seed_js = seed_js[:abs_pos] + f'\n      story_type: "{story_type}",' + seed_js[abs_pos:]
                    else:
                        added_in_entry = re.search(r'addedAt:\s*"[^"]*",', entry_slice)
                        if added_in_entry:
                            abs_pos = search_start + added_in_entry.end()
                            seed_js = seed_js[:abs_pos] + f'\n      story_type: "{story_type}",' + seed_js[abs_pos:]

        # Also update musicalBrief (v3 music system)
        musical_brief = info.get("musicalBrief")
        if musical_brief:
            mb_json = json.dumps(musical_brief, ensure_ascii=False)
            # Find musicalBrief using brace-counting (regex can't handle nested JSON)
            mb_key = "musicalBrief: {"
            title_pat = re.search(r'title:\s*"' + escaped_title + r'"', seed_js)
            if title_pat:
                search_start = title_pat.start()
                mb_pos = seed_js.find(mb_key, search_start)
                # Only match if within the same entry (before next entry's "id:")
                next_id = seed_js.find('\n    {', search_start + 1)
                if mb_pos != -1 and (next_id == -1 or mb_pos < next_id):
                    # Replace entire line content from musicalBrief: to newline
                    # This handles corrupted entries with trailing duplicated fragments
                    line_end = seed_js.find('\n', mb_pos)
                    if line_end == -1:
                        line_end = len(seed_js)
                    old_mb = seed_js[mb_pos:line_end]
                    new_mb = f"musicalBrief: {mb_json},"
                    if old_mb != new_mb:
                        seed_js = seed_js[:mb_pos] + new_mb + seed_js[line_end:]
                else:
                    # Insert musicalBrief after musicParams line
                    mp_key = "musicParams: {"
                    mp_pos = seed_js.find(mp_key, search_start)
                    if mp_pos != -1 and (next_id == -1 or mp_pos < next_id):
                        brace_start = mp_pos + len(mp_key) - 1
                        depth = 0
                        end = brace_start
                        for i in range(brace_start, len(seed_js)):
                            if seed_js[i] == '{':
                                depth += 1
                            elif seed_js[i] == '}':
                                depth -= 1
                            if depth == 0:
                                end = i
                                break
                        if end + 1 < len(seed_js) and seed_js[end + 1] == ',':
                            end += 1
                        insert_point = end + 1
                        seed_js = seed_js[:insert_point] + f"\n      musicalBrief: {mb_json}," + seed_js[insert_point:]

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
