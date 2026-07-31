# Silly Song Duration and Publication Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Target 60–90-second silly songs while accepting 50–100 seconds, persist accepted assets before publication, and exclude incomplete silly-song drafts from public catalogs without deleting their source JSON.

**Architecture:** The generator will separate preferred and accepted duration constants and synchronously copy accepted assets to persistent stores. A shared completeness predicate will gate both the generic content walker and the silly-song list endpoint, while deploy guard will normalize legacy `cover_file` metadata.

**Tech Stack:** Python 3, FastAPI, pytest, pathlib, shutil, JSON file storage

## Global Constraints

- Preferred generation duration is 60–90 seconds.
- Accepted duration is 50–100 seconds inclusive.
- A public silly song requires both `audio_file` and `cover_file`.
- Accepted assets must reach persistent storage before catalog insertion.
- Incomplete source JSON must remain preserved on disk.
- Existing regenerated recovery outputs must remain archived and unused.

---

### Task 1: Duration Guidance and Asset Persistence

**Files:**
- Modify: `scripts/generate_silly_songs_battlecry.py:70-90`
- Modify: `scripts/generate_silly_songs_battlecry.py:420-445`
- Modify: `scripts/generate_silly_songs_battlecry.py:1070-1310`
- Test: `scripts/test_silly_song_diversity_rotation.py:1-115`

**Interfaces:**
- Consumes: generated MP3/WebP paths after validation.
- Produces: `TARGET_SILLY_SONG_SECONDS_MIN`, `TARGET_SILLY_SONG_SECONDS_MAX`, `MIN_SILLY_SONG_SECONDS`, `MAX_SILLY_SONG_SECONDS`, `AUDIO_STORE`, `COVER_STORE`, and `_persist_asset(source: Path, destination: Path) -> bool`.

- [ ] **Step 1: Write failing duration-guidance and backup tests**

```python
from pathlib import Path


def test_generation_prompt_demands_preferred_duration():
    assert "60–90 seconds" in generator.LYRICS_PROMPT_BASE


def test_audio_is_backed_up_after_acceptance(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio"
    audio_store = tmp_path / "store"
    audio_dir.mkdir()
    _stub_minimax_audio(monkeypatch, audio_dir, [60])
    monkeypatch.setattr(generator, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(generator, "AUDIO_STORE", audio_store)
    monkeypatch.setattr(
        generator,
        "_run_minimax_prediction",
        lambda *_: "https://replicate.delivery/song.mp3",
    )
    song = {
        "id": "persisted_audio",
        "lyrics": "[verse]\nA complete silly song",
        "age_group": "9-12",
        "style_prompt": "playful pop",
    }

    assert generator.generate_audio_minimax(song) is True
    assert (audio_store / "persisted_audio.mp3").read_bytes() == (
        audio_dir / "persisted_audio.mp3"
    ).read_bytes()


def test_audio_backup_failure_blocks_success(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _stub_minimax_audio(monkeypatch, audio_dir, [60, 60])
    monkeypatch.setattr(generator, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(
        generator,
        "_run_minimax_prediction",
        lambda *_: "https://replicate.delivery/song.mp3",
    )
    monkeypatch.setattr(generator, "_persist_asset", lambda *_: False)
    song = {
        "id": "unbacked_audio",
        "lyrics": "[verse]\nA complete silly song",
        "age_group": "9-12",
        "style_prompt": "playful pop",
    }

    assert generator.generate_audio_minimax(song) is False
    assert "audio_file" not in song


def test_cover_is_backed_up_before_success(monkeypatch, tmp_path):
    cover_dir = tmp_path / "covers"
    cover_store = tmp_path / "store"
    cover_dir.mkdir()

    class FakeImage:
        LANCZOS = object()

        @staticmethod
        def open(_):
            return FakeImage()

        def convert(self, _):
            return self

        def resize(self, *_):
            return self

        def save(self, path, **_):
            Path(path).write_bytes(b"cover")

    monkeypatch.setattr(generator, "Image", FakeImage)
    monkeypatch.setattr(generator, "COVERS_DIR", cover_dir)
    monkeypatch.setattr(generator, "COVER_STORE", cover_store)
    monkeypatch.setattr(
        generator.httpx,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200, content=b"x" * 2000),
    )
    song = {"id": "persisted_cover", "cover_description": "a dancing child"}

    assert generator.generate_cover_flux(song) is True
    assert (cover_store / "persisted_cover.webp").read_bytes() == b"cover"
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python -m pytest \
  scripts/test_silly_song_diversity_rotation.py::test_generation_prompt_demands_preferred_duration \
  scripts/test_silly_song_diversity_rotation.py::test_audio_is_backed_up_after_acceptance \
  scripts/test_silly_song_diversity_rotation.py::test_audio_backup_failure_blocks_success \
  scripts/test_silly_song_diversity_rotation.py::test_cover_is_backed_up_before_success -q
```

