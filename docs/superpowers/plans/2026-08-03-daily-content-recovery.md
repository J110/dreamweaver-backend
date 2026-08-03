# Daily Content Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably generate Hindi funny shorts, restore the failed English silly-song cover, and make deploy guard preserve and recover the complete pre-deploy content baseline.

**Architecture:** Add validator-aware retries to the Hindi funny-short generator, make deploy-guard state retain canonical silly-song cover metadata and reject absent asset URLs, and replace the English pipeline's lightweight diff with the complete guard verification command. Apply code through a clean isolated worktree, then perform targeted production repair inside a snapshot/verify transaction.

**Tech Stack:** Python 3.10, pytest, FastAPI content APIs, subprocess-based pipeline orchestration, GCP Compute Engine, nginx static assets.

## Global Constraints

- Preserve all existing content IDs, text, audio, titles, and creation timestamps.
- Deploy guard may restore or recreate assets for an existing baseline record but may not generate replacement content or change an ID.
- A missing audio or cover URL is a blocking verification failure.
- Never loosen Hindi funny-short validator thresholds.
- Run `deploy_guard.py snapshot` before every production mutation and `deploy_guard.py verify` afterward.
- Do not include unrelated dirty-worktree changes in commits or deployment.

---

### Task 1: Validator-aware Hindi funny-short retries

**Files:**
- Modify: `scripts/_funny_shorts_common.py`
- Modify: `scripts/generate_funny_shorts_hi.py`
- Test: `scripts/test_funny_shorts_validator.py`

**Interfaces:**
- Consumes: rejected candidate dictionaries and `list[str]` results from `validate_funny_short`.
- Produces: `build_validator_retry_prompt(base_prompt: str, candidate: dict, errors: list[str]) -> str`.

- [ ] **Step 1: Write the failing retry-prompt tests**

Add tests that prove the correction prompt includes the original generation contract, exact validator errors, rejected JSON, and an explicit instruction to return a complete corrected object:

```python
from _funny_shorts_common import build_validator_retry_prompt


def test_validator_retry_prompt_includes_candidate_and_exact_errors():
    candidate = {"title": "Test", "inputs": [{"voice": "A", "text": "Bahut lambi line"}]}
    errors = ["Line 0: too many words", "Line 0: missing Devanagari in 'text_deva' (TTS engine input)"]

    prompt = build_validator_retry_prompt("BASE CONTRACT", candidate, errors)

    assert "BASE CONTRACT" in prompt
    assert "Line 0: too many words" in prompt
    assert "missing Devanagari" in prompt
    assert '"title": "Test"' in prompt
    assert "complete corrected JSON object" in prompt


def test_validator_retry_prompt_does_not_relax_validator_limits():
    prompt = build_validator_retry_prompt("HI hard ceiling: 800", {}, ["Too long: 801 chars"])
    assert "HI hard ceiling: 800" in prompt
    assert "Do not remove or relax any requirement" in prompt
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_funny_shorts_validator.py -k validator_retry_prompt -v
```

Expected: collection fails because `build_validator_retry_prompt` does not exist.

- [ ] **Step 3: Implement the minimal prompt builder**

Add a pure helper to `_funny_shorts_common.py`:

```python
def build_validator_retry_prompt(base_prompt: str, candidate: dict, errors: list[str]) -> str:
    error_lines = "\n".join(f"- {error}" for error in errors)
    rejected = json.dumps(candidate, ensure_ascii=False, indent=2)
    return (
        f"{base_prompt}\n\n"
        "The previous candidate failed the validator. Correct that candidate using the exact failures below.\n"
        f"{error_lines}\n\n"
        "Rejected candidate:\n"
        f"{rejected}\n\n"
        "Return one complete corrected JSON object. Do not remove or relax any requirement."
    )
```

Import the helper in `generate_funny_shorts_hi.py`. Initialize `attempt_prompt = prompt`, call `request_mistral_script(attempt_prompt)`, and after any unrepaired validation failure set:

```python
attempt_prompt = build_validator_retry_prompt(prompt, candidate, last_errors)
```

Correct the terminal message to report five attempts.

- [ ] **Step 4: Run the focused validator suite and confirm GREEN**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_funny_shorts_validator.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the Hindi retry change**

```bash
git add scripts/_funny_shorts_common.py scripts/generate_funny_shorts_hi.py scripts/test_funny_shorts_validator.py
git commit -m "fix: feed validator errors into Hindi funny short retries"
```

### Task 2: Baseline cover preservation and missing-URL detection

