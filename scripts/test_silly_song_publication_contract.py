import json

from app.api.v1 import silly_songs
from app.services.local_store import LocalStore


def _write_song(bucket, song_id, **fields):
    bucket.mkdir(exist_ok=True)
    (bucket / f"{song_id}.json").write_text(json.dumps({"id": song_id, **fields}))


def test_local_store_preserves_but_excludes_incomplete_silly_song(tmp_path):
    bucket = tmp_path / "silly_songs"
    _write_song(
        bucket,
        "complete",
        audio_file="complete.mp3",
        cover_file="complete.webp",
    )
    _write_song(bucket, "draft", audio_file="draft.mp3")
    store = object.__new__(LocalStore)
    store._data_dir = tmp_path

    content = store._walk_per_content()

    assert "complete" in content
    assert "draft" not in content
    assert (bucket / "draft.json").exists()


def test_silly_song_loader_returns_only_complete_records(monkeypatch, tmp_path):
    bucket = tmp_path / "silly_songs"
    _write_song(
        bucket,
        "complete",
        audio_file="complete.mp3",
        cover_file="complete.webp",
    )
    _write_song(bucket, "missing_audio", cover_file="missing_audio.webp")
    _write_song(bucket, "missing_cover", audio_file="missing_cover.mp3")
    monkeypatch.setattr(silly_songs, "DATA_DIRS", [bucket])

    assert [song["id"] for song in silly_songs._load_all_songs()] == ["complete"]
