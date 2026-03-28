#!/usr/bin/env python3
"""Generate covers for funny shorts — FLUX image + comedy SMIL animations.

Separate from the sleep story cover pipeline. No drowsiness guardrails.
Bright, bold, cartoon style with bouncy/playful animations.

Usage:
    python3 scripts/generate_funny_cover.py --short-id crocodile-rock-001-a1b2
    python3 scripts/generate_funny_cover.py --all
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import sys
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load .env (scripts run outside Docker, so env vars aren't auto-loaded)
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow required — pip install Pillow")
    sys.exit(1)

logger = logging.getLogger("funny_cover")
logging.basicConfig(level=logging.INFO, format="%(message)s")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
COVERS_DIR = Path(__file__).resolve().parents[1] / "public" / "covers" / "funny-shorts"

# ── FLUX Prompt ────────────────────────────────────────────────

COVER_PROMPT_TEMPLATE = (
    "Children's book illustration, bold cartoon style, bright saturated colors, "
    "simple background, exaggerated funny expressions, playful and energetic, "
    "square composition, thick outlines, expressive eyes, slightly exaggerated "
    "proportions, Pixar-meets-picture-book aesthetic. "
    "Scene: {cover_description} "
    "DO NOT make it dreamy, muted, watercolor, or soft. This is comedy, not bedtime. "
    "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS anywhere in the image. "
    "No title, no caption, no speech bubbles with text, no signs with writing. "
    "Pure illustration only."
)


# ── FLUX Image Generation (Pollinations.ai) ───────────────────

def generate_flux_image(prompt: str) -> bytes | None:
    """Generate a 512x512 image via Pollinations.ai FLUX endpoint."""
    from urllib.parse import quote

    # Truncate prompt to ~600 chars to stay within URL limits
    truncated = prompt[:600]
    encoded_prompt = quote(truncated, safe="")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=512&height=512&model=flux&nologo=true"

    pollinations_token = os.getenv("POLLINATIONS_API_KEY", "")
    headers = {}
    if pollinations_token:
        headers["Authorization"] = f"Bearer {pollinations_token}"

    logger.info("  Calling FLUX via Pollinations.ai...")

    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                logger.info("  FLUX image: %d bytes", len(resp.content))
                return resp.content
            elif resp.status_code == 429:
                logger.warning("  Rate limited, waiting 15s...")
                time.sleep(15)
            else:
                logger.error("  FLUX error %d (%d bytes)", resp.status_code, len(resp.content))
                if attempt < 2:
                    time.sleep(5)
        except httpx.TimeoutException:
            logger.warning("  FLUX timeout (attempt %d)", attempt + 1)
            if attempt < 2:
                time.sleep(5)
        except Exception as e:
            logger.error("  FLUX error: %s", e)
            return None

    return None


def image_to_webp_b64(image_bytes: bytes, quality: int = 80) -> str:
    """Convert image bytes to base64-encoded WebP."""
    img = Image.open(BytesIO(image_bytes))
    img = img.convert("RGB")
    img = img.resize((512, 512), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


# ── Comedy SMIL Animation Overlay ──────────────────────────────

def _stable_seed(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % (2**31)


def generate_comedy_overlay(short_id: str) -> str:
    """Generate a playful SMIL animation overlay for a funny short cover.

    Comedy-energy animations: wobble, bounce, jiggle, blink, sparkle.
    No drowsiness guardrails. Bright colors. Faster timing.
    """
    rng = random.Random(_stable_seed(short_id))

    elements = []

    # 1. Wobble effect — slight rotation oscillation on the whole image
    wobble_dur = rng.choice([3, 4, 5])
    wobble_deg = rng.uniform(0.8, 1.5)
    elements.append(f"""
    <g transform-origin="256 256">
      <animateTransform attributeName="transform" type="rotate"
        values="0 256 256;{wobble_deg} 256 256;0 256 256;{-wobble_deg} 256 256;0 256 256"
        dur="{wobble_dur}s" repeatCount="indefinite"
        calcMode="spline" keySplines="0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1"/>
    </g>""")

    # 2. Bouncy sparkles — comedy energy particles
    n_sparkles = rng.randint(4, 8)
    sparkle_colors = ["#FFD700", "#FF6B9D", "#00E5FF", "#76FF03", "#FF9100", "#E040FB"]
    for i in range(n_sparkles):
        cx = rng.randint(5, 95)
        cy = rng.randint(5, 95)
        r = rng.uniform(2, 4)
        color = rng.choice(sparkle_colors)
        dur = rng.uniform(1.5, 3.5)
        begin = rng.uniform(0, 3)
        peak_opacity = rng.uniform(0.6, 0.9)
        elements.append(f"""
    <circle cx="{cx}%" cy="{cy}%" r="{r}" fill="{color}">
      <animate attributeName="opacity"
        values="0;{peak_opacity};0" dur="{dur:.1f}s" begin="{begin:.1f}s"
        repeatCount="indefinite" calcMode="spline"
        keySplines="0.4 0 0.6 1;0.4 0 0.6 1"/>
      <animate attributeName="r"
        values="{r};{r*1.5:.1f};{r}" dur="{dur:.1f}s" begin="{begin:.1f}s"
        repeatCount="indefinite"/>
    </circle>""")

    # 3. Cartoon eye blink — two small ellipses that periodically close
    blink_interval = rng.uniform(4, 7)
    blink_x1 = rng.randint(35, 42)
    blink_x2 = blink_x1 + rng.randint(14, 20)
    blink_y = rng.randint(35, 50)
    elements.append(f"""
    <ellipse cx="{blink_x1}%" cy="{blink_y}%" rx="8" ry="6" fill="white" opacity="0">
      <animate attributeName="opacity"
        values="0;0;0.85;0.85;0;0" dur="{blink_interval:.1f}s"
        keyTimes="0;0.85;0.87;0.93;0.95;1"
        repeatCount="indefinite"/>
    </ellipse>
    <ellipse cx="{blink_x2}%" cy="{blink_y}%" rx="8" ry="6" fill="white" opacity="0">
      <animate attributeName="opacity"
        values="0;0;0.85;0.85;0;0" dur="{blink_interval:.1f}s"
        keyTimes="0;0.85;0.87;0.93;0.95;1"
        repeatCount="indefinite"/>
    </ellipse>""")

    # 4. Bouncing exclamation marks / comedy accents
    n_accents = rng.randint(2, 4)
    accent_shapes = ["!", "?", "*", "✦"]
    for i in range(n_accents):
        ax = rng.randint(10, 90)
        ay = rng.randint(8, 30)
        char = rng.choice(accent_shapes)
        size = rng.randint(14, 22)
        color = rng.choice(sparkle_colors)
        dur = rng.uniform(2, 4)
        begin = rng.uniform(0, 3)
        bounce_y = rng.randint(5, 12)
        elements.append(f"""
    <text x="{ax}%" y="{ay}%" font-size="{size}" fill="{color}"
          text-anchor="middle" font-weight="bold" opacity="0.8">
      {char}
      <animate attributeName="opacity"
        values="0;0.8;0.8;0" dur="{dur:.1f}s" begin="{begin:.1f}s"
        repeatCount="indefinite"/>
      <animateTransform attributeName="transform" type="translate"
        values="0,0;0,{-bounce_y};0,0" dur="{dur/2:.1f}s" begin="{begin:.1f}s"
        repeatCount="indefinite" calcMode="spline"
        keySplines="0.3 0 0.7 1;0.3 0 0.7 1"/>
    </text>""")

    # 5. Subtle scale pulse — makes the whole cover feel alive
    pulse_dur = rng.uniform(3, 5)
    pulse_scale = rng.uniform(1.005, 1.015)
    elements.append(f"""
    <animateTransform attributeName="transform" type="scale"
      values="1;{pulse_scale:.3f};1" dur="{pulse_dur:.1f}s"
      repeatCount="indefinite" calcMode="spline"
      keySplines="0.4 0 0.6 1;0.4 0 0.6 1"
      additive="sum"/>""")

    # 6. Comedy border flash — brief bright border pulse
    flash_dur = rng.uniform(4, 8)
    flash_color = rng.choice(["#FFD700", "#FF6B9D", "#00E5FF"])
    elements.append(f"""
    <rect x="2" y="2" width="508" height="508" rx="20" ry="20"
          fill="none" stroke="{flash_color}" stroke-width="3" opacity="0">
      <animate attributeName="opacity"
        values="0;0;0.4;0;0" dur="{flash_dur:.1f}s"
        repeatCount="indefinite"/>
    </rect>""")

    return "\n".join(elements)


def build_cover_svg(bg_b64: str, short_id: str) -> str:
    """Build the final SVG with WebP background + comedy SMIL overlay."""
    overlay = generate_comedy_overlay(short_id)

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <image id="bg" width="512" height="512"
           href="data:image/webp;base64,{bg_b64}"/>
  </defs>

  <!-- Background -->
  <use href="#bg"/>

  <!-- Comedy animation overlay -->
  <g id="comedy-overlay">
    {overlay}
  </g>
</svg>"""

    return svg


