from dataclasses import dataclass, field
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from deploy_guard_manifest import ManifestResult
from deploy_guard_models import AuditResult, Defect, ReasonCode


@dataclass(frozen=True)
class PlaceholderRegistry:
    paths: set[str] = field(default_factory=set)
    filename_patterns: set[str] = field(default_factory=set)
    sha256: set[str] = field(default_factory=set)

    @classmethod
    def from_file(cls, path: Path) -> "PlaceholderRegistry":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            paths=set(data.get("paths") or []),
            filename_patterns=set(data.get("filename_patterns") or []),
            sha256=set(data.get("sha256") or []),
        )

    def matches_path(self, path: str) -> bool:
        filename = Path(urlparse(path).path).name
        return path in self.paths or any(
            fnmatch(filename, pattern) for pattern in self.filename_patterns
        )

    def matches_content(self, content: bytes) -> bool:
        return bool(self.sha256) and hashlib.sha256(content).hexdigest() in self.sha256


def _full_url(origin: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return f"{origin.rstrip('/')}/{path.lstrip('/')}"


def _head_asset(client, path: str, *origins: str):
    last_response = None
    errors = []
    for origin in dict.fromkeys(origin for origin in origins if origin):
        url = _full_url(origin, path)
        try:
            response = client.head(url)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        last_response = response
        if response.status_code in (200, 206):
            return response, url, errors
    return last_response, "", errors


def _audio_candidates(item: dict) -> list[str]:
    values = []
    for key in ("audio_url", "audio"):
        value = item.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    for variant in item.get("audio_variants") or []:
        value = variant.get("url") or variant.get("audio_url")
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _defect(reason: ReasonCode, item_id: str, **details) -> Defect:
    return Defect(reason, item_id, details)


def _asset_details(path: str, kind: str, source_path: Path) -> dict:
    parsed_path = urlparse(path).path
    prefix = f"/{kind}/"
    canonical = parsed_path.split(prefix, 1)[-1] if prefix in parsed_path else Path(parsed_path).name
    return {
        "url": path,
        "asset_kind": "audio" if kind == "audio" else "cover",
        "canonical": canonical,
        "filename": Path(parsed_path).name,
        "source_path": str(source_path),
    }


def audit_catalog(
    manifest: ManifestResult,
    live_items: list[dict],
    client,
    frontend_origin: str,
    placeholder_registry: PlaceholderRegistry | None = None,
    api_origin: str = "",
) -> AuditResult:
    registry = placeholder_registry or PlaceholderRegistry(
        paths={"/covers/default.svg"},
        filename_patterns={"default.svg", "placeholder.svg", "placeholder.webp"},
    )
    defects = list(manifest.defects)
    live_by_id = {
        str(item.get("id")): item for item in live_items if item.get("id")
    }

    for item_id in sorted(set(manifest.items) - set(live_by_id)):
        defects.append(_defect(
            ReasonCode.MISSING_LIVE_ITEM,
            item_id,
            source_path=str(manifest.items[item_id].source_path),
        ))
    for item_id in sorted(set(live_by_id) - set(manifest.items)):
        defects.append(_defect(
            ReasonCode.MISSING_SOURCE_RECORD,
            item_id,
            live_item=live_by_id[item_id],
        ))

    for item_id in sorted(set(manifest.items) & set(live_by_id)):
        item = live_by_id[item_id]
        manifest_item = manifest.items[item_id]
        cover = str(item.get("cover") or manifest_item.cover or "")
        if not cover:
            defects.append(_defect(
                ReasonCode.MISSING_CUSTOM_COVER,
                item_id,
                source_path=str(manifest_item.source_path),
            ))
        elif registry.matches_path(cover):
            defects.append(_defect(
                ReasonCode.PLACEHOLDER_COVER,
                item_id,
                **_asset_details(cover, "covers", manifest_item.source_path),
            ))
        else:
            response, cover_url, errors = _head_asset(
                client, cover, frontend_origin, api_origin,
            )
            if response is None:
                defects.append(_defect(
                    ReasonCode.UNREACHABLE_ORIGIN,
                    item_id,
                    url=cover,
                    error="; ".join(errors),
                ))
            else:
                if response.status_code not in (200, 206):
                    defects.append(_defect(
                        ReasonCode.MISSING_CUSTOM_COVER,
                        item_id,
                        status=response.status_code,
                        **_asset_details(cover, "covers", manifest_item.source_path),
                    ))
                elif registry.sha256:
                    try:
                        content_response = client.get(cover_url)
                    except Exception as exc:
                        defects.append(_defect(
                            ReasonCode.UNREACHABLE_ORIGIN,
                            item_id,
                            url=cover,
                            error=str(exc),
                        ))
                    else:
                        if content_response.status_code not in (200, 206):
                            defects.append(_defect(
                                ReasonCode.UNREACHABLE_ORIGIN,
                                item_id,
                                url=cover,
                                status=content_response.status_code,
                            ))
                        elif registry.matches_content(content_response.content):
                            defects.append(_defect(
                                ReasonCode.PLACEHOLDER_COVER,
                                item_id,
                                sha256=hashlib.sha256(content_response.content).hexdigest(),
                                **_asset_details(cover, "covers", manifest_item.source_path),
                            ))

        audio_urls = list(dict.fromkeys([
            *_audio_candidates(item),
            *manifest_item.audio_candidates,
        ]))
        if not audio_urls:
            defects.append(_defect(ReasonCode.MISSING_AUDIO, item_id))
        for audio_url in audio_urls:
            response, _resolved_url, errors = _head_asset(
                client, audio_url, frontend_origin, api_origin,
            )
            if response is None:
                defects.append(_defect(
                    ReasonCode.UNREACHABLE_ORIGIN,
                    item_id,
                    url=audio_url,
                    error="; ".join(errors),
                ))
                continue
            if response.status_code not in (200, 206):
                defects.append(_defect(
                    ReasonCode.MISSING_AUDIO,
                    item_id,
                    status=response.status_code,
                    **_asset_details(audio_url, "audio", manifest_item.source_path),
                ))
    return AuditResult(defects)


def audit_playlists(
    playlists: dict[tuple[str, str, str], dict],
    required_slots: dict[tuple[str, str, str], set[str]],
    manifest: ManifestResult,
    client=None,
    frontend_origin: str = "",
    placeholder_registry: PlaceholderRegistry | None = None,
    api_origin: str = "",
) -> AuditResult:
    defects = []
    registry = placeholder_registry or PlaceholderRegistry(
        paths={"/covers/default.svg"},
        filename_patterns={"default.svg", "placeholder.svg", "placeholder.webp"},
    )
    for surface, expected_slots in required_slots.items():
        payload = playlists.get(surface) or {}
        items = payload.get("items") or []
        actual_slots = {str(item.get("slot") or "") for item in items}
        for slot in sorted(expected_slots - actual_slots):
            defects.append(_defect(
                ReasonCode.PLAYLIST_SLOT_MISSING,
                "/".join(surface),
                slot=slot,
                surface=surface,
            ))
        ids = [str(item.get("content_id") or item.get("id") or "") for item in items]
        if len(ids) != len(set(ids)):
            defects.append(_defect(
                ReasonCode.PLAYLIST_SLOT_MISSING,
                "/".join(surface),
                error="duplicate content ids",
                surface=surface,
            ))
        for item_id in ids:
            if item_id and item_id not in manifest.items:
                defects.append(_defect(
                    ReasonCode.MISSING_SOURCE_RECORD,
                    item_id,
                    surface=surface,
                ))
        if client is None:
            continue
        for item in items:
            slot = str(item.get("slot") or "")
            playable = slot in expected_slots and not item.get("is_locked")
            item_id = str(item.get("content_id") or item.get("id") or "")
            manifest_item = manifest.items.get(item_id)
            source_path = manifest_item.source_path if manifest_item else Path("")
            tier = surface[2]
            if (
                manifest_item
                and tier not in manifest_item.tiers
                and not item.get("is_locked")
            ):
                defects.append(_defect(
                    ReasonCode.WRONG_METADATA_PATH,
                    item_id,
                    surface=surface,
                    error=f"{tier} surface contains {manifest_item.tiers}-only item",
                ))
            cover = str(item.get("cover_url") or item.get("cover") or "")
            if not cover:
                defects.append(_defect(
                    ReasonCode.MISSING_CUSTOM_COVER,
                    item_id or "/".join(surface),
                    surface=surface,
                    source_path=str(source_path),
                ))
            elif registry.matches_path(cover):
                defects.append(_defect(
                    ReasonCode.PLACEHOLDER_COVER,
                    item_id or "/".join(surface),
                    surface=surface,
                    **_asset_details(cover, "covers", source_path),
                ))
            else:
                response, cover_url, errors = _head_asset(
                    client, cover, frontend_origin, api_origin,
                )
                if response is None:
                    defects.append(_defect(
                        ReasonCode.UNREACHABLE_ORIGIN,
                        item_id or "/".join(surface),
                        surface=surface,
                        url=cover,
                        error="; ".join(errors),
                    ))
                else:
                    if response.status_code not in (200, 206):
                        defects.append(_defect(
                            ReasonCode.MISSING_CUSTOM_COVER,
                            item_id or "/".join(surface),
                            surface=surface,
                            status=response.status_code,
                            **_asset_details(cover, "covers", source_path),
                        ))
                    elif registry.sha256:
                        try:
                            content_response = client.get(cover_url)
                        except Exception as exc:
                            defects.append(_defect(
                                ReasonCode.UNREACHABLE_ORIGIN,
                                item_id or "/".join(surface),
                                surface=surface,
                                url=cover,
                                error=str(exc),
                            ))
                        else:
                            if content_response.status_code not in (200, 206):
                                defects.append(_defect(
                                    ReasonCode.UNREACHABLE_ORIGIN,
                                    item_id or "/".join(surface),
                                    surface=surface,
                                    url=cover,
                                    status=content_response.status_code,
                                ))
                            elif registry.matches_content(content_response.content):
                                defects.append(_defect(
                                    ReasonCode.PLACEHOLDER_COVER,
                                    item_id or "/".join(surface),
                                    surface=surface,
                                    sha256=hashlib.sha256(content_response.content).hexdigest(),
                                    **_asset_details(cover, "covers", source_path),
                                ))
            audio_urls = _audio_candidates(item)
            if playable and not audio_urls:
                defects.append(_defect(
                    ReasonCode.MISSING_AUDIO,
                    item_id or "/".join(surface),
                    surface=surface,
                    source_path=str(source_path),
                ))
            for audio_url in audio_urls if playable else []:
                response, _resolved_url, errors = _head_asset(
                    client, audio_url, frontend_origin, api_origin,
                )
                if response is None:
                    defects.append(_defect(
                        ReasonCode.UNREACHABLE_ORIGIN,
                        item_id or "/".join(surface),
                        surface=surface,
                        url=audio_url,
                        error="; ".join(errors),
                    ))
                else:
                    if response.status_code not in (200, 206):
                        defects.append(_defect(
                            ReasonCode.MISSING_AUDIO,
                            item_id or "/".join(surface),
                            surface=surface,
                            status=response.status_code,
                            **_asset_details(audio_url, "audio", source_path),
                        ))
    return AuditResult(defects)
