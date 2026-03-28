# Dream Valley — Funny Shorts Music Architecture
## Two-Layer System: Base Track + Reactive Stings

---

## Overview

Every funny short has two music layers underneath the dialogue:

```
Layer 3 (top):     Voices — multi-character dialogue              0dB
Layer 2 (middle):  Stings — reactive comedy hits                  -5dB (when firing)
Layer 1 (bottom):  Base track — continuous, unique per short      -12dB
```

The base track provides **continuity** — one unbroken piece of music that holds the entire short together acoustically. The stings provide **punctuation** — character-specific comedy hits at scripted moments. The voices sit on top of both.

---

## What Changed and Why

The previous spec used character-matched loops that crossfaded when the dominant character changed (villain march → bouncy cartoon → mysterious creep). This caused two problems:

1. **Stings overlapping with dialogue.** The flat 500ms after-sting gap was too short for longer stings (tuba deflation = 2-3 seconds). The next character started talking over the sting.

2. **Musical fragmentation.** Loop switching between characters created discontinuity — the music was as choppy as the dialogue used to be before we added it. Instead of one sonic world, each character brought their own soundtrack that appeared and disappeared.

**The fix:** Replace character loop switching with one continuous base track. Character identity is carried by the stings (villain tuba, witch gong, mouse squeak), not by the background music. The base track holds the scene together; the stings tell you who's doing what.

---

## Layer 1: Base Track

### What It Is

A single continuous piece of comedy background music, 60-90 seconds long, that plays from start to finish underneath the entire short. It never switches, never changes style, never cuts. It fades in at the start, fades out at the end.

### What It Sounds Like

Light, playful, not too busy — it must leave room for dialogue and stings on top. Think of it as the acoustic equivalent of a stage set. The characters perform in front of it, not inside it.

The base track should have a gentle arc that mirrors the comedy structure: starts light (setup), builds slightly (beats 1-2), peaks (beat 3), and settles (button). But this arc is subtle — it's background, not foreground.

### Base Track Styles

Five styles that cover all comedy types:

```python
BASE_TRACK_STYLES = {
    "bouncy": {
        # Physical comedy, sound effects, Mouse-led shorts
        "instruments": "pizzicato strings, light ukulele, soft shaker, glockenspiel accents",
        "tempo": "115-125 BPM",
        "feel": "playful, light, bouncy but not hyperactive, leaves lots of space",
    },
    "sneaky": {
        # Villain fails, Croc-led shorts, schemes and plans
        "instruments": "soft pizzicato bass, muted trombone, light snare brushes, subtle woodblock",
        "tempo": "100-110 BPM",
        "feel": "tip-toeing, mischievous, conspiratorial, like a plan is forming",
    },
    "mysterious": {
        # Ominous mundane, Witch-led shorts, deadpan narration
        "instruments": "soft celesta, low sustained pad, gentle vibraphone, sparse harp",
        "tempo": "85-95 BPM",
        "feel": "slightly eerie but playful underneath, dark fairy tale, knowing wink",
    },
    "gentle_absurd": {
        # Sarcastic commentary, Sweet-led shorts, misunderstanding
        "instruments": "toy piano, soft acoustic guitar, light triangle, music box melody",
        "tempo": "105-115 BPM",
        "feel": "innocent on the surface, simple, deceptively sweet, ironic lullaby quality",
    },
    "whimsical": {
        # Funny poems, Musical-led shorts, ensemble chaos
        "instruments": "harp arpeggios, flute melody, light tambourine, woodwind harmonies",
        "tempo": "100-110 BPM",
        "feel": "fairy tale gone sideways, lilting, rhythmic, storybook energy",
    },
}
```

### Mapping Comedy Type to Base Track Style

