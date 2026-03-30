# Dream Valley — Daily Content Pipeline Guide

> **Purpose**: Automate daily publication of new bedtime stories, poems, and lullabies with zero manual intervention. Runs entirely on the GCP production server with no local device dependencies.

---

## Architecture Overview

```
GCP VM (dreamvalley-prod) runs pipeline_run.py daily via cron (7 days/week):

  PREFLIGHT → Warm Modal + test Mistral + check disk + kill stale processes
  1. GENERATE  → Mistral Large (free tier)         → 1 story + 1 poem + 1 lullaby
  2. AUDIO GEN → Modal Chatterbox TTS + ACE-Step   → 14 MP3s (Chatterbox) + 3 MP3s (ACE-Step)
  3. AUDIO QA  → Voxtral transcription (free tier)  → PASS/FAIL
  4. ENRICH    → Mistral Large (free tier)          → unique musicParams
  5. COVERS    → Mistral Large (free tier)          → animated SVG cover per story
  6. SYNC      → content.json → seedData.js + copy audio/covers to web public/
  7. PUBLISH   → git push both repos → Render/Vercel auto-deploy
  8. DEPLOY    → Backend hot-reload (admin API) + nginx serves new static files (zero-downtime)
  POSTFLIGHT → Cost estimate + disk usage summary
  NOTIFY     → Email via Resend (ALWAYS — success, partial, or failure)
```

### Backend Hot-Reload

The backend uses a **zero-downtime hot-reload** architecture. No Docker restart is needed for content changes:

1. **Admin API** (primary): `POST /api/v1/admin/reload` with `X-Admin-Key` header — re-reads content/subscriptions/voices into memory instantly.
2. **Background polling** (safety net): A background task checks `seed_output/content.json` mtime every 60 seconds and auto-reloads on change.
3. **Docker restart** (fallback): Only used if both the HTTP call and polling fail.

The pipeline's `step_deploy_prod()` calls the admin API automatically. The `ADMIN_API_KEY` is loaded from `.env`.

### Cost Summary

#### Per-Run Costs (variable)

| Step | Service | Cost |
|------|---------|------|
| Content generation | Mistral Large (free experiment tier) | $0.00 |
| Audio generation (14 story/poem + 3 lullaby variants) | Modal T4 GPU (~51 GPU-min) | ~$0.68 (from $30/mo free credits) |
| Audio QA (transcription + fidelity) | Voxtral via Mistral API (free tier) | $0.00 |
| Music params | Mistral Large (free tier) | $0.00 |
| Cover SVG generation | Mistral Large (free tier) | $0.00 |
| Email notification | Resend (free tier, 100 emails/day) | $0.00 |
| **Per-run total** | | **~$0.68** |

#### Infrastructure Costs (fixed monthly)

| Resource | Spec | Cost/Month |
|----------|------|-----------|
| GCP VM | e2-small (2 vCPU shared, 2GB RAM), asia-south1 | $14.69 |
| GCP Disk | 30GB standard persistent disk | $1.44 |
| Render (backend) | Free tier | $0.00 |
| Vercel (frontend) | Free tier | $0.00 |
| **Infrastructure total** | | **$16.13/mo** |

#### Monthly Total (daily runs, 7 days/week)

| Component | Monthly Cost |
|-----------|-------------|
| GCP infrastructure (VM + disk) | $16.13 |
| Modal GPU (~30 runs × $0.68) | ~$20.40 (from $30 free credits) |
| Mistral, Resend, Render, Vercel | $0.00 |
| **Total** | **~$36.53/mo** ($16.13 cash + ~$20.40 free credits) |

> **Note**: Modal provides $30/month in free credits. The ~$20.40 Modal cost is covered by free credits, so actual cash spend is **~$16.13/month** (GCP only). Consider a 1-year CUD commitment to reduce GCP to ~$10.69/mo.

---

## Server Setup (One-Time)

### 1. SSH into Production Server

```bash
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a
```

### 2. Clone Backend Repo (if not already present)

```bash
cd /opt
sudo mkdir -p dreamweaver-backend
sudo chown -R anmolmohan:anmolmohan dreamweaver-backend
git clone https://github.com/J110/dreamweaver-backend.git /opt/dreamweaver-backend
```

### 3. Install Python Dependencies

```bash
cd /opt/dreamweaver-backend
pip3 install -r requirements.txt
pip3 install mistralai httpx pydub python-dotenv
```

### 4. Set Environment Variables

Create `/opt/dreamweaver-backend/.env`:

```env
# Mistral AI — free experiment tier (text generation + QA + music params + covers)
MISTRAL_API_KEY=your_mistral_api_key_here

# Resend — email notifications (pipeline status reports)
RESEND_API_KEY=your_resend_api_key_here

# Modal — Chatterbox TTS endpoint (auto-deployed, no token needed for HTTP calls)
# The Modal endpoint URL is baked into generate_audio.py
# Voice references are stored in Modal persistent volume (already uploaded)

# Modal — ACE-Step SongGen endpoint (for lullaby audio generation)
SONGGEN_URL=https://j110--dreamweaver-songgen-sing.modal.run
SONGGEN_HEALTH=https://j110--dreamweaver-songgen-health.modal.run

# Admin API — used by pipeline to hot-reload backend content (no restart needed)
ADMIN_API_KEY=your_admin_api_key_here
```

