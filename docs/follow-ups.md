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

### `seedData.js` migration — backend serves it via API

**The problem:** `dreamweaver-web/src/utils/seedData.js` is the frontend's seed manifest, regenerated daily by the pipeline's `sync_seed_data.py`. Tonight we removed `public/covers/` from git via `SKIP_PUBLISH_STEP=1`, but `seedData.js` is still in `src/utils/` so it's the last reason the pipeline would ever want to commit on prod. Nothing to do for tonight (cron skips publish entirely now), but the data file is still authored alongside JS code, which is the wrong shape.

**Proposed shape:**
- Backend serves a `/api/v1/seed-manifest` endpoint that returns the same data
- Frontend fetches at startup, hydrates the same in-memory store that currently imports `seedData.js`
- `src/utils/seedData.js` deleted from frontend repo

**Estimate:** Half-day. Frontend bootstrap change + a small backend endpoint + delete the file.

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

### Historical orphan backfill

After tonight's `_auto_mirror` fix, future orphans are prevented at source. But there are still historical orphans on disk:

```
data/silly_songs/cat_talk_2_5.json     (rescued tonight)
data/silly_songs/last_day_9_12.json
data/silly_songs/moon_follow_2_5.json
data/silly_songs/new_game_9_12.json
data/silly_songs/new_pet_6_8.json
data/silly_songs/five-more-minutes.json
data/poems/question_9_12_92a6.json     (rescued tonight)
data/funny_shorts/hi-fs-* (multiple)
```

Each needs human triage: was it intended for production, or was it a dev/test artifact? After triage, real ones get rescued via `_auto_mirror`, dev ones get deleted. Separate session.

---

## Observability (for later)

### Staging environment re-sync strategy

Vercel preview + Render test backend no longer get daily content updates because tonight's `SKIP_PUBLISH_STEP=1` removed the `git push` from the cron. Production (`dreamvalley.app`) is unaffected — it lives on the GCP VM and updates via admin/reload. But staging is now stale. Decide:

- GitHub Actions on a schedule that mirrors the prod content delta back to GitHub
- Manual `cherry-pick` from a personal laptop weekly
- A separate non-prod cron that pulls from prod and pushes to GitHub
- Accept that staging diverges from prod (acceptable if staging is just for code review, not content review)

### PR #1 — yesterday's reconciliation

The `reconcile/prod-state-2026-04-28` branch on origin is from yesterday's incomplete reconciliation. Tonight's architecture work supersedes it. Likely stale; verify and close.

---

## Operational notes from tonight

For future Claude sessions, durable lessons from this incident are stored in memory at `~/.claude/projects/-Users-anmolmohan-Music-Bed-Time-Story-App/memory/`:
- `feedback_deploy_guard_required.md` — snapshot before, verify after, every prod change
- `feedback_chown_after_sudo_cp.md` — pair `sudo cp` into pipeline-write paths with `chown`
- `feedback_nginx_backup_location.md` — config backups go to `sites-available/`, never `sites-enabled/`
