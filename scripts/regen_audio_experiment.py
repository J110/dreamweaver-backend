#!/usr/bin/env python3
"""
Regenerate audio ONLY for an existing experimental story.
Re-uses text from content.json, re-adds [MUSIC] at paragraph breaks,
generates TTS + music + assembly, updates content.json audio_variants.

Usage:
    python3 scripts/regen_audio_experiment.py gen-041123d72402
"""

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
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"
MOOD_VOICES = ["female_1", "asmr"]

# Music configs (same as main script)
MOOD_INTRO = {
    "prompt": "6 second gentle calm intro, soft music box, 3-4 simple descending notes, already peaceful, 60 BPM, warm, like a sigh of contentment, pulling up a blanket",
    "duration": 6,
}
MOOD_OUTRO = {
    "prompt": "45 second sleep outro, same music box but even slower, notes further apart, descending, last note rings for 5 seconds and fades, 60 BPM slowing to 35 BPM, calm becoming fully asleep, gentlest possible fade",
    "duration": 45,
}
STING_MAP = {
    "early": {"prompt": "2 second warm moment, soft piano chord, gentle, held, safe", "duration_seconds": 2},
    "mid": {"prompt": "3 second pre-reveal shimmer, about to see something beautiful, golden", "duration_seconds": 3},
    "late": {"prompt": "2.5 second feeling of being safe, warm low chord, held, protected, blanketed", "duration_seconds": 3},
}


def generate_tts(text: str, voice: str, exaggeration: float = 0.5,
                 cfg_weight: float = 0.4, speed: float = 0.88) -> bytes:
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                print(f"    TTS: voice={voice}, attempt {attempt+1}...")
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return resp.content
                print(f"    TTS {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"    TTS error: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}")


def get_musicgen():
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    return gen_cls()


def generate_music(gen, prompt: str, duration_seconds: float, label: str) -> AudioSegment:
    print(f"    MusicGen: {label} ({duration_seconds}s)...")
    start = time.time()
    mp3_data = gen.generate.remote(prompt, duration=int(duration_seconds))
    if not mp3_data or len(mp3_data) < 500:
        raise RuntimeError(f"MusicGen returned empty for {label}")
    elapsed = time.time() - start
    print(f"    +{label}: {len(mp3_data):,} bytes in {elapsed:.0f}s")
    return AudioSegment.from_file(io.BytesIO(mp3_data))