**Getting your Mistral API key:**
1. Go to https://console.mistral.ai/
2. Create an account (no credit card required)
3. Go to API Keys → Create new key
4. Free experiment tier: 1B tokens/month, 2 req/min

**Getting your Resend API key:**
1. Go to https://resend.com/
2. Create account → API Keys → Generate
3. Verify sending domain (dreamvalley.app) or use their test domain
4. Free tier: 100 emails/day (more than enough for daily pipeline)

### 5. Set Up Modal Token (for deploying/updating the TTS endpoint)

```bash
pip3 install modal
modal token set --token-id ak-VYW271t6iDtCpFjA4ma2nE \
                --token-secret as-5FxDxPVA2FsGoWA2IanU42
```

**Note**: The Modal token is only needed if you need to redeploy or update the Chatterbox TTS endpoint. The pipeline itself calls the endpoint via HTTP — no Modal token needed at runtime.

### 6. Set Up Git for Auto-Push

```bash
cd /opt/dreamweaver-backend
git remote set-url origin https://github.com/J110/dreamweaver-backend.git
# Configure git credentials (use GitHub personal access token)
git config credential.helper store
```

### 7. Verify Frontend Repo is Available

The pipeline syncs `seedData.js` to the frontend repo. Ensure it's cloned:

```bash
ls /opt/dreamweaver-web  # Should exist from production deployment
```

### 8. Set Up Daily Cron (7 days/week)

```bash
crontab -e
```

Add this line to run the pipeline daily at 2:00 AM IST (every day, including weekends):

```cron
0 2 * * * cd /opt/dreamweaver-backend && /usr/bin/python3 scripts/pipeline_run.py --lang en --count-lullabies 1 >> /opt/dreamweaver-backend/logs/cron.log 2>&1
```

**Note**: The cron uses `0 2 * * *` (every day at 2 AM). If the server timezone is UTC, use `30 20 * * *` (20:30 UTC = 2:00 AM IST next day). Check timezone with `timedatectl`.

---

## Running the Pipeline

### Full Run (Default: 1 story + 1 poem + 1 lullaby)

```bash
cd /opt/dreamweaver-backend
python3 scripts/pipeline_run.py
```

### Dry Run (Preview without API calls)

```bash
python3 scripts/pipeline_run.py --dry-run
```

### Custom Counts

```bash
python3 scripts/pipeline_run.py --count-stories 3 --count-poems 2 --count-lullabies 1 --lang en
```

### Resume After Failure

If the pipeline fails mid-run, resume from the last checkpoint:

```bash
python3 scripts/pipeline_run.py --resume
```

### Run Single Step

```bash
python3 scripts/pipeline_run.py --step generate   # Only content generation
python3 scripts/pipeline_run.py --step audio       # Only audio generation
python3 scripts/pipeline_run.py --step qa          # Only QA
python3 scripts/pipeline_run.py --step enrich      # Only music params
python3 scripts/pipeline_run.py --step covers      # Only SVG cover generation
python3 scripts/pipeline_run.py --step sync        # Only seed data sync
python3 scripts/pipeline_run.py --step publish     # Only git push
```

### Skip Publishing (Test Mode)

```bash
python3 scripts/pipeline_run.py --skip-publish
```

---

## Email Notifications

The pipeline sends an email notification via Resend API **on every run** — both success and failure.

**From**: `Dream Valley Pipeline <support@dreamvalley.app>`
**To**: `mohan.anmol@gmail.com`
**Subject formats**:
- `[OK] Dream Valley Pipeline — 2026-02-28 — 3 new items` — All items generated successfully
- `[PARTIAL] Dream Valley Pipeline — 2026-02-28 — 1 new items` — Some items failed (e.g., expected 3, got 1)
- `[FAIL] Dream Valley Pipeline — 2026-02-28` — Pipeline failed entirely

### Email Contents

| Field | Description |
|-------|-------------|
| Generated | Number of new stories/poems/lullabies generated (with per-type breakdown) |
| ⚠️ Warning | (PARTIAL only) Expected vs actual item count — e.g., "Expected 3, got 1" |
| Audio QA | X passed, Y failed |
| Covers | X generated, Y fallback (default.svg) |
| Elapsed | Total pipeline run time |
| Cost Breakdown | Modal GPU (actual from elapsed time), GCP VM daily, total this run |
| Monthly Projection | Extrapolated from actual run cost × 30 |
| Disk | Total audio files + cover count |
| New Content | List of generated story/poem titles |
| Log tail (failure only) | Last 50 lines of the pipeline log |

