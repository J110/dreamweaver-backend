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

# Or generate a specific battle cry
python3 scripts/generate_silly_songs_battlecry.py --cry no_bath --lyrics-only --force
```

**What this does:**
- Pre-assigns age groups: cycles through `2-5 → 6-8 → 9-12` (shuffled)
- For each song: generates scene (Step 0) → generates lyrics (Step 1) → validates
- Saves JSON metadata to `data/silly_songs/{song_id}.json`
- Takes ~3-4 minutes (Mistral rate limit: 35s wait between songs)

**Key flags:**
- `--fresh`: Diversity-tracked mode (pre-assigned ages, batch dedup)
- `--count N`: Number of songs (default 3, one per age group)
- `--cry <id>`: Generate a specific battle cry (looks up from full BATTLE_CRIES library)
- `--lyrics-only`: Skip audio/cover generation (review lyrics first)
- `--force`: Regenerate even if files exist

**Review the output.** Check that:
- Each verse is complete sentences (not fragments)
- Rhymes are natural (no forced "trim it / dim it" constructions)
- V1 = real complaints, V2 = exaggerated/pushed further
- Chorus is identical across non-final repetitions
- Max 9 syllables per line (validator enforces this)
- One thought per line (no compound ideas joined by dashes)
- Simple words ("cat" not "dinosaur", "hot" not "distress")
- Quality benchmark: "Five More Minutes" (2-5) in `output/v4_final_batch_lyrics.txt`

## Song Structure (MiniMax constraints)

MiniMax Music 1.5 generates ~30-42 seconds of audio. Lyrics must be short and singable.

```
[verse 1] — 4 lines. Real complaints from this scene.
[chorus]  — 3-4 lines. Battle cry repeated. Identical every time.
[verse 2] — 4 lines. Same complaints, pushed further.
[chorus]  — identical repeat
[ending]  — 2-3 lines. Dissolving chorus or surrender.
```

**Hard limits:**
- Max 20 unique lines total
- Max 9 syllables per line (not words — SYLLABLES)
- One thought per line (never join ideas with dash/comma)
- Max 580 characters after cleanup (enforced by `prepare_lyrics_for_minimax`)
- 2 verses only (no V3)
- No parent response lines in lyrics (stripped before MiniMax)
- Simple words: "cat" not "dinosaur", "hot" not "distress"

**Escalation:** V1 real → V2 exaggerated. The chorus does the heavy lifting through repetition.

## Style Prompts (age-specific vocal clarity)

MiniMax receives two inputs: `prompt` (style) and `lyrics`. The style prompts prioritise vocal CLARITY over speed:

```
2-5:  "Catchy children's song, {instruments}, {BPM} BPM, bouncy beat,
       warm clear child vocal, sing each word clearly and slowly,
       fun and silly, not rushed"

6-8:  "Catchy children's song, {instruments}, {BPM} BPM, groovy beat,
       warm clear vocal, every word easy to understand,
       fun and bouncy, not fast"

9-12: "Catchy children's song, {instruments}, {BPM} BPM, cool beat,
       clear confident vocal, each line sung clearly not rushed,
       groovy and fun"
```

Key phrases: "warm clear vocal", "sing each word clearly", "not rushed", "not fast". The instruments can bounce — the voice doesn't need to race.

## Validation Checks (automatic)

The script runs these checks after generation. Failures trigger LLM retry (up to 2 retries):

| Check | Type | Blocking? |
|-------|------|-----------|
| Battle cry in chorus | `missing_cry` | Yes |
| Chorus consistency | `chorus_inconsistent` | Yes |
| Sound effects present | `no_sfx` | Yes |
| At least 2 verses | `few_verses` | Yes |
| Max 20 lines | `too_many_lines` | Yes |
| Max 9 syllables/line | `too_many_syllables` | Yes |
| No nonsense similes | `nonsense_simile` | Yes |
| Max 8 words/line | warning | No (logged only) |
| Character count < 600 | warning | No (trimmed before send) |

Smart quote normalization handles LLM curly quotes vs ASCII battle cry strings. Parent asides `*(Mom: "...")* ` are stripped before chorus comparison.

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
import json, os, re
from pathlib import Path

# Load env
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

import replicate, httpx

def strip_parent_lines(lyrics):
    lines = lyrics.split("\n")
    filtered = []
    in_parent = False
    for l in lines:
        s = l.strip().lower()
        if s.startswith("[parent"):
            in_parent = True
            continue
        if in_parent:
            if s.startswith("["):
                in_parent = False
            else:
                continue
        if any(s.startswith(p) for p in ["mom:", "dad:", "parent:", "*mom", "*dad", "*parent"]):
            continue
        filtered.append(l)
    return "\n".join(filtered)

def prepare_for_minimax(lyrics, max_chars=580):
    clean = re.sub(r'\[.*?\]', '', lyrics)
    clean = strip_parent_lines(clean)
    lines = [l.strip() for l in clean.split('\n') if l.strip()]
    result = '\n'.join(lines)
    if len(result) > max_chars:
        while len(result) > max_chars and lines:
            lines.pop()
            result = '\n'.join(lines)
        print('  Trimmed to %d chars (%d max)' % (len(result), max_chars))
    return result

# List your new song IDs here:
songs_to_gen = ['song_id_1', 'song_id_2', 'song_id_3']
audio_dir = Path('public/audio/silly-songs')
audio_dir.mkdir(parents=True, exist_ok=True)

for song_id in songs_to_gen:
    print('\n=== %s ===' % song_id)
    song = json.load(open('data/silly_songs/%s.json' % song_id))
    style = song.get('style_prompt', '')
    lyrics = prepare_for_minimax(song['lyrics'])
    print('  Style: %s' % style)
    print('  Lyrics (%d chars)' % len(lyrics))
    output = replicate.run('minimax/music-1.5', input={'prompt': style, 'lyrics': lyrics})
    resp = httpx.get(str(output), timeout=120, follow_redirects=True)
    path = audio_dir / ('%s.mp3' % song_id)
    path.write_bytes(resp.content)
    print('  Saved: %s (%d KB)' % (path, len(resp.content) / 1024))
    song['audio_file'] = '%s.mp3' % song_id
    json.dump(song, open('data/silly_songs/%s.json' % song_id, 'w'), indent=2)
PYEOF
```

