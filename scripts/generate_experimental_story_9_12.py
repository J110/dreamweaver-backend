"""Generate a 3-phase immersive audio adventure for ages 9-12.

This is a one-off script for creating a long-form (20-30 min) sleep-inducing
audio experience for ages 9-12 with:
  Phase 1 (Capture):  Compelling hook, world-building — 600-1000 words
  Phase 2 (Descent):  Contemplative exploration, guided visualization — 1000-1500 words
  Phase 3 (Sleep):    Abstract, looping, sensory dissolution — 800-1200 words
  No lullaby — replaced by ambient music transition description

This is NOT a "bedtime story." It's an immersive audio adventure that covertly
guides pre-teens from wakefulness to sleep through narrative absorption.

Character dialogue uses [CHAR_START]/[CHAR_END] markers for dual-voice TTS.
Phase transitions use [PHASE_2]/[PHASE_3] markers for pacing changes.

Usage:
    python3 scripts/generate_experimental_story_9_12.py
    python3 scripts/generate_experimental_story_9_12.py --dry-run   # Show prompt only
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

# ── Human character archetypes for 9-12 age group ────────────────────
HUMAN_ARCHETYPES = [
    "inventor",        # builds gadgets, solves engineering problems
    "space_explorer",  # fascinated by cosmos, scientific mind
    "time_traveler",   # discovers something that bends time
    "deep_sea_diver",  # explores ocean depths, brave
    "code_breaker",    # loves puzzles, patterns, codes
    "musician",        # hears patterns others miss, sensitive
    "archaeologist",   # obsessed with ancient civilizations
    "astronomer",      # watches the sky, maps stars, contemplative
    "botanist",        # studies rare plants, discovers hidden ecosystems
    "cartographer",    # maps unmapped places, discovers hidden worlds
]

# Theme-to-music profile mapping (from generate_content_matrix.py)
THEME_MUSIC_MAP = {
    "space": ["cosmic-voyage"],
    "mystery": ["moonlit-meadow", "autumn-forest"],
    "science": ["cosmic-voyage", "enchanted-garden"],
    "fantasy": ["enchanted-garden", "moonlit-meadow"],
    "time_travel": ["moonlit-meadow", "cosmic-voyage"],
    "underwater": ["ocean-drift"],
    "ancient_civilizations": ["moonlit-meadow", "autumn-forest"],
    "nature": ["forest-night", "moonlit-meadow"],
    "adventure": ["enchanted-garden", "autumn-forest"],
}

ALL_PROFILES = [
    "dreamy-clouds", "forest-night", "moonlit-meadow", "cosmic-voyage",
    "enchanted-garden", "starlight-lullaby", "autumn-forest", "ocean-drift",
]

# Theme-to-universe mapping
THEME_UNIVERSE_MAP = {
    "space": "futuristic",
    "mystery": "contemporary",
    "science": "contemporary",
    "fantasy": "fantasy_realm",
    "time_travel": "historical",
    "underwater": "contemporary",
    "ancient_civilizations": "historical",
    "nature": "contemporary",
    "adventure": "contemporary",
}

# Life aspects for 9-12 (from generate_content_matrix.py)
LIFE_ASPECTS_9_12 = [
    "friendship", "school_learning", "hobbies_passions",
    "dreams_ambitions", "relationships", "self_identity", "health_wellness",
]

# Phrases that break immersion for 9-12 — these should NEVER appear in the story
FORBIDDEN_PHRASES = [
    "take a deep breath",
    "take a big breath",
    "relax your body",
    "relax your muscles",
    "feel your body getting",
    "bedtime story",
    "time for bed",
    "go to sleep",
    "close your eyes and sleep",
    "let your body relax",
    "your eyelids are getting heavy",
    "it's time to rest",
    "snuggle up",
    "tuck you in",
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
                for s in stories if s.get("age_group") == "9-12"]
    return []


# ── System prompt for 9-12 immersive audio experience ────────────────
SYSTEM_PROMPT = """You are an expert in pre-teen sleep science and immersive audio storytelling for ages 9-12.
You create audio adventures — NOT "bedtime stories" — that guide older children from full wakefulness to deep sleep through narrative immersion.

