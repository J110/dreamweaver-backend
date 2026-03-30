# Dream Valley — Deploy Guide

> **Every deploy must follow this guide. No exceptions.**

This guide covers ALL types of deploys: daily pipeline, backend code changes, frontend code changes, manual content fixes, and Docker rebuilds.

---

## The Golden Rule

> **Only change what you specifically intend to change. Everything else must remain identical.**

Past incidents from violating this rule:
- Hindi stories reappearing after Docker rebuild (LocalStore merged them back from seed)
- Silly songs disappearing (metadata had `audio_file: null`, filtered out by API)
- Extra funny shorts appearing (8 per age group instead of 6)
- Audio files lost after git re-clone (audio is gitignored)

---

## Deploy Guard (MANDATORY)

Every deploy — Docker rebuild, git pull, admin reload, frontend rebuild — **must** use deploy guard.

### Before ANY Deploy

```bash
python3 scripts/deploy_guard.py snapshot
```

Captures: all story IDs/titles/languages/audio status, funny shorts per age group, silly songs per age group.

### After EVERY Deploy

```bash
python3 scripts/deploy_guard.py verify
```

Compares current state against snapshot. Flags every difference:
- Stories added or removed
- Stories that lost audio or covers
- New languages appearing (e.g. Hindi mixed into English)
- Funny shorts count changing
- Silly songs losing audio

**If you see ANY unintended change, roll back immediately.**

### Quick Consistency Check (no snapshot needed)

```bash
python3 scripts/deploy_guard.py check
```

Validates: no Hindi stories, 6 funny shorts per age group, 1 silly song per age group with audio.

---

## Deploy Types

### 1. Daily Content (Pipeline — Zero Downtime)

The daily pipeline (`pipeline_run.py`) handles this automatically. Deploy guard is integrated — it snapshots before and verifies after.

**What it does**: Adds new stories/poems/lullabies. Hot-reloads backend via admin API. nginx serves new covers/audio from `public/` instantly.

**What it does NOT do**: Frontend rebuild, PM2 restart, Docker restart. None of these are needed for daily content.

```bash
# Manual trigger (if pipeline didn't run)
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"
python3 scripts/deploy_guard.py verify
```

### 2. Backend Code Changes

For changes to Python code (API endpoints, services, scripts).

```bash
python3 scripts/deploy_guard.py snapshot          # BEFORE

cd /opt/dreamweaver-backend
git pull origin main                               # NO sudo — prevents ownership issues
sudo docker-compose down
sudo docker-compose up -d --build
sleep 10                                           # Wait for container startup

python3 scripts/deploy_guard.py verify            # AFTER
```

**Critical notes**:
- `git pull` alone does NOT update the running code — Docker must be rebuilt
- NEVER use `sudo git pull` — changes file ownership, breaks pipeline cron
- If you accidentally used sudo: `sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-backend/`

### 3. Frontend Code Changes

For changes to JS/CSS/component code (NOT needed for new content).

```bash
python3 scripts/deploy_guard.py snapshot          # BEFORE

cd /opt/dreamweaver-web
git pull origin main                               # NO sudo
sudo npm run build
sudo cp -r public .next/standalone/public
sudo cp -r .next/static .next/standalone/.next/static
sudo pm2 restart dreamweaver-web

python3 scripts/deploy_guard.py verify            # AFTER
```

**When NOT to rebuild frontend**: Adding new stories, covers, or audio. nginx serves these directly from `public/` via alias directives.

### 4. Content Data Fixes (Removing/Editing Stories)

For manually editing `content.json`, `data/funny_shorts/`, or `data/silly_songs/`.

```bash
python3 scripts/deploy_guard.py snapshot          # BEFORE

# Edit the files
vim data/content.json                              # or data/funny_shorts/*.json etc.

# For content.json changes: Docker restart required (LocalStore loads on startup)
sudo docker-compose restart

# For funny_shorts/silly_songs: Docker restart required (loaded from filesystem)
sudo docker-compose restart

python3 scripts/deploy_guard.py verify            # AFTER
```

