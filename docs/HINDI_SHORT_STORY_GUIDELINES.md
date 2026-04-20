# Hindi Short Story Guidelines

Bedtime short stories delivered in Hindi via ElevenLabs `eleven_multilingual_v2`.
The generation prompt and voice routing live in
`scripts/generate_experimental_hindi.py`.

## Principle: structural parity with English

The Hindi pipeline is structurally identical to English:

- **2 voices per story**, selected by `(mood, age_group)`. Two audio variants
  are generated; the app plays one.
- **No voice switching mid-story.** The same voice narrates the entire piece.
- **3 fixed TTS param sets** applied within the story (NORMAL / HOOK / PHRASE).
  Same voice, different params.
- **Long stories:** Phase 1+2 use the mood voice, Phase 3 always switches to
  Roohi (the analogue of English ASMR). This is the only voice switch in the
  entire pipeline.

If you find yourself adding phase-based voice switching, story-type
affinities, age-split overrides, or dialogue alternation — stop. None of that
exists in English. Phase 1 keeps the mapping simple.

## TTS engine

- **Primary:** ElevenLabs multilingual v2 (shared-library Hindi voices).
- **Fallback (A/B only):** Sarvam Bulbul v3.
- Audio assembly reuses the shared V2 pipeline (`scripts/audio_assembly.py`) —
  the only Hindi-specific delta is the `tts_fn` hook that routes to ElevenLabs.

## Voice cast

Five voices mapped to the five English voice roles. Shreya G is held as a
spare — reserved for content types that need her conversational energy
(funny shorts, Heart Talks).

| Voice     | ElevenLabs ID            | Character                            | English role   |
|-----------|--------------------------|--------------------------------------|----------------|
| Tripti    | `yLldDJzoAIYirDpSiBvy`   | Warm and Captivating                 | calm           |
| Roohi     | `oHNJagRZ2LQEfZb2CEkb`   | Breathy, Soft and Whisper            | soft / asmr    |
| Anika     | `RABOvaPec1ymXz02oDQi`   | Sweet, Lively and Warm               | melodic        |
| Gudiya    | `csPuxct3x4tABDZeKliZ`   | Very Young and Sweet Storyteller     | musical        |
| Meher     | `JS6C6yu2x9Byh4i1a8lX`   | Deep, Soft and Seductive             | gentle         |
| Shreya G  | `RwXLkVKnRloV1UPh3Ccx`   | Expressive and Conversational        | (spare)        |

Roohi doubles as both `soft` and `asmr`. When Shreya G joins the mapping, the
natural home is `musical` for `9-12` (swapping out Gudiya for older kids).

## Story voice map

```python
HINDI_STORY_VOICE_MAP = {
    # (mood, age_group) → [voice_1, voice_2]

    # WIRED
    ("wired",   "2-5"):  ["Anika",  "Meher"],
    ("wired",   "6-8"):  ["Anika",  "Meher"],
    ("wired",   "9-12"): ["Roohi",  "Meher"],

    # CURIOUS
    ("curious", "0-1"):  ["Gudiya", "Meher"],
    ("curious", "2-5"):  ["Gudiya", "Meher"],
    ("curious", "6-8"):  ["Gudiya", "Meher"],
    ("curious", "9-12"): ["Roohi",  "Meher"],

    # CALM
    ("calm",    "0-1"):  ["Tripti", "Roohi"],
    ("calm",    "2-5"):  ["Tripti", "Roohi"],
    ("calm",    "6-8"):  ["Tripti", "Roohi"],
    ("calm",    "9-12"): ["Tripti", "Roohi"],

    # SAD
    ("sad",     "2-5"):  ["Meher",  "Tripti"],
    ("sad",     "6-8"):  ["Meher",  "Tripti"],
    ("sad",     "9-12"): ["Meher",  "Tripti"],

    # ANXIOUS
    ("anxious", "2-5"):  ["Meher",  "Tripti"],
    ("anxious", "6-8"):  ["Meher",  "Roohi"],
    ("anxious", "9-12"): ["Meher",  "Roohi"],

    # ANGRY
    ("angry",   "2-5"):  ["Anika",  "Meher"],
    ("angry",   "6-8"):  ["Roohi",  "Meher"],
    ("angry",   "9-12"): ["Roohi",  "Meher"],
}
HINDI_DEFAULT_VOICES = ["Tripti", "Roohi"]
```

## TTS param sets (NORMAL / HOOK / PHRASE)

Single voice. Params change by role.

