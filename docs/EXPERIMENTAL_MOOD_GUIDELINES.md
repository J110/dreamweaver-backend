# Dream Valley — Experimental Mood Content Guidelines
## Generating Mood-Based Stories, Poems, Lullabies & Long Stories

---

## Purpose

This document supplements `PIPELINE_CONTENT_GUIDELINES.md`. It provides mood-specific instructions for generating experimental content across all content types, age groups, and pipeline stages (text, audio, background music, covers).

The operator specifies a target mood. The system generates content calibrated to that mood, following every existing pipeline rule PLUS the mood-specific overrides in this document. Where this document is silent, the existing pipeline guidelines apply.

---

## Operator Interface

### Command

```bash
# Generate one experimental story in a specific mood
python3 scripts/generate_content_matrix.py \
  --mood wired \
  --age 2-5 \
  --type story \
  --experimental

# Generate a full mood set (one of each type for an age group)
python3 scripts/generate_content_matrix.py \
  --mood sad \
  --age 6-8 \
  --type all \
  --experimental

# Generate a long story with mood
python3 scripts/generate_content_matrix.py \
  --mood anxious \
  --age 9-12 \
  --type long_story \
  --experimental

# Batch: generate one of each mood for an age group
python3 scripts/generate_content_matrix.py \
  --mood all \
  --age 2-5 \
  --type story \
  --experimental
```

The `--experimental` flag writes content to `seed_output/experimental/` instead of the production directory. After review, use `--promote <story-id>` to move approved content to production.

```bash
# Review experimental content
python3 scripts/pipeline_run.py --list-experimental

# Promote to production after testing
python3 scripts/pipeline_run.py --promote gen-abc123
```

### Valid Mood × Content Type × Age Combinations

| Mood | Story | Long Story | Poem | Lullaby |
|---|---|---|---|---|
| **wired** | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | — |
| **curious** | 0-1, 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 0-1, 2-5, 6-8, 9-12 | 0-1, 2-5 |
| **calm** | 0-1, 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 0-1, 2-5, 6-8, 9-12 | 0-1, 2-5 |
| **sad** | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | — |
| **anxious** | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 2-5 |
| **angry** | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | 2-5, 6-8, 9-12 | — |

**Why some moods skip 0-1:** Infants don't experience mood-specific bedtime states the way older children do. Ages 0-1 only get `calm` and `curious` (gentle sensory content).

**Why some moods skip lullabies:** Lullabies are musical, not narrative. Wired, sad, and angry moods require narrative arcs to work — a sung lullaby can't validate anger or reframe fear. Exception: `anxious` lullabies for ages 2-5 use reassuring, "you are safe" lyrics.

---

## The Universal Rule

**All six moods converge to the same Phase 3 / ending.** The mood determines where the content STARTS, not where it ENDS. By the final third of any content piece, the mood-specific elements have dissolved and the content is indistinguishable from calm — slow, warm, sensory, still.

This means: mood affects Phase 1 and early Phase 2 of long stories, the first 60% of short stories and poems, and the verses (not the final humming fade) of lullabies.

---

# SECTION 1: TEXT GENERATION BY MOOD

## Mood Prompt Injection

The mood instruction is injected into the existing text generation prompt AFTER the content type instructions and BEFORE the diversity/fingerprint context. It does not replace any existing prompt — it adds a mood layer.

```python
MOOD_PROMPTS = {
    "wired": """
MOOD: WIRED (Silly)
This story is for a child who is hyper, bouncing, full of unfocused energy.
Your job: capture their attention through humor and absurdity, then land softly.

Phase 1 / Opening 60%: The premise is absurd. Characters do funny things. Physical comedy 
translated to audio — things fall over, plans backfire, sounds are silly. The narrator has 
comic timing. Repetition with variation (the penguin slips AGAIN). The child laughs.

Phase 2 / Final 40%: The silliness softens into coziness. The funny character is tired, 
finds a warm spot, settles down. Humor shifts from "laugh out loud" to "warm smile." 
Descriptions become tactile — soft, warm, snug.

Final sentences: No reference to earlier silliness. Pure stillness and warmth.

CRITICAL: The humor must be AGE-APPROPRIATE. See age-specific instructions below.

EMPHASIS WORDS: Wrap key funny moments in [EMPHASIS] tags so the narrator delivers them 
with comic punch. Use for: onomatopoeia (SPLAT, BONK, WHOOSH), silly names, drawn-out 
words (sooooo, veeeery), and punchline words. Example:
"The penguin slipped and went [EMPHASIS]SPLAAAAAT[/EMPHASIS] right into the pudding."
Use 3-6 emphasis words per story. Not every funny word — just the peaks.
""",

    "curious": """
MOOD: CURIOUS (Adventure)
This story is for a child who is alert, engaged, wanting to explore.
Your job: redirect their mental energy into a world worth following, then still it.

Phase 1 / Opening 60%: Something appears worth following — a trail, a sound, a door, 
a mystery. The character is drawn forward. The world is vivid and specific. Discovery 
drives the narrative.

Phase 2 / Final 40%: The discovery resolves into beauty, not action. The character stops 
moving and starts observing. The world is still extraordinary but now it's still. 
Descriptions shift from visual to sensory.

Final sentences: Pure quiet observation. The character rests in the beautiful place.

EMPHASIS WORDS: Wrap wonder/discovery words in [EMPHASIS] tags so the narrator delivers 
them with a slight lift of awe. Use for: "never seen before," "impossible," "glowing," 
"hidden," "there it was." Example:
"And behind the door was something she had [EMPHASIS]never seen before[/EMPHASIS]."
Use 2-4 emphasis words per story — moments of revelation.
""",

    "calm": """
MOOD: CALM (Gentle)
This story is for a child who is already winding down.
Your job: gentle sensory immersion from the first sentence. No setup needed.

Entire story: Minimal plot. A character in a beautiful, cozy place doing a quiet thing. 
Descriptions are tactile — moss, warmth, rain, soft blankets, breathing. Repetitive 
phrases. The story doesn't build or resolve — it settles.

This is the DEFAULT mood. If no mood is specified, generate calm.

EMPHASIS WORDS: Wrap sensory melt words in [EMPHASIS] tags so the narrator delivers 
them extra-softly, almost melting. Use for: "soft," "warm," "gentle," "still," 
"breathing," "cozy." Example:
"The blanket was [EMPHASIS]sooooft[/EMPHASIS] and the room was [EMPHASIS]warm[/EMPHASIS]."
Use 2-4 emphasis words per story. These should feel like the narrator is savoring the word.
""",

    "sad": """
MOOD: SAD (Comfort)
This story is for a child who had a bad day — lost something, fought with a friend, 
feels alone or disappointed.
Your job: validate the sadness, show comfort arriving, without fixing the problem.

Phase 1 / Opening 50%: A character who feels the way the child feels. The sadness is 
named honestly and simply. The source is specific and concrete. The story does NOT 
rush past the feeling. The character sits with it.

CRITICAL: NEVER dismiss the sadness. NEVER say "cheer up." NEVER fix the problem. 
The lost thing stays lost. The friend stays gone.

EMPHASIS WORDS: Wrap key emotional weight words in [EMPHASIS] tags so the narrator 
delivers them with heaviness and care. Use for: "alone," "gone," "empty," "missing," 
"quiet," "without," "still." Example:
"The bench was still there. But sitting on it [EMPHASIS]alone[/EMPHASIS], it felt wider."
Use 2-4 emphasis words per story. Sparingly — each one should land like a stone.

Phase 2 / Middle 30%: Something small and kind happens. Not a fix — a companion. 
A ladybug lands on a paw. A cat sits nearby without asking for anything. The warmth 
of unexpected gentleness. The sadness doesn't disappear — it transforms into 
something tender.

Phase 3 / Final 20%: The character rests inside the soft feeling. "And that was enough."
""",

    "anxious": """
MOOD: ANXIOUS (Brave)
This story is for a child who is afraid — of the dark, of being alone, of tomorrow, 
of something unnamed.
Your job: validate the fear, encounter the scary thing, reveal it as safe.

Phase 1 / Opening 50%: A character who is afraid. Not brave — scared. The fear is 
specific and physical: the dark corner, the strange sound, the worry about tomorrow. 
Name the body sensations: heart beating fast, cold paws, tight chest.

CRITICAL: NEVER tell the child there's nothing to be afraid of. That dismisses the 
fear. Instead, the character discovers on their own that the feared thing is safe.

EMPHASIS WORDS: Wrap fear words in [EMPHASIS] tags so the narrator delivers them in a 
hushed, careful voice. Use for: "dark," "shadow," "sound," "something," "what if," 
"corner," "behind." Then also wrap SAFETY words when the fear resolves: "singing," 
"cricket," "safe," "just a," "only." The contrast between whispered fear words and 
warmer safety words IS the emotional arc in audio form. Example:
"She looked at the [EMPHASIS]dark corner[/EMPHASIS] and held her breath."
Later: "And there, sitting on the floor, was a [EMPHASIS]cricket, singing[/EMPHASIS]."
Use 3-5 emphasis words per story — some fear, some safety.

Phase 2 / Middle 30%: The feared thing is encountered. It turns out to be harmless — 
even charming. The dark corner has a cricket. The sound is rain on the roof. The 
unknown becomes known, and the known is gentle.

Phase 3 / Final 20%: The character is safe. Not just safe — cozy inside the safety. 
The world that was scary is now the world that's holding them.
""",

    "angry": """
MOOD: ANGRY (Let It Out)
This story is for a child who is frustrated — something felt unfair, they got scolded, 
lost a game, fought with a sibling.
Your job: validate the anger, give it somewhere to go, let it burn itself out.

Phase 1 / Opening 50%: A character who is angry. The anger is named and validated. 
The cause is real and specific. The story does NOT moralize or say "calm down." 
The character's body does the feeling — stomping, throwing, clenching.

CRITICAL: NEVER say the anger is wrong. NEVER lecture. The anger is VALID.

EMPHASIS WORDS: Wrap punch words in [EMPHASIS] tags so the narrator delivers them with 
sharp, emphatic energy. Use for: "NOT fair," "stomped," "THREW," "slammed," "NO," 
action words during the release. Example:
"He picked up a stone and [EMPHASIS]THREW[/EMPHASIS] it into the water."
"It [EMPHASIS]wasn't fair[/EMPHASIS] and he knew it."
Use 3-5 emphasis words, concentrated in Phase 1. By Phase 2, emphasis words disappear 
— the anger has drained and the voice flattens naturally.

Phase 2 / Middle 30%: The anger finds physical expression — the character stomps, 
throws stones in water, kicks leaves, runs. The release is physical. Then something 
in the environment shifts the energy — a sunset appears, the ripples go smooth, the 
breathing slows. The anger doesn't disappear — it exhausts itself.

Phase 3 / Final 20%: The character is spent. Empty in a good way. Arms tired, 
breathing slow. Rest is possible because the energy has been used up.
"""
}
```

