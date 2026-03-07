# Lullaby Generation Guidelines

Evidence-based lullaby generation via ACE-Step prompt engineering.
Two age tiers with distinct parameters. No background music for lullabies — ACE-Step output includes vocals + instrument.

## 1. Age Tiers

### Ages 0-1: Pure Physiological Entrainment

| Parameter | Value |
|-----------|-------|
| Tempo | 58-66 BPM (target: 62) |
| Meter | 6/8 exclusively |
| Melody | Pentatonic, max range a fifth, stepwise only |
| Harmony | None or tonic drone |
| Instrumentation | Solo voice only (a cappella). No instruments. |
| Vocal style | Extremely soft, breathy, humming. Female preferred. |
| Lyrics | Nonsense syllables: "shh", "la la", "mmm", "ooh" |
| Duration | 2-3 minutes |
| Dynamics | Pianissimo only (pp). No variation. |
| ACE-Step mode | `"vocal"` (a cappella) |
| Variants | 2 (female + male) |

### Ages 2-5: Entrainment + Ritual + Emerging Narrative

| Parameter | Value |
|-----------|-------|
| Tempo | 60-72 BPM (target: 66) |
| Meter | 6/8 (preferred) or 3/4 |
| Melody | Pentatonic or simple major, up to one octave, predominantly stepwise |
| Harmony | I-IV-V chords only, simple progressions |
| Instrumentation | Voice + ONE soft instrument (harp, guitar, piano, cello, or flute) |
| Vocal style | Warm, intimate, breathy. Not projected. |
| Lyrics | Simple sleep/safety/warmth imagery (see Section 3) |
| Duration | 3-4 minutes |
| Dynamics | Pianissimo to mezzo-piano (pp-mp). No crescendos. |
| ACE-Step mode | `"full"` (with instrument) |
| Variants | 2 randomly chosen from 5 styles (Harp, Guitar, Piano, Cello, Flute) |

### Ages 6+: No Lullabies

Lullabies are not generated for ages 6-8 or 9-12. At this age, stories and poems with ambient background music are more appropriate.

**Enforcement (3 layers):**
1. `generate_content_matrix.py` — `build_fresh_plan()` restricts songs to age groups 0-1 and 2-5 only
2. `generate_audio.py` — `get_lullaby_config()` returns None for age_min >= 6, skipping audio generation
3. `pipeline_run.py` — post-generation validator auto-corrects any song with age_min >= 6 back to 2-5

## 2. ACE-Step Tag Templates (Ages 2-5)

### Variant A: Voice + Harp
```
solo {gender} vocal lullaby with solo harp,
extremely soft breathy intimate singing,
66 BPM, 6/8 time signature, pentatonic major,
pianissimo, legato, sparse arrangement,
gentle rocking rhythm, warm tone,
traditional cradle song, folk lullaby,
no drums, no bass, no percussion, no synth,
no electric instruments, no full arrangement,
extremely repetitive, simple melody,
narrow vocal range, descending phrases
```

### Variant B: Voice + Acoustic Guitar
```
solo {gender} vocal lullaby with fingerpicked acoustic guitar,
extremely soft breathy intimate singing,
64 BPM, 3/4 time signature, major key,
pianissimo, legato, sparse,
gentle waltz rhythm, warm folk,
traditional lullaby, cradle song,
no drums, no bass, no percussion, no synth,
no electric instruments, no strumming,
extremely repetitive simple melody,
one guitar only, minimal accompaniment
```

### Variant C: Voice + Piano
```
solo gentle vocal lullaby with soft piano,
extremely soft breathy {gender} singing, intimate,
62 BPM, 6/8 time signature, pentatonic,
pianissimo, legato, sparse,
gentle rocking rhythm, classical lullaby,
berceuse, cradle song,
no drums, no bass, no percussion, no synth,
no full arrangement, no orchestral,
extremely repetitive, simple melody,
soft piano arpeggios only, minimal chords
```

### Variant D: Voice + Cello
```
solo {gender} vocal lullaby with solo cello,
extremely soft breathy intimate singing,
62 BPM, 6/8 time signature, minor pentatonic,
pianissimo, legato, sparse,
gentle rocking rhythm, warm rich tone,
classical lullaby, berceuse,
no drums, no bass, no percussion, no synth,
no piano, no guitar, no full arrangement,
extremely repetitive, simple melody,
cello sustains and drones only
```

### Variant E: Voice + Flute
```
solo {gender} vocal lullaby with solo wooden flute,
extremely soft breathy singing, intimate whisper,
64 BPM, 3/4 time signature, pentatonic,
pianissimo, legato, sparse, airy,
gentle folk lullaby, pastoral,
no drums, no bass, no percussion, no synth,
no electric instruments, no full arrangement,
extremely repetitive, simple melody,
flute and voice only, nothing else
```

