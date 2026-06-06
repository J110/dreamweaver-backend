"""Shared audio assembly library for v2 stories with baked-in music.

Extracts common code from generate_experimental_v2.py, regen_exp2_audio.py,
and assemble_frog_story.py into reusable functions.

Used by:
- generate_audio.py (pipeline: short story v2 assembly)
- generate_experimental_v2.py (standalone experimental)
- regen_exp2_audio.py (manual regeneration)
"""

import io
import os
import re
import time
from pathlib import Path

from pydub import AudioSegment

# ── Paths ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
MUSIC_DIR = BASE_DIR / "audio" / "story_music"

# ── Voice mapping by mood ───────────────────────────────────────────────
# Single narrator per mood (per spec §5.1).
MOOD_VOICES = {
    "wired":   ["tara"],
    "curious": ["simran"],
    "calm":    ["tripti"],
    "sad":     ["rhea"],
    "anxious": ["monika"],
    "angry":   ["zara"],
}
DEFAULT_VOICES = ["tripti"]

# ── TTS parameter sets ─────────────────────────────────────────────────
# Params chosen so chatterbox_to_elevenlabs() formula lands on the
# tuned-for-warmth ElevenLabs values (per spec §6 + 2026-04-27 tuning):
#   NORMAL → stab 0.50 / style 0.25 / speed 0.88
#   HOOK   → stab 0.45 / style 0.30 / speed 0.90
#   PHRASE → stab 0.70 / style 0.15 / speed 0.75 (intimate)
NORMAL_TTS = {"exaggeration": 0.42, "speed": 0.88, "cfg_weight": 0.45}
HOOK_TTS   = {"exaggeration": 0.50, "speed": 0.90, "cfg_weight": 0.50}
PHRASE_TTS = {"exaggeration": 0.25, "speed": 0.75, "cfg_weight": 0.27}


# ── Text normalization ──────────────────────────────────────────────────

def normalize_for_tts(text: str) -> str:
    """Normalize ALL CAPS words (3+ chars) to Title Case for TTS.

    Prevents TTS from spelling out words letter-by-letter.
    E.g., WHACK → Whack, BOOM → Boom, CRASH → Crash.
    Short words like I, OK, TV are preserved.
    """
    def fix_caps(match):
        word = match.group(0)
        if len(word) <= 2:
            return word
        return word.capitalize()
    return re.sub(r'\b[A-Z]{3,}\b', fix_caps, text)


def normalize_display_text(text: str) -> str:
    """Normalize ALL CAPS words in display text too."""
    return normalize_for_tts(text)


# ── Segment parsing ────────────────────────────────────────────────────

def parse_segments(text: str) -> list:
    """Parse story text with v2 tags into ordered segments.

    Returns: [("text", content), ("pause", ms), ("phrase", content), ("music", None)]

    Handles:
    - [MUSIC] → 6-second swell region
    - [PAUSE: ms] → silence of given duration (or inline <break/> on ElevenLabs)
    - [PHRASE]...[/PHRASE] → repeated phrase (special TTS delivery)
    - Everything else → narration text

    Short pauses (<2s) are converted to inline SSML <break time="..."/> tags
    so ElevenLabs renders them with natural breath instead of cold silence.
    """
    from _elevenlabs_common import convert_short_pauses_to_breaks
    text = convert_short_pauses_to_breaks(text)

    segments = []
    pattern = r'(\[MUSIC\]|\[PAUSE:\s*\d+\]|\[PHRASE\].*?\[/PHRASE\])'
    parts = re.split(pattern, text, flags=re.DOTALL)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "[MUSIC]":
            segments.append(("music", None))
        elif part.startswith("[PAUSE:"):
            ms = int(re.search(r'\d+', part).group())
            segments.append(("pause", ms))
        elif part.startswith("[PHRASE]"):
            content = part.replace("[PHRASE]", "").replace("[/PHRASE]", "").strip()
            content = re.sub(r'\*+', '', content)  # Strip markdown
            segments.append(("phrase", content))
        else:
            # Strip markdown and any stray markers the LLM included
            cleaned = re.sub(r'\*+', '', part)
            # Catch-all: strip any remaining [TAG] or [/TAG] brackets
            # (LLMs sometimes add [EMPHASIS], [DELIVERY:high], [high], etc.)
            cleaned = re.sub(r'\[/?[A-Za-z_][A-Za-z0-9_:. ]*\]', '', cleaned)
            cleaned = cleaned.strip()
            if cleaned:
                segments.append(("text", cleaned))

    return segments