def add_music_tags(text: str) -> str:
    """Add [MUSIC] tags at paragraph breaks (blank lines) in story text."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    # Put [MUSIC] between paragraphs (not before first, not after last)
    return '\n\n[MUSIC]\n\n'.join(paragraphs)


def parse_story_with_music(story_text: str):
    chunks = []
    music_positions = []
    parts = re.split(r'(\[MUSIC\])', story_text)
    chunk_index = -1
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "[MUSIC]":
            if chunk_index >= 0:
                music_positions.append(chunk_index)
        else:
            chunk_index += 1
            chunks.append(part)

    # Debug
    for i, c in enumerate(chunks):
        tag = " [MUSIC after]" if i in music_positions else ""
        print(f"    chunk[{i}]: {c[:80]!r}...{tag}")

    # Deduplicate consecutive identical last sentences
    if len(chunks) >= 2:
        def last_sentence(text):
            sentences = re.split(r'[.!?]+', text.strip())
            sentences = [s.strip() for s in sentences if s.strip()]
            return sentences[-1].lower() if sentences else ""

        last_1 = last_sentence(chunks[-1])
        last_2 = last_sentence(chunks[-2])
        if last_1 and last_2 and last_1 == last_2:
            print(f"    WARNING: Duplicate last sentence: {last_1!r}")
            clean_last = re.sub(r'[.!?\s]+', '', chunks[-1]).lower()
            clean_sentence = re.sub(r'[.!?\s]+', '', last_1).lower()
            if clean_last == clean_sentence:
                print(f"    Removing duplicate final chunk")
                chunks.pop()
                music_positions = [p for p in music_positions if p < len(chunks)]

    return chunks, music_positions


def select_sting_zone(chunk_pos: int, total_chunks: int) -> str:
    progress = chunk_pos / max(total_chunks, 1)
    if progress < 0.3:
        return "early"
    elif progress < 0.7:
        return "mid"
    else:
        return "late"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/regen_audio_experiment.py <story-id>")
        sys.exit(1)

    story_id = sys.argv[1]
    short_id = story_id[:8]

    # Load story from content.json
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    story = next((s for s in all_content if s["id"] == story_id), None)
    if not story:
        print(f"Story {story_id} not found in content.json")
        sys.exit(1)

    text = story["text"]
    title = story["title"]

    print(f"\n{'='*60}")
    print(f"Audio Regeneration for: {title}")
    print(f"ID: {story_id}")
    print(f"{'='*60}\n")

    # Re-add [MUSIC] tags at paragraph breaks
    tagged_text = add_music_tags(text)
    chunks, music_positions = parse_story_with_music(tagged_text)
    print(f"  Chunks: {len(chunks)}, Music positions: {music_positions}\n")

    # ── 1. Generate music ────────────────────────────────────────────
    print("[1/3] Generating music via MusicGen...")
    gen = get_musicgen()

    # Re-use cached music if available, otherwise regenerate
    intro_path = MUSIC_DIR / "intro_calm.mp3"
    outro_path = MUSIC_DIR / "outro_calm.mp3"

    if intro_path.exists():
        print(f"    Re-using cached intro: {intro_path}")
        intro_audio = AudioSegment.from_mp3(str(intro_path))
    else:
        intro_audio = generate_music(gen, MOOD_INTRO["prompt"], 6, "calm intro")
        intro_audio.export(str(intro_path), format="mp3", bitrate="256k")

    if outro_path.exists():
        print(f"    Re-using cached outro: {outro_path}")
        outro_audio = AudioSegment.from_mp3(str(outro_path))
    else:
        outro_audio = generate_music(gen, MOOD_OUTRO["prompt"], 45, "calm outro")
        outro_audio.export(str(outro_path), format="mp3", bitrate="256k")

    # Stings
    zones_needed = set()
    for pos in music_positions:
        zone = select_sting_zone(pos, len(chunks))
        zones_needed.add(zone)

    sting_audio = {}
    for zone in sorted(zones_needed):
        sting_path = MUSIC_DIR / f"sting_{zone}.mp3"
        if sting_path.exists():
            print(f"    Re-using cached sting: {sting_path}")
            sting_audio[zone] = AudioSegment.from_mp3(str(sting_path))
        else:
            cfg = STING_MAP[zone]
            seg = generate_music(gen, cfg["prompt"], cfg["duration_seconds"], f"sting_{zone}")
            sting_audio[zone] = seg
            seg.export(str(sting_path), format="mp3", bitrate="256k")

    print(f"  intro ({len(intro_audio)/1000:.0f}s), outro ({len(outro_audio)/1000:.0f}s), {len(sting_audio)} stings\n")

    # ── 2. Generate TTS ──────────────────────────────────────────────
    print("[2/3] Generating TTS...")
    chunk_audio_by_voice = {}

    for voice in MOOD_VOICES:
        print(f"  Voice: {voice}")
        chunk_audios = []
        for i, chunk in enumerate(chunks):
            print(f"    [{i}] {len(chunk)} chars: {chunk[:60]!r}...")
            wav_bytes = generate_tts(chunk, voice)
            seg = AudioSegment.from_wav(io.BytesIO(wav_bytes))
            dur = len(seg) / 1000.0
            print(f"        -> {dur:.1f}s")
            chunk_audios.append(seg)
        chunk_audio_by_voice[voice] = chunk_audios
        print(f"    Total chunks: {len(chunk_audios)}\n")

    # ── 3. Assemble ──────────────────────────────────────────────────
    print("[3/3] Assembling...")
    audio_variants = []

    for voice in MOOD_VOICES:
        print(f"  {voice}:")
        output = AudioSegment.silent(duration=0)

        # Intro
        output += intro_audio
        output += AudioSegment.silent(duration=500)

        # Narration with stings
        chunk_audios = chunk_audio_by_voice[voice]
        for i, seg in enumerate(chunk_audios):
            output += seg
            pos_ms = len(output) / 1000.0
            print(f"    +chunk[{i}] @ {pos_ms:.1f}s")

            if i in music_positions:
                zone = select_sting_zone(i, len(chunks))
                output += AudioSegment.silent(duration=500)
                output += sting_audio[zone]
                output += AudioSegment.silent(duration=500)
                print(f"    +sting_{zone} @ {len(output)/1000.0:.1f}s")

        # Silence + outro
        output += AudioSegment.silent(duration=2000)
        output += outro_audio

        # Export
        output_path = AUDIO_DIR / f"{short_id}_{voice}.mp3"
        output.export(str(output_path), format="mp3", bitrate="256k")
        duration = len(output) / 1000.0
        size_kb = output_path.stat().st_size / 1024
        print(f"    => {output_path.name} ({size_kb:.0f} KB, {duration:.1f}s)\n")

        audio_variants.append({
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        })

    # Update content.json
    avg_dur = sum(v["duration_seconds"] for v in audio_variants) / len(audio_variants)
    for s in all_content:
        if s["id"] == story_id:
            s["audio_variants"] = audio_variants
            s["duration_seconds"] = round(avg_dur, 2)
            s["duration"] = max(1, math.ceil(avg_dur / 60))
            break

    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_content, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"{'='*60}")
    print(f"DONE — {len(audio_variants)} variants regenerated")
    for v in audio_variants:
        print(f"  {v['voice']}: {v['duration_seconds']}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
