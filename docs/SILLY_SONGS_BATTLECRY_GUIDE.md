# Silly Songs Generation Guide

How to generate silly songs across three categories. Covers the full workflow from lyrics to production.

---

## Overview

Silly songs are short (~60s) singalong anthems for kids aged 2-12, organized into three categories:

| Category | Vibe | Example |
|----------|------|---------|
| **Battle Cry** | Protest — child resisting an adult | "I'm not tired", "That's not fair" |
| **Celebration** | Joy — something amazing just happened | "Snow day!", "It's my birthday!" |
| **Observation** | Wonder — noticing something weird | "Grown-ups are weird", "Where do socks go?" |

**The Formula** — every song must have ALL FIVE:

1. **ANTHEM**: The chorus is a real phrase kids say — protest, celebration, or observation
2. **NATURAL RHYMES**: Rhyme families vary per verse. No forced rhymes.
3. **BOUNCE**: Full musical production with bass, strong beat, groove
4. **ESCALATION**: V1 reasonable → V2 pushed further
5. **COZY ENDING**: Energy dissolves into sleep/warmth by the ending

---

## Prerequisites

```bash
cd /path/to/dreamweaver-backend

# Required packages
pip install mistralai httpx replicate Pillow

# Required env vars (in .env)
MISTRAL_API_KEY=...        # Free experiment tier, 2 req/min
REPLICATE_API_TOKEN=...    # For MiniMax Music 1.5 audio
TOGETHER_API_KEY=...       # For FLUX cover generation (primary)
POLLINATIONS_API_KEY=...   # Optional fallback for covers
```

---

## Quick Start

```bash
# Generate 3 songs, one per category, with mood rotation (recommended)
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --mood-rotate

# Force a specific category
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --category celebration

# Force a specific mood
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --mood calm

# Lyrics only (no audio/cover, fast, free)
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --lyrics-only

# Generate a specific battle cry by ID
python3 scripts/generate_silly_songs_battlecry.py --cry not_tired

# Force regenerate (overwrite existing)
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --force
```

### CLI Arguments

| Argument | Description |
|----------|------------|
| `--fresh` | Diversity-tracked generation (recommended for daily use) |
| `--count N` | Number of songs (default: 3) |
| `--mood` | Force a mood: wired, curious, calm, sad, anxious, angry |
| `--mood-rotate` | Cycle moods across the batch |
| `--category` | Force a category: battle_cry, celebration, observation |
| `--cry ID` | Generate a specific anthem by ID |
| `--lyrics-only` | Skip audio and cover generation |
| `--force` | Regenerate even if files exist |
| `--test` | Legacy: one song per age group from test set |
| `--all` | Legacy: all 6 test battle cries |

---

## The Generation Process

### Step 0: Scene Generation (Mistral LLM)

For each anthem, generates a concrete scene — the EXACT MOMENT the child says the phrase. Category-specific prompts:

- **Battle cry**: Where are they? Who are they protesting to? What just happened?
- **Celebration**: Where are they? What just happened? What are they doing with their body?
- **Observation**: Where are they? What are they staring at? What made them notice?

### Step 1: Lyrics Generation (Mistral LLM)

Category-specific system messages and verse guides:

| Category | Voice | V1 | V2 | Ending |
|----------|-------|----|----|--------|
| Battle cry | Cheeky, protesting | Real complaints | Same pushed further | Dissolves into sleep/surrender |
| Celebration | Bursting with joy | Excited things child says | Wilder, funnier | Winds down into cozy warmth |
| Observation | Curious, amused | What the child notices | More absurd wondering | Drowsy curiosity |

**Structure**: `[verse 1]` → `[chorus]` → `[verse 2]` → `[chorus]` → `[ending]`. Max 20 lines. Max 9 syllables per line.

### Step 2: Validation + Retry

Automated checks: anthem in chorus, syllable limits, line count, sense check. Retries up to 2x with error feedback.

### Step 3: Audio (MiniMax Music 1.5 via Replicate)

- Lyrics trimmed to ~560 chars (MiniMax limit)
- Style prompt includes: full musical production, bass, instruments, BPM, mood energy, strong singalong chorus
- Output: `public/audio/silly-songs/{song_id}.mp3`

