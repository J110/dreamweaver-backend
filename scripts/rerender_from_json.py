#!/usr/bin/env python3
"""One-off: re-render a funny short's audio from its saved JSON inputs.

Useful when the framing changed (e.g. outro extended) and you want to
rebuild existing shorts cleanly without going back through Mistral.

Usage:
  python3 scripts/rerender_from_json.py <short_id> [<short_id> ...]
"""
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _funny_shorts_common import (
    VOICE_LIBRARY_EN,
    VOICE_LIBRARY_HI,
    frame_dialogue_with_stings,
    render_dialogue_v3,
)
from pydub import AudioSegment

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "funny_shorts"
STINGS = Path("/opt/audio-store/stings")
WEB_AUDIO_BASE = Path("/opt/dreamweaver-web/public/audio")
AUDIO_STORE_BASE = Path("/opt/audio-store")


def rerender(short_id: str) -> None:
    j = DATA / f"{short_id}.json"
    short = json.loads(j.read_text())
    lang = short.get("lang", "en")
    audio_subdir = "funny-shorts-hi" if lang == "hi" else "funny-shorts"
    voice_pair = short.get("voice_pair") or []
    if len(voice_pair) != 2:
        print(f"  ! {short_id}: voice_pair missing/invalid", file=sys.stderr)
        return
    lib = VOICE_LIBRARY_HI if lang == "hi" else VOICE_LIBRARY_EN
    voice_a_id = lib[voice_pair[0]]
    voice_b_id = lib[voice_pair[1]]
    inputs = short.get("inputs") or []
    if not inputs:
        print(f"  ! {short_id}: inputs missing", file=sys.stderr)
        return

    print(f"  Rendering {short_id} ({lang}, {voice_pair[0]}+{voice_pair[1]}, {len(inputs)} lines)...")
    dialogue_bytes = render_dialogue_v3(inputs, voice_a_id, voice_b_id)

    intro = STINGS / f"funny_short_intro_{lang}.mp3"
    outro = STINGS / f"funny_short_outro_{lang}.mp3"
    framed = frame_dialogue_with_stings(dialogue_bytes, intro, outro, gap_ms=1000)

    audio_path = BASE / "public" / "audio" / audio_subdir / f"{short_id}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(framed)

    seg = AudioSegment.from_mp3(io.BytesIO(framed))
    new_dur = round(len(seg) / 1000)
    print(f"  ✓ rebuilt {audio_path.name}: {new_dur}s")

    for dst_dir in (WEB_AUDIO_BASE / audio_subdir, AUDIO_STORE_BASE / audio_subdir):
        if dst_dir.exists():
            shutil.copy2(audio_path, dst_dir / audio_path.name)
            print(f"  synced → {dst_dir / audio_path.name}")

    short["duration_seconds"] = new_dur
    j.write_text(json.dumps(short, indent=2, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: rerender_from_json.py <short_id> [...]", file=sys.stderr)
        return 1
    for sid in sys.argv[1:]:
        print(f"=== {sid} ===")
        try:
            rerender(sid)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
