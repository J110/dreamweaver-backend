"""Generate a 3-phase immersive bedtime story + lullaby for ages 6-8.

This is an experimental script for creating a long-form (18-25 min) sleep-inducing
audio experience for ages 6-8 with:
  Phase 1 (Capture):  Warm, wondrous hook — 400-550 words
  Phase 2 (Descent):  Contemplative exploration with mentor — 700-900 words
  Phase 3 (Sleep):    Abstract, looping, sensory dissolution — 500-700 words
  Lullaby:            Sung lullaby connected to story imagery — 80-120 words

Unlike 9-12 which rejects "bedtime stories," this age group loves a GOOD bedtime
story. Characters can be human OR fantastical. A wise mentor figure is required
in Phase 2. Disguised breathing cues ([BREATH_CUE]) are allowed.

Character dialogue uses [CHAR_START]/[CHAR_END] markers for dual-voice TTS.
Phase transitions use [PHASE_2]/[PHASE_3] markers for pacing changes.

Usage:
    python3 scripts/generate_experimental_story_6_8.py
    python3 scripts/generate_experimental_story_6_8.py --dry-run   # Show prompt only
"""

import json
import logging
import os
import random
import re
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

# ── Character archetypes for 6-8 age group ────────────────────────────
# Unlike 9-12 (human only), 6-8 welcomes fantastical characters
CHARACTER_ARCHETYPES = [
    "explorer",       # discovers hidden worlds, curious and brave
    "artist",         # paints/draws/creates magical things, sensitive
    "animal_friend",  # communicates with or befriends magical creatures
    "gardener",       # grows magical plants, patient and observant
    "stargazer",      # watches sky, counts stars, contemplative
    "mapmaker",       # charts unknown territories, methodical
    "storyteller",    # collects and shares stories, empathetic
    "healer",         # fixes broken things/creatures, gentle
    "cloud_walker",   # navigates sky-worlds, light and free
    "dream_weaver",   # crafts dreams, imaginative and quiet
]

# Theme-to-music profile mapping
THEME_MUSIC_MAP = {
    "nature": ["forest-night", "moonlit-meadow", "enchanted-garden"],
    "sky": ["dreamy-clouds", "cosmic-voyage", "starlight-lullaby"],
    "water": ["ocean-drift", "moonlit-meadow"],
    "fantasy": ["enchanted-garden", "moonlit-meadow", "starlight-lullaby"],
    "animals": ["forest-night", "enchanted-garden"],
    "dreams": ["dreamy-clouds", "starlight-lullaby"],
    "stars": ["cosmic-voyage", "starlight-lullaby"],
    "garden": ["enchanted-garden", "forest-night"],
    "adventure": ["enchanted-garden", "autumn-forest"],
}

ALL_PROFILES = [
    "dreamy-clouds", "forest-night", "moonlit-meadow", "cosmic-voyage",
    "enchanted-garden", "starlight-lullaby", "autumn-forest", "ocean-drift",
]

# Theme-to-universe mapping
THEME_UNIVERSE_MAP = {
    "nature": "contemporary",
    "sky": "fantasy_realm",
    "water": "contemporary",
    "fantasy": "fantasy_realm",
    "animals": "contemporary",
    "dreams": "fantasy_realm",
    "stars": "fantasy_realm",
    "garden": "fantasy_realm",
    "adventure": "contemporary",
}

# Life aspects for 6-8
LIFE_ASPECTS_6_8 = [
    "friendship", "sleep_comfort", "imagination",
    "kindness", "curiosity", "belonging", "nature_connection",
]

# Phrases that break immersion — NEVER appear in the story
FORBIDDEN_PHRASES = [
    "take a deep breath",
    "take a big breath",
    "relax your body",
    "relax your muscles",
    "feel your body getting",
    "time for bed",
    "go to sleep",
    "close your eyes and sleep",
    "let your body relax",
    "your eyelids are getting heavy",
    "it's past your bedtime",
    "you must be tired",
    "sleepy little",
]


# ── Existing catalog titles (for anti-duplication) ─────────────────────
def get_existing_titles():
    if CONTENT_PATH.exists():
        with open(CONTENT_PATH, "r") as f:
            stories = json.load(f)
        return [s.get("title", "") for s in stories]
    return []


