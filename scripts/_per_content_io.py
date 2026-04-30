"""Shared helpers for writing data/<type>/<id>.json per-content files.

Per the 2026-04-29 refactor (docs/superpowers/specs/2026-04-29-content-json-refactor.md),
data/<type>/<id>.json is the single source of truth. seed_output/content.json and
data/content.json are derived snapshots — the backend rebuilds them from per-content
dirs on every admin reload and at boot. Field updates that only touch the snapshot
get silently overwritten on the next reload.

This module gives generators a one-line way to keep the per-content file in sync.

Routing mirrors app/services/local_store.py::_content_target_dir.
"""
import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

_PER_CONTENT_DIRS = (
    "stories", "stories_hi",
    "long_stories", "long_stories_hi",
    "lullabies", "lullabies_hi",
    "silly_songs", "silly_songs_hi",
    "funny_shorts", "funny_shorts_hi",
    "poems", "poems_hi",
)


def per_content_target(item: dict) -> Optional[Path]:
    typ = item.get("type")
    subtype = item.get("subtype")
    lang = item.get("lang") or item.get("language") or "en"
    suffix = "_hi" if lang == "hi" else ""
    if typ == "story":      return DATA_DIR / f"stories{suffix}"
    if typ == "long_story": return DATA_DIR / f"long_stories{suffix}"
    if typ == "poem":       return DATA_DIR / f"poems{suffix}"
    if typ == "song":
        if subtype == "silly_song":  return DATA_DIR / f"silly_songs{suffix}"
        if subtype == "funny_short": return DATA_DIR / f"funny_shorts{suffix}"
        return DATA_DIR / f"lullabies{suffix}"
    return None


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in data.items() if k != "subtype"}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(path)


def write_per_content(item: dict) -> bool:
    target = per_content_target(item)
    if target is None or not item.get("id"):
        return False
    _atomic_write(target / f"{item['id']}.json", item)
    return True


def find_per_content_file(item_id: str) -> Optional[Path]:
    for sub in _PER_CONTENT_DIRS:
        p = DATA_DIR / sub / f"{item_id}.json"
        if p.exists():
            return p
    return None


def update_per_content_fields(item_id: str, **fields) -> bool:
    """Read the per-content file, merge fields in, write atomically.

    Returns False if the file doesn't exist (caller may want to log a warning).
    """
    path = find_per_content_file(item_id)
    if path is None:
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    data.update(fields)
    _atomic_write(path, data)
    return True
