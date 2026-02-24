# Lullaby Generation Guidelines

Best practices for writing lullaby lyrics that ACE-Step can reliably sing without skipping lines.

## 1. ACE-Step Lyric Format Rules

- **Section markers**: `[verse]`, `[chorus]`, `[bridge]` — lowercase, alone on their own line
- **Blank line** between sections (double `\n`)
- **4-6 lines per section** — ACE-Step struggles with >6 lines per section
- **6-12 words per line** — too short = rushed phrasing, too long = skipped entirely
- **Total lyrics**: ≤30 lines for 120s duration (~24-28 is ideal)
- **No parenthetical asides** or complex punctuation (em dashes, semicolons)
- **Simple vocabulary** — avoid tongue-twisters, consonant clusters, invented words

## 2. Structure Template

```
[verse]
4-6 lines, 6-12 words each

[chorus]
3-4 lines, 4-8 words each (shorter = more memorable)

[verse]
4-6 lines, 6-12 words each

[chorus]
(repeat EXACT same lyrics — copy-paste, don't paraphrase)

[verse]
4-6 lines, softer/sleepier tone

[chorus]
(repeat EXACT same lyrics)
```

**Key rule**: Choruses must be **identical** across repetitions. ACE-Step expects repeated choruses — varying the words confuses the model and causes line skipping.

## 3. Known Failure Patterns

| Pattern | Result | Fix |
|---------|--------|-----|
| Lines >15 words | Line skipped entirely | Break into two shorter lines |
| >6 sections in 120s | Compression/skipping | Limit to V-C-V-C-V-C (6 sections) |
| Non-repeating choruses | Model confusion, drift | Copy-paste identical chorus text |
| Emotion markers in lyrics | ACE-Step reads markers as lyrics | Strip `[SINGING]`, `[HUMMING]`, etc. before sending |
| Complex rhyme schemes (ABCABC) | Melodic drift | Use AABB or ABAB |
| Unusual/invented words | Words skipped or mumbled | Use common English vocabulary |
| Names with >2 syllables | Often garbled or skipped | Simplify or remove character names |
| Lines starting with punctuation | Parsing issues | Start lines with words, not quotes/dashes |

## 4. Pre-flight Checklist

Before sending lyrics to ACE-Step, verify:

- [ ] Total non-empty line count ≤ 30 (for 120s duration)
- [ ] No line exceeds 15 words
- [ ] Average line length: 6-12 words
- [ ] Choruses are **identical** (copy-paste, not paraphrased)
- [ ] Section count ≤ 6 (V-C-V-C-V-C typical)
- [ ] All emotion markers stripped (`[SINGING]`, `[GENTLE]`, etc.)
- [ ] All TTS markers stripped (`[PAUSE]`, `[BREATH_CUE]`, `[PHASE_2]`, etc.)
- [ ] Simple, singable vocabulary — no tongue-twisters
- [ ] Clear rhyme pattern (AABB or ABAB preferred)
- [ ] No lines start with punctuation marks

## 5. ACE-Step Parameter Reference

Current production values in `modal-songgen/app.py`:

| Parameter | Value | Notes |
|-----------|-------|-------|
| `guidance_scale_lyric` | 4.5 | Controls lyric adherence (was 2.5, raised to fix skipping) |
| `guidance_interval` | 0.7 | Applies guidance for 70% of inference steps |
| `duration` | 120 | Standard lullaby length in seconds |
| `mode` | "full" | Full instrumental accompaniment |

### Tuning Notes

- `guidance_scale_lyric` range: 1.0-7.0. Higher = stricter lyric following but potentially less natural melody. Sweet spot: 4.0-5.5.
- If line skipping persists at 4.5, try 5.0-5.5 before restructuring lyrics.
- Values >6.0 can cause robotic/choppy singing — avoid.

## 6. Marker Stripping

The `_EMOTION_MARKER_RE` regex in `scripts/generate_audio.py` strips TTS markers from lyrics before sending to ACE-Step. It must stay in sync with `_MARKER_RE`.

Current regex covers:
```
SINGING, HUMMING, GENTLE, CALM, JOYFUL, SLEEPY, EXCITED, DRAMATIC,
WHISPERING, CURIOUS, ADVENTUROUS, MYSTERIOUS, RHYTHMIC, PAUSE,
DRAMATIC_PAUSE, LONG_PAUSE, BREATH_CUE, CHAR_START, CHAR_END,
PHASE_2, PHASE_3, laugh, chuckle
```

**If new markers are added to TTS**, update `_EMOTION_MARKER_RE` in `generate_audio.py` to match.

## 7. Example: Good vs Bad Lyrics

### Bad (will cause skipping)
```
[verse]
In the library of the ancient clouds so very high above the world below,
Where the oldest and most beautiful stories learn to fly across the midnight sky,
Every single dream finds its long and winding way back to its home,
To the quiet place where golden light and silver silence always roam together.
```
Problems: Lines 1-2 are 15+ words. Line 4 is 13 words. Too verbose.

### Good (reliable singing)
```
[verse]
In the library of clouds so high,
Where the oldest stories learn to fly,
Every dream finds its way back home,
To the place where light and silence roam.
```
Each line: 7-9 words. Clean rhyme (AABB). Simple vocabulary.

## 8. Recommendations for Future Improvement

1. **Raise `guidance_scale_lyric`** to 5.0-5.5 if skipping persists at 4.5
2. **Post-generation transcription check**: Use Voxtral to transcribe the generated lullaby and compare against input lyrics (fidelity score)
3. **Split long lullabies**: If >24 singing lines needed, generate as 2x60s segments
4. **Log metrics**: Track line count, word count per line, and section count in generation reports for debugging
5. **A/B test chorus length**: 2-line choruses may be more reliably repeated than 4-line ones
