#!/usr/bin/env python3
"""Generate lullabies for Dream Valley.

End-to-end: selects type → generates lyrics (Mistral) → generates audio (fal.ai MiniMax) → saves.
Replaces ACE-Step for vocal lullaby generation.

Usage:
    # Auto-select type based on mood + age + diversity
    python scripts/generate_lullaby.py --mood calm --age 2-5

    # Force specific type
    python scripts/generate_lullaby.py --type heartbeat

    # Generate multiple
    python scripts/generate_lullaby.py --count 3 --mood calm --age 2-5

    # Use fixed test lyrics (skip Mistral)
    python scripts/generate_lullaby.py --type rocking --skip-lyrics-gen

    # Dry run — show what would be generated
    python scripts/generate_lullaby.py --mood calm --age 2-5 --dry-run
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "seed_output" / "lullabies"
AUDIO_DIR = BASE_DIR / "public" / "audio" / "lullabies"
COVER_DIR = BASE_DIR / "public" / "covers" / "lullabies"
AUDIO_STORE = Path("/opt/audio-store/lullabies")

# ═════════════════════════════════════════════════════════════════════
# LULLABY TYPE DEFINITIONS
# ═════════════════════════════════════════════════════════════════════

LULLABY_TYPES = {
    "heartbeat": {
        "title": "Humming",
        "card_subtitle": "Just a gentle hum",
        "mechanism": "entrainment",
        "valid_ages": ["0-1", "2-5"],
        "signature_opening": None,
        "signature_closing": None,
    },
    "permission": {
        "title": "The World Sleeps",
        "card_subtitle": "Everything is going to sleep",
        "mechanism": "environmental_mirroring",
        "valid_ages": ["0-1", "2-5", "6-8", "9-12"],
        "signature_opening": "The world is going to sleep now",
        "signature_closing": "and so can you",
    },
    "shield": {
        "title": "You Are Safe",
        "card_subtitle": "A song about being protected",
        "mechanism": "security",
        "valid_ages": ["0-1", "2-5", "6-8"],
        "signature_opening": "I am here",
        "signature_closing": "I am still here",
    },
    "closing": {
        "title": "Day Is Done",
        "card_subtitle": "Wrapping up today",
        "mechanism": "cognitive_closure",
        "valid_ages": ["2-5", "6-8", "9-12"],
        "signature_opening": "What a day, what a day",
        "signature_closing": "and the day is done",
    },
    "rocking": {
        "title": "Rock-a-bye",
        "card_subtitle": "A classic cradle song",
        "mechanism": "vestibular_soothing",
        "valid_ages": ["0-1", "2-5", "6-8"],
        "signature_opening": "Rock-a-bye, rock-a-bye",
        "signature_closing": "rock-a-bye, goodnight",
    },
    "counting": {
        "title": "One by One",
        "card_subtitle": "Counting things to sleep",
        "mechanism": "cognitive_monotony",
        "valid_ages": ["2-5", "6-8"],
        "signature_opening": "One",
        "signature_closing": "and that was all",
    },
    "parent_song": {
        "title": "For You",
        "card_subtitle": "A parent's love",
        "mechanism": "bonding",
        "valid_ages": ["2-5", "6-8", "9-12"],
        "signature_opening": "I watched you today",
        "signature_closing": "and I'll be here tomorrow",
    },
    "warning": {
        "title": "Dream Catcher",
        "card_subtitle": "The dreams are waiting",
        "mechanism": "gentle_fomo",
        "valid_ages": ["2-5", "6-8"],
        "signature_opening": "The dreams are out tonight",
        "signature_closing": "better close your eyes",
    },
    "origin": {
        "title": "How Dreams Began",
        "card_subtitle": "Where dreams come from",
        "mechanism": "wonder",
        "valid_ages": ["6-8", "9-12"],
        "signature_opening": "Long before you were born",
        "signature_closing": "and it's still true tonight",
    },
}

# ═════════════════════════════════════════════════════════════════════
# MOOD → TYPE MAPPING
# ═════════════════════════════════════════════════════════════════════

MOOD_TO_TYPES = {
    "wired":   ["counting", "rocking", "warning"],
    "curious": ["origin", "permission", "warning"],
    "calm":    ["permission", "rocking", "heartbeat"],
    "sad":     ["parent_song", "closing", "heartbeat"],
    "anxious": ["shield", "heartbeat", "rocking"],
    "angry":   ["closing", "rocking", "counting"],
}

# ═════════════════════════════════════════════════════════════════════
# MINIMAX STYLE PROMPTS
# ═════════════════════════════════════════════════════════════════════

STYLE_PROMPTS = {
    "heartbeat": (
        "Solo female vocal lullaby, humming only, no instruments, "
        "no melody variation, sustained warm tones, 58 BPM, "
        "extremely intimate, breathy, mouth-closed humming, "
        "monotone drone, like breathing set to pitch, "
        "meditative, hypnotic, no percussion, pure voice"
    ),
    "permission": (
        "Gentle folk lullaby, warm female vocal, "
        "fingerpicked acoustic guitar, 64 BPM, "
        "pastoral, settling, peaceful, evening atmosphere, "
        "descending melody phrases, each verse quieter, "
        "conversational singing, the world going to sleep"
    ),
    "shield": (
        "Protective lullaby, warm female vocal, low register, "
        "simple piano chords, 62 BPM, "
        "steady, certain, grounded, reassuring, "
        "no vibrato, direct delivery, "
        "like a spoken promise set to a simple melody, "
        "minimal melodic movement, unwavering"
    ),
    "closing": (
        "Intimate domestic lullaby, warm female vocal, "
        "soft acoustic guitar, 64 BPM, "
        "cozy, familiar, conversational, "
        "almost speaking melodically, not performative, "
        "kitchen-to-bedroom energy, end of day warmth"
    ),
    "rocking": (
        "Traditional cradle song, warm maternal female vocal, "
        "harp arpeggios, 6/8 time signature, 64 BPM, "
        "swaying rocking rhythm, gentle lilting motion, "
        "the feeling of being carried and rocked, "
        "celtic lullaby influence, repetitive swinging pattern"
    ),
    "counting": (
        "Children's counting lullaby, clear sweet female vocal, "
        "xylophone and music box, 66 BPM, "
        "simple repetitive melody, same tune every line, "
        "cumulative nursery rhyme structure, "
        "bright but soft, childlike, extremely predictable rhythm"
    ),
    "parent_song": (
        "Intimate singer-songwriter lullaby, "
        "breathy unpolished female vocal, low register, "
        "sparse solo piano with single notes, 60 BPM, "
        "vulnerable, tender, raw, emotional, "
        "like singing alone late at night, "
        "not a performance, imperfect and real, extreme sparsity"
    ),
    "warning": (
        "Playful mysterious lullaby, warm female vocal, "
        "soft woodwind and low flute, 64 BPM, "
        "mischievous, conspiratorial, whimsical, "
        "fairy tale energy, like sharing a secret, "
        "mysterious but gentle, storytelling melody"
    ),
    "origin": (
        "Ancient storytelling lullaby, warm resonant female vocal, "
        "singing bowl and soft cello drone, 60 BPM, "
        "mythological, vast, reverent, timeless, "
        "the voice of someone very old and very kind, "
        "starts spacious and narrows to intimate, wonder without weight"
    ),
}

# Instrument pools for diversity within a type
VALID_INSTRUMENTS = {
    "heartbeat":   ["acapella"],
    "rocking":     ["harp", "guitar", "piano", "cello"],
    "counting":    ["xylophone", "music_box", "piano"],
    "shield":      ["piano"],
    "permission":  ["guitar", "harp", "piano", "flute"],
    "closing":     ["guitar", "piano"],
    "parent_song": ["piano"],
    "warning":     ["flute", "woodwind", "clarinet"],
    "origin":      ["singing_bowl", "cello", "drone"],
}

INSTRUMENT_PHRASES = {
    "harp": "harp arpeggios",
    "guitar": "fingerpicked acoustic guitar",
    "piano": "soft piano",
    "cello": "soft cello",
    "flute": "soft breathy flute",
    "xylophone": "xylophone",
    "music_box": "music box",
    "singing_bowl": "singing bowl",
    "woodwind": "soft woodwind",
    "clarinet": "soft clarinet",
    "drone": "low drone pad",
    "acapella": "no instruments, vocal only, a cappella",
}

# Imagery pools for lyrics diversity
VALID_IMAGERY = {
    "heartbeat":   ["none"],
    "rocking":     ["ocean", "sky", "moonlight", "starlight"],
    "counting":    ["forest_animals", "garden", "pond", "sky"],
    "shield":      ["home", "blanket", "walls", "warmth"],
    "permission":  ["moon", "stars", "river", "forest", "birds", "wind"],
    "closing":     ["home", "kitchen", "shoes", "bath", "pillow"],
    "parent_song": ["hands", "memory", "growing_up", "time"],
    "warning":     ["dreams", "window", "wings", "ships"],
    "origin":      ["stars", "first_dream", "ancient_sky", "mountains"],
}

# ═════════════════════════════════════════════════════════════════════
# LYRICS GENERATION (Mistral)
# ═════════════════════════════════════════════════════════════════════

LYRICS_SYSTEM_PROMPT = """You are a lullaby lyricist. Write lyrics that will be SUNG by a female vocalist.