# ── Pipeline ───────────────────────────────────────────────────

def generate_cover_for_short(short: dict) -> str | None:
    """Generate a cover for a funny short. Returns cover filename or None."""
    short_id = short["id"]
    cover_desc = short.get("cover_description", "")

    if not cover_desc:
        # Try to extract from script
        import re
        match = re.search(r"\[COVER:\s*(.+?)\]", short.get("script", ""))
        if match:
            cover_desc = match.group(1).strip()

    if not cover_desc:
        logger.warning("  No cover description for %s — using title", short_id)
        cover_desc = f"A funny cartoon scene from '{short.get('title', 'a comedy short')}'"

    # Build FLUX prompt
    prompt = COVER_PROMPT_TEMPLATE.format(cover_description=cover_desc)
    logger.info("  FLUX prompt: %s", prompt[:100] + "...")

    # Generate image
    image_bytes = generate_flux_image(prompt)
    if not image_bytes:
        logger.error("  Failed to generate FLUX image for %s", short_id)
        return None

    # Convert to WebP base64
    bg_b64 = image_to_webp_b64(image_bytes)

    # Build SVG with animation overlay
    svg_content = build_cover_svg(bg_b64, short_id)

    # Save
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    cover_filename = f"{short_id}.svg"
    cover_path = COVERS_DIR / cover_filename

    with open(cover_path, "w") as f:
        f.write(svg_content)

    svg_size_kb = len(svg_content) / 1024
    logger.info("  Cover saved: %s (%.1f KB)", cover_path, svg_size_kb)
    return cover_filename