def clean_display_text(raw_text: str) -> str:
    """Strip v2 tags from raw text for display in content.json."""
    clean = re.sub(r'\[MUSIC\]', '', raw_text)
    clean = re.sub(r'\[PAUSE:\s*\d+\]', '', clean)
    clean = re.sub(r'\[/?PHRASE\]', '', clean)
    # Catch-all: strip any remaining [TAG] or [/TAG] brackets
    clean = re.sub(r'\[/?[A-Za-z_][A-Za-z0-9_:. ]*\]', '', clean)
    clean = re.sub(r'\*+', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return normalize_display_text(clean)


# ── TTS generation ──────────────────────────────────────────────────────

def generate_tts(text: str, voice: str, exaggeration: float = 0.45,
                 cfg_weight: float = 0.5, speed: float = 0.85,
                 is_phrase: bool = False, **_kwargs) -> AudioSegment:
    """Generate TTS audio via ElevenLabs.

    Raises AllKeysExhaustedError when all keys are exhausted.
    """
    from _elevenlabs_common import tts_eleven_compat
    return tts_eleven_compat(text, voice, exaggeration=exaggeration,
                             cfg_weight=cfg_weight, speed=speed,
                             is_phrase=is_phrase)


def generate_tts_throwaway(voice: str, **_kwargs):
    """Send a throwaway TTS request to prevent voice repeat bug."""
    try:
        generate_tts(".", voice, exaggeration=0.1, speed=0.8, cfg_weight=0.5)
    except Exception:
        pass


# ── Swell envelope ─────────────────────────────────────────────────────

def apply_swell_envelope(bed: AudioSegment, swells: list,
                         base_db: float = -18, peak_db: float = -6) -> AudioSegment:
    """Apply volume swells to bed track in 50ms chunks.

    At [MUSIC] positions, bed volume rises from base_db to peak_db over 2s,
    holds for the swell duration, then fades back to base_db over 2s.
    Between swells, bed plays quietly at base_db.
    """
    chunk_ms = 50
    total_ms = len(bed)
    result = AudioSegment.silent(duration=0)

    pos = 0
    while pos < total_ms:
        chunk_end = min(pos + chunk_ms, total_ms)
        chunk = bed[pos:chunk_end]

        target_db = base_db
        for s in swells:
            if s["start"] <= pos < s["fade_in_end"]:
                progress = (pos - s["start"]) / max(s["fade_in_end"] - s["start"], 1)
                target_db = base_db + (peak_db - base_db) * progress
                break
            elif s["fade_in_end"] <= pos < s["hold_end"]:
                target_db = peak_db
                break
            elif s["hold_end"] <= pos < s["fade_out_end"]:
                progress = (pos - s["hold_end"]) / max(s["fade_out_end"] - s["hold_end"], 1)
                target_db = peak_db + (base_db - peak_db) * progress
                break

        result += chunk + target_db
        pos = chunk_end

    return result


# ── Full assembly ───────────────────────────────────────────────────────

def get_voices_for_mood(mood: str) -> list:
    """Return [voice1, voice2] for a mood."""
    return MOOD_VOICES.get(mood, DEFAULT_VOICES)


def assemble_v2_audio(
    segments: list,
    voice: str,
    mood: str,
    hook: str = None,
    skip_hook: bool = False,
    music_dir: Path = None,
) -> tuple:
    """Assemble a complete v2 story audio track with baked-in music.

    Args:
        segments: List of (type, content) tuples from parse_segments()
        voice: ElevenLabs voice label
        mood: Story mood (wired, calm, etc.)
        hook: Hook text for intro narration (optional)
        skip_hook: Skip hook TTS
        music_dir: Override music directory

    Returns:
        (with_music: AudioSegment, without_music: AudioSegment)
    """
    if music_dir is None:
        music_dir = MUSIC_DIR

    # Load mood music files
    intro = AudioSegment.from_wav(str(music_dir / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(music_dir / f"outro_{mood}.wav"))
    bed = AudioSegment.from_wav(str(music_dir / f"bed_{mood}.wav"))

    # Generate TTS for hook
    hook_audio = None
    if hook and not skip_hook:
        hook_audio = generate_tts(hook, voice, **HOOK_TTS)

    # Generate TTS for all segments
    segment_audios = []
    for stype, content in segments:
        if stype == "text":
            audio = generate_tts(content, voice, **NORMAL_TTS)
            segment_audios.append(("audio", audio))
        elif stype == "phrase":
            audio = generate_tts(content, voice, **PHRASE_TTS, is_phrase=True)
            segment_audios.append(("audio", audio))
        elif stype == "pause":
            segment_audios.append(("pause", content))
        elif stype == "music":
            segment_audios.append(("music", None))

    # Throwaway to prevent voice repeat bug
    generate_tts_throwaway(voice)

    # Build narration track
    narration = AudioSegment.silent(duration=0)
    swell_regions = []

    # Intro
    narration += intro
    narration += AudioSegment.silent(duration=500)

    # Hook (optional)
    if hook_audio:
        narration += hook_audio
        narration += AudioSegment.silent(duration=800)

    # Segments
    for stype, content in segment_audios:
        if stype == "audio":
            narration += content
        elif stype == "pause":
            narration += AudioSegment.silent(duration=content)
        elif stype == "music":
            start = len(narration)
            narration += AudioSegment.silent(duration=6000)
            swell_regions.append((start, len(narration)))

    # Gap + outro
    narration += AudioSegment.silent(duration=3000)
    narration += outro

    total_ms = len(narration)

    # Shape bed: fade out BEFORE outro starts (bed-over-outro fix)
    outro_dur = len(outro)
    gap_before_outro = 3000
    bed_end_ms = total_ms - outro_dur - gap_before_outro
    if len(bed) >= bed_end_ms:
        shaped_bed = bed[:bed_end_ms]
    else:
        loops = (bed_end_ms // len(bed)) + 1
        shaped_bed = (bed * loops)[:bed_end_ms]
    shaped_bed = shaped_bed.fade_out(3000)
    shaped_bed += AudioSegment.silent(duration=total_ms - bed_end_ms)

    # Build swell regions
    swells = []
    for start_ms, end_ms in swell_regions:
        swells.append({
            "start": start_ms,
            "fade_in_end": start_ms + 2000,
            "hold_end": end_ms - 2000,
            "fade_out_end": end_ms,
        })

    shaped_bed = apply_swell_envelope(shaped_bed, swells, base_db=-18, peak_db=-6)

    with_music = narration.overlay(shaped_bed)
    without_music = narration

    return with_music, without_music
