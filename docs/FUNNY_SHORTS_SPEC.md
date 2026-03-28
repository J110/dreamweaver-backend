# Dream Valley — Funny Shorts Spec
## "Before Bed" Tab — Pre-Sleep Comedy Content (English)

---

## What This Is

60-90 second comedy audio pieces that live in the **Before Bed** tab (replacing the Explore tab). They are not sleep content — they are the reason the child opens Dream Valley. The sleep story is a separate action.

**The child's experience:**
```
Opens Dream Valley → 
Taps "Before Bed" tab →
Browses funny shorts while getting ready for bed →
Picks one (or two, or three) → laughs →
Later: parent starts sleep story from Stories tab
```

**The parent's experience:**
"If you brush your teeth and get into pyjamas, you can pick your funny story on Dream Valley."

---

## How Funny Shorts Differ from Everything Else

| | Funny Shorts | Wired Stories | Regular Stories |
|---|---|---|---|
| **Purpose** | Make child want to open the app | Guide hyper child to sleep | Sleep |
| **Duration** | 60-90 seconds | 3-5 minutes | 2-4 minutes |
| **Phases** | None | Phase 1→2→3 | Phase 1→2→3 |
| **Sleep engineering** | None | Full | Full |
| **Music** | Character-matched loops + reactive stings | Background ambient | Background ambient |
| **Voices** | 5 character voices, 1-3 per short | Mood-selected (2 voices) | Mood-selected (2 voices) |
| **Who selects** | Child (from Before Bed tab) | Parent (mood) | Parent (mood) |
| **Where it lives** | Before Bed tab | Stories tab | Stories tab |
| **Replayability** | High — kids replay funny things | Low | Low |
| **Relationship to sleep story** | Independent — played before or separately | IS the sleep content | IS the sleep content |

---

## Comedy Structure

Every funny short follows the same skeleton: **one absurd premise, escalated three times, ending on the biggest payoff.**

### The Skeleton

```
1. SETUP (10-15 sec)
   Meet the character(s). Establish the one weird thing.
   
2. FIRST BEAT (15-20 sec)
   The weird thing happens. Small consequence.
   
3. SECOND BEAT (15-20 sec)
   It happens again. Bigger consequence.
   
4. THIRD BEAT (15-25 sec)
   THIRD time. Maximum absurd consequence.
   
5. BUTTON (5-10 sec)
   One final line. Callback, deflation, or the character completely unfazed.
```

**Total: 60-90 seconds of audio.**

### Comedy Types

#### 1. Physical Comedy Escalation
Something physical happens three times, getting more absurd. **Best voices: Mouse solo, Croc+Mouse duo.**

#### 2. Villain Fails Spectacularly  
A character with grand plans fails at every step. **Best voices: Croc solo, Croc+Mouse duo, Witch+Croc duo.**

#### 3. Misunderstanding / Wrong Conclusion
A character misinterprets something obvious. **Best voices: Sweet solo, Mouse solo.**

#### 4. Sound Effect Comedy
The humor IS the sounds and onomatopoeia. **Best voices: Mouse solo.**

#### 5. Ominous Mundane (Deadpan)
The narrator describes absurd things with complete seriousness. **Best voices: Witch solo, Witch+Sweet duo.**

#### 6. Sarcastic Commentary
Deadpan commentary on absurd situations. **Best voices: Sweet solo, Sweet+Croc duo.**

---

## The Five Character Voices

These are **characters**, not narration variants. Each has a personality the child recognizes and requests by name.

### Voice Profiles

| Character | Voice File | Sounds Like | Personality |
|---|---|---|---|
| 🐭 **Mouse** | high_pitch_cartoon | Minnie Mouse — squeaky, high, energetic | The character things happen TO. Reacts with alarm, panic, confusion. |
| 🐊 **Croc** | comedic_villain | Non-human crocodile — dramatic, deep, theatrical | The villain who fails. Grand plans, dramatic self-importance, spectacular defeat. |
| 😏 **Sweet** | young_sweet | Young, innocent-sounding but sarcastic | Says the opposite of what she means. Sweet tone, cutting content. Unbothered. |
| 🧙‍♀️ **Witch** | mysterious_witch | Dark, low-pitched, mysterious, ominous | Makes everything sound like a dark prophecy. Even pancakes. |
| 🎵 **Musical** | musical_original | Rhythmic, mature, poetic, almost singing | Delivers nonsense verse with poetic seriousness. The straight man. |

