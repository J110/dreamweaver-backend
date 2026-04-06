# Long Story Episode Generation Guide

## Overview

The long story episode format (v2) generates immersive bedtime stories designed for
sleep descent. Each episode is built around four core v2 elements:

1. **A world worth visiting** -- a specific, named, magical place with rules and
   details that make a child think "I want to go there." Not a generic setting
   but a place with purpose: a library where dreams are shelved, a kitchen where
   calm is brewed, a lighthouse that guides sleepy travellers home.

2. **A mystery that resolves into sleep** -- a hook that gives the child a reason
   to keep listening. Something is missing, broken, arriving, lost, strange, or
   someone needs help. The resolution is always rest, sleep, peace, or quiet.
   The plot serves the sleep goal rather than fighting it.

3. **A breathing mechanic** -- a story object that responds to the character's
   breathing. A lantern that glows brighter when you breathe slowly, a door that
   only opens when the air is still, a flower that blooms when you breathe on it
   gently. The child listening unconsciously mirrors the breathing. This is a
   sleep technique disguised as a story element.

4. **A child protagonist** -- the main character is always a child, matched to
   the listener's age group. They should feel like the listener -- someone the
   child becomes, not observes. Supporting characters are mentors or companions
   who help the child understand the world and eventually fall asleep themselves.

Each episode also features:

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

### With specific v2 parameters

```bash
python3 scripts/generate_long_story_episode.py \
  --mood curious \
  --age-group 6-8 \
  --world-type library \
  --mystery-type something_missing \
  --breathing-mechanic lantern \
  --character-count 2 \
  --output-dir output/episode_test
```

### Randomized for diversity (pipeline mode)

```bash
python3 scripts/generate_long_story_episode.py \
  --mood wired \
  --randomize \
  --publish \
  --output-dir output/episode_test
```

`--randomize` uses mood-mapped pools and recency tracking to auto-select world,
mystery, breathing mechanic, character count, and phrase feeling. This is what the
pipeline uses for daily generation.

### Resume from existing (skip completed steps)

```bash
python3 scripts/generate_long_story_episode.py \
  --output-dir output/episode_test \
  --from-metadata
```

Loads `metadata.json` from the output directory and skips text generation, resuming
from TTS onward. Useful for regenerating audio without re-running Mistral.

### Reassembly only (reuse existing TTS)

Delete `episode.mp3` but keep the section WAV files, then run with `--from-metadata`.
The script detects that section audio already exists and skips TTS, proceeding
directly to assembly.

### Dry run (show prompt only)

```bash
python3 scripts/generate_long_story_episode.py --dry-run
```

### Text only (skip audio and cover)

```bash
python3 scripts/generate_long_story_episode.py --text-only
```

### CLI Arguments Reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--mood` | `curious` | One of: curious, calm, wired, sad, anxious, angry |
| `--age-group` | `6-8` | One of: 2-5, 6-8, 9-12 |
| `--world-type` | auto | Story world (see Diversity System below). Auto-selects by mood if omitted |
| `--mystery-type` | auto | Mystery type (see Diversity System below). Auto-selects by mood if omitted |
| `--breathing-mechanic` | auto | Breathing mechanic (see Diversity System below). Random if omitted |
| `--character-count` | `2` | Number of characters: 1, 2, or 3 |
| `--output-dir` | `output/long_story_test` | Where to write all output files |
| `--dry-run` | false | Print the Mistral prompt only, generate nothing |
| `--text-only` | false | Generate text but skip audio and cover |
| `--from-metadata` | false | Resume from saved metadata.json, skip text generation |
| `--publish` | false | Add finished episode to content.json and copy files to web/backend repos |
| `--randomize` | false | Auto-select all params using mood mapping and recency tracking |

---

## Story Structure

The v2 prompt is organized around the four core elements (world, mystery, breathing
mechanic, child protagonist) rather than generic settings and journey types. The
prompt feeds Mistral structured context for each element.

### Prompt Sections

The prompt template (`LONG_STORY_EPISODE_PROMPT`) contains these sections:

- **THE WORLD** -- the world concept and its sleep connection, drawn from
  `STORY_WORLDS[world_type]`
- **THE MYSTERY** -- the mystery setup and its sleep resolution, drawn from
  `MYSTERY_TYPES[mystery_type]`
- **THE BREATHING MECHANIC** -- the mechanic description, drawn from
  `BREATHING_MECHANICS[breathing_mechanic]`
- **THE CHARACTER** -- child protagonist traits from `PROTAGONIST_TYPES[age_group]`,
  plus mentor/companion instructions from `CHARACTER_INSTRUCTIONS[character_count]`
