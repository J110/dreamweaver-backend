#!/usr/bin/env python3
"""
Generate Musical Briefs for each story using Mistral API.

Each story gets a unique Musical Brief (~500 bytes of creative direction)
that the browser-side musicComposer.js translates into full musicParams
at runtime. This replaces the old system of generating raw synthesis
parameters (multi-KB) per story.

v3 — MUSICAL BRIEF SYSTEM:
- Mistral generates high-level creative choices (not synthesis numbers)
- Client-side composition turns briefs into musicParams deterministically
- Diversity enforced via last-5-briefs tracking
- ~500 bytes per story instead of multi-KB

Usage:
    python3 scripts/generate_music_params.py                  # Generate for all stories
    python3 scripts/generate_music_params.py --id gen-xxx     # Specific story
    python3 scripts/generate_music_params.py --dry-run        # Show plan only
    python3 scripts/generate_music_params.py --new-only       # Only stories without musicalBrief
"""

import argparse
import json
import os
import random
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
SEED_DATA_JS = BASE_DIR.parent / "dreamweaver-web" / "src" / "utils" / "seedData.js"

# ── Valid choices for Musical Brief fields ──

CULTURAL_REFERENCES = [
    "celtic", "japanese", "african", "nordic", "indian",
    "middle_eastern", "latin", "chinese", "ambient_electronic",
    "music_box", "orchestral", "folk_acoustic",
]

PRIMARY_LOOPS = [
    "harp_arpeggios", "koto_plucks", "kalimba_melody",
    "singing_bowl_rings", "cello_sustains", "hang_drum_melody",
    "guitar_fingerpick", "music_box_melody", "flute_breathy",
    "marimba_soft", "dulcimer_gentle", "piano_lullaby",
]

PAD_CHARACTERS = [
    "warm_strings", "crystal_air", "deep_ocean", "forest_hum",
    "starfield", "earth_drone", "silk_veil", "cave_resonance",
]

MODES = [
    "major_pentatonic", "minor_pentatonic", "dorian",
    "aeolian", "mixolydian",
]

ROOT_NOTES = ["C", "D", "Eb", "E", "F", "G", "Ab", "A", "Bb", "B"]

MELODIC_CHARACTERS = [
    "descending_lullaby", "cycling_arpeggio",
    "drone_with_ornaments", "stillness",
]

NATURE_SOUNDS_PRIMARY = [
    "forest_night", "rain_steady", "rain_light",
    "ocean_waves_close", "ocean_waves_distant",
    "river_stream", "wind_gentle", "wind_high",
    "underwater", "fireplace_crackle", "near_silence",
]

NATURE_SOUNDS_SECONDARY = [
    "distant_stream", "distant_thunder", "underwater_bubbling",
    "fireplace_crackle", "wind_gentle", None,
]

AMBIENT_EVENTS = [
    "owl", "leaves", "waterDrop", "waveCycle",
    "windGust", "cricket", "heartbeat", "chimes",
]


# ── Mood-specific music rules ──
# Applied AFTER Mistral generates the base brief, to enforce mood constraints.
MOOD_MUSIC_RULES = {
    "wired": {
        "tempo_range": [66, 75],
        "melodic_character": ["cycling_arpeggio", "descending_lullaby"],
        "feel": "gentle_pulse",
        "pad_character_exclude": ["deep_ocean", "cave_resonance"],
        "ambient_events": ["cricket", "chimes", "leaves"],
    },
    "curious": {
        "tempo_range": [62, 72],
        "melodic_character": ["cycling_arpeggio", "drone_with_ornaments"],
        "feel": "gentle_pulse",
        "pad_character_exclude": [],
        "ambient_events": ["owl", "leaves", "waterDrop", "chimes"],
    },
    "calm": {
        "tempo_range": [58, 66],
        "melodic_character": ["descending_lullaby", "stillness"],
        "feel": "free_rubato",
        "pad_character_exclude": [],
        "ambient_events": ["cricket", "waterDrop"],
    },
    "sad": {
        "tempo_range": [58, 64],
        "melodic_character": ["descending_lullaby", "drone_with_ornaments"],
        "feel": "free_rubato",
        "mode_prefer": ["aeolian", "minor_pentatonic"],
        "pad_character_prefer": ["warm_strings", "deep_ocean", "earth_drone"],
        "ambient_events": ["waterDrop", "leaves"],
        "nature_sound_prefer": ["rain_steady", "rain_light"],
    },
    "anxious": {
        "tempo_range": [60, 68],
        "melodic_character": ["drone_with_ornaments", "stillness"],
        "feel": "free_rubato",
        "pad_character_prefer": ["warm_strings", "forest_hum"],
        "nature_sound_prefer": ["forest_night", "rain_light"],
        "ambient_events": ["cricket", "owl"],
    },
    "angry": {
        "tempo_range": [64, 72],
        "melodic_character": ["cycling_arpeggio", "descending_lullaby"],
        "feel": "gentle_pulse",
        "mode_prefer": ["dorian", "aeolian"],
        "pad_character_prefer": ["earth_drone", "deep_ocean"],
        "nature_sound_prefer": ["river_stream", "ocean_waves_close"],
        "ambient_events": ["waveCycle", "windGust"],
    },
}


