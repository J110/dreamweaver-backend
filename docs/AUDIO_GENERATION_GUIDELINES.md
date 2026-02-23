# Dream Valley — Audio Generation Guidelines (Chatterbox TTS)

> **Purpose**: Ensure consistent, high-quality audio narration for all Dream Valley content using Chatterbox TTS on GPU. Follow these guidelines for every batch generation, regeneration, or single-story audio run.

---

## 1. Architecture Overview

### Pipeline

```
content.json (annotated text)
  → parse_annotated_text()     # Split by \n\n paragraphs, then by emotion markers
  → split_into_chunks()        # Sub-chunk any segment > 300 chars
  → generate_tts_for_segment() # One Chatterbox API call per chunk
  → concatenate + post-process # Combine, normalize, fade, export MP3
  → qa_audio.py                # Voxtral-based transcription QA
```

### Infrastructure

| Component | Details |
|-----------|---------|
| **TTS Engine** | Chatterbox (Resemble AI), running on Modal GPU |
| **GPU** | NVIDIA A10G or A100 via Modal (8–16 GB VRAM for inference) |
| **Native Sample Rate** | 24 kHz (do NOT upsample — adds interpolation artifacts) |
| **Output Format** | 256 kbps MP3 at native 24 kHz |
| **Voice References** | Pre-recorded human WAV files (24 kHz, mono) |
| **Endpoint** | `https://anmol-71634--dreamweaver-chatterbox-tts.modal.run` |

---

## 2. Speed — Always 0.8x for Bedtime

All audio MUST be generated at **0.8x speed** (80% of normal pace). This creates the slow, soothing cadence appropriate for bedtime listening.

```bash
# ALWAYS pass --speed 0.8
python3 scripts/generate_audio.py --speed 0.8

# NEVER use default speed (1.0) for production content
```

The `speed` parameter is passed directly to the Chatterbox endpoint. Values below 0.7 may introduce audio artifacts; values above 1.0 are too fast for bedtime content.

| Speed | Use Case | Quality |
|-------|----------|---------|
| 0.7 | Too slow — artifacts possible | Avoid |
| **0.8** | **Bedtime standard** | **Always use this** |
| 0.9 | Slightly relaxed | Acceptable for action scenes |
| 1.0 | Normal speech | Too fast for bedtime |

---

## 3. Text Chunking — Critical for Quality

### Why Chunking Matters

Chatterbox has a **~40-second generation limit per call**. Text that is too long for a single call causes:
- **Hallucination**: Model generates entirely different text than input
- **Skipping**: Model drops sentences or paragraphs mid-generation
- **Quality degradation**: Audio becomes garbled, robotic, or incoherent after ~30 seconds

### Chunk Size Limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| **Hard maximum** | 300 characters per chunk | Chatterbox recommended limit |
| **Ideal range** | 100–250 characters | Best quality sweet spot |
| **Minimum** | 20 characters | Below this, short-text hallucination risk |
| **Absolute minimum** | 10 characters | Pad with filler if shorter (see Section 3.3) |

### 3.1 Two-Level Splitting Strategy

**Level 1 — Paragraph splitting** (already in `generate_audio.py`):
- Split text at `\n\n` (double newline) boundaries
- Each paragraph becomes a separate processing unit
- 1000 ms silence inserted between paragraphs

**Level 2 — Sub-chunk splitting** (MUST be added for long paragraphs):
- Any speech segment exceeding 300 characters MUST be sub-chunked
- Split at sentence boundaries first (`. `, `! `, `? `)
- For Hindi: split at danda (`।`), question mark (`?`), exclamation (`!`)
- Fallback: split at comma (`,`) if a single sentence exceeds 300 chars
- Last resort: split at word boundaries at the 300-char mark

```python
def split_into_chunks(text: str, max_chars: int = 300) -> list[str]:
    """Split text at sentence boundaries, keeping chunks <= max_chars."""
    # Hindi sentence endings: danda (।), purna viram (.), ?, !
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current.strip())
            # If a single sentence exceeds max_chars, split at commas
            if len(sentence) > max_chars:
                sub_parts = sentence.split(",")
                sub_current = ""
                for part in sub_parts:
                    if len(sub_current) + len(part) + 2 <= max_chars:
                        sub_current += (", " if sub_current else "") + part.strip()
                    else:
                        if sub_current:
                            chunks.append(sub_current.strip())
                        sub_current = part.strip()
                current = sub_current
            else:
                current = sentence

    if current:
        chunks.append(current.strip())

    return chunks or [text]
```