```python
HINDI_TTS_PARAMS = {
    "text":   {"stability": 0.70, "style": 0.00, "speed": 0.85},  # NORMAL
    "hook":   {"stability": 0.60, "style": 0.05, "speed": 0.88},  # HOOK
    "phrase": {"stability": 0.80, "style": 0.00, "speed": 0.78},  # PHRASE
}
```

Shared across all sets: `similarity_boost=0.75`, `use_speaker_boost=True`,
`model_id=eleven_multilingual_v2`, `output_format=mp3_44100_128`.

### Role rationale

- **NORMAL** — most of the story. Calm, contained baseline.
- **HOOK** — opening sentences. Slightly lower stability (0.60) and a touch
  of style (0.05) for engagement. Same voice, just more present.
- **PHRASE** — `[PHRASE]` tags. Higher stability (0.80) and slower (0.78) —
  warmer, more settled delivery for the repeated phrase that anchors the
  child into the story. Same voice, not a sleep-voice handoff.

## Long stories

```python
HINDI_LONG_STORY_VOICE_MAP = {
    # Phase 1 + Phase 2: use HINDI_STORY_VOICE_MAP[(mood, age_group)]
    # Phase 3: always Roohi, regardless of mood.
    "phase_3_voice": "Roohi",
}
```

Mirrors the English rule "Phase 3 is always ASMR." The only voice switch.

## Adjacent content types

Same 2-voice selection by `(mood, age_group)`. Same NORMAL/HOOK/PHRASE param
application. No per-content-type special casing beyond the voice table.

- Calm Down / Heart Talks — use this same pipeline.
- Funny shorts — Shreya G is the natural primary when that pipeline comes
  online; reserve her slot there.

## Text preprocessing

Minimal, engine-forced only:

1. **`[PHRASE]` tags** — phrase text gets a trailing `।` if missing.
   Without a terminator ElevenLabs' autoregressive model tends to hallucinate
   trailing syllables (observed bug with phrases ending on commas).

No phase-based punctuation rewriting. No ellipses injection.

## Tonal continuity

Each ElevenLabs call passes `previous_text` and `next_text` with the adjacent
`[TEXT]`/`[PHRASE]` segments. This prevents abrupt mood resets between
chunks. The assembler (`audio_assembly.assemble_v2_audio`) threads
`prev_text`/`next_text` into `tts_params` when a `tts_fn` is provided; the
default English Chatterbox path ignores these keys (no drift).

## Output format

- MP3, 44.1 kHz, 128 kbps.
- 44.1 kHz matches intro/bed/outro music beds exactly — no resampling loss
  on overlay.
- 192 kbps requires Creator tier; we stay on 128 kbps.

## Implementation reference

- Voice IDs + story voice map: `scripts/generate_experimental_hindi.py`
  (`ELEVENLABS_VOICES`, `HINDI_STORY_VOICE_MAP`, `get_story_voices`)
- Param sets: `HINDI_TTS_PARAMS`
- Single-voice TTS fn: `make_elevenlabs_tts_fn`
- Assembler hook (language-agnostic): `scripts/audio_assembly.py`
  `assemble_v2_audio(tts_fn=..., ...)`

## CLI

```bash
# Fresh story, default mood=calm, voice slot 1 (Tripti for calm/6-8)
python3 scripts/generate_experimental_hindi.py --engine elevenlabs

# Pick the secondary voice (slot 2 — Roohi for calm/6-8)
python3 scripts/generate_experimental_hindi.py --engine elevenlabs --voice-slot 2

# Override voice directly
python3 scripts/generate_experimental_hindi.py --engine elevenlabs --voice meher

# Re-render an existing story with a specific voice (A/B)
python3 scripts/generate_experimental_hindi.py \
    --from-story hindi_review/exph-XXXXXXXXXXXX.json \
    --engine elevenlabs --voice tripti
```

---

## Narrative craft checklist

Every Hindi short story must pass this checklist before publishing. Each
item below was added after a shipped story failed it.

### 1. Script policy — dual-script, engine-aware

**Devanagari for the engines. Roman for the UI.**

- ElevenLabs multilingual v2 and MiniMax Music v2.5 both tokenise
  Devanagari as Hindi phonemes cleanly. Roman Hindi is parsed as
  English-ish and clarity craters.
- The app still shows Roman because Hindi-first readers on the parent
  device are often comfortable with Roman transliteration.

**Canonical shape in hand-authored content:**

```python
STORY = {
    "title_roman":  "Chiki Aur Pehli Baarish",
    "title_deva":   "चिकी और पहली बारिश",
    "title_en":     "Chiki and the First Rain",          # cover-gen seed

    "text_roman":   "Shaam thi. Hawa thandi...",          # line-for-line
    "text_deva":    "शाम थी। हवा ठंडी...",                # line-for-line

    "hook_roman":   "...",
    "hook_deva":    "...",

    "description_en": "A small Indian palm squirrel named...",  # FLUX input
}
```

