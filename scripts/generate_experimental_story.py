"""Generate an experimental 3-phase bedtime story with character voice + lullaby lyrics.

This is a one-off script for creating a long-form (15-20 min) sleep-inducing story
for ages 2-5 with:
  Phase 1 (Capture):  Fun, engaging, sensory — 400-600 words
  Phase 2 (Descent):  Progressive relaxation, breathing — 600-900 words
  Phase 3 (Sleep):    Dissolving, repetitive, fragments — 500-800 words
  Lullaby:            2-3 verse song referencing story imagery

Character dialogue uses [CHAR_START]/[CHAR_END] markers for dual-voice TTS.
Phase transitions use [PHASE_2]/[PHASE_3] markers for pacing changes.

Usage:
    python3 scripts/generate_experimental_story.py
    python3 scripts/generate_experimental_story.py --dry-run   # Show prompt only
"""

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


def build_prompt(existing_titles, existing_char_types):
    """Build the generation prompt for the 3-phase story + lullaby."""

    # Determine which character types are underrepresented
    type_counts = {}
    for t in existing_char_types:
        type_counts[t] = type_counts.get(t, 0) + 1

    underrepresented = [
        t for t in ["animal", "bird", "sea_creature", "plant", "mythical"]
        if type_counts.get(t, 0) < 2
    ]
    char_suggestion = ", ".join(underrepresented[:3]) if underrepresented else "animal"

    anti_dup = "\n".join(f"  - {t}" for t in existing_titles[-15:]) if existing_titles else "  (none yet)"

    return f"""Write a 3-phase bedtime story for children aged 2-5 years old.
The story should be 1500-2500 words total and designed to last 15-20 minutes when narrated slowly.

## CHARACTER
- The main character should be an ANIMAL (choose one that's NOT already in our catalog).
- Pick from underrepresented types: {char_suggestion}
- Give the character a simple, memorable name
- The character should be warm, curious, and lovable
- The character speaks in short, simple sentences

## STORY STRUCTURE

### Phase 1 — CAPTURE (400-600 words)
Goal: Hook the child's attention with a fun, vivid scenario.

- Start with [GENTLE] marker, then use [EXCITED], [CURIOUS], [JOYFUL] as the adventure builds
- One clear, simple storyline — the character discovers something magical
- Include 3-5 lines of character dialogue wrapped in [CHAR_START]...[CHAR_END]
- Use lots of sensory language: colors, textures, sounds, smells
- Include 2-3 rhetorical engagement hooks like "Can you guess what happened next?"
- Voice should feel warm and gently animated — cozy storytelling, not cartoon energy
- End Phase 1 with the character arriving somewhere quieter

### Phase 2 — DESCENT (600-900 words)
Mark the start with [PHASE_2] on its own line.
Goal: Guide the child toward relaxation through the story.

- Use [CALM] and [SLEEPY] markers as the pace slows
- The adventure moves to a quiet, cozy place
- Language shifts to body-based, sensory descriptions:
  "the grass felt soft and tickly under her paws"
  "the air was warm like a blanket"
- DISGUISED PROGRESSIVE RELAXATION: The character physically does what the child should do:
  * Stretches arms wide, then goes floppy
  * Takes big breaths ("took a biiiiig breath in... and blew it out slow like blowing a dandelion")
  * Yawns great big yawns
  * Curls up smaller and smaller
- Include 3-4 explicit breathing cues marked with [BREATH_CUE]:
  "[BREATH_CUE] The little [character] breathed in deep... in through the nose... and out through the mouth... ahhhhh."
- Include 1-2 quiet character dialogue lines in [CHAR_START]...[CHAR_END] (whispered)
- Descriptions of warmth, heaviness, coziness increase
- Pacing slows noticeably — shorter sentences, more pauses [PAUSE]

### Phase 3 — SLEEP (500-800 words)
Mark the start with [PHASE_3] on its own line.
Goal: The story dissolves. Induce sleep through extreme repetition and fragmentation.

- Use only [SLEEPY] and [WHISPERING] markers
- NO character dialogue — just the narrator's soft voice
- The character is now in their cozy sleeping place
- Narrative becomes extremely repetitive and cyclical:
  "One star lit up... then another... then another... each one soft and quiet..."
  "Warm... so warm... soft... so soft..."
- Descriptions focus on: heaviness, warmth, softness, closing eyes, sinking into bed
- Use [LONG_PAUSE] between fragments (these become 4-second silences)
- The story doesn't end — it DISSOLVES
- Last 5-6 "sentences" should be just fragments with long pauses:
  "[WHISPERING] soft blanket of stars..."
  "[LONG_PAUSE]"
  "[WHISPERING] warm... and safe..."
  "[LONG_PAUSE]"
  "[WHISPERING] sleep now..."
  "[LONG_PAUSE]"

## LULLABY LYRICS
Also write a simple lullaby (3 verses + 1 chorus) that:
- References the story's character and imagery
- Has a very simple, repetitive chorus
- Uses [verse] and [chorus] section markers
- Is soothing, slow, and sleep-inducing
- Each verse: 4 lines, simple rhyme scheme (AABB or ABAB)
- Chorus: 4 lines, very repetitive

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
    "character_type": "animal type (e.g., otter, hedgehog, deer)",
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
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set")
        sys.exit(1)

    client = Mistral(api_key=api_key)

    existing_titles = get_existing_titles()
    existing_char_types = get_existing_character_types()

    prompt = build_prompt(existing_titles, existing_char_types)

    # Check for --dry-run
    if "--dry-run" in sys.argv:
        print("\n=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT ===")
        print(prompt)
        print(f"\nPrompt length: {len(prompt)} chars")
        return

    logger.info("Generating 3-phase experimental story via Mistral...")
    logger.info("Target: 1500-2500 words, ages 2-5")

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
        "type": "story",
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
        "duration": 18,
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
