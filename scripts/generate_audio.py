"""Pre-generate audio for all stories using Chatterbox TTS via Modal.

Generates 7 variants per story (female_1/2/3, male_1/2/3, asmr per language).
Supports PARALLEL processing for fast generation across Modal GPU containers.
Requires ffmpeg (brew install ffmpeg) for audio processing.

Usage:
    python3 scripts/generate_audio.py                     # Generate all
    python3 scripts/generate_audio.py --story-id <id>     # Single story (7 variants)
    python3 scripts/generate_audio.py --voice female_1    # Single voice across all stories
    python3 scripts/generate_audio.py --lang hi            # Single language
    python3 scripts/generate_audio.py --dry-run            # Show plan only
    python3 scripts/generate_audio.py --force              # Regenerate existing files
    python3 scripts/generate_audio.py --workers 5          # Parallel workers (default 5)
"""

import argparse
import fcntl
import io
import json
import math
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

# ── Load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass  # pipeline_run.py or shell environment should have set env vars

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
OUTPUT_DIR = BASE_DIR / "audio" / "pre-gen"

# ── Chatterbox Modal endpoint ────────────────────────────────────────────
CHATTERBOX_URL = "https://anmol-71634--dreamweaver-chatterbox-tts.modal.run"
CHATTERBOX_HEALTH = "https://anmol-71634--dreamweaver-chatterbox-health.modal.run"

# ── SongGen Modal endpoint (for singing voice generation) ────────────────
SONGGEN_URL = os.getenv("SONGGEN_URL", "")
SONGGEN_HEALTH = os.getenv("SONGGEN_HEALTH", "")

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
    "story":      {"exaggeration": 0.5, "cfg_weight": 0.5},   # default — let Chatterbox shine
    "long_story": {"exaggeration": 0.5, "cfg_weight": 0.5},   # same as story (phases override)
    "poem":       {"exaggeration": 0.5, "cfg_weight": 0.3},   # slightly slower for poems
    "song":       {"exaggeration": 0.7, "cfg_weight": 0.3},   # more expressive for songs
}

PAUSE_MARKERS = {
    "pause": 800,             # natural pause
    "dramatic_pause": 1500,   # longer dramatic pause
    "long_pause": 4000,       # extended pause for sleep phase dissolving
    "breath_cue": 2000,       # breathing cue pause
}

# ── Per-phase TTS parameters for LONG stories (age-specific) ─────────
# Values from long-story-generation-guidelines.md
# Key differences: 9-12 has higher exaggeration/cfg in P2, softer volume curve
#
# Phase 1: engaged, natural speed
# Phase 2: softer, slower (cfg_weight controls pacing natively)
# Phase 3: ASMR voice, whispered
#
# Speed = post-processing stretch. Spec says "minimal or no stretching"
# and use cfg_weight as primary speed control. Speed is a last resort.

PHASE_TTS_PARAMS = {
    # Ages 2-5 and 6-8 share the same TTS params
    "2-5": {
        1: {"exaggeration": 0.5,  "cfg_weight": 0.5,  "speed": 1.0,  "use_asmr": False},
        2: {"exaggeration": 0.25, "cfg_weight": 0.3,  "speed": 0.95, "use_asmr": False},
        3: {"exaggeration": 0.25, "cfg_weight": 0.2,  "speed": 0.88, "use_asmr": True},
    },
    "6-8": {
        1: {"exaggeration": 0.5,  "cfg_weight": 0.5,  "speed": 1.0,  "use_asmr": False},
        2: {"exaggeration": 0.25, "cfg_weight": 0.3,  "speed": 0.95, "use_asmr": False},
        3: {"exaggeration": 0.25, "cfg_weight": 0.2,  "speed": 0.88, "use_asmr": True},
    },
    # Ages 9-12: slightly higher energy in P2 (exag 0.3, cfg 0.35)
    "9-12": {
        1: {"exaggeration": 0.5,  "cfg_weight": 0.5,  "speed": 1.0,  "use_asmr": False},
        2: {"exaggeration": 0.3,  "cfg_weight": 0.35, "speed": 0.95, "use_asmr": False},
        3: {"exaggeration": 0.25, "cfg_weight": 0.22, "speed": 0.90, "use_asmr": True},
    },
}

# Per-phase volume reduction (dB) — age-specific
# Applied before final normalization; normalization preserves RELATIVE differences
PHASE_VOLUME_DB = {
    "2-5":  {1: 0, 2: -3, 3: -6},
    "6-8":  {1: 0, 2: -3, 3: -6},
    "9-12": {1: 0, 2: -2, 3: -5},   # Spec: gentler curve for older kids
}

# Per-phase inter-paragraph pause (ms) — age-specific
# Spec: P3 for 2-5 = 3-5s, P3 for 9-12 = 4-6s
PHASE_PARA_PAUSE_MS = {
    "2-5":  {1: 1000, 2: 1500, 3: 3500},
    "6-8":  {1: 1000, 2: 1500, 3: 3000},
    "9-12": {1: 1000, 2: 1500, 3: 4500},
}

# ASMR voice used for Phase 3 (already soft/breathy, no new clips needed)
ASMR_VOICE = {"en": "asmr", "hi": "asmr_hi"}

_MARKER_RE = re.compile(
    r"\[/?"
    r"(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
    r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
    r"HUMMING|PAUSE|CHAR_START|CHAR_END|PHASE_1|PHASE_2|PHASE_3|LONG_PAUSE|"
    r"BREATH_CUE|laugh|chuckle)"
    r"\]",
    re.IGNORECASE,
)

# ── Voice mapping per language ───────────────────────────────────────────
# Using user-provided real voice recordings (female_1/2/3, male_1/2/3)
# These are high-quality human voice samples converted to 24kHz WAV
# Hindi voices have _hi suffix (separate Hindi voice recordings)
VOICE_MAP = {
    "en": ["female_1", "female_2", "female_3", "male_1", "male_2", "male_3", "asmr"],
    "hi": ["female_1_hi", "female_2_hi", "female_3_hi", "male_1_hi", "male_2_hi", "male_3_hi", "asmr_hi"],
}

