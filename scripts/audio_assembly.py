"""Shared audio assembly library for v2 stories with baked-in music.

Extracts common code from generate_experimental_v2.py, regen_exp2_audio.py,
and assemble_frog_story.py into reusable functions.

Used by:
- generate_audio.py (pipeline: short story v2 assembly)
- generate_experimental_v2.py (standalone experimental)
- regen_exp2_audio.py (manual regeneration)
"""

import io
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment

# ── Paths ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
MUSIC_DIR = BASE_DIR / "audio" / "story_music"

# ── Chatterbox TTS endpoints ────────────────────────────────────────────
CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"

# ── Voice mapping by mood ───────────────────────────────────────────────
# From AUDIO_GENERATION_GUIDELINES: mood → [primary_voice, secondary_voice]
MOOD_VOICES = {
    "wired":   ["female_3", "male_2"],    # melodic + gentle
    "curious": ["female_4", "male_2"],    # musical + gentle
    "calm":    ["female_1", "asmr"],      # calm + asmr
    "sad":     ["male_2", "female_1"],    # gentle + calm
    "anxious": ["male_2", "female_1"],    # gentle + calm
    "angry":   ["female_3", "male_2"],    # melodic + gentle
}
DEFAULT_VOICES = ["female_1", "asmr"]

# ── TTS parameter sets ─────────────────────────────────────────────────
NORMAL_TTS = {"exaggeration": 0.45, "speed": 0.85, "cfg_weight": 0.5}
HOOK_TTS = {"exaggeration": 0.55, "speed": 0.82, "cfg_weight": 0.45}
PHRASE_TTS = {"exaggeration": 0.60, "speed": 0.78, "cfg_weight": 0.42}


# ── Text normalization ──────────────────────────────────────────────────

def normalize_for_tts(text: str) -> str:
    """Normalize ALL CAPS words (3+ chars) to Title Case for TTS.

    Prevents Chatterbox from spelling out words letter-by-letter.
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
    - [PAUSE: ms] → silence of given duration
    - [PHRASE]...[/PHRASE] → repeated phrase (special TTS delivery)
    - Everything else → narration text
    """
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
            # Strip markdown and any stray emotion markers the LLM included
            cleaned = re.sub(r'\*+', '', part)
            cleaned = re.sub(r'\[/?(?:EMPHASIS|GENTLE|SLEEPY|EXCITED|CURIOUS|'
                             r'ADVENTUROUS|MYSTERIOUS|JOYFUL|DRAMATIC|WHISPERING|'
                             r'DRAMATIC_PAUSE|CALM|SAFETY|DELIVERY:[^\]]*)\]',
                             '', cleaned, flags=re.IGNORECASE)
            cleaned = cleaned.strip()
            if cleaned:
                segments.append(("text", cleaned))

    return segments


def clean_display_text(raw_text: str) -> str:
    """Strip v2 tags from raw text for display in content.json."""
    clean = re.sub(r'\[MUSIC\]', '', raw_text)
    clean = re.sub(r'\[PAUSE:\s*\d+\]', '', clean)
    clean = re.sub(r'\[/?PHRASE\]', '', clean)
    # Strip any stray emotion/emphasis markers the LLM may have included
    clean = re.sub(r'\[/?(?:EMPHASIS|GENTLE|SLEEPY|EXCITED|CURIOUS|ADVENTUROUS|'
                   r'MYSTERIOUS|JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|'
                   r'CALM|SAFETY|DELIVERY:[^\]]*)\]', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\*+', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return normalize_display_text(clean)


# ── TTS generation ──────────────────────────────────────────────────────

def generate_tts(text: str, voice: str, exaggeration: float = 0.45,
                 cfg_weight: float = 0.5, speed: float = 0.85,
                 is_phrase: bool = False,
                 chatterbox_url: str = CHATTERBOX_URL) -> AudioSegment:
    """Generate TTS audio via Chatterbox Modal endpoint.

    Args:
        text: Text to speak
        voice: Voice ID (e.g., female_1, male_2, asmr)
        exaggeration: Chatterbox exaggeration param (0-1)
        cfg_weight: Chatterbox cfg_weight param (0-1)
        speed: Chatterbox speed param (0-1)
        is_phrase: If True, prefix with ellipsis for breath effect
        chatterbox_url: Override endpoint URL
    """
    text = normalize_for_tts(text)
    if is_phrase:
        text = f"... {text}"
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{chatterbox_url}?{urlencode(params)}"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_wav(io.BytesIO(resp.content))
            except Exception:
                pass
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}, text={text[:50]}")


def generate_tts_throwaway(voice: str, chatterbox_url: str = CHATTERBOX_URL):
    """Send a throwaway TTS request to prevent Chatterbox repeat bug."""
    try:
        generate_tts(".", voice, exaggeration=0.1, speed=0.8, cfg_weight=0.5,
                     chatterbox_url=chatterbox_url)
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
        voice: Chatterbox voice ID
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

    # Throwaway to prevent Chatterbox repeat bug
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
