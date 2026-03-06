"""
Narrative Diversity Engine for Dream Valley Content Generation.

13-dimension fingerprint system with collision scoring, hard rules,
catalog gap analysis, and compact prompt building.
"""

import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# DIMENSION DEFINITIONS (13 dimensions, no colorPalette, no characterSpecies)
# ═══════════════════════════════════════════════════════════════════════

DIMENSIONS = {
    # Tier 1 — high weight — hard rules (no same value in 3-day batch)
    "characterType": {
        "weight": 10,
        "hard_rule": True,
        "values": [
            "land_mammal", "bird", "sea_creature", "insect",
            "reptile_amphibian", "human_child", "mythical_creature",
            "object_alive", "plant_tree", "celestial_weather",
            "robot_mechanical",
        ],
    },
    "setting": {
        "weight": 10,
        "hard_rule": True,
        "values": [
            "forest_woodland", "ocean_water", "sky_space",
            "mountain_highland", "meadow_field", "desert_arid",
            "arctic_polar", "cozy_indoor", "village_town", "city_urban",
            "underground_cave", "garden_farm", "island_tropical",
            "imaginary_surreal", "miniature_world",
        ],
    },
    "plotShape": {
        "weight": 3,
        "hard_rule": True,
        "values": [
            "journey_destination", "discovery_reveal", "lost_and_found",
            "helping_someone", "building_growing", "transformation",
            "gathering_reunion", "pure_observation", "routine_ritual",
            "cyclical_seasonal",
        ],
    },
    # Tier 2 — medium weight — soft (collision score only)
    "scale": {
        "weight": 5,
        "values": [
            "tiny_intimate", "personal", "local_adventure",
            "journey", "epic_vast",
        ],
    },
    "companion": {
        "weight": 4,
        "values": [
            "solo", "duo", "group_community",
            "meets_stranger", "character_and_environment",
        ],
    },
    "movement": {
        "weight": 4,
        "values": [
            "sleeping_resting", "sitting_watching", "floating_drifting",
            "walking_wandering", "flying_swimming", "building_making",
        ],
    },
    "timeOfDay": {
        "weight": 4,
        "values": [
            "sunset_golden_hour", "twilight_blue_hour",
            "deep_night_starlight", "late_afternoon", "timeless",
        ],
    },
    "weather": {
        "weight": 4,
        "values": [
            "clear_calm", "gentle_rain", "misty_foggy", "snowy",
            "warm_breeze", "overcast_grey", "stormy_distant",
            "magical_atmospheric",
        ],
    },
    # Tier 3 — lower weight — soft
    "theme": {
        "weight": 3,
        "values": [
            "curiosity_wonder", "courage", "kindness", "friendship",
            "patience", "creativity", "belonging", "gratitude",
            "letting_go", "self_acceptance", "gentleness", "rest_stillness",
        ],
    },
    "characterTrait": {
        "weight": 3,
        "values": [
            "shy_quiet", "bold_adventurous", "dreamy_imaginative",
            "kind_nurturing", "clumsy_silly", "wise_old_soul",
            "anxious_worried", "stubborn_determined", "lonely_seeking",
            "playful_mischievous",
        ],
    },
    "magicType": {
        "weight": 3,
        "values": [
            "glowing_bioluminescent", "talking_sentient_world",
            "transformation_metamorphosis", "miniaturization",
            "music_sound_magic", "weather_magic",
            "dream_imagination_bleed", "time_magic", "color_magic",
            "no_magic_realistic",
        ],
    },
    "season": {
        "weight": 2,
        "values": [
            "spring", "summer", "autumn", "winter",
            "seasonal_transition", "seasonless_timeless",
        ],
    },
    "senseEmphasis": {
        "weight": 2,
        "values": [
            "visual", "auditory", "tactile", "olfactory", "kinesthetic",
        ],
    },
}

DIMENSION_NAMES = list(DIMENSIONS.keys())

# Dimensions with hard rules (no repeat in 3-day window)
HARD_RULE_DIMS = [k for k, v in DIMENSIONS.items() if v.get("hard_rule")]


# ═══════════════════════════════════════════════════════════════════════
# LEGACY MAPPING — old fields → new fingerprint dimensions
# ═══════════════════════════════════════════════════════════════════════