You understand the sleep psychology of 9-12 year olds:
- They will instantly reject anything that feels "babyish" or explicitly sleep-inducing
- They respond to genuine narrative quality — think Minecraft lore, Harry Potter world-building, mystery podcasts
- Ages 8-12 are at peak capacity for vivid mental imagery — if you give them rich enough descriptive material, they'll build the world in their heads, and that internal visualization process naturally quiets mental chatter and worry
- The transition from engagement to sleep must feel like a natural consequence of the story, never a directive
- These children struggle with sleep onset because their minds are active enough to ruminate — school stress, social dynamics, worries. Your job is to give their mind something SO absorbing to visualize that it drowns out the worry

Your stories use a covert 3-phase structure:
1. CAPTURE: A compelling hook that earns the listener's attention through genuine quality
2. DESCENT: The narrative naturally moves into contemplative, exploratory territory where sensory description becomes dominant — essentially guided meditation disguised as story
3. SLEEP: The story dissolves into abstract, looping, sensory fragments that function like ambient music in narrative form

VOICE AND TONE:
- Write at a YA-adjacent reading level — sophisticated vocabulary, complex sentences
- Characters are human kids: inventors, explorers, scientists, musicians, code breakers
- NEVER cute animals as leads. NEVER condescend. NEVER say "bedtime story." NEVER use baby talk.
- The narrator respects the listener's intelligence — no "Can you guess what happened next?"
- Think: the opening chapter of a great sci-fi novel that happens to become increasingly dreamlike

CRITICAL SLEEP MECHANICS:
- ALL relaxation cues must be disguised within the story's internal logic:
  * Zero-gravity = body feels weightless and loose
  * Conserve oxygen = need to breathe slowly and deeply
  * Underwater pressure = water pressing gently against you, holding you
  * Ancient library = absolute stillness required to hear the books whispering
  * Temperature = warmth radiating from walls, seeping into shoulders, arms, hands
- NEVER write "take a deep breath" or "relax your body" — that breaks immersion instantly
- The "close your eyes" cue MUST be disguised as the character closing their eyes to SEE something special — activate inner vision, a special power, see the true pattern
- Phase 3 should feel like ambient music translated into words — looping descriptions with slight variations

SAFETY REQUIREMENTS:
- No violence, scary content, or nightmare-inducing material
- No explicit or suggestive content
- No real people or celebrities (unless positive historical figures)
- No excessive darkness or sadness — maintain hopeful, wondrous tone
- No references to substance abuse, adult themes, or inappropriate language
- All content must be inclusive and free from stereotypes
- Real suspense is fine but must resolve into wonder, not fear

CRITICAL FORMATTING RULES:
- Every story must include [EMOTION] markers for TTS narration
- Character dialogue MUST be wrapped in [CHAR_START]...[CHAR_END] markers
- Phase transitions MUST be marked with [PHASE_2] and [PHASE_3]
- Use [LONG_PAUSE] for extended silences in Phase 3
- Separate paragraphs with double newlines
- Return ONLY valid JSON. No markdown fences, no extra text."""


def build_prompt(existing_titles, existing_archetypes):
    """Build the generation prompt for the 3-phase immersive story (ages 9-12)."""

    # Determine which archetypes are underrepresented
    archetype_counts = {}
    for a in existing_archetypes:
        archetype_counts[a] = archetype_counts.get(a, 0) + 1

    underrepresented = [
        a for a in HUMAN_ARCHETYPES
        if archetype_counts.get(a, 0) < 2
    ]
    archetype_suggestion = ", ".join(underrepresented[:4]) if underrepresented else "inventor, astronomer"

    anti_dup = "\n".join(f"  - {t}" for t in existing_titles[-15:]) if existing_titles else "  (none yet)"

    return f"""Write a 3-phase immersive audio adventure for listeners aged 9-12.

