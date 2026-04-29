# Follow-ups

Consolidated technical follow-ups from the 2026-04-29 incident session. Grouped by category, ordered by leverage within each.

---

## Architecture (highest leverage)

These remove root causes that produced multiple incidents tonight. Worth prioritizing because they eliminate whole classes of bugs rather than patching individual symptoms.

### `data/content.json` refactor — treat as derived artifact

**The problem:** `data/content.json` is a 6000+ line master mirror that every generator has to remember to update via an `_auto_mirror`-style helper. When a generator forgets (silly_songs, musical poems, hi-fs-2956 partial-failure path), items go orphan despite generated assets existing. Tonight's session rescued 3 such orphans manually. Probably more in history we haven't audited.

**Proposed shape:**
- Each item gets persisted to `data/<type>/<id>.json` (already happening for most types)
- `seed_output/content.json` is gitignored and rebuilt at backend startup by walking `data/<type>/` directories
- Admin-reload triggers a rebuild + LocalStore reload
- Removes the upsert-into-master-mirror step entirely; orphan files become impossible by construction

**Estimate:** Half-day session. Touches LocalStore boot, `_auto_mirror` callsites (which can be deleted), and deploy_guard's content-source assumptions.

### Walker minting `lang` from `default_language` — document explicit minting case

When a source `content.json` entry has neither a `lang` nor a `language` field, the walker mints `lang` from the directory's `default_language` (e.g., `data/stories/` → `lang=en`). This is **correct behavior** — directory placement is canonical (OQ3, §2c) — but it's an explicit *minting* case rather than a *normalization* case (which only fires when the source field already exists).

Worth documenting in the walker pseudocode comments inside `app/services/local_store.py` so a future reader doesn't read the tightened walker (Option C, "preserve source field-set") and assume `lang` would be missing for items whose source had no `lang`. The two cases coexist:

- **Normalize**: source has `lang` (or `language`) → walker overrides with directory-derived value.
- **Mint**: source has neither → walker adds the directory-derived value.

Surfaced during PR #2 HI bucket migration audit (2026-04-29). Five-minute doc-comment edit; not a code change.

### `seedData.js` migration — backend serves it via API

**The problem:** `dreamweaver-web/src/utils/seedData.js` is the frontend's seed manifest, regenerated daily by the pipeline's `sync_seed_data.py`. Tonight we removed `public/covers/` from git via `SKIP_PUBLISH_STEP=1`, but `seedData.js` is still in `src/utils/` so it's the last reason the pipeline would ever want to commit on prod. Nothing to do for tonight (cron skips publish entirely now), but the data file is still authored alongside JS code, which is the wrong shape.

**Proposed shape:**
- Backend serves a `/api/v1/seed-manifest` endpoint that returns the same data
- Frontend fetches at startup, hydrates the same in-memory store that currently imports `seedData.js`
- `src/utils/seedData.js` deleted from frontend repo

**Estimate:** Half-day. Frontend bootstrap change + a small backend endpoint + delete the file.

### Migrate `view_count` to a proper analytics path

**The problem:** `view_count` on content documents is currently the hottest write path — incremented on every `GET /content/{id}` and persisting via the full content.json snapshot flush. The 2026-04-29 content.json refactor (§2g.2) makes the LocalStore write a no-op as a stopgap; the in-memory increment still runs but doesn't survive process restart. Net effect: per-process ephemeral view counts. Fine for a few days, not a long-term answer.

**Proposed shape:**
- View tracking moves to a proper counter store. Three options worth weighing:
  - **Rollup from `data/analytics.db`** — session-event records likely already log content plays / views. A nightly aggregation job updates a `content_views` table; the API reads from there. Zero new infra; small SQL.
  - **Redis counter** — INCR on a `views:{content_id}` key per request, periodically flushed to durable storage. Lowest latency, but requires running Redis (new dependency on the prod VM).
  - **SQLite WAL counter** — a dedicated lightweight `views.db` with a single-table schema. INCR via `UPDATE ... RETURNING`. No new dependency; sufficient throughput for this app's traffic.
- The API response shape stays the same; the read source changes.

**Estimate:** Half-day. Smaller if the rollup option is taken (the analytics DB likely already has the events).

---

## deploy_guard improvements (close behind — prevents future incidents)

deploy_guard had **multiple blind spots** during tonight's session. Each item below maps to an incident it would have caught.

### Orphan-file scan

Cross-reference `data/<type>/*.json` files against `seed_output/content.json` and report files present on disk but not registered. Today's silly_song (`cat_talk_2_5`) and musical poem (`question_9_12_92a6`) orphans would have been caught on day 1 instead of day 9. So would `hi-fs-2956`.

