#!/usr/bin/env python3
"""
classify_story_types.py — Classify Dream Valley stories into story type categories.

Reads content.json, sends each story's text to Mistral AI,
and writes the story_type tag back into the JSON. The six story types are:

    folk_tale      — Warm oral storyteller voice, named character, rule-of-three
    mythological   — Origin story, how something in nature came to be
    fable          — Two characters in dialogue, a quiet truth emerges
    nature         — Real animals, real phenomena, no magic
    slice_of_life  — Ordinary domestic evening, no fantasy
    dream          — Surreal, dream logic, impossible things as normal

Usage:
    python3 scripts/classify_story_types.py --dry-run          # Preview only
    python3 scripts/classify_story_types.py                     # Classify and save
    python3 scripts/classify_story_types.py --skip-classified   # Skip already-done items
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"

# ── Load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

from mistralai import Mistral

# ── Constants ────────────────────────────────────────────────────────────
VALID_STORY_TYPES = {"folk_tale", "mythological", "fable", "nature", "slice_of_life", "dream"}

# Emotion/TTS markers to strip from text before classification
_MARKER_RE = re.compile(
    r"\[/?(?:GENTLE|CALM|DRAMATIC|WHISPERING|ADVENTUROUS|SLEEPY|CURIOUS|"
    r"EXCITED|JOYFUL|MYSTERIOUS|RHYTHMIC|SINGING|HUMMING|"
    r"PAUSE|DRAMATIC_PAUSE|LONG_PAUSE|BREATH_CUE|"
    r"CHAR_START|CHAR_END|PHASE_\d+)\]\s*",
    re.IGNORECASE,
)

CLASSIFICATION_PROMPT = """You are classifying a children's bedtime story into exactly one story type.

The six story types are narrative traditions — how the story is TOLD,
not what it's about. Two stories about a fox in a forest can be different types.

FOLK_TALE — Warm oral storyteller voice. A named character with a clear trait
or problem. The narrator is present ("and do you know what happened next?").
Uses repetition and rule-of-three. Feels like someone TELLING you a story.

MYTHOLOGICAL — Origin story. Explains how something in nature came to be.
Ancient, timeless setting. Characters are forces of nature or archetypes
(the first river, the old mountain, the wind). Elevated but warm voice.
Opens like "Long ago..." or "Before the rivers knew..."

FABLE — Two characters in dialogue debating a truth. Spare, short, pointed.
The truth is never stated as a moral — it emerges from conversation.
Feels like Aesop or Panchatantra.

NATURE — Real animals, real natural phenomena. No magic, no talking animals.
Wonder through precise observation of the real world. Narrator as curious
guide explaining something true. "Did you know that..."

SLICE_OF_LIFE — Ordinary domestic evening. No fantasy, no adventure.
Bath, dinner, pyjamas, family sounds, bedtime routines. The magic is in
the mundane details. Feels like a child's actual evening.

DREAM — Surreal, associative. Impossible things described as completely normal.
Objects transform, logic doesn't apply, the narrator doesn't question anything.
Feels like being inside a dream.

Rules:
- Choose exactly ONE type. Pick the dominant narrative tradition.
- If the story doesn't clearly fit, default to FOLK_TALE (most LLM stories are).
- Focus on HOW the story is told, not WHAT it's about.

Respond with ONLY the type label in lowercase. No explanation.

Story text:
\"\"\"
{story_text}
\"\"\""""


# ─────────────────────────────────────────────────────────────────────────
# Text extraction — story-type-relevant portions
# ─────────────────────────────────────────────────────────────────────────

def extract_story_text(item: dict) -> str:
    """Extract the portion of the story where the narrative tradition is most evident.

    Long stories (phase-tagged in annotated_text):
        Phase 1 + Phase 2 only. Phase 3 is always calm wind-down — skip it.

    Short stories / poems / lullabies (single block):
        First 60% of the text. The tail is always the wind-down.

    After extraction, strip emotion markers and truncate to 3000 chars.
    """
    text = None
    annotated = item.get("annotated_text", "")

    # --- Phase-tagged long stories ---
    if "[PHASE_1]" in annotated and "[PHASE_3]" in annotated:
        phase3_start = annotated.index("[PHASE_3]")
        text = annotated[:phase3_start]

    # --- Single-block content ---
    if text is None:
        full_text = item.get("text", "") or item.get("annotated_text", "")
        if full_text:
            cutoff = int(len(full_text) * 0.6)
            text = full_text[:cutoff]

    if not text:
        raise ValueError(
            f"No text found for '{item.get('title', item.get('id', '?'))}'. "
            f"Keys: {list(item.keys())}"
        )

    # Strip emotion markers
    text = _MARKER_RE.sub("", text)
    # Clean up excess whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Truncate to 3000 chars
    if len(text) > 3000:
        text = text[:3000]

    return text


