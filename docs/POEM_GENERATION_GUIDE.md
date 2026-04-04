# Poem Generation Guide

Musical poems for the Before Bed tab. Spoken word with musical backing — not songs.

---

## Quick Start

```bash
cd dreamweaver-backend

# Generate all 3 test poems (one per age group, default mood: calm)
python3 scripts/generate_experimental_poems.py --all

# Generate 3 mood-varied poems (wired/calm/curious)
python3 scripts/generate_experimental_poems.py --mood-test

# Generate for specific age + mood
python3 scripts/generate_experimental_poems.py --age 6-8 --mood wired

# Dry run (no API calls)
python3 scripts/generate_experimental_poems.py --mood-test --dry-run

# Text + cover only (skip MiniMax audio)
python3 scripts/generate_experimental_poems.py --all --skip-audio
```

---

## Pipeline

1. **Text** (Mistral `mistral-large-latest`) — generates poem in JSON format
2. **Validation** — line count (8-16), word count (max 8/line), syllable count (max 9/line), couplet rhyme check, syllable consistency, character limit (500 for MiniMax)
3. **Audio** (MiniMax Music) — fal.ai v2 primary, Replicate 1.5 fallback
4. **Cover** (FLUX) — via Replicate `black-forest-labs/flux-schnell` (Pollinations preferred for production pipeline)
5. **Save** — JSON metadata + MP3 + WebP cover

---

## Poem Types

| Type | Description | Best Ages |
|------|-------------|-----------|
| `sound` | Onomatopoeia — words ARE the sounds | 2-5 |
| `nonsense` | Made-up words, mouth feel | 6-8 |
| `question` | Chain of absurd unanswerable questions | 9-12 |
| `tongue_twister` | Alliteration that trips the mouth | any |
| `list` | One category explored through rhythm | any |
| `tiny_story` | Complete narrative in 8-12 lines | any |

---

## Mood System

Each poem is generated for a child mood. Mood affects type selection, tempo, style prompt energy, and word choices.

### Mood-to-Energy

| Mood | Energy Description | Tempo Offset |
|------|-------------------|--------------|
| `wired` | bouncy and playful, fun energy that channels into rhythm | +5 BPM |
| `curious` | dreamy and wondering, spacious, leaves room to think | +0 BPM |
| `calm` | soft and settling, warm steady rhythm, almost a lullaby | -8 BPM |
| `sad` | gentle and tender, quiet rhythm, words that feel like a hug | -10 BPM |
| `anxious` | cozy and reassuring, steady predictable rhythm, safe and warm | -5 BPM |
| `angry` | firm then softening, strong rhythm that gradually settles | +0 BPM |

### Mood-to-Type Filtering

| Mood | Preferred Poem Types |
|------|---------------------|
| `wired` | nonsense, tongue_twister, sound |
| `curious` | question, list, tiny_story |
| `calm` | sound, tiny_story, nonsense |
| `sad` | tiny_story, question, list |
| `anxious` | sound, nonsense, tiny_story |
| `angry` | tongue_twister, sound, list |

### Base Tempo Ranges (before mood offset)

| Age Group | BPM Range |
|-----------|-----------|
| 2-5 | 95-108 |
| 6-8 | 100-112 |
| 9-12 | 105-115 |

---

## How Poems Differ from Songs

| Dimension | Silly Songs | Poems |
|-----------|-------------|-------|
| Structure | Verse-chorus-verse-chorus | Continuous flowing rhythm, no chorus |
| Content | Child's protest words | Language itself being fun |
| Vocal | Singing | Spoken word with melody underneath |
| Tempo | 112-126 BPM | 95-118 BPM |
| Length | ~60 seconds | 30-45 seconds |
| Lines | 18-20 | 8-16 |
| Rhyme | End-of-line | Couplets (aa bb cc dd) |

---

## Style Prompt Structure

The MiniMax style prompt is built from mood energy, instruments, and tempo:

