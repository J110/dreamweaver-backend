#!/usr/bin/env python3
"""
Regenerate audio for an existing exp2 story.
Re-parses raw_text from the output JSON, normalizes text, regenerates TTS,
reassembles with bed + swells.

Usage:
    python3 scripts/regen_exp2_audio.py --story-id exp2-d586859ee5
    python3 scripts/regen_exp2_audio.py --story-id exp2-d586859ee5 --no-hook
"""

import argparse
import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"
MUSIC_DIR = BASE_DIR / "audio" / "story_music"
OUTPUT_DIR = BASE_DIR / "output" / "experimental_stories_v2"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"

# Voice mapping by mood (from AUDIO_GENERATION_GUIDELINES)
MOOD_VOICES = {
    "wired":   ["female_3", "male_2"],    # melodic + gentle
    "curious": ["female_4", "male_2"],    # musical + gentle
    "calm":    ["female_1", "asmr"],      # calm + asmr
    "sad":     ["male_2", "female_1"],    # gentle + calm
    "anxious": ["male_2", "female_1"],    # gentle + calm
    "angry":   ["female_3", "male_2"],    # melodic + gentle
}
DEFAULT_VOICES = ["female_1", "asmr"]

NORMAL_TTS = {"exaggeration": 0.45, "speed": 0.85, "cfg_weight": 0.5}
HOOK_TTS = {"exaggeration": 0.55, "speed": 0.82, "cfg_weight": 0.45}
PHRASE_TTS = {"exaggeration": 0.60, "speed": 0.78, "cfg_weight": 0.42}


# ── Helpers ──────────────────────────────────────────────────────────

def normalize_for_tts(text: str) -> str:
    """Normalize ALL CAPS words (3+ chars) to Title Case for TTS."""
    def fix_caps(match):
        word = match.group(0)
        if len(word) <= 2:
            return word
        return word.capitalize()
    return re.sub(r'\b[A-Z]{3,}\b', fix_caps, text)


def normalize_display_text(text: str) -> str:
    """Normalize ALL CAPS words in display text too."""
    return normalize_for_tts(text)


def generate_tts(text: str, voice: str, exaggeration: float = 0.45,
                 cfg_weight: float = 0.5, speed: float = 0.85,
                 is_phrase: bool = False) -> AudioSegment:
    text = normalize_for_tts(text)
    if is_phrase:
        text = f"... {text}"
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_wav(io.BytesIO(resp.content))
                print(f"    TTS {resp.status_code}: {resp.text[:80]}")
            except Exception as e:
                print(f"    TTS error: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}")


def parse_segments(text: str) -> list:
    """Parse raw_text into segments: text, pause, phrase, music."""
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
            content = re.sub(r'\*+', '', content)
            segments.append(("phrase", content))
        else:
            cleaned = re.sub(r'\*+', '', part).strip()
            if cleaned:
                segments.append(("text", cleaned))

    return segments


