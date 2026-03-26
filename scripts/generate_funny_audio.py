#!/usr/bin/env python3
"""Generate multi-voice TTS audio chunks for funny shorts.

Saves individual per-sentence WAV/MP3 chunks + a manifest JSON.
Does NOT stitch or mix — that's mix_funny_short.py's job.

Output per short:
    public/audio/funny-shorts/<short-id>/
        chunk_00_MOUSE.mp3
        chunk_01_CROC.mp3
        ...
        manifest.json   # sentence metadata + chunk filenames

Usage:
    python3 scripts/generate_funny_audio.py --short-id crocodile-rock-001-a1b2
    python3 scripts/generate_funny_audio.py --all
    python3 scripts/generate_funny_audio.py --all --force
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
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
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
CHUNKS_DIR = Path(__file__).resolve().parents[1] / "public" / "audio" / "funny-shorts"
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
    delivery_tags: list = None

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
            remainder = line[section_match.end():].strip()
            if not remainder:
                continue
            line = remainder

        if line.startswith("[/"):
            continue
        if re.match(r"^\[(TITLE|AGE|VOICES|COMEDY_TYPE|COVER|PREMISE):", line):
            continue

        # Parse character tag — accept [CHAR] text or CHAR: text
        char_match = re.match(r"^\[(\w+)\]\s*(.+)", line)
        if not char_match:
            char_match = re.match(r"^(\w+):\s+(.+)", line)
        if not char_match:
            continue

        character = char_match.group(1).upper()
        rest = char_match.group(2)

        if character not in FUNNY_VOICE_MAP:
            continue

        voice_id = FUNNY_VOICE_MAP[character]
        delivery_tags = parse_delivery_tags(rest)
        is_punchline = "[PUNCHLINE]" in rest

        sting = None
        sting_match = re.search(r"\[STING:\s*(\w+)\]", rest)
        if sting_match:
            sting = sting_match.group(1)

        # Clean text: remove all tags
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
    """Get TTS parameters with delivery + punchline adjustments."""
    params = FUNNY_VOICE_PARAMS.get(voice_id, {}).copy()

    if delivery_tags:
        params = apply_delivery(params, delivery_tags)

    if is_punchline and voice_id in FUNNY_PUNCHLINE_PARAMS:
        punch = FUNNY_PUNCHLINE_PARAMS[voice_id]
        params["exaggeration"] = punch["exaggeration"]
        params["speed"] = params.get("speed", 0.90) * punch["speed_multiplier"]

    return params


def generate_tts_modal(text: str, voice_id: str, params: dict) -> bytes:
    """Generate TTS audio via Modal Chatterbox endpoint."""
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


def generate_chunks_for_short(short: dict, force: bool = False) -> bool:
    """Generate individual TTS chunks for a funny short.

    Saves each sentence as a separate MP3 file + manifest.json.
    Returns True on success.
    """
    script = short.get("script", "")
    short_id = short["id"]

    # Output directory for this short's chunks
    chunk_dir = CHUNKS_DIR / short_id
    manifest_path = chunk_dir / "manifest.json"

    # Skip if manifest exists and not forcing
    if manifest_path.exists() and not force:
        print(f"  Chunks already exist: {chunk_dir}, skipping")
        return True

    sentences = parse_voiced_sentences(script)
    if not sentences:
        print(f"  No sentences parsed from script for {short_id}")
        return False

    print(f"  Parsed {len(sentences)} sentences across voices: "
          f"{set(s.voice_id for s in sentences)}")

    chunk_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    for i, sent in enumerate(sentences):
        params = get_tts_params(sent.voice_id, sent.is_punchline,
                                delivery_tags=sent.delivery_tags)
        label = " [PUNCHLINE]" if sent.is_punchline else ""
        tag_label = f" [DELIVERY: {', '.join(sent.delivery_tags)}]" if sent.delivery_tags else ""
        print(f"  [{i+1}/{len(sentences)}] {sent.character}: "
              f"\"{sent.text[:50]}...\"{label}{tag_label}")

        chunk_filename = f"chunk_{i:02d}_{sent.character}.mp3"
        chunk_path = chunk_dir / chunk_filename

        # Skip if chunk already exists and not forcing
        if chunk_path.exists() and not force:
            print(f"    (cached)")
        else:
            try:
                audio_bytes = generate_tts_modal(sent.text, sent.voice_id, params)
                with open(chunk_path, "wb") as f:
                    f.write(audio_bytes)
            except Exception as e:
                print(f"    TTS ERROR: {e}")
                return False

        manifest_entries.append({
            "index": i,
            "chunk_file": chunk_filename,
            "character": sent.character,
            "voice_id": sent.voice_id,
            "text": sent.text,
            "is_punchline": sent.is_punchline,
            "sting": sent.sting,
            "section": sent.section,
            "delivery_tags": sent.delivery_tags,
        })

    # Write manifest
    manifest = {
        "short_id": short_id,
        "chunk_count": len(manifest_entries),
        "sentences": manifest_entries,
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Saved {len(manifest_entries)} chunks + manifest to {chunk_dir}")
    return True


def process_short(short_path: Path, force: bool = False) -> bool:
    """Process a single funny short JSON file."""
    with open(short_path) as f:
        short = json.load(f)

    short_id = short.get("id", short_path.stem)
    short.setdefault("id", short_id)

    return generate_chunks_for_short(short, force=force)


def main():
    parser = argparse.ArgumentParser(description="Generate funny short audio chunks")
    parser.add_argument("--short-id", help="Process a specific short by ID")
    parser.add_argument("--all", action="store_true", help="Process all shorts")
    parser.add_argument("--force", action="store_true", help="Regenerate even if chunks exist")
    args = parser.parse_args()

    if not args.short_id and not args.all:
        parser.error("Specify --short-id or --all")

    if args.short_id:
        path = DATA_DIR / f"{args.short_id}.json"
        if not path.exists():
            print(f"ERROR: Short not found: {path}")
            sys.exit(1)
        print(f"Processing: {args.short_id}")
        ok = process_short(path, force=args.force)
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
            if process_short(path, force=args.force):
                success += 1

        print(f"\n{'='*60}")
        print(f"Done: {success}/{len(shorts)} succeeded")


if __name__ == "__main__":
    main()
