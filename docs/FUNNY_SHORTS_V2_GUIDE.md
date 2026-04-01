# Funny Shorts V2 Generation Guide

Complete reference for generating new Funny Shorts V2 episodes. This document covers the format, characters, audio pipeline, and publishing workflow so you can create new episodes without reading the source code.

---

## 1. Overview

Funny Shorts V2 is a **pure conversation comedy** format. Nothing "happens" -- no machines, no inventions, no physical events. Just characters talking. The comedy lives in what they say to each other: how they argue, lie, explain, and negotiate.

**Key properties:**

- **3-section structure**: HOST_INTRO, THE_CONVERSATION, THE_END
- **Target duration**: 60-120 seconds depending on age group
- **Age groups**: 2-5, 6-8, 9-12
- **Tone**: Calm comedy. The child should smile and giggle softly, not scream with laughter. Think Pixar, not Cartoon Network.
- **Audio**: Baked music (comedy bed + intro/outro jingle), NOT client-side ambient music
- **Script**: `scripts/generate_funny_shorts_v2.py`

---

## 2. Characters & Voices

There are 5 character voices. Each has a distinct personality, TTS voice reference, and tuned parameters for Modal Chatterbox TTS.

### Boomy

| Parameter | Value |
|-----------|-------|
| voice_id | `comedic_villain` |
| exaggeration | 0.55 |
| speed | 0.95 |
| cfg_weight | 0.55 |

**Personality**: Confident, sure of himself. Not louder -- FASTER. Misplaced confidence. Always wrong but never doubts himself.
**Catchphrase**: "That was SUPPOSED to happen."
**Age restrictions**: Available for all age groups.

### Pip

| Parameter | Value |
|-----------|-------|
| voice_id | `high_pitch_cartoon` |
| exaggeration | 0.65 |
| speed | 1.10 |
| cfg_weight | 0.50 |

**Personality**: Quick, slightly breathless, exasperated. The fastest-speaking character. Always right, never listened to.
**Catchphrase**: "I said this would happen. I SAID."
**Age restrictions**: Do NOT use for ages 9-12 (too childish for older kids).

### Shadow

| Parameter | Value |
|-----------|-------|
| voice_id | `mysterious_witch` |
| exaggeration | 0.45 |
| speed | 0.88 |
| cfg_weight | 0.60 |

**Personality**: Measured but not glacial. Precise, over-formal. Speaks with absolute confidence about things that are completely wrong.
**Catchphrase**: "According to my calculations... hmm."
**Age restrictions**: Do NOT use for ages 2-5 (too formal for young children).

### Sunny

| Parameter | Value |
|-----------|-------|
| voice_id | `young_sweet` |
| exaggeration | 0.60 |
| speed | 1.00 |
| cfg_weight | 0.48 |

**Personality**: Bright, warm, snappy optimism. Not slow -- peppy. Relentlessly optimistic about disasters.
**Catchphrase**: "This is fine! This is completely fine."
**Age restrictions**: Available for all age groups.

### Melody (Narrator/Host)

| Parameter | Value |
|-----------|-------|
| voice_id | `musical_original` |
| exaggeration | 0.50 |
| speed | 0.95 |
| cfg_weight | 0.55 |

**Personality**: Narrator and host. Clear, warm, conspiratorial. Slightly faster than story narrators. Talks directly to the child.
**Catchphrase**: "And that's when things got... interesting."
**Age restrictions**: Used in every episode as the host.

### MELODY_BREAKING (after [BREAK] tag)

When Melody loses composure (triggered by the `[BREAK]` tag), her TTS parameters shift:

| Parameter | Normal | Breaking |
|-----------|--------|----------|
| voice_id | `musical_original` | `musical_original` |
| exaggeration | 0.50 | **0.65** |
| speed | 0.95 | 0.95 |
| cfg_weight | 0.55 | **0.45** |

Higher exaggeration and lower cfg_weight produce a less controlled, more amused delivery. The breaking state applies only to the next Melody line after the `[BREAK]` tag, then resets.

### Character Selection by Age Group

