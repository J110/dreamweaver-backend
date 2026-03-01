# Dream Valley — Content Publishing Guidelines

> **Purpose**: Prevent data loss, broken audio, and publishing errors when adding or modifying content. Covers both automated pipeline and manual publishing workflows.

---

## Golden Rules

1. **Audio files and seedData.js must always be in sync.** If seedData.js references an audio URL, the MP3 file MUST exist in `public/audio/pre-gen/`.
2. **Never modify seedData.js without verifying that referenced assets exist.** This includes audio files, cover SVGs, and any other referenced paths.
3. **Backend content hot-reloads automatically; frontend still needs a manual production deploy.** The backend detects new `seed_output/content.json` via background polling (60s) or the admin reload endpoint — no Docker restart needed. But the frontend still needs `git pull && npm run build && cp static && pm2 restart` on GCP.
4. **Production frontend deploy is MANUAL and separate.** Pipeline auto-deploys to Vercel/Render (test). GCP production frontend requires explicit approval and manual deploy steps.
5. **NEVER remove audio files from `public/audio/pre-gen/` unless the corresponding seedData.js entries are also removed.** Orphan URLs → 404 errors → broken playback.

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

                    BACKEND HOT-RELOAD (zero-downtime)
                    ===================================

Pipeline writes seed_output/content.json
       │
       ├── HTTP POST /api/v1/admin/reload (primary)
       │     Requires X-Admin-Key header
       │     Re-reads content/subscriptions/voices in-memory
       │
       ├── Background polling (safety net, every 60s)
       │     Detects content.json mtime change → auto-reload
       │
       └── Docker restart (last resort fallback)
             Only if HTTP reload AND polling both fail

                    MANUAL PUBLISHING
                    =================

1. Generate/create content → backend content.json
2. Generate audio files → backend audio/pre-gen/
3. Run sync_seed_data.py OR manually edit seedData.js
4. Copy audio MP3s to frontend public/audio/pre-gen/
5. Copy cover SVGs to frontend public/covers/
6. Commit BOTH repos
7. Deploy to test (Vercel/Render auto-deploy on push)
8. Verify on test
9. Deploy to GCP production (manual)
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
- **Backend**: Calls `POST /api/v1/admin/reload` to hot-reload content in-memory (zero downtime). Falls back to `docker restart` if the HTTP call fails.
- **Frontend**: Runs `npm run build`, copies static assets, restarts PM2.

**IMPORTANT**: The pipeline auto-deploys frontend to GCP production and hot-reloads the backend. Content is live within minutes of the pipeline finishing.

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

### 3. Production Deploys Without Static Asset Copy

**What happened**: `npm run build` creates `.next/standalone/` but does NOT copy `public/` or `.next/static/`. Without step 4 (`cp -r public ...`), audio files and covers are missing.

**Prevention**: ALWAYS run the full deploy sequence:
```bash
cd /opt/dreamweaver-web
git pull
npm run build
cp -r public .next/standalone/public          # CRITICAL
cp -r .next/static .next/standalone/.next/static  # CRITICAL
pm2 restart all
```

### 4. Template musicParams (All Stories Sound the Same)

**What happened**: Stories generated with placeholder musicParams (melodyInterval:4000, bassInterval:6000) sound identical.

**Prevention**: Always check musicParams are unique before publishing:
```bash
# Check for duplicate/template musicParams
grep -c "melodyInterval.*4000" src/utils/seedData.js
# Should be 0 or very low. If high, musicParams need regeneration.
```

### 5. Hindi Title Mismatches

**What happened**: content.json and seedData.js had different Hindi titles for the same story ID.

**Prevention**: When syncing Hindi content, match by story ID, not title. Run sync_seed_data.py rather than manual copy-paste.

### 6. Default.svg Trap

**What happened**: API returns `"/covers/default.svg"` which is truthy but the file renders as a blank/generic cover.

**Prevention**: Use `hasRealCover()` utility function. Never treat `default.svg` as a valid custom cover.

### 7. Audio Files Deleted by Git Operations

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

### Pre-Deploy Verification

Run these checks BEFORE deploying to production:

