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
    "small_mammal": "Bunny, fox, mouse, hedgehog — round, soft, curled",
    "aquatic_creature": "Whale, turtle, jellyfish — flowing, gentle",
    "bird": "Owl, small songbird, penguin — feathered, compact",
    "mythical_gentle": "Baby dragon, small griffin, friendly spirit",
    "human_child": "Diverse, age-matched to listener, soft features",
    "nature_spirit": "Tree spirit, cloud being, star creature — abstract",
    "robot_mech": "Soft-edged, warm-eyed, small and round",
    "no_character": "Pure landscape, environment is the subject",
}

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

# World setting → SVG animation types
WORLD_TO_ANIMATIONS = {
    "deep_ocean":       ["particles_bubbles", "glow_bioluminescence", "mist_underwater"],
    "cloud_kingdom":    ["drift_clouds", "twinkle_stars", "vignette"],
    "enchanted_forest": ["particles_pollen", "glow_firefly", "mist_ground"],
    "snow_landscape":   ["particles_snow", "twinkle_stars", "vignette"],
    "desert_night":     ["twinkle_stars", "drift_sand", "glow_campfire"],
    "cozy_interior":    ["glow_candle", "particles_dust", "vignette"],
    "mountain_meadow":  ["particles_pollen", "drift_clouds", "mist_valley"],
    "space_cosmos":     ["twinkle_stars", "glow_nebula", "drift_starfield"],
    "tropical_lagoon":  ["glow_sunset", "particles_fireflies", "mist_sea"],
    "underground_cave": ["glow_crystals", "particles_spores", "mist_steam"],
    "ancient_library":  ["particles_dust", "glow_lantern", "vignette"],
    "floating_islands": ["drift_clouds", "particles_leaves", "twinkle_distant"],
}


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

    # Character visual
    if char_type == "human":
        char_visual = "human_child"
    elif char_type in ("fantastical", "animal"):
        char_visual = random.choice(["mythical_gentle", "nature_spirit"])
    else:
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


# ── FLUX prompt builder ─────────────────────────────────────────────────

def build_flux_prompt(story: dict, axes: dict) -> str:
    """Build FLUX AI prompt from story metadata and axis selections."""
    age_group = story.get("age_group", "6-8")

    world_info = WORLD_SETTINGS.get(axes["world_setting"], {})
    palette_info = COLOR_PALETTES.get(axes["palette"], {})
    comp_desc = COMPOSITIONS.get(axes["composition"], "")
    char_desc = CHARACTER_VISUALS.get(axes["character"], "")
    light_desc = LIGHT_SOURCES.get(axes["light"], "")
    texture_desc = TEXTURES.get(axes["texture"], "")
    time_desc = TIME_MARKERS.get(axes["time"], "")

    # Character details
    char_name = story.get("character_name", "a child")
    char_gender = story.get("lead_gender", "female")
    char_age = story.get("character_age", 7)

    # Age-specific additions
    if age_group in ("2-5", "0-1"):
        age_addition = "simple rounded shapes, soft and cuddly character design, picture book illustration quality, large gentle eyes (closed), storybook warmth"
    elif age_group == "6-8":
        age_addition = "rich atmospheric environment, adventure illustration quality, detailed but soft world-building, Studio Ghibli inspired mood"
    else:
        age_addition = "cinematic concept art, atmospheric landscape, matte painting quality, sophisticated color grading, film still aesthetic"

    # Use Template B for 6-8 (environment-focused)
    # Extract clean texture name
    texture_name = texture_desc.split(",")[0].strip()
    # Extract clean composition
    comp_name = comp_desc.split(",")[0].strip().lower()

    prompt = (
        f"Children's book illustration, {texture_name} style, "
        f"atmospheric {world_info.get('signature', 'magical scene').lower()}, "
        f"{comp_name}, "
        f"a small {char_gender} child figure (age {char_age}) with bright curious eyes wide open, "
        f"gentle smile, looking with wonder at the magical world around them, adventurous and happy, "
        f"{light_desc.lower()}, "
        f"rich {palette_info.get('mood', 'warm').lower()} color palette with "
        f"{palette_info.get('base', 'warm tones').lower()} and "
        f"{palette_info.get('accents', 'soft accents').lower()} accents, "
        f"{time_desc.lower()}, "
        f"{age_addition}, "
        f"warm inviting mood, no text, no harsh contrasts, soft atmospheric depth, "
        f"no bright whites, maximum 70% luminance, sleep-safe colors, "
        f"absolutely no sad expressions, no tears, no frowning, no closed eyes, no sleepy face, "
        f"the child must look happy and excited to explore"
    )

    return prompt


# ── Hugging Face FLUX API ────────────────────────────────────────────────

def generate_flux_image(prompt: str, hf_token: str) -> bytes:
    """Call Hugging Face FLUX.1 Schnell to generate an image."""
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": prompt}

    logger.info("Calling FLUX.1 Schnell via Hugging Face API...")
    logger.info("Prompt: %s", prompt[:200] + "...")

    for attempt in range(3):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=120)

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "image" in content_type or len(response.content) > 1000:
                    logger.info("Image received: %d bytes", len(response.content))
                    return response.content
                else:
                    # Might be JSON error
                    logger.warning("Unexpected response: %s", response.text[:500])

            elif response.status_code == 503:
                # Model loading
                try:
                    data = response.json()
                    wait = data.get("estimated_time", 30)
                except Exception:
                    wait = 30
                logger.info("Model loading, waiting %ds...", int(wait))
                time.sleep(wait + 5)
                continue

            elif response.status_code == 429:
                logger.warning("Rate limited, waiting 60s...")
                time.sleep(60)
                continue

            else:
                logger.error("API error %d: %s", response.status_code, response.text[:500])
                if attempt < 2:
                    time.sleep(10)
                    continue

        except httpx.TimeoutException:
            logger.warning("Timeout on attempt %d", attempt + 1)
            if attempt < 2:
                time.sleep(10)
                continue

    return None


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


# ── SVG Overlay Generator ───────────────────────────────────────────────

