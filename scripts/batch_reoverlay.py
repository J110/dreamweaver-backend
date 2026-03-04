#!/usr/bin/env python3
"""Re-overlay existing FLUX-based covers with new SMIL Animation Bible animations.

Extracts the WebP background from existing combined SVGs and generates
a fresh SMIL overlay using the new animation system.
No FLUX API call needed — only the overlay changes.
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
    generate_svg_overlay,
    validate_overlay_drowsiness,
    auto_select_axes,
    WORLD_ELEMENTS,
)


def extract_background_image_tag(svg_content: str):
    """Extract the <image> tag with base64 WebP data from a combined SVG."""
    match = re.search(
        r'<image[^>]*href="data:image/webp;base64,[^"]*"[^/]*/?>',
        svg_content,
        re.DOTALL,
    )
    if match:
        return match.group(0)
    # Try alternate format
    match = re.search(
        r'<image[^>]*href="data:image[^"]*"[^/]*/?>',
        svg_content,
        re.DOTALL,
    )
    return match.group(0) if match else None


def recombine_svg(image_tag: str, overlay_svg: str) -> str:
    """Combine a background <image> tag with a new SMIL overlay."""
    # Extract inner content from overlay SVG
    match = re.search(r'<svg[^>]*>(.*)</svg>', overlay_svg, re.DOTALL)
    inner = match.group(1) if match else overlay_svg

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512" width="512" height="512">
  <!-- Layer 1: FLUX AI Background (embedded WebP) -->
  {image_tag}
{inner}
</svg>'''


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
    print(f"  RE-OVERLAY: {len(en_items)} English items")
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
            print(f"[{i:2d}/{len(en_items)}] SKIP (file missing): {title} → {cover_file}")
            skipped_no_cover.append(sid)
            continue

        # Read existing SVG
        with open(full_path, "r", encoding="utf-8") as f:
            existing_svg = f.read()

        # Check if FLUX-based
        image_tag = extract_background_image_tag(existing_svg)
        if not image_tag:
            print(f"[{i:2d}/{len(en_items)}] SKIP (hand-crafted): {title}")
            skipped_handcrafted.append(sid)
            continue

        # Generate new overlay
        try:
            axes = auto_select_axes(story, {})
            new_overlay = generate_svg_overlay(axes, story)
            warnings = validate_overlay_drowsiness(new_overlay)

            if warnings:
                print(f"[{i:2d}/{len(en_items)}] ⚠️  WARN: {title} — {warnings}")

            # Recombine
            new_combined = recombine_svg(image_tag, new_overlay)

            # Write back
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_combined)

            overlay_size = len(new_overlay.encode("utf-8"))
            total_size = len(new_combined.encode("utf-8"))
            world = axes.get("world_setting", "?")
            print(
                f"[{i:2d}/{len(en_items)}] ✅ {title[:45]:45s} "
                f"({world}, overlay={overlay_size}B, total={total_size//1024}KB)"
            )
            successes.append(sid)

        except Exception as e:
            print(f"[{i:2d}/{len(en_items)}] ❌ FAILED: {title} — {e}")
            failures.append((sid, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print(f"  RE-OVERLAY COMPLETE")
    print(f"{'='*60}")
    print(f"  ✅ Re-overlayed:      {len(successes)}")
    print(f"  ⏭️  Hand-crafted:      {len(skipped_handcrafted)} (need FLUX API)")
    print(f"  ⏭️  No cover:          {len(skipped_no_cover)} (need FLUX API)")
    print(f"  ❌ Failed:            {len(failures)}")
    print(f"  Total:               {len(en_items)}")

    if failures:
        print(f"\n  Failed items:")
        for sid, reason in failures:
            print(f"    - {sid}: {reason}")


if __name__ == "__main__":
    main()
