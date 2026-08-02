from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys


sys.path.insert(0, str(Path(__file__).parent))

from deploy_guard_models import AuditResult, Defect, ReasonCode, is_blocking
from deploy_guard_audit import PlaceholderRegistry, audit_catalog, audit_playlists
from deploy_guard_manifest import (
    ManifestItem,
    ManifestResult,
    build_publishable_manifest,
)
from deploy_guard_recovery import (
    RecoveryContext,
    RecoveryEngine,
    recover_until_stable,
)
from deploy_guard_transaction import (
    TransactionConfig,
    TransactionPreconditionError,
    run_transaction,
)


def write_record(data_dir, collection, record):
    target = data_dir / collection
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{record['id']}.json"
    path.write_text(__import__("json").dumps(record))
    return path


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses

    def head(self, url):
        response = self.responses.get(url, 404)
        status = response[0] if isinstance(response, tuple) else response
        return SimpleNamespace(status_code=status)

    def get(self, url):
        response = self.responses.get(url, (404, b""))
        status, content = response if isinstance(response, tuple) else (response, b"")
        return SimpleNamespace(status_code=status, content=content)


def manifest_with(item_id):
    record = {"id": item_id, "type": "story", "title": "Story", "text": "Text"}
    return ManifestResult(items={
        item_id: ManifestItem(
            id=item_id,
            language="en",
            content_type="story",
            subtype="",
            title="Story",
            source_path=Path(f"{item_id}.json"),
            audio_candidates=("/audio/story.mp3",),
            cover="/covers/custom.svg",
            cover_context="Custom scene",
            tiers=("free", "premium"),
            created_at="2026-08-02",
            record=record,
        ),
    })


def live_item(item_id, **updates):
    item = {
        "id": item_id,
        "type": "story",
        "title": "Story",
        "audio_url": "/audio/story.mp3",
        "cover": "/covers/custom.svg",
    }
    item.update(updates)
    return item


def test_only_radio_broadcast_is_non_blocking():
    radio = Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {})
    missing = Defect(ReasonCode.MISSING_AUDIO, "story-1", {})

    assert is_blocking(radio) is False
    assert is_blocking(missing) is True


def test_audit_result_exposes_only_current_blockers():
    result = AuditResult(defects=[
        Defect(ReasonCode.MISSING_AUDIO, "story-1", {}),
        Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {}),
    ])

    assert [defect.item_id for defect in result.blockers] == ["story-1"]


def test_manifest_excludes_only_explicit_non_publishable_records(tmp_path):
    write_record(tmp_path, "stories", {
        "id": "live",
        "type": "story",
        "title": "Live",
        "text": "Text",
    })
    write_record(tmp_path, "stories", {
        "id": "draft",
        "type": "story",
        "title": "Draft",
        "status": "draft",
    })

    result = build_publishable_manifest(tmp_path)

    assert set(result.items) == {"live"}


def test_manifest_flags_incomplete_unmarked_record(tmp_path):
    write_record(tmp_path, "stories", {
        "id": "broken",
        "type": "story",
    })

    result = build_publishable_manifest(tmp_path)

    assert result.defects[0].reason is ReasonCode.INVALID_SOURCE_RECORD


def test_audit_flags_missing_publishable_id():
    result = audit_catalog(
        manifest_with("story-1"),
        [],
        FakeHttp({}),
        "https://app",
    )

    assert result.blockers[0].reason is ReasonCode.MISSING_LIVE_ITEM


def test_audit_rejects_placeholder_by_path_and_hash():
    generic = b"generic"
    registry = PlaceholderRegistry(
        paths={"/covers/default.svg"},
        filename_patterns={"default.svg"},
        sha256={hashlib.sha256(generic).hexdigest()},
    )
    live = live_item("story-1", cover="/covers/custom.svg")
    http = FakeHttp({
        "https://app/covers/custom.svg": (200, generic),
        "https://app/audio/story.mp3": 200,
    })

    result = audit_catalog(
        manifest_with("story-1"),
        [live],
        http,
        "https://app",
        registry,
    )

    assert any(
        defect.reason is ReasonCode.PLACEHOLDER_COVER
        for defect in result.blockers
    )


def test_audit_checks_every_audio_candidate():
    live = live_item(
        "story-1",
        audio_url="/audio/story.mp3",
        audio_variants=[{"url": "/audio/broken.mp3"}],
    )
    http = FakeHttp({
        "https://app/covers/custom.svg": (200, b"custom"),
        "https://app/audio/story.mp3": 200,
        "https://app/audio/broken.mp3": 404,
    })

    result = audit_catalog(
        manifest_with("story-1"),
        [live],
        http,
        "https://app",
    )

    assert any(
        defect.reason is ReasonCode.MISSING_AUDIO
        and defect.details["url"] == "/audio/broken.mp3"
        for defect in result.blockers
    )


