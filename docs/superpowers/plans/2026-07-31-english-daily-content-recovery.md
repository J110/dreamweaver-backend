# English Daily Content Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make English short-story and silly-song generation resilient, then regenerate and publish the two missing items from 2026-07-31.

**Architecture:** Keep validators strict while adding bounded retries at the orchestration boundaries. Make the before-bed age explicit, accept complete silly-song renders from 50 through 100 seconds, and publish only the two missing content items under deploy-guard protection.

**Tech Stack:** Python 3, pytest, Mistral content generation, MiniMax Music via Replicate, GCP production VM, deploy guard.

## Global Constraints

- Silly-song duration is valid from 50 through 100 seconds, inclusive.
- Comprehensibility and diversity thresholds remain unchanged.
- Content generation gets at most three independent rounds.
- Production may gain exactly one English short story and one English 9–12 silly song.
- Stop on validator, audio, QA, cover, reload, or deploy-guard failure.

---

### Task 1: Silly-song audio contract

**Files:**
- Modify: `scripts/generate_silly_songs_battlecry.py`
- Test: `scripts/test_silly_song_diversity_rotation.py`

**Interfaces:**
- Consumes: `_run_minimax_prediction(style: str, lyrics: str) -> str` and `_download_replicate_output(audio_url: str) -> httpx.Response`
- Produces: `generate_audio_minimax(song: dict, force: bool = False) -> bool` with two attempts and a 50–100-second inclusive contract

- [ ] **Step 1: Write failing duration and retry tests**

Add tests that replace only the external prediction/download boundary, supply real temporary output paths, and install a minimal `pydub.AudioSegment` test double that returns durations of 50, 100, 49.9, and 100.1 seconds. Assert boundary renders succeed, invalid renders are deleted, and a 52.9-second first render succeeds without a second prediction. Add a separate test where the first prediction raises and the second produces a valid render; assert the function returns `True`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest -q \
  scripts/test_silly_song_diversity_rotation.py::test_minimax_accepts_flexible_duration_boundaries \
  scripts/test_silly_song_diversity_rotation.py::test_minimax_retries_one_failed_render
```

Expected: FAIL because 50-second renders are rejected and the current function performs one attempt.

- [ ] **Step 3: Implement the minimal audio change**

In `generate_audio_minimax`, use inclusive bounds:

```python
MIN_SILLY_SONG_SECONDS = 50
MAX_SILLY_SONG_SECONDS = 100
```

Wrap prediction, download, file validation, and duration validation in:

```python
for audio_attempt in range(1, 3):
    try:
        ...
        if not MIN_SILLY_SONG_SECONDS <= duration_s <= MAX_SILLY_SONG_SECONDS:
            ...
        return True
    except Exception as e:
        ...
return False
```

Keep the existing single-prediction polling behavior inside each attempt and delete invalid audio before retrying.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run:

```bash
python3 -m pytest -q scripts/test_silly_song_diversity_rotation.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_silly_songs_battlecry.py scripts/test_silly_song_diversity_rotation.py
git commit -m "fix: recover flexible silly-song renders"
```

### Task 2: Pipeline age and content retries

**Files:**
- Modify: `scripts/pipeline_run.py`
- Create: `scripts/test_pipeline_daily_recovery.py`

**Interfaces:**
- Consumes: `step_before_bed(args, state: dict) -> bool`, `step_generate(args, state: dict) -> bool`, `run_command(...)`
- Produces: before-bed silly-song commands containing `--age <selected-age>` and content generation with two bounded retry rounds

- [ ] **Step 1: Write the failing before-bed age test**

Patch `_pick_before_bed_age` to return `"9-12"`, `_pick_before_bed_mood` to return `"wired"`, and `run_command` to capture commands while returning successful representative output for all three before-bed generators. Assert the silly-song command contains:

```python
["--age", "9-12"]
```

- [ ] **Step 2: Write the failing content-retry test**

Use temporary `content.json` and `content_expanded.json` paths. Make the initial generation and first retry produce no ID, then make the second retry add one story ID. Assert `run_command` receives three content-generation calls total, `state["generated_ids"]` contains the recovered ID, and `state` has no `generation_warning`.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
python3 -m pytest -q scripts/test_pipeline_daily_recovery.py
```

