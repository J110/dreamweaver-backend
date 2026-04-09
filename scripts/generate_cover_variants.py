#!/usr/bin/env python3
"""Generate progressive darkening variants from each story cover.

One FLUX cover → three extra visual variants via PIL (v1 is the original).
Used for the cover visual descent system: as the story plays, the cover
gets darker, blurrier, and bluer — like dimming the lights.

Only generates variants for SLEEP content (stories, long_stories, lullabies).
Before Bed content (funny_shorts, silly_songs, poems) stays bright and static.

Usage:
    # Process one cover
    python3 scripts/generate_cover_variants.py --cover path/to/cover.webp

    # Process all covers in a directory
    python3 scripts/generate_cover_variants.py --dir public/covers/

    # Process covers for specific content IDs
    python3 scripts/generate_cover_variants.py --ids gen-abc123 gen-def456

    # Process all story/lullaby covers (pipeline mode)
    python3 scripts/generate_cover_variants.py --pipeline
"""

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

# Content types that get the visual descent (sleep content)
VARIANT_CONTENT_TYPES = {"story", "long_story", "lullaby"}

# Directories to scan in pipeline mode
BASE_DIR = Path(__file__).resolve().parent.parent
COVERS_DIR = BASE_DIR / "public" / "covers"
SEED_COVERS = BASE_DIR / "seed_output" / "covers_experimental"
DATA_DIR = BASE_DIR / "data"
CONTENT_PATH = DATA_DIR / "content.json"


def _add_vignette(img, intensity=0.3):
    """Radial vignette using pure PIL — no numpy."""
    width, height = img.size
    cx, cy = width // 2, height // 2

    # Create gradient mask
    mask = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(mask)

    steps = 80
    for i in range(steps, 0, -1):
        scale = i / steps
        brightness = int(255 * (1 - intensity * (1 - scale ** 1.5)))
        rx = int(cx * scale * 1.4)
        ry = int(cy * scale * 1.4)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=brightness)

    # Apply: darken image where mask is dark
    r, g, b = img.split()
    r = ImageChops.multiply(r, mask)
    g = ImageChops.multiply(g, mask)
    b = ImageChops.multiply(b, mask)
    return Image.merge("RGB", (r, g, b))


