# Dream Valley — Immersive Story Guidelines for Ages 9-12

> **Purpose**: Guide the generation of long-form (20-30 min) sleep-inducing audio adventures for the 9-12 age group. This is the trickiest group — too old for "bedtime stories" in their self-concept, but still children who struggle with sleep onset due to active, ruminating minds.

---

## Core Psychology

- **They reject anything "babyish."** Frame as audio adventure / immersive world — NEVER "bedtime story."
- **They consume voluntarily:** Minecraft lore, Harry Potter, fantasy novels, mystery podcasts. Match that quality.
- **Peak imaginative absorption (8-12):** Rich descriptive material activates internal visualization, which naturally quiets mental chatter and worry. This IS meditation — without ever calling it that.
- **Sleep onset problems:** Active minds ruminate (school stress, social dynamics). The story must absorb their mind SO completely that worry gets crowded out.
- **The transition to sleep must feel like a natural consequence of the story**, never a directive.

---

## 3-Phase Structure

| Phase | Name | Duration | Word Count | Speed | Purpose |
|-------|------|----------|------------|-------|---------|
| 1 | CAPTURE | 5-8 min | 450-600 words | 80% (0.8x) | Hook with quality — compelling audiobook opening |
| 2 | DESCENT | 8-12 min | 800-1000 words | 70% (0.7x) | Contemplative exploration — guided visualization disguised as narrative |
| 3 | SLEEP | 6-10 min | 600-800 words | 60% (0.6x) | Abstract, looping, sensory dissolution — ambient music in word form |

**Total: 2000-2500 words → 20-30 minutes at slow narration pace with pauses**

---

## Phase 1 — CAPTURE (450-600 words)

**Goal:** Hook the listener with the quality of a great audiobook opening. They should WANT to keep listening — not because it's soothing, but because it's genuinely compelling.

### What works:
- Opening feels like the beginning of a cool audiobook or immersive game world
- Rich world-building, a compelling hook, a character they'd actually find interesting
- NOT cute animals — a young inventor, a space explorer, a kid who discovers time works differently in their attic
- A discovery in the first 3 sentences — something strange, unexpected, or fascinating
- Sophisticated vocabulary used naturally: "bioluminescent," "electromagnetic," "resonance"
- Think: what does a 10-year-old find cool? Technology, secrets, hidden worlds, being trusted with something important

### Technical requirements:
- Start with `[GENTLE]`, shift to `[CURIOUS]` and `[EXCITED]`
- 4-6 lines of natural dialogue in `[CHAR_START]...[CHAR_END]`
- Voice: engaging narrator, like a podcast host — NOT a parent
- End at the threshold of something vast, quiet, and awe-inspiring

---

## Phase 2 — DESCENT (800-1000 words)

**Goal:** The plot naturally enters a contemplative, exploratory phase. The character reaches a place of wonder rather than action. Narration becomes descriptive and almost hypnotic — guided visualization disguised as narrative.

### The key insight:
Kids 8-12 are at **peak capacity for vivid mental imagery**. If you give them rich enough descriptive material, they'll build the world in their heads, and that internal visualization process naturally quiets external mental chatter and worry. It's essentially **meditation through story** without ever using the word meditation.

### What works:
- Character reaches a place of overwhelming beauty and stillness: alien landscape, vast ancient library, drifting through space, crystal cavern beneath the ocean
- Narration becomes overwhelmingly sensory — every surface, temperature, light quality, sound
- "You can see the rings of the planet stretching out in every direction, pale gold and shimmering, and the silence out here is so complete you can hear your own heartbeat..."
- Think: the contemplative middle section of a Hayao Miyazaki film

### Disguised relaxation cues (CRITICAL):
Breathing and relaxation cues are woven in **very subtly** — zero explicit instructions.

| Story Logic | Physical Effect |
|------------|----------------|
| Zero-gravity environment | Body feels weightless, muscles release |
| Conserve oxygen in space suit | Breathe slowly, long measured inhales |
| Underwater pressure | Water presses gently, holding like a hand |
| Ancient library requires stillness | Become as still as the stone itself |
| Warmth radiating from crystal walls | Heat seeps into hands, arms, whole body |
| Need to listen for faint sounds | Become absolutely quiet and still |

**NEVER write:** "take a deep breath," "relax your body," "feel your body getting heavy" — that breaks immersion instantly.

### Technical requirements:
- Mark with `[PHASE_2]` on its own line
- Use `[CALM]` markers, shifting to `[SLEEPY]` by end
- 1-2 whispered dialogue lines in `[CHAR_START]...[CHAR_END]`
- `[PAUSE]` markers increase in frequency
- Plot barely advances — this is about BEING in the space

---

## Phase 3 — SLEEP (600-800 words)

**Goal:** The world becomes increasingly abstract and dreamy. Less plot, more sensation. Descriptions start to loop and repeat with variations — almost like ambient music but in narrative form.

