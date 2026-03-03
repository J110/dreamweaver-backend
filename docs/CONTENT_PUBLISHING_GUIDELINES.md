# Dream Valley — Content Publishing Guidelines

> **Purpose**: Prevent data loss, broken audio, and publishing errors when adding or modifying content. Covers both automated pipeline and manual publishing workflows.

---

## Golden Rules

1. **Audio files and seedData.js must always be in sync.** If seedData.js references an audio URL, the MP3 file MUST exist in `public/audio/pre-gen/`.
2. **Never modify seedData.js without verifying that referenced assets exist.** This includes audio files, cover SVGs, and any other referenced paths.
3. **NEVER do `npm build` + `pm2 restart` for daily content updates.** nginx serves `/covers/` and `/audio/` directly from `public/`. Backend hot-reloads content via admin reload or 60s polling. Only rebuild frontend for CODE changes (JS/CSS/components).
4. **Every content item MUST have `created_at` and `updated_at` as ISO strings.** Missing `created_at` crashes the entire API sort, making ALL content disappear. Always validate after manual edits.
5. **Audio files must exist in BOTH backend AND frontend `public/` directories.** nginx serves from frontend `public/`. Backend stores the source copies.
6. **NEVER remove audio files from `public/audio/pre-gen/` unless the corresponding seedData.js entries are also removed.** Orphan URLs → 404 errors → broken playback.

---

## Data Flow Overview

```
                    CONTENT PIPELINE (automated)
                    ============================

Backend                                         Frontend
────────────────────                           ────────────────────
seed_output/content.json  ─── sync_seed_data.py ───►  src/utils/seedData.js
audio/pre-gen/*.mp3       ─── step_sync copies  ───►  public/audio/pre-gen/*.mp3
                          ─── covers already in  ───►  public/covers/*.svg

                    PRODUCTION SERVING (nginx + backend)
                    =====================================

nginx (port 443) serves static files DIRECTLY from filesystem:
       │
       ├── /covers/  → alias /opt/dreamweaver-web/public/covers/  (30-day cache)
       ├── /audio/   → alias /opt/dreamweaver-web/public/audio/   (1-year cache, immutable)
       └── Everything else → proxy to Next.js standalone (port 3000)

Backend hot-reload (zero-downtime):
       │
       ├── HTTP POST /api/v1/admin/reload (primary, requires X-Admin-Key)
       ├── Background polling (safety net, every 60s, detects content.json mtime)
       └── Process restart (last resort, only for Python CODE changes)

⚠️  CRITICAL: Next.js standalone only serves files known at BUILD TIME.
    New covers/audio added after build get 404 from Next.js.
    nginx aliases bypass this — files are served directly from public/.

                    DAILY CONTENT DEPLOY (zero-downtime)
                    =====================================

1. Pipeline writes content.json, audio, covers to backend
2. Pipeline copies audio + covers to frontend public/
3. Backend: POST /api/v1/admin/reload → content live instantly
4. nginx: already serves /covers/ and /audio/ from public/ → no restart needed
5. NO npm build, NO pm2 restart

                    FULL FRONTEND REBUILD (CODE changes only)
                    ==========================================

Only when JS/CSS/component code changes:
1. cd /opt/dreamweaver-web && git pull
2. npm run build
3. cp -r public .next/standalone/public && cp -r .next/static .next/standalone/.next/static
4. pm2 restart all

                    MANUAL PUBLISHING
                    =================

1. Generate/create content → backend content.json
2. Generate audio files → backend audio/pre-gen/
3. Copy audio MP3s to frontend public/audio/pre-gen/
4. Copy cover SVGs to frontend public/covers/
5. Hot-reload backend: POST /api/v1/admin/reload
6. Verify on production (nginx serves new files immediately)
7. Run sync_seed_data.py → commit BOTH repos (for Vercel test site)
```

### Key Directories

| Location | What | Repo |
|----------|------|------|
| `dreamweaver-backend/seed_output/content.json` | Master content database | Backend |
| `dreamweaver-backend/audio/pre-gen/*.mp3` | Source audio files | Backend |
| `dreamweaver-web/src/utils/seedData.js` | Frontend content data (generated from content.json) | Frontend |
| `dreamweaver-web/public/audio/pre-gen/*.mp3` | Frontend audio files (copied from backend) | Frontend |
| `dreamweaver-web/public/covers/*.svg` | Cover illustrations | Frontend |

