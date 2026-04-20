"""Diversity monitoring report (canonical-taxonomy, 21-day window).

Runs against content.json and reports actual vs target distribution
across every dimension the diversity_sampler controls. Emits alerts
when any dimension drifts outside tolerance. Intended for daily CI /
pipeline runs — see docs/ENGLISH_DIVERSITY_GUIDELINES.md section 13.

Usage:
  python3 scripts/diversity_report.py               # print report
  python3 scripts/diversity_report.py --json        # machine-readable
  python3 scripts/diversity_report.py --days 7      # different window
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.diversity_sampler import (  # noqa: E402
    AGE_GROUP_TARGETS,
    CHARACTER_TYPE_TARGETS_0_5,
    CHARACTER_TYPE_TARGETS_6_8,
    CHARACTER_TYPE_TARGETS_9_12,
    GEOGRAPHY_TARGETS,
    HARD_BLOCKED_0_5,
    PLOT_ARCHETYPE_TARGETS,
    THEME_TARGETS,
    YOUNG_AGE_GROUPS,
    canonical_character_type,
    canonical_geography,
    canonical_theme,
    load_recent_catalog,
)

# ── Alert thresholds (from guidelines §13) ──────────────────────────────
OVER_THRESHOLD = 0.25   # any dimension >25% of catalog → alert
UNDER_MULTIPLIER = 0.60  # any dimension <60% of target → alert


def _bucket_counts(items, key_fn):
    counts = Counter()
    for item in items:
        val = key_fn(item)
        if val:
            counts[val] += 1
    return counts


def _fraction(count, total):
    return count / total if total else 0.0


def _dim_report(title, counts, total, targets, hide_zero=False):
    """Build a per-dimension report section with alert flags."""
    rows = []
    alerts = []
    keys = set(targets.keys()) | set(counts.keys())
    for k in sorted(keys):
        actual = _fraction(counts.get(k, 0), total)
        target = targets.get(k, 0.0)
        if hide_zero and counts.get(k, 0) == 0 and target == 0:
            continue
        # Under-represented: any target > 0 and actual < 60% of target
        is_under = target > 0 and actual < target * UNDER_MULTIPLIER
        is_over = actual > OVER_THRESHOLD
        rows.append({
            "key": k,
            "count": counts.get(k, 0),
            "actual_pct": round(actual * 100, 1),
            "target_pct": round(target * 100, 1),
            "under": is_under,
            "over": is_over,
        })
        if is_over:
            alerts.append(f"{title}: {k} over 25% ({actual*100:.1f}%)")
        if is_under:
            alerts.append(f"{title}: {k} below 60% of target "
                          f"(actual {actual*100:.1f}% vs target {target*100:.1f}%)")
    return {"title": title, "total": total, "rows": rows, "alerts": alerts}


def build_report(days: int = 21, lang: str = "en") -> dict:
    items = load_recent_catalog(window_days=days, lang=lang)
    total = len(items)

    # ── Character type (age-bucketed) ──────────────────────────────────
    by_age = {ag: [i for i in items if i.get("age_group") == ag]
              for ag in AGE_GROUP_TARGETS}

    char_sections = []
    for age_group, targets in [
        ("0-1", CHARACTER_TYPE_TARGETS_0_5),
        ("2-5", CHARACTER_TYPE_TARGETS_0_5),
        ("6-8", CHARACTER_TYPE_TARGETS_6_8),
        ("9-12", CHARACTER_TYPE_TARGETS_9_12),
    ]:
        age_items = by_age.get(age_group, [])
        age_total = len(age_items)
        counts = _bucket_counts(age_items, canonical_character_type)
        section = _dim_report(f"character_type[{age_group}]",
                              counts, age_total, targets, hide_zero=True)
        char_sections.append(section)

        # Critical alert: aliens + robots combined >10% for young ages
        if age_group in YOUNG_AGE_GROUPS and age_total > 0:
            blocked_count = sum(counts.get(k, 0) for k in HARD_BLOCKED_0_5)
            # "alien" flavor lives in mythical_creature subtype; we can't
            # reliably separate it from pure mythical here, so we only flag
            # the robot_mechanical side (which IS supposed to be 0 for young ages).
            if blocked_count > 0:
                section["alerts"].append(
                    f"CRITICAL: {blocked_count} hard-blocked character(s) "
                    f"slipped into {age_group} — should be 0"
                )

    # ── Theme ──────────────────────────────────────────────────────────
    theme_counts = _bucket_counts(items, canonical_theme)
    theme_section = _dim_report("theme", theme_counts, total, THEME_TARGETS)

    # Hardcoded theme detection (critical)
    raw_themes = Counter(i.get("theme") for i in items if i.get("theme"))
    if raw_themes.get("bedtime", 0) > 0 or raw_themes.get("dreamy", 0) > 0:
        # These only slip through if a generator hardcodes them (legacy data
        # produced before sampler landed is fine — check recency)
        theme_section["alerts"].append(
            f"CRITICAL: legacy theme strings present in last {days}d "
            f"(bedtime={raw_themes.get('bedtime', 0)}, dreamy={raw_themes.get('dreamy', 0)})"
        )

    # ── Geography ──────────────────────────────────────────────────────
    geo_counts = _bucket_counts(items, canonical_geography)
    geo_section = _dim_report("geography", geo_counts, total, GEOGRAPHY_TARGETS)

    # ── Age group ──────────────────────────────────────────────────────
    ag_counts = _bucket_counts(items, lambda i: i.get("age_group"))
    ag_section = _dim_report("age_group", ag_counts, total, AGE_GROUP_TARGETS)

    # ── Plot archetype ─────────────────────────────────────────────────
    arch_counts = _bucket_counts(items, lambda i: i.get("plot_archetype"))
    arch_section = _dim_report("plot_archetype", arch_counts, total,
                               PLOT_ARCHETYPE_TARGETS)

    # ── Gender (simple coverage report) ────────────────────────────────
    gender_counts = _bucket_counts(items, lambda i: i.get("lead_gender"))
    gender_total = sum(gender_counts.values())
    gender_section = {
        "title": "lead_gender",
        "total": gender_total,
        "rows": [
            {
                "key": g,
                "count": c,
                "actual_pct": round(_fraction(c, gender_total) * 100, 1),
                "target_pct": 40.0 if g in ("male", "female") else 20.0,
                "under": False,
                "over": False,
            }
            for g, c in sorted(gender_counts.items())
        ],
        "alerts": [],
    }
    # Coverage alert: gender should be on every item
    missing_gender = total - gender_total
    if total and missing_gender / total > 0.20:
        gender_section["alerts"].append(
            f"{missing_gender}/{total} items missing lead_gender "
            f"({missing_gender/total*100:.0f}% coverage gap)"
        )

    sections = [
        *char_sections,
        theme_section,
        geo_section,
        ag_section,
        arch_section,
        gender_section,
    ]

    all_alerts = []
    for s in sections:
        all_alerts.extend(s["alerts"])

    return {
        "window_days": days,
        "lang": lang,
        "total_items": total,
        "sections": sections,
        "alerts": all_alerts,
    }


def print_report(report: dict):
    print(f"Diversity report — last {report['window_days']} days "
          f"({report['lang']}, {report['total_items']} items)")
    print("=" * 72)
    for section in report["sections"]:
        if section["total"] == 0:
            continue
        print(f"\n{section['title']} (n={section['total']})")
        for row in section["rows"]:
            flag = ""
            if row["over"]:
                flag = " ⚠ over"
            elif row["under"]:
                flag = " ⚠ under"
            print(f"  {row['key']:<22} {row['count']:>3}  "
                  f"{row['actual_pct']:>5.1f}% (target {row['target_pct']:>4.1f}%){flag}")

    if report["alerts"]:
        print("\n" + "=" * 72)
        print(f"ALERTS ({len(report['alerts'])})")
        for a in report["alerts"]:
            print(f"  • {a}")
    else:
        print("\nNo alerts.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = build_report(days=args.days, lang=args.lang)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    # Exit 1 if any critical alerts
    if any("CRITICAL" in a for a in report["alerts"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