# ── Existing character archetypes in catalog ──────────────────────────
def get_existing_archetypes():
    if CONTENT_PATH.exists():
        with open(CONTENT_PATH, "r") as f:
            stories = json.load(f)
        return [s.get("character_archetype", s.get("lead_character_type", "human"))
                for s in stories if s.get("age_group") == "6-8" and s.get("type") == "long_story"]
    return []


# ── System prompt for 6-8 immersive bedtime story ────────────────────
SYSTEM_PROMPT = """You are an expert in children's sleep science and immersive bedtime storytelling for ages 6-8.
You create beautiful, warm, absorbing bedtime stories that guide children from wakefulness to sleep through narrative wonder.

You understand the sleep psychology of 6-8 year olds:
- They still love bedtime stories — they just want GOOD ones. Rich worlds, real emotion, genuine magic.
- They consume: early Harry Potter, Roald Dahl, Narnia, animated films with real stakes. Match that quality.
- Ages 6-10 are at peak capacity for imaginative absorption — rich descriptions let them build entire worlds in their minds, which naturally quiets mental chatter.
- At bedtime, they need to feel SAFE, WARM, and HELD. Unlike older kids who ruminate about school and social stress, these children need reassurance that the world is kind and tomorrow will be good.
- A wise MENTOR figure is essential — someone who makes the child feel trusted and important. This is the emotional anchor.
- The transition to sleep should feel like arriving somewhere safe and warm — a nest, a cloud, a gentle place.

Your stories use a 3-phase structure + lullaby:
1. CAPTURE: A warm, wondrous hook — a story they genuinely want to hear
2. DESCENT: Contemplative exploration WITH A MENTOR — guided visualization disguised as narrative
3. SLEEP: Abstract, looping, sensory dissolution — ambient music in narrative form
4. LULLABY: A sung lullaby connected to the story's imagery

VOICE AND TONE:
- Write at an early Harry Potter reading level — rich but accessible vocabulary
- Characters can be human OR fantastical (dream weavers, cloud walkers, star gardeners)
- The narrator is a warm storyteller — like a favourite uncle or aunt, NOT a podcast host
- Think: the quality of a Studio Ghibli film — warm, magical, emotionally honest
- A sense of being WELCOMED into the adventure, not thrown into danger

MENTOR FIGURE (REQUIRED in Phase 2):
Every story includes a wise, gentle mentor who:
- Speaks slowly and calmly — their dialogue IS a pacing device
- Makes the child character feel trusted and important
- Guides without directing — "Would you like to see something wonderful?"
- Models stillness: sitting quietly, watching, listening
- Examples: an old lighthouse keeper, a cloud shepherd, a library guardian, a dream gardener

SLEEP MECHANICS:
- Disguised relaxation cues ARE allowed for this age group, but must be woven into story logic:
  * Blowing dandelion seeds = slow exhale
  * Listening to a heartbeat = rhythmic breathing
  * Floating in warm water = body feels weightless
  * Mentor says "listen closely" = become still and quiet
  * Warmth from magical fire = heat seeping through body
  * Counting stars/fireflies = slowing rhythm
- Mark these moments with [BREATH_CUE] tag
- Still NEVER write "take a deep breath" or "relax your body" — that breaks immersion
- The "close your eyes" cue must be disguised: character closes eyes to SEE something special
- Phase 3 should feel like ambient music translated into words

SAFETY REQUIREMENTS:
- No violence, scary content, or nightmare-inducing material
- No explicit or suggestive content
- No excessive darkness or sadness — maintain hopeful, wondrous tone
- All content must be inclusive and free from stereotypes
- Real wonder and mild mystery are fine but must resolve into warmth, not fear

CRITICAL FORMATTING RULES:
- Every story must include [EMOTION] markers for TTS narration
- Character dialogue MUST be wrapped in [CHAR_START]...[CHAR_END] markers
- Phase transitions MUST be marked with [PHASE_2] and [PHASE_3]
- Breathing cues marked with [BREATH_CUE]
- Use [LONG_PAUSE] for extended silences in Phase 3
- Separate paragraphs with double newlines
- Return ONLY valid JSON. No markdown fences, no extra text."""