### Infant Template (Ages 0-1): A Cappella
```
solo {gender} vocal lullaby, a cappella, no instruments,
extremely soft breathy intimate whisper singing,
62 BPM, 6/8 time signature, pentatonic,
pianissimo, legato, minimal, sparse,
humming, gentle rocking rhythm,
no drums, no bass, no percussion, no synth,
no guitar, no piano, no strings section,
no reverb tail, no delay effects,
nursery, cradle song, ancient lullaby,
extremely repetitive, simple melody
```

## 3. Lyric Rules

### Ages 2-5: Structured Lyrics

**Structure**: Verse 1, Chorus, Verse 2, Chorus, Verse 3, Chorus
- Each verse: 4 lines, 6-10 words per line
- Each chorus: 3-4 lines, 4-8 words per line
- Total: 20-26 lyric lines
- Choruses MUST be IDENTICAL (copy-paste)
- End with humming: "Mmm mmm mmm..."

**Themes** (sleep-inducing only):
- Sleep cues: close your eyes, time to rest, drifting off
- Safety: I'm here, you're safe, I'll watch over you
- Nature night: stars are sleeping, moon is watching
- Warmth: cozy, snuggle, warm blanket, gentle night
- AVOID: adventure, action, excitement, questions, counting

**Words**: Common English, soft consonants, open vowels. Character names max 2 syllables. No enjambment.

### Ages 0-1: Nonsense Syllables

No real lyrics. Use only: "Shh la la", "Loo loo loo", "Mmm mmm mmm", "Ooh ooh ooh", "Na na na".

## 4. Section Markers (Bare Tags Only)

**CRITICAL**: ACE-Step section markers MUST use bare tags only. Do NOT add performance directions after the tag name — ACE-Step reads everything inside `[...]` as lyrics text and will narrate/sing the directions.

```
[verse]
[chorus]
[verse]
[chorus]
[verse]
[chorus]
[outro]
```

**Wrong** (ACE-Step sings "whispered extremely soft breathy slow"):
```
[verse - whispered, extremely soft, breathy, slow]
```

**Right** (style controlled by LULLABY_STYLES description field):
```
[verse]
```

All vocal style control (tempo, breathiness, dynamics, instrumentation) is handled by the `description` field in `LULLABY_STYLES` which is passed as ACE-Step tags, NOT by section markers.

## 5. Post-Processing Pipeline

All generated lullabies pass through:

1. **LUFS normalization**: -24 LUFS (research-based bedtime loudness). Falls back to -20 dBFS if pyloudnorm unavailable.
2. **Extended fade-out**: Begins at 80% of track duration. Two-stage: gentle fade 80%-95%, steep fade 95%-100%. 5 seconds of silence appended.
3. **2 retakes**: Each variant generates 2 seeds. Best selected by duration accuracy + volume consistency.

## 6. No Background Music for Lullabies

Lullabies (`type: "song"`) do NOT get ambient background music (`musicParams`). The ACE-Step output already includes both vocals and instrumentation. Adding synthesized ambient music would:
- Over-instrument the output (violating the "solo voice + one instrument" principle)
- Interfere with the carefully controlled BPM and dynamics
- Add unpredictable harmonic content

Stories and poems continue to use `musicParams` for ambient background music.

## 7. Known Failure Patterns

| Pattern | Result | Fix |
|---------|--------|-----|
| Lines >15 words | Skipped entirely | Break into shorter lines |
| >6 sections in 120s | Compression/skipping | Limit to V-C-V-C-V-C |
| Non-repeating choruses | Model confusion, drift | Copy-paste identical text |
| Emotion markers in lyrics | Read as lyrics | Strip before ACE-Step |
| **Directions in section markers** | **Narrated as lyrics** ("whisper extremely slow") | **Use bare `[verse]`/`[chorus]` only** — see Section 4 |
| Complex rhyme (ABCABC) | Melodic drift | Use AABB or ABAB |
| Names >2 syllables | Garbled/skipped | Simplify names |
| QA fidelity using wrong field | Whisper check silently skipped | Use `story["text"]` not `story["content"]` |

## 8. ACE-Step Parameter Reference

| Parameter | Value | Notes |
|-----------|-------|-------|
| `guidance_scale` | 18 | Strong overall guidance |
| `guidance_scale_lyric` | 4.5 | Lyric adherence (range 4.0-5.5) |
| `guidance_interval` | 0.7 | 70% of inference steps |
| `infer_step` | 60 | Inference steps |
| `duration` | 240 (2-5) / 180 (0-1) | Seconds |

