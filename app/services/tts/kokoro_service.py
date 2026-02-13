"""Kokoro TTS integration for text-to-speech synthesis.

Uses Kokoro-82M (https://huggingface.co/hexgrad/Kokoro-82M) — a lightweight
82M-parameter TTS model that runs well on CPU. No GPU required.
"""

import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Content-type speed profiles ──────────────────────────────────────
# speed: <1 = slower, 1 = normal, >1 = faster
CONTENT_TYPE_PROFILES: Dict[str, dict] = {
    "story": {"speed": 0.9},
    "poem":  {"speed": 0.8},
    "song":  {"speed": 0.75},
}

# ── Emotion speed adjustments ────────────────────────────────────────
EMOTION_PROFILES: Dict[str, dict] = {
    "sleepy":      {"speed": 0.7},
    "gentle":      {"speed": 0.8},
    "calm":        {"speed": 0.85},
    "excited":     {"speed": 1.1},
    "curious":     {"speed": 0.95},
    "adventurous": {"speed": 1.05},
    "mysterious":  {"speed": 0.8},
    "joyful":      {"speed": 1.05},
    "dramatic":    {"speed": 0.85},
    "whispering":  {"speed": 0.75},
    "rhythmic":    {"speed": 0.85},
    "singing":     {"speed": 0.8},
    "humming":     {"speed": 0.75},
}

# Markers that produce silence instead of speech
PAUSE_MARKERS = {
    "pause": 1000,           # 1 second
    "dramatic_pause": 2000,  # 2 seconds
}

# All recognised emotion marker tags (used for parsing)
_MARKER_RE = re.compile(
    r"\["
    r"(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
    r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
    r"HUMMING|PAUSE|laugh|chuckle)"
    r"\]",
    re.IGNORECASE,
)

# ── Kokoro voice ID mapping ──────────────────────────────────────────
# Maps our app voice IDs → Kokoro voice IDs
KOKORO_VOICE_MAP: Dict[str, str] = {
    "luna":    "af_heart",     # gentle female
    "atlas":   "am_adam",      # warm male
    "aria":    "af_bella",     # playful female
    "cosmo":   "am_puck",      # expressive male
    "whisper": "af_sky",       # soft female
    "melody":  "af_nova",      # musical female
}


