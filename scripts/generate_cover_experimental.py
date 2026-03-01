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

    Sleep-focused: Always includes vignette breathing + glow breathing pacer + particles.
    Plus world-specific animations (mist, twinkle, drift).
    """
    world = axes["world_setting"]
    palette = axes["palette"]
    time_setting = axes.get("time", "early_night")

    # Get ALL animation types for this world (use all, not just 2-3)
    anim_types = WORLD_TO_ANIMATIONS.get(world, ["particles_pollen", "glow_firefly", "vignette"])

    # Palette-based colors
    palette_colors = {
        "ember_warm":   {"glow": "#FFD699", "particle": "#FFCC80", "vignette": "#1a0a05", "star": "#FFF5E0"},
        "twilight_cool": {"glow": "#C8B8E0", "particle": "#D0C4E8", "vignette": "#0a0520", "star": "#E8E0F0"},
        "forest_deep":  {"glow": "#A8D5A0", "particle": "#C4E0B8", "vignette": "#051005", "star": "#D8F0D0"},
        "golden_hour":  {"glow": "#FFE4B5", "particle": "#FFD89B", "vignette": "#1a0f00", "star": "#FFF8E8"},
        "moonstone":    {"glow": "#C0D0E0", "particle": "#B8C8D8", "vignette": "#050810", "star": "#E0E8F0"},
        "berry_dusk":   {"glow": "#D8A8C8", "particle": "#E0B8D0", "vignette": "#100510", "star": "#F0D8E8"},
    }
    colors = palette_colors.get(palette, palette_colors["golden_hour"])

    svg_parts = []
    svg_parts.append(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <radialGradient id="glowGrad">
      <stop offset="0%" stop-color="{colors['glow']}" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="{colors['glow']}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="glowGrad2">
      <stop offset="0%" stop-color="{colors['particle']}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="{colors['particle']}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="vignetteGrad">
      <stop offset="40%" stop-color="transparent"/>
      <stop offset="100%" stop-color="{colors['vignette']}" stop-opacity="0.75"/>
    </radialGradient>
    <filter id="softBlur">
      <feGaussianBlur stdDeviation="2"/>
    </filter>
  </defs>''')

    # --- ALWAYS include these sleep-essential layers ---

    # 1. Vignette breathing (darkens edges, primary sleep cue)
    svg_parts.append(_gen_vignette())

    # 2. Glow breathing pacer (guides breathing rhythm, 6-8 cycles/min)
    svg_parts.append(_gen_glow("glow_breathing", colors))

    # 3. World-specific animations (all of them)
    for anim in anim_types:
        if anim.startswith("particles"):
            svg_parts.append(_gen_particles(anim, colors))
        elif anim.startswith("glow") and anim != "glow_breathing":
            svg_parts.append(_gen_glow_secondary(colors))
        elif anim.startswith("twinkle"):
            svg_parts.append(_gen_twinkle(colors))
        elif anim.startswith("drift"):
            svg_parts.append(_gen_drift(anim, colors))
        elif anim.startswith("mist"):
            svg_parts.append(_gen_mist(colors))

    # 4. Always add twinkle stars for night settings
    if time_setting in ("early_night", "deep_night") and not any(a.startswith("twinkle") for a in anim_types):
        svg_parts.append(_gen_twinkle(colors))

    # 5. Always add mist/fog for grounding
    if not any(a.startswith("mist") for a in anim_types):
        svg_parts.append(_gen_mist(colors))

    # 6. Moonlight wash overlay (gentle top-down light)
    svg_parts.append(_gen_moonlight_wash(colors))

    svg_parts.append('\n</svg>')
    return "\n".join(svg_parts)


def _gen_particles(variant: str, colors: dict) -> str:
    """Generate drifting particle animations — visible but slow.

    Sleep rules: cycle >=4s, opacity <=60%, slow drift.
    """
    count = random.randint(8, 12)
    particles = []
    particles.append('\n  <!-- Drifting Particles (floating orbs) -->')

    for i in range(count):
        cx = random.randint(30, 480)
        cy_start = random.randint(-30, 80)
        # Mix of sizes: some larger glowing orbs, some tiny dust
        if i < 3:
            r = random.uniform(4.0, 7.0)   # Large glowing orbs
            opacity = random.uniform(0.30, 0.50)
        elif i < 7:
            r = random.uniform(2.0, 4.0)   # Medium particles
            opacity = random.uniform(0.25, 0.45)
        else:
            r = random.uniform(1.0, 2.0)   # Tiny dust motes
            opacity = random.uniform(0.15, 0.35)

        dur = random.uniform(15, 28)  # Slow drift (>=4s rule)
        delay = random.uniform(0, 12)

        # Path: gentle S-curve downward
        dx = random.randint(-40, 40)
        dy = random.randint(350, 500)
        cx1 = random.randint(-30, 30)
        cy1 = random.randint(100, 180)
        cx2 = random.randint(-25, 25)
        cy2 = random.randint(250, 350)

        particles.append(f'''  <circle r="{r:.1f}" fill="{colors['particle']}" opacity="0" filter="url(#softBlur)">
    <animateMotion dur="{dur:.0f}s" begin="{delay:.1f}s" repeatCount="indefinite"
      path="M{cx},{cy_start} C{cx+cx1},{cy_start+cy1} {cx+cx2},{cy_start+cy2} {cx+dx},{cy_start+dy}" />
    <animate attributeName="opacity"
      values="0;{opacity:.2f};{opacity:.2f};{opacity*0.4:.2f};0" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')

    return "\n".join(particles)


def _gen_glow(variant: str, colors: dict) -> str:
    """Generate breathing pacer glow — the primary sleep cue.

    Sleep rules: 6-12 cycles/min = 5-10s per cycle. Must be clearly visible.
    Two concentric rings for depth.
    """
    cx = random.randint(200, 320)
    cy = random.randint(240, 360)
    dur = random.randint(7, 9)  # ~7-9 BPM breathing

    r_outer = random.randint(100, 130)
    r_inner = random.randint(50, 70)

    return f'''
  <!-- Breathing Pacer Glow (primary sleep cue) -->
  <!-- Outer glow ring -->
  <circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="url(#glowGrad)" filter="url(#softBlur)">
    <animate attributeName="r"
      values="{r_outer-15};{r_outer+15};{r_outer-15}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.25;0.50;0.25" dur="{dur}s" repeatCount="indefinite" />
  </circle>
  <!-- Inner glow core -->
  <circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="url(#glowGrad)">
    <animate attributeName="r"
      values="{r_inner-8};{r_inner+12};{r_inner-8}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.35;0.55;0.35" dur="{dur}s" repeatCount="indefinite" />
  </circle>'''


def _gen_twinkle(colors: dict) -> str:
    """Generate twinkling star/shimmer effects — visible slow twinkles.

    Sleep rules: cycle >=4s, gentle fade in/out.
    """
    count = random.randint(12, 18)
    twinkles = []
    twinkles.append('\n  <!-- Twinkling Stars -->')

    for i in range(count):
        cx = random.randint(15, 500)
        cy = random.randint(5, 280)
        dur = random.uniform(5, 10)  # >=4s rule
        delay = random.uniform(0, 8)

        # Mix of star sizes
        if i < 4:
            r = random.uniform(2.5, 3.5)
            max_opacity = random.uniform(0.40, 0.55)
        elif i < 10:
            r = random.uniform(1.5, 2.5)
            max_opacity = random.uniform(0.30, 0.50)
        else:
            r = random.uniform(0.8, 1.5)
            max_opacity = random.uniform(0.20, 0.40)

        twinkles.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="{colors['star']}" opacity="0">
    <animate attributeName="opacity"
      values="0;{max_opacity:.2f};{max_opacity*0.5:.2f};{max_opacity:.2f};0" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
    <animate attributeName="r"
      values="{r:.1f};{r*1.3:.1f};{r:.1f}" dur="{dur:.0f}s"
      begin="{delay:.1f}s" repeatCount="indefinite" />
  </circle>''')

    return "\n".join(twinkles)


def _gen_drift(variant: str, colors: dict) -> str:
    """Generate slow drift/pan — gentle horizontal haze movement.

    Sleep rules: very slow (25-40s cycle), low opacity.
    """
    dur = random.randint(25, 40)
    dx = random.randint(8, 15)
    dy = random.randint(2, 5)

    return f'''
  <!-- Slow Drifting Haze -->
  <g>
    <animateTransform attributeName="transform" type="translate"
      values="0,0; {dx},{dy}; 0,0; {-dx},{-dy}; 0,0"
      dur="{dur}s" repeatCount="indefinite" />
    <ellipse cx="256" cy="450" rx="320" ry="60" fill="{colors['particle']}" opacity="0.12" filter="url(#softBlur)"/>
    <ellipse cx="150" cy="470" rx="220" ry="45" fill="{colors['glow']}" opacity="0.10" filter="url(#softBlur)"/>
    <ellipse cx="380" cy="440" rx="180" ry="35" fill="{colors['particle']}" opacity="0.08" filter="url(#softBlur)"/>
  </g>'''


def _gen_mist(colors: dict) -> str:
    """Generate rising mist/fog — three layers for depth.

    Sleep rules: slow movement (20-40s), moderate opacity.
    """
    dur1 = random.randint(22, 32)
    dur2 = random.randint(28, 38)
    dur3 = random.randint(18, 28)

    return f'''
  <!-- Rising Mist (3 layers) -->
  <ellipse cx="180" cy="480" rx="280" ry="60" fill="{colors['glow']}" opacity="0.15" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 20,-12; 0,0; -15,-8; 0,0"
      dur="{dur1}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.10;0.22;0.10" dur="{dur1}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="350" cy="495" rx="230" ry="45" fill="{colors['particle']}" opacity="0.12" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; -18,-10; 0,0; 12,-6; 0,0"
      dur="{dur2}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.08;0.18;0.08" dur="{dur2}s" repeatCount="indefinite" />
  </ellipse>
  <ellipse cx="256" cy="510" rx="350" ry="70" fill="{colors['glow']}" opacity="0.10" filter="url(#softBlur)">
    <animateTransform attributeName="transform" type="translate"
      values="0,0; 10,-5; 0,0; -8,-3; 0,0"
      dur="{dur3}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.06;0.15;0.06" dur="{dur3}s" repeatCount="indefinite" />
  </ellipse>'''


def _gen_glow_secondary(colors: dict) -> str:
    """Generate secondary ambient glows — two offset glows for atmosphere."""
    parts = ['\n  <!-- Secondary Ambient Glows -->']
    for _ in range(2):
        cx = random.randint(80, 440)
        cy = random.randint(150, 420)
        r = random.randint(55, 90)
        dur = random.randint(10, 16)

        parts.append(f'''  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#glowGrad2)" filter="url(#softBlur)">
    <animate attributeName="r"
      values="{r-10};{r+10};{r-10}" dur="{dur}s" repeatCount="indefinite" />
    <animate attributeName="opacity"
      values="0.15;0.35;0.15" dur="{dur}s" repeatCount="indefinite" />
  </circle>''')
    return "\n".join(parts)


def _gen_moonlight_wash(colors: dict) -> str:
    """Generate a gentle top-down moonlight wash — visible ambient light."""
    dur = random.randint(14, 20)

    return f'''
  <!-- Moonlight Wash -->
  <ellipse cx="256" cy="100" rx="320" ry="200" fill="{colors['star']}" opacity="0.05" filter="url(#softBlur)">
    <animate attributeName="opacity"
      values="0.03;0.10;0.03" dur="{dur}s" repeatCount="indefinite" />
  </ellipse>
  <!-- Bottom warm glow -->
  <ellipse cx="256" cy="480" rx="300" ry="100" fill="{colors['glow']}" opacity="0.04" filter="url(#softBlur)">
    <animate attributeName="opacity"
      values="0.03;0.08;0.03" dur="{dur+4}s" repeatCount="indefinite" />
  </ellipse>'''


def _gen_vignette() -> str:
    """Generate vignette breathing — darkens edges, primary sleep framing.

    Sleep rules: slow breathing (7-10s), max opacity 0.85.
    """
    dur = random.randint(8, 10)

    return f'''
  <!-- Vignette Breathing (sleep framing) -->
  <rect width="512" height="512" fill="url(#vignetteGrad)">
    <animate attributeName="opacity"
      values="0.55;0.80;0.55" dur="{dur}s" repeatCount="indefinite"/>
  </rect>'''


# ── Preview HTML Generator ──────────────────────────────────────────────

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
    logger.info("Preview:    %s", html_path)
    logger.info("")
    logger.info("Open the preview in your browser:")
    logger.info("  open %s", html_path)


if __name__ == "__main__":
    main()