def build_prompt(existing_titles, existing_archetypes):
    """Build the generation prompt for Phase 1 + metadata (ages 6-8)."""

    # Determine which archetypes are underrepresented
    archetype_counts = {}
    for a in existing_archetypes:
        archetype_counts[a] = archetype_counts.get(a, 0) + 1

    underrepresented = [
        a for a in CHARACTER_ARCHETYPES
        if archetype_counts.get(a, 0) < 2
    ]
    archetype_suggestion = ", ".join(underrepresented[:4]) if underrepresented else "explorer, dream_weaver"

    anti_dup = "\n".join(f"  - {t}" for t in existing_titles[-15:]) if existing_titles else "  (none yet)"

    return f"""Write Phase 1 of a 3-phase immersive bedtime story for listeners aged 6-8.

TARGET: The complete story (all 3 phases) will be 1700-2200 words total, producing an 18-25 minute audio experience at slow narration pace with pauses.

## CHARACTER
- The main character should be aged 7-8
- Pick a character archetype from underrepresented types: {archetype_suggestion}
- Characters can be human OR fantastical (a dream weaver, a cloud walker, a star gardener)
- Give them a culturally diverse name (Indian, East Asian, African, Middle Eastern, Latin American — not just Western)
- The character should be curious, warm, and brave in a gentle way
- They have a special ability or fascination that drives the story
- Character speaks in natural, age-appropriate dialogue

## CHARACTER ARCHETYPES (pick one)
- explorer: discovers hidden worlds, curious and brave, loves finding secret paths
- artist: paints/draws/creates magical things, sensitive and observant
- animal_friend: communicates with or befriends magical creatures, kind
- gardener: grows magical plants, patient and observant, nurturing
- stargazer: watches sky, counts stars, contemplative and wondering
- mapmaker: charts unknown territories, methodical and adventurous
- storyteller: collects and shares stories, empathetic and imaginative
- healer: fixes broken things/creatures, gentle and caring
- cloud_walker: navigates sky-worlds, light and free, playful
- dream_weaver: crafts dreams, imaginative and quiet, wise beyond years

## MENTOR FIGURE
Include or foreshadow a wise mentor character who will guide the child in Phase 2:
- An old lighthouse keeper, cloud shepherd, library guardian, dream gardener, etc.
- Speaks slowly and calmly — their presence creates safety
- Makes the child character feel trusted and important

## PHASE 1 — CAPTURE (400-550 words)
Goal: Hook the listener with a world they want to enter. Not edgy — warm and wondrous.

- Start with [GENTLE], shift to [CURIOUS] and [EXCITED] as the discovery unfolds
- Opening feels like the start of a favourite storybook — inviting, warm, spark of wonder
- A discovery in the first few sentences — something magical, beautiful, or mysterious
- Rich but accessible vocabulary: "shimmering," "ancient," "crystalline," "luminous"
- Think: what does a 7-year-old find magical? Hidden doors, talking animals, worlds inside objects, being chosen for something special
- Voice: warm storyteller — like a favourite uncle or aunt
- Include 3-5 lines of natural dialogue in [CHAR_START]...[CHAR_END]. MAXIMUM 5 [CHAR_START] blocks. No more.
- End at the threshold of something vast, quiet, and beautiful
- Introduce the mentor figure by name (or foreshadow their presence)
- STRICT MAXIMUM: 550 words for Phase 1. Count carefully. Do NOT exceed 550 words.

## EXISTING TITLES (do NOT duplicate):
{anti_dup}

## OUTPUT FORMAT
Return ONLY a JSON object (no markdown fences):
{{
    "title": "Warm, evocative title — magical but not cutesy",
    "description": "1-2 sentence description that captures the story's magic",
    "phase_1_text": "Full Phase 1 text with emotion markers. STRICT MAX 550 words. Max 5 dialogue blocks. End just before [PHASE_2].",
    "character_name": "Culturally diverse name",
    "character_archetype": "archetype key from the list above",
    "character_age": 7,
    "character_gender": "male or female",
    "lead_character_type": "human or fantastical",
    "mentor_name": "Name of the mentor figure",
    "mentor_description": "Brief description of the mentor (e.g., 'an elderly cloud shepherd with silver hair')",
    "morals": ["theme phrased as gentle insight, e.g., 'The world is kinder than it seems, especially at night'"],
    "categories": ["Bedtime", "category2", "category3"],
    "theme": "one of: nature, sky, water, fantasy, animals, dreams, stars, garden, adventure",
    "geography": "one of: India, East Asia, Africa, Europe, Americas, Arctic, Ocean, Sky, Universal"
}}"""