| Age Group | Available Characters |
|-----------|---------------------|
| 2-5 | Boomy, Pip, Sunny, Melody |
| 6-8 | All 5 characters |
| 9-12 | Boomy, Shadow, Sunny, Melody |

Use 2-3 characters per episode (plus Melody as host). Never use all 5.

---

## 3. Script Format

### Section Tags

Scripts use exactly 3 sections:

```
[HOST_INTRO]
Melody introduces the episode to the child in 1-2 sentences.
[/HOST_INTRO]

[THE_CONVERSATION]
Characters talk. This is 60-80% of the episode runtime.
[/THE_CONVERSATION]

[THE_END]
Melody wraps up in 1-2 sentences. Goodnight.
[/THE_END]
```

### Dialogue Format

Character lines use the format:

```
CHARACTER: "dialogue text"
```

Examples:
```
BOOMY: "That was SUPPOSED to happen."
PIP: "Really?"
MELODY: "So... I overheard Boomy and Pip talking today."
```

### Inline Tags

Three inline tags can appear within or between dialogue lines:

- **`[SFX: name]`** -- Plays a sound effect. Must be one of the 14 names in the SFX library.
- **`[PAUSE: ms]`** -- Inserts silence. Common values: 400 (beat), 600 (before punchline), 800 (peak moment, use once max).
- **`[BREAK]`** -- Marks that Melody loses composure on her next line. Can be standalone or at the end of a dialogue line.

### Metadata Tags

At the top of the script (before sections):

```
[TITLE: The Dark Is Totally Fine]
[CHARACTERS: Boomy, Pip, Melody]
```

### Word Count Targets by Age Group

| Age Group | Word Count | Duration Target | Words per Line |
|-----------|-----------|-----------------|----------------|
| 2-5 | 100-150 words | 60-75 seconds | 4-6 words |
| 6-8 | 150-200 words | 75-90 seconds | 6-10 words |
| 9-12 | 180-220 words | 80-95 seconds | 8-12 words |

### SFX Rules

- Use 4-6 SFX per episode.
- SFX are emotional punctuation, NOT information carriers.
- The episode MUST make complete sense with ALL SFX removed.
- Pick ONLY from the 14-name library (see Section 4).

---

## 4. SFX Library

All 14 SFX are pre-generated once via CassetteAI (fal.ai) and stored at `output/funny_shorts_v2/sfx/`. Each is a short WAV file.

| SFX Name | CassetteAI Prompt | Emotional Meaning |
|----------|-------------------|-------------------|
| `soft_splat` | Soft gentle splat sound like a small ball of mud landing on something, not violent, almost cute, with a slight squelch | Someone landing on the truth |
| `gentle_crash` | Gentle slow-motion crash, things falling softly one after another, tinkle clink bonk thud, like a shelf of soft toys falling in slow motion | A claim falling apart |
| `pillow_thud` | Soft thud like something landing on a pillow, poomf, gentle and warm | Giving up |
| `spring_boing` | Gentle cartoon boing sound, a soft spring bouncing, not loud, warm and silly | Surprise realization |
| `slide_whistle_up` | Soft slide whistle going up gently, like something slowly floating upward, whimsical not shrill | Escalating absurdity |
| `slide_whistle_down` | Soft slide whistle going down gently, like something slowly deflating, sad in a funny way | Argument slowly collapsing |
| `gear_clink` | Tiny mechanical clicking and whirring, like a small invention starting up, delicate, intricate, tick-tick-tick-whirr | Brain working (incorrectly) |
| `tiny_squeak` | Tiny gentle squeak, like a small rubber duck being gently pressed, cute and quiet | Confidence deflating |
| `soft_pop` | Gentle soft pop sound, like a soap bubble popping, barely there, delicate | A lie popping |
| `gentle_rumble` | Soft gentle stomach rumble, quiet and slightly embarrassing, not gross just funny, grumble grumble | Stomach betraying a lie |
| `single_cricket` | A single cricket chirping in awkward silence, chirp chirp, the loneliest funniest sound, perfectly timed comedy silence | Awkward silence |
| `gentle_wind` | Soft gentle breeze, like a tumbleweed moment but cozy, quiet comedic emptiness | Tumbleweed silence |
| `soft_ding` | Gentle soft ding like a tiny bell, a small lightbulb moment, an idea arriving quietly | An idea arriving |
| `warm_tada` | Very gentle warm ta-da, like a shy trumpet trying to celebrate but too quiet, endearing | Sarcastic victory |

