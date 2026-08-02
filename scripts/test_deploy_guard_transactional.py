from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
import hashlib
import sys


sys.path.insert(0, str(Path(__file__).parent))

from deploy_guard_models import (
    AuditResult,
    Defect,
    ReasonCode,
    RecoveryResult,
    is_blocking,
)
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
    validate_hook,
    run_transaction,
)
from deploy_guard_strict import render_verdict
from deploy_guard import build_parser
from app.utils.content_completeness import is_complete_silly_song


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


def test_generated_custom_cover_is_complete_silly_song_media():
    assert is_complete_silly_song({
        "audio_file": "recovered.mp3",
        "cover": "/covers/recovered.svg",
    }) is True


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
        "audio": "/audio/live.mp3",
        "cover": "/covers/live.svg",
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


def test_manifest_normalizes_single_file_poem_and_song_records(tmp_path):
    poem = write_record(tmp_path, "poems", {
        "id": "poem-1",
        "title": "Poem",
        "content_type": "poem",
        "poem_text": "Soft stars glow",
        "audio_file": "poem-1.mp3",
        "cover_file": "poem-1.webp",
    })
    song = write_record(tmp_path, "silly_songs_hi", {
        "id": "hi-song-1",
        "title": "Song",
        "lyrics": "La la",
        "audio_file": "hi-song-1.mp3",
        "cover_file": "hi-song-1.webp",
    })

    result = build_publishable_manifest(tmp_path)

    assert result.defects == []
    assert result.items["poem-1"].source_path == poem
    assert result.items["poem-1"].audio_candidates == ("/audio/poems/poem-1.mp3",)
    assert result.items["poem-1"].cover == "/covers/poems/poem-1.webp"
    assert result.items["hi-song-1"].source_path == song
    assert result.items["hi-song-1"].language == "hi"
    assert result.items["hi-song-1"].audio_candidates == (
        "/audio/silly-songs-hi/hi-song-1.mp3",
    )


def test_manifest_accepts_funny_short_inputs_and_classifies_missing_media(tmp_path):
    write_record(tmp_path, "funny_shorts", {
        "id": "funny-1",
        "title": "Funny",
        "inputs": [{"voice": "A", "text": "Hello"}],
        "audio_file": "funny-1.mp3",
        "cover_file": "funny-1.webp",
    })
    incomplete = write_record(tmp_path, "silly_songs", {
        "id": "song-incomplete",
        "title": "Incomplete",
        "lyrics": "La",
    })

    result = build_publishable_manifest(tmp_path)

    assert "funny-1" in result.items
    assert "song-incomplete" not in result.items
    defect = next(d for d in result.defects if d.item_id == "song-incomplete")
    assert defect.details["source_path"] == str(incomplete)
    assert defect.details["recovery"] == "mark_incomplete"


def test_recovery_marks_audio_less_source_incomplete_and_reloads(tmp_path):
    source = write_record(tmp_path / "data", "silly_songs", {
        "id": "song-incomplete",
        "title": "Incomplete",
        "lyrics": "La",
    })
    reloads = []
    engine = RecoveryEngine(RecoveryContext(
        data_dir=tmp_path / "data",
        audio_store=tmp_path / "audio",
        cover_store=tmp_path / "covers",
        search_roots=(),
        snapshot_root=tmp_path / "snapshot",
        reload_callback=lambda: reloads.append(True),
    ))

    result = engine.recover([Defect(ReasonCode.INVALID_SOURCE_RECORD, "song-incomplete", {
        "source_path": str(source),
        "recovery": "mark_incomplete",
    })])[0]

    assert result.recovered is True
    assert __import__("json").loads(source.read_text())["status"] == "incomplete"
    assert reloads == [True]


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
        and defect.details["source_path"].endswith("story-1.json")
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
        and defect.details["asset_kind"] == "audio"
        and defect.details["canonical"] == "broken.mp3"
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


def test_playlist_audit_rejects_placeholder_and_broken_media():
    playlists = {
        ("nap", "en", "premium"): {
            "items": [{
                "slot": "story",
                "content_id": "story-1",
                "cover_url": "/covers/default.svg",
                "audio_url": "/audio/missing.mp3",
            }],
        },
    }
    required = {("nap", "en", "premium"): {"story"}}
    http = FakeHttp({"https://app/audio/missing.mp3": 404})

    result = audit_playlists(
        playlists,
        required,
        manifest_with("story-1"),
        client=http,
        frontend_origin="https://app",
        placeholder_registry=PlaceholderRegistry(paths={"/covers/default.svg"}),
    )

    assert {defect.reason for defect in result.blockers} == {
        ReasonCode.PLACEHOLDER_COVER,
        ReasonCode.MISSING_AUDIO,
    }


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
        reload_callback=lambda: None,
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


