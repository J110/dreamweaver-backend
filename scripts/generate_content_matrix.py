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
    ("2-5", "story", "LONG"): (500, 800),
    ("6-8", "story", "SHORT"): (200, 400),
    ("6-8", "story", "MEDIUM"): (400, 700),
    ("6-8", "story", "LONG"): (700, 1200),
    ("9-12", "story", "SHORT"): (300, 500),
    ("9-12", "story", "MEDIUM"): (500, 900),
    ("9-12", "story", "LONG"): (900, 1500),
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
    # Songs (Lullabies) — shorter lyrics with verse/chorus structure
    ("0-1", "song", "SHORT"): (30, 60),
    ("0-1", "song", "MEDIUM"): (50, 100),
    ("2-5", "song", "SHORT"): (50, 100),
    ("2-5", "song", "MEDIUM"): (80, 150),
    ("2-5", "song", "LONG"): (120, 200),
    ("6-8", "song", "SHORT"): (60, 120),
    ("6-8", "song", "MEDIUM"): (100, 180),
    ("6-8", "song", "LONG"): (150, 250),
    ("9-12", "song", "SHORT"): (80, 140),
    ("9-12", "song", "MEDIUM"): (120, 200),
    ("9-12", "song", "LONG"): (180, 300),
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
    "title": "The story/poem title",
    "description": "A 1-2 sentence summary",
    "text": "The FULL story/poem text with emotion markers. MUST use \\n\\n between paragraphs/stanzas for readability.",
    "morals": ["Moral 1", "Moral 2"],
    "categories": ["Category1", "Category2"]
}
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


def build_generation_prompt(item: Dict, existing_titles: List[str]) -> str:
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
        base_prompt = SONG_SYSTEM_PROMPT
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

    # Diversity instructions — poem-specific vs story/song
    if content_type == "poem":
        diversity = f"""
DIVERSITY REQUIREMENTS — Make this poem UNIQUE:
- Universe/Setting Era: {item['universe'].upper()} — set this poem in a {item['universe']} world
- Geography/Culture: {item['geography']} — draw imagery and metaphors from {item['geography']}
- Life Aspect: {item['life_aspect'].replace('_', ' ')} — weave this theme into the poem's imagery
- Poetic Mood: {item['plot_archetype'].replace('_', ' ').upper()} — use this as the emotional arc
- Subject: {item['character_name']} ({item['character_species']}) in {item['character_setting']}
{char_type_guidance}
- Subject Gender: {'The subject should be {}'.format(item['lead_gender']) if item['lead_gender'] != 'neutral' else 'The subject can be any gender or non-human'}
"""
    else:
        diversity = f"""
DIVERSITY REQUIREMENTS — Make this piece UNIQUE:
- Universe/Setting Era: {item['universe'].upper()} — set this in a {item['universe']} world/time period
- Geography/Culture: {item['geography']} — the setting should be inspired by {item['geography']}
- Life Aspect: {item['life_aspect'].replace('_', ' ')} — weave this life theme into the narrative
- Plot Structure: {item['plot_archetype'].replace('_', ' ').upper()} — use this as the core plot archetype
- Lead Character: {item['character_name']} ({item['character_species']}) in {item['character_setting']}
{char_type_guidance}
- Lead Character Gender: {'The lead character should be {}'.format(item['lead_gender']) if item['lead_gender'] != 'neutral' else 'The lead character should be non-human or an ensemble cast'}
"""

    # Anti-duplication
    avoid = ""
    if existing_titles:
        titles_str = ", ".join(f'"{t}"' for t in existing_titles[-10:])
        avoid = f"\nTitles already used (yours MUST be different): {titles_str}\n"

    # Hindi
    hindi_block = HINDI_INSTRUCTION if lang == "hi" else ""

    prompt = f"""{base_prompt}

{age_inst}

{theme_inst}

LENGTH: {length_desc}

{diversity}
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
                 max_retries: int = 3, api: str = "claude") -> Optional[Dict]:
    """Generate a single content piece via Claude or Groq API."""

    # Poems are trickier (stanza structure, word count variability) — more attempts
    if item.get("type") == "poem":
        max_retries = max(max_retries, 5)

    prompt = build_generation_prompt(item, existing_titles)

    # Determine max_tokens based on word count range
    max_tokens = min(8192, max(1024, item["max_words"] * 4))

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

            content_obj = {
                "id": content_id,
                "type": item["type"],
                "lang": item["lang"],
                "title": title,
                "description": description,
                "text": text,
                "annotated_text": text,  # Text already has markers from prompt
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
                "lead_character_type": item.get("lead_character_type", "human"),
                "universe": item["universe"],
                "geography": item["geography"],
                "life_aspect": item["life_aspect"],
                "plot_archetype": item["plot_archetype"],
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
                     count_lullabies: int = 0,
                     lang: str = "en", existing: list = None) -> list:
    """Build a plan for N stories + M poems + L lullabies with full diversity randomization.

    Unlike the matrix-based plan, this generates fresh items regardless
    of what's already been produced. Used by the daily pipeline.
    """
    import random as _rng

    if existing is None:
        existing = []

    plan = []
    age_groups_list = list(AGE_GROUPS.keys())

    total = count_stories + count_poems + count_lullabies
    for i in range(total):
        if i < count_stories:
            content_type = "story"
        elif i < count_stories + count_poems:
            content_type = "poem"
        else:
            content_type = "song"

        # Pick random diversity dimensions
        age_group = _rng.choice(age_groups_list)
        ag_info = AGE_GROUPS[age_group]
        themes = THEMES_BY_AGE[age_group]
        lengths = LENGTHS_BY_AGE[age_group]
        life_aspects = LIFE_ASPECTS_BY_AGE[age_group]

        theme = _rng.choice(themes)
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
    args = parser.parse_args()

    # Load existing content
    existing = load_existing()

    if args.stats:
        show_stats(existing)
        return

    # Fresh count mode (for daily pipeline) vs. matrix mode
    use_fresh_mode = args.count_stories > 0 or args.count_poems > 0 or args.count_lullabies > 0

    if use_fresh_mode:
        lang = args.lang or "en"
        new_plan = build_fresh_plan(
            count_stories=args.count_stories,
            count_poems=args.count_poems,
            count_lullabies=args.count_lullabies,
            lang=lang,
            existing=existing,
        )
        logger.info("=== Fresh Generation Plan ===")
        logger.info("Stories: %d, Poems: %d, Lullabies: %d, Lang: %s",
                     args.count_stories, args.count_poems, args.count_lullabies, lang)
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

        result = generate_one(client, item, existing_titles, api=args.api)

        if result:
            existing.append(result)
            existing_titles.append(result["title"])
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
