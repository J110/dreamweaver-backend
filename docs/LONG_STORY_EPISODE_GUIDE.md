# Long Story Episode Generation Guide

## Overview

The long story episode format (v2) generates immersive bedtime stories designed for
sleep descent. Each episode features:

- Multiple character voices (not just one narrator)
- A song woven into the middle of the story
- Mood-matched music beds that play continuously under narration
- A phase-based sleep descent structure (engaging -> sensory -> dissolving)
- 10-15 minute total duration

The generation script handles the full pipeline: text generation via Mistral AI,
multi-voice TTS via Chatterbox, song generation via MiniMax, music bed assembly,
cover art via FLUX, and final audio assembly with pydub.

---

## Script

```
scripts/generate_long_story_episode.py
```

---

## Usage

### Full generation (text + TTS + song + music + cover)

```bash
python3 scripts/generate_long_story_episode.py --output-dir output/episode_test
```

### With specific parameters

```bash
python3 scripts/generate_long_story_episode.py \
  --mood curious \
  --age-group 6-8 \
  --setting forest \
  --character-type owl \
  --character-personality wise \
  --character-count 2 \
  --journey-type following_a_sound \
  --time-of-day dusk \
  --weather light_mist \
  --output-dir output/episode_test
```

### Resume from existing (skip completed steps)

```bash
python3 scripts/generate_long_story_episode.py \
  --output-dir output/episode_test \
  --resume
```

### Reassembly only (reuse existing TTS)

Delete `episode.mp3` but keep the section WAV files, then run with `--resume`.
The script detects that section audio already exists and skips TTS, proceeding
directly to assembly.

### Dry run (show prompt only)

```bash
python3 scripts/generate_long_story_episode.py --dry-run
```

---

## Story Structure

The script generates text in a strict tagged format. Each tag controls narration
style, TTS parameters, and audio assembly behavior.

```
[INTRO] -- 2-3 sentences, narrator talks to child
[PHASE_1] -- 250-400 words (ages 6-8), engaging journey
  - Character dialogue tagged: OWL: "dialogue"
  - [PHRASE] repeated phrase [/PHRASE]
  - [PAUSE: 800] at discovery moments
  - [BREATHE] for 5s musical swell moments (1-2 per phase)
  - Song transition at end
  - [SONG_SEED: description]
[POST_SONG] -- 2-3 sentences, narrator returns softer
[PHASE_2] -- 300-450 words, sensory, slowing
  - Characters fall asleep during this phase
  - Dialogue stops by mid-phase
  - [PHRASE]...repeated phrase...[/PHRASE]
  - [PAUSE: 1500] between sensory images
  - [BREATHE] for musical swells (3-4 per phase)
[PHASE_3] -- 200-300 words, dissolving fragments
  - 60-80 sentences of 3-5 words each
  - No dialogue, no questions
  - [PHRASE]...barely whispered...[/PHRASE]
  - [PAUSE: 3000] every 10-15 sentences
  - [WHISPER]...final lines...[/WHISPER]
  - Ends with one word or silence
```

### Tag Reference

| Tag | Meaning | Audio Effect |
|-----|---------|-------------|
| `[INTRO]` | Narrator addresses the child | Normal TTS, bed begins |
| `[PHASE_1]` | Engaging exploration phase | Active narration with bed at -20dB |
| `[PHASE_2]` | Sensory wind-down phase | Slower TTS, bed at -14dB |
| `[PHASE_3]` | Dissolving fragments | Whisper-speed TTS, bed at -10dB |
| `[POST_SONG]` | Narrator returns after song | Soft TTS, bed fades back in |
| `[PHRASE]...[/PHRASE]` | Repeated anchor phrase | Slightly slower, more melodic TTS |
| `[PAUSE: N]` | Silence for N milliseconds | Literal silence inserted |
| `[BREATHE]` | Musical swell moment | Bed volume rises +10dB for 5s |
| `[WHISPER]...[/WHISPER]` | Final whispered lines | Minimal exaggeration TTS |
| `[SONG_SEED: desc]` | Song topic/mood hint | Used to generate song lyrics |
| `OWL: "dialogue"` | Character speech | TTS switches to character voice |

---

## Audio Assembly Timeline

The final episode is assembled from section WAVs, the song, and a continuous
mood-matched music bed. The timeline is:

```
[Music intro (mood-specific, ~6s)]
[2s silence]
[Part A: intro + phase_1 narration with bed at -20dB]
  - Bed starts from first narrator word
  - [BREATHE] tags create +10dB swells (1.5s ramp up, 2s hold, 1.5s ramp down)
  - Bed fades out 2s before song
[500ms silence]
[Song (with 2s fade-in and 2s fade-out)]
[500ms silence]
[Part B: post_song + phase_2 narration with bed at -14dB]
  - Bed fades in over 2s coming back after song
  - [BREATHE] swells more prominent at -14dB base
[Part C: phase_3 narration with bed at -10dB]
  - Bed is the primary sound, narration dissolves into it
[30s bed tail fading to silence]
```

Key points:

- The bed is continuous from intro through Phase 3 -- it only goes silent during
  the song section.
- There is no separate outro music track. The 30-second bed fade at the end IS
  the outro.
- Song fade-in/out (2s each) prevents abrupt transitions.

---

## Voice Assignment

Voice assignment follows a contrast-maximizing strategy:

- **Narrator**: always `female_2` (or mood-specific override)
- **Characters**: assigned for maximum gender contrast from the narrator
  - If narrator is female, the first character gets a male voice
  - Second character gets the next available contrasting voice
- **Dialogue routing**: character dialogue uses type labels in the text
  (e.g., `OWL:`, `PIP:`) which are mapped to character names (e.g., Hoot, Pip)
