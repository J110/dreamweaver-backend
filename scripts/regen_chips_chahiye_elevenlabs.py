#!/usr/bin/env python3
"""Re-render the Chips Chahiye! silly song using ElevenLabs Music.

Replaces the existing MiniMax v2.5 audio at every served location:
  - dreamweaver-web/public/audio/silly-songs/{id}.mp3      (legacy duplicate)
  - dreamweaver-web/public/audio/pre-gen/{id}.mp3          (legacy duplicate)
  - seed_output/silly_songs/{id}.mp3                        (debug master)
  - /opt/dreamweaver-backend/public/audio/silly-songs/...   (served by api.dreamvalley)
  - /opt/audio-store/silly-songs-hi/...                     (persistent backup, prod)
  - /opt/audio-store/pre-gen/...                            (persistent backup, prod)

Style prompt is tuned for ElevenLabs Music (warmth/major-key/smiling) — its
sadness triggers are different from MiniMax (drone/breathy/ambient). Lyrics
are sent in Devanagari with explicit native-Indian-pronunciation cue.
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

load_dotenv(BASE_DIR / ".env", override=True)

ELEVENLABS_API_KEY = os.getenv(
    "ELEVENLABS_API_KEY",
    "sk_5bbd5d1a1ee9fa532c454154e2a7723f94ffc3bce07087ff",
)
ELEVENLABS_MUSIC_ENDPOINT = "https://api.elevenlabs.io/v1/music"

SONG_ID = "hi-chips_chahiye-2-5-a8f2"
TARGET_MS = 75_000  # 75s, comfortably above the 44s MiniMax baseline

# ─── Style tuned for ElevenLabs Music (warmth + protest energy) ───
# Avoid MiniMax-friendly words that ElevenLabs reads as sadness:
#   drone, monotone, meditative, pastoral, breathy, intimate, ambient
# Lean into ElevenLabs-friendly warmth:
#   sweet, loving, cheerful, smiling, lilting, major key, bouncy
STYLE_PROMPT = (
    "Catchy children's Hindi protest song, bouncy playful battle-cry anthem, "
    "ukulele strums and soft dholki rhythm and rhythmic hand claps, 124 BPM, "
    "super energetic and joyful, smiling cheeky young Indian child female "
    "vocal, cheerful Bollywood-nursery lilt, warm major key, native Hindi "
    "pronunciation, strong singalong chorus, kids should want to chant along, "
    "every Hindi word crystal clear, like a happy four-year-old demanding "
    "chips before dinner"
)

LYRICS_DEVA = (
    "[verse 1]\n"
    "स्कूल खत्म, हम आए\n"
    "*धड़ाम* बैग थम गए\n"
    "माँ बोली, खाना ले लो\n"
    "हम बोली, चिप्स चाहिए!\n"
    "\n"
    "[chorus]\n"
    "चिप्स चाहिए, चिप्स चाहिए!\n"
    "क्रंची क्रंची चिप्स चाहिए!\n"
    "माँ दो ना, प्लीज़ दे ना\n"
    "चिप्स चाहिए, चिप्स चाहिए!\n"
    "\n"
    "[verse 2]\n"
    "माँ कहती, पहले दाल\n"
    "हम कहते, चिप्स अभी लाल\n"
    "*खट खट* फ्रिज खुलता\n"
    "पैकेट भी निकलता\n"
    "\n"
    "[chorus]\n"
    "चिप्स चाहिए, चिप्स चाहिए!\n"
    "क्रंची क्रंची चिप्स चाहिए!\n"
    "माँ दो ना, प्लीज़ दे ना\n"
    "चिप्स चाहिए, चिप्स चाहिए!\n"
    "\n"
    "[ending]\n"
    "माँ हँसी, पैकेट दिया\n"
    "क्रंच क्रंच, नींद आई\n"
)


def build_prompt() -> str:
    return (
        f"{STYLE_PROMPT}.\n\n"
        "Sing the following Hindi (Devanagari) lyrics clearly, in a native "
        "North Indian female child voice, with conversational mother-tongue "
        "pronunciation — not a Western or Chinese vocal lens. The verses "
        "are bouncy and protesting; the chorus is the singalong hook the "
        "child belts out.\n\n"
        f"Lyrics:\n{LYRICS_DEVA}"
    )


def generate_audio() -> bytes:
    prompt = build_prompt()
    body = {
        "prompt": prompt,
        "music_length_ms": TARGET_MS,
        "output_format": "mp3_44100_128",
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    print(f"  prompt length: {len(prompt)} chars, target {TARGET_MS/1000:.0f}s")
    print(f"  calling {ELEVENLABS_MUSIC_ENDPOINT}...")
    start = time.time()
    resp = httpx.post(ELEVENLABS_MUSIC_ENDPOINT, headers=headers, json=body, timeout=600)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs {resp.status_code}: {resp.text[:400]}")
    if len(resp.content) < 5000:
        raise RuntimeError(f"too small: {len(resp.content)} bytes")
    elapsed = time.time() - start
    print(f"  got {len(resp.content):,} bytes in {elapsed:.0f}s")
    return resp.content


def main():
    print(f"\n═══ Re-rendering {SONG_ID} with ElevenLabs Music ═══")
    audio_bytes = generate_audio()
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    duration = round(len(seg) / 1000)
    print(f"  duration: {duration}s")

    # Write to all local paths the publish flow expects.
    paths = [
        BASE_DIR / "seed_output" / "silly_songs" / f"{SONG_ID}.mp3",
        WEB_ROOT / "public" / "audio" / "silly-songs" / f"{SONG_ID}.mp3",
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{SONG_ID}.mp3",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(audio_bytes)
        print(f"  wrote: {p.relative_to(REPO_ROOT)}")

    # Update the per-item JSON in data/silly_songs/ — audio_engine + duration.
    js_path = BASE_DIR / "data" / "silly_songs" / f"{SONG_ID}.json"
    js = json.loads(js_path.read_text())
    js["audio_engine"] = "elevenlabs-music"
    js["duration_seconds"] = duration
    js["style_prompt"] = STYLE_PROMPT
    js["target_length_ms"] = TARGET_MS
    js_path.write_text(json.dumps(js, ensure_ascii=False, indent=2))
    print(f"  updated: {js_path.relative_to(REPO_ROOT)}  (duration={duration}s)")

    # Update silly_songs.json index (in seed_output/) — audio_engine + duration.
    idx_path = BASE_DIR / "seed_output" / "silly_songs" / "silly_songs.json"
    if idx_path.exists():
        idx = json.loads(idx_path.read_text())
        items = idx.get("items", idx) if isinstance(idx, dict) else idx
        for it in items:
            if it.get("id") == SONG_ID:
                it["audio_engine"] = "elevenlabs-music"
                it["tts_engine"] = "elevenlabs-music"
                it["duration_seconds"] = duration
                it["durationSec"] = duration
                if it.get("audio_variants"):
                    for v in it["audio_variants"]:
                        v["provider"] = "elevenlabs-music"
                        v["voice"] = "elevenlabs_music_v1"
                        v["duration_seconds"] = duration
                break
        idx_path.write_text(json.dumps(items if not isinstance(idx, dict) else idx, ensure_ascii=False, indent=2))
        print(f"  updated: {idx_path.relative_to(REPO_ROOT)}")

    # Update content.json mirror.
    cj_path = BASE_DIR / "seed_output" / "content.json"
    data = json.loads(cj_path.read_text())
    items = data["items"] if isinstance(data, dict) else data
    for it in items:
        if it.get("id") == SONG_ID:
            it["audio_engine"] = "elevenlabs-music"
            it["tts_engine"] = "elevenlabs-music"
            it["duration_seconds"] = duration
            it["durationSec"] = duration
            if it.get("audio_variants"):
                for v in it["audio_variants"]:
                    v["provider"] = "elevenlabs-music"
                    v["voice"] = "elevenlabs_music_v1"
                    v["duration_seconds"] = duration
            break
    if isinstance(data, dict):
        data["items"] = items
    cj_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  updated: {cj_path.relative_to(REPO_ROOT)}")

    print("\n  Next: scp to prod silly-songs path + audio-store mirror, then verify.")


if __name__ == "__main__":
    main()