### Step 4: Cover (FLUX via Together AI / Pollinations)

- 512x512 WebP, bold cartoon style
- Cover description extracted from `[COVER: ...]` tag in lyrics
- Primary: Together AI (`FLUX.1-schnell`). Fallback: Pollinations
- Output: `public/covers/silly-songs/{song_id}.webp`

---

## Anthem Libraries

### Battle Cries (35 entries)

Protest phrases. Ages 2-5: "I'm not tired", "No bath", "Pick me up", etc. Ages 6-8: "That's not fair", "But why", "He started it", etc. Ages 9-12: "In a minute", "Whatever", "Leave me alone", etc.

### Celebrations (15 entries)

Joy phrases. Ages 2-5: "Ice cream!", "Puddles!", "It's my birthday!", "Pyjama day!", "Bubbles!". Ages 6-8: "Snow day!", "No school tomorrow!", "Pizza night!", "Sleepover!", "We got a pet!". Ages 9-12: "Last day of school!", "I can stay up late!", "Road trip!", "New game!", "It's the weekend!".

### Observations (15 entries)

Wonder phrases. Ages 2-5: "Where do socks go?", "Why is it dark?", "The moon follows me!", etc. Ages 6-8: "Grown-ups are weird", "Do dogs dream?", "Broccoli looks like trees", etc. Ages 9-12: "Who invented homework?", "The WiFi is down", "Why does Monday exist?", etc.

---

## Mood System

Each mood maps to a subset of anthems per category, plus adjusts the style prompt energy and tempo.

| Mood | Energy | Tempo Offset | Best For |
|------|--------|-------------|----------|
| wired | Super bouncy, strong groove | +4 BPM | High-energy kids before bed |
| curious | Groovy and melodic, catchy hook | 0 | Thoughtful, questioning kids |
| calm | Warm swaying groove, cozy beat | -6 BPM | Already settling down |
| sad | Soft steady groove, warm bass | -8 BPM | Needs comfort |
| anxious | Steady reassuring groove, strong beat | -4 BPM | Needs predictability |
| angry | Firm punchy groove, satisfying stomp | +2 BPM | Needs to channel frustration |

**All moods produce full songs with groove/beat/bass** — never thin or ambient.

---

## Diversity System

The `--fresh` mode auto-rotates to ensure variety across:

- **Categories**: Cycles battle_cry → celebration → observation
- **Age groups**: Cycles 2-5 → 6-8 → 9-12
- **Moods** (with `--mood-rotate`): Cycles through all 6 moods
- **Anthems**: Avoids repeating the same anthem in last 10 songs per age
- **Instruments**: Avoids repeating instruments from last 3 songs
- **Tempo**: Random within range, adjusted by mood

---

## Style Prompts

All style prompts now include:
- **"full musical production"** — prevents thin/sparse generation
- **"bass"** in every instrument combo
- **"strong singalong chorus"** — emphasizes the hook
- **Mood-specific energy** — preserves groove across all moods

Example: `"Catchy children's song, full musical production, ukulele, bass, and hand claps, 122 BPM, super bouncy, high energy, strong groove, clear warm vocal, strong singalong chorus, every word easy to understand"`

---

## Song ID Format

`{anthem_id}_{age_group}` where age uses underscores: `grownups_weird_6_8`, `my_birthday_2_5`, `in_a_minute_9_12`

---

## Song JSON Schema

```json
{
    "id": "grownups_weird_6_8",
    "title": "Grown-Ups Are Weird",
    "age_group": "6-8",
    "category": "observation",
    "mood": "wired",
    "lyrics": "[verse 1]\n...\n[chorus]\n...",
    "style_prompt": "Catchy children's song, full musical production...",
    "instruments": "acoustic guitar, bass, and beatbox",
    "tempo": 118,
    "scene": "The kitchen clock reads 7:22 PM...",
    "cover_description": "...",
    "cover_file": "grownups_weird_6_8.webp",
    "audio_file": "grownups_weird_6_8.mp3",
    "duration_seconds": 75,
    "animation_preset": "bounce_rhythmic",
    "created_at": "2026-04-03",
    "play_count": 0,
    "replay_count": 0,
    "anthem_id": "grownups_weird",
    "anthem": "Grown-ups are weird",
    "battle_cry_id": "grownups_weird",
    "battle_cry": "Grown-ups are weird",
    "generation_method": "battlecry_v4"
}
```

