# Dream Valley — Immersive Story Guidelines for Ages 2-5

> **Purpose**: Guide the generation of long-form (15-22 min) sleep-inducing audio stories for the 2-5 age group. These are the youngest listeners — they live in a world where animals talk, magic is real, and bedtime is a warm, safe ritual. The story wraps them in wonder and gently carries them to sleep.

---

## Core Psychology

- **Everything is real and alive.** A jellyfish can glow, a fox can whisper, flowers can hum. Don't explain magic — just let it happen. Children this age accept wonder without question.
- **They need warmth, safety, and repetition.** Repetition is not boring to a 2-5 year old — it's comforting. Repeated phrases become anchors. "So warm... so safe... so sleepy" works because they can predict what's coming next.
- **Concrete and sensory, never abstract.** No "felt a sense of belonging" — instead "the warm water hugged her like a blanket." Everything must be touchable, seeable, hearable.
- **Animal protagonists engage this age group most.** Research shows 2-5 year olds connect most deeply with animal characters. A glowing jellyfish, a sleepy fox, a tiny firefly — these are the heroes. NOT human children (unlike 9-12). Fantasy creatures with simple personalities are ideal.
- **One character, one storyline, no subplots.** One main character discovers one magical thing. Keep it simple and linear. The bunny finds a magical door. The whale hears a strange sound. The bear discovers his shadow can talk. That's the whole plot.
- **Use "you" and engagement hooks.** Lots of "you" in the narration creates intimacy: "Can you guess what the bunny saw?" "Can you hear that?" These should be **rhetorical** in a bedtime context — inviting wonder, not requiring response.
- **The parent is often listening too.** The story should be genuinely pleasant — warm narration that a parent enjoys hearing alongside their child.
- **Bedtime is welcome, not feared.** Unlike 9-12 who reject "bedtime story" framing, 2-5 year olds WANT bedtime stories. Lean into the cozy ritual.

---

## 3-Phase Structure + Lullaby

| Phase | Name | Duration | Word Count | Speed | Purpose |
|-------|------|----------|------------|-------|---------|
| 1 | CAPTURE | 3-5 min | 250-400 words | 80% (0.8x) | Hook with a fun, sensory discovery |
| 2 | DESCENT | 5-8 min | 400-600 words | 75% (0.75x) | Character physically relaxes — child mirrors |
| 3 | SLEEP | 5-7 min | 350-500 words | 65% (0.65x) | Dissolving fragments → silence |
| 4 | LULLABY | 2-3 min | 80-120 words | 60% (0.6x) | Fades in under final story fragments |

**Total: 1000-1500 words + lullaby → 15-22 minutes at slow narration pace with pauses**

---

## Phase 1 — CAPTURE (250-400 words)

**Goal:** Hook the child with a simple, vivid scenario. One main character, one clear situation, one magical discovery. The world is warm, colorful, and safe.

### What works:
- **One character, one situation**: the bunny finds a magical door, the little whale hears a strange sound in the ocean, the bear discovers his shadow can talk
- **No subplots** — just one clear storyline unfolding
- Open in a cozy, familiar-feeling world: underwater, forest, meadow, garden, clouds
- Rich sensory language but SIMPLE words: "sparkly," "warm," "glowing," "soft," "tickly"
- Short sentences (5-12 words). One idea per sentence.
- **Lots of "you" and engagement hooks** — "Can you guess what the bunny saw?" "Can you hear that?" These should be **rhetorical** in bedtime context, inviting wonder without requiring response
- 3-5 lines of character dialogue in [CHAR_START]...[CHAR_END]
- Voice: warm, gently animated, with character voices that are fun but **not loud or jarring** — cozy storytelling, not cartoon energy
- Build gentle excitement — happy wonder, not frantic energy
- End Phase 1 with the character arriving somewhere quieter (a cozy nook, a soft clearing, a warm pool)

### Technical requirements:
- Start with `[GENTLE]`, progress through `[CURIOUS]`, `[EXCITED]`, `[JOYFUL]`
- 3-5 dialogue blocks in `[CHAR_START]...[CHAR_END]`
- 2-4 `[PAUSE]` markers for natural rhythm
- End on a warm, settling note — character has arrived somewhere cozy

---

## Phase 2 — DESCENT (400-600 words)

**Goal:** The adventure moves to a quieter place. The character physically relaxes, and the child mirrors them. This is where **disguised progressive relaxation** lives — the longest and most important phase. The journey language shifts heavily to sensory and body-based description.