def apply_swell_envelope(bed: AudioSegment, swells: list,
                         base_db: float = -18, peak_db: float = -6) -> AudioSegment:
    """Apply volume swells to bed track in 50ms chunks."""
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


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--no-hook", action="store_true",
                        help="Skip the hook TTS at the start of the audio")
    args = parser.parse_args()

    story_id = args.story_id
    skip_hook = args.no_hook

    # Load story data from output JSON
    story_json = OUTPUT_DIR / f"{story_id}.json"
    if not story_json.exists():
        print(f"ERROR: {story_json} not found")
        sys.exit(1)

    with open(story_json) as f:
        story = json.load(f)

    raw_text = story.get("raw_text", "")
    if not raw_text:
        print("ERROR: No raw_text in story JSON")
        sys.exit(1)

    mood = story.get("mood", "wired")
    title = story.get("title", "")
    hook = story.get("hook", title or "A bedtime story")

    print(f"\n{'='*60}")
    print(f"Regenerating audio for {story_id}")
    print(f"Title: {title}")
    print(f"Hook: {hook} {'(SKIPPED)' if skip_hook else ''}")
    print(f"Mood: {mood}")
    print(f"{'='*60}\n")

    # Parse segments
    segments = parse_segments(raw_text)
    music_count = sum(1 for s in segments if s[0] == "music")
    phrase_count = sum(1 for s in segments if s[0] == "phrase")
    print(f"Segments: {len(segments)} total, {music_count} swells, {phrase_count} phrases\n")

    for i, (stype, content) in enumerate(segments):
        if stype == "text":
            print(f"  [{i}] text: {content[:70]}...")
        elif stype == "phrase":
            print(f"  [{i}] PHRASE: {content}")
        elif stype == "pause":
            print(f"  [{i}] PAUSE: {content}ms")
        elif stype == "music":
            print(f"  [{i}] MUSIC (6s swell)")
    print()

    # Load mood music
    print("Loading mood music...")
    intro = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / f"outro_{mood}.wav"))
    bed = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))
    print(f"  Intro: {len(intro)/1000:.1f}s, Outro: {len(outro)/1000:.1f}s, Bed: {len(bed)/1000:.1f}s\n")

    # Generate TTS per voice
    audio_variants = []
    voices = MOOD_VOICES.get(mood, DEFAULT_VOICES)
    print(f"Voices for mood '{mood}': {voices}\n")
    for voice in voices:
        print(f"Generating TTS for {voice}...")

        # Hook
        hook_audio = None
        if not skip_hook:
            print(f"  TTS [hook]: {hook[:50]}...")
            hook_audio = generate_tts(hook, voice, **HOOK_TTS)
            print(f"    -> {len(hook_audio)}ms")

        # Segments
        segment_audios = []
        for stype, content in segments:
            if stype == "text":
                print(f"  TTS [normal]: {normalize_for_tts(content)[:50]}...")
                audio = generate_tts(content, voice, **NORMAL_TTS)
                segment_audios.append(("audio", audio))
                print(f"    -> {len(audio)}ms")
            elif stype == "phrase":
                print(f"  TTS [phrase]: ... {content}")
                audio = generate_tts(content, voice, **PHRASE_TTS, is_phrase=True)
                segment_audios.append(("audio", audio))
                print(f"    -> {len(audio)}ms")
            elif stype == "pause":
                segment_audios.append(("pause", content))
            elif stype == "music":
                segment_audios.append(("music", None))

        # Throwaway to prevent Chatterbox repeat bug
        try:
            generate_tts(".", voice, exaggeration=0.1, speed=0.8, cfg_weight=0.5)
        except:
            pass
        print()

        # Build narration track
        print(f"Building narration track ({voice})...")
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
                print(f"    +SWELL @ {start}ms")

        # Gap + outro
        narration += AudioSegment.silent(duration=3000)
        narration += outro

        total_ms = len(narration)
        print(f"    Total: {total_ms/1000:.1f}s, Swells: {len(swell_regions)}\n")

        # Shape bed and mix — bed fades out before outro
        print(f"Shaping bed + mixing ({voice})...")
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

        # Export
        path_pipeline = AUDIO_DIR / f"{story_id}_{voice}.mp3"
        with_music.export(str(path_pipeline), format="mp3", bitrate="256k")

        path_music = OUTPUT_DIR / f"{story_id}_{voice}.mp3"
        path_nomusic = OUTPUT_DIR / f"{story_id}_{voice}_nomusic.mp3"
        with_music.export(str(path_music), format="mp3", bitrate="256k")
        without_music.export(str(path_nomusic), format="mp3", bitrate="256k")

        duration_s = total_ms / 1000.0
        music_kb = path_pipeline.stat().st_size / 1024
        print(f"    Pipeline:    {path_pipeline.name} ({music_kb:.0f} KB, {duration_s:.1f}s)")
        print(f"    Output+bed:  {path_music.name}")
        print(f"    Output-bed:  {path_nomusic.name}\n")

        audio_variants.append({
            "voice": voice,
            "url": f"/audio/pre-gen/{path_pipeline.name}",
            "duration_seconds": round(duration_s, 2),
            "provider": "chatterbox",
        })

    # Update content.json — fix text + audio variants + duration
    print("Updating content.json...")
    with open(CONTENT_PATH) as f:
        content = json.load(f)

    # Normalize the display text
    clean_text = re.sub(r'\[MUSIC\]', '', raw_text)
    clean_text = re.sub(r'\[PAUSE:\s*\d+\]', '', clean_text)
    clean_text = re.sub(r'\[/?PHRASE\]', '', clean_text)
    clean_text = re.sub(r'\*+', '', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    clean_text = normalize_display_text(clean_text)

    avg_dur = sum(v["duration_seconds"] for v in audio_variants) / len(audio_variants)
    dur_min = max(1, math.ceil(avg_dur / 60))

    for item in content:
        if item.get("id") == story_id:
            item["text"] = clean_text
            item["audio_variants"] = audio_variants
            item["duration"] = dur_min
            item["duration_seconds"] = round(avg_dur, 2)
            print(f"  Updated: text normalized, {len(audio_variants)} audio variants, {dur_min} min")
            break
    else:
        print(f"  WARNING: {story_id} not found in content.json")

    with open(CONTENT_PATH, "w") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    # Also update the output JSON
    story["text"] = clean_text
    story["audio_variants"] = audio_variants
    story["duration"] = dur_min
    story["duration_seconds"] = round(avg_dur, 2)
    with open(story_json, "w") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Done! Audio regenerated for {story_id}")
    print(f"Variants: {', '.join(v['voice'] for v in audio_variants)}")
    print(f"Duration: ~{dur_min} min ({avg_dur:.1f}s)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
