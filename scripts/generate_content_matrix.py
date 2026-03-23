"""Generate diversified bedtime stories and poems across age groups.

Uses Anthropic Claude, Groq, or Mistral AI APIs to generate content with 8 diversity
dimensions: universe/era, geography, life aspects, plot archetypes, character
gender, lead character entity type, unique characters, and anti-duplication constraints.

Output: seed_output/content_expanded.json (crash-resumable, append-safe)

Usage:
    python3 scripts/generate_content_matrix.py                    # Generate all
    python3 scripts/generate_content_matrix.py --lang en          # English only
    python3 scripts/generate_content_matrix.py --lang hi          # Hindi only
    python3 scripts/generate_content_matrix.py --age-group 0-1    # Specific age group
    python3 scripts/generate_content_matrix.py --dry-run           # Show plan only
    python3 scripts/generate_content_matrix.py --stats             # Show progress
"""

import argparse
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
from typing import Any, Dict, List, Optional, Tuple

# Add parent dir to path so we can import app modules
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env", override=True)

import anthropic

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None

from app.services.ai.prompts import (
    AGE_GROUP_INSTRUCTIONS,
    INFANT_SONG_SYSTEM_PROMPT,
    LONG_STORY_PHASE_INSTRUCTIONS,
    POEM_SYSTEM_PROMPT,
    SAFETY_GUIDELINES,
    SONG_SYSTEM_PROMPT,
    STORY_SYSTEM_PROMPT,
    get_age_group_instructions,
    get_theme_instructions,
)

# ── Paths ──────────────────────────────────────────────────────────────

OUTPUT_PATH = BASE_DIR / "seed_output" / "content_expanded.json"
REPORT_PATH = BASE_DIR / "seed_output" / "generation_report.json"

# ── Logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# CONTENT MATRIX DEFINITION
# ═══════════════════════════════════════════════════════════════════════

AGE_GROUPS = {
    "0-1": {"age_min": 0, "age_max": 1, "target_age": 0, "label": "Baby"},
    "2-5": {"age_min": 2, "age_max": 5, "target_age": 3, "label": "Preschool"},
    "6-8": {"age_min": 6, "age_max": 8, "target_age": 7, "label": "Explorer"},
    "9-12": {"age_min": 9, "age_max": 12, "target_age": 10, "label": "Adventurer"},
}

# Themes available per age group
THEMES_BY_AGE = {
    "0-1": ["bedtime", "animals", "nature", "family", "ocean"],
    "2-5": ["bedtime", "animals", "nature", "family", "fantasy", "adventure", "space"],
    "6-8": ["animals", "nature", "fantasy", "adventure", "friendship", "space"],
    "9-12": ["nature", "fantasy", "adventure", "friendship", "space", "mystery", "science"],
}

# Lengths available per age group
LENGTHS_BY_AGE = {
    "0-1": ["SHORT", "MEDIUM"],
    "2-5": ["SHORT", "MEDIUM", "LONG"],
    "6-8": ["SHORT", "MEDIUM", "LONG"],
    "9-12": ["SHORT", "MEDIUM", "LONG"],
}

# Word count ranges: (age_group, content_type, length) -> (min, max)
WORD_COUNTS = {
    # Stories
    ("0-1", "story", "SHORT"): (30, 60),
    ("0-1", "story", "MEDIUM"): (60, 120),
    ("2-5", "story", "SHORT"): (60, 250),
    ("2-5", "story", "MEDIUM"): (120, 500),
    ("2-5", "story", "LONG"): (1000, 1600),   # ~12-18 min audio with phase-based TTS
    ("6-8", "story", "SHORT"): (200, 400),
    ("6-8", "story", "MEDIUM"): (400, 700),
    ("6-8", "story", "LONG"): (1400, 2200),   # ~15-22 min audio with phase-based TTS
    ("9-12", "story", "SHORT"): (300, 500),
    ("9-12", "story", "MEDIUM"): (500, 900),
    ("9-12", "story", "LONG"): (1800, 3000),  # ~18-28 min audio with phase-based TTS
    # Poems
    ("0-1", "poem", "SHORT"): (20, 40),
    ("0-1", "poem", "MEDIUM"): (40, 70),
    ("2-5", "poem", "SHORT"): (30, 80),
    ("2-5", "poem", "MEDIUM"): (60, 130),
    ("2-5", "poem", "LONG"): (130, 200),
    ("6-8", "poem", "SHORT"): (60, 100),
    ("6-8", "poem", "MEDIUM"): (100, 180),
    ("6-8", "poem", "LONG"): (180, 300),
    ("9-12", "poem", "SHORT"): (80, 130),
    ("9-12", "poem", "MEDIUM"): (130, 220),
    ("9-12", "poem", "LONG"): (220, 400),
    # Songs (Lullabies) — only for ages 0-5 (per LULLABY_GENERATION_GUIDELINES.md)
    ("0-1", "song", "SHORT"): (30, 60),
    ("0-1", "song", "MEDIUM"): (50, 100),
    ("2-5", "song", "SHORT"): (50, 100),
    ("2-5", "song", "MEDIUM"): (80, 150),
    ("2-5", "song", "LONG"): (120, 200),
}

# ═══════════════════════════════════════════════════════════════════════
# DIVERSITY DIMENSIONS
# ═══════════════════════════════════════════════════════════════════════

UNIVERSES = [
    "contemporary",    # modern day
    "historical",      # ancient civilizations, medieval
    "futuristic",      # space stations, robot cities
    "mythological",    # Indian mythology, Greek myths, African folklore
    "fantasy_realm",   # enchanted forests, underwater kingdoms
    "prehistoric",     # dinosaur era, ancient oceans
]

GEOGRAPHIES = [
    "India",           # villages, mountains, coasts
    "East Asia",       # Japan, China
    "Africa",          # savannas, rainforests
    "Europe",          # countryside, castles
    "Americas",        # prairies, jungles
    "Arctic/Polar",    # ice lands, northern lights
    "Ocean/Islands",   # tropical islands, coral reefs
]

PLOT_ARCHETYPES = [
    "quest_journey",       # character goes somewhere, learns something
    "discovery",           # character finds something unexpected
    "friendship_bonding",  # characters connect and help each other
    "transformation",      # character grows or changes
    "problem_solving",     # character faces a challenge, works it out
    "celebration",         # character appreciates what they have
]

LIFE_ASPECTS_BY_AGE = {
    "0-1": ["sleep_comfort", "family_home"],
    "2-5": ["sleep_comfort", "family_home", "play_discovery", "friendship", "school_learning"],
    "6-8": ["friendship", "school_learning", "hobbies_passions", "health_wellness", "family_home"],
    "9-12": ["friendship", "school_learning", "hobbies_passions", "dreams_ambitions", "relationships", "self_identity", "health_wellness"],
}

# Lead gender distribution (mixed pool - all stories work for everyone)
LEAD_GENDERS = ["male", "female", "neutral"]
LEAD_GENDER_WEIGHTS = [0.40, 0.40, 0.20]

# Lead character entity types — for diversity beyond human characters
# Each entry: (type_key, label, examples)
LEAD_CHARACTER_TYPES = [
    ("human",       "Human Child/Teen"),
    ("animal",      "Animal (land)"),
    ("bird",        "Bird"),
    ("sea_creature","Sea/River Creature"),
    ("insect",      "Insect/Bug"),
    ("plant",       "Plant/Flower/Tree"),
    ("celestial",   "Celestial Body (star, moon, planet, comet)"),
    ("atmospheric", "Weather/Atmospheric Entity (snowflake, raindrop, cloud, wave, breeze)"),
    ("mythical",    "Mythical Creature (dragon, phoenix, unicorn, fairy)"),
    ("object",      "Everyday Object (lantern, teacup, kite, music box, umbrella)"),
    ("alien",       "Alien/Extraterrestrial Being"),
    ("robot",       "Robot/AI/Machine"),
]