**Files:**
- Modify: `scripts/deploy_guard.py`
- Test: `scripts/test_deploy_guard_content_recovery.py`

**Interfaces:**
- Consumes: silly-song API records containing `cover`, `cover_file`, or neither.
- Produces: snapshot entries with `cover_url: str` and `has_cover: bool`; verification issue lists for lost or absent covers.

- [ ] **Step 1: Write failing deploy-guard regression tests**

Create focused tests using a fake HTTP client response and direct helper calls:

```python
def test_silly_snapshot_prefers_persisted_cover_url(monkeypatch):
    item = {"id": "song-1", "title": "Song", "audio_file": "song-1.mp3", "cover": "/covers/song-1.svg"}
    state = capture_state_with_items(monkeypatch, [item])
    saved = state["silly_songs"]["2-5"]["song-1"]
    assert saved["cover_url"] == "/covers/song-1.svg"
    assert saved["has_cover"] is True


def test_silly_snapshot_reconstructs_cover_from_cover_file(monkeypatch):
    item = {"id": "song-1", "audio_file": "song-1.mp3", "cover_file": "song-1.webp"}
    state = capture_state_with_items(monkeypatch, [item])
    assert state["silly_songs"]["2-5"]["song-1"]["cover_url"] == "/covers/silly-songs/song-1.webp"


def test_diff_reports_existing_silly_song_lost_cover():
    before = silly_state("song-1", has_cover=True, cover_url="/covers/song-1.svg")
    after = silly_state("song-1", has_cover=False, cover_url="")
    assert any("LOST COVER" in issue for issue in diff_states(before, after)["degraded"])


def test_new_item_without_cover_url_is_rejected():
    issues = verify_new_items_serving(
        [{"category": "silly_song", "item_id": "song-1", "age_group": "2-5", "audio_url": "/audio/song-1.mp3", "cover_url": ""}],
        "https://frontend.invalid",
        "https://api.invalid",
    )
    assert any("no cover URL" in issue for issue in issues)
```

The test file may define small `FakeClient`, `capture_state_with_items`, and `silly_state` helpers entirely inside the test module.

- [ ] **Step 2: Run the focused deploy-guard tests and confirm RED**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_deploy_guard_content_recovery.py -v
```

Expected: failures show persisted `cover` is discarded, `has_cover` is absent, lost covers are not degraded, and empty new cover URLs are accepted.

- [ ] **Step 3: Implement canonical cover capture and degradation checks**

In `capture_state`, compute each silly-song cover as:

```python
cover_url = item.get("cover") or (
    f"/covers/silly-songs/{item['cover_file']}" if item.get("cover_file") else ""
)
```

Store both `cover_url` and `has_cover = bool(cover_url and cover_url != "/covers/default.svg")`. In `diff_states`, append `LOST COVER silly song` when the baseline had a cover and the post-deploy state does not. In `verify_new_items_serving`, append a `no cover URL` issue when the field is empty.

- [ ] **Step 4: Run deploy-guard tests and confirm GREEN**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_deploy_guard_content_recovery.py scripts/test_deploy_guard_regression_contracts.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit baseline cover preservation**

```bash
git add scripts/deploy_guard.py scripts/test_deploy_guard_content_recovery.py
git commit -m "fix: preserve silly song covers in deploy guard baseline"
```

### Task 3: Full English pipeline guard verification

**Files:**
- Modify: `scripts/pipeline_run.py`
- Test: `scripts/test_pipeline_deploy_guard.py`

**Interfaces:**
- Consumes: the pre-deploy state captured by `_deploy_guard_snapshot()` and the post-reload production state.
- Produces: `_deploy_guard_verify(before: dict | None) -> bool`, returning false when full verification fails.

- [ ] **Step 1: Write failing English guard tests**

Use dependency injection through monkeypatching to prove verification runs asset checks, attempts recovery, rechecks, and returns false when a missing asset remains:

```python
def test_deploy_guard_verify_recovers_then_rechecks(monkeypatch):
    states = iter([{"phase": "after"}, {"phase": "rechecked"}])
    monkeypatch.setattr(deploy_guard, "capture_state", lambda _api: next(states))
    monkeypatch.setattr(deploy_guard, "diff_states", lambda _before, _after: empty_changes())
    checks = iter([(["missing"], [{"type": "silly_song_cover", "filename": "song.webp", "url_path": "/covers/song.webp"}]), ([], [])])
    monkeypatch.setattr(deploy_guard, "verify_files", lambda *_args: next(checks))
    monkeypatch.setattr(deploy_guard, "auto_recover", lambda _items: (1, 0))
    assert pipeline_run._deploy_guard_verify({"phase": "before"}) is True


