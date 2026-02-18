#!/usr/bin/env python3
"""Generate animated SVG cover illustrations for stories/poems using Mistral AI.

Reads content.json, finds items without a real cover (missing or default.svg),
and generates a unique SVG cover for each using Mistral Large.

Usage:
    python3 scripts/generate_cover_svg.py                # All items missing covers
    python3 scripts/generate_cover_svg.py --new-only      # Only new items (no cover field)
    python3 scripts/generate_cover_svg.py --id gen-xxx    # Specific item
    python3 scripts/generate_cover_svg.py --dry-run       # Show prompt, don't call API
"""

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

from mistralai import Mistral

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MODEL = "mistral-large-latest"

CONTENT_JSON = BASE_DIR / "seed_output" / "content.json"
WEB_COVERS_DIR = BASE_DIR.parent / "dreamweaver-web" / "public" / "covers"

# Rate limit: 35s between Mistral calls (free tier = 2 req/min)
RATE_LIMIT_DELAY = 35


# ── Helpers ──────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    """Convert title to kebab-case filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[''']s\b", "s", slug)  # possessives
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:40]


def _pick_prefix(title: str, existing_prefixes: set) -> str:
    """Pick a unique 2-letter prefix for SVG IDs."""
    words = re.sub(r"[^a-z\s]", "", title.lower()).split()
    # Try first letters of first two words
    candidates = []
    if len(words) >= 2:
        candidates.append(words[0][0] + words[1][0])
    if len(words) >= 1:
        candidates.append(words[0][:2])
    # Try more combinations
    for w in words:
        for w2 in words:
            if w != w2:
                candidates.append(w[0] + w2[0])
    # Fallback: random-ish
    for c1 in "abcdefghijklmnopqrstuvwxyz":
        for c2 in "abcdefghijklmnopqrstuvwxyz":
            candidates.append(c1 + c2)

    for prefix in candidates:
        if prefix not in existing_prefixes:
            return prefix
    return "zz"


def _get_existing_prefixes() -> set:
    """Scan existing SVG covers for their ID prefixes."""
    prefixes = set()
    if WEB_COVERS_DIR.exists():
        for svg_file in WEB_COVERS_DIR.glob("*.svg"):
            try:
                content = svg_file.read_text()
                # Look for id="XX-" pattern
                matches = re.findall(r'id="([a-z]{2})-', content)
                prefixes.update(matches)
            except Exception:
                pass
    return prefixes


def _build_prompt(story: dict, prefix: str) -> str:
    """Build the Mistral prompt for SVG cover generation."""
    title = story.get("title", "Untitled")
    desc = story.get("description", "")
    theme = story.get("theme", "fantasy")
    stype = story.get("type", "story")
    categories = story.get("categories", [])

    return f"""Generate a complete animated SVG cover illustration for a children's bedtime {stype}.

STORY DETAILS:
- Title: "{title}"
- Description: {desc}
- Theme: {theme}
- Categories: {', '.join(categories) if categories else 'General'}

STRICT SVG REQUIREMENTS (follow ALL of these exactly):
1. viewBox="0 0 512 512" with xmlns="http://www.w3.org/2000/svg"
2. All IDs must use the prefix "{prefix}-" (e.g., {prefix}-skyGrad, {prefix}-softGlow)
3. Structure: <defs> (gradients + filters) → <style> (CSS @keyframes) → 7 layers back to front
4. Layer order: 1=Sky/background, 2=Far background, 3=Mid background, 4=Middle ground, 5=Main character, 6=Foreground particles/sparkles, 7=Vignette overlay
5. At least 6 CSS @keyframes animations with ease-in-out timing:
   - Star/sparkle twinkle (2-3s)
   - Character gentle bobbing or breathing (4-6s)
   - Environmental movement (waves, leaves, clouds) (6-8s)
   - Particle drift (7-9s)
   - Glow/pulse effect (3-5s)
   - At least one more unique to the scene
6. Filters required: softGlow (stdDeviation 2), mediumGlow (4), strongGlow (6)
7. End with vignette: <rect width="512" height="512" fill="url(#{prefix}-vignette)" opacity="0.4"/>
8. Color palette: dreamy, nighttime, calming. Use deep background colors with warm/magical accent colors (#ffd700 gold, soft glows)
9. Main character should be in the center area (x:200-310, y:180-300) and occupy ~30% of the scene
10. File should be 300-600 lines. No JavaScript — CSS animations only.
11. All animations must be infinite with ease-in-out easing
12. NO text elements in the SVG — illustration only

OUTPUT: Return ONLY the complete SVG code starting with <svg and ending with </svg>. No explanation, no markdown code blocks."""