def process_short(short_path: Path, force: bool = False) -> bool:
    """Generate cover for a single funny short."""
    with open(short_path) as f:
        short = json.load(f)

    short.setdefault("id", short_path.stem)

    if short.get("cover_file") and not force:
        cover_path = COVERS_DIR / short["cover_file"]
        if cover_path.exists():
            logger.info("  Cover already exists: %s, skipping", cover_path)
            return True

    cover_filename = generate_cover_for_short(short)
    if not cover_filename:
        return False

    short["cover_file"] = cover_filename

    with open(short_path, "w") as f:
        json.dump(short, f, indent=2)

    return True


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate funny short covers")
    parser.add_argument("--short-id", help="Generate cover for a specific short")
    parser.add_argument("--all", action="store_true", help="Generate covers for all shorts")
    parser.add_argument("--force", action="store_true", help="Regenerate even if cover exists")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    # Pollinations works without API key (but slower without auth)

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            logger.error("Short not found: %s", path)
            sys.exit(1)
        logger.info("Generating cover: %s", args.short_id)
        ok = process_short(path, args.force)
        sys.exit(0 if ok else 1)

    if args.all:
        if not DATA_DIR.exists():
            logger.info("No funny shorts data directory")
            sys.exit(0)

        shorts = sorted(DATA_DIR.glob("*.json"))
        logger.info("Found %d funny shorts", len(shorts))

        success = 0
        for path in shorts:
            logger.info("\n%s", "=" * 60)
            logger.info("Generating cover: %s", path.stem)
            if process_short(path, args.force):
                success += 1

        logger.info("\n%s", "=" * 60)
        logger.info("Done: %d/%d covers generated", success, len(shorts))


if __name__ == "__main__":
    main()