# Weights: humans ~35%, animals/nature ~40%, fantastical ~25%
LEAD_CHARACTER_TYPE_WEIGHTS = [
    0.30,   # human
    0.12,   # animal
    0.06,   # bird
    0.06,   # sea_creature
    0.04,   # insect
    0.06,   # plant
    0.06,   # celestial
    0.06,   # atmospheric
    0.06,   # mythical
    0.06,   # object
    0.06,   # alien
    0.06,   # robot
]

# Character examples per entity type (name, species_desc, setting)
# Used when the CHARACTER_BANK runs out or for fresh diversity
CHARACTER_TYPE_EXAMPLES = {
    "human":        [("Aria", "girl", "a magical playground"), ("Leo", "boy", "a treehouse"),
                     ("Priya", "girl", "a village in India"), ("Kai", "boy", "a beach town")],
    "animal":       [("Rusty", "fox", "an autumn forest"), ("Stripe", "tiger cub", "a bamboo grove"),
                     ("Pebble", "tortoise", "a sunny riverbank"), ("Maple", "deer", "a misty meadow")],
    "bird":         [("Feather", "hummingbird", "a tropical garden"), ("Whistle", "robin", "a snowy branch"),
                     ("Sky", "eagle chick", "a mountain cliff"), ("Koel", "cuckoo", "a mango orchard")],
    "sea_creature": [("Coral", "seahorse", "a coral reef"), ("Pearl", "baby whale", "the deep ocean"),
                     ("Finn", "dolphin", "a lagoon"), ("Ripple", "otter", "a mountain stream")],
    "insect":       [("Flicker", "firefly", "a summer meadow"), ("Honey", "bee", "a wildflower field"),
                     ("Dot", "ladybug", "a vegetable garden"), ("Silk", "caterpillar", "a mulberry tree")],
    "plant":        [("Sunny", "sunflower", "a meadow"), ("Bloom", "lotus", "a temple pond"),
                     ("Oakley", "young oak tree", "a forest clearing"), ("Moss", "fern", "a rainforest floor")],
    "celestial":    [("Nova", "little star", "the night sky"), ("Crescent", "young moon", "above the clouds"),
                     ("Comet", "wandering comet", "the solar system"), ("Mars", "small red planet", "outer space")],
    "atmospheric":  [("Flurry", "snowflake", "a winter sky"), ("Drizzle", "raindrop", "a monsoon cloud"),
                     ("Gust", "playful breeze", "a hilltop"), ("Wavelet", "ocean wave", "the shoreline")],
    "mythical":     [("Ember", "baby dragon", "a volcanic island"), ("Shimmer", "unicorn", "a rainbow valley"),
                     ("Phoenix", "young phoenix", "the edge of sunrise"), ("Nixie", "water sprite", "a hidden lake")],
    "object":       [("Glow", "old lantern", "an attic shelf"), ("Chai", "teacup", "a cozy kitchen"),
                     ("Kite", "paper kite", "a windy hilltop"), ("Tick", "pocket watch", "a grandfather's desk")],
    "alien":        [("Zib", "friendly alien", "a purple moon"), ("Orla", "three-eyed space traveler", "a crystal planet"),
                     ("Bloop", "jelly-like alien", "a floating space garden"), ("Pip", "tiny alien", "inside a meteor")],
    "robot":        [("Bolt", "toy robot", "a child's playroom"), ("Sparks", "garden robot", "an overgrown greenhouse"),
                     ("Echo", "music robot", "a sound workshop"), ("Widget", "tiny repair bot", "a space station")],
}

# ── Character banks per age group ──────────────────────────────────────

CHARACTER_BANK = {
    "0-1": [
        ("Bunny", "bunny", "a moonlit meadow"), ("Kitten", "kitten", "a cozy blanket"),
        ("Owl", "baby owl", "a tall tree"), ("Star", "little star", "the night sky"),
        ("Cloud", "fluffy cloud", "above the rooftops"), ("Duckling", "duckling", "a pond"),
        ("Lamb", "little lamb", "a green hill"), ("Bear Cub", "bear cub", "a warm den"),
        ("Butterfly", "butterfly", "a flower garden"), ("Moonbeam", "moonbeam", "a bedroom window"),
    ],
    "2-5": [
        ("Milo", "puppy", "a friendly neighborhood"), ("Lily", "kitten", "a flower garden"),
        ("Bubbles", "goldfish", "a coral pond"), ("Pepper", "ladybug", "a vegetable patch"),
        ("Sunny", "sunflower", "a meadow"), ("Whiskers", "mouse", "a cozy kitchen"),
        ("Tinker", "toy robot", "a playroom"), ("Maple", "squirrel", "an oak tree"),
        ("Puddle", "frog", "a rainy day"), ("Cookie", "teddy bear", "a child's bedroom"),
        ("Breezy", "bluebird", "a backyard"), ("Nutmeg", "hamster", "a cozy cage"),
        ("Aria", "girl (age 5)", "a magical playground"), ("Leo", "boy (age 4)", "a treehouse"),
        ("Pip", "baby dragon", "a cloud kingdom"), ("Zara", "girl (age 5)", "an enchanted garden"),
        ("Finn", "boy (age 4)", "a pirate cove"), ("Sparkle", "unicorn", "a rainbow valley"),
        ("Maya", "girl (age 5)", "a village in India"), ("Kai", "boy (age 5)", "a beach town"),
        ("Luna", "fairy", "a mushroom forest"), ("Rex", "friendly dinosaur", "a prehistoric jungle"),
        ("Nisha", "girl (age 4)", "a festival in Kerala"), ("Coco", "parrot", "a tropical island"),
        ("Hugo", "boy (age 5)", "a snow mountain"), ("Twinkle", "star child", "outer space"),
        ("Suki", "girl (age 4)", "a Japanese garden"),
    ],
    "6-8": [
        ("Aarav", "boy (age 7)", "a bustling Mumbai street"), ("Meera", "girl (age 8)", "the Himalayan foothills"),
        ("Oliver", "boy (age 7)", "a castle in Scotland"), ("Yuki", "girl (age 6)", "snowy Hokkaido"),
        ("Kofi", "boy (age 8)", "the Ghanaian savanna"), ("Isla", "girl (age 7)", "a lighthouse island"),
        ("Ravi", "boy (age 6)", "a Rajasthani desert"), ("Amara", "girl (age 8)", "an African rainforest"),
        ("Theo", "boy (age 7)", "a European countryside"), ("Priya", "girl (age 7)", "a Kerala backwater"),
        ("Max", "boy (age 8)", "a space station"), ("Anaya", "girl (age 6)", "an underwater kingdom"),
        ("Sam", "non-binary child (age 7)", "a magical library"), ("Lakshmi", "girl (age 8)", "ancient Varanasi"),
        ("Diego", "boy (age 7)", "a Mexican rainforest"), ("Emi", "girl (age 6)", "a futuristic Tokyo"),
        ("Atlas", "shape-shifting fox", "a mythical forest"), ("Noor", "girl (age 8)", "a Mughal garden"),
    ],
    "9-12": [
        ("Advait", "boy (age 10)", "a Ladakh monastery"), ("Zara", "girl (age 11)", "a Moroccan medina"),
        ("Ethan", "boy (age 9)", "a NASA space center"), ("Kavya", "girl (age 12)", "a temple in Tamil Nadu"),
        ("Chen", "boy (age 10)", "a village in Yunnan"), ("Iris", "girl (age 9)", "an Icelandic glacier"),
        ("Vikram", "boy (age 11)", "a warrior's training ground"), ("Lila", "girl (age 10)", "a Victorian London"),
        ("Ash", "non-binary child (age 11)", "a cyberpunk city"), ("Nyala", "girl (age 12)", "a Kenyan wildlife reserve"),
        ("Rohan", "boy (age 10)", "a Maratha hill fort"), ("Saoirse", "girl (age 9)", "an Irish cliffside"),
        ("Aiden", "boy (age 12)", "a submarine in the Mariana Trench"), ("Mei", "girl (age 11)", "ancient Silk Road"),
        ("Kian", "boy (age 9)", "a Persian palace"), ("Tara", "girl (age 10)", "a Tibetan plateau"),
        ("Phoenix", "mythical bird", "between worlds"), ("Sage", "young inventor (age 11)", "a secret lab"),
        ("Arjun", "boy (age 12)", "a Varanasi ghaat at dawn"), ("Zoya", "girl (age 12)", "a Silk Route caravan"),
        ("Aisha", "girl (age 12)", "a bustling Istanbul bazaar"), ("Neel", "boy (age 12)", "a Bengal tiger reserve"),
        ("Sofia", "girl (age 11)", "a Patagonian glacier"), ("Ananya", "girl (age 12)", "an ISRO mission control"),
        ("Leela", "girl (age 12)", "a Kathakali stage in Kerala"), ("Nova", "non-binary child (age 12)", "a space colony"),
    ],
}