**Warning — LocalStore is add-only on reload**:
- `POST /admin/reload` only ADDS items from seed, never removes
- To actually REMOVE a story: edit `data/content.json` AND restart Docker
- The seed file (`seed_output/content.json`) will re-add items on next reload if not also cleaned

### 5. Recovering from Audio/Cover Loss

```bash
# Check what's missing
python3 scripts/deploy_guard.py check

# Recover audio from persistent store
curl -s -X POST https://api.dreamvalley.app/api/v1/analytics/content-audit/recover \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)"

# Recover covers from persistent store
curl -s -X POST https://api.dreamvalley.app/api/v1/analytics/content-audit/covers/recover \
  -H "Authorization: Bearer $(grep ANALYTICS_KEY .env | cut -d= -f2)"
```

---

## What Survives What

| Event | Stories | Audio | Covers | Funny Shorts | Silly Songs |
|-------|---------|-------|--------|-------------|-------------|
| `POST /admin/reload` | Add-only (never removes) | Safe | Safe | Safe | Safe |
| `docker-compose restart` | Reloads from `data/content.json` | Safe (volume mount) | Safe | Reloads from `data/` | Reloads from `data/` |
| `docker-compose up --build` | Same as restart | Safe (volume mount) | Safe | Same | Same |
| `git pull` (backend) | Safe (data/ not in git) | Audio gitignored — may lose | Safe | Safe | Safe |
| `git pull` (frontend) | N/A | Audio gitignored — may lose | Covers in git — safe | N/A | N/A |
| Full re-clone | Loses `data/` | Loses audio | Frontend: in git. Backend: loses | Loses | Loses |

### Persistent Backup Stores (outside git)

- `/opt/audio-store/pre-gen/` — all story/poem audio
- `/opt/audio-store/silly-songs/` — all silly song audio
- `/opt/cover-store/` — all covers

These survive everything including re-clones. The pipeline auto-recovers from these.

---

## Common Mistakes

| Mistake | What Happens | Prevention |
|---------|-------------|------------|
| `sudo git pull` | File ownership changes to root, pipeline cron breaks | Always `git pull` without sudo |
| Editing `seed_output/content.json` to remove stories | LocalStore re-adds them from seed on next reload | Edit `data/content.json` AND restart Docker |
| Frontend rebuild for new content | Unnecessary downtime | Only rebuild for code changes, not content |
| Re-cloning a repo | Loses all gitignored files (audio, data/) | Never re-clone. If you must, backup `/opt/audio-store/` first |
| Restarting Docker without checking state | Hindi stories reappear, extra items sneak in | Always run deploy guard before and after |

---

## Expected Production State

These are the expected counts. If deploy guard shows anything different, investigate.

| Content Type | Expected Count | Notes |
|-------------|---------------|-------|
| English stories | ~147+ (growing daily) | NO Hindi stories mixed in |
| Funny shorts per age group | 4 | 2-5: 4, 6-8: 4, 9-12: 4 (all with mixed episode audio) |
| Silly songs per age group | 1 | 2-5: Five More Minutes, 6-8: Vegetables Are Plotting, 9-12: My Homework Ate Itself |
| All silly songs have audio | Yes | `audio_file` must not be null |
| All stories have audio | Yes (for published ones) | Check with `deploy_guard.py check` |

---

## SSH Access

```bash
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a
```

---

## Quick Reference

```bash
# Before deploy
python3 scripts/deploy_guard.py snapshot

# After deploy
python3 scripts/deploy_guard.py verify

# Quick health check
python3 scripts/deploy_guard.py check

# Backend hot-reload (content only, no restart)
curl -s -X POST http://localhost:8000/api/v1/admin/reload \
  -H "X-Admin-Key: $(grep ADMIN_API_KEY .env | cut -d= -f2)"

# Backend code deploy
git pull origin main && sudo docker-compose down && sudo docker-compose up -d --build

# Frontend code deploy
git pull origin main && sudo npm run build && sudo cp -r public .next/standalone/public && sudo cp -r .next/static .next/standalone/.next/static && sudo pm2 restart dreamweaver-web
```