**Generation command** (one-time, already done):
```bash
python3 scripts/generate_funny_shorts_v2.py --sfx
```

SFX are generated via the `cassetteai/sound-effects-generator` endpoint on fal.ai (durations under 10s use SFX generator instead of music generator).

---

## 5. Intro/Outro Jingle

Five candidate jingles were generated and auditioned. The **winner is funny_2** (gentle kazoo melody).

**Source files**:
- `output/funny_shorts_v2/intro_candidates/funny_2_intro.mp3` (5 seconds, with 0.5s fade-out)
- `output/funny_shorts_v2/intro_candidates/funny_2_outro.mp3` (20 seconds, with 1s fade-in)

**Canonical paths** (the assembler looks here first):
- `output/funny_shorts_v2/show_intro.mp3`
- `output/funny_shorts_v2/show_outro.mp3`

If the canonical paths do not exist, the assembler falls back to the funny_2 files in `intro_candidates/`.

**Generation command** (one-time, already done):
```bash
python3 scripts/generate_funny_shorts_v2.py --intro-outro
```

---

## 6. How to Generate New Episodes

### Step 1: Add Episode Seeds

Open `scripts/generate_funny_shorts_v2.py` and add new entries to the `EPISODE_SEEDS` dict. Each seed has:

```python
EPISODE_SEEDS = {
    "2-5": {
        "setup": "Description of the comedic situation...",
        "characters": ["boomy", "pip", "melody"],
        "comedy_type": "terrible_excuse",
    },
    "6-8": {
        "setup": "Description of the comedic situation...",
        "characters": ["shadow", "sunny", "pip", "melody"],
        "comedy_type": "expert_who_isnt",
    },
    "9-12": {
        "setup": "Description of the comedic situation...",
        "characters": ["boomy", "melody"],
        "comedy_type": "negotiation",
    },
}
```

**Fields:**
- `setup`: A paragraph describing the conversational scenario. Keep it pure dialogue -- no events, no inventions.
- `characters`: List of 2-3 character names (lowercase) plus `"melody"`. Respect age restrictions.
- `comedy_type`: Category tag (see Section 7).

### Step 2: Run Generation

```bash
cd /path/to/dreamweaver-backend
python3 scripts/generate_funny_shorts_v2.py --episodes
```

This runs the full pipeline for each seed:
1. Generates script via Mistral AI
2. Generates comedy bed via CassetteAI
3. Generates TTS for all dialogue segments via Modal Chatterbox
4. Assembles narration + SFX + comedy bed + intro/outro
5. Generates cover image via Pollinations FLUX

**Outputs per episode** (in `output/funny_shorts_v2/episodes/`):
- `funny_{age}_{hex6}.mp3` -- Final episode with music
- `funny_{age}_{hex6}_nomusic.mp3` -- Episode without music bed
- `funny_{age}_{hex6}_cover.webp` -- Cover image (512x512)
- `funny_{age}_{hex6}.json` -- Episode metadata

### Step 3: Publish to the App

#### 3a. Copy Audio Files

```bash
cp output/funny_shorts_v2/episodes/{id}.mp3 ../dreamweaver-web/public/audio/funny-shorts/
```

#### 3b. Copy Cover Files

```bash
cp output/funny_shorts_v2/episodes/{id}_cover.webp ../dreamweaver-web/public/covers/funny-shorts/
```

#### 3c. Create Data JSON

Create a JSON file at `data/funny_shorts/{slug}.json` with the following schema:

