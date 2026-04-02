# Silly Songs: Generation & Deploy Guide

Step-by-step runbook for generating new silly songs and deploying to production.

## Prerequisites

- SSH access to GCP VM (`gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a`)
- Mistral API key in `.env` (free tier: 2 req/min, 32s wait between calls)
- Replicate API token in `.env` (for MiniMax Music 1.5 audio)
- Pollinations API key in `.env` (for FLUX cover images)

## Step 1: Generate Lyrics (local)

```bash
cd dreamweaver-backend

# Generate 3 songs — 1 per age group, lyrics only
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --lyrics-only --force
```

**What this does:**
- Pre-assigns age groups: cycles through `2-5 → 6-8 → 9-12` (shuffled)
- For each song: generates scene (Step 0) → generates lyrics (Step 1) → validates
- Saves JSON metadata to `data/silly_songs/{song_id}.json`
- Takes ~3-4 minutes (Mistral rate limit: 35s wait between songs)

**Key flags:**
- `--fresh`: Diversity-tracked mode (pre-assigned ages, batch dedup)
- `--count N`: Number of songs (default 3, one per age group)
- `--lyrics-only`: Skip audio/cover generation (review lyrics first)
- `--force`: Regenerate even if files exist

**Review the output.** Check that:
- Each verse is complete sentences (not fragments)
- Rhymes are natural (no forced "trim it / dim it" constructions)
- V1 = real, V2 = exaggerated, V3 = absurd escalation
- Chorus is identical across non-final repetitions
- Quality benchmark: "Five More Minutes" (2-5) in `output/v4_final_batch_lyrics.txt`

## Step 2: Commit & Push

```bash
git add scripts/generate_silly_songs_battlecry.py data/silly_songs/*.json
git commit -m "Add N new silly songs: [list titles]"
git push origin main
```

## Step 3: Deploy Guard Snapshot (on GCP)

```bash
# SSH to production
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
```

This captures the current live state (story count, audio/cover status, silly song counts per age group) as a baseline to compare against after deploy.

## Step 4: Pull & Rebuild Backend (on GCP)

```bash
cd /opt/dreamweaver-backend
git pull origin main          # NEVER use sudo git pull
sudo docker-compose down && sudo docker-compose up -d --build
```

If git pull conflicts: `git stash && git pull origin main`

**CRITICAL:** `git pull` alone does NOT update the running backend. You MUST rebuild Docker.

## Step 5: Generate Audio (on GCP)

Run this on the GCP server (Python 3.12, Replicate installed):

```python
cd /opt/dreamweaver-backend
python3 << 'PYEOF'
import json, os, sys
from pathlib import Path

# Load env
env_path = Path('.env')
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

import replicate, httpx

# List your new song IDs here:
songs_to_gen = ['song_id_1', 'song_id_2', 'song_id_3']
audio_dir = Path('public/audio/silly-songs')
audio_dir.mkdir(parents=True, exist_ok=True)

for song_id in songs_to_gen:
    print(f'\n=== {song_id} ===')
    song = json.load(open(f'data/silly_songs/{song_id}.json'))
    lyrics = song['lyrics']
    style = song.get('style_prompt', '')
    if len(lyrics) > 600:
        lines = lyrics.split('\n')
        trimmed, total = [], 0
        for l in lines:
            if total + len(l) + 1 > 580: break
            trimmed.append(l); total += len(l) + 1
        lyrics = '\n'.join(trimmed)
    output = replicate.run('minimax/music-1.5', input={'prompt': style, 'lyrics': lyrics})
    resp = httpx.get(str(output), timeout=120, follow_redirects=True)
    path = audio_dir / f'{song_id}.mp3'
    path.write_bytes(resp.content)
    print(f'  Saved: {path} ({len(resp.content)/1024:.0f} KB)')
    song['audio_file'] = f'{song_id}.mp3'
    json.dump(song, open(f'data/silly_songs/{song_id}.json', 'w'), indent=2)
PYEOF
```

## Step 6: Generate Covers (on GCP)

```python
cd /opt/dreamweaver-backend
python3 << 'PYEOF'
import json, os, time
from pathlib import Path
from urllib.parse import quote
from io import BytesIO

for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

import httpx
from PIL import Image

COVERS_DIR = Path('public/covers/silly-songs')
COVERS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE = 'Digital painting of {desc}, bold cartoon style, bright saturated colors, simple flat background, exaggerated funny expressions, playful and warm, thick outlines, expressive eyes, Pixar-meets-picture-book aesthetic, small floating music notes, cozy musical energy, minimalist'

songs_to_gen = ['song_id_1', 'song_id_2', 'song_id_3']
token = os.getenv('POLLINATIONS_API_KEY', '')
headers = {'Authorization': f'Bearer {token}'} if token else {}

for song_id in songs_to_gen:
    song = json.load(open(f'data/silly_songs/{song_id}.json'))
    desc = song.get('cover_description', 'a cartoon child with funny expression in a cozy bedroom')
    prompt = TEMPLATE.format(desc=desc)[:600]
    url = f'https://gen.pollinations.ai/image/{quote(prompt, safe="")}?width=512&height=512&model=flux&nologo=true'
    resp = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)
    img = Image.open(BytesIO(resp.content)).convert('RGB').resize((512, 512), Image.LANCZOS)
    cover_path = COVERS_DIR / f'{song_id}.webp'
    img.save(str(cover_path), format='WEBP', quality=85)
    print(f'Saved: {cover_path}')
    song['cover_file'] = f'{song_id}.webp'
    json.dump(song, open(f'data/silly_songs/{song_id}.json', 'w'), indent=2)
PYEOF
```

