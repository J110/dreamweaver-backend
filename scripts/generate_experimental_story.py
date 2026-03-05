"""Generate an experimental 3-phase bedtime story with character voice + lullaby lyrics.

This is a one-off script for creating a long-form (8-12 min) sleep-inducing story
for ages 2-5 with:
  Phase 1 (Capture):  Fun, engaging, sensory — 250-350 words
  Phase 2 (Descent):  Progressive relaxation, breathing — 200-300 words
  Phase 3 (Sleep):    Dissolving, repetitive, fragments — 150-250 words
  Lullaby:            3 verse + chorus song referencing story imagery

Character dialogue uses [CHAR_START]/[CHAR_END] markers for dual-voice TTS.
Phase transitions use [PHASE_2]/[PHASE_3] markers for pacing changes.

See docs/STORY_GUIDELINES_2_5.md for full guidelines.

Usage:
    python3 scripts/generate_experimental_story.py
    python3 scripts/generate_experimental_story.py --setting "Holi festival"
    python3 scripts/generate_experimental_story.py --dry-run
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

try:
    from mistralai import Mistral
except ImportError:
    print("ERROR: pip install mistralai")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"

# ── Existing catalog titles (for anti-duplication) ─────────────────────
def get_existing_titles():
    if CONTENT_PATH.exists():
        with open(CONTENT_PATH, "r") as f:
            stories = json.load(f)
        return [s.get("title", "") for s in stories]
    return []

# ── Existing character types in catalog ────────────────────────────────
def get_existing_character_types():
    if CONTENT_PATH.exists():
        with open(CONTENT_PATH, "r") as f:
            stories = json.load(f)
        return [s.get("lead_character_type", "human") for s in stories]
    return []

# ── Custom system prompt for 3-phase sleep story ──────────────────────
SYSTEM_PROMPT = """You are an expert children's bedtime story writer and child sleep consultant.
You create stories specifically designed to guide children (ages 2-5) from wakefulness to deep sleep.

Your stories use a scientifically-informed 3-phase structure:
1. CAPTURE phase: Engaging the child's attention with fun, vivid storytelling
2. DESCENT phase: Gradually transitioning to relaxation through disguised progressive relaxation
3. SLEEP phase: Using extremely repetitive, dissolving narrative to induce sleep

You write in simple, sensory, concrete language appropriate for ages 2-5.
You use warm, cozy imagery and animal characters that children love.

CRITICAL RULES:
- Every story must include [EMOTION] markers for TTS narration
- Character dialogue MUST be wrapped in [CHAR_START]...[CHAR_END] markers
- Phase transitions MUST be marked with [PHASE_2] and [PHASE_3]
- Use [LONG_PAUSE] for extended silences in Phase 3
- Use [BREATH_CUE] before breathing exercises in Phase 2
- Separate paragraphs with double newlines
- Return ONLY valid JSON. No markdown fences, no extra text."""


def build_prompt(existing_titles, existing_char_types, setting=None):
    """Build the generation prompt for the 3-phase story + lullaby."""

    # Determine which character types are underrepresented
    type_counts = {}
    for t in existing_char_types:
        type_counts[t] = type_counts.get(t, 0) + 1

    underrepresented = [
        t for t in ["animal", "bird", "sea_creature", "plant", "mythical", "insect"]
        if type_counts.get(t, 0) < 2
    ]
    char_suggestion = ", ".join(underrepresented[:3]) if underrepresented else "animal"

    anti_dup = "\n".join(f"  - {t}" for t in existing_titles[-15:]) if existing_titles else "  (none yet)"

    setting_block = ""
    if setting:
        setting_block = f"""
## STORY SETTING
Set this story during: {setting}
Weave this setting naturally into the story — it should feel like a normal part of the character's world.
The setting provides sensory material (colors, sounds, smells, activities) but the 3-phase sleep structure still takes priority.
The celebration/event should wind down naturally as the character gets sleepy in Phase 2-3.
"""

    return f"""Write a 3-phase bedtime story for children aged 2-5 years old.
