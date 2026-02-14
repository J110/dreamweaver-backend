"""Pre-generate audio for all stories using Chatterbox TTS via Modal.

Generates 3 variants per story (luna/whisper/atlas for EN, luna_hi/whisper_hi/atlas_hi for HI).
Requires ffmpeg (brew install ffmpeg) for audio processing.

Usage:
    python3 scripts/generate_audio.py                     # Generate all 48
    python3 scripts/generate_audio.py --story-id <id>     # Single story (3 variants)
    python3 scripts/generate_audio.py --voice luna         # Single voice across all stories
    python3 scripts/generate_audio.py --dry-run            # Show plan only
    python3 scripts/generate_audio.py --force              # Regenerate existing files
"""

import argparse
import fcntl
import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
OUTPUT_DIR = BASE_DIR / "audio" / "pre-gen"

# ── Chatterbox Modal endpoint ────────────────────────────────────────────
CHATTERBOX_URL = "https://j110--dreamweaver-chatterbox-tts.modal.run"
CHATTERBOX_HEALTH = "https://j110--dreamweaver-chatterbox-health.modal.run"

# ── Emotion profiles — BALANCED FOR QUALITY ──────────────────────────
# Based on Chatterbox documentation recommendations:
# - Default (0.5/0.5) is best for general purpose
# - Expressive: exaggeration=0.7, cfg_weight=0.3
# - Extreme values (>1.0 exag) cause artifacts
# - Lower cfg_weight = slower pacing
#
# We keep values moderate to avoid degrading audio quality.
# The quality of the voice reference matters MORE than extreme params.
EMOTION_PROFILES: Dict[str, dict] = {
    "sleepy":      {"exaggeration": 0.3,  "cfg_weight": 0.3},    # slow, drowsy
    "gentle":      {"exaggeration": 0.5,  "cfg_weight": 0.4},    # warm, natural
    "calm":        {"exaggeration": 0.5,  "cfg_weight": 0.5},    # default pace
    "excited":     {"exaggeration": 0.7,  "cfg_weight": 0.5},    # lively
    "curious":     {"exaggeration": 0.6,  "cfg_weight": 0.5},    # interested
    "adventurous": {"exaggeration": 0.7,  "cfg_weight": 0.4},    # bold
    "mysterious":  {"exaggeration": 0.5,  "cfg_weight": 0.3},    # slow, suspenseful
    "joyful":      {"exaggeration": 0.7,  "cfg_weight": 0.5},    # bright
    "dramatic":    {"exaggeration": 0.7,  "cfg_weight": 0.3},    # intense but stable
    "whispering":  {"exaggeration": 0.3,  "cfg_weight": 0.3},    # hushed
    "rhythmic":    {"exaggeration": 0.5,  "cfg_weight": 0.3},    # musical cadence
    "singing":     {"exaggeration": 0.7,  "cfg_weight": 0.3},    # expressive
    "humming":     {"exaggeration": 0.4,  "cfg_weight": 0.3},    # soft, melodic
}

CONTENT_TYPE_PROFILES: Dict[str, dict] = {
    "story": {"exaggeration": 0.5, "cfg_weight": 0.5},   # default — let Chatterbox shine
    "poem":  {"exaggeration": 0.5, "cfg_weight": 0.3},   # slightly slower for poems
    "song":  {"exaggeration": 0.7, "cfg_weight": 0.3},   # more expressive for songs
}

PAUSE_MARKERS = {
    "pause": 800,             # natural pause
    "dramatic_pause": 1500,   # longer dramatic pause
}

_MARKER_RE = re.compile(
    r"\["
    r"(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
    r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
    r"HUMMING|PAUSE|laugh|chuckle)"
    r"\]",
    re.IGNORECASE,
)

# ── Voice mapping per language ───────────────────────────────────────────
# Using user-provided real voice recordings (female_1/2/3, male_1/2/3)
# These are high-quality human voice samples converted to 24kHz WAV
# Hindi voices have _hi suffix (separate Hindi voice recordings)
VOICE_MAP = {
    "en": ["female_1", "female_2", "male_1"],
    "hi": ["female_1_hi", "female_2_hi", "male_1_hi"],
}

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# Audio helpers (using pydub + ffmpeg)
# ═════════════════════════════════════════════════════════════════════════

# Keep Chatterbox native sample rate (24kHz). Upsampling doesn't add real
# frequency content and can introduce interpolation artifacts.
NATIVE_SAMPLE_RATE = 24000