def test_transaction_rolls_back_when_deploy_hook_fails_after_mutation(tmp_path):
    data_dir = tmp_path / "data"
    record = write_record(data_dir, "stories", {
        "id": "story-1",
        "type": "story",
        "title": "Before",
        "audio": "/audio/story.mp3",
        "cover": "/covers/story.svg",
    })
    rollback_calls = []

    def deploy(_snapshot):
        record.write_text('{"id":"story-1","title":"Broken"}')
        raise RuntimeError("deploy failed")

    verdict = run_transaction(TransactionConfig(
        snapshot_parent=tmp_path / "snapshots",
        data_dir=data_dir,
        asset_roots=(),
        preflight_audit=lambda: AuditResult(),
        postflight_audit=lambda: AuditResult(),
        recover=lambda defects: None,
        deploy_hook=deploy,
        rollback_hook=lambda snapshot: rollback_calls.append(snapshot.snapshot_id),
    ))

    assert verdict.deployment_succeeded is False
    assert verdict.rolled_back is True
    assert rollback_calls
    assert __import__("json").loads(record.read_text())["title"] == "Before"


def test_transaction_recovers_audio_placeholder_cover_and_source_canaries(tmp_path):
    data_dir = tmp_path / "data"
    story = write_record(data_dir, "stories", {
        "id": "story-1",
        "type": "story",
        "title": "Story",
        "audio": "/audio/story.mp3",
        "cover": "/covers/story-1.svg",
    })
    second = write_record(data_dir, "stories", {
        "id": "story-2",
        "type": "story",
        "title": "Second",
        "audio": "/audio/second.mp3",
        "cover": "/covers/story-2.svg",
    })
    audio_store = tmp_path / "audio-store"
    audio = audio_store / "story.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")

    def generate_cover(source_path, cover_store):
        generated = cover_store / "story-1.svg"
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_bytes(b"custom")
        return "/covers/story-1.svg"

    engine = RecoveryEngine(RecoveryContext(
        data_dir=data_dir,
        audio_store=audio_store,
        cover_store=tmp_path / "cover-store",
        search_roots=(),
        snapshot_root=tmp_path / "snapshots",
        cover_generator=generate_cover,
        reload_callback=lambda: None,
    ))

    def audit():
        defects = []
        if not audio.exists():
            defects.append(Defect(ReasonCode.MISSING_AUDIO, "story-1", {
                "asset_kind": "audio",
                "filename": "story.mp3",
                "canonical": "story.mp3",
            }))
        if story.exists() and __import__("json").loads(story.read_text()).get("cover") == "/covers/default.svg":
            defects.append(Defect(ReasonCode.PLACEHOLDER_COVER, "story-1", {
                "source_path": str(story),
            }))
        if not second.exists():
            defects.append(Defect(ReasonCode.MISSING_SOURCE_RECORD, "story-2", {
                "relative_path": str(second.relative_to(data_dir)),
            }))
        return AuditResult(defects)

    def deploy(_snapshot):
        audio.unlink()
        record = __import__("json").loads(story.read_text())
        record["cover"] = "/covers/default.svg"
        story.write_text(__import__("json").dumps(record))
        second.unlink()

    verdict = run_transaction(TransactionConfig(
        snapshot_parent=tmp_path / "snapshots",
        data_dir=data_dir,
        asset_roots=(("audio-store", audio_store),),
        preflight_audit=audit,
        postflight_audit=audit,
        recover=engine.recover,
        deploy_hook=deploy,
        rollback_hook=lambda snapshot: None,
    ))

    assert verdict.deployment_succeeded is True
    assert audio.read_bytes() == b"audio"
    assert __import__("json").loads(story.read_text())["cover"] == "/covers/story-1.svg"
    assert second.exists()


def test_final_verdict_never_labels_blockers_pre_existing_or_informational():
    audit = AuditResult([
        Defect(ReasonCode.MISSING_AUDIO, "story-1", {"url": "/audio/missing.mp3"}),
    ])

    output = render_verdict(audit)

    assert "pre-existing" not in output.lower()
    assert "informational" not in output.lower()
    assert "MISSING_AUDIO story-1" in output