CRITICAL FORMAT RULES:
- Use [verse] and [chorus] tags on their own lines — NO other tags
- Each line: 5-12 syllables, naturally singable
- Choruses MUST be IDENTICAL every time they appear (copy-paste exact same text)
- Write for the VOICE — these will be sung, not read
- Use common, simple English words
- Character names: 2 syllables max
- Prefer soft consonants and open vowels: moon, dream, star, sleep, gentle, warm
- Each line must be a complete thought (no enjambment)
- Total: 15-25 lyric lines (excluding [verse]/[chorus] headers)

OUTPUT: Only the lyrics. No commentary, no explanation."""

STRUCTURE_INSTRUCTIONS = {
    "heartbeat": (
        "Mostly nonsense syllables: Mmm, La la, Shh, Na na, Hmm.\n"
        "3 verses, each SHORTER than the last.\n"
        "No chorus. The hum IS the song.\n"
        "Last verse: just 2-3 syllables fading."
    ),
    "permission": (
        "3 verses + repeating chorus.\n"
        "Each verse: 4-5 lines, one thing in the world going to sleep.\n"
        "Chorus: 4 lines, identical, granting permission to sleep."
    ),
    "shield": (
        "2 verses + repeating chorus. SHORT.\n"
        "Each verse: 4 lines stating safety. Declarative. Certain.\n"
        "Chorus: 'I am here' repeated. No poetry — promises."
    ),
    "closing": (
        "3 verses + repeating chorus.\n"
        "V1: evening routine. V2: what happened today. V3: settling.\n"
        "Chorus: 'the day is done' repeated."
    ),
    "rocking": (
        "2-3 verses + repeating chorus.\n"
        "Rocking/sailing/swaying imagery. 'Rock-a-bye' anchor.\n"
        "Chorus: 2-3 lines, simple, rhythmic. Write for 6/8.\n"
        "RHYTHM matters more than words."
    ),
    "counting": (
        "4 verses, CUMULATIVE.\n"
        "V1: 'One [thing] [sleeping action]'\n"
        "V2: repeats V1 + 'Two...'\n"
        "V3: repeats V1+V2 + 'Three...'\n"
        "V4: repeats all + 'Four...' + 'And that was all.'\n"
        "SAME melody every line."
    ),
    "parent_song": (
        "2 verses + repeating chorus. SHORT.\n"
        "V1: memory of child when small. V2: child now, bigger.\n"
        "Chorus: 'you won't remember this.'\n"
        "Vulnerable. Real. Not performed."
    ),
    "warning": (
        "2 verses + repeating chorus.\n"
        "V1: dreams gathering, looking for sleeping eyes.\n"
        "V2: a specific dream that almost visited.\n"
        "Chorus: 'close your eyes and they will come.'\n"
        "Playful. Conspiratorial."
    ),
    "origin": (
        "2 verses + repeating chorus.\n"
        "V1: before dreams existed. V2: how the first dream was born.\n"
        "Chorus: 'that was the first dream.'\n"
        "Ancient. Wonder. Profound but gentle."
    ),
}

# Fallback lyrics for --skip-lyrics-gen or Mistral failure
FALLBACK_LYRICS = {
    "heartbeat": (
        "[verse]\nMmm mmm mmm mmm\nLa la la la\nMmm mmm mmm mmm\n"
        "Shh shh shh shh\n\n[verse]\nMmm mmm mmm mmm\nLa la la la\n"
        "Mmm mmm mmm mmm\nLa la la la\n\n[verse]\nMmm mmm mmm\n"
        "La la la\nMmm mmm\nLa la\nMmm"
    ),
    "permission": (
        "[verse]\nThe world is going to sleep now\nThe birds have tucked their wings away\n"
        "The river stopped its song\nThe flowers closed their petals soft\n"
        "The wind has moved along\n\n"
        "[chorus]\nSleep now, sleep now\nEverything is sleeping too\n"
        "Sleep now, sleep now\nThe world is dreaming just like you\n\n"
        "[verse]\nThe moon is watching quietly\nThe stars have dimmed their light\n"
        "The trees have stopped their whispering\nThe whole world says goodnight\n\n"
        "[chorus]\nSleep now, sleep now\nEverything is sleeping too\n"
        "Sleep now, sleep now\nAnd so can you"
    ),
    "shield": (
        "[verse]\nI am here\nThe walls are strong the door is shut\n"
        "The blanket wrapped around\nAnd nothing from the dark outside\n"
        "Can make a single sound\n\n"
        "[chorus]\nI am here, I am here\nNothing going to come\n"
        "I am here, I am here\nYou are safe at home\n\n"
        "[verse]\nThe shadows are just shapes that play\nThey cannot touch they cannot stay\n"
        "And every sound you hear tonight\nIs just the house that holds you tight\n\n"
        "[chorus]\nI am here, I am here\nNothing going to come\n"
        "I am here, I am here\nI am still here"
    ),
    "closing": (
        "[verse]\nWhat a day, what a day\nThe dishes are all washed and stacked\n"
        "Your shoes are by the door\nThe bath is done the teeth are brushed\n"
        "You don't need anything more\n\n"
        "[chorus]\nThe day is done the day is done\nThere's nothing left to do\n"
        "The day is done the day is done\nTomorrow's waiting too\n\n"
        "[verse]\nYou laughed today you played today\nYou ran until you stopped\n"
        "You ate your food you told a joke\nThe day was really a lot\n\n"
        "[chorus]\nThe day is done the day is done\nThere's nothing left to do\n"
        "The day is done the day is done\nAnd the day is done"
    ),
    "rocking": (
        "[verse]\nRock-a-bye, rock-a-bye\nRock-a-bye over the sea\n"
        "Rock-a-bye rock-a-bye\nCome back to me\n"
        "Sailing on moonlight rocking on air\n"
        "Rock-a-bye rock-a-bye I'll meet you there\n\n"
        "[chorus]\nSway and sway and sway and sleep\n"
        "Sway and sway and sway and sleep\n\n"
        "[verse]\nRock-a-bye rock-a-bye into the night\n"
        "Rock-a-bye rock-a-bye hold on tight\n"
        "Carried by starlight drifting so slow\n"
        "Rock-a-bye rock-a-bye let yourself go\n\n"
        "[chorus]\nSway and sway and sway and sleep\n"
        "Sway and sway and sway and sleep\nRock-a-bye goodnight"
    ),
    "counting": (
        "[verse]\nOne little owl closed her eyes\n\n"
        "[verse]\nOne little owl closed her eyes\n"
        "Two little fish stopped their swim\n\n"
        "[verse]\nOne little owl closed her eyes\n"
        "Two little fish stopped their swim\n"
        "Three little clouds stood very still\n\n"
        "[verse]\nOne little owl closed her eyes\n"
        "Two little fish stopped their swim\n"
        "Three little clouds stood very still\n"
        "Four little flowers felt the chill\nAnd that was all"
    ),
    "parent_song": (
        "[verse]\nI watched you today\nI watched you sleeping once before\n"
        "When you were very new\nYour hand was wrapped around my thumb\n"
        "And I just looked at you\n\n"
        "[chorus]\nYou won't remember this\nAnd that's okay\n"
        "I'll remember for us both\nAt the end of every day\n\n"
        "[verse]\nYou're bigger now your shoes have laces\n"
        "Your stories have beginnings\nAnd I'm still here beside your bed\n"
        "Just watching just listening\n\n"
        "[chorus]\nYou won't remember this\nAnd that's okay\n"
        "I'll remember for us both\nAnd I'll be here tomorrow"
    ),
    "warning": (
        "[verse]\nThe dreams are out tonight\nThey're choosing who to visit\n"
        "They only come to sleeping eyes\nIf you're awake you'll miss it\n\n"
        "[chorus]\nClose your eyes and they will come\n"
        "The ones with wings the ones that run\n"
        "But if you're up they'll fly right past\nClose your eyes close your eyes fast\n\n"
        "[verse]\nLast night a dream about a ship\nSailed past an open window\n"
        "It would have taken you on board\nBut you were still awake though\n\n"
        "[chorus]\nClose your eyes and they will come\n"
        "The ones with wings the ones that run\nBetter close your eyes"
    ),
    "origin": (
        "[verse]\nLong before you were born\nBefore there were dreams the night was just dark\n"
        "And no one knew why they would sleep\nUntil a small star fell out of the sky\n"
        "And cracked open soft warm and deep\n\n"
        "[chorus]\nAnd that was the first dream\nThe very first one\n"
        "It taught all the others\nHow dreaming is done\n\n"
        "[verse]\nIt floated through windows of every house\n"
        "And showed the sleeping world things\nMountains that talked and oceans that sang\n"
        "And fish that had feathery wings\n\n"
        "[chorus]\nAnd that was the first dream\nThe very first one\n"
        "And it's still true tonight"
    ),
}

# Cover prompts for FLUX generation (future use)
COVER_PROMPTS = {
    "heartbeat":   "Watercolor, extremely soft, single gentle curve suggesting breath, dark blue and purple, abstract, warmth and stillness",
    "permission":  "Watercolor, gentle night landscape, birds sleeping, quiet river, moon watching, soft blues and silver, everything asleep",
    "shield":      "Watercolor, warm glowing house at night, strong walls, warm light in window, stars above, solid safe golden warmth",
    "closing":     "Watercolor, cozy kitchen at night, dishes stacked, shoes by door, warm light fading, domestic intimate",
    "rocking":     "Watercolor, gentle cradle under stars, motion lines suggesting rocking, crescent moon, soft blues, being carried on water",
    "counting":    "Watercolor, animals sleeping one by one, owl eyes closed, fish still in pond, clouds not moving, soft pastels",
    "parent_song": "Watercolor, parent hand near child hand, just hands close up, warm golden light, extremely intimate, minimal",
    "warning":     "Watercolor, tiny glowing dreams floating past window, luminous creatures with wings, mysterious blues and golds, whimsical",
    "origin":      "Watercolor, single star falling through vast night sky, cracking open revealing golden light, deep blue, ancient, mythological",
}


# ═════════════════════════════════════════════════════════════════════
# DIVERSITY & SELECTION
# ═════════════════════════════════════════════════════════════════════

def load_existing_lullabies() -> list:
    """Load existing lullabies from output directory."""
    index_path = OUTPUT_DIR / "lullabies.json"
    if not index_path.exists():
        return []
    try:
        return json.loads(index_path.read_text())
    except Exception:
        return []


def select_type(mood: str, age: str, existing: list) -> str:
    """Select lullaby type based on mood, age, and diversity."""
    # Get types valid for this mood
    mood_types = MOOD_TO_TYPES.get(mood, ["permission", "rocking"])

    # Filter by age validity
    eligible = [t for t in mood_types
                if age in LULLABY_TYPES[t]["valid_ages"]]
    if not eligible:
        # Fallback: any type valid for this age
        eligible = [t for t, cfg in LULLABY_TYPES.items()
                    if age in cfg["valid_ages"]]

    # Avoid repeating same type in last 5
    recent_types = [l["lullaby_type"] for l in existing[-5:]]
    non_recent = [t for t in eligible if t not in recent_types]
    candidates = non_recent if non_recent else eligible

    # Pick least-used among candidates
    type_counts = Counter(l["lullaby_type"] for l in existing)
    return min(candidates, key=lambda t: type_counts.get(t, 0))


def select_instrument(lullaby_type: str, existing: list) -> str:
    """Pick instrument, avoiding recent repeats."""
    pool = VALID_INSTRUMENTS[lullaby_type]
    if len(pool) == 1:
        return pool[0]
    recent = [l.get("instrument") for l in existing[-3:]
              if l.get("lullaby_type") == lullaby_type]
    non_recent = [i for i in pool if i not in recent]
    return random.choice(non_recent if non_recent else pool)


def select_imagery(lullaby_type: str, existing: list) -> str:
    """Pick imagery theme, avoiding recent repeats."""
    pool = VALID_IMAGERY[lullaby_type]
    if len(pool) == 1:
        return pool[0]
    recent = [l.get("imagery") for l in existing[-3:]
              if l.get("lullaby_type") == lullaby_type]
    non_recent = [i for i in pool if i not in recent]
    return random.choice(non_recent if non_recent else pool)


def build_style_prompt(lullaby_type: str, instrument: str) -> str:
    """Build final MiniMax style prompt with selected instrument."""
    base = STYLE_PROMPTS[lullaby_type]
    if instrument == "acapella":
        return base
    phrase = INSTRUMENT_PHRASES.get(instrument, instrument)
    # Replace the default instrument phrase if present, otherwise append
    return base + f", {phrase} accompaniment"


# ═════════════════════════════════════════════════════════════════════
# LYRICS GENERATION
# ═════════════════════════════════════════════════════════════════════

def generate_lyrics(lullaby_type: str, age: str, mood: str, imagery: str) -> str:
    """Generate lyrics via Mistral AI."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("  WARNING: No MISTRAL_API_KEY — using fallback lyrics")
        return FALLBACK_LYRICS.get(lullaby_type, FALLBACK_LYRICS["rocking"]), None, None, None, None

    try:
        from mistralai import Mistral
    except ImportError:
        print("  WARNING: mistralai not installed — using fallback lyrics")
        return FALLBACK_LYRICS.get(lullaby_type, FALLBACK_LYRICS["rocking"]), None, None, None, None

    type_cfg = LULLABY_TYPES[lullaby_type]
    structure = STRUCTURE_INSTRUCTIONS[lullaby_type]

    sig_opening = type_cfg["signature_opening"]
    sig_closing = type_cfg["signature_closing"]
    sig_text = ""
    if sig_opening:
        sig_text = (
            f"\nSIGNATURE OPENING (mandatory first sung words): {sig_opening}\n"
            f"SIGNATURE CLOSING (mandatory last sung words): {sig_closing}"
        )

    user_prompt = f"""Write lullaby lyrics.

TYPE: {lullaby_type} ({type_cfg['title']})
SLEEP MECHANISM: {type_cfg['mechanism']}
AGE GROUP: {age}
MOOD: {mood}
IMAGERY: {imagery.replace('_', ' ')}
{sig_text}

STRUCTURE:
{structure}

Write the lyrics with [verse] and [chorus] tags.

After the lyrics, generate these metadata lines:

[TITLE: your title here]
[COVER: your cover description here]
[CHARACTER_NAME: the main character's name from the lyrics]
[CHARACTER_IDENTITY: one sentence describing who they are]
[CHARACTER_SPECIAL: one sentence about what makes them special]
[ABOUT: 2-3 sentence description of the lullaby for parents]

TITLE RULES:
The title is the single most evocative IMAGE from the lyrics.
NOT the type name. NOT a character name. Just the image.
Examples:
- If lyrics mention a river stopping: "When the River Stopped"
- If lyrics mention shoes by the door: "Shoes by the Door"
- If lyrics count creatures: "One Sleepy Owl"
Keep it under 6 words.

COVER RULES:
Describe the main character or scene from the lyrics as a soft, dreamy
children's book illustration. Include the character (animal, creature, or
object) and their setting. Keep it cozy and sleepy.
Examples:
- Lyrics about a sleepy owl counting: a round fluffy owl with half-closed eyes perched on a moonlit branch
- Lyrics about a river stopping: a gentle stream at dusk with soft glowing fireflies
- Lyrics about being safe: a small bunny wrapped in a warm blanket under soft starlight

Style: soft watercolor, dreamy, warm muted colors, cozy nighttime, children's book illustration.

CHARACTER RULES:
- CHARACTER_NAME: The name of the main character in the lyrics (e.g., "Owl", "Nimbus", "Lumi"). If no named character, use the most prominent creature or thing.
- CHARACTER_IDENTITY: A warm, short description (e.g., "A round fluffy owl who counts the forest friends to sleep")
- CHARACTER_SPECIAL: Their special quality (e.g., "Knows every creature in the forest by name")
- If the lyrics have no character at all (pure abstract/humming), write "none" for all three.

ABOUT RULES:
Write 2-3 gentle sentences describing the lullaby for parents. Mention what the lullaby is about, the sleep mechanism, and why it helps children sleep. Example: "A gentle counting lullaby where forest creatures drift off one by one. The predictable, cumulative rhythm soothes active minds into stillness.\" """

    print(f"  Generating lyrics via Mistral...")
    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {"role": "system", "content": LYRICS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=1000,
    )

    lyrics = response.choices[0].message.content.strip()

    # Clean: remove markdown code fences if present
    if lyrics.startswith("```"):
        lines = lyrics.split("\n")
        lyrics = "\n".join(l for l in lines if not l.startswith("```"))

    # Extract metadata tags from lyrics
    title = None
    cover_prompt = None
    character = None
    about = None
    import re

    title_match = re.search(r'\[TITLE:\s*(.+?)\]', lyrics)
    if title_match:
        title = title_match.group(1).strip().strip('"\'')
        lyrics = re.sub(r'\n*\[TITLE:[^\]]+\]\n*', '\n', lyrics).strip()

    cover_match = re.search(r'\[COVER:\s*(.+?)\]', lyrics)
    if cover_match:
        cover_prompt = cover_match.group(1).strip().strip('"\'')
        lyrics = re.sub(r'\n*\[COVER:[^\]]+\]\n*', '\n', lyrics).strip()

    # Extract character info
    char_name_match = re.search(r'\[CHARACTER_NAME:\s*(.+?)\]', lyrics)
    char_identity_match = re.search(r'\[CHARACTER_IDENTITY:\s*(.+?)\]', lyrics)
    char_special_match = re.search(r'\[CHARACTER_SPECIAL:\s*(.+?)\]', lyrics)
    if char_name_match:
        name = char_name_match.group(1).strip().strip('"\'')
        if name.lower() != "none":
            character = {
                "name": name,
                "identity": char_identity_match.group(1).strip().strip('"\'') if char_identity_match else "",
                "special": char_special_match.group(1).strip().strip('"\'') if char_special_match else "",
                "personality_tags": ["Gentle", "Sleepy"],
            }
    # Strip character tags from lyrics
    for tag in ["CHARACTER_NAME", "CHARACTER_IDENTITY", "CHARACTER_SPECIAL"]:
        lyrics = re.sub(rf'\n*\[{tag}:[^\]]+\]\n*', '\n', lyrics).strip()

    # Extract about text
    about_match = re.search(r'\[ABOUT:\s*(.+?)\]', lyrics)
    if about_match:
        about = about_match.group(1).strip().strip('"\'')
        lyrics = re.sub(r'\n*\[ABOUT:[^\]]+\]\n*', '\n', lyrics).strip()

    print(f"  Lyrics: {len(lyrics)} chars, {lyrics.count('[verse]')} verses, {lyrics.count('[chorus]')} choruses")
    if title:
        print(f"  Title: {title}")
    if cover_prompt:
        print(f"  Cover: {cover_prompt[:60]}...")
    if character:
        print(f"  Character: {character['name']} — {character.get('identity', '')[:50]}...")
    if about:
        print(f"  About: {about[:60]}...")
    return lyrics, title, cover_prompt, character, about


