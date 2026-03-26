#!/usr/bin/env python3
"""Mix narration chunks + base track + stings into final funny short audio.

Two-layer system:
  Layer 3 (top):    Voice chunks — multi-character dialogue           0 dB
  Layer 2 (middle): Stings — reactive comedy hits at scripted spots  -5 dB
  Layer 1 (bottom): Base track — continuous, unique per short       -12 dB

Builds sequentially: the current position IS the timestamp.
No pre-calculation of timestamps needed.

Usage:
    python3 scripts/mix_funny_short.py --short-id crocodile-rock-001-a1b2
    python3 scripts/mix_funny_short.py --all
    python3 scripts/mix_funny_short.py --all --force
"""

import argparse
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydub import AudioSegment

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
CHUNKS_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-shorts"
MUSIC_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-music"
STINGS_DIR = MUSIC_DIR / "stings"
BASE_TRACKS_DIR = MUSIC_DIR / "base-tracks"

# ── Sting File Mapping ────────────────────────────────────────────────

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

# Pre-measured sting durations (ms). Used for gap calculation.
# If a sting file exists, its actual duration is used instead.
STING_DURATIONS = {
    "buildup_short":     2000,
    "buildup_long":      4000,
    "tiny":              500,
    "medium_hit":        800,
    "big_crash":         1500,
    "silence":           500,
    "deflation":         2000,
    "victory":           1000,
    "splat":             500,
    "boing":             500,
    "whoosh":            500,
    "tiptoe":            2000,
    "run":               2000,
    "slide_whistle":     1500,
    "villain_entrance":  1500,
    "villain_fail":      2500,
    "villain_dramatic":  2000,
    "witch_ominous":     1500,
    "witch_reveal":      1000,
    "witch_dramatic":    2000,
    "mouse_squeak":      300,
    "mouse_panic":       1500,
    "mouse_surprise":    800,
    "sweet_eyeroll":     500,
    "sweet_pause":       2000,
    "musical_flourish":  1000,
    "musical_detuned":   1000,
}

STING_BUFFER_MS = 200  # breathing room after sting ends

# ── Base Track Styles ─────────────────────────────────────────────────

COMEDY_BASE_MAP = {
    "physical_escalation":  "bouncy",
    "villain_fails":        "sneaky",
    "ominous_mundane":      "mysterious",
    "sarcastic_commentary": "gentle_absurd",
    "sound_effect_comedy":  "bouncy",
    "sound_effect":         "bouncy",
    "misunderstanding":     "gentle_absurd",
    "funny_poem":           "whimsical",
}

CHARACTER_BASE_FALLBACK = {
    "MOUSE":   "bouncy",
    "CROC":    "sneaky",
    "WITCH":   "mysterious",
    "SWEET":   "gentle_absurd",
    "MUSICAL": "whimsical",
}

# ── Dialogue Gap Rules ────────────────────────────────────────────────

DIALOGUE_GAP_RULES = {
    "question_to_answer":  150,
    "same_character":      200,
    "character_switch":    350,
    "before_punchline":    600,
    "after_punchline":     400,
}

# Delivery-tag-specific gaps (on top of dialogue rules)
DELIVERY_GAP_AFTER = {
    "stunned":      600,
    "devastating":  550,
    "calm gotcha":  500,
    "revealing":    500,
    "building":     200,
    "panicked":     150,
    "scrambling":   150,
    "excited":      200,
}

DELIVERY_GAP_BEFORE = {
    "caught off guard": 400,
    "stunned":          500,
}

# ── Mix Levels ────────────────────────────────────────────────────────

BASE_TRACK_VOLUME = -12
BASE_TRACK_DUCK_VOLUME = -20
BASE_TRACK_FADE_IN_MS = 500
BASE_TRACK_FADE_OUT_MS = 2000
BASE_TRACK_DUCK_RECOVERY_MS = 300

STING_VOLUME = -5
VOICE_VOLUME = 0