def test_radio_issue_is_reported_outside_content_blockers():
    output = render_verdict(AuditResult([
        Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {}),
    ]))

    assert "Content: HEALTHY" in output
    assert "Radio broadcast: OFFLINE" in output


def test_transaction_command_requires_deploy_and_rollback_hooks():
    with __import__("pytest").raises(SystemExit):
        build_parser().parse_args(["transaction"])


def test_preflight_supports_read_only_dry_run():
    args = build_parser().parse_args(["preflight", "--dry-run"])

    assert args.dry_run is True


def test_postflight_exception_always_rolls_back(tmp_path):
    data_dir = tmp_path / "data"
    record = write_record(data_dir, "stories", {
        "id": "story-1", "title": "Before", "text": "Text",
    })
    audits = iter([AuditResult(), RuntimeError("origin failed"), AuditResult()])
    rollbacks = []

    def audit():
        value = next(audits)
        if isinstance(value, Exception):
            raise value
        return value

    def deploy(_snapshot):
        record.write_text('{"id":"story-1","title":"After"}')

    verdict = run_transaction(TransactionConfig(
        snapshot_parent=tmp_path / "snapshots",
        data_dir=data_dir,
        asset_roots=(),
        preflight_audit=audit,
        postflight_audit=audit,
        recover=lambda defects: None,
        deploy_hook=deploy,
        rollback_hook=lambda snapshot: rollbacks.append(snapshot.snapshot_id),
    ))

    assert verdict.rolled_back is True
    assert rollbacks
    assert __import__("json").loads(record.read_text())["title"] == "Before"


def test_failed_preflight_recovery_restores_partial_mutations(tmp_path):
    data_dir = tmp_path / "data"
    record = write_record(data_dir, "stories", {
        "id": "story-1", "title": "Before", "text": "Text",
    })
    broken = AuditResult([Defect(ReasonCode.MISSING_AUDIO, "story-1", {})])

    def recover(_defects):
        record.write_text('{"id":"story-1","title":"Partially repaired"}')

    with __import__("pytest").raises(TransactionPreconditionError):
        run_transaction(TransactionConfig(
            snapshot_parent=tmp_path / "snapshots",
            data_dir=data_dir,
            asset_roots=(),
            preflight_audit=lambda: broken,
            postflight_audit=lambda: AuditResult(),
            recover=recover,
            deploy_hook=lambda snapshot: None,
            rollback_hook=lambda snapshot: None,
        ))

    assert __import__("json").loads(record.read_text())["title"] == "Before"


def test_recovery_rejects_store_traversal(tmp_path):
    outside = tmp_path / "outside.mp3"
    source = tmp_path / "source" / "outside.mp3"
    source.parent.mkdir()
    source.write_bytes(b"audio")
    engine = RecoveryEngine(RecoveryContext(
        data_dir=tmp_path / "data",
        audio_store=tmp_path / "audio-store",
        cover_store=tmp_path / "cover-store",
        search_roots=(source.parent,),
        snapshot_root=tmp_path / "snapshots",
    ))

    result = engine.recover([Defect(ReasonCode.MISSING_AUDIO, "story-1", {
        "asset_kind": "audio",
        "filename": "outside.mp3",
        "canonical": "../outside.mp3",
    })])[0]

    assert result.recovered is False
    assert not outside.exists()


def test_validate_hook_requires_absolute_path(tmp_path, monkeypatch):
    hook = tmp_path / "hook"
    hook.write_text("#!/bin/sh\n")
    hook.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    with __import__("pytest").raises(TransactionPreconditionError):
        validate_hook(Path("hook"))


def test_free_playlist_locked_teaser_does_not_require_audio():
    playlists = {
        ("nap", "en", "free"): {
            "items": [
                {"slot": "nap_story", "content_id": "story-1", "cover_url": "/covers/custom.svg", "audio_url": "/audio/story.mp3"},
                {"slot": "nap_lullaby_2", "content_id": "story-1", "cover_url": "/covers/custom.svg", "is_locked": True},
            ],
        },
    }
    http = FakeHttp({
        "https://app/covers/custom.svg": (200, b"custom"),
        "https://app/audio/story.mp3": 200,
    })

    result = audit_playlists(
        playlists,
        {("nap", "en", "free"): {"nap_story"}},
        manifest_with("story-1"),
        client=http,
        frontend_origin="https://app",
    )

    assert not any(defect.reason is ReasonCode.MISSING_AUDIO for defect in result.blockers)


