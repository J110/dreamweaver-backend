"""
Story type configuration constants for narrative diversity in content generation.

All 6 story types: folk_tale, mythological, fable, nature, slice_of_life, dream.
Used by generate_content_matrix.py (text), generate_cover_experimental.py (covers),
generate_music_params.py (music), and pipeline_run.py (orchestration).
"""

# ═══════════════════════════════════════════════════════════════════════
# VALID STORY TYPE x AGE x CONTENT TYPE COMBINATIONS
# ═══════════════════════════════════════════════════════════════════════

VALID_STORY_TYPES = {
    "folk_tale", "mythological", "fable", "nature", "slice_of_life", "dream",
}

# All 6 types valid for ages 2-5, 6-8, 9-12. Not valid for 0-1 (infants get lullabies only).
VALID_STORY_TYPE_AGES = {
    "folk_tale":     ["2-5", "6-8", "9-12"],
    "mythological":  ["2-5", "6-8", "9-12"],
    "fable":         ["2-5", "6-8", "9-12"],
    "nature":        ["2-5", "6-8", "9-12"],
    "slice_of_life": ["2-5", "6-8", "9-12"],
    "dream":         ["2-5", "6-8", "9-12"],
}

# Stories, long stories, and poems get story types. Songs (lullabies) do NOT.
VALID_STORY_TYPE_CONTENT_TYPES = {
    "folk_tale":     ["story", "long_story", "poem"],
    "mythological":  ["story", "long_story", "poem"],
    "fable":         ["story", "long_story", "poem"],
    "nature":        ["story", "long_story", "poem"],
    "slice_of_life": ["story", "long_story", "poem"],
    "dream":         ["story", "long_story", "poem"],
}

# ═══════════════════════════════════════════════════════════════════════
# INVALID STORY TYPE x MOOD COMBINATIONS
# ═══════════════════════════════════════════════════════════════════════

INVALID_STORY_TYPE_MOOD = {
    ("slice_of_life", "angry"),   # slice of life is calm domestic — anger needs conflict
    ("slice_of_life", "wired"),   # slice of life is calm domestic — wired energy doesn't fit
    ("mythological", "wired"),    # ancient elevated voice can't carry playful energy
    ("mythological", "angry"),    # ancient elevated voice can't carry anger release
    ("dream", "angry"),           # dream is associative — anger needs a clear arc
    ("dream", "sad"),             # sadness needs grounding, dream is ungrounded
}


def is_valid_story_type_mood(story_type: str, mood: str) -> bool:
    """Check if a story_type x mood combination is valid."""
    return (story_type, mood) not in INVALID_STORY_TYPE_MOOD


def validate_story_type_combo(story_type: str, age: str, content_type: str) -> tuple:
    """Check if story_type x age x content_type combination is valid. Returns (valid, reason)."""
    if story_type not in VALID_STORY_TYPES:
        return False, f"Unknown story type: {story_type}"
    if age not in VALID_STORY_TYPE_AGES[story_type]:
        return False, f"Story type '{story_type}' not valid for age {age}. Valid: {VALID_STORY_TYPE_AGES[story_type]}"
    if content_type not in VALID_STORY_TYPE_CONTENT_TYPES[story_type]:
        return False, f"Story type '{story_type}' not valid for {content_type}. Valid: {VALID_STORY_TYPE_CONTENT_TYPES[story_type]}"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════
# STORY TYPE SIGNATURES — Opening and Closing Lines
# ═══════════════════════════════════════════════════════════════════════

ENGLISH_SIGNATURES = {
    "folk_tale": {
        "opening": "There was a {character}, and {character's name} had {one trait or problem}.",
        "closing": "And {name} fell asleep, warm and still.",
    },
    "mythological": {
        "opening": "Long ago, before {something existed or was understood}...",
        "closing": "And ever since then, {the thing still happens}.",
    },
    "fable": {
        "opening": "One day, {character A} said to {character B} —",
        "closing": "And {character} found their answer.",
    },
    "nature": {
        "opening": "Did you know that {natural wonder}?",
        "closing": "And right now, somewhere, {wonder is still happening}.",
    },
    "slice_of_life": {
        "opening": "It was {day}, and {day}s always {familiar routine}.",
        "closing": "And the house was quiet. And everything was fine. Just like that.",
    },
    "dream": {
        "opening": "{Bedtime object} {transformed} — and the dream began.",
        "closing": "And the dream slowly... slowly... faded away.",
    },
}