# ── Music profile mapping ──────────────────────────────────────────────

THEME_MUSIC_MAP = {
    "dreamy": ["dreamy-clouds", "starlight-lullaby"],
    "adventure": ["enchanted-garden", "autumn-forest"],
    "fantasy": ["enchanted-garden", "moonlit-meadow"],
    "fairy_tale": ["moonlit-meadow", "starlight-lullaby"],
    "space": ["cosmic-voyage"],
    "animals": ["forest-night", "autumn-forest"],
    "nature": ["forest-night", "moonlit-meadow"],
    "ocean": ["ocean-drift"],
    "bedtime": ["starlight-lullaby", "dreamy-clouds"],
    "family": ["dreamy-clouds", "moonlit-meadow"],
    "friendship": ["enchanted-garden", "autumn-forest"],
    "mystery": ["moonlit-meadow", "autumn-forest"],
    "science": ["cosmic-voyage", "enchanted-garden"],
}

ALL_PROFILES = [
    "dreamy-clouds", "forest-night", "moonlit-meadow", "cosmic-voyage",
    "enchanted-garden", "starlight-lullaby", "autumn-forest", "ocean-drift",
]


def pick_music_profile(theme: str) -> str:
    candidates = THEME_MUSIC_MAP.get(theme, ALL_PROFILES)
    return random.choice(candidates)


# ═══════════════════════════════════════════════════════════════════════
# PLAN BUILDER
# ═══════════════════════════════════════════════════════════════════════

def build_generation_plan(lang_filter: Optional[str] = None,
                          age_filter: Optional[str] = None) -> List[Dict]:
    """Build the full list of content pieces to generate."""
    plan = []
    languages = ["en", "hi"] if not lang_filter else [lang_filter]

    for lang in languages:
        for age_group, ag_info in AGE_GROUPS.items():
            if age_filter and age_group != age_filter:
                continue

            themes = THEMES_BY_AGE[age_group]
            lengths = LENGTHS_BY_AGE[age_group]
            life_aspects = LIFE_ASPECTS_BY_AGE[age_group]
            characters = list(CHARACTER_BANK.get(age_group, []))

            # Build story pieces — distribute across themes and lengths
            story_pieces = []
            for i, theme in enumerate(themes):
                # Each theme gets a SHORT story + a MEDIUM story.
                # If LONG available, some themes also get a LONG.
                for length in lengths:
                    story_pieces.append({
                        "type": "story",
                        "theme": theme,
                        "length": length,
                    })
            # Trim to target count per age group
            # (some age groups may have more combos than needed)

            # Build poem pieces — one per theme, varying length
            poem_pieces = []
            for i, theme in enumerate(themes):
                length = lengths[i % len(lengths)]
                poem_pieces.append({
                    "type": "poem",
                    "theme": theme,
                    "length": length,
                })

            # Combine and enrich with diversity dimensions
            all_pieces = story_pieces + poem_pieces
            random.shuffle(characters)
            char_idx = 0

            for idx, piece in enumerate(all_pieces):
                # Rotate diversity dimensions
                universe = UNIVERSES[idx % len(UNIVERSES)]
                geography = GEOGRAPHIES[idx % len(GEOGRAPHIES)]
                archetype = PLOT_ARCHETYPES[idx % len(PLOT_ARCHETYPES)]
                life_aspect = life_aspects[idx % len(life_aspects)]
                lead_gender = random.choices(LEAD_GENDERS, weights=LEAD_GENDER_WEIGHTS, k=1)[0]

                # Pick lead character TYPE for entity diversity
                char_type_key = random.choices(
                    [t[0] for t in LEAD_CHARACTER_TYPES],
                    weights=LEAD_CHARACTER_TYPE_WEIGHTS, k=1
                )[0]
                char_type_label = next(t[1] for t in LEAD_CHARACTER_TYPES if t[0] == char_type_key)

                # Pick character — prefer CHARACTER_BANK for familiar names,
                # fall back to CHARACTER_TYPE_EXAMPLES for entity diversity
                if char_type_key == "human" and char_idx < len(characters):
                    # Use age-appropriate human characters from the bank
                    char_name, char_species, char_setting = characters[char_idx]
                    char_idx += 1
                elif char_type_key in CHARACTER_TYPE_EXAMPLES:
                    # Pick from entity-type examples
                    type_chars = CHARACTER_TYPE_EXAMPLES[char_type_key]
                    picked = type_chars[idx % len(type_chars)]
                    char_name, char_species, char_setting = picked
                else:
                    char_name, char_species, char_setting = "a brave child", "child", "a magical place"
                    char_type_key = "human"
                    char_type_label = "Human Child/Teen"

                # Word count range
                wc_key = (age_group, piece["type"], piece["length"])
                min_words, max_words = WORD_COUNTS.get(wc_key, (100, 300))

                plan.append({
                    "lang": lang,
                    "age_group": age_group,
                    "age_min": ag_info["age_min"],
                    "age_max": ag_info["age_max"],
                    "target_age": ag_info["target_age"],
                    "type": piece["type"],
                    "theme": piece["theme"],
                    "length": piece["length"],
                    "min_words": min_words,
                    "max_words": max_words,
                    "universe": universe,
                    "geography": geography,
                    "plot_archetype": archetype,
                    "life_aspect": life_aspect,
                    "lead_gender": lead_gender,
                    "lead_character_type": char_type_key,
                    "lead_character_type_label": char_type_label,
                    "character_name": char_name,
                    "character_species": char_species,
                    "character_setting": char_setting,
                    # Unique cell ID for crash-resume
                    "cell_id": f"{lang}_{age_group}_{piece['theme']}_{piece['type']}_{piece['length']}_{idx}",
                })

    return plan


# ═══════════════════════════════════════════════════════════════════════
# PROMPT BUILDING
# ═══════════════════════════════════════════════════════════════════════