def test_catalog_accepts_asset_from_api_origin_and_blocks_failed_hash_get():
    live = [live_item("story-1")]
    dual_origin = FakeHttp({
        "https://app/covers/custom.svg": 404,
        "https://api/covers/custom.svg": (200, b"custom"),
        "https://app/audio/story.mp3": 404,
        "https://api/audio/story.mp3": 200,
    })

    clean = audit_catalog(
        manifest_with("story-1"),
        live,
        dual_origin,
        "https://app",
        api_origin="https://api",
    )

    assert clean.blockers == []

    class FailedHashGet(FakeHttp):
        def get(self, url):
            return SimpleNamespace(status_code=503, content=b"")

    failed_hash = FailedHashGet({
        "https://app/covers/custom.svg": 200,
        "https://app/audio/story.mp3": 200,
    })
    result = audit_catalog(
        manifest_with("story-1"),
        live,
        failed_hash,
        "https://app",
        PlaceholderRegistry(sha256={"expected"}),
    )

    assert any(defect.reason is ReasonCode.UNREACHABLE_ORIGIN for defect in result.blockers)


def test_free_playlist_rejects_unlocked_premium_only_item():
    manifest = manifest_with("story-1")
    manifest.items["story-1"] = replace(
        manifest.items["story-1"],
        tiers=("premium",),
    )
    playlists = {
        ("bedtime", "en", "free"): {
            "items": [{
                "slot": "story",
                "content_id": "story-1",
                "cover_url": "/covers/custom.svg",
                "audio_url": "/audio/story.mp3",
            }],
        },
    }
    http = FakeHttp({
        "https://app/covers/custom.svg": 200,
        "https://app/audio/story.mp3": 200,
    })

    result = audit_playlists(
        playlists,
        {("bedtime", "en", "free"): {"story"}},
        manifest,
        client=http,
        frontend_origin="https://app",
    )

    assert any(defect.reason is ReasonCode.WRONG_METADATA_PATH for defect in result.blockers)


def test_catalog_does_not_substitute_source_media_for_missing_live_metadata():
    http = FakeHttp({
        "https://app/covers/custom.svg": 200,
        "https://app/audio/story.mp3": 200,
    })

    result = audit_catalog(
        manifest_with("story-1"),
        [{"id": "story-1", "title": "Story"}],
        http,
        "https://app",
    )

    assert {defect.reason for defect in result.blockers} == {
        ReasonCode.MISSING_CUSTOM_COVER,
        ReasonCode.MISSING_AUDIO,
    }


def test_cover_recovery_reloads_and_reverts_metadata_when_reload_fails(tmp_path):
    data_dir = tmp_path / "data"
    source = write_record(data_dir, "stories", {
        "id": "story-1",
        "title": "Story",
        "text": "Text",
        "cover": "/covers/default.svg",
    })

    def generate(_source, cover_store):
        cover_store.mkdir(parents=True, exist_ok=True)
        (cover_store / "story-1.svg").write_bytes(b"custom")
        return "/covers/story-1.svg"

    reloads = []

    def fail_reload():
        reloads.append(True)
        raise RuntimeError("reload failed")

    engine = RecoveryEngine(RecoveryContext(
        data_dir=data_dir,
        audio_store=tmp_path / "audio",
        cover_store=tmp_path / "covers",
        search_roots=(),
        snapshot_root=tmp_path / "snapshot",
        cover_generator=generate,
        reload_callback=fail_reload,
    ))

    result = engine.recover([Defect(ReasonCode.PLACEHOLDER_COVER, "story-1", {
        "source_path": str(source),
    })])[0]

    assert result.recovered is False
    assert __import__("json").loads(source.read_text())["cover"] == "/covers/default.svg"
    assert len(reloads) == 2


def test_failed_recovery_is_latched_when_next_audit_looks_clean():
    defect = Defect(ReasonCode.PLACEHOLDER_COVER, "story-1", {})
    audits = iter([AuditResult([defect]), AuditResult()])

    result = recover_until_stable(
        lambda: next(audits),
        lambda defects: [RecoveryResult(defects[0], False, "reload timed out")],
    )

    assert result.blockers[0].reason is ReasonCode.STALE_LIVE_STATE