## Step 7: Copy to Web Frontend (on GCP)

```bash
# Audio
sudo cp /opt/dreamweaver-backend/public/audio/silly-songs/*.mp3 /opt/dreamweaver-web/public/audio/silly-songs/

# Covers
sudo cp /opt/dreamweaver-backend/public/covers/silly-songs/*.webp /opt/dreamweaver-web/public/covers/silly-songs/

# Backup audio to persistent store (survives re-clones)
sudo cp /opt/dreamweaver-backend/public/audio/silly-songs/*.mp3 /opt/audio-store/pre-gen/

# Backup JSONs to json-store
sudo cp /opt/dreamweaver-backend/data/silly_songs/*.json /opt/json-store/silly_songs/
```

nginx serves `/audio/` and `/covers/` directly — no frontend rebuild needed.

## Step 8: Reload Backend

```bash
cd /opt/dreamweaver-backend
sudo docker-compose restart
sleep 5
curl -s -X POST https://api.dreamvalley.app/api/v1/admin/reload \
  -H 'X-Admin-Key: dv-reload-ae83c8070f5a4211e6c79bbed2c2c8d2'
```

## Step 9: Deploy Guard Verify

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py verify
```

**Expected output:**
- New items listed as ADDED with serving verification (audio + cover reachable)
- All file URLs reachable
- All 31 invariant checks passed
- Golden baseline auto-updated with new items

## Deleting Songs

If you need to permanently remove a song:

1. Delete from `data/silly_songs/{id}.json` (on server)
2. Delete audio: `public/audio/silly-songs/{id}.mp3` + `/opt/dreamweaver-web/public/audio/silly-songs/{id}.mp3`
3. Delete cover: `public/covers/silly-songs/{id}.webp` + `/opt/dreamweaver-web/public/covers/silly-songs/{id}.webp`
4. Delete from backup stores: `/opt/json-store/silly_songs/{id}.json` + `/opt/audio-store/pre-gen/{id}.mp3`
5. Remove from golden baseline: edit `data/deploy_golden.json` and remove the entry from the appropriate age group under `silly_songs`
6. Restart Docker + reload API
7. Run `deploy_guard.py snapshot` then `verify` to confirm clean state

**CRITICAL:** If you skip steps 4-5, deploy guard will auto-recover the deleted song from backup.

## Battle Cry Library

33 battle cries across 3 age groups. The script auto-selects unused cries per batch.

To see available cries:
```bash
python3 -c "from scripts.generate_silly_songs_battlecry import BATTLE_CRIES; [print(f'{k:20s} {v[\"cry\"]:25s} {v[\"ages\"]}') for k,v in BATTLE_CRIES.items()]"
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Mistral 500 error | Retry logic handles this (3 attempts with backoff). If persistent, wait 5 min. |
| "Battle cry not found in chorus" | Smart quote mismatch — validator normalizes these now. |
| Chorus inconsistency | Parent asides like `*(Mom: "...")* ` are stripped before comparison. |
| Duplicate battle cry in batch | `exclude_cries` param prevents this. 33 cries available. |
| Songs not appearing in API | Check `audio_file` and `cover_file` fields in JSON — API may filter songs without these. |
| `git pull` conflicts on server | `git stash && git pull origin main` |
| NEVER `sudo git pull` | Changes file ownership to root, breaks pipeline cron job. Fix: `sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-backend/` |

## Song Structure (MiniMax constraints)

MiniMax generates ~60 seconds of audio. Lyrics must fit within that window.

```
[verse 1] — 4 lines. Real complaints from this scene.
[chorus]  — 3-4 lines. Battle cry repeated. Identical every time.
[verse 2] — 4 lines. Same complaints, pushed further.
[chorus]  — identical repeat
[ending]  — 2-3 lines. Dissolving chorus or surrender.
```

**Hard limits:**
- Max 20 unique lines total
- Max 8 words per line
- Max 600 characters (MiniMax input limit)
- 2 verses only (no V3)
- No parent response lines in lyrics (stripped before MiniMax)

**Escalation:** V1 real → V2 exaggerated. The chorus does the heavy lifting through repetition.

## Quality Checklist

Before deploying lyrics, verify against the benchmark ("Five More Minutes" 2-5):

- [ ] Every line is a complete sentence a child would say out loud
- [ ] Rhymes are natural — no forced suffixes or fragments
- [ ] Different rhyme sounds per verse (RHYME FREEDOM)
- [ ] V1 real → V2 exaggerated escalation
- [ ] Max 20 lines, max 8 words per line
- [ ] Non-final choruses are word-for-word identical
- [ ] Final chorus dissolves into sleep/surrender
- [ ] No parent response lines in lyrics (added separately in audio)
- [ ] Sound effects are specific to the scene