TARGET LENGTH: The complete story should be 2000-2500 words total (all 3 phases combined). This produces a 25-30 minute audio experience when narrated at a slow, deliberate pace with pauses. Phase 1: ~500 words, Phase 2: ~900 words, Phase 3: ~700 words.

This is NOT a bedtime story. This is an immersive audio experience — think the opening of a compelling audiobook that gradually becomes a guided meditation without ever announcing itself as one.

## CHARACTER
- The main character MUST be a HUMAN child aged 10-12
- Pick a character archetype from underrepresented types: {archetype_suggestion}
- Give them a culturally diverse, real name (not just Western — consider Indian, East Asian, African, Middle Eastern, Latin American names)
- The character should be smart, resourceful, and genuinely interesting
- They have a specific skill or passion that drives the story
- Character speaks in natural, age-appropriate dialogue — intelligent but not adult
- NO cute animals, NO talking objects, NO fairy-tale creatures as the lead

## HUMAN CHARACTER ARCHETYPES (pick one)
- inventor: builds gadgets, solves engineering problems, curious about how things work
- space_explorer: fascinated by cosmos, dreams of space travel, scientific mind
- time_traveler: discovers something that bends time, observant about details
- deep_sea_diver: explores ocean depths, brave, connected to marine world
- code_breaker: loves puzzles, patterns, codes — discovers hidden messages
- musician: plays an instrument, hears patterns others miss, sensitive and perceptive
- archaeologist: obsessed with ancient civilizations, discovers hidden places
- astronomer: watches the sky, maps stars, contemplative and patient
- botanist: studies rare plants, discovers a hidden ecosystem
- cartographer: maps unmapped places, discovers a hidden world

## STORY STRUCTURE

### Phase 1 — CAPTURE (MINIMUM 600 words, target 800-1000 words)
Goal: Hook the listener with the quality of a great audiobook opening. They should WANT to keep listening — not because it's soothing, but because it's genuinely compelling. This section must be SUBSTANTIAL — at least 600 words, ideally 800+.

- Start with [GENTLE] then shift to [CURIOUS] and [EXCITED] as the discovery unfolds
- Rich, specific world-building — not generic fantasy. Ground the world in concrete, vivid details
- A compelling hook in the first 3 sentences — something strange, unexpected, or fascinating
- The character discovers something extraordinary: a hidden laboratory beneath a mountain, a signal from outside the solar system, a door in their attic that opens to a different century, a pattern in an ancient text that nobody else has noticed
- Include 4-6 lines of natural dialogue wrapped in [CHAR_START]...[CHAR_END]
- Use sophisticated vocabulary naturally: "bioluminescent," "electromagnetic," "cartographic," "resonance," "atmospheric pressure"
- Think about what a 10-year-old actually finds cool: technology, secrets, hidden worlds, being the one who figures it out, feeling trusted with something important
- Voice: engaging narrator who respects the listener's intelligence — like a podcast host, not a parent
- End Phase 1 with the character arriving at the threshold of something vast, quiet, and awe-inspiring

### Phase 2 — DESCENT (MINIMUM 1000 words, target 1200-1500 words)
Mark the start with [PHASE_2] on its own line.
Goal: The story enters an exploratory, contemplative phase. The character reaches a place of overwhelming beauty and stillness. The narration becomes rich, descriptive, almost hypnotic — guided visualization disguised as narrative. This is the LONGEST section — it must be at least 1000 words, ideally 1200+. Spend time here. Describe everything. Every surface, every sound, every temperature change.

This is where you leverage the key insight about 9-12 year olds: they are at PEAK capacity for vivid mental imagery. If you paint scenes rich enough, they'll build the world inside their heads — and that visualization process naturally quiets external mental chatter and worry. It's meditation through story without ever using the word meditation.