Expected: the age assertion fails and the second-retry assertion reports only two generation calls.

- [ ] **Step 4: Implement the age propagation**

Build the silly-song command with the selected age:

```python
silly_cmd = [
    sys.executable,
    str(SCRIPTS_DIR / "generate_silly_songs_battlecry.py"),
    "--fresh",
    "--count",
    "1",
    "--age",
    age,
]
```

- [ ] **Step 5: Implement bounded content retries**

Replace the single retry block with a two-iteration loop. Before each retry, recalculate generated type counts from all `new_ids`, calculate only the remaining stories and poems, stop if nothing is missing, run the same Mistral command with mood, story type, age, and language propagation, and append only newly observed IDs.

- [ ] **Step 6: Run focused tests to verify GREEN**

Run:

```bash
python3 -m pytest -q scripts/test_pipeline_daily_recovery.py
```

Expected: all tests pass.

- [ ] **Step 7: Run pipeline regression tests**

Run:

```bash
python3 -m pytest -q \
  scripts/test_pipeline_daily_recovery.py \
  scripts/test_pipeline_lullaby_integration.py \
  scripts/test_silly_song_diversity_rotation.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/pipeline_run.py scripts/test_pipeline_daily_recovery.py
git commit -m "fix: retry missing English daily content"
```

### Task 3: Integrate and publish code

**Files:**
- Verify: all files committed by Tasks 1 and 2

**Interfaces:**
- Consumes: branch `fix/daily-content-recovery`
- Produces: tested commits on `origin/main`

- [ ] **Step 1: Verify branch state**

```bash
git status --short
git log --oneline origin/main..HEAD
```

Expected: clean worktree and the design plus two implementation commits.

- [ ] **Step 2: Run final local verification**

```bash
python3 -m pytest -q \
  scripts/test_pipeline_daily_recovery.py \
  scripts/test_pipeline_lullaby_integration.py \
  scripts/test_silly_song_diversity_rotation.py
```

Expected: all tests pass.

- [ ] **Step 3: Push the branch and fast-forward main**

```bash
git push origin HEAD:main
```

Expected: `main` advances to the verified implementation revision.

### Task 4: Regenerate and publish production content

**Files:**
- Production data: `/opt/dreamweaver-backend/data/stories/*.json`
- Production data: `/opt/dreamweaver-backend/data/silly_songs/*.json`
- Production assets: `/opt/dreamweaver-backend/public/audio/`
- Production assets: `/opt/dreamweaver-backend/public/covers/`

**Interfaces:**
- Consumes: production `main`, `deploy_guard.py`, pipeline step functions, admin reload
- Produces: one published English short story and one published English 9–12 silly song

- [ ] **Step 1: Snapshot production**

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
```

Expected: snapshot completes successfully before any mutation.

- [ ] **Step 2: Deploy pipeline scripts**

```bash
git pull --ff-only origin main
```

Expected: production advances to the verified revision with no local conflict.

- [ ] **Step 3: Regenerate the short story**

Run the generate step with all other content counts zero:

```bash
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py \
  --step generate --lang en --count-stories 1 --count-long-stories 0 \
  --count-poems 0 --count-lullabies 0
```

Expected: one new validator-clean English story ID in pipeline state.

- [ ] **Step 4: Complete the story assets**

Run the remaining content steps against the saved state:

```bash
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step audio
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step qa
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step enrich
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step mood
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step covers
```

Expected: audio, QA, enrichment, mood, and cover stages succeed for the new ID.

- [ ] **Step 5: Regenerate the missing silly song**

```bash
/usr/bin/python3 scripts/generate_silly_songs_battlecry.py \
  --fresh --count 1 --age 9-12 --mood wired
```

Expected: one published 9–12 song with 50–100-second audio and a cover.

- [ ] **Step 6: Sync and reload**

```bash
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step sync
TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --resume --step deploy_prod
```

Expected: assets copy to served paths and admin reload succeeds.

- [ ] **Step 7: Verify production**

```bash
python3 scripts/deploy_guard.py verify
python3 scripts/deploy_guard.py check
```

Expected: only the intended English story and English 9–12 silly song are added; no content loses audio or covers and all health checks pass.