def audio_from_bytes(audio_bytes: bytes) -> AudioSegment:
    """Load audio bytes (MP3 or WAV) into an AudioSegment.

    Keeps native sample rate — no upsampling. Chatterbox outputs 24kHz
    which is perfectly fine for speech. Upsampling only adds artifacts.
    """
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
    return seg


def generate_silence(duration_ms: int) -> AudioSegment:
    """Generate silence AudioSegment at native sample rate."""
    return AudioSegment.silent(duration=duration_ms, frame_rate=NATIVE_SAMPLE_RATE)


def get_mp3_duration(filepath: Path) -> float:
    """Get duration of an MP3 file in seconds."""
    try:
        audio = AudioSegment.from_file(str(filepath))
        return len(audio) / 1000.0
    except Exception:
        return 0.0


# ═════════════════════════════════════════════════════════════════════════
# Text parsing
# ═════════════════════════════════════════════════════════════════════════

def parse_annotated_text(text: str, content_type: str = "story") -> List[dict]:
    """Parse annotated text into segments with emotion parameters."""
    segments = []
    base_profile = CONTENT_TYPE_PROFILES.get(content_type, CONTENT_TYPE_PROFILES["story"])
    current_profile = dict(base_profile)

    parts = _MARKER_RE.split(text)
    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        marker_lower = part_stripped.lower()
        if marker_lower in PAUSE_MARKERS:
            segments.append({"type": "pause", "duration_ms": PAUSE_MARKERS[marker_lower]})
        elif marker_lower in EMOTION_PROFILES:
            current_profile = dict(EMOTION_PROFILES[marker_lower])
        elif marker_lower in ("laugh", "chuckle"):
            continue
        else:
            clean_text = part_stripped.strip()
            if clean_text:
                segments.append({
                    "type": "speech",
                    "text": clean_text,
                    "exaggeration": current_profile["exaggeration"],
                    "cfg_weight": current_profile["cfg_weight"],
                })

    return segments


# ═════════════════════════════════════════════════════════════════════════
# TTS generation
# ═════════════════════════════════════════════════════════════════════════

