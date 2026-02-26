"""Stitch atmospheric ambient music onto existing audio files for a story.

Generates ethereal, wordless vocal ambient music (Sigur Rós / Ólafur Arnalds mood)
via ACE-Step and stitches it onto pre-existing narration audio files.

Usage:
    python3 scripts/stitch_lullaby.py --story-id gen-3b66368b6682
    python3 scripts/stitch_lullaby.py --story-id gen-3b66368b6682 --backup
    python3 scripts/stitch_lullaby.py --story-id gen-3b66368b6682 --duration 180
"""

import argparse
import io
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydub import AudioSegment

# ── Setup ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SONGGEN_URL = os.getenv("SONGGEN_URL", "")
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Voice → Gender mapping ─────────────────────────────────────────────

VOICE_GENDER = {
    "female_1": "female",
    "female_2": "female",
    "female_3": "female",
    "asmr": "female",
    "male_1": "male",
    "male_2": "male",
    "male_3": "male",
}

# ── Atmospheric ambient descriptions (Sigur Rós / Ólafur Arnalds mood) ──

AMBIENT_DESCRIPTIONS = {
    "female": (
        "atmospheric ambient, ethereal female vocals, wordless, "
        "deep cello, slow sustained strings, reverberating piano, "
        "underwater texture, post-rock, Sigur Ros mood, "
        "very slow tempo 45 bpm, cinematic, vast, dreamy, "
        "ocean ambient, fading to silence"
    ),
    "male": (
        "atmospheric ambient, ethereal male vocals, wordless, "
        "deep cello drone, distant piano, underwater reverb, "
        "post-rock, Olafur Arnalds mood, very slow tempo 40 bpm, "
        "cinematic, vast, intimate, ocean ambient, fading to silence"
    ),
}

# ── Non-lexical vocables (Hopelandic-style) ────────────────────────────

AMBIENT_LYRICS = """[verse]
Ooh ooh ooh, ooh ooh ooh ooh,
Aah aah aah, aah aah aah.
Ooh ooh ooh, ooh ooh ooh ooh,
Mmm mmm mmm, mmm mmm mmm.

[chorus]
Ooh aah ooh, ooh aah ooh,
Mmm mmm mmm, mmm.

[verse]
Aah aah aah, aah aah aah,
Ooh ooh ooh, ooh ooh ooh ooh.
Aah aah aah, aah aah aah,
Mmm mmm mmm, mmm mmm mmm.

[chorus]
Ooh aah ooh, ooh aah ooh,
Mmm mmm mmm, mmm.

[verse]
Mmm mmm mmm, mmm mmm mmm,
Ooh ooh ooh, ooh ooh.
Mmm mmm mmm, mmm mmm mmm,
Aah aah aah, aah.

[chorus]
Ooh aah ooh, ooh aah ooh,
Mmm mmm mmm, mmm.
""".strip()


# ── Helpers ────────────────────────────────────────────────────────────

def audio_from_bytes(audio_bytes: bytes) -> AudioSegment:
    """Decode raw audio bytes into a pydub AudioSegment."""
    return AudioSegment.from_file(io.BytesIO(audio_bytes))


def get_mp3_duration(path: Path) -> float:
    """Get duration of an MP3 file in seconds."""
    audio = AudioSegment.from_mp3(str(path))
    return len(audio) / 1000.0


