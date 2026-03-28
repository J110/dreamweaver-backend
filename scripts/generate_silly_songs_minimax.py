#!/usr/bin/env python3
"""Generate silly song audio via MiniMax Music 1.5 on Replicate.

One variant per song. Downloads the output MP3 and saves it.

Usage:
    python3 scripts/generate_silly_songs_minimax.py --all
    python3 scripts/generate_silly_songs_minimax.py --song five-more-minutes
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

# Load .env
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

try:
    import replicate
except ImportError:
    print("ERROR: replicate required — pip install replicate")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx")
    sys.exit(1)

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "silly_songs"
AUDIO_DIR = BASE_DIR / "public" / "audio" / "silly-songs"
AUDIO_STORE = Path("/opt/audio-store/silly-songs")

AUDIO_DIR.mkdir(parents=True, exist_ok=True)

MAX_LYRICS_CHARS = 600


def trim_lyrics(lyrics: str) -> str:
    """Trim lyrics to fit within MiniMax's 600-char limit.

    Keeps complete sections (verse/chorus/bridge) that fit.
    """
    if len(lyrics) <= MAX_LYRICS_CHARS:
        return lyrics

    # Split into sections
    sections = []
    current = []
    for line in lyrics.split("\n"):
        if line.startswith("[") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    # Build up lyrics keeping complete sections
    result = []
    total = 0
    for section in sections:
        new_total = total + len(section) + (1 if result else 0)  # +1 for newline between sections
        if new_total <= MAX_LYRICS_CHARS:
            result.append(section)
            total = new_total
        else:
            break

    return "\n".join(result)


def generate_song(song: dict, force: bool = False) -> bool:
    """Generate audio for a single song via MiniMax Music 1.5."""
    song_id = song["id"]
    title = song["title"]
    audio_path = AUDIO_DIR / f"{song_id}.mp3"

    if audio_path.exists() and not force:
        print(f"  {title} — already exists, skipping")
        return True

    lyrics = song["lyrics"]
    style = song["style_prompt"]

    trimmed = trim_lyrics(lyrics)
    print(f"\n  Generating: {title}")
    print(f"    Lyrics: {len(lyrics)} chars -> {len(trimmed)} chars (trimmed)")
    print(f"    Style: {style[:80]}...")

    try:
        print(f"    Calling MiniMax Music 1.5 on Replicate...")
        output = replicate.run(
            "minimax/music-1.5",
            input={
                "prompt": style,
                "lyrics": trimmed,
            },
        )

        # output is a URL string to the generated audio
        if not output:
            print(f"    ERROR: No output from MiniMax")
            return False

        audio_url = str(output)
        print(f"    Got audio URL, downloading...")

        # Download the audio
        resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 1000:
            print(f"    ERROR: Download failed ({resp.status_code}, {len(resp.content)} bytes)")
            return False

        # Save
        audio_path.write_bytes(resp.content)
        size_kb = len(resp.content) / 1024
        print(f"    Saved: {audio_path.name} ({size_kb:.0f} KB)")

        # Get duration
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(str(audio_path))
            duration_s = len(seg) / 1000.0
            print(f"    Duration: {duration_s:.1f}s")
            song["duration_seconds"] = int(duration_s)
        except Exception:
            print(f"    (could not read duration)")

        # Update JSON
        song["audio_file"] = f"{song_id}.mp3"
        json_path = DATA_DIR / f"{song_id}.json"
        with open(json_path, "w") as f:
            json.dump(song, f, indent=2)

        # Backup to persistent store
        if AUDIO_STORE.exists():
            backup_path = AUDIO_STORE / f"{song_id}.mp3"
            shutil.copy2(str(audio_path), str(backup_path))
            print(f"    Backed up to {backup_path}")

        return True

    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def load_songs(song_id=None):
    songs = []
    if not DATA_DIR.exists():
        return songs
    for f in sorted(DATA_DIR.glob("*.json")):
        if song_id and f.stem != song_id:
            continue
        try:
            with open(f) as fh:
                song = json.load(fh)
                song.setdefault("id", f.stem)
                songs.append(song)
        except Exception as e:
            print(f"  Failed to load {f}: {e}")
    return songs


def main():
    parser = argparse.ArgumentParser(description="Generate silly songs via MiniMax Music 1.5")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--song", help="Generate a specific song by ID")
    parser.add_argument("--force", action="store_true", help="Regenerate even if exists")
    args = parser.parse_args()

    if not args.all and not args.song:
        parser.error("Specify --all or --song <id>")

    songs = load_songs(args.song)
    if not songs:
        print(f"No songs found")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"MiniMax Music 1.5 — {len(songs)} song(s)")
    print(f"{'=' * 60}")

    success = 0
    for song in songs:
        if generate_song(song, force=args.force):
            success += 1
        if song != songs[-1]:
            time.sleep(5)

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{len(songs)} songs generated")


if __name__ == "__main__":
    main()
