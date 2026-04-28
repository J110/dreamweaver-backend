#!/usr/bin/env python3
"""One-time generator for funny shorts intro/outro stings.

Uses fal.ai MiniMax Music to produce candidates per sting type per
language; lets a human pick the best one; trims to exactly 3 seconds
via ffmpeg.

Engines (matching existing prod patterns):
  English: fal-ai/minimax-music/v2       (no reference)
  Hindi:   fal-ai/minimax-music/v2.5     (with Hindi reference audio)

Intro stings: hard-cut at 3s (preserves resolved chord).
Outro stings: 0.5s fade-out from 2.5s (soft ending).

Usage on prod:
  python3 scripts/generate_funny_shorts_stings.py --lang en --kind intro
  python3 scripts/generate_funny_shorts_stings.py --lang en --kind outro
  python3 scripts/generate_funny_shorts_stings.py --lang hi --kind intro
  python3 scripts/generate_funny_shorts_stings.py --lang hi --kind outro
  # listen to /tmp/funny_short_stings/<lang>_<kind>_cand*.mp3
  python3 scripts/generate_funny_shorts_stings.py --lang en --kind intro --pick 3

Output (after pick):
  /opt/audio-store/stings/funny_short_{kind}_{lang}.mp3   (3 seconds)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

import httpx  # noqa: E402

STINGS_DIR_LOCAL = Path("/opt/audio-store/stings")
WORK_DIR = Path("/tmp/funny_short_stings")
WORK_DIR.mkdir(parents=True, exist_ok=True)

REF_HI = Path("/opt/audio-store/reference/hindi_lullaby_ref.m4a")

FAL_ENDPOINT_EN = "fal-ai/minimax-music/v2"
FAL_ENDPOINT_HI = "fal-ai/minimax-music/v2.5"


PROMPTS = {
    ("en", "intro"): (
        "Cheerful 5-second children's musical sting, ukulele and gentle "
        "percussion with handclaps, playful and warm, major key, ascending "
        "rising energy, ending on bright resolved chord, no vocals."
    ),
    ("en", "outro"): (
        "Resolved 5-second children's musical sting, ukulele and gentle "
        "percussion, descending settled energy, major key, warm and "
        "satisfied feeling, ending soft and quiet, no vocals."
    ),
    ("hi", "intro"): (
        "Cheerful 5-second Indian children's musical sting, light tabla "
        "and soft harmonium, kalimba accent, playful and warm Indian "
        "fusion, major key, ascending rising energy, ending on bright "
        "resolved chord, no vocals. Not Western. Not Bollywood."
    ),
    ("hi", "outro"): (
        "Resolved 5-second Indian children's musical sting, light tabla "
        "and soft harmonium, kalimba accent, descending settled energy, "
        "major key, warm and satisfied feeling, ending soft and quiet, "
        "no vocals. Not Western. Not Bollywood."
    ),
}


def _generate_one(lang: str, kind: str, ref_url: str | None) -> str:
    """Call fal.ai once and return the audio URL.

    v2 (English) uses `lyrics_prompt`; v2.5 (Hindi) uses `lyrics` +
    `is_instrumental: True` for instrumental output.
    """
    import fal_client

    endpoint = FAL_ENDPOINT_HI if lang == "hi" else FAL_ENDPOINT_EN
    if lang == "hi":
        args: dict = {
            "prompt": PROMPTS[(lang, kind)],
            "lyrics": "",
            "is_instrumental": True,
        }
    else:
        args = {
            "prompt": PROMPTS[(lang, kind)],
            "lyrics_prompt": "[Instrumental]",
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "mp3",
            },
        }
    if ref_url:
        args["reference_audio_url"] = ref_url

    result = fal_client.subscribe(endpoint, arguments=args, with_logs=False)
    audio = result.get("audio") or result.get("data", {}).get("audio")
    if not audio or not audio.get("url"):
        raise RuntimeError(f"No audio URL in response: {result}")
    return audio["url"]


def generate_candidates(lang: str, kind: str, count: int) -> list[Path]:
    import fal_client

    ref_url: str | None = None
    if lang == "hi":
        if not REF_HI.exists():
            raise FileNotFoundError(
                f"Hindi reference audio missing at {REF_HI}. "
                f"Restore from backup before generating Hindi stings."
            )
        print(f"  Uploading Hindi reference {REF_HI.name}...")
        ref_url = fal_client.upload_file(str(REF_HI))
        print(f"  Reference URL: {ref_url}")

    candidates: list[Path] = []
    for i in range(count):
        print(f"[{i+1}/{count}] requesting MiniMax via fal.ai...")
        try:
            audio_url = _generate_one(lang, kind, ref_url)
        except Exception as e:
            print(f"   request failed: {e}", file=sys.stderr)
            continue
        dst = WORK_DIR / f"{lang}_{kind}_cand{i+1}.mp3"
        resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 1000:
            print(f"   download failed ({resp.status_code}, {len(resp.content)} bytes)", file=sys.stderr)
            continue
        dst.write_bytes(resp.content)
        candidates.append(dst)
        print(f"   wrote {dst}")
    return candidates


def trim_intro_to_3s(src: Path, dst: Path) -> None:
    """Intro: hard cut at 3s — preserves resolved-chord ending."""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-t", "3.0",
        "-ar", "44100", "-b:a", "192k",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def trim_outro_to_3s(src: Path, dst: Path) -> None:
    """Outro: 0.5s fade-out from 2.5s — soft, settled ending."""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-t", "3.0",
        "-af", "afade=t=out:st=2.5:d=0.5",
        "-ar", "44100", "-b:a", "192k",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["en", "hi"], required=True)
    ap.add_argument("--kind", choices=["intro", "outro"], required=True)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--pick", type=int, default=None,
                    help="Skip generation, pick this candidate (1-based) and trim")
    args = ap.parse_args()

    if args.pick is None:
        if not os.environ.get("FAL_KEY"):
            print("ERROR: FAL_KEY not set in env", file=sys.stderr)
            return 1
        cands = generate_candidates(args.lang, args.kind, args.count)
        if not cands:
            print("ERROR: no candidates generated", file=sys.stderr)
            return 1
        print("\nGenerated candidates:")
        for i, c in enumerate(cands, 1):
            print(f"  {i}. {c}")
        print("\nListen to each, then re-run with --pick N to finalize.")
        return 0

    pick_path = WORK_DIR / f"{args.lang}_{args.kind}_cand{args.pick}.mp3"
    if not pick_path.exists():
        print(f"ERROR: {pick_path} not found", file=sys.stderr)
        return 1

    STINGS_DIR_LOCAL.mkdir(parents=True, exist_ok=True)
    final = STINGS_DIR_LOCAL / f"funny_short_{args.kind}_{args.lang}.mp3"
    trimmer = trim_intro_to_3s if args.kind == "intro" else trim_outro_to_3s
    trimmer(pick_path, final)
    print(f"Wrote {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
