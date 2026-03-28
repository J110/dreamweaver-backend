#!/usr/bin/env python3
"""Generate WebP covers for silly songs via Pollinations FLUX.

Static covers (no SMIL animation for now). Same image pipeline as
generate_funny_cover.py but with a musical scene prompt.

Output:
  public/covers/silly-songs/{song_id}.webp

Usage:
    python3 scripts/generate_silly_song_covers.py --all
    python3 scripts/generate_silly_song_covers.py --song not-a-rock
    python3 scripts/generate_silly_song_covers.py --all --force
"""

import argparse
import json
import logging
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

logger = logging.getLogger("song_cover")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "silly_songs"
COVERS_DIR = BASE_DIR / "public" / "covers" / "silly-songs"

# ── FLUX Prompt ─────────────────────────────────────────────

COVER_PROMPT_TEMPLATE = (
    "Children's book illustration, bold cartoon style, bright saturated colors, "
    "simple background, exaggerated funny expressions, playful and energetic, "
    "square composition, thick outlines, expressive eyes, slightly exaggerated "
    "proportions, Pixar-meets-picture-book aesthetic. "
    "Musical scene: {cover_description} "
    "Include subtle musical elements: small floating music notes, or the "
    "character holding/near an instrument, or a stage-like spotlight feel. "
    "NOT a realistic concert — cartoon musical energy. "
    "DO NOT make it dreamy, muted, watercolor, or soft. This is comedy + music, not bedtime. "
    "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS anywhere in the image. "
    "No title, no caption, no speech bubbles with text, no signs with writing. "
    "Pure illustration only."
)


def generate_flux_image(prompt: str) -> bytes | None:
    """Generate a 512x512 image via Pollinations.ai FLUX endpoint."""
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


def save_as_webp(image_bytes: bytes, output_path: Path, quality: int = 85):
    """Convert image bytes to WebP and save."""
    img = Image.open(BytesIO(image_bytes))
    img = img.convert("RGB")
    img = img.resize((512, 512), Image.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), format="WEBP", quality=quality)
    size_kb = output_path.stat().st_size / 1024
    logger.info("  Saved: %s (%.0f KB)", output_path.name, size_kb)


def generate_cover(song: dict, force: bool = False) -> bool:
    """Generate cover for a single song. Returns True on success."""
    song_id = song["id"]
    title = song["title"]
    cover_path = COVERS_DIR / f"{song_id}.webp"

    if cover_path.exists() and not force:
        logger.info("  %s — cover exists, skipping", title)
        return True

    description = song.get("cover_description", "")
    if not description:
        logger.warning("  %s — no cover_description, skipping", title)
        return False

    prompt = COVER_PROMPT_TEMPLATE.format(cover_description=description)
    logger.info("\n  Generating cover: %s", title)

    image_bytes = generate_flux_image(prompt)
    if not image_bytes:
        logger.error("  FAILED: %s", title)
        return False

    save_as_webp(image_bytes, cover_path)

    # Update JSON with cover path
    song["cover_file"] = f"{song_id}.webp"
    json_path = DATA_DIR / f"{song_id}.json"
    with open(json_path, "w") as f:
        json.dump(song, f, indent=2)

    return True


def load_songs(song_id: str | None = None) -> list[dict]:
    """Load song data from JSON files."""
    songs = []
    if not DATA_DIR.exists():
        return songs
    for f in sorted(DATA_DIR.glob("*.json")):
        if song_id and f.stem != song_id:
            continue
        try:
            with open(f) as fh:
                song = json.load(fh)
                song.setdefault("id", f.stem)
                songs.append(song)
        except Exception as e:
            logger.error("  Failed to load %s: %s", f, e)
    return songs


def main():
    parser = argparse.ArgumentParser(description="Generate silly song covers via FLUX")
    parser.add_argument("--all", action="store_true", help="Generate all covers")
    parser.add_argument("--song", help="Generate cover for a specific song by ID")
    parser.add_argument("--force", action="store_true", help="Regenerate even if files exist")
    args = parser.parse_args()

    if not args.all and not args.song:
        parser.error("Specify --all or --song <id>")

    songs = load_songs(args.song)
    if not songs:
        print(f"No songs found" + (f" for id '{args.song}'" if args.song else ""))
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"Silly Song Covers — {len(songs)} song(s)")
    print(f"{'=' * 60}")

    success = 0
    for song in songs:
        if generate_cover(song, force=args.force):
            success += 1
        if song != songs[-1]:
            time.sleep(5)

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{len(songs)} covers generated")


if __name__ == "__main__":
    main()