---

## Output Files

| File | Location | In Git? |
|------|----------|---------|
| Song metadata | `data/silly_songs/{song_id}.json` | Yes |
| Audio | `public/audio/silly-songs/{song_id}.mp3` | No (gitignored) |
| Cover | `public/covers/silly-songs/{song_id}.webp` | No (gitignored) |
| Scene debug | `output/silly_songs_battlecry/{song_id}_scene.txt` | No |

---

## Publishing to Production

### 1. Generate locally

```bash
python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --mood-rotate
```

### 2. Deploy Guard snapshot (BEFORE deploy)

```bash
python3 scripts/deploy_guard.py snapshot
```

### 3. Commit and push metadata

```bash
git add data/silly_songs/*.json
git commit -m "Add N silly songs: titles..."
git push origin main
```

### 4. Pull on server and rebuild Docker

```bash
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a \
  --command="cd /opt/dreamweaver-backend && git pull origin main && sudo docker-compose down && sudo docker-compose up -d --build"
```

**CRITICAL**: Backend runs in Docker. `git pull` alone does NOT update. You MUST rebuild.

### 5. Copy audio + cover files to server

```bash
gcloud compute scp public/audio/silly-songs/*.mp3 \
  dreamvalley-prod:/opt/dreamweaver-backend/public/audio/silly-songs/ \
  --project=strong-harbor-472607-n4 --zone=asia-south1-a

gcloud compute scp public/covers/silly-songs/*.webp \
  dreamvalley-prod:/opt/dreamweaver-backend/public/covers/silly-songs/ \
  --project=strong-harbor-472607-n4 --zone=asia-south1-a
```

### 6. Reload content (instant, no restart)

```bash
curl -X POST https://api.dreamvalley.app/api/v1/admin/reload \
  -H "X-Admin-Key: dv-reload-ae83c8070f5a4211e6c79bbed2c2c8d2"
```

### 7. Deploy Guard verify (AFTER deploy)

```bash
python3 scripts/deploy_guard.py verify
```

---

## Rate Limiting

| Service | Limit | Built-in Wait |
|---------|-------|--------------|
| Mistral (free tier) | 2 req/min | 32s between LLM calls |
| Between songs | — | 35s |
| Pollinations FLUX | Varies | 5s between requests, retry on 429 |
| Together AI | Free tier | No explicit wait |
| Replicate MiniMax | — | Calls take 30-60s naturally |

**Total time**: ~3-4 min per song. ~10-12 min for 3 songs.

---

## Cost Per Run

```
Per song:
  2 × Mistral calls (scene + lyrics):       $0      (free tier)
  1 × MiniMax audio (Replicate):             ~$0.035
  1 × FLUX cover (Together AI):              $0      (free tier)
  Total per song:                            ~$0.04

3 songs:                                     ~$0.12
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Python 3.9 type hint errors | Script has `from __future__ import annotations` — should work. If not, use Python 3.10+ |
| Pollinations timeout | Switch to Together AI (primary). Pollinations is flaky |
| Together AI 400 error | Use model `black-forest-labs/FLUX.1-schnell` (not `-Free`) |
| MiniMax lyrics too long | Script auto-trims to 560 chars keeping complete sections |
| Mistral rate limit (429) | Built-in 32s waits. If still failing, increase sleep time |
| Deploy guard "calm language" warning | False positive — `SONG_MOOD_ENERGY["calm"]` contains the word "calm" as a mood key, not sleep language. Ignore. |
| Validation: anthem not in chorus | Retry usually fixes. If persistent, edit lyrics manually |
| Cover has text in it | FLUX sometimes renders text. Regenerate with `--force` |

---

## History

| Date | What |
|------|------|
| 2026-03-31 | v1: Battle Cry approach. 3 test songs published. |
| 2026-04-02 | v3: Mood mapping added. 6 songs published with mood diversity. |
| 2026-04-03 | v4: Expanded to 3 categories (battle_cry + celebration + observation). Bass in all instruments. Full musical production in style prompts. 3 category-diverse songs published. |
