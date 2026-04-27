# English TTS Migration: Chatterbox → ElevenLabs

**Status:** Draft for review
**Date:** 2026-04-27
**Owner:** Anmol

## 1. Goal

Replace Chatterbox (Modal GPU) with ElevenLabs Multilingual v2 as the TTS engine for English **short stories (V2)** and **long stories**. Drivers: voice quality and Indian-English accent fit. The Hindi pipeline already runs on ElevenLabs and provides a proven implementation pattern to clone.

## 2. Scope

**In scope (English content):**
- V2 short stories — `scripts/generate_experimental_v2.py`, `scripts/generate_audio.py`, `scripts/audio_assembly.py`
- Long stories — `scripts/generate_long_story_episode.py`, `app/services/tts/voice_service.py`

**Out of scope (no changes):**
- Hindi (already on ElevenLabs)
- Lullabies, Silly Songs, Musical Poems (stay on MiniMax)
- Funny shorts (stay on Chatterbox for now)
- Audio assembly logic, music beds, mood pause maps, Phase-3 short-line batching, tag parsing — all preserved

## 3. Architecture

### 3.1 New shared module: `scripts/_elevenlabs_common.py`

Single source of truth for ElevenLabs integration. Lifted from `publish_hindi_long_day1.py` and de-duplicated. Exposes:

- `ELEVENLABS_VOICES_EN` — voice label → voice ID dict (English library)
- `elevenlabs_tts(text, voice_id, *, stability, similarity_boost, style, speed, model_id="eleven_multilingual_v2") -> bytes` — single TTS call returning WAV/MP3 bytes
- `V2_PHASE_TTS`, `LONG_STORY_TTS_EN`, `CHARACTER_VOICE_MODIFIERS_EN` — config tables (see §6, §7)
- `apply_modifier(base_params, modifier) -> params` — merges character voice-style offsets, clamps to legal ranges
- `build_v2_voice_pair(mood)` and `build_long_story_voice_map(mood, characters)` — voice-routing helpers

Hindi continues to use its own existing helpers (no consolidation in this PR — out of scope).

### 3.2 Call sites

- `scripts/generate_audio.py` — when `lang == "en"` and content is V2 short or long story, route to `elevenlabs_tts()` instead of the Modal Chatterbox endpoint. Other paths (poems with old emotion markers, funny shorts) keep Chatterbox.
- `scripts/generate_experimental_v2.py` — V2 generator already calls into a TTS layer; redirect that one call site.
- `scripts/generate_long_story_episode.py` — replace the Modal HTTP call with `elevenlabs_tts()` and feed translated section/character params.

### 3.3 Output format

Preferred: **PCM at 24 kHz** (`output_format=pcm_24000`) wrapped into WAV — drops directly into the existing 24 kHz audio-assembly pipeline with no downstream code changes.

**Plan-tier caveat:** ElevenLabs has historically gated PCM output above 22 kHz to paid tiers (Pro+). Before merge, verify the user's current plan supports `pcm_24000`. Fallbacks if not:
- `pcm_22050` — 22 kHz PCM (Creator-tier accessible) → audio assembly will need to upsample to 24 kHz (one extra step in the pipeline; cheap).
- `mp3_44100_128` — MP3 at 128 kbps → audio assembly already accepts MP3 input via the Hindi pipeline; downstream conversion adds one decode step.

The Hindi pipeline can be inspected to confirm which format it currently uses, since it's already running on this account in production.

## 4. Voice library (English)

Ten ElevenLabs voices, all from the shared library, **distinct voice IDs from the Hindi library** even where names overlap (e.g., Tripti). All added to the user's ElevenLabs account programmatically and smoke-tested 2026-04-27.