def create_cover_variants(base_cover_path, output_dir=None):
    """Create 3 progressive variants from one cover image.

    v1 = original (no new file — already exists)
    v2 = golden hour (warmer, slightly soft) — Phase 1 ending
    v3 = twilight (darker, bluer, blurry) — Phase 2
    v4 = near-dark (almost black, just shapes) — Phase 3

    Returns list of generated variant paths (v2, v3, v4).
    """
    base_path = Path(base_cover_path)
    if not base_path.exists():
        raise FileNotFoundError(f"Cover not found: {base_path}")

    img = Image.open(base_path).convert("RGB")

    if output_dir is None:
        output_dir = base_path.parent
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Base name without extension — e.g. "gen-abc123" or "gen-abc123_background"
    stem = base_path.stem
    # Normalize: strip _background or _cover suffix to get the content ID stem
    for suffix in ("_background", "_cover"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    variants = []

    # --- Variant 2: Golden Hour ---
    v2 = ImageEnhance.Color(img).enhance(0.85)
    v2 = ImageEnhance.Brightness(v2).enhance(0.88)
    v2 = ImageEnhance.Contrast(v2).enhance(0.95)
    # Warm shift — boost red, reduce blue
    r, g, b = v2.split()
    r = r.point(lambda x: min(255, int(x * 1.05)))
    b = b.point(lambda x: int(x * 0.95))
    v2 = Image.merge("RGB", (r, g, b))
    v2 = v2.filter(ImageFilter.GaussianBlur(radius=0.8))
    v2_path = output_dir / f"{stem}_v2.webp"
    v2.save(str(v2_path), "WEBP", quality=85)
    variants.append(v2_path)

    # --- Variant 3: Twilight ---
    v3 = ImageEnhance.Color(img).enhance(0.55)
    v3 = ImageEnhance.Brightness(v3).enhance(0.60)
    v3 = ImageEnhance.Contrast(v3).enhance(0.85)
    # Blue shift — reduce red, boost blue
    r, g, b = v3.split()
    r = r.point(lambda x: int(x * 0.65))
    g = g.point(lambda x: int(x * 0.80))
    b = b.point(lambda x: min(255, int(x * 1.20)))
    v3 = Image.merge("RGB", (r, g, b))
    v3 = v3.filter(ImageFilter.GaussianBlur(radius=2.5))
    v3 = _add_vignette(v3, intensity=0.3)
    v3_path = output_dir / f"{stem}_v3.webp"
    v3.save(str(v3_path), "WEBP", quality=80)
    variants.append(v3_path)

    # --- Variant 4: Near Dark ---
    v4 = ImageEnhance.Color(img).enhance(0.25)
    v4 = ImageEnhance.Brightness(v4).enhance(0.28)
    v4 = ImageEnhance.Contrast(v4).enhance(0.70)
    # Deep blue shift
    r, g, b = v4.split()
    r = r.point(lambda x: int(x * 0.40))
    g = g.point(lambda x: int(x * 0.55))
    b = b.point(lambda x: min(255, int(x * 1.35)))
    v4 = Image.merge("RGB", (r, g, b))
    v4 = v4.filter(ImageFilter.GaussianBlur(radius=5))
    v4 = _add_vignette(v4, intensity=0.6)
    v4_path = output_dir / f"{stem}_v4.webp"
    v4.save(str(v4_path), "WEBP", quality=75)
    variants.append(v4_path)

    return variants


def find_cover_source(content_id, content_type="story"):
    """Find the best cover source for variant generation.

    Priority:
    1. FLUX WebP background in seed_output/covers_experimental/
    2. WebP cover in public/covers/{type}/
    3. PNG cover in public/covers/{type}/
    4. Skip if only SVG exists (placeholder)
    """
    type_dir = {
        "story": "stories",
        "long_story": "stories",
        "lullaby": "lullabies",
    }.get(content_type, "stories")

    candidates = [
        SEED_COVERS / f"{content_id}_background.webp",
        COVERS_DIR / f"{content_id}_cover.webp",
        COVERS_DIR / type_dir / f"{content_id}_cover.webp",
        COVERS_DIR / type_dir / f"{content_id}.webp",
        COVERS_DIR / f"{content_id}_cover.png",
        COVERS_DIR / type_dir / f"{content_id}_cover.png",
    ]

    for path in candidates:
        if path.exists() and path.stat().st_size > 2000:  # Skip tiny SVG fallbacks
            return path

    # Check if only SVG exists — skip
    svg_paths = [
        COVERS_DIR / type_dir / f"{content_id}_cover.svg",
        COVERS_DIR / f"{content_id}.svg",
    ]
    for svg in svg_paths:
        if svg.exists():
            print(f"  ⚠ {content_id}: only SVG cover exists, skipping variants")
            return None

    return None


def process_pipeline_covers():
    """Generate variants for all existing story/lullaby covers (pipeline mode)."""
    if not CONTENT_PATH.exists():
        print("No content.json found — nothing to process")
        return

    content = json.loads(CONTENT_PATH.read_text())
    items = [c for c in content if c.get("type") in VARIANT_CONTENT_TYPES]
    print(f"Found {len(items)} sleep content items (stories + lullabies)")

    generated = 0
    skipped = 0
    failed = 0

    for item in items:
        cid = item["id"]
        ctype = item.get("type", "story")
        title = item.get("title", cid)

        # Check if variants already exist (flat in COVERS_DIR or in type subdirs)
        type_dir = {"lullaby": "lullabies"}.get(ctype, "stories")
        existing_v2 = (
            list(COVERS_DIR.glob(f"{cid}_v2.webp"))
            + list((COVERS_DIR / type_dir).glob(f"{cid}_v2.webp"))
        )
        if existing_v2:
            skipped += 1
            continue

        source = find_cover_source(cid, ctype)
        if not source:
            skipped += 1
            continue

        try:
            # Output to public/covers/ (flat) — same dir nginx serves from
            variants = create_cover_variants(source, COVERS_DIR)
            generated += 1
            print(f"  ✓ {title[:40]} ({cid[:12]}) → {len(variants)} variants")

            # Update content.json with variant paths
            cover_file = item.get("cover", "")
            if cover_file:
                # Cover URL is like /covers/gen-abc123.webp or /covers/gen-abc123.svg
                # Variants are /covers/gen-abc123_v2.webp, etc.
                base = cover_file.rsplit(".", 1)[0]  # e.g. /covers/gen-abc123
                item["cover_variants"] = [
                    cover_file,  # v1 = original
                    f"{base}_v2.webp",
                    f"{base}_v3.webp",
                    f"{base}_v4.webp",
                ]
        except Exception as e:
            failed += 1
            print(f"  ✗ {title[:40]} ({cid[:12]}): {e}")

    # Save updated content.json
    CONTENT_PATH.write_text(json.dumps(content, indent=2, ensure_ascii=False))

    print(f"\nDone: {generated} generated, {skipped} skipped, {failed} failed")


def process_single_cover(cover_path, content_id=None):
    """Generate variants for a single cover file."""
    cover = Path(cover_path)
    if not cover.exists():
        print(f"Cover not found: {cover}")
        return False

    output_dir = cover.parent
    try:
        variants = create_cover_variants(cover, output_dir)
        print(f"✓ {cover.name} → {len(variants)} variants:")
        for v in variants:
            print(f"  {v.name} ({v.stat().st_size:,} bytes)")
        return True
    except Exception as e:
        print(f"✗ {cover.name}: {e}")
        return False


def process_ids(ids):
    """Generate variants for specific content IDs."""
    for cid in ids:
        source = find_cover_source(cid, "story")
        if not source:
            source = find_cover_source(cid, "lullaby")
        if not source:
            print(f"  ⚠ {cid}: no suitable cover found")
            continue

        # Output flat into public/covers/ where nginx serves them
        try:
            variants = create_cover_variants(source, COVERS_DIR)
            print(f"  ✓ {cid} → {len(variants)} variants")

            # Update content.json if it exists
            if CONTENT_PATH.exists():
                content = json.loads(CONTENT_PATH.read_text())
                for item in content:
                    if item.get("id") == cid:
                        cover = item.get("cover", "")
                        if cover:
                            base = cover.rsplit(".", 1)[0]
                            item["cover_variants"] = [
                                cover,
                                f"{base}_v2.webp",
                                f"{base}_v3.webp",
                                f"{base}_v4.webp",
                            ]
                        break
                CONTENT_PATH.write_text(
                    json.dumps(content, indent=2, ensure_ascii=False)
                )
        except Exception as e:
            print(f"  ✗ {cid}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate cover variants for visual descent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cover", help="Path to a single cover file")
    group.add_argument("--dir", help="Directory of covers to process")
    group.add_argument("--ids", nargs="+", help="Content IDs to process")
    group.add_argument("--pipeline", action="store_true", help="Process all sleep content covers")

    args = parser.parse_args()

    if args.cover:
        process_single_cover(args.cover)
    elif args.dir:
        cover_dir = Path(args.dir)
        covers = list(cover_dir.glob("*_cover.webp")) + list(cover_dir.glob("*_cover.png"))
        # Exclude existing variants
        covers = [c for c in covers if "_v2" not in c.stem and "_v3" not in c.stem and "_v4" not in c.stem]
        print(f"Processing {len(covers)} covers in {cover_dir}...")
        for cover in sorted(covers):
            process_single_cover(cover)
    elif args.ids:
        process_ids(args.ids)
    elif args.pipeline:
        process_pipeline_covers()
