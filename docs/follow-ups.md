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

### `seed_output/content.json` gitignore consideration

File is derived from per-content files via the walker at boot and admin reload. Tracking it in git creates divergence on prod when daily cron mutations happen, requiring a stash-pull-strip-reload dance on every backend code merge that includes content.json changes.

**Hit during 2026-05-01 Step 1.7 deploy:** the migration commit included `seed_output/content.json` (post-strip baseline of the local 222-item catalog) as a verification artifact. Prod's content.json had 330 items from today's pipeline mutations; pull conflicted; required `git stash push -- seed_output/content.json`, `git pull`, run migration, drop stash, admin reload. End state was correct but the dance was avoidable.

**Fix:** gitignore `seed_output/content.json` and `data/content.json`. Both are derived snapshots; the canonical state lives in per-content files (`data/<type>[_hi]/<id>.json`). Per the cutover spec (§2c), the walker rebuilds these snapshots at boot and admin reload — git-tracking them is redundant and conflict-prone.

Migration:
- Add to `.gitignore`
- `git rm --cached seed_output/content.json data/content.json`
- One-time commit: "chore(content): gitignore derived snapshots"
- Backend boot path already regenerates them; no behavior change, just removes the divergence vector.

Worth a separate decision and its own commit. Aligns with the architecture, eliminates a recurring class of merge friction.

### Frontend deploy script silent-failure footgun

`CLAUDE.md`'s frontend-deploy snippet has `git pull origin main 2>&1 | tail -5` which masks the exit code via the pipe. If `git pull` fails (merge conflict, unmerged files, etc.), the rest of the script continues running on old code, and `pm2 restart` loads stale assets. **Same class of incident as the 2026-04-29 backend repo lockup that motivated `SKIP_PUBLISH_STEP` (43517a8); the web deploy snippet never got the equivalent guard.**

Hit during 2026-05-01 Step 1.1 frontend deploy: `git pull` failed with stuck unmerged-paths state on `/opt/dreamweaver-web`, but build continued on `ed019c9` (pre-Step-1.1) and PM2 reloaded the old build. Took a manual `git rm --cached` to resolve. Recovery details in session log.

**Fix:**
- Add `set -e` at top of the deploy script, **and**
- Replace pipe-to-tail with `git pull origin main || { echo "FAIL: git pull"; exit 1; }`
- Add a one-line precondition check that fails the deploy if `git ls-files -u` is non-empty (catches stuck merge state before pull is attempted).

Update `CLAUDE.md` "Frontend deploys are NOT automatic for dreamvalley.app" snippet accordingly. Five-line edit; non-urgent but worth shipping before next merge conflict bites.

### HI silly_song cover URL routing mismatch

`scripts/_hindi_generators.py` silly_song path (lines ~795–830) writes the generated cover to:
- `WEB_ROOT/public/covers/<sid>.webp` (legacy default route — no longer aliased by nginx)
- `WEB_ROOT/public/covers/silly-songs/<sid>_cover.webp` (legacy duplicate)
- `BASE_DIR/seed_output/silly_songs/<sid>_cover.webp` (debug master)
- `PROD_COVER_STORE/silly-songs/<sid>_cover.webp` (active path, with `_cover` suffix)

But the item's emitted `cover` field is `/covers/<sid>.webp` (bare-id at root). nginx `/covers/` default route now aliases `/opt/cover-store/` (root) — so the bare-id URL resolves to a path that doesn't exist (file is in `silly-songs/` subdir with different filename shape).

**Hit on 2026-05-01:** `hi-gudiya_ka_gherao-2-5-27fb` cover served 404 on `/covers/<id>.webp`. Patched manually with `cp` from the `silly-songs/` subdir to bare-id path at `/opt/cover-store/`.

**Two structural fix options:**
1. Generator writes the cover to `/opt/cover-store/<sid>.webp` at root (in addition to the subdir), matching the bare-id URL the item emits.
2. Generator emits cover field as `/covers/silly-songs/<sid>_cover.webp` (subdir path), matching where the file actually lands.

Option 2 is cleaner — no extra disk copies, matches the existing nginx subdir alias `/covers/silly-songs/` → `/opt/cover-store/silly-songs/`. Same fix probably applies to other HI generators (poem, lullaby) that have the same dual-write pattern; audit during the same change.

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