### Voice × Age Compatibility

| Character | Ages 2-5 | Ages 6-8 | Ages 9-12 |
|---|---|---|---|
| 🐭 Mouse | ✅ Primary | ✅ Works | ❌ Too childish |
| 🐊 Croc | ✅ Works | ✅ Primary | ✅ Works |
| 😏 Sweet | ❌ Sarcasm lost | ✅ Works | ✅ Primary |
| 🧙‍♀️ Witch | ❌ Too dark | ✅ Works | ✅ Primary |
| 🎵 Musical | ✅ For poems | ✅ Works | ✅ Works |

### Character Interaction Pairings

| Pairing | Dynamic | Why It's Funny |
|---|---|---|
| 🐊+🐭 | Bully meets innocent | Croc's dramatic threats vs Mouse's squeaky "okay but why?" |
| 🧙‍♀️ + any | Ominous narration of silly events | "And then... the penguin... SLIPPED" in prophecy voice |
| 😏+🐊 | Sarcasm meets self-importance | Sweet calmly deflating Croc's ego |
| 🐭+😏 | Panic meets calm | Mouse freaking out, Sweet unbothered |
| 🧙‍♀️+😏 | Dark drama meets sarcasm | Both deadpan from opposite directions |
| 🐊+🧙‍♀️ | Villain narrated by villain | Witch treats Croc's failure as tragic epic |
| 🧙‍♀️+🐭+🐊 | Full ensemble | Witch narrates, Croc schemes, Mouse reacts |

### Per-Voice TTS Params

```python
FUNNY_VOICE_PARAMS = {
    "high_pitch_cartoon": {      # Mouse
        "exaggeration": 0.80,    # very expressive — squeaky reactions
        "cfg_weight": 0.60,
        "speed": 0.95,           # fast — cartoon energy
    },
    "comedic_villain": {         # Croc
        "exaggeration": 0.85,    # maximum drama
        "cfg_weight": 0.55,
        "speed": 0.88,           # slower — villain savors words
    },
    "young_sweet": {             # Sweet
        "exaggeration": 0.55,    # understated — sarcasm needs restraint
        "cfg_weight": 0.50,
        "speed": 0.92,           # natural pace — deadpan timing
    },
    "mysterious_witch": {        # Witch
        "exaggeration": 0.65,    # dramatic but controlled
        "cfg_weight": 0.45,
        "speed": 0.85,           # slow — ominous buildup
    },
    "musical_original": {        # Musical
        "exaggeration": 0.70,    # expressive but rhythmic
        "cfg_weight": 0.55,
        "speed": 0.90,           # steady rhythm
    },
}
```

### Punchline Params Per Voice

Punchline sentences get boosted params specific to each voice's comedy style.

```python
FUNNY_PUNCHLINE_PARAMS = {
    "high_pitch_cartoon": {
        "exaggeration": 0.88,        # even squeakier
        "speed_multiplier": 0.90,
    },
    "comedic_villain": {
        "exaggeration": 0.92,        # maximum dramatic outrage
        "speed_multiplier": 0.85,    # savors the punchline
    },
    "young_sweet": {
        "exaggeration": 0.50,        # MORE understated — peak sarcasm
        "speed_multiplier": 0.95,    # barely changes — deadpan
    },
    "mysterious_witch": {
        "exaggeration": 0.70,        # slightly more dramatic
        "speed_multiplier": 0.80,    # slow — ominous pause
    },
    "musical_original": {
        "exaggeration": 0.78,
        "speed_multiplier": 0.88,
    },
}
```

---

## Age-Specific Comedy

### Ages 2-5: Physical + Sound
- **Primary voices:** Mouse, Croc
- Short sentences (5-10 words). Onomatopoeia. Repetition. Silly names.
- Max 2 characters per short for this age.
- Comedy types: Physical Escalation, Sound Effect, Villain Fails

### Ages 6-8: Absurdity + Character Comedy
- **All five voices available.** Multi-voice scenes shine at this age.
- Medium sentences. Character dynamics: Croc's ego vs Mouse's innocence, Witch's drama vs Sweet's sarcasm.
- Comedy types: all six.

### Ages 9-12: Deadpan + Meta
- **Primary voices:** Witch, Sweet, Croc
- Longer sentences. Dry tone. Humor through understatement.
- NEVER try to be funny. The restraint IS the comedy.
- Comedy types: Ominous Mundane, Sarcastic Commentary, Villain Fails