_CHAR_TYPE_MAP = {
    "human": "human_child",
    "animal": "land_mammal",
    "bird": "bird",
    "sea_creature": "sea_creature",
    "insect": "insect",
    "plant": "plant_tree",
    "celestial": "celestial_weather",
    "atmospheric": "celestial_weather",
    "mythical": "mythical_creature",
    "object": "object_alive",
    "alien": "mythical_creature",
    "robot": "robot_mechanical",
}

_PLOT_MAP = {
    "quest_journey": "journey_destination",
    "discovery": "discovery_reveal",
    "friendship_bonding": "helping_someone",
    "transformation": "transformation",
    "problem_solving": "discovery_reveal",
    "celebration": "gathering_reunion",
}

_THEME_MAP = {
    "dreamy": "rest_stillness",
    "adventure": "courage",
    "nature": "curiosity_wonder",
    "ocean": "curiosity_wonder",
    "animals": "friendship",
    "fantasy": "curiosity_wonder",
    "space": "curiosity_wonder",
    "bedtime": "rest_stillness",
    "friendship": "friendship",
    "mystery": "curiosity_wonder",
    "science": "curiosity_wonder",
    "family": "kindness",
    "fairy_tale": "curiosity_wonder",
}


def _map_legacy_to_fingerprint(story: dict) -> dict:
    """Create a partial fingerprint from legacy content fields.

    Returns a dict with None for dimensions that can't be inferred.
    """
    fp = {dim: None for dim in DIMENSION_NAMES}

    char_type = story.get("lead_character_type")
    if char_type and char_type in _CHAR_TYPE_MAP:
        fp["characterType"] = _CHAR_TYPE_MAP[char_type]

    plot = story.get("plot_archetype")
    if plot and plot in _PLOT_MAP:
        fp["plotShape"] = _PLOT_MAP[plot]

    theme = story.get("theme")
    if theme and theme in _THEME_MAP:
        fp["theme"] = _THEME_MAP[theme]

    return fp


# ═══════════════════════════════════════════════════════════════════════
# COLLISION SCORING
# ═══════════════════════════════════════════════════════════════════════

def compute_collision_score(fp_a: dict, fp_b: dict) -> int:
    """Compute how similar two fingerprints are. Higher = more similar = worse.

    None values in either fingerprint score 0 (no penalty).
    """
    score = 0
    for dim, config in DIMENSIONS.items():
        val_a = fp_a.get(dim)
        val_b = fp_b.get(dim)
        if val_a and val_b and val_a == val_b:
            score += config["weight"]
    return score


def check_collision(new_fp: dict, recent_stories: list,
                    max_3day: int = 12, max_14day: int = 18) -> tuple:
    """Check if a new fingerprint collides with recent stories.

    Returns (passes: bool, details: dict).
    """
    now = datetime.utcnow()
    cutoff_3d = (now - timedelta(days=3)).isoformat()
    cutoff_14d = (now - timedelta(days=14)).isoformat()

    worst_score = 0
    worst_id = None
    worst_3day_score = 0
    worst_3day_id = None

    for story in recent_stories:
        created = story.get("created_at", "")
        if created < cutoff_14d:
            continue

        fp = story.get("diversityFingerprint") or _map_legacy_to_fingerprint(story)
        score = compute_collision_score(new_fp, fp)
        sid = story.get("id", story.get("title", "?"))

        if score > worst_score:
            worst_score = score
            worst_id = sid

        if created >= cutoff_3d and score > worst_3day_score:
            worst_3day_score = score
            worst_3day_id = sid

    passes = worst_3day_score <= max_3day and worst_score <= max_14day

    return passes, {
        "score": max(worst_3day_score, worst_score),
        "worst_14day": {"id": worst_id, "score": worst_score},
        "worst_3day": {"id": worst_3day_id, "score": worst_3day_score},
    }


