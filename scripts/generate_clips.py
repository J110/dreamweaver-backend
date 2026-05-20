#!/usr/bin/env python3
"""generate_clips.py — English social-media clips.

Thin wrapper that supplies English language config to ``_clips_common``.
All FFmpeg / Ken Burns / composite plumbing lives in
``scripts/_clips_common.py``. See ``generate_clips_hi.py`` for the Hindi
counterpart.

Usage:
    python3 scripts/generate_clips.py                          # Daily 6 clips
    python3 scripts/generate_clips.py --story-id <id>          # Single clip
    python3 scripts/generate_clips.py --force                   # Overwrite
    python3 scripts/generate_clips.py --dry-run                 # Preview plan
    python3 scripts/generate_clips.py --batch                   # All unclipped
    python3 scripts/generate_clips.py --limit 5                 # Cap batch
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from _clips_common import BASE_DIR, LangConfig, run_main  # noqa: E402


# ── English display labels ───────────────────────────────────────────────

MOOD_DISPLAY = {
    "wired":   {"label": "Silly",      "emoji": "😄", "color": "FFB946"},
    "curious": {"label": "Adventure",  "emoji": "🔮", "color": "7B68EE"},
    "calm":    {"label": "Gentle",     "emoji": "🌙", "color": "6BB5C9"},
    "sad":     {"label": "Comfort",    "emoji": "💛", "color": "E8A87C"},
    "anxious": {"label": "Brave",      "emoji": "🛡️",  "color": "85C88A"},
    "angry":   {"label": "Let It Out", "emoji": "🌊", "color": "C9896D"},
}

TYPE_LABELS = {
    "song": "Lullaby",
    "story": "Story",
    "poem": "Poem",
    "long_story": "Story",
    "funny_short": "Funny Short",
    "silly_song": "Silly Song",
    "lullaby": "Lullaby",
}

VOICE_LABELS = {
    "female_1": "calm voice",
    "asmr": "ASMR whisper voice",
    "default": "",
}

VOICE_TAGS = {
    "female_1": "#calmvoice",
    "asmr": "#asmr #asmrforkids",
    "default": "#lullaby",
}


# ── Caption builder (English) ────────────────────────────────────────────

def build_captions_en(*, title: str, mood: str, age_group: str,
                      story_id: str, voice: str, content_type: str,
                      subtype: str | None, config: LangConfig) -> dict:
    mood_info = config.mood_display.get(mood, config.mood_display["calm"])
    voice_label = config.voice_labels.get(voice, "")
    voice_tag = config.voice_tags.get(voice, "")

    youtube = (
        f"{title} {mood_info['emoji']} | Bedtime Story for Kids"
        f"{' (' + voice_label + ')' if voice_label else ''}\n\n"
        f"A {mood_info['label'].lower()} bedtime story for ages {age_group}. "
        f"Listen to the full story free on Dream Valley.\n\n"
        f"\U0001F319 dreamvalley.app\n\n"
        f"#bedtimestory #kidssleep #bedtimeroutine #storytime "
        f"#dreamvalley {voice_tag}"
    )

    instagram = (
        f"{title} {mood_info['emoji']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"A {mood_info['label'].lower()} bedtime story for ages {age_group}. "
        f"Full story free on dreamvalley.app \U0001F319\n\n"
        f"#bedtimestories #toddlerbedtime #kidssleep "
        f"#parentinghack #bedtimeroutine {voice_tag}"
    )

    tiktok = (
        f"{title} {mood_info['emoji']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"dreamvalley.app \U0001F319\n\n"
        f"#bedtimestory #toddlermom #bedtimeroutine "
        f"#kidssleep {voice_tag}"
    )

    return {"youtube": youtube, "instagram": instagram, "tiktok": tiktok}


# ── Config ──────────────────────────────────────────────────────────────

CONFIG = LangConfig(
    lang="en",
    output_dir=BASE_DIR / "clips",
    mood_display=MOOD_DISPLAY,
    type_labels=TYPE_LABELS,
    voice_labels=VOICE_LABELS,
    voice_tags=VOICE_TAGS,
    caption_builder=build_captions_en,
    brand_text="dreamvalley.app",
    ages_prefix="Ages",
)


if __name__ == "__main__":
    run_main(CONFIG)