### Test Email Notification

```bash
python3 scripts/pipeline_notify.py --test
```

### Debugging Email Issues

1. Check `RESEND_API_KEY` is set: `grep RESEND .env`
2. Test standalone: `python3 scripts/pipeline_notify.py --test`
3. Check Resend dashboard: https://resend.com/emails
4. Verify domain: `support@dreamvalley.app` must be verified in Resend

---

## Cover SVG Generation

The pipeline auto-generates animated SVG covers using Mistral Large. Each cover is unique, themed to the story.

### How It Works

1. Pipeline reads `content.json` for items needing covers (missing or `default.svg`)
2. For each: sends a detailed prompt to Mistral with story title, description, theme
3. Prompt includes full design rules (7-layer structure, CSS animations, viewBox 512x512)
4. Response is validated (XML parse, @keyframes count, file size)
5. Saved to `dreamweaver-web/public/covers/{slug}.svg`
6. `content.json` updated with the cover path
7. On failure: retry once (35s wait), then fallback to `default.svg`

### Manual Cover Generation

```bash
# Generate cover for a specific story
python3 scripts/generate_cover_svg.py --id gen-xxx

# Preview what would be generated
python3 scripts/generate_cover_svg.py --dry-run

# Only items that have never had a cover
python3 scripts/generate_cover_svg.py --new-only
```

### Cover Design Rules

- viewBox: `0 0 512 512`
- 7 layers: sky → far bg → mid bg → middle ground → main character → sparkles → vignette
- CSS @keyframes only (no JavaScript)
- Unique 2-letter ID prefix per cover (e.g., `fm-skyGrad`)
- Target size: 10-45KB
- Guide: `dreamweaver-web/public/covers/COVER_DESIGN_GUIDE.md`

---

## Cover & Audio Persistence (CRITICAL)

Covers and audio are the most fragile assets in the system. Both have persistent backup stores outside any git repo that survive re-clones, Docker rebuilds, and frontend rebuilds.

### Storage Architecture

```
AUTHORITATIVE (what nginx serves):
  /opt/dreamweaver-web/public/covers/*.svg          ← Regular story/poem covers (141+)
  /opt/dreamweaver-backend/public/covers/funny-shorts/  ← Funny shorts covers
  /opt/dreamweaver-backend/public/covers/silly-songs/   ← Silly songs covers
  /opt/dreamweaver-web/public/audio/pre-gen/*.mp3   ← All story/poem audio

PERSISTENT BACKUP (outside git, survives everything):
  /opt/cover-store/*.svg                            ← Backup of ALL covers
  /opt/audio-store/pre-gen/*.mp3                    ← Backup of ALL audio

GENERATION OUTPUT (backend, committed to git):
  seed_output/covers_experimental/*_combined.svg    ← Raw generated covers
  audio/pre-gen/*.mp3                               ← Raw generated audio
```

### nginx Configuration (dreamvalley.app)

```nginx
# Specific paths (checked first by nginx longest-prefix matching):
location /covers/funny-shorts/ { alias /opt/dreamweaver-backend/public/covers/funny-shorts/; }
location /covers/silly-songs/  { alias /opt/dreamweaver-backend/public/covers/silly-songs/; }

# General covers (all gen-*.svg and legacy named covers):
location /covers/ { alias /opt/dreamweaver-web/public/covers/; }
```

**CRITICAL**: The general `/covers/` MUST point to the **frontend** directory (`/opt/dreamweaver-web/public/covers/`), NOT the backend. The backend only has funny-shorts and silly-songs subdirectories. Pointing `/covers/` to the backend will break ALL regular story covers.

### What Survives What