### The key insight:
2-5 year olds accept direct relaxation cues much more readily than older children. Breathing cues are **simple and explicit** because kids this age will **actually follow along** if the story invites it. "The bunny took a biiiiig breath in... and blew it out slow like blowing a dandelion..." The character models the exact physical process of falling asleep, and the child copies naturally.

### The setting shift:
- The bunny goes through the magical door and finds a meadow at sunset
- The whale swims deeper where the water is warm and still
- The firefly lands on a branch where the bark is warm and bumpy
- The adventure naturally arrives at a quieter, cozier place

### Character-modeled relaxation (CORE TECHNIQUE):
The character does what the child should do. Mark each with `[BREATH_CUE]`:

| Character Action | Child Response |
|-----------------|---------------|
| Takes a biiiiig breath in... and blows it out slow like blowing a dandelion | Deep breath, slow exhale |
| Stretches arms/tentacles/wings wide, then goes floppy | Stretches and releases tension |
| Yawns a great big yawn | Yawns (contagious) |
| Curls up into a tiny ball, smaller and smaller | Curls into sleeping position |
| Feels warm water/blanket wrapping around them | Body awareness → warmth → heaviness |
| Eyes grow heavy, eyelids flutter | Closing eyes |

### What works:
- **Language shifts to body-based, sensory descriptions**: "the grass felt soft and tickly under her paws," "the air was warm like a blanket"
- The cozy place wraps around the character: warm water, soft moss, fluffy clouds
- Sensory descriptions are **overwhelmingly physical**: warmth, heaviness, softness, coziness
- The character's glow/light/energy dims gradually
- Environmental sounds become lullaby-like: humming shell, whispering wind, soft rain
- 1-2 whispered dialogue lines: "Maybe I should rest here..."
- **Voice pacing slows noticeably.** Pauses stretch. Sentences get shorter.
- 4-6 `[BREATH_CUE]` markers with explicit breathing modeled by character
- The breathing visual pacer (in the app) is doing its work alongside the narration

### Technical requirements:
- Mark with `[PHASE_2]` on its own line
- Use `[CALM]` shifting to `[SLEEPY]` markers
- 4-6 `[BREATH_CUE]` markers (explicit, character-modeled breathing)
- 1-2 whispered `[CHAR_START]...[CHAR_END]` dialogue lines
- `[PAUSE]` markers increase in frequency
- End with character's eyes closing or glow dimming

---

## Phase 3 — SLEEP (350-500 words)

**Goal:** The character is now in their cozy place. The narrative becomes **extremely repetitive and cyclical** — the story doesn't really end, it dissolves. The last few "sentences" are fragments with long pauses. This is ambient music in word form.

### What works:
- "One star lit up... then another... then another... each one soft and quiet..."
- Descriptions of **heaviness, warmth, softness, closing eyes**
- Single sensory words repeated: "Warm... so warm... soft... so soft..."
- The character's glow/light flickers once... twice... then goes out
- Environmental details fade: music becomes a whisper, lights dim one by one
- Fragments get shorter and shorter — full sentences → phrases → single words
- Long silences between fragments (4-second pauses)
- **The story doesn't end — it DISSOLVES**

### The dissolving structure:
```
[SLEEPY] Full sentence describing the cozy state. [LONG_PAUSE]
[SLEEPY] Shorter sentence... warmth... dimming. [LONG_PAUSE]
[WHISPERING] Even shorter... a phrase... [LONG_PAUSE]
[WHISPERING] Two words... so soft... [LONG_PAUSE]
[WHISPERING] One word... sleep... [LONG_PAUSE]
```

### Technical requirements:
- Mark with `[PHASE_3]` on its own line
- Use ONLY `[SLEEPY]` and `[WHISPERING]` markers
- NO character dialogue — just the narrator's soft voice
- 10-15 `[LONG_PAUSE]` markers (4-second silences)
- Last 6-8 lines are fragments dissolving into silence
- Story DISSOLVES — it does not end. No "The End."
- Final fragment should evoke safety and warmth: "sleep now... little one..."

---

## Lullaby (80-120 words)

**Goal:** A sung lullaby that fades in under the final story fragments. It references the story's imagery — simple, slow, repetitive. The lullaby IS the final transition to sleep.

### How it works in practice:
The lullaby audio is stitched to fade in during the end of Phase 3. The narrator's voice dissolves, and the lullaby takes over — a seamless handoff from story to song. The child experiences it as one continuous descent into sleep.

