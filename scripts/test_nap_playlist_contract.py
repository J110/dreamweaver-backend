import asyncio

import pytest

from app.api.v1 import playlist


class Store:
    collections = {"playlist_history": {}}

    def _persist_collection(self, _name):
        return None


@pytest.fixture(autouse=True)
def reset_nap_cache():
    playlist._nap_cache.clear()
    yield
    playlist._nap_cache.clear()


def run_nap(user):
    return asyncio.run(playlist.get_nap_playlist(
        lang="en",
        tz="Asia/Kolkata",
        store=Store(),
        current_user=user,
    ))


def fake_pick(slot_def, lang, today, recent_excluded):
    slot = slot_def[0]
    content_id = "shared-lullaby" if slot.startswith("nap_lullaby") else slot
    return ({
        "id": content_id,
        "title": slot,
        "lang": lang,
        "created_at": f"{today}T00:00:00",
        "audio_url": f"/audio/{content_id}.mp3",
    }, False, "audio", "covers")


def prepare_route(monkeypatch):
    monkeypatch.setattr(playlist, "_local_today", lambda _tz: "2026-07-24")
    monkeypatch.setattr(playlist, "_today_bedtime_ids", lambda *_args: set())
    monkeypatch.setattr(playlist, "_recent_excluded_ids", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(playlist, "_record_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(playlist, "_pick_slot", fake_pick)
    monkeypatch.setattr(playlist, "should_lock_for_user", lambda *_args: False)
    monkeypatch.setattr(
        playlist,
        "is_premium",
        lambda user: bool(user and user.get("subscription_tier") == "premium"),
    )


def test_cache_keeps_free_and_premium_counts_separate(monkeypatch):
    prepare_route(monkeypatch)
    free = run_nap({"subscription_tier": "free"})
    premium = run_nap({"subscription_tier": "premium"})
    assert len(free.data["items"]) == playlist.NAP_FREE_COUNT
    assert len(premium.data["items"]) == playlist.NAP_PREMIUM_COUNT


def test_premium_repeats_only_when_distinct_lullabies_are_exhausted(monkeypatch):
    prepare_route(monkeypatch)
    premium = run_nap({"subscription_tier": "premium"})
    assert len(premium.data["items"]) == playlist.NAP_PREMIUM_COUNT
    assert premium.data["items"][-1]["slot"] == "nap_lullaby_2"
    assert premium.data["items"][-1]["content_id"] == "shared-lullaby"


def test_slot_selection_uses_content_older_than_thirty_days(monkeypatch):
    old_item = {
        "id": "old-poem",
        "title": "Old poem",
        "lang": "en",
        "created_at": "2025-01-01T00:00:00",
        "audio_url": "/audio/old-poem.mp3",
    }
    monkeypatch.setattr(playlist, "_load_dir", lambda _dir: [old_item])
    item, is_fallback, _, _ = playlist._pick_slot(
        playlist.NAP_SLOTS[1],
        lang="en",
        today="2026-07-24",
        recent_excluded=set(),
    )
    assert item["id"] == "old-poem"
    assert is_fallback is True
