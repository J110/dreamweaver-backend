#!/usr/bin/env python3
"""One-off: replace the trailing 3s outro on existing funny shorts with the
new 4.5s outro (longer + 1.5s fade). Run after re-trimming the outro stings.

Usage:
  python3 scripts/restitch_outro.py <short_id> [<short_id> ...]
"""
import io
import json
import shutil
import sys
from pathlib import Path

from pydub import AudioSegment

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "funny_shorts"
STINGS = Path("/opt/audio-store/stings")
WEB_AUDIO_BASE = Path("/opt/dreamweaver-web/public/audio")
AUDIO_STORE_BASE = Path("/opt/audio-store")

OLD_OUTRO_MS = 3000  # what we previously framed with


def restitch(short_id: str) -> None:
    j = DATA / f"{short_id}.json"
    short = json.loads(j.read_text())
    lang = short.get("lang", "en")
    audio_subdir = "funny-shorts-hi" if lang == "hi" else "funny-shorts"

    # Source audio is in backend's public/audio
    src_audio = BASE / "public" / "audio" / audio_subdir / f"{short_id}.mp3"
    if not src_audio.exists():
        print(f"  ! missing {src_audio}", file=sys.stderr)
        return

    new_outro = STINGS / f"funny_short_outro_{lang}.mp3"
    if not new_outro.exists():
        print(f"  ! missing new outro {new_outro}", file=sys.stderr)
        return

    seg = AudioSegment.from_mp3(str(src_audio))
    new_outro_seg = AudioSegment.from_mp3(str(new_outro))

    # Strip old outro and append new
    truncated = seg[:-OLD_OUTRO_MS]
    final = truncated + new_outro_seg

    # Re-export over the source
    out = io.BytesIO()
    final.export(out, format="mp3", bitrate="192k")
    src_audio.write_bytes(out.getvalue())
    new_dur = round(len(final) / 1000)
    print(f"  ✓ re-stitched {src_audio.name}: {round(len(seg)/1000)}s → {new_dur}s")

    # Sync to nginx + audio-store paths
    for dst_dir in (WEB_AUDIO_BASE / audio_subdir, AUDIO_STORE_BASE / audio_subdir):
        if dst_dir.exists():
            shutil.copy2(src_audio, dst_dir / src_audio.name)
            print(f"  synced → {dst_dir / src_audio.name}")

    # Update entry duration
    short["duration_seconds"] = new_dur
    j.write_text(json.dumps(short, indent=2, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: restitch_outro.py <short_id> [...]", file=sys.stderr)
        return 1
    for sid in sys.argv[1:]:
        print(f"=== {sid} ===")
        restitch(sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