def generate_tts_for_segment(
    client: httpx.Client,
    text: str,
    voice: str,
    exaggeration: float,
    cfg_weight: float,
    lang: str = "en",
    max_retries: int = 3,
) -> Optional[bytes]:
    """Call Chatterbox Modal endpoint and return audio bytes (WAV for lossless quality)."""
    params = {
        "text": text,
        "voice": voice,
        "lang": lang,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "format": "wav",  # Request lossless WAV — we do MP3 conversion ourselves
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"

    for attempt in range(max_retries):
        try:
            logger.debug("  TTS: voice=%s exag=%.2f cfg=%.2f text=%.50s...",
                        voice, exaggeration, cfg_weight, text)
            resp = client.get(url, timeout=180.0)
            if resp.status_code == 200:
                audio_bytes = resp.content
                if len(audio_bytes) > 100:
                    return audio_bytes
                else:
                    logger.warning("  Small response (%d bytes), retrying...", len(audio_bytes))
            else:
                logger.warning("  TTS %d: %s", resp.status_code, resp.text[:200])
        except httpx.TimeoutException:
            logger.warning("  Timeout (attempt %d/%d)", attempt + 1, max_retries)
        except Exception as e:
            logger.warning("  Error (attempt %d/%d): %s", attempt + 1, max_retries, e)

        if attempt < max_retries - 1:
            wait = 5 * (attempt + 1)
            logger.info("  Retrying in %ds...", wait)
            time.sleep(wait)

    return None


def warm_up_chatterbox(client: httpx.Client) -> bool:
    """Ping health endpoint to wake up Modal container."""
    logger.info("Warming up Chatterbox Modal container...")
    try:
        resp = client.get(CHATTERBOX_HEALTH, timeout=30.0)
        if resp.status_code == 200:
            data = resp.json()
            logger.info("Chatterbox healthy: %s, voices: %s",
                       data.get("engine"), data.get("voice_refs"))
            return True
    except Exception as e:
        logger.warning("Health check failed: %s", e)

    logger.info("Sending warm-up TTS request...")
    try:
        params = {"text": "Hello", "voice": "female_1", "exaggeration": 0.3, "cfg_weight": 0.4}
        resp = client.get(f"{CHATTERBOX_URL}?{urlencode(params)}", timeout=180.0)
        logger.info("Warm-up: %d (%d bytes)", resp.status_code, len(resp.content))
        return resp.status_code == 200
    except Exception as e:
        logger.error("Warm-up failed: %s", e)
        return False


# ═════════════════════════════════════════════════════════════════════════
# Story variant generation
# ═════════════════════════════════════════════════════════════════════════

def generate_story_variant(
    client: httpx.Client,
    story: dict,
    voice: str,
    output_path: Path,
    force: bool = False,
) -> Optional[dict]:
    """Generate a single audio variant for a story. Outputs MP3."""
    story_id = story["id"]
    lang = story.get("lang", "en")
    content_type = story.get("type", "story")
    title = story["title"]

    if output_path.exists() and not force:
        logger.info("  Skipping %s (exists)", output_path.name)
        duration = get_mp3_duration(output_path)
        return {
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        }

    text = story.get("annotated_text", story.get("text", ""))
    if not text:
        logger.error("  No text for story %s", story_id)
        return None

    logger.info("  Generating %s / %s (%s)...", title, voice, lang)

    # Parse annotated text into segments
    paragraphs = text.split("\n\n")
    audio_segments: List[AudioSegment] = []

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        para_segments = parse_annotated_text(para, content_type)

        for seg in para_segments:
            if seg["type"] == "pause":
                audio_segments.append(generate_silence(seg["duration_ms"]))
            elif seg["type"] == "speech":
                audio_bytes = generate_tts_for_segment(
                    client,
                    text=seg["text"],
                    voice=voice,
                    exaggeration=seg["exaggeration"],
                    cfg_weight=seg["cfg_weight"],
                    lang=lang,
                )
                if audio_bytes:
                    try:
                        seg_audio = audio_from_bytes(audio_bytes)
                        audio_segments.append(seg_audio)
                    except Exception as e:
                        logger.error("  Failed to decode audio for segment: %s", e)
                        return None
                else:
                    logger.error("  Failed segment: %.50s...", seg["text"])
                    return None

                # No delay — Modal auto-scales and we're paying per second

        # Paragraph pause (except after last) — generous pause between paragraphs
        # gives a natural storytelling feel, lets the listener process
        if i < len(paragraphs) - 1:
            audio_segments.append(generate_silence(1000))

    if not audio_segments:
        logger.error("  No audio segments for %s", story_id)
        return None

    logger.info("  Parsed %d segments", len(audio_segments))

    # Concatenate all segments
    combined = audio_segments[0]
    for seg_audio in audio_segments[1:]:
        combined = combined + seg_audio

    # NOTE: No warmth EQ — it degraded quality by cutting frequencies.
    # The fix for audio quality is better voice references (WAV not MP3)
    # and moderate Chatterbox parameters.

    # Normalize to -16 dBFS (gentle level, good for bedtime)
    try:
        target_db = -16.0
        gain = target_db - combined.dBFS
        combined = combined.apply_gain(gain)
    except Exception as e:
        logger.warning("  Normalization failed (continuing): %s", e)

    # Apply gentle fade in/out
    try:
        fade_in_ms = min(500, len(combined) // 4)
        fade_out_ms = min(1500, len(combined) // 3)
        combined = combined.fade_in(fade_in_ms).fade_out(fade_out_ms)
    except Exception as e:
        logger.warning("  Fade failed (continuing): %s", e)

    # Export as high-quality MP3 at 256kbps (native 24kHz sample rate)
    # Do NOT upsample — keep Chatterbox's native 24kHz for cleanest output.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(
        str(output_path),
        format="mp3",
        bitrate="256k",
    )

    duration = len(combined) / 1000.0
    size_kb = output_path.stat().st_size / 1024

    logger.info("  Saved %s (%.0f KB, %.1f sec)", output_path.name, size_kb, duration)

    return {
        "voice": voice,
        "url": f"/audio/pre-gen/{output_path.name}",
        "duration_seconds": round(duration, 2),
        "provider": "chatterbox",
    }


def main():
    parser = argparse.ArgumentParser(description="Pre-generate story audio via Chatterbox")
    parser.add_argument("--story-id", help="Generate for a specific story ID only")
    parser.add_argument("--voice", help="Generate for a specific voice only")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    parser.add_argument("--force", action="store_true", help="Regenerate existing files")
    args = parser.parse_args()

    # Ensure ffmpeg is available
    ffmpeg_path = os.popen("which ffmpeg").read().strip()
    if not ffmpeg_path:
        # Try homebrew path
        if os.path.exists("/opt/homebrew/bin/ffmpeg"):
            os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
            logger.info("Added /opt/homebrew/bin to PATH for ffmpeg")
        else:
            logger.error("ffmpeg not found. Install with: brew install ffmpeg")
            sys.exit(1)

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        stories = json.load(f)

    logger.info("Loaded %d stories from %s", len(stories), CONTENT_PATH)

    if args.story_id:
        stories = [s for s in stories if s["id"] == args.story_id]
        if not stories:
            logger.error("Story not found: %s", args.story_id)
            sys.exit(1)

    # Build plan
    plan = []
    for story in stories:
        lang = story.get("lang", "en")
        voices = VOICE_MAP.get(lang, VOICE_MAP["en"])
        if args.voice:
            voices = [v for v in voices if v == args.voice]
            if not voices:
                continue
        for voice in voices:
            story_id_short = story["id"][:8]
            output_path = OUTPUT_DIR / f"{story_id_short}_{voice}.mp3"
            plan.append({
                "story": story,
                "voice": voice,
                "output_path": output_path,
                "exists": output_path.exists(),
            })

    logger.info("\n=== Generation Plan ===")
    logger.info("Total variants: %d", len(plan))
    existing = sum(1 for p in plan if p["exists"])
    new_count = len(plan) - existing
    logger.info("Existing: %d, New: %d", existing, new_count)
    logger.info("Will skip existing files (use --force to regenerate)")

    for item in plan:
        status = "EXISTS" if item["exists"] else "NEW"
        if args.force and item["exists"]:
            status = "REGEN"
        logger.info("  [%s] %s / %s → %s",
                    status, item["story"]["title"], item["voice"], item["output_path"].name)

    if args.dry_run:
        logger.info("\nDry run complete.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(timeout=180.0)
    if not warm_up_chatterbox(client):
        logger.error("Failed to warm up Chatterbox. Aborting.")
        sys.exit(1)

    results = {}
    success = failed = skipped = 0

    lock_path = CONTENT_PATH.with_suffix(".lock")

    def save_content_json(new_results: dict):
        """Incrementally save audio_variants to content.json (file-locked for concurrency)."""
        with open(lock_path, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                with open(CONTENT_PATH, "r", encoding="utf-8") as f:
                    all_stories = json.load(f)

                updated = 0
                for story in all_stories:
                    if story["id"] in new_results:
                        existing_variants = story.get("audio_variants", [])
                        existing_voices = {v["voice"] for v in existing_variants}
                        for nv in new_results[story["id"]]:
                            if nv["voice"] in existing_voices:
                                for j, ev in enumerate(existing_variants):
                                    if ev["voice"] == nv["voice"]:
                                        existing_variants[j] = nv
                                        break
                            else:
                                existing_variants.append(nv)
                        story["audio_variants"] = existing_variants
                        updated += 1

                with open(CONTENT_PATH, "w", encoding="utf-8") as f:
                    json.dump(all_stories, f, ensure_ascii=False, indent=2)
                    f.write("\n")

                return updated
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    for i, item in enumerate(plan):
        story = item["story"]
        voice = item["voice"]
        output_path = item["output_path"]

        logger.info("\n[%d/%d] %s / %s", i + 1, len(plan), story["title"], voice)

        variant = generate_story_variant(client, story, voice, output_path, force=args.force)

        if variant:
            sid = story["id"]
            results.setdefault(sid, []).append(variant)
            if item["exists"] and not args.force:
                skipped += 1
            else:
                success += 1

            # Save content.json after each successful variant (crash-safe)
            try:
                save_content_json(results)
                logger.info("  Saved content.json (%d stories updated)", len(results))
            except Exception as e:
                logger.warning("  content.json save failed (will retry): %s", e)
        else:
            failed += 1

    client.close()

    # Final save of content.json
    logger.info("\n=== Final content.json update ===")
    updated = save_content_json(results)
    logger.info("Updated %d stories", updated)
    logger.info("\n=== Summary ===")
    logger.info("Generated: %d, Skipped: %d, Failed: %d", success, skipped, failed)
    logger.info("Total MP3 files: %d", len(list(OUTPUT_DIR.glob("*.mp3"))))


if __name__ == "__main__":
    main()