---

## Music — Character-Matched Loops + Reactive Stings

### Character Loop Library

Each character has a musical signature. The child hears the tuba and knows the crocodile is about to do something stupid. The music IS half the joke.

```python
CHARACTER_LOOPS = {
    "bouncy_cartoon": {
        # Mouse / physical comedy
        "instruments": "pizzicato strings, ukulele strum, light shaker, glockenspiel",
        "tempo": "120-130 BPM",
        "feel": "playful, bouncy, cartoon-like, mischievous",
        "variants": 3,
    },
    "villain_march": {
        # Croc / villain scenes
        "instruments": "low tuba, sneaky bassoon, light timpani rolls, pizzicato bass",
        "tempo": "100-110 BPM",
        "feel": "sneaky, self-important, marching with false grandeur",
        "variants": 3,
    },
    "mysterious_creep": {
        # Witch / ominous narration
        "instruments": "celesta, low sustained strings, harpsichord, subtle theremin",
        "tempo": "90-100 BPM",
        "feel": "creepy but playful, horror movie for kids, ominous with a wink",
        "variants": 3,
    },
    "sweet_innocence": {
        # Sweet / sarcastic observation
        "instruments": "toy piano, light xylophone, soft acoustic guitar, triangle",
        "tempo": "110-120 BPM",
        "feel": "innocent, cute on the surface, deceptively simple",
        "variants": 2,
    },
    "poetic_bounce": {
        # Musical / funny poems
        "instruments": "harp arpeggios, light snare brushes, woodwind melody, soft bells",
        "tempo": "100-110 BPM",
        "feel": "rhythmic, lilting, whimsical, fairy-tale-gone-sideways",
        "variants": 2,
    },
    "chaos_ensemble": {
        # Multi-character escalation scenes
        "instruments": "all instruments layered, building, organized chaos",
        "tempo": "120-130 BPM",
        "feel": "everything at once but somehow fun, circus-like",
        "variants": 2,
    },
}
```

**Total: 15 loop variants** (3+3+3+2+2+2).

### Loop Switching in Multi-Voice Shorts

```python
CHARACTER_LOOP_MAP = {
    "MOUSE":   "bouncy_cartoon",
    "CROC":    "villain_march",
    "WITCH":   "mysterious_creep",
    "SWEET":   "sweet_innocence",
    "MUSICAL": "poetic_bounce",
}

MIN_SENTENCES_FOR_LOOP_SWITCH = 3  # don't switch for 1-2 line interjections
```

For solo shorts: one loop throughout. For multi-voice: loop crossfades (1.5s) when dominant character shifts (3+ consecutive sentences from a new character). Fast dialogue stays on the scene owner's loop.

### Comedy Sting Library

14 universal + 12 character-specific = **26 stings total.** Generated once, reused forever.

```python
COMEDY_STINGS = {
    # ===== Universal =====
    "buildup_short":     "comedy_buildup_2bar.wav",
    "buildup_long":      "comedy_buildup_4bar.wav",
    "tiny":              "comedy_tiny_squeak.wav",
    "medium_hit":        "comedy_drum_hit.wav",
    "big_crash":         "comedy_full_crash.wav",
    "silence":           "comedy_record_scratch.wav",
    "deflation":         "comedy_sad_trombone.wav",
    "victory":           "comedy_tada.wav",
    "splat":             "comedy_splat.wav",
    "boing":             "comedy_boing.wav",
    "whoosh":            "comedy_whoosh.wav",
    "tiptoe":            "comedy_tiptoe.wav",
    "run":               "comedy_running.wav",
    "slide_whistle":     "comedy_slide_whistle.wav",
    
    # ===== Villain / Croc =====
    "villain_entrance":  "comedy_villain_brass_sting.wav",    # dramatic DUN DUN
    "villain_fail":      "comedy_villain_deflate_tuba.wav",   # tuba going flat
    "villain_dramatic":  "comedy_villain_thunder.wav",        # fake thunder
    
    # ===== Witch =====
    "witch_ominous":     "comedy_witch_celesta_trill.wav",    # creepy trill
    "witch_reveal":      "comedy_witch_gong_tiny.wav",        # anticlimactic gong
    "witch_dramatic":    "comedy_witch_organ_chord.wav",      # organ for "PANCAKES"
    
    # ===== Mouse =====
    "mouse_squeak":      "comedy_mouse_squeak.wav",           # tiny squeak
    "mouse_panic":       "comedy_mouse_scramble.wav",         # fast footsteps
    "mouse_surprise":    "comedy_mouse_gasp_boing.wav",       # squeak + boing
    
    # ===== Sweet =====
    "sweet_eyeroll":     "comedy_sweet_single_note.wav",      # one bland piano note
    "sweet_pause":       "comedy_sweet_crickets.wav",         # literal crickets
    
    # ===== Musical =====
    "musical_flourish":  "comedy_musical_harp_run.wav",       # dramatic harp run
    "musical_detuned":   "comedy_musical_detuned.wav",        # music goes off key
}
```

