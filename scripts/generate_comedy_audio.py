#!/usr/bin/env python3
"""Generate comedy loops and stings for funny shorts via Replicate MusicGen.

Creates:
  - Character background loops (6 types × 2-3 variants each = 15 files)
  - Comedy stings (28 sound effects, ~1-4 seconds each)

Output:
  public/audio/funny-music/loops/*.wav
  public/audio/funny-music/stings/*.wav

Usage:
    python3 scripts/generate_comedy_audio.py --stings
    python3 scripts/generate_comedy_audio.py --loops
    python3 scripts/generate_comedy_audio.py --all
    python3 scripts/generate_comedy_audio.py --all --force
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import replicate
except ImportError:
    print("ERROR: replicate required — pip install replicate")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOOPS_DIR = PROJECT_ROOT / "public" / "audio" / "funny-music" / "loops"
STINGS_DIR = PROJECT_ROOT / "public" / "audio" / "funny-music" / "stings"

# ── Comedy Stings ─────────────────────────────────────────────
# Short 1-4 second sound effects for comedic timing

STING_PROMPTS = {
    # Universal
    "comedy_buildup_2bar.wav": {
        "prompt": "Short comedic drum buildup, snare roll crescendo, cartoon style, 2 bars, comedy timing, bright and punchy",
        "duration": 3,
    },
    "comedy_buildup_4bar.wav": {
        "prompt": "Longer comedic drum buildup with timpani roll and cymbal crescendo, cartoon comedy, building tension, 4 bars",
        "duration": 5,
    },
    "comedy_tiny_squeak.wav": {
        "prompt": "Single tiny cartoon squeak sound effect, high pitched, rubber toy squeak, comedic, very short",
        "duration": 2,
    },
    "comedy_drum_hit.wav": {
        "prompt": "Single comedic bass drum hit with cymbal crash, ba-dum-tss rimshot, comedy punchline drum",
        "duration": 2,
    },
    "comedy_full_crash.wav": {
        "prompt": "Big cartoon crash sound with pots and pans clattering, slapstick comedy, chaotic percussion hit",
        "duration": 3,
    },
    "comedy_record_scratch.wav": {
        "prompt": "Vinyl record scratch stop, dramatic pause sound effect, comedy beat drop, awkward silence",
        "duration": 2,
    },
    "comedy_sad_trombone.wav": {
        "prompt": "Sad trombone wah wah wah descending notes, comedy failure sound, cartoon deflation",
        "duration": 3,
    },
    "comedy_tada.wav": {
        "prompt": "Bright triumphant fanfare ta-da, brass celebration short sting, cartoon victory sound",
        "duration": 2,
    },
    "comedy_splat.wav": {
        "prompt": "Wet cartoon splat sound effect, pie in the face, slapstick comedy impact",
        "duration": 2,
    },
    "comedy_boing.wav": {
        "prompt": "Cartoon spring boing bounce sound, rubber band twang, comedic bouncy sound effect",
        "duration": 2,
    },
    "comedy_whoosh.wav": {
        "prompt": "Fast cartoon whoosh swoosh sound, quick movement through air, comic speed sound",
        "duration": 2,
    },
    "comedy_tiptoe.wav": {
        "prompt": "Quiet sneaky tiptoe pizzicato strings, cartoon creeping music, stealthy comedic",
        "duration": 3,
    },
    "comedy_running.wav": {
        "prompt": "Fast cartoon running music, accelerating xylophone notes going up, comedic chase",
        "duration": 3,
    },
    "comedy_slide_whistle.wav": {
        "prompt": "Slide whistle going up then down, cartoon comedy sound effect, classic slapstick",
        "duration": 2,
    },
    # Villain / Croc
    "comedy_villain_brass_sting.wav": {
        "prompt": "Dramatic villain entrance brass fanfare, ominous tuba and trombone, over-the-top evil, cartoon villain theme",
        "duration": 3,
    },
    "comedy_villain_deflate_tuba.wav": {
        "prompt": "Tuba deflating sad descending notes, villain failure sound, comedic brass fart, embarrassing",
        "duration": 3,
    },
    "comedy_villain_thunder.wav": {
        "prompt": "Dramatic thunder crash with organ chord, over-the-top villain dramatic moment, cartoon evil sting",
        "duration": 3,
    },
    # Witch
    "comedy_witch_celesta_trill.wav": {
        "prompt": "Spooky celesta trill ascending, magical mysterious ominous tinkle, witch entrance, fairy tale dark",
        "duration": 3,
    },
    "comedy_witch_gong_tiny.wav": {
        "prompt": "Small gong hit with shimmering reverb, mystical reveal sound, witch magic, ethereal tiny",
        "duration": 2,
    },
    "comedy_witch_organ_chord.wav": {
        "prompt": "Dramatic pipe organ minor chord, gothic horror comedy, witch dramatic moment, haunted house",
        "duration": 3,
    },
    # Mouse
    "comedy_mouse_squeak.wav": {
        "prompt": "Cute high-pitched mouse squeak, tiny cartoon animal sound, adorable panic squeak",
        "duration": 2,
    },
    "comedy_mouse_scramble.wav": {
        "prompt": "Fast scrambling xylophone notes, tiny feet running in panic, cartoon mouse chase, frantic",
        "duration": 3,
    },
    "comedy_mouse_gasp_boing.wav": {
        "prompt": "High pitched gasp followed by spring boing, cartoon surprise reaction, shocked tiny character",
        "duration": 2,
    },
    # Sweet
    "comedy_sweet_single_note.wav": {
        "prompt": "Single flat unamused piano note, deadpan comedy beat, unimpressed single key press, dry",
        "duration": 2,
    },
    "comedy_sweet_crickets.wav": {
        "prompt": "Awkward crickets chirping silence, comedy dead air, uncomfortable pause, nothing happening",
        "duration": 3,
    },
    # Musical
    "comedy_musical_harp_run.wav": {
        "prompt": "Quick harp glissando run ascending, magical flourish, comedy fairy tale transition, sparkling",
        "duration": 2,
    },
    "comedy_musical_detuned.wav": {
        "prompt": "Detuned out-of-tune piano notes, comedy wrong notes, musical fail, hilariously bad playing",
        "duration": 3,
    },
}

# ── Character Background Loops ────────────────────────────────
# 8-15 second loops that play under narration

LOOP_PROMPTS = {
    "bouncy_cartoon": {
        "prompt": "Bouncy playful cartoon background music, pizzicato strings and xylophone, upbeat silly comedic, children's show, seamless loop",
        "variants": 3,
        "duration": 15,
    },
    "villain_march": {
        "prompt": "Comedic villain march, tuba and bassoon pompous strutting music, over-the-top evil cartoon, funny dramatic, seamless loop",
        "variants": 3,
        "duration": 15,
    },
    "mysterious_creep": {
        "prompt": "Spooky mysterious creepy music, celesta and low strings, witch theme, dark fairy tale, cartoon haunted, comedic tension, seamless loop",
        "variants": 3,
        "duration": 15,
    },
    "sweet_innocence": {
        "prompt": "Innocent sweet gentle music, soft glockenspiel and light flute, understated deadpan comedy, minimal cute, seamless loop",
        "variants": 2,
        "duration": 15,
    },
    "poetic_bounce": {
        "prompt": "Rhythmic bouncy poetic music, light percussion and plucked strings, spoken word accompaniment, whimsical comedy, seamless loop",
        "variants": 2,
        "duration": 15,
    },
    "chaos_ensemble": {
        "prompt": "Chaotic ensemble comedy music, multiple instruments clashing playfully, cartoon madness, funny orchestral chaos, seamless loop",
        "variants": 2,
        "duration": 15,
    },
}


def generate_audio_replicate(prompt: str, duration: int) -> bytes | None:
    """Generate audio via Replicate MusicGen."""
    try:
        output = replicate.run(
            "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedbbe",
            input={
                "model_version": "stereo-melody-large",
                "prompt": prompt,
                "duration": duration,
                "output_format": "wav",
                "normalization_strategy": "peak",
            },
        )
        # output is a FileOutput URL
        if hasattr(output, 'read'):
            audio_bytes = output.read()
        else:
            # It's a URL string
            import httpx
            resp = httpx.get(str(output), timeout=60)
            resp.raise_for_status()
            audio_bytes = resp.content

        if len(audio_bytes) > 1000:
            return audio_bytes
        print(f"    Audio too small: {len(audio_bytes)} bytes")
        return None
    except Exception as e:
        print(f"    Replicate error: {e}")
        return None


def trim_audio(input_path: Path, output_path: Path, start: float = 0.5,
               fade_in: float = 0.3, fade_out: float = 0.5, max_duration: float = None):
    """Trim and fade audio using ffmpeg."""
    filters = [f"atrim=start={start}"]
    if max_duration:
        filters.append(f"atrim=end={start + max_duration}")
    filters.append(f"afade=t=in:st=0:d={fade_in}")
    if max_duration:
        filters.append(f"afade=t=out:st={max_duration - fade_out}:d={fade_out}")

    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", ",".join(filters),
            str(output_path),
        ], capture_output=True, timeout=30)
        return output_path.exists() and output_path.stat().st_size > 1000
    except Exception as e:
        print(f"    ffmpeg error: {e}")
        return False


def generate_stings(force: bool = False):
    """Generate all comedy stings."""
    STINGS_DIR.mkdir(parents=True, exist_ok=True)
    total = len(STING_PROMPTS)
    success = 0
    skipped = 0

    print(f"\n=== Generating {total} comedy stings ===\n")

    for filename, config in STING_PROMPTS.items():
        out_path = STINGS_DIR / filename

        if out_path.exists() and out_path.stat().st_size > 1000 and not force:
            print(f"  SKIP: {filename} (exists)")
            skipped += 1
            continue

        print(f"  Generating: {filename}")
        print(f"    Prompt: {config['prompt'][:80]}...")

        audio_bytes = generate_audio_replicate(config["prompt"], config["duration"])
        if not audio_bytes:
            print(f"    FAILED: {filename}")
            continue

        # Write raw, then trim
        tmp_path = STINGS_DIR / f"_tmp_{filename}"
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)

        # Trim: skip first 0.5s, apply fades
        ok = trim_audio(tmp_path, out_path,
                        start=0.3, fade_in=0.1, fade_out=0.3,
                        max_duration=config["duration"])
        tmp_path.unlink(missing_ok=True)

        if ok:
            size_kb = out_path.stat().st_size // 1024
            print(f"    OK: {size_kb}KB")
            success += 1
        else:
            # Fallback: use raw file
            with open(out_path, "wb") as f:
                f.write(audio_bytes)
            success += 1
            print(f"    OK (raw, no trim)")

        # Rate limit
        time.sleep(1)

    print(f"\nStings: {success} generated, {skipped} skipped, "
          f"{total - success - skipped} failed")


def generate_loops(force: bool = False):
    """Generate all character background loops."""
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
    total = sum(cfg["variants"] for cfg in LOOP_PROMPTS.values())
    success = 0
    skipped = 0

    print(f"\n=== Generating {total} character loops ===\n")

    for loop_name, config in LOOP_PROMPTS.items():
        for v in range(config["variants"]):
            filename = f"{loop_name}_v{v+1}.wav"
            out_path = LOOPS_DIR / filename

            if out_path.exists() and out_path.stat().st_size > 1000 and not force:
                print(f"  SKIP: {filename} (exists)")
                skipped += 1
                continue

            # Vary the prompt slightly per variant
            variant_suffix = ["", ", slightly different rhythm", ", alternate melody"][v % 3]
            prompt = config["prompt"] + variant_suffix

            print(f"  Generating: {filename}")
            print(f"    Prompt: {prompt[:80]}...")

            audio_bytes = generate_audio_replicate(prompt, config["duration"])
            if not audio_bytes:
                print(f"    FAILED: {filename}")
                continue

            # Write raw, then trim
            tmp_path = LOOPS_DIR / f"_tmp_{filename}"
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)

            # Trim loops: skip first 1s, fade to make loopable
            ok = trim_audio(tmp_path, out_path,
                            start=1.0, fade_in=0.5, fade_out=1.0,
                            max_duration=config["duration"] - 1)
            tmp_path.unlink(missing_ok=True)

            if ok:
                size_kb = out_path.stat().st_size // 1024
                print(f"    OK: {size_kb}KB")
                success += 1
            else:
                with open(out_path, "wb") as f:
                    f.write(audio_bytes)
                success += 1
                print(f"    OK (raw, no trim)")

            time.sleep(1)

    print(f"\nLoops: {success} generated, {skipped} skipped, "
          f"{total - success - skipped} failed")


def main():
    parser = argparse.ArgumentParser(description="Generate comedy loops and stings via Replicate")
    parser.add_argument("--stings", action="store_true", help="Generate comedy stings")
    parser.add_argument("--loops", action="store_true", help="Generate character loops")
    parser.add_argument("--all", action="store_true", help="Generate both loops and stings")
    parser.add_argument("--force", action="store_true", help="Regenerate even if files exist")
    args = parser.parse_args()

    if not args.stings and not args.loops and not args.all:
        parser.error("Specify --stings, --loops, or --all")

    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        print("ERROR: REPLICATE_API_TOKEN not set")
        sys.exit(1)

    if args.stings or args.all:
        generate_stings(args.force)

    if args.loops or args.all:
        generate_loops(args.force)


if __name__ == "__main__":
    main()