# ═════════════════════════════════════════════════════════════════════
# AUDIO GENERATION (fal.ai MiniMax)
# ═════════════════════════════════════════════════════════════════════

def generate_audio(style_prompt: str, lyrics: str) -> tuple:
    """Generate audio via fal.ai MiniMax Music v2. Returns (audio_bytes, audio_url)."""
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise RuntimeError("FAL_KEY not set in environment")

    try:
        import fal_client
    except ImportError:
        raise RuntimeError("fal-client not installed — pip install fal-client")

    print(f"  Calling fal.ai MiniMax Music v2...")
    print(f"  Style: {style_prompt[:80]}...")
    start = time.time()

    result = fal_client.subscribe("fal-ai/minimax-music/v2", arguments={
        "prompt": style_prompt,
        "lyrics_prompt": lyrics,
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
    })

    audio_info = result.get("audio") or result.get("data", {}).get("audio")
    if not audio_info or not audio_info.get("url"):
        raise RuntimeError(f"No audio URL in response: {result}")

    audio_url = audio_info["url"]
    print(f"  Got audio URL, downloading...")

    import httpx
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    elapsed = time.time() - start
    print(f"  Got {len(resp.content):,} bytes in {elapsed:.0f}s")
    return resp.content, audio_url


def generate_audio_replicate(style_prompt: str, lyrics: str) -> tuple:
    """Fallback: generate audio via Replicate MiniMax Music 1.5."""
    try:
        import replicate
        import httpx
    except ImportError:
        raise RuntimeError("replicate/httpx not installed")

    print(f"  Calling MiniMax Music 1.5 on Replicate (fallback)...")
    start = time.time()

    output = replicate.run(
        "minimax/music-1.5",
        input={"prompt": style_prompt, "lyrics": lyrics},
    )
    if not output:
        raise RuntimeError("No output from Replicate")

    audio_url = str(output)
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    elapsed = time.time() - start
    print(f"  Got {len(resp.content):,} bytes in {elapsed:.0f}s")
    return resp.content, audio_url


