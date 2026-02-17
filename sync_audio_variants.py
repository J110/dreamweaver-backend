#!/usr/bin/env python3
"""
Sync audio_variants from content.json (backend) to seedData.js (frontend)
for all 20 Hindi stories that had audio regenerated.

ID mapping:
- 8 original Hindi stories: hi-* in content.json -> seed-* in seedData.js
- 12 newer gen-* stories: same ID in both files
"""

import json
import re

CONTENT_JSON = "/Users/anmolmohan/Music/Bed Time Story App/dreamweaver-backend/seed_output/content.json"
SEED_DATA_JS = "/Users/anmolmohan/Music/Bed Time Story App/dreamweaver-web/src/utils/seedData.js"

# ID mapping: content.json ID -> seedData.js ID
ORIGINAL_HINDI_MAPPING = {
    "hi-neendwala-badal": "seed-neendwala-badal",
    "hi-bahadur-jugnu": "seed-bahadur-jugnu",
    "hi-chaand-ki-lori": "seed-chaand-ki-lori",
    "hi-captain-sitaara": "seed-captain-sitaara",
    "hi-gungunata-baag": "seed-gungunata-baag",
    "hi-chamakta-sapna": "seed-chamakta-sapna",
    "hi-ullu-ki-shubhraatri": "seed-ullu-ki-shubhraatri",
    "hi-sapnon-ki-naav": "seed-sapnon-ki-naav",
}

def load_hindi_audio_variants(content_json_path):
    """Load audio_variants for all Hindi stories from content.json."""
    with open(content_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {}
    for story in data:
        if story.get("lang") == "hi":
            content_id = story["id"]
            # Map to seedData.js ID
            seed_id = ORIGINAL_HINDI_MAPPING.get(content_id, content_id)
            result[seed_id] = story.get("audio_variants", [])

    return result


def format_audio_variant_js(variant):
    """Format a single audio variant as a JS object literal (no quotes on keys)."""
    voice = variant["voice"]
    url = variant["url"]
    duration = variant["duration_seconds"]
    return f'{{ voice: "{voice}", url: "{url}", duration_seconds: {duration} }}'


def format_audio_variants_block(variants):
    """Format the full audio_variants array as JS source."""
    lines = []
    lines.append("audio_variants: [")
    for v in variants:
        lines.append(f"        {format_audio_variant_js(v)},")
    lines.append("      ]")
    return "\n".join(lines)


def sync_audio_variants():
    """Main sync function."""
    # Load source data
    audio_data = load_hindi_audio_variants(CONTENT_JSON)
    print(f"Loaded audio_variants for {len(audio_data)} Hindi stories from content.json")

    # Read seedData.js
    with open(SEED_DATA_JS, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content
    updated_count = 0

    for seed_id, variants in audio_data.items():
        # Build regex to find the audio_variants block for this story ID
        # Pattern: find `id: "SEED_ID"` then match through to the audio_variants block
        # We need to replace just the audio_variants array for each story

        # Strategy: find the id line, then find the next audio_variants block after it
        # Use a regex that captures from audio_variants: [ ... ] within each story block

        # Find position of this story's id
        id_pattern = f'id: "{seed_id}"'
        id_pos = content.find(id_pattern)

        if id_pos == -1:
            print(f"  WARNING: Could not find {seed_id} in seedData.js")
            continue

        # Find the audio_variants block starting from this story's id position
        # Look for the next "audio_variants: [" after the id
        search_start = id_pos
        av_match = re.search(
            r'audio_variants:\s*\[.*?\]',
            content[search_start:],
            re.DOTALL
        )

        if not av_match:
            print(f"  WARNING: No audio_variants block found for {seed_id}")
            continue

        # Calculate absolute positions
        abs_start = search_start + av_match.start()
        abs_end = search_start + av_match.end()

        # Make sure this audio_variants block belongs to this story (not the next one)
        # Check there's no other `id:` between our id and the audio_variants
        between = content[id_pos + len(id_pattern):abs_start]
        if re.search(r'\bid:\s*"', between):
            print(f"  WARNING: audio_variants block for {seed_id} seems misplaced, skipping")
            continue

        # Build replacement
        new_block = format_audio_variants_block(variants)

        # Replace
        content = content[:abs_start] + new_block + content[abs_end:]
        updated_count += 1
        print(f"  Updated audio_variants for {seed_id} ({len(variants)} variants)")

    if content != original_content:
        with open(SEED_DATA_JS, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\nSuccessfully updated {updated_count} stories in seedData.js")
    else:
        print("\nNo changes were made")

    return updated_count


if __name__ == "__main__":
    count = sync_audio_variants()
    if count != 20:
        print(f"\nWARNING: Expected 20 updates but only made {count}")
