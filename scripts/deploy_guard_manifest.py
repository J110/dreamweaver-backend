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
REQUIRED_FIELDS = {
    "story": {"id", "type", "title", "text"},
    "long_story": {"id", "type", "title", "text"},
    "poem": {"id", "type", "title", "text"},
    "song": {"id", "type", "title"},
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


def _audio_candidates(record: dict) -> tuple[str, ...]:
    candidates = []
    for key in ("audio_url", "audio"):
        value = record.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for variant in record.get("audio_variants") or []:
        value = variant.get("url") or variant.get("audio_url")
        if value:
            candidates.append(value)
    return tuple(dict.fromkeys(candidates))


def _required_fields(record: dict) -> set[str]:
    content_type = str(record.get("type") or "")
    return REQUIRED_FIELDS.get(content_type, {"id", "type", "title"})


def _tiers(record: dict) -> tuple[str, ...]:
    if record.get("premium_only") or record.get("is_premium"):
        return ("premium",)
    return ("free", "premium")


def build_publishable_manifest(data_dir: Path) -> ManifestResult:
    result = ManifestResult()
    for directory in PER_CONTENT_DIRS:
        root = data_dir / directory
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
            missing = sorted(
                key for key in _required_fields(record) if not record.get(key)
            )
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
            result.items[item_id] = ManifestItem(
                id=item_id,
                language=str(record.get("lang") or record.get("language") or "en"),
                content_type=str(record.get("type") or ""),
                subtype=str(record.get("subtype") or ""),
                title=str(record.get("title") or ""),
                source_path=source_path,
                audio_candidates=_audio_candidates(record),
                cover=str(record.get("cover") or ""),
                cover_context=str(record.get("cover_context") or ""),
                tiers=_tiers(record),
                created_at=str(record.get("created_at") or ""),
                record=record,
            )
    return result