Roman and Devanagari must be **1-for-1 line-matched** so a diff is
trivially reviewable.

The audio renderer reads `text_deva`. Everything the app shows — title,
subtitle, text, hook — reads from the Roman fields. The `description_en`
is **never shown to the user**; it feeds the cover generator and any
English LLM that analyses the story.

### 2. Schema — `text` vs `raw_text`

The `text` field is what the app renders. It must be **clean of all v2
tags**: `[PAUSE: ms]`, `[PHRASE]…[/PHRASE]`, `[MUSIC]`, `[verse]`,
`[chorus]`, `[bridge]`. Paragraph breaks (`\n\n`) are preserved.

The tagged source lives only in `raw_text` (and `raw_text_deva` for
Hindi). The audio renderer consumes `raw_text_deva`; the app never
reads `raw_text`.

**Implementation**: use `scripts/fix_hindi_batch_day2_patch.clean_lyrics_text()`
(not `audio_assembly.clean_display_text` — that flattens paragraph
breaks). The cleaner strips any `[TAG]` bracket, collapses
intra-paragraph whitespace, and caps consecutive blank lines at 2.

### 3. When to skip the spoken audio hook

The v2 audio assembler speaks a `hook` line between the intro music and
the first narration segment. **Set `skip_hook=True` when the story's
first spoken line already grabs the child's attention.**

Hallmarks of a story that needs no spoken hook:

- Opens with a narrator→child call ("Suno na bachcho…", "Tumne kabhi…").
- Opens with a sensory image strong enough to be its own hook
  ("Shaam thi. Hawa thandi thandi.").
- The hook field duplicates the description or the first line.

If the hook is distinct and additive (English-style question: "What
happens when a girl finally makes the moon bounce?"), speak it. The
written `hook` field is still stored on the content entry for
subtitle/card display, just not rendered into the audio track.

The content entry sets `"hook_spoken_in_audio": false` when we
suppress it, so the publisher can later re-render without guessing.

### 4. Story-type signature openings

`story_type` is not just metadata — it dictates the opening beat. The
child's ear should recognise the shape of the story within the first
two sentences. Getting this wrong is a miscategorisation, not a style
choice.

| `story_type`      | Opening must be                                                            | Anti-pattern                                          |
|-------------------|----------------------------------------------------------------------------|-------------------------------------------------------|
| `prakriti_katha`  | A **sensory image** — sound, smell, temperature, weather, light.           | "Suno na bachcho. Aaj ___ ki kahani" (lok-katha).     |
| `lok_katha`       | Village/storyteller framing — "Suno na bachcho", "Ek baar ki baat hai".    | Cold environment description with no listener call.   |
| `chatur_katha`    | A problem or mischief stated up front.                                     | Slow descriptive opener; delays the hook.             |
| `mitra_katha`     | Two characters already together — friendship in the first line.           | Lone-character opening; friend arrives late.          |
| `sanskaar_katha`  | A moment of choice or small virtue action in the opener.                  | Pure description of character; no choice visible.     |

For `prakriti_katha` specifically: the child walks into the **scene
first**, meets the character **second**. Example:

> ✅ "Shaam thi. Hawa thandi thandi chal rahi thi. Peepal ke bade se
>    ped par, sabse upar wali shaakh par, ek chhoti si gilhari baithi
>    thi. Naam tha Chiki."

> ❌ "Suno na bachcho. Aaj Chiki gilhari ki kahani. Chiki ek bade
>    pipal ke ped par rehti thi…"

### 5. Direct addresses to the child — 2-3 per story

The narrator speaks **to the child**, not just about the character.
This is what makes a Hindi bedtime story feel like a parent at the
bedside rather than a read-aloud from a book.

**Requirement: at least 2, ideally 3, clean narrator→child addresses
per story.** Spread across the story: one early to pull the child in,
one at the turning point, one near the close if warranted.

**Clean markers** (these cleanly count):
- `Tumne kabhi …?` ("Have you ever …?")
- `Tumhe pata hai …?` ("Do you know …?")
- `Suno na bachcho, …` ("Listen, children, …")
- `Socho zara, …` ("Just think, …")

**Do NOT count** (ambiguous — could be character-internal):
- `Arre, yeh kya ho raha hai?` — might be the character's own
  surprise; reframe as `Tumhe pata hai kya ho raha tha?`.
- `Pata hai, …` used as filler — not a real question to the child.

A narrator question that could plausibly be the character thinking
must be rewritten to be **unambiguously addressed to the listener**.

### 6. Character — one specific endearing detail

Generic character traits describe the species, not the individual:

> ❌ "Choti choti aankhein, bhuri si dumm, aur hamesha kuch na kuch
>    chabati rehti." (describes every squirrel)

The SPECIFICITY OVER GENERIC principle: give the character **one small
thing that only they do**, and repeat or pay it off later in the
story.

> ✅ "Chiki hamesha isi shaakh par aati thi — sabse upar wali —
>    jahan se saara gaon dikhta tha." (Chiki's specific habit + the
>    view becomes the anchor for the sensory scene).