### What works:
- 3 verses + chorus structure (chorus repeats identically between verses)
- Imagery drawn directly from the story: if underwater, mention waves and glow; if forest, mention trees and moonlight
- Very simple rhyme: AABB or ABAB
- Repetitive chorus with a rocking, rhythmic quality
- Emotional tone: "you are safe, sleep is warm, the world is gentle"
- Simple, slow, repetitive — a true lullaby

### Technical requirements:
- Format: `[verse]` and `[chorus]` section markers
- 3 verses + chorus (chorus between each verse)
- Each verse: 4 lines, roughly 20-30 words
- Chorus: 4 lines, identical each time, roughly 15-25 words
- Total: 80-120 words
- Must reference at least 2 story-specific images

---

## Characters

### Always animal or fantasy creature for this age group.
No human children as leads — 2-5 year olds connect more deeply with animal characters. A jellyfish, a fox, a firefly, a baby dragon, a cloud bunny — these feel like friends, not people.

### Character types (diverse pool):
| Type | Examples |
|------|----------|
| sea_creature | Jellyfish, seahorse, baby whale, starfish, turtle |
| animal | Fox, bunny, hedgehog, otter, deer, bear cub |
| bird | Owl, robin, hummingbird, baby penguin |
| insect | Firefly, ladybug, butterfly, cricket |
| plant | Talking flower, mushroom, tiny tree spirit |
| mythical | Baby dragon, cloud bunny, star fox, moon moth |

### Character personality:
- Warm, curious, lovable
- Speaks in short, simple sentences
- Easily delighted, easily sleepy
- A little brave, a little shy
- Simple, memorable name (1-2 syllables preferred): Lumi, Pip, Fern, Milo, Dot, Kai

### Cultural diversity in settings:
While the character is an animal/creature, the WORLD can be culturally diverse:
- Indian ocean with mangoes and jasmine
- Japanese garden with cherry blossoms
- African savanna with baobab trees
- Arctic with northern lights
- Tropical rainforest with monsoon rain

---

## Audio Generation Speeds

The audio pipeline (`generate_audio.py`) automatically adjusts speed per phase when called with `--speed 0.8`:

| Phase | Base Speed | Multiplier | Effective Speed |
|-------|-----------|------------|-----------------|
| Phase 1 (Capture) | 0.8 | 1.0x | 0.8 (80%) |
| Phase 2 (Descent) | 0.8 | 0.9375x | 0.75 (75%) |
| Phase 3 (Sleep) | 0.8 | 0.8125x | 0.65 (65%) |

The `[PHASE_2]` and `[PHASE_3]` markers in the story text trigger these speed changes automatically.

---

## Emotion Markers (TTS Pipeline Compatible)

| Marker | Usage | Phase |
|--------|-------|-------|
| `[GENTLE]` | Opening, warm moments | 1 |
| `[EXCITED]` | Fun discoveries | 1 |
| `[CURIOUS]` | Wonder, questions | 1 |
| `[JOYFUL]` | Happy, bright moments | 1 |
| `[CALM]` | Peaceful settling | 2 |
| `[SLEEPY]` | Drowsy, heavy, warm | 2-3 |
| `[WHISPERING]` | Barely audible, intimate | 3 |
| `[BREATH_CUE]` | Character models breathing | 2 |
| `[PAUSE]` | 800ms natural pause | All |
| `[DRAMATIC_PAUSE]` | 1.5s pause | 1 |
| `[LONG_PAUSE]` | 4s extended silence | 3 |
| `[CHAR_START]`/`[CHAR_END]` | Character dialogue | 1-2 |
| `[PHASE_2]` | Descent transition | — |
| `[PHASE_3]` | Sleep transition | — |

---

## Forbidden Phrases

These break the gentle spell for 2-5 year olds and must NEVER appear:

- "relax your body" / "relax your muscles"
- "feel your body getting heavy"
- "it's past your bedtime"
- "you must be tired"
- "be quiet now"
- "stop moving"
- "lie still"

### Allowed (unlike older age groups):
- Character yawning, stretching, breathing — this is ENCOURAGED
- "Close your eyes" as character dialogue — acceptable at this age
- "Sleepy," "cozy," "bedtime" — all fine, these are warm words for 2-5
- Explicit breathing cues via character modeling — natural and welcome

---

## Setting Support