def test_deploy_guard_verify_fails_when_recheck_still_missing(monkeypatch):
    monkeypatch.setattr(deploy_guard, "capture_state", lambda _api: {"phase": "after"})
    monkeypatch.setattr(deploy_guard, "diff_states", lambda _before, _after: empty_changes())
    monkeypatch.setattr(deploy_guard, "verify_files", lambda *_args: (["missing"], []))
    assert pipeline_run._deploy_guard_verify({"phase": "before"}) is False
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_pipeline_deploy_guard.py -v
```

Expected: current `_deploy_guard_verify` returns `None` and never invokes file verification or recovery.

- [ ] **Step 3: Implement complete in-process verification**

Import the deploy-guard module rather than only two functions. Verify removed/degraded baseline items, verify all added items have reachable audio and covers, run `verify_files`, call `auto_recover` for recoverable assets, and perform an authoritative second `capture_state` plus `verify_files` check. Return `True` only when no unresolved issue remains.

In `step_deploy_prod`, set `step_deploy_prod` to failed when backend reload succeeds but `_deploy_guard_verify` returns false. Do not report the deployment complete after an unresolved guard failure.

- [ ] **Step 4: Run focused pipeline and guard suites and confirm GREEN**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_pipeline_deploy_guard.py scripts/test_deploy_guard_content_recovery.py scripts/test_pipeline_cover_status.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit full English verification**

```bash
git add scripts/pipeline_run.py scripts/test_pipeline_deploy_guard.py
git commit -m "fix: enforce full deploy guard in English pipeline"
```

### Task 4: Deploy code and repair production content

**Files:**
- Modify on production: `data/silly_songs/why_does_broccoli_stare_2_5.json`
- Create on production: `public/covers/silly-songs/why_does_broccoli_stare_2_5.webp`
- Create on production: one new `data/funny_shorts_hi/hi-fs-*.json`
- Create on production: matching Hindi funny-short audio and cover assets

**Interfaces:**
- Consumes: committed generator and guard fixes, existing English silly-song JSON, production environment credentials.
- Produces: one published 2026-08-03 Hindi funny short, one canonical English WebP cover, and a clean post-deploy guard verdict.

- [ ] **Step 1: Verify the local implementation before publication**

Run:

```bash
.venv-test/bin/python -m pytest scripts/test_funny_shorts_validator.py scripts/test_deploy_guard_content_recovery.py scripts/test_pipeline_deploy_guard.py scripts/test_pipeline_cover_status.py scripts/test_deploy_guard_regression_contracts.py -v
```

Expected: all focused tests pass with no warnings or errors.

- [ ] **Step 2: Push the implementation branch and update production code**

Push the reviewed commits, then on `dreamvalley-prod` fetch and fast-forward the deployed branch. Stop if production has overlapping tracked modifications in any changed script.

- [ ] **Step 3: Capture the production baseline**

Run on production:

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
```

Expected: snapshot exits zero and records the current live IDs and assets.

- [ ] **Step 4: Regenerate the English silly-song cover**

Run:

```bash
python3 scripts/generate_silly_song_covers.py --song why_does_broccoli_stare_2_5 --force
```

Confirm the JSON contains:

```json
{
  "cover_file": "why_does_broccoli_stare_2_5.webp",
  "cover": "/covers/silly-songs/why_does_broccoli_stare_2_5.webp"
}
```

Confirm the WebP exists in the canonical cover output and persistent cover store before reload.

- [ ] **Step 5: Generate only the missing Hindi funny short**

Run:

```bash
python3 scripts/pipeline_run_hi.py --types funny_short
```

Expected: one new `hi-fs-*` record is created with audio, custom cover, and `created_at` on 2026-08-03; no other content type is generated.

- [ ] **Step 6: Reload and verify user-facing assets**

Call the authenticated admin reload endpoint, then require HTTP 200 for the English WebP, Hindi funny-short audio, and Hindi funny-short cover. Confirm both records appear through their live API surfaces.

- [ ] **Step 7: Run deploy guard and confirm the baseline is preserved**

Run:

```bash
python3 scripts/deploy_guard.py verify
```

Expected: all baseline IDs remain present, all referenced assets are reachable, recovery has no unresolved failures, and the command exits zero.

- [ ] **Step 8: Record final production evidence**

Capture the new Hindi ID, English cover URL, HTTP statuses, focused test count, deployed commit, and deploy-guard exit status in the task handoff.
