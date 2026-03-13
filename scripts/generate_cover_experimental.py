"""Generate experimental 2-layer cover: FLUX AI background + SVG animation overlay.

Implements the cover design strategy from cover-design-strategy.md:
  Layer 1: FLUX AI-generated illustration (WebP, 15-40 KB)
  Layer 2: SVG animation overlay (2-5 KB) — particles, glows, mist

Uses Hugging Face Inference API (free tier) with FLUX.1 Schnell model.

Usage:
    python3 scripts/generate_cover_experimental.py \\
        --story-json seed_output/experimental_6_8_gen-XXXX.json

    python3 scripts/generate_cover_experimental.py \\
        --story-json seed_output/experimental_6_8_gen-XXXX.json \\
        --world-setting enchanted_forest \\
        --palette golden_hour

    python3 scripts/generate_cover_experimental.py \\
        --story-json seed_output/experimental_6_8_gen-XXXX.json \\
        --dry-run
"""

import argparse
import io
import json
import logging
import math
import os
import hashlib
import random
import sys
import time
from datetime import datetime
from pathlib import Path


def _stable_seed(s: str) -> int:
    """Deterministic seed from string. Unlike hash(), same across Python processes."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % (2**31)


AXES_HISTORY_FILE = Path(__file__).parent.parent / "seed_output" / "covers_experimental" / "_axes_history.json"
_RECENT_PENALTY = 0.15   # Weight multiplier for recently used values (lower = stronger diversity)
_THEME_BOOST = 2.0       # Weight multiplier for theme-matched options
_CONTEXT_BOOST = 3.0     # Weight multiplier for context-matched options
_RECENT_WINDOW = 30      # Number of recent covers to consider


def _weighted_choice(options: list[str], weights: dict[str, float], rng: random.Random) -> str:
    """Pick from options using weighted random selection."""
    w = [weights.get(o, 1.0) for o in options]
    total = sum(w)
    r = rng.random() * total
    cumulative = 0.0
    for i, option in enumerate(options):
        cumulative += w[i]
        if r <= cumulative:
            return option
    return options[-1]


def _load_recent_axes() -> dict[str, list[str]]:
    """Load recent axis history and return per-axis lists of recently used values."""
    result = {k: [] for k in ("world_setting", "palette", "composition", "light", "texture", "time")}
    try:
        if AXES_HISTORY_FILE.exists():
            with open(AXES_HISTORY_FILE, "r") as f:
                history = json.load(f)
            # Take last N entries
            for entry in history[-_RECENT_WINDOW:]:
                axes = entry.get("axes", {})
                for k in result:
                    if k in axes:
                        result[k].append(axes[k])
    except Exception:
        pass  # Gracefully degrade — no history is fine
    return result


def _save_axes_history(story_id: str, axes: dict):
    """Append axes to history file. Keeps last 50 entries."""
    history = []
    try:
        if AXES_HISTORY_FILE.exists():
            with open(AXES_HISTORY_FILE, "r") as f:
                history = json.load(f)
    except Exception:
        pass
    history.append({
        "id": story_id,
        "axes": axes,
        "timestamp": datetime.now().isoformat(),
    })
    # Keep last 50
    history = history[-50:]
    try:
        AXES_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AXES_HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass


def _apply_recent_penalty(weights: dict[str, float], recent_values: list[str]) -> dict[str, float]:
    """Reduce weight for values that appear frequently in recent history."""
    if not recent_values:
        return weights
    from collections import Counter
    counts = Counter(recent_values)
    total = len(recent_values)
    result = dict(weights)
    for val, count in counts.items():
        if val in result:
            # More frequent in recent history = stronger penalty
            freq = count / total
            penalty = _RECENT_PENALTY ** freq  # e.g., 0.25^0.5 ≈ 0.5 for 50% freq
            result[val] *= penalty
    return result

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

try:
    import httpx
    from PIL import Image
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}. Run: pip install httpx Pillow")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

OUTPUT_DIR = BASE_DIR / "seed_output" / "covers_experimental"
SEED_OUTPUT = BASE_DIR / "seed_output"

# ── 7 Diversity Axes ────────────────────────────────────────────────────

WORLD_SETTINGS = {
    "deep_ocean":       {"signature": "Bioluminescent glow, depth gradient, coral forms", "shapes": "Flowing, organic curves"},
    "cloud_kingdom":    {"signature": "Volumetric clouds, soft edges, vast sky", "shapes": "Rounded, billowing masses"},
    "enchanted_forest": {"signature": "Canopy light, moss textures, mushroom glow", "shapes": "Vertical trunks, layered canopy"},
    "snow_landscape":   {"signature": "Blue-white palette, soft drifts, aurora hints", "shapes": "Gentle slopes, crystalline"},
    "desert_night":     {"signature": "Vast starfield, warm sand, silhouette forms", "shapes": "Horizontal planes, dunes"},
    "cozy_interior":    {"signature": "Warm lamp light, books/blankets, window view", "shapes": "Contained, intimate framing"},
    "mountain_meadow":  {"signature": "Wildflowers, distant peaks, golden hour light", "shapes": "Rolling ground, distant layers"},
    "space_cosmos":     {"signature": "Nebulae, planet curves, infinite depth", "shapes": "Spherical, vast, floating"},
    "tropical_lagoon":  {"signature": "Warm turquoise, palm silhouettes, sunset water", "shapes": "Reflective horizontal plane"},
    "underground_cave": {"signature": "Crystal formations, warm inner glow, hidden pools", "shapes": "Enclosed, cathedral-like"},
    "ancient_library":  {"signature": "Towering shelves, dust motes, amber lanterns", "shapes": "Vertical lines, warm rectangles"},
    "floating_islands": {"signature": "Sky gaps between land masses, waterfalls into sky", "shapes": "Suspended, weightless geometry"},
}

COLOR_PALETTES = {
    "ember_warm":   {"base": "Deep burgundy to warm amber", "accents": "Soft gold, muted coral", "mood": "Firelight, hearth, autumn"},
    "twilight_cool": {"base": "Deep indigo to soft lavender", "accents": "Pale silver, muted rose", "mood": "Dusk, first stars, quiet evening"},
    "forest_deep":  {"base": "Dark teal to sage green", "accents": "Warm moss, soft cream", "mood": "Canopy shade, fern grotto, rain"},
    "golden_hour":  {"base": "Deep ochre to pale buttermilk", "accents": "Dusty rose, warm brown", "mood": "Sunset, wheat fields, honey"},
    "moonstone":    {"base": "Charcoal blue to cool grey", "accents": "Pale blue-white, silver", "mood": "Moonlight, snow, quiet night"},
    "berry_dusk":   {"base": "Deep plum to dusty mauve", "accents": "Soft peach, warm grey", "mood": "Evening garden, twilight flowers"},
}

COMPOSITIONS = {
    "vast_landscape": "Wide aspect feel, low horizon line, big sky, character small in frame, environment dominant",
    "intimate_closeup": "Character fills most of frame, soft background blur, warm and personal",
    "overhead_canopy": "Looking up through trees/clouds/stars, radial composition, character small at bottom",
    "winding_path": "Depth composition, path/river/trail leading into soft distance, character on path facing away",
    "circular_nest": "Concentric composition, character at center surrounded by layers, nest/burrow/clearing structure",
}

CHARACTER_VISUALS = {
    "human_child":      "a young child with soft rounded features and bright curious eyes",
    "small_mammal":     "a small cute animal with soft round body and gentle expression",
    "aquatic_creature": "a gentle sea creature with flowing form and luminous eyes",
    "bird":             "a small bird with soft feathers and round body and bright curious eyes",
    "insect":           "a tiny insect with delicate features and round friendly face",
    "plant":            "a sentient plant with gentle glowing organic form",
    "celestial":        "a glowing celestial being with radiant soft light and ethereal form",
    "atmospheric":      "a personified weather element with translucent flowing form",
    "mythical_gentle":  "a baby mythical creature with soft features and round friendly face",
    "object":           "a personified everyday object with gentle expressive features and warm glow",
    "robot_mech":       "a small round friendly robot with soft edges and warm glowing eyes",
    "nature_spirit":    "an abstract nature spirit with flowing translucent form",
    "no_character":     "",
}

# Map lead_character_type (from content generation) → CHARACTER_VISUALS key
CHAR_TYPE_TO_VISUAL = {
    "human":        "human_child",
    "animal":       "small_mammal",
    "bird":         "bird",
    "sea_creature": "aquatic_creature",
    "insect":       "insect",
    "plant":        "plant",
    "celestial":    "celestial",
    "atmospheric":  "atmospheric",
    "mythical":     "mythical_gentle",
    "object":       "object",
    "alien":        "nature_spirit",
    "robot":        "robot_mech",
}

# Human appearance diversity — deterministically selected per story via hash
# Gender-appropriate options to avoid mismatches
HAIR_STYLES_FEMALE = [
    "long straight black hair", "braided hair with ribbons", "curly dark hair",
    "pigtails", "bob cut hair", "afro hair", "long flowing red hair",
    "two buns", "ponytail with bangs", "wavy brown hair with flowers",
]
HAIR_STYLES_MALE = [
    "short curly dark hair", "messy wavy brown hair", "short spiky hair",
    "short afro hair", "buzz cut", "shaggy brown hair", "neat black hair",
    "short hair with a headband", "tousled red hair", "close-cropped hair",
]
SKIN_TONES = [
    "warm brown skin", "light olive skin", "dark brown skin", "fair rosy skin",
    "tan skin", "deep ebony skin", "golden tan skin", "pale with freckles",
]
CLOTHING_STYLES_FEMALE = [
    "wearing a cozy knitted sweater", "wearing a flowing colorful dress",
    "wearing overalls and a striped shirt", "wearing a hooded cape",
    "wearing a hoodie", "wearing traditional embroidered clothing",
    "wearing a puffy jacket and scarf", "wearing a simple tunic",
]
CLOTHING_STYLES_MALE = [
    "wearing a cozy knitted sweater", "wearing a vest and rolled-up sleeves",
    "wearing overalls and a striped shirt", "wearing a hooded cape",
    "wearing a hoodie and sneakers", "wearing traditional embroidered clothing",
    "wearing a puffy jacket and scarf", "wearing a simple tunic and sandals",
]

LIGHT_SOURCES = {
    "above": "Cool, gentle moonlight/starlight diffused from top",
    "backlit": "Warm rim light from behind/sunset/horizon glow, silhouettes",
    "below": "Unusual magical glow from bioluminescence/campfire/glowing object, intimate",
    "ambient": "No shadows, fog/overcast/underwater diffusion, everything soft and even, most calming",
}

TEXTURES = {
    "watercolor_soft": "Visible paper grain, bleeding color edges, organic imperfections, warm handmade feel",
    "soft_pastel": "Dusty, matte, slightly grainy, textured and tactile, muted tones",
    "digital_painterly": "Smooth but with visible brushwork, rich depth and glow, Studio Ghibli adjacent",
    "paper_cutout": "Layered, textural, slight 3D parallax feeling, handcraft aesthetic",
}

TIME_MARKERS = {
    "early_night": "First stars, deep blue sky, some light on horizon",
    "deep_night": "Full dark, many stars, moon present, no horizon glow",
    "eternal_dusk": "Perpetual sunset quality, everything amber-pink",
    "timeless_indoor": "No sky visible, time is irrelevant, interior warmth",
}

# Theme → world setting auto-mapping
THEME_TO_WORLD = {
    "water": ["tropical_lagoon", "deep_ocean"],
    "nature": ["enchanted_forest", "mountain_meadow"],
    "sky": ["cloud_kingdom", "floating_islands"],
    "fantasy": ["enchanted_forest", "floating_islands", "cloud_kingdom"],
    "animals": ["enchanted_forest", "mountain_meadow"],
    "dreams": ["cloud_kingdom", "floating_islands"],
    "stars": ["space_cosmos", "desert_night"],
    "garden": ["enchanted_forest", "mountain_meadow"],
    "adventure": ["enchanted_forest", "underground_cave"],
    "space": ["space_cosmos"],
    "mystery": ["ancient_library", "underground_cave"],
    "underwater": ["deep_ocean"],
    "ancient_civilizations": ["ancient_library", "underground_cave"],
}

# Theme → palette auto-mapping
THEME_TO_PALETTE = {
    "water": ["twilight_cool", "moonstone"],
    "nature": ["forest_deep", "golden_hour"],
    "sky": ["twilight_cool", "moonstone"],
    "fantasy": ["berry_dusk", "twilight_cool"],
    "animals": ["forest_deep", "golden_hour"],
    "dreams": ["berry_dusk", "twilight_cool"],
    "stars": ["moonstone", "twilight_cool"],
    "garden": ["forest_deep", "berry_dusk"],
    "adventure": ["golden_hour", "ember_warm"],
    "space": ["moonstone", "twilight_cool"],
}


# ── SMIL Animation — 3-Layer World-to-Element Mapping (Revised) ─────────
#
# Rich, layered animations: 12-20 elements per cover across 3 depth layers.
# Background (4-6): atmosphere, depth. Midground (4-7): living world. Foreground (3-5): framing.
# Plus fauna detail (1-2) and rare events (0-1).

WORLD_ELEMENTS = {
    "enchanted_forest": {
        "background": {"pool": ["stars", "moon_glow", "fog", "aurora"], "pick": (3, 4)},
        "midground":  {"pool": ["fireflies", "dust_motes", "falling_leaves", "closing_flowers", "shadow_play"], "pick": (4, 5)},
        "foreground": {"pool": ["swaying_branches", "fog", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_owl", "sleeping_butterfly", "cricket"],
        "rare_event": ["shooting_star"],
        "vignette":   "bottom_heavy",
        "pacer_variant": "forest",
    },
    "deep_ocean": {
        "background": {"pool": ["fog", "caustics", "aurora", "moon_glow"], "pick": (3, 4)},
        "midground":  {"pool": ["bubbles", "caustics", "dust_motes", "water_ripples", "shadow_play"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "swaying_branches", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "top_heavy",
        "pacer_variant": "ocean",
    },
    "space_cosmos": {
        "background": {"pool": ["stars", "aurora", "moon_glow", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "stars", "fireflies", "shadow_play"], "pick": (3, 4)},
        "foreground": {"pool": ["fog", "dust_motes", "stars"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "corners_only",
        "pacer_variant": "space",
    },
    "snow_landscape": {
        "background": {"pool": ["stars", "moon_glow", "aurora", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["snowfall", "chimney_smoke", "dust_motes", "wind_grass", "shadow_play"], "pick": (4, 5)},
        "foreground": {"pool": ["swaying_branches", "fog", "snowfall"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_owl"],
        "rare_event": ["shooting_star"],
        "vignette":   "bottom_light",
        "pacer_variant": "forest",
    },
    "cozy_interior": {
        "background": {"pool": ["stars", "moon_glow", "shadow_play", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "candle_flicker", "shadow_play", "fireflies", "closing_flowers"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "dust_motes", "shadow_play"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly", "cricket"],
        "rare_event": ["shooting_star"],
        "vignette":   "full_soft",
        "pacer_variant": "interior",
    },
    "desert_night": {
        "background": {"pool": ["stars", "moon_glow", "fog", "aurora"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "wind_grass", "fireflies", "shadow_play"], "pick": (3, 4)},
        "foreground": {"pool": ["fog", "dust_motes", "shadow_play"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["cricket"],
        "rare_event": ["shooting_star"],
        "vignette":   "top_corners",
        "pacer_variant": "space",
    },
    "mountain_meadow": {
        "background": {"pool": ["stars", "moon_glow", "fog", "aurora"], "pick": (3, 4)},
        "midground":  {"pool": ["fireflies", "dust_motes", "wind_grass", "falling_leaves", "closing_flowers"], "pick": (4, 5)},
        "foreground": {"pool": ["swaying_branches", "fog", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["cricket", "sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "bottom_light",
        "pacer_variant": "forest",
    },
    "cloud_kingdom": {
        "background": {"pool": ["stars", "aurora", "moon_glow", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "fireflies", "falling_leaves", "wind_grass", "shadow_play"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "dust_motes", "swaying_branches"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "full_soft",
        "pacer_variant": "space",
    },
    "underground_cave": {
        "background": {"pool": ["fog", "caustics", "shadow_play", "aurora"], "pick": (3, 4)},
        "midground":  {"pool": ["candle_flicker", "dust_motes", "caustics", "bubbles", "fireflies"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "shadow_play", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["cricket", "sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "full_heavy",
        "pacer_variant": "forest",
    },
    "tropical_lagoon": {
        "background": {"pool": ["stars", "moon_glow", "fog", "aurora"], "pick": (3, 4)},
        "midground":  {"pool": ["water_ripples", "fireflies", "bubbles", "dust_motes", "caustics"], "pick": (4, 5)},
        "foreground": {"pool": ["swaying_branches", "fog", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["cricket", "sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "top_heavy",
        "pacer_variant": "ocean",
    },
    "ancient_library": {
        "background": {"pool": ["stars", "moon_glow", "shadow_play", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "candle_flicker", "shadow_play", "fireflies", "closing_flowers"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "dust_motes", "shadow_play"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly", "cricket"],
        "rare_event": ["shooting_star"],
        "vignette":   "full_soft",
        "pacer_variant": "interior",
    },
    "floating_islands": {
        "background": {"pool": ["stars", "aurora", "moon_glow", "fog"], "pick": (3, 4)},
        "midground":  {"pool": ["dust_motes", "falling_leaves", "fireflies", "wind_grass", "shadow_play"], "pick": (4, 5)},
        "foreground": {"pool": ["fog", "swaying_branches", "dust_motes"], "pick": (2, 3)},
        "required":   ["breathing_pacer"],
        "fauna":      ["sleeping_butterfly"],
        "rare_event": ["shooting_star"],
        "vignette":   "full_soft",
        "pacer_variant": "space",
    },
}


# ── V3 Cinemagraph: Region Templates ─────────────────────────────────────
#
# Deterministic region templates per world_setting. Since we control the FLUX
# prompt, we know what each scene contains — no ML segmentation needed.
#
# Each region: id, type (9 types), zone (mask shape), feather_px, is_primary,
# context_variant (filter style hint).

REGION_TEMPLATES = {
    "enchanted_forest": [
        {"id": "sky_main", "type": "sky", "zone": "top_third", "feather_px": 15, "is_primary": False, "context_variant": "thin_wispy"},
        {"id": "canopy", "type": "vegetation_canopy", "zone": "upper_sides", "feather_px": 12, "is_primary": True, "context_variant": "dense_canopy"},
        {"id": "ground_veg", "type": "vegetation_ground", "zone": "bottom_strip", "feather_px": 10, "is_primary": False, "context_variant": "flowers"},
        {"id": "fog_floor", "type": "fog_zone", "zone": "lower_band", "feather_px": 25, "is_primary": False, "context_variant": "forest_mist"},
    ],
    "deep_ocean": [
        {"id": "water_main", "type": "water", "zone": "full_frame", "feather_px": 20, "is_primary": True, "context_variant": "underwater"},
        {"id": "seaweed", "type": "vegetation_ground", "zone": "bottom_strip", "feather_px": 12, "is_primary": False, "context_variant": "seaweed"},
        {"id": "fog_depth", "type": "fog_zone", "zone": "upper_band", "feather_px": 25, "is_primary": False, "context_variant": "underwater_haze"},
    ],
    "cloud_kingdom": [
        {"id": "sky_main", "type": "sky", "zone": "top_half", "feather_px": 18, "is_primary": True, "context_variant": "magical"},
        {"id": "fog_clouds", "type": "fog_zone", "zone": "mid_band", "feather_px": 25, "is_primary": False, "context_variant": "mountain_cloud"},
    ],
    "snow_landscape": [
        {"id": "sky_main", "type": "sky", "zone": "top_third", "feather_px": 15, "is_primary": False, "context_variant": "open_night_sky"},
        {"id": "fog_snow", "type": "fog_zone", "zone": "lower_band", "feather_px": 25, "is_primary": True, "context_variant": "mountain_cloud"},
        {"id": "reflection_ice", "type": "reflection", "zone": "bottom_quarter", "feather_px": 12, "is_primary": False, "context_variant": "crystal_ice"},
    ],
    "desert_night": [
        {"id": "sky_main", "type": "sky", "zone": "top_half", "feather_px": 15, "is_primary": True, "context_variant": "open_night_sky"},
        {"id": "fog_ground", "type": "fog_zone", "zone": "bottom_strip", "feather_px": 20, "is_primary": False, "context_variant": "magical_shimmer"},
    ],
    "cozy_interior": [
        {"id": "fire_hearth", "type": "fire", "zone": "lower_center_circle", "feather_px": 15, "is_primary": True, "context_variant": "campfire"},
        {"id": "smoke_chimney", "type": "smoke", "zone": "upper_center_narrow", "feather_px": 15, "is_primary": False, "context_variant": "chimney"},
        {"id": "fog_dust", "type": "fog_zone", "zone": "mid_band", "feather_px": 20, "is_primary": False, "context_variant": "cave_steam"},
    ],
    "mountain_meadow": [
        {"id": "sky_main", "type": "sky", "zone": "top_third", "feather_px": 15, "is_primary": False, "context_variant": "thin_wispy"},
        {"id": "grass", "type": "vegetation_ground", "zone": "bottom_half", "feather_px": 12, "is_primary": True, "context_variant": "tall_grass"},
        {"id": "fog_meadow", "type": "fog_zone", "zone": "lower_band", "feather_px": 25, "is_primary": False, "context_variant": "forest_mist"},
    ],
    "space_cosmos": [
        {"id": "sky_main", "type": "sky", "zone": "full_frame", "feather_px": 20, "is_primary": True, "context_variant": "space_nebula"},
    ],
    "tropical_lagoon": [
        {"id": "water_lagoon", "type": "water", "zone": "bottom_half", "feather_px": 15, "is_primary": True, "context_variant": "lake"},
        {"id": "sky_main", "type": "sky", "zone": "top_third", "feather_px": 15, "is_primary": False, "context_variant": "thin_wispy"},
        {"id": "reflection_water", "type": "reflection", "zone": "bottom_quarter", "feather_px": 12, "is_primary": False, "context_variant": "water_reflection"},
    ],
    "underground_cave": [
        {"id": "water_pool", "type": "water", "zone": "bottom_quarter", "feather_px": 12, "is_primary": False, "context_variant": "pond"},
        {"id": "fire_torch", "type": "fire", "zone": "right_circle", "feather_px": 12, "is_primary": True, "context_variant": "lantern"},
        {"id": "fog_steam", "type": "fog_zone", "zone": "mid_band", "feather_px": 25, "is_primary": False, "context_variant": "cave_steam"},
    ],
    "ancient_library": [
        {"id": "fire_candle", "type": "fire", "zone": "right_circle", "feather_px": 12, "is_primary": True, "context_variant": "candle"},
        {"id": "fog_dust", "type": "fog_zone", "zone": "upper_band", "feather_px": 20, "is_primary": False, "context_variant": "magical_shimmer"},
    ],
    "floating_islands": [
        {"id": "sky_main", "type": "sky", "zone": "full_frame", "feather_px": 20, "is_primary": True, "context_variant": "magical"},
        {"id": "fog_clouds", "type": "fog_zone", "zone": "mid_band", "feather_px": 25, "is_primary": False, "context_variant": "mountain_cloud"},
        {"id": "veg_island", "type": "vegetation_canopy", "zone": "center_sides", "feather_px": 12, "is_primary": False, "context_variant": "branches"},
    ],
}


# ── V3 Cinemagraph: Mask Path Generation ─────────────────────────────────

def _zone_to_mask_path(zone, feather_px, rng, width=512, height=512):
    """Convert a zone descriptor to an SVG path with organic edges.

    Returns (path_d, mask_type) where mask_type is 'path' or 'circle'.
    Uses quadratic Bezier curves for natural contours.
    """
    w, h = width, height
    # Small random perturbation for organic edges
    def _jitter(base, amt=15):
        return base + rng.randint(-amt, amt)

    if zone == "top_third":
        # Sky region: organic bottom edge
        y_base = int(h * 0.35)
        pts = [
            (0, 0), (w, 0), (w, _jitter(y_base, 20)),
            (_jitter(w * 0.75, 10), _jitter(y_base - 15, 12)),
            (_jitter(w * 0.5, 10), _jitter(y_base + 10, 12)),
            (_jitter(w * 0.25, 10), _jitter(y_base - 10, 12)),
            (0, _jitter(y_base, 20)),
        ]
        d = f"M{pts[0][0]},{pts[0][1]} L{pts[1][0]},{pts[1][1]} L{pts[2][0]},{pts[2][1]}"
        d += f" Q{pts[3][0]},{pts[3][1]} {pts[4][0]},{pts[4][1]}"
        d += f" Q{pts[5][0]},{pts[5][1]} {pts[6][0]},{pts[6][1]} Z"
        return d, "path"

    elif zone == "top_half":
        y_base = int(h * 0.55)
        pts = [
            (0, 0), (w, 0), (w, _jitter(y_base, 20)),
            (_jitter(w * 0.7, 10), _jitter(y_base - 20, 15)),
            (_jitter(w * 0.4, 10), _jitter(y_base + 15, 15)),
            (0, _jitter(y_base, 20)),
        ]
        d = f"M{pts[0][0]},{pts[0][1]} L{pts[1][0]},{pts[1][1]} L{pts[2][0]},{pts[2][1]}"
        d += f" Q{pts[3][0]},{pts[3][1]} {pts[4][0]},{pts[4][1]}"
        d += f" Q{pts[4][0]},{pts[4][1]} {pts[5][0]},{pts[5][1]} Z"
        return d, "path"

    elif zone == "bottom_quarter":
        y_base = int(h * 0.75)
        pts = [
            (0, _jitter(y_base, 15)), (w, _jitter(y_base, 15)),
            (w, h), (0, h),
        ]
        # Organic top edge
        mid_x = _jitter(w * 0.5, 15)
        mid_y = _jitter(y_base - 10, 10)
        d = f"M{pts[0][0]},{pts[0][1]} Q{mid_x},{mid_y} {pts[1][0]},{pts[1][1]}"
        d += f" L{pts[2][0]},{pts[2][1]} L{pts[3][0]},{pts[3][1]} Z"
        return d, "path"

    elif zone == "bottom_half":
        y_base = int(h * 0.48)
        pts = [
            (0, _jitter(y_base, 20)),
            (_jitter(w * 0.3, 10), _jitter(y_base + 15, 12)),
            (_jitter(w * 0.6, 10), _jitter(y_base - 10, 12)),
            (w, _jitter(y_base, 20)),
            (w, h), (0, h),
        ]
        d = f"M{pts[0][0]},{pts[0][1]} Q{pts[1][0]},{pts[1][1]} {pts[2][0]},{pts[2][1]}"
        d += f" Q{pts[2][0]},{pts[2][1]} {pts[3][0]},{pts[3][1]}"
        d += f" L{pts[4][0]},{pts[4][1]} L{pts[5][0]},{pts[5][1]} Z"
        return d, "path"

    elif zone == "bottom_strip":
        y_base = int(h * 0.82)
        pts = [
            (0, _jitter(y_base, 12)),
            (_jitter(w * 0.35, 10), _jitter(y_base - 8, 8)),
            (_jitter(w * 0.65, 10), _jitter(y_base + 5, 8)),
            (w, _jitter(y_base, 12)),
            (w, h), (0, h),
        ]
        d = f"M{pts[0][0]},{pts[0][1]} Q{pts[1][0]},{pts[1][1]} {pts[2][0]},{pts[2][1]}"
        d += f" Q{pts[2][0]},{pts[2][1]} {pts[3][0]},{pts[3][1]}"
        d += f" L{pts[4][0]},{pts[4][1]} L{pts[5][0]},{pts[5][1]} Z"
        return d, "path"

    elif zone == "upper_sides":
        # Two patches left+right for canopy
        y_top = int(h * 0.08)
        y_bot = int(h * 0.55)
        lw = int(w * 0.3)
        rw_start = int(w * 0.7)
        d = f"M0,{_jitter(y_top, 10)} L{_jitter(lw, 15)},{_jitter(y_top + 20, 10)}"
        d += f" Q{_jitter(lw + 20, 10)},{_jitter(y_bot * 0.5, 15)} {_jitter(lw - 10, 15)},{_jitter(y_bot, 15)}"
        d += f" L0,{_jitter(y_bot, 15)} Z"
        d += f" M{_jitter(rw_start, 15)},{_jitter(y_top + 10, 10)} L{w},{_jitter(y_top, 10)}"
        d += f" L{w},{_jitter(y_bot, 15)}"
        d += f" Q{_jitter(rw_start - 10, 10)},{_jitter(y_bot * 0.6, 15)} {_jitter(rw_start + 10, 15)},{_jitter(y_top + 30, 10)} Z"
        return d, "path"

    elif zone == "center_sides":
        # Vegetation on left+right sides of center
        y_top = int(h * 0.25)
        y_bot = int(h * 0.75)
        lw = int(w * 0.25)
        rw = int(w * 0.75)
        d = f"M0,{_jitter(y_top, 10)} L{_jitter(lw, 10)},{_jitter(y_top + 20, 10)}"
        d += f" L{_jitter(lw - 10, 10)},{_jitter(y_bot, 10)} L0,{_jitter(y_bot, 10)} Z"
        d += f" M{_jitter(rw, 10)},{_jitter(y_top + 10, 10)} L{w},{_jitter(y_top, 10)}"
        d += f" L{w},{_jitter(y_bot, 10)} L{_jitter(rw + 10, 10)},{_jitter(y_bot - 10, 10)} Z"
        return d, "path"

    elif zone == "lower_band":
        # Fog band in lower portion
        y_top = int(h * 0.6)
        y_bot = int(h * 0.82)
        pts_top = [
            (0, _jitter(y_top, 15)),
            (_jitter(w * 0.25, 10), _jitter(y_top - 10, 10)),
            (_jitter(w * 0.5, 10), _jitter(y_top + 12, 10)),
            (_jitter(w * 0.75, 10), _jitter(y_top - 8, 10)),
            (w, _jitter(y_top, 15)),
        ]
        d = f"M{pts_top[0][0]},{pts_top[0][1]}"
        d += f" Q{pts_top[1][0]},{pts_top[1][1]} {pts_top[2][0]},{pts_top[2][1]}"
        d += f" Q{pts_top[3][0]},{pts_top[3][1]} {pts_top[4][0]},{pts_top[4][1]}"
        d += f" L{w},{_jitter(y_bot, 12)} L0,{_jitter(y_bot, 12)} Z"
        return d, "path"

    elif zone == "upper_band":
        y_top = int(h * 0.15)
        y_bot = int(h * 0.4)
        d = f"M0,{_jitter(y_top, 10)} L{w},{_jitter(y_top, 10)}"
        d += f" L{w},{_jitter(y_bot, 12)}"
        mid_x = _jitter(w * 0.5, 15)
        mid_y = _jitter(y_bot + 10, 8)
        d += f" Q{mid_x},{mid_y} 0,{_jitter(y_bot, 12)} Z"
        return d, "path"

    elif zone == "mid_band":
        y_top = int(h * 0.35)
        y_bot = int(h * 0.65)
        d = f"M0,{_jitter(y_top, 12)} L{w},{_jitter(y_top, 12)}"
        d += f" L{w},{_jitter(y_bot, 12)} L0,{_jitter(y_bot, 12)} Z"
        return d, "path"

    elif zone in ("center_circle", "lower_center_circle", "upper_center",
                   "upper_right_circle", "right_circle", "center_wide"):
        # Circular or elliptical glow/fire regions
        if zone == "center_circle":
            cx, cy, r = w // 2, h // 2, int(min(w, h) * 0.15)
        elif zone == "lower_center_circle":
            cx, cy, r = w // 2, int(h * 0.7), int(min(w, h) * 0.12)
        elif zone == "upper_center":
            cx, cy, r = w // 2, int(h * 0.2), int(min(w, h) * 0.14)
        elif zone == "upper_right_circle":
            cx, cy, r = int(w * 0.75), int(h * 0.18), int(min(w, h) * 0.12)
        elif zone == "right_circle":
            cx, cy, r = int(w * 0.78), int(h * 0.45), int(min(w, h) * 0.10)
        elif zone == "center_wide":
            cx, cy, r = w // 2, int(h * 0.5), int(min(w, h) * 0.30)
        else:
            cx, cy, r = w // 2, h // 2, int(min(w, h) * 0.15)
        # Add jitter to circle
        cx = _jitter(cx, 8)
        cy = _jitter(cy, 8)
        return f"{cx},{cy},{r}", "circle"

    elif zone == "upper_center_narrow":
        # Narrow column for chimney smoke
        x_left = int(w * 0.4)
        x_right = int(w * 0.6)
        y_top = 0
        y_bot = int(h * 0.5)
        d = f"M{_jitter(x_left, 8)},{y_top} L{_jitter(x_right, 8)},{y_top}"
        d += f" L{_jitter(x_right + 10, 8)},{_jitter(y_bot, 10)}"
        d += f" L{_jitter(x_left - 10, 8)},{_jitter(y_bot, 10)} Z"
        return d, "path"

    elif zone == "full_frame":
        # Entire frame (for underwater / space)
        return f"M0,0 L{w},0 L{w},{h} L0,{h} Z", "path"

    else:
        # Fallback: center rectangle
        margin = int(min(w, h) * 0.15)
        return f"M{margin},{margin} L{w - margin},{margin} L{w - margin},{h - margin} L{margin},{h - margin} Z", "path"


# ── Character Exclusion Zones ────────────────────────────────────────────
#
# Maps composition type → approximate character bounding ellipse (cx, cy, rx, ry)
# as fractions of the 512x512 canvas. A black ellipse is added inside every
# cinemagraph mask to prevent filters from distorting the character's face/body.
# The exclusion has a soft feathered edge (20px blur) so the transition is seamless.

CHARACTER_EXCLUSION_ZONES = {
    "vast_landscape":    {"cx": 0.50, "cy": 0.72, "rx": 0.10, "ry": 0.14},  # Small character at bottom center
    "intimate_closeup":  {"cx": 0.50, "cy": 0.45, "rx": 0.28, "ry": 0.35},  # Character fills most of frame
    "overhead_canopy":   {"cx": 0.50, "cy": 0.78, "rx": 0.12, "ry": 0.12},  # Small at bottom
    "winding_path":      {"cx": 0.45, "cy": 0.60, "rx": 0.12, "ry": 0.18},  # On path, mid-lower
    "circular_nest":     {"cx": 0.50, "cy": 0.50, "rx": 0.18, "ry": 0.22},  # Center of frame
}

# Fallback: most compositions place the character in the lower-center
_DEFAULT_EXCLUSION = {"cx": 0.50, "cy": 0.62, "rx": 0.15, "ry": 0.20}


def _generate_mask_element(region, rng, composition=None):
    """Generate a complete SVG <mask> element for a region with feathered edges.

    Includes a character exclusion zone — a soft black ellipse that prevents
    cinemagraph filters from distorting the character's face/body.
    """
    rid = region["id"]
    zone = region["zone"]
    feather = region["feather_px"]
    seed = rng.randint(1, 9999)

    path_data, mask_type = _zone_to_mask_path(zone, feather, rng)

    # Feathering filter for this mask
    blur_id = f"blur-{rid}"
    parts = []
    parts.append(f'    <filter id="{blur_id}"><feGaussianBlur stdDeviation="{feather}"/></filter>')

    # Character exclusion: soft black ellipse to protect character face/body
    char_zone = CHARACTER_EXCLUSION_ZONES.get(composition, _DEFAULT_EXCLUSION) if composition else _DEFAULT_EXCLUSION
    char_cx = int(char_zone["cx"] * 512)
    char_cy = int(char_zone["cy"] * 512)
    char_rx = int(char_zone["rx"] * 512)
    char_ry = int(char_zone["ry"] * 512)
    # Feathered exclusion filter
    char_blur_id = f"char-blur-{rid}"
    parts.append(f'    <filter id="{char_blur_id}"><feGaussianBlur stdDeviation="20"/></filter>')

    if mask_type == "circle":
        cx, cy, r = path_data.split(",")
        parts.append(f'    <mask id="mask-{rid}">')
        parts.append(f'      <circle cx="{cx}" cy="{cy}" r="{int(float(r)) + feather}" fill="white" filter="url(#{blur_id})"/>')
        parts.append(f'      <ellipse cx="{char_cx}" cy="{char_cy}" rx="{char_rx}" ry="{char_ry}" fill="black" filter="url(#{char_blur_id})"/>')
        parts.append(f'    </mask>')
    else:
        parts.append(f'    <mask id="mask-{rid}">')
        parts.append(f'      <path d="{path_data}" fill="white" filter="url(#{blur_id})"/>')
        parts.append(f'      <ellipse cx="{char_cx}" cy="{char_cy}" rx="{char_rx}" ry="{char_ry}" fill="black" filter="url(#{char_blur_id})"/>')
        parts.append(f'    </mask>')

    return "\n".join(parts)


# ── V3 Cinemagraph: Filter Generators ────────────────────────────────────
#
# 8 filter types from animated-cover-plan-v3.md.
# Each returns an SVG <filter> string with SMIL-animated attributes.
# Parameters randomized within diversity ranges using seeded rng.

FILTER_GENERATORS = {}  # Populated below: type -> generator function


def _gen_filter_water_flow(region, rng):
    """Water flow: undulating distortion for water surfaces."""
    rid = region["id"]
    fid = f"water-flow-{rid}"
    variant = region.get("context_variant", "lake")
    seed = rng.randint(1, 999)

    # Context-based parameter ranges (subtle cinemagraph — gentle motion, not warping)
    params = {
        "ocean":      {"freq_x": (0.008, 0.012), "freq_y": (0.025, 0.035), "octaves": (3, 4), "scale": (12, 12), "dur_freq": (12, 16), "dur_scale": (13, 17)},
        "lake":       {"freq_x": (0.012, 0.016), "freq_y": (0.030, 0.040), "octaves": (2, 3), "scale": (9, 9),   "dur_freq": (10, 14), "dur_scale": (12, 16)},
        "pond":       {"freq_x": (0.016, 0.020), "freq_y": (0.040, 0.050), "octaves": (2, 2), "scale": (7, 7),   "dur_freq": (8, 12),  "dur_scale": (10, 14)},
        "river":      {"freq_x": (0.010, 0.014), "freq_y": (0.040, 0.050), "octaves": (2, 3), "scale": (10, 10), "dur_freq": (9, 13),  "dur_scale": (11, 15)},
        "underwater": {"freq_x": (0.006, 0.010), "freq_y": (0.015, 0.025), "octaves": (2, 3), "scale": (5, 5),   "dur_freq": (14, 18), "dur_scale": (16, 20)},
    }.get(variant, {"freq_x": (0.012, 0.016), "freq_y": (0.030, 0.040), "octaves": (2, 3), "scale": (9, 9), "dur_freq": (10, 14), "dur_scale": (12, 16)})

    fx = round(rng.uniform(*params["freq_x"]), 3)
    fy = round(rng.uniform(*params["freq_y"]), 3)
    octaves = rng.randint(*params["octaves"])
    scale_base = rng.randint(*params["scale"])
    dur_freq = rng.randint(*params["dur_freq"])
    dur_scale = rng.randint(*params["dur_scale"])
    # Ensure different primes for staggered recalculation
    if dur_freq == dur_scale:
        dur_scale += 1

    # Animation values: base ± variation (gentle swing)
    fx_var = round(fx * 0.20, 3)
    fy_var = round(fy * 0.12, 3)
    freq_vals = f"{fx} {fy}; {fx + fx_var:.3f} {fy - fy_var:.3f}; {fx - fx_var:.3f} {fy + fy_var:.3f}; {fx + fx_var * 0.5:.3f} {fy - fy_var * 0.5:.3f}; {fx} {fy}"
    s_lo = max(scale_base - 2, 3)
    s_hi = scale_base + 2
    scale_vals = f"{scale_base};{s_hi};{s_lo};{scale_base + 1};{scale_base}"

    splines = "0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"
    return f'''    <filter id="{fid}" x="-5%" y="-5%" width="110%" height="110%">
      <feTurbulence type="turbulence" baseFrequency="{fx} {fy}" numOctaves="{octaves}" result="noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur_freq}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{scale_vals}" dur="{dur_scale}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["water"] = _gen_filter_water_flow


def _gen_filter_cloud_drift(region, rng):
    """Cloud drift: slow large-scale distortion for sky regions."""
    rid = region["id"]
    fid = f"cloud-drift-{rid}"
    variant = region.get("context_variant", "open_night_sky")
    seed = rng.randint(1, 999)

    params = {
        "open_night_sky": {"freq": (0.004, 0.007), "octaves": (1, 2), "scale": (8, 8),   "dur_churn": (25, 35), "dur_drift": (35, 55), "drift_px": (8, 10), "noise_type": "fractalNoise"},
        "dramatic":       {"freq": (0.005, 0.009), "octaves": (2, 3), "scale": (14, 14),  "dur_churn": (20, 30), "dur_drift": (30, 45), "drift_px": (12, 15), "noise_type": "turbulence"},
        "magical":        {"freq": (0.004, 0.008), "octaves": (2, 3), "scale": (12, 12),  "dur_churn": (22, 35), "dur_drift": (30, 50), "drift_px": (10, 12), "noise_type": "fractalNoise"},
        "space_nebula":   {"freq": (0.003, 0.006), "octaves": (2, 3), "scale": (10, 10),  "dur_churn": (30, 50), "dur_drift": (40, 60), "drift_px": (8, 10), "noise_type": "fractalNoise"},
        "thin_wispy":     {"freq": (0.008, 0.010), "octaves": (1, 2), "scale": (7, 7),    "dur_churn": (25, 40), "dur_drift": (35, 55), "drift_px": (7, 8),  "noise_type": "fractalNoise"},
    }.get(variant, {"freq": (0.005, 0.008), "octaves": (2, 2), "scale": (10, 10), "dur_churn": (25, 35), "dur_drift": (35, 50), "drift_px": (8, 10), "noise_type": "fractalNoise"})

    f_base = round(rng.uniform(*params["freq"]), 3)
    f_y = round(f_base * rng.uniform(1.2, 1.8), 3)
    octaves = rng.randint(*params["octaves"])
    scale_base = rng.randint(*params["scale"])
    dur_churn = rng.randint(*params["dur_churn"])
    dur_drift = rng.randint(*params["dur_drift"])
    drift_px = rng.randint(*params["drift_px"])
    noise_type = params["noise_type"]

    f_var = round(f_base * 0.2, 3)
    freq_vals = f"{f_base} {f_y}; {f_base + f_var:.3f} {f_y - f_var:.3f}; {f_base - f_var:.3f} {f_y + f_var:.3f}; {f_base + f_var * 0.5:.3f} {f_y - f_var * 0.3:.3f}; {f_base} {f_y}"
    s_lo = max(scale_base - 2, 3)
    s_hi = scale_base + 2
    scale_vals = f"{s_lo};{s_hi};{s_lo};{s_hi - 1};{s_lo}"

    splines = "0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1"
    drift_half = drift_px // 2
    return f'''    <filter id="{fid}" x="-10%" y="-5%" width="120%" height="110%">
      <feTurbulence type="{noise_type}" baseFrequency="{f_base} {f_y}" numOctaves="{octaves}" result="cloud-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur_churn}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="cloud-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{scale_vals}" dur="{dur_drift}s" repeatCount="indefinite"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["sky"] = _gen_filter_cloud_drift


def _gen_filter_fire_flicker(region, rng):
    """Fire flicker: brightness fluctuation + shape distortion."""
    rid = region["id"]
    fid = f"fire-flicker-{rid}"
    variant = region.get("context_variant", "candle")
    seed = rng.randint(1, 999)

    params = {
        "candle":          {"freq": (0.035, 0.050), "scale": (2, 3),  "bright_range": 0.10, "blue_base": 0.85, "dur_shape": (4, 5),   "dur_bright": (3.7, 4.7)},
        "lantern":         {"freq": (0.035, 0.045), "scale": (3, 5),  "bright_range": 0.12, "blue_base": 0.82, "dur_shape": (3.5, 4.5), "dur_bright": (3.3, 4.3)},
        "campfire":        {"freq": (0.040, 0.060), "scale": (4, 6),  "bright_range": 0.18, "blue_base": 0.78, "dur_shape": (2.5, 3.5), "dur_bright": (3.0, 4.0)},
        "torch":           {"freq": (0.040, 0.055), "scale": (4, 6),  "bright_range": 0.15, "blue_base": 0.80, "dur_shape": (3.0, 4.0), "dur_bright": (3.5, 4.5)},
        "bioluminescence": {"freq": (0.020, 0.035), "scale": (1, 3),  "bright_range": 0.08, "blue_base": 0.88, "dur_shape": (6, 8),   "dur_bright": (5.0, 7.0)},
    }.get(variant, {"freq": (0.035, 0.050), "scale": (2, 3), "bright_range": 0.10, "blue_base": 0.85, "dur_shape": (4, 5), "dur_bright": (3.7, 4.7)})

    freq_base = round(rng.uniform(*params["freq"]), 3)
    freq_y = round(freq_base * rng.uniform(1.5, 2.2), 3)
    scale_base = rng.randint(*params["scale"])
    dur_shape = round(rng.uniform(*params["dur_shape"]), 1)
    dur_bright = round(rng.uniform(*params["dur_bright"]), 1)
    br = params["bright_range"]
    blue_base = params["blue_base"]

    # Shape distortion animation values
    s_vals = ";".join(str(v) for v in [scale_base, scale_base + 3, scale_base - 1, scale_base + 2, scale_base, scale_base - 1, scale_base + 3, scale_base])
    # Brightness animation
    r_vals = f"1.0;{1.0 + br:.2f};{1.0 - br * 0.5:.2f};{1.0 + br * 0.8:.2f};{1.0 - br * 0.6:.2f};{1.0 + br * 0.3:.2f};1.0"
    g_vals = f"1.0;{1.0 + br * 0.7:.2f};{1.0 - br * 0.6:.2f};{1.0 + br * 0.6:.2f};{1.0 - br * 0.8:.2f};{1.0 + br * 0.2:.2f};1.0"
    b_vals = f"{blue_base};{blue_base - 0.05:.2f};{blue_base - 0.07:.2f};{blue_base - 0.03:.2f};{blue_base - 0.10:.2f};{blue_base - 0.05:.2f};{blue_base}"

    return f'''    <filter id="{fid}" x="-10%" y="-15%" width="120%" height="130%">
      <feTurbulence type="turbulence" baseFrequency="{freq_base} {freq_y}" numOctaves="3" result="flame-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_base} {freq_y}; {freq_base + 0.01:.3f} {freq_y - 0.01:.3f}; {freq_base - 0.005:.3f} {freq_y + 0.01:.3f}; {freq_base + 0.005:.3f} {freq_y - 0.005:.3f}; {freq_base} {freq_y}" dur="{dur_shape}s" repeatCount="indefinite"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="flame-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{s_vals}" dur="{dur_shape}s" repeatCount="indefinite"/>
      </feDisplacementMap>
      <feComponentTransfer>
        <feFuncR type="linear" slope="1.0"><animate attributeName="slope" values="{r_vals}" dur="{dur_bright}s" repeatCount="indefinite"/></feFuncR>
        <feFuncG type="linear" slope="1.0"><animate attributeName="slope" values="{g_vals}" dur="{dur_bright}s" repeatCount="indefinite"/></feFuncG>
        <feFuncB type="linear" slope="{blue_base}"><animate attributeName="slope" values="{b_vals}" dur="{dur_bright}s" repeatCount="indefinite"/></feFuncB>
      </feComponentTransfer>
    </filter>'''

FILTER_GENERATORS["fire"] = _gen_filter_fire_flicker


def _gen_filter_veg_sway(region, rng):
    """Vegetation sway: horizontal displacement for wind-through-leaves."""
    rid = region["id"]
    fid = f"veg-sway-{rid}"
    variant = region.get("context_variant", "branches")
    seed = rng.randint(1, 999)
    is_ground = region["type"] == "vegetation_ground"

    params = {
        "dense_canopy": {"freq_x": (0.005, 0.008), "scale": (8, 8),   "dur_freq": (12, 18), "dur_scale": (14, 20)},
        "branches":     {"freq_x": (0.010, 0.012), "scale": (6, 6),   "dur_freq": (10, 15), "dur_scale": (12, 18)},
        "tall_grass":   {"freq_x": (0.012, 0.018), "scale": (6, 6),   "dur_freq": (6, 10),  "dur_scale": (8, 12)},
        "flowers":      {"freq_x": (0.008, 0.012), "scale": (4, 4),   "dur_freq": (10, 16), "dur_scale": (12, 18)},
        "seaweed":      {"freq_x": (0.004, 0.008), "scale": (6, 6),   "dur_freq": (12, 20), "dur_scale": (14, 22)},
    }.get(variant, {"freq_x": (0.008, 0.012), "scale": (6, 6), "dur_freq": (10, 15), "dur_scale": (12, 18)})

    fx = round(rng.uniform(*params["freq_x"]), 3)
    fy = round(fx * rng.uniform(1.5, 2.2), 3)
    scale_base = rng.randint(*params["scale"])
    dur_freq = rng.randint(*params["dur_freq"])
    dur_scale = rng.randint(*params["dur_scale"])
    if dur_freq == dur_scale:
        dur_scale += 1
    # Ground vegetation: slightly delayed start, different seed
    begin = f'{rng.uniform(0.5, 1.5):.1f}s' if is_ground else "0s"

    fx_var = round(fx * 0.20, 3)
    freq_vals = f"{fx} {fy}; {fx + fx_var:.3f} {fy - fx_var:.3f}; {fx - fx_var:.3f} {fy + fx_var:.3f}; {fx + fx_var * 0.5:.3f} {fy - fx_var * 0.3:.3f}; {fx} {fy}"
    s_vals = f"{scale_base - 1};{scale_base + 1};{scale_base - 2};{scale_base + 1};{scale_base - 1};{scale_base + 2};{scale_base - 1}"
    # R/B channel = mostly horizontal sway
    ch_y = "B" if variant != "seaweed" else "G"

    splines = "0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"
    splines6 = "0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"
    return f'''    <filter id="{fid}" x="-5%" y="-5%" width="110%" height="110%">
      <feTurbulence type="fractalNoise" baseFrequency="{fx} {fy}" numOctaves="2" result="wind-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur_freq}s" begin="{begin}" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="wind-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="{ch_y}">
        <animate attributeName="scale" values="{s_vals}" dur="{dur_scale}s" begin="{begin}" repeatCount="indefinite" calcMode="spline" keySplines="{splines6}"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["vegetation_canopy"] = _gen_filter_veg_sway
FILTER_GENERATORS["vegetation_ground"] = _gen_filter_veg_sway


def _gen_filter_reflection_shimmer(region, rng):
    """Reflection shimmer: high-frequency low-amplitude distortion."""
    rid = region["id"]
    fid = f"shimmer-{rid}"
    variant = region.get("context_variant", "water_reflection")
    seed = rng.randint(1, 999)

    params = {
        "water_reflection": {"freq_x": (0.025, 0.035), "freq_y": (0.050, 0.070), "scale": (5, 5), "dur": (6, 8)},
        "crystal_ice":      {"freq_x": (0.035, 0.040), "freq_y": (0.060, 0.080), "scale": (4, 4), "dur": (5, 7)},
        "wet_surface":      {"freq_x": (0.030, 0.040), "freq_y": (0.050, 0.070), "scale": (3, 3), "dur": (6, 9)},
    }.get(variant, {"freq_x": (0.025, 0.035), "freq_y": (0.050, 0.070), "scale": (5, 5), "dur": (6, 8)})

    fx = round(rng.uniform(*params["freq_x"]), 3)
    fy = round(rng.uniform(*params["freq_y"]), 3)
    scale_base = rng.randint(*params["scale"])
    dur = rng.randint(*params["dur"])
    dur2 = dur + 1

    freq_vals = f"{fx} {fy}; {fx + 0.005:.3f} {fy - 0.005:.3f}; {fx - 0.003:.3f} {fy + 0.005:.3f}; {fx + 0.003:.3f} {fy - 0.002:.3f}; {fx} {fy}"
    s_vals = f"{scale_base};{scale_base + 2};{scale_base - 1};{scale_base + 1};{scale_base}"

    return f'''    <filter id="{fid}" x="-2%" y="-2%" width="104%" height="104%">
      <feTurbulence type="turbulence" baseFrequency="{fx} {fy}" numOctaves="2" result="shimmer-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur}s" repeatCount="indefinite"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="shimmer-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{s_vals}" dur="{dur2}s" repeatCount="indefinite"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["reflection"] = _gen_filter_reflection_shimmer


def _gen_filter_glow_pulse(region, rng):
    """Glow pulse: breathing pacer integrated into image glow sources."""
    rid = region["id"]
    fid = f"glow-pulse-{rid}"
    variant = region.get("context_variant", "moon")
    seed = rng.randint(1, 999)

    params = {
        "moon":            {"r_peak": (1.10, 1.15), "blur_peak": (0.5, 1.0), "blue_base": 0.88},
        "candle_area":     {"r_peak": (1.15, 1.20), "blur_peak": (1.0, 1.5), "blue_base": 0.82},
        "bioluminescence": {"r_peak": (1.20, 1.30), "blur_peak": (1.5, 2.5), "blue_base": 0.85},
        "window":          {"r_peak": (1.08, 1.12), "blur_peak": (0.3, 0.8), "blue_base": 0.90},
    }.get(variant, {"r_peak": (1.10, 1.20), "blur_peak": (0.5, 1.5), "blue_base": 0.85})

    r_peak = round(rng.uniform(*params["r_peak"]), 2)
    g_peak = round(r_peak - 0.05, 2)
    blur_peak = round(rng.uniform(*params["blur_peak"]), 1)
    blue_base = params["blue_base"]
    blue_inhale = round(blue_base - 0.05, 2)
    dur = 5  # Phase 1: 12 bpm breathing rate

    splines = "0.4 0 0.6 1;0.4 0 0.6 1"
    return f'''    <filter id="{fid}" x="-15%" y="-15%" width="130%" height="130%">
      <feComponentTransfer>
        <feFuncR type="linear" slope="1.0"><animate attributeName="slope" values="1.0;{r_peak};1.0" dur="{dur}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/></feFuncR>
        <feFuncG type="linear" slope="1.0"><animate attributeName="slope" values="1.0;{g_peak};1.0" dur="{dur}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/></feFuncG>
        <feFuncB type="linear" slope="{blue_base}"><animate attributeName="slope" values="{blue_base};{blue_inhale};{blue_base}" dur="{dur}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/></feFuncB>
      </feComponentTransfer>
      <feGaussianBlur stdDeviation="0">
        <animate attributeName="stdDeviation" values="0;{blur_peak};0" dur="{dur}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feGaussianBlur>
    </filter>'''

FILTER_GENERATORS["glow_source"] = _gen_filter_glow_pulse


def _gen_filter_fog_drift(region, rng):
    """Fog drift: displacement + horizontal translation for drifting mist."""
    rid = region["id"]
    fid = f"fog-drift-{rid}"
    variant = region.get("context_variant", "forest_mist")
    seed = rng.randint(1, 999)

    params = {
        "forest_mist":     {"freq": (0.005, 0.008), "scale": (7, 7),   "dur_churn": (18, 25), "dur_drift": (28, 40), "drift_px": (10, 12)},
        "mountain_cloud":  {"freq": (0.004, 0.007), "scale": (8, 8),   "dur_churn": (15, 25), "dur_drift": (25, 40), "drift_px": (12, 15)},
        "underwater_haze": {"freq": (0.003, 0.006), "scale": (5, 5),   "dur_churn": (22, 30), "dur_drift": (35, 50), "drift_px": (7, 8)},
        "cave_steam":      {"freq": (0.006, 0.010), "scale": (6, 6),   "dur_churn": (18, 25), "dur_drift": (25, 35), "drift_px": (8, 10)},
        "magical_shimmer": {"freq": (0.007, 0.010), "scale": (5, 5),   "dur_churn": (20, 28), "dur_drift": (30, 45), "drift_px": (8, 10)},
    }.get(variant, {"freq": (0.005, 0.008), "scale": (7, 7), "dur_churn": (18, 25), "dur_drift": (28, 40), "drift_px": (10, 12)})

    f_base = round(rng.uniform(*params["freq"]), 3)
    f_y = round(f_base * rng.uniform(1.3, 1.8), 3)
    scale_base = rng.randint(*params["scale"])
    dur_churn = rng.randint(*params["dur_churn"])
    dur_drift = rng.randint(*params["dur_drift"])
    drift_px = rng.randint(*params["drift_px"])

    f_var = round(f_base * 0.2, 3)
    freq_vals = f"{f_base} {f_y}; {f_base + f_var:.3f} {f_y - f_var:.3f}; {f_base - f_var:.3f} {f_y + f_var:.3f}; {f_base + f_var * 0.5:.3f} {f_y - f_var * 0.3:.3f}; {f_base} {f_y}"
    s_vals = f"{scale_base - 1};{scale_base + 1};{scale_base - 2};{scale_base + 1};{scale_base - 1}"

    splines = "0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1"
    return f'''    <filter id="{fid}" x="-15%" y="-5%" width="130%" height="110%">
      <feTurbulence type="fractalNoise" baseFrequency="{f_base} {f_y}" numOctaves="2" result="fog-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur_churn}s" repeatCount="indefinite" calcMode="spline" keySplines="{splines}"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="fog-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{s_vals}" dur="{dur_drift}s" repeatCount="indefinite"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["fog_zone"] = _gen_filter_fog_drift


def _gen_filter_smoke_rise(region, rng):
    """Smoke rise: displacement + upward translation."""
    rid = region["id"]
    fid = f"smoke-rise-{rid}"
    seed = rng.randint(1, 999)

    f_base = round(rng.uniform(0.008, 0.015), 3)
    f_y = round(f_base * rng.uniform(1.5, 2.2), 3)
    scale_base = rng.randint(6, 6)
    dur_churn = rng.randint(10, 18)
    dur_rise = rng.randint(15, 25)

    f_var = round(f_base * 0.2, 3)
    freq_vals = f"{f_base} {f_y}; {f_base + f_var:.3f} {f_y - f_var:.3f}; {f_base - f_var:.3f} {f_y + f_var:.3f}; {f_base + f_var * 0.5:.3f} {f_y - f_var * 0.3:.3f}; {f_base} {f_y}"
    s_vals = f"{scale_base - 1};{scale_base + 1};{scale_base - 2};{scale_base + 1};{scale_base - 1}"

    return f'''    <filter id="{fid}" x="-10%" y="-20%" width="120%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="{f_base} {f_y}" numOctaves="2" result="smoke-noise" seed="{seed}">
        <animate attributeName="baseFrequency" values="{freq_vals}" dur="{dur_churn}s" repeatCount="indefinite"/>
      </feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="smoke-noise" scale="{scale_base}" xChannelSelector="R" yChannelSelector="G">
        <animate attributeName="scale" values="{s_vals}" dur="{dur_rise}s" repeatCount="indefinite"/>
      </feDisplacementMap>
    </filter>'''

FILTER_GENERATORS["smoke"] = _gen_filter_smoke_rise


# ── V3 Cinemagraph: Assembly Functions ────────────────────────────────────

# Lean overlay: elements handled by cinemagraph filters, removed from overlay pools
_FILTER_HANDLED_ELEMENTS = {"fog", "caustics", "water_ripples", "candle_flicker", "shadow_play", "chimney_smoke", "wind_grass"}

WORLD_ELEMENTS_LEAN = {}
for _ws, _mapping in WORLD_ELEMENTS.items():
    _lean = {}
    for _layer in ("background", "midground", "foreground"):
        if _layer in _mapping:
            _lean[_layer] = {
                "pool": [e for e in _mapping[_layer]["pool"] if e not in _FILTER_HANDLED_ELEMENTS],
                "pick": _mapping[_layer]["pick"],
            }
            # Reduce pick counts since fewer elements available
            _available = len(_lean[_layer]["pool"])
            _min_pick = min(_lean[_layer]["pick"][0], _available)
            _max_pick = min(_lean[_layer]["pick"][1], _available)
            _lean[_layer]["pick"] = (max(1, _min_pick), max(1, _max_pick))
    _lean["required"] = _mapping.get("required", [])
    _lean["fauna"] = _mapping.get("fauna", [])
    _lean["rare_event"] = _mapping.get("rare_event", [])
    _lean["vignette"] = _mapping.get("vignette", "full_soft")
    _lean["pacer_variant"] = _mapping.get("pacer_variant", "forest")
    WORLD_ELEMENTS_LEAN[_ws] = _lean


def generate_v3_filters_and_masks(world_setting, rng, composition=None):
    """Generate all cinemagraph filter and mask definitions for a world setting.

    Returns dict with 'defs_svg' (combined <filter> and <mask> SVG),
    'regions' (list of region dicts with filter/mask ids), and metadata.
    Enforces performance budget: max 4 filters, combined numOctaves <= 12.
    Character exclusion zone is applied to all masks based on composition.
    """
    regions = REGION_TEMPLATES.get(world_setting, REGION_TEMPLATES["enchanted_forest"])

    # Performance budget
    MAX_FILTERS = 4
    MAX_OCTAVES = 12

    # Prioritize: primary first, then glow_source, then others
    sorted_regions = sorted(regions, key=lambda r: (
        0 if r.get("is_primary") else (1 if r["type"] == "glow_source" else 2)
    ))

    active_regions = []
    total_octaves = 0
    filters_svg = []
    masks_svg = []

    for region in sorted_regions:
        if len(active_regions) >= MAX_FILTERS:
            break

        rtype = region["type"]
        gen_fn = FILTER_GENERATORS.get(rtype)
        if not gen_fn:
            continue

        # Generate filter
        filter_svg = gen_fn(region, rng)

        # Estimate octaves from this filter (most use 2-3)
        octaves_est = 3 if rtype == "fire" else 2
        if total_octaves + octaves_est > MAX_OCTAVES:
            continue

        total_octaves += octaves_est

        # Generate mask with character exclusion zone
        mask_svg = _generate_mask_element(region, rng, composition=composition)

        filters_svg.append(filter_svg)
        masks_svg.append(mask_svg)
        active_regions.append(region)

    # Combine into defs block
    defs_parts = []
    for m in masks_svg:
        defs_parts.append(m)
    for f in filters_svg:
        defs_parts.append(f)

    return {
        "defs_svg": "\n".join(defs_parts),
        "regions": active_regions,
        "total_octaves": total_octaves,
        "filter_count": len(active_regions),
    }


def generate_lean_overlay(axes, story):
    """Generate a lean SMIL overlay — only elements not handled by cinemagraph filters.

    Reuses existing ELEMENT_GENERATORS but with reduced pools (no fog, caustics,
    water_ripples, candle_flicker, shadow_play, chimney_smoke, wind_grass).
    """
    world = axes["world_setting"]
    palette = axes["palette"]
    rng = random.Random(_stable_seed(story.get("id", "") + world + "_lean"))
    mapping = WORLD_ELEMENTS_LEAN.get(world, WORLD_ELEMENTS_LEAN.get("enchanted_forest", {}))

    # Build colors (same as generate_svg_overlay)
    palette_colors = {
        "ember_warm":    {"glow": "#FFD699", "particle": "#FFCC80", "vignette": "#1a0a05", "star": "#FFF5E0"},
        "twilight_cool": {"glow": "#C8B8E0", "particle": "#D0C4E8", "vignette": "#0a0520", "star": "#E8E0F0"},
        "forest_deep":   {"glow": "#A8D5A0", "particle": "#C4E0B8", "vignette": "#051005", "star": "#D8F0D0"},
        "golden_hour":   {"glow": "#FFE4B5", "particle": "#FFD89B", "vignette": "#1a0f00", "star": "#FFF8E8"},
        "moonstone":     {"glow": "#C0D0E0", "particle": "#B8C8D8", "vignette": "#050810", "star": "#E0E8F0"},
        "berry_dusk":    {"glow": "#D8A8C8", "particle": "#E0B8D0", "vignette": "#100510", "star": "#F0D8E8"},
    }
    colors = palette_colors.get(palette, palette_colors["golden_hour"])
    accents = world_accents.get(world, {})
    if accents:
        colors = {**colors, **accents}

    element_parts = []
    budget_remaining = 4000  # Reduced from 6600 — lean overlay is smaller

    def _pick_lean(layer_key):
        nonlocal budget_remaining
        layer = mapping.get(layer_key)
        if not layer or not layer.get("pool"):
            return
        pool = layer["pool"][:]
        rng.shuffle(pool)
        pick_min, pick_max = layer["pick"]
        pick_count = rng.randint(pick_min, pick_max)

        selected = 0
        for elem_name in pool:
            if selected >= pick_count or budget_remaining < 150:
                break
            if elem_name not in ELEMENT_GENERATORS:
                continue
            svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
            size = _svg_size(svg)
            if budget_remaining - size >= 0:
                element_parts.append(svg)
                budget_remaining -= size
                selected += 1

    # Required: breathing pacer
    for elem_name in mapping.get("required", []):
        if elem_name not in ELEMENT_GENERATORS:
            continue
        svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
        element_parts.append(svg)
        budget_remaining -= _svg_size(svg)

    _pick_lean("background")
    _pick_lean("midground")
    _pick_lean("foreground")

    # Fauna
    fauna_pool = [f for f in mapping.get("fauna", []) if f in ELEMENT_GENERATORS]
    if fauna_pool:
        rng.shuffle(fauna_pool)
        fauna_count = min(rng.randint(1, 2), len(fauna_pool))
        for elem_name in fauna_pool[:fauna_count]:
            if budget_remaining < 150:
                break
            svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
            size = _svg_size(svg)
            if budget_remaining - size >= 0:
                element_parts.append(svg)
                budget_remaining -= size

    # Rare event
    rare_pool = [r for r in mapping.get("rare_event", []) if r in ELEMENT_GENERATORS]
    if rare_pool and rng.random() < 0.95 and budget_remaining >= 250:
        svg = ELEMENT_GENERATORS[rng.choice(rare_pool)](colors, world, story, rng)
        size = _svg_size(svg)
        if budget_remaining - size >= 0:
            element_parts.append(svg)
            budget_remaining -= size

    # Vignette
    vig_style = mapping.get("vignette", "full_soft")
    vig = _gen_vignette(vig_style, colors)
    if vig:
        element_parts.append(vig)

    return "\n".join(element_parts)


def generate_v3_combined_svg(bg_b64, axes, story):
    """Create 3-layer V3 SVG: cinemagraph filters on background + lean SMIL overlay.

    Args:
        bg_b64: Base64-encoded WebP image data (no data: prefix)
        axes: Diversity axes dict (must have 'world_setting')
        story: Story dict

    Returns:
        Complete SVG string with embedded background, filters, masks, and overlay.
    """
    world = axes["world_setting"]
    rng = random.Random(_stable_seed(story.get("id", "") + world + "_v3"))

    # Generate cinemagraph filters and masks
    composition = axes.get("composition")
    fm = generate_v3_filters_and_masks(world, rng, composition=composition)

    # Generate full rich overlay (same as v2 but layered on top of cinemagraph filters)
    # The full overlay follows the revised SMIL guidelines: 12-20 elements, 3 depth layers,
    # breathing pacer, fauna, rare events, etc. Cinemagraph filters add image-level motion
    # underneath — they complement, not replace, the SMIL overlay.
    full_overlay_svg = generate_svg_overlay(axes, story)
    # Extract inner content (strip the <svg> wrapper since V3 has its own)
    import re as _re
    _inner_match = _re.search(r'<svg[^>]*>(.*)</svg>', full_overlay_svg, _re.DOTALL)
    overlay_content = _inner_match.group(1) if _inner_match else full_overlay_svg

    # Build the <use> elements for filtered regions
    use_elements = []
    for region in fm["regions"]:
        rid = region["id"]
        rtype = region["type"]
        # Map type to filter id prefix
        filter_prefixes = {
            "water": "water-flow", "sky": "cloud-drift", "fire": "fire-flicker",
            "vegetation_canopy": "veg-sway", "vegetation_ground": "veg-sway",
            "reflection": "shimmer", "glow_source": "glow-pulse",
            "fog_zone": "fog-drift", "smoke": "smoke-rise",
        }
        fid_prefix = filter_prefixes.get(rtype, rtype)
        fid = f"{fid_prefix}-{rid}"

        # Fog/smoke get additional drift animateTransform on the <use>
        drift_transform = ""
        if rtype == "fog_zone":
            drift_px = rng.randint(10, 12)
            drift_dur = rng.randint(28, 45)
            drift_half = drift_px // 2
            drift_transform = f'''
      <animateTransform attributeName="transform" type="translate" values="0,0; {drift_px},1; 0,0; -{drift_half},-1; 0,0" dur="{drift_dur}s" repeatCount="indefinite" calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1"/>'''
        elif rtype == "smoke":
            rise_y = rng.randint(3, 8)
            lateral_x = rng.randint(2, 5)
            rise_dur = rng.randint(15, 25)
            drift_transform = f'''
      <animateTransform attributeName="transform" type="translate" values="0,0; {lateral_x},{-rise_y}; 0,0; {-lateral_x // 2},{-rise_y // 2}; 0,0" dur="{rise_dur}s" repeatCount="indefinite" calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1"/>'''
        elif rtype == "sky":
            # Cloud drift: horizontal translate
            drift_px = rng.randint(10, 10)
            drift_dur = rng.randint(35, 55)
            drift_transform = f'''
      <animateTransform attributeName="transform" type="translate" values="0,0; {drift_px},0; 0,0; {-drift_px // 2},0; 0,0" dur="{drift_dur}s" repeatCount="indefinite" calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1;0.3 0 0.7 1"/>'''

        use_elements.append(f'''  <g mask="url(#mask-{rid})">
    <use href="#bg" filter="url(#{fid})"/>{drift_transform}
  </g>''')

    # Assemble final SVG
    axes_comment = json.dumps(axes, separators=(',', ':'))
    svg = f'''<!-- axes: {axes_comment} -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <image id="bg" width="512" height="512" href="data:image/webp;base64,{bg_b64}"/>
{fm["defs_svg"]}
  </defs>

  <!-- Layer 1: Static background -->
  <use href="#bg"/>

  <!-- Layer 2: Cinemagraph filtered regions ({fm["filter_count"]} filters, {fm["total_octaves"]} octaves) -->
{chr(10).join(use_elements)}

  <!-- Layer 3: Full SMIL overlay (12-20 elements, 3 depth layers) -->
{overlay_content}
</svg>'''

    return svg


# ── SVG Overlay Generator (SMIL Animation Bible v2) ──────────────────────
#
# Implements the 7-category element library from smil-animation-bible.md:
#   A. Celestial: stars, shooting_star, moon_glow, aurora
#   B. Atmospheric: fog, rain, snowfall, dust_motes, caustics
#   C. Flora: swaying_branches, falling_leaves, closing_flowers
#   D. Fauna: fireflies, sleeping_butterfly, sleeping_owl, cricket
#   E. Water: water_ripples, bubbles
#   F. Light & Shadow: candle_flicker, shadow_play, breathing_pacer
#   G. Environmental: chimney_smoke, wind_grass
#
# Every generator: _gen_<element>(colors, world, story, rng) -> str
# Assembly: WORLD_ELEMENTS with required/select/optional, <5KB budget.

import re as _re

# ── SMIL Helper Functions ────────────────────────────────────────────────

PRIME_DURATIONS = [5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]

_BIBLE_COLORS = {
    "star":   ["#FFF5E0", "#FFE8CC", "#FFEFD5", "#FFF0DB", "#FFE4B5"],
    "glow":   ["#FFD89C", "#FFE4B5", "#FFD080", "#FFBA60", "#FFCA78"],
    "fog":    ["#F5E6D3", "#EDE0D0", "#F0E4D6", "#D4C8B8", "#E8D8C4"],
    "leaf":   ["#C4956A", "#B8845A", "#D4A878", "#C8A060"],
    "shadow": ["#1A0F05", "#2A1F14", "#3D2B1F", "#4A3828"],
    "flora":  ["#D4A0B8", "#C890A8", "#C8A080"],
    "rain":   ["#D4C8B8", "#C8BCA8", "#D0C4B0"],
    "aurora":  ["#D4C8A0", "#D4B8A0", "#E0C8A0", "#C8B0A0", "#D0C0A0"],
    "snow":   ["#FFF8F0", "#FFF0E0", "#FFF0D0"],
    "branch": ["#2A1F14", "#3D2B1F", "#4A3828"],
    "smoke":  ["#D4C8B8", "#C8BCA8", "#D0C4B0"],
}


def _smil_spline(n_segments):
    """Return keySplines attr value with n copies of gentle ease-in-out."""
    return ";".join(["0.4 0 0.6 1"] * n_segments)


def _pick_prime_dur(lo, hi, rng):
    """Return a prime-number duration in [lo, hi] to prevent sync."""
    candidates = [p for p in PRIME_DURATIONS if lo <= p <= hi]
    return rng.choice(candidates) if candidates else round(rng.uniform(lo, hi), 1)


def _fade_values(peak, steps=5):
    """Generate semicolon-joined opacity fade: 0 -> peak -> 0."""
    if steps == 3:
        return f"0;{peak:.2f};0"
    if steps == 5:
        return f"0;{peak * 0.4:.2f};{peak:.2f};{peak * 0.6:.2f};0"
    vals = []
    mid = steps // 2
    for i in range(steps):
        if i <= mid:
            vals.append(f"{peak * i / mid:.2f}")
        else:
            remaining = steps - 1 - mid
            vals.append(f"{peak * (steps - 1 - i) / remaining:.2f}" if remaining else "0")
    return ";".join(vals)


def _warm_color(rng, palette="glow"):
    """Pick a random warm color from the Bible's palette tables."""
    return rng.choice(_BIBLE_COLORS.get(palette, _BIBLE_COLORS["glow"]))