Expected: FAIL because the preferred-duration constants, persistent-store paths, and backup helper do not exist.

- [ ] **Step 3: Add separate preferred and accepted duration constants**

```python
TARGET_SILLY_SONG_SECONDS_MIN = 60
TARGET_SILLY_SONG_SECONDS_MAX = 90
MIN_SILLY_SONG_SECONDS = 50
MAX_SILLY_SONG_SECONDS = 100
```

Use the target constants in generation instructions and retry feedback. Keep runtime validation on `MIN_SILLY_SONG_SECONDS` and `MAX_SILLY_SONG_SECONDS`.

- [ ] **Step 4: Add persistent-store paths and the copy gate**

```python
AUDIO_STORE = Path("/opt/audio-store/silly-songs")
COVER_STORE = Path("/opt/cover-store/silly-songs")


def _persist_asset(source: Path, destination: Path) -> bool:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination.exists() and destination.stat().st_size == source.stat().st_size
    except OSError as exc:
        print(f"    Backup failed: {exc}")
        return False
```

Call `_persist_asset` after audio duration validation and after cover encoding. Set `audio_file`, `duration_seconds`, `cover_file`, and `cover` only after the corresponding persistent copy succeeds.

- [ ] **Step 5: Run Task 1 tests and verify GREEN**

Run:

```bash
python -m pytest \
  scripts/test_silly_song_diversity_rotation.py \
  scripts/test_silly_song_replicate_polling.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/generate_silly_songs_battlecry.py scripts/test_silly_song_diversity_rotation.py
git commit -m "fix: persist accepted silly song assets"
```

### Task 2: Public Completeness Gate and Legacy Guard Schema

**Files:**
- Create: `app/utils/content_completeness.py`
- Modify: `app/services/local_store.py:20-35`
- Modify: `app/services/local_store.py:245-323`
- Modify: `app/api/v1/silly_songs.py:1-115`
- Modify: `scripts/deploy_guard.py:185-235`
- Create: `scripts/test_silly_song_publication_contract.py`
- Modify: `scripts/test_deploy_guard_regression_contracts.py:30-40`

**Interfaces:**
- Consumes: per-content silly-song dictionaries.
- Produces: `is_complete_silly_song(item: dict) -> bool`, used by both catalog builders.

- [ ] **Step 1: Write failing completeness tests**

```python
import json

from app.api.v1.silly_songs import _load_all_songs
from app.services.local_store import LocalStore
from app.utils.content_completeness import is_complete_silly_song


def test_silly_song_requires_audio_and_cover():
    assert is_complete_silly_song({"audio_file": "song.mp3", "cover_file": "song.webp"})
    assert not is_complete_silly_song({"audio_file": "song.mp3"})
    assert not is_complete_silly_song({"cover_file": "song.webp"})


def test_local_store_preserves_but_excludes_incomplete_silly_song(tmp_path):
    bucket = tmp_path / "silly_songs"
    bucket.mkdir()
    (bucket / "complete.json").write_text(json.dumps({
        "id": "complete",
        "audio_file": "complete.mp3",
        "cover_file": "complete.webp",
    }))
    (bucket / "draft.json").write_text(json.dumps({
        "id": "draft",
        "audio_file": "draft.mp3",
    }))

    store = LocalStore(data_dir=tmp_path)

    assert "complete" in store.collections["content"]
    assert "draft" not in store.collections["content"]
    assert (bucket / "draft.json").exists()
```

Add an endpoint-loader test by monkeypatching `DATA_DIRS` to a temporary bucket and asserting `_load_all_songs()` returns only complete records.

