#!/usr/bin/env python3
"""Re-overlay existing FLUX-based covers with V3 cinemagraph animations.

V3 architecture: 3-layer SVG
  Layer 1: FLUX WebP background (defined once in <defs>, referenced via <use>)
  Layer 2: SVG cinemagraph filters (feTurbulence + feDisplacementMap on masked regions)
  Layer 3: Lean SMIL overlay (particles, breathing pacer, vignette)

Extracts the WebP base64 from existing combined SVGs and generates
fresh cinemagraph filters + lean overlay. No FLUX API call needed.
"""

import json
import os
import re
import sys
from pathlib import Path

# Add parent to path so we can import the cover generator
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scripts.generate_cover_experimental import (
    generate_v3_combined_svg,
    auto_select_axes,
)


def extract_background_b64(svg_content: str):
    """Extract the base64 WebP data from a combined SVG.

    Handles both v2 format (<image ... href="data:image/webp;base64,..."/>)
    and v3 format (<image id="bg" ... href="data:image/webp;base64,..."/>).
    """
    match = re.search(
        r'href="data:image/webp;base64,([^"]*)"',
        svg_content,
        re.DOTALL,
    )
    return match.group(1) if match else None


def main():
    # Load content.json
    with open("seed_output/content.json", "r", encoding="utf-8") as f:
        all_content = json.load(f)

    covers_dir = Path("../dreamweaver-web/public/covers")

    hindi_words = [
        'aur', 'ki', 'ka', 'ke', 'mein', 'hai', 'ek', 'nanha', 'nanhe',
        'sapno', 'lori', 'neend', 'dosti', 'yatra', 'sahayogiyon', 'bhavishya',
        'chhota', 'aethoria', 'prakriti', 'jaadui', 'shiksha', 'vidya', 'devi',
        'gahrai', 'taairte', 'dweep', 'barf', 'vidyalay', 'seal', 'narm',
        'bistar', 'khoj', 'samudri',
    ]

    # Filter to English items only
    en_items = []
    for s in all_content:
        lang = s.get("language", "en")
        if lang != "en":
            continue
        sid = s.get("id", "")
        if sid.startswith("hi-"):
            continue
        title_words = s.get("title", "").lower().split()
        if sum(1 for w in title_words if w in hindi_words) >= 2:
            continue
        en_items.append(s)

    print(f"\n{'='*60}")
    print(f"  V3 RE-OVERLAY: {len(en_items)} English items")
    print(f"  Architecture: Cinemagraph filters + lean SMIL overlay")
    print(f"{'='*60}\n")

    successes = []
    skipped_no_cover = []
    skipped_handcrafted = []
    failures = []

    for i, story in enumerate(en_items, 1):
        sid = story["id"]
        title = story.get("title", "Untitled")
        cover_path = story.get("cover", "")

        if not cover_path or cover_path == "/covers/default.svg":
            print(f"[{i:2d}/{len(en_items)}] SKIP (no cover): {title}")
            skipped_no_cover.append(sid)
            continue

        cover_file = cover_path.split("/")[-1]
        full_path = covers_dir / cover_file

        if not full_path.exists():
            print(f"[{i:2d}/{len(en_items)}] SKIP (file missing): {title} -> {cover_file}")
            skipped_no_cover.append(sid)
            continue

        # Read existing SVG
        with open(full_path, "r", encoding="utf-8") as f:
            existing_svg = f.read()

        # Extract base64 WebP
        bg_b64 = extract_background_b64(existing_svg)
        if not bg_b64:
            print(f"[{i:2d}/{len(en_items)}] SKIP (hand-crafted): {title}")
            skipped_handcrafted.append(sid)
            continue

        # Generate V3 combined SVG
        try:
            axes = auto_select_axes(story, {})
            new_combined = generate_v3_combined_svg(bg_b64, axes, story)

            # Write back
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_combined)

            total_size = len(new_combined.encode("utf-8"))
            world = axes.get("world_setting", "?")
            print(
                f"[{i:2d}/{len(en_items)}] OK {title[:45]:45s} "
                f"({world}, total={total_size//1024}KB)"
            )
            successes.append(sid)

        except Exception as e:
            print(f"[{i:2d}/{len(en_items)}] FAILED: {title} -- {e}")
            import traceback
            traceback.print_exc()
            failures.append((sid, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print(f"  V3 RE-OVERLAY COMPLETE")
    print(f"{'='*60}")
    print(f"  OK:              {len(successes)}")
    print(f"  Hand-crafted:    {len(skipped_handcrafted)} (need FLUX API)")
    print(f"  No cover:        {len(skipped_no_cover)} (need FLUX API)")
    print(f"  Failed:          {len(failures)}")
    print(f"  Total:           {len(en_items)}")

    if failures:
        print(f"\n  Failed items:")
        for sid, reason in failures:
            print(f"    - {sid}: {reason}")


if __name__ == "__main__":
    main()