---

## Pending: commit `generate_audio.py` per-content write fix (2026-05-01)

**File**: `scripts/generate_audio.py` — `save_content_json` function (around line 2444)

**Status**: Patched on prod via scp on 2026-05-01 with backup at `/opt/dreamweaver-backend/scripts/generate_audio.py.bak.20260501`. **Not** committed to `origin/main`. Local working tree (`dreamweaver-backend/scripts/generate_audio.py`) holds the same change, also uncommitted.

**What the change does**: After writing `audio_variants` and `duration` into `seed_output/content.json`, also calls `_per_content_io.update_per_content_fields(sid, audio_variants=..., duration=...)` for each story so the per-content file (`data/<type>/<id>.json`) — the source of truth post the 2026-04-29 refactor — stays in sync. Without this, the backend's 60s mtime poller rebuilds the snapshot from per-content and silently wipes the just-written `audio_variants`. That's how *Stripe and the Whispering Stones* got dropped at the pre-publish gate on 2026-05-01 despite a clean MP3 and QA pass.

**Risk while uncommitted**: prod is running code that `origin/main` doesn't reflect. Any redeploy from main (re-clone, fresh checkout, `git reset --hard`) silently regresses the fix and the next pipeline run drops its short story again.

**Resolution after the cutover observation window closes cleanly**:
1. `git add scripts/generate_audio.py && git commit -m "fix(generate_audio): mirror audio_variants to per-content files"`
2. `git push origin main`
3. On prod: `git pull --ff-only origin main` (effective no-op — file already at the patched state, git just reconciles to the committed SHA)
4. `diff /opt/dreamweaver-backend/scripts/generate_audio.py /opt/dreamweaver-backend/scripts/generate_audio.py.bak.20260501` to confirm only the intended hunks differ
5. Once verified, remove the `.bak.20260501` backup

**Do not act during cutover observation.** The change is benign and confirmed working on prod (Stripe was successfully recovered today via the same per-content write path); no new breakage if we wait.

**Related**: this is the same class of bug as the architecture follow-up at the top of this file (`data/content.json` refactor — treat as derived artifact). The proposed shape there — generators write only per-content, snapshot fully derived — would make this whole synchronization-bug class structurally impossible. The `generate_audio.py` patch is a targeted fix that aligns this generator with the partial migration that's already happened; the architecture follow-up would finish the migration.

---

## Logging gaps surfaced by 2026-05-03 HI funny short failure

Three small follow-ups discovered while debugging today's failed HI funny short slot. None blocking; batch into a single cleanup commit when convenient.

1. **Cron stdout truncation hides Mistral attempts + repair logs.**
   `pipeline_hi_cron.log` only captures the `stdout tail` (~100 chars) of each generator subprocess. When `generate_funny_shorts_hi.py` fails after 5 attempts, attempts 1–3 and any `Devanagari repair: ...` log lines are lost from the audit trail. Today's investigation needed a manual `tee /tmp/...` rerun on prod to confirm the repair pass was firing at all.
   - Workaround: `2>&1 | tee /tmp/...` for ad-hoc reruns.
   - Real fix: redirect each generator's stdout/stderr to a per-day log file alongside `pipeline_hi_cron.log` (e.g. `pipeline_hi_2026-05-03_funny_short.log`) so attempt-level diagnostics survive past the cron tail window.

2. **Stale "after 3 attempts" message at `scripts/generate_funny_shorts_hi.py:287`.**
   The error log line says `failed validation after 3 attempts: ...` but the loop at line 249 actually iterates 5 times. Misleading when reading cron output. One-line edit: change `3` to `5` (or interpolate `range_size`).

3. **Silent return path at `scripts/_funny_shorts_common.py:521`.**
   Inside `repair_devanagari`, post-revalidation builds a `still_missing` list by regex-matching `^Line N:.*missing Devanagari` against `post_errors`. If `post_errors` contains errors that don't match the regex (a brand-new error type introduced by the repair), `still_missing` stays empty and the function returns `None` at line 521 without printing any log line. Add a `print(f"{log_prefix}Devanagari repair: post-repair revalidation surfaced non-Devanagari errors: {post_errors}")` before that return so this branch becomes visible in logs.

---

## Pipeline sync gating + manual-test orphan risk (2026-05-07)