# ═════════════════════════════════════════════════════════════════════
# COVER & METADATA
# ═════════════════════════════════════════════════════════════════════

def generate_placeholder_cover(lullaby_type: str, lullaby_id: str) -> str:
    """Generate placeholder SVG cover. Returns filename."""
    meta = LULLABY_TYPES[lullaby_type]
    cover_file = f"{lullaby_id}_cover.svg"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#1a1a3e"/>
      <stop offset="100%" stop-color="#0d0d1a"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <circle cx="256" cy="200" r="60" fill="#2a2a5e" opacity="0.5">
    <animate attributeName="r" values="58;62;58" dur="4s" repeatCount="indefinite"/>
  </circle>
  <circle cx="256" cy="200" r="30" fill="#3a3a7e" opacity="0.4">
    <animate attributeName="r" values="28;32;28" dur="3s" repeatCount="indefinite"/>
  </circle>
  <text x="256" y="350" text-anchor="middle" fill="#8888bb" font-family="Georgia" font-size="28">{meta['title']}</text>
  <text x="256" y="385" text-anchor="middle" fill="#6666aa" font-family="Georgia" font-size="16">{meta['card_subtitle']}</text>
</svg>"""
    (OUTPUT_DIR / cover_file).write_text(svg)
    return cover_file


def get_audio_duration(mp3_path: Path) -> int:
    """Get duration of MP3 in seconds."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(str(mp3_path))
        return int(len(audio) / 1000)
    except Exception:
        # Estimate from file size (~16kB/s for 128kbps)
        return max(1, int(mp3_path.stat().st_size / 16000))