---

## Automated Pipeline Publishing

The daily pipeline (`pipeline_run.py`) handles everything automatically:

1. **Generate** → Creates story/poem/lullaby text
2. **Audio** → Generates MP3 variants via Chatterbox TTS
3. **QA** → Validates audio duration + fidelity
4. **Enrich** → Generates unique musicParams
5. **Covers** → Generates animated SVG covers
6. **Sync** → Writes seedData.js + copies audio/covers to frontend
7. **Publish** → `git push` both repos → Vercel/Render auto-deploy

**What the sync step does:**
- Runs `sync_seed_data.py` to convert content.json → seedData.js
- Copies audio MP3s from `backend/audio/pre-gen/` to `web/public/audio/pre-gen/`
- Git adds `seedData.js`, `public/audio/pre-gen/`, and `public/covers/`
- Commits and pushes both repos

**What the deploy_prod step does (after publish):**
- **Backend**: Calls `POST /api/v1/admin/reload` to hot-reload content in-memory (zero downtime). Falls back to process restart if HTTP call fails.
- **Frontend**: nginx serves `/covers/` and `/audio/` directly from `public/`. No build or restart needed.

**IMPORTANT**: The pipeline deploys content with ZERO downtime. No `npm build`, no `pm2 restart`. Content is live within seconds of the pipeline finishing.

---

## Manual Publishing Checklist

Use this checklist whenever you manually add, modify, or remove content.

### Adding New Content

- [ ] **Content exists in content.json** — story/poem text, metadata, audio_variants
- [ ] **Audio files exist in BOTH repos:**
  - `dreamweaver-backend/audio/pre-gen/{short_id}_*.mp3`
  - `dreamweaver-web/public/audio/pre-gen/{short_id}_*.mp3`
- [ ] **seedData.js has correct audio_variants** — each variant URL must map to an existing MP3
- [ ] **Cover SVG exists** (if custom) — `dreamweaver-web/public/covers/{slug}.svg`
- [ ] **seedData.js cover path is correct** — must match actual file in public/covers/
- [ ] **musicParams are set** — unique per story (not template values)
- [ ] **addedAt timestamp** — needed for "NEW" badge and sort order
- [ ] **Content appears in correct categories** — theme/type fields are valid

### Modifying Existing Content

- [ ] **Identify what changed** — text only? audio? cover? metadata?
- [ ] **If audio changed**: replace MP3s in BOTH repos (backend + frontend)
- [ ] **If cover changed**: update SVG and seedData.js cover path
- [ ] **If title changed**: update BOTH content.json and seedData.js
- [ ] **seedData.js entry matches content.json** — IDs, titles, audio paths all consistent

### Removing Content

- [ ] **Remove from content.json** (backend)
- [ ] **Remove from seedData.js** (frontend)
- [ ] **Remove audio files from BOTH repos** (backend + frontend)
- [ ] **Remove cover SVG** (if dedicated cover, not shared)
- [ ] **Verify no other content references the same audio/cover files**

---

## Common Pitfalls & How to Avoid Them

### 1. Audio URLs in seedData.js but MP3 Files Missing (THE LEO BUG)

**What happened**: seedData.js was updated with audio_variants pointing to `gen-9e87_*.mp3`, but the actual MP3 files were never committed to the frontend repo.

**Root cause**: Audio was either:
- Generated locally but not copied to `public/audio/pre-gen/`
- Deleted during a git operation (reset, clean, or overwrite)
- Only added to seedData.js manually without the corresponding files

**Prevention**:
```bash
# ALWAYS verify audio files exist before committing seedData.js changes
# Extract all audio URLs from seedData.js and check each one:
grep -oP '/audio/pre-gen/[^"]+\.mp3' src/utils/seedData.js | sort -u | while read url; do
  file="public${url}"
  if [ ! -f "$file" ]; then
    echo "MISSING: $file"
  fi
done
```

**Quick fix if it happens**:
```bash
# Option 1: Copy from backend repo (if files exist there)
cp dreamweaver-backend/audio/pre-gen/gen-XXXX_*.mp3 dreamweaver-web/public/audio/pre-gen/

# Option 2: Regenerate via Chatterbox TTS
# See "Manual Audio Regeneration" section below
```