- [ ] **Step 2: Write a failing deploy-guard legacy cover test**

```python
def test_story_snapshot_recognizes_single_file_silly_song_cover():
    assert 'item.get("subtype") == "silly_song"' in SOURCE
    assert 'f"/covers/silly-songs/{item[\'cover_file\']}"' in SOURCE
```

- [ ] **Step 3: Run Task 2 tests and verify RED**

Run:

```bash
python -m pytest \
  scripts/test_silly_song_publication_contract.py \
  scripts/test_deploy_guard_regression_contracts.py::test_story_snapshot_recognizes_single_file_silly_song_cover -q
```

Expected: FAIL because the shared predicate and legacy cover fallback do not exist.

- [ ] **Step 4: Implement the shared completeness predicate**

```python
def is_complete_silly_song(item: dict) -> bool:
    return bool(item.get("audio_file") and item.get("cover_file"))
```

In `LocalStore._walk_per_content`, skip incomplete records only when `default_subtype == "silly_song"`. In `_load_all_songs`, filter with the same predicate before returning records. Do not unlink, move, or rewrite incomplete JSON.

- [ ] **Step 5: Add the deploy-guard legacy cover fallback**

```python
cover_url = item.get("cover", "")
if (
    not cover_url
    and item.get("subtype") == "silly_song"
    and item.get("cover_file")
):
    cover_url = f"/covers/silly-songs/{item['cover_file']}"
```

- [ ] **Step 6: Run Task 2 tests and verify GREEN**

Run:

```bash
python -m pytest \
  scripts/test_silly_song_publication_contract.py \
  scripts/test_deploy_guard_regression_contracts.py \
  scripts/test_character_local_store.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add \
  app/utils/content_completeness.py \
  app/services/local_store.py \
  app/api/v1/silly_songs.py \
  scripts/deploy_guard.py \
  scripts/test_silly_song_publication_contract.py \
  scripts/test_deploy_guard_regression_contracts.py
git commit -m "fix: hide incomplete silly song drafts"
```

### Task 3: Verification and Production Rollout

**Files:**
- No source files added.
- Production state: `/opt/dreamweaver-backend`

**Interfaces:**
- Consumes: committed Tasks 1–2.
- Produces: a deployed backend where incomplete drafts remain backed up but are absent from public catalogs.

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
python -m pytest \
  scripts/test_silly_song_diversity_rotation.py \
  scripts/test_silly_song_replicate_polling.py \
  scripts/test_silly_song_publication_contract.py \
  scripts/test_deploy_guard_regression_contracts.py \
  scripts/test_character_local_store.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Inspect the final diff**

Run:

```bash
git diff origin/main...HEAD --check
git diff --stat origin/main...HEAD
git status --short
```

Expected: no whitespace errors and only planned files changed.

- [ ] **Step 3: Push the implementation**

```bash
git push origin HEAD:main
```

Expected: remote `main` advances to the implementation commit.

- [ ] **Step 4: Capture a fresh deploy-guard snapshot**

Run on production:

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
```

Expected: snapshot succeeds before pulling the new code.

- [ ] **Step 5: Pull and hot-reload production**

Run on production:

```bash
cd /opt/dreamweaver-backend
git pull --ff-only origin main
curl -fsS -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(sed -n 's/^ADMIN_API_KEY=//p' .env | tail -1)"
```

Expected: reload succeeds and the public content count drops only by incomplete silly-song drafts.

- [ ] **Step 6: Verify production catalogs and assets**

Run on production:

```bash
python3 scripts/deploy_guard.py verify
python3 scripts/deploy_guard.py check
```

Expected: no missing silly-song audio or covers, legacy `cover_file` records are recognized, and all referenced URLs are reachable. Any unrelated external YouTube broadcast state is reported separately from content completeness.

- [ ] **Step 7: Confirm preserved drafts and archived recovery outputs**

Run on production:

```bash
test -f data/silly_songs/cake_tsunami_crash_6_8.json
test -f /opt/json-store/daily-recovery-20260731T1100/cake_tsunami_crash_6_8.json
test -d /opt/audio-store/_recovery-generated-20260731
test -d /opt/cover-store/_recovery-generated-20260731
```

Expected: all commands exit zero; no incomplete source or regenerated recovery artifact was deleted.