### 3.2 Where to Apply Chunking

Chunking MUST happen **after** emotion marker parsing and **before** the TTS API call:

```
Paragraph text
  → parse_annotated_text()     # Extract emotion markers → speech segments
  → For each speech segment:
      → If len(segment.text) > 300:
          → split_into_chunks(segment.text, max_chars=300)
          → Generate TTS for each sub-chunk (same emotion params)
          → Concatenate sub-chunk audio (no gap between sub-chunks)
      → Else:
          → Generate TTS normally (single call)
```

**Important**: Sub-chunks within the same emotion segment should be joined with **zero silence** (direct concatenation). Pauses only go between paragraphs (1000 ms) and at explicit `[PAUSE]` / `[DRAMATIC_PAUSE]` markers.

### 3.3 Short Text Padding

Text shorter than ~20 characters can cause Chatterbox to hallucinate or produce garbled output. For very short segments:

```python
# Pad short text to avoid hallucination
if len(text.strip()) < 20:
    # Add trailing period and space to stabilize generation
    text = text.strip() + ". "
```

**Known short-text issues**:
- Single words may be repeated or garbled
- Very short phrases (<10 chars) may produce silence or noise
- Onomatopoeia ("Shh", "Hush") should be extended: "Shh, shh, shh..."

---

## 4. Voice References

### Requirements for Voice Reference Files

| Property | Requirement |
|----------|-------------|
| **Format** | WAV (lossless) — never use MP3 as reference |
| **Sample rate** | 24 kHz (match Chatterbox native rate) |
| **Channels** | Mono |
| **Duration** | 10–20 seconds optimal (longer is fine, shorter hurts quality) |
| **Content** | Clear speech, minimal background noise |
| **Quality** | Clean recording, no compression artifacts |

### Current Voice Lineup

**English (7 voices)**:
| Voice ID | Gender | Character |
|----------|--------|-----------|
| `female_1` | Female | Warm, maternal |
| `female_2` | Female | Young, gentle |
| `female_3` | Female | Soft, soothing |
| `male_1` | Male | Deep, calming |
| `male_2` | Male | Warm, friendly |
| `male_3` | Male | Gentle, storyteller |
| `asmr` | Neutral | Ultra-soft whisper |

**Hindi (7 voices)** — `_hi` suffix variants with Hindi-specific recordings.

### Voice Reference Best Practices

- Record references in a **quiet environment** (background noise transfers to output)
- Use **consistent recording equipment** across all reference files
- Reference should contain **natural speech** (not reading robotically)
- Avoid references with **strong emotion** — the emotion params control that
- Re-record references if quality issues persist across multiple generations

---

## 5. Emotion Profiles — Chatterbox Parameters

Chatterbox controls vocal expression through two parameters:

### Parameter Ranges

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| `exaggeration` | 0.25–2.0 | 0.5 | Higher = more expressive, animated delivery |
| `cfg_weight` | 0.2–1.0 | 0.5 | Lower = slower pacing, more deliberate |

**Quality warning**: Values of `exaggeration` above 1.0 frequently cause audio artifacts (crackling, distortion, robotic tones). Keep values moderate.

### Emotion Profile Map

These profiles are applied based on emotion markers in the annotated text:

| Marker | Exaggeration | CFG Weight | Effect |
|--------|-------------|------------|--------|
| `[SLEEPY]` | 0.3 | 0.3 | Slow, drowsy, winding down |
| `[GENTLE]` | 0.5 | 0.4 | Warm, natural, tender |
| `[CALM]` | 0.5 | 0.5 | Default pace, serene |
| `[EXCITED]` | 0.7 | 0.5 | Lively, energetic |
| `[CURIOUS]` | 0.6 | 0.5 | Interested, wondering |
| `[ADVENTUROUS]` | 0.7 | 0.4 | Bold, confident |
| `[MYSTERIOUS]` | 0.5 | 0.3 | Slow, suspenseful |
| `[JOYFUL]` | 0.7 | 0.5 | Bright, warm |
| `[DRAMATIC]` | 0.7 | 0.3 | Intense but stable |
| `[WHISPERING]` | 0.3 | 0.3 | Hushed, intimate |
| `[RHYTHMIC]` | 0.5 | 0.3 | Measured, poetic cadence |
| `[SINGING]` | 0.7 | 0.3 | Expressive, melodic |
| `[HUMMING]` | 0.4 | 0.3 | Soft, melodic |