def _svg_size(svg_str):
    """Return byte count for budget tracking."""
    return len(svg_str.encode("utf-8"))


# World-specific warm-spectrum color overrides (drowsiness guardrail)
world_accents = {
    "deep_ocean":       {"particle": "#FFB74D", "glow": "#FF8F00", "accent": "#FFA726", "star": "#FFF5E0"},
    "cloud_kingdom":    {"particle": "#FFF8E1", "glow": "#FFE0B2", "accent": "#FFECB3", "star": "#FFF8E8"},
    "enchanted_forest": {"particle": "#FFD54F", "glow": "#FFA000", "accent": "#FFCA28", "star": "#FFECD2"},
    "snow_landscape":   {"particle": "#FFF3E0", "glow": "#FFE0B2", "accent": "#FFE8CC", "star": "#FFF8E8"},
    "desert_night":     {"particle": "#FFAB00", "glow": "#FF6D00", "accent": "#FF9100", "star": "#FFF5E0"},
    "cozy_interior":    {"particle": "#FFD54F", "glow": "#FFB300", "accent": "#FFC107", "star": "#FFF8E8"},
    "mountain_meadow":  {"particle": "#FFE082", "glow": "#FFD54F", "accent": "#FFCA28", "star": "#FFF5E0"},
    "space_cosmos":     {"particle": "#FFD180", "glow": "#FFB74D", "accent": "#FFCC80", "star": "#FFECD2"},
    "tropical_lagoon":  {"particle": "#FF6E40", "glow": "#FF3D00", "accent": "#FF8A65", "star": "#FFF5E0"},
    "underground_cave": {"particle": "#FFB74D", "glow": "#FF8F00", "accent": "#FFA726", "star": "#FFECD2"},
    "ancient_library":  {"particle": "#FFE082", "glow": "#FFA000", "accent": "#FFD740", "star": "#FFF8E8"},
    "floating_islands": {"particle": "#FFAB91", "glow": "#FF8A65", "accent": "#FFCCBC", "star": "#FFF5E0"},
}