```
Children's musical poem, {instruments}, {tempo} BPM,
{mood_energy},
clear warm vocal, every word easy to understand
```

### Instrument Pools (per age group)

**2-5:** xylophone and soft claps, kalimba and gentle shaker, music box and light tambourine

**6-8:** acoustic guitar and finger snaps, ukulele and soft bongos, piano and light brush drums

**9-12:** acoustic guitar and lo-fi beat, piano and soft snare, guitar and gentle beatbox

---

## Syllable Consistency

The generation prompt instructs Mistral to keep all lines between 6-8 syllables. Validation checks for lines that deviate more than 3 syllables from the poem's average. This prevents MiniMax from rushing long lines and stretching short ones.

Syllable issues are **warnings only** — they don't reject the poem. On retry, syllable feedback is included in the prompt.

---

## Output Structure

Files are saved to:
- **Metadata:** `seed_output/poems_test/{poem_id}.json`
- **Audio:** `public/audio/poems/{poem_id}.mp3`
- **Covers:** `public/covers/poems/{poem_id}_cover.webp`

For production serving, copy to `data/poems/` (JSON) for the API.

### Metadata Schema

```json
{
  "id": "nonsense_6_8_526b",
  "title": "Zizzle Zing Zoom",
  "content_type": "poem",
  "poem_type": "nonsense",
  "age_group": "6-8",
  "mood": "wired",
  "instruments": "piano and light brush drums",
  "tempo": 111,
  "poem_text": "...",
  "char_count": 236,
  "line_count": 8,
  "audio_file": "nonsense_6_8_526b.mp3",
  "cover_file": "nonsense_6_8_526b_cover.webp",
  "cover_context": "...",
  "style_prompt": "...",
  "duration_seconds": 36,
  "audio_engine": "minimax-music-1.5-replicate",
  "created_at": "2026-04-03"
}
```

---

## Diversity Check (Anti-Duplication)

The generation script automatically loads all existing poems from `data/poems/` and appends an anti-duplication section to the Mistral prompt. For each poem type being generated, it lists existing poems' titles and opening lines, instructing the model to use completely different subjects, titles, and imagery.

This prevents issues like two "question" poems both being titled "Why Does the Moon?" with identical opening lines.

**How it works:**
- `load_existing_poems()` reads all `data/poems/*.json`
- `build_anti_duplication_prompt()` filters to same `poem_type` and builds a "DO NOT DUPLICATE" section
- Appended to the generation prompt before every Mistral call

---

## Publishing to Before Bed

1. Generate poems: `python3 scripts/generate_experimental_poems.py --mood-test`
2. Copy JSON to data dir: `cp seed_output/poems_test/{id}.json data/poems/`
3. Audio already saved to `public/audio/poems/`
4. Cover already saved to `public/covers/poems/`
5. Backend API serves from `data/poems/` at `/api/v1/poems`
6. Frontend Before Bed tab loads poems section automatically

---

## Cover Generation

**Preferred:** Pollinations (for production pipeline)

**Current fallback chain:**
1. Replicate `black-forest-labs/flux-schnell` ($0.003/image)
2. Together AI FLUX.1-schnell (free tier — may be unavailable)
3. Placeholder SVG

**Prompt rules:**
- Always include "no text no words no letters no characters no faces"
- Use "abstract minimal art, soft watercolor, dreamy, children book illustration"
- Each poem type gets a distinct visual mood

---

## Cost Per Run

```
3 Mistral calls:        ~$0.01  (free tier)
3 MiniMax generations:  ~$0.11  (Replicate)
3 FLUX covers:          ~$0.01  (Replicate)
Total:                  ~$0.13
```

---

## Evaluation Checklist

After generating, listen to each poem and check:

1. Can you hear every word clearly?
2. Is the rhythm strong enough to rock to?
3. Does it feel like spoken word, not singing?
4. Could a child repeat a line after hearing it twice?
5. Is it distinctly different from a silly song?
6. For mood-varied sets: does wired feel more energetic than calm?
