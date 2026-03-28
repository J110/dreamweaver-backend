# Funny Shorts — Generation Guidelines
## Hard Rules for Script Generation, Audio, and Publishing

> **Purpose**: Single source of truth for all constraints when generating funny shorts.
> Cross-references: `FUNNY_SHORTS_EPISODE_STRUCTURE.md`, `FUNNY_SHORTS_MUSIC_SPEC.md`, `FUNNY_SHORTS_DELIVERY_TAGS.md`, `FUNNY_SHORTS_DIVERSITY_SCHEDULER.md`

---

## HARD RULES — Violations MUST Be Fixed Before Publishing

### 1. Maximum Stings Per Short: 8

No short may have more than 8 `[STING: ...]` tags. This is a firm limit across ALL age groups.

**How to check**: Count all `[STING: ...]` occurrences in the script. If > 8, remove the least essential ones (keep punchline stings, cut mid-beat stings).

### 2. Maximum Characters Per Age Group

| Age Group | Max Characters | Max Voices in `voices` array |
|-----------|---------------|------------------------------|
| 2-5       | **2**         | 2                            |
| 6-8       | 3             | 3                            |
| 9-12      | 3             | 3                            |

**Ages 2-5 can NEVER have a trio.** If format is `trio`, it is invalid for ages 2-5. Use `solo` or `duo` only.

### 3. Comedy Type × Age Validity

Not all comedy types are valid for all ages:

| Age Group | Valid Comedy Types |
|-----------|--------------------|
| 2-5       | `physical_escalation`, `villain_fails`, `sound_effect` |
| 6-8       | `physical_escalation`, `villain_fails`, `misunderstanding`, `ominous_mundane`, `sarcastic_commentary`, `sound_effect` |
| 9-12      | `villain_fails`, `misunderstanding`, `ominous_mundane`, `sarcastic_commentary` |

### 4. Voice × Age Validity

Not all voices are valid for all ages:

| Age Group | Valid Voices |
|-----------|-------------|
| 2-5       | `high_pitch_cartoon` (Pip), `comedic_villain` (Boomy), `musical_original` (Melody) |
| 6-8       | All 5 voices |
| 9-12      | `comedic_villain` (Boomy), `young_sweet` (Sunny), `mysterious_witch` (Shadow), `musical_original` (Melody) |

**`high_pitch_cartoon` (Pip) is NOT valid for ages 9-12.** `young_sweet` (Sunny) and `mysterious_witch` (Shadow) are NOT valid for ages 2-5.

### 5. Duration: 60-90 Seconds (Story Only)

The story portion (without episode bookends) must be 60-90 seconds. Full episode with jingles + host intro/outro: 75-110 seconds.

### 6. Every Sentence Must Have a Delivery Tag

Every dialogue line MUST include `[DELIVERY: tag1, tag2]` before the text. 1-2 tags per sentence. This is how emotional arcs are created.

### 7. Comedy Structure: SETUP → BEAT_1 → BEAT_2 → BEAT_3 → BUTTON

Every short follows this skeleton. No exceptions.
- SETUP (10-15s): Establish premise
- BEAT_1 (15-20s): First escalation
- BEAT_2 (15-20s): Second escalation
- BEAT_3 (15-25s): Maximum absurdity
- BUTTON (5-10s): Final punchline/callback

### 8. Punchline Tag Required

Exactly ONE line must be wrapped in `[PUNCHLINE]...[/PUNCHLINE]`. This triggers special TTS params.

### 9. Host Intro and Outro Required

Every script MUST include:
- `[HOST_INTRO: sentence]` — Under 20 words. Who + what + hint it goes wrong.
- `[HOST_OUTRO: sentence]` — Under 15 words. Winking callback.

Both are read by Melody (show host), NOT by any character in the story.

### 10. Required JSON Fields

Every funny short JSON MUST have ALL of these:

```json
{
  "id": "string",
  "title": "string",
  "age_group": "2-5|6-8|9-12",
  "comedy_type": "physical_escalation|villain_fails|misunderstanding|ominous_mundane|sarcastic_commentary|sound_effect",
  "format": "solo|duo|trio",
  "voices": ["voice_id_1", ...],
  "voice_combo": ["sorted", "voice_ids"],
  "primary_voice": "voice_id",
  "premise_summary": "string",
  "cover_description": "string",
  "host_intro": "string",
  "host_outro": "string",
  "base_track_style": "bouncy|sneaky|mysterious|gentle_absurd|whimsical",
  "script": "full script text",
  "created_at": "YYYY-MM-DD",
  "play_count": 0,
  "replay_count": 0
}
```

---

## DIVERSITY RULES — Enforced by Scheduler

### Format Distribution Targets

| Format | Target % |
|--------|----------|
| solo   | 40%      |
| duo    | 40%      |
| trio   | 20%      |

**Common mistake**: Generating all solos and trios with zero duos. Every batch of shorts MUST include duos.

### Comedy Type Distribution Targets

| Comedy Type | Target % |
|-------------|----------|
| physical_escalation | 20% |
| villain_fails | 20% |
| misunderstanding | 15% |
| ominous_mundane | 15% |
| sarcastic_commentary | 15% |
| sound_effect | 15% |

### Recency Check

No identical fingerprint (comedy_type × format × voice_combo) in the last 5 shorts for the same age group.

### Voice Combo Affinity (Soft Preferences)

These are not hard rules — preferences for when multiple combos are equally underrepresented:

| Comedy Type | Solo Preference | Duo Preference |
|-------------|----------------|----------------|
| physical_escalation | Pip | Pip + Boomy |
| villain_fails | Boomy | Boomy + Pip |
| misunderstanding | Sunny | Sunny + Boomy |
| ominous_mundane | Shadow | Shadow + Sunny |
| sarcastic_commentary | Sunny | Sunny + Boomy |
| sound_effect | Pip | Pip + Boomy |

