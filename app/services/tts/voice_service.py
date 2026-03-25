"""Unified voice registry — single source of truth for all TTS voices."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Tuple

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


# ── Funny Short Character Voices ─────────────────────────────
# Completely separate from sleep voices. Used only by the funny
# shorts pipeline. Never mixed with sleep story generation.

FUNNY_VOICES: Dict[str, Voice] = {
    "high_pitch_cartoon": Voice(
        id="high_pitch_cartoon",
        name="Mouse",
        gender=Gender.NEUTRAL,
        description="Squeaky, high, energetic — Minnie Mouse energy. Reacts with alarm and panic.",
        emotions=["alarm", "panic", "confusion", "surprise"],
        recommended_for=["funny_short"],
        age_group="child",
        reference_audio="high_pitch_cartoon.wav",
    ),
    "comedic_villain": Voice(
        id="comedic_villain",
        name="Croc",
        gender=Gender.NEUTRAL,
        description="Dramatic, deep, theatrical crocodile villain. Grand plans, spectacular defeat.",
        emotions=["dramatic", "self-important", "outraged", "defeated"],
        recommended_for=["funny_short"],
        age_group="child",
        reference_audio="comedic_villain.wav",
    ),
    "young_sweet": Voice(
        id="young_sweet",
        name="Sweet",
        gender=Gender.FEMALE,
        description="Young, innocent-sounding but sarcastic. Sweet tone, cutting content. Unbothered.",
        emotions=["sarcastic", "deadpan", "unbothered", "dry"],
        recommended_for=["funny_short"],
        age_group="child",
        reference_audio="young_sweet.wav",
    ),
    "mysterious_witch": Voice(
        id="mysterious_witch",
        name="Witch",
        gender=Gender.FEMALE,
        description="Dark, low-pitched, mysterious, ominous. Makes everything a dark prophecy.",
        emotions=["ominous", "dramatic", "mysterious", "deadpan"],
        recommended_for=["funny_short"],
        age_group="child",
        reference_audio="mysterious_witch.wav",
    ),
    "musical_original": Voice(
        id="musical_original",
        name="Musical",
        gender=Gender.NEUTRAL,
        description="Rhythmic, mature, poetic, almost singing. Delivers nonsense verse seriously.",
        emotions=["rhythmic", "poetic", "whimsical", "serious"],
        recommended_for=["funny_short"],
        age_group="general",
        reference_audio="musical_original.wav",
    ),
}


# ── Funny Voice TTS Parameters ──────────────────────────────

FUNNY_VOICE_PARAMS: Dict[str, dict] = {
    "high_pitch_cartoon": {
        "exaggeration": 0.80,
        "cfg_weight": 0.60,
        "speed": 0.95,
    },
    "comedic_villain": {
        "exaggeration": 0.85,
        "cfg_weight": 0.55,
        "speed": 0.88,
    },
    "young_sweet": {
        "exaggeration": 0.55,
        "cfg_weight": 0.50,
        "speed": 0.92,
    },
    "mysterious_witch": {
        "exaggeration": 0.65,
        "cfg_weight": 0.45,
        "speed": 0.85,
    },
    "musical_original": {
        "exaggeration": 0.70,
        "cfg_weight": 0.55,
        "speed": 0.90,
    },
}

FUNNY_PUNCHLINE_PARAMS: Dict[str, dict] = {
    "high_pitch_cartoon": {
        "exaggeration": 0.88,
        "speed_multiplier": 0.90,
    },
    "comedic_villain": {
        "exaggeration": 0.92,
        "speed_multiplier": 0.85,
    },
    "young_sweet": {
        "exaggeration": 0.50,
        "speed_multiplier": 0.95,
    },
    "mysterious_witch": {
        "exaggeration": 0.70,
        "speed_multiplier": 0.80,
    },
    "musical_original": {
        "exaggeration": 0.78,
        "speed_multiplier": 0.88,
    },
}

# ── Funny Voice → Character Loop Mapping ─────────────────────

FUNNY_VOICE_MAP: Dict[str, str] = {
    "MOUSE": "high_pitch_cartoon",
    "CROC": "comedic_villain",
    "SWEET": "young_sweet",
    "WITCH": "mysterious_witch",
    "MUSICAL": "musical_original",
}

CHARACTER_LOOP_MAP: Dict[str, str] = {
    "MOUSE": "bouncy_cartoon",
    "CROC": "villain_march",
    "WITCH": "mysterious_creep",
    "SWEET": "sweet_innocence",
    "MUSICAL": "poetic_bounce",
}


def get_funny_voice(voice_id: str) -> Optional[Voice]:
    """Get a funny character voice by ID."""
    return FUNNY_VOICES.get(voice_id)


def get_funny_voice_params(voice_id: str, is_punchline: bool = False) -> dict:
    """Get TTS params for a funny voice, with optional punchline boost."""
    params = FUNNY_VOICE_PARAMS.get(voice_id, {}).copy()
    if is_punchline and voice_id in FUNNY_PUNCHLINE_PARAMS:
        punch = FUNNY_PUNCHLINE_PARAMS[voice_id]
        params["exaggeration"] = punch["exaggeration"]
        params["speed"] = params.get("speed", 0.90) * punch["speed_multiplier"]
    return params


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


# ── Mood → Voice ID Mapping ──────────────────────────────────────────
# Descriptive mood-voice names → actual Chatterbox voice file IDs.
# "musical" is the NEW female_4 voice (rhythmic, almost-singing).
VOICE_ID_MAP: Dict[str, str] = {
    "calm":    "female_1",   # luna — slow, soothing, sleepy
    "soft":    "female_2",   # whisper — British clarity, controlled
    "melodic": "female_3",   # aria/melody — playful teenage energy
    "musical": "female_4",   # NEW — rhythmic, almost singing
    "gentle":  "male_2",     # cosmo — warm, comforting male
    "asmr":    "asmr",       # ultra-soft whisper
}

# Hindi equivalents
VOICE_ID_MAP_HI: Dict[str, str] = {
    "calm":    "female_1_hi",
    "soft":    "female_2_hi",
    "melodic": "female_3_hi",
    "musical": "female_4_hi",
    "gentle":  "male_2_hi",
    "asmr":    "asmr_hi",
}


def resolve_voice_id(mood_voice_name: str, lang: str = "en") -> str:
    """Convert mood system voice name to actual Chatterbox voice file ID."""
    if lang == "hi":
        return VOICE_ID_MAP_HI.get(mood_voice_name, mood_voice_name)
    return VOICE_ID_MAP.get(mood_voice_name, mood_voice_name)


# ── Mood × Age × Content-Type Voice Selection Maps ─────────────────
# Each entry: (mood, age_group) → [voice_1, voice_2]
# Uses descriptive names; call resolve_voice_id() to get file IDs.

STORY_VOICE_MAP: Dict[Tuple[str, str], List[str]] = {
    # WIRED
    ("wired", "0-1"):  ["melodic", "gentle"],
    ("wired", "2-5"):  ["melodic", "gentle"],
    ("wired", "6-8"):  ["melodic", "gentle"],
    ("wired", "9-12"): ["soft",    "gentle"],
    # CURIOUS
    ("curious", "0-1"): ["musical", "gentle"],
    ("curious", "2-5"): ["musical", "gentle"],
    ("curious", "6-8"): ["musical", "gentle"],
    ("curious", "9-12"):["soft",    "gentle"],
    # CALM
    ("calm", "0-1"):  ["calm", "asmr"],
    ("calm", "2-5"):  ["calm", "asmr"],
    ("calm", "6-8"):  ["calm", "asmr"],
    ("calm", "9-12"): ["calm", "asmr"],
    # SAD
    ("sad", "0-1"):  ["gentle", "calm"],
    ("sad", "2-5"):  ["gentle", "calm"],
    ("sad", "6-8"):  ["gentle", "calm"],
    ("sad", "9-12"): ["gentle", "calm"],
    # ANXIOUS
    ("anxious", "0-1"):  ["gentle", "calm"],
    ("anxious", "2-5"):  ["gentle", "calm"],
    ("anxious", "6-8"):  ["gentle", "soft"],
    ("anxious", "9-12"): ["gentle", "soft"],
    # ANGRY
    ("angry", "0-1"):  ["melodic", "gentle"],
    ("angry", "2-5"):  ["melodic", "gentle"],
    ("angry", "6-8"):  ["soft",    "gentle"],
    ("angry", "9-12"): ["soft",    "gentle"],
}

LONG_STORY_VOICE_MAP: Dict[Tuple[str, str], List[str]] = {
    # Same as STORY_VOICE_MAP except calm uses gentle instead of asmr
    # (asmr is reserved for Phase 3 in all long stories).
    # WIRED
    ("wired", "0-1"):  ["melodic", "gentle"],
    ("wired", "2-5"):  ["melodic", "gentle"],
    ("wired", "6-8"):  ["melodic", "gentle"],
    ("wired", "9-12"): ["soft",    "gentle"],
    # CURIOUS
    ("curious", "0-1"): ["musical", "gentle"],
    ("curious", "2-5"): ["musical", "gentle"],
    ("curious", "6-8"): ["musical", "gentle"],
    ("curious", "9-12"):["soft",    "gentle"],
    # CALM — gentle instead of asmr (asmr reserved for Phase 3)
    ("calm", "0-1"):  ["calm", "gentle"],
    ("calm", "2-5"):  ["calm", "gentle"],
    ("calm", "6-8"):  ["calm", "gentle"],
    ("calm", "9-12"): ["calm", "gentle"],
    # SAD
    ("sad", "0-1"):  ["gentle", "calm"],
    ("sad", "2-5"):  ["gentle", "calm"],
    ("sad", "6-8"):  ["gentle", "calm"],
    ("sad", "9-12"): ["gentle", "calm"],
    # ANXIOUS
    ("anxious", "0-1"):  ["gentle", "calm"],
    ("anxious", "2-5"):  ["gentle", "calm"],
    ("anxious", "6-8"):  ["gentle", "soft"],
    ("anxious", "9-12"): ["gentle", "soft"],
    # ANGRY
    ("angry", "0-1"):  ["melodic", "gentle"],
    ("angry", "2-5"):  ["melodic", "gentle"],
    ("angry", "6-8"):  ["soft",    "gentle"],
    ("angry", "9-12"): ["soft",    "gentle"],
}

POEM_VOICE_MAP: Dict[Tuple[str, str], List[str]] = {
    # WIRED
    ("wired", "0-1"):  ["melodic", "musical"],
    ("wired", "2-5"):  ["melodic", "musical"],
    ("wired", "6-8"):  ["melodic", "musical"],
    ("wired", "9-12"): ["soft",    "musical"],
    # CURIOUS
    ("curious", "0-1"): ["musical", "calm"],
    ("curious", "2-5"): ["musical", "calm"],
    ("curious", "6-8"): ["musical", "gentle"],
    ("curious", "9-12"):["musical", "soft"],
    # CALM
    ("calm", "0-1"):  ["musical", "calm"],
    ("calm", "2-5"):  ["musical", "calm"],
    ("calm", "6-8"):  ["calm",    "asmr"],
    ("calm", "9-12"): ["calm",    "asmr"],
    # SAD
    ("sad", "0-1"):  ["musical", "calm"],
    ("sad", "2-5"):  ["musical", "calm"],
    ("sad", "6-8"):  ["musical", "gentle"],
    ("sad", "9-12"): ["gentle",  "calm"],
    # ANXIOUS
    ("anxious", "0-1"):  ["musical", "calm"],
    ("anxious", "2-5"):  ["musical", "calm"],
    ("anxious", "6-8"):  ["musical", "gentle"],
    ("anxious", "9-12"): ["gentle",  "soft"],
    # ANGRY
    ("angry", "0-1"):  ["melodic", "musical"],
    ("angry", "2-5"):  ["melodic", "musical"],
    ("angry", "6-8"):  ["musical", "gentle"],
    ("angry", "9-12"): ["soft",    "gentle"],
}


def get_voices_for_content(
    mood: str, age_group: str, content_type: str
) -> List[str]:
    """Return the 2 descriptive voice names for this mood + age + content type.

    Returns descriptive names (calm, soft, melodic, musical, gentle, asmr).
    Call resolve_voice_id() on each to get the actual Chatterbox voice file ID.
    """
    if content_type == "poem":
        voice_map = POEM_VOICE_MAP
    elif content_type == "long_story":
        voice_map = LONG_STORY_VOICE_MAP
    else:
        voice_map = STORY_VOICE_MAP

    return voice_map.get((mood, age_group), ["calm", "gentle"])


def get_long_story_voice(
    mood: str, age_group: str, phase: int
) -> List[str]:
    """Return voice(s) for a specific phase of a long story.

    Phase 3 ALWAYS returns ["asmr"] regardless of mood.
    Phase 1 and 2 return the 2 mood voices from LONG_STORY_VOICE_MAP.
    """
    if phase == 3:
        return ["asmr"]
    return LONG_STORY_VOICE_MAP.get((mood, age_group), ["calm", "gentle"])


def get_clip_voice(story_data: dict) -> str:
    """Pick one of the 2 mood voices for social media clips.

    Alternates between the two voices daily using deterministic hash.
    Returns a descriptive voice name; call resolve_voice_id() for file ID.
    """
    mood = story_data.get("mood", "calm")
    age_group = story_data.get("age_group", "6-8")
    content_type = story_data.get("type", "story")
    voices = get_voices_for_content(mood, age_group, content_type)

    today = date.today().isoformat()
    day_index = int(hashlib.md5(today.encode()).hexdigest(), 16) % 2
    return voices[day_index]


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
