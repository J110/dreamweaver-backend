"""Deficit-aware diversity sampler for Dream Valley content generation.

Replaces static-weighted random.choices with catalog-aware sampling that
boosts under-represented options and suppresses over-represented ones.

Used by all English generators (short stories, long stories, lullabies) to
keep the combined catalog balanced across character type, theme, geography,
age group, universe, and plot archetype.

See: docs/ENGLISH_DIVERSITY_GUIDELINES.md
"""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"


# ═══════════════════════════════════════════════════════════════════════
#  Canonical taxonomies (single source of truth)
# ═══════════════════════════════════════════════════════════════════════

CANONICAL_CHARACTER_TYPES = [
    "land_mammal", "bird", "sea_creature", "insect", "reptile_amphibian",
    "human_child", "mythical_creature", "object_alive", "plant_tree",
    "celestial_weather", "robot_mechanical",
]

# Orchestrator legacy → canonical mapping. Legacy values survive in the
# old catalog; new generations should emit canonical values directly.
ORCHESTRATOR_TO_CANONICAL = {
    "human": "human_child",
    "animal": "land_mammal",
    "bird": "bird",
    "sea_creature": "sea_creature",
    "insect": "insect",
    "plant": "plant_tree",
    "celestial": "celestial_weather",
    "atmospheric": "celestial_weather",
    "mythical": "mythical_creature",
    "object": "object_alive",
    "alien": "mythical_creature",
    "robot": "robot_mechanical",
}

# FLUX cover generator still keys off legacy orchestrator values.
CANONICAL_TO_FLUX = {
    "land_mammal": "animal",
    "bird": "bird",
    "sea_creature": "sea_creature",
    "insect": "insect",
    "reptile_amphibian": "animal",
    "human_child": "human",
    "mythical_creature": "mythical",
    "object_alive": "object",
    "plant_tree": "plant",
    "celestial_weather": "celestial",
    "robot_mechanical": "robot",
}


# ─── Character type targets (age-gated) ────────────────────────────────
# Aliens and robots HARD-BLOCKED for ages 0-5 (not just weighted low).

CHARACTER_TYPE_TARGETS_0_5 = {
    "land_mammal":       0.24,   # 22% familiar + 2% exotic
    "bird":              0.15,
    "insect":            0.12,
    "human_child":       0.12,
    "sea_creature":      0.08,
    "object_alive":      0.08,
    "plant_tree":        0.06,
    "celestial_weather": 0.06,
    "mythical_creature": 0.05,
    "reptile_amphibian": 0.04,
    # robot_mechanical and "alien as mythical" explicitly excluded here
}

CHARACTER_TYPE_TARGETS_6_8 = {
    "land_mammal":       0.18,
    "human_child":       0.15,
    "bird":              0.12,
    "insect":            0.10,
    "sea_creature":      0.08,
    "mythical_creature": 0.12,  # 8% pure mythical + 4% alien-flavored
    "object_alive":      0.06,
    "plant_tree":        0.05,
    "celestial_weather": 0.05,
    "robot_mechanical":  0.05,
    "reptile_amphibian": 0.04,
}

CHARACTER_TYPE_TARGETS_9_12 = {
    "human_child":       0.22,
    "land_mammal":       0.12,
    "mythical_creature": 0.16,  # 10% pure + 6% alien-flavored
    "celestial_weather": 0.08,
    "bird":              0.08,
    "robot_mechanical":  0.08,
    "sea_creature":      0.06,
    "insect":            0.06,
    "object_alive":      0.05,
    "plant_tree":        0.04,
    "reptile_amphibian": 0.03,
}

# Types forbidden at sample time for young ages
HARD_BLOCKED_0_5 = {"robot_mechanical"}  # aliens map to mythical, but no "alien" subtype
YOUNG_AGE_GROUPS = {"0-1", "2-5"}


# ─── Theme targets (canonical 14) ──────────────────────────────────────

THEME_TARGETS = {
    "friendship":      0.11,
    "family":          0.11,
    "curiosity":       0.10,
    "kindness":        0.10,
    "rest":            0.09,
    "nature_wonder":   0.08,
    "imagination":     0.08,
    "courage":         0.06,
    "belonging":       0.06,
    "gratitude":       0.05,
    "self_acceptance": 0.05,
    "letting_go":      0.04,
    "celebration":     0.04,
    "mystery":         0.03,
}

# Legacy theme → canonical at reporter read-time. No catalog migration.
THEME_BACK_COMPAT = {
    "bedtime":    "rest",
    "dreamy":     "rest",
    "animals":    "nature_wonder",
    "nature":     "nature_wonder",
    "ocean":      "nature_wonder",
    "fantasy":    "imagination",
    "adventure":  "courage",
    "space":      "curiosity",
    "science":    "curiosity",
    "fairy_tale": "imagination",
    "emotions":   "self_acceptance",
    "learning":   "curiosity",
}


