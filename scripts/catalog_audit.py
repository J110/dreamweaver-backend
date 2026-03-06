#!/usr/bin/env python3
"""
Catalog Diversity Audit for Dream Valley.

Analyzes the full content library and reports on dimension distribution,
overrepresented defaults, underrepresented gaps, and LLM bias flags.

Usage:
    python3 scripts/catalog_audit.py                # Print report
    python3 scripts/catalog_audit.py --json         # JSON output
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Add parent dir so we can import from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.diversity import (
    DIMENSIONS, DIMENSION_NAMES, load_recent_fingerprints,
    find_catalog_gaps, _map_legacy_to_fingerprint,
)

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"

# LLM bias thresholds — flag these as overrepresented
BIAS_FLAGS = {
    "characterType": {"land_mammal": 0.25},
    "setting": {"forest_woodland": 0.20},
    "plotShape": {"journey_destination": 0.25},
    "magicType": {"glowing_bioluminescent": 0.15},
    "timeOfDay": {"deep_night_starlight": 0.35},
    "weather": {"clear_calm": 0.30},
    "companion": {"solo": 0.40},  # We WANT 30%+ solo, but not 40%+
}


def audit(content_path: Path = CONTENT_PATH) -> dict:
    """Run a full catalog diversity audit. Returns structured report."""
    if not content_path.exists():
        return {"error": f"Content file not found: {content_path}"}

    with open(content_path, "r", encoding="utf-8") as f:
        all_stories = json.load(f)

    # Filter to stories/poems (not songs)
    stories = [s for s in all_stories if s.get("type") in ("story", "long_story", "poem")]
    total = len(stories)

    if total == 0:
        return {"error": "No stories found in content.json"}

    # Count fingerprinted vs legacy
    fp_count = sum(1 for s in stories if s.get("diversityFingerprint"))

    # Build dimension distributions
    distributions = {}
    for dim, config in DIMENSIONS.items():
        counter = Counter()
        for story in stories:
            fp = story.get("diversityFingerprint")
            if fp:
                val = fp.get(dim)
            else:
                val = _map_legacy_to_fingerprint(story).get(dim)
            if val:
                counter[val] += 1
            else:
                counter["_unknown"] += 1
        distributions[dim] = dict(counter.most_common())

    # Find gaps
    gaps = find_catalog_gaps(content_path)

    # Find overrepresented values
    overrep = {}
    for dim, counts in distributions.items():
        counted_total = sum(v for k, v in counts.items() if k != "_unknown")
        if counted_total == 0:
            continue
        for value, count in counts.items():
            if value == "_unknown":
                continue
            share = count / counted_total
            if share > 0.25:
                overrep.setdefault(dim, []).append({
                    "value": value, "count": count, "share": round(share, 2),
                })

    # LLM bias flags
    bias_warnings = []
    for dim, thresholds in BIAS_FLAGS.items():
        counts = distributions.get(dim, {})
        counted_total = sum(v for k, v in counts.items() if k != "_unknown")
        if counted_total == 0:
            continue
        for value, max_share in thresholds.items():
            actual = counts.get(value, 0) / counted_total
            if actual > max_share:
                bias_warnings.append({
                    "dimension": dim,
                    "value": value,
                    "actual_share": round(actual, 2),
                    "threshold": max_share,
                })

    return {
        "total_stories": total,
        "with_fingerprint": fp_count,
        "legacy_only": total - fp_count,
        "distributions": distributions,
        "gaps": gaps,
        "overrepresented": overrep,
        "bias_warnings": bias_warnings,
    }


def print_report(report: dict):
    """Print a human-readable audit report."""
    if "error" in report:
        print(f"ERROR: {report['error']}")
        return

    print("=" * 60)
    print("  DREAM VALLEY — CATALOG DIVERSITY AUDIT")
    print("=" * 60)
    print(f"\nTotal stories/poems: {report['total_stories']}")
    print(f"  With fingerprint:  {report['with_fingerprint']}")
    print(f"  Legacy (partial):  {report['legacy_only']}")

    # Dimension distributions
    print(f"\n{'─' * 60}")
    print("DIMENSION DISTRIBUTIONS")
    print(f"{'─' * 60}")

    for dim in DIMENSION_NAMES:
        counts = report["distributions"].get(dim, {})
        counted = {k: v for k, v in counts.items() if k != "_unknown"}
        unknown = counts.get("_unknown", 0)
        total_known = sum(counted.values())

        print(f"\n  {dim}:")
        if not counted:
            print(f"    (no data — {unknown} unknown)")
            continue

        for value, count in sorted(counted.items(), key=lambda x: -x[1]):
            share = count / total_known * 100 if total_known > 0 else 0
            bar = "█" * int(share / 5)
            print(f"    {value:<30} {count:>3} ({share:>4.0f}%) {bar}")
        if unknown:
            print(f"    {'_unknown':<30} {unknown:>3}")

    # Gaps
    gaps = report.get("gaps", {})
    if gaps:
        print(f"\n{'─' * 60}")
        print("UNDERREPRESENTED (fill these gaps)")
        print(f"{'─' * 60}")
        for dim, values in gaps.items():
            labels = ", ".join(v.replace("_", " ") for v in values[:5])
            print(f"  {dim}: {labels}")

    # Overrepresented
    overrep = report.get("overrepresented", {})
    if overrep:
        print(f"\n{'─' * 60}")
        print("OVERREPRESENTED (>25% share)")
        print(f"{'─' * 60}")
        for dim, items in overrep.items():
            for item in items:
                print(f"  {dim}: {item['value']} = {item['share']:.0%} ({item['count']} stories)")

    # LLM bias flags
    warnings = report.get("bias_warnings", [])
    if warnings:
        print(f"\n{'─' * 60}")
        print("⚠ LLM BIAS FLAGS")
        print(f"{'─' * 60}")
        for w in warnings:
            print(f"  {w['dimension']}: {w['value']} at {w['actual_share']:.0%} "
                  f"(threshold: {w['threshold']:.0%})")

    print(f"\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Catalog diversity audit")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--content", type=str, default=None,
                        help="Path to content.json (default: seed_output/content.json)")
    args = parser.parse_args()

    path = Path(args.content) if args.content else CONTENT_PATH
    report = audit(path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
