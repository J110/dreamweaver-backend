#!/usr/bin/env python3
"""
classify_language_levels.py — Classify Dream Valley stories into language levels.

Reads content.json, sends each story's text to Mistral AI,
and writes the language_level tag back into the JSON. The three levels are:

    basic        — Short simple sentences, common words only, no figurative language
    intermediate — Medium sentences, descriptive but accessible, simple similes okay
    advanced     — Rich vocabulary, literary language, metaphors, complex sentences

Lullabies (type=song) and funny shorts are skipped — they don't use language levels.

Usage:
    python3 scripts/classify_language_levels.py --dry-run          # Preview only
    python3 scripts/classify_language_levels.py                     # Classify and save
    python3 scripts/classify_language_levels.py --skip-classified   # Skip already-done items
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
VALID_LEVELS = {"basic", "intermediate", "advanced"}

# Content types that get language levels (lullabies and funny shorts are exempt)
CLASSIFIABLE_TYPES = {"story", "long_story", "poem"}

# Emotion/TTS markers to strip from text before classification
_MARKER_RE = re.compile(
    r"\[/?(?:GENTLE|CALM|DRAMATIC|WHISPERING|ADVENTUROUS|SLEEPY|CURIOUS|"
    r"EXCITED|JOYFUL|MYSTERIOUS|RHYTHMIC|SINGING|HUMMING|"
    r"PAUSE|DRAMATIC_PAUSE|LONG_PAUSE|BREATH_CUE|"
    r"CHAR_START|CHAR_END|PHASE_\d+)\]\s*",
    re.IGNORECASE,
)

CLASSIFICATION_PROMPT = """Read this children's bedtime story written for ages {age_group}.
Rate its vocabulary and sentence complexity:

BASIC — Short simple sentences (5-8 words average). Only common everyday
words. No metaphors or figurative language. A child at the LOWER end of
this age group understands every word without help.

INTERMEDIATE — Medium sentences (8-15 words average). Some descriptive
words but nothing unusual. Simple comparisons ("soft as a cloud").
A typical child in this age group understands comfortably.

ADVANCED — Rich vocabulary, longer sentences, literary language, metaphors,
unusual words. A child at the UPPER end of this age group or a strong
reader understands this. This is the default for most AI-generated content.

Respond with ONLY: basic, intermediate, or advanced

Story text:
\"\"\"
{story_text}
\"\"\""""


# ─────────────────────────────────────────────────────────────────────────
# Text extraction
# ─────────────────────────────────────────────────────────────────────────

def extract_story_text(item: dict) -> str:
    """Extract story text for classification.

    Uses the full text (not just mood-relevant portions like classify_moods.py)
    because language level is about vocabulary/sentence structure throughout.
    Strips emotion markers and truncates to 3000 chars.
    """
    text = None
    annotated = item.get("annotated_text", "")

    # Prefer annotated_text (has full content including phase markers)
    if annotated:
        text = annotated
    else:
        text = item.get("text", "")

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

def classify_story(client: Mistral, story_text: str, age_group: str,
                   model: str = "mistral-small-latest",
                   max_retries: int = 3) -> tuple:
    """Send story text to Mistral, get back one language level label."""
    prompt = CLASSIFICATION_PROMPT.format(
        age_group=age_group,
        story_text=story_text,
    )

    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )
            level = response.choices[0].message.content.strip().lower().strip(".'\"")

            if level not in VALID_LEVELS:
                print(f"  WARNING: Got '{level}', defaulting to 'advanced'")
                level = "advanced"

            return level, response.usage
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

    # Should not reach here, but default to advanced
    return "advanced", None


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classify Dream Valley stories into language levels")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print classifications without modifying content.json")
    parser.add_argument("--skip-classified", action="store_true",
                        help="Skip stories that already have a language_level field")
    parser.add_argument("--delay", type=float, default=35.0,
                        help="Seconds between API calls (default: 35 for Mistral rate limit)")
    parser.add_argument("--model", default="mistral-small-latest",
                        help="Mistral model to use")
    parser.add_argument("--log", default=str(BASE_DIR / "seed_output" / "language_level_classification_log.csv"),
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
    skipped_type = 0
    errors = 0

    for i, item in enumerate(content):
        title = item.get("title", item.get("id", "?"))[:50]
        item_type = item.get("type", "?")

        # Skip lullabies (songs) — they don't use language levels
        if item_type not in CLASSIFIABLE_TYPES:
            print(f"[{i + 1}/{len(content)}] {title} ({item_type})... skipped (type={item_type})")
            skipped_type += 1
            continue

        # Derive age_group from available fields
        age_group = item.get("age_group", "")
        if not age_group:
            age_min = item.get("age_min", 0)
            age_max = item.get("age_max", 0)
            if age_min is not None and age_max is not None and age_max > 0:
                age_group = f"{age_min}-{age_max}"
            elif item.get("target_age") is not None:
                age_group = str(item["target_age"])
            else:
                age_group = "unknown"
        print(f"[{i + 1}/{len(content)}] {title} ({item_type})...", end=" ")

        # Skip if already classified
        if args.skip_classified and item.get("language_level"):
            print(f"already '{item['language_level']}', skipping")
            skipped += 1
            counts[item["language_level"]] += 1
            continue

        try:
            story_text = extract_story_text(item)
            level, usage = classify_story(client, story_text, age_group, args.model)

            print(f"→ {level}")

            counts[level] += 1
            log_rows.append({
                "id": item.get("id", ""),
                "title": title,
                "type": item_type,
                "age_group": age_group,
                "language_level": level,
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
            })

            # Write language_level to item (in-memory, saved later)
            if not args.dry_run:
                item["language_level"] = level

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
                "age_group": age_group,
                "language_level": "error",
                "input_tokens": 0,
                "output_tokens": 0,
            })

    # Save modified content.json
    if not args.dry_run and errors < len(content):
        with open(content_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Saved {content_path}")

        # Also propagate language_level to content_expanded.json (used by generate_content_matrix.py)
        expanded_path = content_path.parent / "content_expanded.json"
        if expanded_path.exists():
            try:
                expanded = json.loads(expanded_path.read_text())
                # Build lookup from content.json classifications
                ll_by_id = {s["id"]: s["language_level"] for s in content if s.get("language_level")}
                updated = 0
                for item in expanded:
                    if item.get("id") in ll_by_id and not item.get("language_level"):
                        item["language_level"] = ll_by_id[item["id"]]
                        updated += 1
                if updated:
                    with open(expanded_path, "w", encoding="utf-8") as f:
                        json.dump(expanded, f, indent=2, ensure_ascii=False)
                    print(f"✅ Propagated language_level to {updated} items in content_expanded.json")
            except Exception as e:
                print(f"⚠️ Could not update content_expanded.json: {e}")

    # Write CSV log
    log_path = Path(args.log)
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "title", "type", "age_group", "language_level",
                           "input_tokens", "output_tokens"]
        )
        writer.writeheader()
        writer.writerows(log_rows)

    # Summary
    total_classified = sum(counts.values())
    print(f"\n{'=' * 60}")
    print(f"DONE — {total_classified} classified, {skipped} skipped (already done), "
          f"{skipped_type} skipped (type), {errors} errors")
    print(f"{'=' * 60}\n")
    for level in ["basic", "intermediate", "advanced"]:
        c = counts.get(level, 0)
        pct = (c / total_classified * 100) if total_classified else 0
        bar = "█" * c
        print(f"  {level:15s}  {c:3d}  ({pct:4.1f}%)  {bar}")
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