- **MOOD** -- mood-specific energy guidance from `MOOD_TO_STORY_ENERGY[mood]`,
  which tells the LLM how to calibrate Phase 1 engagement and Phase 2 descent
  for each mood (e.g., wired children need more engaging Phase 1 to capture
  excess energy; anxious children need safety from the first line)
- **REPEATED PHRASE** -- a unique-to-this-story phrase under 6 words, appearing
  in all three phases and getting quieter each time
- **STRUCTURE** -- the phase-by-phase structure with word count targets and
  formatting rules

### Tagged Output Format

The script generates text in a strict tagged format. Each tag controls narration
style, TTS parameters, and audio assembly behavior.

```
[CHARACTER: Name, personality, voice_style]

[INTRO] -- 2-3 sentences, narrator talks to child
[PHASE_1] -- Engaging phase: world entered, mystery discovered,
             breathing mechanic obtained, companions met
  - Character dialogue tagged: MIRA: "dialogue"
  - [PHRASE] repeated phrase [/PHRASE]
  - [PAUSE: 800] at discovery moments
  - [BREATHE] for 5s musical swell moments (1-2 per phase)
  - Song transition at end
  - [SONG_SEED: description]
[POST_SONG] -- 2-3 sentences, narrator returns softer
[PHASE_2] -- Mystery resolves into rest/sleep/peace
  - Breathing mechanic works easily now
  - Companion characters fall asleep during this phase
  - Dialogue stops by mid-phase
  - Shift from plot to sensation
  - [PHRASE]...repeated phrase...[/PHRASE]
  - [PAUSE: 1500] between sensory images
  - [BREATHE] for musical swells (3-4 per phase)
[PHASE_3] -- Dissolving fragments
  - Character sits or lies down, breathing mechanic settles
  - Many short sentences (50-70+), not few short sentences
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
| `NAME: "dialogue"` | Character speech | TTS switches to character voice |

---

## Diversity System

v2 replaces the old random pools (settings, character types, journey types) with
a structured diversity system based on story worlds, mystery types, and breathing
mechanics, all mapped to moods and tracked for recency.

### Story Worlds (`STORY_WORLDS`)

Each world has a concept and a sleep connection that tells Mistral why the world
naturally leads to sleep.

| World | Concept | Sleep Connection |
|-------|---------|-----------------|
| `library` | Stories/dreams/memories stored as physical objects | The stored things need rest, just like the child |
| `workshop` | Sleep/dreams/stars/clouds are MADE by someone | The child sees sleep being crafted with care |
| `transport` | A vehicle travelling somewhere magical | The journey itself is the settling -- rocking, rhythm, arrival |
| `garden` | Dreams/thoughts/feelings are plants or weather | Things bloom at night, settle into soil, cycles of rest |
| `observatory` | A place for watching stars, dreams, the night sky | Watching is passive -- doing to observing to resting |
| `kitchen` | Sleep/calm/warmth is cooked or brewed or baked | The recipe requires stillness, slow stirring, patient waiting |
| `post_office` | Delivers dreams/lullabies/goodnight messages | Tonight's delivery is for the listener |
| `museum` | The quietest/oldest/most peaceful things are kept | Exhibits get quieter deeper in -- silence is the final exhibit |
| `lighthouse` | Guides sleepy travellers/dreams/stars home | The light dims when everything is safely home |
| `theater` | The night performs -- stars act, moon directs | The final act is silence, the curtain closes |

### Mystery Types (`MYSTERY_TYPES`)

Each mystery has a setup (the hook) and a sleep resolution (the answer is always
rest/sleep/peace/quiet).

| Mystery | Setup | Sleep Resolution |
|---------|-------|-----------------|
| `something_missing` | Something important has disappeared or gone quiet | It went to rest. It was tired. |
| `something_broken` | Something that usually works has stopped working | It wasn't broken -- it was settling, dreaming, recharging |
| `something_arriving` | Something is coming but nobody knows what | It was sleep itself arriving |
| `something_lost` | The character is looking for something specific | They find it in the quietest place |
| `something_strange` | Something is happening that doesn't make sense | It makes perfect sense once you're still enough |
| `someone_needs_help` | A creature or person needs the character's help | What they needed was company while they fell asleep |

### Breathing Mechanics (`BREATHING_MECHANICS`)

Each mechanic is a story object that responds to the character's calm breathing.
The child listening unconsciously mirrors the breathing pattern.

| Mechanic | Description |
|----------|-------------|
| `lantern` | A light that glows brighter when you breathe slowly, dims when you rush |
| `door` | A door/gate/passage that only opens when the air is completely still |
| `creature` | A shy creature that comes closer when you're quiet, retreats when you rush |
| `flower` | A flower that blooms when you breathe on it gently, closes when air is rough |
| `path` | A path that only appears when you walk slowly -- rushing makes it fade |
| `instrument` | A musical object that plays by itself when the room is calm enough |
| `water` | Water that becomes clear when you breathe calmly, cloudy when restless |
| `cloud` | A cloud that lowers/softens/glows when the world below it is quiet |
| `key` | A key that only turns when held with completely relaxed hands |
| `ink` | Words/images that only appear on a page when the reader is perfectly still |

### Mood Mapping

Worlds and mysteries are not chosen purely at random. Each mood has a curated
pool of worlds and mysteries that match the mood's emotional needs.

**`MOOD_TO_WORLDS`** -- which worlds suit each mood:

| Mood | Eligible Worlds |
|------|----------------|
| wired | transport, workshop, theater, post_office |
| curious | library, observatory, museum, lighthouse |
| calm | garden, kitchen, lighthouse, library |
| sad | post_office, garden, lighthouse, kitchen |
| anxious | kitchen, workshop, lighthouse, garden |
| angry | workshop, theater, transport, observatory |

**`MOOD_TO_MYSTERIES`** -- which mysteries suit each mood:

| Mood | Eligible Mysteries |
|------|-------------------|
| wired | something_arriving, something_strange, something_missing |
| curious | something_missing, something_strange, something_lost |
| calm | someone_needs_help, something_arriving, something_lost |
| sad | someone_needs_help, something_lost, something_missing |
| anxious | something_broken, someone_needs_help, something_arriving |
| angry | something_broken, something_strange, something_missing |

**`MOOD_TO_STORY_ENERGY`** -- per-mood prose guidance fed to the LLM explaining
how to calibrate engagement and descent for each emotional state.

### Recency Tracking

When `--randomize` is used, the script loads existing v2 long stories from
`content.json` and avoids repeating recent choices. The `_pick_avoiding_recent()`
function filters the eligible pool against the last N stories.

Recency windows (`DIVERSITY_RECENCY`):

| Parameter | Recency Window |
|-----------|---------------|
| `world_type` | 5 stories |
| `mystery_type` | 4 stories |
| `breathing_mechanic` | 6 stories |
| `repeated_phrase_feeling` | 6 stories |

If all options in a pool have been used within the recency window, the filter
resets and any option becomes available again.

Character count is weighted random: `[1, 2, 2, 2, 3]` -- two-character stories
are the most common.

### Character System

The v2 character system centers on a child protagonist rather than animal characters.

**Protagonist types** (`PROTAGONIST_TYPES`) -- age-matched to the listener:

| Age Group | Protagonist |
|-----------|-------------|
| 2-5 | 4-5 years old. Small, brave in a wobbly way, talks to everything, asks obvious questions that are actually profound |
| 6-8 | 7-9 years old. Curious, capable, wants to prove they can handle it, secretly worried but pushes through |
| 9-12 | 10-12 years old. Thoughtful, independent, notices things adults miss, feels deeply but doesn't always show it |

**Mentor types** (`MENTOR_TYPES`) -- for 2-3 character stories:
- Elderly keeper/librarian who moves slowly and explains nothing directly
- Ancient creature (owl, whale, old tree, tortoise) wise through patience
- A living object (lantern, book, clock, compass) that guides without words
- A slightly older child who has done this before

**Companion types** (`COMPANION_TYPES`) -- for 2-3 character stories:
- A tiny creature (mouse, moth, firefly) brave despite size
- A nervous living object (cup, key, letter)
- A sleepy creature already half-asleep, modeling the target behavior
- An echo or shadow -- always there, never intrusive

---

## Validation

The `validate_story()` function checks the parsed story against v2 requirements.
It returns a list of issues (ERRORs and WARNs).

### Standard Checks

- All required sections present: `[CHARACTER:]`, `[INTRO]`, `[PHASE_1]`,
  `[PHASE_2]`, `[PHASE_3]`, `[SONG_SEED:]`, `[PHRASE]`
- Per-phase word counts within 70%-130% of targets
- Total word count within 70%-130% of target
- Repeated phrase appears at least 3 times
- At least one `[WHISPER]` tag in Phase 3
- At least 4 `[PAUSE:]` tags across the story

### v2-Specific Checks

- **Breathing mechanic presence**: scans the full story text for breathing
  keywords (`breath`, `breathe`, `breathing`, `inhale`, `exhale`,
  `in through`, `out through`, `slow breath`). Warns if none found.
- **Phase 3 sentence count**: splits Phase 3 text on sentence boundaries and
  checks against the age-group minimum (50 for 2-5, 60 for 6-8, 70 for 9-12),
  with 60% tolerance. Warns if the LLM produced too few short sentences.
- **`[BREATHE]` tag count**: checks for at least 3 `[BREATHE]` tags across
  the entire story (expected: 1-2 in Phase 1, 3-4 in Phase 2). Warns if
  fewer than 3 found.

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

- **Narrator**: mood-specific (see `MOOD_NARRATOR_VOICE` in script)
- **Characters**: assigned for maximum gender contrast from the narrator
  - If narrator is female, the first character gets a male voice
  - Second character gets the next available contrasting voice
- **Dialogue routing**: character dialogue uses name labels in the text
  (e.g., `MIRA:`, `PIP:`) which are mapped to character voices
- **Voice map**: stored in `metadata.json` under the `voice_map` key
- **Character voice modifiers**: each character's `voice_style` (confident,
  gentle, small, wise, nervous, curious, stubborn, dreamy, brave, quiet,
  playful, careful, sleepy) adjusts TTS speed and exaggeration offsets

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
| breathing | 0.35 | 0.75 | 0.40 |

The `breathing` entry is used for text around `[BREATHE]` moments -- slightly
slower and softer than Phase 1 narration to reinforce the calm breathing cue.

---

## Phase 3 TTS Batching

Chatterbox cannot handle 1-3 word inputs -- it either hangs or produces garbled
audio. Phase 3 contains 50-70+ very short sentences (3-5 words each), so a
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

- **Lyrics**: generated via Mistral AI based on story content, the `[SONG_SEED]`
  tag, the character name, the world concept, the repeated phrase, and a
  mood-specific song arc (`MOOD_SONG_ARC`)
- **Audio**: generated via MiniMax Music 1.5 on Replicate (model: `minimax/music-01`)
- **Style varies by mood**:

| Mood | Instruments | BPM |
|------|-------------|-----|
| curious | soft celesta and light harp | 85 |
| wired | gentle guitar and soft xylophone | 90 |
| calm | warm music box and gentle harp | 78 |
| sad | solo piano | 75 |
| anxious | soft low strings and gentle harp | 80 |
| angry | low warm cello and soft drum | 82 |

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

The LLM prompt adjusts word counts based on the target age group. v2 targets are
higher than v1 to support richer world-building and breathing mechanics.

| Age Group | Phase 1 | Phase 2 | Phase 3 | Total | Phase 3 Min Sentences |
|-----------|---------|---------|---------|-------|-----------------------|
| 2-5 | 250-400 | 250-400 | 200-300 | 700-1100 | 50 |
| 6-8 | 350-500 | 300-450 | 250-350 | 900-1300 | 60 |
| 9-12 | 400-600 | 350-500 | 300-400 | 1050-1500 | 70 |

---

## Character Count Options

The `--character-count` flag controls the story's cast. The protagonist is always
a child.

- **1 character**: Solo journey. The child talks to themselves, the moon,
  the wind, or other non-speaking elements. The breathing mechanic is their
  tool -- they use it alone.
- **2 characters**: The child protagonist plus a mentor OR a companion. Short
  dialogue exchanges (1-2 lines each, back and forth). The second character
  helps the child understand the breathing mechanic. They fall asleep or grow
  quiet by mid-Phase 2.
- **3 characters**: The child protagonist, a mentor, AND a companion. Each has
  a distinct personality. In Phase 2, the companion sleeps first (already
  half-asleep), then the mentor grows quiet, then the child is last. The child
  watches each one fall asleep, normalizing it.

---

## Mood Options

Six moods are supported, each affecting world selection, mystery selection,
story energy, music bed selection, song style, narration tone, and breathing
mechanic urgency:

- `curious` -- feeds the wondering; answers are quieter than questions
- `calm` -- gentle from the start; the child is already receptive
- `wired` -- Phase 1 is more engaging to capture excess energy before settling
- `sad` -- tender and warm; the resolution is being held, being safe, being not-alone
- `anxious` -- safety from the first line; the breathing mechanic is especially important
- `angry` -- frustration is validated; the solution is understanding, not fighting

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mistralai` | Text generation and song lyrics |
| `pydub` | Audio assembly (mixing, fading, concatenation) |
| `httpx` | TTS API calls and cover API calls |
| `replicate` | Song audio generation via MiniMax |
| `ffmpeg` | Required by pydub. PATH must include `/opt/homebrew/bin` on macOS |
| `dotenv` | Loading environment variables from `.env` |

---

## Integration with Pipeline

The content pipeline (`scripts/pipeline_run.py`) calls this script for long story
generation instead of the older matrix-based approach. See the `step_generate()`
function in the pipeline orchestrator for how it invokes the episode generator
and passes parameters.

When called from the pipeline, `--randomize` and `--publish` are typically used
together so the script auto-selects diverse parameters and adds the finished
episode to `content.json`.

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
  "MANY short sentences, not FEW short sentences" and specifies a minimum
  sentence count (50-70 depending on age group) to counteract this.

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