def apply_mood_to_brief(brief: dict, mood: str) -> dict:
    """Apply mood-specific constraints to a generated Musical Brief.

    Enforces tempo range, feel, mode preferences, melodic character,
    pad character exclusions, and nature sound preferences per mood.
    """
    rules = MOOD_MUSIC_RULES.get(mood, MOOD_MUSIC_RULES["calm"])

    # Enforce tempo range
    if "rhythm" in brief and "baseTempo" in brief["rhythm"]:
        lo, hi = rules["tempo_range"]
        brief["rhythm"]["baseTempo"] = max(lo, min(hi, brief["rhythm"]["baseTempo"]))

    # Enforce feel
    if "feel" in rules and "rhythm" in brief:
        brief["rhythm"]["feel"] = rules["feel"]

    # Apply mode preferences (70% chance of switching)
    if "mode_prefer" in rules and "tonality" in brief:
        if brief["tonality"].get("mode") not in rules["mode_prefer"]:
            if random.random() < 0.7:
                brief["tonality"]["mode"] = random.choice(rules["mode_prefer"])

    # Apply melodic character
    if "melodicCharacter" in brief:
        if brief["melodicCharacter"] not in rules.get("melodic_character", []):
            brief["melodicCharacter"] = random.choice(rules["melodic_character"])

    # Exclude inappropriate pad characters
    if "pad_character_exclude" in rules and rules["pad_character_exclude"]:
        mi = brief.get("musicalIdentity", {})
        if mi.get("padCharacter") in rules["pad_character_exclude"]:
            available = [p for p in PAD_CHARACTERS if p not in rules["pad_character_exclude"]]
            if available:
                mi["padCharacter"] = random.choice(available)

    # Apply pad character preferences (60% chance)
    if "pad_character_prefer" in rules:
        mi = brief.get("musicalIdentity", {})
        if mi.get("padCharacter") not in rules["pad_character_prefer"]:
            if random.random() < 0.6:
                mi["padCharacter"] = random.choice(rules["pad_character_prefer"])

    # Apply nature sound preferences (60% chance)
    if "nature_sound_prefer" in rules and "environment" in brief:
        if brief["environment"].get("natureSoundPrimary") not in rules["nature_sound_prefer"]:
            if random.random() < 0.6:
                brief["environment"]["natureSoundPrimary"] = random.choice(rules["nature_sound_prefer"])

    return brief


def get_age_group(target_age):
    """Map numeric target age to age group string."""
    if target_age <= 1:
        return "0-1"
    elif target_age <= 5:
        return "2-5"
    elif target_age <= 8:
        return "6-8"
    else:
        return "9-12"


# ── Diversity Tracking ──