The story MUST be 1000-1500 words total (this is CRITICAL — stories under 1000 words are too short).
Target 1200 words. Designed to last 15-22 minutes when narrated slowly.

## CHARACTER
- The main character should be an ANIMAL or FANTASY CREATURE (NOT a human child).
- Pick from underrepresented types: {char_suggestion}
- Give the character a simple, memorable name (1-2 syllables: Pip, Lumi, Fern, Milo, Dot, Kai)
- The character should be warm, curious, and lovable
- The character speaks in short, simple sentences (5-12 words)
{setting_block}
## STORY STRUCTURE

### Phase 1 — CAPTURE (250-400 words)
Goal: Hook the child's attention with a fun, sensory discovery.

- Start with [GENTLE] marker, then use [CURIOUS], [EXCITED], [JOYFUL] as the adventure builds
- One clear, simple storyline — the character discovers something magical and beautiful
- Include 3-5 lines of character dialogue wrapped in [CHAR_START]...[CHAR_END]
- Use lots of sensory language: colors, textures, sounds, smells, warmth
- Simple vocabulary — "sparkly," "warm," "glowing," "soft," "tickly"
- Short sentences: one idea per sentence
- Voice should feel warm and cozy — like a loving parent reading aloud
- End Phase 1 with the character arriving somewhere quieter and cozier

### Phase 2 — DESCENT (400-600 words)
Mark the start with [PHASE_2] on its own line.
Goal: The adventure moves to a quieter place. The character physically relaxes — the child mirrors them. This is the LONGEST phase.

- Use [CALM] and [SLEEPY] markers as the pace slows
- The character settles into a cozy place
- CHARACTER-MODELED RELAXATION: The character physically does what the child should do:
  * Takes a biiiiig breath in... and blows it out slow — ahhhhh
  * Stretches arms/tentacles/wings wide, then goes floppy
  * Yawns a great big yawn
  * Curls up into a tiny ball
  * Feels warmth wrapping around them like a blanket
- Include 4-6 breathing cues marked with [BREATH_CUE]:
  "[BREATH_CUE] She breathed in deep—whoosh—and out—ahhh—slow and steady."
- The character takes big breaths: "took a biiiiig breath in... and blew it out slow like blowing a dandelion"
- Include 1-2 whispered character dialogue lines in [CHAR_START]...[CHAR_END]
- Language shifts to body-based: "the grass felt soft and tickly under her paws," "the air was warm like a blanket"
- Descriptions of warmth, heaviness, coziness increase. Voice pacing slows noticeably.
- Sentences get shorter. More [PAUSE] markers. Pauses stretch.
- Character's glow/light/energy starts dimming

### Phase 3 — SLEEP (350-500 words)
Mark the start with [PHASE_3] on its own line.
Goal: The story dissolves into fragments and silence.

- Use ONLY [SLEEPY] and [WHISPERING] markers
- NO character dialogue — just the narrator's soft voice
- Narrative becomes extremely repetitive:
  "Warm... so warm... soft... so soft..."
  "One light dimmed... then another... then another..."
- Use [LONG_PAUSE] between fragments (4-second silences)
- 10-15 [LONG_PAUSE] markers total
- Fragments get shorter: sentences → phrases → single words
- The story DISSOLVES — it does NOT end. No "The End."
- Last 5-6 lines should be just fragments with long pauses:
  "[WHISPERING] Warm... and safe... [LONG_PAUSE]"
  "[WHISPERING] Sleep now... little one... [LONG_PAUSE]"
  "[WHISPERING] Sleep... [LONG_PAUSE]"

