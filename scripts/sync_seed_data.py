"""Sync audio_variants from content.json to seedData.js.

Reads the generated audio variants from content.json and updates the
seedData.js file in dreamweaver-web with the correct URLs and durations.

Usage:
    python3 scripts/sync_seed_data.py
"""

import json
import re
from pathlib import Path

CONTENT_PATH = Path(__file__).parent.parent / "seed_output" / "content.json"
SEED_DATA_PATH = Path(__file__).parent.parent.parent / "dreamweaver-web" / "src" / "utils" / "seedData.js"


def main():
    # Load content.json
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        stories = json.load(f)

    # Build a map of story_id -> audio_variants
    variants_map = {}
    for story in stories:
        sid = story["id"]
        variants = story.get("audio_variants", [])
        if variants:
            variants_map[sid] = variants

    print(f"Loaded {len(variants_map)} stories with audio_variants from content.json")

    # Read seedData.js
    seed_js = SEED_DATA_PATH.read_text(encoding="utf-8")

    # For each story with variants, replace the audio_variants array in seedData.js
    # We need to match the ID in seedData.js to the UUID in content.json
    #
    # Strategy: For each story in content.json, find the matching entry in seedData.js
    # by title, then replace its audio_variants block.

    # Build title -> variants map
    title_map = {}
    for story in stories:
        title = story["title"]
        variants = story.get("audio_variants", [])
        if variants:
            title_map[title] = variants

    # Also build a map based on the short ID prefix (first 8 chars of UUID)
    # which is used in the audio file URLs
    id_prefix_map = {}
    for story in stories:
        prefix = story["id"][:8]
        variants = story.get("audio_variants", [])
        if variants:
            id_prefix_map[prefix] = variants

    # Find and replace each audio_variants block in seedData.js
    # Pattern: audio_variants: [\n ... ],
    replacements = 0

    for title, variants in title_map.items():
        if not variants:
            continue

        # Build the new audio_variants JS array
        variant_lines = []
        for v in variants:
            variant_lines.append(
                f'        {{ voice: "{v["voice"]}", '
                f'url: "{v["url"]}", '
                f'duration_seconds: {v["duration_seconds"]} }},'
            )
        new_block = "audio_variants: [\n" + "\n".join(variant_lines) + "\n      ],"

        # Escape the title for regex
        escaped_title = re.escape(title)

        # Find the title in seedData.js, then find the audio_variants block after it
        # This pattern finds "title: "The Title"" followed by audio_variants: [...]
        pattern = (
            r'(title:\s*"' + escaped_title + r'".*?)'
            r'audio_variants:\s*\[.*?\],'
        )

        match = re.search(pattern, seed_js, re.DOTALL)
        if match:
            # Replace just the audio_variants part
            old_full = match.group(0)
            prefix_part = match.group(1)
            new_full = prefix_part + new_block
            seed_js = seed_js.replace(old_full, new_full)
            replacements += 1
            print(f"  Updated: {title} ({len(variants)} variants)")
        else:
            print(f"  NOT FOUND in seedData.js: {title}")

    if replacements > 0:
        SEED_DATA_PATH.write_text(seed_js, encoding="utf-8")
        print(f"\nUpdated {replacements} stories in seedData.js")
    else:
        print("\nNo updates needed.")


if __name__ == "__main__":
    main()