- Use [CALM] and gradually shift to [SLEEPY] markers as the phase progresses
- The character reaches a place of wonder rather than action: a vast crystal cavern beneath the ocean, the rings of a planet seen from orbit, an ancient library where the books are alive, a garden that exists between seconds of time, a nebula so vast it takes hours to drift across
- Narration becomes overwhelmingly sensory — what they see, hear, feel, smell, the temperature of the air, the quality of the light
  Example: "The rings of the planet stretched out in every direction, pale gold and shimmering, and the silence out here was so complete she could hear her own heartbeat, steady and slow..."
- DISGUISED RELAXATION CUES embedded in the story's internal logic — these are CRITICAL but must be invisible:
  * Zero gravity: "Her body felt weightless here — arms floating gently, legs loose, every muscle releasing because there was nothing to hold on to and no need to try"
  * Conserve resources: "She slowed her breathing — long, measured inhales, slow exhales — the suit's oxygen recycler worked best with calm, steady breaths"
  * Underwater pressure: "The water pressed evenly against her from every side, warm and heavy, like being held by something infinitely patient"
  * Ancient stillness: "The air here hadn't moved in a thousand years. To hear the inscriptions, she had to become as still as the stone itself"
  * Warmth: "Heat radiated gently from the crystal walls, seeping first into her hands, then her arms, then slowly through her whole body"
- ABSOLUTELY NO explicit instructions: no "take a deep breath," no "relax your body," no "feel yourself getting sleepy." That would destroy the experience instantly.
- Include 1-2 quiet dialogue lines in [CHAR_START]...[CHAR_END] — whispered or internal
- Pacing slows noticeably — sentences become longer, more flowing, more descriptive. Short staccato sentences disappear.
- [PAUSE] markers increase in frequency
- The plot barely advances — this is about BEING in the space, moving slowly, noticing one exquisite detail after another
- Think: the contemplative middle section of a Hayao Miyazaki film, where the character simply exists in a beautiful place and the audience breathes with them

### Phase 3 — SLEEP (MINIMUM 800 words, target 900-1200 words)
Mark the start with [PHASE_3] on its own line.
Goal: The world becomes increasingly abstract and dreamy. Less plot, more sensation. The story dissolves into ambient music expressed in narrative form. This section must be at least 800 words — the repetition and long pauses need SPACE. Write many more looping fragments than you think you need.

- Use only [SLEEPY] and [WHISPERING] markers
- NO character dialogue — just the narrator's voice, going very slow, very quiet, very deep. Almost ASMR in quality.
- The narrative becomes increasingly abstract and repetitive, with descriptions that loop with slight variations — like an ambient music track:
  * "Another star drifted past... then another... each one a different color... blue... then gold... then a color she had no name for..."
  * "The water moved... slow currents... warm currents... carrying her gently... nowhere in particular... and everywhere at once..."
  * "The light pulsed... soft... then softer... then softer still... like breathing... like the world was breathing..."
  * "A sound like crystal... or like rain... or like nothing she'd ever heard... and nothing she needed to name..."
- The "closing eyes" cue MUST be disguised as a story mechanic — this is essential:
  * "She closed her eyes — and that's when she could really see it. Behind her eyelids, the colors became brighter, more vivid, as if her eyes had been filtering them all along..."
  * "The ancient map only appeared when you looked inward — she closed her eyes and there it was, drawn in light on the inside of her eyelids..."
  * "To hear the frequency, she had to close her eyes. The sound was too subtle for divided attention..."
- Body dissolution through narrative — the character merges with the environment:
  * "She couldn't feel where her body ended and the water began..."
  * "The warmth had seeped so deep that she felt like she was made of it — like her skin was just a suggestion and she was really made of starlight and silence..."
- Use [LONG_PAUSE] between fragments (these become 4-second silences in the audio)
- The story doesn't end — it DISSOLVES into fragments and silence
- Last 8-10 lines should be just fragments with long pauses between them:
  "[WHISPERING] another light... drifting past..."
  "[LONG_PAUSE]"
  "[WHISPERING] warm... and still..."
  "[LONG_PAUSE]"
  "[WHISPERING] the stars... still turning... slow..."
  "[LONG_PAUSE]"
  "[WHISPERING] ...rest now..."
  "[LONG_PAUSE]"