def generate_ambient_audio(
    client: httpx.Client,
    gender: str,
    story_title: str,
    duration: int = 150,
    max_retries: int = 3,
) -> AudioSegment:
    """Generate atmospheric ambient music via ACE-Step.

    Uses non-lexical vocables with atmospheric descriptions to produce
    ethereal, wordless vocal textures over ambient instrumentation.
    """
    description = AMBIENT_DESCRIPTIONS[gender]
    voice_seed = hash(f"ambient_{gender}_{story_title}") % 999999 + 1

    payload = {
        "lyrics": AMBIENT_LYRICS,
        "description": description,
        "mode": "full",
        "format": "mp3",
        "duration": duration,
        "seed": voice_seed,
    }

    for attempt in range(1, max_retries + 1):
        logger.info(
            "  Generating %s ambient piece via ACE-Step (attempt %d/%d, %ds duration)...",
            gender, attempt, max_retries, duration,
        )
        try:
            resp = client.post(
                SONGGEN_URL,
                json=payload,
                timeout=600.0,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.error(
                    "  ACE-Step HTTP %d: %s", resp.status_code, resp.text[:200]
                )
                if attempt < max_retries:
                    wait = 10 * attempt
                    logger.info("  Retrying in %ds...", wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"ACE-Step failed after {max_retries} attempts")

            audio_bytes = resp.content
        except httpx.TimeoutException:
            logger.error("  ACE-Step request timed out")
            if attempt < max_retries:
                wait = 10 * attempt
                logger.info("  Retrying in %ds...", wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"ACE-Step timed out after {max_retries} attempts")

        if not audio_bytes or len(audio_bytes) < 1000:
            logger.error(
                "  ACE-Step returned empty audio (%d bytes)", len(audio_bytes)
            )
            if attempt < max_retries:
                wait = 10 * attempt
                logger.info("  Retrying in %ds...", wait)
                time.sleep(wait)
                continue
            raise RuntimeError("ACE-Step returned empty audio")

        # Successfully got audio
        break

    ambient = audio_from_bytes(audio_bytes)

    # Normalize to -19 dBFS (slightly quieter than narration at -16 dBFS)
    try:
        target_db = -19.0
        gain = target_db - ambient.dBFS
        ambient = ambient.apply_gain(gain)
    except Exception:
        logger.warning("  Normalization failed, continuing with raw audio")

    # Fade in over 5s, fade out over 3s
    try:
        ambient = ambient.fade_in(5000).fade_out(3000)
    except Exception:
        logger.warning("  Fade failed, continuing without fades")

    logger.info(
        "  Generated %s ambient: %.1f sec, %.0f KB",
        gender, len(ambient) / 1000.0, len(audio_bytes) / 1024,
    )
    return ambient


def stitch_ambient(
    story_audio: AudioSegment,
    ambient_audio: AudioSegment,
    crossfade_ms: int = 10000,
) -> AudioSegment:
    """Append ambient music after story with fade-out / silence gap / fade-in.

    Replicates the stitch_lullaby() logic from generate_audio.py.
    """
    crossfade_ms = min(
        crossfade_ms,
        len(story_audio) // 2,
        len(ambient_audio) // 2,
    )

    story_faded = story_audio.fade_out(crossfade_ms)
    ambient_faded = ambient_audio.fade_in(crossfade_ms)
    silence = AudioSegment.silent(duration=3000)

    combined = story_faded + silence + ambient_faded

    # Apply final gentle fade-out on the entire combined audio
    # (matches generate_audio.py line 808-813 behavior)
    try:
        combined = combined.fade_out(1500)
    except Exception:
        pass

    return combined


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stitch atmospheric ambient music onto story audio files"
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., gen-3b66368b6682)")
    parser.add_argument("--backup", action="store_true", help="Create .bak copies before overwriting")
    parser.add_argument("--duration", type=int, default=150, help="Ambient duration in seconds (default: 150)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without generating")
    args = parser.parse_args()

    if not SONGGEN_URL:
        logger.error("SONGGEN_URL not set in .env — cannot generate ambient music")
        sys.exit(1)

    # ── Load content.json ──
    logger.info("Loading content.json...")
    with open(CONTENT_PATH, "r") as f:
        content = json.load(f)

    # Find the story
    story = None
    story_idx = None
    for idx, item in enumerate(content):
        if item["id"] == args.story_id:
            story = item
            story_idx = idx
            break

    if story is None:
        logger.error("Story %s not found in content.json", args.story_id)
        sys.exit(1)

    title = story["title"]
    logger.info("Found story: %s", title)

    # Get existing audio variants
    audio_variants = story.get("audio_variants", [])
    if not audio_variants:
        logger.error("No audio_variants found for story %s", args.story_id)
        sys.exit(1)

    logger.info("Audio variants: %d", len(audio_variants))

    # Build file prefix from story ID
    story_prefix = args.story_id[:8]  # e.g., "gen-3b66"

    if args.dry_run:
        logger.info("\n=== DRY RUN ===")
        logger.info("Would generate 2 ambient pieces (female + male) of %ds each", args.duration)
        for av in audio_variants:
            voice = av["voice"]
            gender = VOICE_GENDER.get(voice, "female")
            mp3_name = f"{story_prefix}_{voice}.mp3"
            mp3_path = AUDIO_DIR / mp3_name
            logger.info(
                "  Would stitch %s ambient onto %s (%.1fs → ~%.1fs)",
                gender, mp3_name, av.get("duration_seconds", 0),
                av.get("duration_seconds", 0) + args.duration - 7,  # approximate
            )
        return

    # ── Generate ambient audio (2 pieces: female + male) ──
    logger.info("\n=== Generating ambient music via ACE-Step ===")
    ambient_cache = {}

    with httpx.Client() as client:
        for gender in ["female", "male"]:
            ambient_cache[gender] = generate_ambient_audio(
                client, gender, title, duration=args.duration
            )

    # ── Stitch onto each variant ──
    logger.info("\n=== Stitching ambient music onto audio variants ===")
    updated_variants = []

    for av in audio_variants:
        voice = av["voice"]
        gender = VOICE_GENDER.get(voice, "female")
        mp3_name = f"{story_prefix}_{voice}.mp3"
        mp3_path = AUDIO_DIR / mp3_name

        if not mp3_path.exists():
            logger.error("  MP3 not found: %s", mp3_path)
            updated_variants.append(av)
            continue

        logger.info("  Processing %s (%s)...", mp3_name, gender)

        # Backup if requested
        if args.backup:
            bak_path = mp3_path.with_suffix(".mp3.bak")
            if not bak_path.exists():
                shutil.copy2(mp3_path, bak_path)
                logger.info("    Backed up to %s", bak_path.name)

        # Load existing audio
        story_audio = AudioSegment.from_mp3(str(mp3_path))
        original_duration = len(story_audio) / 1000.0
        logger.info("    Original: %.1f sec", original_duration)

        # Stitch
        ambient = ambient_cache[gender]
        combined = stitch_ambient(story_audio, ambient)
        new_duration = len(combined) / 1000.0
        logger.info("    Combined: %.1f sec (+%.1f sec)", new_duration, new_duration - original_duration)

        # Export
        combined.export(str(mp3_path), format="mp3", bitrate="256k")
        size_kb = mp3_path.stat().st_size / 1024
        logger.info("    Saved: %s (%.0f KB)", mp3_name, size_kb)

        # Update variant metadata
        updated_av = dict(av)
        updated_av["duration_seconds"] = round(new_duration, 2)
        updated_variants.append(updated_av)

    # ── Update content.json ──
    logger.info("\n=== Updating content.json ===")
    story["audio_variants"] = updated_variants
    story["lullaby_lyrics"] = AMBIENT_LYRICS

    content[story_idx] = story

    with open(CONTENT_PATH, "w") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
        f.write("\n")

    logger.info("Updated content.json with new durations and ambient lyrics")

    # ── Summary ──
    logger.info("\n=== Summary ===")
    logger.info("Story: %s (%s)", title, args.story_id)
    logger.info("Ambient duration: %d seconds", args.duration)
    for av in updated_variants:
        logger.info(
            "  %s: %.1f sec (%.1f min)",
            av["voice"], av["duration_seconds"], av["duration_seconds"] / 60,
        )
    logger.info("\nDone! Next steps:")
    logger.info("  1. Copy MP3s to frontend: cp audio/pre-gen/%s_*.mp3 ../dreamweaver-web/public/audio/pre-gen/", story_prefix)
    logger.info("  2. Sync seedData.js: python3 scripts/sync_seed_data.py --lang en")
    logger.info("  3. Deploy to production")


if __name__ == "__main__":
    main()
