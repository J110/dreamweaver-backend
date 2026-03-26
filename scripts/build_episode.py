#!/usr/bin/env python3
"""Build complete Before Bed episodes with show structure.

Wraps the mixed story audio with:
  [show intro jingle] → [host intro TTS] → [character intro jingles]
  → [story] → [character outro jingle] → [host outro TTS] → [show outro jingle]

Requires:
  - Jingles in public/audio/jingles/ (run generate_jingles.py first)
  - Mixed story audio in public/audio/funny-shorts/<id>.mp3 (run mix_funny_short.py first)
  - host_intro and host_outro text in the short JSON

Usage:
    python3 scripts/build_episode.py --short-id the-bridge-too-far-4b64
    python3 scripts/build_episode.py --all
    python3 scripts/build_episode.py --all --force
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydub import AudioSegment

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
AUDIO_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-shorts"
JINGLES_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "jingles"

MODAL_TTS_URL = os.getenv(
    "MODAL_TTS_URL",
    "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run",
)

# ── Jingle File References ────────────────────────────────────

SHOW_INTRO_FILE = "beforebed_intro_jingle.wav"
SHOW_OUTRO_FILE = "beforebed_outro_jingle.wav"

CHARACTER_INTRO_JINGLES = {
    "comedic_villain":    "char_jingle_boomy_intro.wav",
    "high_pitch_cartoon": "char_jingle_pip_intro.wav",
    "mysterious_witch":   "char_jingle_shadow_intro.wav",
    "young_sweet":        "char_jingle_sunny_intro.wav",
    "musical_original":   "char_jingle_melody_intro.wav",
}

CHARACTER_OUTRO_JINGLES = {
    "comedic_villain":    "char_jingle_boomy_outro.wav",
    "high_pitch_cartoon": "char_jingle_pip_outro.wav",
    "mysterious_witch":   "char_jingle_shadow_outro.wav",
    "young_sweet":        "char_jingle_sunny_outro.wav",
    "musical_original":   "char_jingle_melody_outro.wav",
}

# ── Host Voice TTS Params (Melody as show host) ──────────────

HOST_VOICE_PARAMS = {
    "voice": "musical_original",
    "exaggeration": 0.65,
    "cfg_weight": 0.50,
    "speed": 0.90,
}

# ── Silence Gaps ──────────────────────────────────────────────

GAP_AFTER_SHOW_INTRO = 200      # ms
GAP_AFTER_HOST_INTRO = 300      # ms
GAP_BETWEEN_CHAR_JINGLES = 150  # ms
GAP_BEFORE_STORY = 300          # ms (breath before story starts)
GAP_AFTER_STORY = 500           # ms (breath after story ends)
GAP_AFTER_CHAR_OUTRO = 200      # ms
GAP_AFTER_HOST_OUTRO = 200      # ms


# ── TTS Generation ────────────────────────────────────────────

def generate_host_tts(text: str) -> bytes | None:
    """Generate TTS audio for host intro/outro via Modal Chatterbox."""
    import httpx

    query_params = {
        "text": text,
        "voice": HOST_VOICE_PARAMS["voice"],
        "exaggeration": HOST_VOICE_PARAMS["exaggeration"],
        "cfg_weight": HOST_VOICE_PARAMS["cfg_weight"],
        "speed": HOST_VOICE_PARAMS["speed"],
    }

    url = f"{MODAL_TTS_URL}?{urlencode(query_params)}"

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.get(url)
            resp.raise_for_status()
            if len(resp.content) > 1000:
                return resp.content
            else:
                print(f"    Host TTS too small: {len(resp.content)} bytes")
                return None
    except Exception as e:
        print(f"    Host TTS error: {e}")
        return None


def load_audio(path: Path) -> AudioSegment | None:
    """Load an audio file. Returns None if not found."""
    if not path.exists():
        print(f"    Missing: {path}")
        return None
    try:
        return AudioSegment.from_file(str(path))
    except Exception as e:
        print(f"    Error loading {path}: {e}")
        return None


# ── Episode Assembly ──────────────────────────────────────────

def build_episode(short: dict, force: bool = False) -> bool:
    """Build a complete Before Bed episode for a short.

    Assembly order:
      1. Show intro jingle
      2. Host intro (Melody TTS)
      3. Character intro jingles (primary first, then others)
      4. Story (pre-mixed audio)
      5. Primary character outro jingle
      6. Host outro (Melody TTS)
      7. Show outro jingle
    """
    short_id = short["id"]
    episode_path = AUDIO_DIR / f"{short_id}_episode.mp3"

    if episode_path.exists() and not force:
        print(f"  Episode already exists: {episode_path}, skipping")
        return True

    # ── Validate inputs ───────────────────────────────────────

    # Story audio
    story_path = AUDIO_DIR / f"{short_id}.mp3"
    if not story_path.exists():
        print(f"  No story audio found — run mix_funny_short.py first")
        return False

    # Host text
    host_intro_text = short.get("host_intro", "")
    host_outro_text = short.get("host_outro", "")
    if not host_intro_text or not host_outro_text:
        print(f"  Missing host_intro or host_outro text in JSON")
        return False

    # Jingles
    show_intro_path = JINGLES_DIR / SHOW_INTRO_FILE
    show_outro_path = JINGLES_DIR / SHOW_OUTRO_FILE
    if not show_intro_path.exists() or not show_outro_path.exists():
        print(f"  Missing show jingles — run generate_jingles.py first")
        return False

    # ── Load audio components ─────────────────────────────────

    print(f"  Loading components...")

    show_intro = load_audio(show_intro_path)
    show_outro = load_audio(show_outro_path)
    story = load_audio(story_path)

    if not show_intro or not show_outro or not story:
        return False

    # Generate host TTS
    print(f"  Generating host intro TTS: \"{host_intro_text[:60]}...\"")
    host_intro_bytes = generate_host_tts(host_intro_text)
    if not host_intro_bytes:
        print(f"  Failed to generate host intro TTS")
        return False
    host_intro_audio = AudioSegment.from_mp3(
        __import__("io").BytesIO(host_intro_bytes)
    )

    print(f"  Generating host outro TTS: \"{host_outro_text[:60]}...\"")
    host_outro_bytes = generate_host_tts(host_outro_text)
    if not host_outro_bytes:
        print(f"  Failed to generate host outro TTS")
        return False
    host_outro_audio = AudioSegment.from_mp3(
        __import__("io").BytesIO(host_outro_bytes)
    )

    # Character jingles
    voices = short.get("voices", [])
    primary_voice = short.get("primary_voice", voices[0] if voices else "")

    # Order: primary first, then others
    ordered_voices = [primary_voice] + [v for v in voices if v != primary_voice]

    char_intro_audios = []
    for voice_id in ordered_voices:
        jingle_file = CHARACTER_INTRO_JINGLES.get(voice_id)
        if jingle_file:
            jingle_path = JINGLES_DIR / jingle_file
            jingle_audio = load_audio(jingle_path)
            if jingle_audio:
                char_intro_audios.append(jingle_audio)

    char_outro_file = CHARACTER_OUTRO_JINGLES.get(primary_voice)
    char_outro_audio = None
    if char_outro_file:
        char_outro_audio = load_audio(JINGLES_DIR / char_outro_file)

    # ── Assemble episode ──────────────────────────────────────

    print(f"  Assembling episode...")

    episode = AudioSegment.empty()

    # 1. Show intro jingle
    episode += show_intro
    episode += AudioSegment.silent(duration=GAP_AFTER_SHOW_INTRO)

    # 2. Host intro
    episode += host_intro_audio
    episode += AudioSegment.silent(duration=GAP_AFTER_HOST_INTRO)

    # 3. Character intro jingles
    for i, jingle in enumerate(char_intro_audios):
        episode += jingle
        if i < len(char_intro_audios) - 1:
            episode += AudioSegment.silent(duration=GAP_BETWEEN_CHAR_JINGLES)

    episode += AudioSegment.silent(duration=GAP_BEFORE_STORY)

    # 4. Story
    episode += story
    episode += AudioSegment.silent(duration=GAP_AFTER_STORY)

    # 5. Character outro jingle (primary only)
    if char_outro_audio:
        episode += char_outro_audio
        episode += AudioSegment.silent(duration=GAP_AFTER_CHAR_OUTRO)

    # 6. Host outro
    episode += host_outro_audio
    episode += AudioSegment.silent(duration=GAP_AFTER_HOST_OUTRO)

    # 7. Show outro jingle
    episode += show_outro

    # ── Export ─────────────────────────────────────────────────

    episode.export(str(episode_path), format="mp3", bitrate="128k")

    duration_sec = int(len(episode) / 1000)
    print(f"  Episode: {episode_path} ({duration_sec}s)")

    # Update short metadata
    short["episode_file"] = f"{short_id}_episode.mp3"
    short["episode_duration_seconds"] = duration_sec

    return True


# ── CLI ───────────────────────────────────────────────────────

def process_short(short_path: Path, force: bool = False) -> bool:
    """Build episode for a single short."""
    with open(short_path) as f:
        short = json.load(f)

    short.setdefault("id", short_path.stem)

    result = build_episode(short, force=force)

    if result:
        with open(short_path, "w") as f:
            json.dump(short, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build complete Before Bed episodes"
    )
    parser.add_argument("--short-id", help="Build episode for a specific short")
    parser.add_argument("--all", action="store_true",
                        help="Build episodes for all shorts")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild even if episode exists")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            print(f"ERROR: Short not found: {path}")
            sys.exit(1)
        print(f"\nBuilding episode: {args.short_id}")
        ok = process_short(path, args.force)
        sys.exit(0 if ok else 1)

    if args.all:
        if not DATA_DIR.exists():
            print("No funny shorts data directory")
            sys.exit(0)

        shorts = sorted(DATA_DIR.glob("*.json"))
        print(f"Found {len(shorts)} funny shorts")

        success = 0
        for path in shorts:
            print(f"\n{'=' * 60}")
            print(f"Building episode: {path.stem}")
            if process_short(path, args.force):
                success += 1

        print(f"\n{'=' * 60}")
        print(f"Done: {success}/{len(shorts)} episodes built")


if __name__ == "__main__":
    main()
