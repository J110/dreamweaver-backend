#!/usr/bin/env python3
"""Batch regenerate covers for all English content items using the new SMIL Animation Bible overlay system."""

import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BATCH_DIR = BASE / "seed_output" / "batch_regen"
SCRIPT = BASE / "scripts" / "generate_cover_experimental.py"

def main():
    manifest = BATCH_DIR / "_manifest.json"
    with open(manifest) as f:
        ids = json.load(f)

    total = len(ids)
    print(f"\n{'='*60}")
    print(f"  BATCH COVER REGENERATION — {total} items")
    print(f"{'='*60}\n")

    successes = []
    failures = []
    skipped = []

    for i, story_id in enumerate(ids, 1):
        json_path = BATCH_DIR / f"{story_id}.json"
        if not json_path.exists():
            print(f"[{i:2d}/{total}] SKIP — {story_id} (no JSON file)")
            skipped.append(story_id)
            continue

        with open(json_path) as f:
            story = json.load(f)
        title = story.get("title", "Untitled")

        print(f"\n[{i:2d}/{total}] Generating: {title}")
        print(f"         ID: {story_id}")
        start = time.time()

        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--story-json", str(json_path)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(BASE),
            )

            elapsed = time.time() - start

            # Check for success marker in stderr (logger output)
            output = result.stderr + result.stdout
            if "OK:" in output or result.returncode == 0:
                # Verify the combined SVG was actually created
                combined = BASE / "seed_output" / "covers_experimental" / f"{story_id}_combined.svg"
                if combined.exists():
                    size_kb = combined.stat().st_size // 1024
                    print(f"         ✅ SUCCESS ({elapsed:.1f}s, {size_kb}KB)")
                    successes.append(story_id)
                else:
                    print(f"         ⚠️  Script ran but no combined SVG found ({elapsed:.1f}s)")
                    failures.append((story_id, "No combined SVG"))
            else:
                err_line = [l for l in output.split('\n') if 'error' in l.lower() or 'ERROR' in l]
                err_msg = err_line[0][:100] if err_line else f"exit code {result.returncode}"
                print(f"         ❌ FAILED ({elapsed:.1f}s): {err_msg}")
                failures.append((story_id, err_msg))

        except subprocess.TimeoutExpired:
            print(f"         ❌ TIMEOUT (120s)")
            failures.append((story_id, "Timeout"))
        except Exception as e:
            print(f"         ❌ ERROR: {e}")
            failures.append((story_id, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"  ✅ Success: {len(successes)}/{total}")
    print(f"  ❌ Failed:  {len(failures)}/{total}")
    print(f"  ⏭️  Skipped: {len(skipped)}/{total}")

    if failures:
        print(f"\n  Failed items:")
        for sid, reason in failures:
            print(f"    - {sid}: {reason}")

    if successes:
        print(f"\n  All cover SVGs in: seed_output/")
        print(f"  Frontend copies in: dreamweaver-web/public/covers/")


if __name__ == "__main__":
    main()