```python
# Sketch:
for type_dir in ["silly_songs", "poems", "funny_shorts", "lullabies"]:
    on_disk = {p.stem for p in (DATA_DIR / type_dir).glob("*.json")}
    in_mirror = {item["id"] for item in content_json if matches_type(item, type_dir)}
    orphans = on_disk - in_mirror
    for orphan in orphans:
        report_warning(f"orphan: data/{type_dir}/{orphan}.json not in content.json")
```

### Expected-vs-delivered check

Pipeline logs `Generated: 6 items` but deploy_guard only validates *registered* items (whatever the upsert step put in content.json). Tonight: pipeline reported `Generated: 6 items` from this manual run, but only 4 made it live until rescue. Add a check:

- Pipeline writes its intended-generation count to a file (or state object) at start
- After deploy, compare expected vs delivered; non-zero diff = fail loud

### Cron output surfacing

Both EN and HI crons currently swallow `deploy_guard verify` output:
- EN cron pipes everything through `>> /opt/dreamweaver-backend/logs/cron.log 2>&1` so output IS captured, but the `step_deploy_prod` block calls `_deploy_guard_verify(snapshot)` which logs only a one-line summary
- HI cron's `pipeline_run_hi.py:244` does `subprocess.run(... capture_output=True ...)` then prints `"✓ verify completed"` regardless of what verify said

Either:
- Pipe verify's full output to the run-specific log file, OR
- Have deploy_guard exit non-zero on violations so the orchestrator's `check=False` becomes `check=True` (or at least logs the failure prominently)

The current behavior is "silently green when actually red".

### Subtype-aware classification

deploy_guard's STORIES section reports `cat_talk_2_5` as a story (it's actually a silly_song with `type=song, subtype=silly_song`). The classifier reads top-level `type` without checking `subtype`. Fix: cross-reference `subtype`/`story_type` fields, mirror the same predicates the frontend uses (`isSillySong`, `isFunnyShort`, etc. — see `dreamweaver-web/src/utils/contentTypes.js`).

### Snapshot-vs-current bug for new-item check

Tonight's verify reported `❌ NEW story: cat_talk_2_5 — no audio URL` despite the seed entry having `audio_url: "/audio/silly-songs/cat_talk_2_5.mp3"` and the URL returning 200. Possible cause: the new-item-serving check reads from the snapshot blob (which might be from before the rescue), not from the live API/current seed. Investigation needed.

---

## Code defaults / cleanup (smaller, opportunistic)

Quick wins. None of these are urgent but each removes a small footgun.

### Flip `TTS_ENGINE_EN` default `chatterbox` → `elevenlabs`

Production runs ElevenLabs via the cron's inline env var. Manual invocations that forget the env var silently regress to Chatterbox. Per CLAUDE.md "Known Production Drift" — flip the code default so production reality matches dev defaults.

### Cover-output pattern unification

Two patterns coexist:
- HI generators: `PROD_COVER_STORE = Path("/opt/cover-store")` + `ON_PROD` guard, hardcoded path
- EN generators: `COVER_OUTPUT_DIR` env var via `scripts/_paths.py`, defaults to `BASE_DIR/public/covers`

Both work but they're inconsistent. Unify on the env-var pattern (the EN approach) — touch `_hindi_generators.py:_save_cover` calls to read from `_paths.COVER_OUTPUT_DIR` instead of `PROD_COVER_STORE`.

### Localhost vs public URL admin reload

- EN (`pipeline_run.py`): `POST http://localhost:8000/api/v1/admin/reload` — direct to container, fast, no nginx/DNS dependency
- HI (`pipeline_run_hi.py:_admin_reload`): `POST https://api.dreamvalley.app/api/v1/admin/reload` — through nginx, depends on TLS + DNS being healthy

EN's pattern is more robust. Switch HI to localhost for symmetry. No history of HI failures from this, but reduces failure surface for future cron runs.

### `silly-songs/` vs `silly_songs/` consolidation

`public/covers/` has both. Hyphen is canonical (per CLAUDE.md "Known Production Drift"). Migrate the underscore variant's contents to hyphen, delete the underscore dir, audit any code references.

### Backend `public/covers/` duplicate cleanup

