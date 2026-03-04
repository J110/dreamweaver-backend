#!/usr/bin/env python3
"""Backfill character card data for existing stories using Mistral AI.

Reads each story's title, description, and text, asks Mistral AI to extract:
  - character.name: lead character's name
  - character.identity: brief personality description (max 15 words)
  - character.special: unique quality that drives the story (max 20 words)
  - character.personality_tags: exactly 2 warm trait words

Usage:
    python3 scripts/backfill_about_data.py                  # All stories missing character
    python3 scripts/backfill_about_data.py --id <story-id>  # Specific story
    python3 scripts/backfill_about_data.py --dry-run         # Preview only
    python3 scripts/backfill_about_data.py --force           # Re-generate even if exists
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from mistralai import Mistral
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-large-latest"

CONTENT_JSON = BASE_DIR / "seed_output" / "content.json"

VALID_TAGS = [
    "Curious", "Brave", "Gentle", "Dreamy", "Playful", "Kind", "Quiet",
    "Wise", "Adventurous", "Warm", "Creative", "Patient", "Cheerful",
    "Determined", "Magical", "Peaceful",
]

PROMPT_TEMPLATE = """Given this bedtime story, extract the lead character's information for a children's app "About" panel.

Title: {title}
Description: {description}
Story text (excerpt): {text_excerpt}

Return ONLY a valid JSON object with these fields (no markdown, no extra text):
{{
    "name": "The lead character's first name from the story",
    "identity": "Who they are through personality, not appearance (max 15 words, e.g. 'A bold little dreamer who talks to shadows')",
    "special": "Their unique ability or quality that drives the story (max 20 words, e.g. 'She can hear the secret songs that flowers sing at night')",
    "personality_tags": ["Trait1", "Trait2"]
}}

Rules:
- name: Extract the actual character name from the story text. If no named character, use the most descriptive name.
- identity: Describe personality and role, NOT physical appearance. Start with "A" or "The".
- special: What makes them unique — should make a child think "how?" or "I want to know more".
- personality_tags: Exactly 2 words from this list: {valid_tags}
- For poems/lullabies without a clear character, use the subject or narrator as the character."""


def generate_character(story: dict):
    """Call Mistral to generate character card for a story."""
    title = story.get("title", "")
    description = story.get("description", "")
    text = story.get("text", "")
    text_excerpt = text[:800] if text else ""

    prompt = PROMPT_TEMPLATE.format(
        title=title,
        description=description,
        text_excerpt=text_excerpt,
        valid_tags=", ".join(VALID_TAGS),
    )

    try:
        resp = client.chat.complete(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)

        name = parsed.get("name", "").strip()
        if not name:
            return None

        # Validate and normalize personality tags
        tags = parsed.get("personality_tags", [])
        valid = [t.strip().title() for t in tags if t.strip().title() in VALID_TAGS]
        if len(valid) < 2:
            # Fill with defaults based on story type
            defaults = ["Curious", "Brave", "Gentle", "Dreamy", "Kind"]
            for d in defaults:
                if d not in valid:
                    valid.append(d)
                if len(valid) >= 2:
                    break
        valid = valid[:2]

        return {
            "name": name,
            "identity": parsed.get("identity", "").strip()[:100],
            "special": parsed.get("special", "").strip()[:150],
            "personality_tags": valid,
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Backfill character card data")
    parser.add_argument("--id", help="Process only this story ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--force", action="store_true", help="Re-generate even if character exists")
    args = parser.parse_args()

    with open(CONTENT_JSON, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    # Filter stories to process
    to_process = []
    for story in all_content:
        if args.id and story.get("id") != args.id:
            continue
        if not args.force:
            existing = story.get("character", {})
            if existing and existing.get("name"):
                continue
        to_process.append(story)

    print(f"\n{'='*60}")
    print(f"  CHARACTER BACKFILL: {len(to_process)} stories to process")
    print(f"  (Total in content.json: {len(all_content)})")
    print(f"  Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    if not to_process:
        print("Nothing to do — all stories already have character data.")
        return

    successes = 0
    failures = 0

    for i, story in enumerate(to_process, 1):
        sid = story.get("id", "?")
        title = story.get("title", "Untitled")
        print(f"[{i:2d}/{len(to_process)}] {title[:55]}", end=" ... ")

        if args.dry_run:
            print("SKIP (dry-run)")
            continue

        character = generate_character(story)
        if character:
            # Update in-memory
            story["character"] = character
            print(f"OK — {character['name']} ({', '.join(character['personality_tags'])})")
            successes += 1
        else:
            print("FAILED (no name extracted)")
            failures += 1

        # Rate limit: Mistral free tier is 2 req/min
        if i < len(to_process):
            time.sleep(31)

    if not args.dry_run and successes > 0:
        # Write back to content.json
        with open(CONTENT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_content, f, ensure_ascii=False, indent=2)
        print(f"\nWrote {successes} character cards to {CONTENT_JSON}")

    print(f"\n{'='*60}")
    print(f"  BACKFILL COMPLETE")
    print(f"  Successes: {successes}")
    print(f"  Failures:  {failures}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