**IMPORTANT:** Always use `prepare_for_minimax()` — it strips parent lines, section tags, and enforces the 580-char limit. Never send raw lyrics to MiniMax.

## Step 6: Generate Covers (on GCP)

```python
cd /opt/dreamweaver-backend
python3 << 'PYEOF'
import json, os
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
headers = {'Authorization': 'Bearer %s' % token} if token else {}

for song_id in songs_to_gen:
    song = json.load(open('data/silly_songs/%s.json' % song_id))
    desc = song.get('cover_description', 'a cartoon child with funny expression in a cozy bedroom')
    prompt = TEMPLATE.format(desc=desc)[:600]
    encoded = quote(prompt, safe='')
    url = 'https://gen.pollinations.ai/image/%s?width=512&height=512&model=flux&nologo=true' % encoded
    resp = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)
    img = Image.open(BytesIO(resp.content)).convert('RGB').resize((512, 512), Image.LANCZOS)
    cover_path = COVERS_DIR / ('%s.webp' % song_id)
    img.save(str(cover_path), format='WEBP', quality=85)
    print('Saved: %s' % cover_path)
    song['cover_file'] = '%s.webp' % song_id
    json.dump(song, open('data/silly_songs/%s.json' % song_id, 'w'), indent=2)
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

**Dropped cries:** `where_mommy` (not a resistance/protest phrase). All battle cries must be something a child says when resisting bedtime, chores, or rules.

## Expected Audio Durations

MiniMax Music 1.5 produces ~30-42 seconds regardless of lyrics length. Longer lyrics get compressed/truncated. With the vocal clarity style prompts:

| Age Group | Typical Duration | Style Focus |
|-----------|-----------------|-------------|
| 2-5 | ~32s | "warm clear child vocal, sing each word clearly and slowly, not rushed" |
| 6-8 | ~40s | "warm clear vocal, every word easy to understand, not fast" |
| 9-12 | ~42s | "clear confident vocal, each line sung clearly not rushed" |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Mistral 500 error | Retry logic handles this (3 attempts with backoff). If persistent, wait 5 min. |
| "Battle cry not found in chorus" | Smart quote mismatch — validator normalizes these now. |
| Chorus inconsistency | Parent asides like `*(Mom: "...")* ` are stripped before comparison. |
| Duplicate battle cry in batch | `exclude_cries` param prevents this. 33 cries available. |
| Songs not appearing in API | Check `audio_file` and `cover_file` fields in JSON — API may filter songs without these. |
| `git pull` conflicts on server | `git stash && git pull origin main` — then delete any stale JSONs that come back. |
| NEVER `sudo git pull` | Changes file ownership to root, breaks pipeline cron job. Fix: `sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-backend/` |
| Lyrics too long (>580 chars) | `prepare_lyrics_for_minimax()` trims from the end automatically. |
| Too many syllables per line | Validator flags and retries — LLM rewrites with shorter words. |
| Nonsense similes ("like a sad bridge") | Validator flags and retries — LLM rewrites with real sentences. |
| LLM splits lines to fix syllables | Retry prompt says "keep 4 lines per verse, rewrite shorter". |
| Deploy guard "energetic style" fails | Style must contain "bouncy beat", "groovy beat", or "cool beat". |
| Old songs reappear after git stash | Delete stale JSONs manually + clean golden baseline. |

## Quality Checklist

Before deploying lyrics, verify against the benchmark ("Five More Minutes" 2-5):

- [ ] Every line is a complete sentence a child would say out loud
- [ ] Rhymes are natural — no forced suffixes or fragments
- [ ] Different rhyme sounds per verse (RHYME FREEDOM)
- [ ] V1 real → V2 exaggerated escalation
- [ ] Max 20 lines total
- [ ] Max 9 syllables per line
- [ ] One thought per line (no compound dash/comma lines)
- [ ] Simple words ("cat" not "dinosaur", "hot" not "distress")
- [ ] Non-final choruses are word-for-word identical
- [ ] Final chorus dissolves into sleep/surrender
- [ ] No parent response lines in lyrics (added separately in audio)
- [ ] Sound effects are specific to the scene
- [ ] No nonsense similes ("like a sad bridge")
- [ ] Lyrics fit under 580 chars after cleanup