FORMAT_JSON = """
Return ONLY a valid JSON object with these fields (no markdown, no extra text):
{
    "characterType": "main character type (land_mammal, bird, sea_creature, insect, reptile_amphibian, human_child, mythical_creature, object_alive, plant_tree, celestial_weather, robot_mechanical)",
    "setting": "where it happens (forest_woodland, ocean_water, sky_space, mountain_highland, meadow_field, desert_arid, arctic_polar, cozy_indoor, village_town, city_urban, underground_cave, garden_farm, island_tropical, imaginary_surreal, miniature_world)",
    "plotShape": "story structure (journey_destination, discovery_reveal, lost_and_found, helping_someone, building_growing, transformation, gathering_reunion, pure_observation, routine_ritual, cyclical_seasonal)",
    "timeOfDay": "sunset_golden_hour, twilight_blue_hour, deep_night_starlight, late_afternoon, or timeless",
    "weather": "clear_calm, gentle_rain, misty_foggy, snowy, warm_breeze, overcast_grey, stormy_distant, or magical_atmospheric",
    "theme": "curiosity_wonder, courage, kindness, friendship, patience, creativity, belonging, gratitude, letting_go, self_acceptance, gentleness, or rest_stillness",
    "scale": "tiny_intimate, personal, local_adventure, journey, or epic_vast",
    "companion": "solo, duo, group_community, meets_stranger, or character_and_environment",
    "movement": "sleeping_resting, sitting_watching, floating_drifting, walking_wandering, flying_swimming, or building_making",
    "magicType": "glowing_bioluminescent, talking_sentient_world, transformation_metamorphosis, miniaturization, music_sound_magic, weather_magic, dream_imagination_bleed, time_magic, color_magic, or no_magic_realistic",
    "season": "spring, summer, autumn, winter, seasonal_transition, or seasonless_timeless",
    "senseEmphasis": "dominant sense: visual, auditory, tactile, olfactory, or kinesthetic",
    "characterTrait": "shy_quiet, bold_adventurous, dreamy_imaginative, kind_nurturing, clumsy_silly, wise_old_soul, anxious_worried, stubborn_determined, lonely_seeking, or playful_mischievous",
    "title": "The story/poem title",
    "description": "A 2-3 sentence mood hook (max 50 words). Start with something intriguing happening in the world, then show the character being drawn into it. Never mention sleep, bedtime, or relaxation. Never reveal the ending.",
    "text": "The FULL story/poem text with emotion markers. MUST use \\n\\n between paragraphs/stanzas. NEVER use markdown emphasis (*word*, **word**). NEVER use ALL CAPS for sound effects (write 'poof' not 'POOF'). Plain text only.",
    "morals": ["Moral 1", "Moral 2"],
    "categories": ["Category1", "Category2"],
    "character": {
        "name": "The lead character's first name",
        "identity": "Who they are through personality, not appearance (max 15 words, e.g. 'A bold little dreamer who talks to shadows')",
        "special": "Their unique ability or quality that drives the story (max 20 words, e.g. 'She can hear the secret songs that flowers sing at night')",
        "personality_tags": ["Trait1", "Trait2"]
    },
    "cover_context": "1-2 sentence visual scene description for the cover illustration. Describe ONLY the world/scene (NOT the character). Focus on setting, cultural elements, colors, objects, atmosphere, time of day. Example: 'A meadow dusted with vibrant pink and blue gulal powder at golden hour, festive garlands between trees, flower petals floating in warm light'"
}

personality_tags must be exactly 2 warm, aspirational trait words from: Curious, Brave, Gentle, Dreamy, Playful, Kind, Quiet, Wise, Adventurous, Warm, Creative, Patient, Cheerful, Determined, Magical, Peaceful.
"""

HINDI_INSTRUCTION = """
IMPORTANT — HINDI GENERATION:
Write the story in Hindi using BOTH formats:
1. "text" field: Write in informal Hindi Romanized script (Latin letters). Example: "Ek chhota sa jugnu tha jiska naam Flicker tha."
2. "text_devanagari" field: Write the SAME text in Devanagari script. Example: "एक छोटा सा जुगनू था जिसका नाम फ्लिकर था।"

Add "text_devanagari" as an additional field in the JSON response.

The title and description should be in Romanized Hindi (Latin letters).
Cultural references should be authentically Indian/South Asian when appropriate.
Emotion markers like [GENTLE], [SLEEPY] etc. stay in English square brackets in BOTH versions.
"""


# ── Mood configuration (imported from mood_config.py) ─────────────────
from scripts.mood_config import (
    MOOD_PROMPTS, MOOD_POEM_PROMPTS, MOOD_POEM_AGE_NOTES,
    MOOD_LULLABY_PROMPTS, MOOD_SAFETY, get_mood_safety,
    VALID_MOOD_AGES, VALID_MOOD_TYPES, validate_mood_combo,
)


def build_generation_prompt(item: Dict, existing_titles: List[str],
                            recent_fingerprints: List[Dict] = None,
                            catalog_gaps: Dict = None,
                            mood: str = None) -> str:
    """Build a complete prompt for generating one content piece."""

    content_type = item["type"]
    age_group = item["age_group"]
    theme = item["theme"]
    length = item["length"]
    lang = item["lang"]
    min_words = item["min_words"]
    max_words = item["max_words"]

    # Base system prompt
    if content_type == "story":
        base_prompt = STORY_SYSTEM_PROMPT
    elif content_type == "song":
        # Age 0-1 uses infant lullaby prompt (a cappella, nonsense syllables)
        base_prompt = INFANT_SONG_SYSTEM_PROMPT if age_group == "0-1" else SONG_SYSTEM_PROMPT
    else:
        base_prompt = POEM_SYSTEM_PROMPT

    # Age instructions
    age_inst = get_age_group_instructions(age_group)

    # Theme instructions
    theme_inst = get_theme_instructions(theme)

    # Length with exact word count
    length_desc = {
        "SHORT": f"SHORT — between {min_words} and {max_words} words. Brief and focused.",
        "MEDIUM": f"MEDIUM — between {min_words} and {max_words} words. Well-developed.",
        "LONG": f"LONG — between {min_words} and {max_words} words. Rich and immersive.",
    }[length]

    # Character type guidance
    char_type = item.get('lead_character_type', 'human')
    char_type_label = item.get('lead_character_type_label', 'Human Child/Teen')
    char_type_guidance = ""
    if content_type == "poem":
        # Poem-specific character guidance (no "story" language)
        if char_type != "human":
            char_type_guidance = f"- Subject Entity Type: {char_type_label.upper()} — The poem's subject must be a {char_type_label.lower()}, NOT a human. Give it personality and voice through imagery."
        else:
            char_type_guidance = f"- Subject Entity Type: HUMAN — The poem's subject is a human child/teen."
    else:
        if char_type != "human":
            char_type_guidance = f"""- Lead Character Entity Type: {char_type_label.upper()} — The main character must be a {char_type_label.lower()}, NOT a human. Give it personality, emotions, and a voice. The story should be told from its perspective or centered on its journey."""
        else:
            char_type_guidance = f"- Lead Character Entity Type: HUMAN — The main character is a human child/teen."

    # Diversity instructions — new fingerprint-based system + character guidance
    from scripts.diversity import build_diversity_prompt
    if recent_fingerprints is not None:
        diversity_block = build_diversity_prompt(recent_fingerprints[-5:], catalog_gaps or {})
    else:
        diversity_block = ""

    gender_line = ""
    if item.get("lead_gender") and item["lead_gender"] != "neutral":
        gender_line = f"- Lead character gender: {item['lead_gender']}"

    diversity = f"""
{char_type_guidance}
{gender_line}
{diversity_block}
"""

    # Anti-duplication
    avoid = ""
    if existing_titles:
        titles_str = ", ".join(f'"{t}"' for t in existing_titles[-10:])
        avoid = f"\nTitles already used (yours MUST be different): {titles_str}\n"

    # For 0-1 lullabies: show recent syllable patterns so the LLM avoids them
    if content_type == "song" and age_group == "0-1" and recent_fingerprints:
        recent_songs = [s for s in recent_fingerprints
                        if s.get("type") == "song" and s.get("age_group") == "0-1"]
        if recent_songs:
            lines = []
            for s in recent_songs[-3:]:
                # Extract first 2 lines to show the syllable pattern
                text = s.get("text", "")
                text_lines = [l.strip() for l in text.split("\n")
                              if l.strip() and not l.strip().startswith("[")]
                snippet = " / ".join(text_lines[:2]) if text_lines else ""
                if snippet:
                    lines.append(f'  - "{snippet}"')
            if lines:
                avoid += "\nRECENT LULLABY PATTERNS (yours MUST use completely different syllable combinations):\n"
                avoid += "\n".join(lines) + "\n"

    # Hindi
    hindi_block = HINDI_INSTRUCTION if lang == "hi" else ""

    # Phase structuring for LONG stories — age-specific [PHASE_1]...[/PHASE_3] tags
    phase_instructions = ""
    phase_word_budget = ""
    if length == "LONG" and content_type == "story":
        phase_instructions = LONG_STORY_PHASE_INSTRUCTIONS.get(age_group, LONG_STORY_PHASE_INSTRUCTIONS["2-5"])
        # Per-phase word count targets help the model budget its output
        # (models are bad at hitting high total word counts without phase guidance)
        phase_pcts = {
            "2-5":  {"p1": (0.30, 0.35), "p2": (0.35, 0.40), "p3": (0.25, 0.30)},
            "6-8":  {"p1": (0.30, 0.35), "p2": (0.35, 0.40), "p3": (0.25, 0.30)},
            "9-12": {"p1": (0.25, 0.30), "p2": (0.35, 0.40), "p3": (0.30, 0.40)},
        }.get(age_group, {"p1": (0.30, 0.35), "p2": (0.35, 0.40), "p3": (0.25, 0.30)})
        p1_min = int(min_words * phase_pcts["p1"][0])
        p1_max = int(max_words * phase_pcts["p1"][1])
        p2_min = int(min_words * phase_pcts["p2"][0])
        p2_max = int(max_words * phase_pcts["p2"][1])
        p3_min = int(min_words * phase_pcts["p3"][0])
        p3_max = int(max_words * phase_pcts["p3"][1])
        phase_word_budget = f"""
CRITICAL — WORD COUNT PER PHASE (you MUST hit these targets):
- Phase 1: {p1_min}-{p1_max} words
- Phase 2: {p2_min}-{p2_max} words
- Phase 3: {p3_min}-{p3_max} words
- TOTAL: {min_words}-{max_words} words

This is a LONG bedtime story. Write a FULL, LENGTHY, richly detailed narrative.
Do NOT abbreviate, summarize, or write a short version. Each phase must be substantial.
"""

    # Mood instruction (experimental)
    mood_block = ""
    if mood:
        if content_type == "song":
            # Lullaby mood prompts
            lullaby_moods = MOOD_LULLABY_PROMPTS.get(mood, {})
            mood_block = lullaby_moods.get(age_group, "")
        elif content_type == "poem":
            mood_block = MOOD_POEM_PROMPTS.get(mood, "")
            # Add age-specific poem note
            poem_age_note = MOOD_POEM_AGE_NOTES.get(age_group, "")
            if poem_age_note:
                mood_block += f"\nAGE-SPECIFIC POEM RULE: {poem_age_note}\n"
        else:
            # Story / long_story
            age_moods = MOOD_PROMPTS.get(mood, {})
            mood_block = age_moods.get(age_group, age_moods.get("6-8", ""))

        # Append mood-specific safety guidelines for sad/anxious/angry
        safety_text = get_mood_safety(mood, age_group)
        if safety_text:
            mood_block += f"\n{safety_text}\n"

    prompt = f"""{base_prompt}

{age_inst}

{theme_inst}

LENGTH: {length_desc}
{phase_instructions}
{phase_word_budget}
{diversity}
{mood_block}
{avoid}
{SAFETY_GUIDELINES}

{hindi_block}

{FORMAT_JSON}

Now generate a {content_type} following ALL the above instructions. Return ONLY the JSON object."""

    return prompt.strip()


