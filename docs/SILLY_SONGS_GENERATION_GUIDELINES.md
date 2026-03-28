# Silly Songs — Generation Guidelines
## Complete Reference for Audio, Covers, and Publishing

> **Purpose**: Single source of truth for generating silly songs for the Before Bed tab.
> Cross-references: `SILLY_SONGS_TEST_PLAN.md`, `SILLY_SONGS_COVER_SPEC.md`

---

## Overview

Silly songs are 60-90 second comedy songs generated via ACE-Step on Modal. They live alongside funny shorts in the Before Bed tab. Unlike funny shorts (multi-layer TTS + stings + base track), silly songs are **single audio files** — one API call to ACE-Step produces the complete song.

**Content type**: Catchy, funny, age-appropriate songs with singable choruses.
**Audio generation**: ACE-Step on Modal (self-hosted SongGen endpoint).
**Cover generation**: FLUX Schnell via Pollinations.ai (WebP, static for now).
**Cost per song**: ~$0.03 (2 variants × ACE-Step on Modal).

---

## Song Structure

Every song follows this structure:

```
[verse]     — Sets up the funny situation (4 lines)
[chorus]    — Catchy, singable, repeatable (4-5 lines)
[verse]     — Escalates the situation (4 lines)
[chorus]    — Same chorus (builds familiarity)
[bridge]    — Twist or reflection (3-4 lines)
[chorus]    — Final chorus, often with a goodnight tag
```

### Structure Rules

1. **Chorus must be identical** across all repetitions (ACE-Step produces melodic drift if choruses differ)
2. **End with "Goodnight" or a sleep-adjacent closing line** — these play before bed
3. **3 verses max** — keeps songs under 90 seconds
4. **Bridge is optional** but recommended for comedy (the twist/realization moment)

---

## Age-Specific Guidelines

### Ages 2-5: Nursery Rhyme Energy

- Simple rhymes, repetitive patterns
- Onomatopoeia ("achoo", "plink", "boing")
- Animal characters
- Warm, bouncy instrumentation (ukulele, glockenspiel, claps)
- Male or female vocal, cheerful
- BPM: 110-125
- **The chorus test**: Can a 3-year-old sing along after 2 listens?

### Ages 6-8: Character Comedy + Absurdity

- Funny situations described with personality
- Can be theatrical/dramatic (villain songs, deadpan observation)
- Mix of instruments (indie folk, Broadway-lite, quirky)
- Male or female vocal, character-driven
- BPM: 100-115
- Comedy through contrast (dramatic delivery of silly content)

### Ages 9-12: Dry Humor + Indie Pop

- Sarcasm, understatement, meta-humor
- The singer comments on absurd situations while staying calm
- Indie pop/folk instrumentation (acoustic guitar, soft piano, light drums)
- Young female or male vocal, understated delivery
- BPM: 95-105
- **NEVER try to be funny** — the restraint IS the comedy (same principle as funny shorts)

---

## ACE-Step Generation

### Modal Endpoint

```python
SONGGEN_URL = os.getenv("SONGGEN_URL")  # Self-hosted ACE-Step on Modal
```

### Payload

```python
payload = {
    "lyrics": lyrics_text,        # Full lyrics with [verse], [chorus], [bridge] tags
    "description": style_prompt,   # Genre, instruments, tempo, vocal description
    "mode": "full",               # Always "full" for silly songs (vocal + instruments)
    "format": "mp3",              # MP3 output
    "duration": target_duration,   # Target seconds (60-90)
    "seed": seed_value,           # Different seed per variant
}
```

### Generation Strategy

1. Generate **2 variants** per song (different seeds)
2. Pick the variant **closest to target duration**
3. If both variants are under 60s or over 100s, **flag for lyrics trim/extension**
4. Rate limit: 5-10 seconds between variants, 10 seconds between songs

### Duration Control

ACE-Step doesn't precisely control output duration. Guidelines:

| Target | Acceptable Range | Action if Outside |
|--------|-----------------|-------------------|
| 75s    | 60-90s          | OK                |
| 75s    | < 60s           | Add a verse or extend bridge |
| 75s    | > 100s          | Remove a verse or shorten bridge |

### Style Prompt Best Practices

- **Be specific about instruments**: "ukulele, claps, glockenspiel" not just "bouncy"
- **Include BPM**: ACE-Step respects tempo hints
- **Describe the vocal**: "cheerful male vocal" or "slightly bored young female vocal"
- **Include mood adjectives**: "silly", "dramatic", "deadpan", "theatrical"
- **Include negative guidance**: Use "NOT dreamy, NOT sleepy" for comedy songs

