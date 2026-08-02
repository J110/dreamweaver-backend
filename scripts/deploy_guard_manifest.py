from dataclasses import dataclass, field
import json
from pathlib import Path

from deploy_guard_models import Defect, ReasonCode


PER_CONTENT_DIRS = (
    "stories",
    "stories_hi",
    "long_stories",
    "long_stories_hi",
    "lullabies",
    "lullabies_hi",
    "silly_songs",
    "silly_songs_hi",
    "funny_shorts",
    "funny_shorts_hi",
    "poems",
    "poems_hi",
)
NON_PUBLISHABLE = {"draft", "incomplete", "quarantined", "deleted"}
DIRECTORY_INFO = {
    "stories": ("story", "", "en", "stories"),
    "stories_hi": ("story", "", "hi", "stories-hi"),
    "long_stories": ("long_story", "", "en", "long-stories"),
    "long_stories_hi": ("long_story", "", "hi", "long-stories-hi"),
    "lullabies": ("song", "lullaby", "en", "lullabies"),
    "lullabies_hi": ("song", "lullaby", "hi", "lullabies-hi"),
    "silly_songs": ("song", "silly_song", "en", "silly-songs"),
    "silly_songs_hi": ("song", "silly_song", "hi", "silly-songs-hi"),
    "funny_shorts": ("song", "funny_short", "en", "funny-shorts"),
    "funny_shorts_hi": ("song", "funny_short", "hi", "funny-shorts-hi"),
    "poems": ("poem", "", "en", "poems"),
    "poems_hi": ("poem", "", "hi", "poems-hi"),
}


@dataclass(frozen=True)
class ManifestItem:
    id: str
    language: str
    content_type: str
    subtype: str
    title: str
    source_path: Path
    audio_candidates: tuple[str, ...]
    cover: str
    cover_context: str
    tiers: tuple[str, ...]
    created_at: str
    record: dict = field(compare=False, hash=False, repr=False)


@dataclass
class ManifestResult:
    items: dict[str, ManifestItem] = field(default_factory=dict)
    defects: list[Defect] = field(default_factory=list)


def is_publishable(record: dict) -> bool:
    state = str(
        record.get("status") or record.get("publication_status") or ""
    ).lower()
    return not record.get("is_draft") and state not in NON_PUBLISHABLE


def _media_path(value: str, kind: str, media_dir: str) -> str:
    if value.startswith(("/", "http://", "https://")):
        return value
    return f"/{kind}/{media_dir}/{value}"


def _audio_candidates(record: dict, media_dir: str) -> tuple[str, ...]:
    candidates = []
    for key in ("audio_url", "audio"):
        value = record.get(key)
        if isinstance(value, str) and value:
            candidates.append(_media_path(value, "audio", media_dir))
    audio_file = record.get("audio_file")
    if not candidates and isinstance(audio_file, str) and audio_file:
        candidates.append(_media_path(audio_file, "audio", media_dir))
    for variant in record.get("audio_variants") or []:
        value = variant.get("url") or variant.get("audio_url")
        if value:
            candidates.append(value)
    return tuple(dict.fromkeys(candidates))


def _missing_fields(record: dict, content_type: str) -> list[str]:
    missing = [key for key in ("id", "title") if not record.get(key)]
    body_fields = {
        "story": ("text", "story_text", "content"),
        "long_story": ("text", "story_text", "content"),
        "poem": ("poem_text", "text", "content"),
        "song": ("lyrics", "text", "song_text", "content", "inputs"),
    }.get(content_type, ())
    if body_fields and not any(record.get(key) for key in body_fields):
        missing.append("content_body")
    return missing


def _tiers(record: dict) -> tuple[str, ...]:
    if record.get("premium_only") or record.get("is_premium"):
        return ("premium",)
    return ("free", "premium")


def build_publishable_manifest(data_dir: Path) -> ManifestResult:
    result = ManifestResult()
    for directory in PER_CONTENT_DIRS:
        root = data_dir / directory
        inferred_type, inferred_subtype, inferred_language, media_dir = DIRECTORY_INFO[directory]
        if not root.exists():
            continue
        for source_path in sorted(root.glob("*.json")):
            try:
                record = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                result.defects.append(Defect(
                    ReasonCode.INVALID_SOURCE_RECORD,
                    source_path.stem,
                    {"source_path": str(source_path), "error": str(exc)},
                ))
                continue
            if not is_publishable(record):
                continue
            content_type = str(record.get("type") or inferred_type)
            subtype = str(record.get("subtype") or inferred_subtype)
            missing = _missing_fields(record, content_type)
            if missing:
                result.defects.append(Defect(
                    ReasonCode.INVALID_SOURCE_RECORD,
                    str(record.get("id") or source_path.stem),
                    {"source_path": str(source_path), "missing_fields": missing},
                ))
                continue
            item_id = str(record["id"])
            if item_id in result.items:
                result.defects.append(Defect(
                    ReasonCode.INVALID_SOURCE_RECORD,
                    item_id,
                    {
                        "source_path": str(source_path),
                        "error": "duplicate publishable id",
                    },
                ))
                continue
            audio_candidates = _audio_candidates(record, media_dir)
            cover = str(
                record.get("cover")
                or (
                    _media_path(str(record["cover_file"]), "covers", media_dir)
                    if record.get("cover_file")
                    else ""
                )
            )
            if not audio_candidates:
                result.defects.append(Defect(
                    ReasonCode.INVALID_SOURCE_RECORD,
                    item_id,
                    {
                        "source_path": str(source_path),
                        "missing_fields": ["audio"],
                        "recovery": "mark_incomplete",
                    },
                ))
                continue
            if not cover:
                result.defects.append(Defect(
                    ReasonCode.MISSING_CUSTOM_COVER,
                    item_id,
                    {"source_path": str(source_path)},
                ))
            result.items[item_id] = ManifestItem(
                id=item_id,
                language=str(record.get("lang") or record.get("language") or inferred_language),
                content_type=content_type,
                subtype=subtype,
                title=str(record.get("title") or ""),
                source_path=source_path,
                audio_candidates=audio_candidates,
                cover=cover,
                cover_context=str(record.get("cover_context") or ""),
                tiers=_tiers(record),
                created_at=str(record.get("created_at") or ""),
                record=record,
            )
    return result
