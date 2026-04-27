"""Shared ElevenLabs TTS layer for English content (V2 short stories + long stories).

Drop-in alternative to the Chatterbox `generate_tts(text, voice, exaggeration,
cfg_weight, speed, ...)` contract used in audio_assembly.py,
generate_experimental_v2.py, and generate_long_story_episode.py.

Activated via env flag: TTS_ENGINE_EN=elevenlabs (default: chatterbox).

See: docs/superpowers/specs/2026-04-27-english-tts-elevenlabs-migration-design.md
"""

from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path

import httpx
from pydub import AudioSegment

# ────────────────────────────────────────────────────────────────────────
#  ElevenLabs API
# ────────────────────────────────────────────────────────────────────────

ELEVENLABS_API_KEY = os.getenv(
    "ELEVENLABS_API_KEY",
    "sk_5bbd5d1a1ee9fa532c454154e2a7723f94ffc3bce07087ff",
)
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"

# 2000 chars: above this, ElevenLabs Multilingual v2 prosody soft-degrades.
SOFT_LIMIT = 2000


# ────────────────────────────────────────────────────────────────────────
#  Voice library — English (10 voices)
# ────────────────────────────────────────────────────────────────────────

ELEVENLABS_VOICES_EN = {
    # Female narrators
    "tripti":  "MwUMLXurEzSN7bIfIdXF",  # Calm and Experienced
    "monika":  "2zRM7PkgwBPiau2jvVXc",  # Deep and Natural
    "tara":    "P7vsEyTOpZ6YUTulin8m",  # Conversational and Expressive
    "simran":  "1ea3IFhmSWgw8sJkSvfJ",  # Cheerful Best Friend
    "rhea":    "eUdJpUEN3EslrgE24PKx",  # Soft, Polished and Calm
    "maya":    "4O1sYUnmtThcBoSBrri7",  # Friendly and Cheerful
    "zara":    "wdymxIQkYn7MJCYCQF2Q",  # Soothing, Meditative — ASMR / whisper
    # Male voices (long-story characters only)
    "ranbir":  "MgKG6W05zBkvXijkNguO",  # Deep and Dramatic Storyteller
    "tarun":   "qr9D67rNgxf5xNgv46nx",  # Rich, Warm and Friendly (replaced harshit 2026-04-27)
    "ishan":   "N09NFwYJJG9VSSgdLQbT",  # Bold and Upbeat
    # harshit retired 2026-04-27 (user feedback); voice ID kept for legacy lookups.
    "harshit": "6TcvxMZXgg9AlJrd8iCl",  # Strong, Deep and Casual — retired, unused
}

# Legacy chatterbox voice labels → ElevenLabs labels (used when call sites
# pass chatterbox names like "female_1" / "male_2" / "asmr").
LEGACY_VOICE_MAP_EN = {
    "female_1": "tripti",
    "female_2": "monika",
    "female_3": "tara",
    "female_4": "simran",
    "female_5": "rhea",
    "female_6": "maya",
    "male_1":   "tarun",   # was harshit; retired 2026-04-27
    "male_2":   "ranbir",
    "male_3":   "ishan",
    "asmr":     "zara",
}

# Mood → narrator voice label (single narrator per mood, per spec §5.1).
MOOD_NARRATOR_EN = {
    "wired":   "tara",     # Conversational and Expressive — playful energy
    "curious": "simran",   # Cheerful Best Friend — wonder vibe
    "calm":    "tripti",   # Calm and Experienced — the anchor
    "sad":     "rhea",     # Soft, Polished and Calm — tender
    "anxious": "monika",   # Deep and Natural — grounding, reassuring
    "angry":   "zara",     # Soothing/Meditative — softens the heat (was maya, swapped 2026-04-27)
}
WHISPER_VOICE_EN = "zara"


# ────────────────────────────────────────────────────────────────────────
#  TTS parameter tables (per spec §6, §7)
# ────────────────────────────────────────────────────────────────────────

