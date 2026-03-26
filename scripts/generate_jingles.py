#!/usr/bin/env python3
"""Generate show + character jingles for Before Bed episodes via Replicate MusicGen.

One-time generation of 12 static audio files:
  - 1 show intro jingle (3.5s)
  - 1 show outro jingle (3.5s)
  - 5 character intro jingles (2-2.5s each)
  - 5 character outro jingles (1-1.5s each)

Output:
  public/audio/jingles/beforebed_intro_jingle.wav
  public/audio/jingles/beforebed_outro_jingle.wav
  public/audio/jingles/char_jingle_boomy_intro.wav
  public/audio/jingles/char_jingle_boomy_outro.wav
  ... etc.

Usage:
    python3 scripts/generate_jingles.py --all
    python3 scripts/generate_jingles.py --show-only
    python3 scripts/generate_jingles.py --character boomy
    python3 scripts/generate_jingles.py --all --force
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

JINGLES_DIR = (
    Path(__file__).resolve().parents[1] / "public" / "audio" / "jingles"
)

# ── Jingle Definitions ────────────────────────────────────────

SHOW_INTRO_JINGLE = {
    "file": "beforebed_intro_jingle.wav",
    "duration": 4,
    "prompt": (
        "3.5 second playful jingle for a children's audio show. "
        "Glockenspiel melody, 4-5 notes ascending, ending on a cheeky "
        "wobble note. Soft pizzicato bass underneath. One triangle hit "
        "at the very end. Bright, mischievous, instantly recognizable. "
        "Like a music box that's slightly naughty. Must sound complete "
        "in 3.5 seconds — not a fade, a proper ending."
    ),
}

SHOW_OUTRO_JINGLE = {
    "file": "beforebed_outro_jingle.wav",
    "duration": 4,
    "prompt": (
        "3.5 second closing jingle for a children's audio show. "
        "Glockenspiel melody descending, same instruments as the intro "
        "(glockenspiel, pizzicato bass). Slower tempo. The last "
        "note rings out and fades gently. Like the intro melody going to "
        "sleep. Must feel like the intro played backwards and sleepier. "
        "Warm, resolved, settling."
    ),
}

CHARACTER_INTRO_JINGLES = {
    "boomy": {
        "file": "char_jingle_boomy_intro.wav",
        "duration": 3,
        "prompt": (
            "2.5 second comedic villain entrance. Low tuba "
            "playing 3 notes — dun, dun, DUNNN. Sneaky, "
            "dramatic, played for laughs. Cartoon villain "
            "stepping onto stage."
        ),
    },
    "pip": {
        "file": "char_jingle_pip_intro.wav",
        "duration": 3,
        "prompt": (
            "2 second cartoon character entrance. Quick high "
            "xylophone run going up — biddly-biddly-BING. "
            "Small, fast, cute. Something tiny scurrying in."
        ),
    },
    "shadow": {
        "file": "char_jingle_shadow_intro.wav",
        "duration": 3,
        "prompt": (
            "2.5 second mysterious entrance. Low celesta "
            "trill with a single deep gong at the end. "
            "Spooky but playful — dark fairy tale, not "
            "actually scary. Curtain slowly opening."
        ),
    },
    "sunny": {
        "file": "char_jingle_sunny_intro.wav",
        "duration": 3,
        "prompt": (
            "2 second innocent entrance. Simple toy piano "
            "playing 3 sweet notes, almost too cute, "
            "followed by a tiny pause. The innocence is "
            "slightly suspicious."
        ),
    },
    "melody": {
        "file": "char_jingle_melody_intro.wav",
        "duration": 3,
        "prompt": (
            "2.5 second elegant entrance. Quick harp "
            "arpeggio flourish going up. Fairy-tale-like, "
            "whimsical, warm. The musical 'once upon a time.'"
        ),
    },
}

CHARACTER_OUTRO_JINGLES = {
    "boomy": {
        "file": "char_jingle_boomy_outro.wav",
        "duration": 2,
        "prompt": (
            "1.5 second comedy defeat. Single tuba note "
            "deflating — wahhh. The villain lost again."
        ),
    },
    "pip": {
        "file": "char_jingle_pip_outro.wav",
        "duration": 2,
        "prompt": (
            "1 second cheerful ending. Single high "
            "xylophone 'bing!' — bright, quick, happy."
        ),
    },
    "shadow": {
        "file": "char_jingle_shadow_outro.wav",
        "duration": 2,
        "prompt": (
            "1.5 second mysterious ending. Low celesta "
            "single note fading into silence. Unresolved."
        ),
    },
    "sunny": {
        "file": "char_jingle_sunny_outro.wav",
        "duration": 2,
        "prompt": (
            "1 second deadpan ending. One toy piano note, "
            "completely flat. The musical 'cool.'"
        ),
    },
    "melody": {
        "file": "char_jingle_melody_outro.wav",
        "duration": 2,
        "prompt": (
            "1.5 second fairy tale closing. Harp glissando "
            "descending gently. Warm, resolved, settling."
        ),
    },
}

# Voice name → voice_id mapping for episode assembly
VOICE_NAME_TO_ID = {
    "boomy":  "comedic_villain",
    "pip":    "high_pitch_cartoon",
    "shadow": "mysterious_witch",
    "sunny":  "young_sweet",
    "melody": "musical_original",
}

VOICE_ID_TO_NAME = {v: k for k, v in VOICE_NAME_TO_ID.items()}


# ── Generation ────────────────────────────────────────────────

def generate_jingle(prompt: str, duration: int, max_retries: int = 5) -> bytes | None:
    """Generate a jingle via Replicate MusicGen."""
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

            if len(audio_bytes) > 1000:
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


def generate_single(name: str, config: dict, force: bool = False) -> bool:
    """Generate a single jingle. Returns True on success."""
    filepath = JINGLES_DIR / config["file"]

    if filepath.exists() and not force:
        print(f"  {config['file']} — already exists, skipping")
        return True

    print(f"  Generating {config['file']}...")
    audio = generate_jingle(config["prompt"], config["duration"])

    if audio:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(audio)
        size_kb = len(audio) / 1024
        print(f"  Saved {config['file']} ({size_kb:.0f} KB)")
        return True
    else:
        print(f"  FAILED: {config['file']}")
        return False


def generate_show_jingles(force: bool = False) -> int:
    """Generate show intro and outro jingles. Returns success count."""
    success = 0
    for name, config in [("show_intro", SHOW_INTRO_JINGLE),
                          ("show_outro", SHOW_OUTRO_JINGLE)]:
        if generate_single(name, config, force):
            success += 1
        time.sleep(30)  # Rate limit pause
    return success


def generate_character_jingles(character: str | None = None,
                                force: bool = False) -> int:
    """Generate character jingles. Returns success count."""
    success = 0

    chars = [character] if character else list(CHARACTER_INTRO_JINGLES.keys())

    for char in chars:
        # Intro jingle
        intro = CHARACTER_INTRO_JINGLES.get(char)
        if intro:
            if generate_single(f"{char}_intro", intro, force):
                success += 1
            time.sleep(30)

        # Outro jingle
        outro = CHARACTER_OUTRO_JINGLES.get(char)
        if outro:
            if generate_single(f"{char}_outro", outro, force):
                success += 1
            time.sleep(30)

    return success


# ── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Before Bed jingles")
    parser.add_argument("--all", action="store_true",
                        help="Generate all jingles (show + characters)")
    parser.add_argument("--show-only", action="store_true",
                        help="Generate show intro/outro jingles only")
    parser.add_argument("--character",
                        choices=list(CHARACTER_INTRO_JINGLES.keys()),
                        help="Generate jingles for a specific character")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files exist")
    args = parser.parse_args()

    if not args.all and not args.show_only and not args.character:
        parser.error("Specify --all, --show-only, or --character")

    if not os.getenv("REPLICATE_API_TOKEN"):
        print("ERROR: REPLICATE_API_TOKEN not set")
        sys.exit(1)

    total = 0
    success = 0

    if args.all or args.show_only:
        print("\n" + "=" * 60)
        print("Show Jingles")
        print("=" * 60)
        total += 2
        success += generate_show_jingles(args.force)

    if args.all or args.character:
        print("\n" + "=" * 60)
        print("Character Jingles")
        print("=" * 60)
        if args.character:
            total += 2
        else:
            total += 10
        success += generate_character_jingles(args.character, args.force)

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{total} jingles generated")


if __name__ == "__main__":
    main()
