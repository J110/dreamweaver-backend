import asyncio
from types import SimpleNamespace

import pytest

from app.api.v1 import playlist
from scripts import deploy_guard


class Store:
    def __init__(self):
        self.collections = {"playlist_history": {}}

    def _persist_collection(self, _name):
        return None


@pytest.mark.parametrize(
    ("user", "expected_count"),
    [
        ({"subscription_tier": "free", "subscription_status": "inactive"}, 4),
        ({"subscription_tier": "premium", "subscription_status": "active"}, 6),
    ],
)
def test_bedtime_playlist_fills_every_tier_slot_from_available_content(
    monkeypatch,
    user,
    expected_count,
):
    def pick(slot_def, lang, today, recent_excluded):
        if slot_def[0] != "short_story":
            return None, False, "audio", "covers"
        return (
            {
                "id": "older-story",
                "title": "Older story",
                "lang": lang,
                "created_at": "2025-01-01T00:00:00",
                "audio_url": "/audio/older-story.mp3",
            },
            True,
            "audio",
            "covers",
        )

    monkeypatch.setattr(playlist, "_local_today", lambda _tz: "2026-07-25")
    monkeypatch.setattr(
        playlist,
        "_recent_excluded_ids",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(playlist, "_record_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(playlist, "_pick_slot", pick)
    monkeypatch.setattr(playlist, "should_lock_for_user", lambda *_args: False)

    response = asyncio.run(playlist.get_today_playlist(
        lang="en",
        tz="Asia/Kolkata",
        store=Store(),
        current_user=user,
    ))

    assert len(response.data["items"]) == expected_count
    assert all(item["audio_url"] for item in response.data["items"])
    assert response.data["missing_slots"] == []


def test_bedtime_guard_reports_tier_count_mismatch(monkeypatch):
    result = SimpleNamespace(
        returncode=0,
        stdout='{"en/free":{"actual":3,"expected":4}}\n',
        stderr="",
    )
    monkeypatch.setattr(deploy_guard.subprocess, "run", lambda *_args, **_kwargs: result)

    assert deploy_guard.verify_bedtime_playlist_counts() == [
        "Bedtime playlist en/free returned 3 items; expected 4"
    ]