# V2 short-story phase params (per spec §6 + 2026-04-27 emotional-warmth tuning).
# Initial values (stab 0.55-0.85 / style 0.00-0.05) sounded flat — too high
# stability + zero style suppressed emotion. New range: lower stability for
# range, moderate style for warmth. Hindi defaults don't translate to English
# because Hindi rhythm/voice carries warmth innately; English needs more style.
V2_PHASE_PARAMS_EN = {
    1: {"stability": 0.45, "similarity_boost": 0.75, "style": 0.30, "speed": 0.92},
    2: {"stability": 0.55, "similarity_boost": 0.75, "style": 0.20, "speed": 0.85},
    3: {"stability": 0.65, "similarity_boost": 0.75, "style": 0.10, "speed": 0.78},
}
V2_PHRASE_PARAMS_EN = {"stability": 0.70, "similarity_boost": 0.75, "style": 0.15, "speed": 0.75}

# Long-story section params — emotional-warmth tuning v2 (2026-04-27).
# Long stories need MORE arc than V2 shorts (15-25 min runtime traversing
# engagement → easing → settling → dissolution). Earlier values kept style
# at 0.00 across all phases — that flattens the arc the text already has.
# New design: stability rises across phases, style descends, speed slows.
# Whisper is the ONLY place style 0.00 is correct.
LONG_STORY_TTS_EN = {
    "intro":           {"stability": 0.45, "similarity_boost": 0.75, "style": 0.35, "speed": 0.92},
    "phase_1":         {"stability": 0.50, "similarity_boost": 0.75, "style": 0.30, "speed": 0.88},
    "phrase":          {"stability": 0.60, "similarity_boost": 0.75, "style": 0.20, "speed": 0.75},
    "song_transition": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.25, "speed": 0.82},
    "post_song":       {"stability": 0.60, "similarity_boost": 0.75, "style": 0.20, "speed": 0.78},
    "phase_2":         {"stability": 0.65, "similarity_boost": 0.75, "style": 0.15, "speed": 0.78},
    "phase_3":         {"stability": 0.75, "similarity_boost": 0.75, "style": 0.10, "speed": 0.72},
    "whisper":         {"stability": 0.85, "similarity_boost": 0.75, "style": 0.00, "speed": 0.70},
    "breathing":       {"stability": 0.70, "similarity_boost": 0.75, "style": 0.10, "speed": 0.72},
    "breathe_guide":   {"stability": 0.75, "similarity_boost": 0.75, "style": 0.05, "speed": 0.70},
}

# Character voice-style modifiers (per spec §7.1).
# Applied as offsets on the section base; clamped after summing.
CHARACTER_VOICE_MODIFIERS_EN = {
    "confident": {"speed_offset": +0.03, "style_offset": +0.05, "stability_offset": -0.05},
    "gentle":    {"speed_offset": -0.03, "style_offset": +0.03, "stability_offset":  0.00},
    "small":     {"speed_offset": +0.05, "style_offset": +0.05, "stability_offset": -0.05},
    "wise":      {"speed_offset": -0.05, "style_offset": -0.03, "stability_offset": +0.05},
    "nervous":   {"speed_offset": +0.04, "style_offset": +0.08, "stability_offset": -0.08},
    "curious":   {"speed_offset": +0.02, "style_offset": +0.05, "stability_offset": -0.03},
    "stubborn":  {"speed_offset": -0.02, "style_offset": +0.05, "stability_offset": -0.05},
    "dreamy":    {"speed_offset": -0.06, "style_offset": -0.02, "stability_offset": +0.05},
    "brave":     {"speed_offset": +0.01, "style_offset": +0.04, "stability_offset": -0.02},
    "quiet":     {"speed_offset": -0.04, "style_offset": -0.05, "stability_offset": +0.10},
    "playful":   {"speed_offset": +0.04, "style_offset": +0.05, "stability_offset": -0.05},
    "careful":   {"speed_offset": -0.03, "style_offset": -0.03, "stability_offset": +0.05},
    "sleepy":    {"speed_offset": -0.08, "style_offset": -0.05, "stability_offset": +0.10},
}


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def is_enabled(lang: str = "en") -> bool:
    """Whether ElevenLabs is the active engine for the given language."""
    if lang != "en":
        return False
    return os.getenv("TTS_ENGINE_EN", "chatterbox").lower() == "elevenlabs"


