"""Slow down all pre-generated audio files to 80% speed for sleepy kids.

Uses ffmpeg's atempo filter which preserves pitch while changing tempo.
atempo=0.8 means 80% of original speed (i.e., 25% slower).

This processes files in-place (overwrites originals). It also updates
duration_seconds in content.json.

Usage:
    python3 scripts/slow_down_audio.py           # Process all files
    python3 scripts/slow_down_audio.py --dry-run  # Show plan only
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR_BACKEND = BASE_DIR / "audio" / "pre-gen"
AUDIO_DIR_WEB = BASE_DIR.parent / "dreamweaver-web" / "public" / "audio" / "pre-gen"

TEMPO = 0.8  # 80% speed = 25% slower

def get_ffmpeg():
    """Find ffmpeg binary."""
    for path in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(path):
            return path
    result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
    sys.exit(1)


def slow_down_file(ffmpeg: str, input_path: Path) -> float:
    """Slow down an MP3 file in-place using ffmpeg atempo filter.
    Returns the new duration in seconds."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            ffmpeg, "-y", "-i", str(input_path),
            "-filter:a", f"atempo={TEMPO}",
            "-b:a", "256k",
            tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: ffmpeg failed for {input_path.name}: {result.stderr[:200]}")
            os.unlink(tmp_path)
            return 0.0

        # Get new duration
        probe_cmd = [
            ffmpeg.replace("ffmpeg", "ffprobe"),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            tmp_path,
        ]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True)
        new_duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0

        # Replace original
        os.replace(tmp_path, str(input_path))
        return new_duration

    except Exception as e:
        print(f"  ERROR: {e}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Slow down audio to 80% speed")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    args = parser.parse_args()

    ffmpeg = get_ffmpeg()
    print(f"Using ffmpeg: {ffmpeg}")
    print(f"Tempo: {TEMPO} (={int(TEMPO*100)}% speed)")

    # Find all MP3 files in both directories
    dirs_to_process = []
    if AUDIO_DIR_BACKEND.exists():
        dirs_to_process.append(("backend", AUDIO_DIR_BACKEND))
    if AUDIO_DIR_WEB.exists():
        dirs_to_process.append(("web", AUDIO_DIR_WEB))

    if not dirs_to_process:
        print("ERROR: No audio directories found")
        sys.exit(1)

    # Collect all unique base filenames from web dir (source of truth)
    web_files = sorted(AUDIO_DIR_WEB.glob("*.mp3")) if AUDIO_DIR_WEB.exists() else []
    print(f"\nFound {len(web_files)} MP3 files to process")

    if args.dry_run:
        for f in web_files:
            print(f"  Would slow down: {f.name}")
        print("\nDry run complete.")
        return

    # Process web directory (these are the ones served to users)
    print(f"\n=== Processing web directory ===")
    duration_map = {}  # filename -> new_duration
    for i, mp3 in enumerate(web_files):
        print(f"[{i+1}/{len(web_files)}] {mp3.name}...", end=" ", flush=True)
        new_dur = slow_down_file(ffmpeg, mp3)
        if new_dur > 0:
            duration_map[mp3.name] = round(new_dur, 2)
            print(f"OK ({new_dur:.1f}s)")
        else:
            print("FAILED")

    # Process backend directory too (keep in sync)
    backend_files = sorted(AUDIO_DIR_BACKEND.glob("*.mp3")) if AUDIO_DIR_BACKEND.exists() else []
    if backend_files:
        print(f"\n=== Processing backend directory ===")
        for i, mp3 in enumerate(backend_files):
            print(f"[{i+1}/{len(backend_files)}] {mp3.name}...", end=" ", flush=True)
            new_dur = slow_down_file(ffmpeg, mp3)
            print(f"OK ({new_dur:.1f}s)" if new_dur > 0 else "FAILED")

    # Update content.json with new durations
    if duration_map and CONTENT_PATH.exists():
        print(f"\n=== Updating content.json ===")
        with open(CONTENT_PATH, "r", encoding="utf-8") as f:
            stories = json.load(f)

        updated = 0
        for story in stories:
            variants = story.get("audio_variants", [])
            for variant in variants:
                url = variant.get("url", "")
                filename = url.split("/")[-1] if "/" in url else ""
                if filename in duration_map:
                    old_dur = variant.get("duration_seconds", 0)
                    variant["duration_seconds"] = duration_map[filename]
                    updated += 1

        with open(CONTENT_PATH, "w", encoding="utf-8") as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
            f.write("\n")

        print(f"Updated {updated} variant durations in content.json")

    print(f"\n=== Summary ===")
    print(f"Processed: {len(duration_map)}/{len(web_files)} files")
    print(f"Average new duration: {sum(duration_map.values()) / max(len(duration_map), 1):.1f}s")


if __name__ == "__main__":
    main()
