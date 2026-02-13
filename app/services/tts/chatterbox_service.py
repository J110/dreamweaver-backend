"""Chatterbox TTS integration for text-to-speech synthesis.

Uses Chatterbox (https://github.com/resemble-ai/chatterbox) for
zero-shot voice cloning with emotion exaggeration control.
Falls back gracefully when the library or GPU is unavailable.
"""

import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Content-type base profiles ────────────────────────────────────────
# exaggeration: 0=monotone … 1+=very expressive
# cfg_weight:   lower=slower/deliberate, higher=faster/energetic

CONTENT_TYPE_PROFILES: Dict[str, dict] = {
    "story": {"exaggeration": 0.6, "cfg_weight": 0.4},
    "poem":  {"exaggeration": 0.4, "cfg_weight": 0.3},
    "song":  {"exaggeration": 0.8, "cfg_weight": 0.25},
}

# ── Emotion profiles (override content-type base when a marker is hit) ─
EMOTION_PROFILES: Dict[str, dict] = {
    "sleepy":      {"exaggeration": 0.2, "cfg_weight": 0.3},
    "gentle":      {"exaggeration": 0.3, "cfg_weight": 0.4},
    "calm":        {"exaggeration": 0.3, "cfg_weight": 0.5},
    "excited":     {"exaggeration": 0.8, "cfg_weight": 0.5},
    "curious":     {"exaggeration": 0.5, "cfg_weight": 0.5},
    "adventurous": {"exaggeration": 0.7, "cfg_weight": 0.45},
    "mysterious":  {"exaggeration": 0.5, "cfg_weight": 0.35},
    "joyful":      {"exaggeration": 0.7, "cfg_weight": 0.5},
    "dramatic":    {"exaggeration": 0.8, "cfg_weight": 0.35},
    "whispering":  {"exaggeration": 0.15, "cfg_weight": 0.3},
    "rhythmic":    {"exaggeration": 0.4, "cfg_weight": 0.3},
    "singing":     {"exaggeration": 0.85, "cfg_weight": 0.2},
    "humming":     {"exaggeration": 0.3, "cfg_weight": 0.2},
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


class ChatterboxTTSService:
    """Text-to-speech service powered by Chatterbox.

    The model is loaded lazily on first synthesis call and kept as a
    singleton for the lifetime of the process.
    """

    _model = None  # class-level singleton

    def __init__(
        self,
        voice_references_dir: str = "./voice_references",
        cache_dir: str = "./cache/tts",
        device: str = "auto",
    ):
        self.voice_references_dir = Path(voice_references_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._device = device

        logger.info(
            "ChatterboxTTSService initialised "
            "(refs=%s, cache=%s, device=%s)",
            self.voice_references_dir, self.cache_dir, device,
        )

    # ── Model loading ─────────────────────────────────────────────────

    def _ensure_model(self):
        """Lazily load the Chatterbox model (singleton)."""
        if ChatterboxTTSService._model is not None:
            return

        import torch
        from chatterbox.tts import ChatterboxTTS

        device = self._device
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        logger.info("Loading Chatterbox model on %s …", device)
        ChatterboxTTSService._model = ChatterboxTTS.from_pretrained(device=device)
        logger.info("Chatterbox model loaded successfully")

    # ── Public API ────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice_id: str = "luna",
        content_type: str = "story",
        tone: str = "calm",
        exaggeration_override: Optional[float] = None,
        cfg_weight_override: Optional[float] = None,
    ) -> bytes:
        """Synthesize text to MP3 audio.

        Parameters
        ----------
        text : str
            Content text, may contain emotion markers like ``[EXCITED]``.
        voice_id : str
            Voice identifier (must have a matching reference WAV).
        content_type : str
            One of ``story``, ``poem``, ``song``.
        tone : str
            Tone preset name (``calm``, ``relaxing``, ``dramatic``, …).
        exaggeration_override / cfg_weight_override : float | None
            Manual overrides; bypass all profile/tone logic when set.

        Returns
        -------
        bytes
            MP3-encoded audio.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Check cache first
        cache_key = self._cache_key(text, voice_id, content_type, tone,
                                    exaggeration_override, cfg_weight_override)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        self._ensure_model()

        # Resolve voice reference audio path
        ref_path = self._resolve_reference(voice_id)

        # Import tone presets from voice_service (avoid circular at module level)
        from app.services.tts.voice_service import TONE_PRESETS
        tone_mod = TONE_PRESETS.get(tone, TONE_PRESETS["calm"])

        # Base profile from content type
        base = CONTENT_TYPE_PROFILES.get(
            content_type, CONTENT_TYPE_PROFILES["story"]
        )

        # Parse the text into (emotion | None, segment_text) pairs
        segments = self._parse_emotion_segments(text)

        audio_chunks: list[bytes] = []

        for emotion, segment_text in segments:
            segment_text = segment_text.strip()
            if not segment_text:
                continue

            # Handle pause markers → silence
            if emotion and emotion.lower() in PAUSE_MARKERS:
                ms = PAUSE_MARKERS[emotion.lower()]
                audio_chunks.append(self._silence_wav(ms))
                continue

            # Handle paralinguistic tags (laugh, chuckle) → short silence
            if emotion and emotion.lower() in ("laugh", "chuckle"):
                audio_chunks.append(self._silence_wav(500))
                continue

            # Determine exaggeration / cfg_weight
            if exaggeration_override is not None:
                exag = exaggeration_override
            else:
                profile = EMOTION_PROFILES.get(emotion, base) if emotion else base
                exag = profile["exaggeration"] * tone_mod["exaggeration_scale"]

            if cfg_weight_override is not None:
                cfg = cfg_weight_override
            else:
                profile = EMOTION_PROFILES.get(emotion, base) if emotion else base
                cfg = profile["cfg_weight"] * tone_mod["cfg_scale"]

            # Clamp
            exag = max(0.0, min(1.5, exag))
            cfg = max(0.1, min(1.0, cfg))

            # Sub-chunk long segments (≤600 chars ≈ 40s of speech)
            sub_chunks = self._split_into_chunks(segment_text, max_chars=600)
            for chunk in sub_chunks:
                wav_bytes = self._generate_chunk(chunk, ref_path, exag, cfg)
                audio_chunks.append(wav_bytes)

        if not audio_chunks:
            raise RuntimeError("No audio produced — text may have been empty after parsing")

        # Concatenate all chunks with short pauses
        combined = self._concatenate(audio_chunks, pause_ms=400)

        # Normalise and convert to MP3
        mp3_bytes = self._to_mp3(combined)

        # Cache
        self._write_cache(cache_key, mp3_bytes)

        logger.info(
            "Synthesised %d chars → %d bytes MP3 (voice=%s, type=%s, tone=%s)",
            len(text), len(mp3_bytes), voice_id, content_type, tone,
        )
        return mp3_bytes

    # ── Parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_emotion_segments(text: str) -> List[Tuple[Optional[str], str]]:
        """Split text at emotion markers.

        Returns a list of ``(emotion_or_None, text_segment)`` tuples.
        """
        parts: list[Tuple[Optional[str], str]] = []
        last_end = 0
        current_emotion: Optional[str] = None

        for m in _MARKER_RE.finditer(text):
            # Text before this marker belongs to the previous emotion
            before = text[last_end:m.start()]
            if before.strip():
                parts.append((current_emotion, before))

            current_emotion = m.group(1).lower()
            last_end = m.end()

        # Remaining text after last marker
        tail = text[last_end:]
        if tail.strip():
            parts.append((current_emotion, tail))

        # If no markers found, return the whole text with no emotion
        if not parts:
            parts.append((None, text))

        return parts

    # ── Audio generation ──────────────────────────────────────────────

    def _generate_chunk(
        self,
        text: str,
        ref_path: str,
        exaggeration: float,
        cfg_weight: float,
    ) -> bytes:
        """Generate a single WAV chunk via Chatterbox."""
        import torch
        import torchaudio as ta

        model = ChatterboxTTSService._model
        wav = model.generate(
            text,
            audio_prompt_path=ref_path,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
        )

        buf = io.BytesIO()
        ta.save(buf, wav.cpu(), model.sr, format="wav")
        return buf.getvalue()

    @staticmethod
    def _silence_wav(duration_ms: int) -> bytes:
        """Create a silent WAV of the given duration."""
        from pydub import AudioSegment
        silence = AudioSegment.silent(duration=duration_ms, frame_rate=24000)
        buf = io.BytesIO()
        silence.export(buf, format="wav")
        return buf.getvalue()

    # ── Text chunking ─────────────────────────────────────────────────

    @staticmethod
    def _split_into_chunks(text: str, max_chars: int = 600) -> List[str]:
        """Split text at sentence boundaries, keeping chunks ≤ max_chars."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= max_chars:
                current += (" " if current else "") + sentence
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())

        return chunks or [text]

    # ── Audio post-processing ─────────────────────────────────────────

    @staticmethod
    def _concatenate(wav_chunks: List[bytes], pause_ms: int = 400) -> bytes:
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
        """Convert WAV bytes to MP3."""
        from pydub import AudioSegment

        audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        # Normalise to -3 dBFS
        change = -3.0 - audio.dBFS
        audio = audio.apply_gain(change)
        # Fade in/out for smooth listening
        audio = audio.fade_in(1000).fade_out(2000)

        buf = io.BytesIO()
        audio.export(buf, format="mp3", bitrate=bitrate)
        return buf.getvalue()

    # ── Voice reference ───────────────────────────────────────────────

    def _resolve_reference(self, voice_id: str) -> str:
        """Return the absolute path to the voice reference WAV file."""
        from app.services.tts.voice_service import VOICES

        voice = VOICES.get(voice_id)
        if voice is None:
            raise ValueError(f"Unknown voice: {voice_id}")

        ref_path = self.voice_references_dir / voice.reference_audio
        if not ref_path.exists():
            raise FileNotFoundError(
                f"Voice reference not found: {ref_path}. "
                f"Run scripts/generate_voice_references.py first."
            )
        return str(ref_path)

    # ── Caching ───────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(
        text: str,
        voice_id: str,
        content_type: str,
        tone: str,
        exaggeration_override: Optional[float],
        cfg_weight_override: Optional[float],
    ) -> str:
        raw = f"{text}:{voice_id}:{content_type}:{tone}:{exaggeration_override}:{cfg_weight_override}"
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
        """Delete all cached MP3 files. Returns count of files removed."""
        count = 0
        for f in self.cache_dir.glob("*.mp3"):
            f.unlink(missing_ok=True)
            count += 1
        return count