### 2. seedData.js and content.json Out of Sync

**What happened**: Manual edits to seedData.js diverged from content.json, causing inconsistencies.

**Prevention**:
- Always use `sync_seed_data.py` to regenerate seedData.js from content.json
- If you must edit seedData.js manually, also update content.json
- After any manual edit, run the verification script (see below)

### 3. Missing `created_at` Crashes Entire API (THE SORT BUG)

**What happened**: A content item was missing its `created_at` field. The API's sort fallback used `datetime.utcnow()` (a datetime object) while all other items had ISO string timestamps. Python cannot compare datetime with str → `TypeError: '<' not supported` → the entire `/api/v1/content` endpoint returned 0 items, making ALL content disappear from the app.

**Root cause**: Content was added through a path that didn't set `created_at` (manual edit, broken script, etc.). One bad item breaks sorting for ALL items.

**Prevention**:
```bash
# Validate ALL items have created_at and updated_at before publishing
cd /opt/dreamweaver-backend
python3 -c "
import json
content = json.load(open('seed_output/content.json'))
for item in content:
    if not item.get('created_at'):
        print('MISSING created_at:', item.get('id'), '-', item.get('title'))
    if not item.get('updated_at'):
        print('MISSING updated_at:', item.get('id'), '-', item.get('title'))
"
```

**Quick fix if it happens**:
```bash
# Set created_at from updated_at (or current time) for items missing it
python3 -c "
import json
from datetime import datetime
for fname in ['data/content.json', 'seed_output/content.json']:
    content = json.load(open(fname))
    for item in content:
        if not item.get('created_at'):
            item['created_at'] = item.get('updated_at', datetime.now().isoformat())
        if not item.get('updated_at'):
            item['updated_at'] = item['created_at']
    json.dump(content, open(fname, 'w'), indent=2)
"
# Then hot-reload: POST /api/v1/admin/reload
```

### 4. Daily Content Deploy Does NOT Need Frontend Rebuild

**What happened**: `npm run build` + `pm2 restart` was run for daily content, causing unnecessary downtime and wasted time. Next.js standalone only serves files from build time — new covers/audio added after build get 404.

**How it works now**: nginx serves `/covers/` and `/audio/` directly from `public/` via alias directives. New files are available instantly. Backend hot-reloads content.json. No frontend rebuild or restart needed.

**Prevention**: NEVER run `npm build` or `pm2 restart` for daily content updates. Only rebuild for code changes (JS/CSS/component modifications).

### 5. New Stories Invisible on Home Page (THE TRENDING GAP)

**What happened**: New stories start with 0 views and 0 likes. The home page uses the `/api/v1/trending` endpoint sorted by `(likes × 5) + views`, with a limit. New stories with score=0 landed beyond the limit and were invisible, even though the API served them correctly.

**Root cause**: Home page requested `getTrending(40)` but there were 71+ items. All items with score=0 were at the end, and new items fell beyond position 40.

**Fix applied**: Changed `getTrending(40)` to `getTrending(100)` in `src/app/page.js`. This is a CODE change requiring a frontend rebuild.

**Prevention**: When total content count approaches the trending limit, increase the limit. Monitor after adding batches of content.

**Quick fix if a new story is invisible**: View it once via `curl https://api.dreamvalley.app/api/v1/content/STORY_ID` — this increments view_count to 1, moving it above other 0-score items.

### 7. Template musicParams (All Stories Sound the Same)

**What happened**: Stories generated with placeholder musicParams (melodyInterval:4000, bassInterval:6000) sound identical.

**Prevention**: Always check musicParams are unique before publishing:
```bash
# Check for duplicate/template musicParams
grep -c "melodyInterval.*4000" src/utils/seedData.js
# Should be 0 or very low. If high, musicParams need regeneration.
```

### 8. Hindi Title Mismatches

**What happened**: content.json and seedData.js had different Hindi titles for the same story ID.

**Prevention**: When syncing Hindi content, match by story ID, not title. Run sync_seed_data.py rather than manual copy-paste.

### 9. Default.svg Trap