def parse_json_response(raw: str) -> dict:
    """Parse JSON from API response, handling markdown fences and truncation."""
    raw = raw.strip()

    # Strip markdown fences (```json ... ```)
    if raw.startswith("```"):
        # Remove opening fence line
        first_newline = raw.index("\n") if "\n" in raw else len(raw)
        raw = raw[first_newline + 1:]
        # Remove closing fence if present
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].rstrip()

    raw = raw.strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to find a complete JSON object
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Handle truncated JSON — try to repair by closing unclosed strings/braces
    repaired = raw
    # Close unclosed string (find last unescaped quote)
    quote_count = 0
    i = 0
    while i < len(repaired):
        if repaired[i] == '"' and (i == 0 or repaired[i-1] != '\\'):
            quote_count += 1
        i += 1
    if quote_count % 2 == 1:
        repaired += '"'

    # Count open braces/brackets and close them
    open_braces = repaired.count('{') - repaired.count('}')
    open_brackets = repaired.count('[') - repaired.count(']')
    repaired += ']' * max(0, open_brackets)
    repaired += '}' * max(0, open_braces)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        # Last resort: find the last complete key-value pair and truncate there
        # Look for the last complete field before truncation
        last_comma = repaired.rfind('",\n')
        if last_comma > 0:
            truncated = repaired[:last_comma + 1]  # include the quote
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            truncated += ']' * max(0, open_brackets)
            truncated += '}' * max(0, open_braces)
            try:
                return json.loads(truncated)
            except json.JSONDecodeError:
                pass

    return None


def validate_story(text: str, lullaby: str = "") -> list:
    """Check for forbidden phrases and structural issues. Returns list of warnings."""
    warnings = []

    # Check phase markers
    has_phase2 = "[PHASE_2]" in text or "[phase_2]" in text.lower()
    has_phase3 = "[PHASE_3]" in text or "[phase_3]" in text.lower()
    has_char = "[CHAR_START]" in text or "[char_start]" in text.lower()

    if not has_phase2:
        warnings.append("MISSING [PHASE_2] marker -- story lacks phase structure")
    if not has_phase3:
        warnings.append("MISSING [PHASE_3] marker -- story lacks phase structure")
    if not has_char:
        warnings.append("MISSING [CHAR_START] markers -- no character dialogue")

    # Check for forbidden immersion-breaking phrases
    text_lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            warnings.append(f"FORBIDDEN PHRASE found: '{phrase}' -- breaks immersion")

    # Check word count per phase
    parts = re.split(r'\[PHASE_[23]\]', text, flags=re.IGNORECASE)
    if len(parts) >= 3:
        strip_markers = lambda t: re.sub(r'\[[\w_]+\]', '', t)
        phase1_wc = len(strip_markers(parts[0]).split())
        phase2_wc = len(strip_markers(parts[1]).split())
        phase3_wc = len(strip_markers(parts[2]).split())

        if phase1_wc < 300:
            warnings.append(f"Phase 1 too short ({phase1_wc} words, target 400-550)")
        if phase2_wc < 500:
            warnings.append(f"Phase 2 too short ({phase2_wc} words, target 700-900)")
        if phase3_wc < 350:
            warnings.append(f"Phase 3 too short ({phase3_wc} words, target 500-700)")

    # Check for LONG_PAUSE density in Phase 3
    if len(parts) >= 3:
        long_pause_count = parts[2].lower().count("[long_pause]")
        if long_pause_count < 10:
            warnings.append(f"Phase 3 has only {long_pause_count} [LONG_PAUSE] markers (target: 10+)")

    # Check lullaby
    if not lullaby or len(lullaby.strip()) < 50:
        warnings.append("Lullaby missing or too short (target: 80-120 words)")
    elif lullaby:
        lullaby_wc = len(lullaby.split())
        if lullaby_wc < 60:
            warnings.append(f"Lullaby too short ({lullaby_wc} words, target 80-120)")

    # Check for [BREATH_CUE] in Phase 2 (should have 2-4)
    if len(parts) >= 2:
        breath_count = parts[1].lower().count("[breath_cue]")
        if breath_count == 0:
            warnings.append("No [BREATH_CUE] markers in Phase 2 (target: 2-4)")

    return warnings