### Mixing Rules

- Loop plays at -10dB under voice
- Stings fire, loop ducks to -18dB for sting duration + 300ms
- Stings at -4dB to -6dB
- Loop crossfades at 1.5s when dominant character changes
- Maximum 8 stings per short
- Loop fades out over 2 seconds at end

---

## Script Format

Every sentence tagged with one character. One sentence per line.

```
[TITLE: The Crocodile Who Was Definitely a Rock]
[AGE: 6-8]
[VOICES: comedic_villain, high_pitch_cartoon, mysterious_witch]
[COMEDY_TYPE: villain_fails]

[SETUP]
[WITCH] In the middle of a very ordinary pond, there was a rock. [STING: witch_ominous]
[WITCH] At least, it said it was a rock.
[/SETUP]

[BEAT_1]
[MOUSE] Excuse me, are you a rock?
[CROC] Yes. Obviously. Can you not see how rocky I am.
[MOUSE] You have eyes.
[CROC] Rocky eyes. Very common. [STING: villain_fail]
[/BEAT_1]

[BEAT_2]
[MOUSE] You also have teeth.
[CROC] Those are... minerals.
[MOUSE] They're very pointy minerals.
[CROC] IGNEOUS minerals. Very normal. Stop asking questions. [STING: medium_hit]
[/BEAT_2]

[BEAT_3]
[MOUSE] Can rocks swim?
[CROC] ...
[MOUSE] Because you're swimming right now.
[CROC] I am SINKING. SLOWLY. As rocks DO. [STING: big_crash]
[WITCH] He was not sinking. He was swimming quite fast, actually.
[/BEAT_3]

[BUTTON]
[WITCH] And the rock swam away. [STING: villain_fail]
[WITCH] [PUNCHLINE]It was a very talented rock.[/PUNCHLINE] [STING: witch_reveal]
[/BUTTON]
```

### Script Generation Prompt

```python
FUNNY_SHORT_PROMPT = """
Write a 60-90 second funny short for children aged {age_group}.

CHARACTERS AVAILABLE for this age group:
{available_characters}

Choose 1-3 characters. Tag EVERY sentence with the speaking character.

STRUCTURE (mandatory):
- SETUP: 2-3 sentences. Introduce characters and one funny premise.
- BEAT 1: The funny thing happens. Small consequence.
- BEAT 2: It happens again. Bigger consequence.
- BEAT 3: THIRD time. Maximum absurd consequence.
- BUTTON: 1-2 sentences. Final punchline.

RULES:
1. ONE premise, THREE escalations. No subplots.
2. 60-90 seconds when read aloud.
3. [PUNCHLINE]...[/PUNCHLINE] on punchline sentences (sentence-level only).
4. [STING: type] at END of the sentence. Max 8 stings.
5. Every sentence = one character. No mixing within a sentence.
6. Sentence-level audio only — no word-level emphasis or mid-sentence changes.
7. Each character sounds distinct: Mouse = alarm/panic, Croc = self-importance,
   Sweet = deadpan sarcasm, Witch = ominous drama.
8. No sleep language. Pure comedy.

Available stings: buildup_short, buildup_long, tiny, medium_hit, big_crash,
silence, deflation, victory, splat, boing, whoosh, tiptoe, run, slide_whistle,
villain_entrance, villain_fail, villain_dramatic, witch_ominous, witch_reveal,
witch_dramatic, mouse_squeak, mouse_panic, mouse_surprise, sweet_eyeroll,
sweet_pause, musical_flourish, musical_detuned

COMEDY STYLE for {age_group}:
{age_comedy_instructions}
"""

AVAILABLE_CHARACTERS = {
    "2-5": """
- MOUSE: Squeaky Minnie Mouse energy. Reacts with alarm and panic. Short sentences.
- CROC: Deep dramatic villain. Non-human crocodile voice. Self-important, always failing.
- MUSICAL: Rhythmic, poetic. For funny poems and nonsense verse only.
Max 2 characters per short for this age.
""",
    "6-8": """
- MOUSE: Squeaky cartoon. Reacts with alarm and confusion.
- CROC: Dramatic villain crocodile. Self-important, always failing.
- SWEET: Innocent-sounding but sarcastic. Deadpan. Unbothered.
- WITCH: Dark, low, mysterious. Makes everything a dark prophecy.
- MUSICAL: Rhythmic, poetic. For verse comedy.
2-3 characters per short. Multi-voice scenes work best at this age.
""",
    "9-12": """
- CROC: Dramatic villain crocodile. Self-important, always failing.
- SWEET: Sarcastic. Master of understatement. The less she reacts, the funnier.
- WITCH: Dark, mysterious. Makes mundane things ominous. The dramatic narrator.
- MUSICAL: Rhythmic, poetic. For verse comedy.
2-3 characters. Dry humor. Never try to be funny — restraint IS the comedy.
""",
}
```

