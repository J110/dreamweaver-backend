#!/usr/bin/env python3
"""Test script: Generate a single 9-12 LONG story with phase-based audio.

Usage:
    python3 scripts/test_long_story.py                    # Generate story text only
    python3 scripts/test_long_story.py --audio            # Generate story + audio (1 voice)
    python3 scripts/test_long_story.py --audio --voice female_1  # Specific voice
    python3 scripts/test_long_story.py --age-group 2-5    # Different age group
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Setup path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

import httpx

from scripts.generate_content_matrix import (
    AGE_GROUPS,
    WORD_COUNTS,
    THEMES_BY_AGE,
    LENGTHS_BY_AGE,
    LIFE_ASPECTS_BY_AGE,
    UNIVERSES,
    GEOGRAPHIES,
    PLOT_ARCHETYPES,
    LEAD_GENDERS,
    LEAD_CHARACTER_TYPES,
    CHARACTER_TYPE_EXAMPLES,
    build_generation_prompt,
    generate_one,
    load_existing,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_test_item(age_group: str = "9-12", lang: str = "en"):
    """Build a single LONG story item for the given age group."""
    import random

    ag_info = AGE_GROUPS[age_group]
    themes = THEMES_BY_AGE[age_group]
    life_aspects = LIFE_ASPECTS_BY_AGE[age_group]

    theme = random.choice(themes)
    universe = random.choice(UNIVERSES)
    geography = random.choice(GEOGRAPHIES)
    archetype = random.choice(PLOT_ARCHETYPES)
    life_aspect = random.choice(life_aspects)
    lead_gender = random.choice(LEAD_GENDERS)

    # Pick a character
    char_type_key = "human"
    char_type_label = "Human Child/Teen"
    type_chars = CHARACTER_TYPE_EXAMPLES[char_type_key]
    char_name, char_species, char_setting = random.choice(type_chars)

    wc_key = (age_group, "story", "LONG")
    min_words, max_words = WORD_COUNTS.get(wc_key, (500, 800))

    return {
        "lang": lang,
        "age_group": age_group,
        "age_min": ag_info["age_min"],
        "age_max": ag_info["age_max"],
        "target_age": ag_info["target_age"],
        "type": "story",
        "theme": theme,
        "length": "LONG",
        "min_words": min_words,
        "max_words": max_words,
        "universe": universe,
        "geography": geography,
        "plot_archetype": archetype,
        "life_aspect": life_aspect,
        "lead_gender": lead_gender,
        "lead_character_type": char_type_key,
        "lead_character_type_label": char_type_label,
        "character_name": char_name,
        "character_species": char_species,
        "character_setting": char_setting,
        "cell_id": f"test_{age_group}_LONG",
    }


def main():
    parser = argparse.ArgumentParser(description="Test long story generation")
    parser.add_argument("--age-group", default="9-12", help="Age group (2-5, 6-8, 9-12)")
    parser.add_argument("--audio", action="store_true", help="Also generate audio")
    parser.add_argument("--voice", default="female_1", help="Voice for audio (default: female_1)")
    parser.add_argument("--lang", default="en", help="Language (en/hi)")
    args = parser.parse_args()

    # ── Step 1: Generate story text ──────────────────────────────────
    logger.info("=" * 60)
    logger.info("TEST: Generating %s LONG story (age %s)", args.lang, args.age_group)
    logger.info("=" * 60)

    item = build_test_item(age_group=args.age_group, lang=args.lang)
    logger.info("Theme: %s | Universe: %s | Geography: %s",
                item["theme"], item["universe"], item["geography"])
    logger.info("Character: %s (%s) in %s",
                item["character_name"], item["character_species"], item["character_setting"])
    logger.info("Word range: %d-%d", item["min_words"], item["max_words"])

    # Show the prompt for debugging
    prompt = build_generation_prompt(item, [])
    logger.info("Prompt length: %d chars", len(prompt))

    # Check phase instructions are included
    if "[PHASE_1]" in prompt and "[/PHASE_3]" in prompt:
        logger.info("Phase instructions: PRESENT")
    else:
        logger.error("Phase instructions: MISSING!")
        return

    # Generate via Mistral
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")

    try:
        from mistralai import Mistral
    except ImportError:
        logger.error("mistralai package not installed. Run: pip install mistralai")
        return

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set. Check .env file.")
        return

    client = Mistral(api_key=api_key)
    logger.info("Calling Mistral API...")
    existing_titles = [c.get("title", "") for c in load_existing()]
    result = generate_one(client, item, existing_titles, max_retries=3, api="mistral")

    if not result:
        logger.error("Story generation FAILED")
        return

    # ── Step 2: Analyze result ───────────────────────────────────────
    title = result["title"]
    text = result.get("annotated_text", result.get("text", ""))
    word_count = result.get("word_count", len(text.split()))

    logger.info("")
    logger.info("=" * 60)
    logger.info("RESULT: %s", title)
    logger.info("=" * 60)
    logger.info("Word count: %d", word_count)

    # Check phase markers
    has_phase1 = "[PHASE_1]" in text and "[/PHASE_1]" in text
    has_phase2 = "[PHASE_2]" in text and "[/PHASE_2]" in text
    has_phase3 = "[PHASE_3]" in text and "[/PHASE_3]" in text

    logger.info("Phase 1: %s", "PRESENT" if has_phase1 else "MISSING")
    logger.info("Phase 2: %s", "PRESENT" if has_phase2 else "MISSING")
    logger.info("Phase 3: %s", "PRESENT" if has_phase3 else "MISSING")

    if has_phase1 and has_phase2 and has_phase3:
        # Extract and measure phase sizes
        import re
        for pnum in [1, 2, 3]:
            match = re.search(rf'\[PHASE_{pnum}\](.*?)\[/PHASE_{pnum}\]', text, re.DOTALL)
            if match:
                phase_text = match.group(1).strip()
                phase_words = len(phase_text.split())
                pct = phase_words / word_count * 100 if word_count > 0 else 0
                logger.info("  Phase %d: %d words (%.0f%%)", pnum, phase_words, pct)
    else:
        logger.warning("Missing phase markers — story will use legacy audio flow")

    # Save the story to a test file
    test_output = BASE_DIR / "seed_output" / "test_long_story.json"
    with open(test_output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Saved story to: %s", test_output)

    # Print Phase 3 text for inspection
    if has_phase3:
        import re
        match = re.search(r'\[PHASE_3\](.*?)\[/PHASE_3\]', text, re.DOTALL)
        if match:
            p3_text = match.group(1).strip()
            logger.info("")
            logger.info("── Phase 3 text (age %s style) ──", args.age_group)
            # Print first 500 chars
            preview = p3_text[:500] + ("..." if len(p3_text) > 500 else "")
            print(preview)

    # ── Step 3: Generate audio (optional) ────────────────────────────
    if not args.audio:
        logger.info("")
        logger.info("Skipping audio (use --audio to generate)")
        logger.info("To generate audio: python3 scripts/test_long_story.py --audio --voice %s", args.voice)
        return

    logger.info("")
    logger.info("=" * 60)
    logger.info("AUDIO: Generating %s variant...", args.voice)
    logger.info("=" * 60)

    from scripts.generate_audio import generate_story_variant

    story_id = result["id"]
    voice = args.voice
    output_dir = BASE_DIR / "audio" / "pre-gen"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{story_id}_{voice}.mp3"

    with httpx.Client(timeout=120.0) as client:
        audio_result = generate_story_variant(
            client=client,
            story=result,
            voice=voice,
            output_path=output_path,
            force=True,
            speed=0.8,  # pipeline default (ignored by phased stories)
        )

    if audio_result:
        logger.info("")
        logger.info("AUDIO SUCCESS: %s", audio_result["url"])
        logger.info("Duration: %.1f sec (%.1f min)", audio_result["duration_seconds"],
                     audio_result["duration_seconds"] / 60)
        logger.info("File: %s", output_path)
    else:
        logger.error("AUDIO FAILED")


if __name__ == "__main__":
    main()
