import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import deploy_guard, pipeline_run


def empty_changes():
    return {
        "added": [],
        "removed": [],
        "updated": [],
        "degraded": [],
        "removed_items": [],
        "added_items": [],
    }


def test_deploy_guard_verify_recovers_then_rechecks(monkeypatch):
    states = iter([{"phase": "after"}, {"phase": "rechecked"}])
    monkeypatch.setattr(
        deploy_guard,
        "capture_state",
        lambda _api: next(states),
    )
    monkeypatch.setattr(
        deploy_guard,
        "diff_states",
        lambda _before, _after: empty_changes(),
    )
    checks = iter([
        (["missing"], [{
            "type": "silly_song_cover",
            "filename": "song.webp",
            "url_path": "/covers/song.webp",
        }]),
        ([], []),
    ])
    monkeypatch.setattr(
        deploy_guard,
        "verify_files",
        lambda *_args: next(checks),
    )
    monkeypatch.setattr(
        deploy_guard,
        "verify_new_items_serving",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        deploy_guard,
        "auto_recover",
        lambda _items: (1, 0),
    )

    assert pipeline_run._deploy_guard_verify({"phase": "before"}) is True


def test_deploy_guard_verify_fails_when_recheck_still_missing(monkeypatch):
    monkeypatch.setattr(
        deploy_guard,
        "capture_state",
        lambda _api: {"phase": "after"},
    )
    monkeypatch.setattr(
        deploy_guard,
        "diff_states",
        lambda _before, _after: empty_changes(),
    )
    monkeypatch.setattr(
        deploy_guard,
        "verify_files",
        lambda *_args: (["missing"], []),
    )
    monkeypatch.setattr(
        deploy_guard,
        "verify_new_items_serving",
        lambda *_args: [],
    )

    assert pipeline_run._deploy_guard_verify({"phase": "before"}) is False


def test_deploy_guard_verify_fails_on_baseline_degradation(monkeypatch):
    changes = empty_changes()
    changes["degraded"] = ["LOST COVER silly song"]
    monkeypatch.setattr(
        deploy_guard,
        "capture_state",
        lambda _api: {"phase": "after"},
    )
    monkeypatch.setattr(
        deploy_guard,
        "diff_states",
        lambda _before, _after: changes,
    )
    monkeypatch.setattr(
        deploy_guard,
        "verify_files",
        lambda *_args: ([], []),
    )
    monkeypatch.setattr(
        deploy_guard,
        "verify_new_items_serving",
        lambda *_args: [],
    )

    assert pipeline_run._deploy_guard_verify({"phase": "before"}) is False
