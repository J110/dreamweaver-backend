import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import deploy_guard


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, silly_items):
        self.silly_items = silly_items

    def get(self, url, params=None):
        if url.endswith("/api/v1/content"):
            return FakeResponse({"data": {"items": [], "pages": 1}})
        if url.endswith("/api/v1/silly-songs"):
            items = (
                self.silly_items
                if params == {"age_group": "2-5", "lang": "en"}
                else []
            )
            return FakeResponse({"data": {"items": items}})
        if url.endswith("/api/v1/poems"):
            return FakeResponse({"data": {"items": []}})
        raise AssertionError(f"unexpected URL: {url}")


def capture_state_with_items(monkeypatch, items):
    monkeypatch.setattr(
        deploy_guard.httpx,
        "Client",
        lambda **_kwargs: FakeClient(items),
    )
    return deploy_guard.capture_state("https://api.test")


def silly_state(song_id, has_cover, cover_url):
    item = {
        "title": "Song",
        "lang": "en",
        "has_audio": True,
        "audio_url": f"/audio/silly-songs/{song_id}.mp3",
        "has_cover": has_cover,
        "cover_url": cover_url,
    }
    return {
        "stories": {},
        "silly_songs": {"2-5": {song_id: item}, "6-8": {}, "9-12": {}},
        "poems": {"2-5": {}, "6-8": {}, "9-12": {}},
    }


def test_silly_snapshot_prefers_persisted_cover_url(monkeypatch):
    item = {
        "id": "song-1",
        "title": "Song",
        "audio_file": "song-1.mp3",
        "cover": "/covers/song-1.svg",
    }

    state = capture_state_with_items(monkeypatch, [item])

    saved = state["silly_songs"]["2-5"]["song-1"]
    assert saved["cover_url"] == "/covers/song-1.svg"
    assert saved["has_cover"] is True


def test_silly_snapshot_reconstructs_cover_from_cover_file(monkeypatch):
    item = {
        "id": "song-1",
        "title": "Song",
        "audio_file": "song-1.mp3",
        "cover_file": "song-1.webp",
    }

    state = capture_state_with_items(monkeypatch, [item])

    saved = state["silly_songs"]["2-5"]["song-1"]
    assert saved["cover_url"] == "/covers/silly-songs/song-1.webp"
    assert saved["has_cover"] is True


def test_diff_reports_existing_silly_song_lost_cover():
    before = silly_state(
        "song-1",
        has_cover=True,
        cover_url="/covers/song-1.svg",
    )
    after = silly_state("song-1", has_cover=False, cover_url="")

    changes = deploy_guard.diff_states(before, after)

    assert any("LOST COVER" in issue for issue in changes["degraded"])


def test_new_item_without_cover_url_is_rejected():
    issues = deploy_guard.verify_new_items_serving(
        [{
            "category": "silly_song",
            "item_id": "song-1",
            "age_group": "2-5",
            "audio_url": "",
            "cover_url": "",
        }],
        "https://frontend.invalid",
        "https://api.invalid",
    )

    assert any("no cover URL" in issue for issue in issues)
