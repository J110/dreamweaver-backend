# Pipeline Cover Failure Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the three broken 2026-08-02 covers and make both daily pipelines report cover failures truthfully.

**Architecture:** Add a focused English lullaby finalizer that chooses and persists the generated or placeholder cover path while updating pipeline state. Preserve each Hindi generator's returned cover path in its result and derive cover success from that path. Repair production from existing per-content records under deploy-guard protection.

**Tech Stack:** Python 3, pytest, FastAPI content reload, Pollinations FLUX, nginx cover store, GCP SSH.

## Global Constraints

- Do not change content text, audio, IDs, titles, descriptions, or creation timestamps.
- Cover generation failures remain non-fatal for otherwise valid content.
- English placeholders must resolve at `/covers/lullabies/{id}_cover.svg`.
- Hindi empty or `/covers/default.svg` values must be reported as cover failures.
- Capture a deploy-guard snapshot before production mutation and verify afterward.

---

### Task 1: English lullaby fallback and reporting

**Files:**
- Modify: `scripts/pipeline_run.py:1480-1645`
- Create: `scripts/test_pipeline_cover_status.py`

**Interfaces:**
- Consumes: lullaby entry `dict`, pipeline state `dict`, FLUX success `bool`, per-content writer callable.
- Produces: `_finalize_lullaby_cover(entry, state, cover_ok, writer) -> str`.

- [ ] **Step 1: Write the failing English regression tests**

```python
def test_failed_english_lullaby_cover_persists_placeholder_and_failure_state():
    entry = {"id": "permission-test", "cover": "/covers/permission-test.svg"}
    state = {"covers_generated": [], "covers_flux": [], "covers_failed": []}
    written = []

    path = pipeline_run._finalize_lullaby_cover(entry, state, False, written.append)

    assert path == "/covers/lullabies/permission-test_cover.svg"
    assert entry["cover"] == path
    assert written == [entry]
    assert state["covers_failed"] == ["permission-test"]
    assert state["covers_generated"] == []


def test_successful_english_lullaby_cover_persists_flux_path_and_success_state():
    entry = {"id": "permission-test", "cover": "/covers/permission-test.svg"}
    state = {"covers_generated": [], "covers_flux": [], "covers_failed": []}
    written = []

    path = pipeline_run._finalize_lullaby_cover(entry, state, True, written.append)

    assert path == "/covers/permission-test.svg"
    assert written == [entry]
    assert state["covers_generated"] == ["permission-test"]
    assert state["covers_flux"] == ["permission-test"]
    assert state["covers_failed"] == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q scripts/test_pipeline_cover_status.py -k english`

Expected: FAIL because `_finalize_lullaby_cover` does not exist.

- [ ] **Step 3: Implement the English finalizer and call it after FLUX**

```python
def _append_unique(state: dict, key: str, value: str) -> None:
    values = state.setdefault(key, [])
    if value not in values:
        values.append(value)


def _finalize_lullaby_cover(entry, state, cover_ok, writer=_write_per_content_file):
    lid = entry["id"]
    if cover_ok:
        path = f"/covers/{lid}.svg"
        _append_unique(state, "covers_generated", lid)
        _append_unique(state, "covers_flux", lid)
    else:
        path = f"/covers/lullabies/{lid}_cover.svg"
        _append_unique(state, "covers_failed", lid)
    entry["cover"] = path
    writer(entry)
    return path
```

Call `_finalize_lullaby_cover(entry, state, cover_ok)` before deleting the temporary JSON and before writing `content.json`.

- [ ] **Step 4: Run the English tests and verify GREEN**

Run: `pytest -q scripts/test_pipeline_cover_status.py -k english`

Expected: 2 passed.

- [ ] **Step 5: Commit the English fix**

```bash
git add scripts/pipeline_run.py scripts/test_pipeline_cover_status.py
git commit -m "fix: persist English lullaby cover fallback"
```

---

### Task 2: Hindi cover-result accounting

**Files:**
- Modify: `scripts/pipeline_run_hi.py:82-138,225-250`
- Modify: `scripts/test_pipeline_cover_status.py`

**Interfaces:**
- Consumes: Hindi generation result records containing `id`, `title`, `status`, and `cover`.
- Produces: `_build_state(results, elapsed)` with accurate generated and failed cover collections.

- [ ] **Step 1: Write the failing Hindi regression test**

```python
def test_hindi_state_reports_default_and_empty_covers_as_failed():
    results = {
        "lullaby": {"status": "ok", "type": "lullaby", "id": "hi-good", "title": "Good", "cover": "/covers/hi-good.webp"},
        "silly_song": {"status": "ok", "type": "silly_song", "id": "hi-default", "title": "Default", "cover": "/covers/default.svg"},
        "short_story": {"status": "ok", "type": "short_story", "id": "hi-empty", "title": "Empty", "cover": ""},
    }

    state = pipeline_run_hi._build_state(results, 1.0)

    assert state["covers_generated"] == ["hi-good"]
    assert state["covers_flux"] == ["hi-good"]
    assert state["covers_failed"] == ["hi-default", "hi-empty"]
    assert "covers failed: hi-default, hi-empty" in state["generation_warning"]
```