---

## DELIVERY TAG RULES

### Tag Format

```
[CHARACTER] [DELIVERY: tag1, tag2] Dialogue text. [STING: type]
```

### Available Tags (1-2 per sentence max)

**Confidence**: confident, dismissive, bluster, triumphant, smug
**Uncertainty**: tentative, caught off guard, scrambling, defensive, desperate, stunned
**Pressure**: curious, suspicious, pointed, pressing, calm gotcha, devastating
**Energy**: loud, excited, panicked, outraged, delighted
**Calm**: quiet, deadpan, unbothered, ominous, gentle, wistful

### Character Arcs (How Tags Should Progress)

| Character | Typical Arc | Why |
|-----------|-------------|-----|
| Boomy (Croc) | confident → caught off guard → desperate → deflated | Grand plans crumble |
| Pip (Mouse) | curious → suspicious → calm gotcha | Quietly exposes the truth |
| Sunny (Sweet) | unbothered → deadpan → devastating | Minimal change IS the comedy |
| Shadow (Witch) | ominous → building → revealing | Dramatic narrator energy |
| Melody (Musical) | gentle → excited → deadpan | Straight man reacts |

**Key principle**: If one character gets louder, the other should get quieter. The contrast IS the comedy.

---

## MUSIC RULES

### Base Track Selection

| Comedy Type | Base Track Style |
|-------------|-----------------|
| physical_escalation | bouncy |
| villain_fails | sneaky |
| ominous_mundane | mysterious |
| sarcastic_commentary | gentle_absurd |
| sound_effect | bouncy |
| misunderstanding | gentle_absurd |

### Audio Layers

| Layer | Volume | Notes |
|-------|--------|-------|
| Voice (top) | 0 dB | Multi-character dialogue |
| Stings (middle) | -5 dB | Reactive comedy hits at `[STING:]` points |
| Base track (bottom) | -12 dB | Continuous, one style throughout, ducks to -20 dB for stings |

### Sting Rules

- Max 8 stings per short (HARD LIMIT)
- Sting-aware gaps: after a sting, wait sting_duration + 200ms before next dialogue
- Base track ducks to -20 dB during stings, recovers over 300ms
- Use character-specific stings when available (villain_fail for Boomy, witch_ominous for Shadow, etc.)

---

## EPISODE STRUCTURE

Every short is wrapped in a show structure:

```
[SHOW INTRO JINGLE]     ← 3.5s, static, same every episode
[HOST INTRO TTS]        ← 3-5s, Melody reads host_intro
[CHARACTER JINGLES]     ← 2-4.5s, one per character
[STORY]                 ← 60-90s, voice + base track + stings
[CHARACTER OUTRO JINGLE]← 1-1.5s, primary character only
[HOST OUTRO TTS]        ← 2-4s, Melody reads host_outro
[SHOW OUTRO JINGLE]     ← 3.5s, static, same every episode
```

### Jingle Files (Static, Generated Once)

12 files in `public/audio/jingles/`:
- Show: `beforebed_intro_jingle.wav`, `beforebed_outro_jingle.wav`
- Per character: `char_jingle_{name}_intro.wav`, `char_jingle_{name}_outro.wav`

These are persistent on the GCP server at `/opt/audio-store/jingles/` (backup) and `public/audio/jingles/` (active). They survive Docker rebuilds.

---

## AGE-SPECIFIC WRITING GUIDELINES

### Ages 2-5

- Short sentences: 5-10 words
- Onomatopoeia and repetition
- Silly names and sounds
- Max 2 characters (NO trios)
- Only: Mouse (Pip), Croc (Boomy), Musical (Melody)
- Only: physical_escalation, villain_fails, sound_effect
- Simple premise, clear cause-and-effect

### Ages 6-8

- Medium sentences
- Character dynamics shine (ego vs innocence, drama vs sarcasm)
- All 5 voices available
- All 6 comedy types available
- Can handle multi-voice scenes and character switching

### Ages 9-12

- Longer sentences, dry tone
- Humor through understatement — NEVER try to be funny
- The restraint IS the comedy
- Primary: Shadow, Sunny, Boomy
- No Pip (too childish for this age)
- Only: villain_fails, misunderstanding, ominous_mundane, sarcastic_commentary
- No physical_escalation, no sound_effect (too young)

---

## VOICE NAME MAPPING

Scripts use character names, code uses voice IDs:

| Script Name | Voice ID | Jingle Prefix |
|-------------|----------|---------------|
| BOOMY | comedic_villain | boomy |
| PIP | high_pitch_cartoon | pip |
| SHADOW | mysterious_witch | shadow |
| SUNNY | young_sweet | sunny |
| MELODY | musical_original | melody |

---

## PRE-PUBLISH CHECKLIST

Before publishing any new funny short:

1. [ ] Sting count ≤ 8
2. [ ] Character count ≤ 2 for ages 2-5
3. [ ] Comedy type valid for age group
4. [ ] All voices valid for age group
5. [ ] Every sentence has `[DELIVERY: ...]` tag
6. [ ] Has `[PUNCHLINE]` wrapper
7. [ ] Has `[HOST_INTRO:]` and `[HOST_OUTRO:]`
8. [ ] Format (solo/duo/trio) matches voice count
9. [ ] `voice_combo` is alphabetically sorted
10. [ ] `base_track_style` is set and valid
11. [ ] `created_at` is set to publication date
12. [ ] Duration 60-90s (story portion)
13. [ ] No identical fingerprint in last 5 shorts for same age group
14. [ ] Batch includes duos (not all solos/trios)