**What happened**: API returns `"/covers/default.svg"` which is truthy but the file renders as a blank/generic cover.

**Prevention**: Use `hasRealCover()` utility function. Never treat `default.svg` as a valid custom cover.

### 10. Audio Files Deleted by Git Operations

**What happened**: `git checkout .`, `git clean -f`, or `git reset --hard` removed uncommitted audio files.

**Prevention**:
- ALWAYS commit audio files immediately after generating/copying them
- Never run destructive git commands without checking for uncommitted audio files first
- The pipeline should commit audio files in the same commit as seedData.js changes

---

## Manual Audio Regeneration

If audio files are missing or corrupted, regenerate them:

### Using the Pipeline Script (Preferred)

```bash
cd /opt/dreamweaver-backend

# Regenerate audio for a specific story
python3 scripts/generate_audio.py --story-id gen-XXXX --speed 0.8

# This generates 5 voice variants:
# gen-XXXX_female_1.mp3, gen-XXXX_female_2.mp3, gen-XXXX_female_3.mp3
# gen-XXXX_male_1.mp3, gen-XXXX_male_2.mp3

# Copy to frontend
cp audio/pre-gen/gen-XXXX_*.mp3 /opt/dreamweaver-web/public/audio/pre-gen/
```

### Using Chatterbox TTS Directly (Local Machine)

The Chatterbox TTS endpoint uses **GET** requests:

```bash
# URL format (note: GET, not POST)
curl -o output.mp3 "https://anmol-71634--dreamweaver-chatterbox-tts.modal.run?\
text=URL_ENCODED_STORY_TEXT&\
voice=female_1&\
exaggeration=0.4&\
cfg_weight=0.5&\
speed=0.85&\
format=mp3"
```

**Voice names**: `female_1`, `female_2`, `female_3`, `male_1`, `male_2`

**File naming**: `gen-{first8chars}_voice_name.mp3` → e.g., `gen-9e87_female_1.mp3`

**After regeneration, ALWAYS**:
1. Copy MP3s to frontend `public/audio/pre-gen/`
2. Verify seedData.js audio_variants match the file names
3. Commit and push both repos
4. Deploy to production

---

## Production Deployment Procedure

### A. Daily Content Deploy (zero-downtime, automated by pipeline)

No frontend rebuild needed. nginx serves new covers and audio directly from `public/`.

```bash
# SSH into production
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

# 1. Pull latest backend
cd /opt/dreamweaver-backend && git pull

# 2. Hot-reload backend (or wait 60s for auto-polling)
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"

# 3. Pull frontend (for new covers/audio in public/)
cd /opt/dreamweaver-web && git pull

# 4. Verify new content
curl -s http://localhost:8000/api/v1/content?page_size=3 | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('data', {}).get('items', [])
print('Total:', data.get('data', {}).get('total', 0))
for i in items:
    print(' -', i.get('title', '?'))
"

# That's it! NO npm build, NO pm2 restart.
# nginx serves /covers/ and /audio/ directly from public/.
```

> **IMPORTANT**: Never do `npm build` + `pm2 restart` for daily content updates.
> Only needed for CODE changes (see section B below).

### B. Full Frontend Rebuild (only for CODE changes)

Only when JS/CSS/component code changes — NOT for new stories/covers/audio.

```bash
# SSH into production
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

cd /opt/dreamweaver-web && git pull
npm run build
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
pm2 restart all
```

### Pre-Deploy Validation

Run these checks BEFORE any deploy to catch data issues:

```bash
cd /opt/dreamweaver-backend

# 1. Verify ALL items have required timestamp fields
python3 -c "
import json
content = json.load(open('seed_output/content.json'))
errors = 0
for item in content:
    sid = item.get('id', '?')
    if not item.get('created_at'):
        print('MISSING created_at:', sid, '-', item.get('title'))
        errors += 1
    if not item.get('updated_at'):
        print('MISSING updated_at:', sid, '-', item.get('title'))
        errors += 1
print('Checked %d items, %d errors' % (len(content), errors))
"

# 2. Verify audio files exist in frontend public/
cd /opt/dreamweaver-web
python3 -c "
import json, os
content = json.load(open('/opt/dreamweaver-backend/seed_output/content.json'))
missing = 0
for item in content:
    for av in (item.get('audio_variants') or []):
        url = av.get('url', '') if isinstance(av, dict) else ''
        if url:
            path = 'public' + url
            if not os.path.exists(path):
                print('MISSING:', path, '(' + item.get('title', '?') + ')')
                missing += 1
print('Missing audio files:', missing)
"

# 3. Verify cover files exist
python3 -c "
import json, os
content = json.load(open('/opt/dreamweaver-backend/seed_output/content.json'))
missing = 0
for item in content:
    cover = item.get('cover', '')
    if cover and cover != '/covers/default.svg':
        path = 'public' + cover
        if not os.path.exists(path):
            print('MISSING:', path, '(' + item.get('title', '?') + ')')
            missing += 1
print('Missing cover files:', missing)
"
```