### Content Type Base Profiles

When no emotion marker is active, use the content type default:

| Content Type | Exaggeration | CFG Weight |
|-------------|-------------|------------|
| Story | 0.5 | 0.5 |
| Poem | 0.5 | 0.3 |
| Lullaby | 0.7 | 0.3 |

### Tuning Guidelines

- **If audio sounds too robotic**: Lower `cfg_weight` slightly (try 0.3–0.4)
- **If audio sounds too flat**: Raise `exaggeration` slightly (try 0.6–0.7)
- **If audio has artifacts/crackling**: Lower `exaggeration` (keep below 0.8)
- **If pacing is too fast**: Lower `cfg_weight` and ensure `--speed 0.8`
- **If pacing is too slow**: Raise `cfg_weight` toward 0.5
- **Never exceed**: `exaggeration > 1.0` for production content

---

## 6. Post-Processing Pipeline

After TTS generation, every audio file goes through these steps:

### 6.1 Concatenation

```python
# Combine all segments for a story variant
combined = audio_segments[0]
for seg in audio_segments[1:]:
    combined = combined + seg

# Paragraph pauses (1000 ms between paragraphs)
# Emotion pauses: [PAUSE] = 800 ms, [DRAMATIC_PAUSE] = 1500 ms
```

### 6.2 Normalization

- Target: **-16 dBFS** (gentle level, appropriate for bedtime listening)
- Apply gain adjustment: `gain = -16.0 - combined.dBFS`
- This ensures consistent volume across all stories and voices

### 6.3 Fade In / Fade Out

| Fade | Duration | Purpose |
|------|----------|---------|
| Fade in | 500 ms (or 25% of audio, whichever is smaller) | Gentle audio onset |
| Fade out | 1500 ms (or 33% of audio, whichever is smaller) | Smooth, sleepy ending |

### 6.4 Export

```python
combined.export(
    output_path,
    format="mp3",
    bitrate="256k",    # High quality for clear speech
    # Native 24 kHz sample rate preserved — do NOT upsample
)
```

### What NOT to Do in Post-Processing

- **Do NOT upsample** to 44.1 kHz or 48 kHz — adds interpolation artifacts with no quality benefit
- **Do NOT apply EQ** — warmth filters cut useful frequencies; quality comes from voice references
- **Do NOT add reverb or effects** — Chatterbox output is production-ready
- **Do NOT compress dynamic range** — the natural volume variation is desirable for storytelling
- **Do NOT re-encode** — generate WAV from Chatterbox, convert to MP3 once

---

## 7. Parallel Generation

### Configuration

| Setting | Default | Recommendation |
|---------|---------|----------------|
| Workers | 5 | 5 for Modal (matches container auto-scaling) |
| Timeout | 180 s per call | Sufficient for ~300-char chunks |
| Retries | 3 per segment | With exponential backoff (5s, 10s, 15s) |

### Thread Safety

- Each worker thread creates its own `httpx.Client`
- `content.json` is saved with file locking (`fcntl.flock`) every 5 completions
- Results are accumulated in a thread-safe dict with `threading.Lock`

### Warm-Up

Always warm up the Modal container before batch generation:

```python
# Health check first, then warm-up TTS call if needed
warm_up_chatterbox(client)  # Sends "Hello" with female_1 voice
```

Cold starts on Modal take 30–60 seconds. The warm-up prevents the first real generation from timing out.

---

## 8. Known Issues & Workarounds

### 8.1 Hallucination on Long Text

**Problem**: Text longer than ~300 characters may cause Chatterbox to generate speech for entirely different text.

**Fix**: Always chunk text to 300 characters max (see Section 3).

**Detection**: Run `qa_audio.py` — Phase 2 (transcription fidelity) catches this with score < 0.50.

### 8.2 Short Text Hallucination

**Problem**: Very short text (<20 chars) can cause garbled or repeated output.

**Fix**: Pad short segments with trailing `. ` or extend onomatopoeia.

**Example**: `"Shh"` becomes `"Shh, shh, shh..."` in the annotated text.

### 8.3 Chunk Boundary Artifacts

**Problem**: Audio at the join point between two sub-chunks may have audible clicks, pops, or unnatural transitions.

**Fix**: Apply a short crossfade (20–50 ms) when concatenating sub-chunks within the same paragraph:

