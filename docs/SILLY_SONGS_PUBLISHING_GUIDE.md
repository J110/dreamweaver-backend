# Silly Songs Publishing Guide

How to create, generate, and publish silly songs to Dream Valley.

---

## 1. Song Data Schema

Each song is a JSON file in `data/silly_songs/{song-id}.json`:

```json
{
    "id": "five-more-minutes",
    "title": "Five More Minutes",
    "age_group": "2-5",
    "duration_seconds": 75,
    "lyrics": "[verse]\nFirst verse...\n\n[chorus]\nChorus...\n\n[bridge]\nBridge...",
    "style_prompt": "children's song, sweet and funny, soft acoustic guitar, xylophone...",
    "cover_description": "A tiny child in pajamas kneeling dramatically beside a bed...",
    "cover_file": "five-more-minutes.webp",
    "animation_preset": "sway",
    "audio_file": "five-more-minutes.mp3",
    "created_at": "2026-03-28",
    "play_count": 0,
    "replay_count": 0
}
```

### Required fields (create manually)

| Field | Description |
|-------|-------------|
| `id` | Unique slug, used as filename. Use lowercase-kebab-case. |
| `title` | Display title |
| `age_group` | One of: `"2-5"`, `"6-8"`, `"9-12"` |
| `lyrics` | Full lyrics with section tags: `[verse]`, `[chorus]`, `[bridge]`, `[outro]` |
| `style_prompt` | Music generation prompt describing genre, instruments, tempo, mood |
| `cover_description` | Visual scene description for FLUX image generation |
| `created_at` | ISO date (YYYY-MM-DD). Songs with today's date show a "NEW" badge in the app. |

### Auto-populated by scripts

| Field | Description |
|-------|-------------|
| `audio_file` | Set by audio generation script (`{id}.mp3`) |
| `cover_file` | Set by cover generation script (`{id}.webp`) |
| `duration_seconds` | Set by audio generation script |
| `animation_preset` | CSS animation for cover: `"sway"`, `"pulse"`, `"bounce"` |
| `play_count` / `replay_count` | Analytics, start at 0 |

---

## 2. Writing Lyrics

- Use section tags: `[verse]`, `[chorus]`, `[bridge]`, `[outro]`
- Keep total length 60-100 seconds when sung (roughly 150-250 words)
- Age-appropriate humor:
  - **2-5**: Simple repetition, silly sounds, physical comedy
  - **6-8**: Wordplay, absurd situations, relatable school/home scenarios
  - **9-12**: Sarcasm, exaggeration, self-aware humor