Surfaced during EN short_story retry-hint deploy verification (commit 55c3e7c). Manual `generate_content_matrix.py --count-stories 1` produced a content_expanded.json entry with no audio/cover/QA — would have leaked to `content.json` on next cron sync if not removed manually.

1. **Pipeline sync gating on audio existence.**
   Should the sync step from `content_expanded.json` → `content.json` gate on per-item audio file existence? Two possible gates:
   - `sync_seed_data.py` skips items without an audio file at expected path.
   - `generate_content_matrix.py` does not write to `content_expanded.json` until audio is generated for the item.
   Investigate which is the right gate. Either eliminates a class of orphan-publish risk that the manual-test path exposed today.

2. **Manual generation pipeline lacks dry-run.**
   `--count-stories 1` directly via `generate_content_matrix.py` produces content without audio/cover/QA. `SKIP_PUBLISH_STEP=1` is now a no-op (deleted in refactor). For ad-hoc test/debug runs:
   - Run full `pipeline_run.py` with a dry-run flag (does it support one?), OR
   - Remember to clean up `content_expanded.json` afterward, OR
   - Add a `--dry-run` flag to `generate_content_matrix.py` that writes nowhere.
   Track the `--dry-run` flag addition.

3. **nginx `/audio/` has two duplicate `location` blocks.**
   `/etc/nginx/sites-enabled/...` declares `location /audio/` twice — one alias to `/opt/audio-store/`, one to `/opt/dreamweaver-web/public/audio/`. nginx uses first match wins; the second block is dead. Both directories currently mirror identical content so no user impact, but the config is misleading. Consolidate to a single `location` block; pick a canonical source-of-truth directory. Confirm one mirror is the legitimate source before removing the other. Low priority, no current user impact.

4. **`data/content.json` is a runtime artifact committed to git.**
   Pipeline mutates it every run; `git stash`/`git stash pop` cycle in preflight is required only to keep the tree clean before `git pull`. The file should be gitignored and read-only-from-git; the pipeline owns it. Currently the "stash pop FAILED" log line is expected noise. Cleanup requires moving any seed-of-record content elsewhere and adjusting deploy_guard expectations.

5a. **EN `silly_songs` + `funny_shorts` matrix support.**
   `pipeline_run.py` (EN orchestrator) lacks matrix-level support for silly_songs and funny_shorts. These types are only generated via the before-bed sub-step. HI generates them via `pipeline_run_hi.py` per-type iteration. EN needs equivalent matrix generators added to reach full HI parity. ~50-100 lines of orchestration code. Priority: low until daily content volume gap becomes a user-facing problem.

5b. **EN poems re-enablement investigation.**
   `pipeline_run.py --help` text says "poems removed from content" for `--count-poems` (default 0). Commit 59725f3 (2026-04-03 "Remove poem content type from content system") removed 51 EN poem items + dropped "poem" from `--type` choices + filtered poem type from deploy_guard. Before Bed musical poems via `poemsApi` are unaffected. Commit message doesn't state the rationale. Need to investigate why EN poems were disabled before re-enabling — possible causes: content quality issue, validator bug, abandoned content type, regulatory concern. Re-enabling prematurely could re-introduce whatever issue triggered removal. Priority: medium.

5. **Rusty-class `audio_variants` enrichment race.**
   2026-05-12 EN pipeline dropped "Rusty and the Door That Glowed" at the pre-publish gate with "no audio_variants" — despite QA Phase 2 having transcribed the file (marginal_fidelity 0.58, WARN not FAIL). The AUTO-FIX disk-recovery cross-check at `pipeline_run.py:761-780` is supposed to self-heal missing audio_variants entries by scanning `/audio/pre-gen/` for files matching the `gen-<id>` prefix. Rusty was not recovered. Possible causes: (1) Rusty's audio filename doesn't match the `gen-<id>` prefix convention the recovery loop expects, (2) AUTO-FIX runs at the wrong point in orchestration (after the gate, or before audio is written), (3) genuine missing `audio_variants` entry that should have been written by `step_audio` but wasn't. Investigation needed: read `step_audio` variant-attachment code + AUTO-FIX cross-check logic + verify the actual filename of Rusty's audio on disk. Priority: medium. One story dropped is acceptable; recurring drops would compound into catalog gaps.