`/opt/dreamweaver-backend/public/covers/` exists as an unnecessary duplicate. Not in nginx alias chain (after tonight's flip nginx serves from `/opt/cover-store/`). Not load-bearing. Delete after verifying no scripts read from this path.

### Stale TTS log message

`generate_long_story_episode.py` logs `"Generating TTS via Chatterbox..."` even when ElevenLabs is the active engine. Cosmetic; update the log line to read from the active engine.

### Document the two `/audio/` nginx blocks

`/etc/nginx/sites-enabled/dreamvalley` has two `location /audio/` blocks — one inside `api.dreamvalley.app`'s server block (aliases `/opt/audio-store/`), one inside `dreamvalley.app`'s server block (aliases `/opt/dreamweaver-web/public/audio/`). Confirmed intentional during tonight's audit. Add a note in `CLAUDE.md` "Production Path Routing" so it doesn't get flagged as a config bug next time.

---

## Content-level items

### silly_song lyrics body length

`generate_silly_songs_battlecry.py`'s validator caps lyrics body at 500 chars. Mistral keeps producing 500–550 char bodies; tonight's HI silly_song failed 3 attempts in a row (`'lyrics body too long: 535 chars (max 500)'`). Either:
- Raise cap to 600 (and update the validator + test on 5+ samples to ensure quality holds)
- Tighten the system prompt's brevity guidance and re-test

Per CLAUDE.md "On non-empty error list: regenerate (up to 3 attempts), then route to QA critic if Hindi short story, else surface failure" — silly_song has no QA critic, so 3 failures is the end. Worth a tuning pass.

### poems-hi/hi-nonsense-9-12-dfcd.mp3 404

nginx error log shows repeated HEAD requests for this audio file failing with `(2: No such file or directory)` against `/opt/dreamweaver-web/public/audio/poems-hi/hi-nonsense-9-12-dfcd.mp3`. Pre-existing — the HI poem from Apr 27. Single-file recovery: copy from `/opt/audio-store/poems-hi/` (where it does exist) or regenerate.

### Tali (`gen-b70846bfc0eb`) golden baseline noise

deploy_guard flags `❌ REMOVED story: gen-b70846bfc0eb — "Tali and Moss and the Lighthouse"` on every verify. Story isn't in any branch's `seed_output/content.json` and has no recoverable source. Decide:
- Regenerate from scratch (real API costs)
- Strike from `data/deploy_golden.json` (one-line edit, baseline acknowledges it's gone)

### ~~Historical orphan backfill~~ (RESOLVED 2026-04-29 cutover)

~~After tonight's `_auto_mirror` fix, future orphans are prevented at source. But there are still historical orphans on disk: ...~~

**Resolved 2026-04-29:** during the per-content-file cutover, `scripts/backfill_per_content.py` quarantined 66 historical orphans (38 silly_songs + 28 poems). All 66 were verified via HEAD checks (audio + cover serving 200) and published via `scripts/triage_quarantine.py --publish-all --confirm`. Items now appear in `seed_output/content.json` and the canonical buckets. The HI funny_shorts mentioned in the original list (hi-fs-*) were also resolved separately during step 5b. Future orphans are now structurally impossible (per-content files are the source of truth, content.json is derived).

---

## Observability (for later)

### ~~Staging environment re-sync strategy~~ (RESOLVED — staging removed)

~~Vercel preview + Render test backend no longer get daily content updates because tonight's `SKIP_PUBLISH_STEP=1` removed the `git push` from the cron.~~ **Resolved 2026-04-29:** Render and Vercel decommissioned entirely. No staging environment exists. Production-only architecture: GitHub holds code, GCP VM holds production state, no sync needed. See `docs/decommissioned/render-vercel-2026-04-29.md` for the config snapshot taken before tear-down.

### Broader doc cleanup — staging references in non-spec'd docs

The 2026-04-29 Render/Vercel teardown updated the spec-pinned files (`CLAUDE.md` and `docs/DAILY_PIPELINE_GUIDE.md`). Phase A audit identified **~25 additional doc files** with staging / Render / Vercel references outside that pinned set. They likely range from "outdated narrative that should be edited" to "the word 'staging' used as a generic verb" (e.g., "staging area"); requires per-file inspection.

**Backend repo (18 files):**
- `API_QUICK_REFERENCE.md`, `REWRITE_SUMMARY.md`, `DEPLOYMENT_GUIDE.md`, `COMPLETION_REPORT.md`, `README_DEPLOYMENT.md`, `DEPLOYMENT_CHECKLIST.md`
- `docs/ENVIRONMENT_CONFIG.md`, `docs/HINDI_DAILY_PIPELINE.md`, `docs/AUDIO_GENERATION_GUIDELINES.md`, `docs/FUNNY_SHORTS_V2_GUIDE.md`, `docs/funny_shorts_production_notes.md`, `docs/SILLY_SONGS_BATTLECRY_GUIDE.md`, `docs/CONTENT_GENERATION_GUIDELINES.md`, `docs/SILLY_SONGS_DEPLOY_GUIDE.md`, `docs/CONTENT_PUBLISHING_GUIDELINES.md`, `docs/FUNNY_SHORTS_MUSIC_SPEC.md`, `docs/FUNNY_SHORTS_SPEC.md`
- `docs/follow-ups.md` (self-referential — this file's earlier "Staging environment re-sync strategy" entry was updated in this same pass)

**Frontend repo (7 files):**
- `START_HERE.md`, `QUICKSTART.md`, `DEPLOYMENT.md`, `PROJECT_INDEX.md`, `README.md`, `INSTALLATION.md`, `docs/UI_DISPLAY_GUIDELINES.md`

**Approach:** quick pass per file — `grep -nE "render|vercel|staging" <file>`, decide per match: delete entirely, edit to match production-only architecture, or skip if "staging" is generic English. Batch-commit at the end. Estimate: 60–90 minutes for the full sweep across both repos.

### PR #1 — yesterday's reconciliation

The `reconcile/prod-state-2026-04-28` branch on origin is from yesterday's incomplete reconciliation. Tonight's architecture work supersedes it. Likely stale; verify and close.

---

## Cutover follow-ups (2026-04-29 — content.json refactor)

Items surfaced during the per-content-file cutover that aren't covered above. Cutover itself succeeded (PR #2 merged, walker active, all 306 items reachable, HI Before Bed serving correctly). These are post-cutover loose ends.

### YouTube broadcast restart (deploy_guard's only remaining blocker)

`deploy_guard verify` fails on: `❌ YouTube broadcast is OFFLINE — ffmpeg may still be pushing into a dead stream key`. Pre-existing radio/streaming issue, not refactor-induced. Resolution per the radio runbook (restart radio process). Until restarted, deploy_guard exits non-zero — but the cutover-relevant checks all pass.

### Today's HI cron failures (pre-existing, surfaced during step 1 audit)

The 04:00 UTC HI cron on 2026-04-29 produced 3/6 successes:

| Type | Result | Cause |
|---|---|---|
| short_story | ✓ hi-lok_katha-6-8-bulb | OK |
| long_story | ✓ hi-long-9-12-meer | OK |
| lullaby | ✓ hi-heartbeat-9-12-chan | OK |
| poem | ✗ PermissionError | overwrite of `/opt/dreamweaver-web/public/audio/poems-hi/...` blocked |
| funny_short | ✗ PermissionError | overwrite of `/opt/dreamweaver-web/public/audio/funny-shorts-hi/hi-fs-2956.mp3` blocked at `sync_to_prod_paths` (file was already there with different ownership) |
| silly_song | ✗ validator: lyrics body too long | already tracked above (#silly_song lyrics body length) |

The poem and funny_short PermissionErrors are the `sudo cp without chown` anti-pattern (`feedback_chown_after_sudo_cp.md`). Need to audit `/opt/dreamweaver-web/public/audio/funny-shorts-hi/` and `/opt/dreamweaver-web/public/audio/poems-hi/` for root-owned files and chown back to `anmolmohan:anmolmohan`. Note: the cutover Phase 1 work (Option A architectural fix) chowned the files we copied, but doesn't help if older root-owned files are still there from before.

### EN cron git merge conflicts in per-content files

EN cron log shows: `data/funny_shorts/en-fs-ec06.json: needs merge` and `data/funny_shorts/hi-fs-54fa.json: needs merge`. The cron's `git pull` step (still present pre-step-15-cleanup) hits conflicts when local working tree has uncommitted state. After post-cutover step 16 deletes the generator-side `_auto_mirror` / `_upsert_content` calls and the publish-step is fully removed, this should disappear. But pre-step-16 it's noisy. Worth confirming the cron behavior post-cleanup.

### `/api/v1/lullabies` endpoint bypasses walker

`app/api/v1/lullabies.py` reads `seed_output/lullabies/lullabies.json` directly via `_load_lullabies()` — completely bypassing LocalStore + the new walker. Result: 7 HI lullabies served by API vs 9 in `data/lullabies_hi/`. Two-of-disk gap is pre-existing drift between the two storage paths. Migrating `/api/v1/lullabies` to read from LocalStore (mirror of how silly_songs / poems / funny_shorts now work) would close the architectural gap and let walker be the single source of truth across all content types.

### HI funny_short content.json schema gap

The HI funny_short JSON (in `data/funny_shorts_hi/`) has 28 fields including `subtype`, `comedic_device`, `setting`, `voice_pair`, `closing_pattern`, `opening_tag`, `character_age_dynamic`, `tone`, `emotional_dynamic` — generator-local metadata used by anti-template rotation. **None of these are in `seed_output/content.json`** (only 12 fields propagate via the mirror). If anti-template rotation depends on reading prior items' metadata via the API or content.json, the lean view would degrade rotation quality. Worth verifying the rotation logic reads from per-content files (which preserves all 28 fields) vs content.json (the lean 12).

### Walker boots: 7 items lacking audio

After walker boot, `seed_output/content.json` has 306 items; **7 lack audio_url AND audio_file**:
```
gen-d785f05f65d5    no audio
gen-f52ccb91767c    no audio
gen-ffc731157f8c    no audio
gen-56e0eb178411    no audio
gen-f979b2293b94    no audio
heartbeat-0-1-61e7  no audio   (atypical 0-1 age range lullaby)
permission-0-1-91d2 no audio   (atypical 0-1 age range lullaby)
```

The 5 `gen-*` UUID-format IDs look like draft/preview generations that leaked into the per-content dirs. The 2 `0-1` lullabies are an atypical age range. Pre-existing content quality drift, not refactor-induced (these were already in the prod content.json pre-cutover when content.json had 240 items). Triage decisions:
- Regenerate audio for the 5 `gen-*` items if they're real
- Delete the `gen-*` items from `data/<bucket>/` if they're abandoned drafts
- Determine if 0-1 lullabies are intentional (different cohort) or test artifacts

### Stale recovery watcher process on prod

PID 351105 (`bash -c 'until ! pgrep -f "pipeline_run_hi.py.*types" >/dev/null; do sleep 5; done; ...'`) is orphaned (parent PID 1, ELAPSED 1d+) from yesterday's interactive recovery session. It's stuck in a self-match loop (its own bash command line contains `pipeline_run_hi.py.*types`, so `pgrep -f` always finds at least itself → loop never exits). Harmless but should be killed:

```bash
kill 351105
```

### Cleanup one-shot scripts on prod

The cutover left several ad-hoc scripts on prod that aren't tracked in git:
- `/opt/dreamweaver-backend/scripts/merge_hi_bucket_duplicates.py` — step 5a EN→HI merge
- `/tmp/cutover_hi_diagnose.py`, `/tmp/cutover_hi_assets_diag.py`, `/tmp/cutover_step11_diff.py`, `/tmp/cutover_fix_audio_file.py`, `/tmp/cutover_normalize_hi_schema.py` — diagnostic/fix scripts run during the cutover

These can be deleted post-cutover:
```bash
rm /opt/dreamweaver-backend/scripts/merge_hi_bucket_duplicates.py
rm /tmp/cutover_*.py
```

### Spec §4 step 16+ — generator de-upsert (post-24h-window)

Per spec §4 step 16: after 24h clean observation, delete the `_auto_mirror` / `_upsert_content` calls from generators that now write per-content files directly. Audit list in spec; primary files:
- `scripts/generate_funny_shorts.py` — `_auto_mirror` call
- `scripts/generate_silly_songs_battlecry.py` — `_auto_mirror` call
- `scripts/generate_experimental_poems.py` — `_auto_mirror` call
- `scripts/_hindi_generators.py` — `_upsert_content` calls (5 functions)
- `scripts/generate_long_story_episode.py:2761`, `scripts/generate_short_story_experiment.py:596+`, `scripts/generate_experimental_v2.py:900+`

### Spec §4 step 17 — clean crontab

Remove `SKIP_PUBLISH_STEP=1` from both cron lines (EN at `30 1 * * *`, HI at `0 4 * * *`). The env var is now unreferenced in code; the crontab should not reference variables that don't exist.

### Spec §4 step 18 — declare success

After 24h clean observation, delete rollback branches and `*.bak.*` snapshots; mark this content.json refactor entry as RESOLVED.

---

## Operational notes from tonight

For future Claude sessions, durable lessons from this incident are stored in memory at `~/.claude/projects/-Users-anmolmohan-Music-Bed-Time-Story-App/memory/`:
- `feedback_deploy_guard_required.md` — snapshot before, verify after, every prod change
- `feedback_chown_after_sudo_cp.md` — pair `sudo cp` into pipeline-write paths with `chown`
- `feedback_nginx_backup_location.md` — config backups go to `sites-available/`, never `sites-enabled/`