def generate_svg_overlay(axes: dict, story: dict) -> str:
    """Generate an animated SVG overlay based on world setting and diversity axes.

    Each world gets a UNIQUE overlay personality — not the same formula with different params.
    Some worlds are particle-heavy, some are glow-heavy, some are minimal.
    The vignette style also varies per world to break the "same dark edges" pattern.
    """
    world = axes["world_setting"]
    palette = axes["palette"]
    time_setting = axes.get("time", "early_night")

    # Get ALL animation types for this world (use all, not just 2-3)
    anim_types = WORLD_TO_ANIMATIONS.get(world, ["particles_pollen", "glow_firefly", "vignette"])

    # Palette-based colors (base layer)
    palette_colors = {
        "ember_warm":   {"glow": "#FFD699", "particle": "#FFCC80", "vignette": "#1a0a05", "star": "#FFF5E0"},
        "twilight_cool": {"glow": "#C8B8E0", "particle": "#D0C4E8", "vignette": "#0a0520", "star": "#E8E0F0"},
        "forest_deep":  {"glow": "#A8D5A0", "particle": "#C4E0B8", "vignette": "#051005", "star": "#D8F0D0"},
        "golden_hour":  {"glow": "#FFE4B5", "particle": "#FFD89B", "vignette": "#1a0f00", "star": "#FFF8E8"},
        "moonstone":    {"glow": "#C0D0E0", "particle": "#B8C8D8", "vignette": "#050810", "star": "#E0E8F0"},
        "berry_dusk":   {"glow": "#D8A8C8", "particle": "#E0B8D0", "vignette": "#100510", "star": "#F0D8E8"},
    }
    colors = palette_colors.get(palette, palette_colors["golden_hour"])

    # World-specific colors — MUST be visually distinct from each other at thumbnail size
    # Rule: no two worlds share the same hue family for their primary visible color
    world_accents = {
        "deep_ocean":       {"particle": "#00E5FF", "glow": "#0097A7", "accent": "#00BCD4"},  # CYAN — unmistakable ocean blue-green
        "cloud_kingdom":    {"particle": "#E0E0E0", "glow": "#B0BEC5", "accent": "#ECEFF1"},  # SILVER/WHITE — cloud-like
        "enchanted_forest": {"particle": "#76FF03", "glow": "#00C853", "accent": "#64DD17"},  # VIVID GREEN — forest canopy
        "snow_landscape":   {"particle": "#E1F5FE", "glow": "#81D4FA", "accent": "#B3E5FC"},  # ICE BLUE — cold and pale
        "desert_night":     {"particle": "#FFAB00", "glow": "#FF6D00", "accent": "#FF9100"},  # ORANGE — desert warmth
        "cozy_interior":    {"particle": "#FFD54F", "glow": "#FFB300", "accent": "#FFC107"},  # AMBER/YELLOW — candlelight
        "mountain_meadow":  {"particle": "#B2FF59", "glow": "#69F0AE", "accent": "#A5D6A7"},  # SOFT GREEN — meadow fresh
        "space_cosmos":     {"particle": "#B388FF", "glow": "#7C4DFF", "accent": "#EA80FC"},  # PURPLE/VIOLET — cosmic
        "tropical_lagoon":  {"particle": "#FF6E40", "glow": "#FF3D00", "accent": "#FF8A65"},  # RED-ORANGE — sunset fire
        "underground_cave": {"particle": "#18FFFF", "glow": "#00E5FF", "accent": "#84FFFF"},  # BRIGHT TEAL — crystal glow
        "ancient_library":  {"particle": "#FFE082", "glow": "#FFA000", "accent": "#FFD740"},  # GOLD — aged warmth
        "floating_islands": {"particle": "#FF80AB", "glow": "#F50057", "accent": "#FF4081"},  # MAGENTA/PINK — magical
    }
    accents = world_accents.get(world, {})
    if accents:
        colors = {**colors, **accents}  # world accents override palette defaults

    accent = colors.get("accent", colors["glow"])

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
    <filter id="heavyBlur">
      <feGaussianBlur stdDeviation="8"/>
    </filter>
  </defs>''')

    # --- Per-world vignette style (NOT the same dark edges on every cover) ---
    VIGNETTE_STYLE = {
        "deep_ocean":       "top_heavy",      # dark at top like deep water
        "cloud_kingdom":    "none",            # clean, no vignette — bright sky
        "enchanted_forest": "bottom_heavy",    # dark at bottom, light canopy above
        "snow_landscape":   "none",            # clean white landscape
        "desert_night":     "top_corners",     # dark sky corners, bright horizon
        "cozy_interior":    "full_soft",       # gentle all-around darkness
        "mountain_meadow":  "bottom_light",    # very subtle bottom only
        "space_cosmos":     "corners_only",    # dark corners, open center
        "tropical_lagoon":  "top_heavy",       # dark sky, bright water below
        "underground_cave": "full_heavy",      # heavy darkness, glows punch through
        "ancient_library":  "full_soft",       # gentle ambient darkness
        "floating_islands": "none",            # clean, airy
    }
    vig_style = VIGNETTE_STYLE.get(world, "full_soft")
    svg_parts.append(_gen_vignette(vig_style, colors))

    # --- World-specific animations ONLY (no forced layers) ---
    for anim in anim_types:
        if anim.startswith("particles"):
            svg_parts.append(_gen_particles(anim, colors))
        elif anim.startswith("glow") and anim != "glow_breathing":
            svg_parts.append(_gen_glow_secondary(anim, colors))
        elif anim.startswith("twinkle"):
            svg_parts.append(_gen_twinkle(colors))
        elif anim.startswith("drift"):
            svg_parts.append(_gen_drift(anim, colors))
        elif anim.startswith("mist"):
            svg_parts.append(_gen_mist(anim, colors))

    # Add twinkle for deep_night only if not already present
    if time_setting == "deep_night" and not any(a.startswith("twinkle") for a in anim_types):
        svg_parts.append(_gen_twinkle(colors))

    svg_parts.append('\n</svg>')
    return "\n".join(svg_parts)


def _gen_particles(variant: str, colors: dict) -> str:
    """Generate variant-aware particle animations — visually distinct per world.

    Sleep rules: cycle >=4s, opacity <=60%, slow drift.
    Each variant produces a different motion, shape, and feel.
    """
    # Variant-specific configuration (opacity boosted for visibility, max 0.60)
    configs = {
        "particles_bubbles": {
            "label": "Rising Bubbles", "count": (6, 10), "direction": "up",
            "r_large": (6.0, 10.0), "r_med": (3.5, 6.0), "r_small": (2.0, 3.5),
            "op_large": (0.35, 0.55), "op_med": (0.25, 0.45), "op_small": (0.18, 0.35),
            "dur": (18, 28), "size_pulse": True, "use_filter": True,
        },
        "particles_snow": {
            "label": "Falling Snowflakes", "count": (12, 20), "direction": "down_sway",
            "r_large": (3.0, 5.0), "r_med": (2.0, 3.0), "r_small": (1.0, 2.0),
            "op_large": (0.45, 0.60), "op_med": (0.35, 0.55), "op_small": (0.25, 0.40),
            "dur": (16, 26), "size_pulse": False, "use_filter": False,
        },
        "particles_pollen": {
            "label": "Floating Pollen", "count": (8, 14), "direction": "float",
            "r_large": (3.0, 4.5), "r_med": (1.5, 3.0), "r_small": (0.8, 1.5),
            "op_large": (0.35, 0.55), "op_med": (0.25, 0.45), "op_small": (0.18, 0.30),
            "dur": (20, 35), "size_pulse": False, "use_filter": True,
        },
        "particles_dust": {
            "label": "Dust Motes in Light", "count": (8, 14), "direction": "diagonal",
            "r_large": (2.0, 3.5), "r_med": (1.2, 2.0), "r_small": (0.6, 1.2),
            "op_large": (0.35, 0.55), "op_med": (0.25, 0.40), "op_small": (0.15, 0.30),
            "dur": (22, 35), "size_pulse": False, "use_filter": True,
        },
        "particles_fireflies": {
            "label": "Firefly Glows", "count": (5, 8), "direction": "bob",
            "r_large": (5.0, 8.0), "r_med": (3.0, 5.0), "r_small": (2.0, 3.0),
            "op_large": (0.15, 0.60), "op_med": (0.12, 0.55), "op_small": (0.08, 0.45),
            "dur": (8, 16), "size_pulse": True, "use_filter": True,
        },
        "particles_leaves": {
            "label": "Falling Leaves", "count": (5, 8), "direction": "down_rotate",
            "r_large": (4.0, 6.0), "r_med": (3.0, 4.0), "r_small": (2.0, 3.0),
            "op_large": (0.35, 0.55), "op_med": (0.28, 0.45), "op_small": (0.20, 0.35),
            "dur": (18, 30), "size_pulse": False, "use_filter": False,
        },
        "particles_spores": {
            "label": "Rising Spores", "count": (8, 14), "direction": "up_gentle",
            "r_large": (2.5, 4.0), "r_med": (1.5, 2.5), "r_small": (0.8, 1.5),
            "op_large": (0.35, 0.55), "op_med": (0.25, 0.40), "op_small": (0.15, 0.30),
            "dur": (20, 32), "size_pulse": False, "use_filter": True,
        },
    }
    cfg = configs.get(variant, configs["particles_pollen"])

    count = random.randint(*cfg["count"])
    filt = ' filter="url(#softBlur)"' if cfg["use_filter"] else ""
    particles = []
    particles.append(f'\n  <!-- {cfg["label"]} -->')

    for i in range(count):
        # Size tiers: ~25% large, ~40% medium, rest small
        if i < count // 4:
            r = random.uniform(*cfg["r_large"])
            opacity = random.uniform(*cfg["op_large"])
        elif i < count * 2 // 3:
            r = random.uniform(*cfg["r_med"])
            opacity = random.uniform(*cfg["op_med"])
        else:
            r = random.uniform(*cfg["r_small"])
            opacity = random.uniform(*cfg["op_small"])

        dur = random.uniform(*cfg["dur"])
        delay = random.uniform(0, dur * 0.6)
        direction = cfg["direction"]

        if direction == "up":
            # Rising bubbles — upward S-curve with wobble
            cx = random.randint(40, 470)
            cy_start = random.randint(420, 540)
            dx = random.randint(-50, 50)
            dy = random.randint(-400, -300)
            cx1 = random.randint(-40, 40)
            cy1 = random.randint(-100, -60)
            cx2 = random.randint(-35, 35)
            cy2 = random.randint(-250, -180)
            path = f"M{cx},{cy_start} C{cx+cx1},{cy_start+cy1} {cx+cx2},{cy_start+cy2} {cx+dx},{cy_start+dy}"
        elif direction == "down_sway":
            # Snow — falling with wide horizontal sway
            cx = random.randint(20, 500)
            cy_start = random.randint(-40, -10)
            sway = random.randint(40, 80) * random.choice([-1, 1])
            dy = random.randint(480, 560)
            path = f"M{cx},{cy_start} C{cx+sway},{cy_start+dy//3} {cx-sway},{cy_start+2*dy//3} {cx+sway//2},{cy_start+dy}"
        elif direction == "float":
            # Pollen — lazy figure-8 / random drift, barely moving
            cx = random.randint(40, 470)
            cy = random.randint(60, 420)
            dx1 = random.randint(-25, 25)
            dy1 = random.randint(-20, 20)
            dx2 = random.randint(-25, 25)
            dy2 = random.randint(-20, 20)
            path = f"M{cx},{cy} C{cx+dx1},{cy+dy1} {cx+dx2},{cy+dy2} {cx-dx1},{cy-dy1} C{cx-dx2},{cy-dy2} {cx+dx1},{cy+dy1} {cx},{cy}"
        elif direction == "diagonal":
            # Dust — slow diagonal drift in a light beam area
            beam_cx = random.randint(150, 380)
            cx = beam_cx + random.randint(-60, 60)
            cy_start = random.randint(50, 200)
            dx = random.randint(20, 50)
            dy = random.randint(200, 350)
            path = f"M{cx},{cy_start} C{cx+dx//2},{cy_start+dy//3} {cx+dx},{cy_start+2*dy//3} {cx+dx},{cy_start+dy}"
        elif direction == "bob":
            # Fireflies — bobbing in place with random wander
            cx = random.randint(50, 460)
            cy = random.randint(100, 420)
            bx = random.randint(15, 35)
            by = random.randint(10, 25)
            path = f"M{cx},{cy} C{cx+bx},{cy-by} {cx-bx},{cy+by} {cx},{cy}"
        elif direction == "down_rotate":
            # Leaves — falling with wide S-curve (rotation handled separately)
            cx = random.randint(30, 480)
            cy_start = random.randint(-30, 30)
            dx = random.randint(-80, 80)
            dy = random.randint(400, 540)
            path = f"M{cx},{cy_start} C{cx+dx},{cy_start+dy//4} {cx-dx},{cy_start+3*dy//4} {cx+dx//2},{cy_start+dy}"
        elif direction == "up_gentle":
            # Spores — gentle rise from ground
            cx = random.randint(60, 450)
            cy_start = random.randint(440, 510)
            dx = random.randint(-30, 30)
            dy = random.randint(-250, -150)
            path = f"M{cx},{cy_start} C{cx+dx},{cy_start+dy//2} {cx-dx},{cy_start+dy} {cx},{cy_start+dy-40}"
        else:
            # Default: gentle downward drift
            cx = random.randint(30, 480)
            cy_start = random.randint(-30, 80)
            dx = random.randint(-40, 40)
            dy = random.randint(350, 500)
            path = f"M{cx},{cy_start} C{cx},{cy_start+dy//3} {cx+dx},{cy_start+2*dy//3} {cx+dx},{cy_start+dy}"

        # Use ellipse for leaves, circle for everything else
        if direction == "down_rotate":
            rx = r * random.uniform(1.4, 2.0)
            ry = r * random.uniform(0.6, 0.9)
            rot_dur = random.uniform(6, 12)
            rot_dir = random.choice([-1, 1]) * random.randint(180, 360)
            particles.append(f'''  <ellipse rx="{rx:.1f}" ry="{ry:.1f}" fill="{colors['particle']}" opacity="0"{filt}>
    <animateMotion dur="{dur:.0f}s" begin="{delay:.1f}s" repeatCount="indefinite" path="{path}" />
    <animateTransform attributeName="transform" type="rotate"
      values="0;{rot_dir};0" dur="{rot_dur:.0f}s" begin="{delay:.1f}s" repeatCount="indefinite" additive="sum" />
    <animate attributeName="opacity"
      values="0;{opacity:.2f};{opacity:.2f};{opacity*0.3:.2f};0" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </ellipse>''')
        else:
            size_anim = ""
            if cfg["size_pulse"]:
                pulse_dur = random.uniform(4, 8)
                r_max = r * random.uniform(1.3, 1.6)
                size_anim = f'''
    <animate attributeName="r" values="{r:.1f};{r_max:.1f};{r:.1f}" dur="{pulse_dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />'''

            # Fireflies use a distinctive pulse pattern: dim → bright → dim with long dark phases
            if direction == "bob":
                op_vals = f"0;{opacity*0.2:.2f};{opacity:.2f};{opacity:.2f};{opacity*0.1:.2f};0;0"
            else:
                op_vals = f"0;{opacity:.2f};{opacity:.2f};{opacity*0.4:.2f};0"

            particles.append(f'''  <circle r="{r:.1f}" fill="{colors['particle']}" opacity="0"{filt}>
    <animateMotion dur="{dur:.0f}s" begin="{delay:.1f}s" repeatCount="indefinite" path="{path}" />{size_anim}
    <animate attributeName="opacity"
      values="{op_vals}" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')

    return "\n".join(particles)


def _gen_glow(variant: str, colors: dict, world: str = "") -> str:
    """Generate breathing pacer glow — the primary sleep cue, with shape diversity.

    Sleep rules: 7-9s cycle. Must be clearly visible.
    Shape varies by world to avoid the "same circles on every cover" look.
    """
    dur = random.randint(7, 9)
    accent = colors.get("accent", colors["glow"])

    # Choose pacer shape based on world setting
    # Group worlds into shape families to ensure visual diversity
    SHAPE_MAP = {
        "deep_ocean": "horizontal_band",
        "cloud_kingdom": "top_wash",
        "enchanted_forest": "off_center_orb",
        "snow_landscape": "top_wash",
        "desert_night": "horizon_line",
        "cozy_interior": "corner_glow",
        "mountain_meadow": "diagonal_band",
        "space_cosmos": "center_nebula",
        "tropical_lagoon": "horizon_line",
        "underground_cave": "bottom_pool",
        "ancient_library": "corner_glow",
        "floating_islands": "diagonal_band",
    }
    shape = SHAPE_MAP.get(world, random.choice(["off_center_orb", "horizontal_band", "diagonal_band"]))

    if shape == "off_center_orb":
        # Single off-center orb (NOT centered, NOT bottom)
        cx = random.choice([random.randint(100, 180), random.randint(340, 420)])
        cy = random.randint(160, 320)
        r = random.randint(80, 110)
        return f'''
  <!-- Breathing Pacer (off-center orb) -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#glowGrad)" filter="url(#heavyBlur)">
    <animate attributeName="r"
      values="{r-12};{r+15};{r-12}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.20;0.45;0.20" dur="{dur}s" repeatCount="indefinite" />
  </circle>'''

    elif shape == "horizontal_band":
        # Wide horizontal band across middle — like underwater light
        cy = random.randint(200, 350)
        return f'''
  <!-- Breathing Pacer (horizontal band) -->
  <rect x="0" y="{cy-40}" width="512" height="80" fill="url(#horizGlow)" filter="url(#heavyBlur)">
    <animate attributeName="opacity"
      values="0.15;0.40;0.15" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="height"
      values="60;100;60" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    elif shape == "top_wash":
        # Diffuse wash from top — like sky glow or cloud light
        return f'''
  <!-- Breathing Pacer (top wash) -->
  <rect x="0" y="0" width="512" height="280" fill="url(#horizGlow)" filter="url(#heavyBlur)" transform="rotate(180,256,140)">
    <animate attributeName="opacity"
      values="0.15;0.38;0.15" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    elif shape == "horizon_line":
        # Glow along horizon — for sunset/desert worlds
        cy = random.randint(340, 400)
        return f'''
  <!-- Breathing Pacer (horizon glow) -->
  <ellipse cx="256" cy="{cy}" rx="350" ry="25" fill="{accent}" filter="url(#heavyBlur)">
    <animate attributeName="opacity"
      values="0.20;0.50;0.20" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="ry"
      values="20;40;20" dur="{dur}s" repeatCount="indefinite" />
  </ellipse>'''

    elif shape == "corner_glow":
        # Warm glow from one corner — for interior/library worlds
        corner = random.choice(["top_left", "top_right", "bottom_left", "bottom_right"])
        cx = 80 if "left" in corner else 430
        cy = 80 if "top" in corner else 430
        r = random.randint(100, 140)
        return f'''
  <!-- Breathing Pacer (corner glow) -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{accent}" filter="url(#heavyBlur)">
    <animate attributeName="r"
      values="{r-15};{r+20};{r-15}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.18;0.42;0.18" dur="{dur}s" repeatCount="indefinite" />
  </circle>'''

    elif shape == "diagonal_band":
        # Diagonal light band across the image
        return f'''
  <!-- Breathing Pacer (diagonal band) -->
  <rect x="-100" y="180" width="712" height="100" fill="url(#diagonalGlow)" filter="url(#heavyBlur)"
    transform="rotate(-15,256,256)">
    <animate attributeName="opacity"
      values="0.15;0.40;0.15" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    elif shape == "center_nebula":
        # Two overlapping large blobs — for space/cosmos
        cx1 = random.randint(160, 240)
        cy1 = random.randint(180, 280)
        cx2 = random.randint(280, 360)
        cy2 = random.randint(220, 320)
        r1 = random.randint(90, 120)
        r2 = random.randint(80, 110)
        return f'''
  <!-- Breathing Pacer (nebula blobs) -->
  <circle cx="{cx1}" cy="{cy1}" r="{r1}" fill="{accent}" filter="url(#heavyBlur)">
    <animate attributeName="r"
      values="{r1-10};{r1+15};{r1-10}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.30;0.12" dur="{dur}s" repeatCount="indefinite" />
  </circle>
  <circle cx="{cx2}" cy="{cy2}" r="{r2}" fill="{colors['glow']}" filter="url(#heavyBlur)">
    <animate attributeName="r"
      values="{r2+10};{r2-8};{r2+10}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.25;0.10" dur="{dur}s" repeatCount="indefinite" />
  </circle>'''

    elif shape == "bottom_pool":
        # Glowing pool at bottom — for cave/underground
        return f'''
  <!-- Breathing Pacer (bottom pool) -->
  <ellipse cx="256" cy="480" rx="200" ry="50" fill="{accent}" filter="url(#heavyBlur)">
    <animate attributeName="opacity"
      values="0.18;0.45;0.18" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="rx"
      values="180;220;180" dur="{dur}s" repeatCount="indefinite" />
  </ellipse>'''

    else:
        # Fallback: original off-center orb
        cx = random.randint(150, 370)
        cy = random.randint(180, 340)
        r = random.randint(80, 110)
        return f'''
  <!-- Breathing Pacer (default orb) -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#glowGrad)" filter="url(#heavyBlur)">
    <animate attributeName="r"
      values="{r-12};{r+15};{r-12}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.20;0.45;0.20" dur="{dur}s" repeatCount="indefinite" />
  </circle>'''


def _gen_twinkle(colors: dict) -> str:
    """Generate twinkling star/shimmer effects — visible slow twinkles.

    Sleep rules: cycle >=4s, gentle fade in/out.
    """
    accent = colors.get("accent", colors["star"])
    count = random.randint(14, 22)
    twinkles = []
    twinkles.append('\n  <!-- Twinkling Stars -->')

    for i in range(count):
        cx = random.randint(15, 500)
        cy = random.randint(5, 300)
        dur = random.uniform(5, 10)  # >=4s rule
        delay = random.uniform(0, 8)
        # Use accent color for some stars to add color variety
        star_color = accent if i % 4 == 0 else colors["star"]

        # Mix of star sizes — boosted for visibility
        if i < 5:
            r = random.uniform(3.0, 4.5)
            max_opacity = random.uniform(0.50, 0.60)
        elif i < 12:
            r = random.uniform(2.0, 3.0)
            max_opacity = random.uniform(0.40, 0.55)
        else:
            r = random.uniform(1.0, 2.0)
            max_opacity = random.uniform(0.30, 0.45)

        twinkles.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="{star_color}" opacity="0">
    <animate attributeName="opacity"
      values="0;{max_opacity:.2f};{max_opacity*0.5:.2f};{max_opacity:.2f};0" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r:.1f};{r*1.5:.1f};{r:.1f}" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')

    return "\n".join(twinkles)


def _gen_drift(variant: str, colors: dict) -> str:
    """Generate variant-aware drift animations — visually distinct per world.

    Sleep rules: very slow (25-40s cycle), low opacity, no jarring motion.
    Each variant produces a different drift character.
    """
    accent = colors.get("accent", colors["glow"])

    if variant == "drift_clouds":
        # Large soft cloud shapes at top, slow horizontal pan
        dur1 = random.randint(30, 45)
        dur2 = random.randint(35, 50)
        dx1 = random.randint(25, 50)
        dx2 = random.randint(20, 40)
        cy1 = random.randint(60, 120)
        cy2 = random.randint(90, 160)
        return f'''
  <!-- Drifting Clouds -->
  <ellipse cx="180" cy="{cy1}" rx="220" ry="55" fill="{colors['particle']}" opacity="0.18" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx1},3; 0,0; {-dx1},-2; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.28;0.12" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="380" cy="{cy2}" rx="180" ry="45" fill="{accent}" opacity="0.14" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {-dx2},2; 0,0; {dx2},-3; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.22;0.10" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="100" cy="{cy1 + 50}" rx="140" ry="30" fill="{colors['glow']}" opacity="0.10" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx1+10},1; 0,0; {-dx2},0; 0,0"
      dur="{dur1 + 8}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "drift_sand":
        # Low ground-level wisps, horizontal motion like desert wind
        dur1 = random.randint(25, 35)
        dur2 = random.randint(28, 38)
        dx = random.randint(30, 60)
        return f'''
  <!-- Desert Sand Drift -->
  <ellipse cx="200" cy="480" rx="350" ry="28" fill="{colors['particle']}" opacity="0.18" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx},0; {dx//2},-3; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.28;0.15;0.12" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="380" cy="495" rx="250" ry="20" fill="{accent}" opacity="0.12" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx+10},0; {dx//3},-2; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.08;0.20;0.08" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="80" cy="470" rx="180" ry="15" fill="{colors['glow']}" opacity="0.10" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx+20},1; 0,0"
      dur="{dur1+5}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "drift_starfield":
        # Very slow rotation of entire star group — subtle sky rotation
        dur = random.randint(60, 90)
        return f'''
  <!-- Starfield Drift (slow sky rotation) -->
  <g opacity="0.30">
    <animateTransform attributeName="transform" type="rotate"
      values="0 256 256; 8 256 256; 0 256 256; -5 256 256; 0 256 256"
      dur="{dur}s" repeatCount="indefinite" />
    <circle cx="120" cy="80" r="1.8" fill="{colors['star']}" opacity="0.6"/>
    <circle cx="350" cy="60" r="1.4" fill="{accent}" opacity="0.5"/>
    <circle cx="420" cy="180" r="1.5" fill="{colors['star']}" opacity="0.45"/>
    <circle cx="80" cy="220" r="1.2" fill="{accent}" opacity="0.4"/>
    <circle cx="280" cy="40" r="1.6" fill="{colors['star']}" opacity="0.55"/>
    <circle cx="450" cy="120" r="1.0" fill="{colors['star']}" opacity="0.35"/>
    <circle cx="200" cy="150" r="1.8" fill="{accent}" opacity="0.5"/>
  </g>'''

    else:
        # Default: original gentle bottom haze
        dur = random.randint(25, 40)
        dx = random.randint(8, 15)
        dy = random.randint(2, 5)
        return f'''
  <!-- Slow Drifting Haze -->
  <g>
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx},{dy}; 0,0; {-dx},{-dy}; 0,0"
      dur="{dur}s" repeatCount="indefinite" />
    <ellipse cx="256" cy="450" rx="320" ry="60" fill="{colors['particle']}" opacity="0.20" filter="url(#softBlur)"/>
    <ellipse cx="150" cy="470" rx="220" ry="45" fill="{colors['glow']}" opacity="0.16" filter="url(#softBlur)"/>
    <ellipse cx="380" cy="440" rx="180" ry="35" fill="{accent}" opacity="0.14" filter="url(#softBlur)"/>
  </g>'''


def _gen_mist(variant: str, colors: dict) -> str:
    """Generate variant-aware mist/fog animations — visually distinct per world.

    Sleep rules: slow movement (18-40s), moderate opacity, gentle.
    Each variant produces a different mist character.
    """
    accent = colors.get("accent", colors["glow"])

    if variant == "mist_underwater":
        # Horizontal swaying current-like motion — wide, slow lateral waves
        dur1 = random.randint(24, 34)
        dur2 = random.randint(28, 38)
        sx = random.randint(30, 50)
        return f'''
  <!-- Underwater Currents -->
  <ellipse cx="200" cy="350" rx="300" ry="45" fill="{colors['glow']}" opacity="0.18" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {sx},5; 0,0; {-sx},-5; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.30;0.12" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="350" cy="420" rx="260" ry="38" fill="{accent}" opacity="0.15" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {-sx+10},3; 0,0; {sx-10},-3; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.25;0.10" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "mist_valley":
        # Rolling in from one side — asymmetric drift from left
        dur1 = random.randint(30, 42)
        dur2 = random.randint(34, 46)
        return f'''
  <!-- Valley Mist (rolling in from side) -->
  <ellipse cx="60" cy="460" rx="250" ry="55" fill="{colors['glow']}" opacity="0.20" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 120,-15; 180,-8; 80,-5; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.32;0.22;0.16;0.12" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="30" cy="490" rx="200" ry="40" fill="{accent}" opacity="0.15" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 150,-10; 200,-5; 60,-3; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.08;0.25;0.15;0.08" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "mist_sea":
        # Low horizontal drift at very bottom only — like sea fog on shore
        dur1 = random.randint(22, 32)
        dur2 = random.randint(26, 36)
        dx = random.randint(20, 35)
        return f'''
  <!-- Sea Fog (low horizon) -->
  <ellipse cx="256" cy="498" rx="380" ry="35" fill="{colors['glow']}" opacity="0.22" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx},0; 0,0; {-dx},0; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.15;0.32;0.15" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="160" cy="505" rx="300" ry="25" fill="{accent}" opacity="0.16" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {-dx-5},0; 0,0; {dx+5},0; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.24;0.10" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "mist_steam":
        # Small rising wisps from specific points — like cave vents or hot springs
        parts = ['\n  <!-- Steam Wisps -->']
        num_vents = random.randint(3, 5)
        for _ in range(num_vents):
            vx = random.randint(100, 420)
            vy = random.randint(430, 490)
            dur = random.randint(14, 24)
            delay = random.uniform(0, 6)
            rise = random.randint(50, 100)
            rx = random.randint(25, 45)
            ry = random.randint(14, 25)
            wisp_color = random.choice([colors["glow"], accent])
            parts.append(f'''  <ellipse cx="{vx}" cy="{vy}" rx="{rx}" ry="{ry}" fill="{wisp_color}" opacity="0" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {random.randint(-12,12)},{-rise}; 0,0"
      dur="{dur}s" begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0;0.30;0.20;0" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </ellipse>''')
        return "\n".join(parts)

    else:
        # Default (mist_ground): Slow rise from bottom with horizontal sway
        dur1 = random.randint(22, 32)
        dur2 = random.randint(28, 38)
        dur3 = random.randint(18, 28)
        return f'''
  <!-- Rising Ground Mist (3 layers) -->
  <ellipse cx="180" cy="480" rx="280" ry="60" fill="{colors['glow']}" opacity="0.22" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 20,-12; 0,0; -15,-8; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.15;0.32;0.15" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="350" cy="495" rx="230" ry="45" fill="{accent}" opacity="0.18" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; -18,-10; 0,0; 12,-6; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.12;0.28;0.12" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="256" cy="510" rx="350" ry="70" fill="{colors['particle']}" opacity="0.15" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 10,-5; 0,0; -8,-3; 0,0"
      dur="{dur3}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.25;0.10" dur="{dur3}s" repeatCount="indefinite" />
  </ellipse>'''


def _gen_ground_glow(colors: dict) -> str:
    """Generate a subtle grounding layer — varies shape to avoid sameness."""
    dur = random.randint(16, 24)
    accent = colors.get("accent", colors["glow"])
    # Randomly pick different grounding styles
    style = random.choice(["bottom_band", "side_fade", "diagonal_stripe"])

    if style == "bottom_band":
        return f'''
  <!-- Ground Glow (bottom band) -->
  <rect x="0" y="440" width="512" height="72" fill="url(#horizGlow)" filter="url(#heavyBlur)" opacity="0.10">
    <animate attributeName="opacity"
      values="0.06;0.16;0.06" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''
    elif style == "side_fade":
        return f'''
  <!-- Ground Glow (side fade) -->
  <rect x="0" y="0" width="512" height="512" fill="url(#sideGlow)" filter="url(#heavyBlur)" opacity="0.06">
    <animate attributeName="opacity"
      values="0.04;0.10;0.04" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''
    else:
        return f'''
  <!-- Ground Glow (diagonal stripe) -->
  <rect x="-50" y="380" width="612" height="60" fill="{accent}" filter="url(#heavyBlur)" opacity="0.06"
    transform="rotate(-8,256,410)">
    <animate attributeName="opacity"
      values="0.04;0.12;0.04" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''


def _gen_glow_secondary(variant: str, colors: dict) -> str:
    """Generate variant-aware secondary glow animations — visually distinct per world.

    Sleep rules: cycle >=4s, gentle pulse, max opacity 60%.
    Each variant produces a different glow character with world-specific colors.
    """
    accent = colors.get("accent", colors["glow"])

    if variant == "glow_firefly":
        # 4-6 small glows at random positions, staggered pulse timings
        parts = ['\n  <!-- Firefly Glows -->']
        count = random.randint(4, 6)
        for i in range(count):
            cx = random.randint(60, 450)
            cy = random.randint(120, 440)
            r = random.randint(22, 35)
            dur = random.randint(6, 12)
            delay = random.uniform(0, dur * 0.7)
            glow_col = accent if i % 2 == 0 else colors["glow"]
            parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{glow_col}" filter="url(#softBlur)" opacity="0">
    <animate attributeName="opacity"
      values="0;0.08;0.50;0.40;0.08;0;0" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r};{r+10};{r+5};{r}" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')
        return "\n".join(parts)

    elif variant == "glow_bioluminescence":
        # 3 elongated horizontal glows at bottom, wave-like timing
        parts = ['\n  <!-- Bioluminescent Glow -->']
        count = 3
        for i in range(count):
            cx = random.randint(80, 440)
            cy = random.randint(320, 460)
            rx = random.randint(90, 160)
            ry = random.randint(25, 40)
            dur = random.randint(10, 18)
            delay = i * random.uniform(2, 4)
            bio_color = accent if i % 2 == 0 else colors["glow"]
            parts.append(f'''  <ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{bio_color}" opacity="0" filter="url(#softBlur)">
    <animate attributeName="opacity"
      values="0;0.12;0.40;0.25;0.12;0" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {random.randint(8,20)},0; 0,0; {random.randint(-15,-5)},0; 0,0"
      dur="{dur+4}s" begin="{delay:.1f}s" repeatCount="indefinite" />
  </ellipse>''')
        return "\n".join(parts)

    elif variant == "glow_campfire":
        # Single warm glow at bottom-center, faster flicker (4-6s)
        cx = random.randint(220, 300)
        cy = random.randint(410, 450)
        r = random.randint(55, 80)
        dur = random.randint(4, 6)
        return f'''
  <!-- Campfire Glow -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{accent}" filter="url(#softBlur)" opacity="0.25">
    <animate attributeName="opacity"
      values="0.20;0.50;0.35;0.55;0.25;0.20" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r};{r+8};{r-3};{r+10};{r}" dur="{dur}s" repeatCount="indefinite" />
  </circle>
  <circle cx="{cx}" cy="{cy+5}" r="{r//2}" fill="{colors['glow']}" opacity="0.15">
    <animate attributeName="opacity"
      values="0.12;0.30;0.18;0.32;0.12" dur="{dur-1}s" repeatCount="indefinite" />
  </circle>'''

    elif variant == "glow_candle":
        # Single small warm glow, slight position wobble
        cx = random.randint(200, 320)
        cy = random.randint(280, 400)
        r = random.randint(30, 50)
        dur = random.randint(5, 8)
        return f'''
  <!-- Candle Glow -->
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{accent}" filter="url(#softBlur)" opacity="0.30">
    <animate attributeName="opacity"
      values="0.22;0.50;0.30;0.48;0.22" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r};{r+6};{r-3};{r+4};{r}" dur="{dur}s" repeatCount="indefinite" />
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 3,-2; -2,0; 2,1; 0,0"
      dur="{dur+2}s" repeatCount="indefinite" />
  </circle>'''

    elif variant == "glow_crystals":
        # 4-5 sharp small glows, longer dim phases between pulses
        parts = ['\n  <!-- Crystal Glows -->']
        count = random.randint(4, 5)
        for i in range(count):
            cx = random.randint(80, 440)
            cy = random.randint(180, 440)
            r = random.randint(18, 30)
            dur = random.randint(8, 14)
            delay = random.uniform(0, dur * 0.5)
            crystal_color = accent if i % 2 == 0 else colors["glow"]
            parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{crystal_color}" filter="url(#softBlur)" opacity="0">
    <animate attributeName="opacity"
      values="0;0;0.08;0.55;0.40;0.08;0;0" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r};{r};{r+4};{r+8};{r+4};{r}" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')
        return "\n".join(parts)

    elif variant == "glow_nebula":
        # 2 very large diffuse glows, very slow (16-24s)
        parts = ['\n  <!-- Nebula Glow -->']
        count = 2
        for idx in range(count):
            cx = random.randint(120, 400)
            cy = random.randint(120, 380)
            r = random.randint(130, 200)
            dur = random.randint(16, 24)
            delay = random.uniform(0, 5)
            neb_color = accent if idx == 0 else colors["glow"]
            parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{neb_color}" filter="url(#softBlur)" opacity="0.08">
    <animate attributeName="opacity"
      values="0.06;0.20;0.10;0.18;0.06" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r-20};{r+25};{r-10};{r+15};{r-20}" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')
        return "\n".join(parts)

    elif variant == "glow_sunset":
        # Wide horizontal glow at horizon level, slow breathing
        cy = random.randint(370, 420)
        rx = random.randint(220, 320)
        ry = random.randint(45, 70)
        dur = random.randint(12, 18)
        return f'''
  <!-- Sunset Horizon Glow -->
  <ellipse cx="256" cy="{cy}" rx="{rx}" ry="{ry}" fill="{accent}" opacity="0.18" filter="url(#softBlur)">
    <animate attributeName="opacity"
      values="0.12;0.35;0.18;0.30;0.12" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="ry"
      values="{ry};{ry+12};{ry-5};{ry+10};{ry}" dur="{dur}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="256" cy="{cy+10}" rx="{rx-40}" ry="{ry//2}" fill="{colors['glow']}" opacity="0.12" filter="url(#softBlur)">
    <animate attributeName="opacity"
      values="0.08;0.22;0.08" dur="{dur+3}s" repeatCount="indefinite" />
  </ellipse>'''

    elif variant == "glow_lantern":
        # 2 warm glows in upper area, gentle flicker
        parts = ['\n  <!-- Lantern Glows -->']
        count = 2
        for idx in range(count):
            cx = random.randint(100, 420)
            cy = random.randint(80, 250)
            r = random.randint(35, 55)
            dur = random.randint(6, 10)
            delay = random.uniform(0, 3)
            lantern_color = accent if idx == 0 else colors["glow"]
            parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{lantern_color}" filter="url(#softBlur)" opacity="0.25">
    <animate attributeName="opacity"
      values="0.20;0.45;0.28;0.48;0.20" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r};{r+6};{r-2};{r+4};{r}" dur="{dur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')
        return "\n".join(parts)

    else:
        # Default: 2 breathing circles
        parts = ['\n  <!-- Secondary Ambient Glows -->']
        for idx in range(2):
            cx = random.randint(80, 440)
            cy = random.randint(150, 420)
            r = random.randint(60, 100)
            dur = random.randint(10, 16)
            glow_color = accent if idx == 0 else colors["glow"]
            parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{glow_color}" filter="url(#softBlur)">
    <animate attributeName="r"
      values="{r-10};{r+12};{r-10}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.18;0.42;0.18" dur="{dur}s" repeatCount="indefinite" />
  </circle>''')
        return "\n".join(parts)


def _gen_moonlight_wash(colors: dict, world: str = "") -> str:
    """Generate ambient light wash — varies by world to avoid sameness."""
    dur = random.randint(14, 20)
    accent = colors.get("accent", colors["glow"])

    # Choose wash style based on world
    WASH_MAP = {
        "deep_ocean": "side_curtains",
        "cloud_kingdom": "top_down",
        "enchanted_forest": "dappled",
        "snow_landscape": "top_down",
        "desert_night": "none",  # desert has enough glow from horizon
        "cozy_interior": "none",  # interior has corner glow
        "mountain_meadow": "side_curtains",
        "space_cosmos": "none",  # space has nebula blobs
        "tropical_lagoon": "bottom_warm",
        "underground_cave": "dappled",
        "ancient_library": "dappled",
        "floating_islands": "top_down",
    }
    style = WASH_MAP.get(world, "top_down")

    if style == "none":
        return ""

    elif style == "top_down":
        return f'''
  <!-- Moonlight Wash (top-down) -->
  <rect x="0" y="0" width="512" height="300" fill="url(#horizGlow)" filter="url(#heavyBlur)" opacity="0.08"
    transform="rotate(180,256,150)">
    <animate attributeName="opacity"
      values="0.05;0.14;0.05" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    elif style == "side_curtains":
        # Soft light from both sides
        return f'''
  <!-- Ambient Wash (side curtains) -->
  <rect x="0" y="0" width="512" height="512" fill="url(#sideGlow)" filter="url(#heavyBlur)" opacity="0.10">
    <animate attributeName="opacity"
      values="0.06;0.15;0.06" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    elif style == "dappled":
        # Scattered light patches — like forest canopy or cave crystals
        parts = ['\n  <!-- Dappled Light Wash -->']
        for _ in range(3):
            cx = random.randint(60, 450)
            cy = random.randint(60, 400)
            rx = random.randint(40, 80)
            ry = random.randint(30, 60)
            rot = random.randint(-30, 30)
            pdur = dur + random.randint(-3, 3)
            delay = random.uniform(0, 5)
            parts.append(f'''  <ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{accent}" opacity="0"
    filter="url(#heavyBlur)" transform="rotate({rot},{cx},{cy})">
    <animate attributeName="opacity"
      values="0;0.12;0.06;0.10;0" dur="{pdur}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </ellipse>''')
        return "\n".join(parts)

    elif style == "bottom_warm":
        return f'''
  <!-- Bottom Warm Wash -->
  <rect x="0" y="350" width="512" height="162" fill="url(#horizGlow)" filter="url(#heavyBlur)" opacity="0.10">
    <animate attributeName="opacity"
      values="0.06;0.16;0.06" dur="{dur}s" repeatCount="indefinite" />
  </rect>'''

    else:
        return ""


def _gen_vignette(style: str, colors: dict) -> str:
    """Generate per-world vignette — NOT the same dark edges on every cover.

    Different worlds get different darkness patterns so covers look distinct.
    Sleep rules: slow breathing (7-10s), max opacity 0.85.
    """
    dur = random.randint(8, 10)
    vig = colors["vignette"]

    if style == "none":
        # No vignette at all — clean, bright covers (cloud, snow, floating)
        return ""

    elif style == "top_heavy":
        # Dark at top, fading to clear at bottom (ocean, lagoon)
        return f'''
  <!-- Vignette (top-heavy) -->
  <defs><linearGradient id="vigLG" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{vig}" stop-opacity="0.7"/>
    <stop offset="50%" stop-color="{vig}" stop-opacity="0.15"/>
    <stop offset="100%" stop-color="{vig}" stop-opacity="0"/>
  </linearGradient></defs>
  <rect width="512" height="512" fill="url(#vigLG)">
    <animate attributeName="opacity" values="0.6;0.85;0.6" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    elif style == "bottom_heavy":
        # Dark at bottom, clear at top (forest — canopy lets light in from above)
        return f'''
  <!-- Vignette (bottom-heavy) -->
  <defs><linearGradient id="vigLG" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{vig}" stop-opacity="0"/>
    <stop offset="50%" stop-color="{vig}" stop-opacity="0.15"/>
    <stop offset="100%" stop-color="{vig}" stop-opacity="0.7"/>
  </linearGradient></defs>
  <rect width="512" height="512" fill="url(#vigLG)">
    <animate attributeName="opacity" values="0.6;0.85;0.6" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    elif style == "bottom_light":
        # Very subtle bottom only (meadow)
        return f'''
  <!-- Vignette (subtle bottom) -->
  <defs><linearGradient id="vigLG" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{vig}" stop-opacity="0"/>
    <stop offset="70%" stop-color="{vig}" stop-opacity="0"/>
    <stop offset="100%" stop-color="{vig}" stop-opacity="0.4"/>
  </linearGradient></defs>
  <rect width="512" height="512" fill="url(#vigLG)">
    <animate attributeName="opacity" values="0.5;0.7;0.5" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    elif style == "top_corners":
        # Dark in top corners only, open bottom and center (desert)
        return f'''
  <!-- Vignette (top corners) -->
  <defs><radialGradient id="vigRC" cx="0.5" cy="0.3" r="0.7">
    <stop offset="50%" stop-color="transparent"/>
    <stop offset="100%" stop-color="{vig}" stop-opacity="0.6"/>
  </radialGradient></defs>
  <rect width="512" height="512" fill="url(#vigRC)">
    <animate attributeName="opacity" values="0.5;0.75;0.5" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    elif style == "corners_only":
        # Dark corners only, very open center (space)
        return f'''
  <!-- Vignette (corners only) -->
  <defs><radialGradient id="vigRC" cx="0.5" cy="0.5" r="0.6">
    <stop offset="40%" stop-color="transparent"/>
    <stop offset="100%" stop-color="{vig}" stop-opacity="0.55"/>
  </radialGradient></defs>
  <rect width="512" height="512" fill="url(#vigRC)">
    <animate attributeName="opacity" values="0.5;0.7;0.5" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    elif style == "full_heavy":
        # Heavy all-around vignette (cave — glows punch through the darkness)
        return f'''
  <!-- Vignette (heavy) -->
  <rect width="512" height="512" fill="url(#vignetteGrad)">
    <animate attributeName="opacity" values="0.7;0.90;0.7" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''

    else:
        # full_soft — gentle all-around (library, interior)
        return f'''
  <!-- Vignette (soft) -->
  <rect width="512" height="512" fill="url(#vignetteGrad)">
    <animate attributeName="opacity" values="0.40;0.60;0.40" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''


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
        print(f"\nAnimations: {WORLD_TO_ANIMATIONS.get(axes['world_setting'], [])}")
        return

    # Check for HF token
    hf_token = os.getenv("HF_API_TOKEN")
    if not hf_token:
        logger.error("HF_API_TOKEN not set in .env")
        logger.error("Sign up at https://huggingface.co/ (free), create a Read token,")
        logger.error("then add HF_API_TOKEN=hf_xxx to dreamweaver-backend/.env")
        sys.exit(1)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate FLUX image
    image_bytes = generate_flux_image(prompt, hf_token)
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