# ── Helper Functions ──────────────────────────────────────────────────

def load_sting(sting_type: str) -> AudioSegment | None:
    """Load a sting audio file. Returns None if not found."""
    filename = COMEDY_STINGS.get(sting_type)
    if not filename:
        return None
    path = STINGS_DIR / filename
    if not path.exists():
        return None
    try:
        return AudioSegment.from_file(str(path))
    except Exception:
        return None


def get_sting_duration_ms(sting_type: str) -> int:
    """Get the duration of a sting in ms."""
    sting = load_sting(sting_type)
    if sting:
        return len(sting)
    return STING_DURATIONS.get(sting_type, 500)


def get_base_track_style(comedy_type: str, primary_character: str) -> str:
    """Determine base track style for a short."""
    if comedy_type in COMEDY_BASE_MAP:
        return COMEDY_BASE_MAP[comedy_type]
    return CHARACTER_BASE_FALLBACK.get(primary_character, "bouncy")


def find_base_track(style: str, short_id: str) -> Path | None:
    """Find a base track file from the pool."""
    if not BASE_TRACKS_DIR.exists():
        return None

    candidates = sorted(BASE_TRACKS_DIR.glob(f"base_{style}_*.wav"))
    if not candidates:
        candidates = sorted(BASE_TRACKS_DIR.glob(f"base_{style}_*.mp3"))
    if not candidates:
        return None

    rng = random.Random(hash(short_id))
    return rng.choice(candidates)


def get_dialogue_gap(prev_sent: dict | None, curr_sent: dict) -> int:
    """Calculate the base dialogue gap between two sentences."""
    if prev_sent is None:
        return 0

    gap = DIALOGUE_GAP_RULES["character_switch"]

    if prev_sent["character"] == curr_sent["character"]:
        gap = DIALOGUE_GAP_RULES["same_character"]

    if prev_sent.get("text", "").strip().endswith("?"):
        gap = min(gap, DIALOGUE_GAP_RULES["question_to_answer"])

    if curr_sent.get("is_punchline"):
        gap = max(gap, DIALOGUE_GAP_RULES["before_punchline"])

    if prev_sent.get("is_punchline"):
        gap = max(gap, DIALOGUE_GAP_RULES["after_punchline"])

    for tag in prev_sent.get("delivery_tags", []):
        if tag in DELIVERY_GAP_AFTER:
            gap = max(gap, DELIVERY_GAP_AFTER[tag])

    for tag in curr_sent.get("delivery_tags", []):
        if tag in DELIVERY_GAP_BEFORE:
            gap = max(gap, DELIVERY_GAP_BEFORE[tag])

    return gap


def get_sentence_gap(prev_sent: dict | None, curr_sent: dict) -> int:
    """Calculate total gap between sentences, including sting duration.

    If the previous sentence had a sting, the gap must be at least
    sting_duration + buffer, so the sting plays fully before the next
    character speaks.
    """
    base_gap = get_dialogue_gap(prev_sent, curr_sent)

    if prev_sent and prev_sent.get("sting"):
        sting_ms = get_sting_duration_ms(prev_sent["sting"])
        sting_gap = sting_ms + STING_BUFFER_MS
        return max(sting_gap, base_gap)

    return base_gap


# ── Core Mix Function ─────────────────────────────────────────────────