Stories can be set during specific events, festivals, or situations. When a `--setting` is provided, weave it naturally into the story world:

- The setting should feel like a normal part of the character's world
- Don't over-explain cultural elements — let them be natural backdrop
- The setting provides sensory material: colors, sounds, smells, foods, activities
- The story still follows the 3-phase sleep structure — the setting is WHERE it happens, not WHAT it's about
- The bedtime wind-down still takes priority in Phases 2-3

---

## Output Format

The generation script outputs JSON with these 2-5-specific fields:

```json
{
    "type": "long_story",
    "target_age": 3,
    "age_min": 2,
    "age_max": 5,
    "age_group": "2-5",
    "duration": 18,
    "lullaby_lyrics": "[verse]\n...\n[chorus]\n...",
    "lead_character_type": "sea_creature | animal | bird | insect | plant | mythical",
    "character_name": "Simple 1-2 syllable name",
    "musicProfile": "dreamy-clouds"
}
```

---

## Generation Script

```bash
# Generate a new story
python3 scripts/generate_experimental_story.py

# With a specific setting (e.g., Holi festival)
python3 scripts/generate_experimental_story.py --setting "Holi festival celebrations"

# Preview prompt only
python3 scripts/generate_experimental_story.py --dry-run

# Full pipeline after generation
python3 scripts/generate_audio.py --story-id gen-XXXX --force --speed 0.8
python3 scripts/stitch_lullaby.py --story-id gen-XXXX
python3 scripts/qa_audio.py --story-id gen-XXXX --no-quality-score
python3 scripts/generate_music_params.py --id gen-XXXX
python3 scripts/generate_cover_experimental.py --story-json seed_output/content.json --story-id gen-XXXX
python3 scripts/sync_seed_data.py --lang en
```

---

## Quality Benchmark

The benchmark story is "Lumi and the Glowing Tide" (`seed_output/content.json`, id: `gen-308d5f0d1268`):
- Character: Lumi, jellyfish (sea creature), underwater fantasy realm
- Phase structure: ~340 / ~215 / ~170 words (total 725 words)
- 3 `[BREATH_CUE]` markers in Phase 2 (character-modeled breathing)
- 7 `[LONG_PAUSE]` markers in Phase 3
- Emotion progression: GENTLE → CURIOUS → EXCITED → JOYFUL → CALM → SLEEPY → WHISPERING
- Lullaby: 3 verses + chorus referencing glowing tide, ocean beat, shell music
- Produces ~10 minutes of audio at 0.8x speed
- No abstract concepts — everything concrete and sensory

**Note:** This benchmark was an early generation at the lower end of the word count range. New stories should target 1000-1500 words for the full 15-22 minute experience, with Phase 2 (400-600 words) and Phase 3 (350-500 words) being significantly longer.

---

## Lullaby Generation

Each 2-5 long story includes a `lullaby_lyrics` field with verse-chorus structure. This guides the generation of a **120-second sung lullaby** that gets stitched onto the end of every audio variant.

### Generation via ACE-Step

The lullaby is generated using **ACE-Step** (Modal singing endpoint) with full lyrics.

#### ACE-Step parameters:

| Parameter | Female Variant | Male Variant |
|-----------|---------------|--------------|
| `mode` | `"full"` | `"full"` |
| `duration` | 120s | 120s |
| `description` | gentle lullaby, warm female vocals, simple melody, soft piano, music box, 55 bpm, soothing, intimate, nursery | gentle lullaby, warm male vocals, simple melody, acoustic guitar, soft piano, 55 bpm, soothing, intimate, nursery |

### Stitching onto narration audio

The `stitch_lullaby.py` script handles the pipeline:

```bash
python3 scripts/stitch_lullaby.py --story-id gen-XXXX [--backup] [--duration 120]
```

**What it does:**
1. Generates **2 lullaby pieces** via ACE-Step (female + male, cached by gender)
2. For each of the 7 voice variants:
   - Loads existing narration MP3
   - Maps voice to gender (female_1/2/3 + asmr → female, male_1/2/3 → male)
   - Stitches: `narration.fade_out(10s)` → `3s silence` → `lullaby.fade_in(10s)`
   - Normalizes lullaby to **-19 dBFS** (slightly quieter than narration at -16 dBFS)
   - Exports as MP3 at 256kbps
3. Updates `content.json` with new durations and lullaby lyrics

**Expected result:** Each audio variant gains ~113 seconds (120s lullaby - crossfade overlap).