---

## Audio Pipeline

### Step 1: Generate Script
```bash
python3 scripts/generate_funny_short.py --age 6-8
```
Validate: SETUP + 3 BEATs + BUTTON, ≤8 stings, ≤3 voices, every sentence tagged.

### Step 2: Generate Multi-Voice Narration

```python
FUNNY_VOICE_MAP = {
    "MOUSE":   "high_pitch_cartoon",
    "CROC":    "comedic_villain",
    "SWEET":   "young_sweet",
    "WITCH":   "mysterious_witch",
    "MUSICAL": "musical_original",
}

def generate_funny_audio(script):
    """Generate multi-voice audio for a funny short."""
    sentences = parse_voiced_sentences(script)
    audio_chunks = []
    
    for sentence in sentences:
        voice = FUNNY_VOICE_MAP[sentence.character]
        params = FUNNY_VOICE_PARAMS[voice].copy()
        
        if sentence.is_punchline:
            punch = FUNNY_PUNCHLINE_PARAMS[voice]
            params["exaggeration"] = punch["exaggeration"]
            params["speed"] = params["speed"] * punch["speed_multiplier"]
        
        clean_text = strip_all_tags(sentence.text)
        audio = generate_tts(clean_text, voice=voice, **params)
        audio_chunks.append(audio)
    
    # 300ms gaps — comedy needs snappy timing
    return stitch_sentences(audio_chunks, gap_ms=300)
```

### Step 3: Mix Loop + Stings + Narration

```python
def mix_funny_short(narration_audio, script):
    """Mix narration + character loops + stings."""
    timeline = AudioTimeline(narration_audio)
    
    # 1. Character-matched loop segments
    sentences = parse_voiced_sentences(script)
    loop_segments = get_loop_segments(sentences)
    for i, seg in enumerate(loop_segments):
        loop_file = get_random_variant(seg["loop"])
        if i == 0:
            timeline.add_loop(loop_file, volume_db=-10)
        else:
            timeline.crossfade_loop(loop_file, at=seg["start"],
                                     crossfade_ms=1500, volume_db=-10)
    
    # 2. Place stings
    stings = parse_sting_positions(script, narration_audio)
    for sting in stings:
        timeline.duck_loop(at=sting.timestamp, duck_to_db=-18,
                          duration=sting.audio_duration + 0.3)
        timeline.add_sting(COMEDY_STINGS[sting.type],
                          at=sting.timestamp, volume_db=-5)
    
    # 3. Fade out
    timeline.fade_loop(duration=2.0)
    return timeline.render()
```

### Step 4: No Cover Generation
Cards in the Before Bed tab use title + character emojis. No FLUX covers needed.

---

## App Integration

### Tab Structure

```
┌─────────────────────────────────────────────┐
│  [🏠 Home]   [🌙 Before Bed]   [📚 Stories] │
└─────────────────────────────────────────────┘
```

### The Before Bed Tab

Cards show title, character emojis, and play button. Child browses by cast.