```python
ELEVENLABS_VOICES_EN = {
    # Female narrators (six unique mood narrators + asmr)
    "tripti":  "MwUMLXurEzSN7bIfIdXF",  # Calm and Experienced
    "monika":  "2zRM7PkgwBPiau2jvVXc",  # Deep and Natural
    "tara":    "P7vsEyTOpZ6YUTulin8m",  # Conversational and Expressive
    "simran":  "1ea3IFhmSWgw8sJkSvfJ",  # Cheerful Best Friend
    "rhea":    "eUdJpUEN3EslrgE24PKx",  # Soft, Polished and Calm
    "maya":    "4O1sYUnmtThcBoSBrri7",  # Friendly and Cheerful
    "zara":    "wdymxIQkYn7MJCYCQF2Q",  # Soothing, Meditative — ASMR / whisper
    # Male voices (long-story characters only)
    "ranbir":  "MgKG6W05zBkvXijkNguO",  # Deep and Dramatic Storyteller
    "harshit": "6TcvxMZXgg9AlJrd8iCl",  # Strong, Deep and Casual
    "ishan":   "N09NFwYJJG9VSSgdLQbT",  # Bold and Upbeat
}
```

## 5. Voice routing

### 5.1 V2 short stories — one narrator per mood (single variant)

This is a **deliberate departure** from the existing dual-narrator A/B system documented in `ENGLISH_SHORT_STORY_GUIDELINES.md` §14 and the Hindi mood × age `[primary, secondary]` pattern. Rationale: the engine swap to ElevenLabs already brings a quality lift; running both engine and architecture changes in the same PR makes A/B comparison muddy ("did quality improve because of ElevenLabs, or regress because we lost the second voice?"). Single-narrator is also faster to iterate per mood. We can revisit dual-narrator after the engine swap is validated; reverting is a config-only change.

| Mood | Narrator | Voice descriptor | Why this voice |
|------|----------|------------------|----------------|
| wired | tara | Conversational and Expressive | Channels wound-up energy without amplifying it; expressive cadence carries Phase-1 momentum and naturally softens through the descent |
| curious | simran | Cheerful Best Friend | Wonder reads better in a bright, friendly voice than a deep one; matches the discovery arc |
| calm | tripti | Calm and Experienced | The steady anchor — mature, unrushed, the baseline a calm story should sit on |
| sad | rhea | Soft, Polished and Calm | Tender and soft, doesn't push or perform sympathy; sits beside the feeling rather than fixing it |
| anxious | monika | Deep and Natural | **Grounding and reassuring.** Anxious children settle into a deep, slow-breathing voice that signals "everything is steady" — the depth is the reassurance |
| angry | zara | Soothing, Meditative and Calm | **Softens the heat with stillness.** Anger meets a hushed, meditative voice — not warmth that matches its energy, not gravity that adds weight, but a voice so calm it pulls the child toward stillness. Maya was the original pick (Friendly and Cheerful) but the voice didn't land; replaced 2026-04-27. Zara double-duties as the whisper/Phase-3-ASMR voice, so angry long-stories play in zara throughout (no Phase-3 voice switch — the takeover is just continuation) |

### 5.2 Long stories — three-layer voice system (preserved)

**Layer 1 — Mood narrator** (same as V2 table above).

**Layer 2 — Phase 3 ASMR takeover.** For all moods, **`zara`** narrates `[PHASE_3]` and any `[WHISPER]` blocks, replacing the mood narrator for those sections. (Hindi pipeline does the same with `roohi`.) For **angry** mood specifically, zara is also the Phase-1/2 narrator — so the takeover is a no-op (same voice throughout the story).

**Layer 3 — Character casting.** Per-story `CHAR_VOICE` dict assigns voices to dialogue characters. We **do not** apply the legacy "narrator female → first character male" override — that rule, applied across daily long-story output, would cast a male voice in ~80% of stories and create male-voice monoculture against the diversity-pipeline's intended `~40/40/20` gender split.

