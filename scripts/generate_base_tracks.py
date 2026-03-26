#!/usr/bin/env python3
"""Generate 90-second base tracks for funny shorts via Replicate MusicGen.

Creates 5 styles × 3 variants = 15 unique background tracks.
These play underneath voice + stings in the final mix.

Output:
  public/audio/funny-music/base-tracks/base_<style>_<NN>.wav

Usage:
    python3 scripts/generate_base_tracks.py --all
    python3 scripts/generate_base_tracks.py --style bouncy
    python3 scripts/generate_base_tracks.py --all --force
"""

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import replicate
except ImportError:
    print("ERROR: replicate required — pip install replicate")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx")
    sys.exit(1)

BASE_TRACKS_DIR = (
    Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-music" / "base-tracks"
)

# ── Base Track Definitions ────────────────────────────────────────

BASE_TRACK_PROMPTS = {
    "bouncy": {
        "prompt": (
            "Playful bouncy children's cartoon background music, pizzicato strings, "
            "xylophone, light percussion, upbeat and silly, gentle energy, "
            "comedy underscore, not too busy, leaves room for voice-over, "
            "seamless loop feel, bright and cheerful, 90 seconds"
        ),
        "variants": 3,
    },
    "sneaky": {
        "prompt": (
            "Sneaky comedic villain background music, tiptoeing pizzicato bass, "
            "muted trombone, quiet percussion, cartoon scheming music, "
            "playful suspense, not scary, children's comedy underscore, "
            "low energy but mischievous, leaves room for voice-over, 90 seconds"
        ),
        "variants": 3,
    },
    "mysterious": {
        "prompt": (
            "Mysterious spooky cartoon background music, celesta, low strings, "
            "gentle harp arpeggios, dark fairy tale atmosphere, not actually scary, "
            "comedic tension, witch theme, children's comedy underscore, "
            "ethereal and floaty, leaves room for voice-over, 90 seconds"
        ),
        "variants": 3,
    },
    "gentle_absurd": {
        "prompt": (
            "Gentle absurdist comedy background music, soft glockenspiel, "
            "light flute, minimal piano, understated and dry, deadpan comedy feel, "
            "quirky pauses, children's comedy underscore, not energetic, "
            "calm and slightly odd, leaves room for voice-over, 90 seconds"
        ),
        "variants": 3,
    },
    "whimsical": {
        "prompt": (
            "Whimsical poetic children's background music, harp and light woodwinds, "
            "gentle rhythm section, storybook feel, bouncy but graceful, "
            "nursery rhyme accompaniment, comedy underscore, "
            "playful and musical, leaves room for voice-over, 90 seconds"
        ),
        "variants": 3,
    },
}


def generate_track(prompt: str, duration: int = 90, max_retries: int = 5) -> bytes | None:
    """Generate a base track via Replicate MusicGen."""
    for attempt in range(max_retries):
        try:
            output = replicate.run(
                "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
                input={
                    "model_version": "stereo-melody-large",
                    "prompt": prompt,
                    "duration": duration,
                    "output_format": "wav",
                    "normalization_strategy": "peak",
                },
            )

            if hasattr(output, "read"):
                audio_bytes = output.read()
            else:
                resp = httpx.get(str(output), timeout=120)
                resp.raise_for_status()
                audio_bytes = resp.content

            if len(audio_bytes) > 10000:
                return audio_bytes
            else:
                print(f"    Too small: {len(audio_bytes)} bytes")

        except Exception as e:
            err_str = str(e)
            if "rate" in err_str.lower() or "429" in err_str:
                wait = 60 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)

    return None


def generate_style(style: str, force: bool = False) -> int:
    """Generate all variants for a style. Returns count of successes."""
    config = BASE_TRACK_PROMPTS.get(style)
    if not config:
        print(f"  Unknown style: {style}")
        return 0

    success = 0
    for v in range(1, config["variants"] + 1):
        filename = f"base_{style}_{v:02d}.wav"
        filepath = BASE_TRACKS_DIR / filename

        if filepath.exists() and not force:
            print(f"  {filename} — already exists, skipping")
            success += 1
            continue

        print(f"  Generating {filename}...")
        audio = generate_track(config["prompt"])

        if audio:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(audio)
            size_mb = len(audio) / (1024 * 1024)
            print(f"  Saved {filename} ({size_mb:.1f} MB)")
            success += 1
        else:
            print(f"  FAILED: {filename}")

        # Rate limit pause between requests
        time.sleep(30)

    return success


def main():
    parser = argparse.ArgumentParser(description="Generate comedy base tracks")
    parser.add_argument("--style", choices=list(BASE_TRACK_PROMPTS.keys()),
                        help="Generate tracks for a specific style")
    parser.add_argument("--all", action="store_true", help="Generate all styles")
    parser.add_argument("--force", action="store_true", help="Regenerate existing tracks")
    args = parser.parse_args()

    if not args.style and not args.all:
        parser.error("Specify --style or --all")

    if not os.getenv("REPLICATE_API_TOKEN"):
        print("ERROR: REPLICATE_API_TOKEN not set")
        sys.exit(1)

    styles = [args.style] if args.style else list(BASE_TRACK_PROMPTS.keys())

    total = sum(BASE_TRACK_PROMPTS[s]["variants"] for s in styles)
    success = 0

    for style in styles:
        print(f"\n{'='*60}")
        print(f"Style: {style}")
        print(f"{'='*60}")
        success += generate_style(style, args.force)

    print(f"\n{'='*60}")
    print(f"Done: {success}/{total} tracks generated")


if __name__ == "__main__":
    main()