## LULLABY LYRICS
Also write a lullaby (3 verses + 1 repeating chorus) that:
- References the story's character and imagery (at least 2 story-specific images)
- Has a very simple, repetitive chorus (identical each time)
- Uses [verse] and [chorus] section markers
- Each verse: 4 lines, simple rhyme scheme (AABB or ABAB), ~20-30 words
- Chorus: 4 lines, ~15-25 words
- Total: 80-120 words

## EMOTION MARKERS REFERENCE
Available markers (place at start of paragraph or sentence):
- [GENTLE] — Soft, warm moments
- [EXCITED] — Fun discoveries, action
- [CURIOUS] — Wonder, questions
- [JOYFUL] — Happy, bright moments
- [CALM] — Peaceful passages
- [SLEEPY] — Drowsy, slow sections
- [WHISPERING] — Very quiet, intimate
- [PAUSE] — 800ms natural pause
- [DRAMATIC_PAUSE] — 1.5s pause
- [LONG_PAUSE] — 4s extended pause (Phase 3)
- [BREATH_CUE] — 2s pause for breathing
- [CHAR_START] — Start of character dialogue
- [CHAR_END] — End of character dialogue
- [PHASE_2] — Marks descent phase transition
- [PHASE_3] — Marks sleep phase transition

## EXISTING TITLES (do NOT duplicate):
{anti_dup}