```python
# Crossfade between sub-chunks of the same speech segment
if len(sub_chunks) > 1:
    crossfade_ms = 30
    result = sub_chunks[0]
    for chunk_audio in sub_chunks[1:]:
        result = result.append(chunk_audio, crossfade=crossfade_ms)
```

For paragraph boundaries, use silence (1000 ms) instead of crossfade.

### 8.4 40-Second Generation Limit

**Problem**: Chatterbox quality degrades significantly for generations exceeding ~40 seconds of audio.

**Fix**: At 0.8x speed, 300 characters generates approximately 25–35 seconds of audio, well within the safe zone. The chunk limit (300 chars) inherently prevents this issue.

### 8.5 Female_1 Consistently Slow

**Problem**: The `female_1` voice reference naturally speaks slower, causing duration outliers (>15% above median).

**Impact**: Flagged as WARN in QA but not a quality issue — the voice is still clear and pleasant.

**Action**: Accept as characteristic of this voice. No fix needed unless duration exceeds 25% above median.

### 8.6 Modal Container Cold Starts

**Problem**: First request after container idle period takes 30–60 seconds.

**Fix**: Always run `warm_up_chatterbox()` before batch generation. For time-sensitive runs, hit the health endpoint 2 minutes before starting.

---

## 9. Quality Assurance — Post-Generation

### Automated QA Pipeline

Run after every generation batch:

```bash
# Full 3-phase QA (recommended)
python3 scripts/qa_audio.py --lang en

# Quick duration check only (free, instant)
python3 scripts/qa_audio.py --lang en --duration-only

# Transcription fidelity only (no Voxtral quality scoring)
python3 scripts/qa_audio.py --lang en --no-quality-score
```

### QA Phases

| Phase | What It Checks | Cost |
|-------|---------------|------|
| **Phase 1**: Duration | Per-story median deviation >15% flags WARN | Free |
| **Phase 2**: Transcription | Voxtral ASR → text comparison (ratio, word overlap, word order) | ~$0.003/min |
| **Phase 3**: Quality | Voxtral chat scoring (pronunciation, fluency, pacing, emotion) | Token-based |

### Pass/Fail Thresholds

| Verdict | Criteria |
|---------|----------|
| **PASS** | Fidelity >= 0.70 AND no quality score < 5 |
| **WARN** | Fidelity 0.49–0.70 OR any quality score < 5 OR duration outlier |
| **FAIL** | Fidelity < 0.49 OR completeness < 4 OR overall < 4 |

### Manual Listening Checklist

Even with automated QA, manually listen to **at least 1 voice variant per story**:

- [ ] Audio starts and ends cleanly (no abrupt cuts)
- [ ] Speech is intelligible throughout
- [ ] Pacing feels appropriate for bedtime (not rushed)
- [ ] Emotion markers are audibly reflected (gentle vs. excited sections differ)
- [ ] No clicks, pops, or digital artifacts
- [ ] Paragraph pauses feel natural
- [ ] Fade in/out is smooth
- [ ] Duration is reasonable for the content length

---

## 10. CLI Reference

### generate_audio.py

```bash
# Standard bedtime generation (ALWAYS use --speed 0.8)
python3 scripts/generate_audio.py --speed 0.8

# Single story, all 7 voices
python3 scripts/generate_audio.py --story-id <id> --speed 0.8

# Single voice across all stories
python3 scripts/generate_audio.py --voice female_1 --speed 0.8

# English only
python3 scripts/generate_audio.py --lang en --speed 0.8

# Force regeneration of existing files
python3 scripts/generate_audio.py --force --speed 0.8

# Preview plan without generating
python3 scripts/generate_audio.py --dry-run

# Adjust parallel workers (default 5)
python3 scripts/generate_audio.py --workers 3 --speed 0.8
```

### qa_audio.py

```bash
# Full QA (all 3 phases)
python3 scripts/qa_audio.py --lang en

# Duration outliers only (free)
python3 scripts/qa_audio.py --duration-only

# Skip Voxtral quality scoring
python3 scripts/qa_audio.py --lang en --no-quality-score

# Single story
python3 scripts/qa_audio.py --story-id <id>

# Single voice
python3 scripts/qa_audio.py --voice female_1

# Custom fidelity threshold
python3 scripts/qa_audio.py --threshold 0.80

# Fix failed variants (regenerate)
python3 scripts/qa_audio.py --fix
```

---

## 11. Batch Generation Workflow