# ─────────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────────

def classify_story(client: Mistral, story_text: str,
                   model: str = "mistral-small-latest",
                   max_retries: int = 3) -> tuple:
    """Send story text to Mistral, get back one story type label."""
    prompt = CLASSIFICATION_PROMPT.format(story_text=story_text)

    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )
            story_type = response.choices[0].message.content.strip().lower().strip(".'\"")

            if story_type not in VALID_STORY_TYPES:
                print(f"  WARNING: Got '{story_type}', defaulting to 'folk_tale'")
                story_type = "folk_tale"

            return story_type, response.usage
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                wait = min(2 ** (attempt + 1) * 15, 120)
                print(f"  Rate limited (attempt {attempt + 1}/{max_retries}), waiting {wait}s...")
                time.sleep(wait)
                continue
            if attempt < max_retries - 1:
                print(f"  API error: {e}, retrying...")
                time.sleep(5)
                continue
            raise

    # Should not reach here, but default to folk_tale
    return "folk_tale", None


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classify Dream Valley stories into story types")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print classifications without modifying content.json")
    parser.add_argument("--skip-classified", action="store_true",
                        help="Skip stories that already have a story_type field")
    parser.add_argument("--delay", type=float, default=35.0,
                        help="Seconds between API calls (default: 35 for Mistral rate limit)")
    parser.add_argument("--model", default="mistral-small-latest",
                        help="Mistral model to use")
    parser.add_argument("--log", default=str(BASE_DIR / "seed_output" / "story_type_classification_log.csv"),
                        help="Output CSV log path")
    parser.add_argument("--content-json", default=str(CONTENT_PATH),
                        help="Path to content.json")
    args = parser.parse_args()

    # Load content
    content_path = Path(args.content_json)
    if not content_path.exists():
        print(f"ERROR: {content_path} not found")
        sys.exit(1)

    with open(content_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    print(f"Loaded {len(content)} items from {content_path}")
    if args.dry_run:
        print("DRY RUN — content.json will NOT be modified\n")

    # Init Mistral client
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not found in environment")
        sys.exit(1)
    client = Mistral(api_key=api_key)

    # Classify each item
    log_rows = []
    counts = Counter()
    skipped = 0
    errors = 0

    for i, item in enumerate(content):
        title = item.get("title", item.get("id", "?"))[:50]
        item_type = item.get("type", "?")

        # Skip songs (lullabies have no story type)
        if item_type == "song":
            print(f"[{i + 1}/{len(content)}] {title} ({item_type})... skipping (lullaby)")
            skipped += 1
            continue

        print(f"[{i + 1}/{len(content)}] {title} ({item_type})...", end=" ")

        # Skip if already classified
        if args.skip_classified and item.get("story_type"):
            print(f"already '{item['story_type']}', skipping")
            skipped += 1
            counts[item["story_type"]] += 1
            continue

        try:
            story_text = extract_story_text(item)
            story_type, usage = classify_story(client, story_text, args.model)

            print(f"-> {story_type}")

            counts[story_type] += 1
            log_rows.append({
                "id": item.get("id", ""),
                "title": title,
                "type": item_type,
                "story_type": story_type,
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
            })

            # Write story_type to item (in-memory, saved later)
            if not args.dry_run:
                item["story_type"] = story_type

            # Rate limit delay (skip on last item)
            if i < len(content) - 1:
                time.sleep(args.delay)

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1
            log_rows.append({
                "id": item.get("id", ""),
                "title": title,
                "type": item_type,
                "story_type": "error",
                "input_tokens": 0,
                "output_tokens": 0,
            })

    # Save modified content.json
    if not args.dry_run and errors < len(content):
        with open(content_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {content_path}")

    # Write CSV log
    log_path = Path(args.log)
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "title", "type", "story_type",
                           "input_tokens", "output_tokens"]
        )
        writer.writeheader()
        writer.writerows(log_rows)

    # Summary
    total_classified = sum(counts.values())
    print(f"\n{'=' * 55}")
    print(f"DONE — {total_classified} classified, {skipped} skipped, {errors} errors")
    print(f"{'=' * 55}\n")
    for st in ["folk_tale", "mythological", "fable", "nature", "slice_of_life", "dream"]:
        c = counts.get(st, 0)
        pct = (c / total_classified * 100) if total_classified else 0
        bar = "█" * c
        print(f"  {st:15s}  {c:3d}  ({pct:4.1f}%)  {bar}")
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