def make_lullaby_id(lullaby_type: str, age: str) -> str:
    """Generate a unique lullaby ID."""
    ts = int(time.time()) & 0xFFFF  # last 16 bits of timestamp
    return f"{lullaby_type}-{age}-{ts:04x}"


# ═════════════════════════════════════════════════════════════════════
# MAIN GENERATION LOOP
# ═════════════════════════════════════════════════════════════════════

def generate_one(mood: str, age: str, lullaby_type: str = None,
                 skip_lyrics_gen: bool = False, dry_run: bool = False) -> dict | None:
    """Generate a single lullaby end-to-end. Returns metadata dict or None on failure."""
    existing = load_existing_lullabies()

    # Select type if not forced
    if not lullaby_type:
        lullaby_type = select_type(mood, age, existing)

    # Validate age for this type
    type_cfg = LULLABY_TYPES[lullaby_type]
    if age not in type_cfg["valid_ages"]:
        print(f"  WARNING: {lullaby_type} not valid for age {age}, picking closest valid age")
        age = type_cfg["valid_ages"][0]

    # Select diversity dimensions
    instrument = select_instrument(lullaby_type, existing)
    imagery = select_imagery(lullaby_type, existing)
    style_prompt = build_style_prompt(lullaby_type, instrument)

    lullaby_id = make_lullaby_id(lullaby_type, age)

    print(f"\n{'='*60}")
    print(f"Generating: {lullaby_type} — {type_cfg['title']}")
    print(f"  Age: {age} | Mood: {mood} | Instrument: {instrument} | Imagery: {imagery}")
    print(f"  ID: {lullaby_id}")
    print(f"{'='*60}")

    if dry_run:
        print(f"  [DRY RUN] Would generate lyrics + audio")
        return {"id": lullaby_id, "lullaby_type": lullaby_type, "dry_run": True}

    # 1. Generate lyrics
    generated_title = None
    generated_cover_prompt = None
    generated_character = None
    generated_about = None
    if skip_lyrics_gen:
        lyrics = FALLBACK_LYRICS.get(lullaby_type, FALLBACK_LYRICS["rocking"])
        print(f"  Using fallback lyrics ({len(lyrics)} chars)")
    else:
        try:
            lyrics, generated_title, generated_cover_prompt, generated_character, generated_about = generate_lyrics(lullaby_type, age, mood, imagery)
        except Exception as e:
            print(f"  Lyrics generation failed: {e}")
            lyrics = FALLBACK_LYRICS.get(lullaby_type, FALLBACK_LYRICS["rocking"])
            print(f"  Using fallback lyrics ({len(lyrics)} chars)")

    # 2. Generate audio (try fal.ai first, fall back to Replicate)
    try:
        audio_bytes, audio_url = generate_audio(style_prompt, lyrics)
    except Exception as e:
        print(f"  fal.ai failed: {e}")
        print(f"  Trying Replicate fallback...")
        try:
            audio_bytes, audio_url = generate_audio_replicate(style_prompt, lyrics)
        except Exception as e2:
            print(f"  ERROR: Both audio engines failed: {e2}")
            return None

    # 3. Save audio
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mp3_path = OUTPUT_DIR / f"{lullaby_id}.mp3"
    mp3_path.write_bytes(audio_bytes)
    print(f"  Audio: {mp3_path.name} ({len(audio_bytes):,} bytes)")

    # Also copy to public audio dir for serving
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIO_DIR / f"{lullaby_id}.mp3").write_bytes(audio_bytes)

    # Backup to persistent store
    if AUDIO_STORE.exists():
        import shutil
        shutil.copy2(str(mp3_path), str(AUDIO_STORE / f"{lullaby_id}.mp3"))
        print(f"  Backed up to {AUDIO_STORE}")

    # 4. Generate cover
    cover_file = generate_placeholder_cover(lullaby_type, lullaby_id)
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    cover_src = OUTPUT_DIR / cover_file
    if cover_src.exists():
        import shutil
        shutil.copy2(str(cover_src), str(COVER_DIR / cover_file))

    # 5. Get duration
    duration = get_audio_duration(mp3_path)

    # 6. Build metadata
    # Title: use LLM-generated title, fallback to type label
    title = generated_title or type_cfg["title"]
    # Cover prompt: use LLM-generated (lyrics-specific), fallback to type-level generic
    cover_prompt_text = generated_cover_prompt or COVER_PROMPTS.get(lullaby_type, "")

    meta = {
        "id": lullaby_id,
        "title": title,
        "content_type": "lullaby",
        "lullaby_type": lullaby_type,
        "card_label": type_cfg["title"],
        "card_subtitle": type_cfg["card_subtitle"],
        "age_group": age,
        "mood": mood,
        "language": "en",
        "instrument": instrument,
        "imagery": imagery,
        "audio_file": f"{lullaby_id}.mp3",
        "cover_file": cover_file,
        "cover_prompt": cover_prompt_text,
        "duration_seconds": duration,
        "lyrics": lyrics,
        "style_prompt": style_prompt,
        "engine": "minimax-music-v2-fal",
        "fingerprint": {
            "lullabyType": lullaby_type,
            "instrument": instrument,
            "imagery": imagery,
            "mood": mood,
        },
        "created_at": str(date.today()),
        "character": generated_character,
        "about": generated_about or "",
    }

    # Save individual metadata
    meta_path = OUTPUT_DIR / f"{lullaby_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"  Metadata: {meta_path.name} (duration: {duration}s)")

    # 7. Update lullabies index
    existing.append(meta)
    index_path = OUTPUT_DIR / "lullabies.json"
    index_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"  Index updated: {len(existing)} total lullabies")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Generate lullabies via MiniMax Music (fal.ai)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--type", choices=list(LULLABY_TYPES.keys()),
                        help="Force specific lullaby type")
    parser.add_argument("--mood", choices=list(MOOD_TO_TYPES.keys()),
                        default="calm", help="Child mood (default: calm)")
    parser.add_argument("--age", default="2-5",
                        choices=["0-1", "2-5", "6-8", "9-12"],
                        help="Age group (default: 2-5)")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of lullabies to generate (default: 1)")
    parser.add_argument("--skip-lyrics-gen", action="store_true",
                        help="Use fallback lyrics (skip Mistral)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without generating")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"Lullaby Generator — MiniMax Music v2 via fal.ai")
    print(f"  Mood: {args.mood} | Age: {args.age} | Count: {args.count}")
    if args.type:
        print(f"  Forced type: {args.type}")
    print(f"{'='*60}")

    results = []
    for i in range(args.count):
        if i > 0:
            time.sleep(3)  # Brief pause between generations

        meta = generate_one(
            mood=args.mood,
            age=args.age,
            lullaby_type=args.type,
            skip_lyrics_gen=args.skip_lyrics_gen,
            dry_run=args.dry_run,
        )
        if meta:
            results.append(meta)
        else:
            print(f"  FAILED: lullaby {i+1}/{args.count}")

    print(f"\n{'='*60}")
    print(f"Done: {len(results)}/{args.count} lullabies generated")
    for m in results:
        dur = m.get("duration_seconds", "?")
        print(f"  [{m['lullaby_type']}] {m.get('title', '?')} — {dur}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
