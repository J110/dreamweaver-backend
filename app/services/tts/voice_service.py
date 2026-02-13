"""Unified voice registry — single source of truth for all TTS voices."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


@dataclass
class Voice:
    """A TTS voice with metadata and Chatterbox reference info."""

    id: str
    name: str
    gender: Gender
    description: str
    description_hi: str = ""
    emotions: List[str] = field(default_factory=list)
    recommended_for: List[str] = field(default_factory=list)
    age_group: str = "general"  # toddler, child, teen, general
    reference_audio: str = ""  # filename inside voice_references_dir
    language: str = "en-US"
    sample_url: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender.value,
            "description": self.description,
            "description_hi": self.description_hi,
            "emotions": self.emotions,
            "recommended_for": self.recommended_for,
            "age_group": self.age_group,
            "language": self.language,
            "sample_url": self.sample_url,
        }


# ── Voice Registry ────────────────────────────────────────────────────
# This is the ONLY place voices are defined.  The audio router, Flutter
# app, and all other components read from this registry.

VOICES: Dict[str, Voice] = {
    "luna": Voice(
        id="luna",
        name="Luna",
        gender=Gender.FEMALE,
        description="Gentle and soothing — perfect for bedtime stories",
        description_hi="Komal aur sukoon bhari — sone ki kahaaniyon ke liye",
        emotions=["calm", "gentle", "soothing", "sleepy"],
        recommended_for=["story", "poem"],
        age_group="general",
        reference_audio="luna.wav",
    ),
    "atlas": Voice(
        id="atlas",
        name="Atlas",
        gender=Gender.MALE,
        description="Warm and comforting — like a favourite uncle reading",
        description_hi="Garmahat bhari — pyare chacha ki tarah",
        emotions=["warm", "adventurous", "reassuring", "calm"],
        recommended_for=["story"],
        age_group="general",
        reference_audio="atlas.wav",
    ),
    "aria": Voice(
        id="aria",
        name="Aria",
        gender=Gender.FEMALE,
        description="Playful and energetic — great for fun tales",
        description_hi="Chanchal aur urjavan — mazedar kahaaniyon ke liye",
        emotions=["playful", "excited", "cheerful", "joyful"],
        recommended_for=["story"],
        age_group="child",
        reference_audio="aria.wav",
    ),
    "cosmo": Voice(
        id="cosmo",
        name="Cosmo",
        gender=Gender.MALE,
        description="Adventurous and expressive — brings stories to life",
        description_hi="Saahasi aur bhaavpurna — kahaaniyon mein jaan daalte hain",
        emotions=["adventurous", "curious", "excited", "dramatic"],
        recommended_for=["story"],
        age_group="child",
        reference_audio="cosmo.wav",
    ),
    "whisper": Voice(
        id="whisper",
        name="Whisper",
        gender=Gender.NEUTRAL,
        description="Very soft and calming — ideal for relaxation",
        description_hi="Bahut komal — aaraam ke liye perfect",
        emotions=["calm", "soothing", "peaceful", "sleepy"],
        recommended_for=["story", "poem"],
        age_group="general",
        reference_audio="whisper.wav",
    ),
    "melody": Voice(
        id="melody",
        name="Melody",
        gender=Gender.FEMALE,
        description="Musical and melodic — best for songs and lullabies",
        description_hi="Sureeli — gaanon aur loriyon ke liye sabse achhi",
        emotions=["musical", "gentle", "lyrical", "joyful"],
        recommended_for=["song", "poem"],
        age_group="general",
        reference_audio="melody.wav",
    ),
}


# ── Tone Presets ──────────────────────────────────────────────────────
# Scale factors applied on top of content-type base profiles.

TONE_PRESETS: Dict[str, dict] = {
    "calm": {
        "exaggeration_scale": 0.7,
        "cfg_scale": 0.8,
        "speed_scale": 0.9,
        "description": "Slow and soothing — the default bedtime voice",
        "description_hi": "Dhheema aur sukoon bhara — sone ke liye perfect",
        "icon": "moon",
    },
    "relaxing": {
        "exaggeration_scale": 0.5,
        "cfg_scale": 0.7,
        "speed_scale": 0.8,
        "description": "Very subdued and peaceful — deep relaxation",
        "description_hi": "Bahut shant — gehri shaanti ke liye",
        "icon": "spa",
    },
    "dramatic": {
        "exaggeration_scale": 1.3,
        "cfg_scale": 1.0,
        "speed_scale": 1.05,
        "description": "Animated and expressive — brings stories to life",
        "description_hi": "Jaandar — kahaaniyon mein jaan daalti hai",
        "icon": "sparkles",
    },
    "energetic": {
        "exaggeration_scale": 1.5,
        "cfg_scale": 1.1,
        "speed_scale": 1.15,
        "description": "Bright and lively — for fun, upbeat content",
        "description_hi": "Chamakdar aur josh bhari — mazedaar content ke liye",
        "icon": "bolt",
    },
    "neutral": {
        "exaggeration_scale": 1.0,
        "cfg_scale": 1.0,
        "speed_scale": 1.0,
        "description": "Natural delivery — no extra styling",
        "description_hi": "Natural awaaz — bina kisi badlaav ke",
        "icon": "circle",
    },
}


class VoiceService:
    """Service for querying and recommending voices."""

    @staticmethod
    def get_available_voices() -> List[Voice]:
        return list(VOICES.values())

    @staticmethod
    def get_voice_by_id(voice_id: str) -> Optional[Voice]:
        return VOICES.get(voice_id.lower())

    @staticmethod
    def get_voices_by_gender(gender: Gender) -> List[Voice]:
        return [v for v in VOICES.values() if v.gender == gender]

    @staticmethod
    def get_voices_by_emotion(emotion: str) -> List[Voice]:
        return [v for v in VOICES.values() if emotion.lower() in v.emotions]

    @staticmethod
    def get_voices_for_content_type(content_type: str) -> List[Voice]:
        return [v for v in VOICES.values() if content_type in v.recommended_for]

    @staticmethod
    def get_voices_for_age(age: int) -> List[Voice]:
        if age <= 5:
            return [
                v for v in VOICES.values()
                if v.age_group in ("child", "general")
            ]
        return [v for v in VOICES.values() if v.age_group != "teen"]

    @staticmethod
    def get_recommended_voice(
        child_age: int = 5,
        content_type: str = "story",
        preference: str = "calm",
    ) -> Voice:
        candidates = [
            v for v in VOICES.values()
            if content_type in v.recommended_for
        ]
        if not candidates:
            candidates = list(VOICES.values())

        for v in candidates:
            if preference in v.emotions:
                return v

        return candidates[0]

    @staticmethod
    def validate_voice_id(voice_id: str) -> bool:
        return voice_id.lower() in VOICES

    @staticmethod
    def get_voices_as_dicts() -> List[dict]:
        return [v.to_dict() for v in VOICES.values()]

    @staticmethod
    def get_tone_presets() -> Dict[str, dict]:
        return TONE_PRESETS

    @staticmethod
    def get_tone_presets_for_api() -> List[dict]:
        return [
            {
                "name": name,
                "description": p["description"],
                "description_hi": p["description_hi"],
                "icon": p["icon"],
            }
            for name, p in TONE_PRESETS.items()
        ]
