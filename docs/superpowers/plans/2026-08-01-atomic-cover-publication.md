# Atomic Cover Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent generated Hindi silly songs and poems from becoming visible without durable covers, and make Deploy Guard recover persistent covers without nested VM authentication.

**Architecture:** Generation fails before writing content JSON unless cover bytes have been saved to every required path and each file is non-empty. Production covers live in `/opt/cover-store`; Deploy Guard restores the subtype path from its root alias, or the root alias from its subtype path, using a local subprocess when already running on production.

**Tech Stack:** Python 3, pytest, FastAPI content records, nginx static media, Deploy Guard.

## Global Constraints

- Do not regenerate covers.
- Do not publish new silly-song or poem JSON when required cover creation or persistence fails.
- Treat `/opt/cover-store` as the production source of truth.
- Preserve all unrelated working-tree changes.
- Deploy Guard must hard-fail when a newly added canonical cover does not serve.

---

### Task 1: Fail-closed cover persistence

**Files:**
- Modify: `scripts/_hindi_generators.py`
- Create: `scripts/test_required_cover_publication.py`

**Interfaces:**
- Consumes: `_save_cover(png_bytes, *paths, size=(w, h))` and the existing silly-song/poem `cover_paths`.
- Produces: `_save_required_cover(png_bytes, paths, *, item_label, size=(1024, 1024)) -> None`.

- [ ] **Step 1: Write failing helper tests**

```python
def test_required_cover_rejects_missing_bytes(tmp_path):
    with pytest.raises(RuntimeError, match="cover generation failed"):
        gen._save_required_cover(None, [tmp_path / "cover.webp"], item_label="poem:test")


def test_required_cover_rejects_missing_output(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "_save_cover", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="cover persistence failed"):
        gen._save_required_cover(b"image", [tmp_path / "cover.webp"], item_label="song:test")


def test_required_cover_accepts_nonempty_output(monkeypatch, tmp_path):
    output = tmp_path / "cover.webp"
    monkeypatch.setattr(gen, "_save_cover", lambda *_args, **_kwargs: output.write_bytes(b"webp"))
    gen._save_required_cover(b"image", [output], item_label="song:test")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_required_cover_publication.py`

Expected: FAIL because `_save_required_cover` does not exist.

- [ ] **Step 3: Implement the required-cover gate**

```python
def _save_required_cover(
    png_bytes: bytes | None,
    paths: list[Path],
    *,
    item_label: str,
    size: tuple[int, int] = (1024, 1024),
) -> None:
    if not png_bytes:
        raise RuntimeError(f"{item_label}: cover generation failed; content not published")
    _save_cover(png_bytes, *paths, size=size)
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(
            f"{item_label}: cover persistence failed; content not published: {', '.join(missing)}"
        )
```

- [ ] **Step 4: Route silly-song and poem covers through the gate**

Build each `cover_paths` list unconditionally, append the production subtype and root-alias paths when `ON_PROD`, then call `_save_required_cover`. Set `cover` to `/covers/<id>.webp` without a default-cover branch only after the call succeeds.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `pytest -q scripts/test_required_cover_publication.py scripts/test_hi_id_collision.py scripts/test_hi_longstory_deadline.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/_hindi_generators.py scripts/test_required_cover_publication.py
git commit -m "fix: require covers before Hindi content publication"
```

### Task 2: Persistent cover recovery on production

**Files:**
- Modify: `scripts/deploy_guard.py`
- Create: `scripts/test_deploy_guard_cover_recovery.py`

**Interfaces:**
- Consumes: `ON_PROD_VM`, `COVER_STORE`, `auto_recover(recoverable, dry_run=False)`.
- Produces: `_run_production_command(command, *, timeout) -> subprocess.CompletedProcess` and `_cover_recovery_command(ftype, filename) -> str`.

- [ ] **Step 1: Write failing recovery tests**

```python
def test_poem_cover_recovery_uses_persistent_subtype_and_root_alias():
    command = guard._cover_recovery_command("poem_cover", "hi-sound-6-8-0851_cover.webp")
    assert "/opt/cover-store/poems/hi-sound-6-8-0851_cover.webp" in command
    assert "/opt/cover-store/hi-sound-6-8-0851.webp" in command


def test_silly_song_cover_recovery_uses_persistent_subtype_and_root_alias():
    command = guard._cover_recovery_command(
        "silly_song_cover", "hi-kaale_jute_ka_halla-6-8-1547_cover.webp"
    )
    assert "/opt/cover-store/silly-songs/hi-kaale_jute_ka_halla-6-8-1547_cover.webp" in command
    assert "/opt/cover-store/hi-kaale_jute_ka_halla-6-8-1547.webp" in command


def test_production_command_runs_locally_on_vm(monkeypatch):
    monkeypatch.setattr(guard, "ON_PROD_VM", True)
    calls = []
    monkeypatch.setattr(guard.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    guard._run_production_command("true", timeout=5)
    assert calls == [["bash", "-lc", "true"]]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q scripts/test_deploy_guard_cover_recovery.py`

Expected: FAIL because the recovery helpers do not exist.

- [ ] **Step 3: Implement local/remote command routing**

```python
def _run_production_command(command: str, *, timeout: int):
    argv = ["bash", "-lc", command] if ON_PROD_VM else SSH_CMD + [command]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
```

- [ ] **Step 4: Implement subtype/root-alias recovery**

For `silly_song_cover` and `poem_cover`, derive the root alias by replacing `_cover.webp` with `.webp`. The command must restore whichever of the persistent subtype or root files is missing from the other, and emit `RECOVERED` only after both non-empty files exist.

- [ ] **Step 5: Use the routing helper in cover recovery**

Replace the direct nested `subprocess.run(SSH_CMD + ...)` call in `auto_recover` with `_run_production_command`. Leave unrelated recovery behavior unchanged.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `pytest -q scripts/test_deploy_guard_cover_recovery.py scripts/test_deploy_guard_regression_contracts.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_guard.py scripts/test_deploy_guard_cover_recovery.py
git commit -m "fix: recover covers from persistent production storage"
```

### Task 3: Verification and deployment

**Files:**
- Verify: `scripts/_hindi_generators.py`
- Verify: `scripts/deploy_guard.py`
- Verify: `scripts/test_required_cover_publication.py`
- Verify: `scripts/test_deploy_guard_cover_recovery.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: deployed backend code and fresh Deploy Guard evidence.

- [ ] **Step 1: Run focused regression tests**

Run: `pytest -q scripts/test_required_cover_publication.py scripts/test_deploy_guard_cover_recovery.py scripts/test_deploy_guard_regression_contracts.py scripts/test_silly_song_publication_contract.py`

Expected: PASS.

- [ ] **Step 2: Run source validation**

Run: `python3 -m py_compile scripts/_hindi_generators.py scripts/deploy_guard.py`

Expected: exit 0.

- [ ] **Step 3: Push the feature commit and deploy the backend using the established guarded release flow**

Deploy only the tested commits. Preserve `/opt/cover-store`, `/opt/audio-store`, `/opt/json-store`, and production per-content data.

- [ ] **Step 4: Run Deploy Guard on production**

Run: `cd /opt/dreamweaver-backend && python3 scripts/deploy_guard.py verify`

Expected for this scope: zero missing canonical covers and no nested-gcloud authentication error during cover recovery.

- [ ] **Step 5: Verify the restored cover URLs remain healthy**

Run HEAD checks for the two restored silly-song and poem subtype URLs and their root aliases.

Expected: four `200 image/webp` responses.