Other patterns that work:
- A one-line habit: "__ ko bari-bari patte ginna pasand tha."
- A signature preference: "__ sirf neele phool sungti thi."
- A spot they always return to: "__ ki apni chhoti si darar thi
  deewar mein."

The `character.identity` dict field (English) is fed to FLUX for the
cover. It must be rich enough for FLUX to render the species and
visual distinctiveness:

```python
"character": {
    "name":      "Chiki",
    "identity":  "a small Indian palm squirrel named Chiki with a "
                 "striped brown back and bright curious eyes",
    "special":   "she always sits on the topmost branch of the peepal "
                 "tree, where she can see the whole village",
    "personality_tags": ["Curious", "Gentle"],
}
```

### 7. Cover taxonomy — canonical 11 vs cover-gen 12

The 11 canonical `characterType` values used in the content schema
(`land_mammal`, `bird`, `sea_creature`, etc.) **do not** map 1-to-1
onto the cover generator's 12-key FLUX taxonomy (`animal`, `bird`,
`sea_creature`, …). Feeding `land_mammal` into the cover generator
falls through to the `human_child` default and produces a child
instead of the animal.

When invoking `generate_cover_experimental.py`, translate:

```python
CHAR_TYPE_CANONICAL_TO_COVER = {
    "land_mammal":         "animal",
    "reptile_amphibian":   "animal",
    "bird":                "bird",
    "sea_creature":        "sea_creature",
    "insect":              "insect",
    "human_child":         "human",
    "mythical_creature":   "mythical",
    "object_alive":        "object",
    "plant_tree":          "plant",
    "celestial_weather":   "celestial",
    "robot_mechanical":    "robot",
}
```

Canonical 11 goes into `content.json`. The cover-gen mapping is
published in `scripts/fix_hindi_batch_day2.py` and should be copied
into any new publisher.

### 8. Pre-publish checklist (run before every Hindi story)

- [ ] `text_roman` and `text_deva` line-for-line matched (same number
      of `\n\n` paragraph breaks).
- [ ] `text` field in the content entry has **zero** `[` characters
      (no tag leakage).
- [ ] `raw_text_deva` preserved on the entry.
- [ ] Opening matches `story_type` signature (§4).
- [ ] ≥ 2 clean direct addresses to the child (§5). Ambiguous ones
      reworded.
- [ ] One specific endearing character detail (§6). No species-level
      generics.
- [ ] `character` is a dict (name / identity / special /
      personality_tags), not a string.
- [ ] `character.identity` is rich English (fed to FLUX).
- [ ] `characterType` is canonical 11. Cover seed translates to
      cover-gen 12 (§7).
- [ ] `description_en` matches the story's actual opening beat
      (used for FLUX cover prompt).
- [ ] `skip_hook=True` unless the hook is genuinely additive (§3).
- [ ] `hook_spoken_in_audio` flag set accordingly.
- [ ] Audio produced from `text_deva`, not `text_roman`.
- [ ] MiniMax lullabies (if part of the batch): `reference_audio_url`
      passed; `lyrics` are Devanagari.

### 9. When these rules fail

If a shipped story misses any of §1-7, the fix is the same shape:

1. Edit the STORY dict in a `fix_*_patch.py` script (don't regenerate
   from scratch — keeps the ID, filenames, cover, and URL stable).
2. Re-render audio with the fixed `text_deva`.
3. Rewrite only the affected content entry via
   `upsert_content([entry])`.
4. On prod: pop the entry from `data/content.json`, admin-reload.
   (LocalStore's SEED_PREFERRED_FIELDS don't force-update `text`,
   `raw_text`, or `character`, so the pop is required to re-seed
   these.)
5. Deploy guard: `snapshot` before, `verify` after.

Precedents: `scripts/fix_hindi_batch_day2.py` (bugs 1-3),
`fix_hindi_batch_day2_patch.py` (bugs 4-5),
`fix_hindi_batch_day2_patch2.py` (bugs 6-8).