```json
{
  "id": "funny_2_5_a1b2c3",
  "slug": "the-dark-is-totally-fine",
  "title": "The Dark Is Totally Fine",
  "content_type": "funny_short_v2",
  "age_group": "2-5",
  "characters": ["boomy", "pip", "melody"],
  "comedy_type": "terrible_excuse",
  "duration_seconds": 75,
  "audio_variants": {
    "with_music": "/audio/funny-shorts/funny_2_5_a1b2c3.mp3",
    "no_music": "/audio/funny-shorts/funny_2_5_a1b2c3_nomusic.mp3"
  },
  "cover": "/covers/funny-shorts/funny_2_5_a1b2c3_cover.webp",
  "has_baked_music": true,
  "created_at": "2026-04-01"
}
```

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique ID from the generated filename |
| `slug` | string | URL-friendly version of title |
| `title` | string | Episode title from [TITLE: ...] tag |
| `content_type` | string | Always `"funny_short_v2"` |
| `age_group` | string | `"2-5"`, `"6-8"`, or `"9-12"` |
| `characters` | array | Character names used in this episode |
| `comedy_type` | string | Comedy category (see Section 7) |
| `duration_seconds` | int | Duration from the generated metadata |
| `audio_variants` | object | Paths to with-music and no-music MP3s |
| `cover` | string | Path to cover image |
| `has_baked_music` | bool | Always `true` for V2 (music is baked in) |
| `created_at` | string | Date in YYYY-MM-DD format |

#### 3d. Commit and Push

```bash
# Backend repo (data JSON)
cd /path/to/dreamweaver-backend
git add data/funny_shorts/
git commit -m "Add funny short: The Dark Is Totally Fine"
git push origin main

# Frontend repo (audio + covers)
cd /path/to/dreamweaver-web
git add public/audio/funny-shorts/ public/covers/funny-shorts/
git commit -m "Add funny short assets: The Dark Is Totally Fine"
git push origin main
```

#### 3e. Deploy to GCP Production

**Backend** (data JSON):
```bash
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-a
cd /opt/dreamweaver-backend
git pull origin main   # NO sudo
sudo docker-compose down && sudo docker-compose up -d --build
```

**Frontend** (audio + covers -- served by nginx, no rebuild needed):
```bash
cd /opt/dreamweaver-web
git pull origin main   # NO sudo
# Audio and covers are served directly by nginx aliases -- no npm build needed
```

---

## 7. Comedy Types

The `comedy_type` field categorizes the conversational dynamic. Known types:

| Comedy Type | Description |
|-------------|-------------|
| `terrible_excuse` | A character makes a claim and their excuses get progressively worse |
| `expert_who_isnt` | A character explains something with total confidence while being completely wrong |
| `negotiation` | A character tries to negotiate their way out of something, negotiations go badly |

You can invent new comedy types as needed. The type is a metadata tag used for content diversity tracking -- it does not affect generation behavior. Some ideas:

- `misunderstanding` -- Characters talk past each other
- `one_upping` -- Characters try to outdo each other
- `denial` -- Character denies something that is obviously true
- `over_planning` -- Characters over-plan something simple until it collapses

---

## 8. Content Generation Prompt

The Mistral AI prompt enforces these key rules:

**Format**: Pure conversation. Nothing "happens." The child's eyes are closed -- they hear VOICES, that is all.

**Conversation shape**:
1. Starts normal
2. One character says something slightly wrong
3. The other character questions it
4. The first character doubles down
5. It escalates -- each line digs the hole deeper
6. Catchphrases arrive at natural moments of failure
7. It reaches a peak of absurdity
8. It collapses -- someone gives up, falls asleep, or accidentally proves themselves wrong

**Rules**:
- No character speaks more than 2 lines in a row (it is a rally, not a monologue)
- Each line is short (word counts per age group above)
- SFX are chosen ONLY from the 14-name library
- Each character's catchphrase appears 1-2 times, never forced
- Exactly 1 `[BREAK]` moment where Melody loses composure
- `[PAUSE: 600]` before punchlines -- the silence IS the joke
- Escalation through conversation: small claim at line 1, medium at line 5, absurd at line 10, collapse at line 15

**System prompt for Mistral**: "You are a children's comedy writer specializing in calm bedtime humor. You write short, punchy comedy scripts for audio production. Output ONLY the script in the exact format requested. No explanations, no markdown code blocks."

