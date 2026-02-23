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
  POSTFLIGHT → Cost estimate + disk usage summary
  NOTIFY     → Email via Resend (ALWAYS — success or failure)
```

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
SONGGEN_URL=https://anmol-71634--dreamweaver-songgen-sing.modal.run
SONGGEN_HEALTH=https://anmol-71634--dreamweaver-songgen-health.modal.run
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
**Subject**: `[OK] Dream Valley Pipeline — 2026-02-19 — 2 new items` or `[FAIL] Dream Valley Pipeline — 2026-02-19`

### Email Contents

| Field | Description |
|-------|-------------|
| Generated | Number of new stories/poems/lullabies generated (with per-type breakdown) |
| Audio QA | X passed, Y failed |
| Covers | X generated, Y fallback (default.svg) |
| Elapsed | Total pipeline run time |
| Cost Breakdown | Modal GPU (actual from elapsed time), GCP VM daily, total this run |
| Monthly Projection | Extrapolated from actual run cost × 30 |
| Disk | Total audio files + cover count |
| New Content | List of generated story/poem titles |
| Log tail (failure only) | Last 20 lines of the pipeline log |

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

## Known Limitations (Manual Steps)

| Step | Status | Notes |
|------|--------|-------|
| Production deploy | **Manual** | Pipeline publishes to Vercel/Render test only. GCP production deploy requires manual approval and `git pull && npm run build && pm2 restart`. |
| Content review | **Recommended** | While QA catches audio issues, human review of story text quality is recommended before production deploy. |
| Cover quality review | **Recommended** | AI-generated covers may occasionally need manual refinement. Check the Vercel test app. |

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
curl -s "https://anmol-71634--dreamweaver-chatterbox-health.modal.run" | python3 -m json.tool

# ACE-Step SongGen (lullabies)
curl -s "https://anmol-71634--dreamweaver-songgen-health.modal.run" | python3 -m json.tool
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
| `scripts/pipeline_run.py` | Main orchestrator (preflight → 7 steps → postflight → notify) |
| `scripts/pipeline_notify.py` | Email notifications via Resend API |
| `scripts/generate_content_matrix.py` | Story/poem generation with diversity matrix |
| `scripts/generate_audio.py` | Audio generation (Chatterbox TTS for stories/poems, ACE-Step for lullabies) |
| `scripts/qa_audio.py` | Audio QA (duration + fidelity) |
| `scripts/generate_music_params.py` | Unique ambient music parameters per story |
| `scripts/generate_cover_svg.py` | AI-powered animated SVG cover generation |
| `scripts/sync_seed_data.py` | Sync content.json to seedData.js |
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

## Deployment Flow

```
Pipeline generates content (runs daily at 2 AM IST, 1 story + 1 poem + 1 lullaby)
       │
       ├── PREFLIGHT: Warm Modal, test Mistral, check disk
       │
       ├── GENERATE → AUDIO → QA → ENRICH → COVERS
       │
       ├── SYNC: content.json → seedData.js
       │         + copy audio MP3s to web/public/audio/pre-gen/
       │         + cover paths read from content.json (AI-generated or default.svg)
       │
       ├── git push backend → Render auto-deploys backend API
       │     (includes: seed_output/content.json, audio/ files)
       │
       ├── git push frontend → Vercel auto-deploys web app
       │     (includes: seedData.js, public/audio/pre-gen/*.mp3, public/covers/*.svg)
       │
       ├── POSTFLIGHT: Cost estimate + disk usage
       │
       └── NOTIFY: Email sent (success or failure, with cost estimate)
                                     │
                          (User reviews on Vercel test app)
                                     │
                          (Once approved, deploy to GCP production)
```

**IMPORTANT**: The pipeline publishes to **test only** (Render/Vercel). Production deployment (GCP/dreamvalley.app) is manual and requires explicit approval.

### Post-Pipeline Checklist (Manual Review Before Production Deploy)

1. **Appears first**: New story/poem shows at top of feed (requires `addedAt` in seedData.js — auto-generated by sync)
2. **NEW tag shows**: Pink "NEW" badge visible on the card (based on listening history — shows for unlistened content)
3. **Audio plays**: Tap play → hear audio in all voice variants
4. **Cover shows**: Story card has a custom SVG cover (not blank/default)
5. **Music is unique**: Ambient music sounds distinct from other stories
6. **Text is correct**: Story reads well, no garbled text or truncated content
7. **Categories correct**: Story appears in appropriate browse categories

### Production Deploy (after review)

```bash
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

# Backend
cd /opt/dreamweaver-backend && git pull

# Frontend
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