def resolve_voice_id(voice: str) -> str:
    """Resolve a voice label or chatterbox legacy label to an ElevenLabs voice_id."""
    if voice in ELEVENLABS_VOICES_EN:
        return ELEVENLABS_VOICES_EN[voice]
    if voice in LEGACY_VOICE_MAP_EN:
        return ELEVENLABS_VOICES_EN[LEGACY_VOICE_MAP_EN[voice]]
    # Already a raw voice_id?
    if len(voice) == 20 and voice.isalnum():
        return voice
    raise ValueError(f"Unknown voice label: {voice!r}")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def apply_modifier(base: dict, modifier_name: str) -> dict:
    """Apply a character voice-style modifier on top of a section base.

    Clamps to: stability ∈ [0.40, 1.0], style ∈ [0,1], speed ∈ [0.70, 1.2].

    Stability floor at 0.40 (raised 2026-04-27 from 0.0) prevents the
    "speaking too fast and randomly" failure mode when a `nervous` or
    `small` modifier stacks on top of an already-low phase_1 base. Per
    ElevenLabs docs: stability <0.30 risks overly random performances.
    """
    mod = CHARACTER_VOICE_MODIFIERS_EN.get(modifier_name)
    if not mod:
        return dict(base)
    return {
        "stability":        _clamp(base["stability"] + mod["stability_offset"], 0.40, 1.0),
        "similarity_boost": base.get("similarity_boost", 0.75),
        "style":            _clamp(base["style"] + mod["style_offset"], 0.0, 1.0),
        "speed":            _clamp(base["speed"] + mod["speed_offset"], 0.70, 1.2),
    }


def chatterbox_to_elevenlabs(exaggeration: float, cfg_weight: float, speed: float) -> dict:
    """Translate Chatterbox params → ElevenLabs params (formula-based).

    Tuned 2026-04-27 for English emotional warmth: original formula gave
    stability ≈ 0.75 / style ≈ 0.10 from default chatterbox params, which
    sounded flat (high stability + zero style = "consistent narration" mode
    with no expressivity).

    New formula: stab = 1.0 - cfg*1.1 (more aggressive looseness),
                 style = exag*0.6 (more aggressive expressivity).

    Used by V2 short-story call sites where the audio_assembly chatterbox-
    style param dicts (NORMAL_TTS, HOOK_TTS, PHRASE_TTS) are now picked to
    map to the desired ElevenLabs values via this formula.
    """
    return {
        "stability":        _clamp(1.0 - cfg_weight * 1.1, 0.40, 0.95),
        "similarity_boost": 0.75,
        "style":            _clamp(exaggeration * 0.6, 0.0, 0.50),
        "speed":            _clamp(speed, 0.70, 1.2),
    }


# ────────────────────────────────────────────────────────────────────────
#  SSML / pause handling
# ────────────────────────────────────────────────────────────────────────

# Pauses below this threshold render inline as <break time="..."/> SSML
# tags inside a TTS chunk, producing natural breath rhythm. Pauses at or
# above this threshold stay as discrete silence inserts at the assembly
# level (audio_assembly handles the segment break).
INLINE_PAUSE_THRESHOLD_MS = 2000

# ElevenLabs warns: more than ~3 break tags in a single generation can
# cause prosody instability. We cap and split if a chunk exceeds this.
MAX_INLINE_BREAKS_PER_CHUNK = 3


def convert_short_pauses_to_breaks(text: str,
                                   threshold_ms: int = INLINE_PAUSE_THRESHOLD_MS) -> str:
    """Replace `[PAUSE: <ms>]` tags below `threshold_ms` with inline SSML
    `<break time="<s>s"/>` tags so ElevenLabs renders natural breath inside
    a single TTS chunk. Longer pauses are left as-is (audio assembly converts
    them to silence inserts at segment boundaries).
    """
    def _replace(m):
        ms = int(m.group(1))
        if ms < threshold_ms:
            return f' <break time="{ms/1000:.2f}s"/> '
        return m.group(0)
    return re.sub(r'\[PAUSE:\s*(\d+)\]', _replace, text)


