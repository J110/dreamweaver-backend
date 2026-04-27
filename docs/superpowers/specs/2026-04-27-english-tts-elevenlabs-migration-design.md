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
| wired | tara | Conversational and Expressive | Channels the wound-up energy without amplifying it; expressive cadence carries the Phase-1 momentum and naturally softens through the descent |
| curious | simran | Cheerful Best Friend | Wonder reads better in a bright, friendly voice than a deep one; matches the discovery arc |
| calm | tripti | Calm and Experienced | The steady anchor — mature, unrushed, the baseline a calm story should sit on |
| sad | rhea | Soft, Polished and Calm | Tender and soft, doesn't push or perform sympathy; sits beside the feeling rather than fixing it. Distinct from tripti (mature/anchored) — rhea is delicate, tripti is steady |
| anxious | maya | Friendly and Cheerful | Anxious children need **warmth**, not gravity. A reassuring, approachable voice defuses anxiety better than a deep one |
| angry | monika | Deep and Natural | **Grounding, not energy-mirror.** A deep, settled voice meets anger by not matching it; depth is the counter-weight that pulls the child down toward sleep |

### 5.2 Long stories — three-layer voice system (preserved)

**Layer 1 — Mood narrator** (same as V2 table above).

**Layer 2 — Phase 3 ASMR takeover.** For all moods, **`zara`** narrates `[PHASE_3]` and any `[WHISPER]` blocks, replacing the mood narrator for those sections. (Hindi pipeline does the same with `roohi`.)

**Layer 3 — Character casting.** Per-story `CHAR_VOICE` dict assigns voices to dialogue characters. We **do not** apply the legacy "narrator female → first character male" override — that rule, applied across daily long-story output, would cast a male voice in ~80% of stories and create male-voice monoculture against the diversity-pipeline's intended `~40/40/20` gender split.

Routing rule:
- The orchestrator (`generate_long_story_episode.py`) already samples character gender per story from the diversity scheduler. Voice routing **respects** that sampling, not overrides it.
- For each character, pick a voice matching the sampled gender that is not already in use by the narrator, whisper, or another character in this story.
- Male pool: `ranbir` → `harshit` → `ishan` (priority order).
- Female pool: any of the 6 mood narrators not currently assigned, plus rotation across the unused mood narrators for variety across stories.
- `WHISPER_VOICE = "zara"` regardless of cast.

The `voice_map` is persisted in `metadata.json` exactly as today.

## 6. TTS parameters — V2 short stories

Translated from `generate_audio.py` Chatterbox phase profiles. `similarity_boost = 0.75` for all V2 calls.

| Phase | stability | style | speed |
|-------|-----------|-------|-------|
| 1 (engaged) | 0.55 | 0.05 | 0.90 |
| 2 (settling) | 0.70 | 0.00 | 0.82 |
| 3 (sleep) | 0.85 | 0.00 | 0.78 |
| `[PHRASE]` block | 0.85 | 0.00 | 0.78 |
| `[PAUSE: ms]` | n/a — handled by audio assembly (silence insert) |

## 7. TTS parameters — long stories

Translated from `LONG_STORY_TTS` in `scripts/generate_long_story_episode.py:522`. `similarity_boost = 0.75` for all calls.

| Section | stability | style | speed |
|---------|-----------|-------|-------|
| intro | 0.60 | 0.05 | 0.90 |
| phase_1 | 0.70 | 0.00 | 0.85 |
| phrase | 0.85 | 0.05 | 0.78 |
| song_transition | 0.72 | 0.00 | 0.80 |
| post_song | 0.75 | 0.00 | 0.78 |
| phase_2 | 0.78 | 0.00 | 0.78 |
| phase_3 | 0.85 | 0.00 | 0.72 |
| whisper | 0.95 | 0.00 | 0.68 |
| breathing | 0.78 | 0.00 | 0.75 |
| breathe_guide | 0.82 | 0.00 | 0.70 |

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

### 8.2 Long-input defensive check

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