# ═══════════════════════════════════════════════════════════════════════
# GENERATION ENGINE
# ═══════════════════════════════════════════════════════════════════════

def load_existing() -> List[Dict]:
    """Load existing generated content for crash-resume."""
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Could not load existing content: %s", e)
    return []


def save_content(content: List[Dict]):
    """Save content to JSON file."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_json_response(text: str) -> Optional[Dict]:
    """Extract JSON from LLM response, handling markdown code fences."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("```"):
        # Remove markdown code fences
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def ensure_paragraph_breaks(text: str, content_type: str = "story") -> str:
    """Ensure text has paragraph breaks for readability.

    If the text has fewer than 2 paragraph breaks (double newlines) and is longer
    than 200 chars, insert breaks at emotion marker boundaries. This fixes LLM
    responses that produce one continuous block of text.
    """
    if not text:
        return text
    # Already has good paragraph structure
    if text.count("\n\n") >= 2:
        return text
    # Short text doesn't need breaks
    if len(text) < 200:
        return text

    if content_type == "poem":
        # For poems: break at [PAUSE] markers or [RHYTHMIC] markers
        text = re.sub(r"\s*\[PAUSE\]\s*", "\n\n", text)
        # If still no breaks, split at [RHYTHMIC]
        if text.count("\n\n") < 2:
            text = re.sub(r"\s+(\[RHYTHMIC\])", r"\n\n\1", text)
    else:
        # For stories: break before emotion markers that start new beats
        # Pattern: insert \n\n before [MARKER] when preceded by sentence-ending punctuation
        markers = r"\[(?:GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|JOYFUL|SLEEPY|DRAMATIC|WHISPERING|DRAMATIC_PAUSE)\]"
        # Split at emotion markers that follow sentence endings
        parts = re.split(rf'(\s+)({markers})', text)
        if len(parts) > 3:
            # Rejoin with paragraph breaks every 2-4 markers
            result = []
            marker_count = 0
            for part in parts:
                if re.match(markers, part):
                    marker_count += 1
                    # Insert paragraph break every 2-3 markers
                    if marker_count > 1 and marker_count % 3 == 1:
                        result.append("\n\n")
                    result.append(part)
                elif part.strip() == "":
                    # Skip whitespace-only parts between markers (we add our own breaks)
                    if not result or not result[-1].endswith("\n\n"):
                        result.append(" ")
                else:
                    result.append(part)
            text = "".join(result).strip()

        # If still no breaks, force them every ~3 sentences
        if text.count("\n\n") < 2:
            sentences = re.split(r'(?<=[.!?])\s+', text)
            if len(sentences) >= 4:
                chunk_size = max(2, len(sentences) // 4)
                chunks = []
                for i in range(0, len(sentences), chunk_size):
                    chunks.append(" ".join(sentences[i:i+chunk_size]))
                text = "\n\n".join(chunks)

    return text.strip()


def count_words(text: str) -> int:
    """Count words, ignoring emotion markers."""
    clean = re.sub(r"\[[\w_]+\]", "", text)
    return len(clean.split())


def _call_claude(client: anthropic.Anthropic, prompt: str, max_tokens: int,
                 model: str = "claude-sonnet-4-20250514") -> Optional[str]:
    """Call Anthropic Claude API with rate-limit awareness.

    Handles rate limiting with exponential backoff.
    Returns raw response text or None.
    """
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system="You are a creative bedtime story generator. Return ONLY valid JSON. No markdown fences, no extra text.",
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
            )
            # Extract text from response
            text_blocks = [block.text for block in response.content if block.type == "text"]
            return "\n".join(text_blocks).strip() if text_blocks else None
        except anthropic.RateLimitError as e:
            wait_secs = min(2 ** (attempt + 1) * 5, 120)  # 10s, 20s, 40s, 80s, 120s
            logger.warning("  Rate limited (attempt %d/%d). Waiting %d seconds...",
                           attempt + 1, max_retries, wait_secs)
            time.sleep(wait_secs)
            continue
        except anthropic.APIStatusError as e:
            if e.status_code == 529:  # Overloaded
                wait_secs = min(2 ** (attempt + 1) * 10, 180)
                logger.warning("  API overloaded (attempt %d/%d). Waiting %d seconds...",
                               attempt + 1, max_retries, wait_secs)
                time.sleep(wait_secs)
                continue
            else:
                raise
        except Exception as e:
            logger.error("  Claude API error: %s", e)
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            raise
    return None


def _call_groq(client, prompt: str, max_tokens: int,
               model: str = "llama-3.3-70b-versatile") -> Optional[str]:
    """Call Groq API with rate-limit awareness."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a creative bedtime story generator. Return ONLY valid JSON. No markdown fences, no extra text."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
            )
            return response.choices[0].message.content.strip() if response.choices else None
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "limit" in err_str or "429" in err_str:
                wait_secs = min(2 ** (attempt + 1) * 5, 120)
                logger.warning("  Groq rate limited (attempt %d/%d). Waiting %d seconds...",
                               attempt + 1, max_retries, wait_secs)
                time.sleep(wait_secs)
                continue
            elif "503" in err_str or "overloaded" in err_str:
                wait_secs = min(2 ** (attempt + 1) * 10, 180)
                logger.warning("  Groq overloaded (attempt %d/%d). Waiting %d seconds...",
                               attempt + 1, max_retries, wait_secs)
                time.sleep(wait_secs)
                continue
            else:
                logger.error("  Groq API error: %s", e)
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise
    return None


def _call_mistral(client, prompt: str, max_tokens: int,
                  model: str = "mistral-large-latest") -> Optional[str]:
    """Call Mistral AI API with rate-limit awareness.

    Free experiment tier: 2 req/min, 500K tokens/min, 1B tokens/month.
    We add a small delay between calls to stay within limits.
    """
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a creative bedtime story generator. Return ONLY valid JSON. No markdown fences, no extra text."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
                response_format={"type": "json_object"},
            )
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
            return None
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "limit" in err_str or "429" in err_str:
                wait_secs = min(2 ** (attempt + 1) * 15, 180)  # Longer waits for 2 req/min limit
                logger.warning("  Mistral rate limited (attempt %d/%d). Waiting %d seconds...",
                               attempt + 1, max_retries, wait_secs)
                time.sleep(wait_secs)
                continue
            elif "503" in err_str or "overloaded" in err_str:
                wait_secs = min(2 ** (attempt + 1) * 10, 180)
                logger.warning("  Mistral overloaded (attempt %d/%d). Waiting %d seconds...",
                               attempt + 1, max_retries, wait_secs)
                time.sleep(wait_secs)
                continue
            else:
                logger.error("  Mistral API error: %s", e)
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise
    return None


def generate_one(client, item: Dict, existing_titles: List[str],
                 max_retries: int = 3, api: str = "claude",
                 recent_fingerprints: List[Dict] = None,
                 catalog_gaps: Dict = None,
                 mood: str = None) -> Optional[Dict]:
    """Generate a single content piece via Claude or Groq API."""

    # Poems are trickier (stanza structure, word count variability) — more attempts
    if item.get("type") == "poem":
        max_retries = max(max_retries, 5)
    # LONG stories need more attempts — models struggle with high word counts
    if item.get("length") == "LONG" and item.get("type") == "story":
        max_retries = max(max_retries, 5)

    prompt = build_generation_prompt(item, existing_titles,
                                     recent_fingerprints=recent_fingerprints,
                                     catalog_gaps=catalog_gaps,
                                     mood=mood)

    # Determine max_tokens based on word count range
    # LONG stories (up to 3000 words) need ~12K+ tokens — raise cap to 16384
    max_tokens = min(16384, max(1024, item["max_words"] * 4))

    # Mistral free tier = 2 req/min — need longer waits between retries
    retry_delay = 35 if api == "mistral" else 2

    for attempt in range(max_retries):
        try:
            if api == "mistral":
                raw = _call_mistral(client, prompt, max_tokens)
            elif api == "groq":
                raw = _call_groq(client, prompt, max_tokens)
            else:
                raw = _call_claude(client, prompt, max_tokens)
            if not raw:
                logger.warning("  Attempt %d: No response from API", attempt + 1)
                time.sleep(retry_delay)
                continue

            parsed = parse_json_response(raw)

            if not parsed:
                logger.warning("  Attempt %d: Failed to parse JSON", attempt + 1)
                time.sleep(retry_delay)
                continue

            # Extract and validate diversity fingerprint from LLM output
            from scripts.diversity import (DIMENSION_NAMES, validate_fingerprint,
                                           check_hard_rules, check_collision)
            raw_fp = {}
            for dim in DIMENSION_NAMES:
                val = parsed.pop(dim, None)
                if val:
                    raw_fp[dim] = val
            fingerprint = validate_fingerprint(raw_fp) if raw_fp else None

            # Collision check against recent stories
            if fingerprint and recent_fingerprints:
                passes_hard, violations = check_hard_rules(fingerprint, recent_fingerprints)
                if not passes_hard and attempt < max_retries - 1:
                    logger.warning("  Attempt %d: Hard rule violation: %s — retrying",
                                   attempt + 1, "; ".join(violations[:3]))
                    time.sleep(retry_delay)
                    continue

                passes_soft, details = check_collision(fingerprint, recent_fingerprints)
                if not passes_soft and attempt < max_retries - 1:
                    logger.warning("  Attempt %d: Collision score %d (threshold 18) — retrying",
                                   attempt + 1, details["score"])
                    time.sleep(retry_delay)
                    continue

                if not passes_hard or not passes_soft:
                    logger.warning("  Accepting on final attempt despite diversity collision")

            title = parsed.get("title", "").strip()
            text = parsed.get("text", parsed.get("content", "")).strip()
            description = parsed.get("description", "").strip()
            morals = parsed.get("morals", [])
            categories = parsed.get("categories", [])
            text_devanagari = parsed.get("text_devanagari", "").strip()

            if not title or not text:
                logger.warning("  Attempt %d: Missing title or text", attempt + 1)
                time.sleep(retry_delay)
                continue

            # Ensure paragraph breaks for readability
            text = ensure_paragraph_breaks(text, item["type"])
            if text_devanagari:
                text_devanagari = ensure_paragraph_breaks(text_devanagari, item["type"])

            # Validate phase markers for LONG stories
            if item["length"] == "LONG" and item["type"] == "story":
                if "[PHASE_1]" not in text or "[/PHASE_3]" not in text:
                    logger.warning("  Attempt %d: LONG story missing phase markers, retrying...",
                                   attempt + 1)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    # Accept on last attempt anyway (will fall back to legacy audio flow)
                    logger.warning("  Accepting unphased LONG story on final attempt")

            # Validate word count
            wc = count_words(text)
            # Poems get wider tolerance (stanza structure makes word counts variable)
            if item["type"] == "poem":
                min_ok = int(item["min_words"] * 0.5)
                max_ok = int(item["max_words"] * 1.5)
            else:
                min_ok = int(item["min_words"] * 0.7)
                max_ok = int(item["max_words"] * 1.3)
            if wc < min_ok or wc > max_ok:
                logger.warning("  Attempt %d: Word count %d outside range [%d-%d]",
                               attempt + 1, wc, item["min_words"], item["max_words"])
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                # Accept on last attempt anyway
                logger.warning("  Accepting anyway on final attempt")

            # Check for duplicate title
            if title.lower() in [t.lower() for t in existing_titles]:
                logger.warning("  Attempt %d: Duplicate title '%s'", attempt + 1, title)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue

            # Build content object
            content_id = f"gen-{uuid.uuid4().hex[:12]}"
            now = datetime.utcnow().isoformat()

            # LONG stories use type "long_story" for frontend section placement
            content_type = item["type"]
            if item["length"] == "LONG" and content_type == "story":
                content_type = "long_story"

            # Strip phase markers from display text; keep in annotated_text for TTS
            display_text = text
            if "[PHASE_1]" in text:
                display_text = re.sub(r'\[/?PHASE_\d+\]', '', text).strip()
                display_text = re.sub(r'\n{3,}', '\n\n', display_text)

            content_obj = {
                "id": content_id,
                "type": content_type,
                "lang": item["lang"],
                "title": title,
                "description": description,
                "text": display_text,
                "annotated_text": text,  # Keeps phase markers for TTS pipeline
                "target_age": item["target_age"],
                "age_min": item["age_min"],
                "age_max": item["age_max"],
                "age_group": item["age_group"],
                "length": item["length"],
                "word_count": wc,
                "duration_seconds": 0,
                "categories": categories,
                "theme": item["theme"],
                "morals": morals,
                "cover": "",
                "musicProfile": pick_music_profile(item["theme"]),
                "music_type": "ambient",
                "audio_variants": [],
                "author_id": "system",
                "is_generated": True,
                "generation_quality": "pending_review",
                "lead_gender": item["lead_gender"],
                "character": parsed.get("character", {"name": "", "identity": "", "special": "", "personality_tags": []}),
                "cover_context": parsed.get("cover_context", ""),
                "lead_character_type": item.get("lead_character_type", "human"),
                "universe": item["universe"],
                "geography": item["geography"],
                "life_aspect": item["life_aspect"],
                "plot_archetype": item["plot_archetype"],
                "diversityFingerprint": fingerprint,
                "mood": mood if mood else None,
                "created_at": now,
                "updated_at": now,
                "view_count": 0,
                "like_count": 0,
                "save_count": 0,
            }

            # Add Hindi Devanagari if available
            if item["lang"] == "hi" and text_devanagari:
                content_obj["annotated_text_devanagari"] = text_devanagari

            return content_obj

        except Exception as e:
            logger.error("  Attempt %d: API error: %s", attempt + 1, e)
            wait = 2 ** (attempt + 1)
            time.sleep(wait)

    return None


# ═══════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════

def show_stats(content: List[Dict]):
    """Show generation progress statistics."""
    print("\n=== Content Generation Stats ===")
    print(f"Total pieces: {len(content)}")

    # By language
    by_lang = {}
    for c in content:
        lang = c.get("lang", "en")
        by_lang[lang] = by_lang.get(lang, 0) + 1
    print(f"\nBy Language:")
    for lang, count in sorted(by_lang.items()):
        print(f"  {lang}: {count}")

    # By age group
    by_age = {}
    for c in content:
        ag = c.get("age_group", "unknown")
        by_age[ag] = by_age.get(ag, 0) + 1
    print(f"\nBy Age Group:")
    for ag in ["0-1", "2-5", "6-8", "9-12"]:
        count = by_age.get(ag, 0)
        print(f"  {ag}: {count}")

    # By type
    by_type = {}
    for c in content:
        t = c.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"\nBy Type:")
    for t, count in sorted(by_type.items()):
        print(f"  {t}: {count}")

    # By quality status
    by_quality = {}
    for c in content:
        q = c.get("generation_quality", "unknown")
        by_quality[q] = by_quality.get(q, 0) + 1
    print(f"\nBy Review Status:")
    for q, count in sorted(by_quality.items()):
        print(f"  {q}: {count}")

    # By theme
    by_theme = {}
    for c in content:
        theme = c.get("theme", "unknown")
        by_theme[theme] = by_theme.get(theme, 0) + 1
    print(f"\nBy Theme:")
    for theme, count in sorted(by_theme.items()):
        print(f"  {theme}: {count}")

    # Gender distribution
    by_gender = {}
    for c in content:
        g = c.get("lead_gender", "unknown")
        by_gender[g] = by_gender.get(g, 0) + 1
    total = max(len(content), 1)
    print(f"\nLead Gender Distribution:")
    for g, count in sorted(by_gender.items()):
        pct = count / total * 100
        print(f"  {g}: {count} ({pct:.0f}%)")

    # Character type distribution
    by_char_type = {}
    for c in content:
        ct = c.get("lead_character_type", "human")
        by_char_type[ct] = by_char_type.get(ct, 0) + 1
    print(f"\nLead Character Type Distribution:")
    for ct, count in sorted(by_char_type.items()):
        pct = count / total * 100
        print(f"  {ct}: {count} ({pct:.0f}%)")

    print()


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def build_fresh_plan(count_stories: int = 1, count_poems: int = 1,
                     count_lullabies: int = 0, count_long_stories: int = 0,
                     lang: str = "en", existing: list = None) -> list:
    """Build a plan for N stories + M poems + L lullabies with full diversity randomization.

    Unlike the matrix-based plan, this generates fresh items regardless
    of what's already been produced. Used by the daily pipeline.

    count_long_stories adds extra stories forced to LONG length (on top of count_stories).
    """
    import random as _rng

    if existing is None:
        existing = []

    plan = []
    age_groups_list = list(AGE_GROUPS.keys())

    all_stories = count_stories + count_long_stories
    total = all_stories + count_poems + count_lullabies
    for i in range(total):
        if i < all_stories:
            content_type = "story"
        elif i < all_stories + count_poems:
            content_type = "poem"
        else:
            content_type = "song"

        # Force LONG for the extra long-story slots
        force_long = (content_type == "story" and i >= count_stories and i < all_stories)

        # Pick random diversity dimensions
        # Lullabies (songs) are only for ages 0-1 and 2-5.
        # Alternate roughly 40% 0-1 / 60% 2-5 to maintain healthy ratio.
        if content_type == "song":
            age_group = _rng.choices(["0-1", "2-5"], weights=[40, 60], k=1)[0]
        else:
            age_group = _rng.choice(age_groups_list)
        ag_info = AGE_GROUPS[age_group]
        themes = THEMES_BY_AGE[age_group]
        lengths = LENGTHS_BY_AGE[age_group]
        life_aspects = LIFE_ASPECTS_BY_AGE[age_group]

        theme = _rng.choice(themes)
        if force_long:
            length = "LONG"
        elif content_type == "story":
            # Regular story slots must NOT be LONG (that's what count_long_stories is for)
            non_long = [l for l in lengths if l != "LONG"]
            length = _rng.choice(non_long) if non_long else lengths[0]
        else:
            length = _rng.choice(lengths)
        universe = _rng.choice(UNIVERSES)
        geography = _rng.choice(GEOGRAPHIES)
        archetype = _rng.choice(PLOT_ARCHETYPES)
        life_aspect = _rng.choice(life_aspects)
        lead_gender = _rng.choices(LEAD_GENDERS, weights=LEAD_GENDER_WEIGHTS, k=1)[0]

        # Character type diversity
        char_type_key = _rng.choices(
            [t[0] for t in LEAD_CHARACTER_TYPES],
            weights=LEAD_CHARACTER_TYPE_WEIGHTS, k=1
        )[0]
        char_type_label = next(t[1] for t in LEAD_CHARACTER_TYPES if t[0] == char_type_key)

        # Pick character
        if char_type_key in CHARACTER_TYPE_EXAMPLES:
            type_chars = CHARACTER_TYPE_EXAMPLES[char_type_key]
            char_name, char_species, char_setting = _rng.choice(type_chars)
        else:
            char_name, char_species, char_setting = "a brave child", "child", "a magical place"

        # Word count range
        wc_key = (age_group, content_type, length)
        min_words, max_words = WORD_COUNTS.get(wc_key, (100, 300))

        plan.append({
            "lang": lang,
            "age_group": age_group,
            "age_min": ag_info["age_min"],
            "age_max": ag_info["age_max"],
            "target_age": ag_info["target_age"],
            "type": content_type,
            "theme": theme,
            "length": length,
            "min_words": min_words,
            "max_words": max_words,
            "universe": universe,
            "geography": geography,
            "plot_archetype": archetype,
            "life_aspect": life_aspect,
            "lead_gender": lead_gender,
            "lead_character_type": char_type_key,
            "lead_character_type_label": char_type_label,
            "character_name": char_name,
            "character_species": char_species,
            "character_setting": char_setting,
            "cell_id": f"{lang}_{age_group}_{theme}_{content_type}_{length}_fresh_{i}",
        })

    return plan


def main():
    parser = argparse.ArgumentParser(description="Generate diversified bedtime content")
    parser.add_argument("--lang", help="Generate for specific language (en/hi)")
    parser.add_argument("--age-group", help="Generate for specific age group (0-1, 1-3, etc.)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    parser.add_argument("--stats", action="store_true", help="Show current progress stats")
    parser.add_argument("--api", choices=["claude", "groq", "mistral"], default="mistral",
                        help="API to use for generation (default: mistral)")
    parser.add_argument("--count-stories", type=int, default=0,
                        help="Generate N fresh stories (bypasses matrix, for daily pipeline)")
    parser.add_argument("--count-poems", type=int, default=0,
                        help="Generate N fresh poems (bypasses matrix, for daily pipeline)")
    parser.add_argument("--count-lullabies", type=int, default=0,
                        help="Generate N fresh lullabies (bypasses matrix, for daily pipeline)")
    parser.add_argument("--count-long-stories", type=int, default=0,
                        help="Generate N additional LONG stories (bypasses matrix, for daily pipeline)")
    parser.add_argument("--mood", choices=["wired", "curious", "calm", "sad", "anxious", "angry"],
                        default=None, help="Target mood for content generation (experimental)")
    parser.add_argument("--age", help="Force specific age group (e.g. 6-8) for --mood runs")
    parser.add_argument("--type", dest="content_type",
                        choices=["story", "long_story", "poem", "song", "all"],
                        default=None,
                        help="Content type to generate (shorthand for --count-* flags, used with --mood)")
    args = parser.parse_args()

    # --type flag sets count flags (convenience for mood runs)
    if args.content_type:
        if args.content_type == "story":
            args.count_stories = max(args.count_stories, 1)
        elif args.content_type == "long_story":
            args.count_long_stories = max(args.count_long_stories, 1)
        elif args.content_type == "poem":
            args.count_poems = max(args.count_poems, 1)
        elif args.content_type == "song":
            args.count_lullabies = max(args.count_lullabies, 1)
        elif args.content_type == "all":
            args.count_stories = max(args.count_stories, 1)
            args.count_poems = max(args.count_poems, 1)
            # Only add lullaby if mood allows it
            if args.mood and "song" in VALID_MOOD_TYPES.get(args.mood, []):
                args.count_lullabies = max(args.count_lullabies, 1)

    # Validate mood × age × type combinations
    if args.mood and args.age:
        # Check each requested type against mood validation
        type_checks = []
        if args.count_stories > 0:
            type_checks.append("story")
        if args.count_long_stories > 0:
            type_checks.append("long_story")
        if args.count_poems > 0:
            type_checks.append("poem")
        if args.count_lullabies > 0:
            type_checks.append("song")

        for ct in type_checks:
            valid, reason = validate_mood_combo(args.mood, args.age, ct)
            if not valid:
                logger.error("Invalid mood combination: %s", reason)
                sys.exit(1)

    # Load existing content
    existing = load_existing()

    if args.stats:
        show_stats(existing)
        return

    # Fresh count mode (for daily pipeline) vs. matrix mode
    use_fresh_mode = args.count_stories > 0 or args.count_poems > 0 or args.count_lullabies > 0 or args.count_long_stories > 0

    if use_fresh_mode:
        lang = args.lang or "en"
        new_plan = build_fresh_plan(
            count_stories=args.count_stories,
            count_poems=args.count_poems,
            count_lullabies=args.count_lullabies,
            count_long_stories=args.count_long_stories,
            lang=lang,
            existing=existing,
        )
        # Force age group when --age is specified (used with --mood)
        if args.age:
            forced_age = args.age
            if forced_age not in AGE_GROUPS:
                logger.error("Invalid age group: %s. Valid: %s", forced_age, list(AGE_GROUPS.keys()))
                sys.exit(1)
            for item in new_plan:
                ag_info = AGE_GROUPS[forced_age]
                item["age_group"] = forced_age
                item["age_min"] = ag_info["age_min"]
                item["age_max"] = ag_info["age_max"]
                item["target_age"] = ag_info["target_age"]
                # Update theme if current one isn't valid for forced age group
                if item["theme"] not in THEMES_BY_AGE[forced_age]:
                    item["theme"] = random.choice(THEMES_BY_AGE[forced_age])
                # Update word counts for forced age group
                wc_key = (forced_age, item["type"], item["length"])
                item["min_words"], item["max_words"] = WORD_COUNTS.get(wc_key, (100, 300))
            logger.info("Forced all items to age group: %s", forced_age)

        logger.info("=== Fresh Generation Plan ===")
        logger.info("Stories: %d, Long stories: %d, Poems: %d, Lullabies: %d, Lang: %s",
                     args.count_stories, args.count_long_stories, args.count_poems, args.count_lullabies, lang)
        if args.mood:
            logger.info("Mood: %s (experimental)", args.mood)
        logger.info("To generate: %d", len(new_plan))
    else:
        # Matrix mode — fill in missing cells
        plan = build_generation_plan(lang_filter=args.lang, age_filter=args.age_group)

        # Find already-generated cell IDs
        existing_cell_ids = set()
        for c in existing:
            # Reconstruct cell_id from existing content
            cell = f"{c.get('lang')}_{c.get('age_group')}_{c.get('theme')}_{c.get('type')}_{c.get('length')}"
            existing_cell_ids.add(cell)

        # Filter plan to only new items (match on lang_age_theme_type_length prefix)
        new_plan = []
        for item in plan:
            prefix = f"{item['lang']}_{item['age_group']}_{item['theme']}_{item['type']}_{item['length']}"
            if prefix not in existing_cell_ids:
                new_plan.append(item)

        logger.info("=== Generation Plan ===")
        logger.info("Total planned: %d", len(plan))
        logger.info("Already generated: %d", len(plan) - len(new_plan))
        logger.info("To generate: %d", len(new_plan))

    if args.dry_run:
        print(f"\n{'Lang':<4} {'Age':<5} {'Theme':<12} {'Type':<6} {'Len':<7} {'Words':<10} {'Universe':<14} {'Geography':<14}")
        print("-" * 85)
        for item in new_plan:
            print(f"{item['lang']:<4} {item['age_group']:<5} {item['theme']:<12} {item['type']:<6} "
                  f"{item['length']:<7} {item['min_words']}-{item['max_words']:<5} "
                  f"{item['universe']:<14} {item['geography']:<14}")
        print(f"\nTotal: {len(new_plan)} pieces to generate")
        return

    if not new_plan:
        logger.info("Nothing to generate. All cells already have content.")
        show_stats(existing)
        return

    # Initialize API client
    if args.api == "mistral":
        if Mistral is None:
            logger.error("mistralai package not installed. Run: pip install mistralai")
            sys.exit(1)
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            logger.error("MISTRAL_API_KEY not set. Check .env file.")
            sys.exit(1)
        client = Mistral(api_key=api_key)
        logger.info("Using Mistral API (mistral-large-latest)")
    elif args.api == "groq":
        if Groq is None:
            logger.error("groq package not installed. Run: pip install groq")
            sys.exit(1)
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.error("GROQ_API_KEY not set. Check .env file.")
            sys.exit(1)
        client = Groq(api_key=api_key)
        logger.info("Using Groq API (llama-3.3-70b-versatile)")
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set. Check .env file.")
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
        logger.info("Using Claude API (claude-sonnet-4-20250514)")

    # Collect existing titles for dedup
    existing_titles = [c.get("title", "") for c in existing]

    # Load diversity fingerprints for collision checking
    from scripts.diversity import load_recent_fingerprints, find_catalog_gaps
    content_json = BASE_DIR / "seed_output" / "content.json"
    recent_fps = load_recent_fingerprints(content_json, days=14)
    catalog_gaps = find_catalog_gaps(content_json)
    logger.info("Diversity: %d recent fingerprints, gaps in %d dimensions",
                len(recent_fps), len(catalog_gaps))

    success = 0
    failed = 0

    for i, item in enumerate(new_plan):
        logger.info(
            "\n[%d/%d] %s | %s | %s | %s | %s | %s",
            i + 1, len(new_plan),
            item["lang"].upper(), item["age_group"],
            item["theme"], item["type"], item["length"],
            item["character_name"],
        )

        result = generate_one(client, item, existing_titles, api=args.api,
                              recent_fingerprints=recent_fps,
                              catalog_gaps=catalog_gaps,
                              mood=args.mood)

        if result:
            existing.append(result)
            existing_titles.append(result["title"])
            # Track new fingerprint for within-batch collision checking
            if result.get("diversityFingerprint"):
                recent_fps.append(result)
            save_content(existing)
            wc = result.get("word_count", 0)
            logger.info("  OK: '%s' (%d words)", result["title"], wc)
            success += 1
        else:
            logger.error("  FAILED [%s] after all retries", item["type"])
            failed += 1

        # Rate limiting: Mistral free tier = 2 req/min, so wait 45s between items
        # (35s was too tight — retries within generate_one can exhaust the quota)
        if args.api == "mistral":
            logger.info("  Waiting 45s for Mistral rate limit (2 req/min)...")
            time.sleep(45)
        else:
            time.sleep(2)

    logger.info("\n=== Generation Complete ===")
    logger.info("Generated: %d, Failed: %d", success, failed)
    show_stats(existing)

    # Save report
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_generated": success,
        "total_failed": failed,
        "total_content": len(existing),
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
