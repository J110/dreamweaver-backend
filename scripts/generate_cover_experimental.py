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
import random
import sys
import time
from pathlib import Path

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


# ── SMIL Animation Bible v2 — World-to-Element Mapping ──────────────────
#
# Replaces flat WORLD_TO_ANIMATIONS with required/select/optional structure.
# Each world gets exactly 1 breathing pacer (required) + 2-3 pool picks + optional.

WORLD_ELEMENTS = {
    "enchanted_forest": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["fireflies", "dust_motes", "swaying_branches",
                            "falling_leaves", "sleeping_butterfly", "cricket", "fog"], "pick": (2, 3)},
        "optional": ["stars", "sleeping_owl"],
        "vignette": "bottom_heavy",
        "pacer_variant": "forest",
    },
    "deep_ocean": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["bubbles", "caustics", "fog"], "pick": (2, 3)},
        "optional": ["dust_motes"],
        "vignette": "top_heavy",
        "pacer_variant": "ocean",
    },
    "space_cosmos": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["stars", "shooting_star", "aurora"], "pick": (2, 3)},
        "optional": ["dust_motes"],
        "vignette": "corners_only",
        "pacer_variant": "space",
    },
    "snow_landscape": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["snowfall", "stars", "aurora", "fog"], "pick": (2, 3)},
        "optional": ["chimney_smoke"],
        "vignette": "none",
        "pacer_variant": "forest",
    },
    "cozy_interior": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["candle_flicker", "dust_motes", "shadow_play"], "pick": (2, 3)},
        "optional": ["chimney_smoke", "sleeping_butterfly"],
        "vignette": "full_soft",
        "pacer_variant": "interior",
    },
    "desert_night": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["stars", "shooting_star", "fog"], "pick": (2, 3)},
        "optional": ["cricket", "wind_grass"],
        "vignette": "top_corners",
        "pacer_variant": "space",
    },
    "mountain_meadow": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["fireflies", "stars", "wind_grass", "fog"], "pick": (2, 3)},
        "optional": ["cricket", "sleeping_butterfly", "falling_leaves"],
        "vignette": "bottom_light",
        "pacer_variant": "forest",
    },
    "cloud_kingdom": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["stars", "fog", "dust_motes"], "pick": (2, 3)},
        "optional": ["aurora", "moon_glow"],
        "vignette": "none",
        "pacer_variant": "space",
    },
    "underground_cave": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["candle_flicker", "dust_motes", "fog"], "pick": (2, 3)},
        "optional": ["caustics", "bubbles"],
        "vignette": "full_heavy",
        "pacer_variant": "forest",
    },
    "tropical_lagoon": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["water_ripples", "fireflies", "stars"], "pick": (2, 3)},
        "optional": ["fog", "cricket"],
        "vignette": "top_heavy",
        "pacer_variant": "ocean",
    },
    "ancient_library": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["dust_motes", "candle_flicker", "shadow_play"], "pick": (2, 3)},
        "optional": ["sleeping_butterfly", "stars"],
        "vignette": "full_soft",
        "pacer_variant": "interior",
    },
    "floating_islands": {
        "required": ["breathing_pacer"],
        "select": {"pool": ["fog", "stars", "dust_motes"], "pick": (2, 3)},
        "optional": ["falling_leaves", "aurora"],
        "vignette": "none",
        "pacer_variant": "space",
    },
}


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
    4-8 stars, upper 40%, 6-14s durations, peak 0.25-0.50.
    """
    count = rng.randint(4, 8)
    parts = ['<!-- A1: Twinkling Stars -->\n<g id="stars">']
    star_colors = _BIBLE_COLORS["star"]
    for i in range(count):
        cx = rng.randint(5, 95)
        cy = rng.randint(5, 40)
        r = round(rng.uniform(0.8, 2.0), 1)
        color = rng.choice(star_colors)
        dur = _pick_prime_dur(6, 14, rng)
        begin = round(rng.uniform(0, 10), 1)
        peak = round(rng.uniform(0.25, 0.50), 2)
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
    Always arcs downward. 6-10s visible portion.
    """
    interval = rng.randint(30, 90)
    vis_dur = _pick_prime_dur(6, 11, rng)
    x1 = rng.randint(-50, 50)
    y1 = rng.randint(-30, 20)
    x2 = rng.randint(200, 350)
    y2 = rng.randint(50, 100)
    xm = (x1 + x2) // 2 + rng.randint(-30, 30)
    ym = (y1 + y2) // 2 + rng.randint(-10, 10)
    path = f"M{x1},{y1} Q{xm},{ym} {x2},{y2}"
    color_head = _warm_color(rng, "star")
    color_tail = _warm_color(rng, "glow")
    # Mostly invisible with brief flash
    vis_vals = "0;0;0.5;0.5;0;0;0;0;0;0;0;0;0"
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
    """A3. Crescent moon glow — soft warm radial in upper 25%, breathing pulse 7-10s."""
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
        f'    <stop offset="0%" stop-color="{core_color}" stop-opacity="0.25"/>\n'
        f'    <stop offset="40%" stop-color="{halo_color}" stop-opacity="0.1"/>\n'
        f'    <stop offset="100%" stop-color="{halo_color}" stop-opacity="0"/>\n'
        f'  </radialGradient>\n'
        f'  <circle cx="{cx}%" cy="{cy}%" r="{halo_r}" fill="url(#{grad_id})">\n'
        f'    <animate attributeName="r" values="{r_lo};{r_hi};{r_lo}" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'    <animate attributeName="opacity" values="0.45;0.60;0.45" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'  </circle>\n'
        f'  <circle cx="{cx}%" cy="{cy}%" r="{core_r}" fill="{core_color}" opacity="0.15">\n'
        f'    <animate attributeName="opacity" values="0.12;0.18;0.12" dur="{dur}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
        f'  </circle>\n'
        f'</g>'
    )


