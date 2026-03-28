#!/usr/bin/env python3
"""Generate missing funny-shorts covers via Pollinations (default) or Together AI fallback."""
import base64
import hashlib
import json
import os
import random
import sys
import urllib.parse
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"
COVERS_DIR = Path(__file__).resolve().parents[1] / "public" / "covers" / "funny-shorts"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

# Load API keys from .env
TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "")
if not TOGETHER_KEY:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in open(env_path):
            if line.startswith("TOGETHER_API_KEY"):
                TOGETHER_KEY = line.split("=", 1)[1].strip().strip('"')

PROMPT_TPL = (
    "Children's book illustration, bold cartoon style, bright saturated colors, "
    "simple background, exaggerated funny expressions, playful and energetic, "
    "square composition, thick outlines, expressive eyes, slightly exaggerated "
    "proportions, Pixar-meets-picture-book aesthetic. "
    "Scene: {desc} "
    "DO NOT make it dreamy, muted, watercolor, or soft. This is comedy, not bedtime. "
    "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS anywhere in the image. "
    "Pure illustration only."
)


def stable_seed(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % (2**31)


def gen_overlay(sid):
    rng = random.Random(stable_seed(sid))
    els = []
    colors = ["#FFD700", "#FF6B9D", "#00E5FF", "#76FF03", "#FF9100", "#E040FB"]
    for _ in range(rng.randint(4, 8)):
        cx, cy = rng.randint(5, 95), rng.randint(5, 95)
        r = rng.uniform(2, 4)
        c = rng.choice(colors)
        d = rng.uniform(1.5, 3.5)
        b = rng.uniform(0, 3)
        p = rng.uniform(0.6, 0.9)
        els.append(
            f'<circle cx="{cx}%" cy="{cy}%" r="{r}" fill="{c}">'
            f'<animate attributeName="opacity" values="0;{p:.1f};0" '
            f'dur="{d:.1f}s" begin="{b:.1f}s" repeatCount="indefinite"/>'
            f'</circle>'
        )
    return "\n    ".join(els)


def _generate_image_pollinations(prompt: str, sid: str) -> bytes | None:
    """Generate image via Pollinations.ai (free, no auth required)."""
    try:
        seed = stable_seed(sid)
        encoded = urllib.parse.quote(prompt[:500])
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&seed={seed}&nologo=true&model=flux"
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        print(f"  Pollinations: {resp.status_code} ({len(resp.content)} bytes)")
        return None
    except Exception as e:
        print(f"  Pollinations error: {e}")
        return None


def _generate_image_together(prompt: str) -> bytes | None:
    """Generate image via Together AI FLUX.1-schnell (fallback)."""
    try:
        resp = httpx.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {TOGETHER_KEY}"},
            json={
                "model": "black-forest-labs/FLUX.1-schnell",
                "prompt": prompt,
                "width": 512,
                "height": 512,
                "n": 1,
                "response_format": "b64_json",
            },
            timeout=120,
        )
        if resp.status_code != 200:
            print(f"  Together: {resp.status_code} {resp.text[:200]}")
            return None
        b64_data = resp.json()["data"][0]["b64_json"]
        return base64.b64decode(b64_data)
    except Exception as e:
        print(f"  Together error: {e}")
        return None


def main():
    missing = []
    for p in sorted(DATA_DIR.glob("*.json")):
        d = json.load(open(p))
        sid = d.get("id", p.stem)
        cover_file = f"{sid}.svg"
        if (COVERS_DIR / cover_file).exists():
            continue
        missing.append((p, d, sid, cover_file))

    print(f"Missing covers: {len(missing)}")
    if not missing:
        return

    for p, d, sid, cover_file in missing:
        desc = d.get("cover_description", d.get("title", "funny cartoon scene"))
        prompt = PROMPT_TPL.format(desc=desc)[:600]
        print(f"Generating: {sid}")

        try:
            img_bytes = _generate_image_pollinations(prompt, sid)
            if img_bytes is None and TOGETHER_KEY:
                print("  Pollinations failed, trying Together AI...")
                img_bytes = _generate_image_together(prompt)
            if img_bytes is None:
                print("  FAILED: all providers")
                continue
            img = Image.open(BytesIO(img_bytes)).convert("RGB").resize((512, 512), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="WEBP", quality=80)
            webp_b64 = base64.b64encode(buf.getvalue()).decode()

            overlay = gen_overlay(sid)
            svg = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">\n'
                f'  <defs><image id="bg" width="512" height="512" href="data:image/webp;base64,{webp_b64}"/></defs>\n'
                '  <use href="#bg"/>\n'
                f'  <g id="comedy-overlay">\n    {overlay}\n  </g>\n'
                '</svg>'
            )

            with open(COVERS_DIR / cover_file, "w") as f:
                f.write(svg)

            d["cover_file"] = cover_file
            with open(p, "w") as f:
                json.dump(d, f, indent=2)

            print(f"  OK: {len(svg)/1024:.1f} KB")

        except Exception as e:
            print(f"  ERROR: {e}")

    print("Done")


if __name__ == "__main__":
    main()