---

## Mood × Age Group: Text Instructions

### WIRED

#### Wired — Ages 2-5
- Humor: Broad physical comedy. Things fall. Characters slip, trip, bonk. A bear who thinks he's a butterfly. Repetition with variation is the key tool (the penguin slips three times, each time landing in something softer).
- Characters: Animals or objects-come-to-life. Not human children.
- Language: Short sentences. Funny sounds. Onomatopoeia. "SPLAT. BONK. PLOP." Capital-letter emphasis for the narrator to deliver with comic timing.
- Emotion markers: Start `[EXCITED]` or `[JOYFUL]`, transition through `[GENTLE]` to `[SLEEPY]`.

#### Wired — Ages 6-8
- Humor: Conceptual absurdity played with commitment. A cloud afraid of heights. A lighthouse afraid of the dark. The premise is the joke — the narrator tells it straight.
- Characters: Animals, mythical creatures, or objects with personality.
- Language: Longer sentences with comic rhythm — build-up, pause, payoff. The narrator is bemused, not silly.
- Emotion markers: Start `[CURIOUS]` or `[JOYFUL]`, transition through `[GENTLE]` to `[SLEEPY]`.

#### Wired — Ages 9-12
- Humor: Dry, deadpan, smart. The narrator treats ridiculous situations with complete seriousness. "The raccoon had been staring at the moon for forty-five minutes. She wasn't sure what she was expecting." The child feels smart for getting the humor.
- Characters: Animals with internal monologues, or human characters with wry self-awareness.
- Language: Conversational, precise, unexpected word choices. No exclamation marks. No spectacle.
- Emotion markers: Start `[CURIOUS]`, transition through `[CALM]` to `[SLEEPY]`.

### SAD

#### Sad — Ages 2-5
- Source: Concrete, immediate. A lost toy, a friend who didn't come, a parent away for the day.
- Resolution: Something small and warm arrives — a ladybug, a warm blanket, a gentle companion. NOT a fix.
- Language: Simple, repetitive. "Bear was sad. He sat by the river. The river kept moving. Bear was still." Repetition is comforting — the rhythm calms even as the content is emotionally honest.
- Emotion markers: Start `[GENTLE]` (never `[DRAMATIC]`), use `[CALM]` through middle, end `[SLEEPY]`.

#### Sad — Ages 6-8
- Source: Relational. A friendship that changed, a pet that died, feeling left out, something that's gone.
- Resolution: Companionship without fixing. A cat sits nearby. The sunset is beautiful despite everything. The character discovers they're not alone, even though nothing is fixed.
- Language: Specific observations. "The bench was the same colour. The same peeling paint. But sitting on it alone, it felt wider."
- Emotion markers: Start `[GENTLE]`, use `[CALM]` through middle, end `[SLEEPY]`.

#### Sad — Ages 9-12
- Source: Existential. Impermanence, change, the realization that things don't stay. Grandma's house being sold. The last day of something.
- Resolution: A small shift in perspective that makes the feeling livable without eliminating it. "The view didn't belong to the house. It belonged to whoever was looking."
- Language: Literary, precise. The specificity of sensory detail makes it real — the screen door, the third step that creaks.
- Emotion markers: Start `[GENTLE]` or `[MYSTERIOUS]`, use `[CALM]`, end `[WHISPERING]`.

### ANXIOUS