## 9. Quality Checks (Lullaby Test)

Every generated lullaby should pass:

| Check | Pass Criteria |
|-------|--------------|
| Tempo | 55-75 BPM throughout. Fail if any section >80 BPM. |
| Instruments | Voice + 0 or 1 instrument. Fail if drums/bass/synth present. |
| Dynamics | No sudden loud moments. Fail if volume adjustment needed. |
| Groove | Should make you want to sway, not tap. Fail if rhythmic/groovy. |
| Sparsity | Moments of near-silence between phrases. Fail if continuous. |

Expected yield with optimized prompts: 15-25% pass rate. Generate 2 retakes per variant and select best.

## 10. Automated Lullaby QA (Phase L)

Lullaby QA is separate from story/poem QA. Stories use Voxtral transcription fidelity. Lullabies use local audio analysis + Whisper-based lyrics fidelity (no API calls, all local, free).

### 10.1 Audio Quality Scoring (6 dimensions)

During generation, 2 retakes are scored on 6 dimensions:

| Dimension | What It Measures | Good Score |
|-----------|-----------------|------------|
| `duration_accuracy` | How close to target duration (240s/180s) | > 0.7 |
| `volume_consistency` | dBFS variance across 10 chunks | > 0.7 |
| `loudness` | Average dBFS near target (-22 dBFS) | > 0.6 |
| `sparsity` | Quiet gaps between phrases (10-40% quiet) | > 0.5 |
| `spectral_softness` | Energy above 4kHz < 20% (not harsh/bright) | > 0.7 |
| `no_peaks` | No sudden 6dB+ volume spikes | 1.0 |

### 10.2 Lyrics Fidelity (3-gate Whisper-based)

Uses faster-whisper (local, CPU, "small" model, int8) to transcribe lullaby audio and check lyrics integrity. Three content types are classified by real-word ratio in original lyrics:

| Type | Real-word Ratio | Ages | Example |
|------|----------------|------|---------|
| **L** (Lyrical) | > 60% | 2-5 | "Close your eyes and dream of stars" |
| **N** (Nonsense) | < 20% | 0-1 | "Shh la la, mmm, loo loo" |
| **M** (Mixed) | 20-60% | Any | Mix of real words + vocables |

**Gate 1 — Content Fidelity:**
- Type L: Word overlap between original lyrics and transcript >= 75%
- Type N: Real-word ratio in transcript <= 30% (nonsense purity)
- Type M: Both overlap AND unexpected word ratio <= 25%

**Gate 2 — Purpose-Specific Words:**
- Type L: >= 80% of sleep-cue words (sleep, dream, eyes, night, etc.) detected in transcript
- Type N: Zero high-severity phantom words (blocklist words hallucinated from nonsense)
- Type M: Both checks combined

**Gate 3 — Safety Blocklist (zero tolerance):**
- Scans transcript against `data/blocklist.txt` (~170 words across profanity, violence, fear, sexual, substances, sleep-inappropriate)
- Any match = REJECT regardless of other gates

Fidelity verdicts: PASS / WARN / REJECT. Fidelity score (0-1) used for retake comparison.

### 10.3 Retake Selection

Combined score: 60% audio quality + 40% fidelity (lower=better). Fidelity REJECT adds +10 penalty (never selected). Best candidate kept.

### 10.4 Pipeline QA (Phase L in qa_audio.py)

Runs both audio analysis AND fidelity checking on saved files. Verdict rules:
- Fidelity REJECT → FAIL (override)
- 0 warnings → PASS
- 1-2 warnings → WARN
- 3+ warnings → FAIL

### 10.5 Data Files

| File | Purpose |
|------|---------|
| `data/blocklist.txt` | ~170 safety words (Gate 3) |
| `data/english_common.txt` | ~3300 common English words (Type N detection) |
| `scripts/lullaby_fidelity.py` | Core 3-gate fidelity module |

### 10.6 QA Flow Comparison

| Aspect | Stories/Poems | Lullabies (Songs) |
|--------|--------------|-------------------|
| Phase 1 | Duration anomaly | Duration anomaly |
| Phase 2 | Voxtral transcription + fidelity | N/A (singing distorts TTS QA) |
| Phase L | N/A | Audio analysis (6 dims) + fidelity (3 gates) |
| Phase 3 | Voxtral quality scoring (optional) | N/A |
| Retakes | N/A | 2 retakes, combined QA selection |
| Dependencies | Mistral API (paid) | faster-whisper, scipy, numpy (local, free) |
| API Cost | ~$0.01-0.02 per file | $0 (all local) |