# Song variants: 5 instrument-specific lullaby styles (Harp, Guitar, Piano, Cello, Flute)
SONG_VOICE_MAP = {
    "en": ["female_1", "female_2", "female_3", "male_1", "male_2"],
    "hi": ["female_1_hi", "female_2_hi", "female_3_hi", "male_1_hi", "male_2_hi"],
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
    """Parse annotated text into segments with emotion parameters.

    Supports character voice switching via [CHAR_START]/[CHAR_END] markers
    and phase-based pacing via [PHASE_2]/[PHASE_3] markers.
    These are backward-compatible — existing stories without these markers
    parse identically to before.
    """
    segments = []
    base_profile = CONTENT_TYPE_PROFILES.get(content_type, CONTENT_TYPE_PROFILES["story"])
    current_profile = dict(base_profile)
    current_phase = 1

    parts = _MARKER_RE.split(text)
    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        marker_lower = part_stripped.lower()

        # Character voice markers — strip only (narrator voice used for all)
        if marker_lower in ("char_start", "char_end"):
            continue
        # Phase tags — opening/closing markers from structured long stories
        elif marker_lower == "phase_1":
            # Phase 1 start (or closing tag) — no state change needed
            continue
        # Phase transitions
        elif marker_lower == "phase_2":
            current_phase = 2
            segments.append({"type": "pause", "duration_ms": 3000})
            current_profile = dict(EMOTION_PROFILES["calm"])
            continue
        elif marker_lower == "phase_3":
            current_phase = 3
            segments.append({"type": "pause", "duration_ms": 4000})
            current_profile = dict(EMOTION_PROFILES["whispering"])
            continue
        elif marker_lower in PAUSE_MARKERS:
            segments.append({"type": "pause", "duration_ms": PAUSE_MARKERS[marker_lower]})
        elif marker_lower in EMOTION_PROFILES:
            current_profile = dict(EMOTION_PROFILES[marker_lower])
        elif marker_lower in ("laugh", "chuckle"):
            continue
        else:
            clean_text = part_stripped.strip()
            if clean_text:
                seg = {
                    "type": "speech",
                    "text": clean_text,
                    "exaggeration": current_profile["exaggeration"],
                    "cfg_weight": current_profile["cfg_weight"],
                    "phase": current_phase,
                }
                segments.append(seg)

    return segments


# ═════════════════════════════════════════════════════════════════════════
# Phase-based audio generation (LONG stories with [PHASE_N] tags)
# ═════════════════════════════════════════════════════════════════════════

def parse_phases(story_text: str) -> Dict[int, str]:
    """Extract phase texts from [PHASE_N]...[/PHASE_N] tagged story.

    Returns dict: {1: "phase 1 text", 2: "phase 2 text", 3: "phase 3 text"}
    Fallback: if no phase tags found, treat entire text as Phase 1 (backward compat).
    """
    phases = {}
    for phase_num in [1, 2, 3]:
        pattern = rf'\[PHASE_{phase_num}\](.*?)\[/PHASE_{phase_num}\]'
        match = re.search(pattern, story_text, re.DOTALL)
        if match:
            phases[phase_num] = match.group(1).strip()

    if not phases:
        # No phase tags → legacy story, treat all as Phase 1
        phases[1] = story_text

    return phases


def get_phase_voice(base_voice: str, phase_num: int, lang: str, age_group: str = "2-5") -> str:
    """Get voice for a phase. Phase 3 uses ASMR voice for whispered delivery."""
    params = PHASE_TTS_PARAMS.get(age_group, PHASE_TTS_PARAMS["2-5"])
    if params[phase_num].get("use_asmr"):
        return ASMR_VOICE.get(lang, "asmr")
    return base_voice


def apply_phase_volume(audio: "AudioSegment", phase_num: int, age_group: str = "2-5") -> "AudioSegment":
    """Apply age-specific per-phase volume reduction.

    After crossfading and final normalization, the RELATIVE differences are preserved.
    """
    vol_db = PHASE_VOLUME_DB.get(age_group, PHASE_VOLUME_DB["2-5"])
    reduction = vol_db.get(phase_num, 0)
    if reduction == 0:
        return audio
    return audio.apply_gain(reduction)


def crossfade_phases(phase_audios: list, crossfade_ms: int = 3000) -> "AudioSegment":
    """Stitch phase AudioSegments with crossfade overlaps using pydub's append()."""
    result = phase_audios[0]
    for next_audio in phase_audios[1:]:
        if next_audio is None or len(next_audio) == 0:
            continue
        # Clamp crossfade to safe limits (half of shorter audio)
        safe_xfade = min(crossfade_ms, len(result) // 2, len(next_audio) // 2)
        if safe_xfade < 100:
            result = result + next_audio  # too short for crossfade
        else:
            result = result.append(next_audio, crossfade=safe_xfade)
    return result


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
    speed: float = 1.0,
    max_retries: int = 3,
) -> Optional[bytes]:
    """Call Chatterbox Modal endpoint and return audio bytes (WAV for lossless quality)."""
    params = {
        "text": text,
        "voice": voice,
        "lang": lang,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "speed": speed,
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
# Song generation via SongGen (LeVo)
# ═════════════════════════════════════════════════════════════════════════

# Regex to strip TTS emotion markers from song text
_EMOTION_MARKER_RE = re.compile(
    r"\[(?:SINGING|HUMMING|GENTLE|CALM|JOYFUL|SLEEPY|EXCITED|DRAMATIC|"
    r"WHISPERING|CURIOUS|ADVENTUROUS|MYSTERIOUS|RHYTHMIC|PAUSE|DRAMATIC_PAUSE|"
    r"LONG_PAUSE|BREATH_CUE|CHAR_START|CHAR_END|PHASE_2|PHASE_3|laugh|chuckle)\]\s*",
    re.IGNORECASE,
)


# ── Lullaby performance directions for section markers ─────────────────
# ACE-Step section markers — bare tags only.
# Performance directions (e.g. "whispered, extremely soft") MUST NOT appear
# in section markers because ACE-Step reads them as lyrics to sing.
# All style/mood control goes in the LULLABY_STYLES description field instead.


def _inject_lullaby_directions(lyrics: str) -> str:
    """Ensure section markers use bare tags only (no performance directions).

    ACE-Step reads anything after '[verse -' as lyrics text, causing it to
    narrate directions like 'whisper extremely slow'. All vocal style control
    is handled by the description field in LULLABY_STYLES.
    """
    lines = lyrics.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()
        if stripped == "[verse]":
            result.append("[verse]")
        elif stripped == "[chorus]":
            result.append("[chorus]")
        elif stripped == "[bridge]":
            result.append("[bridge]")
        elif stripped == "[outro]":
            result.append("[outro]")
        else:
            result.append(line)

    return "\n".join(result)


def validate_lullaby_lyrics(lyrics: str) -> list:
    """Validate lullaby lyrics against ACE-Step formatting rules.

    Returns a list of warning strings. Empty list = all checks pass.
    Does NOT block generation — diagnostic only.
    """
    warnings = []
    lines = [l.strip() for l in lyrics.split("\n") if l.strip()]

    # Count non-header lines
    content_lines = [l for l in lines if not l.startswith("[")]
    if len(content_lines) > 30:
        warnings.append(f"Too many lyric lines: {len(content_lines)} (max 30 for 120s)")

    # Check line lengths
    for i, line in enumerate(content_lines):
        word_count = len(line.split())
        if word_count > 15:
            warnings.append(f"Line {i+1} has {word_count} words (max 15): '{line[:50]}...'")

    # Count sections
    section_headers = [l for l in lines if l.startswith("[")]
    if len(section_headers) > 8:
        warnings.append(f"Too many sections: {len(section_headers)} (max 8)")

    # Check chorus repetition
    chorus_texts = []
    in_chorus = False
    current_chorus = []
    for line in lines:
        if "[chorus" in line.lower():
            if current_chorus:
                chorus_texts.append("\n".join(current_chorus))
            current_chorus = []
            in_chorus = True
        elif line.startswith("["):
            if current_chorus:
                chorus_texts.append("\n".join(current_chorus))
            current_chorus = []
            in_chorus = False
        elif in_chorus:
            current_chorus.append(line)
    if current_chorus:
        chorus_texts.append("\n".join(current_chorus))

    if len(chorus_texts) >= 2:
        unique_choruses = set(chorus_texts)
        if len(unique_choruses) > 1:
            warnings.append(
                f"Choruses are not identical ({len(unique_choruses)} unique versions). "
                "Non-repeating choruses cause ACE-Step melodic drift."
            )

    return warnings


def prepare_lyrics_for_songgen(story: dict) -> str:
    """Convert story text to ACE-Step-compatible lyrics format.

    Cleans up TTS emotion markers, parenthetical stage directions, and
    re-groups lines into proper 4-line verse stanzas. Humming lines become
    [chorus] sections. For songs, injects performance directions into
    section markers to guide ACE-Step vocal delivery.
    """
    text = story.get("text", "")
    if not text:
        return ""

    content_type = story.get("type", "story").lower()

    # Strip TTS emotion markers: [SINGING], [GENTLE], [PAUSE], etc.
    text = _EMOTION_MARKER_RE.sub("", text)

    # Regex for parenthetical stage directions: (Hum a soft melody...), (Whisper)...
    _STAGE_DIR_RE = re.compile(r"^\s*\(.*?\)\s*$")
    # Regex for humming lines: "Hmmm, hmmm..." or "La la la..."
    _HUMMING_RE = re.compile(r"^(?:h[mu]+m+|la\s+la|do\s+do|na\s+na)[,\s]", re.IGNORECASE)

    # First pass: split into lines, classify each
    raw_lines = text.split("\n")
    classified = []  # (type, text) where type is "lyric", "hum", "header", "blank"

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            classified.append(("blank", ""))
        elif _STAGE_DIR_RE.match(stripped):
            # Skip parenthetical directions entirely
            continue
        elif re.match(r"\[?(?:Verse|Chorus|Bridge)\s*\d*\]?", stripped, re.IGNORECASE):
            classified.append(("header", stripped))
        elif _HUMMING_RE.match(stripped):
            classified.append(("hum", stripped))
        elif stripped.lower().startswith("(whisper)"):
            # Convert whisper direction to lyric
            classified.append(("lyric", stripped.split(")", 1)[-1].strip()))
        else:
            classified.append(("lyric", stripped))

    # Second pass: detect if original text has [Verse]/[Chorus] structure
    has_section_headers = any(t == "header" for t, _ in classified)

    if has_section_headers:
        # Text already has proper section structure — use it
        ace_parts = []
        current_tag = "[verse]"
        current_lines = []

        for ctype, ctext in classified:
            if ctype == "header":
                # Flush previous section
                if current_lines:
                    ace_parts.append(f"{current_tag}\n" + "\n".join(current_lines))
                    current_lines = []
                # Detect tag
                if re.match(r"\[?Chorus\]?", ctext, re.IGNORECASE):
                    current_tag = "[chorus]"
                elif re.match(r"\[?Bridge\]?", ctext, re.IGNORECASE):
                    current_tag = "[bridge]"
                else:
                    current_tag = "[verse]"
            elif ctype == "lyric" and ctext:
                current_lines.append(ctext)
            elif ctype == "hum" and ctext:
                # Flush lyrics before hum, add hum as chorus
                if current_lines:
                    ace_parts.append(f"{current_tag}\n" + "\n".join(current_lines))
                    current_lines = []
                ace_parts.append(f"[chorus]\n{ctext}")

        if current_lines:
            ace_parts.append(f"{current_tag}\n" + "\n".join(current_lines))

        lyrics = "\n\n".join(ace_parts)
    else:
        # No section headers — regroup flat lines into 4-line verses
        lyric_lines = []
        hum_lines = []
        for ctype, ctext in classified:
            if ctype == "lyric" and ctext:
                lyric_lines.append(ctext)
            elif ctype == "hum" and ctext:
                hum_lines.append(ctext)

        ace_parts = []
        verse_num = 0

        # Group lyric lines into 4-line stanzas
        for i in range(0, len(lyric_lines), 4):
            chunk = lyric_lines[i:i + 4]
            if chunk:
                ace_parts.append("[verse]\n" + "\n".join(chunk))
                verse_num += 1
                # Insert a humming chorus after every 2 verses (if we have hum lines)
                if verse_num % 2 == 0 and hum_lines:
                    hum = hum_lines.pop(0)
                    ace_parts.append(f"[chorus]\n{hum}")

        # Append any remaining hum lines as a final chorus
        for hum in hum_lines:
            ace_parts.append(f"[chorus]\n{hum}")

        lyrics = "\n\n".join(ace_parts)

    # For songs: inject performance directions and validate
    if content_type == "song":
        lyrics = _inject_lullaby_directions(lyrics)

        # Run diagnostic validation
        warnings = validate_lullaby_lyrics(lyrics)
        if warnings:
            for w in warnings:
                logger.warning("  Lyrics validation: %s", w)

    return lyrics


def build_song_description(story: dict, voice: str) -> str:
    """Build ACE-Step description from song metadata to match the song's theme.

    The description controls the musical style, instruments, mood, and tempo
    so the generated singing matches the text content.
    """
    parts = []

    # Voice gender
    if "female" in voice:
        parts.append("female vocal")
    elif "male" in voice:
        parts.append("male vocal")
    else:
        parts.append("female vocal")  # default

    # Vocal qualities for lullabies
    parts.append("warm")
    parts.append("soft")

    # Genre from metadata
    genre = story.get("music_genre", "lullaby")
    parts.append(genre)

    # Theme-based mood descriptors
    theme = story.get("theme", "dreamy")
    theme_moods = {
        "dreamy": "ethereal, dreamy, floating",
        "ocean": "oceanic, wavy, flowing",
        "animals": "playful, gentle, nature",
        "nature": "pastoral, peaceful, organic",
        "fantasy": "magical, whimsical, enchanting",
        "adventure": "uplifting, hopeful, spirited",
        "space": "cosmic, spacey, twinkling",
        "bedtime": "sleepy, cozy, hushed",
        "friendship": "heartfelt, warm, tender",
        "mystery": "mystical, atmospheric, intriguing",
        "science": "curious, wonder, bright",
        "family": "comforting, loving, nurturing",
    }
    mood = theme_moods.get(theme, "gentle, soothing")
    parts.append(mood)

    # Instruments from metadata
    instruments = story.get("instruments", [])
    if instruments:
        parts.append(", ".join(instruments))
    else:
        # Default lullaby instruments
        parts.append("piano, soft strings")

    # Story description for additional context
    desc = story.get("description", "")
    if desc:
        # Extract key mood words from the story description
        parts.append(desc[:80])

    # Always end with tempo and bedtime context
    parts.append("slow tempo")
    parts.append("bedtime lullaby for children")

    return ", ".join(parts)


# ── Lullaby style variations for songs ──────────────────────────────────
# 5 instrument-specific styles with hyper-specific ACE-Step tags.
# Evidence-based parameters: 55-72 BPM, 6/8 or 3/4 meter, pentatonic,
# solo voice + one instrument, pianissimo, breathy/intimate vocals.
# Negative exclusions prevent ACE-Step from adding unwanted instrumentation.
LULLABY_STYLES = {
    "female_1": {
        "name": "Harp Lullaby",
        "mode": "full",
        "description": (
            "solo {gender} vocal lullaby with solo harp, "
            "extremely soft breathy intimate singing, "
            "66 BPM, 6/8 time signature, pentatonic major, "
            "pianissimo, legato, sparse arrangement, "
            "gentle rocking rhythm, warm tone, "
            "traditional cradle song, folk lullaby, "
            "no drums, no bass, no percussion, no synth, "
            "no electric instruments, no full arrangement, "
            "extremely repetitive, simple melody, "
            "narrow vocal range, descending phrases"
        ),
        "duration": 240,
    },
    "female_2": {
        "name": "Guitar Lullaby",
        "mode": "full",
        "description": (
            "solo {gender} vocal lullaby with fingerpicked acoustic guitar, "
            "extremely soft breathy intimate singing, "
            "64 BPM, 3/4 time signature, major key, "
            "pianissimo, legato, sparse, "
            "gentle waltz rhythm, warm folk, "
            "traditional lullaby, cradle song, "
            "no drums, no bass, no percussion, no synth, "
            "no electric instruments, no strumming, "
            "extremely repetitive simple melody, "
            "one guitar only, minimal accompaniment"
        ),
        "duration": 240,
    },
    "female_3": {
        "name": "Piano Lullaby",
        "mode": "full",
        "description": (
            "solo gentle vocal lullaby with soft piano, "
            "extremely soft breathy {gender} singing, intimate, "
            "62 BPM, 6/8 time signature, pentatonic, "
            "pianissimo, legato, sparse, "
            "gentle rocking rhythm, classical lullaby, "
            "berceuse, cradle song, "
            "no drums, no bass, no percussion, no synth, "
            "no full arrangement, no orchestral, "
            "extremely repetitive, simple melody, "
            "soft piano arpeggios only, minimal chords"
        ),
        "duration": 240,
    },
    "male_1": {
        "name": "Cello Lullaby",
        "mode": "full",
        "description": (
            "solo {gender} vocal lullaby with solo cello, "
            "extremely soft breathy intimate singing, "
            "62 BPM, 6/8 time signature, minor pentatonic, "
            "pianissimo, legato, sparse, "
            "gentle rocking rhythm, warm rich tone, "
            "classical lullaby, berceuse, "
            "no drums, no bass, no percussion, no synth, "
            "no piano, no guitar, no full arrangement, "
            "extremely repetitive, simple melody, "
            "cello sustains and drones only"
        ),
        "duration": 240,
    },
    "male_2": {
        "name": "Flute Lullaby",
        "mode": "full",
        "description": (
            "solo {gender} vocal lullaby with solo wooden flute, "
            "extremely soft breathy singing, intimate whisper, "
            "64 BPM, 3/4 time signature, pentatonic, "
            "pianissimo, legato, sparse, airy, "
            "gentle folk lullaby, pastoral, "
            "no drums, no bass, no percussion, no synth, "
            "no electric instruments, no full arrangement, "
            "extremely repetitive, simple melody, "
            "flute and voice only, nothing else"
        ),
        "duration": 240,
    },
}
# Hindi variants use the same styles
LULLABY_STYLES.update({
    f"{k}_hi": v for k, v in list(LULLABY_STYLES.items())
})

# ── Age 0-1 infant lullaby styles ──────────────────────────────────────
# Pure physiological entrainment: a cappella only, no instruments, slower BPM,
# nonsense syllables, maximum sparsity. Uses "vocal" mode (no instruments).
INFANT_LULLABY_STYLES = {
    "female_1": {
        "name": "A Cappella Lullaby",
        "mode": "vocal",
        "description": (
            "solo female vocal lullaby, a cappella, no instruments, "
            "extremely soft breathy intimate whisper singing, "
            "62 BPM, 6/8 time signature, pentatonic, "
            "pianissimo, legato, minimal, sparse, "
            "humming, gentle rocking rhythm, "
            "no drums, no bass, no percussion, no synth, "
            "no guitar, no piano, no strings section, "
            "no reverb tail, no delay effects, "
            "nursery, cradle song, ancient lullaby, "
            "extremely repetitive, simple melody"
        ),
        "duration": 180,
    },
    "male_1": {
        "name": "A Cappella Lullaby (Male)",
        "mode": "vocal",
        "description": (
            "solo male vocal lullaby, a cappella, no instruments, "
            "extremely soft breathy intimate whisper singing, "
            "62 BPM, 6/8 time signature, pentatonic, "
            "pianissimo, legato, minimal, sparse, "
            "humming, gentle rocking rhythm, "
            "no drums, no bass, no percussion, no synth, "
            "no guitar, no piano, no strings section, "
            "no reverb tail, no delay effects, "
            "nursery, cradle song, ancient lullaby, "
            "extremely repetitive, simple melody"
        ),
        "duration": 180,
    },
}
INFANT_LULLABY_STYLES.update({
    f"{k}_hi": v for k, v in list(INFANT_LULLABY_STYLES.items())
})

# Voice map for infant lullabies (fewer variants — a cappella only)
INFANT_SONG_VOICE_MAP = {
    "en": ["female_1", "male_1"],
    "hi": ["female_1_hi", "male_1_hi"],
}


def get_lullaby_config(story: dict) -> tuple:
    """Return (styles_dict, voice_map) based on story's target age.

    Ages 0-1: a cappella only, 2 variants (female + male)
    Ages 2-5: voice + instrument, 2 randomly chosen from 5 styles
              (harp, guitar, piano, cello, flute). Keeps generation
              time and QA manageable while maintaining variety across
              the catalog.
    Ages 6+:  no lullabies (returns None, None)
    """
    target_age = story.get("target_age", 4)
    age_min = story.get("age_min", target_age)

    if age_min >= 6 or target_age >= 6:
        return None, None  # No lullabies for 6+
    elif target_age <= 1 or age_min <= 1:
        return INFANT_LULLABY_STYLES, INFANT_SONG_VOICE_MAP
    else:
        # Randomly pick 2 of 5 instrument variants for variety without
        # generating all 5 (which takes too long for generation + QA)
        import random
        picked_voices = {
            lang: random.sample(voices, min(2, len(voices)))
            for lang, voices in SONG_VOICE_MAP.items()
        }
        return LULLABY_STYLES, picked_voices


# ── Lullaby post-processing helpers ─────────────────────────────────────

def _normalize_lullaby(audio: AudioSegment, target_lufs: float = -24.0) -> AudioSegment:
    """Normalize lullaby audio to -24 LUFS (research-based bedtime loudness).

    Falls back to -20 dBFS if pyloudnorm is unavailable.
    """
    try:
        import pyloudnorm as pyln
        import numpy as np

        samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
        # Normalize sample values to [-1, 1] range
        max_val = float(2 ** (audio.sample_width * 8 - 1))
        samples = samples / max_val

        if audio.channels == 2:
            samples = samples.reshape((-1, 2))
        elif audio.channels == 1:
            samples = samples.reshape((-1, 1))

        meter = pyln.Meter(audio.frame_rate)
        current_lufs = meter.integrated_loudness(samples)

        if current_lufs == float('-inf'):
            logger.warning("  LUFS measurement returned -inf (silent audio?), using dBFS fallback")
            gain = -20.0 - audio.dBFS
        else:
            gain = target_lufs - current_lufs
            logger.info("  LUFS: %.1f → %.1f (gain: %.1f dB)", current_lufs, target_lufs, gain)

        return audio.apply_gain(gain)
    except ImportError:
        logger.warning("  pyloudnorm not available, using dBFS fallback (-20 dBFS)")
        gain = -20.0 - audio.dBFS
        return audio.apply_gain(gain)
    except Exception as e:
        logger.warning("  LUFS normalization failed (using dBFS fallback): %s", e)
        gain = -20.0 - audio.dBFS
        return audio.apply_gain(gain)


def _apply_lullaby_fade(audio: AudioSegment) -> AudioSegment:
    """Apply extended lullaby fade-out starting at 80% of track duration.

    Two-stage fade: gentle from 80%-95%, steeper from 95%-100%.
    Appends 5 seconds of silence after fade for clean ending.
    """
    total_ms = len(audio)
    if total_ms < 10000:  # Too short for extended fade
        return audio.fade_in(500).fade_out(1500)

    # Gentle fade-in (1 second)
    audio = audio.fade_in(1000)

    # Split at 80% point
    fade_start = int(total_ms * 0.80)
    mid_point = int(total_ms * 0.95)

    pre_fade = audio[:fade_start]
    gentle_section = audio[fade_start:mid_point]
    steep_section = audio[mid_point:]

    # Stage 1: gentle fade (80% → 95%) — reduce by ~6 dB
    gentle_section = gentle_section.fade(to_gain=-6.0, start=0, end=len(gentle_section))

    # Stage 2: steep fade (95% → 100%) — fade to near-silence
    steep_section = steep_section.apply_gain(-6.0)  # already 6dB down from stage 1
    steep_section = steep_section.fade_out(len(steep_section))

    # Combine + append 5 seconds of silence
    result = pre_fade + gentle_section + steep_section
    result = result + AudioSegment.silent(duration=5000)

    return result


def _score_lullaby_quality(audio: AudioSegment, style: Optional[dict] = None) -> dict:
    """Score a lullaby candidate on multiple quality dimensions.

    Runs local audio analysis (no API calls) to evaluate adherence to
    lullaby guidelines. Used both during retake selection and post-generation QA.

    Returns dict with per-dimension scores (0.0-1.0, higher=better) and
    a composite 'score' (lower=better, for retake selection compatibility).
    """
    import numpy as np

    duration_ms = len(audio)
    duration_sec = duration_ms / 1000.0
    target_duration = (style or {}).get("duration", 240)
    results = {"dimensions": {}, "warnings": []}

    # ── 1. Duration accuracy ────────────────────────────────────────────
    duration_deviation = abs(duration_sec - target_duration) / target_duration
    duration_score = max(0.0, 1.0 - duration_deviation)
    results["dimensions"]["duration_accuracy"] = {
        "score": round(duration_score, 3),
        "actual": round(duration_sec, 1),
        "target": target_duration,
        "deviation_pct": round(duration_deviation * 100, 1),
    }
    if duration_deviation > 0.30:
        results["warnings"].append(f"duration {duration_sec:.0f}s vs target {target_duration}s ({duration_deviation:.0%} off)")

    # ── 2. Volume consistency (dBFS variance across chunks) ─────────────
    chunk_len = max(duration_ms // 10, 1000)
    chunks_dbfs = []
    for j in range(0, duration_ms - chunk_len, chunk_len):
        chunk = audio[j:j + chunk_len]
        if chunk.dBFS > -80:
            chunks_dbfs.append(chunk.dBFS)

    dbfs_variance = 0.0
    dbfs_range = 0.0
    if len(chunks_dbfs) >= 3:
        mean_db = sum(chunks_dbfs) / len(chunks_dbfs)
        dbfs_variance = sum((d - mean_db) ** 2 for d in chunks_dbfs) / len(chunks_dbfs)
        dbfs_range = max(chunks_dbfs) - min(chunks_dbfs)

    # Lower variance = better. Variance < 10 is good, > 30 is bad.
    vol_score = max(0.0, 1.0 - (dbfs_variance / 30.0))
    results["dimensions"]["volume_consistency"] = {
        "score": round(vol_score, 3),
        "variance": round(dbfs_variance, 1),
        "range_db": round(dbfs_range, 1),
    }
    if dbfs_range > 12:
        results["warnings"].append(f"dynamic range {dbfs_range:.0f}dB (max 8dB recommended)")

    # ── 3. Overall loudness level ───────────────────────────────────────
    avg_dbfs = audio.dBFS
    # Target: -24 LUFS ≈ roughly -20 to -28 dBFS range is acceptable
    loudness_deviation = abs(avg_dbfs - (-22.0))  # rough center
    loudness_score = max(0.0, 1.0 - (loudness_deviation / 15.0))
    results["dimensions"]["loudness"] = {
        "score": round(loudness_score, 3),
        "avg_dbfs": round(avg_dbfs, 1),
    }
    if avg_dbfs > -14:
        results["warnings"].append(f"too loud: avg {avg_dbfs:.0f} dBFS (target ~-22)")

    # ── 4. Sparsity: presence of near-silence gaps ──────────────────────
    # Good lullabies have moments of near-silence between phrases
    silence_threshold = avg_dbfs - 20  # 20dB below average = near-silence
    short_chunk = max(duration_ms // 40, 500)  # ~40 chunks
    quiet_chunks = 0
    total_chunks = 0
    for j in range(0, duration_ms - short_chunk, short_chunk):
        chunk = audio[j:j + short_chunk]
        total_chunks += 1
        if chunk.dBFS < silence_threshold:
            quiet_chunks += 1

    sparsity_ratio = quiet_chunks / max(total_chunks, 1)
    # Target: 10-40% quiet chunks. 0% = continuous, >50% = too sparse
    if sparsity_ratio < 0.05:
        sparsity_score = 0.3  # too continuous
    elif sparsity_ratio > 0.50:
        sparsity_score = 0.5  # too sparse
    else:
        sparsity_score = min(1.0, sparsity_ratio / 0.15)  # peaks at ~15%
    results["dimensions"]["sparsity"] = {
        "score": round(sparsity_score, 3),
        "quiet_ratio": round(sparsity_ratio, 3),
    }
    if sparsity_ratio < 0.03:
        results["warnings"].append("no gaps between phrases (continuous audio)")

    # ── 5. Spectral brightness: flag excessive high-frequency energy ────
    try:
        samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
        max_val = float(2 ** (audio.sample_width * 8 - 1))
        samples = samples / max_val
        if audio.channels == 2:
            samples = samples[::2]  # take one channel

        # Compute FFT and check energy above 4kHz
        from scipy.fft import rfft, rfftfreq
        N = len(samples)
        fft_vals = np.abs(rfft(samples))
        freqs = rfftfreq(N, 1.0 / audio.frame_rate)

        total_energy = np.sum(fft_vals ** 2)
        high_freq_mask = freqs > 4000
        high_energy = np.sum(fft_vals[high_freq_mask] ** 2)
        high_ratio = high_energy / max(total_energy, 1e-10)

        # Lullabies should have <15% energy above 4kHz
        brightness_score = max(0.0, 1.0 - (high_ratio / 0.20))
        results["dimensions"]["spectral_softness"] = {
            "score": round(brightness_score, 3),
            "high_freq_ratio": round(high_ratio, 4),
        }
        if high_ratio > 0.20:
            results["warnings"].append(f"bright/harsh audio: {high_ratio:.0%} energy above 4kHz")
    except Exception as e:
        results["dimensions"]["spectral_softness"] = {
            "score": 0.5, "error": str(e),
        }

    # ── 6. Peak detection: flag sudden loud moments ─────────────────────
    peak_count = 0
    if len(chunks_dbfs) >= 3:
        mean_db = sum(chunks_dbfs) / len(chunks_dbfs)
        for db in chunks_dbfs:
            if db > mean_db + 6:  # 6dB spike = sudden loud moment
                peak_count += 1
    peak_score = max(0.0, 1.0 - (peak_count / 3.0))
    results["dimensions"]["no_peaks"] = {
        "score": round(peak_score, 3),
        "spike_count": peak_count,
    }
    if peak_count > 0:
        results["warnings"].append(f"{peak_count} sudden volume spike(s) detected")

    # ── Composite score (lower = better, for retake selection) ──────────
    dim_scores = [d["score"] for d in results["dimensions"].values()]
    avg_quality = sum(dim_scores) / len(dim_scores) if dim_scores else 0.5

    # Composite: weight duration + volume most, penalize warnings
    composite = (
        (1.0 - results["dimensions"]["duration_accuracy"]["score"]) * 0.25
        + (1.0 - results["dimensions"]["volume_consistency"]["score"]) * 0.25
        + (1.0 - results["dimensions"]["spectral_softness"]["score"]) * 0.15
        + (1.0 - results["dimensions"]["sparsity"]["score"]) * 0.15
        + (1.0 - results["dimensions"]["no_peaks"]["score"]) * 0.10
        + (1.0 - results["dimensions"]["loudness"]["score"]) * 0.10
    )

    results["composite_score"] = round(composite, 4)
    results["quality_avg"] = round(avg_quality, 3)
    results["warning_count"] = len(results["warnings"])
    results["verdict"] = "PASS" if len(results["warnings"]) == 0 else ("WARN" if len(results["warnings"]) <= 2 else "FAIL")

    return results


def generate_song_variant(
    client: httpx.Client,
    story: dict,
    voice: str,
    output_path: Path,
    force: bool = False,
) -> Optional[dict]:
    """Generate singing audio for a song using ACE-Step on Modal.

    Unlike stories (segment-by-segment via Chatterbox), songs are generated
    as a single piece for musical coherence. Each voice slot maps to a distinct
    lullaby style (harp, guitar, piano, cello, flute) via LULLABY_STYLES.
    Generates 2 retakes, scores each on lullaby quality dimensions, and selects the best.
    """
    story_id = story["id"]
    title = story["title"]

    if output_path.exists() and not force:
        logger.info("  Skipping %s (exists)", output_path.name)
        duration = get_mp3_duration(output_path)
        return {
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "ace-step",
        }

    if not SONGGEN_URL:
        logger.warning("  SONGGEN_URL not configured, falling back to Chatterbox for song")
        return generate_story_variant(client, story, voice, output_path, force)

    # Prepare lyrics for ACE-Step
    lyrics = prepare_lyrics_for_songgen(story)

    if not lyrics:
        logger.error("  No lyrics for song %s", story_id)
        return None

    # Use age-appropriate lullaby style (0-1: a cappella, 2-5: instrument variants)
    voice_base = voice.replace("_hi", "")
    gender = "female" if "female" in voice else "male"
    styles_dict, _ = get_lullaby_config(story)
    style = (styles_dict or LULLABY_STYLES).get(voice)

    if style:
        description = style["description"].format(gender=gender)
        mode = style["mode"]
        logger.info("  Generating song %s / %s [%s] via ACE-Step...", title, voice, style["name"])
    else:
        description = build_song_description(story, voice)
        mode = "vocal"
        logger.info("  Generating song %s / %s via ACE-Step...", title, voice)
    logger.info("  Mode: %s | Description: %s", mode, description[:100])

    # Generate 2 retakes with different seeds, select the best
    voice_seed = hash(voice) % 999999 + 1
    style_duration = style.get("duration", 90) if style else 90
    num_retakes = 2

    candidates = []  # list of (AudioSegment, seed, score)

    for retake_idx in range(num_retakes):
        seed = voice_seed + (retake_idx * 1000)
        payload = {
            "lyrics": lyrics,
            "description": description,
            "mode": mode,
            "format": "mp3",
            "duration": style_duration,
            "seed": seed,
        }

        logger.info("  Retake %d/%d (seed=%d)...", retake_idx + 1, num_retakes, seed)
        try:
            resp = client.post(SONGGEN_URL, json=payload, timeout=600.0, follow_redirects=True)
            if resp.status_code != 200:
                logger.error("  ACE-Step HTTP %d: %s", resp.status_code, resp.text[:200])
                continue
            audio_bytes = resp.content
        except Exception as e:
            logger.error("  ACE-Step request failed: %s", e)
            continue

        if not audio_bytes or len(audio_bytes) < 1000:
            logger.error("  ACE-Step returned empty/tiny audio (%d bytes)", len(audio_bytes))
            continue

        try:
            audio = audio_from_bytes(audio_bytes)
        except Exception as e:
            logger.error("  Failed to decode ACE-Step audio: %s", e)
            continue

        # Run lullaby quality analysis on this candidate
        qa_result = _score_lullaby_quality(audio, style)
        audio_score = qa_result["composite_score"]

        # Run Whisper-based fidelity check (optional — skipped if faster-whisper not installed)
        fidelity_result = None
        combined_score = audio_score
        tmp_path = None
        try:
            from scripts.lullaby_fidelity import check_lullaby_fidelity
            import tempfile as _tempfile
            with _tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
            audio.export(tmp_path, format="mp3", bitrate="128k")
            fidelity_result = check_lullaby_fidelity(tmp_path, lyrics)
            os.unlink(tmp_path)
            tmp_path = None

            # Blend: 60% audio quality + 40% fidelity (both 0-1, lower=better for combined)
            fidelity_penalty = 1.0 - fidelity_result["fidelity_score"]
            combined_score = audio_score * 0.6 + fidelity_penalty * 0.4
            # REJECT = never select this take
            if fidelity_result["verdict"] == "REJECT":
                combined_score += 10.0
        except ImportError:
            logger.debug("    faster-whisper not available, skipping fidelity check")
        except Exception as e:
            logger.warning("    Fidelity check error: %s", e)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        candidates.append((audio, seed, combined_score, qa_result, fidelity_result))

        duration_ms = len(audio)
        logger.info("    Retake %d: %.1fs, quality=%.3f (%s), warnings=%d",
                     retake_idx + 1, duration_ms / 1000, qa_result["quality_avg"],
                     qa_result["verdict"], qa_result["warning_count"])
        if fidelity_result:
            logger.info("    Fidelity: %s (score=%.3f, type=%s)",
                         fidelity_result["verdict"], fidelity_result["fidelity_score"],
                         fidelity_result["content_type"])
            if fidelity_result["gate3"]["hits"]:
                logger.warning("    ⛔ Blocklist: %s", fidelity_result["gate3"]["hits"])
        for w in qa_result["warnings"]:
            logger.info("      ⚠ %s", w)

    if not candidates:
        logger.error("  All retakes failed for %s / %s", title, voice)
        return None

    # Select best candidate (lowest combined score)
    candidates.sort(key=lambda x: x[2])
    audio, best_seed, best_score, best_qa, best_fidelity = candidates[0]
    if len(candidates) > 1:
        logger.info("  Selected retake seed=%d (combined=%.4f, quality=%.3f, %s)",
                     best_seed, best_score, best_qa["quality_avg"], best_qa["verdict"])
        for dim_name, dim_data in best_qa["dimensions"].items():
            logger.info("    %s: %.3f", dim_name, dim_data["score"])
        if best_fidelity:
            logger.info("    fidelity: %.3f (%s, type=%s)",
                         best_fidelity["fidelity_score"], best_fidelity["verdict"],
                         best_fidelity["content_type"])

    # Normalize to -24 LUFS (research-based bedtime loudness)
    audio = _normalize_lullaby(audio)

    # Extended fade-out: begin at 80% of duration, two-stage exponential-like curve
    audio = _apply_lullaby_fade(audio)

    # Export as MP3 at 256kbps
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(output_path), format="mp3", bitrate="256k")

    duration = len(audio) / 1000.0
    size_kb = output_path.stat().st_size / 1024

    logger.info("  Saved %s (%.0f KB, %.1f sec)", output_path.name, size_kb, duration)

    return {
        "voice": voice,
        "url": f"/audio/pre-gen/{output_path.name}",
        "duration_seconds": round(duration, 2),
        "provider": "ace-step",
    }


# ═════════════════════════════════════════════════════════════════════════
# Story variant generation
# ═════════════════════════════════════════════════════════════════════════

# ── Lullaby stitching cache ────────────────────────────────────────────
# Cache generated lullaby AudioSegments so we generate only 2 (female + male)
# and reuse them across narrator variants.
_lullaby_cache: Dict[str, AudioSegment] = {}
_lullaby_cache_lock = threading.Lock()


def generate_lullaby_audio(
    client: httpx.Client,
    lyrics: str,
    voice_gender: str,
    story_title: str,
) -> Optional[AudioSegment]:
    """Generate a lullaby via ACE-Step and return as AudioSegment.

    Uses a cache so we only generate 2 lullabies (female + male) total,
    then reuse the appropriate one for each narrator variant.
    """
    cache_key = voice_gender  # "female" or "male"
    with _lullaby_cache_lock:
        if cache_key in _lullaby_cache:
            logger.info("  Reusing cached %s lullaby", cache_key)
            return _lullaby_cache[cache_key]

    if not SONGGEN_URL:
        logger.warning("  SONGGEN_URL not set, skipping lullaby generation")
        return None

    # Build description based on gender — uses Piano Lullaby template (most universal)
    if voice_gender == "female":
        description = (
            "solo gentle vocal lullaby with soft piano, "
            "extremely soft breathy female singing, intimate, "
            "62 BPM, 6/8 time signature, pentatonic, "
            "pianissimo, legato, sparse, "
            "gentle rocking rhythm, classical lullaby, berceuse, "
            "no drums, no bass, no percussion, no synth, "
            "no full arrangement, extremely repetitive, simple melody, "
            "soft piano arpeggios only, minimal chords"
        )
    else:
        description = (
            "solo gentle vocal lullaby with soft piano, "
            "extremely soft breathy male singing, intimate, "
            "62 BPM, 6/8 time signature, pentatonic, "
            "pianissimo, legato, sparse, "
            "gentle rocking rhythm, classical lullaby, berceuse, "
            "no drums, no bass, no percussion, no synth, "
            "no full arrangement, extremely repetitive, simple melody, "
            "soft piano arpeggios only, minimal chords"
        )

    voice_seed = hash(f"lullaby_{voice_gender}_{story_title}") % 999999 + 1
    payload = {
        "lyrics": lyrics,
        "description": description,
        "mode": "full",
        "format": "mp3",
        "duration": 240,  # 4 minutes — enough for all lyrics at slow lullaby tempo
        "seed": voice_seed,
    }

    logger.info("  Generating %s lullaby via ACE-Step for '%s'...", voice_gender, story_title)
    try:
        resp = client.post(SONGGEN_URL, json=payload, timeout=600.0, follow_redirects=True)
        if resp.status_code != 200:
            logger.error("  ACE-Step lullaby HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        audio_bytes = resp.content
    except Exception as e:
        logger.error("  ACE-Step lullaby request failed: %s", e)
        return None

    if not audio_bytes or len(audio_bytes) < 1000:
        logger.error("  ACE-Step lullaby returned empty audio (%d bytes)", len(audio_bytes))
        return None

    try:
        lullaby = audio_from_bytes(audio_bytes)
    except Exception as e:
        logger.error("  Failed to decode lullaby audio: %s", e)
        return None

    # Normalize to slightly quieter than narration (-19 dBFS vs -16 dBFS)
    try:
        target_db = -19.0
        gain = target_db - lullaby.dBFS
        lullaby = lullaby.apply_gain(gain)
    except Exception:
        pass

    # Fade in over 5 seconds
    try:
        lullaby = lullaby.fade_in(5000).fade_out(3000)
    except Exception:
        pass

    logger.info("  Generated %s lullaby: %.1f sec", voice_gender, len(lullaby) / 1000.0)

    with _lullaby_cache_lock:
        _lullaby_cache[cache_key] = lullaby

    return lullaby


def stitch_lullaby(
    story_audio: AudioSegment,
    lullaby_audio: AudioSegment,
    crossfade_ms: int = 10000,
) -> AudioSegment:
    """Append lullaby after story with fade-out / silence gap / fade-in.

    Avoids overlay so narration and lullaby never play simultaneously.
    """
    crossfade_ms = min(crossfade_ms, len(story_audio) // 2, len(lullaby_audio) // 2)

    # Fade out story ending, add silence gap, fade in lullaby
    story_faded = story_audio.fade_out(crossfade_ms)
    lullaby_faded = lullaby_audio.fade_in(crossfade_ms)
    silence = AudioSegment.silent(duration=3000)

    return story_faded + silence + lullaby_faded


# ═════════════════════════════════════════════════════════════════════════
# Phase-based long story audio generation
# ═════════════════════════════════════════════════════════════════════════

def generate_phase_audio(
    client: httpx.Client,
    phase_text: str,
    voice: str,
    phase_num: int,
    lang: str = "en",
    content_type: str = "story",
    age_group: str = "2-5",
) -> Optional[AudioSegment]:
    """Generate audio for one phase with age-specific TTS params and voice.

    Uses parse_annotated_text() to strip emotion markers and handle pauses,
    but overrides per-segment emotion values with phase-level params.
    Phase 3 uses the ASMR voice for whispered delivery.
    """
    if not phase_text.strip():
        return None

    age_params = PHASE_TTS_PARAMS.get(age_group, PHASE_TTS_PARAMS["2-5"])
    params = age_params[phase_num]
    phase_voice = get_phase_voice(voice, phase_num, lang, age_group)
    paragraphs = phase_text.split("\n\n")
    audio_segments: List[AudioSegment] = []
    age_pauses = PHASE_PARA_PAUSE_MS.get(age_group, PHASE_PARA_PAUSE_MS["2-5"])
    para_pause_ms = age_pauses[phase_num]

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        # parse_annotated_text strips emotion markers and handles pauses
        segments = parse_annotated_text(para, content_type)

        for seg in segments:
            if seg["type"] == "pause":
                audio_segments.append(generate_silence(seg["duration_ms"]))
            elif seg["type"] == "speech":
                # Override emotion values with PHASE-LEVEL params
                audio_bytes = generate_tts_for_segment(
                    client,
                    text=seg["text"],
                    voice=phase_voice,
                    exaggeration=params["exaggeration"],
                    cfg_weight=params["cfg_weight"],
                    lang=lang,
                    speed=params["speed"],
                )
                if audio_bytes:
                    try:
                        audio_segments.append(audio_from_bytes(audio_bytes))
                    except Exception as e:
                        logger.error("  Phase %d decode error: %s", phase_num, e)
                        return None
                else:
                    logger.error("  Phase %d TTS failed: %.50s...", phase_num, seg["text"])
                    return None

        # Inter-paragraph pause (except after last)
        if i < len(paragraphs) - 1:
            audio_segments.append(generate_silence(para_pause_ms))

    if not audio_segments:
        return None

    # Concatenate all segments within this phase
    combined = audio_segments[0]
    for seg_audio in audio_segments[1:]:
        combined = combined + seg_audio
    return combined


def generate_long_story_audio(
    client: httpx.Client,
    story_text: str,
    voice: str,
    lang: str = "en",
    content_type: str = "story",
    age_group: str = "2-5",
) -> Optional[AudioSegment]:
    """Generate long story audio with age-specific per-phase TTS params and ASMR Phase 3.

    Flow: parse phases → generate per-phase audio → apply volume
          → add silence padding → crossfade → normalize
    """
    phases = parse_phases(story_text)

    phase_audios = []
    for phase_num in [1, 2, 3]:
        phase_text = phases.get(phase_num, "")
        if not phase_text:
            continue

        phase_voice = get_phase_voice(voice, phase_num, lang, age_group)
        logger.info("  Phase %d: %d chars, voice=%s, age=%s",
                     phase_num, len(phase_text), phase_voice, age_group)

        audio = generate_phase_audio(
            client, phase_text, voice, phase_num, lang, content_type, age_group
        )
        if audio is None:
            logger.error("  Phase %d generation failed", phase_num)
            return None

        # Apply age-specific per-phase volume reduction
        audio = apply_phase_volume(audio, phase_num, age_group)

        # Add 1.5s silence padding at end of phase (spec: "1-2 seconds of silence
        # between the last word of Phase N and the first word of Phase N+1, before
        # crossfading"). Applied to all phases except the last.
        if phase_num < 3 and phases.get(phase_num + 1):
            audio = audio + generate_silence(1500)

        logger.info("  Phase %d: %.1f sec", phase_num, len(audio) / 1000.0)
        phase_audios.append(audio)

    if not phase_audios:
        return None

    # Crossfade stitch (3-5 second transitions between phases)
    combined = crossfade_phases(phase_audios, crossfade_ms=3000)

    # Normalize to -16 dBFS (preserves relative phase volume differences)
    try:
        gain = -16.0 - combined.dBFS
        combined = combined.apply_gain(gain)
    except Exception as e:
        logger.warning("  Normalization failed: %s", e)

    return combined


def generate_story_variant(
    client: httpx.Client,
    story: dict,
    voice: str,
    output_path: Path,
    force: bool = False,
    speed: float = 1.0,
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

    # For Hindi stories, prefer Devanagari text (better TTS pronunciation)
    if lang == "hi" and story.get("annotated_text_devanagari"):
        text = story["annotated_text_devanagari"]
        logger.info("  Using Devanagari text for Hindi story")
    else:
        text = story.get("annotated_text", story.get("text", ""))
    if not text:
        logger.error("  No text for story %s", story_id)
        return None

    logger.info("  Generating %s / %s (%s)...", title, voice, lang)

    # ── Phase-based generation for new LONG stories ──────────────
    is_phased = "[PHASE_1]" in text and "[/PHASE_1]" in text
    if is_phased:
        age_group = story.get("age_group", "2-5")
        logger.info("  Phase-tagged story — using phase-based generation (age %s)", age_group)
        combined = generate_long_story_audio(
            client, text, voice, lang, content_type, age_group
        )
        if combined is None:
            logger.error("  Phase-based generation failed for %s", story_id)
            return None

        # Apply gentle fade in + longer fade out (spec: 5s fade-out for Phase 3 ending)
        try:
            fade_in_ms = min(500, len(combined) // 4)
            fade_out_ms = min(5000, len(combined) // 3)
            combined = combined.fade_in(fade_in_ms).fade_out(fade_out_ms)
        except Exception as e:
            logger.warning("  Fade failed (continuing): %s", e)

        # Export (skip lullaby stitching — Phase 3 + ASMR voice replaces it)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.export(str(output_path), format="mp3", bitrate="256k")

        duration = len(combined) / 1000.0
        size_kb = output_path.stat().st_size / 1024
        logger.info("  Saved %s (%.0f KB, %.1f sec, phased)", output_path.name, size_kb, duration)

        return {
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        }

    # ── Legacy flow (existing code, unchanged) ────────────────────
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
                # Phase-based speed adjustment (slows down through phases)
                phase = seg.get("phase", 1)
                if phase == 1:
                    phase_speed = speed           # normal (80% at base 0.8)
                elif phase == 2:
                    phase_speed = speed * 0.875   # 70% at base 0.8
                else:
                    phase_speed = speed * 0.75    # 60% at base 0.8

                audio_bytes = generate_tts_for_segment(
                    client,
                    text=seg["text"],
                    voice=voice,
                    exaggeration=seg["exaggeration"],
                    cfg_weight=seg["cfg_weight"],
                    lang=lang,
                    speed=phase_speed,
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
        # Phase-based: longer pauses as story progresses toward sleep
        last_phase = para_segments[-1].get("phase", 1) if para_segments else 1
        para_pause_ms = {1: 1000, 2: 1500, 3: 2500}.get(last_phase, 1000)
        if i < len(paragraphs) - 1:
            audio_segments.append(generate_silence(para_pause_ms))

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

    # ── Lullaby stitching (for stories with lullaby_lyrics) ──────────
    lullaby_lyrics = story.get("lullaby_lyrics")
    if lullaby_lyrics and SONGGEN_URL:
        voice_gender = "female" if "female" in voice or voice == "asmr" else "male"
        lullaby_audio = generate_lullaby_audio(client, lullaby_lyrics, voice_gender, title)
        if lullaby_audio:
            logger.info("  Stitching %s lullaby onto %s variant...", voice_gender, voice)
            combined = stitch_lullaby(combined, lullaby_audio, crossfade_ms=10000)
            logger.info("  Combined duration with lullaby: %.1f sec", len(combined) / 1000.0)

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
    parser = argparse.ArgumentParser(description="Pre-generate story audio via Chatterbox (parallel)")
    parser.add_argument("--story-id", help="Generate for a specific story ID only")
    parser.add_argument("--voice", help="Generate for a specific voice only")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    parser.add_argument("--force", action="store_true", help="Regenerate existing files")
    parser.add_argument("--lang", help="Generate for a specific language only (en/hi)")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed 0.5-2.0 (0.8 for bedtime)")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers (default 5)")
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

    if args.lang:
        stories = [s for s in stories if s.get("lang", "en") == args.lang]
        if not stories:
            logger.error("No stories found for language: %s", args.lang)
            sys.exit(1)
        logger.info("Filtered to %d %s stories", len(stories), args.lang)

    # Build plan
    plan = []
    for story in stories:
        lang = story.get("lang", "en")
        content_type = story.get("type", "story")
        # Songs use age-appropriate voice variants via get_lullaby_config()
        if content_type == "song" and SONGGEN_URL:
            styles, voice_map = get_lullaby_config(story)
            if styles is None:
                logger.info("Skipping song %s (age 6+ — no lullabies)", story["title"])
                continue
            voices = voice_map.get(lang, voice_map["en"])
        else:
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

    # Filter plan based on force flag
    if not args.force:
        actionable = [p for p in plan if not p["exists"]]
    else:
        actionable = plan

    logger.info("\n=== Generation Plan ===")
    logger.info("Total variants: %d", len(plan))
    existing = sum(1 for p in plan if p["exists"])
    new_count = len(plan) - existing
    logger.info("Existing: %d, New/Regen: %d", existing, len(actionable))
    logger.info("Parallel workers: %d", args.workers)

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

    # Warm up with a single client first
    warmup_client = httpx.Client(timeout=180.0)
    if not warm_up_chatterbox(warmup_client):
        logger.error("Failed to warm up Chatterbox. Aborting.")
        sys.exit(1)
    warmup_client.close()

    # ── Thread-safe state ──
    results = {}
    results_lock = threading.Lock()
    counters = {"success": 0, "failed": 0, "skipped": 0}
    counters_lock = threading.Lock()
    lock_path = CONTENT_PATH.with_suffix(".lock")
    save_counter = {"count": 0}

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
                        # Auto-compute duration (minutes) from average audio length
                        durs = [v.get("duration_seconds") for v in existing_variants if v.get("duration_seconds")]
                        if durs:
                            story["duration"] = max(1, math.ceil(sum(durs) / len(durs) / 60))
                        updated += 1

                with open(CONTENT_PATH, "w", encoding="utf-8") as f:
                    json.dump(all_stories, f, ensure_ascii=False, indent=2)
                    f.write("\n")

                return updated
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)

    def process_item(item, item_idx, total):
        """Process a single story/voice variant (runs in thread pool)."""
        story = item["story"]
        voice = item["voice"]
        output_path = item["output_path"]
        content_type = story.get("type", "story")

        # Each thread gets its own HTTP client for thread safety
        thread_client = httpx.Client(timeout=300.0)
        try:
            logger.info("[%d/%d] %s / %s [%s]", item_idx + 1, total, story["title"], voice, content_type)

            # Route songs to SongGen, everything else to Chatterbox
            if content_type == "song" and SONGGEN_URL:
                variant = generate_song_variant(
                    thread_client, story, voice, output_path,
                    force=args.force,
                )
            else:
                variant = generate_story_variant(
                    thread_client, story, voice, output_path,
                    force=args.force, speed=args.speed,
                )

            if variant:
                sid = story["id"]
                with results_lock:
                    results.setdefault(sid, []).append(variant)
                    current_results = dict(results)  # snapshot for saving

                with counters_lock:
                    if item["exists"] and not args.force:
                        counters["skipped"] += 1
                    else:
                        counters["success"] += 1
                    save_counter["count"] += 1

                # Save content.json every 5 completions (crash-safe + not too frequent)
                if save_counter["count"] % 5 == 0:
                    try:
                        n = save_content_json(current_results)
                        logger.info("  💾 Saved content.json (%d stories)", n)
                    except Exception as e:
                        logger.warning("  content.json save failed: %s", e)

                return True
            else:
                with counters_lock:
                    counters["failed"] += 1
                return False
        finally:
            thread_client.close()

    # ── Parallel execution ──
    logger.info("\n🚀 Starting parallel generation with %d workers...\n", args.workers)
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for idx, item in enumerate(actionable):
            future = executor.submit(process_item, item, idx, len(actionable))
            futures[future] = item

        for future in as_completed(futures):
            item = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error("Worker error for %s/%s: %s",
                           item["story"]["title"], item["voice"], e)
                with counters_lock:
                    counters["failed"] += 1

    elapsed = time.time() - start_time

    # Final save of content.json
    logger.info("\n=== Final content.json update ===")
    with results_lock:
        final_results = dict(results)
    updated = save_content_json(final_results)
    logger.info("Updated %d stories", updated)
    logger.info("\n=== Summary ===")
    logger.info("Generated: %d, Skipped: %d, Failed: %d",
               counters["success"], counters["skipped"], counters["failed"])
    logger.info("Time: %.0f seconds (%.1f min)", elapsed, elapsed / 60)
    logger.info("Total MP3 files: %d", len(list(OUTPUT_DIR.glob("*.mp3"))))


if __name__ == "__main__":
    main()