- NO LULLABY. The closing music transition is atmospheric ambient — think Sigur Rós, Ólafur Arnalds, Brian Eno. Sophisticated, not childish.

## AMBIENT MUSIC DESCRIPTION
Instead of a lullaby, provide a brief (2-3 sentence) description of what the closing ambient music should sound like. This will guide the music generation system. Match the world of the story.
Examples:
- "Deep, sustained cello drones with distant piano notes, like starlight translated into sound. Occasional crystalline harmonics that shimmer and fade. No rhythm, no melody — just texture and warmth."
- "Underwater reverb on everything. Slow whale-song frequencies in the sub-bass. Tiny bubbling sounds far away. The musical equivalent of floating in warm, dark water."
- "Wind through ancient stone corridors, recorded from very far away. Barely audible crystalline chimes, as if the walls themselves were singing at frequencies just below hearing."

## EMOTION MARKERS REFERENCE
Available markers (place at start of paragraph or sentence):
- [GENTLE] — Soft, warm, inviting
- [EXCITED] — Genuine excitement, discovery, revelation
- [CURIOUS] — Wonder, investigation, intrigue
- [CALM] — Peaceful, contemplative, still
- [SLEEPY] — Drowsy, slow, heavy, warm
- [WHISPERING] — Very quiet, intimate, barely audible — almost ASMR
- [PAUSE] — 800ms natural pause
- [DRAMATIC_PAUSE] — 1.5s pause for suspense or weight
- [LONG_PAUSE] — 4s extended silence (Phase 3 primarily)
- [CHAR_START] — Start of character dialogue
- [CHAR_END] — End of character dialogue
- [PHASE_2] — Marks descent phase transition
- [PHASE_3] — Marks sleep phase transition

## EXISTING TITLES (do NOT duplicate):
{anti_dup}