- End with a sleepy/winding-down tone (it's bedtime content)

### Style Prompt Tips

The `style_prompt` drives the music generation model. Include:
- Genre/style (children's song, lullaby, pop, etc.)
- Instruments (guitar, xylophone, piano, claps, etc.)
- Tempo in BPM (80-120 for bedtime-appropriate)
- Vocal character (child-like, warm, silly, gentle)
- Mood/energy (bouncy, gentle, dramatic, etc.)

---

## 3. Generate Audio

Two options — use whichever has available credits:

### Option A: ACE-Step via SongGen on Modal

```bash
# Single song
python3 scripts/generate_silly_songs.py --song five-more-minutes

# All songs missing audio
python3 scripts/generate_silly_songs.py --all

# Force regenerate
python3 scripts/generate_silly_songs.py --song five-more-minutes --force

# Generate 3 variants and pick best duration match
python3 scripts/generate_silly_songs.py --all --variants 3
```

Requires: `SONGGEN_URL` env var pointing to Modal endpoint.

### Option B: MiniMax Music 1.5 via Replicate

```bash
python3 scripts/generate_silly_songs_minimax.py --song five-more-minutes
python3 scripts/generate_silly_songs_minimax.py --all
```

Requires: `REPLICATE_API_TOKEN` env var.
Note: Trims lyrics to 600-char limit while preserving complete sections.

### Output

Audio saved to: `public/audio/silly-songs/{song-id}.mp3`
JSON updated with: `audio_file`, `duration_seconds`

---

## 4. Generate Cover

```bash
# Single song
python3 scripts/generate_silly_song_covers.py --song five-more-minutes

# All songs missing covers
python3 scripts/generate_silly_song_covers.py --all

# Force regenerate
python3 scripts/generate_silly_song_covers.py --all --force
```

Uses Pollinations FLUX endpoint. Generates 512x512 WebP images.

### Output

Cover saved to: `public/covers/silly-songs/{song-id}.webp`
JSON updated with: `cover_file`

---

## 5. File Serving Architecture

Understanding where files are served from is critical for publishing.

### On GCP Production Server

| Content | Server Path | Served By | URL Pattern | Cache |
|---------|-------------|-----------|-------------|-------|
| Song audio | `/opt/dreamweaver-backend/public/audio/silly-songs/` | **nginx** (api.dreamvalley.app) | `https://api.dreamvalley.app/audio/silly-songs/{id}.mp3` | 1 year, immutable |
| Song covers | `/opt/dreamweaver-backend/public/covers/silly-songs/` | **nginx** (dreamvalley.app) | `https://dreamvalley.app/covers/silly-songs/{id}.webp` | 30 days |
| Song metadata | `/opt/dreamweaver-backend/data/silly_songs/{id}.json` | **Backend API** (Docker) | `https://api.dreamvalley.app/api/v1/silly-songs` | No cache |

### nginx Configuration (in `/etc/nginx/sites-enabled/dreamvalley`)

**api.dreamvalley.app** server block:
```nginx
# Serves ALL audio under /opt/dreamweaver-backend/public/audio/
# This includes silly-songs/, funny-shorts/, and pre-gen/
location /audio/ {
    alias /opt/dreamweaver-backend/public/audio/;
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

**dreamvalley.app** (frontend) server block:
```nginx
# Silly songs covers from backend
location /covers/silly-songs/ {
    alias /opt/dreamweaver-backend/public/covers/silly-songs/;
    add_header Cache-Control "public, max-age=2592000";
}
```

### Backend Static Mounts (in `app/main.py`, used in Docker/local dev)

```python
app.mount("/audio/silly-songs", StaticFiles(directory="public/audio/silly-songs"))
app.mount("/covers/silly-songs", StaticFiles(directory="public/covers/silly-songs"))
```

These are used when running locally or on Render. On GCP production, nginx handles these paths directly (before requests reach Docker).

### How the Frontend Plays Audio

```javascript
// src/app/before-bed/page.js
const audio = new Audio(`${API_URL}/audio/silly-songs/${song.audio_file}`);
```

Where `API_URL` = `https://api.dreamvalley.app` in production.

### How the Frontend Shows Covers

```javascript
// Silly songs use <img> tags (WebP images)
<img src={`/covers/silly-songs/${song.cover_file}`} />
```

Note: Silly song covers use `<img>` tags (WebP), while funny shorts use `<object>` tags (SVG).

---

## 6. Publishing to Production

### Step 1: Generate locally

```bash
# Create the JSON file in data/silly_songs/
# Then generate audio + cover
python3 scripts/generate_silly_songs.py --song {id}
python3 scripts/generate_silly_song_covers.py --song {id}
```

### Step 2: Push metadata to git

```bash
git add data/silly_songs/{id}.json
git commit -m "Add silly song: {title}"
git push origin main
```

Note: Audio and cover files are NOT in git (they're in `public/` which is gitignored).

### Step 3: Deploy backend code (if code changes)

```bash
# SSH to server
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a

# Pull and rebuild
cd /opt/dreamweaver-backend
git pull origin main  # NO sudo
sudo docker-compose down && sudo docker-compose up -d --build
```

### Step 4: Copy audio and cover files to server

```bash
# From local machine
gcloud compute scp public/audio/silly-songs/{id}.mp3 \
  dreamvalley-prod:/opt/dreamweaver-backend/public/audio/silly-songs/ \
  --project=strong-harbor-472607-n4 --zone=asia-south1-a

gcloud compute scp public/covers/silly-songs/{id}.webp \
  dreamvalley-prod:/opt/dreamweaver-backend/public/covers/silly-songs/ \
  --project=strong-harbor-472607-n4 --zone=asia-south1-a
```

Files are served instantly by nginx once copied. No restart needed.

### Step 5: Verify

```bash
# On the server
python3 scripts/deploy_guard.py check

# Or just check the specific files
curl -I https://api.dreamvalley.app/audio/silly-songs/{id}.mp3
curl -I https://dreamvalley.app/covers/silly-songs/{id}.webp
```

---

## 7. Persistent Audio Store

Silly song audio is backed up to `/opt/audio-store/silly-songs/` on the GCP server. This survives git re-clones.

The generation scripts auto-recover from the store if files exist there but are missing from `public/audio/silly-songs/`.

---

## 8. API Behavior

- `GET /api/v1/silly-songs?age_group=2-5` — lists songs (excludes `lyrics` and `style_prompt`)
- `GET /api/v1/silly-songs/{id}` — full song with lyrics
- `POST /api/v1/silly-songs/{id}/play` — record first play
- `POST /api/v1/silly-songs/{id}/replay` — record subsequent plays

Songs without `audio_file` are filtered out of the list endpoint. So a song won't appear in the app until its audio is generated and the field is set in the JSON.

---

## 9. Quick Reference: Adding a New Song

```bash
# 1. Create metadata
cat > data/silly_songs/my-new-song.json << 'EOF'
{
    "id": "my-new-song",
    "title": "My New Song",
    "age_group": "6-8",
    "lyrics": "[verse]\n...\n\n[chorus]\n...",
    "style_prompt": "children's pop, piano, gentle claps, 100 BPM...",
    "cover_description": "A child laughing at...",
    "created_at": "2026-03-30",
    "play_count": 0,
    "replay_count": 0
}
EOF

# 2. Generate audio + cover
python3 scripts/generate_silly_songs.py --song my-new-song
python3 scripts/generate_silly_song_covers.py --song my-new-song

# 3. Commit + push
git add data/silly_songs/my-new-song.json
git commit -m "Add silly song: My New Song"
git push origin main

# 4. Deploy to server
gcloud compute ssh dreamvalley-prod ... -- "cd /opt/dreamweaver-backend && git pull origin main && sudo docker-compose down && sudo docker-compose up -d --build"

# 5. Copy files
gcloud compute scp public/audio/silly-songs/my-new-song.mp3 dreamvalley-prod:/opt/dreamweaver-backend/public/audio/silly-songs/ ...
gcloud compute scp public/covers/silly-songs/my-new-song.webp dreamvalley-prod:/opt/dreamweaver-backend/public/covers/silly-songs/ ...

# 6. Verify
gcloud compute ssh dreamvalley-prod ... -- "python3 /opt/dreamweaver-backend/scripts/deploy_guard.py check"
```