```python
COMEDY_BASE_MAP = {
    "physical_escalation":  "bouncy",
    "villain_fails":        "sneaky",
    "ominous_mundane":      "mysterious",
    "sarcastic_commentary": "gentle_absurd",
    "sound_effect":         "bouncy",
    "misunderstanding":     "gentle_absurd",
    "funny_poem":           "whimsical",
}

# Override by primary character if comedy type doesn't have a clear map
CHARACTER_BASE_FALLBACK = {
    "MOUSE":   "bouncy",
    "CROC":    "sneaky",
    "WITCH":   "mysterious",
    "SWEET":   "gentle_absurd",
    "MUSICAL": "whimsical",
}

def get_base_track_style(comedy_type, primary_character):
    """Determine which base track style fits this short."""
    if comedy_type in COMEDY_BASE_MAP:
        return COMEDY_BASE_MAP[comedy_type]
    return CHARACTER_BASE_FALLBACK.get(primary_character, "bouncy")
```

### Production: Pool Approach (Launch)

Generate 3-4 base tracks per style = **15-20 base tracks total.** Each is 90 seconds long, instrumental only. Assign to shorts based on comedy type. Different shorts of the same style get different tracks from the pool for variety.

```python
BASE_TRACK_POOL = {
    "bouncy":        ["base_bouncy_01.wav", "base_bouncy_02.wav", "base_bouncy_03.wav"],
    "sneaky":        ["base_sneaky_01.wav", "base_sneaky_02.wav", "base_sneaky_03.wav"],
    "mysterious":    ["base_mysterious_01.wav", "base_mysterious_02.wav", "base_mysterious_03.wav"],
    "gentle_absurd": ["base_gentle_01.wav", "base_gentle_02.wav", "base_gentle_03.wav"],
    "whimsical":     ["base_whimsical_01.wav", "base_whimsical_02.wav", "base_whimsical_03.wav"],
}

def select_base_track(style, recent_shorts):
    """Pick a base track from the pool, avoiding recent repeats."""
    pool = BASE_TRACK_POOL[style]
    recent_tracks = [s.get("base_track") for s in recent_shorts[-5:]]
    available = [t for t in pool if t not in recent_tracks]
    if not available:
        available = pool  # all used recently — just pick any
    return random.choice(available)
```

### MusicGen Prompt for Base Track Generation

```python
BASE_TRACK_GEN_PROMPT = """
90 second comedy background music, instrumental only, no vocals.

Style: {style_description}
Tempo: {tempo}
Feel: {feel}

CRITICAL REQUIREMENTS:
- Must work as BACKGROUND under spoken dialogue — not too busy
- Leave space in the mid-range frequencies where voices live
- No sudden loud hits or accents — stings handle that separately
- Gentle energy arc: starts light, builds slightly in the middle, settles at the end
- Should loop cleanly if needed (smooth ending that could connect to start)
- No silence gaps longer than 1 second anywhere in the track
"""
```

### Base Track Specs