| Event | Covers | Audio | Action Needed |
|-------|--------|-------|---------------|
| Docker rebuild (`docker-compose up --build`) | ✅ Safe (volume mount `./public:/app/public`) | ✅ Safe | None |
| `git pull` in frontend | ✅ Safe (covers are in git) | ⚠️ Audio is gitignored | Pipeline auto-recovers from `/opt/audio-store` |
| `git pull` in backend | ✅ Safe (experimental covers in git) | ⚠️ Audio is gitignored | Pipeline auto-recovers |
| Frontend re-clone | ⚠️ Only git-tracked covers survive | ❌ Audio lost | Run `python3 scripts/pipeline_run.py --step sync` to recover from stores |
| Backend re-clone | ✅ Git-tracked covers survive | ❌ Audio lost | Same as above |
| `npm run build` (frontend) | ✅ Safe (build doesn't delete public/) | ✅ Safe | None |
| nginx config change | ⚠️ Check aliases point to correct dirs | ✅ Safe | Verify with `curl` after reload |

### Automatic Backup/Recovery (Pipeline Step 6: SYNC)

The pipeline's sync step automatically:
1. **Backs up** all covers from `dreamweaver-web/public/covers/` → `/opt/cover-store/`
2. **Backs up** experimental covers from `seed_output/covers_experimental/` → `/opt/cover-store/`
3. **Recovers** any missing covers from `/opt/cover-store/` → `dreamweaver-web/public/covers/`
4. Same for audio: backup to `/opt/audio-store/`, recover from it

### Manual Recovery

```bash
# Audit covers (check what's missing)
curl -s https://api.dreamvalley.app/api/v1/analytics/content-audit/covers \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)" | python3 -m json.tool

# Auto-recover missing covers from persistent store
curl -s -X POST https://api.dreamvalley.app/api/v1/analytics/content-audit/covers/recover \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)" | python3 -m json.tool

# Same for audio (existing endpoints)
curl -s https://api.dreamvalley.app/api/v1/analytics/content-audit \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)" | python3 -m json.tool
curl -s -X POST https://api.dreamvalley.app/api/v1/analytics/content-audit/recover \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)" | python3 -m json.tool
```

### Rules for Agents / Developers

1. **NEVER change the nginx `/covers/` alias** to point to the backend — it must point to `/opt/dreamweaver-web/public/covers/`
2. **NEVER re-clone repos** without first checking `/opt/cover-store/` and `/opt/audio-store/` exist and are populated
3. **After any Docker rebuild**: verify covers still serve — `curl -s -o /dev/null -w '%{http_code}' https://dreamvalley.app/covers/gen-728f2c9e4615.svg` should return 200
4. **After any nginx change**: test ALL cover types (gen-*, funny-shorts/*, silly-songs/*, legacy named covers)
5. **If covers are missing**: use the audit/recover API endpoints above before regenerating — they may be recoverable from the persistent store

---

## Known Limitations

| Step | Status | Notes |
|------|--------|-------|
| Production deploy | **Zero-downtime** | Pipeline auto-deploys: backend hot-reloads via admin API, nginx serves new covers/audio from `public/`. NO frontend rebuild or PM2 restart for daily content. |
| Content review | **Recommended** | While QA catches audio issues, human review of story text quality is recommended as a spot-check. |
| Cover quality review | **Recommended** | AI-generated covers may occasionally need manual refinement. Check the production app after deploy. |
| Partial generation | **Auto-detected** | If Mistral fails mid-generation, pipeline reports PARTIAL (yellow) in email with expected vs actual count. Items that were generated still proceed through the full pipeline. |

---

## Server Independence

The pipeline is fully self-contained on the GCP server. No local machine dependencies:

| Dependency | Where It Lives | How Accessed |
|------------|---------------|--------------|
| Voice references | Modal persistent volume (`/data/voices/`) | Via HTTP (Chatterbox endpoint) |
| Content files | GCP VM (`/opt/dreamweaver-backend/seed_output/`) | Local filesystem |
| Audio files | GCP VM (`/opt/dreamweaver-backend/audio/pre-gen/`) | Local filesystem |
| Cover SVGs | GCP VM (`/opt/dreamweaver-web/public/covers/`) | Local filesystem |
| Mistral AI | Cloud API | HTTP (MISTRAL_API_KEY in .env) |
| Modal TTS | Cloud endpoint | HTTP (no local GPU needed) |
| Resend Email | Cloud API | HTTP (RESEND_API_KEY in .env) |
| Git repos | GitHub | `git push` from GCP VM |

### Voice References

Voice references are stored in the **Modal persistent volume** (`chatterbox-data`), not on any local machine. They were uploaded during the one-time setup:

```bash
# This was already done — voice refs live in Modal volume /data/voices/
modal volume put chatterbox-data voice_references/ /voices/
```

To update voice references:
```bash
# From any machine with the Modal token configured
modal volume put chatterbox-data new_references/ /voices/
```

---

## Content Diversity

The pipeline enforces 8 diversity dimensions:

1. **Universe/Era**: Contemporary, Historical, Futuristic, Mythological, Fantasy, Prehistoric
2. **Geography**: India, East Asia, Africa, Europe, Americas, Arctic, Ocean
3. **Life Aspects**: Family, friendship, school, dreams, etc. (age-appropriate)
4. **Plot Archetypes**: Quest, Discovery, Friendship, Transformation, Celebration
5. **Character Gender**: 40% female, 40% male, 20% neutral
6. **Lead Character Type** (NEW): Human ~30%, Animals ~24%, Plants/Celestial/Weather ~18%, Objects/Aliens/Robots ~18%, Mythical ~6%
7. **Theme**: 11 themes with balanced coverage
8. **Anti-duplication**: Title, plot, character, setting uniqueness enforced
9. **Lullaby age restriction**: Songs/lullabies are only generated for ages 0-1 and 2-5. Ages 6+ get stories and poems only. Enforced in content generation, audio generation, and pipeline post-validation.

---

## Monitoring & Troubleshooting

### Check Logs

```bash
# Latest pipeline log
ls -lt /opt/dreamweaver-backend/logs/pipeline_*.log | head -5

# Watch live
tail -f /opt/dreamweaver-backend/logs/pipeline_*.log

# Cron log
tail -50 /opt/dreamweaver-backend/logs/cron.log
```

### Check Pipeline State

```bash
cat /opt/dreamweaver-backend/seed_output/pipeline_state.json
```

### Common Issues

| Issue | Solution |
|-------|----------|
| `MISTRAL_API_KEY not set` | Add key to `/opt/dreamweaver-backend/.env` |
| Mistral rate limited | Wait 30s and resume. Free tier = 2 req/min |
| Modal endpoint cold start | Preflight warms it up. First call still takes ~60s. |
| Modal credits exhausted | Check https://modal.com/billing. $30/mo free. |
| Audio QA fails | Check fidelity scores in logs. May need to regenerate audio. |
| Git push fails (auth) | Check SSH keys / GitHub token. Run `git push` manually. |
| Git push fails (identity) | Run `git config user.email 'pipeline@dreamvalley.app'` and `git config user.name 'Dream Valley Pipeline'` in both repo dirs. Pipeline auto-configures this since 2026-02-19. |
| Publish runs from wrong directory | Frontend git commands must use `cwd=WEB_DIR`. Fixed in `step_publish()` on 2026-02-19 — no longer uses string splitting. |
| Story text is one big block (no paragraphs) | LLM sometimes generates text without newlines. Fixed: (1) prompts now mandate paragraph breaks, (2) `ensure_paragraph_breaks()` post-processor auto-fixes. |
| `content.json` corrupt | Restore from git: `git checkout -- seed_output/content.json` |
| Backend content stale | Hot-reload: `curl -X POST localhost:8000/api/v1/admin/reload -H "X-Admin-Key: KEY"`. Or wait 60s for auto-polling. |
| Pipeline shows PARTIAL | Some items failed generation (usually Mistral flakiness). Items that succeeded still publish. Re-run `--resume` for missing items. |
| Admin reload returns 403 | Wrong API key. Check `ADMIN_API_KEY` in `.env` matches the header value. |
| Audio not playing on deployed app | Audio files must be in BOTH repos. Pipeline auto-copies during sync. If missing: `cp backend/audio/pre-gen/XXXX*.mp3 web/public/audio/pre-gen/` |
| New story has no cover image | Cover generation may have failed — check logs. Run manually: `python3 scripts/generate_cover_svg.py --id STORY_ID` |
| Cover shows as blank | SVG validation failed. Check logs for XML parse errors. May need manual SVG creation per `COVER_DESIGN_GUIDE.md`. |
| `dotenv` not loading env vars | All scripts load dotenv. Verify: `grep -l "load_dotenv" scripts/*.py` |
| Hindi content appearing unexpectedly | Pipeline defaults to `--lang en`. sync_seed_data.py also filters by `--lang en`. |
| New story not appearing first in feed | Missing `addedAt` field. sync_seed_data.py auto-generates this from `created_at`. |
| Email notification not received | Check `RESEND_API_KEY` in `.env`. Test: `python3 scripts/pipeline_notify.py --test`. Check Resend dashboard. |
| Pipeline runs but no email | Notification module import may fail. Check: `python3 -c "from scripts.pipeline_notify import send_pipeline_notification; print('OK')"` |

### Modal Health Checks

```bash
# Chatterbox TTS (stories/poems)
curl -s "https://j110--dreamweaver-chatterbox-health.modal.run" | python3 -m json.tool

# ACE-Step SongGen (lullabies)
curl -s "https://j110--dreamweaver-songgen-health.modal.run" | python3 -m json.tool
```

### Mistral API Check

```bash
python3 -c "
from mistralai import Mistral
import os
client = Mistral(api_key=os.environ['MISTRAL_API_KEY'])
r = client.chat.complete(model='mistral-large-latest', messages=[{'role':'user','content':'Say hello'}], max_tokens=10)
print(r.choices[0].message.content)
"
```

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/pipeline_run.py` | Main orchestrator (preflight → 8 steps → postflight → notify) |
| `scripts/pipeline_notify.py` | Email notifications via Resend API |
| `scripts/generate_content_matrix.py` | Story/poem generation with diversity matrix |
| `scripts/generate_audio.py` | Audio generation (Chatterbox TTS for stories/poems, ACE-Step for lullabies) |
| `scripts/qa_audio.py` | Audio QA (duration + fidelity) |
| `scripts/generate_music_params.py` | Unique ambient music parameters per story |
| `scripts/generate_cover_svg.py` | AI-powered animated SVG cover generation |
| `scripts/sync_seed_data.py` | Sync content.json to seedData.js |
| `app/api/v1/admin.py` | Admin reload endpoint (hot-reload content without restart) |
| `app/services/local_store.py` | LocalStore with hot-reload support (reload_content, has_seed_changed) |
| `seed_output/content.json` | Master content file (backend) |
| `seed_output/content_expanded.json` | Generated content output |
| `seed_output/pipeline_state.json` | Pipeline checkpoint for crash-resume |
| `logs/pipeline_*.log` | Pipeline execution logs |
| `docs/CONTENT_GENERATION_GUIDELINES.md` | Content quality and diversity rules |
| `docs/AUDIO_GENERATION_GUIDELINES.md` | Audio generation specs |
| `docs/WORD_FIDELITY_QA_GUIDELINES.md` | QA pipeline specifications |
| `../dreamweaver-web/public/audio/pre-gen/` | Frontend audio files (copied from backend during sync) |
| `../dreamweaver-web/public/covers/` | Cover SVG illustrations |
| `../dreamweaver-web/public/covers/default.svg` | Fallback cover (dreamy night sky) |
| `../dreamweaver-web/public/covers/COVER_DESIGN_GUIDE.md` | SVG cover design system |

---

## Deploy Guard (MANDATORY)

> **⚠️ Full deploy instructions are in [`docs/DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md). Every deploy MUST follow that guide.**

Quick reference:
```bash
python3 scripts/deploy_guard.py snapshot   # BEFORE any deploy
# ... do the deploy ...
python3 scripts/deploy_guard.py verify     # AFTER — flags unintended changes
python3 scripts/deploy_guard.py check      # Quick health check (no snapshot needed)
```

---

## Deployment Flow

```
Pipeline generates content (runs daily at 2 AM IST, 1 story + 1 poem + 1 lullaby)
       │
       ├── PREFLIGHT: Warm Modal, test Mistral, check disk
       │
       ├── GENERATE → AUDIO → QA → ENRICH → COVERS
       │     (validates expected vs actual count — triggers PARTIAL if items missing)
       │
       ├── SYNC: content.json → seedData.js
       │         + copy audio MP3s to web/public/audio/pre-gen/
       │         + cover paths read from content.json (AI-generated or default.svg)
       │
       ├── PUBLISH (test):
       │     ├── git push backend → Render auto-deploys backend API
       │     │     (includes: seed_output/content.json, audio/ files)
       │     └── git push frontend → Vercel auto-deploys web app
       │           (includes: seedData.js, public/audio/pre-gen/*.mp3, public/covers/*.svg)
       │
       ├── DEPLOY PROD (GCP, zero-downtime):
       │     ├── Backend: POST /api/v1/admin/reload (hot-reload content from content.json)
       │     │     Falls back to docker restart if HTTP call fails
       │     └── Frontend: nginx serves /covers/ and /audio/ directly from public/
       │           (NO npm build, NO pm2 restart — files are already in public/)
       │
       ├── POSTFLIGHT: Cost estimate + disk usage
       │
       └── NOTIFY: Email sent (SUCCESS / PARTIAL / FAIL, with cost estimate)
```

**Pipeline deploys to both test (Render/Vercel) AND production (GCP)**. Production deploy is fully zero-downtime:
- **Backend**: hot-reloads content via admin API (serves new data immediately)
- **Frontend**: nginx serves `/covers/` and `/audio/` directly from `public/` via alias directives — new files are available instantly without any build or restart
- **seedData.js**: synced and pushed for Vercel test deployment, but production frontend fetches content from API at runtime

**IMPORTANT**: Never do `npm build` + `pm2 restart` for daily content updates. This causes downtime and is unnecessary. Only rebuild frontend for code changes (new components, CSS, etc.).

### Post-Pipeline Checklist (Spot-Check on Production)

The pipeline auto-deploys to production. These are spot-checks to verify everything worked:

1. **Appears first**: New story/poem shows at top of feed (requires `addedAt` in seedData.js — auto-generated by sync)
2. **NEW tag shows**: Pink "NEW" badge visible on the card (based on listening history — shows for unlistened content)
3. **Audio plays**: Tap play → hear audio in all voice variants
4. **Cover shows**: Story card has a custom SVG cover (not blank/default)
5. **Music is unique**: Ambient music sounds distinct from other stories
6. **Text is correct**: Story reads well, no garbled text or truncated content
7. **Categories correct**: Story appears in appropriate browse categories
8. **Check email status**: If PARTIAL (yellow), some items failed — review which types are missing

### Manual Content Deploy (if pipeline's deploy_prod step failed)

```bash
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

# Backend: pull latest content + hot-reload (zero-downtime)
cd /opt/dreamweaver-backend && git pull
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"

# Frontend: pull new covers/audio (nginx serves them directly — NO rebuild needed)
cd /opt/dreamweaver-web && git pull
# That's it! nginx serves /covers/ and /audio/ from public/ via alias directives.
```

### Full Frontend Rebuild (only for CODE changes, not content)

Only needed when JS/CSS/component code changes — never for daily content updates.

```bash
cd /opt/dreamweaver-web && git pull && npm run build
cp -r public .next/standalone/public && cp -r .next/static .next/standalone/.next/static
pm2 restart all
```

---

## Weekly Content Target

| Day | Stories | Poems | Lullabies | Total New Items |
|-----|---------|-------|-----------|-----------------|
| Mon | 1 | 1 | 1 | 3 |
| Tue | 1 | 1 | 1 | 3 |
| Wed | 1 | 1 | 1 | 3 |
| Thu | 1 | 1 | 1 | 3 |
| Fri | 1 | 1 | 1 | 3 |
| Sat | 1 | 1 | 1 | 3 |
| Sun | 1 | 1 | 1 | 3 |
| **Weekly** | **7** | **7** | **7** | **21** |
| **Monthly** | **~30** | **~30** | **~30** | **~90** |

**Monthly cost**: ~$36.53/mo total ($16.13 GCP cash + ~$20.40 Modal from free credits). Actual cash spend: **~$16.13/mo** (GCP VM + disk only). All text generation, covers, and email are $0 (free tiers).

---

## Funny Shorts (Before Bed Tab)

Shorts have a separate generation pipeline from stories/poems/lullabies.

### Generation Steps

Scripts can be run locally, but **mixing MUST happen on the GCP server** where base tracks and stings exist.

```bash
# 1. Generate scripts (Mistral AI) — can run locally or on server
python3 scripts/generate_funny_short.py --age 6-8 --auto

# 2. Generate audio chunks (Modal Chatterbox TTS) — can run locally or on server
python3 scripts/generate_funny_audio.py --short-id <id>

# 3. Mix audio (voice + base track + stings) — MUST run on GCP server
#    Base tracks: public/audio/funny-music/base-tracks/
#    Stings:      public/audio/funny-music/stings/
#    These only exist on the server, NOT in git. Mixing locally produces voice-only output.
python3 scripts/mix_funny_short.py --short-id <id>

# 4. Generate covers (Pollinations default, Together AI fallback)
python3 scripts/gen_missing_funny_covers.py
```

### Required Short Fields

Every funny short JSON MUST have:
- `host_intro` — one-line intro read before the short (e.g. "Tonight, Melody tries to steal a cake.")
- `host_outro` — one-line outro after the punchline (e.g. "Melody is wearing the cake. The cake is winning.")
- `base_track_style` — one of: `bouncy`, `sneaky`, `mysterious`, `gentle_absurd`, `whimsical`
- `comedy_type`, `format`, `voices`, `voice_combo`, `primary_voice`, `cover_description`, `premise_summary`

The generation script (`generate_funny_short.py`) produces `[HOST_INTRO:]` and `[HOST_OUTRO:]` tags — these get parsed into the JSON automatically.

### Hard Validation Rules (MUST pass before publishing)

**Full spec**: `docs/FUNNY_SHORTS_GENERATION_GUIDELINES.md`

1. **Max 8 stings per short** — count `[STING:]` tags in script
2. **Max 2 characters for ages 2-5** — NO trios for youngest age group
3. **Comedy type must be valid for age group** — e.g. no `physical_escalation` for 9-12
4. **Voices must be valid for age group** — e.g. no `high_pitch_cartoon` (Pip) for 9-12
5. **Every sentence must have `[DELIVERY: tag1, tag2]`** — drives emotional arcs via TTS params
6. **Must have `[PUNCHLINE]` tag** — triggers special voice params
7. **Must have `[HOST_INTRO:]` and `[HOST_OUTRO:]`** — for episode wrapping
8. **Format must include duos** — target 40% solo / 40% duo / 20% trio (not all solos+trios)
9. **No identical fingerprint in last 5** — comedy_type × format × voice_combo per age group

### Diversity Scheduler

**Full spec**: `docs/FUNNY_SHORTS_DIVERSITY_SCHEDULER.md`

When generating shorts with `--auto`, the scheduler picks the most underrepresented comedy_type × format × voice_combo for the given age group. This prevents template repetition (e.g. all villain_fails solos).

### Related Spec Documents

| Doc | What It Covers |
|-----|---------------|
| `docs/FUNNY_SHORTS_GENERATION_GUIDELINES.md` | **Start here** — all hard rules consolidated |
| `docs/FUNNY_SHORTS_SPEC.md` | Original spec — comedy structure, voices, age rules |
| `docs/FUNNY_SHORTS_DELIVERY_TAGS.md` | Delivery tag dictionary, multipliers, character arcs |
| `docs/FUNNY_SHORTS_DIVERSITY_SCHEDULER.md` | Fingerprint-based generation targeting |
| `docs/FUNNY_SHORTS_EPISODE_STRUCTURE.md` | Show jingles, host intro/outro, assembly pipeline |
| `docs/FUNNY_SHORTS_MUSIC_SPEC.md` | Base tracks, stings, sting-aware dialogue gaps |

### Mixing Requirements (CRITICAL)

- **NEVER mix locally** — base tracks and stings only exist on the GCP server at `/opt/dreamweaver-backend/public/audio/funny-music/`
- If you generate audio chunks locally, **scp** them to the server before mixing
- Verify mix output includes: base track placement, sting placement, and correct duration
- A properly mixed short should show: `Base track: base_<style>_XX.wav` and `Placed N/N stings`
- If it says "No base track found" or "Placed 0/N stings", the mix is **broken**

### Publishing & "New" Badge

- The frontend **Before Bed** page shows a **"NEW" badge** on shorts where `created_at` matches today's date (same pattern as regular content's `addedAt` in `ContentCard.js`)
- Shorts data lives in `data/funny_shorts/*.json` — the API serves them directly
- Audio files go to `public/audio/funny-shorts/`
- Covers go to `public/covers/funny-shorts/` — served by nginx from `/opt/dreamweaver-web/public/covers/` (same alias as regular covers)
- **IMPORTANT**: When generating new shorts for publication, ensure `created_at` is set to today's date so the "NEW" badge appears
- **No frontend rebuild needed** — shorts are API-served, covers/audio are nginx-served

### Publishing Checklist (CRITICAL)

After generating new shorts locally or on the server:

1. **Commit ALL generated assets to git** — data JSONs, audio MP3s, AND cover SVGs
2. **Push to remote** before deploying
3. On GCP: `git pull` then `docker-compose up -d --build`
4. After Docker rebuild: **verify covers still exist** with `ls public/covers/funny-shorts/`
5. If covers are missing: `git checkout -- public/covers/funny-shorts/` to restore them

**WHY**: Docker `COPY . /app` copies the repo at build time, but the running container doesn't write back to the host. If covers were generated on-server but not committed, `docker-compose down` + `up --build` wipes the build context. Always commit generated assets to git so `git checkout` can restore them.

**NEVER** generate covers only on the server without committing — they WILL be lost on next Docker rebuild.

### Cover Image Provider

- **Default**: Pollinations.ai (`image.pollinations.ai`) — free, no API key required
- **Fallback**: Together AI (`FLUX.1-schnell`) — requires `TOGETHER_API_KEY`
- Both `generate_funny_cover.py` and `gen_missing_funny_covers.py` use this order

### Episode Structure (Intro/Outro Wrapping)

Every funny short is wrapped in a "show" structure that makes Before Bed feel like a real audio show. The mixing script (`mix_funny_short.py`) automatically assembles the full episode:

```
[SHOW INTRO JINGLE]     ← 3.5s, static, same every episode
[HOST INTRO]            ← 3-5s, dynamic TTS (Melody voice reads one-sentence premise)
[CHARACTER JINGLES]     ← 2-4.5s, static, one per character in the short
[STORY]                 ← 60-90s, the funny short with base track + stings
[CHARACTER OUTRO]       ← 1-1.5s, static, primary character's sign-off jingle
[HOST OUTRO]            ← 2-4s, dynamic TTS (Melody voice reads one-sentence callback)
[SHOW OUTRO JINGLE]     ← 3.5s, static, same every episode
```

**Key requirements:**
- `host_intro` and `host_outro` are **TTS-generated** from text in the short JSON (Melody/musical_original voice via Modal Chatterbox)
- Jingle files are **static** — generated once, stored in `public/audio/jingles/` on the GCP server
- The mix script gracefully skips missing jingles (so shorts still work before jingles are generated)
- **Full spec**: `docs/FUNNY_SHORTS_EPISODE_STRUCTURE.md` (voice profiles, jingle MusicGen prompts, assembly pipeline)
- **Music spec**: `docs/FUNNY_SHORTS_MUSIC_SPEC.md` (base tracks, stings, sting-aware dialogue gaps)

### Static Jingle Files (One-Time Generation)

12 files stored in `public/audio/jingles/`:

| File | Duration | Purpose |
|------|----------|---------|
| `beforebed_intro_jingle.wav` | 3.5s | Show opener (glockenspiel ascending) |
| `beforebed_outro_jingle.wav` | 3.5s | Show closer (same melody descending) |
| `char_jingle_boomy_intro.wav` | 2.5s | Boomy entrance (tuba: dun dun DUNNN) |
| `char_jingle_boomy_outro.wav` | 1.5s | Boomy exit (tuba deflating) |
| `char_jingle_pip_intro.wav` | 2.0s | Pip entrance (xylophone run) |
| `char_jingle_pip_outro.wav` | 1.0s | Pip exit (xylophone bing) |
| `char_jingle_shadow_intro.wav` | 2.5s | Shadow entrance (celesta + gong) |
| `char_jingle_shadow_outro.wav` | 1.5s | Shadow exit (celesta fade) |
| `char_jingle_sunny_intro.wav` | 2.0s | Sunny entrance (toy piano) |
| `char_jingle_sunny_outro.wav` | 1.0s | Sunny exit (flat piano note) |
| `char_jingle_melody_intro.wav` | 2.5s | Melody entrance (harp flourish) |
| `char_jingle_melody_outro.wav` | 1.5s | Melody exit (harp glissando) |

Generate with MusicGen prompts from `docs/FUNNY_SHORTS_EPISODE_STRUCTURE.md`. These files are NOT in git — they live only on the server.