Routing rule:
- The orchestrator (`generate_long_story_episode.py`) already samples character gender per story from the diversity scheduler. Voice routing **respects** that sampling, not overrides it.
- For each character, pick a voice matching the sampled gender that is not already in use by the narrator, whisper, or another character in this story.
- Male pool: `ranbir` → `harshit` → `ishan` (priority order).
- Female pool: any of the 5 narrator voices not currently assigned (`tripti, monika, tara, simran, rhea`). `zara` is **excluded** from character casting — she's reserved for the angry-narrator + whisper roles to keep that voice unique.
- `maya` is **retired** as of 2026-04-27 (voice didn't land in user testing); the voice ID stays in the library for reference but is unused.
- `WHISPER_VOICE = "zara"` regardless of cast.

The `voice_map` is persisted in `metadata.json` exactly as today.

## 6. TTS parameters — V2 short stories

`similarity_boost = 0.75` for all V2 calls.

**Tuning history.** Initial values (stability 0.55–0.85, style 0.00) were copied from the Hindi spec and sounded flat — high stability + zero style puts the model in "consistent narration" mode with no emotional range. Hindi works at those values because Hindi rhythm and Tripti's voice carry warmth innately; English voices need explicit `style` to be expressive. Updated 2026-04-27 to lower stability and add moderate style across phases.

| Phase | stability | style | speed | Why |
|-------|-----------|-------|-------|-----|
| 1 (engaged) | 0.45 | 0.30 | 0.92 | Lower stability for emotional range; moderate style for warmth |
| 2 (settling) | 0.55 | 0.20 | 0.85 | Settling but still warm |
| 3 (sleep) | 0.65 | 0.10 | 0.78 | Calmer but not robotic |
| `[PHRASE]` block | 0.70 | 0.15 | 0.75 | Slow, intimate, warm |
| `[PAUSE: ms]` | inline `<break>` if `<2000ms`, else silence insert (see §8.3) |

## 7. TTS parameters — long stories

`similarity_boost = 0.75` for all calls. Long stories need MORE emotional range than V2 shorts because they have a 15–25-minute arc — voice should traverse engagement → easing → settling → dissolution. Initial values had style 0.00 across all phases, flattening the arc the text already has. Tuned 2026-04-27 (round 2): stability rises across phases, style descends, speed slows. Whisper is the **only** place style 0.00 is correct.

| Section | stability | style | speed | Why |
|---------|-----------|-------|-------|-----|
| intro | 0.45 | 0.35 | 0.92 | Opening hook needs warmth — the "narrator pulls you in" moment |
| phase_1 | 0.50 | 0.30 | 0.88 | Active discovery, dialogue-heavy; voice should be alive |
| phrase | 0.60 | 0.20 | 0.75 | Slow, intimate, warm — emotional anchor |
| song_transition | 0.55 | 0.25 | 0.82 | Bridging into the song; slightly softer than phase_1 |
| post_song | 0.60 | 0.20 | 0.78 | Returning softer after the song |
| phase_2 | 0.65 | 0.15 | 0.78 | Settling, sensation over plot |
| phase_3 | 0.75 | 0.10 | 0.72 | Dissolution, fragments; style 0.10 keeps trace warmth |
| whisper | 0.85 | 0.00 | 0.70 | Final 3–4 lines; only place style 0.00 is right |
| breathing | 0.70 | 0.10 | 0.72 | Slow steady delivery, calmer than narrator default |
| breathe_guide | 0.75 | 0.05 | 0.70 | Instructional, very slow, almost meditative |

**Speed floor 0.70**: ElevenLabs API rejects `speed < 0.70` with HTTP 400 (`invalid_voice_settings`). Originally tuned to 0.65–0.68 for whisper/breathe_guide; raised 2026-04-27 after the API rejection. Clamps in `chatterbox_to_elevenlabs()`, `tts_eleven_raw()`, and `apply_modifier()` all enforce `[0.70, 1.20]`.

### 7.1 Modifier floor clamp

Character voice-style modifiers (§7.2) stack offsets on top of the section base. To prevent the "speaking too fast and randomly" failure mode when (e.g.) a `nervous` modifier (`stability_offset: -0.08`) lands on top of an already-low phase_1 base, `apply_modifier()` clamps to:

- `stability ∈ [0.40, 1.0]` — raised from 0.0 floor 2026-04-27
- `style ∈ [0, 1]`
- `speed ∈ [0.65, 1.20]`

ElevenLabs docs warn that stability < 0.30 risks overly random performances; 0.40 keeps the voice grounded while still allowing emotional range.

### 7.2 Phase 3 staged voice transition

Original design: at the `[PHASE_3]` boundary, switch the narrator from the mood voice to `zara` (whisper voice) for the rest of the section. Listeners hear a hard voice change at the phase boundary — "wait, this is a different person now." The discontinuity announces itself rather than burying inside the dissolution arc.

Updated 2026-04-27: stage the transition across Phase 3 in three sub-stages, computed by position among Phase-3 narration segments:

| Sub-stage | Range | Voice | Section params |
|-----------|-------|-------|----------------|
| early | first 25% | mood narrator | `phase_2` |
| middle | middle 50% | mood narrator | `phase_3` |
| late | final 25% | `zara` | `whisper` |

The voice change happens deep inside dissolution where the listener is already drifting, masking the transition. For the **angry** mood (where narrator is already `zara`), this stages params only — no voice switch since narrator and whisper are the same voice. `[WHISPER]` blocks always force `zara` regardless of position.

Implemented in `generate_section_tts()` via a per-segment override map computed before the rendering loop.

### 7.1 Character voice-style modifiers

Per-character offsets applied on top of the section base (translated from `CHARACTER_VOICE_MODIFIERS` in `scripts/generate_long_story_episode.py:506`). After applying offsets, all values clamp to: `stability ∈ [0,1]`, `style ∈ [0,1]`, **`speed ∈ [0.65, 1.2]`**.

**Why 0.65, not 0.70:** the `whisper` section base is `speed: 0.68`, below the original 0.70 floor. A `whisper` line on a `quiet`-modifier character (offset −0.04) would target 0.64 and silently clamp up to 0.70, losing the slow-whisper effect. Floor of 0.65 preserves the spec'd whisper pace; ElevenLabs accepts down to 0.7 in some plan tiers, so values <0.7 will be capped by the API itself if the plan doesn't support them.

| Style | speed_offset | style_offset | stability_offset |
|-------|--------------|--------------|-------------------|
| confident | +0.03 | +0.05 | −0.05 |
| gentle | −0.03 | +0.03 | 0.00 |
| small | +0.05 | +0.05 | −0.05 |
| wise | −0.05 | −0.03 | +0.05 |
| nervous | +0.04 | +0.08 | −0.08 |
| curious | +0.02 | +0.05 | −0.03 |
| stubborn | −0.02 | +0.05 | −0.05 |
| dreamy | −0.06 | −0.02 | +0.05 |
| brave | +0.01 | +0.04 | −0.02 |
| quiet | −0.04 | −0.05 | +0.10 |
| playful | +0.04 | +0.05 | −0.05 |
| careful | −0.03 | −0.03 | +0.05 |
| sleepy | −0.08 | −0.05 | +0.10 |

## 8. Tag handling (unchanged)

The existing tag set is parsed pre-TTS exactly as today. ElevenLabs receives only narration text + voice/params per segment.

| Tag | Behavior |
|-----|----------|
| `[INTRO]`, `[PHASE_1/2/3]`, `[POST_SONG]` | Section boundary; selects the section's TTS params. |
| `[PHRASE]...[/PHRASE]` | Renders with `phrase` params; mood narrator voice. |
| `[WHISPER]...[/WHISPER]` | Renders with `whisper` params; voice forced to `zara`. |
| `[BREATHE]`, `[BREATHE_GUIDE]` | Renders with respective params; mood narrator voice. |
| `[PAUSE: ms]` | Silence insert in audio assembly; no TTS call. |
| `[MUSIC]` | Replaced with 6 s music swell in audio assembly; no TTS call. |
| `[CHARACTER: name, traits, voice_style]` | Metadata only — drives `CHAR_VOICE` and modifier selection. |
| `NAME: "dialogue"` | Switches to character voice for that line. |
| `[SONG_SEED: ...]` | Metadata only — drives MiniMax song generation. |

### 8.1 Phase 3 short-line batching

`_batch_short_lines()` is preserved. ElevenLabs handles 1–3 word inputs cleanly (so the original Chatterbox crash-avoidance reason is gone), but batching produces more natural prosody than 80 micro-segments stitched with silence. Behavior unchanged.

### 8.2 Inline `<break>` tags for short pauses (per ElevenLabs SSML)

Originally all `[PAUSE: ms]` tags were rendered as discrete silence inserts at segment boundaries — each sentence around a pause became its own TTS call, and ElevenLabs got no signal that a pause was coming, so the sentence ended cold without a trailing breath.

Updated 2026-04-27 (per ElevenLabs SSML guidance):

- `[PAUSE: ms]` with **ms < 2000** → converted to inline `<break time="<s>s"/>` SSML inside the TTS chunk. The model renders natural breath rhythm around the pause (trailing breath before, soft pickup after).
- `[PAUSE: ms]` with **ms ≥ 2000** → stays as a discrete silence insert at the segment boundary (ElevenLabs caps inline breaks at 3 seconds and warns about prosody artifacts above 3 break tags per chunk).

Implemented in `_elevenlabs_common.convert_short_pauses_to_breaks()` and applied in `audio_assembly.parse_segments()` only when `TTS_ENGINE_EN=elevenlabs`. The Chatterbox path is unchanged.

### 8.3 Context passing for long-story tonal continuity

Long stories produce 30–50 TTS chunks. Without context hints, every chunk starts emotionally fresh — the voice resets state at every segment boundary, flattening the multi-phase arc the text encodes. Updated 2026-04-27: every long-story TTS call passes:

- `previous_text`: last ~300 chars of the preceding text-bearing segment
- `next_text`: first ~200 chars of the following text-bearing segment

ElevenLabs uses these for tonal continuity — the chunk knows what came before and what's coming, so prosody flows naturally across phase transitions, dialogue boundaries, and music swells. Pauses, breathes, and music segments are **skipped** when computing context (we only look back/forward to the nearest text-bearing segment).

V2 short stories also accept these params via `tts_eleven_compat()` but the V2 caller doesn't currently set them — V2 chunks are short enough that a fresh emotional state per chunk doesn't audibly hurt.

### 8.4 Long-input defensive check

ElevenLabs Multilingual v2 prosody soft-degrades on inputs longer than ~2000 characters per call (less expressive, more monotone, occasional mispronunciations of less common words). Long stories segmented properly (one `[PHASE_1]` chunk = ~3–4 calls) won't hit this, but a defensive guard catches edge cases (a weird story producing one long settling block, an over-eager `_batch_short_lines()` flush):

```python
SOFT_LIMIT = 2000
if len(text) > SOFT_LIMIT:
    log.warning("TTS chunk %d chars exceeds soft limit; splitting at sentence boundary", len(text))
    chunks = _split_at_sentence_boundary(text, SOFT_LIMIT)
    return b"".join(elevenlabs_tts(c, ...) for c in chunks)
```

`_split_at_sentence_boundary` is a small helper (split on `.!?` then re-balance to chunks ≤ SOFT_LIMIT). Logged warnings flag any story repeatedly hitting the limit so we can investigate the upstream segmenter.

## 9. Output format & post-processing

ElevenLabs `output_format=pcm_24000` returns raw 24 kHz PCM, which we wrap into WAV and feed into the unchanged post-processing pipeline (loudness normalization, MP3 encode). Audio file paths, naming, and metadata schemas are unchanged.

## 10. Configuration & env

- `ELEVENLABS_API_KEY` — already in `dreamweaver-backend/.env` for Hindi. Reused for English.
- `ELEVENLABS_MODEL` — `eleven_multilingual_v2` (already used by Hindi).
- No new dependencies (Hindi pipeline already uses `requests` for HTTP calls; no SDK).

## 11. Phased rollout

1. **Day 0 (this PR):** Implement `_elevenlabs_common.py`, swap V2 short-story call site, deploy to test environment.
2. **Day 1–3 — V2 validation:**
   - Generate 5–10 V2 shorts via the new path.
   - Listen to all 6 moods end-to-end.
   - **Specifically validate Phase 3 zara takeover for each mood**, especially `angry` and `anxious`. The concern: zara's whisper-meditative voice may feel jarringly disconnected when closing a story whose Phase 1 was deep/grounded (angry → monika → zara) or warm (anxious → maya → zara). If any mood feels wrong, the fallback is **mood-narrator continuation into Phase 3 with whisper params** (i.e., monika narrates Phase 3 of an angry story with `whisper` TTS settings instead of switching voice). This is a flip of one boolean per mood in `_elevenlabs_common.py`.
   - Verify `pcm_24000` (or fallback format) drops cleanly into audio assembly without code changes.
3. **Day 4 — long-story validation:** swap long-story call site, generate one long story per mood (6 total). Validate multi-voice character casting, Phase-3 voice switch experience, long-input prosody on the longest section.
4. **Day 5 — cron cutover:** before flipping production, **explicitly test the env-flag plumbing** on the actual cron environment:
   - SSH to the cron host, manually run `pipeline_run.py` once with `TTS_ENGINE_EN=elevenlabs` and once with `TTS_ENGINE_EN=chatterbox`. Confirm each routes correctly. Don't assume cron inherits the right env.
5. **Day 5+:** Cut over the daily pipeline to ElevenLabs for English. Leave the Modal Chatterbox-EN endpoint warm for one week as fallback, then deprecate.

Rollback: a single env flag `TTS_ENGINE_EN=chatterbox|elevenlabs` (default `elevenlabs` after cutover) routes back to the Modal endpoint if needed.

## 12. Cost

- V2 short story: ~5–8 k chars × 1 variant = ~6 k chars/story.
- Long story: ~50 k chars/story (single voice variant; multi-voice changes routing, not total chars).
- User has an ElevenLabs subscription that covers expected daily volume; no new billing concern.

## 13. Out-of-scope cleanup (flagged, not done here)

- Hindi voice library and `elevenlabs_tts` helper are duplicated across `publish_hindi_*.py` files. Worth consolidating into `_elevenlabs_common.py` later, but doing so in this PR expands blast radius unnecessarily.
- The retired Chatterbox-EN Modal endpoint and its voice-reference WAVs in `chatterbox-data` volume can be deleted ~2 weeks after cutover.

## 14. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| ElevenLabs prosody on long inputs degrades vs. Hindi (different language model behavior) | Phased rollout — validate V2 first before committing long-story migration |
| Voice ID for "Tripti" English ≠ "Tripti" Hindi causes confusion | Library uses prefix-free labels and is documented as English-only; Hindi keeps separate dict |
| ElevenLabs API rate limit during pipeline burst (e.g., 50-segment long story) | Existing Hindi long-story already handles this with sequential calls + retry; reuse the pattern |
| Output sample-rate mismatch breaks audio assembly | Request `pcm_24000` explicitly; assembly already standardizes to 24 kHz / mono |
| User dislikes a mood→narrator pairing after launch | Single config table change in `_elevenlabs_common.py`; no code change needed |

## 15. Open items before implementation

1. Populate the 10 voice IDs in `ELEVENLABS_VOICES_EN` from the user's ElevenLabs dashboard.
2. **Verify ElevenLabs plan tier supports `pcm_24000`.** If not, fall back per §3.3 (pcm_22050 with upsample, or mp3_44100_128). Inspect Hindi pipeline output format — likely already answered there.
3. **Verify cron env-flag plumbing** on Day 5 per §11 step 4: actual run with `TTS_ENGINE_EN` set both ways before flipping production. Don't assume; verify on the cron host.