### Standard Workflow

1. **Prepare content**: Ensure all stories in `content.json` have `annotated_text` with emotion markers
2. **Verify text formatting**: Paragraphs separated by `\n\n`, no paragraph exceeds 300 chars after marker removal
3. **Warm up Modal**: Run `--dry-run` to verify plan, then start generation
4. **Generate at 0.8x speed**: `python3 scripts/generate_audio.py --speed 0.8 --lang en`
5. **Run QA**: `python3 scripts/qa_audio.py --lang en`
6. **Review report**: Check `seed_output/qa_reports/qa_audio_latest.json`
7. **Fix failures**: Investigate FAIL/WARN variants, fix source text if needed, regenerate
8. **Copy to frontend**: `cp audio/pre-gen/*.mp3 ../dreamweaver-web/public/audio/pre-gen/`
9. **Deploy**: Push to main for Vercel auto-deployment

### Pre-Generation Checklist

- [ ] Modal container is awake (health check returns 200)
- [ ] Voice reference files exist for all target voices
- [ ] `content.json` is valid JSON with all required fields
- [ ] `annotated_text` uses correct emotion markers (see Content Generation Guidelines)
- [ ] No single paragraph exceeds ~600 characters (will be sub-chunked to 300)
- [ ] `--speed 0.8` is set (NEVER use default 1.0 for production)
- [ ] Sufficient Modal credits for the batch (estimate: ~$0.02 per voice variant)
- [ ] `ffmpeg` is installed (`brew install ffmpeg`)

### Cost Estimation

| Item | Cost |
|------|------|
| Modal GPU (A10G) | ~$0.10/min active |
| Per voice variant (avg) | ~$0.02–0.05 |
| 20 stories x 7 voices | ~$3–7 total |
| QA transcription | ~$0.003/min audio |
| Full batch (generate + QA) | ~$5–10 |

---

## 12. File Structure

```
dreamweaver-backend/
├── scripts/
│   ├── generate_audio.py          # Main audio generation script
│   └── qa_audio.py                # Voxtral-based QA pipeline
├── audio/
│   └── pre-gen/                   # Generated MP3 files
│       ├── gen-xxxx_female_1.mp3
│       ├── gen-xxxx_female_2.mp3
│       └── ...
├── voice_references/              # Voice reference WAV files
│   ├── female_1.wav
│   ├── female_2.wav
│   └── ...
├── seed_output/
│   ├── content.json               # Story data with audio_variants
│   └── qa_reports/
│       ├── qa_audio_latest.json   # Latest QA report
│       └── transcript_cache.json  # Cached Voxtral transcriptions
└── docs/
    ├── CONTENT_GENERATION_GUIDELINES.md
    └── AUDIO_GENERATION_GUIDELINES.md  # This document
```

---

## 13. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Garbled speech mid-story | Text too long for single TTS call | Enable sub-chunking (300 char max) |
| Different text spoken than written | Hallucination from long input | Chunk to 300 chars, re-run QA |
| Audio cuts off abruptly | Exceeded 40-second generation limit | Chunk to 300 chars |
| Crackling/distortion | `exaggeration` too high (>1.0) | Lower to 0.5–0.7 range |
| Robotic monotone voice | `cfg_weight` too high or bad reference | Lower `cfg_weight`, check reference WAV |
| Timeout errors | Modal cold start or overloaded | Warm up first, retry with backoff |
| Silent output | Very short input text (<10 chars) | Pad text, extend onomatopoeia |
| Click at chunk boundary | No crossfade between sub-chunks | Add 30 ms crossfade |
| Volume inconsistent across stories | Missing normalization | Ensure -16 dBFS normalization step |
| female_1 always longer than others | Natural voice characteristic | Accept unless >25% deviation |

---

## Summary of Non-Negotiable Rules

1. **Speed**: Always `--speed 0.8` for all production audio
2. **Chunking**: Maximum 300 characters per TTS call
3. **No upsampling**: Keep native 24 kHz sample rate
4. **Normalization**: -16 dBFS for all output
5. **Fades**: 500 ms in, 1500 ms out
6. **Paragraph pause**: 1000 ms silence between paragraphs
7. **QA**: Run `qa_audio.py` after every generation batch
8. **Voice references**: WAV format only, 10–20 seconds, clean recording
9. **Exaggeration cap**: Never exceed 1.0 for production content
10. **Warm-up**: Always warm up Modal container before batch generation