def check_hard_rules(new_fp: dict, recent_stories: list, days: int = 3) -> tuple:
    """Check hard rules: characterType, setting, plotShape must differ from 3-day stories.

    Returns (passes: bool, violations: list[str]).
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    violations = []

    for story in recent_stories:
        created = story.get("created_at", "")
        if created < cutoff:
            continue

        fp = story.get("diversityFingerprint") or _map_legacy_to_fingerprint(story)
        sid = story.get("id", story.get("title", "?"))

        for dim in HARD_RULE_DIMS:
            new_val = new_fp.get(dim)
            old_val = fp.get(dim)
            if new_val and old_val and new_val == old_val:
                violations.append(f"{dim}={new_val} (same as {sid})")

    return len(violations) == 0, violations


# ═══════════════════════════════════════════════════════════════════════
# FINGERPRINT VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_fingerprint(raw: dict) -> dict:
    """Validate and normalize a fingerprint from LLM output.

    Clamps each dimension value to the nearest valid value.
    Missing dimensions get None.
    """
    validated = {}
    for dim, config in DIMENSIONS.items():
        value = raw.get(dim)
        if not value:
            validated[dim] = None
            continue

        value = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        allowed = config["values"]

        # Exact match
        if value in allowed:
            validated[dim] = value
            continue

        # Fuzzy: check if value is a substring of an allowed value or vice versa
        for av in allowed:
            if value in av or av in value:
                validated[dim] = av
                break
        else:
            # Last resort: find best overlap by common tokens
            value_tokens = set(value.split("_"))
            best_match = None
            best_overlap = 0
            for av in allowed:
                av_tokens = set(av.split("_"))
                overlap = len(value_tokens & av_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = av
            validated[dim] = best_match if best_overlap > 0 else None

    return validated


# ═══════════════════════════════════════════════════════════════════════
# LOADING & GAP ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def load_recent_fingerprints(content_path, days: int = 14) -> list:
    """Load stories from content.json within the last N days.

    Returns list of story dicts (with diversityFingerprint or legacy fields).
    """
    path = Path(content_path)
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            all_stories = json.load(f)
    except (json.JSONDecodeError, Exception):
        return []

    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    recent = []
    for story in all_stories:
        created = story.get("created_at", "")
        if created >= cutoff:
            recent.append(story)

    return recent


def find_catalog_gaps(content_path) -> dict:
    """Analyze all stories and find underrepresented dimension values.

    Returns dict like {"setting": ["desert_arid", "arctic_polar"], ...}.
    """
    path = Path(content_path)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            all_stories = json.load(f)
    except (json.JSONDecodeError, Exception):
        return {}

    stories = [s for s in all_stories if s.get("type") in ("story", "long_story", "poem", "song")]
    if not stories:
        return {}

    gaps = {}
    for dim, config in DIMENSIONS.items():
        counter = Counter()
        for story in stories:
            fp = story.get("diversityFingerprint")
            if fp:
                val = fp.get(dim)
            else:
                val = _map_legacy_to_fingerprint(story).get(dim)
            if val:
                counter[val] += 1

        total = sum(counter.values())
        if total == 0:
            # No data for this dimension — all values are gaps
            gaps[dim] = config["values"][:]
            continue

        expected = total / len(config["values"])
        underrep = []
        for value in config["values"]:
            if counter.get(value, 0) < expected * 0.5:
                underrep.append(value)

        if underrep:
            gaps[dim] = underrep

    return gaps


# ═══════════════════════════════════════════════════════════════════════
# PROMPT BUILDING — compact diversity block for LLM
# ═══════════════════════════════════════════════════════════════════════

def _fingerprint_oneliner(fp: dict) -> str:
    """Compact single-line representation of a fingerprint for prompt."""
    parts = []
    for dim in DIMENSION_NAMES:
        val = fp.get(dim)
        parts.append(val or "?")
    return " / ".join(parts)


def _short_fingerprint(fp: dict) -> str:
    """Even shorter: just the 7 most important dims."""
    key_dims = ["characterType", "setting", "timeOfDay", "weather",
                "theme", "plotShape", "companion"]
    parts = []
    for dim in key_dims:
        val = fp.get(dim)
        parts.append(val or "?")
    return " / ".join(parts)


def build_diversity_prompt(recent_fps: list, catalog_gaps: dict) -> str:
    """Build a compact diversity guidance block for the generation prompt.

    Keeps it to ~5-8 lines. Shows last 3-5 recent fingerprints as one-liners
    and underrepresented values as a single line.
    """
    lines = []

    lines.append("""NARRATIVE DIVERSITY — Include these fields in your JSON output:
  "characterType", "setting", "timeOfDay", "weather", "theme",
  "plotShape", "scale", "companion", "movement", "magicType",
  "season", "senseEmphasis", "characterTrait"