**Model**: `mistral-large-latest`, temperature 0.9, max_tokens 2000.

---

## 9. Audio Assembly Pipeline

The pipeline has 5 stages per episode:

### Stage 1: Script Generation (Mistral)

Mistral generates the raw script text. The parser then:
- Extracts `[TITLE: ...]` and `[CHARACTERS: ...]` metadata
- Identifies section boundaries (`[HOST_INTRO]`, `[THE_CONVERSATION]`, `[THE_END]`)
- Splits each line around inline `[SFX:]`, `[PAUSE:]`, and `[BREAK]` tags
- Assigns each text chunk to the correct speaker (tracks `_last_speaker` for continuity after inline tags)

### Stage 2: Comedy Bed (CassetteAI via fal.ai)

A 2-minute comedy underscore generated with this prompt: soft pizzicato, light playful percussion, 95 BPM, warm and quiet. Generated via the `cassetteai/music-generator` endpoint. Cached per age group at `output/funny_shorts_v2/episodes/bed_{age_group}.wav`.

### Stage 3: TTS (Modal Chatterbox)

Each dialogue segment is sent to the Modal Chatterbox TTS endpoint with character-specific parameters.

Pre-processing:
- `normalize_caps_for_tts()` converts ALL CAPS words to Title Case (prevents TTS from spelling them letter-by-letter)
- Same function strips any leftover bracket tags (`[SFX: ...]`, `[PAUSE: ...]`, `[BREAK]`, section tags) as a safety net
- Short lines (4 words or fewer) get a `"... "` prefix to prevent abrupt TTS starts
- A throwaway TTS call with `"."` is made at the end to prevent a Chatterbox quirk where the last real line gets repeated

`[BREAK]` handling: When a `[BREAK]` marker is encountered, the next Melody line uses `MELODY_BREAKING` params (higher exaggeration, lower cfg_weight), then resets.

### Stage 4: Assembly

The assembler builds the final audio in this order:

1. **Show intro** (5s) + 300ms silence
2. **Narration track**: dialogue segments with 150ms gaps between them, pause segments as silent gaps, SFX segments with 100ms gap before and 200ms gap after
3. **1000ms silence** before outro
4. **Show outro** (20s)

**Comedy bed shaping** (`shape_comedy_bed()`):
- Base level: -18dB under narration
- Before punchlines (at `[PAUSE:]` positions): duck to ~-30dB starting 2s before
- After punchlines: lift to -12dB for 2 seconds (the bed "laughs")
- Section transitions: swell to -8dB

The bed is trimmed or looped to match total narration duration, with 500ms fade-in and 2000ms fade-out.

### Stage 5: Export

Two MP3 files at 128kbps:
- `{episode_id}.mp3` -- narration overlaid on shaped comedy bed
- `{episode_id}_nomusic.mp3` -- narration only (no bed)

---

## 10. Cover Generation

Covers are generated via **Pollinations.ai FLUX** image model.

**Prompt template**:
```
Fun warm children's illustration, {title}, cartoon style, gentle colors,
bedtime comedy, cozy and funny, not loud or chaotic, soft warm lighting,
children's book style. ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS.
```

**Parameters**: 512x512, model=flux, nologo=true

**Output format**: The API returns PNG. The script converts it to WebP (quality 85) using Pillow. Falls back to saving as PNG if Pillow conversion fails.

**Frontend compatibility**: The frontend handles both SVG covers (legacy V1) and WebP covers (V2).

---

## 11. Dependencies

### Python Packages

```
httpx          # HTTP client for all API calls
pydub          # Audio manipulation and assembly
Pillow         # Image format conversion (PNG to WebP)
mistralai      # Mistral AI client for script generation
```

### External APIs

| Service | Purpose | Auth |
|---------|---------|------|
| **Mistral AI** | Script generation (`mistral-large-latest`) | `MISTRAL_API_KEY` in `.env` |
| **Modal Chatterbox** | TTS voice generation | `MODAL_TTS_URL` env var (no key needed, public endpoint) |
| **CassetteAI via fal.ai** | SFX generation + comedy bed generation | `FAL_KEY` in `.env` |
| **Pollinations.ai** | Cover image generation (FLUX model) | `POLLINATIONS_API_KEY` in `.env` (optional but recommended) |

