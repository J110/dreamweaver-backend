from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

from deploy_guard_audit import PlaceholderRegistry, audit_catalog
from deploy_guard_audit import audit_playlists
from deploy_guard_manifest import ManifestResult
from deploy_guard_manifest import build_publishable_manifest
from deploy_guard_models import AuditResult, Defect, ReasonCode
from deploy_guard_recovery import RecoveryContext, RecoveryEngine, recover_until_stable


@dataclass(frozen=True)
class StrictGuardConfig:
    data_dir: Path
    placeholder_registry_path: Path
    api_origin: str
    frontend_origin: str
    admin_key: str = ""
    playlist_audit: Callable[[ManifestResult], AuditResult] | None = None


def _env_value(base_dir: Path, key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    env_path = base_dir / ".env"
    if not env_path.is_file():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw_value = line.partition("=")
        if name.strip() == key:
            return raw_value.strip().strip('"').strip("'")
    return ""


def _response_json(response) -> dict:
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    return response.json()


def fetch_live_items(config: StrictGuardConfig, client) -> list[dict]:
    headers = {"X-Admin-Key": config.admin_key} if config.admin_key else {}
    items = []
    for language in ("en", "hi"):
        page = 1
        while True:
            response = client.get(
                f"{config.api_origin.rstrip('/')}/api/v1/content",
                params={
                    "lang": language,
                    "page": page,
                    "page_size": 100,
                    "sort_by": "created_at",
                },
                headers=headers,
            )
            payload = _response_json(response).get("data") or {}
            page_items = payload.get("items") or []
            items.extend(page_items)
            if page >= int(payload.get("pages") or 1):
                break
            page += 1
    return items


def run_strict_audit(config: StrictGuardConfig, client=None) -> AuditResult:
    owns_client = client is None
    if client is None:
        import httpx

        client = httpx.Client(timeout=20, follow_redirects=True)
    try:
        manifest = build_publishable_manifest(config.data_dir)
        registry = PlaceholderRegistry.from_file(config.placeholder_registry_path)
        live_items = fetch_live_items(config, client)
        catalog_audit = audit_catalog(
            manifest,
            live_items,
            client,
            config.frontend_origin,
            registry,
        )
        defects = list(catalog_audit.defects)
        if config.playlist_audit is None:
            defects.append(Defect(
                ReasonCode.PLAYLIST_SLOT_MISSING,
                "all-playlists",
                {"error": "playlist audit provider is required"},
            ))
        else:
            defects.extend(config.playlist_audit(manifest).defects)
        return AuditResult(defects)
    finally:
        if owns_client:
            client.close()


def strict_verify(
    config: StrictGuardConfig,
    recover: Callable[[list[Defect]], object],
    max_rounds: int = 3,
) -> AuditResult:
    return recover_until_stable(
        lambda: run_strict_audit(config),
        recover,
        max_rounds,
    )


def render_verdict(audit: AuditResult) -> str:
    lines = [
        f"Content: {'HEALTHY' if not audit.blockers else 'BLOCKED'}",
    ]
    radio_offline = any(
        defect.reason is ReasonCode.RADIO_BROADCAST_OFFLINE
        for defect in audit.defects
    )
    lines.append(
        f"Radio broadcast: {'OFFLINE' if radio_offline else 'HEALTHY'}"
    )
    if audit.blockers:
        lines.append(f"Unresolved user-facing defects: {len(audit.blockers)}")
        for defect in audit.blockers:
            lines.append(
                f"- {defect.reason.value} {defect.item_id}: {defect.details}"
            )
    return "\n".join(lines)


def internal_playlist_audit(manifest: ManifestResult) -> AuditResult:
    import asyncio
    import httpx
    from app.api.v1 import playlist

    class GuardStore:
        collections = {"playlist_history": {}}

        def _persist_collection(self, _name):
            return None

    users = {
        "free": {
            "uid": "deploy-guard-free",
            "username": "deploy-guard-free",
            "subscription_tier": "free",
            "subscription_status": "inactive",
        },
        "premium": {
            "uid": "deploy-guard-premium",
            "username": "deploy-guard-premium",
            "subscription_tier": "premium",
            "subscription_status": "active",
        },
    }
    payloads = {}
    required = {}
    original_record_history = playlist._record_history
    original_record_nap_history = playlist._record_nap_history
    original_nap_cache = dict(playlist._nap_cache)
    try:
        playlist._record_history = lambda *_args, **_kwargs: None
        playlist._record_nap_history = lambda *_args, **_kwargs: None
        playlist._nap_cache.clear()
        for language in ("en", "hi"):
            for tier, user in users.items():
                bedtime = asyncio.run(playlist.get_today_playlist(
                    age="6-8",
                    lang=language,
                    tz="Asia/Kolkata",
                    store=GuardStore(),
                    current_user=user,
                ))
                nap = asyncio.run(playlist.get_nap_playlist(
                    lang=language,
                    tz="Asia/Kolkata",
                    store=GuardStore(),
                    current_user=user,
                ))
                bedtime_key = ("bedtime", language, tier)
                nap_key = ("nap", language, tier)
                payloads[bedtime_key] = bedtime.data
                payloads[nap_key] = nap.data
                required[bedtime_key] = (
                    {slot[0] for slot in playlist.SLOTS}
                    if tier == "premium"
                    else set(playlist.FREE_SLOTS)
                )
                required[nap_key] = (
                    {slot[0] for slot in playlist.NAP_SLOTS}
                    if tier == "premium"
                    else set(playlist.NAP_FREE_SLOTS)
                )
    finally:
        playlist._record_history = original_record_history
        playlist._record_nap_history = original_record_nap_history
        playlist._nap_cache.clear()
        playlist._nap_cache.update(original_nap_cache)
    config = default_config(Path(__file__).resolve().parents[1], playlist_audit=None)
    registry = PlaceholderRegistry.from_file(config.placeholder_registry_path)
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        return audit_playlists(
            payloads,
            required,
            manifest,
            client=client,
            frontend_origin=config.frontend_origin,
            placeholder_registry=registry,
        )


def default_config(
    base_dir: Path,
    playlist_audit=internal_playlist_audit,
) -> StrictGuardConfig:
    return StrictGuardConfig(
        data_dir=base_dir / "data",
        placeholder_registry_path=base_dir / "data" / "deploy_placeholder_hashes.json",
        api_origin=os.environ.get("DEPLOY_GUARD_API", "https://api.dreamvalley.app"),
        frontend_origin=os.environ.get("DEPLOY_GUARD_FRONTEND", "https://dreamvalley.app"),
        admin_key=_env_value(base_dir, "ADMIN_API_KEY"),
        playlist_audit=playlist_audit,
    )


def default_recovery_engine(
    base_dir: Path,
    config: StrictGuardConfig,
) -> RecoveryEngine:
    def reload_content() -> None:
        import httpx

        if not config.admin_key:
            raise RuntimeError("ADMIN_API_KEY is required for automatic reload")
        response = httpx.post(
            f"{config.api_origin.rstrip('/')}/api/v1/admin/reload",
            headers={"X-Admin-Key": config.admin_key},
            timeout=30,
        )
        response.raise_for_status()

    def generate_cover(source_path: Path, cover_store: Path) -> str:
        environment = os.environ.copy()
        environment["COVER_OUTPUT_DIR"] = str(cover_store)
        result = subprocess.run(
            [
                sys.executable,
                str(base_dir / "scripts" / "generate_cover_experimental.py"),
                "--story-json",
                str(source_path),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            raise RuntimeError(f"cover generation failed: {output[-2000:]}")
        record = __import__("json").loads(source_path.read_text(encoding="utf-8"))
        return str(record.get("cover") or f"/covers/{record['id']}.svg")

    return RecoveryEngine(RecoveryContext(
        data_dir=config.data_dir,
        audio_store=Path(os.environ.get("DEPLOY_GUARD_AUDIO_STORE", "/opt/audio-store")),
        cover_store=Path(os.environ.get("DEPLOY_GUARD_COVER_STORE", "/opt/cover-store")),
        search_roots=(
            base_dir / "public",
            base_dir / "seed_output",
            Path(os.environ.get("DEPLOY_GUARD_JSON_STORE", "/opt/json-store")),
        ),
        snapshot_root=Path(os.environ.get(
            "DEPLOY_GUARD_SNAPSHOT_ROOT",
            "/opt/deploy-guard-snapshots",
        )),
        cover_generator=generate_cover,
        reload_callback=reload_content,
    ))