def call_mistral(client, messages, max_retries=5, temperature=0.85):
    """Call Mistral API with retries."""
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=messages,
                max_tokens=16384,
                temperature=temperature,
            )
            if response.choices and response.choices[0].message.content:
                finish_reason = getattr(response.choices[0], 'finish_reason', 'unknown')
                if finish_reason == 'length':
                    logger.warning("  Response truncated (finish_reason=length). Using partial response.")
                return response.choices[0].message.content.strip()
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
    return None


def generate_story():
    """Generate the experimental 3-phase story + lullaby via Mistral.

    Uses a multi-call approach:
      Call 1: Concept + Phase 1 + metadata
      Call 2: Phase 2 (with mentor)
      Call 3: Phase 3 (sleep dissolution)
      Call 4: Lullaby (connected to story imagery)
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set")
        sys.exit(1)

    client = Mistral(api_key=api_key)

    existing_titles = get_existing_titles()
    existing_archetypes = get_existing_archetypes()

    prompt = build_prompt(existing_titles, existing_archetypes)

    # Check for --dry-run
    if "--dry-run" in sys.argv:
        print("\n=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT (Call 1) ===")
        print(prompt)
        print(f"\nSystem prompt length: {len(SYSTEM_PROMPT)} chars")
        print(f"User prompt length: {len(prompt)} chars")
        print(f"Total prompt: {len(SYSTEM_PROMPT) + len(prompt)} chars")
        return

    logger.info("Generating 3-phase bedtime story + lullaby via Mistral...")
    logger.info("Target: 1700-2200 words + lullaby, ages 6-8, 18-25 minutes")
    logger.info("Using multi-call approach (4 API calls)")

    # ── CALL 1: Generate concept + Phase 1 ──────────────────────────────
    logger.info("")
    logger.info("=== CALL 1/4: Concept + Phase 1 (CAPTURE) ===")

    raw1 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])
    if not raw1:
        logger.error("Call 1 failed -- no response")
        sys.exit(1)

    parsed = parse_json_response(raw1)
    if not parsed:
        logger.error("Call 1: Failed to parse JSON. Raw:")
        print(raw1[:3000])
        sys.exit(1)

    phase1 = parsed.get("phase_1_text", parsed.get("text", "")).strip()
    title = parsed.get("title", "").strip()
    description = parsed.get("description", "").strip()
    character_name = parsed.get("character_name", "").strip()
    character_archetype = parsed.get("character_archetype", "explorer").strip()
    character_age = parsed.get("character_age", 7)
    character_gender = parsed.get("character_gender", "female").strip()
    lead_character_type = parsed.get("lead_character_type", "human").strip()
    mentor_name = parsed.get("mentor_name", "").strip()
    mentor_description = parsed.get("mentor_description", "").strip()
    morals = parsed.get("morals", ["The world is kinder than it seems, especially at night"])
    categories = parsed.get("categories", ["Bedtime", "Fantasy", "Relaxation"])
    theme = parsed.get("theme", "fantasy")
    geography = parsed.get("geography", "Universal")

    p1_wc = len(phase1.split())
    logger.info("Phase 1 generated: '%s' -- %d words", title, p1_wc)
    logger.info("Character: %s (%s), Mentor: %s", character_name, character_archetype, mentor_name)

    # Brief pause between calls
    time.sleep(35)

    # ── CALL 2: Generate Phase 2 (DESCENT with mentor) ───────────────────
    logger.info("")
    logger.info("=== CALL 2/4: Phase 2 (DESCENT with mentor) ===")

    call2_prompt = f"""Continue the story "{title}" with Phase 2 (DESCENT).