### Environment Variables

Required in `dreamweaver-backend/.env`:

```bash
MISTRAL_API_KEY=...       # Mistral AI API key (free experiment tier)
FAL_KEY=...               # fal.ai API key for CassetteAI
POLLINATIONS_API_KEY=...  # Pollinations API key (optional, for auth)
MODAL_TTS_URL=https://mohan-32314--dreamweaver-chatterbox-tts.modal.run  # Default, override if needed
```

### System Dependencies

- `ffmpeg` -- Required by pydub for audio format conversions

---

## 12. Troubleshooting

### SFX Spoken Aloud by TTS

If you hear TTS reading out "[SFX: soft_splat]" literally, the inline tag was not properly stripped before reaching the TTS engine. The safety net in `normalize_caps_for_tts()` strips leftover bracket tags, but if you see this:
- Check that the script parser is correctly splitting inline tags via `_split_inline_tags()`
- Check that the regex `_INLINE_TAG_RE` matches the exact tag format in the script

### Character Voice Continuity After Inline Tags

When an inline tag splits a dialogue line (e.g., `PIP: "I-- [SFX: pillow_thud] --oh no."`), the text after the tag must still be spoken in Pip's voice. The `_last_speaker` global variable tracks this. If a continuation chunk has no character prefix, it inherits `_last_speaker`. If voices are swapping incorrectly:
- Check that `_last_speaker` is being reset at the start of each new script parse (`parse_funny_short()` sets it to `"melody"`)
- Check that `parse_dialogue_line()` updates `_last_speaker` when it detects a character prefix

### Episodes Too Long

If episodes exceed the target duration:
- Reduce word count in the episode seed's `setup` field
- Check TTS speed params -- Pip at 1.10 is the fastest, Shadow at 0.88 is the slowest
- The prompt enforces strict word count limits per age group, but Mistral sometimes exceeds them. Re-run or manually trim the script.
- Check if too many pauses or SFX are inflating duration

### [BREAK] Tag Not Working

The `[BREAK]` tag must trigger `MELODY_BREAKING` params on the next Melody line. If it is not working:
- Ensure `[BREAK]` appears on its own line or at the start of a line (the parser handles both)
- The breaking state applies only to the NEXT Melody line, then resets. If Melody does not speak immediately after `[BREAK]`, the state persists until she does.

### Comedy Bed Missing or Silent

- The comedy bed is cached per age group at `output/funny_shorts_v2/episodes/bed_{age_group}.wav`
- If it failed to generate, delete the file and re-run. It will regenerate.
- The bed is shaped to -18dB baseline, which is intentionally quiet. It should be barely audible under dialogue.

### Intro/Outro Missing

- The assembler first checks `output/funny_shorts_v2/show_intro.mp3` and `show_outro.mp3`
- Falls back to `output/funny_shorts_v2/intro_candidates/funny_2_intro.mp3` and `funny_2_outro.mp3`
- If both are missing, the episode assembles without intro/outro

### TTS Failures

- Modal Chatterbox endpoint has a 120-second timeout per request
- The script retries up to 3 times with increasing backoff (5s, 10s)
- If all retries fail, the episode generation aborts
- Check that the Modal app is deployed and healthy: `curl https://mohan-32314--dreamweaver-chatterbox-tts.modal.run`

### Re-generating SFX or Intro/Outro

These are one-time assets. To regenerate:
```bash
python3 scripts/generate_funny_shorts_v2.py --sfx --force      # Regenerate all 14 SFX
python3 scripts/generate_funny_shorts_v2.py --intro-outro --force  # Regenerate all 5 candidates
```

### Running Everything from Scratch

```bash
python3 scripts/generate_funny_shorts_v2.py --all
```

This runs SFX generation, intro/outro generation, then episode generation in sequence. Existing files are skipped unless `--force` is passed.