class KokoroTTSService:
    """Text-to-speech service powered by Kokoro-82M.

    The pipeline is loaded lazily on first synthesis call and kept as a
    singleton for the lifetime of the process.
    """

    _pipeline = None  # class-level singleton

    def __init__(self, cache_dir: str = "./cache/tts"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("KokoroTTSService initialised (cache=%s)", self.cache_dir)

    # ── Pipeline loading ─────────────────────────────────────────────

    def _ensure_pipeline(self):
        """Lazily load the Kokoro KPipeline (singleton)."""
        if KokoroTTSService._pipeline is not None:
            return

        from kokoro import KPipeline

        logger.info("Loading Kokoro-82M pipeline …")
        KokoroTTSService._pipeline = KPipeline(lang_code='a')
        logger.info("Kokoro pipeline loaded successfully")

    # ── Public API ────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice_id: str = "luna",
        content_type: str = "story",
        tone: str = "calm",
        speed_override: Optional[float] = None,
    ) -> bytes:
        """Synthesize text to MP3 audio.

        Parameters
        ----------
        text : str
            Content text, may contain emotion markers like ``[EXCITED]``.
        voice_id : str
            Voice identifier (mapped to a Kokoro voice).
        content_type : str
            One of ``story``, ``poem``, ``song``.
        tone : str
            Tone preset name (``calm``, ``relaxing``, ``dramatic``, …).
        speed_override : float | None
            Manual speed override; bypasses all profile/tone logic when set.

        Returns
        -------
        bytes
            MP3-encoded audio.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Check cache first
        cache_key = self._cache_key(text, voice_id, content_type, tone, speed_override)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        self._ensure_pipeline()

        # Resolve Kokoro voice ID
        kokoro_voice = KOKORO_VOICE_MAP.get(voice_id, "af_heart")

        # Import tone presets from voice_service
        from app.services.tts.voice_service import TONE_PRESETS
        tone_mod = TONE_PRESETS.get(tone, TONE_PRESETS["calm"])

        # Base speed from content type
        base = CONTENT_TYPE_PROFILES.get(content_type, CONTENT_TYPE_PROFILES["story"])

        # Parse the text into (emotion | None, segment_text) pairs
        segments = self._parse_emotion_segments(text)

        audio_chunks: list = []

        for emotion, segment_text in segments:
            segment_text = segment_text.strip()
            if not segment_text:
                continue

            # Handle pause markers → silence
            if emotion and emotion.lower() in PAUSE_MARKERS:
                ms = PAUSE_MARKERS[emotion.lower()]
                audio_chunks.append(self._silence_bytes(ms))
                continue

            # Handle paralinguistic tags → short silence
            if emotion and emotion.lower() in ("laugh", "chuckle"):
                audio_chunks.append(self._silence_bytes(500))
                continue

            # Determine speed
            if speed_override is not None:
                speed = speed_override
            else:
                profile = EMOTION_PROFILES.get(emotion, base) if emotion else base
                speed = profile["speed"] * tone_mod.get("speed_scale", 1.0)

            # Clamp speed
            speed = max(0.5, min(2.0, speed))

            # Generate audio for this segment
            wav_data = self._generate_segment(segment_text, kokoro_voice, speed)
            if wav_data is not None:
                audio_chunks.append(wav_data)

        if not audio_chunks:
            raise RuntimeError("No audio produced — text may have been empty after parsing")

        # Concatenate all chunks with short pauses
        combined = self._concatenate(audio_chunks, pause_ms=300)

        # Convert to MP3
        mp3_bytes = self._to_mp3(combined)

        # Cache
        self._write_cache(cache_key, mp3_bytes)

        logger.info(
            "Synthesised %d chars → %d bytes MP3 (voice=%s→%s, type=%s, tone=%s)",
            len(text), len(mp3_bytes), voice_id, kokoro_voice, content_type, tone,
        )
        return mp3_bytes

    # ── Parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_emotion_segments(text: str) -> List[Tuple[Optional[str], str]]:
        """Split text at emotion markers."""
        parts: list = []
        last_end = 0
        current_emotion: Optional[str] = None

        for m in _MARKER_RE.finditer(text):
            before = text[last_end:m.start()]
            if before.strip():
                parts.append((current_emotion, before))
            current_emotion = m.group(1).lower()
            last_end = m.end()

        tail = text[last_end:]
        if tail.strip():
            parts.append((current_emotion, tail))

        if not parts:
            parts.append((None, text))

        return parts

    # ── Audio generation ──────────────────────────────────────────────

    def _generate_segment(
        self,
        text: str,
        kokoro_voice: str,
        speed: float,
    ) -> Optional[bytes]:
        """Generate WAV bytes for a text segment using Kokoro."""
        import soundfile as sf
        import numpy as np

        pipeline = KokoroTTSService._pipeline
        all_audio = []

        try:
            generator = pipeline(text, voice=kokoro_voice, speed=speed)
            for gs, ps, audio in generator:
                if audio is not None:
                    all_audio.append(audio)
        except Exception as e:
            logger.error("Kokoro generation error: %s", e)
            return None

        if not all_audio:
            return None

        # Concatenate all generated audio segments
        combined = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]

        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format="WAV")
        return buf.getvalue()

    @staticmethod
    def _silence_bytes(duration_ms: int) -> bytes:
        """Create silent WAV bytes of the given duration."""
        from pydub import AudioSegment
        silence = AudioSegment.silent(duration=duration_ms, frame_rate=24000)
        buf = io.BytesIO()
        silence.export(buf, format="wav")
        return buf.getvalue()

    # ── Audio post-processing ─────────────────────────────────────────

    @staticmethod
    def _concatenate(wav_chunks: list, pause_ms: int = 300) -> bytes:
        """Concatenate WAV byte chunks with short silence gaps."""
        from pydub import AudioSegment

        combined = None
        pause = AudioSegment.silent(duration=pause_ms)

        for chunk in wav_chunks:
            if not chunk:
                continue
            seg = AudioSegment.from_file(io.BytesIO(chunk), format="wav")
            if combined is None:
                combined = seg
            else:
                combined = combined + pause + seg

        if combined is None:
            return b""

        buf = io.BytesIO()
        combined.export(buf, format="wav")
        return buf.getvalue()

    @staticmethod
    def _to_mp3(wav_bytes: bytes, bitrate: str = "128k") -> bytes:
        """Convert WAV bytes to MP3 with normalisation."""
        from pydub import AudioSegment

        audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        # Normalise to -3 dBFS
        change = -3.0 - audio.dBFS
        audio = audio.apply_gain(change)
        # Gentle fade in/out
        audio = audio.fade_in(500).fade_out(1500)

        buf = io.BytesIO()
        audio.export(buf, format="mp3", bitrate=bitrate)
        return buf.getvalue()

    # ── Caching ───────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(
        text: str, voice_id: str, content_type: str,
        tone: str, speed_override: Optional[float],
    ) -> str:
        raw = f"{text}:{voice_id}:{content_type}:{tone}:{speed_override}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _read_cache(self, key: str) -> Optional[bytes]:
        path = self.cache_dir / f"{key}.mp3"
        if path.exists() and path.stat().st_size > 0:
            logger.debug("TTS cache hit: %s", key[:8])
            return path.read_bytes()
        return None

    def _write_cache(self, key: str, data: bytes) -> None:
        path = self.cache_dir / f"{key}.mp3"
        path.write_bytes(data)

    def clear_cache(self) -> int:
        """Delete all cached MP3 files."""
        count = 0
        for f in self.cache_dir.glob("*.mp3"):
            f.unlink(missing_ok=True)
            count += 1
        return count