Here is Phase 1 that was already written:
---
{phase1}
---

Character: {character_name} ({character_archetype}, age {character_age})
Mentor: {mentor_name} — {mentor_description}

Now write Phase 2 — the DESCENT phase. This is the longest and most important section.

Start with [PHASE_2] on its own line, then write the contemplative, exploratory phase.
The character meets or continues with the mentor {mentor_name} and enters a place of deep wonder.

REQUIREMENTS:
- STRICT MAXIMUM: 900 words. This MUST NOT exceed 900 words. Count carefully.
- Start with [PHASE_2] marker
- The mentor {mentor_name} MUST be present — speaking slowly, guiding gently
- MAXIMUM 3 [CHAR_START]/[CHAR_END] dialogue blocks total. The mentor speaks only 2-3 SHORT whispered lines. NO back-and-forth conversation. NO other characters speak. The child character does NOT speak in Phase 2 — all their experience is NARRATED.
- IMPORTANT: Do NOT introduce new subplots, flashbacks, vision sequences, or new characters. This phase is about BEING in one beautiful place with the mentor, described slowly and sensuously. Almost no plot advancement.
- Use [CALM] markers, shifting to [SLEEPY] by the end
- Rich sensory description — surfaces, temperatures, light, sound. This is the MAIN content: long, flowing paragraphs of pure sensory narration.
- Include 2-4 disguised breathing cues marked with [BREATH_CUE]:
  * Blowing dandelion seeds / gentle exhale
  * Listening to a heartbeat / slow rhythm
  * Floating in warm water / weightlessness
  * Mentor says "listen closely" / become still
  * Warmth from magical source / heat seeping through body
  * Counting stars/fireflies / slowing rhythm
- NO explicit relaxation instructions ("take a deep breath", "relax your body")
- Pacing slows — longer sentences, more [PAUSE] markers
- Think: the quiet, beautiful middle of a Miyazaki film — pure atmosphere, almost no dialogue
- End with the character settling into deep stillness and warmth

Do NOT include [PHASE_3] or write Phase 3. Stop just before Phase 3 would begin.

Return ONLY the Phase 2 text (starting with [PHASE_2]). No JSON wrapper — just the raw text."""

    raw2 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call2_prompt},
    ])
    if not raw2:
        logger.error("Call 2 failed -- no response")
        sys.exit(1)

    # Clean up
    phase2 = raw2.strip()
    if phase2.startswith("{"):
        try:
            p2_parsed = json.loads(phase2)
            phase2 = p2_parsed.get("phase_2_text", p2_parsed.get("text", phase2))
        except json.JSONDecodeError:
            pass
    if phase2.startswith("```"):
        lines = phase2.split("\n")
        phase2 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Ensure it starts with [PHASE_2]
    if not phase2.strip().upper().startswith("[PHASE_2]"):
        phase2 = "[PHASE_2]\n\n" + phase2

    p2_wc = len(phase2.split())
    logger.info("Phase 2 generated: %d words", p2_wc)

    time.sleep(35)

    # ── CALL 3: Generate Phase 3 (SLEEP) ─────────────────────────────────
    logger.info("")
    logger.info("=== CALL 3/4: Phase 3 (SLEEP) ===")

    # Send condensed version of Phase 2's ending for context
    phase2_last_400 = " ".join(phase2.split()[-400:])

    call3_prompt = f"""Continue the story "{title}" with Phase 3 (SLEEP) — the final dissolution phase.

Character: {character_name} ({character_archetype})
Mentor: {mentor_name} (fading into background — may hum but no words)

For context, here is how Phase 2 ends:
---
...{phase2_last_400}
---

Now write Phase 3 — the SLEEP dissolution phase. The story becomes ambient music in word form.

Start with [PHASE_3] on its own line.