ENGLISH_SIGNATURE_PROMPT = """\
STORY SIGNATURE: Every story MUST use the correct opening and closing
for its story type. These are recognizable frames the child learns.

Your story type is: {story_type}

OPENING — Start your story with EXACTLY this pattern:
{opening_template}

CLOSING — End your story with EXACTLY this pattern:
{closing_template}

Fill the {{variable}} parts based on your story's content.
The fixed words must appear exactly as written."""


def build_signature_prompt(story_type: str) -> str:
    """Build the signature prompt for a given story type."""
    sig = ENGLISH_SIGNATURES.get(story_type)
    if not sig:
        return ""
    return ENGLISH_SIGNATURE_PROMPT.format(
        story_type=story_type,
        opening_template=sig["opening"],
        closing_template=sig["closing"],
    )


# ═══════════════════════════════════════════════════════════════════════
# STORY TYPE PROMPTS — TEXT GENERATION
# ═══════════════════════════════════════════════════════════════════════

ENGLISH_STORY_TYPE_PROMPTS = {
    "folk_tale": """\
STORY TYPE: FOLK TALE

The warm oral storyteller voice. You're telling this story to a child,
not reading it. You're present — you can say "and guess what happened?"
or "now, here's the thing about Bramble..."

Use rule-of-three: first time, second time, third time.
Use repetition with variation — same phrase, slightly different each time.
Give the character a name the child will remember.""",

    "mythological": """\
STORY TYPE: MYTHOLOGICAL — Origin Story

Tell a story about how something in nature came to be. The voice is ancient
but warm — like a grandparent who was there when the world was young.

Characters are forces of nature or archetypes: the first river, the wind
who forgot how to blow, the mountain who was afraid of the sky.
NOT gods, NOT religious figures. Original mythological voice, not mythology.""",

    "fable": """\
STORY TYPE: FABLE — Wisdom Through Dialogue

Two characters in conversation. A question, a dialogue, a quiet truth.
Keep it SHORT — fables lose power when they sprawl.

The truth is NEVER stated as a moral. It emerges from the conversation.
No "the lesson of this story is..." The child draws their own conclusion.""",

    "nature": """\
STORY TYPE: NATURE — True World Wonder

Real animals. Real phenomena. NO magic, NO talking animals, NO anthropomorphism.
The wonder comes from real facts described beautifully.

Use real science, simplified for the age group. A firefly story describes
real bioluminescence. A whale story describes real whale songs.
The world is magical enough without inventing magic.""",

    "slice_of_life": """\
STORY TYPE: SLICE OF LIFE — The Ordinary Evening

An ordinary child's evening described with extraordinary warmth.
No fantasy. No adventure. No conflict. Just: dinner, family, sounds, bed.

Sensory details: the smell of dinner, the sound of dishes, the warmth of
a bath, the feel of clean pyjamas, the voices of family in another room.
The child listening should think "that's MY evening.\"""",

    "dream": """\
STORY TYPE: DREAM — Surreal

Dream logic. Impossible things described as completely normal.
The narrator doesn't question anything — a fish flying is just what happens.

Start with a real object the child has in bed (pillow, blanket, window) transforming.
Everything is strange. Everything is safe. Objects transform,
gravity is optional, colours are wrong in beautiful ways.
The dream is not a story — it's a sequence of images that drift.""",
}

# Poem-adapted story type first lines (for poem signature integration)
STORY_TYPE_POEM_HINTS = {
    "folk_tale":     "Storytelling verse with named character. Example first line: 'There was a cat named Mabel Grey...'",
    "mythological":  "Origin verse — how something came to be. Example first line: 'Before the stars had learned to shine...'",
    "fable":         "Two voices in rhyming dialogue. Example first line: 'The river asked the stone one day...'",
    "nature":        "Real world wonder in verse. Example first line: 'Did you know a spider's thread...'",
    "slice_of_life": "Ordinary evening in verse. Example first line: 'The kitchen smells of Tuesday night...'",
    "dream":         "Surreal imagery in verse. Example first line: 'The pillow turned into a boat...'",
}


# ═══════════════════════════════════════════════════════════════════════
# TARGET DISTRIBUTION — for catch-up scheduling
# ═══════════════════════════════════════════════════════════════════════

STORY_TYPE_TARGET = {
    "folk_tale":     0.30,   # Still the largest — it's the natural bedtime tradition
    "mythological":  0.15,   # Origin stories are powerful but shouldn't dominate
    "fable":         0.15,   # Short, pointed — great for variety
    "nature":        0.15,   # Real world wonder — no competition in bedtime apps
    "slice_of_life": 0.10,   # Ordinary evenings — hardest to generate, most unique
    "dream":         0.15,   # Surreal — the most distinctive from everything else
}


