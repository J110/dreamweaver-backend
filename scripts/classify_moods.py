#!/usr/bin/env python3
"""
classify_moods.py — Classify Dream Valley stories into mood categories.

Reads content.json, sends each story's mood-relevant text to Mistral AI,
and writes the mood tag back into the JSON. The six moods are:

    wired    — Silly, playful, humorous energy
    curious  — Discovery, exploration, wonder
    calm     — Gentle, sensory, low energy throughout
    sad      — Loss, loneliness, comfort without fixing
    anxious  — Fear, worry, encountering the scary thing safely
    angry    — Frustration, unfairness, anger finding an outlet

Usage:
    python3 scripts/classify_moods.py --dry-run          # Preview only
    python3 scripts/classify_moods.py                     # Classify and save
    python3 scripts/classify_moods.py --skip-classified   # Skip already-done items
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
VALID_MOODS = {"wired", "curious", "calm", "sad", "anxious", "angry"}

# Emotion/TTS markers to strip from text before classification
_MARKER_RE = re.compile(
    r"\[/?(?:GENTLE|CALM|DRAMATIC|WHISPERING|ADVENTUROUS|SLEEPY|CURIOUS|"
    r"EXCITED|JOYFUL|MYSTERIOUS|RHYTHMIC|SINGING|HUMMING|"
    r"PAUSE|DRAMATIC_PAUSE|LONG_PAUSE|BREATH_CUE|"
    r"CHAR_START|CHAR_END|PHASE_\d+)\]\s*",
    re.IGNORECASE,
)

CLASSIFICATION_PROMPT = """You are classifying a children's bedtime story into exactly one mood category.

The story is written for ages {age_group}.

The six moods are:

WIRED — The story uses humor, absurdity, silliness, or playful energy to capture attention. Characters do funny things, premises are ridiculous, there's laughter or comic timing in the narrative.

CURIOUS — The story is driven by discovery, exploration, mystery, or wonder. A character follows something, finds something, investigates something. There's forward motion and intrigue.

CALM — The story is gentle and sensory from the start. Minimal plot. Soft descriptions of warmth, texture, sound, light. A character resting, watching, being present. Low energy throughout.

SAD — The story centers on loss, disappointment, loneliness, or missing someone/something. A character feels heavy or withdrawn. The story validates the sadness and offers comfort through companionship or gentle reframing — but does NOT fix the problem.

ANXIOUS — The story features a character who is afraid, worried, or hypervigilant. Fear of the dark, fear of the unknown, fear of tomorrow, fear of being alone. The feared thing is encountered and revealed as safe, or the worry is reframed.

ANGRY — The story features a character who is frustrated, upset about unfairness, or emotionally hot. The anger is validated and given an outlet — physical release, transformation, or gradual exhaustion.

Rules:
- Choose exactly ONE mood.
- If the story doesn't clearly fit any mood, default to CALM.
- A story can have mild elements of multiple moods. Pick the dominant one.

Respond with ONLY the mood label in lowercase. No explanation. No punctuation.

Story text:
\"\"\"
{story_text}
\"\"\""""


# ─────────────────────────────────────────────────────────────────────────
# Text extraction — mood-relevant portions only
# ─────────────────────────────────────────────────────────────────────────

def extract_story_text(item: dict) -> str:
    """Extract the portion of the story where the mood is most evident.

    Long stories (phase-tagged in annotated_text):
        Phase 1 + Phase 2 only. Phase 3 is always calm — skip it.

    Short stories / poems / lullabies (single block):
        First 60% of the text. The tail is always the wind-down.

    After extraction, strip emotion markers and truncate to 3000 chars.
    """
    text = None
    annotated = item.get("annotated_text", "")

    # --- Phase-tagged long stories ---
    if "[PHASE_1]" in annotated and "[PHASE_3]" in annotated:
        # Extract everything from [PHASE_1] up to (but not including) [PHASE_3]
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

def classify_story(client: Mistral, story_text: str, age_group: str,
                   model: str = "mistral-small-latest",
                   max_retries: int = 3) -> tuple:
    """Send story text to Mistral, get back one mood label."""
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
            mood = response.choices[0].message.content.strip().lower().strip(".'\"")

            if mood not in VALID_MOODS:
                print(f"  WARNING: Got '{mood}', defaulting to 'calm'")
                mood = "calm"

            return mood, response.usage
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

    # Should not reach here, but default to calm
    return "calm", None


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classify Dream Valley stories into moods")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print classifications without modifying content.json")
    parser.add_argument("--skip-classified", action="store_true",
                        help="Skip stories that already have a mood field")
    parser.add_argument("--delay", type=float, default=35.0,
                        help="Seconds between API calls (default: 35 for Mistral rate limit)")
    parser.add_argument("--model", default="mistral-small-latest",
                        help="Mistral model to use")
    parser.add_argument("--log", default=str(BASE_DIR / "seed_output" / "mood_classification_log.csv"),
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
        age_group = item.get("age_group", "unknown")
        print(f"[{i + 1}/{len(content)}] {title} ({item_type})...", end=" ")

        # Skip if already classified
        if args.skip_classified and item.get("mood"):
            print(f"already '{item['mood']}', skipping")
            skipped += 1
            counts[item["mood"]] += 1
            continue

        try:
            story_text = extract_story_text(item)
            mood, usage = classify_story(client, story_text, age_group, args.model)

            print(f"→ {mood}")

            counts[mood] += 1
            log_rows.append({
                "id": item.get("id", ""),
                "title": title,
                "type": item_type,
                "age_group": age_group,
                "mood": mood,
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
            })

            # Write mood to item (in-memory, saved later)
            if not args.dry_run:
                item["mood"] = mood

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
                "mood": "error",
                "input_tokens": 0,
                "output_tokens": 0,
            })

    # Save modified content.json
    if not args.dry_run and errors < len(content):
        with open(content_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Saved {content_path}")

    # Write CSV log
    log_path = Path(args.log)
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "title", "type", "age_group", "mood",
                           "input_tokens", "output_tokens"]
        )
        writer.writeheader()
        writer.writerows(log_rows)

    # Summary
    total_classified = sum(counts.values())
    print(f"\n{'=' * 55}")
    print(f"DONE — {total_classified} classified, {skipped} skipped, {errors} errors")
    print(f"{'=' * 55}\n")
    for mood in ["calm", "curious", "wired", "sad", "anxious", "angry"]:
        c = counts.get(mood, 0)
        pct = (c / total_classified * 100) if total_classified else 0
        bar = "█" * c
        print(f"  {mood:10s}  {c:3d}  ({pct:4.1f}%)  {bar}")
    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