### Post-Deploy Verification

1. **Open https://dreamvalley.app** — home page loads
2. **Play a story** — audio plays correctly
3. **Check new content** — appears at top of feed
4. **Test all voice variants** — each voice sounds different
5. **Check covers** — custom SVG covers render correctly
6. **Test on mobile** — touch controls work, background audio works

---

## Rollback Procedure

If a deploy breaks production:

### Quick Rollback (< 2 minutes)

```bash
# SSH into production
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

cd /opt/dreamweaver-web

# Find the last known good commit
git log --oneline -10

# Revert to that commit
git checkout <GOOD_COMMIT_HASH>

# Rebuild and restart
npm run build
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
pm2 restart all
```

### Backend Rollback

```bash
cd /opt/dreamweaver-backend
git log --oneline -10
git checkout <GOOD_COMMIT_HASH>

# Content changes: hot-reload picks up the reverted content.json within 60s
# Or force immediate reload:
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"

# Code changes: Docker restart needed only if you changed Python code
sudo docker compose down && sudo docker compose up -d --build
```

---

## Content Verification Script

Save this as `scripts/verify_content.sh` and run before any production deploy:

```bash
#!/bin/bash
# Verify all content references are valid before deploying
# Usage: cd dreamweaver-web && bash ../dreamweaver-backend/scripts/verify_content.sh

ERRORS=0

echo "🔍 Dream Valley Content Verification"
echo "========================================"

# Check 1: Audio files referenced in seedData.js
echo ""
echo "📻 Checking audio files..."
MISSING_AUDIO=$(grep -oP '/audio/pre-gen/[^"]+\.mp3' src/utils/seedData.js | sort -u | while read url; do
  file="public${url}"
  if [ ! -f "$file" ]; then
    echo "$file"
  fi
done)

if [ -n "$MISSING_AUDIO" ]; then
  echo "❌ MISSING AUDIO FILES:"
  echo "$MISSING_AUDIO"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ All audio files present"
fi

# Check 2: Cover SVGs referenced in seedData.js
echo ""
echo "🎨 Checking cover files..."
MISSING_COVERS=$(grep -oP '/covers/[^"]+\.svg' src/utils/seedData.js | sort -u | while read url; do
  if [ "$url" = "/covers/default.svg" ]; then continue; fi
  file="public${url}"
  if [ ! -f "$file" ]; then
    echo "$file"
  fi
done)

if [ -n "$MISSING_COVERS" ]; then
  echo "❌ MISSING COVER FILES:"
  echo "$MISSING_COVERS"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ All cover files present"
fi

# Check 3: Audio file sizes (detect 0-byte files)
echo ""
echo "📏 Checking audio file sizes..."
EMPTY_AUDIO=$(find public/audio/pre-gen/ -name "*.mp3" -size 0 2>/dev/null)
if [ -n "$EMPTY_AUDIO" ]; then
  echo "❌ EMPTY AUDIO FILES (0 bytes):"
  echo "$EMPTY_AUDIO"
  ERRORS=$((ERRORS + 1))
else
  echo "✅ No empty audio files"
fi

# Check 4: Total audio count
TOTAL_AUDIO=$(find public/audio/pre-gen/ -name "*.mp3" 2>/dev/null | wc -l)
TOTAL_REFS=$(grep -oP '/audio/pre-gen/[^"]+\.mp3' src/utils/seedData.js | sort -u | wc -l)
echo ""
echo "📊 Audio stats: $TOTAL_AUDIO files on disk, $TOTAL_REFS unique references in seedData.js"

# Summary
echo ""
echo "========================================"
if [ $ERRORS -eq 0 ]; then
  echo "✅ All checks passed! Safe to deploy."
else
  echo "❌ $ERRORS check(s) FAILED. Fix issues before deploying."
  exit 1
fi
```