## OUTPUT FORMAT
Return ONLY a JSON object (no markdown fences):
{{
    "title": "Story Title",
    "description": "1-2 sentence hook for card view",
    "text": "Full story text with all emotion markers, character markers, and phase markers. Use \\n\\n between paragraphs.",
    "lullaby_lyrics": "Lullaby with [verse] and [chorus] markers",
    "character_name": "Name of the animal character",
    "character_description": "Brief visual description of the character (e.g., 'A tiny glowing jellyfish with soft blue tentacles')",
    "character_type": "animal type (e.g., jellyfish, firefly, fox, butterfly)",
    "morals": ["lesson1"],
    "categories": ["Bedtime", "category2", "category3"],
    "theme": "bedtime",
    "geography": "one of: India, East Asia, Africa, Europe, Americas, Arctic, Ocean"
}}"""


def parse_json_response(raw: str) -> dict:
    """Parse JSON from API response, handling markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        start = 1
        end = len(lines) - 1
        if lines[-1].strip() == "```":
            end = -1
        raw = "\n".join(lines[start:end])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON object
        import re
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def generate_story():
    """Generate the experimental 3-phase story via Mistral."""
    parser = argparse.ArgumentParser(description="Generate a 3-phase bedtime story for ages 2-5")
    parser.add_argument("--setting", type=str, default=None,
                        help="Story setting/situation (e.g., 'Holi festival celebrations')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show prompt only, don't call API")
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set")
        sys.exit(1)

    client = Mistral(api_key=api_key)

    existing_titles = get_existing_titles()
    existing_char_types = get_existing_character_types()

    prompt = build_prompt(existing_titles, existing_char_types, setting=args.setting)

    if args.dry_run:
        print("\n=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT ===")
        print(prompt)
        print(f"\nPrompt length: {len(prompt)} chars")
        if args.setting:
            print(f"Setting: {args.setting}")
        return

    logger.info("Generating 3-phase experimental story via Mistral...")
    logger.info("Target: 1000-1500 words, ages 2-5")
    if args.setting:
        logger.info("Setting: %s", args.setting)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=16384,
                temperature=0.85,
            )
            if response.choices and response.choices[0].message.content:
                raw = response.choices[0].message.content.strip()
                break
            logger.warning("  Attempt %d: Empty response", attempt + 1)
            time.sleep(35)
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str:
                wait = min(2 ** (attempt + 1) * 15, 180)
                logger.warning("  Rate limited. Waiting %ds...", wait)
                time.sleep(wait)
            else:
                logger.error("  API error: %s", e)
                time.sleep(10)
    else:
        logger.error("Failed after %d attempts", max_retries)
        sys.exit(1)

    parsed = parse_json_response(raw)
    if not parsed:
        logger.error("Failed to parse JSON response. Raw output:")
        print(raw[:3000])
        sys.exit(1)

    title = parsed.get("title", "").strip()
    text = parsed.get("text", "").strip()
    lullaby_lyrics = parsed.get("lullaby_lyrics", "").strip()
    description = parsed.get("description", "").strip()
    character_name = parsed.get("character_name", "").strip()
    character_description = parsed.get("character_description", "").strip()
    character_type = parsed.get("character_type", "animal").strip()
    morals = parsed.get("morals", ["Feeling safe and cozy helps you sleep"])
    categories = parsed.get("categories", ["Bedtime", "Animals", "Relaxation"])
    theme = parsed.get("theme", "bedtime")
    geography = parsed.get("geography", "Universal")

    if not title or not text:
        logger.error("Missing title or text in response")
        print(json.dumps(parsed, indent=2)[:3000])
        sys.exit(1)

    word_count = len(text.split())
    logger.info("Generated: '%s'", title)
    logger.info("Character: %s (%s)", character_name, character_type)
    logger.info("Word count: %d", word_count)
    logger.info("Has lullaby lyrics: %s", bool(lullaby_lyrics))

    # Check phase markers
    has_phase2 = "[PHASE_2]" in text or "[phase_2]" in text.lower()
    has_phase3 = "[PHASE_3]" in text or "[phase_3]" in text.lower()
    has_char = "[CHAR_START]" in text or "[char_start]" in text.lower()
    logger.info("Phase markers: Phase2=%s, Phase3=%s, CharVoice=%s", has_phase2, has_phase3, has_char)

    if not has_phase2 or not has_phase3:
        logger.warning("WARNING: Missing phase markers! Story may not have proper 3-phase structure.")

    # Build content object
    content_id = f"gen-{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    content_obj = {
        "id": content_id,
        "type": "long_story",
        "lang": "en",
        "title": title,
        "description": description,
        "text": text,
        "annotated_text": text,
        "lullaby_lyrics": lullaby_lyrics,
        "target_age": 3,
        "age_min": 2,
        "age_max": 5,
        "age_group": "2-5",
        "length": "LONG",
        "word_count": word_count,
        "duration_seconds": 0,
        "duration": 10,
        "categories": categories,
        "theme": theme,
        "morals": morals,
        "cover": "",
        "musicProfile": "dreamy-clouds",
        "musicParams": {},
        "music_type": "ambient",
        "audio_variants": [],
        "author_id": "system",
        "is_generated": True,
        "generation_quality": "pending_review",
        "lead_gender": "neutral",
        "lead_character_type": character_type,
        "character_name": character_name,
        "character_description": character_description,
        "universe": "fantasy_realm",
        "geography": geography,
        "life_aspect": "sleep_comfort",
        "plot_archetype": "transformation",
        "created_at": now,
        "updated_at": now,
        "view_count": 0,
        "like_count": 0,
        "save_count": 0,
    }

    # Add to content.json
    if CONTENT_PATH.exists():
        with open(CONTENT_PATH, "r", encoding="utf-8") as f:
            all_stories = json.load(f)
    else:
        all_stories = []

    all_stories.append(content_obj)

    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_stories, f, ensure_ascii=False, indent=2)
        f.write("\n")

    logger.info("Added to content.json (total: %d stories)", len(all_stories))
    logger.info("Story ID: %s", content_id)
    logger.info("")
    logger.info("=== NEXT STEPS ===")
    logger.info("1. Review the story text and lullaby lyrics")
    logger.info("2. Generate audio: python3 scripts/generate_audio.py --story-id %s --force --speed 0.8", content_id)
    logger.info("3. Run QA: python3 scripts/qa_audio.py --story-id %s --no-quality-score", content_id)
    logger.info("4. Generate music: python3 scripts/generate_music_params.py --id %s", content_id)

    return content_id


if __name__ == "__main__":
    generate_story()