class BriefDiversityTracker:
    """Track recent briefs to enforce variety."""

    def __init__(self):
        self.recent_briefs = []

    def record(self, brief):
        self.recent_briefs.append(brief)

    def get_last_n(self, n):
        return self.recent_briefs[-n:] if len(self.recent_briefs) >= n else list(self.recent_briefs)

    def get_summary_for_prompt(self):
        """Build a summary of recent briefs for the Mistral prompt."""
        last5 = self.get_last_n(5)
        if not last5:
            return "No previous briefs generated yet."
        lines = []
        for i, b in enumerate(last5):
            mi = b.get("musicalIdentity", {})
            t = b.get("tonality", {})
            lines.append(
                f"  {i+1}. culture={mi.get('culturalReference')}, "
                f"loop={mi.get('primaryLoop')}, "
                f"mode={t.get('mode')}, root={t.get('rootNote')}"
            )
        return "\n".join(lines)

    def summary(self):
        if not self.recent_briefs:
            print("  No briefs generated.")
            return
        from collections import Counter
        cultures = Counter(b["musicalIdentity"]["culturalReference"] for b in self.recent_briefs)
        loops = Counter(b["musicalIdentity"]["primaryLoop"] for b in self.recent_briefs)
        modes = Counter(b["tonality"]["mode"] for b in self.recent_briefs)
        roots = Counter(b["tonality"]["rootNote"] for b in self.recent_briefs)
        print(f"\n{'─'*50}")
        print(f"  MUSICAL BRIEF DIVERSITY REPORT")
        print(f"{'─'*50}")
        print(f"  Cultural refs: {dict(cultures)}")
        print(f"  Primary loops: {dict(loops)}")
        print(f"  Modes: {dict(modes)}")
        print(f"  Root notes: {dict(roots)}")
        print(f"  Total briefs: {len(self.recent_briefs)}")
        print(f"{'─'*50}\n")


tracker = BriefDiversityTracker()


# ── Mistral API ──