---

## Lyrics Writing Rules

### Format

```
[verse]
Line 1
Line 2
Line 3
Line 4

[chorus]
Line 1
Line 2
Line 3
Line 4

[bridge]
Line 1
Line 2
Line 3
```

### Rules

1. **One blank line between sections** — ACE-Step uses these as phrase boundaries
2. **No text after section tags** — `[verse]` alone on its line, not `[verse - the first one]`
3. **Choruses must be identical text** — copy-paste, don't rephrase
4. **4 lines per verse, 4-5 lines per chorus** — sweet spot for ACE-Step
5. **Rhyme scheme**: AABB or ABAB for verses, AABB for choruses (simpler = catchier)
6. **Last line of last chorus**: Add the "goodnight" tag ("Goodnight, little croc", "Goodnight, I'm fine")

### Comedy in Lyrics

- **Escalation across verses**: Each verse should be bigger/more absurd than the last
- **Punchline in chorus**: The chorus itself should be funny ("He's not a rock, he's a croc")
- **Bridge = the twist**: Self-aware moment, brief reflection, or pivot ("Maybe the problem is... me? No.")
- **Ending tag after final chorus**: Short, deadpan closing line

---

## Cover Generation

### Image: FLUX Schnell via Pollinations.ai

```python
COVER_PROMPT_TEMPLATE = (
    "Children's book illustration, bold cartoon style, bright saturated colors, "
    "simple background, exaggerated funny expressions, playful and energetic, "
    "square composition, thick outlines, expressive eyes, slightly exaggerated "
    "proportions, Pixar-meets-picture-book aesthetic. "
    "Musical scene: {cover_description} "
    "Include subtle musical elements: small floating music notes, or the "
    "character holding/near an instrument, or a stage-like spotlight feel. "
    "NOT a realistic concert — cartoon musical energy. "
    "DO NOT make it dreamy, muted, watercolor, or soft. This is comedy + music, not bedtime. "
    "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS anywhere in the image."
)
```

### Cover Specs

| Property | Value |
|----------|-------|
| Size | 512x512 |
| Format | WebP |
| Filename | `{song_id}.webp` |
| Location | `public/covers/silly-songs/` |
| Animation | Static for now (SMIL animation planned later) |

### Cover Description Rules

- Show the song's **iconic moment** — the single image that captures what the song is about
- Include **subtle musical elements** (notes, instrument, performance pose)
- Must be visually distinguishable from funny short covers (musical cues signal "this is a song")
- Bold, bright, cartoon — NOT dreamy or soft

---

## JSON Schema

```json
{
    "id": "not-a-rock",
    "title": "Not a Rock",
    "age_group": "2-5",
    "duration_seconds": 75,
    "lyrics": "[verse]\n...\n[chorus]\n...",
    "style_prompt": "children's song, funny, upbeat, ukulele...",
    "cover_description": "A big green crocodile lying flat...",
    "cover_file": "not-a-rock.webp",
    "animation_preset": "bounce_rhythmic",
    "audio_file": "not-a-rock.mp3",
    "created_at": "2026-03-28",
    "play_count": 0,
    "replay_count": 0
}
```

### Required Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | URL-safe slug |
| `title` | string | Display name |
| `age_group` | string | `2-5`, `6-8`, or `9-12` |
| `duration_seconds` | int | Target duration (updated after generation) |
| `lyrics` | string | Full lyrics with section tags |
| `style_prompt` | string | ACE-Step description/tags |
| `cover_description` | string | Scene description for FLUX |
| `cover_file` | string/null | WebP filename (null before generation) |
| `animation_preset` | string | For future SMIL: `bounce_rhythmic`, `sway`, `pulse` |
| `audio_file` | string/null | MP3 filename (null before generation) |
| `created_at` | string | YYYY-MM-DD |
| `play_count` | int | First plays |
| `replay_count` | int | Subsequent plays |

---

## File Layout

```
dreamweaver-backend/
  data/silly_songs/
    not-a-rock.json
    sneezy-bear.json
    ...
  public/audio/silly-songs/
    not-a-rock.mp3
    sneezy-bear.mp3
    ...
  public/covers/silly-songs/
    not-a-rock.webp
    sneezy-bear.webp
    ...
  scripts/
    generate_silly_songs.py      # Audio generation
    generate_silly_song_covers.py # Cover generation
  app/api/v1/
    silly_songs.py               # API endpoint
```

---

## Audio Persistence

### Backup Location

`/opt/audio-store/silly-songs/` on GCP server (outside git repo).

### Auto-Recovery

