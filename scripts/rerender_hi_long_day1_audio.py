"""Re-render only the day-1 Hindi long-story audio.

Skips:
  - MiniMax song regeneration (loads cached mp3)
  - FLUX cover regen
  - content.json upsert

Re-runs:
  - All ElevenLabs TTS for narration / dialogue / phrase / whisper /
    breathe_guide segments
  - assemble_long_story_audio() with the patched bed + breath-swell logic

Usage:
  python3 scripts/rerender_hi_long_day1_audio.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from pydub import AudioSegment

# Reuse all constants and helpers from publish_hindi_long_day1.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_hindi_long_day1 import (  # type: ignore
    BASE_DIR,
    NARRATOR_VOICE,
    STORY,
    STORY_TEXT_DEVA,
    WEB_ROOT,
    assemble_long_story_audio,
    parse_long_segments,
)


def main() -> None:
    cached_song = BASE_DIR / "seed_output" / "hindi_long" / f"{STORY['id']}_song.mp3"
    if not cached_song.exists():
        sys.exit(f"❌ Cached song not found at {cached_song}")

    song_audio = AudioSegment.from_file(cached_song, format="mp3")
    if len(song_audio) > 45000:
        song_audio = song_audio[:45000].fade_out(2000)
    print(f"  song (cached): {len(song_audio) / 1000:.1f}s")

    segments = parse_long_segments(STORY_TEXT_DEVA)
    counts: dict = {}
    for s in segments:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    print(f"  segments: {counts}")

    print("\n═══ Re-rendering with new bed + breath-swell architecture ═══")
    story_audio = assemble_long_story_audio(segments, song_audio)
    out_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{STORY['id']}_{NARRATOR_VOICE}.mp3"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    story_audio.export(out_path, format="mp3", bitrate="192k")
    duration = round(len(story_audio) / 1000)
    print(f"  → {out_path}")
    print(f"  duration: {duration}s ({duration // 60}m{duration % 60}s)")


if __name__ == "__main__":
    main()
