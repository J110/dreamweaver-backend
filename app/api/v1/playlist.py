"""Bedtime playlist API — composes today's 6-item bedtime queue.

Slot order (fixed): silly_song → poem → funny_short → short_story →
lullaby → long_story. Each slot is filled with today's cron-generated
content for the user's lang (age is ignored on the free tier — any
age group's fresh item is acceptable; paid tier will restore
age-targeted curation). Missing slots fall back to the past 30 days,
with a 7-day dedup window keyed by (date, lang) in playlist_history.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies import get_db_client, get_optional_user
from app.utils.gating import is_premium
from app.utils.backlog import should_lock_for_user
from app.utils.logger import get_logger

FREE_SLOTS = {"silly_song", "poem", "short_story", "lullaby"}

logger = get_logger(__name__)
router = APIRouter()

_BASE = Path(__file__).resolve().parents[3] / "data"

# slot_name, type, subtype, data_dir_en, data_dir_hi, audio_url_dir_en, audio_url_dir_hi, cover_url_dir_en, cover_url_dir_hi
SLOTS = [
    ("silly_song",  "song",       "silly_song",   "silly_songs",  "silly_songs_hi",  "silly-songs",  "silly-songs-hi",  "silly-songs",  "silly-songs-hi"),
    ("poem",        "poem",       None,           "poems",        "poems_hi",        "poems",        "poems-hi",        "poems",        "poems-hi"),
    ("funny_short", "song",       "funny_short",  "funny_shorts", "funny_shorts_hi", "funny-shorts", "funny-shorts-hi", "funny-shorts", "funny-shorts-hi"),
    ("short_story", "story",      None,           "stories",      "stories_hi",      "stories",      "stories-hi",      "stories",      "stories-hi"),
    ("lullaby",     "song",       "lullaby",      "lullabies",    "lullabies_hi",    "lullabies",    "lullabies-hi",    "lullabies",    "lullabies-hi"),
    ("long_story",  "long_story", None,           "long_stories", "long_stories_hi", "long-stories", "long-stories-hi", "long-stories", "long-stories-hi"),
]


class PlaylistItem(BaseModel):
    slot: str
    content_id: str
    title: str
    audio_file: Optional[str] = None
    audio_url: Optional[str] = None
    cover_file: Optional[str] = None
    cover_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    is_fallback: bool = False


class PlaylistResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _resolve_tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


def _local_today(tz: str) -> str:
    return datetime.now(_resolve_tz(tz)).date().isoformat()


def _load_dir(dir_name: str) -> list[dict]:
    d = _BASE / dir_name
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            with open(f) as fh:
                item = json.load(fh)
                item.setdefault("id", f.stem)
                out.append(item)
        except Exception as e:
            logger.warning("playlist: failed to load %s: %s", f, e)
    return out


def _audio_info(item: dict, audio_dir: str) -> tuple[Optional[str], Optional[str]]:
    """Return (audio_file, audio_url) for an item.

    Prefers the item's own `audio_url` field — it records where the file
    actually lives on disk, which can differ from the SLOTS-table audio_dir
    when cron writes a Hindi item's audio to the unsuffixed English audio
    dir (drift). Reconstructing `/audio/{audio_dir}/{audio_file}` from the
    table produced 404s for today's HI silly_song which landed in
    `/audio/silly-songs/` not `/audio/silly-songs-hi/`.
    """
    if item.get("audio_url"):
        return item.get("audio_file"), item["audio_url"]
    if item.get("audio_file"):
        return item["audio_file"], f"/audio/{audio_dir}/{item['audio_file']}"
    variants = item.get("audio_variants") or []
    for v in variants:
        url = v.get("url") or v.get("audio_url")
        if url:
            return None, url
    return None, None


def _cover_info(item: dict, cover_dir: str) -> tuple[Optional[str], Optional[str]]:
    # Same precedence rationale as _audio_info: trust the item's `cover`
    # field over the reconstructed path, since covers also drift across
    # the canonical / non-suffixed dirs in cron output.
    if item.get("cover"):
        return item.get("cover_file"), item["cover"]
    if item.get("cover_file"):
        return item["cover_file"], f"/covers/{cover_dir}/{item['cover_file']}"
    return None, None


def _item_date(item: dict) -> str:
    raw = item.get("created_at") or item.get("generation_date") or ""
    if isinstance(raw, str) and len(raw) >= 10:
        return raw[:10]
    return ""


def _item_age(item: dict) -> Optional[str]:
    if item.get("age_group"):
        return item["age_group"]
    if item.get("target_age"):
        return item["target_age"]
    amin, amax = item.get("age_min"), item.get("age_max")
    if amin is not None and amax is not None:
        return f"{amin}-{amax}"
    return None


def _pick_slot(slot_def, lang: str, today: str, recent_excluded: set) -> tuple[Optional[dict], bool, str]:
    """Return (item, is_fallback, audio_dir, cover_dir) or (None, False, ...) if no candidate.

    Free-tier selection: lang-only filter. Age groups are pooled — if today's
    cron produced any (age, lang) item for the slot type, it qualifies. Multi-
    candidate days resolve deterministically by oldest created_at, then id.
    """
    name, typ, subtype, dir_en, dir_hi, aud_en, aud_hi, cov_en, cov_hi = slot_def
    data_dir = dir_hi if lang == "hi" else dir_en
    audio_dir = aud_hi if lang == "hi" else aud_en
    cover_dir = cov_hi if lang == "hi" else cov_en

    items = _load_dir(data_dir)

    def matches(it):
        item_lang = it.get("lang", "en")
        if item_lang != lang:
            return False
        _, url = _audio_info(it, audio_dir)
        return url is not None

    candidates = [it for it in items if matches(it)]

    todays = [it for it in candidates if _item_date(it) == today]
    if todays:
        todays.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
        return todays[0], False, audio_dir, cover_dir

    # Fallback: past 30 days, excluding recent playlist members
    cutoff = (datetime.fromisoformat(today) - timedelta(days=30)).date().isoformat()
    fallbacks = [
        it for it in candidates
        if _item_date(it) >= cutoff and it.get("id") not in recent_excluded
    ]
    if not fallbacks:
        # Loosen dedup if catalog is too narrow
        fallbacks = [it for it in candidates if _item_date(it) >= cutoff]
    if fallbacks:
        # Oldest first — rotate through library
        fallbacks.sort(key=lambda x: x.get("created_at", ""))
        return fallbacks[0], True, audio_dir, cover_dir

    return None, False, audio_dir, cover_dir


def _recent_excluded_ids(store, lang: str, lookback_days: int = 7) -> set:
    """Content_ids used in any same-lang playlist in the last N days."""
    cutoff = (datetime.utcnow().date() - timedelta(days=lookback_days)).isoformat()
    history = store.collections.get("playlist_history", {})
    excluded = set()
    for record in history.values():
        if record.get("date", "") < cutoff:
            continue
        if record.get("lang") and record.get("lang") != lang:
            continue
        for cid in record.get("item_ids", []):
            excluded.add(cid)
    return excluded


def _record_history(store, date: str, lang: str, item_ids: list[str]) -> None:
    if not item_ids:
        return
    history = store.collections.setdefault("playlist_history", {})
    record_id = str(uuid.uuid4())
    history[record_id] = {
        "id": record_id,
        "date": date,
        "lang": lang,
        "item_ids": item_ids,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        store._persist_collection("playlist_history")
    except Exception as e:
        logger.warning("playlist: failed to persist history: %s", e)


@router.get("/today", response_model=PlaylistResponse)
async def get_today_playlist(
    age: str = Query("6-8", description="Age group (accepted for client compatibility; ignored on free tier)"),
    lang: str = Query("en", description="'en' or 'hi'"),
    tz: str = Query("Asia/Kolkata", description="IANA timezone string"),
    store=Depends(get_db_client),
    current_user: Optional[dict] = Depends(get_optional_user),
) -> PlaylistResponse:
    today = _local_today(tz)
    recent_excluded = _recent_excluded_ids(store, lang=lang, lookback_days=7)

    slots = SLOTS if is_premium(current_user) else [s for s in SLOTS if s[0] in FREE_SLOTS]

    items: list[PlaylistItem] = []
    missing: list[str] = []
    all_fresh = True

    for slot_def in slots:
        item, is_fallback, audio_dir, cover_dir = _pick_slot(
            slot_def, lang=lang, today=today, recent_excluded=recent_excluded,
        )
        slot_name = slot_def[0]
        if item is None:
            missing.append(slot_name)
            continue
        # Defense-in-depth: a locked item must NEVER enter the playlist.
        # FREE_SLOTS already excludes premium types and _pick_slot favors
        # recent items, so this never fires in practice — it makes the
        # guarantee structural, not coincidental. Flag-off → always False.
        if should_lock_for_user(item, current_user):
            continue
        audio_file, audio_url = _audio_info(item, audio_dir)
        cover_file, cover_url = _cover_info(item, cover_dir)
        if is_fallback:
            all_fresh = False
        items.append(PlaylistItem(
            slot=slot_name,
            content_id=item.get("id"),
            title=item.get("title") or item.get("title_en") or "",
            audio_file=audio_file,
            audio_url=audio_url,
            cover_file=cover_file,
            cover_url=cover_url,
            duration_seconds=item.get("duration_seconds") or item.get("duration"),
            is_fallback=is_fallback,
        ))

    _record_history(store, today, lang, [it.content_id for it in items])

    return PlaylistResponse(
        success=True,
        data={
            "date": today,
            "tz": tz,
            "items": [it.model_dump() for it in items],
            "missing_slots": missing,
            "all_fresh": all_fresh and not missing,
        },
        message="Today's bedtime playlist",
    )