```
┌──────────────────────────────────┐
│  🌙 Before Bed                   │
│                                  │
│  ┌──────────────┐ ┌──────────────┐
│  │ 🐊🐭         │ │ 🐊           │
│  │ The Crocodile │ │ The Great    │
│  │ Who Was       │ │ Tree Climbing│
│  │ Definitely    │ │ Disaster     │
│  │ a Rock        │ │              │
│  │       [▶]     │ │       [▶]    │
│  └──────────────┘ └──────────────┘
│  ┌──────────────┐ ┌──────────────┐
│  │ 🐭           │ │ 🧙‍♀️          │
│  │ The Bear Who  │ │ The Perfectly│
│  │ Sneezed       │ │ Normal Day   │
│  │       [▶]     │ │       [▶]    │
│  └──────────────┘ └──────────────┘
│  ┌──────────────┐                 
│  │   🔒 New     │                 
│  │   tomorrow!  │                 
│  └──────────────┘                 
└──────────────────────────────────┘
```

### Key Design Decisions

1. **No auto-transition to sleep story.** Before Bed and Stories are independent tabs.
2. **Full library visible.** Child picks what they want. Replays encouraged.
3. **One new short per day** (locked card). Daily retention.
4. **Future content types** (riddles, silly songs) slot in as new sections within Before Bed.

### Bedtime Flow (Two Independent Actions)

```
BEFORE BED (child-driven, optional):
1. Child opens Before Bed tab
2. Picks and plays funny shorts
3. Can happen during teeth brushing, pyjamas, etc.

SLEEP TIME (parent-driven):
4. Parent opens Stories tab, selects mood
5. Sleep story plays with full phase engineering
6. Child falls asleep
```

---

## Content Volume

### Launch: 22 Shorts

| Format | Age 2-5 | Age 6-8 | Age 9-12 | Total |
|---|---|---|---|---|
| 🐭 Mouse solo | 2 | 1 | — | 3 |
| 🐊 Croc solo | 1 | 1 | 1 | 3 |
| 🧙‍♀️ Witch solo | — | 1 | 2 | 3 |
| 😏 Sweet solo | — | 1 | 1 | 2 |
| 🎵 Musical solo | 1 | — | 1 | 2 |
| 🐊+🐭 duo | 1 | 2 | — | 3 |
| 🧙‍♀️+🐊 duo | — | 1 | 1 | 2 |
| 😏+🐊 duo | — | 1 | 1 | 2 |
| 🧙‍♀️+🐭+🐊 trio | — | 1 | — | 1 |
| 🧙‍♀️+😏 duo | — | — | 1 | 1 |
| **Total** | **5** | **9** | **8** | **22** |

### Ongoing: 3-5 per week
Alternate solo, duo, trio. Track which combos get most replays. Generate more of what works.

### Production Cost Per Short

```
Solo:     ~$0.012 (script + 1 voice TTS + $0 music)
Duo/Trio: ~$0.025-0.035 (script + 2-3 voice TTS + $0 music)
```

One-time music library: ~$3.30 for all 45 files.

---

## Metrics

| Metric | Target |
|---|---|
| Before Bed tab open rate | >60% of sessions |
| Shorts played per session | 1.5-2.5 |
| Completion rate | >90% |
| Replay rate | Track — high is good |
| Character popularity | Track — informs generation |
| Combo popularity | Track — informs generation |
| Before Bed → Stories correlation | >75% |
| Child asks for Dream Valley | The north star |

---

## Implementation Checklist

### One-Time Music Library
- [ ] Generate 6 character loops × 2-3 variants = 15 loop files
- [ ] Generate 14 universal stings
- [ ] Generate 12 character-specific stings
- [ ] Total: ~45 audio files

### Voice Setup
- [ ] Register all 5 funny voice references in voice_service.py
- [ ] Test each at base exaggeration — no hallucination
- [ ] Test each at punchline exaggeration — clean output
- [ ] Test multi-voice stitching with 300ms gaps — no artifacts at switches

### Pipeline
- [ ] Build `scripts/generate_funny_short.py` — character-tagged script generation
- [ ] Build `scripts/generate_funny_audio.py` — multi-voice TTS
- [ ] Build `scripts/mix_funny_short.py` — loop switching + sting placement
- [ ] Script validation: every sentence tagged, ≤8 stings, ≤3 voices, ≤90 sec

### App
- [ ] Replace Explore tab with Before Bed tab
- [ ] Grid with title, character emojis, play button
- [ ] Age-filtered content
- [ ] "New tomorrow!" locked card
- [ ] Play and replay count tracking

### Launch Content
- [ ] Generate 5 shorts for ages 2-5
- [ ] Generate 9 shorts for ages 6-8
- [ ] Generate 8 shorts for ages 9-12
- [ ] QA with real children — are they funny?
- [ ] QA stings, loop switching, dialogue timing