REQUIREMENTS:
- Write 500-700 words for Phase 3. STRICT MAXIMUM: 700 words.
- Start with [PHASE_3] marker
- Use ONLY [SLEEPY] and [WHISPERING] markers — no other emotions
- NO character dialogue — just the narrator's voice, slow, quiet, deep, ASMR-like
- The mentor {mentor_name} may be nearby but speaks no words (perhaps hums, perhaps is just present)
- The child character finds a resting place: a cloud nest, warm hollow, bed of soft moss
- The narrative becomes abstract and repetitive — descriptions that LOOP with slight variations:
  * "Another light drifted past... then another... each one softer than the last..."
  * "The warmth spread a little further... into her fingers... into her toes..."
- Include a disguised "close your eyes" cue:
  * Character closes eyes to SEE something (inner vision, true colours, hidden pattern)
- Body dissolution — character merges with environment:
  * "She couldn't feel where her body ended and the cloud began..."
  * "The warmth had seeped so deep that she felt like she was made of starlight..."
- Use [LONG_PAUSE] between fragments (4-second silences)
- At LEAST 10 [LONG_PAUSE] markers throughout Phase 3
- Last 6-8 lines should be single fragments with [LONG_PAUSE] between each:
  "[WHISPERING] another light... drifting past..."
  "[LONG_PAUSE]"
  "[WHISPERING] warm... and safe..."
  "[LONG_PAUSE]"
  End with a fragment evoking safety and warmth
- The story DISSOLVES — it does not end. It fragments into silence.

Return ONLY the Phase 3 text (starting with [PHASE_3]). No JSON wrapper — just the raw text."""

    raw3 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call3_prompt},
    ])
    if not raw3:
        logger.error("Call 3 failed -- no response")
        sys.exit(1)

    phase3 = raw3.strip()
    if phase3.startswith("{"):
        try:
            p3_parsed = json.loads(phase3)
            phase3 = p3_parsed.get("phase_3_text", p3_parsed.get("text", phase3))
        except json.JSONDecodeError:
            pass
    if phase3.startswith("```"):
        lines = phase3.split("\n")
        phase3 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    if not phase3.strip().upper().startswith("[PHASE_3]"):
        phase3 = "[PHASE_3]\n\n" + phase3

    p3_wc = len(phase3.split())
    logger.info("Phase 3 generated: %d words", p3_wc)

    time.sleep(35)

    # ── CALL 4: Generate Lullaby ──────────────────────────────────────────
    logger.info("")
    logger.info("=== CALL 4/4: Lullaby ===")

    # Build summary of story imagery for lullaby connection
    story_summary = f"Title: {title}\nCharacter: {character_name}\nMentor: {mentor_name}\nTheme: {theme}"

    call4_prompt = f"""Write a lullaby for the bedtime story "{title}".

Story context:
{story_summary}

The lullaby should connect to the story's imagery and world. It will be SUNG at the end of the audio, after the narration fades.

REQUIREMENTS:
- 3 verses + chorus structure
- Chorus repeats identically between verses
- Each verse: exactly 4 lines, 20-25 words per verse
- Chorus: exactly 4 lines, 15-20 words per chorus
- STRICT MAXIMUM: 120 words total. Count carefully. Do NOT exceed 120 words. Keep it SHORT and singable.
- Reference at least 2 specific images from the story
- Tone: folk song quality — beautiful, melodic, NOT a nursery rhyme
- Think: Studio Ghibli ending credits song quality
- Emotional message: "you are safe, the world is kind, sleep is a gift"
- Do NOT use baby talk, overly precious language, or forced rhymes
- Each line should be singable — natural rhythm, not too many syllables

Format with [verse] and [chorus] section markers:

[verse]
Line 1
Line 2
Line 3
Line 4

[chorus]
Line 1
Line 2
Line 3
Line 4

[verse]
...

[chorus]
...

[verse]
...

[chorus]
...