---

## Quick Reference: File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Story ID | `gen-{12-char-hex}` | `gen-9e87531b7db6` |
| Audio file | `gen-{first8}_{voice}.mp3` | `gen-9e87_female_1.mp3` |
| Cover SVG | `{slug}.svg` | `leo-moonlight-waves.svg` |
| Voice names | `female_1`, `female_2`, `female_3`, `male_1`, `male_2` | — |

### Audio Variants per Content Type

| Type | Voices | Total Files |
|------|--------|-------------|
| Story | female_1, female_2, female_3, male_1, male_2 | 5 |
| Poem | female_1, female_2, female_3, male_1, male_2 | 5 |
| Lullaby (song) | Generated via ACE-Step (single variant) | 1-3 |

---

## Emergency: Content is Broken on Production

### Audio not playing (404 errors)

1. Check browser console for the exact 404 URL
2. SSH into production: `ls /opt/dreamweaver-web/public/audio/pre-gen/` (nginx serves from HERE, not `.next/standalone/`)
3. If file missing from `public/`: copy from backend `audio/pre-gen/` or regenerate
4. If file missing everywhere: regenerate via Chatterbox TTS (see above)
5. Check nginx is serving: `curl -I https://dreamvalley.app/audio/pre-gen/FILENAME.mp3`

### Story showing wrong/no cover

1. Check content.json for the story's `cover` field
2. Verify SVG file exists in `public/covers/` (nginx serves from HERE)
3. If missing: regenerate with FLUX: `python3 scripts/generate_cover_experimental.py --story-json <file>`
4. Hot-reload backend: `POST /api/v1/admin/reload`

### Story appearing but with no audio options

1. Check content.json for `audio_variants` field
2. If empty/missing: run audio generation → copy MP3s to frontend `public/audio/pre-gen/`
3. If populated but audio 404: check files exist in `public/audio/pre-gen/` (see above)

### ALL content disappeared from the app

1. Check API directly: `curl -s http://localhost:8000/api/v1/content?page_size=1`
2. If error mentions `datetime` or `'<' not supported`: a content item is missing `created_at`
3. Fix: find and add the missing field (see Pitfall #3 above)
4. Hot-reload backend after fixing

---

## Summary: What to Do When...

| Scenario | Steps |
|----------|-------|
| Pipeline ran successfully | Content is live automatically (zero-downtime deploy). Verify on dreamvalley.app |
| Pipeline reported PARTIAL | Check email for FLUX vs Mistral breakdown. Missing items failed at audio/generation. Re-run: `pipeline_run.py --resume` |
| Pipeline failed at audio | Check Modal credits/health → Resume: `pipeline_run.py --resume` |
| Pipeline failed at sync | Check content.json validity → Re-run: `pipeline_run.py --step sync` |
| ALL content disappeared from app | Check API: `curl localhost:8000/api/v1/content`. If error mentions datetime/sort → missing `created_at` on an item. See Pitfall #3 |
| Need to add content manually | Edit content.json (MUST include `created_at`) → Copy audio/covers to frontend `public/` → Hot-reload backend |
| Need to regenerate audio | `generate_audio.py --story-id X` → Copy MP3s to frontend `public/audio/pre-gen/` → Hot-reload backend |
| Need to regenerate a cover | `generate_cover_experimental.py --story-json <file>` → Cover auto-copied to frontend `public/covers/` → Hot-reload backend |
| Audio 404 on production | Check file exists in `public/audio/pre-gen/` (nginx serves from there, NOT from `.next/standalone/`) |
| Cover 404 on production | Check file exists in `public/covers/` (nginx serves from there, NOT from `.next/standalone/`) |
| Backend content stale | `curl -X POST localhost:8000/api/v1/admin/reload -H "X-Admin-Key: KEY"` or wait 60s for polling |
| Need to rollback | `git checkout <good-commit>` → Backend auto-reloads content. Frontend covers/audio: nginx serves from `public/` (no rebuild needed) |