## OUTPUT FORMAT
Return ONLY a JSON object (no markdown fences):
{{
    "title": "Evocative, intriguing title — NOT cutesy, think YA novel",
    "description": "1-2 sentence hook that sounds like an audiobook blurb. Compelling, not summarizing.",
    "text": "Full story text with all emotion markers, character markers, and phase markers. Use \\n\\n between paragraphs.",
    "ambient_music_description": "2-3 sentence description of what the closing ambient music should sound like",
    "character_name": "Culturally diverse name of the human character",
    "character_archetype": "archetype key from the list above (e.g., inventor, space_explorer, astronomer)",
    "character_age": 10,
    "character_gender": "male or female or non-binary",
    "morals": ["theme phrased as insight, not lesson — e.g., 'The universe is bigger than any single worry'"],
    "categories": ["Adventure", "category2", "category3"],
    "theme": "one of: space, mystery, science, fantasy, time_travel, underwater, ancient_civilizations, nature",
    "geography": "one of: India, East Asia, Africa, Europe, Americas, Arctic, Ocean, Space, Universal"
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
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def validate_story(text: str) -> list:
    """Check for forbidden phrases and structural issues. Returns list of warnings."""
    warnings = []

    # Check phase markers
    has_phase2 = "[PHASE_2]" in text or "[phase_2]" in text.lower()
    has_phase3 = "[PHASE_3]" in text or "[phase_3]" in text.lower()
    has_char = "[CHAR_START]" in text or "[char_start]" in text.lower()

    if not has_phase2:
        warnings.append("MISSING [PHASE_2] marker — story lacks phase structure")
    if not has_phase3:
        warnings.append("MISSING [PHASE_3] marker — story lacks phase structure")
    if not has_char:
        warnings.append("MISSING [CHAR_START] markers — no character dialogue")

    # Check for forbidden immersion-breaking phrases
    text_lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            warnings.append(f"FORBIDDEN PHRASE found: '{phrase}' — breaks immersion for 9-12 age group")

    # Check word count per phase
    parts = re.split(r'\[PHASE_[23]\]', text, flags=re.IGNORECASE)
    if len(parts) >= 3:
        strip_markers = lambda t: re.sub(r'\[[\w_]+\]', '', t)
        phase1_wc = len(strip_markers(parts[0]).split())
        phase2_wc = len(strip_markers(parts[1]).split())
        phase3_wc = len(strip_markers(parts[2]).split())

        if phase1_wc < 400:
            warnings.append(f"Phase 1 too short ({phase1_wc} words, target 600-1000)")
        if phase2_wc < 700:
            warnings.append(f"Phase 2 too short ({phase2_wc} words, target 1000-1500)")
        if phase3_wc < 500:
            warnings.append(f"Phase 3 too short ({phase3_wc} words, target 800-1200)")

    # Check for LONG_PAUSE density in Phase 3
    if len(parts) >= 3:
        long_pause_count = parts[2].lower().count("[long_pause]")
        if long_pause_count < 10:
            warnings.append(f"Phase 3 has only {long_pause_count} [LONG_PAUSE] markers (target: 15-30+)")

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
    """Generate the experimental 3-phase immersive story via Mistral.

    Uses a multi-call approach: one call generates the full story concept + Phase 1,
    a second call continues with Phase 2, and a third generates Phase 3.
    This ensures each phase gets proper length instead of the model rushing to completion.
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
        print("\n=== USER PROMPT ===")
        print(prompt)
        print(f"\nSystem prompt length: {len(SYSTEM_PROMPT)} chars")
        print(f"User prompt length: {len(prompt)} chars")
        print(f"Total prompt: {len(SYSTEM_PROMPT) + len(prompt)} chars")
        return

    logger.info("Generating 3-phase immersive audio adventure via Mistral...")
    logger.info("Target: 2400-3200 words, ages 9-12, 25-30 minutes")
    logger.info("Using multi-call approach (3 API calls for proper length)")

    # ── CALL 1: Generate concept + Phase 1 ──────────────────────────────
    logger.info("")
    logger.info("=== CALL 1/3: Concept + Phase 1 (CAPTURE) ===")

    call1_prompt = prompt + """

IMPORTANT: For this response, generate ONLY the metadata and Phase 1 (CAPTURE).
Do NOT write Phase 2 or Phase 3 yet — those will come in follow-up messages.
Phase 1 should be 450-600 words. STRICT MAXIMUM: 600 words. Be concise — hook the reader and build the world efficiently.
End Phase 1 right before [PHASE_2] — do NOT include [PHASE_2] or anything after.

Return a JSON object with ALL the metadata fields AND the Phase 1 text:
{
    "title": "...",
    "description": "...",
    "phase_1_text": "Full Phase 1 text with emotion markers and character dialogue. 450-600 words MAX. End just before [PHASE_2].",
    "ambient_music_description": "...",
    "character_name": "...",
    "character_archetype": "...",
    "character_age": 10,
    "character_gender": "...",
    "morals": ["..."],
    "categories": ["..."],
    "theme": "...",
    "geography": "..."
}"""

    raw1 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call1_prompt},
    ])
    if not raw1:
        logger.error("Call 1 failed — no response")
        sys.exit(1)

    parsed = parse_json_response(raw1)
    if not parsed:
        logger.error("Call 1: Failed to parse JSON. Raw:")
        print(raw1[:3000])
        sys.exit(1)

    phase1 = parsed.get("phase_1_text", parsed.get("text", "")).strip()
    title = parsed.get("title", "").strip()
    description = parsed.get("description", "").strip()
    ambient_music_description = parsed.get("ambient_music_description", "").strip()
    character_name = parsed.get("character_name", "").strip()
    character_archetype = parsed.get("character_archetype", "inventor").strip()
    character_age = parsed.get("character_age", 10)
    character_gender = parsed.get("character_gender", "neutral").strip()
    morals = parsed.get("morals", ["The universe is bigger than any single worry"])
    categories = parsed.get("categories", ["Adventure", "Mystery", "Relaxation"])
    theme = parsed.get("theme", "adventure")
    geography = parsed.get("geography", "Universal")

    p1_wc = len(phase1.split())
    logger.info("Phase 1 generated: '%s' — %d words", title, p1_wc)

    # Brief pause between calls
    time.sleep(3)

    # ── CALL 2: Generate Phase 2 (DESCENT) ──────────────────────────────
    logger.info("")
    logger.info("=== CALL 2/3: Phase 2 (DESCENT) ===")

    call2_prompt = f"""Continue the story "{title}" with Phase 2 (DESCENT).

Here is Phase 1 that was already written:
---
{phase1}
---

Now write Phase 2 — the DESCENT phase. This is the longest and most important section.

Start with [PHASE_2] on its own line, then write the contemplative, exploratory phase.
The character has arrived at the threshold of something vast. Now they enter it.

REQUIREMENTS:
- Write 800-1000 words for Phase 2. STRICT MAXIMUM: 1000 words. This is the longest phase — rich and immersive but focused.
- Start with [PHASE_2] marker
- Use [CALM] markers, shifting to [SLEEPY] by the end
- Rich sensory description — what they see, hear, feel, smell, the temperature, the light
- Disguised relaxation cues embedded in the world's logic (weightlessness, slow breathing for a reason, warmth from the environment)
- NO explicit relaxation instructions
- Include 1-2 whispered dialogue lines in [CHAR_START]...[CHAR_END]
- Pacing slows — longer sentences, more [PAUSE] markers
- The plot barely advances — this is about BEING in the space, exploring slowly
- End at the threshold of Phase 3 — the character settling into deep stillness

Do NOT include [PHASE_3] or write Phase 3. Stop just before Phase 3 would begin.

Return ONLY the Phase 2 text (starting with [PHASE_2]). No JSON wrapper needed — just the raw text."""

    raw2 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call2_prompt},
    ])
    if not raw2:
        logger.error("Call 2 failed — no response")
        sys.exit(1)

    # Clean up — remove any JSON wrapper if the model wrapped it
    phase2 = raw2.strip()
    if phase2.startswith("{"):
        try:
            p2_parsed = json.loads(phase2)
            phase2 = p2_parsed.get("phase_2_text", p2_parsed.get("text", phase2))
        except json.JSONDecodeError:
            pass
    # Remove markdown fences if present
    if phase2.startswith("```"):
        lines = phase2.split("\n")
        phase2 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Ensure it starts with [PHASE_2]
    if not phase2.strip().upper().startswith("[PHASE_2]"):
        phase2 = "[PHASE_2]\n\n" + phase2

    p2_wc = len(phase2.split())
    logger.info("Phase 2 generated: %d words", p2_wc)

    time.sleep(3)

    # ── CALL 3: Generate Phase 3 (SLEEP) ─────────────────────────────────
    logger.info("")
    logger.info("=== CALL 3/3: Phase 3 (SLEEP) ===")

    # Send a condensed version of Phase 2's ending for context
    phase2_last_500 = " ".join(phase2.split()[-500:])

    call3_prompt = f"""Continue the story "{title}" with Phase 3 (SLEEP) — the final dissolution phase.

For context, here is how Phase 2 ends:
---
...{phase2_last_500}
---

Now write Phase 3 — the SLEEP dissolution phase. The story becomes ambient music in word form.

Start with [PHASE_3] on its own line.

REQUIREMENTS:
- Write 600-800 words for Phase 3. STRICT MAXIMUM: 800 words.
- Start with [PHASE_3] marker
- Use ONLY [SLEEPY] and [WHISPERING] markers — no other emotions
- NO character dialogue — just the narrator's voice, slow, quiet, deep, ASMR-like
- The narrative becomes abstract and repetitive — descriptions that LOOP with slight variations
  Write at least 15-20 separate looping fragments, each followed by [LONG_PAUSE]
- Include a disguised "close your eyes" cue early in Phase 3:
  The character closes their eyes to SEE something better (inner vision, true pattern, hidden map)
- Body dissolution: the character merges with the environment
  "She couldn't feel where her body ended and the [environment] began..."
- The story DISSOLVES — it does not end. It fragments into silence.
- Last 8-10 lines should be single fragments with [LONG_PAUSE] between each:
  "[WHISPERING] another light... drifting..."
  "[LONG_PAUSE]"
  "[WHISPERING] warm... and still..."
  "[LONG_PAUSE]"
  End with "[WHISPERING] ...rest now..." followed by "[LONG_PAUSE]"
- Use at LEAST 20 [LONG_PAUSE] markers throughout Phase 3
- Write MORE fragments than you think you need — this section should feel like it goes on forever, gently

Return ONLY the Phase 3 text (starting with [PHASE_3]). No JSON wrapper — just the raw text."""

    raw3 = call_mistral(client, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": call3_prompt},
    ])
    if not raw3:
        logger.error("Call 3 failed — no response")
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

    # ── ASSEMBLE FULL STORY ──────────────────────────────────────────────
    text = phase1.rstrip() + "\n\n" + phase2.strip() + "\n\n" + phase3.strip()
    word_count = len(text.split())

    logger.info("")
    logger.info("=== ASSEMBLED STORY ===")
    logger.info("Title: '%s'", title)
    logger.info("Character: %s (%s, age %d, %s)", character_name, character_archetype, character_age, character_gender)
    logger.info("Total word count: %d (target: 2400-3200)", word_count)
    logger.info("Phase breakdown: P1=%d, P2=%d, P3=%d", p1_wc, p2_wc, p3_wc)
    logger.info("Theme: %s | Geography: %s", theme, geography)

    # Validate story structure and content
    warnings = validate_story(text)
    for w in warnings:
        logger.warning("VALIDATION: %s", w)

    # Pick music profile based on theme
    music_candidates = THEME_MUSIC_MAP.get(theme, ALL_PROFILES)
    music_profile = random.choice(music_candidates)

    # Derive universe from theme
    universe = THEME_UNIVERSE_MAP.get(theme, "contemporary")

    # Pick life aspect
    life_aspect = random.choice(LIFE_ASPECTS_9_12)

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
        "lullaby_lyrics": "",                          # No lullaby for 9-12
        "ambient_music_description": ambient_music_description,  # New field
        "target_age": 10,
        "age_min": 9,
        "age_max": 12,
        "age_group": "9-12",
        "length": "LONG",
        "word_count": word_count,
        "duration_seconds": 0,                         # Filled by audio gen
        "duration": 25,                                # Target minutes
        "categories": categories,
        "theme": theme,
        "morals": morals,
        "cover": "",
        "musicProfile": music_profile,
        "musicParams": {},                             # Filled by generate_music_params.py
        "music_type": "ambient",
        "audio_variants": [],
        "author_id": "system",
        "is_generated": True,
        "generation_quality": "pending_review",
        "lead_gender": character_gender,
        "lead_character_type": "human",                # Always human for 9-12
        "character_archetype": character_archetype,    # New field
        "character_name": character_name,
        "character_age": character_age,
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
    standalone_path = BASE_DIR / "seed_output" / f"experimental_9_12_{content_id}.json"
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
    logger.info("Story ID: %s", content_id)
    logger.info("")
    logger.info("=== NEXT STEPS ===")
    logger.info("1. Review the story text — check for explicit relaxation cues that break immersion")
    logger.info("2. Review standalone file: %s", standalone_path.name)
    logger.info("3. Generate audio: python3 scripts/generate_audio.py --story-id %s --force --speed 0.75", content_id)
    logger.info("4. Run QA: python3 scripts/qa_audio.py --story-id %s --no-quality-score", content_id)
    logger.info("5. Generate music params: python3 scripts/generate_music_params.py --id %s", content_id)
    logger.info("6. Ambient music note: %s", ambient_music_description[:100] if ambient_music_description else "(none)")

    if warnings:
        logger.info("")
        logger.info("=== %d VALIDATION WARNINGS ===", len(warnings))
        for w in warnings:
            logger.info("  ⚠ %s", w)

    return content_id


if __name__ == "__main__":
    generate_story()