def call_mistral(prompt, max_tokens=2000, temperature=0.5, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                wait = (attempt + 1) * 10
                print(f"  [rate-limit, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
            else:
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise
    raise Exception("Max retries exceeded")


def parse_json_response(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON: {text[:300]}")


# ── Brief Validation ──

def validate_brief_schema(brief):
    """Validate the Musical Brief has all required fields with valid values."""
    errors = []

    mi = brief.get("musicalIdentity", {})
    if mi.get("culturalReference") not in CULTURAL_REFERENCES:
        errors.append(f"invalid culturalReference: {mi.get('culturalReference')}")
    if mi.get("primaryLoop") not in PRIMARY_LOOPS:
        errors.append(f"invalid primaryLoop: {mi.get('primaryLoop')}")
    if mi.get("padCharacter") not in PAD_CHARACTERS:
        errors.append(f"invalid padCharacter: {mi.get('padCharacter')}")

    t = brief.get("tonality", {})
    if t.get("mode") not in MODES:
        errors.append(f"invalid mode: {t.get('mode')}")
    if t.get("rootNote") not in ROOT_NOTES:
        errors.append(f"invalid rootNote: {t.get('rootNote')}")

    if brief.get("melodicCharacter") not in MELODIC_CHARACTERS:
        errors.append(f"invalid melodicCharacter: {brief.get('melodicCharacter')}")

    r = brief.get("rhythm", {})
    tempo = r.get("baseTempo", 0)
    if not (58 <= tempo <= 75):
        errors.append(f"baseTempo {tempo} outside 58-75 range")

    env = brief.get("environment", {})
    if env.get("natureSoundPrimary") not in NATURE_SOUNDS_PRIMARY:
        errors.append(f"invalid natureSoundPrimary: {env.get('natureSoundPrimary')}")

    events = env.get("ambientEvents", [])
    for e in events:
        if e not in AMBIENT_EVENTS:
            errors.append(f"invalid ambientEvent: {e}")

    return errors


def validate_brief_diversity(new_brief, recent_briefs):
    """Check diversity constraints. Returns list of errors."""
    errors = []

    last_3 = recent_briefs[-3:] if len(recent_briefs) >= 3 else recent_briefs
    last_5 = recent_briefs[-5:] if len(recent_briefs) >= 5 else recent_briefs
    all_briefs = recent_briefs  # check global uniqueness too

    mi = new_brief.get("musicalIdentity", {})
    t = new_brief.get("tonality", {})

    # GLOBAL: No duplicate (primaryLoop, mode, rootNote, padCharacter) 4-tuple
    new_sig = (mi.get("primaryLoop"), t.get("mode"), t.get("rootNote"), mi.get("padCharacter"))
    for b in all_briefs:
        bmi = b.get("musicalIdentity", {})
        bt = b.get("tonality", {})
        old_sig = (bmi.get("primaryLoop"), bt.get("mode"), bt.get("rootNote"), bmi.get("padCharacter"))
        if new_sig == old_sig:
            errors.append(f"duplicate 4-tuple signature: {new_sig}")
            break

    # No same culturalReference in last 3
    if last_3:
        recent_cultures = [b["musicalIdentity"]["culturalReference"] for b in last_3]
        if mi.get("culturalReference") in recent_cultures:
            errors.append("culturalReference repeated in last 3")

    # No same primaryLoop in last 5
    if last_5:
        recent_loops = [b["musicalIdentity"]["primaryLoop"] for b in last_5]
        if mi.get("primaryLoop") in recent_loops:
            errors.append("primaryLoop repeated in last 5")

    # No same rootNote in last 5
    if last_5:
        recent_roots = [b["tonality"]["rootNote"] for b in last_5]
        if t.get("rootNote") in recent_roots:
            errors.append("rootNote repeated in last 5")

    # No same (primaryLoop, padCharacter) pair in all briefs
    new_loop_pad = (mi.get("primaryLoop"), mi.get("padCharacter"))
    for b in all_briefs:
        bmi = b.get("musicalIdentity", {})
        if (bmi.get("primaryLoop"), bmi.get("padCharacter")) == new_loop_pad:
            errors.append(f"duplicate loop+pad pair: {new_loop_pad}")
            break

    # No same mode in last 3
    if last_3:
        recent_modes = [b["tonality"]["mode"] for b in last_3]
        if t.get("mode") in recent_modes:
            errors.append("mode repeated in last 3")

    # Age-specific validation
    age = new_brief.get("ageGroup", "6-8")
    mode = t.get("mode", "")
    melody = new_brief.get("melodicCharacter", "")
    tempo = new_brief.get("rhythm", {}).get("baseTempo", 66)

    if age == "2-5" and mode not in ["major_pentatonic", "minor_pentatonic"]:
        errors.append("ages 2-5 require pentatonic modes")
    if age == "2-5" and melody not in ["descending_lullaby", "cycling_arpeggio"]:
        errors.append("ages 2-5 require lullaby or arpeggio melody")
    if age == "9-12" and len(new_brief.get("environment", {}).get("ambientEvents", [])) > 0:
        errors.append("ages 9-12 should have no ambient events")

    return errors


def fix_brief(brief, age_group):
    """Auto-fix common issues in the brief to avoid re-generation."""
    mi = brief.setdefault("musicalIdentity", {})
    t = brief.setdefault("tonality", {})
    r = brief.setdefault("rhythm", {})
    env = brief.setdefault("environment", {})

    # Fix invalid enum values
    if mi.get("culturalReference") not in CULTURAL_REFERENCES:
        mi["culturalReference"] = random.choice(CULTURAL_REFERENCES)
    if mi.get("primaryLoop") not in PRIMARY_LOOPS:
        mi["primaryLoop"] = random.choice(PRIMARY_LOOPS)
    if mi.get("padCharacter") not in PAD_CHARACTERS:
        mi["padCharacter"] = random.choice(PAD_CHARACTERS)
    if t.get("mode") not in MODES:
        t["mode"] = "major_pentatonic"
    if t.get("rootNote") not in ROOT_NOTES:
        t["rootNote"] = random.choice(ROOT_NOTES)
    if brief.get("melodicCharacter") not in MELODIC_CHARACTERS:
        brief["melodicCharacter"] = "descending_lullaby"

    # Fix tempo
    tempo = r.get("baseTempo", 66)
    r["baseTempo"] = max(58, min(75, int(tempo)))

    # Fix nature sounds
    if env.get("natureSoundPrimary") not in NATURE_SOUNDS_PRIMARY:
        env["natureSoundPrimary"] = "rain_steady"
    sec = env.get("natureSoundSecondary")
    if sec is not None and sec not in [s for s in NATURE_SOUNDS_SECONDARY if s]:
        env["natureSoundSecondary"] = None

    # Fix ambient events
    env["ambientEvents"] = [e for e in env.get("ambientEvents", []) if e in AMBIENT_EVENTS]

    # Age-specific fixes
    if age_group == "2-5":
        if t["mode"] not in ["major_pentatonic", "minor_pentatonic"]:
            t["mode"] = "major_pentatonic"
        if brief["melodicCharacter"] not in ["descending_lullaby", "cycling_arpeggio"]:
            brief["melodicCharacter"] = "descending_lullaby"
    if age_group == "9-12":
        env["ambientEvents"] = []
        if brief["melodicCharacter"] not in ["drone_with_ornaments", "stillness"]:
            brief["melodicCharacter"] = "drone_with_ornaments"

    # Fix rhythm feel
    if r.get("feel") not in ["free_rubato", "gentle_pulse"]:
        r["feel"] = "free_rubato"

    return brief


def fix_duplicate_signature(brief, existing_briefs, age_group):
    """Mutate brief to avoid duplicate (loop, mode, rootNote, pad) 4-tuple."""
    mi = brief.get("musicalIdentity", {})
    t = brief.get("tonality", {})

    existing_sigs = set()
    existing_loop_pads = set()
    for b in existing_briefs:
        bmi = b.get("musicalIdentity", {})
        bt = b.get("tonality", {})
        existing_sigs.add((bmi.get("primaryLoop"), bt.get("mode"), bt.get("rootNote"), bmi.get("padCharacter")))
        existing_loop_pads.add((bmi.get("primaryLoop"), bmi.get("padCharacter")))

    current_sig = (mi.get("primaryLoop"), t.get("mode"), t.get("rootNote"), mi.get("padCharacter"))
    if current_sig not in existing_sigs:
        return brief  # already unique

    # Try changing rootNote first (cheapest change musically)
    allowed_modes = MODES
    if age_group == "2-5":
        allowed_modes = ["major_pentatonic", "minor_pentatonic"]

    for root in ROOT_NOTES:
        test_sig = (mi.get("primaryLoop"), t.get("mode"), root, mi.get("padCharacter"))
        if test_sig not in existing_sigs:
            t["rootNote"] = root
            return brief

    # Try changing mode
    for mode in allowed_modes:
        for root in ROOT_NOTES:
            test_sig = (mi.get("primaryLoop"), mode, root, mi.get("padCharacter"))
            if test_sig not in existing_sigs:
                t["mode"] = mode
                t["rootNote"] = root
                return brief

    # Try changing pad
    for pad in PAD_CHARACTERS:
        test_sig = (mi.get("primaryLoop"), t.get("mode"), t.get("rootNote"), pad)
        if test_sig not in existing_sigs:
            mi["padCharacter"] = pad
            return brief

    # Last resort: change loop
    for loop in PRIMARY_LOOPS:
        for root in ROOT_NOTES:
            test_sig = (loop, t.get("mode"), root, mi.get("padCharacter"))
            if test_sig not in existing_sigs:
                mi["primaryLoop"] = loop
                t["rootNote"] = root
                return brief

    return brief  # couldn't fix — accept as-is


# ── Brief Generation ──

def generate_brief_for_story(story, story_index, total_stories):
    """Generate a Musical Brief for a story using Mistral."""
    title = story.get("title", "Untitled")
    theme = story.get("theme", "dreamy")
    description = story.get("description", "")
    content_type = story.get("type", "story")
    target_age = story.get("target_age", 5)
    age_group = get_age_group(target_age)

    # Build story metadata string
    char_info = ""
    if isinstance(story.get("character"), dict):
        char_info = f"Character: {story['character'].get('name', '')}"
        if story['character'].get('special'):
            char_info += f" ({story['character']['special']})"

    story_metadata = f"""Title: "{title}"
Theme: {theme}
Type: {content_type}
Description: {description}
{char_info}
Target age: {target_age} years
Language: {story.get('lang', 'en')}"""

    last_5_summary = tracker.get_summary_for_prompt()

    prompt = f"""You are a music director for a children's bedtime story app.
Generate a Musical Brief — a high-level creative description
of the background music for this story.

STORY METADATA:
{story_metadata}

AGE GROUP: {age_group}

Choose from these options:

culturalReference (pick ONE):
  celtic | japanese | african | nordic | indian |
  middle_eastern | latin | chinese | ambient_electronic |
  music_box | orchestral | folk_acoustic

primaryLoop (pick ONE matching the culturalReference):
  harp_arpeggios | koto_plucks | kalimba_melody |
  singing_bowl_rings | cello_sustains | hang_drum_melody |
  piano_lullaby | guitar_fingerpick | music_box_melody |
  flute_breathy | marimba_soft | dulcimer_gentle

padCharacter (pick ONE):
  warm_strings | crystal_air | deep_ocean | forest_hum |
  starfield | earth_drone | silk_veil | cave_resonance

mode (pick ONE):
  major_pentatonic | minor_pentatonic | dorian |
  aeolian | mixolydian

rootNote (pick ONE):
  C | D | Eb | E | F | G | Ab | A | Bb | B

melodicCharacter (pick ONE):
  descending_lullaby | cycling_arpeggio |
  drone_with_ornaments | stillness

rhythm.feel (pick ONE):
  free_rubato | gentle_pulse

baseTempo: integer between 58 and 75

natureSoundPrimary (pick ONE):
  forest_night | rain_steady | rain_light |
  ocean_waves_close | ocean_waves_distant |
  river_stream | wind_gentle | wind_high |
  underwater | fireplace_crackle | near_silence

natureSoundSecondary (pick ONE or null):
  distant_stream | distant_thunder | underwater_bubbling |
  fireplace_crackle | wind_gentle | null

ambientEvents (pick 0-2):
  owl | leaves | waterDrop | waveCycle |
  windGust | cricket | heartbeat | chimes

RULES:
- baseTempo must be 58-75 BPM
- For ages 2-5: mode must be major_pentatonic or minor_pentatonic
- For ages 2-5: melodicCharacter must be descending_lullaby or cycling_arpeggio
- For ages 9-12: melodicCharacter should be drone_with_ornaments or stillness
- For ages 9-12: ambientEvents should be empty []
- Match culturalReference to the story's world, but be creative.
  A forest story could be celtic OR japanese OR african.
  An ocean story could be ambient_electronic OR latin.
- emotionalArc.phase3 must always be "deep_stillness" or "warm_silence"

IMPORTANT — DIVERSITY: Here are the last 5 briefs generated.
Do NOT repeat the same culturalReference, primaryLoop, mode,
or rootNote as any of these:
{last_5_summary}

Respond with ONLY the JSON brief. No explanation.

{{
  "storyId": "{story.get('id', '')}",
  "ageGroup": "{age_group}",
  "musicalIdentity": {{
    "culturalReference": "...",
    "primaryLoop": "...",
    "padCharacter": "..."
  }},
  "tonality": {{
    "mode": "...",
    "rootNote": "..."
  }},
  "melodicCharacter": "...",
  "rhythm": {{
    "feel": "...",
    "baseTempo": 66
  }},
  "environment": {{
    "natureSoundPrimary": "...",
    "natureSoundSecondary": "..." or null,
    "ambientEvents": ["..."]
  }},
  "emotionalArc": {{
    "phase1": "...",
    "phase2": "...",
    "phase3": "deep_stillness"
  }}
}}"""

    max_attempts = 3
    for attempt in range(max_attempts):
        raw = call_mistral(prompt, max_tokens=600, temperature=0.85)
        brief = parse_json_response(raw)

        # Ensure storyId and ageGroup are set
        brief["storyId"] = story.get("id", "")
        brief["ageGroup"] = age_group

        # Auto-fix common issues
        brief = fix_brief(brief, age_group)

        # Validate schema
        schema_errors = validate_brief_schema(brief)
        if schema_errors:
            print(f"  [attempt {attempt+1}] schema errors: {schema_errors}")
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            # Last attempt — fix what we can
            brief = fix_brief(brief, age_group)

        # Validate diversity
        diversity_errors = validate_brief_diversity(brief, tracker.recent_briefs)
        if diversity_errors:
            print(f"  [diversity warning] {diversity_errors}")
            # Try to auto-fix duplicate signature
            brief = fix_duplicate_signature(brief, tracker.recent_briefs, age_group)
            # Re-check after fix
            diversity_errors = validate_brief_diversity(brief, tracker.recent_briefs)
            if diversity_errors and attempt < max_attempts - 1:
                time.sleep(2)
                continue
            # Accept on last attempt even with remaining diversity issues

        break

    return brief


# ── Seed Data Update ──

def update_seed_data_musical_brief(story_id, brief):
    """Add musicalBrief field to a story in seedData.js."""
    if not SEED_DATA_JS.exists():
        print(f"  WARNING: seedData.js not found")
        return False

    content = SEED_DATA_JS.read_text(encoding="utf-8")
    escaped_id = re.escape(story_id)
    brief_json = json.dumps(brief)

    # Find the story's id line
    id_match = re.search(rf'id:\s*"{escaped_id}"', content)
    if not id_match:
        print(f"  WARNING: {story_id} not found in seedData.js")
        return False

    # Find the end of this story's object block
    block_start = id_match.start()
    next_id = re.search(r'\n\s*id:\s*"', content[block_start + 10:])
    block_end = block_start + 10 + next_id.start() if next_id else len(content)
    block = content[block_start:block_end]

    # Check if musicalBrief already exists in this block
    mb_match = re.search(
        r',\s*musicalBrief:\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})',
        block
    )
    if mb_match:
        # Replace existing musicalBrief
        abs_start = block_start + mb_match.start()
        abs_end = block_start + mb_match.end()
        new_content = content[:abs_start] + f",\n      musicalBrief: {brief_json}" + content[abs_end:]
        SEED_DATA_JS.write_text(new_content, encoding="utf-8")
        return True

    # No existing musicalBrief — insert after musicProfile or musicParams or id
    for pattern in [r'musicParams:\s*\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}',
                    r'musicProfile:\s*"[^"]*"',
                    rf'id:\s*"{escaped_id}"']:
        match = re.search(pattern, block)
        if match:
            insert_point = block_start + match.end()
            break
    else:
        insert_point = block_start + len(story_id) + 10

    new_content = content[:insert_point] + f",\n      musicalBrief: {brief_json}" + content[insert_point:]
    SEED_DATA_JS.write_text(new_content, encoding="utf-8")
    return True


# ── Main ──

def run():
    parser = argparse.ArgumentParser(description="Generate Musical Briefs per story (v3)")
    parser.add_argument("--id", help="Generate for specific story ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--new-only", action="store_true", help="Only stories without musicalBrief")
    args = parser.parse_args()

    with open(CONTENT_JSON, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    # Skip songs — they use their own audio, no background music needed
    stories = [s for s in all_content if s.get("type") != "song"]
    if args.id:
        # Pre-seed tracker with existing briefs from other stories
        for s in all_content:
            mb = s.get("musicalBrief")
            if mb and s["id"] != args.id:
                tracker.record(mb)
        print(f"  Pre-seeded tracker with {len(tracker.recent_briefs)} existing briefs")
        stories = [s for s in stories if s["id"] == args.id]
    if args.new_only:
        stories = [s for s in stories if not s.get("musicalBrief")]

    # Shuffle for diversity fairness
    story_order = list(enumerate(stories))
    random.seed(42)
    random.shuffle(story_order)

    print(f"\n{'='*60}")
    print(f"  MUSICAL BRIEF GENERATION v3")
    print(f"  Stories: {len(stories)}")
    print(f"  API: Mistral ({MODEL})")
    print(f"  Output: ~500-byte Musical Briefs (composed client-side)")
    print(f"{'='*60}\n")

    results = {}
    total = len(story_order)

    for proc_idx, (orig_idx, story) in enumerate(story_order):
        age_group = get_age_group(story.get("target_age", 5))
        print(f"[{proc_idx+1}/{total}] {story['title']} ({story.get('theme', '?')}, age {age_group})")

        if args.dry_run:
            print(f"  → Would generate Musical Brief")
            continue

        try:
            brief = generate_brief_for_story(story, proc_idx, total)

            # Apply mood-specific music rules
            mood = story.get("mood", "calm") or "calm"
            brief = apply_mood_to_brief(brief, mood)

            results[story["id"]] = brief
            tracker.record(brief)

            mi = brief["musicalIdentity"]
            t = brief["tonality"]
            print(f"  ✓ culture={mi['culturalReference']}, loop={mi['primaryLoop']}, "
                  f"pad={mi['padCharacter']}")
            print(f"    mode={t['mode']}, root={t['rootNote']}, "
                  f"melody={brief['melodicCharacter']}")
            print(f"    nature={brief['environment']['natureSoundPrimary']}, "
                  f"events={brief['environment']['ambientEvents']}")

            time.sleep(2)  # Rate limit buffer

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Apply results
    if not args.dry_run:
        updated_count = 0
        for story in all_content:
            if story["id"] in results:
                story["musicalBrief"] = results[story["id"]]
                update_seed_data_musical_brief(story["id"], results[story["id"]])
                updated_count += 1

        with open(CONTENT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_content, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Updated {updated_count} stories in {CONTENT_JSON}")

    tracker.summary()


if __name__ == "__main__":
    run()