| Property | Value |
|---|---|
| Duration | 90 seconds (trim to match short's actual length) |
| Format | WAV, 44.1kHz, stereo |
| Volume in mix | -12dB |
| Fade in | 500ms at start |
| Fade out | 2000ms at end |
| Ducking | Ducks to -20dB when stings fire |

---

## Layer 2: Reactive Stings

### What They Are

Short (0.5-3 second) comedy sound effects that fire at scripted moments. They sit ON TOP of the base track and dialogue. When a sting fires, the base track ducks briefly to let the sting be heard clearly.

### The Sting Library (26 stings)

Generated once, reused across all shorts forever.

```python
COMEDY_STINGS = {
    # ===== Universal (14) =====
    "buildup_short":     "comedy_buildup_2bar.wav",        # ~2s rising tension
    "buildup_long":      "comedy_buildup_4bar.wav",        # ~4s dramatic build
    "tiny":              "comedy_tiny_squeak.wav",          # ~0.5s small deflation
    "medium_hit":        "comedy_drum_hit.wav",             # ~0.8s snare + cymbal
    "big_crash":         "comedy_full_crash.wav",           # ~1.5s full percussion
    "silence":           "comedy_record_scratch.wav",       # ~0.5s sudden stop
    "deflation":         "comedy_sad_trombone.wav",         # ~2s wah wah waaah
    "victory":           "comedy_tada.wav",                 # ~1s triumphant
    "splat":             "comedy_splat.wav",                # ~0.5s wet impact
    "boing":             "comedy_boing.wav",                # ~0.5s bounce
    "whoosh":            "comedy_whoosh.wav",               # ~0.5s fast movement
    "tiptoe":            "comedy_tiptoe.wav",               # ~2s sneaking pizzicato
    "run":               "comedy_running.wav",              # ~2s rapid footsteps
    "slide_whistle":     "comedy_slide_whistle.wav",        # ~1.5s falling/rising
    
    # ===== Villain / Croc (3) =====
    "villain_entrance":  "comedy_villain_brass_sting.wav",  # ~1.5s dramatic DUN DUN
    "villain_fail":      "comedy_villain_deflate_tuba.wav", # ~2.5s tuba going flat
    "villain_dramatic":  "comedy_villain_thunder.wav",      # ~2s fake thunder
    
    # ===== Witch (3) =====
    "witch_ominous":     "comedy_witch_celesta_trill.wav",  # ~1.5s creepy trill
    "witch_reveal":      "comedy_witch_gong_tiny.wav",      # ~1s anticlimactic gong
    "witch_dramatic":    "comedy_witch_organ_chord.wav",    # ~2s church organ hit
    
    # ===== Mouse (3) =====
    "mouse_squeak":      "comedy_mouse_squeak.wav",         # ~0.3s tiny squeak
    "mouse_panic":       "comedy_mouse_scramble.wav",       # ~1.5s fast footsteps
    "mouse_surprise":    "comedy_mouse_gasp_boing.wav",     # ~0.8s squeak + boing
    
    # ===== Sweet (2) =====
    "sweet_eyeroll":     "comedy_sweet_single_note.wav",    # ~0.5s one bland piano note
    "sweet_pause":       "comedy_sweet_crickets.wav",       # ~2s literal crickets
    
    # ===== Musical (2) =====
    "musical_flourish":  "comedy_musical_harp_run.wav",     # ~1s dramatic harp
    "musical_detuned":   "comedy_musical_detuned.wav",      # ~1s music goes off key
}
```

### Sting Specs

| Property | Value |
|---|---|
| Duration | 0.3s - 4s depending on sting |
| Format | WAV, 44.1kHz, stereo |
| Volume in mix | -5dB (louder than base track, softer than voice) |
| Base track duck | To -20dB for sting duration + 300ms recovery |
| Max per short | 8 stings |

### MusicGen Prompts for Sting Generation

```python
STING_GEN_PROMPTS = {
    "villain_fail": "cartoon comedy sound effect, tuba going flat and deflating, "
                    "2.5 seconds, like a villain's plan just failed, wah wah waaah, "
                    "bright and playful, children's show style",
    
    "witch_ominous": "creepy celesta trill, 1.5 seconds, mysterious but playful, "
                     "like a kid's horror movie, spooky music box, building tension "
                     "that resolves to nothing",
    
    "witch_dramatic": "dramatic church organ single chord, 2 seconds, comedy horror, "
                      "over-the-top dramatic sting for a mundane reveal, "
                      "like announcing 'PANCAKES' with a pipe organ",
    
    "mouse_squeak": "tiny cartoon squeak, 0.3 seconds, high pitched, like a small "
                    "mouse being surprised, cute and quick",
    
    "sweet_pause": "literal crickets chirping, 2 seconds, comedy pause, "
                   "the sound of awkward silence after a sarcastic comment, "
                   "sparse cricket sounds",
    
    # ... etc for all 26 stings
}
```

---

## Sting-Aware Dialogue Gaps

The critical fix. The gap after a sting must account for the sting's actual duration. A 2.5-second tuba deflation needs 2.7 seconds before the next character speaks, not 500ms.

```python
# Pre-measured sting durations (in milliseconds)
STING_DURATIONS = {
    "buildup_short":     2000,
    "buildup_long":      4000,
    "tiny":              500,
    "medium_hit":        800,
    "big_crash":         1500,
    "silence":           500,
    "deflation":         2000,
    "victory":           1000,
    "splat":             500,
    "boing":             500,
    "whoosh":            500,
    "tiptoe":            2000,
    "run":               2000,
    "slide_whistle":     1500,
    "villain_entrance":  1500,
    "villain_fail":      2500,
    "villain_dramatic":  2000,
    "witch_ominous":     1500,
    "witch_reveal":      1000,
    "witch_dramatic":    2000,
    "mouse_squeak":      300,
    "mouse_panic":       1500,
    "mouse_surprise":    800,
    "sweet_eyeroll":     500,
    "sweet_pause":       2000,
    "musical_flourish":  1000,
    "musical_detuned":   1000,
}

DIALOGUE_GAP_RULES = {
    "question_to_answer":  150,    # quick response
    "same_character":      200,    # continuing thought
    "character_switch":    350,    # new character
    "before_punchline":    600,    # comedic anticipation
    "after_punchline":     400,    # let it land
}

STING_BUFFER_MS = 200  # breathing room after sting ends

def get_sentence_gap(prev_line, current_line):
    """Calculate gap between sentences, accounting for sting duration."""
    
    # If previous line had a sting, wait for it to finish
    if prev_line and prev_line.get("stings"):
        last_sting = prev_line["stings"][-1]
        sting_ms = STING_DURATIONS.get(last_sting, 500)
        sting_gap = sting_ms + STING_BUFFER_MS
        
        # The sting gap is the MINIMUM — dialogue gap rules can make it longer
        base_gap = _get_dialogue_gap(prev_line, current_line)
        return max(sting_gap, base_gap)
    
    return _get_dialogue_gap(prev_line, current_line)

def _get_dialogue_gap(prev_line, current_line):
    """Standard dialogue gap without sting consideration."""
    if current_line.get("is_punchline"):
        return DIALOGUE_GAP_RULES["before_punchline"]
    
    if prev_line and prev_line.get("is_punchline"):
        return DIALOGUE_GAP_RULES["after_punchline"]
    
    if prev_line and prev_line["character"] == current_line["character"]:
        return DIALOGUE_GAP_RULES["same_character"]
    
    if prev_line and prev_line["text"].strip().endswith("?"):
        return DIALOGUE_GAP_RULES["question_to_answer"]
    
    return DIALOGUE_GAP_RULES["character_switch"]
```

### How Sting Timing Works in Practice

```
Example: "The Crocodile Who Was Definitely a Rock"

CROC: "Rocky eyes. Very common."
  → [STING: villain_fail] fires at end of sentence
  → villain_fail duration: 2500ms
  → gap = 2500 + 200 = 2700ms before next line
  → during this 2700ms: base track is ducked, tuba plays and fades,
    base track recovers, then:
MOUSE: "You also have teeth."
  → child hears: Croc speaks → tuba deflates (comedy beat) → 
    brief silence → Mouse responds

Without sting-aware gaps:
CROC: "Rocky eyes. Very common." [STING: villain_fail]
  → gap: 500ms (old flat gap)
  → MOUSE talks over the tuba: "You also have teeth." + "wah wah waaah"
  → comedy timing destroyed
```

---

## Mixing Pipeline

```python
def mix_funny_short(narration_chunks, script, base_track_file):
    """
    Mix multi-voice narration + base track + stings into final audio.
    
    Args:
        narration_chunks: list of per-sentence audio chunks with timestamps
        script: parsed script with sting positions
        base_track_file: path to the base track WAV file
    """
    # Calculate total duration from narration + gaps
    total_duration = calculate_total_duration(narration_chunks, script)
    
    # 1. Create timeline at total duration
    timeline = AudioTimeline(duration_ms=total_duration)
    
    # 2. Place base track — continuous, full duration
    base_track = load_and_trim(base_track_file, duration_ms=total_duration)
    timeline.add_layer(
        "base",
        audio=base_track,
        volume_db=-12,
        fade_in_ms=500,
        fade_out_ms=2000,
    )
    
    # 3. Place narration chunks at calculated timestamps
    timestamp = 0
    prev_line = None
    
    for i, (chunk, line) in enumerate(zip(narration_chunks, script.lines)):
        if i > 0:
            gap = get_sentence_gap(prev_line, line)
            timestamp += gap
        
        timeline.add_layer(
            f"voice_{i}",
            audio=chunk,
            start_ms=timestamp,
            volume_db=0,
        )
        
        # Place stings at end of this sentence
        sentence_end = timestamp + get_duration(chunk)
        if line.get("stings"):
            for sting_type in line["stings"]:
                sting_audio = load_audio(COMEDY_STINGS[sting_type])
                sting_duration = STING_DURATIONS[sting_type]
                
                # Duck base track for sting
                timeline.duck_layer(
                    "base",
                    at_ms=sentence_end,
                    duck_to_db=-20,
                    duration_ms=sting_duration + 300,
                    recovery_ms=300,
                )
                
                # Place sting
                timeline.add_layer(
                    f"sting_{i}",
                    audio=sting_audio,
                    start_ms=sentence_end,
                    volume_db=-5,
                )
        
        timestamp = sentence_end
        prev_line = line
    
    # 4. Render final mix
    return timeline.render()
```

---

## What's Retired from the Previous Spec

| Removed | Why |
|---|---|
| 6 character loop types (bouncy_cartoon, villain_march, mysterious_creep, sweet_innocence, poetic_bounce, chaos_ensemble) | Replaced by single continuous base track |
| 15 loop variants (3 per type × 5, 2 per type × 1) | Replaced by 15-20 base tracks in pool |
| `CHARACTER_LOOP_MAP` | No longer needed — no per-character loop assignment |
| `MIN_SENTENCES_FOR_LOOP_SWITCH` | No switching |
| `get_loop_segments()` | No segments — one track throughout |
| 1.5s loop crossfades | No crossfades — one continuous track |
| Loop at -10dB | Base track at -12dB (quieter, richer music needs more room) |
| Flat 500ms after-sting gap | Replaced by `get_sentence_gap()` with sting duration awareness |

---

## What Stays the Same

| Kept | Notes |
|---|---|
| All 26 stings | Unchanged — same library, same files |
| Sting volume at -5dB | Unchanged |
| Base track ducks for stings | Same principle, now ducks to -20dB (was -18dB) with 300ms recovery |
| Max 8 stings per short | Unchanged |
| 2-second fade out at end | Now on the base track instead of the loop |
| `[STING: type]` tags in script | Unchanged — same tag format |

---

## Audio File Inventory

### Base Tracks (one-time generation)

| Style | Count | Total Files |
|---|---|---|
| Bouncy | 3-4 variants | 3-4 |
| Sneaky | 3-4 variants | 3-4 |
| Mysterious | 3 variants | 3 |
| Gentle Absurd | 3 variants | 3 |
| Whimsical | 3 variants | 3 |
| **Total base tracks** | | **15-18** |

### Stings (one-time generation)

| Category | Count |
|---|---|
| Universal | 14 |
| Villain / Croc | 3 |
| Witch | 3 |
| Mouse | 3 |
| Sweet | 2 |
| Musical | 2 |
| **Total stings** | **27** |

### Grand Total: ~42-45 audio files

All generated once. Reused across every funny short forever. Total generation cost: ~$3-5 via MusicGen on Modal.

---

## Implementation Checklist

### Music Library Generation
- [ ] Generate 15-18 base tracks (3-4 per style, 90 seconds each, instrumental)
- [ ] Generate 14 universal stings
- [ ] Generate 13 character-specific stings
- [ ] Measure and record duration of each sting → populate `STING_DURATIONS` dict
- [ ] QA: listen to each base track under sample dialogue — does it leave room for voices?
- [ ] QA: listen to each sting in isolation — is it clearly identifiable and the right length?

### Pipeline Integration
- [ ] Add `BASE_TRACK_POOL` and `COMEDY_BASE_MAP` to music config
- [ ] Add `select_base_track()` function
- [ ] Update `mix_funny_short.py` — remove loop switching, add base track layer
- [ ] Implement `get_sentence_gap()` with sting duration awareness
- [ ] Add `STING_DURATIONS` dict with measured values
- [ ] Add base track ducking logic (duck to -20dB on sting, recover over 300ms)
- [ ] Add `"base_track"` field to funny short JSON schema

### Testing
- [ ] Mix one short with base track + stings — verify no sting-dialogue overlap
- [ ] Verify base track continuity — no cuts, no style changes, one smooth piece
- [ ] Verify sting-aware gaps — long stings (villain_fail) get full duration + buffer
- [ ] Verify base track ducking — stings are clearly audible above ducked base track
- [ ] Compare with old loop-switching version — the new version should sound more cohesive
- [ ] Test with the "Crocodile Rock" script — the villain_fail tuba should play fully before Mouse responds
