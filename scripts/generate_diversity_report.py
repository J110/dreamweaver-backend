"""
Diversity Report Generator for Dream Valley.

Computes distribution stats across mood, content diversity (13 dimensions),
and cover diversity (7 axes). Used by:
  - API endpoint (GET /api/v1/analytics/diversity) for live dashboard
  - Pipeline (saves snapshot to data/diversity_snapshot.json after each run)

Usage:
  python3 scripts/generate_diversity_report.py               # print JSON
  python3 scripts/generate_diversity_report.py --save         # save snapshot
  python3 scripts/generate_diversity_report.py --pretty       # pretty-print
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "data" / "content.json"
AXES_HISTORY_PATH = BASE_DIR / "seed_output" / "covers_experimental" / "_axes_history.json"
SNAPSHOT_PATH = BASE_DIR / "data" / "diversity_snapshot.json"

# ── Import dimension configs ─────────────────────────────────────────

sys.path.insert(0, str(BASE_DIR))

from scripts.diversity import DIMENSIONS, HARD_RULE_DIMS, _map_legacy_to_fingerprint
from scripts.mood_config import VALID_MOOD_AGES, VALID_MOOD_TYPES
from scripts.generate_cover_experimental import (
    WORLD_SETTINGS, COLOR_PALETTES, COMPOSITIONS,
    CHARACTER_VISUALS, LIGHT_SOURCES, TEXTURES, TIME_MARKERS,
)

# ── Mood labels (keep in sync with frontend MOOD_CONFIG) ─────────────

MOOD_LABELS = {
    "wired": "Silly",
    "curious": "Adventure",
    "calm": "Gentle",
    "sad": "Comfort",
    "anxious": "Brave",
    "angry": "Let It Out",
}

ALL_MOODS = list(MOOD_LABELS.keys())

# ── Cover axes config (flattened for report) ─────────────────────────

COVER_AXES = {
    "world_setting": list(WORLD_SETTINGS.keys()),
    "palette": list(COLOR_PALETTES.keys()),
    "composition": list(COMPOSITIONS.keys()),
    "character": list(CHARACTER_VISUALS.keys()),
    "light": list(LIGHT_SOURCES.keys()),
    "texture": list(TEXTURES.keys()),
    "time": list(TIME_MARKERS.keys()),
}

# ── Age group normalization ──────────────────────────────────────────

AGE_GROUPS = ["0-1", "2-5", "6-8", "9-12"]


def _target_age_to_group(target_age) -> str:
    """Convert numeric target_age to age group string."""
    if target_age is None:
        return "unknown"
    try:
        age = int(target_age)
    except (ValueError, TypeError):
        return str(target_age)
    if age <= 1:
        return "0-1"
    elif age <= 5:
        return "2-5"
    elif age <= 8:
        return "6-8"
    else:
        return "9-12"


# ── Report generation ────────────────────────────────────────────────


def generate_report(content_path: Path = None, axes_history_path: Path = None) -> dict:
    """Generate a complete diversity report from content and cover history.

    Returns a dict ready for JSON serialization.
    """
    content_path = content_path or CONTENT_PATH
    axes_history_path = axes_history_path or AXES_HISTORY_PATH

    # Load content
    items = []
    if content_path.exists():
        try:
            items = json.loads(content_path.read_text())
        except Exception:
            pass

    # Load cover axes history
    axes_history = []
    if axes_history_path.exists():
        try:
            axes_history = json.loads(axes_history_path.read_text())
        except Exception:
            pass

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "catalog": _build_catalog_section(items),
        "mood": _build_mood_section(items),
        "content": _build_content_section(items),
        "covers": _build_covers_section(items, axes_history),
    }
    return report


def _build_catalog_section(items: list) -> dict:
    """Catalog overview: total counts, type breakdown, age breakdown."""
    type_counter = Counter(item.get("type", "story") for item in items)
    age_counter = Counter(_target_age_to_group(item.get("target_age")) for item in items)

    return {
        "total": len(items),
        "byType": dict(sorted(type_counter.items())),
        "byAge": {ag: age_counter.get(ag, 0) for ag in AGE_GROUPS},
        "withFingerprint": sum(1 for i in items if i.get("diversityFingerprint")),
        "withMood": sum(1 for i in items if i.get("mood")),
        "withCover": sum(
            1 for i in items
            if i.get("cover") and i["cover"] != "/covers/default.svg"
        ),
        "withAudio": sum(1 for i in items if i.get("audio_url")),
    }


def _build_mood_section(items: list) -> dict:
    """Mood distribution overall, by type, and by age group."""
    # Overall distribution
    mood_counter = Counter()
    mood_by_type = {}
    mood_by_age = {}

    for item in items:
        mood = item.get("mood")
        if not mood:
            mood = "none"
        mood_counter[mood] += 1

        ctype = item.get("type", "story")
        if ctype not in mood_by_type:
            mood_by_type[ctype] = Counter()
        mood_by_type[ctype][mood] += 1

        age_group = _target_age_to_group(item.get("target_age"))
        if age_group not in mood_by_age:
            mood_by_age[age_group] = Counter()
        mood_by_age[age_group][mood] += 1

    total = len(items) or 1
    distribution = {}
    for m in ALL_MOODS + ["none"]:
        count = mood_counter.get(m, 0)
        distribution[m] = {"count": count, "pct": round(count * 100 / total, 1)}

    return {
        "config": {
            "moods": ALL_MOODS,
            "labels": MOOD_LABELS,
        },
        "distribution": distribution,
        "byType": {t: dict(c) for t, c in sorted(mood_by_type.items())},
        "byAge": {ag: dict(mood_by_age.get(ag, {})) for ag in AGE_GROUPS},
    }


def _build_content_section(items: list) -> dict:
    """Content diversity: 13-dimension fingerprint distributions + gaps."""
    # Collect fingerprints (native + legacy-mapped)
    fingerprints = []
    for item in items:
        fp = item.get("diversityFingerprint")
        if fp:
            fingerprints.append(fp)
        else:
            legacy_fp = _map_legacy_to_fingerprint(item)
            # Only include if at least one dimension was mapped
            if any(v is not None for v in legacy_fp.values()):
                fingerprints.append(legacy_fp)

    # Compute per-dimension distributions
    dimensions = {}
    for dim_name, dim_config in DIMENSIONS.items():
        all_values = dim_config["values"]
        weight = dim_config["weight"]
        hard_rule = dim_config.get("hard_rule", False)

        # Determine tier
        if hard_rule:
            tier = 1
        elif weight >= 4:
            tier = 2
        else:
            tier = 3

        # Count values from fingerprints
        value_counter = Counter()
        tagged = 0
        for fp in fingerprints:
            val = fp.get(dim_name)
            if val:
                value_counter[val] += 1
                tagged += 1

        # Build distribution (include all possible values, even zero)
        dist = {}
        for v in all_values:
            dist[v] = value_counter.get(v, 0)

        used_values = sum(1 for v in all_values if value_counter.get(v, 0) > 0)
        coverage = round(used_values / len(all_values), 2) if all_values else 0

        dimensions[dim_name] = {
            "weight": weight,
            "tier": tier,
            "hardRule": hard_rule,
            "values": all_values,
            "distribution": dist,
            "coverage": coverage,
            "tagged": tagged,
        }

    # Catalog gaps: values with 0 or very low counts
    gaps = {}
    for dim_name, dim_data in dimensions.items():
        missing = [
            v for v in dim_data["values"]
            if dim_data["distribution"].get(v, 0) == 0
        ]
        if missing:
            gaps[dim_name] = missing

    return {
        "totalFingerprinted": len(fingerprints),
        "dimensions": dimensions,
        "gaps": gaps,
    }


def _build_covers_section(items: list, axes_history: list) -> dict:
    """Cover diversity: 7-axis distributions from axes history + content."""
    # Build distributions from axes history
    axes_data = {}
    for axis_name, axis_values in COVER_AXES.items():
        value_counter = Counter()
        for entry in axes_history:
            axes = entry.get("axes", {})
            val = axes.get(axis_name)
            if val:
                value_counter[val] += 1

        dist = {v: value_counter.get(v, 0) for v in axis_values}
        used = sum(1 for v in axis_values if value_counter.get(v, 0) > 0)
        coverage = round(used / len(axis_values), 2) if axis_values else 0

        axes_data[axis_name] = {
            "values": axis_values,
            "distribution": dist,
            "coverage": coverage,
        }

    # Lead character type distribution (from content, not cover history)
    char_type_counter = Counter()
    for item in items:
        ct = item.get("lead_character_type")
        if ct:
            char_type_counter[ct] += 1

    return {
        "historyCount": len(axes_history),
        "axes": axes_data,
        "leadCharacterType": dict(char_type_counter.most_common()),
    }


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate diversity report")
    parser.add_argument("--save", action="store_true", help="Save snapshot to data/diversity_snapshot.json")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    report = generate_report()

    if args.save:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(report, indent=2))
        print(f"Saved diversity snapshot to {SNAPSHOT_PATH}")
    else:
        indent = 2 if args.pretty else None
        print(json.dumps(report, indent=indent))