# ────────────────────────────────────────────────────────────────────────
#  Core TTS call
# ────────────────────────────────────────────────────────────────────────

def _normalize_text(text: str, is_phrase: bool) -> str:
    """Match the same normalization the chatterbox path applies."""
    text = re.sub(r'\b[A-Z]{3,}\b', lambda m: m.group(0).capitalize(), text)
    if is_phrase:
        text = f"... {text}"
    return text


def _split_at_sentence_boundary(text: str, soft_limit: int = SOFT_LIMIT) -> list[str]:
    """Split a long passage at sentence boundaries into chunks ≤ soft_limit chars."""
    if len(text) <= soft_limit:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) + 1 > soft_limit and buf:
            chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        chunks.append(buf.strip())
    return chunks


def tts_eleven_raw(text: str, voice: str, *,
                   stability: float, similarity_boost: float, style: float, speed: float,
                   is_phrase: bool = False, timeout: float = 180.0,
                   previous_text: str = "", next_text: str = "") -> AudioSegment:
    """Single ElevenLabs TTS call → AudioSegment (MP3 decoded via pydub).

    Caller passes section-correct ElevenLabs params (preferred over the
    chatterbox-formula path).

    `previous_text` / `next_text` (added 2026-04-27): pass surrounding
    chunks (last ~300 chars / first ~200 chars respectively) so ElevenLabs
    maintains tonal continuity across long-story chunk boundaries. Without
    these, the voice resets emotional state at every segment boundary,
    flattening the multi-phase arc.
    """
    text = _normalize_text(text, is_phrase)
    if not text or not text.strip():
        return AudioSegment.silent(duration=200)

    # Defensive: split at sentence boundaries if over soft limit.
    if len(text) > SOFT_LIMIT:
        print(f"     [eleven] chunk {len(text)} chars > {SOFT_LIMIT}, splitting")
        chunks = _split_at_sentence_boundary(text, SOFT_LIMIT)
        out = AudioSegment.empty()
        for c in chunks:
            out += tts_eleven_raw(c, voice, stability=stability,
                                  similarity_boost=similarity_boost, style=style,
                                  speed=speed, is_phrase=False, timeout=timeout,
                                  previous_text=previous_text, next_text=next_text)
        return out

    voice_id = resolve_voice_id(voice)
    url = ELEVENLABS_URL.format(voice_id=voice_id) + f"?output_format={ELEVENLABS_OUTPUT_FORMAT}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": _clamp(stability, 0.0, 1.0),
            "similarity_boost": _clamp(similarity_boost, 0.0, 1.0),
            "style": _clamp(style, 0.0, 1.0),
            "speed": _clamp(speed, 0.70, 1.2),
        },
    }
    if previous_text:
        body["previous_text"] = previous_text[-300:]
    if next_text:
        body["next_text"] = next_text[:200]

    last_err = None
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.post(url, headers=headers, json=body, timeout=timeout)
                if resp.status_code == 200 and len(resp.content) > 200:
                    return AudioSegment.from_file(io.BytesIO(resp.content), format="mp3")
                last_err = f"http={resp.status_code} body={resp.text[:200]}"
            except Exception as e:
                last_err = repr(e)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))

    print(f"     [eleven] FAILED voice={voice} text={text[:40]!r}  err={last_err}")
    word_count = len(text.split())
    return AudioSegment.silent(duration=max(500, word_count * 300))


def tts_eleven_compat(text: str, voice: str, exaggeration: float = 0.45,
                      cfg_weight: float = 0.5, speed: float = 0.85,
                      is_phrase: bool = False, timeout: float = 180.0,
                      previous_text: str = "", next_text: str = "") -> AudioSegment:
    """Drop-in replacement for chatterbox `generate_tts(...)`.

    Same signature, formula-translated params, English-only voices. Optional
    `previous_text` / `next_text` for tonal continuity across long-story
    chunks (no-op for V2 short stories which are short enough).
    """
    params = chatterbox_to_elevenlabs(exaggeration, cfg_weight, speed)
    return tts_eleven_raw(text, voice, is_phrase=is_phrase, timeout=timeout,
                          previous_text=previous_text, next_text=next_text, **params)