""")

    # Show recent fingerprints (last 3-5)
    recent_with_fp = []
    for story in reversed(recent_fps):
        fp = story.get("diversityFingerprint") or _map_legacy_to_fingerprint(story)
        if any(fp.get(d) for d in HARD_RULE_DIMS):
            recent_with_fp.append((story, fp))
        if len(recent_with_fp) >= 5:
            break

    if recent_with_fp:
        lines.append("Your story MUST differ from recent stories on characterType AND setting AND plotShape:")
        for i, (story, fp) in enumerate(recent_with_fp, 1):
            title = story.get("title", "untitled")
            short = _short_fingerprint(fp)
            lines.append(f"  {i}. \"{title}\" — {short}")
        lines.append("")

    # Catalog gaps — single line
    gap_items = []
    priority_dims = ["setting", "characterType", "plotShape", "magicType",
                     "companion", "senseEmphasis"]
    for dim in priority_dims:
        values = catalog_gaps.get(dim, [])
        if values:
            # Pick up to 2 gap values per dimension
            samples = values[:2]
            labels = [v.replace("_", " ") for v in samples]
            gap_items.append(f"{dim}: {', '.join(labels)}")

    if gap_items:
        lines.append(f"Underrepresented (prioritize): {'; '.join(gap_items[:4])}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# CHARACTER NAME POOLS
# ═══════════════════════════════════════════════════════════════════════

NAME_POOLS = {
    "south_asian": [
        "Aarav", "Priya", "Dev", "Ananya", "Kavya", "Rohan", "Meera",
        "Arjun", "Sia", "Veer", "Isha", "Kian", "Riya", "Arun", "Diya",
        "Taj", "Nila", "Ravi", "Anu", "Jai", "Zara", "Neel", "Tara",
    ],
    "east_asian": [
        "Mei", "Hana", "Kenji", "Li", "Yuki", "Chen", "Suki", "Ren",
        "Aiko", "Bao", "Kai", "Mina", "Jun", "Haru", "Lin", "Sora",
        "Yui", "Tao", "Kira", "Nori",
    ],
    "african": [
        "Amara", "Kofi", "Zuri", "Nia", "Jabari", "Imani", "Ayo",
        "Kaya", "Sefu", "Lila", "Oba", "Ada", "Tendai", "Esi", "Kwame",
        "Sanaa", "Duma", "Zola", "Nala", "Tau",
    ],
    "european": [
        "Elara", "Finn", "Astrid", "Luca", "Maren", "Nico", "Freya",
        "Otto", "Iris", "Emil", "Lena", "Hugo", "Signe", "Arlo",
        "Cosima", "Elio", "Petra", "Rune", "Alma", "Stellan",
    ],
    "american_latin": [
        "Diego", "Luna", "Nayeli", "Rio", "Sol", "Paloma", "Mateo",
        "Coral", "Lark", "Luz", "Remy", "Sage", "Ira", "Maia",
        "Cruz", "Isla", "Seren", "Vale", "Cleo", "Wren",
    ],
    "nature_inspired": [
        "Ember", "Willow", "Brook", "Thistle", "Fern", "Storm", "Pebble",
        "Ivy", "Moss", "Hazel", "Clover", "Bramble", "Juniper", "Maple",
        "Rowan", "Basil", "Reed", "Lark", "Sage", "Flicker", "Pip",
        "Dewdrop", "Shimmer", "Hush", "Murmur", "Tilly", "Nutmeg",
    ],
}

ALL_NAMES = []
for pool in NAME_POOLS.values():
    ALL_NAMES.extend(pool)
# Deduplicate while preserving order
_seen = set()
ALL_NAMES = [n for n in ALL_NAMES if not (n in _seen or _seen.add(n))]


def pick_diverse_name(recent_names: list = None) -> str:
    """Pick a character name not used in recent stories (30-day window).

    Falls back to random from full pool if all names exhausted.
    """
    if recent_names is None:
        recent_names = []

    recent_set = {n.lower() for n in recent_names if n}
    available = [n for n in ALL_NAMES if n.lower() not in recent_set]

    if available:
        return random.choice(available)
    # All names used — pick least-recently-used by shuffling full pool
    return random.choice(ALL_NAMES)


def get_recent_names(content_path, days: int = 30) -> list:
    """Load character names from recent stories."""
    stories = load_recent_fingerprints(content_path, days=days)
    names = []
    for s in stories:
        char = s.get("character", {})
        name = char.get("name", "")
        if name:
            names.append(name)
    return names