# ── Category A: Celestial ────────────────────────────────────────────────

def _gen_stars(colors, world, story, rng):
    """A1. Twinkling stars — warm points fading in/out at staggered intervals.
    5-10 stars, upper 40%, 4-8s durations, peak 0.30-0.70.
    """
    count = rng.randint(5, 10)
    parts = ['<!-- A1: Twinkling Stars -->\n<g id="stars">']
    star_colors = _BIBLE_COLORS["star"]
    for i in range(count):
        cx = rng.randint(5, 95)
        cy = rng.randint(5, 40)
        r = round(rng.uniform(1.0, 3.0), 1)
        color = rng.choice(star_colors)
        dur = round(rng.uniform(4, 8), 1)
        begin = round(rng.uniform(0, 10), 1)
        peak = round(rng.uniform(0.30, 0.70), 2)
        vals = f"0;0;{peak:.2f};{peak * 0.7:.2f};0"
        n_seg = len(vals.split(";")) - 1
        parts.append(
            f'  <circle cx="{cx}%" cy="{cy}%" r="{r}" fill="{color}">\n'
            f'    <animate attributeName="opacity" values="{vals}"\n'
            f'      dur="{dur}s" begin="{begin}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(n_seg)}"/>\n'
            f'  </circle>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_shooting_star(colors, world, story, rng):
    """A2. Shooting star — single soft streak, appears once per 30-90s.
    Always arcs downward. 5-7s visible portion. Peak 0.50-0.80.
    """
    interval = rng.randint(30, 90)
    vis_dur = round(rng.uniform(5, 7), 1)
    x1 = rng.randint(-50, 50)
    y1 = rng.randint(-30, 20)
    x2 = rng.randint(200, 350)
    y2 = rng.randint(50, 100)
    xm = (x1 + x2) // 2 + rng.randint(-30, 30)
    ym = (y1 + y2) // 2 + rng.randint(-10, 10)
    path = f"M{x1},{y1} Q{xm},{ym} {x2},{y2}"
    color_head = _warm_color(rng, "star")
    color_tail = _warm_color(rng, "glow")
    # Mostly invisible with brief bright flash
    peak = round(rng.uniform(0.50, 0.80), 2)
    vis_vals = f"0;0;{peak};{peak};0;0;0;0;0;0;0;0;0"
    n_seg = 12
    return (
        f'<!-- A2: Shooting Star -->\n'
        f'<g id="shooting-star" opacity="0">\n'
        f'  <line x1="0" y1="0" x2="-20" y2="-8" stroke="{color_tail}" stroke-width="1.5"\n'
        f'    stroke-linecap="round" opacity="0.5"/>\n'
        f'  <circle cx="0" cy="0" r="2" fill="{color_head}" opacity="0.6"/>\n'
        f'  <circle cx="0" cy="0" r="5" fill="{color_tail}" opacity="0.15"/>\n'
        f'  <animateMotion dur="{vis_dur}s" begin="{interval}s" repeatCount="indefinite"\n'
        f'    path="{path}"\n'
        f'    calcMode="spline" keySplines="0.2 0 0.8 1"/>\n'
        f'  <animate attributeName="opacity" values="{vis_vals}"\n'
        f'    dur="{interval}s" begin="0s" repeatCount="indefinite"\n'
        f'    calcMode="spline" keySplines="{_smil_spline(n_seg)}"/>\n'
        f'</g>'
    )


def _gen_moon_glow(colors, world, story, rng):
    """A3. Crescent moon glow — soft warm radial in upper 25%, breathing pulse 7-10s.
    Opacity 0.30-0.60.
    """
    cx = rng.randint(65, 85)
    cy = rng.randint(8, 22)
    halo_r = rng.randint(40, 80)
    dur = _pick_prime_dur(7, 11, rng)
    halo_color = colors.get("glow", _warm_color(rng, "glow"))
    core_color = colors.get("star", _warm_color(rng, "star"))
    r_lo = halo_r - 5
    r_hi = halo_r + 10
    core_r = rng.randint(14, 22)
    grad_id = f"moonH{rng.randint(100, 999)}"
    return (
        f'<!-- A3: Moon Glow -->\n'
        f'<g id="moon-glow">\n'
        f'  <radialGradient id="{grad_id}">\n'
        f'    <stop offset="0%" stop-color="{core_color}" stop-opacity="0.35"/>\n'
        f'    <stop offset="40%" stop-color="{halo_color}" stop-opacity="0.15"/>\n'
        f'    <stop offset="100%" stop-color="{halo_color}" stop-opacity="0"/>\n'
        f'  </radialGradient>\n'
        f'  <circle cx="{cx}%" cy="{cy}%" r="{halo_r}" fill="url(#{grad_id})">\n'
        f'    <animate attributeName="r" values="{r_lo};{r_hi};{r_lo}" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'    <animate attributeName="opacity" values="0.30;0.60;0.30" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'  </circle>\n'
        f'  <circle cx="{cx}%" cy="{cy}%" r="{core_r}" fill="{core_color}" opacity="0.20">\n'
        f'    <animate attributeName="opacity" values="0.15;0.25;0.15" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'  </circle>\n'
        f'</g>'
    )


def _gen_aurora(colors, world, story, rng):
    """A4. Aurora / Northern Lights — slow undulating bands, upper 30%.
    2-3 bands, radialGradient fills for soft edges on FLUX backgrounds.
    20-35s durations. Opacity 0.12-0.25.
    """
    count = rng.randint(2, 3)
    uid = rng.randint(100, 999)
    aurora_colors = _BIBLE_COLORS["aurora"]
    # Build gradient defs and ellipses
    defs_parts = []
    ellipse_parts = []
    for i in range(count):
        gid = f"aur-g{uid}-{i}"
        cx = rng.randint(35, 65)
        cy = rng.randint(10, 25)
        rx = rng.randint(120, 180)
        ry = rng.randint(18, 35)
        color = rng.choice(aurora_colors)
        op_base = round(rng.uniform(0.10, 0.18), 2)
        dur_t = _pick_prime_dur(19, 37, rng)
        dur_o = _pick_prime_dur(23, 37, rng)
        dur_ry = _pick_prime_dur(19, 31, rng)
        tx1, ty1 = rng.randint(10, 20), rng.randint(2, 6)
        tx2, ty2 = rng.randint(-15, -5), rng.randint(1, 5)
        tx3, ty3 = rng.randint(3, 8), rng.randint(-3, -1)
        op_hi = min(op_base + 0.08, 0.25)
        op_vals = f"{op_base:.2f};{op_base + 0.06:.2f};{op_base + 0.02:.2f};{op_hi:.2f};{op_base:.2f}"
        ry_vals = f"{ry - 3};{ry + 5};{ry - 4};{ry + 3};{ry - 3}"
        # Radial gradient: center color fades to transparent at edges
        defs_parts.append(
            f'  <radialGradient id="{gid}">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.6"/>'
            f'<stop offset="50%" stop-color="{color}" stop-opacity="0.3"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
            f'</radialGradient>'
        )
        ellipse_parts.append(
            f'  <ellipse cx="{cx}%" cy="{cy}%" rx="{rx}" ry="{ry}" fill="url(#{gid})" opacity="{op_base:.2f}">\n'
            f'    <animateTransform attributeName="transform" type="translate"\n'
            f'      values="0,0; {tx1},{ty1}; {tx2},{ty2}; {tx3},{ty3}; 0,0" dur="{dur_t}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'    <animate attributeName="opacity" values="{op_vals}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="ry" values="{ry_vals}"\n'
            f'      dur="{dur_ry}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts = [f'<!-- A4: Aurora -->\n<g id="aurora-{uid}">']
    parts.append(f'  <defs>{"".join(defs_parts)}</defs>')
    parts.extend(ellipse_parts)
    parts.append('</g>')
    return "\n".join(parts)


# ── Category B: Atmospheric ──────────────────────────────────────────────

def _gen_fog(colors, world, story, rng):
    """B1. Drifting fog/mist — large shapes, lower 55-85%.
    2-3 layers, radialGradient fills for soft edges on FLUX backgrounds.
    30-50s cycles, 0.06-0.15 opacity, alternate directions.
    """
    count = rng.randint(2, 3)
    uid = rng.randint(100, 999)
    fog_colors = _BIBLE_COLORS["fog"]
    defs_parts = []
    ellipse_parts = []
    for i in range(count):
        gid = f"fog-g{uid}-{i}"
        cx = rng.randint(20, 80)
        cy = rng.randint(55, 85)
        rx = rng.randint(160, 280)
        ry = rng.randint(25, 50)
        color = rng.choice(fog_colors)
        op_base = round(rng.uniform(0.06, 0.12), 2)
        dur_t = _pick_prime_dur(29, 47, rng)
        dur_o = _pick_prime_dur(31, 47, rng)
        drift = rng.randint(50, 100) * (1 if i % 2 == 0 else -1)
        op_hi = min(op_base + 0.05, 0.15)
        op_vals = f"{op_base:.2f};{op_base + 0.03:.2f};{op_base + 0.01:.2f};{op_hi:.2f};{op_base:.2f}"
        # Radial gradient: soft center to fully transparent edges
        defs_parts.append(
            f'  <radialGradient id="{gid}">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.5"/>'
            f'<stop offset="40%" stop-color="{color}" stop-opacity="0.25"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
            f'</radialGradient>'
        )
        ellipse_parts.append(
            f'  <ellipse cx="{cx}%" cy="{cy}%" rx="{rx}" ry="{ry}" fill="url(#{gid})" opacity="{op_base:.2f}">\n'
            f'    <animateTransform attributeName="transform" type="translate"\n'
            f'      values="0,0; {drift},3; {drift * 2},0; {drift},-3; 0,0"\n'
            f'      dur="{dur_t}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'    <animate attributeName="opacity" values="{op_vals}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts = [f'<!-- B1: Drifting Fog -->\n<g id="fog-{uid}">']
    parts.append(f'  <defs>{"".join(defs_parts)}</defs>')
    parts.extend(ellipse_parts)
    parts.append('</g>')
    return "\n".join(parts)


def _gen_rain(colors, world, story, rng):
    """B2. Gentle rain — thin lines drifting down at slight angle.
    6-10 drops, 3-8 deg leftward, warm grey, 3.5-5.5s. Opacity 0.20-0.40.
    """
    count = rng.randint(6, 10)
    parts = ['<!-- B2: Gentle Rain -->\n<g id="rain" opacity="0.25">']
    rain_colors = _BIBLE_COLORS["rain"]
    for i in range(count):
        x = rng.randint(5, 95)
        color = rng.choice(rain_colors)
        dur = round(rng.uniform(3.5, 5.5), 1)
        begin = round(rng.uniform(0, 4), 1)
        width = round(rng.uniform(0.4, 0.8), 1)
        angle_drift = rng.randint(-12, -4)
        op = round(rng.uniform(0.20, 0.40), 2)
        parts.append(
            f'  <line x1="{x}%" y1="-5%" x2="{x - 1}%" y2="2%" stroke="{color}" stroke-width="{width}"\n'
            f'    stroke-linecap="round" opacity="{op}">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite"\n'
            f'      path="M0,0 L{angle_drift},300" begin="{begin}s"/>\n'
            f'    <animate attributeName="opacity" values="0;{op};{op};0" dur="{dur}s"\n'
            f'      repeatCount="indefinite" begin="{begin}s"/>\n'
            f'  </line>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_snowfall(colors, world, story, rng):
    """B3. Falling snow — soft circles in wandering bezier paths downward.
    5-8 flakes, 12-22s, unique paths. Opacity 0.25-0.55.
    """
    count = rng.randint(5, 8)
    parts = ['<!-- B3: Falling Snow -->\n<g id="snowfall" opacity="0.40">']
    snow_colors = _BIBLE_COLORS["snow"]
    for i in range(count):
        r = round(rng.uniform(1.5, 4.0), 1)
        color = rng.choice(snow_colors)
        dur = round(rng.uniform(12, 22), 1)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.25, 0.55), 2)
        sx = rng.randint(50, 460)
        # Build wandering bezier downward
        points = []
        y = -20
        for j in range(6):
            y += rng.randint(50, 80)
            x_d = rng.randint(-30, 30)
            points.append(f"{sx + x_d},{y}")
        path = f"M{sx},-20 C{points[0]} {points[1]} {points[2]} S{points[3]} {points[4]}"
        n_seg = 4  # C has 3 segments, S adds 1
        parts.append(
            f'  <circle cx="0" cy="0" r="{r}" fill="{color}" opacity="{op}">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(n_seg)}"/>\n'
            f'    <animate attributeName="opacity" values="0;{op};{op};{op * 0.85:.2f};0"\n'
            f'      dur="{dur}s" repeatCount="indefinite" begin="{begin}s"/>\n'
            f'  </circle>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_dust_motes(colors, world, story, rng):
    """B4. Floating dust motes — particles drifting in light area.
    4-8 motes, non-directional, 10-20s, opacity 0.25-0.55.
    """
    count = rng.randint(4, 8)
    mote_id = f"dust-motes-{rng.randint(100, 999)}"
    parts = [f'<!-- B4: Dust Motes -->\n<g id="{mote_id}">']
    mote_color = colors.get("particle", "#FFE8C8")
    for i in range(count):
        r = round(rng.uniform(1.0, 2.0), 1)
        dur = _pick_prime_dur(11, 19, rng)
        begin = round(rng.uniform(0, 6), 1)
        peak_op = round(rng.uniform(0.25, 0.55), 2)
        cx = rng.randint(100, 400)
        cy = rng.randint(100, 350)
        # Micro-drift path (non-directional)
        pts = []
        for j in range(6):
            pts.append(f"{cx + rng.randint(-15, 15)},{cy + rng.randint(-12, 12)}")
        path = f"M{cx},{cy} C{pts[0]} {pts[1]} {pts[2]} S{pts[3]} {pts[4]}"
        op_vals = f"0;{peak_op:.2f};{peak_op * 0.5:.2f};{peak_op:.2f};{peak_op * 0.4:.2f};0"
        parts.append(
            f'  <circle cx="0" cy="0" r="{r}" fill="{mote_color}" opacity="0">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"/>\n'
            f'    <animate attributeName="opacity" values="{op_vals}"\n'
            f'      dur="{dur}s" repeatCount="indefinite" begin="{begin}s"/>\n'
            f'  </circle>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_caustics(colors, world, story, rng):
    """B5. Underwater caustics — slow-moving light patterns.
    2-4 patterns, all properties on different prime durations. Opacity 0.10-0.25.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- B5: Underwater Caustics -->\n<g id="caustics" opacity="0.18">']
    caustic_color = colors.get("glow", "#FFE8C8")
    for i in range(count):
        cx = rng.randint(25, 75)
        cy = rng.randint(40, 80)
        rx = rng.randint(30, 60)
        ry = rng.randint(18, 35)
        op = round(rng.uniform(0.10, 0.25), 2)
        dur_rx = _pick_prime_dur(13, 23, rng)
        dur_ry = _pick_prime_dur(17, 29, rng)
        dur_t = _pick_prime_dur(19, 31, rng)
        dur_o = _pick_prime_dur(17, 23, rng)
        tx, ty = rng.randint(5, 15), rng.randint(3, 8)
        parts.append(
            f'  <ellipse cx="{cx}%" cy="{cy}%" rx="{rx}" ry="{ry}" fill="{caustic_color}" opacity="{op}">\n'
            f'    <animate attributeName="rx" values="{rx - 5};{rx + 5};{rx - 2};{rx + 8};{rx - 5}" dur="{dur_rx}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="ry" values="{ry - 3};{ry + 5};{ry - 5};{ry + 3};{ry - 3}" dur="{dur_ry}s" repeatCount="indefinite"/>\n'
            f'    <animateTransform attributeName="transform" type="translate"\n'
            f'      values="0,0; {tx},{ty}; {-tx // 2},{ty + 3}; {tx - 3},{-ty // 2}; 0,0" dur="{dur_t}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="opacity" values="{op:.2f};{min(op + 0.06, 0.25):.2f};{op + 0.02:.2f};{min(op + 0.08, 0.25):.2f};{op:.2f}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


# ── Category C: Flora ────────────────────────────────────────────────────

def _gen_swaying_branches(colors, world, story, rng):
    """C1. Swaying branches — silhouettes at frame edges, 2-5 deg, 5-10s.
    Opacity 0.15-0.35.
    """
    edges = rng.sample(["left", "right"], k=rng.randint(1, 2))
    branch_color = _warm_color(rng, "branch")
    parts = ['<!-- C1: Swaying Branches -->']
    for edge in edges:
        dur = round(rng.uniform(5, 10), 1)
        sway = rng.randint(2, 5)
        op = round(rng.uniform(0.15, 0.35), 2)
        gid = f"branch-{edge}"
        if edge == "left":
            py = rng.randint(80, 160)
            d = f"M0,{py} Q{rng.randint(12, 25)},{py - 30} {rng.randint(10, 20)},{py - 60} Q{rng.randint(20, 35)},{py - 80} {rng.randint(15, 25)},{py - 100}"
            anchor = f"0,{py}"
            leaf_cx, leaf_cy = rng.randint(12, 22), py - rng.randint(80, 100)
        else:
            py = rng.randint(80, 160)
            d = f"M512,{py} Q{512 - rng.randint(12, 25)},{py - 30} {512 - rng.randint(10, 20)},{py - 60}"
            anchor = f"512,{py}"
            leaf_cx, leaf_cy = 512 - rng.randint(12, 22), py - rng.randint(40, 60)
        parts.append(
            f'<g id="{gid}" transform-origin="0% 30%">\n'
            f'  <path d="{d}" stroke="{branch_color}" stroke-width="2" fill="none" opacity="{op}"/>\n'
            f'  <ellipse cx="{leaf_cx}" cy="{leaf_cy}" rx="12" ry="6" fill="{branch_color}" opacity="{op * 0.7:.2f}"\n'
            f'    transform="rotate({rng.randint(-30, 30)},{leaf_cx},{leaf_cy})"/>\n'
            f'  <animateTransform attributeName="transform" type="rotate"\n'
            f'    values="0,{anchor}; {sway},{anchor}; 0,{anchor}; {-sway + 1},{anchor}; 0,{anchor}"\n'
            f'    dur="{dur}s" repeatCount="indefinite"\n'
            f'    calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'</g>'
        )
    return "\n".join(parts)


def _gen_falling_leaves(colors, world, story, rng):
    """C2. Falling leaves — 2-4 ellipses spiraling down with rotation.
    Warm earth tones, 12-20s. Opacity 0.25-0.50.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- C2: Falling Leaves -->\n<g id="falling-leaves">']
    leaf_colors = _BIBLE_COLORS["leaf"]
    for i in range(count):
        rx = rng.randint(4, 7)
        ry = max(2, int(rx * 0.6))
        color = rng.choice(leaf_colors)
        dur = round(rng.uniform(12, 20), 1)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.25, 0.50), 2)
        sx = rng.randint(60, 450)
        pts = []
        y = -20
        for j in range(5):
            y += rng.randint(60, 90)
            pts.append(f"{sx + rng.randint(-40, 40)},{y}")
        path = f"M{sx},-20 C{pts[0]} {pts[1]} {pts[2]} S{pts[3]} {pts[4]}"
        rot_vals = ";".join([str(rng.randint(-60, 60)) for _ in range(7)])
        parts.append(
            f'  <ellipse cx="0" cy="0" rx="{rx}" ry="{ry}" fill="{color}" opacity="{op}">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"/>\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="{rot_vals}" dur="{dur}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="opacity" values="0;{op};{op + 0.05:.2f};{op};{max(op - 0.05, 0.05):.2f};0"\n'
            f'      dur="{dur}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_closing_flowers(colors, world, story, rng):
    """C3. Glowing flowers closing — 1-3 at bottom, petals close over 300-900s.
    fill="freeze" one-time close. Center glow pulses 6-10s.
    """
    count = rng.randint(1, 3)
    parts = ['<!-- C3: Closing Flowers -->']
    flower_colors = ["#D4A0B8", "#C890A8", "#D4A878", "#C8A080"]
    center_color = _warm_color(rng, "glow")
    for i in range(count):
        fx = rng.randint(15, 85)
        fy = rng.randint(80, 92)
        close_dur = rng.randint(300, 900)
        pulse_dur = _pick_prime_dur(6, 11, rng)
        petal_color = rng.choice(flower_colors)
        petal_count = rng.randint(3, 6)
        petals = []
        for p in range(petal_count):
            open_angle = int((360 / petal_count) * p - 30)
            closed_angle = int((360 / petal_count) * p - 5)
            mid_angle = (open_angle + closed_angle) // 2
            pcx = rng.randint(-10, 10)
            pcy = rng.randint(-6, -2)
            petals.append(
                f'    <ellipse cx="{pcx}" cy="{pcy}" rx="10" ry="5" fill="{petal_color}" opacity="0.15"\n'
                f'      transform="rotate({open_angle},{pcx},{pcy})">\n'
                f'      <animateTransform attributeName="transform" type="rotate"\n'
                f'        values="{open_angle},{pcx},{pcy}; {mid_angle},{pcx},{pcy}; {closed_angle},{pcx},{pcy}"\n'
                f'        dur="{close_dur}s" repeatCount="1" fill="freeze"\n'
                f'        calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
                f'    </ellipse>'
            )
        parts.append(
            f'<g id="flower-{i}" transform="translate({fx}%, {fy}%)">\n'
            + "\n".join(petals) + "\n"
            f'  <circle cx="0" cy="0" r="4" fill="{center_color}" opacity="0.3">\n'
            f'    <animate attributeName="opacity" values="0.2;0.35;0.2" dur="{pulse_dur}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="r" values="3.5;4.5;3.5" dur="{pulse_dur}s" repeatCount="indefinite"/>\n'
            f'  </circle>\n'
            f'</g>'
        )
    return "\n".join(parts)


# ── Category D: Fauna ────────────────────────────────────────────────────

def _gen_fireflies(colors, world, story, rng):
    """D1. Fireflies — 3-5 warm dots with async glow, core+outer pairs.
    18-28s drift, 4-7s pulse. Core 0.40-0.75, halo 0.10-0.25.
    """
    count = rng.randint(3, 5)
    parts = ['<!-- D1: Fireflies -->\n<g id="fireflies">']
    fly_color = colors.get("glow", "#FFD89C")
    for i in range(count):
        core_r = round(rng.uniform(2.0, 3.0), 1)
        outer_r = round(rng.uniform(7, 12), 1)
        drift_dur = _pick_prime_dur(17, 29, rng)
        pulse_dur = round(rng.uniform(4, 7), 1)
        begin = round(rng.uniform(0, 8), 1)
        cx = rng.randint(60, 440)
        cy = rng.randint(180, 380)
        pts = []
        for j in range(6):
            pts.append(f"{cx + rng.randint(-20, 20)},{cy + rng.randint(-15, 15)}")
        path = f"M{cx},{cy} C{pts[0]} {pts[1]} {pts[2]} S{pts[3]} {pts[4]}"
        core_peak = round(rng.uniform(0.40, 0.75), 2)
        pulse_vals = f"0;0.05;{core_peak:.2f};{core_peak * 0.95:.2f};0.1;0;0;0"
        halo_peak = round(rng.uniform(0.10, 0.25), 2)
        outer_vals = f"0;0.02;{halo_peak:.2f};{halo_peak * 0.9:.2f};0.03;0;0;0"
        n_seg = 7
        parts.append(
            f'  <circle cx="0" cy="0" r="{core_r}" fill="{fly_color}" opacity="0">\n'
            f'    <animateMotion dur="{drift_dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'    <animate attributeName="opacity" values="{pulse_vals}"\n'
            f'      dur="{pulse_dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(n_seg)}"/>\n'
            f'  </circle>\n'
            f'  <circle cx="0" cy="0" r="{outer_r}" fill="{fly_color}" opacity="0">\n'
            f'    <animateMotion dur="{drift_dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"/>\n'
            f'    <animate attributeName="opacity" values="{outer_vals}"\n'
            f'      dur="{pulse_dur}s" repeatCount="indefinite"/>\n'
            f'  </circle>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_sleeping_butterfly(colors, world, story, rng):
    """D2. Sleeping butterfly/moth — 1-2 wing pairs, 10-20 deg open/close, 8-12s.
    Opacity 0.20-0.40.
    """
    count = rng.randint(1, 2)
    parts = ['<!-- D2: Sleeping Butterfly -->']
    wing_colors = ["#C8A080", "#B8946A", "#D4B890", "#A08060"]
    body_color = "#8B7355"
    for i in range(count):
        bx = rng.randint(15, 85)
        by = rng.randint(65, 85)
        wing_color = rng.choice(wing_colors)
        dur = _pick_prime_dur(7, 13, rng)
        rx = rng.randint(4, 7)
        ry = max(2, int(rx * 0.6))
        wing_open_l = rng.randint(-15, -8)
        wing_close_l = wing_open_l - rng.randint(10, 20)
        wing_open_r = -wing_open_l
        wing_close_r = -wing_close_l
        op = round(rng.uniform(0.20, 0.40), 2)
        parts.append(
            f'<g id="butterfly-{i}" transform="translate({bx}%, {by}%)">\n'
            f'  <ellipse cx="-5" cy="0" rx="{rx}" ry="{ry}" fill="{wing_color}" opacity="{op}"\n'
            f'    transform="rotate({wing_open_l},-5,0)">\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="{wing_open_l},-5,0; {wing_close_l},-5,0; {wing_open_l},-5,0"\n'
            f'      dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </ellipse>\n'
            f'  <ellipse cx="5" cy="0" rx="{rx}" ry="{ry}" fill="{wing_color}" opacity="{op}"\n'
            f'    transform="rotate({wing_open_r},5,0)">\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="{wing_open_r},5,0; {wing_close_r},5,0; {wing_open_r},5,0"\n'
            f'      dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </ellipse>\n'
            f'  <ellipse cx="0" cy="0" rx="1.5" ry="4" fill="{body_color}" opacity="{op + 0.03:.2f}"/>\n'
            f'</g>'
        )
    return "\n".join(parts)


def _gen_sleeping_owl(colors, world, story, rng):
    """D3. Sleeping owl — silhouette at edge, eyes close one-time (fill="freeze").
    Opacity 0.20-0.40.
    """
    ox = rng.choice([rng.randint(80, 92), rng.randint(8, 20)])
    oy = rng.randint(30, 50)
    shadow_color = _warm_color(rng, "shadow")
    eye_color = _warm_color(rng, "glow")
    eye_begin = rng.randint(10, 60)
    eye_dur = rng.randint(20, 40)
    eye2_delay = round(rng.uniform(0.5, 2.0), 1)
    op = round(rng.uniform(0.20, 0.40), 2)
    return (
        f'<!-- D3: Sleeping Owl -->\n'
        f'<g id="sleeping-owl" transform="translate({ox}%, {oy}%)" opacity="{op}">\n'
        f'  <ellipse cx="0" cy="0" rx="10" ry="13" fill="{shadow_color}"/>\n'
        f'  <polygon points="-7,-11 -5,-18 -2,-11" fill="{shadow_color}"/>\n'
        f'  <polygon points="7,-11 5,-18 2,-11" fill="{shadow_color}"/>\n'
        f'  <ellipse cx="-4" cy="-2" rx="2.5" ry="2.5" fill="{eye_color}" opacity="0.4">\n'
        f'    <animate attributeName="ry" values="2.5;2.5;2.5;1.5;0.3"\n'
        f'      dur="{eye_dur}s" begin="{eye_begin}s" repeatCount="1" fill="freeze"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
        f'    <animate attributeName="opacity" values="0.4;0.4;0.4;0.2;0.05"\n'
        f'      dur="{eye_dur}s" begin="{eye_begin}s" repeatCount="1" fill="freeze"/>\n'
        f'  </ellipse>\n'
        f'  <ellipse cx="4" cy="-2" rx="2.5" ry="2.5" fill="{eye_color}" opacity="0.4">\n'
        f'    <animate attributeName="ry" values="2.5;2.5;2.5;1.8;0.3"\n'
        f'      dur="{eye_dur}s" begin="{eye_begin + eye2_delay}s" repeatCount="1" fill="freeze"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
        f'    <animate attributeName="opacity" values="0.4;0.4;0.35;0.2;0.05"\n'
        f'      dur="{eye_dur}s" begin="{eye_begin + eye2_delay}s" repeatCount="1" fill="freeze"/>\n'
        f'  </ellipse>\n'
        f'</g>'
    )


def _gen_cricket(colors, world, story, rng):
    """D4. Resting cricket — 1-2 tiny silhouettes, twitches every 15-25s.
    Opacity 0.08-0.15. Bible: antenna 15s, legs 20s, twitch every 15-25s.
    """
    count = rng.randint(1, 2)
    parts = ['<!-- D4: Cricket -->']
    bug_color = _warm_color(rng, "shadow")
    for i in range(count):
        bx = rng.randint(40, 80)
        by = rng.randint(86, 94)
        op = round(rng.uniform(0.08, 0.15), 2)
        leg_dur = _pick_prime_dur(17, 23, rng)
        ant_dur = _pick_prime_dur(13, 19, rng)
        twitch = rng.randint(3, 8)
        # Mostly still with rare twitch
        leg_vals = "0,2,1; 0,2,1; 0,2,1; 0,2,1; 0,2,1; 0,2,1; 0,2,1; " + f"{twitch},2,1; 0,2,1; 0,2,1"
        ant_vals = f"0,-3,-1; {twitch // 2},-3,-1; 0,-3,-1; {-twitch // 2},-3,-1; 0,-3,-1"
        parts.append(
            f'<g id="cricket-{i}" transform="translate({bx}%, {by}%)" opacity="{op}">\n'
            f'  <ellipse cx="0" cy="0" rx="4" ry="1.5" fill="{bug_color}"/>\n'
            f'  <line x1="2" y1="1" x2="6" y2="4" stroke="{bug_color}" stroke-width="0.5">\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="{leg_vals}"\n'
            f'      dur="{leg_dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(9)}"/>\n'
            f'  </line>\n'
            f'  <line x1="-3" y1="-1" x2="-7" y2="-4" stroke="{bug_color}" stroke-width="0.3">\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="{ant_vals}"\n'
            f'      dur="{ant_dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'  </line>\n'
            f'</g>'
        )
    return "\n".join(parts)


# ── Category E: Water ────────────────────────────────────────────────────

def _gen_water_ripples(colors, world, story, rng):
    """E1. Gentle ripples — expanding/fading concentric rings.
    2-3 sources, 2-4 rings each, 6-10s. Opacity 0.20-0.45.
    """
    sources = rng.randint(2, 3)
    parts = ['<!-- E1: Water Ripples -->']
    ring_color = colors.get("particle", "#D4C8B8")
    for s in range(sources):
        sx = rng.randint(25, 75)
        sy = rng.randint(60, 80)
        ring_count = rng.randint(2, 4)
        dur = round(rng.uniform(6, 10), 1)
        stagger = round(dur / ring_count, 1)
        max_r = rng.randint(30, 60)
        rings = []
        for ri in range(ring_count):
            begin = round(stagger * ri, 1)
            op_peak = round(0.35 - ri * 0.05, 2)
            rings.append(
                f'  <circle cx="0" cy="0" r="5" fill="none" stroke="{ring_color}" stroke-width="0.5" opacity="0">\n'
                f'    <animate attributeName="r" values="3;{max_r // 2};{max_r}" dur="{dur}s" begin="{begin}s" repeatCount="indefinite"\n'
                f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
                f'    <animate attributeName="opacity" values="0;{op_peak};0" dur="{dur}s" begin="{begin}s"\n'
                f'      repeatCount="indefinite" calcMode="spline" keySplines="0.3 0 0.7 1;0.4 0 0.6 1"/>\n'
                f'    <animate attributeName="stroke-width" values="0.8;0.4;0.1" dur="{dur}s" begin="{begin}s"\n'
                f'      repeatCount="indefinite"/>\n'
                f'  </circle>'
            )
        parts.append(
            f'<g id="ripple-{s}" transform="translate({sx}%, {sy}%)">\n'
            + "\n".join(rings) + "\n"
            f'</g>'
        )
    return "\n".join(parts)


def _gen_bubbles(colors, world, story, rng):
    """E2. Slow underwater bubbles — 3-5 stroke-only circles, slow rise.
    Grow as they rise, 14-22s. Exception: upward motion is physically correct.
    Opacity 0.25-0.50.
    """
    count = rng.randint(3, 5)
    parts = ['<!-- E2: Slow Bubbles -->\n<g id="bubbles" opacity="0.35">']
    bubble_color = colors.get("particle", "#E8D8C4")
    for i in range(count):
        r_start = round(rng.uniform(2.0, 5.0), 1)
        r_end = round(r_start + rng.uniform(1.0, 2.5), 1)
        dur = round(rng.uniform(14, 22), 1)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.25, 0.50), 2)
        sx = rng.randint(80, 430)
        sy_start = 350 + rng.randint(0, 100)
        pts = []
        y = sy_start
        for j in range(5):
            y -= rng.randint(50, 80)
            pts.append(f"{sx + rng.randint(-15, 15)},{y}")
        path = f"M{sx},{sy_start} C{pts[0]} {pts[1]} {pts[2]} S{pts[3]} {pts[4]}"
        r_vals = ";".join([f"{r_start + (r_end - r_start) * j / 4:.1f}" for j in range(5)])
        parts.append(
            f'  <circle cx="0" cy="0" r="{r_start}" fill="none" stroke="{bubble_color}" stroke-width="0.5" opacity="{op}">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"/>\n'
            f'    <animate attributeName="opacity" values="0;{op};{min(op + 0.05, 0.33):.2f};{op};{op * 0.5:.2f};0"\n'
            f'      dur="{dur}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="r" values="{r_vals}"\n'
            f'      dur="{dur}s" repeatCount="indefinite"/>\n'
            f'  </circle>'
        )
    parts.append('</g>')
    return "\n".join(parts)


# ── Category F: Light & Shadow ───────────────────────────────────────────

def _gen_candle_flicker(colors, world, story, rng):
    """F1. Candle/lantern flicker — radialGradient, prime-number durations.
    Irregular +-15% flicker band. 3-5s cycles. Opacity 0.40-0.70.
    """
    cx = rng.randint(20, 80)
    cy = rng.randint(45, 75)
    glow_r = rng.randint(30, 60)
    core_r = rng.randint(4, 6)
    dur_o = round(rng.uniform(3, 5), 1)
    dur_r = round(rng.uniform(3.5, 5.5), 1)
    dur_core = round(rng.uniform(3, 5), 1)
    glow_outer = colors.get("glow", "#FFCA78")
    glow_inner = colors.get("star", "#FFF0D0")
    grad_id = f"flameG{rng.randint(100, 999)}"
    op_vals = ";".join([f"{0.55 + rng.uniform(-0.12, 0.15):.2f}" for _ in range(10)])
    r_vals = ";".join([str(glow_r + rng.randint(-4, 6)) for _ in range(10)])
    core_op = ";".join([f"{0.35 + rng.uniform(0, 0.18):.2f}" for _ in range(7)])
    cy_vals = ";".join([str(-2 + rng.randint(-2, 1)) for _ in range(5)])
    return (
        f'<!-- F1: Candle Flicker -->\n'
        f'<g id="candle-glow" transform="translate({cx}%, {cy}%)">\n'
        f'  <radialGradient id="{grad_id}">\n'
        f'    <stop offset="0%" stop-color="{glow_inner}" stop-opacity="0.55"/>\n'
        f'    <stop offset="30%" stop-color="{glow_outer}" stop-opacity="0.25"/>\n'
        f'    <stop offset="100%" stop-color="{glow_outer}" stop-opacity="0"/>\n'
        f'  </radialGradient>\n'
        f'  <circle cx="0" cy="0" r="{glow_r}" fill="url(#{grad_id})">\n'
        f'    <animate attributeName="opacity" values="{op_vals}"\n'
        f'      dur="{dur_o}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(9)}"/>\n'
        f'    <animate attributeName="r" values="{r_vals}"\n'
        f'      dur="{dur_r}s" repeatCount="indefinite"/>\n'
        f'  </circle>\n'
        f'  <circle cx="0" cy="-3" r="{core_r}" fill="{glow_inner}" opacity="0.45">\n'
        f'    <animate attributeName="opacity" values="{core_op}"\n'
        f'      dur="{dur_core}s" repeatCount="indefinite"/>\n'
        f'    <animate attributeName="cy" values="{cy_vals}"\n'
        f'      dur="{round(rng.uniform(3, 5), 1)}s" repeatCount="indefinite"/>\n'
        f'  </circle>\n'
        f'</g>'
    )


def _gen_shadow_play(colors, world, story, rng):
    """F2. Shadow play — soft dark shapes, 10-20s, 0.06-0.15 opacity."""
    count = rng.randint(1, 3)
    parts = ['<!-- F2: Shadow Play -->\n<g id="window-shadows" opacity="0.10">']
    shadow_color = _warm_color(rng, "shadow")
    for i in range(count):
        dur = round(rng.uniform(10, 20), 1)
        op = round(rng.uniform(0.06, 0.15), 2)
        if rng.random() < 0.5:
            x1 = rng.randint(40, 200)
            y1 = rng.randint(80, 200)
            pts = " ".join([
                f"Q{x1 + rng.randint(10, 40)},{y1 - rng.randint(5, 20)} {x1 + rng.randint(30, 60)},{y1 + rng.randint(5, 20)}"
                for _ in range(2)
            ])
            parts.append(
                f'  <path d="M{x1},{y1} {pts}"\n'
                f'    fill="none" stroke="{shadow_color}" stroke-width="15" stroke-linecap="round" opacity="{op}">\n'
                f'    <animateTransform attributeName="transform" type="translate"\n'
                f'      values="0,0; {rng.randint(3, 8)},{rng.randint(1, 3)}; {rng.randint(-4, -1)},{rng.randint(1, 3)}; {rng.randint(2, 6)},{rng.randint(-2, 0)}; 0,0"\n'
                f'      dur="{dur}s" repeatCount="indefinite"\n'
                f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
                f'  </path>'
            )
        else:
            ex, ey = rng.randint(80, 400), rng.randint(100, 350)
            erx, ery = rng.randint(20, 40), rng.randint(15, 30)
            dur_o = _pick_prime_dur(19, 29, rng)
            parts.append(
                f'  <ellipse cx="{ex}" cy="{ey}" rx="{erx}" ry="{ery}" fill="{shadow_color}" opacity="{op * 0.8:.2f}">\n'
                f'    <animateTransform attributeName="transform" type="translate"\n'
                f'      values="0,0; {rng.randint(2, 5)},{rng.randint(1, 3)}; {rng.randint(-3, -1)},{rng.randint(1, 3)}; {rng.randint(2, 5)},0; 0,0"\n'
                f'      dur="{dur}s" repeatCount="indefinite"/>\n'
                f'    <animate attributeName="opacity" values="{op * 0.7:.2f};{op:.2f};{op * 0.5:.2f};{op * 0.8:.2f};{op * 0.7:.2f}"\n'
                f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
                f'  </ellipse>'
            )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_breathing_pacer(colors, world, story, rng):
    """F3. Breathing glow orb (MANDATORY) — primary sleep cue.
    4 world-specific variants via pacer_variant. dur=5s (12 bpm). Opacity 0.35-0.65.
    Sized large enough to be clearly visible on FLUX photographic backgrounds.
    """
    dur = 5
    glow_color = colors.get("glow", "#FFD89C")
    star_color = colors.get("star", "#FFF5E0")
    mapping = WORLD_ELEMENTS.get(world, WORLD_ELEMENTS["enchanted_forest"])
    variant = mapping.get("pacer_variant", "forest")
    grad_id = f"breathG{rng.randint(100, 999)}"

    if variant == "ocean":
        cx, cy = "50%", "60%"
        rx_base, ry_base = 40, 50
        return (
            f'<!-- F3: Breathing Pacer (Ocean) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.65"/>\n'
            f'    <stop offset="35%" stop-color="{glow_color}" stop-opacity="0.35"/>\n'
            f'    <stop offset="70%" stop-color="{glow_color}" stop-opacity="0.10"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <ellipse cx="{cx}" cy="{cy}" rx="{rx_base}" ry="{ry_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="ry" values="{ry_base - 5};{ry_base + 5};{ry_base - 5}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="rx" values="{rx_base - 4};{rx_base + 4};{rx_base - 4}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.45;0.75;0.45" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </ellipse>\n'
            f'</g>'
        )
    elif variant == "space":
        cx, cy = "50%", "50%"
        r_base = 55
        return (
            f'<!-- F3: Breathing Pacer (Space) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{star_color}" stop-opacity="0.60"/>\n'
            f'    <stop offset="30%" stop-color="{glow_color}" stop-opacity="0.30"/>\n'
            f'    <stop offset="70%" stop-color="{glow_color}" stop-opacity="0.08"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 8};{r_base + 5};{r_base - 8}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.45;0.70;0.45" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )
    elif variant == "interior":
        cx, cy = "35%", "55%"
        r_base = 50
        return (
            f'<!-- F3: Breathing Pacer (Interior) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.70"/>\n'
            f'    <stop offset="30%" stop-color="{glow_color}" stop-opacity="0.35"/>\n'
            f'    <stop offset="70%" stop-color="{glow_color}" stop-opacity="0.10"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 6};{r_base + 4};{r_base - 6}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.50;0.75;0.50" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )
    else:  # forest (default)
        cx, cy = "50%", "70%"
        r_base = 50
        return (
            f'<!-- F3: Breathing Pacer (Forest) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.70"/>\n'
            f'    <stop offset="30%" stop-color="{glow_color}" stop-opacity="0.35"/>\n'
            f'    <stop offset="70%" stop-color="{glow_color}" stop-opacity="0.10"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 6};{r_base + 5};{r_base - 6}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.50;0.75;0.50" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )


# ── Category G: Environmental ────────────────────────────────────────────

def _gen_chimney_smoke(colors, world, story, rng):
    """G1. Chimney wisps — 1-3 expanding wisps, 12-20s, 0.08-0.15 opacity."""
    count = rng.randint(1, 3)
    sx = rng.randint(55, 80)
    sy = rng.randint(18, 30)
    parts = [f'<!-- G1: Chimney Smoke -->\n<g id="chimney-smoke" transform="translate({sx}%, {sy}%)">']
    smoke_colors = _BIBLE_COLORS["smoke"]
    for i in range(count):
        color = rng.choice(smoke_colors)
        dur = _pick_prime_dur(11, 19, rng)
        begin = round(rng.uniform(0, 6), 1)
        op_peak = round(rng.uniform(0.08, 0.15), 2)
        rx_start = rng.randint(5, 8)
        rx_end = rx_start * rng.randint(3, 5)
        ry_start = max(2, int(rx_start * 0.5))
        ry_end = max(4, int(rx_end * 0.4))
        dx = rng.randint(-8, 8)
        path = f"M0,0 C{dx + 5},-20 {dx - 8},-45 {dx + 3},-70 S{dx - 5},-95 {dx + 2},-120"
        parts.append(
            f'  <ellipse cx="0" cy="0" rx="{rx_start}" ry="{ry_start}" fill="{color}" opacity="0">\n'
            f'    <animateMotion dur="{dur}s" repeatCount="indefinite" begin="{begin}s"\n'
            f'      path="{path}"/>\n'
            f'    <animate attributeName="opacity" values="0;{op_peak};{op_peak * 0.75:.2f};{op_peak * 0.4:.2f};0"\n'
            f'      dur="{dur}s" repeatCount="indefinite" begin="{begin}s"/>\n'
            f'    <animate attributeName="rx" values="{rx_start};{rx_start + 4};{rx_start + 10};{rx_start + 18};{rx_end}"\n'
            f'      dur="{dur}s" repeatCount="indefinite" begin="{begin}s"/>\n'
            f'    <animate attributeName="ry" values="{ry_start};{ry_start + 2};{ry_start + 5};{ry_start + 8};{ry_end}"\n'
            f'      dur="{dur}s" repeatCount="indefinite" begin="{begin}s"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_wind_grass(colors, world, story, rng):
    """G2. Wind through grass — 8-15 blades, staggered begin delays (traveling wave).
    5-10s sway cycle. Opacity 0.15-0.35.
    """
    count = rng.randint(8, 15)
    parts = ['<!-- G2: Wind Through Grass -->\n<g id="grass-wind" opacity="0.25">']
    grass_color = _warm_color(rng, "shadow")
    dur = round(rng.uniform(5, 10), 1)
    sway = rng.randint(3, 6)
    stagger = round(rng.uniform(0.3, 0.6), 2)
    for i in range(count):
        x_pct = round(10 + (80 * i / count), 1)
        h = rng.randint(5, 10)
        width = round(rng.uniform(0.6, 0.9), 1)
        begin = round(stagger * i, 1)
        parts.append(
            f'  <line x1="{x_pct}%" y1="95%" x2="{x_pct}%" y2="{95 - h}%" stroke="{grass_color}" stroke-width="{width}"\n'
            f'    stroke-linecap="round">\n'
            f'    <animateTransform attributeName="transform" type="rotate"\n'
            f'      values="0,{x_pct}%,95%; {sway},{x_pct}%,95%; 0,{x_pct}%,95%; {-sway + 1},{x_pct}%,95%; 0,{x_pct}%,95%"\n'
            f'      dur="{dur}s" begin="{begin}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'  </line>'
        )
    parts.append('</g>')
    return "\n".join(parts)


# ── Element Dispatch Table ───────────────────────────────────────────────

ELEMENT_GENERATORS = {
    "stars":              _gen_stars,
    "shooting_star":      _gen_shooting_star,
    "moon_glow":          _gen_moon_glow,
    "aurora":             _gen_aurora,
    "fog":                _gen_fog,
    "rain":               _gen_rain,
    "snowfall":           _gen_snowfall,
    "dust_motes":         _gen_dust_motes,
    "caustics":           _gen_caustics,
    "swaying_branches":   _gen_swaying_branches,
    "falling_leaves":     _gen_falling_leaves,
    "closing_flowers":    _gen_closing_flowers,
    "fireflies":          _gen_fireflies,
    "sleeping_butterfly":  _gen_sleeping_butterfly,
    "sleeping_owl":       _gen_sleeping_owl,
    "cricket":            _gen_cricket,
    "water_ripples":      _gen_water_ripples,
    "bubbles":            _gen_bubbles,
    "candle_flicker":     _gen_candle_flicker,
    "shadow_play":        _gen_shadow_play,
    "breathing_pacer":    _gen_breathing_pacer,
    "chimney_smoke":      _gen_chimney_smoke,
    "wind_grass":         _gen_wind_grass,
}


# ── Vignette Generator ──────────────────────────────────────────────────

def _gen_vignette(style, colors):
    """Generate per-world vignette. NOT the same dark edges on every cover."""
    vig_color = colors.get("vignette", "#1a0a05")
    dur = random.randint(8, 10)

    if style == "none":
        return ""

    elif style == "top_heavy":
        op = round(random.uniform(0.60, 0.85), 2)
        grad_id = f"vigLG{random.randint(100, 999)}"
        return (
            f'<!-- Vignette: top_heavy -->\n'
            f'<linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">\n'
            f'  <stop offset="0%" stop-color="{vig_color}" stop-opacity="0.15"/>\n'
            f'  <stop offset="50%" stop-color="{vig_color}" stop-opacity="0.15"/>\n'
            f'  <stop offset="100%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'</linearGradient>\n'
            f'<rect width="512" height="512" fill="url(#{grad_id})" opacity="{op}">\n'
            f'  <animate attributeName="opacity" values="{op};{min(op + 0.05, 0.90)};{op}" dur="{dur}s" repeatCount="indefinite"\n'
            f'    calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'</rect>'
        )

    elif style == "bottom_heavy":
        op = round(random.uniform(0.60, 0.85), 2)
        grad_id = f"vigLG{random.randint(100, 999)}"
        return (
            f'<!-- Vignette: bottom_heavy -->\n'
            f'<linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">\n'
            f'  <stop offset="0%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'  <stop offset="50%" stop-color="{vig_color}" stop-opacity="0.15"/>\n'
            f'  <stop offset="100%" stop-color="{vig_color}" stop-opacity="0.70"/>\n'
            f'</linearGradient>\n'
            f'<rect width="512" height="512" fill="url(#{grad_id})" opacity="{op}">\n'
            f'  <animate attributeName="opacity" values="{op};{min(op + 0.05, 0.90)};{op}" dur="{dur}s" repeatCount="indefinite"\n'
            f'    calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'</rect>'
        )

    elif style == "bottom_light":
        op = round(random.uniform(0.50, 0.70), 2)
        grad_id = f"vigLG{random.randint(100, 999)}"
        return (
            f'<!-- Vignette: bottom_light -->\n'
            f'<linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">\n'
            f'  <stop offset="0%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'  <stop offset="70%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'  <stop offset="100%" stop-color="{vig_color}" stop-opacity="0.40"/>\n'
            f'</linearGradient>\n'
            f'<rect width="512" height="512" fill="url(#{grad_id})" opacity="{op}"/>'
        )

    elif style == "top_corners":
        op = round(random.uniform(0.50, 0.75), 2)
        grad_id = f"vigRC{random.randint(100, 999)}"
        return (
            f'<!-- Vignette: top_corners -->\n'
            f'<radialGradient id="{grad_id}" cx="0.5" cy="0.3" r="0.7">\n'
            f'  <stop offset="50%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'  <stop offset="100%" stop-color="{vig_color}" stop-opacity="0.60"/>\n'
            f'</radialGradient>\n'
            f'<rect width="512" height="512" fill="url(#{grad_id})" opacity="{op}"/>'
        )

    elif style == "corners_only":
        op = round(random.uniform(0.50, 0.70), 2)
        grad_id = f"vigRC{random.randint(100, 999)}"
        return (
            f'<!-- Vignette: corners_only -->\n'
            f'<radialGradient id="{grad_id}" cx="0.5" cy="0.5" r="0.6">\n'
            f'  <stop offset="40%" stop-color="{vig_color}" stop-opacity="0"/>\n'
            f'  <stop offset="100%" stop-color="{vig_color}" stop-opacity="0.55"/>\n'
            f'</radialGradient>\n'
            f'<rect width="512" height="512" fill="url(#{grad_id})" opacity="{op}"/>'
        )

    elif style == "full_heavy":
        op = round(random.uniform(0.70, 0.90), 2)
        return (
            f'<!-- Vignette: full_heavy -->\n'
            f'<rect width="512" height="512" fill="url(#vignetteGrad)" opacity="{op}">\n'
            f'  <animate attributeName="opacity" values="{op};{min(op + 0.05, 0.95)};{op}" dur="{dur}s" repeatCount="indefinite"\n'
            f'    calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'</rect>'
        )

    else:  # full_soft (default)
        op = round(random.uniform(0.40, 0.60), 2)
        return (
            f'<!-- Vignette: full_soft -->\n'
            f'<rect width="512" height="512" fill="url(#vignetteGrad)" opacity="{op}">\n'
            f'  <animate attributeName="opacity" values="{op};{min(op + 0.05, 0.65)};{op}" dur="{dur}s" repeatCount="indefinite"\n'
            f'    calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'</rect>'
        )


# ── Assembly ─────────────────────────────────────────────────────────────

def _character_aware_elements(story):
    """Return extra element names based on protagonist type/keywords."""
    extras = []
    char_type = story.get("lead_character_type", "").lower()
    keywords = (story.get("title", "") + " " + story.get("description", "")).lower()
    if char_type in ("owl", "bird") or "owl" in keywords:
        extras.append("sleeping_owl")
    if char_type == "butterfly" or "butterfly" in keywords:
        extras.append("sleeping_butterfly")
    if any(k in keywords for k in ("campfire", "bonfire")):
        extras.append("chimney_smoke")
    if "lantern" in keywords:
        extras.append("candle_flicker")
    if "rain" in keywords:
        extras.append("rain")
    if "window" in keywords:
        extras.append("shadow_play")
    return extras


def _should_include_optional(elem_name, story, rng):
    """30% base chance + keyword boost for optional elements."""
    keywords = (story.get("title", "") + " " + story.get("description", "")).lower()
    keyword_map = {
        "stars": ["star", "night", "sky"],
        "sleeping_owl": ["owl", "bird", "tree"],
        "sleeping_butterfly": ["butterfly", "moth", "garden", "flower"],
        "chimney_smoke": ["cabin", "chimney", "fire", "cottage", "campfire"],
        "cricket": ["cricket", "insect", "meadow", "grass"],
        "wind_grass": ["grass", "meadow", "wind", "field"],
        "moon_glow": ["moon", "night"],
        "aurora": ["northern", "aurora", "arctic"],
        "fog": ["mist", "fog", "haze"],
        "dust_motes": ["dust", "light", "beam"],
        "caustics": ["water", "pool", "underwater"],
        "bubbles": ["bubble", "underwater", "ocean"],
        "falling_leaves": ["leaf", "autumn", "fall"],
        "rain": ["rain", "storm"],
        "shadow_play": ["shadow", "window"],
    }
    boost = any(kw in keywords for kw in keyword_map.get(elem_name, []))
    chance = 0.6 if boost else 0.3
    return rng.random() < chance


def generate_svg_overlay(axes: dict, story: dict) -> str:
    """Generate an animated SVG overlay using the 3-layer system.

    Layers: background (4-6), midground (4-7), foreground (3-5).
    Plus fauna (1-2), rare events (0-1), vignette.
    Target: 12-20 elements total. Budget: 8KB.
    """
    world = axes["world_setting"]
    palette = axes["palette"]
    rng = random.Random(_stable_seed(story.get("id", "") + world))
    mapping = WORLD_ELEMENTS.get(world, WORLD_ELEMENTS["enchanted_forest"])

    # Build colors from palette + world accents
    palette_colors = {
        "ember_warm":    {"glow": "#FFD699", "particle": "#FFCC80", "vignette": "#1a0a05", "star": "#FFF5E0"},
        "twilight_cool": {"glow": "#C8B8E0", "particle": "#D0C4E8", "vignette": "#0a0520", "star": "#E8E0F0"},
        "forest_deep":   {"glow": "#A8D5A0", "particle": "#C4E0B8", "vignette": "#051005", "star": "#D8F0D0"},
        "golden_hour":   {"glow": "#FFE4B5", "particle": "#FFD89B", "vignette": "#1a0f00", "star": "#FFF8E8"},
        "moonstone":     {"glow": "#C0D0E0", "particle": "#B8C8D8", "vignette": "#050810", "star": "#E0E8F0"},
        "berry_dusk":    {"glow": "#D8A8C8", "particle": "#E0B8D0", "vignette": "#100510", "star": "#F0D8E8"},
    }
    colors = palette_colors.get(palette, palette_colors["golden_hour"])
    accents = world_accents.get(world, {})
    if accents:
        colors = {**colors, **accents}

    svg_parts = []
    svg_parts.append(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <radialGradient id="vignetteGrad">
      <stop offset="40%" stop-color="transparent"/>
      <stop offset="100%" stop-color="{colors['vignette']}" stop-opacity="0.75"/>
    </radialGradient>
    <filter id="softBlur">
      <feGaussianBlur stdDeviation="2"/>
    </filter>
  </defs>''')

    element_parts = []
    budget_remaining = 50000  # No budget constraint — prioritize animation quality and diversity

    def _pick_from_layer(layer_key):
        """Pick elements from a layer pool, respecting budget."""
        nonlocal budget_remaining
        layer = mapping.get(layer_key)
        if not layer:
            return
        pool = layer["pool"][:]
        rng.shuffle(pool)
        pick_min, pick_max = layer["pick"]
        pick_count = rng.randint(pick_min, pick_max)

        # Prioritize character-aware elements in this layer
        char_elements = _character_aware_elements(story)
        for ce in char_elements:
            if ce in pool:
                pool.remove(ce)
                pool.insert(0, ce)

        selected = 0
        for elem_name in pool:
            if selected >= pick_count or budget_remaining < 200:
                break
            if elem_name not in ELEMENT_GENERATORS:
                continue
            svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
            size = _svg_size(svg)
            if budget_remaining - size >= 0:
                element_parts.append(svg)
                budget_remaining -= size
                selected += 1

    # 1. Required: breathing pacer (always first)
    for elem_name in mapping.get("required", []):
        if elem_name not in ELEMENT_GENERATORS:
            continue
        svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
        element_parts.append(svg)
        budget_remaining -= _svg_size(svg)

    # 2. Background layer (4-6 elements: atmosphere, depth)
    _pick_from_layer("background")

    # 3. Midground layer (4-7 elements: living world)
    _pick_from_layer("midground")

    # 4. Foreground layer (2-3 elements: framing, close particles)
    _pick_from_layer("foreground")

    # 5. Fauna detail (pick 1-2 from fauna list)
    fauna_pool = [f for f in mapping.get("fauna", []) if f in ELEMENT_GENERATORS]
    if fauna_pool:
        rng.shuffle(fauna_pool)
        char_elements = _character_aware_elements(story)
        for ce in char_elements:
            if ce in fauna_pool:
                fauna_pool.remove(ce)
                fauna_pool.insert(0, ce)
        fauna_count = min(rng.randint(1, 2), len(fauna_pool))
        for elem_name in fauna_pool[:fauna_count]:
            if budget_remaining < 200:
                break
            svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
            size = _svg_size(svg)
            if budget_remaining - size >= 0:
                element_parts.append(svg)
                budget_remaining -= size

    # 6. Rare event (0-1 from rare_event list)
    rare_pool = [r for r in mapping.get("rare_event", []) if r in ELEMENT_GENERATORS]
    if rare_pool and rng.random() < 0.95 and budget_remaining >= 300:
        elem_name = rng.choice(rare_pool)
        svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
        size = _svg_size(svg)
        if budget_remaining - size >= 0:
            element_parts.append(svg)
            budget_remaining -= size

    # 7. Vignette (always)
    vig_style = mapping.get("vignette", "full_soft")
    vig = _gen_vignette(vig_style, colors)
    if vig:
        element_parts.append(vig)

    # Assemble
    svg_parts.extend(element_parts)
    svg_parts.append('\n</svg>')
    svg_output = "\n".join(svg_parts)

    # Validate drowsiness guardrails
    warnings = validate_overlay_drowsiness(svg_output)
    if warnings:
        for w in warnings:
            logger.warning("DROWSINESS VIOLATION: %s", w)

    return svg_output


# ── Drowsiness Guardrail Validator ────────────────────────────────────────

def _is_warm_color(hex_color: str) -> bool:
    """Check if a hex color is warm-spectrum (amber-to-gold range)."""
    hex_color = hex_color.strip().lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    if len(hex_color) != 6:
        return True
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return True
    if r >= 0xE0 and g >= 0xE0 and b >= 0xE0:
        return True
    if b > r:
        return False
    if g > r and b > r * 0.5:
        return False
    if b >= 0x90 and r < 0xC0:
        return False
    return True


def validate_overlay_drowsiness(svg_str: str) -> list:
    """Validate SVG overlay against drowsiness-inducing design principles.

    Rules: no upward motion, min 3s duration, max 0.80 opacity,
    max 20 elements/group, warm colors only, exactly 1 breathing pacer.
    """
    warnings = []

    # Rule 1: No dominant upward motion
    for m in _re.finditer(r'<animateMotion[^>]*path="([^"]*)"', svg_str):
        path = m.group(1)
        coords = _re.findall(r'(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)', path)
        if len(coords) >= 2:
            start_y = float(coords[0][1])
            end_y = float(coords[-1][1])
            delta_y = end_y - start_y
            if delta_y < -80:
                start_x = float(coords[0][0])
                end_x = float(coords[-1][0])
                delta_x = abs(end_x - start_x)
                # Allow bubbles and smoke (physically correct upward motion)
                preceding = svg_str[max(0, m.start() - 2500):m.start()]
                pre_lower = preceding.lower()
                if 'bubble' in pre_lower or 'smoke' in pre_lower or 'chimney' in pre_lower:
                    continue
                if abs(delta_y) > delta_x * 1.5:
                    warnings.append(
                        f"Dominant upward motion: dy={delta_y:.0f}px (dx={delta_x:.0f}px)"
                    )

    for m in _re.finditer(
        r'<animateTransform[^>]*type="translate"[^>]*values="([^"]*)"', svg_str
    ):
        values = m.group(1)
        y_vals = _re.findall(r',\s*(-?\d+(?:\.\d+)?)', values)
        for yv in y_vals:
            if float(yv) < -50:
                warnings.append(f"Upward translate: y={yv}")

    # Rule 2: Min duration >= 3s
    for m in _re.finditer(r'dur="(\d+(?:\.\d+)?)s?"', svg_str):
        dur = float(m.group(1))
        if dur < 3.0:
            warnings.append(f"Duration too short: {dur}s (min 3s)")

    # Rule 3: Max opacity 0.80 (light elements only, skip vignettes)
    for m in _re.finditer(r'opacity="([^"]*)"', svg_str):
        val = m.group(1)
        pos = m.start()
        preceding = svg_str[max(0, pos - 500):pos]
        if '<defs>' in preceding and '</defs>' not in preceding:
            continue
        if 'vignette' in preceding.lower() or 'vigLG' in preceding or 'vigRC' in preceding:
            continue
        if 'stop-opacity' in svg_str[max(0, pos - 15):pos + 1]:
            continue
        try:
            op = float(val)
            if op > 0.81:
                warnings.append(f"Light opacity too high: {op:.2f} (max 0.80)")
        except ValueError:
            pass

    for m in _re.finditer(r'attributeName="opacity"[^>]*values="([^"]*)"', svg_str):
        vals = m.group(1)
        pos = m.start()
        preceding = svg_str[max(0, pos - 500):pos]
        if 'vignette' in preceding.lower() or 'vigLG' in preceding or 'vigRC' in preceding:
            continue
        for v in vals.split(';'):
            v = v.strip()
            if not v:
                continue
            try:
                op = float(v)
                if op > 0.81:
                    warnings.append(f"Animated opacity peak: {op:.2f} (max 0.80)")
            except ValueError:
                pass

    # Rule 4: Element count per group <= 20
    sections = _re.split(r'<!--\s*(.*?)\s*-->', svg_str)
    current_label = ""
    for i, section in enumerate(sections):
        if i % 2 == 1:
            current_label = section
        elif i % 2 == 0 and current_label:
            elements = len(_re.findall(r'<(?:circle|ellipse|rect|path|line|polygon)\s', section))
            if elements > 20:
                warnings.append(f"Too many elements in '{current_label}': {elements}")

    # Rule 5: Warm colors only
    for m in _re.finditer(r'fill="(#[0-9a-fA-F]{3,8})"', svg_str):
        color = m.group(1)
        pos = m.start()
        preceding = svg_str[max(0, pos - 200):pos]
        if '<defs>' in preceding and '</defs>' not in preceding:
            continue
        if 'vignette' in preceding.lower():
            continue
        if not _is_warm_color(color):
            warnings.append(f"Cool color in overlay: {color}")

    # Rule 6: Exactly one breathing pacer
    pacer_count = len(_re.findall(r'id="breath-pacer"', svg_str))
    if pacer_count == 0:
        warnings.append("Missing breathing pacer (mandatory)")
    elif pacer_count > 1:
        warnings.append(f"Multiple breathing pacers: {pacer_count} (must be exactly 1)")

    return warnings




# ── Auto-select axes from story metadata ────────────────────────────────

def _infer_character_type(story: dict) -> str:
    """Infer lead_character_type from title/description when not explicitly set.

    Uses the protagonist phrase (extracted from description) to determine
    if the lead character is non-human. This avoids false positives from
    keywords that appear in settings or supporting characters.
    """
    import re as _re

    # Get the protagonist phrase from the description
    char_phrase = _extract_character_phrase(story).lower()
    title = story.get("title", "").lower()

    # Extract title subject: "The Owl's Goodnight" → "owl"
    title_subject = ""
    title_match = _re.match(r"^the\s+(\w+(?:'s)?)\s+", title)
    if title_match:
        title_subject = title_match.group(1).rstrip("'s").rstrip("s")

    # Combined text to check: protagonist phrase + title subject
    check_text = f"{char_phrase} {title_subject}"

    # Check non-human keywords FIRST (before human indicators)
    # This ensures "a young fox" matches "fox" → animal, not "young" → human
    keyword_map = [
        # Birds
        (["owl", "parrot", "eagle", "sparrow", "robin", "heron", "penguin",
          "flamingo", "peacock", "hummingbird", "dove", "crow", "raven"], "bird"),
        # Sea creatures
        (["dolphin", "whale", "jellyfish", "octopus", "seahorse", "coral",
          "fish", "shark", "seal", "turtle", "crab", "starfish",
          "mermaid", "ocean spirit"], "sea_creature"),
        # Insects
        (["firefly", "butterfly", "caterpillar", "moth", "bee", "ladybug",
          "cricket", "dragonfly", "beetle", "ant", "spider"], "insect"),
        # Animals (mammals/reptiles)
        (["rabbit", "bunny", "fox", "bear", "deer", "mouse", "squirrel",
          "hedgehog", "kitten", "puppy", "wolf", "tiger", "lion", "elephant",
          "monkey", "panda", "raccoon", "otter", "badger", "tortoise",
          "dinosaur", "dragon", "frog", "gecko", "chameleon"], "animal"),
        # Celestial — include "moon" and "star" (safe: only checked in protagonist phrase)
        (["moon", "star", "comet", "sun", "moonbeam", "moonlight",
          "starlight", "aurora"], "celestial"),
        # Atmospheric / weather
        (["cloud", "raindrop", "snowflake", "breeze", "drizzle", "thunder",
          "rainbow"], "atmospheric"),
        # Plants
        (["flower", "tree", "leaf", "seed", "vine", "mushroom", "petal",
          "blossom", "bamboo"], "plant"),
        # Objects
        (["lantern", "clock", "teacup", "chai", "kite", "bell",
          "candle", "lamp", "compass", "pebble", "stone",
          "feather", "blanket", "pillow"], "object"),
        # Robot / mechanical
        (["robot", "automaton", "clockwork", "mechanical"], "robot"),
    ]

    for keywords, char_type in keyword_map:
        for kw in keywords:
            if _re.search(r'\b' + _re.escape(kw) + r'\b', check_text):
                return char_type

    return "human"


def auto_select_axes(story: dict, overrides: dict = None, mood: str = None) -> dict:
    """Select 7 diversity axes from story metadata with optional overrides.

    Uses weighted random selection from the FULL pool of options for each axis.
    Theme/context provide weight boosts (not exclusive filters).
    Recently used values are penalized to ensure diversity across stories.
    Mood provides palette/composition preference boosts when specified.
    """
    overrides = overrides or {}
    theme = story.get("theme", "fantasy")
    age_group = story.get("age_group", "6-8")
    char_type = story.get("lead_character_type", "")
    if not char_type:
        char_type = _infer_character_type(story)
    ctx = story.get("cover_context", "").lower()
    title_lower = story.get("title", "").lower()
    desc_lower = story.get("description", "").lower()

    # Per-story seeded RNG for deterministic axis selection
    _rng = random.Random(_stable_seed(story.get("id", "") + theme + "_axes_v2"))

    # Load recent history for diversity penalty
    recent = _load_recent_axes()

    # ── World Setting (all 12 options, theme/context boost) ──
    all_worlds = list(WORLD_SETTINGS.keys())
    w_weights = {w: 1.0 for w in all_worlds}
    # Boost theme-matched worlds
    for w in THEME_TO_WORLD.get(theme, []):
        w_weights[w] = w_weights.get(w, 1.0) * _THEME_BOOST
    # Boost context-matched worlds
    ctx_world_map = {
        ("festival", "holi", "diwali", "celebration", "meadow", "garden", "field"): "mountain_meadow",
        ("ocean", "underwater", "coral", "sea"): "deep_ocean",
        ("forest", "jungle", "woods"): "enchanted_forest",
        ("snow", "winter", "ice", "frost"): "snow_landscape",
        ("library", "room", "house", "kitchen", "indoor"): "cozy_interior",
        ("space", "cosmos", "nebula", "planet"): "space_cosmos",
        ("desert", "sand", "dune"): "desert_night",
        ("cave", "crystal", "underground"): "underground_cave",
        ("cloud", "sky", "float"): "cloud_kingdom",
    }
    if ctx:
        for keywords, target_world in ctx_world_map.items():
            if any(kw in ctx for kw in keywords):
                w_weights[target_world] = w_weights.get(target_world, 1.0) * _CONTEXT_BOOST
    w_weights = _apply_recent_penalty(w_weights, recent.get("world_setting", []))
    world = overrides.get("world_setting") or _weighted_choice(all_worlds, w_weights, _rng)

    # ── Palette (all 6 options, theme/context boost) ──
    all_palettes = list(COLOR_PALETTES.keys())
    p_weights = {p: 1.0 for p in all_palettes}
    for p in THEME_TO_PALETTE.get(theme, []):
        p_weights[p] = p_weights.get(p, 1.0) * _THEME_BOOST
    # Context palette boosts
    if ctx:
        if any(w in ctx for w in ("holi", "gulal", "vibrant", "colorful", "festival")):
            p_weights["ember_warm"] = p_weights.get("ember_warm", 1.0) * _CONTEXT_BOOST
        if any(w in ctx for w in ("snow", "winter", "frost", "ice")):
            p_weights["moonstone"] = p_weights.get("moonstone", 1.0) * _CONTEXT_BOOST
            p_weights["twilight_cool"] = p_weights.get("twilight_cool", 1.0) * _CONTEXT_BOOST
    # Mood palette boosts
    if mood and mood in MOOD_PALETTE_BOOSTS:
        for pal, mult in MOOD_PALETTE_BOOSTS[mood].items():
            if pal in p_weights:
                p_weights[pal] *= mult
    p_weights = _apply_recent_penalty(p_weights, recent.get("palette", []))
    palette = overrides.get("palette") or _weighted_choice(all_palettes, p_weights, _rng)

    # ── Composition (all 5 options, title keyword boost) ──
    all_comps = list(COMPOSITIONS.keys())
    c_weights = {c: 1.0 for c in all_comps}
    if any(w in title_lower for w in ("river", "path", "trail", "road", "journey")):
        c_weights["winding_path"] = c_weights.get("winding_path", 1.0) * _CONTEXT_BOOST
    if any(w in title_lower for w in ("cave", "nest", "cocoon", "burrow")):
        c_weights["circular_nest"] = c_weights.get("circular_nest", 1.0) * _CONTEXT_BOOST
    # Mood composition boosts
    if mood and mood in MOOD_COMPOSITION_BOOSTS:
        for cp, mult in MOOD_COMPOSITION_BOOSTS[mood].items():
            if cp in c_weights:
                c_weights[cp] *= mult
    c_weights = _apply_recent_penalty(c_weights, recent.get("composition", []))
    comp = overrides.get("composition") or _weighted_choice(all_comps, c_weights, _rng)

    # ── Character visual (deterministic from story metadata, unchanged) ──
    char_visual = CHAR_TYPE_TO_VISUAL.get(char_type, None)
    if char_visual is None:
        ct_lower = char_type.lower()
        for keyword, visual in [
            ("sea", "aquatic_creature"), ("fish", "aquatic_creature"), ("whale", "aquatic_creature"),
            ("bird", "bird"), ("owl", "bird"), ("eagle", "bird"),
            ("insect", "insect"), ("bug", "insect"), ("caterpillar", "insect"),
            ("firefly", "insect"), ("butterfly", "insect"), ("bee", "insect"),
            ("moth", "insect"), ("ladybug", "insect"), ("cricket", "insect"),
            ("ant", "insect"),
            ("plant", "plant"), ("flower", "plant"), ("tree", "plant"),
            ("dragon", "mythical_gentle"), ("mythical", "mythical_gentle"),
            ("robot", "robot_mech"), ("machine", "robot_mech"),
            ("star", "celestial"), ("moon", "celestial"), ("comet", "celestial"),
            ("rain", "atmospheric"), ("cloud", "atmospheric"), ("snow", "atmospheric"),
            ("object", "object"), ("lantern", "object"), ("clock", "object"),
            ("animal", "small_mammal"),
        ]:
            if keyword in ct_lower:
                char_visual = visual
                break
        if char_visual is None:
            char_visual = "human_child"
    char_visual = overrides.get("character") or char_visual

    # ── Light source (all 4 options, world-appropriate boost) ──
    all_lights = ["above", "backlit", "below", "ambient"]
    l_weights = {l: 1.0 for l in all_lights}
    # World-appropriate light gets a boost (not forced)
    # Spread light preferences across all 4 values (3 worlds each)
    world_light_pref = {
        "deep_ocean": "below", "underground_cave": "below", "ancient_library": "below",
        "desert_night": "backlit", "mountain_meadow": "backlit", "tropical_lagoon": "backlit",
        "cozy_interior": "ambient", "enchanted_forest": "ambient", "space_cosmos": "ambient",
        "cloud_kingdom": "above", "snow_landscape": "above", "floating_islands": "above",
    }
    if world in world_light_pref:
        l_weights[world_light_pref[world]] = l_weights.get(world_light_pref[world], 1.0) * _THEME_BOOST
    l_weights = _apply_recent_penalty(l_weights, recent.get("light", []))
    light = overrides.get("light") or _weighted_choice(all_lights, l_weights, _rng)

    # ── Texture (all 4 options, age-appropriate boost) ──
    all_textures = ["watercolor_soft", "soft_pastel", "digital_painterly", "paper_cutout"]
    t_weights = {t: 1.0 for t in all_textures}
    if age_group in ("0-1", "2-5"):
        t_weights["watercolor_soft"] *= 2.0
        t_weights["soft_pastel"] *= 2.0
    elif age_group == "6-8":
        t_weights["watercolor_soft"] *= 1.5
        t_weights["digital_painterly"] *= 1.5
        t_weights["soft_pastel"] *= 1.2
    else:  # 9-12+
        t_weights["digital_painterly"] *= 2.0
        t_weights["paper_cutout"] *= 1.5
    # TEMPORARY (March 2026): Boost underrepresented textures to rebalance
    # historical digital_painterly dominance. Remove after March 31.
    now = datetime.now()
    if now.year == 2026 and now.month == 3:
        t_weights["paper_cutout"] *= 2.5
        t_weights["watercolor_soft"] *= 2.0
        t_weights["soft_pastel"] *= 2.0
        t_weights["digital_painterly"] *= 0.5  # Dampen the overrepresented one
    t_weights = _apply_recent_penalty(t_weights, recent.get("texture", []))
    texture = overrides.get("texture") or _weighted_choice(all_textures, t_weights, _rng)

    # ── Time marker (all 4 options, context boost) ──
    all_times = ["early_night", "deep_night", "eternal_dusk", "timeless_indoor"]
    tm_weights = {t: 1.0 for t in all_times}
    if world == "cozy_interior":
        tm_weights["timeless_indoor"] *= _THEME_BOOST
    if "sunset" in desc_lower or "dusk" in desc_lower:
        tm_weights["eternal_dusk"] *= _CONTEXT_BOOST
    tm_weights = _apply_recent_penalty(tm_weights, recent.get("time", []))
    time_marker = overrides.get("time") or _weighted_choice(all_times, tm_weights, _rng)

    return {
        "world_setting": world,
        "palette": palette,
        "composition": comp,
        "character": char_visual,
        "light": light,
        "texture": texture,
        "time": time_marker,
    }


# ── Character extraction ───────────────────────────────────────────────

import re

def _extract_character_phrase(story: dict) -> str:
    """Extract the lead character identity from the story description.

    e.g. "A tiny raindrop named Drizzle embarks on..." → "a tiny raindrop named Drizzle"
         "When seven-year-old Aarohi discovers..." → "seven-year-old Aarohi"
         "A gentle tortoise named Pebble embarks..." → "a gentle tortoise named Pebble"
         "In a cottage... A little teacup named Chai watches..." → "a little teacup named Chai"
    """
    desc = story.get("description", "")
    if not desc:
        return ""

    # Try all sentences (not just the first) — character may be introduced later
    # e.g. "In a snug Arctic cottage... A little teacup named Chai watches..."
    sentences = re.split(r'[.!?]', desc)

    # First: scan for "a/an/the <descriptor> named <Name>" across ALL sentences
    for sent in sentences:
        sent = sent.strip()
        named_match = re.search(
            r'\b(an?\s+\w+(?:\s+\w+){0,3}\s+named\s+\w+)',
            sent, re.IGNORECASE
        )
        if named_match:
            return named_match.group(1).strip()

    first_sent = sentences[0].strip()

    # Common story-start verbs that mark the end of the character phrase
    verb_pattern = r'\b(embarks?|discovers?|learns?|finds?|begins?|sets?\s+out|ventures?|travels?|journeys?|explores?|weaves?|must|hears?|meets?|wakes?|searches?|stumbles?|follows?|seeks?|drifts?|wanders?|deciphers?|helps?|uncovers?|lights?|creates?|forges?|teaches?|guides?|says?|sings?|tells?|flies?|swims?|runs?|walks?|sits?|goes?|hums?|dances?|plays?|tends?|whispers?|races?|gathers?|collects?|lives?|works?)\b'

    # Strip common prefixes that precede the character phrase
    # "When seven-year-old Aarohi discovers..." → "seven-year-old Aarohi discovers..."
    # "In a futuristic city where X float, Aria discovers..." → harder, use comma split
    prefix_pattern = r'^(?:When|As|After|Before|In|On|During|While|One\s+night)\s+'
    if re.match(prefix_pattern, first_sent, re.IGNORECASE):
        # If there's a comma, the character is usually after the comma
        if ',' in first_sent:
            after_comma = first_sent.split(',', 1)[1].strip()
            if len(after_comma) > 5:
                first_sent = after_comma
        else:
            # Just strip the leading word
            first_sent = re.sub(prefix_pattern, '', first_sent, flags=re.IGNORECASE).strip()

    # Handle "Join X as..." pattern
    join_match = re.match(r'(?:Join|Meet|Follow)\s+(.+?)\s*(?:as|on|in|who)\b', first_sent, re.IGNORECASE)
    if join_match:
        return join_match.group(1).strip()

    # Strip "A gentle lullaby/story/poem about..." wrappers
    about_match = re.match(r'^A\s+(?:gentle\s+)?(?:lullaby|story|poem|song|tale)\s+about\s+', first_sent, re.IGNORECASE)
    if about_match:
        first_sent = first_sent[about_match.end():].strip()

    # Find verb and take everything before it as the character phrase
    verb_match = re.search(verb_pattern, first_sent, re.IGNORECASE)
    if verb_match:
        phrase = first_sent[:verb_match.start()].strip().rstrip(',')
        # Clean up common artifacts
        phrase = re.sub(r'\s+', ' ', phrase)
        # Cap at reasonable length for a FLUX prompt character description
        if len(phrase) > 60:
            short_match = re.search(r'\b(?:who|from|in\s+(?:a|an|the|her|his))\b', phrase)
            if short_match and short_match.start() > 10:
                phrase = phrase[:short_match.start()].strip().rstrip(',')
        if len(phrase) > 5:
            return phrase

    # Fallback: use title-based character name
    title = story.get("title", "")
    # Try to extract name from title patterns: "X and the Y", "X's Y"
    title_match = re.match(r"^(.+?)(?:\s+and the|[''\u2019]s)\s+", title)
    if title_match:
        return title_match.group(1).strip()

    return ""


def _build_human_appearance(story: dict) -> str:
    """Generate diverse human appearance descriptors using story ID as seed.

    Deterministic: same story always gets the same appearance.
    Gender-aware: picks from appropriate hair/clothing lists.
    """
    import hashlib
    story_id = story.get("id", story.get("title", "default"))
    gender = story.get("lead_gender", "neutral")
    # Use MD5 for stable, well-distributed hash across all story IDs
    digest = hashlib.md5(story_id.encode('utf-8')).digest()
    h1, h2, h3, h4 = digest[0], digest[1], digest[2], digest[3]

    # Pick gender-appropriate hair and clothing
    if gender == "male":
        hair_list = HAIR_STYLES_MALE
        clothing_list = CLOTHING_STYLES_MALE
    elif gender == "female":
        hair_list = HAIR_STYLES_FEMALE
        clothing_list = CLOTHING_STYLES_FEMALE
    else:
        hair_list = HAIR_STYLES_FEMALE if h4 % 2 == 0 else HAIR_STYLES_MALE
        clothing_list = CLOTHING_STYLES_FEMALE if h4 % 2 == 0 else CLOTHING_STYLES_MALE

    hair = hair_list[h1 % len(hair_list)]
    skin = SKIN_TONES[h2 % len(SKIN_TONES)]
    clothing = clothing_list[h3 % len(clothing_list)]

    return f"{skin}, {hair}, {clothing}"


# ── Mood-specific cover prompt modifiers (imported from mood_config) ────
from scripts.mood_config import (
    MOOD_COVER_PROMPTS, MOOD_PALETTE_BOOSTS, MOOD_COMPOSITION_BOOSTS,
)

# ── FLUX prompt builder ─────────────────────────────────────────────────

def build_flux_prompt(story: dict, axes: dict, mood: str = None) -> str:
    """Build FLUX AI prompt from story metadata and axis selections.

    Character description is context-aware:
    - Non-human leads (animal, object, insect, etc.) use the actual character
      identity from the story description
    - Human leads get diverse appearance traits (hair, skin, clothing)
    - All characters get world-appropriate poses and expressions
    """
    age_group = story.get("age_group", "6-8")

    world_info = WORLD_SETTINGS.get(axes["world_setting"], {})
    palette_info = COLOR_PALETTES.get(axes["palette"], {})
    comp_desc = COMPOSITIONS.get(axes["composition"], "")
    char_visual_key = axes["character"]
    char_visual_desc = CHARACTER_VISUALS.get(char_visual_key, "")
    light_desc = LIGHT_SOURCES.get(axes["light"], "")
    texture_desc = TEXTURES.get(axes["texture"], "")
    time_desc = TIME_MARKERS.get(axes["time"], "")

    char_gender = story.get("lead_gender", "female")
    char_age = story.get("character_age", 7)
    is_human = char_visual_key == "human_child"

    # Extract character phrase from description (e.g., "a tiny raindrop named Drizzle")
    char_phrase = _extract_character_phrase(story)

    # Build the character description for the prompt
    if is_human:
        # Human child — add diversity in appearance
        appearance = _build_human_appearance(story)
        gender_word = {"male": "boy", "female": "girl", "neutral": "child"}.get(char_gender, "child")
        if char_phrase and not any(w in char_phrase.lower() for w in ["child", "girl", "boy"]):
            # char_phrase has a name like "seven-year-old Aarohi"
            char_section = (
                f"{char_phrase}, a young {gender_word}, {appearance}, "
                f"bright curious eyes wide open, gentle smile, "
                f"looking with wonder at the magical world"
            )
        else:
            char_section = (
                f"a young {gender_word} (age {char_age}), {appearance}, "
                f"bright curious eyes wide open, gentle smile, "
                f"looking with wonder at the magical world"
            )
    else:
        # Non-human character — use the actual character identity
        # Strip diminutive size words so FLUX renders the character large
        if char_phrase:
            clean_phrase = re.sub(
                r'\b(a\s+)?(tiny|small|little|miniature|wee|itty-bitty)\b\s*',
                '', char_phrase, flags=re.IGNORECASE
            ).strip()
            clean_phrase = re.sub(r'\s+', ' ', clean_phrase)  # collapse double spaces
            # Remove leading "a/an" since we prepend "large"
            clean_phrase = re.sub(r'^(?:a|an)\s+', '', clean_phrase, flags=re.IGNORECASE)
            char_section = f"large {clean_phrase} character centered in frame, friendly expression"
        else:
            char_section = f"large {char_visual_desc} character centered in frame, friendly expression"

    # Age-specific art style additions
    if age_group in ("2-5", "0-1"):
        age_addition = "simple rounded shapes, soft and cuddly character design, picture book illustration quality, storybook warmth"
    elif age_group == "6-8":
        age_addition = "rich atmospheric environment, adventure illustration quality, detailed but soft world-building, Studio Ghibli inspired mood"
    else:
        age_addition = "cinematic concept art, atmospheric landscape, matte painting quality, sophisticated color grading, film still aesthetic"

    # Story-specific scene context (festivals, cultural elements, weather, etc.)
    cover_context = story.get("cover_context", "").strip()
    # Trim cover_context to keep prompt within URL limits
    if cover_context and len(cover_context) > 100:
        cover_context = cover_context[:100].rsplit(",", 1)[0].strip()
    context_section = f"{cover_context.lower().rstrip('.')}, " if cover_context else ""

    # Extract clean texture and composition names
    texture_name = texture_desc.split(",")[0].strip()
    comp_name = comp_desc.split(",")[0].strip().lower()

    # Mood-specific atmosphere clause
    mood_clause = ""
    if mood and mood in MOOD_COVER_PROMPTS:
        mood_clause = MOOD_COVER_PROMPTS[mood] + ", "

    # Character goes FIRST — FLUX weighs early tokens more, and truncation cuts from the end
    prompt = (
        f"{char_section}, "
        f"children's book illustration, {texture_name} style, "
        f"{mood_clause}"
        f"{context_section}"
        f"atmospheric {world_info.get('signature', 'magical scene').lower()}, "
        f"{comp_name}, "
        f"{light_desc.lower()}, "
        f"{palette_info.get('mood', 'warm').lower()} palette, "
        f"{time_desc.lower()}, "
        f"{age_addition}, "
        f"warm inviting mood, no text, soft atmospheric depth, sleep-safe muted colors"
    )

    return prompt


# ── FLUX Image Generation ────────────────────────────────────────────────

def generate_flux_image_pollinations(prompt: str) -> bytes:
    """Call Pollinations.ai FLUX endpoint (0.001 pollen/image).

    Pollinations uses a GET URL with prompt in the path, so we truncate
    long prompts to avoid Cloudflare 400 errors on oversized URLs.
    Auth required. Pollen balance resets weekly.
    """
    from urllib.parse import quote
    pollinations_token = os.getenv("POLLINATIONS_API_KEY", "")
    if not pollinations_token:
        logger.warning("POLLINATIONS_API_KEY not set, skipping Pollinations")
        return None

    # Truncate prompt to ~600 chars to stay within URL limits after encoding
    # (600 chars → ~900 encoded → ~1000 total URL, well under Cloudflare's 2048 limit)
    truncated = prompt[:600].rsplit(",", 1)[0] if len(prompt) > 600 else prompt
    encoded_prompt = quote(truncated, safe="")
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width=512&height=512&model=flux"
    headers = {"Authorization": f"Bearer {pollinations_token}"}

    logger.info("Calling FLUX via Pollinations.ai...")

    for attempt in range(3):
        try:
            response = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "image" in content_type or len(response.content) > 1000:
                    logger.info("Pollinations image received: %d bytes", len(response.content))
                    return response.content
                else:
                    logger.warning("Unexpected Pollinations response: %s", response.text[:500])

            elif response.status_code == 429:
                logger.warning("Pollinations rate limited, waiting 20s...")
                time.sleep(20)
                continue

            else:
                logger.error("Pollinations error %d: %s", response.status_code, response.text[:500])
                if attempt < 2:
                    time.sleep(10)
                    continue

        except httpx.TimeoutException:
            logger.warning("Pollinations timeout on attempt %d", attempt + 1)
            if attempt < 2:
                time.sleep(10)
                continue

    return None


def generate_flux_image_fluxapi(prompt: str) -> bytes:
    """Call FluxAPI.ai Kontext Pro endpoint (async task-based).

    Uses FLUXAPI_KEY env var. Creates a task, polls for result, downloads image.
    Returns image bytes or None on failure.
    """
    api_key = os.getenv("FLUXAPI_KEY", "")
    if not api_key:
        logger.warning("FLUXAPI_KEY not set, skipping FluxAPI.ai")
        return None

    logger.info("Calling FLUX via FluxAPI.ai (Kontext Pro)...")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt[:1500],  # Kontext supports longer prompts
        "aspectRatio": "1:1",
        "outputFormat": "png",
    }

    try:
        # Step 1: Create task
        create_url = "https://api.fluxapi.ai/api/v1/flux/kontext/generate"
        resp = httpx.post(create_url, headers=headers, json=payload, timeout=30)

        if resp.status_code != 200:
            logger.error("FluxAPI create error %d: %s", resp.status_code, resp.text[:300])
            return None

        data = resp.json()
        task_id = data.get("data", {}).get("taskId")
        if not task_id:
            logger.error("FluxAPI no taskId in response: %s", resp.text[:300])
            return None

        logger.info("FluxAPI task created: %s", task_id)

        # Step 2: Poll for result (up to 3 minutes)
        record_url = "https://api.fluxapi.ai/api/v1/flux/kontext/record-info"
        for attempt in range(36):  # 36 × 5s = 180s max
            time.sleep(5)
            poll = httpx.get(record_url, headers=headers, params={"taskId": task_id}, timeout=30)
            poll_data = poll.json().get("data", {})
            flag = poll_data.get("successFlag")

            if flag == 1:  # SUCCESS
                result_url = poll_data.get("response", {}).get("resultImageUrl")
                if not result_url:
                    logger.error("FluxAPI success but no resultImageUrl")
                    return None
                img_resp = httpx.get(result_url, timeout=60)
                if len(img_resp.content) > 1000:
                    logger.info("FluxAPI image received: %d bytes", len(img_resp.content))
                    return img_resp.content
                logger.warning("FluxAPI image too small: %d bytes", len(img_resp.content))
                return None
            elif flag in (2, 3):  # FAILED
                logger.error("FluxAPI task failed: %s", poll_data.get("errorMessage", "unknown"))
                return None

        logger.warning("FluxAPI task timed out after 3 minutes")
        return None

    except Exception as e:
        logger.error("FluxAPI error: %s", e)
        return None


def generate_flux_image_replicate(prompt: str) -> bytes:
    """Call Replicate FLUX.1-schnell API ($0.003/image).

    Uses the REPLICATE_API_TOKEN env var (also used for MusicGen).
    Returns image bytes or None on failure.
    """
    replicate_token = os.getenv("REPLICATE_API_TOKEN", "")
    if not replicate_token:
        logger.warning("REPLICATE_API_TOKEN not set, skipping Replicate")
        return None

    logger.info("Calling FLUX via Replicate...")
    try:
        import replicate

        output = replicate.run(
            "black-forest-labs/flux-schnell",
            input={
                "prompt": prompt,
                "num_outputs": 1,
                "aspect_ratio": "1:1",
                "output_format": "webp",
                "output_quality": 90,
                "go_fast": True,
            },
        )

        # output is a list of FileOutput objects
        for item in output:
            image_bytes = item.read()
            if len(image_bytes) > 1000:
                logger.info("Replicate image received: %d bytes", len(image_bytes))
                return image_bytes

        logger.warning("Replicate returned empty or small output")
        return None

    except Exception as e:
        logger.error("Replicate error: %s", e)
        return None


def generate_flux_image_together(prompt: str) -> bytes:
    """Call Together AI FLUX.1-schnell endpoint.

    Uses TOGETHER_API_KEY env var. OpenAI-compatible images API.
    Returns image bytes or None on failure.
    """
    api_key = os.getenv("TOGETHER_API_KEY", "")
    if not api_key:
        logger.warning("TOGETHER_API_KEY not set, skipping Together AI")
        return None

    logger.info("Calling FLUX via Together AI...")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell",
        "prompt": prompt[:1500],
        "width": 512,
        "height": 512,
        "steps": 4,
        "n": 1,
        "response_format": "b64_json",
    }

    for attempt in range(3):
        try:
            resp = httpx.post(
                "https://api.together.xyz/v1/images/generations",
                headers=headers, json=payload, timeout=120
            )
            if resp.status_code == 200:
                data = resp.json()
                b64_data = data["data"][0]["b64_json"]
                import base64 as _b64
                image_bytes = _b64.b64decode(b64_data)
                if len(image_bytes) > 1000:
                    logger.info("Together AI image received: %d bytes", len(image_bytes))
                    return image_bytes
                logger.warning("Together AI image too small: %d bytes", len(image_bytes))
            elif resp.status_code == 429:
                logger.warning("Together AI rate limited, waiting 15s...")
                time.sleep(15)
                continue
            else:
                logger.error("Together AI error %d: %s", resp.status_code, resp.text[:300])
                if attempt < 2:
                    time.sleep(5)
                    continue
        except httpx.TimeoutException:
            logger.warning("Together AI timeout on attempt %d", attempt + 1)
            if attempt < 2:
                time.sleep(5)
                continue
        except Exception as e:
            logger.error("Together AI error: %s", e)
            return None

    return None


def generate_flux_image(prompt: str, hf_token: str = None) -> bytes:
    """Generate a FLUX image. Tries Pollinations → Together AI → FluxAPI.ai → Replicate."""
    # Primary: Pollinations (pollen balance resets weekly)
    result = generate_flux_image_pollinations(prompt)
    if result:
        return result

    # Fallback 1: Together AI (free tier: FLUX.1-schnell-Free)
    logger.info("Pollinations failed, trying Together AI fallback...")
    result = generate_flux_image_together(prompt)
    if result:
        return result

    # Fallback 2: FluxAPI.ai (free trial credits)
    logger.info("Together AI failed, trying FluxAPI fallback...")
    result = generate_flux_image_fluxapi(prompt)
    if result:
        return result

    # Fallback 3: Replicate ($0.003/image)
    logger.info("FluxAPI failed, trying Replicate fallback...")
    return generate_flux_image_replicate(prompt)


def save_as_webp(image_bytes: bytes, output_path: Path, quality: int = 80) -> int:
    """Convert image bytes to WebP, return file size in bytes."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")

    # Resize to 512x512 if needed (cover standard size)
    if img.size != (512, 512):
        img = img.resize((512, 512), Image.LANCZOS)

    img.save(output_path, "WebP", quality=quality)
    size = output_path.stat().st_size
    logger.info("Saved WebP: %s (%d KB)", output_path.name, size // 1024)

    # If too large, reduce quality
    if size > 40960:  # 40 KB
        for q in [70, 60, 50]:
            img.save(output_path, "WebP", quality=q)
            size = output_path.stat().st_size
            if size <= 40960:
                logger.info("Reduced quality to %d: %d KB", q, size // 1024)
                break

    return size



# ── Preview HTML Generator ──────────────────────────────────────────────

def generate_combined_svg(bg_path: Path, svg_overlay: str, axes: dict = None, story: dict = None) -> str:
    """Create a V3 combined SVG with cinemagraph filters + lean overlay.

    Uses the 3-layer architecture: background in <defs>, filtered <use> regions,
    lean SMIL overlay on top. Falls back to v2 (flat overlay) if axes/story missing.
    """
    import base64
    import re

    with open(bg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    # V3 path: use cinemagraph filters + lean overlay
    if axes and story and axes.get("world_setting"):
        return generate_v3_combined_svg(b64, axes, story)

    # V2 fallback: simple background + overlay
    match = re.search(r'<svg[^>]*>(.*)</svg>', svg_overlay, re.DOTALL)
    inner = match.group(1) if match else svg_overlay

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" width="512" height="512">
  <!-- Layer 1: FLUX AI Background (embedded WebP) -->
  <image width="512" height="512" href="data:image/webp;base64,{b64}" />
{inner}
</svg>'''


def generate_preview_html(story_id: str, title: str, axes: dict, prompt: str) -> str:
    """Generate an HTML file for previewing the layered cover."""
    bg_file = f"{story_id}_background.webp"
    svg_file = f"{story_id}_overlay.svg"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cover Preview: {title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #111;
    color: #ccc;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
    min-height: 100vh;
  }}
  h1 {{ color: #FFE4B5; margin-bottom: 8px; font-size: 1.4em; }}
  .subtitle {{ color: #888; margin-bottom: 30px; font-size: 0.9em; }}
  .cover-container {{
    position: relative;
    width: 512px;
    height: 512px;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  }}
  .cover-bg {{
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    object-fit: cover;
  }}
  .cover-overlay {{
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    pointer-events: none;
  }}
  .info {{
    margin-top: 30px;
    max-width: 600px;
    background: #1a1a1a;
    border-radius: 12px;
    padding: 20px;
    font-size: 0.85em;
    line-height: 1.6;
  }}
  .info h3 {{ color: #FFE4B5; margin-bottom: 10px; }}
  .info dt {{ color: #aaa; float: left; width: 120px; }}
  .info dd {{ margin-left: 130px; margin-bottom: 6px; }}
  .prompt {{ margin-top: 15px; padding: 12px; background: #222; border-radius: 8px; font-size: 0.8em; word-break: break-word; }}
  .controls {{
    margin-top: 20px;
    display: flex;
    gap: 12px;
  }}
  button {{
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid #444;
    background: #222;
    color: #ccc;
    cursor: pointer;
    font-size: 0.85em;
  }}
  button:hover {{ background: #333; }}
  .phase-label {{ color: #FFE4B5; margin-top: 10px; text-align: center; font-size: 0.9em; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <p class="subtitle">Experimental Cover Preview — 2-Layer Architecture</p>

  <div class="cover-container" id="coverContainer">
    <img class="cover-bg" src="{bg_file}" alt="Background" />
    <object class="cover-overlay" data="{svg_file}" type="image/svg+xml"></object>
  </div>

  <div class="controls">
    <button onclick="toggleOverlay()">Toggle Overlay</button>
    <button onclick="simulatePhase('capture')">Phase 1: Capture</button>
    <button onclick="simulatePhase('descent')">Phase 2: Descent</button>
    <button onclick="simulatePhase('sleep')">Phase 3: Sleep</button>
  </div>
  <div class="phase-label" id="phaseLabel">Resting State</div>

  <div class="info">
    <h3>Diversity Axes</h3>
    <dl>
      <dt>World:</dt><dd>{axes['world_setting'].replace('_', ' ').title()}</dd>
      <dt>Palette:</dt><dd>{axes['palette'].replace('_', ' ').title()}</dd>
      <dt>Composition:</dt><dd>{axes['composition'].replace('_', ' ').title()}</dd>
      <dt>Character:</dt><dd>{axes['character'].replace('_', ' ').title()}</dd>
      <dt>Light:</dt><dd>{axes['light'].replace('_', ' ').title()}</dd>
      <dt>Texture:</dt><dd>{axes['texture'].replace('_', ' ').title()}</dd>
      <dt>Time:</dt><dd>{axes['time'].replace('_', ' ').title()}</dd>
    </dl>
    <div class="prompt">
      <strong>FLUX Prompt:</strong><br>{prompt}
    </div>
  </div>

  <script>
    let overlayVisible = true;
    function toggleOverlay() {{
      const overlay = document.querySelector('.cover-overlay');
      overlayVisible = !overlayVisible;
      overlay.style.display = overlayVisible ? 'block' : 'none';
    }}

    function simulatePhase(phase) {{
      const bg = document.querySelector('.cover-bg');
      const overlay = document.querySelector('.cover-overlay');
      const label = document.getElementById('phaseLabel');

      if (phase === 'capture') {{
        bg.style.filter = 'brightness(1) saturate(1)';
        overlay.style.opacity = '1';
        label.textContent = 'Phase 1: Capture — Full brightness';
      }} else if (phase === 'descent') {{
        bg.style.filter = 'brightness(0.85) saturate(0.8) sepia(0.1)';
        overlay.style.opacity = '0.8';
        label.textContent = 'Phase 2: Descent — Dimming';
      }} else if (phase === 'sleep') {{
        bg.style.filter = 'brightness(0.5) saturate(0.5) sepia(0.2)';
        overlay.style.opacity = '0.5';
        label.textContent = 'Phase 3: Sleep — Near dark';
      }}
    }}
  </script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate experimental 2-layer cover")
    parser.add_argument("--story-json", required=True, help="Path to story JSON file")
    parser.add_argument("--world-setting", help="Override world setting (e.g., enchanted_forest)")
    parser.add_argument("--palette", help="Override color palette (e.g., golden_hour)")
    parser.add_argument("--composition", help="Override composition (e.g., winding_path)")
    parser.add_argument("--texture", help="Override texture (e.g., digital_painterly)")
    parser.add_argument("--dry-run", action="store_true", help="Show prompt without calling API")
    parser.add_argument("--mood", choices=["wired", "curious", "calm", "sad", "anxious", "angry"],
                        default=None, help="Target mood for cover atmosphere (experimental)")
    args = parser.parse_args()

    # Load story
    story_path = Path(args.story_json)
    if not story_path.exists():
        logger.error("Story file not found: %s", story_path)
        sys.exit(1)

    with open(story_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    story_id = story.get("id", "unknown")
    title = story.get("title", "Untitled")
    logger.info("Generating cover for: '%s' (%s)", title, story_id)

    # Build overrides from CLI args
    overrides = {}
    if args.world_setting:
        overrides["world_setting"] = args.world_setting
    if args.palette:
        overrides["palette"] = args.palette
    if args.composition:
        overrides["composition"] = args.composition
    if args.texture:
        overrides["texture"] = args.texture

    # Auto-select axes
    axes = auto_select_axes(story, overrides, mood=args.mood)
    logger.info("Axes: %s", json.dumps(axes, indent=2))

    # Build FLUX prompt
    prompt = build_flux_prompt(story, axes, mood=args.mood)
    logger.info("FLUX prompt (%d chars): %s", len(prompt), prompt[:300])

    if args.dry_run:
        print("\n=== DRY RUN ===")
        print(f"\nStory: {title} ({story_id})")
        print(f"\nAxes: {json.dumps(axes, indent=2)}")
        print(f"\nFLUX Prompt:\n{prompt}")
        print(f"\nAnimations: {WORLD_ELEMENTS.get(axes['world_setting'], {})}")
        return

    # Save axes to history for cross-story diversity tracking
    _save_axes_history(story_id, axes)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate FLUX image via Pollinations.ai
    image_bytes = generate_flux_image(prompt)
    if not image_bytes:
        logger.error("Failed to generate FLUX image")
        sys.exit(1)

    # Save as WebP
    bg_path = OUTPUT_DIR / f"{story_id}_background.webp"
    save_as_webp(image_bytes, bg_path)

    # Generate SVG overlay
    logger.info("Generating SVG overlay...")
    svg_content = generate_svg_overlay(axes, story)
    svg_path = OUTPUT_DIR / f"{story_id}_overlay.svg"
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    svg_size = svg_path.stat().st_size
    logger.info("Saved SVG: %s (%d KB)", svg_path.name, svg_size // 1024)

    # Generate combined SVG (V3: cinemagraph filters + lean overlay)
    logger.info("Generating V3 combined SVG (cinemagraph filters)...")
    combined_svg = generate_combined_svg(bg_path, svg_content, axes=axes, story=story)
    combined_path = OUTPUT_DIR / f"{story_id}_combined.svg"
    with open(combined_path, "w", encoding="utf-8") as f:
        f.write(combined_svg)
    combined_size = combined_path.stat().st_size
    logger.info("Saved combined SVG: %s (%d KB)", combined_path.name, combined_size // 1024)

    # Copy combined SVG to frontend public/covers/
    web_covers = BASE_DIR.parent / "dreamweaver-web" / "public" / "covers"
    if web_covers.exists():
        import shutil
        dest = web_covers / f"{story_id}.svg"
        shutil.copy2(combined_path, dest)
        logger.info("Copied to frontend: %s", dest)

    # Update cover path in content.json
    content_path = SEED_OUTPUT / "content.json"
    if content_path.exists():
        try:
            with open(content_path, "r", encoding="utf-8") as f:
                all_stories = json.load(f)
            for s in all_stories:
                if s["id"] == story_id:
                    s["cover"] = f"/covers/{story_id}.svg"
                    logger.info("Updated cover path in content.json: %s", s["cover"])
                    break
            with open(content_path, "w", encoding="utf-8") as f:
                json.dump(all_stories, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            logger.warning("Could not update content.json: %s", e)

    # Generate preview HTML
    logger.info("Generating preview HTML...")
    html_content = generate_preview_html(story_id, title, axes, prompt)
    html_path = OUTPUT_DIR / f"{story_id}_preview.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("")
    logger.info("=== COVER GENERATED ===")
    logger.info("Background: %s", bg_path)
    logger.info("Overlay:    %s", svg_path)
    logger.info("Combined:   %s (%d KB)", combined_path, combined_size // 1024)
    logger.info("Preview:    %s", html_path)
    logger.info("")
    logger.info("OK: %s", combined_path)
    logger.info("Open the preview in your browser:")
    logger.info("  open %s", html_path)


if __name__ == "__main__":
    main()