- **Voice map**: stored in `metadata.json` under the `voice_map` key

---

## TTS Parameters

Each section uses different Chatterbox parameters to create the sleep descent
effect. Exaggeration and speed decrease as the story progresses; lower values
produce softer, slower speech.

| Section | Exaggeration | Speed | CFG Weight |
|---------|-------------|-------|------------|
| intro | 0.55 | 0.88 | 0.50 |
| phase_1 | 0.50 | 0.85 | 0.50 |
| phrase | 0.60 | 0.78 | 0.42 |
| song_transition | 0.45 | 0.80 | 0.48 |
| post_song | 0.40 | 0.78 | 0.45 |
| phase_2 | 0.35 | 0.78 | 0.40 |
| phase_3 | 0.25 | 0.72 | 0.35 |
| whisper | 0.15 | 0.68 | 0.30 |

---

## Phase 3 TTS Batching

Chatterbox cannot handle 1-3 word inputs -- it either hangs or produces garbled
audio. Phase 3 contains 60-80 very short sentences (3-5 words each), so a
batching strategy is used:

- Adjacent short narration lines (fewer than 4 words) are joined with `"... "`
  as a separator
- The buffer flushes when it reaches 8 or more words
- Pauses, breathes, phrases, and dialogue lines act as batch boundaries
  (they force a flush)
- This reduces approximately 80 TTS calls down to around 41 segments

The batching logic lives in the `_batch_short_lines()` function within the
generation script.

---

## Song Generation

Each episode includes an original song that bridges Phase 1 and Phase 2.

- **Lyrics**: generated via Mistral AI based on story content and the
  `[SONG_SEED]` tag
- **Audio**: generated via MiniMax Music 1.5 on Replicate (model: `minimax/music-01`)
- **Style varies by mood**:

| Mood | Style | BPM |
|------|-------|-----|
| curious | soft celesta and light harp | 85 |
| calm | gentle piano and soft strings | 72 |

(Other moods follow similar patterns with mood-appropriate instrumentation
and tempo.)

- **Validation**: song relevance is checked -- it must share words with the story
  and mention a character name

---

## Cover Generation

- Generated via FLUX.1-schnell through Together AI
- Watercolor children's illustration style
- Falls back to a placeholder image if the API is unavailable

---

## Output Files

A complete generation produces the following files in the output directory:

```
output_dir/
  metadata.json    -- Full episode metadata (characters, voice_map, sections, etc.)
  story_raw.txt    -- Raw LLM response
  song_lyrics.txt  -- Generated song lyrics
  song.mp3         -- Song audio (MiniMax)
  cover.webp       -- Cover image (FLUX)
  intro.wav        -- Section TTS audio
  phase_1.wav
  post_song.wav
  phase_2.wav
  phase_3.wav
  episode.mp3      -- Final assembled episode
```

---

## Word Count Targets by Age Group

The LLM prompt adjusts word counts based on the target age group:

| Age Group | Phase 1 | Phase 2 | Phase 3 | Total |
|-----------|---------|---------|---------|-------|
| 2-5 | 200-300 | 200-350 | 150-250 | 550-900 |
| 6-8 | 250-400 | 300-450 | 200-300 | 750-1150 |
| 9-12 | 300-500 | 350-500 | 250-400 | 900-1400 |

---

## Character Count Options

The `--character-count` flag controls the story's cast:

- **1 character**: Solo story. The character talks to themselves, the moon,
  the wind, or other non-speaking elements.
- **2 characters**: Main character plus a companion. The companion falls asleep
  during Phase 2.
- **3 characters**: Main character plus two companions. One falls asleep early
  in Phase 2, the other falls asleep mid-Phase 2. The main character is the
  last voice heard before Phase 3 narration takes over.

---

## Mood Options

Six moods are supported, each affecting music bed selection, song style,
narration tone, and story atmosphere:

- `curious`
- `calm`
- `wired`
- `sad`
- `anxious`
- `angry`

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mistralai` | Text generation and song lyrics |
| `pydub` | Audio assembly (mixing, fading, concatenation) |
| `requests` | TTS API calls and cover API calls |
| `replicate` | Song audio generation via MiniMax |
| `ffmpeg` | Required by pydub. PATH must include `/opt/homebrew/bin` on macOS |

---

## Integration with Pipeline

The content pipeline (`scripts/pipeline_run.py`) calls this script for long story
generation instead of the older matrix-based approach. See the `step_generate()`
function in the pipeline orchestrator for how it invokes the episode generator
and passes parameters.

---

## Known Issues and Tips

### LLM output quirks

- **Markdown-wrapped tags**: Mistral sometimes wraps tags in markdown bold
  (e.g., `**[PHASE_3]**` instead of `[PHASE_3]`). This is handled by the
  `clean_markdown()` function.
- **Untagged dialogue**: The LLM occasionally produces character dialogue without
  the expected label prefix. This is handled by `fix_untagged_dialogue()`.
- **Phase 3 word count**: The LLM tends to confuse "short sentences" with
  "short section", producing too few lines. The prompt explicitly instructs
  "60-80 sentences, MANY short sentences not FEW" to counteract this.

### TTS quirks

- **Chatterbox hangs on short inputs**: 1-3 word inputs cause Chatterbox to
  hang or produce garbled output. Solved by the `_batch_short_lines()` batching
  strategy described above.

### Audio assembly notes

- Song fade-in/out (2s each) prevents abrupt transitions between narration
  and song.
- The bed is continuous from intro through Phase 3. It only goes silent during
  the song.
- There is no separate outro music file for long stories. The 30-second bed
  fade at the end serves as the outro.