def mix_short(short: dict, chunk_dir: Path) -> bool:
    """Mix voice chunks + base track + stings into final audio.

    Builds sequentially — the current position IS the timestamp.
    """
    short_id = short["id"]
    manifest_path = chunk_dir / "manifest.json"

    if not manifest_path.exists():
        print(f"  No manifest found at {manifest_path}")
        print(f"  Run generate_funny_audio.py first")
        return False

    with open(manifest_path) as f:
        manifest = json.load(f)

    sentences = manifest["sentences"]
    if not sentences:
        print(f"  Empty manifest for {short_id}")
        return False

    # Load all voice chunks
    voice_chunks = []
    for sent in sentences:
        chunk_path = chunk_dir / sent["chunk_file"]
        if not chunk_path.exists():
            print(f"  Missing chunk: {chunk_path}")
            return False
        try:
            chunk = AudioSegment.from_mp3(str(chunk_path))
        except Exception:
            chunk = AudioSegment.from_file(str(chunk_path))
        voice_chunks.append(chunk)

    # ── Step 1: Build the voice + gap timeline ────────────────────────
    # Sequential build: cursor advances through gaps and chunks.

    cursor = 0  # current position in ms
    voice_events = []  # (start_ms, chunk_index)
    sting_events = []  # (start_ms, sting_type)

    for i, (sent, chunk) in enumerate(zip(sentences, voice_chunks)):
        if i > 0:
            gap = get_sentence_gap(sentences[i - 1], sent)
            cursor += gap

        voice_start = cursor
        voice_events.append((voice_start, i))

        voice_end = cursor + len(chunk)

        # Sting fires at end of voice chunk
        if sent.get("sting"):
            sting_events.append((voice_end, sent["sting"]))

        cursor = voice_end

    total_duration = cursor + 500  # 500ms padding at end

    print(f"  Timeline: {total_duration / 1000:.1f}s, "
          f"{len(voice_events)} voice chunks, {len(sting_events)} stings")

    # ── Step 2: Build the base track layer ────────────────────────────

    comedy_type = short.get("comedy_type", "")
    chars = [s["character"] for s in sentences]
    from collections import Counter
    primary_char = Counter(chars).most_common(1)[0][0] if chars else "MOUSE"
    style = get_base_track_style(comedy_type, primary_char)

    base_track_path = find_base_track(style, short_id)
    base_track = None

    if base_track_path:
        print(f"  Base track: {base_track_path.name} (style: {style})")
        base_track = AudioSegment.from_file(str(base_track_path))

        # Trim or loop to match total duration
        if len(base_track) < total_duration:
            loops_needed = (total_duration // len(base_track)) + 1
            base_track = base_track * loops_needed
        base_track = base_track[:total_duration]

        # Apply volume + fades
        base_track = base_track + BASE_TRACK_VOLUME
        base_track = base_track.fade_in(BASE_TRACK_FADE_IN_MS)
        base_track = base_track.fade_out(BASE_TRACK_FADE_OUT_MS)

        # Duck base track for each sting
        for sting_start, sting_type in sting_events:
            sting_dur = get_sting_duration_ms(sting_type)
            duck_duration = sting_dur + BASE_TRACK_DUCK_RECOVERY_MS

            duck_start = max(0, sting_start)
            duck_end = min(len(base_track), sting_start + duck_duration)

            if duck_start < duck_end:
                before = base_track[:duck_start]
                ducked = base_track[duck_start:duck_end] + (BASE_TRACK_DUCK_VOLUME - BASE_TRACK_VOLUME)
                after = base_track[duck_end:]

                if len(ducked) > BASE_TRACK_DUCK_RECOVERY_MS:
                    recovery_start = len(ducked) - BASE_TRACK_DUCK_RECOVERY_MS
                    ducked = ducked[:recovery_start] + ducked[recovery_start:].fade_in(BASE_TRACK_DUCK_RECOVERY_MS)

                base_track = before + ducked + after
    else:
        print(f"  No base track found for style '{style}' — trying legacy loops")
        base_track = _try_legacy_loop(primary_char, total_duration)

    # ── Step 3: Build the final mix ───────────────────────────────────

    if base_track:
        mixed = base_track
    else:
        mixed = AudioSegment.silent(duration=total_duration)

    # Overlay voice chunks
    for voice_start, chunk_idx in voice_events:
        chunk = voice_chunks[chunk_idx] + VOICE_VOLUME
        mixed = mixed.overlay(chunk, position=voice_start)

    # Overlay stings
    stings_placed = 0
    for sting_start, sting_type in sting_events:
        sting_audio = load_sting(sting_type)
        if sting_audio:
            sting_audio = sting_audio + STING_VOLUME
            if sting_start + len(sting_audio) > len(mixed):
                extra = sting_start + len(sting_audio) - len(mixed) + 100
                mixed += AudioSegment.silent(duration=extra)
            mixed = mixed.overlay(sting_audio, position=sting_start)
            stings_placed += 1

    print(f"  Placed {stings_placed}/{len(sting_events)} stings")

    # ── Step 4: Export ────────────────────────────────────────────────

    out_file = f"{short_id}.mp3"
    out_path = CHUNKS_DIR / out_file
    mixed.export(str(out_path), format="mp3", bitrate="128k")

    duration_sec = int(len(mixed) / 1000)
    print(f"  Output: {out_path} ({duration_sec}s)")

    short["audio_file"] = out_file
    short["duration_seconds"] = duration_sec
    short["base_track_style"] = style

    return True


def _try_legacy_loop(primary_char: str, total_duration: int) -> AudioSegment | None:
    """Fall back to old character loop files if base tracks don't exist yet."""
    from app.services.tts.voice_service import CHARACTER_LOOP_MAP

    LOOPS_DIR = MUSIC_DIR / "loops"
    if not LOOPS_DIR.exists():
        return None

    loop_name = CHARACTER_LOOP_MAP.get(primary_char)
    if not loop_name:
        return None

    for ext in ["wav", "mp3"]:
        for v in range(1, 4):
            path = LOOPS_DIR / f"{loop_name}_v{v}.{ext}"
            if path.exists():
                print(f"  Legacy loop fallback: {path.name} (for {primary_char})")
                loop = AudioSegment.from_file(str(path))
                loop = loop + BASE_TRACK_VOLUME

                loops_needed = (total_duration // len(loop)) + 1
                looped = loop * loops_needed
                looped = looped[:total_duration]
                looped = looped.fade_in(BASE_TRACK_FADE_IN_MS)
                looped = looped.fade_out(BASE_TRACK_FADE_OUT_MS)
                return looped

    return None


# ── CLI ───────────────────────────────────────────────────────────────

def process_short(short_path: Path, force: bool = False) -> bool:
    """Process a single funny short for mixing."""
    with open(short_path) as f:
        short = json.load(f)

    short_id = short.get("id", short_path.stem)
    short.setdefault("id", short_id)

    chunk_dir = CHUNKS_DIR / short_id

    if not chunk_dir.exists():
        print(f"  No chunks directory — run generate_funny_audio.py first")
        return False

    if not force:
        out_path = CHUNKS_DIR / f"{short_id}.mp3"
        if out_path.exists() and short.get("audio_file") == f"{short_id}.mp3":
            print(f"  Already mixed: {out_path}, skipping")
            return True

    result = mix_short(short, chunk_dir)

    if result:
        with open(short_path, "w") as f:
            json.dump(short, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Mix funny short audio: voice chunks + base track + stings"
    )
    parser.add_argument("--short-id", help="Mix a specific short")
    parser.add_argument("--all", action="store_true", help="Mix all shorts with chunks")
    parser.add_argument("--force", action="store_true", help="Remix even if output exists")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            print(f"ERROR: Short not found: {path}")
            sys.exit(1)
        print(f"Mixing: {args.short_id}")
        ok = process_short(path, args.force)
        sys.exit(0 if ok else 1)

    if args.all:
        shorts = sorted(DATA_DIR.glob("*.json"))
        print(f"Found {len(shorts)} funny shorts")

        success = 0
        for path in shorts:
            print(f"\n{'='*60}")
            print(f"Mixing: {path.stem}")
            if process_short(path, args.force):
                success += 1

        print(f"\n{'='*60}")
        print(f"Done: {success}/{len(shorts)} mixed")


if __name__ == "__main__":
    main()