def test_playlist_audit_rejects_missing_required_slot():
    playlists = {
        ("bedtime", "en", "free"): {
            "items": [{"slot": "story", "content_id": "story-1"}],
        },
    }
    required = {("bedtime", "en", "free"): {"story", "poem"}}

    result = audit_playlists(playlists, required, manifest_with("story-1"))

    assert result.blockers[0].reason is ReasonCode.PLAYLIST_SLOT_MISSING


def test_recovery_copies_misrouted_asset_to_canonical_store(tmp_path):
    seed_root = tmp_path / "seed"
    source = seed_root / "poems_hi" / "poem.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    context = RecoveryContext(
        data_dir=tmp_path / "data",
        audio_store=tmp_path / "audio-store",
        cover_store=tmp_path / "cover-store",
        search_roots=(seed_root,),
        snapshot_root=tmp_path / "snapshot",
    )
    defect = Defect(
        ReasonCode.MISROUTED_ASSET,
        "poem",
        {
            "asset_kind": "audio",
            "filename": "poem.mp3",
            "canonical": "poems/poem.mp3",
        },
    )

    result = RecoveryEngine(context).recover([defect])[0]

    assert result.recovered is True
    assert (context.audio_store / "poems" / "poem.mp3").read_bytes() == b"audio"


def test_placeholder_recovery_regenerates_without_changing_record_fields(tmp_path):
    data_dir = tmp_path / "data"
    source = write_record(data_dir, "stories", {
        "id": "story-1",
        "type": "story",
        "title": "Story",
        "text": "Text",
        "created_at": "2026-08-02",
        "cover": "/covers/default.svg",
        "cover_context": "Moonlit custom scene",
    })

    def generate_cover(source_path, cover_store):
        target = cover_store / "story-1.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"custom")
        return "/covers/story-1.svg"

    context = RecoveryContext(
        data_dir=data_dir,
        audio_store=tmp_path / "audio-store",
        cover_store=tmp_path / "cover-store",
        search_roots=(),
        snapshot_root=tmp_path / "snapshot",
        cover_generator=generate_cover,
    )
    defect = Defect(
        ReasonCode.PLACEHOLDER_COVER,
        "story-1",
        {"source_path": str(source)},
    )

    result = RecoveryEngine(context).recover([defect])[0]
    after = __import__("json").loads(source.read_text())

    assert result.recovered is True
    assert after["id"] == "story-1"
    assert after["created_at"] == "2026-08-02"
    assert after["cover"] == "/covers/story-1.svg"


def test_recover_until_stable_stops_when_audit_is_clean():
    audits = iter([
        AuditResult([Defect(ReasonCode.MISSING_AUDIO, "story-1", {})]),
        AuditResult(),
    ])
    recovered = []

    result = recover_until_stable(
        lambda: next(audits),
        lambda defects: recovered.extend(defects),
    )

    assert result.blockers == []
    assert [defect.item_id for defect in recovered] == ["story-1"]


def test_transaction_rolls_back_when_recovery_cannot_reach_zero(tmp_path):
    calls = []
    broken = AuditResult([
        Defect(ReasonCode.MISSING_AUDIO, "story-1", {"url": "/audio/missing.mp3"}),
    ])
    postflight = iter([broken, broken, AuditResult()])
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "content.json").write_text("[]")
    config = TransactionConfig(
        snapshot_parent=tmp_path / "snapshots",
        data_dir=data_dir,
        asset_roots=(),
        preflight_audit=lambda: AuditResult(),
        postflight_audit=lambda: next(postflight),
        recover=lambda defects: calls.append(("recover", len(defects))),
        deploy_hook=lambda snapshot: calls.append(("deploy", snapshot.snapshot_id)),
        rollback_hook=lambda snapshot: calls.append(("rollback", snapshot.snapshot_id)),
    )

    verdict = run_transaction(config)

    assert calls[0][0] == "deploy"
    assert calls[-1][0] == "rollback"
    assert verdict.deployment_succeeded is False
    assert verdict.rolled_back is True
    assert verdict.app_healthy is True


def test_transaction_refuses_dirty_preflight_or_missing_rollback_hook(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    broken = AuditResult([Defect(ReasonCode.MISSING_AUDIO, "story-1", {})])
    config = TransactionConfig(
        snapshot_parent=tmp_path / "snapshots",
        data_dir=data_dir,
        asset_roots=(),
        preflight_audit=lambda: broken,
        postflight_audit=lambda: broken,
        recover=lambda defects: None,
        deploy_hook=lambda snapshot: None,
        rollback_hook=None,
    )

    with __import__("pytest").raises(TransactionPreconditionError):
        run_transaction(config)