def _extract_svg(response_text: str) -> str:
    """Extract SVG content from Mistral response."""
    # Try to find <svg...>...</svg>
    match = re.search(r"(<svg[\s\S]*?</svg>)", response_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Maybe wrapped in code blocks
    match = re.search(r"```(?:xml|svg)?\s*\n([\s\S]*?)\n```", response_text)
    if match:
        inner = match.group(1).strip()
        svg_match = re.search(r"(<svg[\s\S]*?</svg>)", inner, re.IGNORECASE)
        if svg_match:
            return svg_match.group(1).strip()
    return ""


def _validate_svg(svg_text: str, prefix: str) -> tuple:
    """Validate SVG meets requirements. Returns (is_valid, issues_list)."""
    issues = []

    # 1. Parse as XML
    try:
        ET.fromstring(svg_text)
    except ET.ParseError as e:
        issues.append(f"XML parse error: {e}")
        return False, issues

    # 2. Check viewBox
    if 'viewBox="0 0 512 512"' not in svg_text:
        issues.append("Missing viewBox='0 0 512 512'")

    # 3. Check @keyframes count
    keyframes = re.findall(r"@keyframes\s+", svg_text)
    if len(keyframes) < 4:
        issues.append(f"Only {len(keyframes)} @keyframes (need ≥4)")

    # 4. Check file size
    size_kb = len(svg_text.encode("utf-8")) / 1024
    if size_kb < 5:
        issues.append(f"Too small: {size_kb:.1f}KB (min 5KB)")
    if size_kb > 60:
        issues.append(f"Too large: {size_kb:.1f}KB (max 60KB)")

    # 5. Check has style block
    if "<style>" not in svg_text:
        issues.append("Missing <style> block")

    # 6. Check has defs
    if "<defs>" not in svg_text:
        issues.append("Missing <defs> block")

    is_valid = len(issues) == 0
    return is_valid, issues


def generate_cover(story: dict, client: Mistral, prefix: str, dry_run: bool = False) -> str:
    """Generate an SVG cover for a story. Returns the SVG file path or empty string."""
    title = story.get("title", "Untitled")
    slug = _slugify(title)
    output_path = WEB_COVERS_DIR / f"{slug}.svg"

    prompt = _build_prompt(story, prefix)

    if dry_run:
        print(f"\n  [DRY RUN] Would generate cover for: {title}")
        print(f"  Prefix: {prefix}")
        print(f"  Output: {output_path}")
        print(f"  Prompt length: {len(prompt)} chars")
        return ""

    print(f"\n  Generating cover for: {title}")
    print(f"  Prefix: {prefix}, Output: {slug}.svg")

    for attempt in range(2):
        try:
            resp = client.chat.complete(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=16000,
                temperature=0.7 + (attempt * 0.1),  # Slightly higher temp on retry
            )

            raw = resp.choices[0].message.content
            svg_text = _extract_svg(raw)

            if not svg_text:
                print(f"    Attempt {attempt + 1}: Could not extract SVG from response")
                if attempt == 0:
                    print(f"    Retrying in {RATE_LIMIT_DELAY}s...")
                    time.sleep(RATE_LIMIT_DELAY)
                continue

            is_valid, issues = _validate_svg(svg_text, prefix)
            if not is_valid:
                print(f"    Attempt {attempt + 1}: Validation failed: {issues}")
                if attempt == 0:
                    print(f"    Retrying in {RATE_LIMIT_DELAY}s...")
                    time.sleep(RATE_LIMIT_DELAY)
                continue

            # Success — write SVG
            WEB_COVERS_DIR.mkdir(parents=True, exist_ok=True)
            output_path.write_text(svg_text)
            size_kb = len(svg_text.encode("utf-8")) / 1024
            keyframes = len(re.findall(r"@keyframes\s+", svg_text))
            print(f"    OK: {slug}.svg ({size_kb:.1f}KB, {keyframes} animations)")
            return f"/covers/{slug}.svg"

        except Exception as e:
            print(f"    Attempt {attempt + 1}: API error: {e}")
            if attempt == 0:
                print(f"    Retrying in {RATE_LIMIT_DELAY}s...")
                time.sleep(RATE_LIMIT_DELAY)

    print(f"    FAILED: Falling back to default.svg for '{title}'")
    return "/covers/default.svg"


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate SVG covers for stories")
    parser.add_argument("--id", help="Generate for a specific story ID")
    parser.add_argument("--new-only", action="store_true",
                        help="Only items without any cover field")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without calling API")
    args = parser.parse_args()

    if not MISTRAL_API_KEY and not args.dry_run:
        print("ERROR: MISTRAL_API_KEY not set")
        sys.exit(1)

    # Load content
    if not CONTENT_JSON.exists():
        print(f"ERROR: {CONTENT_JSON} not found")
        sys.exit(1)

    stories = json.loads(CONTENT_JSON.read_text())
    existing_prefixes = _get_existing_prefixes()

    # Filter items that need covers
    needs_cover = []
    for s in stories:
        if args.id and s.get("id") != args.id:
            continue
        cover = s.get("cover", "")
        if args.new_only:
            if not cover:
                needs_cover.append(s)
        else:
            if not cover or cover == "/covers/default.svg":
                needs_cover.append(s)

    if not needs_cover:
        print("No items need cover generation.")
        return

    print(f"Generating covers for {len(needs_cover)} items...")

    client = Mistral(api_key=MISTRAL_API_KEY) if not args.dry_run else None

    generated = []
    failed = []

    for i, story in enumerate(needs_cover):
        if i > 0:
            print(f"  Rate limit delay: {RATE_LIMIT_DELAY}s...")
            time.sleep(RATE_LIMIT_DELAY)

        prefix = _pick_prefix(story.get("title", ""), existing_prefixes)
        existing_prefixes.add(prefix)

        cover_path = generate_cover(story, client, prefix, dry_run=args.dry_run)

        if args.dry_run:
            continue

        # Update content.json with the cover path
        story["cover"] = cover_path
        if cover_path and cover_path != "/covers/default.svg":
            generated.append(story["id"])
        else:
            failed.append(story["id"])

    # Save updated content.json
    if not args.dry_run and (generated or failed):
        CONTENT_JSON.write_text(json.dumps(stories, indent=2, ensure_ascii=False) + "\n")
        print(f"\nUpdated content.json: {len(generated)} covers generated, {len(failed)} fallback")

    # Print summary
    print(f"\n{'='*40}")
    print(f"  COVER GENERATION SUMMARY")
    print(f"{'='*40}")
    print(f"  Generated: {len(generated)}")
    print(f"  Failed:    {len(failed)}")
    if failed:
        print(f"  Failed IDs: {', '.join(failed)}")


if __name__ == "__main__":
    main()
