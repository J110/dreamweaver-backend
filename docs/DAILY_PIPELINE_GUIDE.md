# Dream Valley — Daily Content Pipeline Guide

> **Purpose**: Automate daily publication of new bedtime stories and poems with zero manual intervention. Runs entirely on the GCP production server with no local device dependencies.

---

## Architecture Overview

```
GCP VM (dreamvalley-prod) runs pipeline_run.py daily via cron:

  1. GENERATE  → Mistral Large (free tier)         → 1 story + 1 poem
  2. AUDIO GEN → Modal Chatterbox TTS (free $30/mo) → 14 MP3 files
  3. AUDIO QA  → Voxtral transcription (free tier)  → PASS/FAIL
  4. ENRICH    → Mistral Large (free tier)          → unique musicParams
  5. SYNC      → content.json → seedData.js
  6. PUBLISH   → git push → Render/Vercel auto-deploy
  7. LOG       → pipeline summary → logs/
```

### Cost per Run: ~$0.43 from free Modal credits, $0.00 elsewhere

| Step | Service | Cost |
|------|---------|------|
| Content generation | Mistral Large (free experiment tier) | $0.00 |
| Audio generation (14 variants) | Modal T4 GPU (~43.5 GPU-min) | ~$0.43 (free credits) |
| Audio QA (transcription + fidelity) | Voxtral via Mistral API (free tier) | $0.00 |
| Music params | Mistral Large (free tier) | $0.00 |
| **Monthly at daily cadence** | | **~$13 from $30 free credits** |

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
pip3 install mistralai httpx pydub
```

### 4. Set Environment Variables

Create `/opt/dreamweaver-backend/.env`:

```env
# Mistral AI — free experiment tier (text generation + QA + music params)
MISTRAL_API_KEY=your_mistral_api_key_here

# Modal — Chatterbox TTS endpoint (auto-deployed, no token needed for HTTP calls)
# The Modal endpoint URL is baked into generate_audio.py
# Voice references are stored in Modal persistent volume (already uploaded)
```

**Getting your Mistral API key:**
1. Go to https://console.mistral.ai/
2. Create an account (no credit card required)
3. Go to API Keys → Create new key
4. Free experiment tier: 1B tokens/month, 2 req/min

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

### 8. Set Up Daily Cron

```bash
crontab -e
```

Add this line to run the pipeline daily at 2:00 AM IST:

```cron
0 2 * * * cd /opt/dreamweaver-backend && /usr/bin/python3 scripts/pipeline_run.py --lang en >> /opt/dreamweaver-backend/logs/cron.log 2>&1
```

---

## Running the Pipeline

### Full Run (Default: 1 story + 1 poem)

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
python3 scripts/pipeline_run.py --count-stories 3 --count-poems 2 --lang en
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
python3 scripts/pipeline_run.py --step sync        # Only seed data sync
python3 scripts/pipeline_run.py --step publish     # Only git push
```

### Skip Publishing (Test Mode)

```bash
python3 scripts/pipeline_run.py --skip-publish
```

---

## Server Independence

The pipeline is fully self-contained on the GCP server. No local machine dependencies:

| Dependency | Where It Lives | How Accessed |
|------------|---------------|--------------|
| Voice references | Modal persistent volume (`/data/voices/`) | Via HTTP (Chatterbox endpoint) |
| Content files | GCP VM (`/opt/dreamweaver-backend/seed_output/`) | Local filesystem |
| Audio files | GCP VM (`/opt/dreamweaver-backend/audio/pre-gen/`) | Local filesystem |
| Mistral AI | Cloud API | HTTP (MISTRAL_API_KEY in .env) |
| Modal TTS | Cloud endpoint | HTTP (no local GPU needed) |
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
| Modal endpoint cold start | First call takes ~60s. Health check warms it up. |
| Modal credits exhausted | Check https://modal.com/billing. $30/mo free. |
| Audio QA fails | Check fidelity scores in logs. May need to regenerate audio. |
| Git push fails | Check SSH keys / GitHub token. Run `git push` manually. |
| `content.json` corrupt | Restore from git: `git checkout -- seed_output/content.json` |

### Modal Health Check

```bash
curl -s "https://anmol-71634--dreamweaver-chatterbox-health.modal.run" | python3 -m json.tool
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
| `scripts/pipeline_run.py` | Main orchestrator (this pipeline) |
| `scripts/generate_content_matrix.py` | Story/poem generation with diversity matrix |
| `scripts/generate_audio.py` | Chatterbox TTS audio generation |
| `scripts/qa_audio.py` | Audio QA (duration + fidelity) |
| `scripts/generate_music_params.py` | Unique ambient music parameters per story |
| `scripts/sync_seed_data.py` | Sync content.json to seedData.js |
| `seed_output/content.json` | Master content file (backend) |
| `seed_output/content_expanded.json` | Generated content output |
| `seed_output/pipeline_state.json` | Pipeline checkpoint for crash-resume |
| `logs/pipeline_*.log` | Pipeline execution logs |
| `docs/CONTENT_GENERATION_GUIDELINES.md` | Content quality and diversity rules |
| `docs/AUDIO_GENERATION_GUIDELINES.md` | Audio generation specs |
| `docs/WORD_FIDELITY_QA_GUIDELINES.md` | QA pipeline specifications |

---

## Deployment Flow

```
Pipeline generates content
       │
       ├── git push backend → Render auto-deploys backend API
       │
       └── git push frontend → Vercel auto-deploys web app
                                     │
                          (User reviews on Vercel test app)
                                     │
                          (Once approved, deploy to GCP production)
```

**IMPORTANT**: The pipeline publishes to **test only** (Render/Vercel). Production deployment (GCP/dreamvalley.app) is manual and requires explicit approval.

---

## Weekly Content Target

| Day | Stories | Poems | Total New Items |
|-----|---------|-------|-----------------|
| Mon | 1 | 1 | 2 |
| Tue | 1 | 1 | 2 |
| Wed | 1 | 1 | 2 |
| Thu | 1 | 1 | 2 |
| Fri | 1 | 1 | 2 |
| Sat | 0 | 0 | 0 (off) |
| Sun | 0 | 0 | 0 (off) |
| **Weekly** | **5** | **5** | **10** |
| **Monthly** | **~22** | **~22** | **~44** |

At daily cadence: ~$13/month in Modal free credits. All text generation is $0 (Mistral free tier).