```bash
cd /opt/dreamweaver-web

# 1. Verify all referenced audio files exist
echo "=== Checking audio file references ==="
grep -oP '/audio/pre-gen/[^"]+\.mp3' src/utils/seedData.js | sort -u | while read url; do
  file="public${url}"
  if [ ! -f "$file" ]; then
    echo "❌ MISSING: $file"
  fi
done
echo "=== Done ==="

# 2. Verify all referenced cover files exist
echo "=== Checking cover references ==="
grep -oP '/covers/[^"]+\.svg' src/utils/seedData.js | sort -u | while read url; do
  file="public${url}"
  if [ "$url" != "/covers/default.svg" ] && [ ! -f "$file" ]; then
    echo "❌ MISSING: $file"
  fi
done
echo "=== Done ==="

# 3. Check build succeeds
npm run build
echo "Build exit code: $?"
```

### Deploy Steps

```bash
# SSH into production
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

# 1. Pull latest backend (content hot-reloads automatically via 60s polling)
cd /opt/dreamweaver-backend && git pull
# Content will auto-reload within 60s. To force immediate reload:
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"

# 2. Pull and build frontend
cd /opt/dreamweaver-web && git pull

# 3. Build frontend
npm run build

# 4. CRITICAL: Copy static assets to standalone
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static

# 5. Restart frontend
pm2 restart all

# 6. Verify
curl -s https://dreamvalley.app | head -20  # Should return HTML
curl -s -o /dev/null -w "%{http_code}" https://dreamvalley.app/audio/pre-gen/SOME_KNOWN_FILE.mp3
# Should return 200
```

> **Note**: The backend no longer needs a Docker restart for content changes. The `git pull` updates `seed_output/content.json`, and the background polling task detects the new mtime within 60 seconds. Only Docker restart if you changed backend Python code.

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
2. SSH into production: `ls /opt/dreamweaver-web/.next/standalone/public/audio/pre-gen/`
3. If file missing from standalone but exists in `public/`: re-run `cp -r public .next/standalone/public`
4. If file missing from `public/`: copy from backend repo or regenerate
5. If file missing everywhere: regenerate via Chatterbox TTS (see above)

### Story showing wrong/no cover

1. Check seedData.js cover path for the story
2. Verify SVG file exists in `public/covers/`
3. If missing, check if pipeline generated it → `git log -- public/covers/`
4. Regenerate: `python3 scripts/generate_cover_svg.py --id STORY_ID`

### Story appearing but with no audio options

1. Check seedData.js for `audio_variants` field
2. If empty/missing: content.json may not have audio URLs → run audio generation
3. If populated but audio fails: check MP3 files exist (see above)

---

## Summary: What to Do When...

| Scenario | Steps |
|----------|-------|
| Pipeline ran successfully | Backend auto-reloads content. Review frontend on Vercel → Deploy frontend to GCP production |
| Pipeline reported PARTIAL | Check email for expected vs actual count. Missing items failed at generation (likely Mistral flakiness). Re-run: `pipeline_run.py --resume` |
| Pipeline failed at audio | Check Modal credits/health → Resume: `pipeline_run.py --resume` |
| Pipeline failed at sync | Check content.json validity → Re-run: `pipeline_run.py --step sync` |
| Need to add content manually | Edit content.json → Backend auto-reloads (60s) or call admin reload → Run sync → Copy audio/covers → Commit frontend → Deploy frontend |
| Need to regenerate audio | `generate_audio.py --story-id X` → Copy MP3s to frontend → Commit → Deploy |
| Need to regenerate a cover | `generate_cover_svg.py --id X` → Commit frontend → Deploy |
| Audio 404 on production | Verify files in standalone/public → `cp -r public .next/standalone/public` → `pm2 restart all` |
| seedData.js looks wrong | Regenerate: `python3 scripts/sync_seed_data.py --lang en` → Commit → Deploy |
| Backend content stale | `curl -X POST localhost:8000/api/v1/admin/reload -H "X-Admin-Key: KEY"` or wait 60s for polling |
| Need to rollback | `git checkout <good-commit>` → Backend auto-reloads content. Frontend: Rebuild → Copy static → Restart |