# ─── Geography targets (canonical 12) ──────────────────────────────────

GEOGRAPHY_TARGETS = {
    "north_america":  0.15,
    "europe":         0.12,
    "east_asia":      0.10,
    "south_asia":     0.10,
    "africa":         0.10,
    "southeast_asia": 0.08,
    "middle_east":    0.08,
    "south_america":  0.08,
    "arctic_polar":   0.06,
    "oceania":        0.05,
    "ocean_islands":  0.05,
    "imaginary":      0.03,
}

# Legacy geography → canonical at reporter read-time.
GEOGRAPHY_BACK_COMPAT = {
    "Americas":     "north_america",
    "India":        "south_asia",
    "East Asia":    "east_asia",
    "Africa":       "africa",
    "Europe":       "europe",
    "Arctic/Polar": "arctic_polar",
    "Ocean/Islands": "ocean_islands",
    "Middle East":  "middle_east",
}


# ─── Age group targets ─────────────────────────────────────────────────

AGE_GROUP_TARGETS = {
    "0-1":  0.15,
    "2-5":  0.30,
    "6-8":  0.30,
    "9-12": 0.25,
}


# ─── Plot archetype targets (short stories use these; long stories map) ─

PLOT_ARCHETYPE_TARGETS = {
    "quest_journey":      0.20,
    "discovery":          0.20,
    "friendship_bonding": 0.18,
    "transformation":     0.14,
    "problem_solving":    0.14,
    "celebration":        0.14,
}


# ═══════════════════════════════════════════════════════════════════════
#  Core sampler
# ═══════════════════════════════════════════════════════════════════════

def deficit_aware_sample(
    options: Iterable[str],
    target_weights: dict,
    recent_counts: dict,
    recent_total: int,
    boost_factor: float = 2.0,
    rng: random.Random | None = None,
) -> str:
    """Sample from options, boosting under-represented and suppressing over.

    Tuned for low daily volume (~1 item/day):
    - boost_factor=2.0 (not 3.0) prevents oscillation
    - Caller supplies the recency window (typically 21 days)

    Args:
        options: iterable of option keys
        target_weights: {option: target_fraction}
        recent_counts: {option: count_in_window}
        recent_total: total items in window (denominator)
        boost_factor: multiplier for under-represented options
        rng: optional random.Random for deterministic sampling
    """
    options = list(options)
    if not options:
        raise ValueError("deficit_aware_sample: options is empty")

    chooser = rng.choices if rng is not None else random.choices

    weights = []
    for opt in options:
        target = target_weights.get(opt, 0.05)
        actual = recent_counts.get(opt, 0) / max(recent_total, 1)

        if actual < target * 0.8:
            w = target * boost_factor
        elif actual > target * 1.3:
            w = target * 0.2
        else:
            w = target

        weights.append(max(0.01, w))

    return chooser(options, weights=weights, k=1)[0]


# ═══════════════════════════════════════════════════════════════════════
#  Catalog loader with back-compat mapping
# ═══════════════════════════════════════════════════════════════════════

def load_recent_catalog(window_days: int = 21, lang: str = "en") -> list[dict]:
    """Load content.json items created within the window."""
    if not CONTENT_PATH.exists():
        return []
    with open(CONTENT_PATH) as f:
        data = json.load(f)
    cutoff = datetime.now() - timedelta(days=window_days)
    recent = []
    for item in data:
        if item.get("lang") != lang:
            continue
        ts = item.get("created_at", "")
        if not ts:
            continue
        try:
            created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
        except ValueError:
            continue
        if created >= cutoff:
            recent.append(item)
    return recent


def canonical_character_type(item: dict) -> str | None:
    """Return canonical character type, mapping legacy values."""
    # Prefer explicit canonical field if set
    ct = item.get("characterType")
    if ct and ct in CANONICAL_CHARACTER_TYPES:
        return ct
    # Fall back to orchestrator legacy field
    legacy = item.get("lead_character_type")
    if legacy:
        return ORCHESTRATOR_TO_CANONICAL.get(legacy, legacy)
    return None


def canonical_theme(item: dict) -> str | None:
    theme = item.get("theme")
    if not theme:
        return None
    if theme in THEME_TARGETS:
        return theme
    return THEME_BACK_COMPAT.get(theme, theme)


def canonical_geography(item: dict) -> str | None:
    geo = item.get("geography")
    if not geo:
        return None
    if geo in GEOGRAPHY_TARGETS:
        return geo
    return GEOGRAPHY_BACK_COMPAT.get(geo, geo)


# ═══════════════════════════════════════════════════════════════════════
#  High-level samplers (per dimension)
# ═══════════════════════════════════════════════════════════════════════

