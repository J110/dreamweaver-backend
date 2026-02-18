# Dream Valley — Common Issues & Fixes

> **Purpose**: Quick reference for diagnosing and fixing issues found during pipeline runs and deployments. Gathered from real production incidents.

---

## Table of Contents

1. [Audio Not Playing on Deployed App](#1-audio-not-playing-on-deployed-app)
2. [Missing Cover Image (Blank Card)](#2-missing-cover-image-blank-card)
3. [Environment Variables Not Loading in Scripts](#3-environment-variables-not-loading-in-scripts)
4. [Mistral API Rate Limiting](#4-mistral-api-rate-limiting)
5. [Story Generation Fails (Only Poem Generated)](#5-story-generation-fails-only-poem-generated)
6. [Hindi Content Appearing When Not Wanted](#6-hindi-content-appearing-when-not-wanted)
7. [Audio QA Warns on Duration Outlier](#7-audio-qa-warns-on-duration-outlier)
8. [New Entry Not Found in seedData.js During Sync](#8-new-entry-not-found-in-seeddata-js-during-sync)
9. [Music Sounds the Same for All Stories](#9-music-sounds-the-same-for-all-stories)
10. [Git Push Fails in Pipeline](#10-git-push-fails-in-pipeline)
11. [Production Deploy Static Assets Missing](#11-production-deploy-static-assets-missing)
12. [Modal Endpoint Cold Start Timeout](#12-modal-endpoint-cold-start-timeout)

---

## 1. Audio Not Playing on Deployed App

**Symptom**: User sees "Could not load audio. Try again later." when trying to play a story.

**Root Cause**: Audio files exist only in `dreamweaver-backend/audio/pre-gen/` but NOT in `dreamweaver-web/public/audio/pre-gen/`. The Next.js frontend serves audio from its own `public/` directory. The backend's FastAPI `StaticFiles` mount is for the API, not the web app.

**Fix**:
```bash
# Copy audio files for a specific story (replace SHORT_ID with first 8 chars of story ID)
cp /path/to/dreamweaver-backend/audio/pre-gen/SHORT_ID*.mp3 \
   /path/to/dreamweaver-web/public/audio/pre-gen/

# Example for story gen-ae9ed8804fa7:
cp backend/audio/pre-gen/gen-ae9e*.mp3 web/public/audio/pre-gen/
```

**Prevention**: The pipeline's sync step (step 5) now auto-copies audio files for QA-passed stories. If you run audio generation manually outside the pipeline, remember to copy files to both locations.

**Verify**:
```bash
# Check both locations have the same files
ls backend/audio/pre-gen/gen-ae9e*.mp3
ls web/public/audio/pre-gen/gen-ae9e*.mp3
```

---

## 2. Missing Cover Image (Blank Card)

**Symptom**: Story card in the app shows just the title text overlaying a blank/purple card with no illustration.

**Root Cause**: `sync_seed_data.py` sets `cover: "/covers/default.svg"` for new entries. This file does NOT actually exist in `public/covers/`. The `hasRealCover()` function in the frontend detects this and tries to fall back to seed data — but if seed data also has `default.svg`, there's no valid fallback.

**Fix**:
1. Create a custom SVG cover following `COVER_DESIGN_GUIDE.md`
2. Place it in `dreamweaver-web/public/covers/your-cover-name.svg`
3. Register in COVERS constant in `seedData.js`
4. Update the story's `cover` field in `seedData.js`

**Quick Workaround** (use an existing unused cover temporarily):
```bash
# List unused covers (exist in public/covers/ but not referenced in seedData.js):
# captain-stardust.svg, owl-goodnight.svg, sailing-dreamland.svg,
# garden-whispers.svg, moon-lullaby.svg, brave-firefly.svg, twinkle-dream.svg
```

**Prevention**: Cover generation is currently manual. Each new story/poem needs a custom SVG created before production deploy. This is noted in the post-pipeline checklist.

---

## 3. Environment Variables Not Loading in Scripts

**Symptom**: Scripts fail with errors like `MISTRAL_API_KEY not found` or `KeyError: 'MODAL_TOKEN_ID'` even though `.env` file exists.

**Root Cause**: Not all scripts had `dotenv` loading. When run as subprocesses from `pipeline_run.py`, environment variables from the parent process ARE inherited, but when scripts are run standalone, they need their own dotenv loading.

**Fix**: Every script that reads environment variables must have this near the top:
```python
BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass  # pipeline_run.py or shell env should have set vars
```

**Verify all scripts have dotenv**:
```bash
grep -l "load_dotenv" scripts/*.py
# Should list: pipeline_run.py, generate_content_matrix.py, generate_audio.py,
#              qa_audio.py, generate_music_params.py, sync_seed_data.py
```

---

## 4. Mistral API Rate Limiting

**Symptom**: `429 Too Many Requests` error from Mistral API. Content generation produces fewer items than expected.

**Root Cause**: Mistral free experiment tier has a strict 2 requests/minute rate limit. The pipeline's 35-second delay between calls is usually sufficient but can still hit limits if multiple steps make rapid calls.

**Fix**:
- The pipeline already has a 35-second delay between generation calls
- If still hitting limits, increase the delay in `generate_content_matrix.py` (search for `time.sleep(35)`)
- Resume with `--resume` after the rate limit window passes

**Prevention**: Don't run multiple pipeline instances simultaneously. Use `--resume` after failures instead of restarting.

---

## 5. Story Generation Fails (Only Poem Generated)

**Symptom**: Pipeline requested 1 story + 1 poem but only the poem was generated. Log shows "New items generated: 1" instead of 2.

**Root Cause**: Mistral rate limiting caused the story generation API call to fail silently. The pipeline continued with just the poem.

**Fix**:
```bash
# Re-run just the generate step to get the missing story
python3 scripts/pipeline_run.py --step generate --count-stories 1 --count-poems 0
# Then resume the full pipeline
python3 scripts/pipeline_run.py --resume
```

---

## 6. Hindi Content Appearing When Not Wanted

**Symptom**: Hindi stories show up in seedData.js or on the app even though Hindi content isn't being served.

**Root Cause**:
- `sync_seed_data.py` defaults to `--lang en` but the pipeline or manual runs might not pass this flag
- `content.json` contains both English and Hindi stories from previous batch generations

**Fix**:
```bash
# Always use --lang en flag
python3 scripts/pipeline_run.py --lang en

# If Hindi entries leaked into seedData.js, manually remove them
# or re-run sync with explicit filter:
python3 scripts/sync_seed_data.py --lang en
```

**Prevention**: The pipeline defaults to `--lang en`. Don't use `--lang all` or `--lang hi` unless intentionally adding Hindi content.

---

## 7. Audio QA Warns on Duration Outlier

**Symptom**: QA report shows "WARN" for a variant with reason "duration_outlier (X% off)".

**Root Cause**: One voice variant's audio duration differs significantly from the median of all variants for that story. Threshold is typically 15-20%. This often happens with female_1 (slower/more expressive) or asmr (dramatic pauses).

**Impact**: Warning only — the variant still passes QA. Audio is usable but may feel noticeably longer/shorter than other voice options.

**Fix**: Usually no action needed. If the outlier is severe (>25% off):
```bash
# Regenerate just that variant
python3 scripts/generate_audio.py --story-id STORY_ID --voices female_1
```

---

## 8. New Entry Not Found in seedData.js During Sync

**Symptom**: Sync log shows "NOT FOUND in seedData.js: Story Title" for entries that should be updated.

**Root Cause**: Title mismatch between `content.json` and `seedData.js`. This is common with Hindi titles where transliteration varies, or when titles contain special characters (quotes, em-dashes).

**Fix**: The sync script matches by exact title string. Verify titles match:
```bash
# Check title in content.json
python3 -c "import json; data=json.load(open('seed_output/content.json')); print([s['title'] for s in data if 'keyword' in s['title'].lower()])"

# Compare with seedData.js
grep 'title:.*keyword' ../dreamweaver-web/src/utils/seedData.js
```

**For new entries**: If the title is a new story that doesn't exist in seedData.js yet, the `add_new_entries()` function handles it — but only for stories that have `audio_variants` (i.e., audio generation was completed).

---

## 9. Music Sounds the Same for All Stories

**Symptom**: Ambient music across different stories sounds identical (same melody, same key, same events).

**Root Cause**: `musicParams` contains template/default values. The `generate_music_params.py` script may have failed silently or returned generic values.

**How to Verify**:
```bash
# Check musicParams diversity in content.json
python3 -c "
import json
data = json.load(open('seed_output/content.json'))
for s in data[-5:]:
    mp = s.get('musicParams', {})
    print(f'{s[\"title\"][:30]:30s} key={mp.get(\"key\"):5s} pad={mp.get(\"padType\"):8s} events={[e[\"type\"] for e in mp.get(\"events\", [])]}')"
```

**Fix**: Re-run music params generation:
```bash
python3 scripts/generate_music_params.py --id STORY_ID
```

**Known template values to watch for**: `melodyInterval: 4000`, `bassInterval: 6000`, `counterInterval: 4500` — these are defaults that signal the generation failed.

---

## 10. Git Push Fails in Pipeline

**Symptom**: Pipeline completes all content steps but fails at publish with git authentication errors.

**Fix**:
```bash
# On the server, verify git credentials
cd /opt/dreamweaver-backend
git push origin main  # Test manually

# If auth fails, re-configure
git config credential.helper store
# Then do a manual push (enter GitHub PAT when prompted)
git push origin main
```

**For frontend repo**:
```bash
cd /opt/dreamweaver-web
git push origin main
```

---

## 11. Production Deploy Static Assets Missing

**Symptom**: After deploying to GCP production, CSS/images/audio don't load. Page looks broken.

**Root Cause**: Next.js standalone build does NOT auto-copy static assets. Step 4 of the deploy process is critical.

**Fix**:
```bash
cd /opt/dreamweaver-web
npm run build
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
pm2 restart all
```

**CRITICAL**: Never skip the `cp` commands after `npm run build`. This is the most common production deployment issue.

---

## 12. Modal Endpoint Cold Start Timeout

**Symptom**: First audio generation call takes >60s and may timeout. Subsequent calls are fast.

**Root Cause**: Modal serverless containers spin down after inactivity (~5 min). First call requires cold start: pulling container image + loading TTS model into GPU memory.

**Fix**:
```bash
# Warm up the endpoint before running the pipeline
curl -s "https://anmol-71634--dreamweaver-chatterbox-health.modal.run" | python3 -m json.tool
# Wait 5-10 seconds, then run the pipeline
```

**Prevention**: The pipeline could add a health check at the start of the audio step. Consider adding a warmup call in `step_audio()`.

---

## Quick Diagnostic Commands

```bash
# Check if .env is loaded
python3 -c "import os; from dotenv import load_dotenv; load_dotenv('.env'); print('MISTRAL_API_KEY:', 'set' if os.getenv('MISTRAL_API_KEY') else 'MISSING')"

# Count content items
python3 -c "import json; d=json.load(open('seed_output/content.json')); print(f'Total: {len(d)}, With audio: {sum(1 for s in d if s.get(\"audio_variants\"))}')"

# Check last pipeline state
cat seed_output/pipeline_state.json | python3 -m json.tool

# List recent logs
ls -lt logs/pipeline_*.log | head -3

# Verify audio files exist for a story
ls -la audio/pre-gen/gen-ae9e*

# Check Modal endpoint health
curl -s "https://anmol-71634--dreamweaver-chatterbox-health.modal.run"

# Check Mistral API connectivity
python3 -c "from mistralai import Mistral; import os; c=Mistral(api_key=os.environ['MISTRAL_API_KEY']); r=c.chat.complete(model='mistral-large-latest', messages=[{'role':'user','content':'ping'}], max_tokens=5); print('OK:', r.choices[0].message.content)"
```

---

*Last updated: 2026-02-18. Add new issues as they're discovered.*
