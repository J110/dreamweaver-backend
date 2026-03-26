#!/usr/bin/env python3
"""Generate multi-voice TTS audio for funny shorts.

Usage:
    python3 scripts/generate_funny_audio.py --short-id crocodile-rock-001-a1b2
    python3 scripts/generate_funny_audio.py --all
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tts.voice_service import (
    FUNNY_VOICE_MAP,
    FUNNY_VOICE_PARAMS,
    FUNNY_PUNCHLINE_PARAMS,
)
from app.services.tts.delivery import (
    apply_delivery,
    parse_delivery_tags,
    strip_delivery_tags,
    get_sentence_gap,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
AUDIO_OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-shorts"
MODAL_TTS_URL = os.getenv(
    "MODAL_TTS_URL",
    "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run",
)


@dataclass
class VoicedSentence:
    character: str       # MOUSE, CROC, WITCH, etc.
    voice_id: str        # high_pitch_cartoon, comedic_villain, etc.
    text: str            # Clean text without tags
    is_punchline: bool
    sting: Optional[str]  # Sting type if present
    section: str         # SETUP, BEAT_1, etc.
    delivery_tags: list = None  # ["curious", "tentative"], etc.

    def __post_init__(self):
        if self.delivery_tags is None:
            self.delivery_tags = []


def parse_voiced_sentences(script: str) -> list[VoicedSentence]:
    """Parse a funny short script into voiced sentences."""
    sentences = []
    current_section = ""

    for line in script.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Track sections
        section_match = re.match(r"^\[(SETUP|BEAT_\d|BUTTON)\]", line)
        if section_match:
            current_section = section_match.group(1)
            # Check if there's content on the same line after the section tag
            remainder = line[section_match.end():].strip()
            if not remainder:
                continue
            line = remainder

        if line.startswith("[/"):
            continue
        if re.match(r"^\[(TITLE|AGE|VOICES|COMEDY_TYPE):", line):
            continue

        # Parse character tag — accept [CHAR] text or CHAR: text
        char_match = re.match(r"^\[(\w+)\]\s*(.+)", line)
        if not char_match:
            # Fallback: accept CHAR: text format (LLM sometimes generates this)
            char_match = re.match(r"^(\w+):\s+(.+)", line)
        if not char_match:
            continue

        character = char_match.group(1).upper()
        rest = char_match.group(2)

        # Check if character is valid
        if character not in FUNNY_VOICE_MAP:
            continue

        voice_id = FUNNY_VOICE_MAP[character]

        # Extract delivery tags before cleaning
        delivery_tags = parse_delivery_tags(rest)

        # Check for punchline
        is_punchline = "[PUNCHLINE]" in rest

        # Extract sting
        sting = None
        sting_match = re.search(r"\[STING:\s*(\w+)\]", rest)
        if sting_match:
            sting = sting_match.group(1)

        # Clean text: remove all tags (delivery, punchline, sting)
        clean = strip_delivery_tags(rest)
        clean = re.sub(r"\[/?PUNCHLINE\]", "", clean)
        clean = re.sub(r"\[STING:\s*\w+\]", "", clean)
        clean = clean.strip()

        if clean:
            sentences.append(VoicedSentence(
                character=character,
                voice_id=voice_id,
                text=clean,
                is_punchline=is_punchline,
                sting=sting,
                section=current_section,
                delivery_tags=delivery_tags,
            ))

    return sentences


def get_tts_params(voice_id: str, is_punchline: bool,
                   delivery_tags: list = None) -> dict:
    """Get TTS parameters for a voice, with delivery + punchline adjustments.

    Order: base params -> delivery tag multipliers -> punchline boost (overwrites exag).
    """
    params = FUNNY_VOICE_PARAMS.get(voice_id, {}).copy()

    # 1. Apply delivery tag adjustments (multiplicative)
    if delivery_tags:
        params = apply_delivery(params, delivery_tags)

    # 2. Apply punchline boost ON TOP of delivery (overwrites exaggeration)
    if is_punchline and voice_id in FUNNY_PUNCHLINE_PARAMS:
        punch = FUNNY_PUNCHLINE_PARAMS[voice_id]
        params["exaggeration"] = punch["exaggeration"]
        params["speed"] = params.get("speed", 0.90) * punch["speed_multiplier"]

    return params


def generate_tts_modal(text: str, voice_id: str, params: dict) -> bytes:
    """Generate TTS audio via Modal Chatterbox endpoint (GET with query params)."""
    import httpx
    from urllib.parse import urlencode

    query_params = {
        "text": text,
        "voice": voice_id,
        "exaggeration": params.get("exaggeration", 0.7),
        "cfg_weight": params.get("cfg_weight", 0.5),
        "speed": params.get("speed", 0.9),
    }

    url = f"{MODAL_TTS_URL}?{urlencode(query_params)}"

    with httpx.Client(timeout=120) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def stitch_audio_chunks(chunks: list[bytes], gap_ms: int = 300,
                        gap_list: list[int] = None) -> bytes:
    """Stitch audio chunks with gaps between them using pydub.

    If gap_list is provided, uses variable gaps per sentence boundary.
    gap_list[i] is the gap AFTER chunk[i] (length = len(chunks) - 1).
    Falls back to fixed gap_ms if gap_list is not provided.
    """
    from pydub import AudioSegment
    import io

    if not chunks:
        return b""

    combined = AudioSegment.empty()

    for i, chunk in enumerate(chunks):
        try:
            seg = AudioSegment.from_mp3(io.BytesIO(chunk))
        except Exception:
            seg = AudioSegment.from_wav(io.BytesIO(chunk))

        if i > 0:
            # Use variable gap if available, otherwise fixed
            if gap_list and i - 1 < len(gap_list):
                this_gap = gap_list[i - 1]
            else:
                this_gap = gap_ms
            combined += AudioSegment.silent(duration=this_gap)
        combined += seg

    buf = io.BytesIO()
    combined.export(buf, format="mp3", bitrate="128k")
    return buf.getvalue()


def generate_audio_for_short(short: dict) -> Optional[str]:
    """Generate multi-voice narration audio for a funny short.

    Returns the output filename, or None on failure.
    """
    script = short.get("script", "")
    short_id = short["id"]

    sentences = parse_voiced_sentences(script)
    if not sentences:
        print(f"  No sentences parsed from script for {short_id}")
        return None

    print(f"  Parsed {len(sentences)} sentences across voices: "
          f"{set(s.voice_id for s in sentences)}")

    audio_chunks = []
    for i, sent in enumerate(sentences):
        params = get_tts_params(sent.voice_id, sent.is_punchline,
                                delivery_tags=sent.delivery_tags)
        label = " [PUNCHLINE]" if sent.is_punchline else ""
        tag_label = f" [DELIVERY: {', '.join(sent.delivery_tags)}]" if sent.delivery_tags else ""
        print(f"  [{i+1}/{len(sentences)}] {sent.character}: "
              f"\"{sent.text[:50]}...\"{label}{tag_label}")

        try:
            chunk = generate_tts_modal(sent.text, sent.voice_id, params)
            audio_chunks.append(chunk)
        except Exception as e:
            print(f"    TTS ERROR: {e}")
            return None

    # Calculate variable gaps based on delivery tags
    gap_list = []
    for i in range(len(sentences) - 1):
        gap = get_sentence_gap(sentences[i], sentences[i + 1])
        gap_list.append(gap)

    print(f"  Stitching {len(audio_chunks)} chunks with variable gaps "
          f"({min(gap_list) if gap_list else 300}-{max(gap_list) if gap_list else 300}ms)...")
    narration = stitch_audio_chunks(audio_chunks, gap_ms=300, gap_list=gap_list)

    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = f"{short_id}.mp3"
    out_path = AUDIO_OUT_DIR / out_file

    with open(out_path, "wb") as f:
        f.write(narration)

    # Calculate duration
    from pydub import AudioSegment
    import io
    seg = AudioSegment.from_mp3(io.BytesIO(narration))
    duration_sec = int(len(seg) / 1000)

    print(f"  Output: {out_path} ({duration_sec}s)")
    return out_file, duration_sec


def process_short(short_path: Path) -> bool:
    """Process a single funny short JSON file."""
    with open(short_path) as f:
        short = json.load(f)

    short_id = short.get("id", short_path.stem)
    short.setdefault("id", short_id)

    if short.get("audio_file"):
        audio_path = AUDIO_OUT_DIR / short["audio_file"]
        if audio_path.exists():
            print(f"  Audio already exists: {audio_path}, skipping")
            return True

    result = generate_audio_for_short(short)
    if result is None:
        return False

    out_file, duration = result
    short["audio_file"] = out_file
    short["duration_seconds"] = duration

    with open(short_path, "w") as f:
        json.dump(short, f, indent=2)

    return True


def main():
    parser = argparse.ArgumentParser(description="Generate funny short audio")
    parser.add_argument("--short-id", help="Process a specific short by ID")
    parser.add_argument("--all", action="store_true", help="Process all shorts without audio")
    parser.add_argument("--force", action="store_true", help="Regenerate even if audio exists")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            print(f"ERROR: Short not found: {path}")
            sys.exit(1)
        print(f"Processing: {args.short_id}")
        ok = process_short(path)
        sys.exit(0 if ok else 1)

    if args.all:
        if not DATA_DIR.exists():
            print("No funny shorts data directory found")
            sys.exit(0)

        shorts = sorted(DATA_DIR.glob("*.json"))
        print(f"Found {len(shorts)} funny shorts")

        success = 0
        for path in shorts:
            print(f"\n{'='*60}")
            print(f"Processing: {path.stem}")
            if process_short(path):
                success += 1

        print(f"\n{'='*60}")
        print(f"Done: {success}/{len(shorts)} succeeded")


if __name__ == "__main__":
    main()