def sample_character_type(age_group: str, recent: list[dict] | None = None,
                          rng: random.Random | None = None) -> str:
    """Sample a canonical character type appropriate for the age group.

    Hard-blocks aliens/robots for ages 0-5 (filters pool BEFORE weighting).
    """
    if age_group in ("0-1", "2-5"):
        targets = CHARACTER_TYPE_TARGETS_0_5
    elif age_group == "6-8":
        targets = CHARACTER_TYPE_TARGETS_6_8
    else:
        targets = CHARACTER_TYPE_TARGETS_9_12

    options = [k for k in targets.keys() if k not in HARD_BLOCKED_0_5
               or age_group not in YOUNG_AGE_GROUPS]

    recent = recent if recent is not None else load_recent_catalog()
    counts = Counter(canonical_character_type(i) for i in recent
                     if canonical_character_type(i) is not None)

    return deficit_aware_sample(options, targets, counts, len(recent), rng=rng)


def sample_theme(recent: list[dict] | None = None,
                 rng: random.Random | None = None) -> str:
    recent = recent if recent is not None else load_recent_catalog()
    counts = Counter(canonical_theme(i) for i in recent
                     if canonical_theme(i) is not None)
    return deficit_aware_sample(
        THEME_TARGETS.keys(), THEME_TARGETS, counts, len(recent), rng=rng
    )


def sample_geography(recent: list[dict] | None = None,
                     rng: random.Random | None = None) -> str:
    recent = recent if recent is not None else load_recent_catalog()
    counts = Counter(canonical_geography(i) for i in recent
                     if canonical_geography(i) is not None)
    return deficit_aware_sample(
        GEOGRAPHY_TARGETS.keys(), GEOGRAPHY_TARGETS, counts, len(recent), rng=rng
    )


def sample_age_group(recent: list[dict] | None = None,
                     rng: random.Random | None = None) -> str:
    recent = recent if recent is not None else load_recent_catalog()
    counts = Counter(i.get("age_group") for i in recent if i.get("age_group"))
    return deficit_aware_sample(
        AGE_GROUP_TARGETS.keys(), AGE_GROUP_TARGETS, counts, len(recent), rng=rng
    )


def sample_plot_archetype(recent: list[dict] | None = None,
                          rng: random.Random | None = None) -> str:
    recent = recent if recent is not None else load_recent_catalog()
    counts = Counter(i.get("plot_archetype") for i in recent if i.get("plot_archetype"))
    return deficit_aware_sample(
        PLOT_ARCHETYPE_TARGETS.keys(), PLOT_ARCHETYPE_TARGETS, counts, len(recent), rng=rng
    )


# ═══════════════════════════════════════════════════════════════════════
#  Recency windows (names 30d, species 7d, categories 3d)
# ═══════════════════════════════════════════════════════════════════════

def recent_names(days: int = 30, lang: str = "en") -> set[str]:
    """Character first names in the window."""
    out = set()
    for item in load_recent_catalog(window_days=days, lang=lang):
        name = (item.get("character") or {}).get("name")
        if name:
            out.add(name.strip())
    return out


def recent_species(days: int = 7, lang: str = "en") -> set[str]:
    """Species/identity descriptors in the window.

    Extracted from character.identity when available. A story about
    "a small fox" and another about "a curious fox" both count as fox.
    """
    import re
    species_words = set()
    for item in load_recent_catalog(window_days=days, lang=lang):
        identity = ((item.get("character") or {}).get("identity") or "").lower()
        # extract first noun-ish token after "a "/"an "/"the "
        m = re.search(r"\b(?:a|an|the)\s+(?:small\s+|little\s+|tiny\s+|young\s+|baby\s+|old\s+)*(\w+)", identity)
        if m:
            species_words.add(m.group(1))
    return species_words


def recent_categories(days: int = 3, lang: str = "en") -> set[str]:
    """Canonical character categories in the window."""
    out = set()
    for item in load_recent_catalog(window_days=days, lang=lang):
        cat = canonical_character_type(item)
        if cat:
            out.add(cat)
    return out


# ═══════════════════════════════════════════════════════════════════════
#  CLI sanity check
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Canonical taxonomies ===")
    print(f"Character types: {len(CANONICAL_CHARACTER_TYPES)}")
    print(f"Themes: {len(THEME_TARGETS)}")
    print(f"Geographies: {len(GEOGRAPHY_TARGETS)}")

    recent = load_recent_catalog()
    print(f"\nCatalog items in last 21d: {len(recent)}")

    print("\n=== Sample distributions (1000 draws with current catalog) ===")
    for age in ("0-1", "2-5", "6-8", "9-12"):
        draws = Counter(sample_character_type(age, recent=recent) for _ in range(1000))
        top = draws.most_common(5)
        print(f"  {age}: {top}")