### What works:
- "Another star drifted past... then another... each one a different color... and the ship moved so slowly now it felt like it wasn't moving at all..."
- Looping descriptions with slight variations — like an ambient music track in narrative form
- Narrator's voice is slow, deep, quiet, almost ASMR-like in quality
- NO lullaby — atmospheric ambient music transition (Sigur Ros / Olafur Arnalds mood, NOT a children's lullaby)

### The "closing eyes" cue (DELICATE):
You can't say "close your eyes." But you CAN have the character close their eyes to **see** something:
- "She closed her eyes and the real map appeared, drawn in light on the inside of her eyelids..."
- "To hear the true frequency, she had to close her eyes. The sound was too subtle for divided attention..."
- Now the child closes their eyes because it's part of the experience, not because they're being told to sleep.

### Body dissolution:
- "She couldn't feel where her body ended and the water began..."
- "The warmth had seeped so deep that she felt like she was made of it..."

### Technical requirements:
- Mark with `[PHASE_3]` on its own line
- Use ONLY `[SLEEPY]` and `[WHISPERING]` markers
- NO character dialogue — just narrator
- `[LONG_PAUSE]` between fragments (4-second silences)
- At least 20 `[LONG_PAUSE]` markers
- Last 8-10 lines are fragments dissolving into silence
- Story DISSOLVES — it does not end
- Provide `ambient_music_description` instead of lullaby lyrics

---

## Characters

### Always human for this age group.
No cute animals, no talking objects. Real kids with real passions.

### Archetypes:
| Archetype | Description |
|-----------|-------------|
| inventor | Builds gadgets, solves engineering problems |
| space_explorer | Fascinated by cosmos, scientific mind |
| time_traveler | Discovers something that bends time |
| deep_sea_diver | Explores ocean depths, brave |
| code_breaker | Loves puzzles, patterns, hidden codes |
| musician | Hears patterns others miss, sensitive |
| archaeologist | Obsessed with ancient civilizations |
| astronomer | Watches sky, maps stars, contemplative |
| botanist | Studies rare plants, hidden ecosystems |
| cartographer | Maps unmapped places, hidden worlds |

### Cultural diversity:
Use names from across cultures — Indian, East Asian, African, Middle Eastern, Latin American, not just Western. Reference the CHARACTER_BANK in `generate_content_matrix.py` for name/setting ideas.

---

## Audio Generation Speeds

The audio pipeline (`generate_audio.py`) automatically adjusts speed per phase when called with `--speed 0.8`:

| Phase | Base Speed | Multiplier | Effective Speed |
|-------|-----------|------------|-----------------|
| Phase 1 (Capture) | 0.8 | 1.0x | 0.8 (80%) |
| Phase 2 (Descent) | 0.8 | 0.875x | 0.7 (70%) |
| Phase 3 (Sleep) | 0.8 | 0.75x | 0.6 (60%) |

The `[PHASE_2]` and `[PHASE_3]` markers in the story text trigger these speed changes automatically.

---

## Emotion Markers (TTS Pipeline Compatible)

| Marker | Usage | Phase |
|--------|-------|-------|
| `[GENTLE]` | Opening, warm moments | 1 |
| `[EXCITED]` | Discoveries, revelations | 1 |
| `[CURIOUS]` | Investigation, intrigue | 1 |
| `[CALM]` | Peaceful exploration | 2 |
| `[SLEEPY]` | Drowsy, heavy, warm | 2-3 |
| `[WHISPERING]` | Barely audible, ASMR | 3 |
| `[PAUSE]` | 800ms natural pause | All |
| `[DRAMATIC_PAUSE]` | 1.5s pause | 1-2 |
| `[LONG_PAUSE]` | 4s extended silence | 3 |
| `[CHAR_START]`/`[CHAR_END]` | Character dialogue | 1-2 |
| `[PHASE_2]` | Descent transition | — |
| `[PHASE_3]` | Sleep transition | — |

---

## Forbidden Phrases

These break immersion for 9-12 year olds and must NEVER appear in the story:

- "take a deep breath" / "take a big breath"
- "relax your body" / "relax your muscles"
- "feel your body getting..."
- "bedtime story"
- "time for bed" / "go to sleep"
- "close your eyes and sleep"
- "let your body relax"
- "your eyelids are getting heavy"
- "snuggle up" / "tuck you in"
- "sleepy little..."

---

## Output Format

The generation script outputs JSON with these 9-12-specific fields:

```json
{
    "type": "long_story",
    "target_age": 10,
    "age_min": 9,
    "age_max": 12,
    "age_group": "9-12",
    "duration": 25,
    "lullaby_lyrics": "",
    "ambient_music_description": "2-3 sentences describing closing ambient music",
    "lead_character_type": "human",
    "character_archetype": "inventor | space_explorer | etc.",
    "character_name": "Culturally diverse name",
    "character_age": 10
}
```

---

## Generation Script

```bash
# Generate a new story
python3 scripts/generate_experimental_story_9_12.py

# Preview prompts only
python3 scripts/generate_experimental_story_9_12.py --dry-run

# Full pipeline after generation
python3 scripts/generate_audio.py --story-id gen-XXXX --speed 0.8
python3 scripts/stitch_lullaby.py --story-id gen-XXXX           # Stitch atmospheric ambient music
python3 scripts/generate_music_params.py --id gen-XXXX
python3 scripts/generate_cover_svg.py --id gen-XXXX
python3 scripts/sync_seed_data.py --lang en
```

---

## Quality Benchmark

The benchmark story is "The Secret of the Dream Library" (`seed_output/experimental_cloud_kingdom.json`):
- Character: Mira, age 10, human (librarian apprentice)
- Phase structure: 624 / 849 / 481 words
- 37 `[LONG_PAUSE]` markers in Phase 3
- 15 `[WHISPERING]` markers
- No explicit relaxation cues — all disguised in story logic
- Produces ~21 minutes of audio

---

## Music Transition (NOT Lullaby)

This age group should feel like they're listening to something **sophisticated** — a film score fading out, NOT a children's lullaby. Think **Sigur Rós** or **Ólafur Arnalds** in mood.

### How it works

Each story includes an `ambient_music_description` field with 2-3 sentences describing the closing music mood. This guides the generation of a **150-second atmospheric ambient piece** that gets stitched onto the end of every audio variant.

#### Example descriptions:
- "Deep, resonant cello notes submerged in water, creating a slow, pulsing rhythm like the rise and fall of tides. Distant, echoing chimes fade in and out, leaving trails of reverb."
- "Sustained cello drones with distant piano notes, like starlight translated to sound. Slow, breathing strings."
- "Wind through ancient stone corridors, barely audible crystalline chimes, sub-bass hum."

### Generation via ACE-Step

The ambient music is generated using **ACE-Step** (our Modal singing endpoint) with **non-lexical vocables** — wordless "ooh, aah, mmm" vocalizations in a V-C-V-C-V-C structure. This captures the Sigur Rós "Hopelandic" aesthetic: ethereal, wordless vocals floating over atmospheric instrumentation.

**Why vocables, not instrumental?** ACE-Step is a singing model that requires lyrics. Non-lexical vocables give it enough vocal content to work with while producing an ethereal, non-verbal ambient result. The `description` parameter drives the instrumental mood.

#### ACE-Step parameters:

| Parameter | Female Variant | Male Variant |
|-----------|---------------|--------------|
| `mode` | `"full"` | `"full"` |
| `duration` | 150s | 150s |
| `description` | atmospheric ambient, ethereal female vocals, wordless, deep cello, slow sustained strings, reverberating piano, post-rock, Sigur Ros mood, 45 bpm | atmospheric ambient, ethereal male vocals, wordless, deep cello drone, distant piano, underwater reverb, Olafur Arnalds mood, 40 bpm |

#### Non-lexical vocable template:

```
[verse]
Ooh ooh ooh, ooh ooh ooh ooh,
Aah aah aah, aah aah aah.
Ooh ooh ooh, ooh ooh ooh ooh,
Mmm mmm mmm, mmm mmm mmm.

[chorus]
Ooh aah ooh, ooh aah ooh,
Mmm mmm mmm, mmm.

(repeat V-C-V-C-V-C — choruses identical)
```

### Stitching onto narration audio

The `stitch_lullaby.py` script handles the full pipeline:

```bash
python3 scripts/stitch_lullaby.py --story-id gen-XXXX [--backup] [--duration 150]
```

**What it does:**
1. Generates **2 ambient pieces** via ACE-Step (female + male, cached by gender)
2. For each of the 7 voice variants:
   - Loads existing narration MP3
   - Maps voice to gender (female_1/2/3 + asmr → female, male_1/2/3 → male)
   - Stitches: `narration.fade_out(10s)` → `3s silence` → `ambient.fade_in(10s)`
   - Applies final fade_out(1.5s) on combined audio
   - Normalizes ambient to **-19 dBFS** (slightly quieter than narration at -16 dBFS)
   - Exports as MP3 at 256kbps
3. Updates `content.json` with new durations and ambient lyrics

**Expected result:** Each audio variant gains ~143 seconds (150s ambient - crossfade overlap).

### Key differences from ages 2-8 lullaby

| Aspect | Ages 2-8 | Ages 9-12 |
|--------|----------|-----------|
| Content | Sung lullaby with children's lyrics | Wordless atmospheric ambient |
| Mood | Warm, nurturing, music-box feel | Film score, post-rock, cinematic |
| ACE-Step lyrics | Full lyric sections (words) | Non-lexical vocables (ooh/aah/mmm) |
| Duration | 120s | 150s |
| Description tone | "gentle lullaby, piano, bedtime" | "atmospheric ambient, post-rock, Sigur Rós mood" |
| Normalization | -19 dBFS | -19 dBFS |
