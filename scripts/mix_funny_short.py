#!/usr/bin/env python3
"""Mix narration + character loops + comedy stings for funny shorts.

This script takes the raw narration audio (from generate_funny_audio.py)
and mixes it with:
1. Character-matched background music loops
2. Comedy stings placed at script-specified positions

The output is a single mixed MP3 — the client plays it as-is.

Usage:
    python3 scripts/mix_funny_short.py --short-id crocodile-rock-001-a1b2
    python3 scripts/mix_funny_short.py --all
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydub import AudioSegment

from app.services.tts.voice_service import CHARACTER_LOOP_MAP

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
AUDIO_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-shorts"
MUSIC_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-music"
STINGS_DIR = MUSIC_DIR / "stings"
LOOPS_DIR = MUSIC_DIR / "loops"

# ── Comedy Sting Files ──────────────────────────────────────────

COMEDY_STINGS = {
    # Universal
    "buildup_short":     "comedy_buildup_2bar.wav",
    "buildup_long":      "comedy_buildup_4bar.wav",
    "tiny":              "comedy_tiny_squeak.wav",
    "medium_hit":        "comedy_drum_hit.wav",
    "big_crash":         "comedy_full_crash.wav",
    "silence":           "comedy_record_scratch.wav",
    "deflation":         "comedy_sad_trombone.wav",
    "victory":           "comedy_tada.wav",
    "splat":             "comedy_splat.wav",
    "boing":             "comedy_boing.wav",
    "whoosh":            "comedy_whoosh.wav",
    "tiptoe":            "comedy_tiptoe.wav",
    "run":               "comedy_running.wav",
    "slide_whistle":     "comedy_slide_whistle.wav",
    # Villain / Croc
    "villain_entrance":  "comedy_villain_brass_sting.wav",
    "villain_fail":      "comedy_villain_deflate_tuba.wav",
    "villain_dramatic":  "comedy_villain_thunder.wav",
    # Witch
    "witch_ominous":     "comedy_witch_celesta_trill.wav",
    "witch_reveal":      "comedy_witch_gong_tiny.wav",
    "witch_dramatic":    "comedy_witch_organ_chord.wav",
    # Mouse
    "mouse_squeak":      "comedy_mouse_squeak.wav",
    "mouse_panic":       "comedy_mouse_scramble.wav",
    "mouse_surprise":    "comedy_mouse_gasp_boing.wav",
    # Sweet
    "sweet_eyeroll":     "comedy_sweet_single_note.wav",
    "sweet_pause":       "comedy_sweet_crickets.wav",
    # Musical
    "musical_flourish":  "comedy_musical_harp_run.wav",
    "musical_detuned":   "comedy_musical_detuned.wav",
}

# Character → loop name mapping
CHARACTER_LOOPS = {
    "bouncy_cartoon":   {"variants": 3},
    "villain_march":    {"variants": 3},
    "mysterious_creep": {"variants": 3},
    "sweet_innocence":  {"variants": 2},
    "poetic_bounce":    {"variants": 2},
    "chaos_ensemble":   {"variants": 2},
}

# Mixing levels (dB)
LOOP_VOLUME = -10
LOOP_DUCK_VOLUME = -18
STING_VOLUME = -5
LOOP_CROSSFADE_MS = 1500
LOOP_FADE_OUT_MS = 2000
STING_DUCK_EXTRA_MS = 300
MIN_SENTENCES_FOR_LOOP_SWITCH = 3


def get_loop_file(loop_name: str, variant: int = 0) -> Optional[Path]:
    """Get a loop audio file path."""
    max_v = CHARACTER_LOOPS.get(loop_name, {}).get("variants", 1)
    v = variant % max_v
    # Try common extensions
    for ext in ["wav", "mp3"]:
        path = LOOPS_DIR / f"{loop_name}_v{v+1}.{ext}"
        if path.exists():
            return path
    # Try without variant
    for ext in ["wav", "mp3"]:
        path = LOOPS_DIR / f"{loop_name}.{ext}"
        if path.exists():
            return path
    return None


def get_sting_file(sting_type: str) -> Optional[Path]:
    """Get a sting audio file path."""
    filename = COMEDY_STINGS.get(sting_type)
    if not filename:
        return None
    path = STINGS_DIR / filename
    if path.exists():
        return path
    return None


def parse_sting_positions(script: str, sentence_timestamps: list[float]) -> list[dict]:
    """Extract sting positions from script and map to audio timestamps."""
    stings = []
    sentence_idx = 0

    for line in script.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("[TITLE") or line.startswith("[AGE") or \
           line.startswith("[VOICES") or line.startswith("[COMEDY") or \
           line.startswith("[SETUP]") or line.startswith("[BEAT_") or \
           line.startswith("[BUTTON]") or line.startswith("[/"):
            continue

        char_match = re.match(r"^\[(\w+)\]\s*(.+)", line)
        if not char_match:
            continue

        character = char_match.group(1)
        if character in ("TITLE", "AGE", "VOICES", "COMEDY_TYPE"):
            continue

        rest = char_match.group(2)
        sting_match = re.search(r"\[STING:\s*(\w+)\]", rest)

        if sting_match and sentence_idx < len(sentence_timestamps):
            stings.append({
                "type": sting_match.group(1),
                "timestamp": sentence_timestamps[sentence_idx],
            })

        sentence_idx += 1

    return stings


def get_sentence_timestamps(narration: AudioSegment, script: str, gap_ms: int = 300) -> list[float]:
    """Estimate when each sentence ends based on equal division + gaps.

    This is a rough estimate. For precise placement, we'd need the
    individual sentence durations from generate_funny_audio.py.
    """
    # Count sentences
    count = 0
    for line in script.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        char_match = re.match(r"^\[(\w+)\]\s*(.+)", line)
        if char_match:
            character = char_match.group(1)
            if character not in ("TITLE", "AGE", "VOICES", "COMEDY_TYPE"):
                count += 1

    if count == 0:
        return []

    total_ms = len(narration)
    # Each sentence takes roughly equal time
    per_sentence = total_ms / count

    timestamps = []
    for i in range(count):
        # End of each sentence
        end_ms = (i + 1) * per_sentence
        timestamps.append(end_ms / 1000.0)

    return timestamps


def mix_short(short: dict) -> bool:
    """Mix narration with loops and stings for a funny short."""
    short_id = short["id"]
    audio_file = short.get("audio_file")
    if not audio_file:
        print(f"  No audio file for {short_id}")
        return False

    narration_path = AUDIO_DIR / audio_file
    if not narration_path.exists():
        print(f"  Narration not found: {narration_path}")
        return False

    script = short.get("script", "")
    if not script:
        print(f"  No script for {short_id}")
        return False

    print(f"  Loading narration: {narration_path}")
    narration = AudioSegment.from_mp3(str(narration_path))
    total_ms = len(narration)

    # Check if loops/stings directory exists
    if not LOOPS_DIR.exists() and not STINGS_DIR.exists():
        print(f"  Music directories not found ({LOOPS_DIR}, {STINGS_DIR})")
        print(f"  Skipping mix — narration-only output is already in place")
        return True

    # Start building the mixed timeline
    mixed = narration

    # 1. Add character loop underneath
    # Determine primary character (most sentences)
    chars = re.findall(r"^\[(\w+)\]", script, re.MULTILINE)
    meta_tags = {"TITLE", "AGE", "VOICES", "COMEDY_TYPE", "SETUP", "BEAT_1",
                 "BEAT_2", "BEAT_3", "BUTTON", "PUNCHLINE", "STING"}
    chars = [c for c in chars if c not in meta_tags and not c.startswith("/")]

    if chars:
        from collections import Counter
        char_counts = Counter(chars)
        primary_char = char_counts.most_common(1)[0][0]
        loop_name = CHARACTER_LOOP_MAP.get(primary_char)

        if loop_name:
            import random
            loop_path = get_loop_file(loop_name, random.randint(0, 2))
            if loop_path:
                print(f"  Adding loop: {loop_name} (for {primary_char})")
                loop = AudioSegment.from_file(str(loop_path))
                loop = loop + LOOP_VOLUME  # Set volume

                # Loop it to cover entire narration
                loops_needed = (total_ms // len(loop)) + 1
                looped = loop * loops_needed
                looped = looped[:total_ms]

                # Fade out at end
                looped = looped.fade_out(LOOP_FADE_OUT_MS)

                # Overlay
                mixed = looped.overlay(narration)

    # 2. Place stings
    timestamps = get_sentence_timestamps(narration, script)
    sting_positions = parse_sting_positions(script, timestamps)

    stings_placed = 0
    for sp in sting_positions:
        sting_path = get_sting_file(sp["type"])
        if not sting_path:
            continue

        sting_audio = AudioSegment.from_file(str(sting_path))
        sting_audio = sting_audio + STING_VOLUME

        position_ms = int(sp["timestamp"] * 1000)
        if position_ms >= total_ms:
            position_ms = total_ms - len(sting_audio) - 100

        if position_ms >= 0:
            mixed = mixed.overlay(sting_audio, position=max(0, position_ms))
            stings_placed += 1

    print(f"  Placed {stings_placed} stings")

    # Export
    mixed_file = f"{short_id}_mixed.mp3"
    mixed_path = AUDIO_DIR / mixed_file
    mixed.export(str(mixed_path), format="mp3", bitrate="128k")

    # Update the short to point to mixed version
    short["audio_file"] = mixed_file
    duration_sec = int(len(mixed) / 1000)
    short["duration_seconds"] = duration_sec

    print(f"  Mixed output: {mixed_path} ({duration_sec}s)")
    return True


def process_short(short_path: Path) -> bool:
    """Process a single funny short for mixing."""
    with open(short_path) as f:
        short = json.load(f)

    short.setdefault("id", short_path.stem)

    if not short.get("audio_file"):
        print(f"  No audio generated yet — run generate_funny_audio.py first")
        return False

    result = mix_short(short)

    if result:
        with open(short_path, "w") as f:
            json.dump(short, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Mix funny short audio with loops and stings")
    parser.add_argument("--short-id", help="Mix a specific short")
    parser.add_argument("--all", action="store_true", help="Mix all shorts with audio")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            print(f"ERROR: Short not found: {path}")
            sys.exit(1)
        print(f"Mixing: {args.short_id}")
        ok = process_short(path)
        sys.exit(0 if ok else 1)

    if args.all:
        shorts = sorted(DATA_DIR.glob("*.json"))
        print(f"Found {len(shorts)} funny shorts")

        success = 0
        for path in shorts:
            print(f"\n{'='*60}")
            print(f"Mixing: {path.stem}")
            if process_short(path):
                success += 1

        print(f"\n{'='*60}")
        print(f"Done: {success}/{len(shorts)} mixed")


if __name__ == "__main__":
    main()
