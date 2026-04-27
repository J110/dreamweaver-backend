"""Diversity sampler for Hindi daily pipeline.

Loads existing Hindi catalog from seed_output/content.json and picks
content axes (age_group, mood, type-specific dim) such that the new piece
doesn't collide with anything in the last N items of that type.

Each content type has its own diversity dimensions:

    short_story   age × mood × characterType × story_type
    long_story    age × mood × world × characterType
    lullaby       age × mood × lullaby_type
    silly_song    age × mood × category × anthem_id
    poem          age × mood × poem_type

Returned axes are dicts the generator scripts feed into their LLM prompts
(as anti-duplication blocklists) and into their content generation.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONTENT_JSON = BASE_DIR / "seed_output" / "content.json"

AGE_GROUPS = ["2-5", "6-8", "9-12"]
MOODS = ["calm", "curious", "wired", "sad", "anxious", "angry"]

# Per-type axis options (from each spec's diversity section)

SHORT_STORY_TYPES = [
    "katha", "lok_katha", "neeti_katha", "prakriti_katha",
    "sapnon_ki_katha", "ghar_ki_kahani",
]

# Canonical 11 character types (from English/Hindi long-story spec §14)
CHARACTER_TYPES = [
    "land_mammal", "bird", "sea_creature", "insect", "reptile_amphibian",
    "human_child", "mythical_creature", "object_alive", "plant_tree",
    "celestial_weather", "robot_mechanical",
]

LULLABY_TYPES = [
    "heartbeat", "permission", "rocking", "counting",
    "shield", "closing", "humming", "naming",
]

SILLY_CATEGORIES = ["battle_cry", "celebration", "observation"]

POEM_TYPES = ["sound", "nonsense", "question"]

# Indian world taxonomy for long stories (HINDI_LONG_STORY_GUIDELINES §5)
LONG_STORY_WORLDS = [
    # Natural
    "Bargad Ghaati",
    "Jugnu Ka Jungle",
    "Chaandni Pahaadi",
    "Kamal Talaab",
    "Monsoon Gaon",
    "Peepal Chowk",
    "Taaron Ka Bagicha",
    # Cozy/domestic
    "Daadi Ka Ghar",
    "Chai Ki Dukaan",
    "Purani Railgaadi",
    "Kitaabon Ka Kamra",
    "Khilono Ka Shehar",
    # Mythical/dream
    "Sapnon Ki Nadi",
    "Purani Kahaniyon Ka Dweep",
    "Chaand Ki Khidki",
    "Samay Ka Bagicha",
]


def load_hindi_catalog() -> list[dict]:
    """Return all Hindi-language items from the seed content store."""
    if not CONTENT_JSON.exists():
        return []
    data = json.loads(CONTENT_JSON.read_text())
    items = data["items"] if isinstance(data, dict) else data
    return [i for i in items if i.get("lang") == "hi"]


def _by_type(items: list[dict], type_filter: dict) -> list[dict]:
    """Filter items where every (key, value) in type_filter matches."""
    out = []
    for it in items:
        if all(it.get(k) == v for k, v in type_filter.items()):
            out.append(it)
    return out


def _last_n(items: list[dict], n: int) -> list[dict]:
    """Sort by created_at desc, take first n."""
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:n]


def _avoid_collisions(options: list[str], used: list[str], top_n_to_avoid: int = None) -> str:
    """Pick from `options` an item not in the most-recent N of `used`.

    `used` should be already sorted with most-recent first. We avoid the
    last `top_n_to_avoid` items (default = min(len(options)-1, len(used))
    so there's always a valid choice).
    """
    if not options:
        raise ValueError("no options to pick from")
    if not used:
        return random.choice(options)
    if top_n_to_avoid is None:
        top_n_to_avoid = min(len(options) - 1, len(used))
    blocked = set(used[:top_n_to_avoid])
    available = [o for o in options if o not in blocked]
    if not available:
        # Last resort: avoid only the most recent one
        return random.choice([o for o in options if o != used[0]] or options)
    return random.choice(available)


def pick_short_story_axes(catalog: list[dict] | None = None) -> dict:
    """Pick (age, mood, characterType, story_type) for a fresh short story."""
    catalog = catalog if catalog is not None else load_hindi_catalog()
    same_type = _by_type(catalog, {"type": "story"})
    recent = _last_n(same_type, 30)
    return {
        "age_group": _avoid_collisions(AGE_GROUPS, [r.get("age_group") for r in recent]),
        "mood": _avoid_collisions(MOODS, [r.get("mood") for r in recent]),
        "characterType": _avoid_collisions(
            CHARACTER_TYPES, [r.get("characterType") for r in recent]
        ),
        "story_type": _avoid_collisions(
            SHORT_STORY_TYPES, [r.get("story_type") for r in recent]
        ),
        "recent_titles": [r.get("title") for r in recent[:10]],
        "recent_phrases": [r.get("repeated_phrase") for r in recent[:10] if r.get("repeated_phrase")],
        "recent_names": [
            (r.get("character") or {}).get("name", "") for r in recent[:14]
        ],
    }


def pick_long_story_axes(catalog: list[dict] | None = None) -> dict:
    catalog = catalog if catalog is not None else load_hindi_catalog()
    same_type = _by_type(catalog, {"type": "long_story"})
    recent = _last_n(same_type, 14)
    return {
        "age_group": _avoid_collisions(AGE_GROUPS, [r.get("age_group") for r in recent]),
        "mood": _avoid_collisions(MOODS, [r.get("mood") for r in recent]),
        "characterType": _avoid_collisions(
            CHARACTER_TYPES, [r.get("characterType") for r in recent]
        ),
        "world_name": _avoid_collisions(
            LONG_STORY_WORLDS, [r.get("world_name") for r in recent]
        ),
        "recent_titles": [r.get("title") for r in recent[:10]],
        "recent_phrases": [r.get("repeated_phrase") for r in recent[:10] if r.get("repeated_phrase")],
        "recent_mysteries": [r.get("mystery") for r in recent[:10] if r.get("mystery")],
    }


def pick_lullaby_axes(catalog: list[dict] | None = None) -> dict:
    catalog = catalog if catalog is not None else load_hindi_catalog()
    # Hindi lullabies live as type=song with story_format/storyType=lullaby
    same_type = [
        i for i in catalog
        if i.get("type") == "song" and (
            i.get("story_format") == "lullaby"
            or i.get("storyType") == "lullaby"
            or i.get("lullaby_type")
        )
    ]
    recent = _last_n(same_type, 14)
    return {
        "age_group": _avoid_collisions(AGE_GROUPS, [r.get("age_group") for r in recent]),
        "mood": _avoid_collisions(MOODS, [r.get("mood") for r in recent]),
        "lullaby_type": _avoid_collisions(
            LULLABY_TYPES, [r.get("lullaby_type") for r in recent]
        ),
        "recent_titles": [r.get("title") for r in recent[:10]],
    }


def pick_silly_song_axes(catalog: list[dict] | None = None) -> dict:
    catalog = catalog if catalog is not None else load_hindi_catalog()
    same_type = [
        i for i in catalog
        if i.get("type") == "song" and i.get("subtype") == "silly_song"
    ]
    recent = _last_n(same_type, 14)
    return {
        "age_group": _avoid_collisions(AGE_GROUPS, [r.get("age_group") for r in recent]),
        "mood": _avoid_collisions(MOODS, [r.get("mood") for r in recent]),
        "category": _avoid_collisions(
            SILLY_CATEGORIES, [r.get("category") for r in recent]
        ),
        "recent_anthem_ids": [r.get("anthem_id") for r in recent[:14] if r.get("anthem_id")],
        "recent_titles": [r.get("title") for r in recent[:10]],
    }


def pick_poem_axes(catalog: list[dict] | None = None) -> dict:
    catalog = catalog if catalog is not None else load_hindi_catalog()
    same_type = _by_type(catalog, {"type": "poem"})
    recent = _last_n(same_type, 14)
    return {
        "age_group": _avoid_collisions(AGE_GROUPS, [r.get("age_group") for r in recent]),
        "mood": _avoid_collisions(MOODS, [r.get("mood") for r in recent]),
        "poem_type": _avoid_collisions(
            POEM_TYPES, [r.get("poem_type") for r in recent]
        ),
        "recent_titles": [r.get("title") for r in recent[:10]],
        "recent_openings": [
            (r.get("poem_text", "") or "").split("\n")[0]
            for r in recent[:10]
            if r.get("poem_text")
        ],
    }


PICKERS = {
    "short_story": pick_short_story_axes,
    "long_story":  pick_long_story_axes,
    "lullaby":     pick_lullaby_axes,
    "silly_song":  pick_silly_song_axes,
    "poem":        pick_poem_axes,
}


if __name__ == "__main__":
    # Quick smoke test — print picked axes for each type
    cat = load_hindi_catalog()
    print(f"Hindi catalog size: {len(cat)}\n")
    for t, pick in PICKERS.items():
        axes = pick(cat)
        print(f"=== {t} ===")
        for k, v in axes.items():
            if isinstance(v, list):
                print(f"  {k}: {len(v)} items → {v[:3]}{'…' if len(v) > 3 else ''}")
            else:
                print(f"  {k}: {v}")
        print()
