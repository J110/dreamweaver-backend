#!/usr/bin/env python3
"""Generate a FLUX cover for a funny short.

Uses the same image-generation fallback chain as
generate_cover_experimental.py (Pollinations → Together AI → FluxAPI →
Replicate) but with a funny-shorts-specific prompt template, and writes
the output WebP to the right per-language directory.

Usage:
  python3 scripts/generate_funny_short_cover.py \
    --story-json data/funny_shorts/en-fs-XXXX.json
"""

import argparse
import json
import os
import sys
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_cover_experimental import (  # noqa: E402
    generate_flux_image,
    save_as_webp,
)

BASE = Path(__file__).resolve().parents[1]
COVERS_EN = BASE / "public" / "covers" / "funny-shorts"
COVERS_HI = BASE / "public" / "covers" / "funny-shorts-hi"
COVERS_EN.mkdir(parents=True, exist_ok=True)
COVERS_HI.mkdir(parents=True, exist_ok=True)


PROMPT_EN = (
    "Digital painting of {context}, bold cartoon style, bright "
    "saturated colors, two child characters with exaggerated funny "
    "expressions, simple flat background, playful and warm, thick "
    "outlines, expressive eyes, Pixar-meets-picture-book aesthetic, "
    "cozy comedic energy, minimalist"
)

PROMPT_HI = (
    "Digital painting of {context}, bold cartoon style, bright "
    "saturated colors, two Indian child characters with exaggerated "
    "funny expressions, simple flat background with Indian household "
    "detail (ceiling fan, chai cup, mosquito coil, pressure cooker) "
    "where natural, playful and warm, thick outlines, expressive eyes, "
    "Pixar-meets-picture-book aesthetic, cozy comedic energy, minimalist"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story-json", required=True)
    args = ap.parse_args()

    src = Path(args.story_json)
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 1

    short = json.loads(src.read_text())
    lang = short.get("lang", "en")
    short_id = short["id"]
    context = short.get("cover_context") or short.get("title", "two kids")

    template = PROMPT_HI if lang == "hi" else PROMPT_EN
    prompt = template.format(context=context)
    print(f"Prompt: {prompt[:160]}...")

    image_bytes = generate_flux_image(prompt)
    if not image_bytes:
        print("ERROR: all FLUX backends failed", file=sys.stderr)
        return 1

    covers_dir = COVERS_HI if lang == "hi" else COVERS_EN
    out_path = covers_dir / f"{short_id}_cover.webp"
    save_as_webp(image_bytes, out_path, quality=80)
    print(f"\n✓ Wrote {out_path}")

    # Update entry to record cover_file (string only — `cover` URL is set by orchestrator)
    short["cover_file"] = f"{short_id}_cover.webp"
    src.write_text(json.dumps(short, indent=2, ensure_ascii=False))
    print(f"✓ Updated {src} with cover_file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
