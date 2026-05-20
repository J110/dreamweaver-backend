#!/usr/bin/env python3
"""generate_clips_hi.py — Hindi social-media clips.

Parallel to ``generate_clips.py`` per dreamweaver-backend/CLAUDE.md
(parallel scripts, not ``--lang`` flags). Supplies Hindi language config
to ``_clips_common``: Roman-Hindi mood/type labels, Hinglish captions,
``clips/hi/`` output, ``lang == 'hi'`` content filter, ``_hi``-suffixed
voice resolution.

All user-facing strings are Roman script per the Hindi content invariant.

Usage:
    python3 scripts/generate_clips_hi.py                          # Daily 6 clips
    python3 scripts/generate_clips_hi.py --story-id <id>          # Single clip
    python3 scripts/generate_clips_hi.py --force                   # Overwrite
    python3 scripts/generate_clips_hi.py --dry-run                 # Preview plan
    python3 scripts/generate_clips_hi.py --batch                   # All unclipped
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


# ── Roman Hindi display labels ───────────────────────────────────────────

MOOD_DISPLAY_HI = {
    "wired":   {"label": "Mazedaar",   "emoji": "😄", "color": "FFB946"},
    "curious": {"label": "Adventure",  "emoji": "🔮", "color": "7B68EE"},
    "calm":    {"label": "Pyaara",     "emoji": "🌙", "color": "6BB5C9"},
    "sad":     {"label": "Sukoon",     "emoji": "💛", "color": "E8A87C"},
    "anxious": {"label": "Bahaadur",   "emoji": "🛡️",  "color": "85C88A"},
    "angry":   {"label": "Gussa",      "emoji": "🌊", "color": "C9896D"},
}

TYPE_LABELS_HI = {
    "song": "Lori",
    "story": "Kahani",
    "poem": "Kavita",
    "long_story": "Lambi Kahani",
    "funny_short": "Funny Short",
    "silly_song": "Gaana",
    "lullaby": "Lori",
}

VOICE_LABELS_HI = {
    "female_1_hi": "shaant awaaz",
    "asmr_hi": "ASMR fusfusahat",
    "default": "",
    "default_hi": "",
}

VOICE_TAGS_HI = {
    "female_1_hi": "#shaantawaaz",
    "asmr_hi": "#asmr #asmrforkids",
    "default": "#lori",
    "default_hi": "#lori",
}


# ── Caption builder (Roman Hindi + bilingual hashtags) ───────────────────

def build_captions_hi(*, title: str, mood: str, age_group: str,
                      story_id: str, voice: str, content_type: str,
                      subtype: str | None, config: LangConfig) -> dict:
    mood_info = config.mood_display.get(mood, config.mood_display["calm"])
    voice_label = config.voice_labels.get(voice, "")
    voice_tag = config.voice_tags.get(voice, "")

    type_key = subtype if (subtype and subtype in config.type_labels) else content_type
    type_label = config.type_labels.get(type_key, "Kahani")
    type_label_lower = type_label.lower()
    mood_lower = mood_info["label"].lower()

    youtube = (
        f"{title} {mood_info['emoji']} | Bachchon ki bedtime kahani | Dream Valley"
        f"{' (' + voice_label + ')' if voice_label else ''}\n\n"
        f"Ek {mood_lower} {type_label_lower} — ages {age_group}. "
        f"Poori kahani sunne ke liye dreamvalley.app.\n\n"
        f"\U0001F319 dreamvalley.app\n\n"
        f"#bedtimekahani #bachchonkikahani #lori #DreamValley "
        f"#bedtimestory #kidssleep {voice_tag}"
    )

    instagram = (
        f"{title} {mood_info['emoji']} — {mood_info['label']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"{type_label} for ages {age_group}. "
        f"Poori kahani dreamvalley.app par \U0001F319\n\n"
        f"#bedtimekahani #bachchonkikahani #lori #DreamValley "
        f"#toddlerbedtime #bedtimestory {voice_tag}"
    )

    tiktok = (
        f"{title} {mood_info['emoji']} — {mood_info['label']}"
        f"{' · ' + voice_label if voice_label else ''}\n\n"
        f"dreamvalley.app \U0001F319\n\n"
        f"#bedtimekahani #lori #bachchemom #toddlermom "
        f"#DreamValley {voice_tag}"
    )

    return {"youtube": youtube, "instagram": instagram, "tiktok": tiktok}


# ── Config ──────────────────────────────────────────────────────────────

CONFIG = LangConfig(
    lang="hi",
    output_dir=BASE_DIR / "clips" / "hi",
    mood_display=MOOD_DISPLAY_HI,
    type_labels=TYPE_LABELS_HI,
    voice_labels=VOICE_LABELS_HI,
    voice_tags=VOICE_TAGS_HI,
    caption_builder=build_captions_hi,
    brand_text="dreamvalley.app",
    ages_prefix="Ages",
)


if __name__ == "__main__":
    run_main(CONFIG)