def _gen_aurora(colors, world, story, rng):
    """A4. Aurora / Northern Lights — very slow undulating bands, upper 30%.
    2-4 bands, desaturated warm tones, prime-number durations.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- A4: Aurora -->\n<g id="aurora" opacity="0.2">']
    aurora_colors = _BIBLE_COLORS["aurora"]
    for i in range(count):
        cx = rng.randint(35, 65)
        cy = rng.randint(12, 28)
        rx = rng.randint(150, 220)
        ry = rng.randint(20, 40)
        color = rng.choice(aurora_colors)
        op_base = round(rng.uniform(0.08, 0.18), 2)
        dur_t = _pick_prime_dur(23, 37, rng)
        dur_o = _pick_prime_dur(29, 41, rng)
        dur_ry = _pick_prime_dur(19, 31, rng)
        tx1, ty1 = rng.randint(10, 20), rng.randint(2, 6)
        tx2, ty2 = rng.randint(-15, -5), rng.randint(1, 5)
        tx3, ty3 = rng.randint(3, 8), rng.randint(-3, -1)
        op_hi = min(op_base + 0.10, 0.28)
        op_vals = f"{op_base:.2f};{op_base + 0.08:.2f};{op_base + 0.02:.2f};{op_hi:.2f};{op_base:.2f}"
        ry_vals = f"{ry - 3};{ry + 7};{ry - 5};{ry + 4};{ry - 3}"
        parts.append(
            f'  <ellipse cx="{cx}%" cy="{cy}%" rx="{rx}" ry="{ry}" fill="{color}" opacity="{op_base:.2f}">\n'
            f'    <animateTransform attributeName="transform" type="translate"\n'
            f'      values="0,0; {tx1},{ty1}; {tx2},{ty2}; {tx3},{ty3}; 0,0" dur="{dur_t}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'    <animate attributeName="opacity" values="{op_vals}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'    <animate attributeName="ry" values="{ry_vals}"\n'
            f'      dur="{dur_ry}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


# ── Category B: Atmospheric ──────────────────────────────────────────────

def _gen_fog(colors, world, story, rng):
    """B1. Drifting fog/mist — large low-opacity shapes, lower 55-85%.
    2-4 layers, 40-80s cycles, 0.03-0.12 opacity, alternate directions.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- B1: Drifting Fog -->\n<g id="fog-layers">']
    fog_colors = _BIBLE_COLORS["fog"]
    for i in range(count):
        cx = rng.randint(20, 80)
        cy = rng.randint(55, 85)
        rx = rng.randint(200, 350)
        ry = rng.randint(30, 60)
        color = rng.choice(fog_colors)
        op_base = round(rng.uniform(0.03, 0.08), 2)
        dur_t = _pick_prime_dur(41, 79, rng)
        dur_o = _pick_prime_dur(37, 67, rng)
        drift = rng.randint(60, 120) * (1 if i % 2 == 0 else -1)
        op_vals = f"{op_base:.2f};{op_base + 0.04:.2f};{op_base + 0.02:.2f};{min(op_base + 0.06, 0.12):.2f};{op_base:.2f}"
        parts.append(
            f'  <ellipse cx="{cx}%" cy="{cy}%" rx="{rx}" ry="{ry}" fill="{color}" opacity="{op_base:.2f}">\n'
            f'    <animateTransform attributeName="transform" type="translate"\n'
            f'      values="0,0; {drift},3; {drift * 2},0; {drift},-3; 0,0"\n'
            f'      dur="{dur_t}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(4)}"/>\n'
            f'    <animate attributeName="opacity" values="{op_vals}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


def _gen_rain(colors, world, story, rng):
    """B2. Gentle rain — thin lines drifting down at slight angle.
    5-10 drops, 3-8 deg leftward, warm grey, 3.5-5.5s.
    """
    count = rng.randint(5, 10)
    parts = ['<!-- B2: Gentle Rain -->\n<g id="rain" opacity="0.15">']
    rain_colors = _BIBLE_COLORS["rain"]
    for i in range(count):
        x = rng.randint(5, 95)
        color = rng.choice(rain_colors)
        dur = round(rng.uniform(3.5, 5.5), 1)
        begin = round(rng.uniform(0, 4), 1)
        width = round(rng.uniform(0.4, 0.8), 1)
        angle_drift = rng.randint(-12, -4)
        op = round(rng.uniform(0.2, 0.35), 2)
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
    4-7 flakes, 14-28s, unique paths.
    """
    count = rng.randint(4, 7)
    parts = ['<!-- B3: Falling Snow -->\n<g id="snowfall" opacity="0.25">']
    snow_colors = _BIBLE_COLORS["snow"]
    for i in range(count):
        r = round(rng.uniform(0.8, 3.0), 1)
        color = rng.choice(snow_colors)
        dur = _pick_prime_dur(13, 29, rng)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.25, 0.40), 2)
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
    """B4. Floating dust motes — tiny particles drifting in light area.
    3-6 motes, non-directional, 10-20s, opacity fluctuates.
    """
    count = rng.randint(3, 6)
    parts = ['<!-- B4: Dust Motes -->\n<g id="dust-motes">']
    mote_color = colors.get("particle", "#FFE8C8")
    for i in range(count):
        r = round(rng.uniform(0.6, 1.8), 1)
        dur = _pick_prime_dur(11, 19, rng)
        begin = round(rng.uniform(0, 6), 1)
        peak_op = round(rng.uniform(0.15, 0.40), 2)
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
    2-4 patterns, all properties on different prime durations.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- B5: Underwater Caustics -->\n<g id="caustics" opacity="0.08">']
    caustic_color = colors.get("glow", "#FFE8C8")
    for i in range(count):
        cx = rng.randint(25, 75)
        cy = rng.randint(40, 80)
        rx = rng.randint(30, 60)
        ry = rng.randint(18, 35)
        op = round(rng.uniform(0.06, 0.14), 2)
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
            f'    <animate attributeName="opacity" values="{op:.2f};{min(op + 0.06, 0.20):.2f};{op + 0.02:.2f};{min(op + 0.08, 0.20):.2f};{op:.2f}"\n'
            f'      dur="{dur_o}s" repeatCount="indefinite"/>\n'
            f'  </ellipse>'
        )
    parts.append('</g>')
    return "\n".join(parts)


# ── Category C: Flora ────────────────────────────────────────────────────

def _gen_swaying_branches(colors, world, story, rng):
    """C1. Swaying branches — silhouettes at frame edges, 2-5 deg, 8-15s."""
    edges = rng.sample(["left", "right"], k=rng.randint(1, 2))
    branch_color = _warm_color(rng, "branch")
    parts = ['<!-- C1: Swaying Branches -->']
    for edge in edges:
        dur = _pick_prime_dur(7, 17, rng)
        sway = rng.randint(2, 5)
        op = round(rng.uniform(0.08, 0.18), 2)
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
    Warm earth tones, 16-28s.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- C2: Falling Leaves -->\n<g id="falling-leaves">']
    leaf_colors = _BIBLE_COLORS["leaf"]
    for i in range(count):
        rx = rng.randint(3, 7)
        ry = max(2, int(rx * 0.6))
        color = rng.choice(leaf_colors)
        dur = _pick_prime_dur(17, 29, rng)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.15, 0.25), 2)
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
    18-28s drift, 6-12s pulse, mostly dark with brief flash.
    """
    count = rng.randint(3, 5)
    parts = ['<!-- D1: Fireflies -->\n<g id="fireflies">']
    fly_color = colors.get("glow", "#FFD89C")
    for i in range(count):
        core_r = round(rng.uniform(2.0, 2.8), 1)
        outer_r = round(core_r * 3.5, 1)
        drift_dur = _pick_prime_dur(17, 29, rng)
        pulse_dur = _pick_prime_dur(7, 13, rng)
        begin = round(rng.uniform(0, 8), 1)
        cx = rng.randint(60, 440)
        cy = rng.randint(180, 380)
        pts = []
        for j in range(6):
            pts.append(f"{cx + rng.randint(-20, 20)},{cy + rng.randint(-15, 15)}")
        path = f"M{cx},{cy} C{pts[0]} {pts[1]} {pts[2]} S{pts[3]} {pts[4]}"
        pulse_vals = "0;0.05;0.4;0.45;0.1;0;0;0"
        outer_vals = "0;0.01;0.1;0.12;0.03;0;0;0"
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
    """D2. Sleeping butterfly/moth — 1-2 wing pairs, 10-20 deg open/close, 8-12s."""
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
        op = round(rng.uniform(0.12, 0.18), 2)
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
    """D3. Sleeping owl — silhouette at edge, eyes close one-time (fill="freeze")."""
    ox = rng.choice([rng.randint(80, 92), rng.randint(8, 20)])
    oy = rng.randint(30, 50)
    shadow_color = _warm_color(rng, "shadow")
    eye_color = _warm_color(rng, "glow")
    eye_begin = rng.randint(10, 60)
    eye_dur = rng.randint(20, 40)
    eye2_delay = round(rng.uniform(0.5, 2.0), 1)
    op = round(rng.uniform(0.15, 0.25), 2)
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
    """D4. Resting cricket — 1-2 tiny silhouettes, rare twitches every 15-25s."""
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
    1-2 sources, 2-4 rings each, 10-16s.
    """
    sources = rng.randint(1, 2)
    parts = ['<!-- E1: Water Ripples -->']
    ring_color = colors.get("particle", "#D4C8B8")
    for s in range(sources):
        sx = rng.randint(25, 75)
        sy = rng.randint(60, 80)
        ring_count = rng.randint(2, 4)
        dur = _pick_prime_dur(11, 17, rng)
        stagger = round(dur / ring_count, 1)
        max_r = rng.randint(30, 60)
        rings = []
        for ri in range(ring_count):
            begin = round(stagger * ri, 1)
            op_peak = round(0.2 - ri * 0.03, 2)
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
    """E2. Slow underwater bubbles — 2-4 stroke-only circles, slow rise.
    Grow as they rise, 18-30s. Exception: upward motion is physically correct.
    """
    count = rng.randint(2, 4)
    parts = ['<!-- E2: Slow Bubbles -->\n<g id="bubbles" opacity="0.2">']
    bubble_color = colors.get("particle", "#E8D8C4")
    for i in range(count):
        r_start = round(rng.uniform(1.5, 3.0), 1)
        r_end = round(r_start + rng.uniform(1.0, 2.0), 1)
        dur = _pick_prime_dur(17, 31, rng)
        begin = round(rng.uniform(0, 8), 1)
        op = round(rng.uniform(0.15, 0.28), 2)
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
    Irregular +-15% flicker band. Multiple prime durations per property.
    """
    cx = rng.randint(20, 80)
    cy = rng.randint(45, 75)
    glow_r = rng.randint(30, 60)
    core_r = rng.randint(4, 6)
    dur_o = _pick_prime_dur(5, 7, rng)
    dur_r = _pick_prime_dur(6, 8, rng)
    dur_core = _pick_prime_dur(4, 6, rng)
    glow_outer = colors.get("glow", "#FFCA78")
    glow_inner = colors.get("star", "#FFF0D0")
    grad_id = f"flameG{rng.randint(100, 999)}"
    op_vals = ";".join([f"{0.5 + rng.uniform(-0.08, 0.10):.2f}" for _ in range(10)])
    r_vals = ";".join([str(glow_r + rng.randint(-4, 6)) for _ in range(10)])
    core_op = ";".join([f"{0.25 + rng.uniform(0, 0.13):.2f}" for _ in range(7)])
    cy_vals = ";".join([str(-2 + rng.randint(-2, 1)) for _ in range(5)])
    return (
        f'<!-- F1: Candle Flicker -->\n'
        f'<g id="candle-glow" transform="translate({cx}%, {cy}%)">\n'
        f'  <radialGradient id="{grad_id}">\n'
        f'    <stop offset="0%" stop-color="{glow_inner}" stop-opacity="0.4"/>\n'
        f'    <stop offset="30%" stop-color="{glow_outer}" stop-opacity="0.15"/>\n'
        f'    <stop offset="100%" stop-color="{glow_outer}" stop-opacity="0"/>\n'
        f'  </radialGradient>\n'
        f'  <circle cx="0" cy="0" r="{glow_r}" fill="url(#{grad_id})">\n'
        f'    <animate attributeName="opacity" values="{op_vals}"\n'
        f'      dur="{dur_o}s" repeatCount="indefinite"\n'
        f'      calcMode="spline" keySplines="{_smil_spline(9)}"/>\n'
        f'    <animate attributeName="r" values="{r_vals}"\n'
        f'      dur="{dur_r}s" repeatCount="indefinite"/>\n'
        f'  </circle>\n'
        f'  <circle cx="0" cy="-3" r="{core_r}" fill="{glow_inner}" opacity="0.3">\n'
        f'    <animate attributeName="opacity" values="{core_op}"\n'
        f'      dur="{dur_core}s" repeatCount="indefinite"/>\n'
        f'    <animate attributeName="cy" values="{cy_vals}"\n'
        f'      dur="{_pick_prime_dur(4, 6, rng)}s" repeatCount="indefinite"/>\n'
        f'  </circle>\n'
        f'</g>'
    )


def _gen_shadow_play(colors, world, story, rng):
    """F2. Shadow play — soft dark shapes, 12-25s, 0.03-0.10 opacity."""
    count = rng.randint(1, 3)
    parts = ['<!-- F2: Shadow Play -->\n<g id="window-shadows" opacity="0.06">']
    shadow_color = _warm_color(rng, "shadow")
    for i in range(count):
        dur = _pick_prime_dur(13, 23, rng)
        op = round(rng.uniform(0.03, 0.10), 2)
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
    4 world-specific variants via pacer_variant. dur=8s base.
    """
    dur = 8
    glow_color = colors.get("glow", "#FFD89C")
    star_color = colors.get("star", "#FFF5E0")
    mapping = WORLD_ELEMENTS.get(world, WORLD_ELEMENTS["enchanted_forest"])
    variant = mapping.get("pacer_variant", "forest")
    grad_id = f"breathG{rng.randint(100, 999)}"

    if variant == "ocean":
        cx, cy = "50%", "60%"
        rx_base, ry_base = 20, 25
        return (
            f'<!-- F3: Breathing Pacer (Ocean) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.4"/>\n'
            f'    <stop offset="40%" stop-color="{glow_color}" stop-opacity="0.15"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <ellipse cx="{cx}" cy="{cy}" rx="{rx_base}" ry="{ry_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="ry" values="{ry_base - 3};{ry_base + 3};{ry_base - 3}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="rx" values="{rx_base - 2};{rx_base + 2};{rx_base - 2}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.3;0.5;0.3" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </ellipse>\n'
            f'</g>'
        )
    elif variant == "space":
        cx, cy = "50%", "50%"
        r_base = 35
        return (
            f'<!-- F3: Breathing Pacer (Space) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{star_color}" stop-opacity="0.35"/>\n'
            f'    <stop offset="60%" stop-color="{glow_color}" stop-opacity="0.1"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 5};{r_base + 3};{r_base - 5}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.3;0.5;0.3" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )
    elif variant == "interior":
        cx, cy = "35%", "55%"
        r_base = 30
        return (
            f'<!-- F3: Breathing Pacer (Interior) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.45"/>\n'
            f'    <stop offset="40%" stop-color="{glow_color}" stop-opacity="0.15"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 4};{r_base + 2};{r_base - 4}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.35;0.55;0.35" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )
    else:  # forest (default)
        cx, cy = "50%", "70%"
        r_base = 25
        return (
            f'<!-- F3: Breathing Pacer (Forest) -->\n'
            f'<g id="breath-pacer">\n'
            f'  <radialGradient id="{grad_id}">\n'
            f'    <stop offset="0%" stop-color="{glow_color}" stop-opacity="0.45"/>\n'
            f'    <stop offset="50%" stop-color="{glow_color}" stop-opacity="0.15"/>\n'
            f'    <stop offset="100%" stop-color="{glow_color}" stop-opacity="0"/>\n'
            f'  </radialGradient>\n'
            f'  <circle cx="{cx}" cy="{cy}" r="{r_base}" fill="url(#{grad_id})">\n'
            f'    <animate attributeName="r" values="{r_base - 3};{r_base + 3};{r_base - 3}" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'    <animate attributeName="opacity" values="0.35;0.55;0.35" dur="{dur}s" repeatCount="indefinite"\n'
            f'      calcMode="spline" keySplines="{_smil_spline(2)}"/>\n'
            f'  </circle>\n'
            f'</g>'
        )


# ── Category G: Environmental ────────────────────────────────────────────

def _gen_chimney_smoke(colors, world, story, rng):
    """G1. Chimney wisps — 1-3 expanding wisps, 12-20s, 0.06-0.10 opacity."""
    count = rng.randint(1, 3)
    sx = rng.randint(55, 80)
    sy = rng.randint(18, 30)
    parts = [f'<!-- G1: Chimney Smoke -->\n<g id="chimney-smoke" transform="translate({sx}%, {sy}%)">']
    smoke_colors = _BIBLE_COLORS["smoke"]
    for i in range(count):
        color = rng.choice(smoke_colors)
        dur = _pick_prime_dur(11, 19, rng)
        begin = round(rng.uniform(0, 6), 1)
        op_peak = round(rng.uniform(0.06, 0.10), 2)
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
    """G2. Wind through grass — 8-15 blades, staggered begin delays (traveling wave)."""
    count = rng.randint(8, 15)
    parts = ['<!-- G2: Wind Through Grass -->\n<g id="grass-wind" opacity="0.12">']
    grass_color = _warm_color(rng, "shadow")
    dur = _pick_prime_dur(7, 11, rng)
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
    """Generate an animated SVG overlay using the SMIL Animation Bible system.

    Uses WORLD_ELEMENTS mapping with required/select/optional structure.
    Tracks <5KB size budget. Validates drowsiness guardrails.
    """
    world = axes["world_setting"]
    palette = axes["palette"]
    rng = random.Random(hash(story.get("id", "") + world))
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
    budget_remaining = 3600  # ~5000 total - ~1400 fixed overhead

    # 1. Required: breathing pacer (always)
    for elem_name in mapping["required"]:
        svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
        element_parts.append(svg)
        budget_remaining -= _svg_size(svg)

    # 2. Select from pool
    pool = mapping["select"]["pool"][:]
    rng.shuffle(pool)
    pick_min, pick_max = mapping["select"]["pick"]
    pick_count = rng.randint(pick_min, pick_max)

    # Prioritize character-aware elements
    char_elements = _character_aware_elements(story)
    for ce in char_elements:
        if ce in pool:
            pool.remove(ce)
            pool.insert(0, ce)
        elif ce in ELEMENT_GENERATORS:
            pool.insert(0, ce)

    selected = 0
    for elem_name in pool:
        if selected >= pick_count or budget_remaining < 300:
            break
        if elem_name not in ELEMENT_GENERATORS:
            continue
        svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
        size = _svg_size(svg)
        if budget_remaining - size >= 0:
            element_parts.append(svg)
            budget_remaining -= size
            selected += 1

    # 3. Optional elements
    for elem_name in mapping.get("optional", []):
        if budget_remaining < 200:
            break
        if elem_name not in ELEMENT_GENERATORS:
            continue
        if _should_include_optional(elem_name, story, rng):
            svg = ELEMENT_GENERATORS[elem_name](colors, world, story, rng)
            size = _svg_size(svg)
            if budget_remaining - size >= 0:
                element_parts.append(svg)
                budget_remaining -= size

    # 4. Vignette (always)
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

    Rules: no upward motion, min 4s duration, max 0.60 opacity,
    max 10 elements/group, warm colors only, exactly 1 breathing pacer.
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

    # Rule 2: Min duration >= 4s
    for m in _re.finditer(r'dur="(\d+(?:\.\d+)?)s?"', svg_str):
        dur = float(m.group(1))
        if dur < 4.0:
            warnings.append(f"Duration too short: {dur}s (min 4s)")

    # Rule 3: Max opacity 0.60 (light elements only, skip vignettes)
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
            if op > 0.61:
                warnings.append(f"Light opacity too high: {op:.2f} (max 0.60)")
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
                if op > 0.61:
                    warnings.append(f"Animated opacity peak: {op:.2f} (max 0.60)")
            except ValueError:
                pass

    # Rule 4: Element count per group <= 10
    sections = _re.split(r'<!--\s*(.*?)\s*-->', svg_str)
    current_label = ""
    for i, section in enumerate(sections):
        if i % 2 == 1:
            current_label = section
        elif i % 2 == 0 and current_label:
            elements = len(_re.findall(r'<(?:circle|ellipse|rect|path|line|polygon)\s', section))
            if elements > 10:
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

def auto_select_axes(story: dict, overrides: dict = None) -> dict:
    """Select 7 diversity axes from story metadata with optional overrides."""
    overrides = overrides or {}
    theme = story.get("theme", "fantasy")
    age_group = story.get("age_group", "6-8")
    char_type = story.get("lead_character_type", "human")

    # World setting
    world_options = THEME_TO_WORLD.get(theme, list(WORLD_SETTINGS.keys()))
    world = overrides.get("world_setting") or random.choice(world_options)

    # Palette
    palette_options = THEME_TO_PALETTE.get(theme, list(COLOR_PALETTES.keys()))
    palette = overrides.get("palette") or random.choice(palette_options)

    # Composition — choose based on story content
    if "river" in story.get("title", "").lower() or "path" in story.get("title", "").lower():
        comp = "winding_path"
    elif "cave" in story.get("title", "").lower() or "nest" in story.get("title", "").lower():
        comp = "circular_nest"
    else:
        comp = random.choice(list(COMPOSITIONS.keys()))
    comp = overrides.get("composition") or comp

    # Character visual — map all 12 lead_character_type values to the correct visual
    # Handle compound types like "jellyfish (sea creature)" by checking for known keywords
    char_visual = CHAR_TYPE_TO_VISUAL.get(char_type, None)
    if char_visual is None:
        # Try fuzzy match for compound types
        ct_lower = char_type.lower()
        for keyword, visual in [
            ("sea", "aquatic_creature"), ("fish", "aquatic_creature"), ("whale", "aquatic_creature"),
            ("bird", "bird"), ("owl", "bird"), ("eagle", "bird"),
            ("insect", "insect"), ("bug", "insect"), ("caterpillar", "insect"),
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

    # Light source
    if world in ("deep_ocean", "underground_cave"):
        light = "below"
    elif world in ("desert_night", "mountain_meadow"):
        light = "backlit"
    elif world in ("cozy_interior",):
        light = "ambient"
    else:
        light = "above"
    light = overrides.get("light") or light

    # Texture — age group preference
    if age_group in ("2-5", "0-1"):
        texture = "watercolor_soft"
    elif age_group == "6-8":
        texture = random.choice(["digital_painterly", "watercolor_soft"])
    else:
        texture = "digital_painterly"
    texture = overrides.get("texture") or texture

    # Time marker
    if world in ("cozy_interior",):
        time_marker = "timeless_indoor"
    elif "sunset" in story.get("description", "").lower() or "dusk" in story.get("description", "").lower():
        time_marker = "eternal_dusk"
    else:
        time_marker = random.choice(["early_night", "deep_night"])
    time_marker = overrides.get("time") or time_marker

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
    """
    desc = story.get("description", "")
    if not desc:
        return ""

    # Take first sentence
    first_sent = re.split(r'[.!?]', desc)[0].strip()

    # Common story-start verbs that mark the end of the character phrase
    verb_pattern = r'\b(embarks?|discovers?|learns?|finds?|begins?|sets?\s+out|ventures?|travels?|journeys?|explores?|weaves?|must|hears?|meets?|wakes?|searches?|stumbles?|follows?|seeks?|drifts?|wanders?|deciphers?|helps?|uncovers?|lights?|creates?|forges?|teaches?|guides?)\b'

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
    title_match = re.match(r"^(.+?)\s+(?:and the|'s)\s+", title)
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


# ── FLUX prompt builder ─────────────────────────────────────────────────

def build_flux_prompt(story: dict, axes: dict) -> str:
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
        if char_phrase:
            # Use the extracted phrase directly: "a tiny raindrop named Drizzle"
            char_section = (
                f"{char_phrase}, {char_visual_desc}, "
                f"gentle and friendly expression, "
                f"in a magical world"
            )
        else:
            # Fallback to generic visual description
            char_section = (
                f"{char_visual_desc}, "
                f"gentle and friendly expression, "
                f"in a magical world"
            )

    # Age-specific art style additions
    if age_group in ("2-5", "0-1"):
        age_addition = "simple rounded shapes, soft and cuddly character design, picture book illustration quality, storybook warmth"
    elif age_group == "6-8":
        age_addition = "rich atmospheric environment, adventure illustration quality, detailed but soft world-building, Studio Ghibli inspired mood"
    else:
        age_addition = "cinematic concept art, atmospheric landscape, matte painting quality, sophisticated color grading, film still aesthetic"

    # Extract clean texture and composition names
    texture_name = texture_desc.split(",")[0].strip()
    comp_name = comp_desc.split(",")[0].strip().lower()

    prompt = (
        f"Children's book illustration, {texture_name} style, "
        f"atmospheric {world_info.get('signature', 'magical scene').lower()}, "
        f"{comp_name}, "
        f"{char_section}, "
        f"{light_desc.lower()}, "
        f"rich {palette_info.get('mood', 'warm').lower()} color palette with "
        f"{palette_info.get('base', 'warm tones').lower()} and "
        f"{palette_info.get('accents', 'soft accents').lower()} accents, "
        f"{time_desc.lower()}, "
        f"{age_addition}, "
        f"warm inviting mood, no text, no harsh contrasts, soft atmospheric depth, "
        f"no bright whites, maximum 70% luminance, sleep-safe colors, "
        f"absolutely no sad expressions, no tears, no frowning, no closed eyes, no sleepy face"
    )

    return prompt


# ── Hugging Face FLUX API ────────────────────────────────────────────────

def generate_flux_image_pollinations(prompt: str) -> bytes:
    """Call Pollinations.ai FLUX endpoint (free, unlimited for flux model).

    Pollinations uses a GET URL with prompt in the path, so we truncate
    long prompts to avoid Cloudflare 400 errors on oversized URLs.
    """
    from urllib.parse import quote
    pollinations_token = os.getenv("POLLINATIONS_API_KEY", "")

    # Truncate prompt to ~450 chars to stay within URL limits after encoding
    truncated = prompt[:450].rsplit(",", 1)[0] if len(prompt) > 450 else prompt
    encoded_prompt = quote(truncated, safe="")
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width=512&height=512&model=flux&nologo=true"
    headers = {}
    if pollinations_token:
        headers["Authorization"] = f"Bearer {pollinations_token}"

    logger.info("Calling FLUX via Pollinations.ai...")
    logger.info("Prompt: %s", prompt[:200] + "...")

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


def generate_flux_image(prompt: str, hf_token: str = None) -> bytes:
    """Generate a FLUX image via Pollinations.ai (free, unlimited for flux model)."""
    return generate_flux_image_pollinations(prompt)


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

def generate_combined_svg(bg_path: Path, svg_overlay: str) -> str:
    """Create a single SVG with the WebP background embedded as base64 + animated overlay.

    This is the final deliverable — a single .svg file that can be served via <object> tag
    and renders the FLUX background with animated overlay on top.
    """
    import base64
    import re

    with open(bg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    # Extract inner content from overlay SVG (everything between <svg...> and </svg>)
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
    axes = auto_select_axes(story, overrides)
    logger.info("Axes: %s", json.dumps(axes, indent=2))

    # Build FLUX prompt
    prompt = build_flux_prompt(story, axes)
    logger.info("FLUX prompt (%d chars): %s", len(prompt), prompt[:300])

    if args.dry_run:
        print("\n=== DRY RUN ===")
        print(f"\nStory: {title} ({story_id})")
        print(f"\nAxes: {json.dumps(axes, indent=2)}")
        print(f"\nFLUX Prompt:\n{prompt}")
        print(f"\nAnimations: {WORLD_ELEMENTS.get(axes['world_setting'], {})}")
        return

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

    # Generate combined SVG (single file: embedded WebP + animated overlay)
    logger.info("Generating combined SVG...")
    combined_svg = generate_combined_svg(bg_path, svg_content)
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