Return ONLY the lullaby text with section markers. No JSON, no explanation."""

    raw4 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call4_prompt},
    ], temperature=0.9)
    if not raw4:
        logger.error("Call 4 failed -- no response")
        sys.exit(1)

    lullaby = raw4.strip()
    # Remove any JSON wrapper or markdown fences
    if lullaby.startswith("{"):
        try:
            l_parsed = json.loads(lullaby)
            lullaby = l_parsed.get("lullaby_lyrics", l_parsed.get("text", lullaby))
        except json.JSONDecodeError:
            pass
    if lullaby.startswith("```"):
        lines = lullaby.split("\n")
        lullaby = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    lullaby_wc = len(lullaby.split())
    logger.info("Lullaby generated: %d words", lullaby_wc)

    # ── ASSEMBLE FULL STORY ──────────────────────────────────────────────
    text = phase1.rstrip() + "\n\n" + phase2.strip() + "\n\n" + phase3.strip()
    word_count = len(text.split())

    logger.info("")
    logger.info("=== ASSEMBLED STORY ===")
    logger.info("Title: '%s'", title)
    logger.info("Character: %s (%s, age %d, %s, %s)", character_name, character_archetype,
                character_age, character_gender, lead_character_type)
    logger.info("Mentor: %s -- %s", mentor_name, mentor_description)
    logger.info("Total word count: %d (target: 1700-2200)", word_count)
    logger.info("Phase breakdown: P1=%d, P2=%d, P3=%d", p1_wc, p2_wc, p3_wc)
    logger.info("Lullaby: %d words", lullaby_wc)
    logger.info("Theme: %s | Geography: %s", theme, geography)

    # Validate story structure and content
    warnings = validate_story(text, lullaby)
    for w in warnings:
        logger.warning("VALIDATION: %s", w)

    # Pick music profile based on theme
    music_candidates = THEME_MUSIC_MAP.get(theme, ALL_PROFILES)
    music_profile = random.choice(music_candidates)

    # Derive universe from theme
    universe = THEME_UNIVERSE_MAP.get(theme, "fantasy_realm")

    # Pick life aspect
    life_aspect = random.choice(LIFE_ASPECTS_6_8)

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
        "lullaby_lyrics": lullaby,
        "target_age": 7,
        "age_min": 6,
        "age_max": 8,
        "age_group": "6-8",
        "length": "LONG",
        "word_count": word_count,
        "duration_seconds": 0,
        "duration": 22,                                # Target minutes
        "categories": categories,
        "theme": theme,
        "morals": morals,
        "cover": "",
        "musicProfile": music_profile,
        "musicParams": {},
        "music_type": "ambient",
        "audio_variants": [],
        "author_id": "system",
        "is_generated": True,
        "generation_quality": "pending_review",
        "lead_gender": character_gender,
        "lead_character_type": lead_character_type,
        "character_archetype": character_archetype,
        "character_name": character_name,
        "character_age": character_age,
        "mentor_name": mentor_name,
        "mentor_description": mentor_description,
        "universe": universe,
        "geography": geography,
        "life_aspect": life_aspect,
        "plot_archetype": "discovery",
        "created_at": now,
        "updated_at": now,
        "view_count": 0,
        "like_count": 0,
        "save_count": 0,
    }

    # Save standalone JSON for review
    standalone_path = BASE_DIR / "seed_output" / f"experimental_6_8_{content_id}.json"
    with open(standalone_path, "w", encoding="utf-8") as f:
        json.dump(content_obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    logger.info("Saved standalone: %s", standalone_path.name)

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

    logger.info("")
    logger.info("Story ID: %s", content_id)
    logger.info("")
    logger.info("=== NEXT STEPS ===")
    logger.info("1. Review the story text -- check quality, phase structure, mentor presence")
    logger.info("2. Review standalone file: %s", standalone_path.name)
    logger.info("3. Generate audio: python3 scripts/generate_audio.py --story-id %s --force --speed 0.8", content_id)
    logger.info("4. Generate cover: python3 scripts/generate_cover_experimental.py --story-json %s", standalone_path.name)
    logger.info("5. Generate music params: python3 scripts/generate_music_params.py --id %s", content_id)

    if warnings:
        logger.info("")
        logger.info("=== %d VALIDATION WARNINGS ===", len(warnings))
        for w in warnings:
            logger.info("  ! %s", w)

    return content_id


if __name__ == "__main__":
    generate_story()