The generation script (`generate_silly_songs.py`) automatically:
1. **On startup**: Checks `/opt/audio-store/silly-songs/` and copies any missing files to `public/audio/silly-songs/`
2. **After generation**: Backs up each new MP3 to the persistent store
3. **Manual recovery**: `python3 scripts/generate_silly_songs.py --recover`

### Docker Safety

The backend runs in Docker but the `public/` directory is on the host filesystem. Docker rebuilds do NOT affect audio files. However, `git clone` (re-cloning the repo) WILL wipe `public/audio/silly-songs/` since audio is gitignored. The persistent store at `/opt/audio-store/` survives re-clones.

---

## API

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/silly-songs` | GET | List songs (filter by `?age_group=`) |
| `/api/v1/silly-songs/{id}` | GET | Get single song (includes lyrics) |
| `/api/v1/silly-songs/{id}/play` | POST | Increment play count |
| `/api/v1/silly-songs/{id}/replay` | POST | Increment replay count |

### Audio Serving

- **Local dev**: FastAPI static mount at `/audio/silly-songs/`
- **Production**: nginx alias (add to nginx config alongside funny-shorts)

### Cover Serving

- **Local dev**: FastAPI static mount at `/covers/silly-songs/`
- **Production**: nginx alias

---

## Frontend

Songs appear in the Before Bed page under a "Silly Songs" section (below Funny Shorts). Same card layout, same age-group filtering.

- Song cards show `🎵` emoji (not character emojis)
- Covers are `<img>` tags (WebP) not `<object>` (SVG)
- Shared audio player (mini player at bottom) works for both shorts and songs
- Play/replay tracking via `sillySongsApi`

---

## Generation Pipeline (CLI)

```bash
# Step 1: Generate audio (2 variants per song, pick best)
python3 scripts/generate_silly_songs.py --all

# Step 2: Generate covers
python3 scripts/generate_silly_song_covers.py --all

# Step 3: Recover from persistent store (if audio was lost)
python3 scripts/generate_silly_songs.py --recover

# Regenerate specific song
python3 scripts/generate_silly_songs.py --song not-a-rock --force

# More variants for better quality
python3 scripts/generate_silly_songs.py --all --variants 3
```

---

## Evaluation Criteria

After generating, evaluate each song:

| Criteria | What to Listen For | Fail If |
|----------|-------------------|---------|
| Chorus catchiness | Can you hum it after one listen? | Can't remember after 2 listens |
| Vocal clarity | Words understandable? | > 20% garbled |
| Comedy timing | Punchlines land? | Punchlines buried in melody |
| Age match | Musical style fits age group? | 10-year-old would cringe at their song |
| Production quality | Sounds like a real song? | Broken or glitchy |
| Singability | Could a child sing along? | Lyrics fight the melody |
| Duration | 60-90s feels complete? | Cut off or drags |

### The Ultimate Test

Play the song for a child in the target age group. If they sing the chorus afterward, it works.

---

## Pre-Publish Checklist

1. [ ] Audio file exists and plays cleanly
2. [ ] Duration 60-90 seconds
3. [ ] Lyrics have proper section tags ([verse], [chorus], [bridge])
4. [ ] Choruses are identical text
5. [ ] Ends with a goodnight/closing line
6. [ ] Cover image generated (or 🎵 fallback)
7. [ ] `audio_file` set in JSON
8. [ ] `created_at` set to publication date
9. [ ] Audio backed up to `/opt/audio-store/silly-songs/`
10. [ ] Age group is valid (2-5, 6-8, 9-12)

---

## Animation Presets (Future — Not Yet Implemented)

When SMIL animation is added to covers:

| Preset | Animation | Used For |
|--------|-----------|----------|
| `bounce_rhythmic` | translateY 0→-8→0 at 1.5s | Upbeat songs |
| `sway` | rotate -2→2→-2 at 2s | Gentle/mysterious songs |
| `pulse` | scale 1.0→1.03→1.0 at 1.2s | Building/escalating songs |
| `notes_float` | translateY 0→-30 at 3s + fade | Music notes floating up |

Animation should feel **rhythmic** (like moving to a beat), NOT **slapstick** (like funny short wobble/jiggle).

---

## Related Docs

| Doc | What It Covers |
|-----|---------------|
| `docs/SILLY_SONGS_TEST_PLAN.md` | Original 6-song test plan with all lyrics |
| `docs/SILLY_SONGS_COVER_SPEC.md` | Cover generation spec (FLUX + animation presets) |
| `docs/SILLY_SONGS_GENERATION_GUIDELINES.md` | **This file** — comprehensive generation guide |
