#!/usr/bin/env python3
"""Patch follow-up to fix_hindi_batch_day2.py for 2 remaining bugs.

Bug 1 — narration tags visible in the `text` field (UI shows
  `[PAUSE: 800]`, `[PHRASE]...[/PHRASE]`, `[MUSIC]` as literals).
  Root cause: I populated `text` with the tagged Roman source.
  Fix: run the Roman through clean_display_text() and store that in
  `text`; keep the tagged version in `raw_text`.

Bug 2 — audio has an extra line at the beginning.
  Root cause: the hook "Chiki gilhari ki pehli baarish — tap tap, chupke
  chupke" is spoken before the story proper, but it essentially duplicates
  the description, and the story opens with a natural listener-grab
  ("Suno na bachcho. Aaj Chiki gilhari ki kahani.") that already serves as
  the hook for a 2-5 Hindi listener.
  Fix: re-render story audio with skip_hook=True (no pre-hook line).

Scope is intentionally narrow:
  * Story MP3 re-rendered (hook suppressed, same path/filename, Devanagari).
  * Lullaby MP3 untouched (MiniMax output was fine — no hook issue).
  * Covers untouched (already correct after fix_hindi_batch_day2).
  * content.json both entries rewritten: text=clean, raw_text=tagged, hook
    kept as a short subtitle/description string but NOT spoken.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
import re
from audio_assembly import (
    normalize_for_tts, apply_swell_envelope, MUSIC_DIR, clean_display_text,
    normalize_display_text,
)


def clean_lyrics_text(raw: str) -> str:
    """Strip tags from song lyrics but PRESERVE line breaks.

    Unlike clean_display_text (which flattens all whitespace with \\s+ → ' '),
    this keeps each lyric line on its own line so the lullaby player can
    render them as verses. Removes [verse]/[chorus]/[bridge] markers,
    [PAUSE: ms], [PHRASE], [MUSIC], and any other [TAG] brackets.
    """
    # Strip tags on any line containing them.
    clean = re.sub(r"\[/?[A-Za-z_][A-Za-z0-9_:. ]*\]", "", raw)
    clean = re.sub(r"\*+", "", clean)
    # Normalize per-line: trim trailing whitespace, collapse intra-line spaces.
    out_lines = []
    for line in clean.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        out_lines.append(line)
    # Collapse 3+ consecutive blank lines to a single blank line.
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return normalize_display_text(result)
from fix_hindi_batch_day2 import (
    STORY, LULLABY,
    ELEVENLABS_VOICES, ELEVENLABS_URL, ELEVENLABS_MODEL, HINDI_TTS_PARAMS,
    _ensure_terminal_danda, parse_segments_deva,
    elevenlabs_tts,
    story_entry as original_story_entry,
    lullaby_song_entry as original_lullaby_song_entry,
    lullaby_agg_entry,
    upsert_content, upsert_lullabies_agg,
)

load_dotenv(BASE_DIR / ".env", override=True)


# ─────────────────────────────────────────────────────────────────────────
# Story audio — NO hook, otherwise identical to fix_hindi_batch_day2.
# ─────────────────────────────────────────────────────────────────────────

def assemble_story_audio_no_hook(text_deva: str, voice_label: str, mood: str):
    voice_id = ELEVENLABS_VOICES[voice_label]
    intro = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / f"outro_{mood}.wav"))
    bed   = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))

    def call(text, role, prev, nxt, is_phrase=False):
        preset = HINDI_TTS_PARAMS[role]
        effective = _ensure_terminal_danda(text) if is_phrase else text
        effective = normalize_for_tts(effective)
        return elevenlabs_tts(
            effective, voice_id,
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt,
        )

    segments = parse_segments_deva(text_deva)
    counts = {}
    for s, _ in segments:
        counts[s] = counts.get(s, 0) + 1
    print(f"  segments: {counts}  (hook suppressed)")

    texts_only = [s[1] if s[0] in ("text", "phrase") else "" for s in segments]

    rendered = []
    for idx, (stype, content) in enumerate(segments):
        if stype in ("text", "phrase"):
            prev = texts_only[idx-1] if idx > 0 else ""
            nxt  = texts_only[idx+1] if idx+1 < len(texts_only) else ""
            role = "phrase" if stype == "phrase" else "text"
            rendered.append(("audio", call(content, role, prev, nxt,
                                           is_phrase=(stype == "phrase"))))
        elif stype == "pause":
            rendered.append(("pause", content))
        elif stype == "music":
            rendered.append(("music", None))

    narration = AudioSegment.silent(duration=0)
    swells = []
    narration += intro
    narration += AudioSegment.silent(duration=500)
    # NO hook. Story opens with "Suno na bachcho." directly.
    for stype, content in rendered:
        if stype == "audio":
            narration += content
        elif stype == "pause":
            narration += AudioSegment.silent(duration=content)
        elif stype == "music":
            start = len(narration)
            narration += AudioSegment.silent(duration=6000)
            swells.append((start, len(narration)))
    narration += AudioSegment.silent(duration=3000)
    narration += outro

    total = len(narration)
    outro_dur = len(outro)
    bed_end = total - outro_dur - 3000
    if len(bed) >= bed_end:
        shaped = bed[:bed_end]
    else:
        loops = (bed_end // len(bed)) + 1
        shaped = (bed * loops)[:bed_end]
    shaped = shaped.fade_out(3000)
    shaped += AudioSegment.silent(duration=total - bed_end)
    regions = [
        {"start": s, "fade_in_end": s+2000, "hold_end": e-2000, "fade_out_end": e}
        for s, e in swells
    ]
    shaped = apply_swell_envelope(shaped, regions, base_db=-18, peak_db=-6)
    return narration.overlay(shaped)


# ─────────────────────────────────────────────────────────────────────────
# content.json entry rewrites — clean `text`, raw in `raw_text`.
# ─────────────────────────────────────────────────────────────────────────

def story_entry_clean(duration: int) -> dict:
    entry = original_story_entry(duration)
    # Strip tags from display text but preserve paragraph breaks
    # (English stories render with \n\n). clean_lyrics_text does exactly
    # this: strips [TAG]s, keeps line breaks, collapses 3+ blanks to 2.
    entry["text"]      = clean_lyrics_text(STORY["text_roman"])
    entry["text_deva"] = clean_lyrics_text(STORY["text_deva"])
    entry["raw_text"]      = STORY["text_roman"]
    entry["raw_text_deva"] = STORY["text_deva"]
    entry["duration_seconds"] = duration
    entry["audio_variants"][0]["duration_seconds"] = duration
    entry["word_count"] = len(entry["text"].split())
    # Hook remains as a short subtitle for content.json display, but the
    # audio track no longer speaks it.
    entry["hook_spoken_in_audio"] = False
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return entry


def lullaby_song_entry_clean(duration: int) -> dict:
    entry = original_lullaby_song_entry(duration)
    # Lyrics have [verse] / [chorus] markers for MiniMax structure — strip
    # them but preserve line breaks so the lullaby player renders verses.
    entry["text"]      = clean_lyrics_text(LULLABY["lyrics_roman"])
    entry["text_deva"] = clean_lyrics_text(LULLABY["lyrics_deva"])
    entry["lyrics"]      = entry["text"]
    entry["lyrics_deva"] = entry["text_deva"]
    entry["raw_lyrics"]      = LULLABY["lyrics_roman"]
    entry["raw_lyrics_deva"] = LULLABY["lyrics_deva"]
    entry["word_count"] = len(entry["text"].split())
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return entry


def lullaby_agg_entry_clean(duration: int) -> dict:
    entry = lullaby_agg_entry(duration)
    entry["lyrics"]      = clean_lyrics_text(LULLABY["lyrics_roman"])
    entry["lyrics_deva"] = clean_lyrics_text(LULLABY["lyrics_deva"])
    entry["raw_lyrics"]      = LULLABY["lyrics_roman"]
    entry["raw_lyrics_deva"] = LULLABY["lyrics_deva"]
    return entry


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-audio", action="store_true",
                    help="only rewrite JSON, keep existing MP3")
    args = ap.parse_args()

    # Existing audio paths — same filenames as before, overwriting in-place.
    story_audio_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{STORY['id']}_{STORY['voice']}.mp3"
    lullaby_audio_path = WEB_ROOT / "public" / "audio" / "lullabies" / f"{LULLABY['id']}.mp3"

    # 1. Re-render story audio with NO hook.
    if args.skip_audio:
        story_duration = round(len(AudioSegment.from_file(str(story_audio_path))) / 1000)
        print(f"\n═══ STORY audio: SKIPPED (existing {story_duration}s) ═══")
    else:
        print("\n═══ STORY audio: re-render with skip_hook=True ═══")
        story_audio = assemble_story_audio_no_hook(
            STORY["text_deva"], STORY["voice"], STORY["mood"])
        story_audio.export(story_audio_path, format="mp3", bitrate="192k")
        story_duration = round(len(story_audio) / 1000)
        print(f"  → {story_audio_path}  ({story_duration}s)")

    # 2. Lullaby audio: UNTOUCHED. Just read the duration.
    lul_duration = round(len(AudioSegment.from_file(str(lullaby_audio_path))) / 1000)
    print(f"\n═══ LULLABY audio: unchanged ({lul_duration}s) ═══")

    # 3. Rewrite both content.json entries with clean `text` + raw_text.
    print("\n═══ JSON rewrites (clean text, raw_text preserved) ═══")
    s_entry = story_entry_clean(story_duration)
    l_song  = lullaby_song_entry_clean(lul_duration)
    l_agg   = lullaby_agg_entry_clean(lul_duration)

    # Sanity-print what the UI will see.
    print(f"\n  story.text (first 120 chars): {s_entry['text'][:120]!r}")
    print(f"  story.text contains tag?   {'[' in s_entry['text']}")
    print(f"  lullaby.text (first 120 chars): {l_song['text'][:120]!r}")
    print(f"  lullaby.text contains tag? {'[' in l_song['text']}")

    upsert_content([s_entry, l_song])
    upsert_lullabies_agg(l_agg)

    per_entry = BASE_DIR / "seed_output" / "lullabies" / f"{LULLABY['id']}.json"
    with open(per_entry, "w", encoding="utf-8") as f:
        json.dump(l_agg, f, ensure_ascii=False, indent=2)
    print(f"  {per_entry}")

    print("\n═════ PATCH DONE ═════")
    print(f"  story:   {story_duration}s, hook suppressed, text clean")
    print(f"  lullaby: {lul_duration}s, lyrics clean (no [verse]/[chorus])")


if __name__ == "__main__":
    main()
