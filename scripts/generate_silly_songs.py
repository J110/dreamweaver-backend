#!/usr/bin/env python3
"""Generate silly song audio via ACE-Step on Modal.

Reads song data from data/silly_songs/*.json, generates 2 variants per song
via the SongGen Modal endpoint, picks the variant closest to the target
duration, and saves the MP3.

Output:
  public/audio/silly-songs/{song_id}.mp3

Usage:
    python3 scripts/generate_silly_songs.py --all
    python3 scripts/generate_silly_songs.py --song not-a-rock
    python3 scripts/generate_silly_songs.py --all --force
    python3 scripts/generate_silly_songs.py --all --variants 3
"""

import argparse
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

# Load .env (scripts run outside Docker, so env vars aren't auto-loaded)
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx")
    sys.exit(1)

try:
    from pydub import AudioSegment
except ImportError:
    print("ERROR: pydub required — pip install pydub")
    sys.exit(1)

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "silly_songs"
AUDIO_DIR = BASE_DIR / "public" / "audio" / "silly-songs"
AUDIO_STORE = Path("/opt/audio-store/silly-songs")  # persistent backup on GCP

# ── Config ───────────────────────────────────────────────────────────

SONGGEN_URL = os.getenv("SONGGEN_URL", "")
MIN_DURATION_S = 60
MAX_DURATION_S = 100
NUM_VARIANTS = 2


def load_env():
    """Load .env if SONGGEN_URL not already set."""
    if SONGGEN_URL:
        return
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if key and not os.environ.get(key):
                os.environ[key] = val


def get_songgen_url() -> str:
    url = os.environ.get("SONGGEN_URL", "")
    if not url:
        print("ERROR: SONGGEN_URL not set in environment or .env")
        sys.exit(1)
    return url


def get_mp3_duration(audio_bytes: bytes) -> float:
    """Get duration in seconds from MP3 bytes."""
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        return len(audio) / 1000.0
    except Exception:
        return 0.0


def generate_song(song: dict, force: bool = False, num_variants: int = NUM_VARIANTS) -> bool:
    """Generate audio for a single song. Returns True on success."""
    song_id = song["id"]
    title = song["title"]
    target_duration = song.get("duration_seconds", 80)
    audio_path = AUDIO_DIR / f"{song_id}.mp3"

    if audio_path.exists() and not force:
        print(f"  {title} — already exists, skipping")
        return True

    url = get_songgen_url()
    lyrics = song.get("lyrics", "")
    description = song.get("style_prompt", "")

    if not lyrics:
        print(f"  {title} — no lyrics, skipping")
        return False

    print(f"\n  Generating: {title} (target {target_duration}s, {num_variants} variants)")

    candidates = []  # (audio_bytes, duration, seed)

    for i in range(num_variants):
        seed = hash(song_id) % 999999 + 1 + (i * 1000)
        payload = {
            "lyrics": lyrics,
            "description": description,
            "mode": "full",
            "format": "mp3",
            "duration": target_duration,
            "seed": seed,
        }

        print(f"    Variant {i + 1}/{num_variants} (seed={seed})...")
        try:
            with httpx.Client(timeout=600.0) as client:
                resp = client.post(url, json=payload, follow_redirects=True)
                if resp.status_code != 200:
                    print(f"    HTTP {resp.status_code}: {resp.text[:200]}")
                    continue
                audio_bytes = resp.content
        except Exception as e:
            print(f"    Request failed: {e}")
            continue

        if not audio_bytes or len(audio_bytes) < 1000:
            print(f"    Empty/tiny audio ({len(audio_bytes)} bytes)")
            continue

        duration = get_mp3_duration(audio_bytes)
        print(f"    Got {duration:.1f}s ({len(audio_bytes) / 1024:.0f} KB)")
        candidates.append((audio_bytes, duration, seed))

        # Rate limit pause between variants
        if i < num_variants - 1:
            time.sleep(5)

    if not candidates:
        print(f"  FAILED: {title} — no valid variants generated")
        return False

    # Pick variant closest to target duration
    best = min(candidates, key=lambda c: abs(c[1] - target_duration))
    audio_bytes, duration, seed = best

    # Flag bad durations
    if duration < MIN_DURATION_S:
        print(f"  WARNING: {title} is only {duration:.1f}s (min {MIN_DURATION_S}s) — may need lyrics extension")
    elif duration > MAX_DURATION_S:
        print(f"  WARNING: {title} is {duration:.1f}s (max {MAX_DURATION_S}s) — may need lyrics trim")

    # Save audio
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    # Update JSON with audio info
    song["audio_file"] = f"{song_id}.mp3"
    song["duration_seconds"] = round(duration)
    json_path = DATA_DIR / f"{song_id}.json"
    with open(json_path, "w") as f:
        json.dump(song, f, indent=2)

    print(f"  Saved: {song_id}.mp3 ({duration:.1f}s, seed={seed})")

    # Backup to persistent store
    backup_audio(song_id, audio_bytes)

    return True


def backup_audio(song_id: str, audio_bytes: bytes):
    """Backup audio to persistent store (survives repo re-clones)."""
    if not AUDIO_STORE.parent.exists():
        return  # Not on GCP server
    try:
        AUDIO_STORE.mkdir(parents=True, exist_ok=True)
        backup_path = AUDIO_STORE / f"{song_id}.mp3"
        with open(backup_path, "wb") as f:
            f.write(audio_bytes)
        print(f"    Backed up to {backup_path}")
    except Exception as e:
        print(f"    Backup failed (non-fatal): {e}")


def recover_from_store():
    """Recover audio files from persistent store if missing locally."""
    if not AUDIO_STORE.exists():
        return 0
    recovered = 0
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for src in AUDIO_STORE.glob("*.mp3"):
        dest = AUDIO_DIR / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            print(f"  Recovered from store: {src.name}")
            recovered += 1
    return recovered


def load_songs(song_id: str | None = None) -> list[dict]:
    """Load song data from JSON files."""
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
    parser = argparse.ArgumentParser(description="Generate silly song audio via ACE-Step")
    parser.add_argument("--all", action="store_true", help="Generate all songs")
    parser.add_argument("--song", help="Generate a specific song by ID")
    parser.add_argument("--force", action="store_true", help="Regenerate even if files exist")
    parser.add_argument("--variants", type=int, default=NUM_VARIANTS,
                        help=f"Number of variants per song (default: {NUM_VARIANTS})")
    parser.add_argument("--recover", action="store_true",
                        help="Recover audio from persistent store only")
    args = parser.parse_args()

    if args.recover:
        n = recover_from_store()
        print(f"Recovered {n} files from persistent store")
        return

    if not args.all and not args.song:
        parser.error("Specify --all or --song <id>")

    load_env()

    # Auto-recover before generating
    recovered = recover_from_store()
    if recovered:
        print(f"Auto-recovered {recovered} files from persistent store\n")

    songs = load_songs(args.song)
    if not songs:
        print(f"No songs found" + (f" for id '{args.song}'" if args.song else ""))
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"Silly Songs Generation — {len(songs)} song(s)")
    print(f"{'=' * 60}")

    success = 0
    for song in songs:
        if generate_song(song, force=args.force, num_variants=args.variants):
            success += 1
        # Rate limit between songs
        if song != songs[-1]:
            time.sleep(10)

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{len(songs)} songs generated")
    if success < len(songs):
        print("Some songs failed — re-run with --force to retry")


if __name__ == "__main__":
    main()