# ═══════════════════════════════════════════════════════════════════════
# STORY TYPE — COVER ART CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

STORY_TYPE_COVER_PROMPTS = {
    "folk_tale": {
        "style": "warm storybook illustration, inviting, hand-painted feel",
        "composition": "character-centered, close framing, cozy",
        "palette_boost": {"ember_warm": 1.5, "golden_hour": 1.5},
        "palette_suppress": {"moonstone": 0.5, "twilight_cool": 0.7},
    },
    "mythological": {
        "style": "ancient, timeless, grand but soft, painted mural quality",
        "composition": "wide landscape, small figure against vast nature, epic scale",
        "palette_boost": {"twilight_cool": 1.5, "berry_dusk": 1.5},
        "palette_suppress": {"golden_hour": 0.7, "ember_warm": 0.7},
    },
    "fable": {
        "style": "minimal, clean, two subjects facing each other, graphic",
        "composition": "symmetrical or near-symmetrical, two characters, negative space",
        "palette_boost": {"golden_hour": 1.3, "forest_deep": 1.3},
        "palette_suppress": {},
    },
    "nature": {
        "style": "photorealistic-inspired, natural lighting, documentary beauty",
        "composition": "macro or close-up of real natural detail, shallow depth of field feel",
        "palette_boost": {"forest_deep": 1.5, "golden_hour": 1.3},
        "palette_suppress": {"berry_dusk": 0.5},
    },
    "slice_of_life": {
        "style": "warm domestic interior, soft lighting, lived-in spaces",
        "composition": "interior framing, window light, kitchen or bedroom setting",
        "palette_boost": {"ember_warm": 1.5, "golden_hour": 1.3},
        "palette_suppress": {"twilight_cool": 0.5, "berry_dusk": 0.5},
    },
    "dream": {
        "style": "surreal, impossible geometry, soft focus, objects out of place",
        "composition": "off-kilter, floating elements, distorted perspective",
        "palette_boost": {"berry_dusk": 1.5, "twilight_cool": 1.3},
        "palette_suppress": {"ember_warm": 0.7},
    },
}

# Composition weight modifiers by story type
STORY_TYPE_COMPOSITION_BOOSTS = {
    "folk_tale":     {"intimate_closeup": 1.5, "circular_nest": 1.3},
    "mythological":  {"vast_landscape": 1.8, "winding_path": 1.3},
    "fable":         {"intimate_closeup": 1.3},
    "nature":        {"overhead_canopy": 1.3, "vast_landscape": 1.3},
    "slice_of_life": {"circular_nest": 1.5, "intimate_closeup": 1.5},
    "dream":         {"winding_path": 1.5, "overhead_canopy": 1.3},
}


# ═══════════════════════════════════════════════════════════════════════
# STORY TYPE — MUSIC BRIEF CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

STORY_TYPE_MUSIC_RULES = {
    "folk_tale": {
        "instrument_prefer": ["guitar_fingerpick", "piano_lullaby", "harp_arpeggios"],
        "tempo_bias": 0,          # no change from mood default
        "feel": "warm, organic, handmade, storytelling campfire quality",
    },
    "mythological": {
        "instrument_prefer": ["singing_bowl_rings", "cello_sustains", "dulcimer_gentle"],
        "tempo_bias": -4,         # slightly slower — timeless, unhurried
        "feel": "ancient, vast, reverent, cathedral-like space",
    },
    "fable": {
        "instrument_prefer": ["piano_lullaby", "flute_breathy"],
        "tempo_bias": 0,
        "feel": "minimal, spare, two voices — like the two characters",
        "density": "sparse",      # fewer layers than default
    },
    "nature": {
        "instrument_prefer": ["flute_breathy", "piano_lullaby", "kalimba_melody"],
        "tempo_bias": -2,
        "feel": "documentary, observational, nature sounds prominent",
        "nature_sounds_boost": 1.5,   # nature sounds louder than usual
    },
    "slice_of_life": {
        "instrument_prefer": ["piano_lullaby", "guitar_fingerpick"],
        "tempo_bias": 0,
        "feel": "domestic, cozy, simple, like background music in a warm kitchen",
        "nature_sounds_suppress": True,   # no cricket sounds in a kitchen story
    },
    "dream": {
        "instrument_prefer": ["music_box_melody", "singing_bowl_rings", "dulcimer_gentle"],
        "tempo_bias": -3,
        "feel": "floaty, untethered, slightly detuned, dreamy reverb",
    },
}