- [ ] **Step 2: Run the Hindi test and verify RED**

Run: `pytest -q scripts/test_pipeline_cover_status.py -k hindi`

Expected: FAIL because all successful content is currently classified as a generated cover.

- [ ] **Step 3: Preserve cover paths and classify them in `_build_state`**

Add `"cover": entry.get("cover", "")` to each successful result. In `_build_state`, classify successful results with a non-empty, non-default cover as generated; classify the remainder as failed. Append `covers failed: <ids>` to `generation_warning` without changing content success status.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `pytest -q scripts/test_pipeline_cover_status.py`

Expected: 3 passed.

- [ ] **Step 5: Commit the Hindi fix**

```bash
git add scripts/pipeline_run_hi.py scripts/test_pipeline_cover_status.py
git commit -m "fix: report Hindi cover failures"
```

---

### Task 3: Repair the three production records

**Files:**
- Modify: `/opt/dreamweaver-backend/data/lullabies/permission-6-8-a0be.json`
- Modify: `/opt/dreamweaver-backend/data/silly_songs_hi/hi-chidiya_ka_par_tyohaar-2-5-eb23.json`
- Modify: `/opt/dreamweaver-backend/data/stories_hi/hi-neeti_katha-2-5-tota-05a0aec0.json`
- Create: `/opt/cover-store/hi-chidiya_ka_par_tyohaar-2-5-eb23.svg`
- Create: `/opt/cover-store/hi-neeti_katha-2-5-tota-05a0aec0.svg`

**Interfaces:**
- Consumes: existing per-content JSON and `cover_context` fields.
- Produces: three live non-default cover URLs returning HTTP 200.

- [ ] **Step 1: Capture the production baseline**

Run on production: `cd /opt/dreamweaver-backend && python3 scripts/deploy_guard.py snapshot`.

Expected: baseline saved.

- [ ] **Step 2: Validate target records before mutation**

Read the three per-content files and confirm IDs, creation timestamps, and non-empty `cover_context` fields. Stop if any target differs.

- [ ] **Step 3: Generate the two Hindi SVG covers**

```bash
COVER_OUTPUT_DIR=/opt/cover-store python3 scripts/generate_cover_experimental.py --story-json data/silly_songs_hi/hi-chidiya_ka_par_tyohaar-2-5-eb23.json
COVER_OUTPUT_DIR=/opt/cover-store python3 scripts/generate_cover_experimental.py --story-json data/stories_hi/hi-neeti_katha-2-5-tota-05a0aec0.json
```

Expected: both commands exit 0, both per-content records reference `/covers/{id}.svg`, and both files exist under `/opt/cover-store`.

- [ ] **Step 4: Persist the English placeholder path**

Use `_per_content_io.update_per_content_fields` to set `permission-6-8-a0be` to `/covers/lullabies/permission-6-8-a0be_cover.svg`. Confirm that placeholder file exists in `/opt/cover-store/lullabies` before changing metadata.

- [ ] **Step 5: Reload production content**

Source `/opt/dreamweaver-backend/.env` and call `POST /api/v1/admin/reload` with `X-Admin-Key`.

Expected: reload succeeds without changing content count except derived snapshot rebuilding.

---

### Task 4: Deploy and verify

**Files:**
- Deploy: `scripts/pipeline_run.py`
- Deploy: `scripts/pipeline_run_hi.py`
- Deploy: `scripts/test_pipeline_cover_status.py`

**Interfaces:**
- Consumes: committed local pipeline fixes and repaired production data.
- Produces: truthful future pipeline notifications and verified live covers.

- [ ] **Step 1: Run focused local verification**

Run: `pytest -q scripts/test_pipeline_cover_status.py`

Expected: 3 passed with no warnings.

- [ ] **Step 2: Push the committed changes and fast-forward production**

Push the current branch to its configured upstream. On production, confirm the checkout can fast-forward cleanly, then run `git pull --ff-only`.

- [ ] **Step 3: Verify all affected live URLs**

```text
https://dreamvalley.app/covers/lullabies/permission-6-8-a0be_cover.svg
https://dreamvalley.app/covers/hi-chidiya_ka_par_tyohaar-2-5-eb23.svg
https://dreamvalley.app/covers/hi-neeti_katha-2-5-tota-05a0aec0.svg
```

Expected: HTTP 200 for all three, and the live API returns the same paths.

- [ ] **Step 4: Run production deploy-guard verification**

Run on production: `cd /opt/dreamweaver-backend && python3 scripts/deploy_guard.py verify`.

Expected: no new cover, content-count, audio, or invariant violations.