#### Anxious — Ages 2-5
- Fears: The dark, monsters, being alone, strange sounds. Fear of dark peaks at ages 3-4.
- The character: A small animal afraid of a specific thing — the dark corner, the shadow, the sound at night.
- The reveal: The scary thing IS something specific and gentle. The dark corner has a cricket singing. The shadow is a branch moving in the wind.
- Language: Name physical sensations. "Her heart was beating fast. Her paws were cold." The naming itself is calming.
- Emotion markers: Start `[GENTLE]` (not `[DRAMATIC]` — don't amplify the fear), use `[MYSTERIOUS]` for the encounter, resolve through `[CALM]` to `[SLEEPY]`.

#### Anxious — Ages 6-8
- Fears: Transitional — some monsters, but also fear of tomorrow, fear of getting in trouble, fear of not being liked. "What if no one talks to me?"
- The character: A child or animal lying awake, mind racing with "what ifs."
- The reframe: Not "the scary thing is harmless" but "I can handle this" or "time will pass." The moon will be the same tomorrow night.
- Language: Interior monologue. "The thoughts kept coming, one after another, like waves."
- Emotion markers: Start `[GENTLE]`, use `[CURIOUS]` when the character starts noticing the world around them, end `[SLEEPY]`.

#### Anxious — Ages 9-12
- Fears: Realistic and social. Replaying an embarrassing moment. Dreading a test. Fear of judgment.
- The character: Lying in bed ruminating. The specific, grinding quality of replaying a moment.
- The reframe: Grounding — coming out of the head into the body and senses. The pillow is cool. The house is quiet. Right now, nothing bad is happening.
- Language: Precise, interior. "The moment grew bigger in the dark, the way moments do when there's nothing else to look at."
- Emotion markers: Start `[CALM]` (not dramatic), use `[GENTLE]` as the character grounds, end `[WHISPERING]`.

### ANGRY

#### Angry — Ages 2-5
- Source: Immediate, physical. Doesn't need to be named — "Bear was SO angry. He didn't even know why anymore."
- Release: Physical. STOMP. SPLASH. THROW. Each action is a sound the narrator delivers with emphasis. The actions get smaller (big splash → small splash → tiny plip). The energy visibly drains.
- Metaphor: The ripples go smooth. The echoes fade. The character's body is tired.
- Emotion markers: Start `[EXCITED]` (the anger has energy), transition through `[GENTLE]` as it drains, end `[SLEEPY]`.

#### Angry — Ages 6-8
- Source: Specific unfairness. A sibling destroyed something. A rule felt wrong. The character names what happened and why it wasn't fair.
- Release: Physical action (kicking stones, walking fast, stomping through puddles) then environmental beauty that arrives uninvited. "She didn't want the sunset to be beautiful right now, but it was."
- Underlying hurt: At this age, anger is usually sadness or disappointment wearing armor. The story can gently reveal the softer feeling underneath without forcing it.
- Emotion markers: Start `[EXCITED]` or `[DRAMATIC]`, move through `[GENTLE]`, end `[SLEEPY]`.

#### Angry — Ages 9-12
- Source: Layered. Tangled with powerlessness. "They decided things about his life without asking him." The anger might not even be about the trigger — it's about control, autonomy, being heard.
- Release: Not stomping — sensory awareness. Opening a window. Feeling cold air. Coming out of the head into the body. The anger isn't resolved or transformed — it's placed alongside other things (the cold air, the sound of the house, the neighbour's dog) until it's one thing among many rather than the only thing.
- Language: Interior, tight, controlled. Short sentences that mirror clenching. "He hadn't asked for this. He hadn't been asked about this. There was a difference."
- Emotion markers: Start `[CALM]` (controlled anger, not explosive), use `[GENTLE]` as the character opens the window / notices the world, end `[WHISPERING]`.

---

## Mood × Long Stories: Phase Tag Instructions

Long stories use `[PHASE_1]...[/PHASE_1]` etc. The mood modifies WHAT happens in each phase, not the phase structure itself. Phase ratios, TTS params, and crossfade rules remain unchanged from `PIPELINE_CONTENT_GUIDELINES.md`.

### Long Story Phase Content by Mood

| Mood | Phase 1 (Engagement) | Phase 2 (Settling) | Phase 3 (Sleep) |
|---|---|---|---|
| **wired** | Absurd premise, funny situations, comic energy, laughter | Humor softens to warmth, character finds cozy spot, smile replaces laugh | Standard: still, warm, sensory |
| **curious** | Discovery, mystery, following a trail, vivid world | Discovery resolves into beauty, character stops and observes | Standard: quiet observation |
| **calm** | Already gentle, sensory from the start, no inciting incident | Even gentler, nearly nothing happens | Standard: dissolution |
| **sad** | Character feels the sadness, it's named, specific, not rushed | Small kindness arrives, companionship without fixing | Standard: tender warmth, rest |
| **anxious** | Character is afraid, fear is specific and physical, body sensations named | Feared thing encountered and revealed as safe, reframing | Standard: safe, held, protected |
| **angry** | Character is angry, cause is real, body does the feeling, stomping/throwing | Physical release exhausts energy, environment beauty arrives | Standard: spent, empty, calm |

**CRITICAL FOR ALL MOODS:** Phase 3 text follows the existing age-group rules exactly. No mood-specific content in Phase 3. The mood has already dissolved by the end of Phase 2.

### Long Story Emotion Marker Sequences by Mood

| Mood | Phase 1 Markers | Phase 2 Markers | Phase 3 Markers |
|---|---|---|---|
| wired | `[EXCITED]` `[JOYFUL]` `[CURIOUS]` | `[GENTLE]` `[CALM]` | `[SLEEPY]` `[WHISPERING]` |
| curious | `[CURIOUS]` `[ADVENTUROUS]` `[MYSTERIOUS]` | `[GENTLE]` `[CALM]` | `[SLEEPY]` `[WHISPERING]` |
| calm | `[GENTLE]` `[CALM]` | `[CALM]` `[SLEEPY]` | `[SLEEPY]` `[WHISPERING]` |
| sad | `[GENTLE]` `[CALM]` | `[GENTLE]` `[CALM]` | `[SLEEPY]` `[WHISPERING]` |
| anxious | `[GENTLE]` `[MYSTERIOUS]` `[CURIOUS]` | `[CALM]` `[GENTLE]` | `[SLEEPY]` `[WHISPERING]` |
| angry | `[EXCITED]` `[DRAMATIC]` | `[GENTLE]` `[CALM]` | `[SLEEPY]` `[WHISPERING]` |

---

## Mood × Poems

Poems follow the existing structure (4-12 stanzas, `[RHYTHMIC]` per stanza, `[PAUSE]` between, `[SLEEPY]` at end). The mood modifies the content and imagery, not the structure.

| Mood | Opening Stanzas (60%) | Closing Stanzas (40%) |
|---|---|---|
| **wired** | Funny rhymes, silly images, nonsense words, absurd characters. "The fish put on his finest hat / and told the sea, 'I'm done with that.'" | Shift to warm, sleepy rhymes. The silly character rests. |
| **curious** | Wonder, discovery, questions. "Who lit the lanterns in the deep? / Who told the mountains when to sleep?" | The questions resolve into quiet acceptance. No answers needed. |
| **calm** | Sensory, slow. "The rain came soft upon the stone / the moss grew warm, the world was home." | Even softer. Pure sleep imagery. |
| **sad** | Gentle acknowledgment of a hard feeling. "Some days are heavy, some days are long / some days the world just feels all wrong." | Warmth arrives. "But even on the hardest days, / the moon still rises anyway." |
| **anxious** | Names the fear gently. "The shadows stretch across my wall / I think I hear the darkness call." | Reframes to safety. "But darkness is just light at rest / and night is when the world is blessed." |
| **angry** | Names the frustration with rhythm. "It wasn't fair, it wasn't right / I want to stomp into the night." | Energy drains through the verse. "But stomping feet grow tired too / the stars don't mind what we've been through." |

### Age-specific poem adjustments:
- **Ages 2-5:** AABB rhyme mandatory for all moods. Simple vocabulary. Wired poems use silly sounds and onomatopoeia.
- **Ages 6-8:** AABB or ABAB. Richer imagery. Anxious and sad poems can be more specific about the feeling.
- **Ages 9-12:** Free verse allowed for sad, anxious, and angry. Rhyme optional. More literary, less sing-song.

---

## Mood × Lullabies (Ages 0-1 and 2-5 Only)

Lullabies are limited to moods that work in a musical, non-narrative format.

### Lullabies — Ages 0-1

Only `calm` and `curious` moods. Both use the existing 0-1 lullaby format (nonsense syllables, minimal real words). The mood affects the soothing word choices:

| Mood | Permitted Soothing Words | Syllable Energy |
|---|---|---|
| calm | sleep, hush, dream, moon, star, warm | Slow, even, repetitive |
| curious | moon, star, glow, soft, see, wonder | Slightly more varied pitch pattern, still slow |

### Lullabies — Ages 2-5

| Mood | Verse Content | Chorus Character |
|---|---|---|
| **calm** | Gentle imagery: stars, moon, warmth, blankets | "Sleep now, sleep now, the world is at rest..." |
| **curious** | Wonder imagery: what the stars do, where the moon goes | "Dream now, dream now, of faraway things..." |
| **anxious** | Reassurance: you are safe, I am here, the night is kind | "Safe now, safe now, the dark is your friend..." |

**Anxious lullabies (2-5):** This is the ONE lullaby mood that addresses a specific emotional state. The verses name safety in simple, physical terms: "The door is locked, the windows shut / your blanket's warm, the light is up." The chorus is pure reassurance. The humming fade is unchanged.

---

# SECTION 2: AUDIO GENERATION BY MOOD

## 2.1 Voice Selection by Mood

Each content piece generates **2 mood-appropriate voice variants per language** (not 5). The voice pairing is automatically selected based on mood, content type, and age group using the maps in `voice_service.py`.

This cuts audio generation cost and time by 60% while producing more appropriate voice pairings.

**Applies to:** Stories, Long Stories, Poems.
**Does NOT apply to:** Lullabies (use ACE-Step, not Chatterbox TTS).

See `voice-mood-autoselection.md` for the complete `STORY_VOICE_MAP`, `POEM_VOICE_MAP`, and `LONG_STORY_VOICE_MAP` tables, including age group overrides and the rationale for each pairing.

**Key design choices:**
- `gentle` (male) appears in 5/6 moods — every mood benefits from a male-female pair for variety
- `musical` (almost-singing quality) anchors most poem deliveries
- Long stories use mood voices for Phase 1-2, then ASMR voice always takes over Phase 3
- Calm long stories use `gentle` as Voice 2 (not `asmr`) to preserve contrast with the ASMR Phase 3 takeover

---

## 2.2 Mood-Specific Paragraph Pause Patterns

The biggest audio lever for conveying mood. The silence between paragraphs IS the mood — comedy needs irregular rhythm, sadness needs weight, anger needs rapid-fire then space.

**Current system:** Flat pause per phase (e.g., 1200ms for all Phase 1 paragraphs).
**Mood system:** Variable pauses within a phase, determined by mood and punctuation context.

### Pause Pattern Rules

```python
MOOD_PAUSE_PATTERNS = {
    "wired": {
        # Comedy needs irregular rhythm: short-short-LONG (setup-setup-punchline)
        "phase1": {
            "default": 800,
            "after_exclamation": 1800,     # pause after the punchline lands
            "after_ellipsis": 1500,        # comedic timing pause
            "after_caps_word": 1600,       # pause after SPLAT, BONK etc.
        },
        "phase2": {"default": 1500},
        "phase3": {"default": 3500},       # standard sleepy pause
    },
    "curious": {
        # Steady forward momentum — regular, unhurried
        "phase1": {"default": 1000},
        "phase2": {"default": 1800},
        "phase3": {"default": 3500},
    },
    "calm": {
        # Even, predictable — no surprises
        "phase1": {"default": 1200},
        "phase2": {"default": 2000},
        "phase3": {"default": 3500},
    },
    "sad": {
        # Every pause is heavy — the silence carries the feeling
        "phase1": {"default": 1500},
        "phase2": {"default": 2200},
        "phase3": {"default": 3500},
    },
    "anxious": {
        # Phase 1: irregular — halting, uncertain. Phase 2: regularizes (= safety)
        "phase1": {
            "default": 1000,
            "alternating": [800, 2000],    # odd paragraphs 800ms, even 2000ms
        },
        "phase2": {"default": 1800},       # steady = safe
        "phase3": {"default": 3500},
    },
    "angry": {
        # Phase 1: rapid-fire, stacking. Phase 2: dramatically spacious
        "phase1": {
            "default": 600,
            "after_short_sentence": 500,   # sentences < 40 chars get even shorter gaps
        },
        "phase2": {"default": 2200},       # the contrast IS the anger draining
        "phase3": {"default": 3500},
    },
}
```

### Implementation

```python
def get_paragraph_pause(mood, phase, paragraph_index, sentence_text):
    """Determine pause duration after this paragraph based on mood and context."""
    pattern = MOOD_PAUSE_PATTERNS.get(mood, MOOD_PAUSE_PATTERNS["calm"])
    phase_pattern = pattern.get(f"phase{phase}", pattern.get("phase1"))
    
    # Check for alternating pattern (anxious Phase 1)
    if "alternating" in phase_pattern:
        values = phase_pattern["alternating"]
        return values[paragraph_index % len(values)]
    
    # Check contextual rules
    text = sentence_text.strip()
    
    if "after_exclamation" in phase_pattern and text.endswith("!"):
        return phase_pattern["after_exclamation"]
    
    if "after_ellipsis" in phase_pattern and text.endswith("..."):
        return phase_pattern["after_ellipsis"]
    
    if "after_caps_word" in phase_pattern and re.search(r'[A-Z]{3,}', text):
        return phase_pattern["after_caps_word"]
    
    if "after_short_sentence" in phase_pattern and len(text) < 40:
        return phase_pattern["after_short_sentence"]
    
    return phase_pattern["default"]
```

---

## 2.3 Exaggeration Ramping (Per-Paragraph)

Instead of flat exaggeration per content type, ramp it from a mood-specific starting value down to 0.25 (sleepy) across the story. The child hears the narrator gradually settling.

### Starting Exaggeration by Mood

| Mood | Start | End | Character |
|---|---|---|---|
| **wired** | 0.75 | 0.25 | Starts maximum expressive (comic timing), ends flat |
| **angry** | 0.70 | 0.25 | Starts intense (frustration energy), ends flat |
| **curious** | 0.60 | 0.25 | Starts engaged (wonder), ends flat |
| **anxious** | 0.55 | 0.25 | Starts moderate (can't be too performative with fear), ends flat |
| **calm** | 0.40 | 0.25 | Starts already low (gentle from the start), ends flat |
| **sad** | 0.35 | 0.25 | Starts lowest (heavy, restrained — sadness is not performative), ends flat |

### Ramp Function

```python
MOOD_EXAGGERATION = {
    "wired":   {"start": 0.75, "end": 0.25},
    "angry":   {"start": 0.70, "end": 0.25},
    "curious": {"start": 0.60, "end": 0.25},
    "anxious": {"start": 0.55, "end": 0.25},
    "calm":    {"start": 0.40, "end": 0.25},
    "sad":     {"start": 0.35, "end": 0.25},
}

def get_paragraph_exaggeration(mood, paragraph_index, total_paragraphs):
    """Ease-out ramp: drops fast early, plateaus toward the end."""
    params = MOOD_EXAGGERATION.get(mood, MOOD_EXAGGERATION["calm"])
    start = params["start"]
    end = params["end"]
    progress = paragraph_index / max(total_paragraphs - 1, 1)
    # Ease-out curve — drops fast then flattens
    return end + (start - end) * (1 - progress) ** 1.5
```

**Example: wired story with 20 paragraphs:**
```
Para 1:  0.75  (full comic energy)
Para 5:  0.58  (still playful)
Para 10: 0.42  (settling)
Para 15: 0.31  (nearly flat)
Para 20: 0.25  (sleepy)
```

**Example: sad story with 20 paragraphs:**
```
Para 1:  0.35  (heavy from the start)
Para 5:  0.31  (barely changes — sadness is steady)
Para 10: 0.28  (subtle settling)
Para 20: 0.25  (sleepy)
```

The contrast: a wired story starts 2x more expressive than a sad story. The child hears this difference immediately.

---

## 2.4 Speed Ramping (Per-Paragraph)

Same principle as exaggeration — the narrator gradually slows. The starting speed depends on the mood's natural energy.

### Starting Speed by Mood

| Mood | Start | End | Why |
|---|---|---|---|
| **wired** | 1.00 | 0.78 | Natural pace — humor needs conversational speed |
| **angry** | 0.98 | 0.78 | Slightly fast — urgency, stacking sentences |
| **curious** | 0.92 | 0.78 | Engaged but not rushed |
| **anxious** | 0.88 | 0.78 | Moderate — cautious, not fast |
| **calm** | 0.85 | 0.78 | Already slow |
| **sad** | 0.83 | 0.78 | Slowest start — weight from the first word |

### Ramp Function

```python
MOOD_SPEED = {
    "wired":   {"start": 1.00, "end": 0.78},
    "angry":   {"start": 0.98, "end": 0.78},
    "curious": {"start": 0.92, "end": 0.78},
    "anxious": {"start": 0.88, "end": 0.78},
    "calm":    {"start": 0.85, "end": 0.78},
    "sad":     {"start": 0.83, "end": 0.78},
}

def get_paragraph_speed(mood, paragraph_index, total_paragraphs):
    """Same ease-out curve as exaggeration."""
    params = MOOD_SPEED.get(mood, MOOD_SPEED["calm"])
    start = params["start"]
    end = params["end"]
    progress = paragraph_index / max(total_paragraphs - 1, 1)
    return end + (start - end) * (1 - progress) ** 1.5
```

---

## 2.5 Mood Emphasis Words — Special TTS for Key Words

The most distinctive audio feature. Specific words within a sentence get their own TTS parameters, creating natural emphasis that mirrors how a real human narrator would deliver the mood.

### How It Works

1. The LLM wraps key words in `[EMPHASIS]...[/EMPHASIS]` markers during text generation (see Section 1 mood prompts).
2. A backup keyword dictionary catches common mood words the LLM didn't wrap.
3. The TTS chunker isolates emphasis words into their own chunks.
4. Each emphasis chunk is generated with mood-specific TTS parameters.
5. The chunks are stitched back together with 50ms crossfades to smooth any seams.

### Emphasis TTS Parameters by Mood

```python
MOOD_EMPHASIS_PARAMS = {
    "wired": {
        # Comic punch — louder, more expressive, slight slowdown for emphasis
        "exaggeration": 0.85,
        "cfg_weight": 0.6,
        "speed_multiplier": 0.85,   # relative to current paragraph speed
    },
    "curious": {
        # Wonder lift — brighter, slightly open
        "exaggeration": 0.65,
        "cfg_weight": 0.45,
        "speed_multiplier": 0.88,
    },
    "calm": {
        # Melt — extra soft, slow, savored
        "exaggeration": 0.15,
        "cfg_weight": 0.15,
        "speed_multiplier": 0.75,
    },
    "sad": {
        # Heavy — flat, deliberate, weighty
        "exaggeration": 0.20,
        "cfg_weight": 0.20,
        "speed_multiplier": 0.75,
    },
    "anxious": {
        # Two sets: fear words (hushed) and safety words (warm)
        "fear": {
            "exaggeration": 0.15,
            "cfg_weight": 0.15,
            "speed_multiplier": 0.80,
        },
        "safety": {
            "exaggeration": 0.50,
            "cfg_weight": 0.40,
            "speed_multiplier": 0.90,
        },
    },
    "angry": {
        # Punch — sharp, clipped, emphatic
        "exaggeration": 0.80,
        "cfg_weight": 0.55,
        "speed_multiplier": 1.05,   # slightly fast = clipped emphasis
    },
}
```

### Backup Keyword Dictionary

Catches mood words the LLM didn't wrap in `[EMPHASIS]` tags. These are applied automatically during chunking.

```python
MOOD_KEYWORDS = {
    "wired": {
        "patterns": [
            r'[A-Z]{3,}',              # ALL CAPS words (SPLAT, BONK, CRASH)
            r'(\w)\1{2,}',             # repeated letters (sooooo, veeeery)
        ],
        "words": ["splat", "bonk", "crash", "whoosh", "plop", "thud",
                  "splash", "bang", "boing", "squish", "pop", "zoom",
                  "oh no", "again", "oops"],
    },
    "sad": {
        "words": ["gone", "empty", "alone", "missing", "quiet", "without",
                  "lost", "left", "used to", "no longer", "still", "away"],
    },
    "anxious": {
        "fear_words": ["dark", "shadow", "sound", "something", "what if",
                       "corner", "behind", "watching", "creak", "nothing there"],
        "safety_words": ["safe", "warm", "friend", "singing", "gentle", "okay",
                         "just a", "only a", "it was", "cricket", "branch"],
    },
    "angry": {
        "words": ["not fair", "stomped", "threw", "slammed", "no",
                  "couldn't", "wouldn't", "shouldn't", "why"],
    },
    "curious": {
        "words": ["never seen", "impossible", "behind", "glowing", "what",
                  "discovered", "hidden", "secret", "there it was"],
    },
    "calm": {
        "words": ["soft", "warm", "gentle", "breathing", "still", "quiet",
                  "slowly", "peaceful", "drift", "floating", "cozy"],
    },
}
```

### Chunking With Emphasis

The existing TTS chunker splits text at paragraph breaks then sentence boundaries. The mood emphasis system adds one more split layer: isolating emphasis words within sentences.

```python
import re

def chunk_with_mood_emphasis(text, mood):
    """Split text into chunks, isolating mood-emphasis words for special TTS."""
    chunks = []
    
    # Step 1: Normal sentence-level chunking (existing logic)
    sentences = split_into_sentences(text)
    
    for sentence in sentences:
        # Step 2: Check for [EMPHASIS] markers from LLM
        if "[EMPHASIS]" in sentence:
            parts = re.split(r'\[EMPHASIS\](.*?)\[/EMPHASIS\]', sentence)
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                if i % 2 == 0:
                    # Normal text — check against keyword dictionary too
                    sub_chunks = split_by_keywords(part, mood)
                    chunks.extend(sub_chunks)
                else:
                    # LLM-tagged emphasis word
                    emphasis_type = get_emphasis_type(part, mood)
                    chunks.append({
                        "text": part,
                        "params": "emphasis",
                        "emphasis_type": emphasis_type,
                    })
        else:
            # Step 3: Check against keyword dictionary
            sub_chunks = split_by_keywords(sentence, mood)
            chunks.extend(sub_chunks)
    
    return chunks


def split_by_keywords(text, mood):
    """Split a text fragment around mood keywords, tagging matches for emphasis."""
    keywords = MOOD_KEYWORDS.get(mood, {})
    chunks = []
    
    # Check regex patterns (ALL_CAPS, repeated letters)
    for pattern in keywords.get("patterns", []):
        match = re.search(pattern, text)
        if match:
            before = text[:match.start()].strip()
            word = match.group().strip()
            after = text[match.end():].strip()
            if before:
                chunks.append({"text": before, "params": "normal"})
            chunks.append({
                "text": word,
                "params": "emphasis",
                "emphasis_type": get_emphasis_type(word, mood),
            })
            if after:
                # Recurse on remainder
                chunks.extend(split_by_keywords(after, mood))
            return chunks
    
    # Check word lists
    all_words = keywords.get("words", [])
    all_words += keywords.get("fear_words", [])
    all_words += keywords.get("safety_words", [])
    
    text_lower = text.lower()
    for keyword in sorted(all_words, key=len, reverse=True):  # longest first
        idx = text_lower.find(keyword)
        if idx >= 0:
            before = text[:idx].strip()
            word = text[idx:idx+len(keyword)].strip()
            after = text[idx+len(keyword):].strip()
            if before:
                chunks.append({"text": before, "params": "normal"})
            chunks.append({
                "text": word,
                "params": "emphasis",
                "emphasis_type": get_emphasis_type(word, mood),
            })
            if after:
                chunks.extend(split_by_keywords(after, mood))
            return chunks
    
    # No keywords found — return as normal chunk
    if text.strip():
        chunks.append({"text": text, "params": "normal"})
    return chunks


def get_emphasis_type(word, mood):
    """For anxious mood, distinguish fear vs safety emphasis. Others have one type."""
    if mood == "anxious":
        fear_words = MOOD_KEYWORDS.get("anxious", {}).get("fear_words", [])
        safety_words = MOOD_KEYWORDS.get("anxious", {}).get("safety_words", [])
        word_lower = word.lower()
        if any(fw in word_lower for fw in fear_words):
            return "fear"
        if any(sw in word_lower for sw in safety_words):
            return "safety"
    return "default"
```

### Generating Audio for Emphasis Chunks

```python
def generate_chunk_audio(chunk, mood, paragraph_index, total_paragraphs, base_voice):
    """Generate TTS for a single chunk with mood-appropriate parameters."""
    
    if chunk["params"] == "normal":
        # Standard parameters with per-paragraph ramping
        exag = get_paragraph_exaggeration(mood, paragraph_index, total_paragraphs)
        speed = get_paragraph_speed(mood, paragraph_index, total_paragraphs)
        cfg = 0.4  # base cfg, ramped by existing emotion marker system
        
    elif chunk["params"] == "emphasis":
        emphasis_type = chunk.get("emphasis_type", "default")
        params = MOOD_EMPHASIS_PARAMS.get(mood, MOOD_EMPHASIS_PARAMS["calm"])
        
        # Anxious has two emphasis types
        if mood == "anxious" and emphasis_type in params:
            emp = params[emphasis_type]
        elif isinstance(params, dict) and "exaggeration" in params:
            emp = params
        else:
            emp = params.get("default", {"exaggeration": 0.5, "cfg_weight": 0.4, "speed_multiplier": 1.0})
        
        exag = emp["exaggeration"]
        cfg = emp["cfg_weight"]
        # Speed is relative to current paragraph speed
        base_speed = get_paragraph_speed(mood, paragraph_index, total_paragraphs)
        speed = base_speed * emp["speed_multiplier"]
    
    return call_chatterbox(
        text=chunk["text"],
        voice=base_voice,
        exaggeration=exag,
        cfg_weight=cfg,
        speed=speed,
    )
```

### Stitching Emphasis Chunks

Within a sentence, emphasis chunks and normal chunks are stitched with **50ms crossfades** (not silence). This prevents audible seams while keeping the emphasis delivery distinct.

Between sentences: standard pause (no change).
Between paragraphs: mood-specific pause from Section 2.2.

```python
def stitch_sentence_chunks(chunk_audios):
    """Stitch chunks within a sentence with 50ms crossfades."""
    if len(chunk_audios) == 1:
        return chunk_audios[0]
    
    result = chunk_audios[0]
    for next_chunk in chunk_audios[1:]:
        # 50ms crossfade to smooth the parameter transition
        result = crossfade(result, next_chunk, overlap_ms=50)
    return result
```

### Seam Risk Mitigation

The main risk with emphasis chunks is audible parameter discontinuity — the voice suddenly changing character on the emphasis word. Two rules minimize this:

1. **Maximum parameter delta.** The emphasis exaggeration should never be more than 0.4 above the current paragraph's base exaggeration. If the paragraph is at exaggeration 0.30 (late in a calm story), the emphasis word maxes at 0.70 — not 0.85. This prevents late-story emphasis words from sounding like they belong to a different story.

```python
def clamp_emphasis_exaggeration(emphasis_exag, paragraph_exag, max_delta=0.4):
    return min(emphasis_exag, paragraph_exag + max_delta)
```

2. **No emphasis in the final 20% of the story.** By the last fifth of the text, all emphasis markers are ignored and every chunk is generated with normal (ramped) parameters. The ending must be seamless.

```python
def should_apply_emphasis(paragraph_index, total_paragraphs):
    return paragraph_index < total_paragraphs * 0.8
```

---

## 2.6 Long Story Phase-Based Audio + Mood

For long stories with `[PHASE_1]...[/PHASE_1]` tags, the existing phase-based TTS params from `PIPELINE_CONTENT_GUIDELINES.md` Section 3.5 remain the PRIMARY control. Mood adds these layers on top:

**Paragraph pauses:** Use mood-specific pause patterns (Section 2.2) within each phase, BUT the phase's base pause overrides the mood default if the mood default is shorter. This means Phase 3 always gets 3000-3500ms pauses regardless of mood.

```python
def get_long_story_pause(mood, phase, paragraph_index, sentence_text, age_group):
    mood_pause = get_paragraph_pause(mood, phase, paragraph_index, sentence_text)
    phase_base = PHASE_PAUSE_MS[age_group][phase]  # from existing pipeline config
    return max(mood_pause, phase_base)  # never shorter than the phase base
```

**Exaggeration ramping:** Applied WITHIN each phase (not across the whole story). Phase 1 ramps from the mood's start value to a midpoint. Phase 2 ramps from the midpoint to near-end. Phase 3 is flat at 0.25.

**Speed ramping:** Same within-phase approach. Phase 1 and Phase 2 use the mood ramp. Phase 3 uses existing phase speed (0.78-0.82 depending on age group).

**Emphasis words:** Applied in Phase 1 and Phase 2 only. Phase 3 has no emphasis — all chunks are normal.

---

## 2.7 Summary: What the Child Hears

A **wired story** starts fast (speed 1.0), expressive (exaggeration 0.75), with irregular pauses (800ms then 1800ms after the joke). The word "SPLAAAAAT" hits with exaggeration 0.85. By the end, speed is 0.78, exaggeration is 0.25, pauses are 3500ms. The narrator went from comedian to lullaby singer.

A **sad story** starts already slow (speed 0.83), heavy (exaggeration 0.35), with long pauses (1500ms). The word "alone" drops to exaggeration 0.20 — barely there, like the narrator can barely say it. The pauses between paragraphs are the heaviest silences in any mood. By the end, it's the same 0.78/0.25/3500ms destination — but the journey was completely different.

An **angry story** starts fast (speed 0.98), emphatic (exaggeration 0.70), with rapid-fire pauses (600ms). "NOT FAIR" hits at exaggeration 0.80, speed 1.03. Then Phase 2 arrives and the pauses jump to 2200ms — the contrast IS the anger draining. The child's body follows the deceleration.

An **anxious story** starts moderate (speed 0.88), with irregular pauses that mirror the character's halting uncertainty (800ms, 2000ms, 800ms, 2000ms). "Dark corner" drops to a whisper (exaggeration 0.15). Then the cricket appears and "singing" lifts to exaggeration 0.50 — the voice opens up. The pauses regularize in Phase 2 (1800ms, 1800ms, 1800ms). The steadiness itself IS the resolution.

---

## 2.8 Implementation Priority

For the first test run, implement in this order:

1. **Paragraph pause patterns** (Section 2.2) — highest impact, lowest risk, just changing silence durations
2. **Exaggeration ramping** (Section 2.3) — second highest impact, moderate risk (per-paragraph param changes)
3. **Emphasis words** (Section 2.5) — most distinctive feature, highest risk (new chunking logic, potential seams)

If time allows only one change for the first wired test, do paragraph pauses. The irregular comedy timing (800ms-800ms-1800ms) will make the wired story sound fundamentally different from a calm story even if all other TTS params are unchanged.

---

## 2.9 Key Files to Modify

| File | Change |
|------|--------|
| `app/services/tts/audio_processing.py` | Add `get_paragraph_pause()`, mood-aware pause insertion |
| `scripts/generate_audio.py` | Add per-paragraph exaggeration/speed ramping, pass mood to TTS calls |
| `app/services/tts/chatterbox_service.py` | Accept per-chunk params (if not already parameterized per-call) |
| `app/services/tts/voice_service.py` | Add `MOOD_EMPHASIS_PARAMS` lookup |
| NEW: `app/services/tts/mood_emphasis.py` | `chunk_with_mood_emphasis()`, `split_by_keywords()`, `MOOD_KEYWORDS` |

---

# SECTION 3: BACKGROUND MUSIC BY MOOD

## Musical Brief Overrides

The mood adds constraints to the musical brief generated by Mistral. These are injected as additional rules into the brief generation prompt.

```python
MOOD_MUSIC_RULES = {
    "wired": {
        "tempo_range": [66, 75],          # Slightly faster — matches initial energy
        "melodic_character": ["cycling_arpeggio", "descending_lullaby"],  # Active melody
        "feel": "gentle_pulse",            # Rhythmic, not rubato — humor needs timing
        "pad_character_exclude": ["deep_ocean", "cave_resonance"],  # Too serious
        "ambient_events": ["cricket", "chimes", "leaves"],  # Light, playful
        "notes": "Music should feel lively in early playback, not somber. The phase system will darken it automatically."
    },
    "curious": {
        "tempo_range": [62, 72],
        "melodic_character": ["cycling_arpeggio", "drone_with_ornaments"],
        "feel": "gentle_pulse",
        "pad_character_exclude": [],
        "ambient_events": ["owl", "leaves", "waterDrop", "chimes"],
        "notes": "Music should feel like exploration — open, spacious, slightly mysterious."
    },
    "calm": {
        "tempo_range": [58, 66],
        "melodic_character": ["descending_lullaby", "stillness"],
        "feel": "free_rubato",
        "pad_character_exclude": [],
        "ambient_events": ["cricket", "waterDrop"],  # Minimal
        "notes": "Default mood. Existing brief generation rules apply without modification."
    },
    "sad": {
        "tempo_range": [58, 64],          # Slower
        "melodic_character": ["descending_lullaby", "drone_with_ornaments"],
        "feel": "free_rubato",
        "mode_prefer": ["aeolian", "minor_pentatonic"],  # Minor modes feel appropriate
        "pad_character_prefer": ["warm_strings", "deep_ocean", "earth_drone"],
        "ambient_events": ["rain_steady", "rain_light"],  # Rain is emotionally fitting
        "notes": "Music should feel warm and empathetic, not bleak. Minor key but not cold."
    },
    "anxious": {
        "tempo_range": [60, 68],
        "melodic_character": ["drone_with_ornaments", "stillness"],
        "feel": "free_rubato",
        "pad_character_prefer": ["warm_strings", "forest_hum"],  # Grounding
        "nature_sound_prefer": ["forest_night", "rain_light"],   # Familiar, safe sounds
        "ambient_events": ["cricket", "owl"],   # Night sounds — the story reframes these as safe
        "notes": "Music should feel safe and steady. Not ethereal or spacious — grounded and present."
    },
    "angry": {
        "tempo_range": [64, 72],          # Slightly faster to match energy
        "melodic_character": ["cycling_arpeggio", "descending_lullaby"],
        "feel": "gentle_pulse",            # Rhythmic — anger has a beat
        "mode_prefer": ["dorian", "aeolian"],   # Minor but not fragile
        "pad_character_prefer": ["earth_drone", "deep_ocean"],  # Grounding, substantial
        "nature_sound_prefer": ["river_stream", "ocean_waves_close"],  # Movement — matches anger's energy
        "ambient_events": ["waveCycle", "windGust"],   # Dynamic, then settling
        "notes": "Music should have weight and substance in Phase 1, not delicate. The phase system will soften it."
    },
}
```

### How It Integrates

In `scripts/generate_music_params.py`, after the standard brief is generated, apply mood rules:

```python
def apply_mood_to_brief(brief, mood):
    rules = MOOD_MUSIC_RULES.get(mood, MOOD_MUSIC_RULES["calm"])
    
    # Enforce tempo range
    brief["rhythm"]["baseTempo"] = max(
        rules["tempo_range"][0],
        min(rules["tempo_range"][1], brief["rhythm"]["baseTempo"])
    )
    
    # Enforce feel
    if "feel" in rules:
        brief["rhythm"]["feel"] = rules["feel"]
    
    # Apply mode preferences (suggest, don't force)
    if "mode_prefer" in rules and brief["tonality"]["mode"] not in rules["mode_prefer"]:
        # 70% chance of switching to preferred mode
        if random.random() < 0.7:
            brief["tonality"]["mode"] = random.choice(rules["mode_prefer"])
    
    # Apply melodic character
    if brief["melodicCharacter"] not in rules["melodic_character"]:
        brief["melodicCharacter"] = random.choice(rules["melodic_character"])
    
    # Exclude inappropriate pad characters
    if "pad_character_exclude" in rules:
        if brief["musicalIdentity"]["padCharacter"] in rules["pad_character_exclude"]:
            available = [p for p in ALL_PAD_CHARACTERS if p not in rules["pad_character_exclude"]]
            brief["musicalIdentity"]["padCharacter"] = random.choice(available)
    
    # Apply nature sound preferences
    if "nature_sound_prefer" in rules:
        if random.random() < 0.6:
            brief["environment"]["natureSoundPrimary"] = random.choice(rules["nature_sound_prefer"])
    
    return brief
```

---

# SECTION 4: COVER ART BY MOOD

## FLUX Prompt Mood Layer

The mood adds a clause to the FLUX prompt AFTER the character and style tokens and BEFORE the world/palette tokens. This changes the emotional register of the image without overriding the diversity axes.

```python
MOOD_COVER_PROMPTS = {
    "wired":   "playful and whimsical atmosphere, bright eyes, sense of fun and gentle mischief, warm humor",
    "curious": "sense of wonder and discovery, character looking ahead or upward, mysterious gentle light ahead",
    "calm":    "peaceful and serene, eyes closed or half-closed, completely at rest, cozy warmth",
    "sad":     "tender and gentle, soft expression, character sitting quietly, warm empathetic mood, NOT bleak",
    "anxious": "character looking brave, protective warm light nearby, cozy shelter visible, reassuring safety",
    "angry":   "character in motion or settling after motion, windswept, dynamic but calming, warm undertones",
}
```

### Mood → Palette Preferences

Certain moods pair better with certain palettes. These are weight boosts, not overrides — the diversity system still rotates palettes.

| Mood | Boosted Palettes (1.5x) | Suppressed Palettes (0.5x) |
|---|---|---|
| wired | golden_hour, ember_warm | moonstone |
| curious | twilight_cool, forest_deep | — |
| calm | moonstone, twilight_cool | — |
| sad | ember_warm, golden_hour | twilight_cool |
| anxious | ember_warm, golden_hour | berry_dusk |
| angry | ember_warm, forest_deep | moonstone |

**Rationale:** Sad stories should feel warm, not cold — `ember_warm` and `golden_hour` provide the "warm hug" visual feeling. Anxious stories need warm, protective light. Angry stories need grounding earth tones.

### Mood → Composition Preferences

| Mood | Preferred Compositions | Why |
|---|---|---|
| wired | intimate_closeup, winding_path | See the character's expression (humor is in the face) |
| curious | winding_path, vast_landscape | Forward motion, something ahead to discover |
| calm | circular_nest, intimate_closeup | Enclosed, safe, contained |
| sad | intimate_closeup, circular_nest | Close to the character, empathetic framing |
| anxious | circular_nest, intimate_closeup | Enclosed = safe. No vast empty spaces. |
| angry | vast_landscape, winding_path | Space for the feeling. Open sky. Room to breathe. |

### Mood → Animation Overlay Preferences

The SVG overlay elements can be weighted by mood. These are suggestions to the overlay generator, not hard rules.

| Mood | Boosted Elements | Suppressed Elements |
|---|---|---|
| wired | fireflies, floating_dust_motes, gentle_rain | sleeping_owl, sleeping_butterfly |
| curious | shooting_star, fireflies, caustics | sleeping_owl, sleeping_butterfly |
| calm | sleeping_owl, sleeping_butterfly, twinkling_stars | shooting_star |
| sad | gentle_rain, falling_leaves, candle_flicker | shooting_star, fireflies |
| anxious | candle_flicker, moon_glow, twinkling_stars | drifting_fog, shadow_play |
| angry | swaying_branches, wind_grass, water_ripples | sleeping_owl, sleeping_butterfly |

---

# SECTION 5: DIVERSITY INTEGRATION

## New Fingerprint Dimension: `mood`

Add `mood` to the diversity fingerprint at Tier 1:

```python
DIMENSION_WEIGHTS = {
    # Tier 1
    "characterType": 10,
    "setting": 10,
    "mood": 8,          # NEW — high weight because mood is immediately felt
    # ... existing dimensions unchanged
}
```

**Hard rule:** No same mood within a 3-day batch (same rule as characterType and setting).

**Catalog balance target:**

```
calm:     30%
curious:  25%
wired:    20%
anxious:  10%
sad:      10%
angry:     5%
```

## Future Dimension: `storyType` (Not Yet Implemented)

**Planned** as a future fingerprint dimension after the mood system is stable and generating content daily. Will include values like `folk_tale`, `mythological`, `fable`, `nature`, `slice_of_life`, `dream`. Not in scope for the current implementation.

---

# SECTION 6: EXPERIMENTAL WORKFLOW

## Step 1: Generate

```bash
# Example: Generate a wired story for ages 6-8
python3 scripts/generate_content_matrix.py \
  --mood wired --age 6-8 --type story --experimental
```

Output lands in `seed_output/experimental/`:
```
seed_output/experimental/
  gen-exp-abc123.json          # Story text + metadata + mood tag
  gen-exp-abc123_melodic.mp3   # Audio variant 1 (mood-selected voice)
  gen-exp-abc123_gentle.mp3    # Audio variant 2 (mood-selected voice)
  gen-exp-abc123_music.json    # Musical brief (mood-modified)
  gen-exp-abc123_background.webp
  gen-exp-abc123_overlay.svg
  gen-exp-abc123_combined.svg
```

Only 2 audio variants are generated per content piece, automatically selected by mood × age × content type. See Section 2.1.

## Step 2: Review

Listen to the story. Check:
- [ ] Does Phase 1 feel like the target mood? (Is the wired story actually funny? Is the sad story actually tender?)
- [ ] Does the mood dissolve by Phase 3 / the ending?
- [ ] **Pause patterns:** Do the pauses feel mood-appropriate? (Wired: irregular comic timing? Sad: heavy silences? Angry: rapid-fire then spacious?)
- [ ] **Exaggeration arc:** Does the narrator start with the right energy and settle? (Wired should start expressive and become flat. Sad should start flat and stay flat.)
- [ ] **Emphasis words:** Do the key words land with special delivery? (SPLAT sounds punchy? "alone" sounds heavy? "dark corner" sounds hushed?)
- [ ] **No audible seams:** Do emphasis word chunks blend smoothly with surrounding narration? No clicks, pops, or "different person" artifacts?
- [ ] **Emphasis in final 20%:** There should be NONE. Check that the last fifth of the story has flat, uniform delivery.
- [ ] Does the background music feel appropriate?
- [ ] Does the cover convey the right emotional register?

## Step 3: Promote or Reject

```bash
# Promote to production
python3 scripts/pipeline_run.py --promote gen-exp-abc123

# Reject (stays in experimental, not deployed)
python3 scripts/pipeline_run.py --reject gen-exp-abc123 --reason "humor too subtle for 2-5"
```

Promoted content moves to the production directory and becomes visible on the app. Rejected content is logged for iteration.

## Step 4: Test in Production

After promoting a few mood stories per age group:
- Monitor analytics: Do mood stories get higher completion rates?
- Monitor retention: Do users who access mood-specific content come back more?
- Monitor the sleep success rate: Do mood stories (especially wired and anxious) lead to more Phase 3 abandonments (= the child fell asleep)?

## Step 5: Iterate

Based on test results, adjust:
- **Pause patterns:** If wired stories don't feel funny, increase the post-punchline pause (1800ms → 2200ms). If sad stories feel too slow, reduce Phase 1 pause (1500ms → 1200ms).
- **Exaggeration range:** If wired stories sound too wild, reduce start from 0.75 to 0.65. If sad stories sound too flat, increase start from 0.35 to 0.42.
- **Speed range:** If angry Phase 1 sounds too rushed, reduce start from 0.98 to 0.92. If calm stories sound too fast, reduce start from 0.85 to 0.82.
- **Emphasis params:** If SPLAT doesn't sound distinct enough, increase emphasis exaggeration (0.85 → 0.90). If there are audible seams, reduce the delta between emphasis and base params.
- **Emphasis word count:** If stories have too many emphasized words, tighten the keyword dictionary or reduce the LLM's `[EMPHASIS]` budget (3-6 → 2-4 per story).
- Music rules (if sad stories feel too bleak, boost tempo or switch to major pentatonic)
- Cover prompts (if anxious covers look too scary, increase warm-light language)

---

# SECTION 7: SAFETY MODIFICATIONS FOR MOOD CONTENT

The existing safety rules in `PIPELINE_CONTENT_GUIDELINES.md` Section 8.1 still apply. These ADDITIONAL rules apply to mood-specific content:

### Sad Stories
- **Under 7:** No death, no permanent separation from parents, no abandonment. The sadness must be about smaller losses — a toy, a temporary absence, a friend moving away (not disappearing forever).
- **All ages:** The story must end with warmth. The sadness can persist ("the bench still felt wider") but the character must be in a state of comfort, not despair.
- **Never:** Depression, hopelessness, self-blame. The character is sad about something that happened, not about who they are.

### Anxious Stories
- **Under 7:** The feared thing is ALWAYS revealed as safe by the end. No ambiguity. The dark corner has a cricket. The shadow is a branch. Clear, specific, complete safety.
- **Ages 9-12:** The fear can remain partially unresolved ("the hallway would still be there tomorrow") but the character must reach a state of calm acceptance, not ongoing dread.
- **Never:** Real danger. The feared thing is never actually dangerous. This is not a horror story with a happy ending — the fear was always about perception, not reality.

### Angry Stories
- **All ages:** The anger is NEVER directed at the child listening. The character is angry about something in their world, not at the listener.
- **All ages:** No violence toward other characters. The physical release is directed at the environment — stones in water, stomping on ground, kicking leaves. Never hitting, breaking things belonging to others, or harming anyone.
- **All ages:** The cause of anger is real and valid. The story doesn't imply the character "shouldn't" be angry.
- **Under 7:** The anger resolves into physical tiredness and rest, not into understanding or a lesson. "Bear was tired now" — not "Bear realized he shouldn't have been angry."

---

# APPENDIX: Quick Reference Card

## Generate by Mood — What Changes

| Pipeline Stage | What the Mood Modifies |
|---|---|
| **Text** | Opening emotional arc, character state, Phase 1-2 content, emotion markers, `[EMPHASIS]` word tags |
| **Audio — Pauses** | Mood-specific paragraph pause patterns (irregular for wired/anxious/angry, heavy for sad) |
| **Audio — Exaggeration** | Per-paragraph ramp from mood start value (0.35-0.75) down to 0.25 (sleepy) |
| **Audio — Speed** | Per-paragraph ramp from mood start value (0.83-1.00) down to 0.78 (sleepy) |
| **Audio — Emphasis** | Key words isolated and generated with mood-specific TTS params (comic punch, heavy weight, whisper, etc.) |
| **Audio — Voice** | 2 mood-appropriate voices auto-selected per content piece (see `voice-mood-autoselection.md`) |
| **Music** | Tempo range, mode preference, melodic character, nature sounds, pad preference |
| **Cover** | FLUX prompt mood clause, palette boost, composition preference, overlay elements |
| **Fingerprint** | New `mood` dimension at weight 8 in collision scoring |

## What Mood Does NOT Change

| Pipeline Stage | Unchanged |
|---|---|
| **Text** | Word counts, phase ratios, safety rules, diversity dimensions |
| **Audio** | Number of variants (2 per language, mood-selected), normalization, QA, export format |
| **Audio — Long stories** | Phase-based TTS params remain primary control; mood layers on top |
| **Music** | Brief schema structure, diversity constraints, playback phase system, loop files |
| **Cover** | Architecture (FLUX + SVG), diversity axes, sleep-safe animation rules, output format |

## Implementation Priority (First Test Run)

| Priority | Change | Impact | Risk |
|---|---|---|---|
| 1 | Mood prompt injection in text generation | Highest — defines the story content | Low |
| 2 | Mood paragraph pause patterns | High — comedy timing, sadness weight | Low — only silence durations |
| 3 | Mood FLUX prompt clause for covers | Medium — visual mood register | Low — additive to existing prompt |
| 4 | Exaggeration ramping per paragraph | Medium — voice energy arc | Moderate — per-chunk param changes |
| 5 | Speed ramping per paragraph | Medium — pace arc | Moderate |
| 6 | Emphasis words (chunking + special params) | High — most distinctive feature | Higher — new chunking logic, seam risk |
| 7 | Music brief mood rules | Lower — phase system handles most of it | Low |
| 8 | Fingerprint dimension (mood) | Future — not needed for manual runs | Low |
