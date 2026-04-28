# Funny Shorts — Production Notes (v3 dialogue, post-2026-04-28)

These notes capture the production-tested patterns for the v3 dialogue
funny shorts pipeline. Read alongside the original spec docs
(`ENGLISH_FUNNY_SHORTS_GUIDELINES.md`, `HINDI_FUNNY_SHORTS_GUIDELINES.md`)
— this file documents deltas from the spec that were discovered while
shipping the first English + Hindi shorts.

## Pipeline overview

```
generate_funny_shorts.py (EN)        ──┐
generate_funny_shorts_hi.py (HI)     ──┼─→ data/funny_shorts/{id}.json
                                       │   public/audio/funny-shorts[-hi]/{id}.mp3
                                       │   (auto-syncs to /opt/dreamweaver-web/public,
                                       │    /opt/audio-store, /opt/cover-store)
generate_funny_short_cover.py        ──┴─→ public/covers/funny-shorts[-hi]/{id}_cover.webp
                                           (FLUX via Pollinations → Together AI → FluxAPI → Replicate)

Daily cron:
  pipeline_run.py        — EN, before-bed block, calls generate_funny_shorts.py
  pipeline_run_hi.py     — HI, content_type "funny_short" via _hindi_generators
```

Shared library: `scripts/_funny_shorts_common.py` — validator, sampler,
Mistral prompt builder, ElevenLabs v3 dialogue caller, sting frame
assembler.

## Key v3-API constraints discovered in production

### v3 `/text-to-dialogue` rejects empty-text inputs

`{"text": "[laughs together]", ...}` returns HTTP 400 with
`status: "input_text_empty"`. Workaround: append punctuation or
laughter onomatopoeia after the tag — the tag still produces real
non-verbal audio because v3 strips it before the empty check.

| Pattern | Status | v3 audio length |
|---|---|---|
| `[laughs together]` | 400 (rejected) | — |
| `[laughs together]...` | 200 | ~1.1s |
| `[laughs together] hahaha` | 200 | ~1.7s ← **canonical closing** |
| `[laughs together] hahaha hee hee` | 200 | ~2.6s |

The validator's `_is_standalone_effect_line()` accepts a tag followed
by punctuation OR laugh onomatopoeia (regex `_LAUGH_ONOMATOPOEIA`).

### Hindi voices need Devanagari, not Roman

Passing Roman script (`"Bijli phir gayi yaar."`) to a Hindi voice
results in English-transliterated phonemes. Existing prod pattern (see
`_hindi_generators.py:402` for short stories) uses Devanagari for the
TTS engine while keeping Roman for storage.

The Hindi prompt now requires both `text` (Roman, stored) and
`text_deva` (Devanagari, engine input) per dialogue line. The
orchestrator builds `engine_inputs` from `text_deva` before calling v3:

```python
engine_inputs = [
    {"voice": l["voice"], "text": l.get("text_deva") or l["text"]}
    for l in script["inputs"]
]
dialogue_bytes = render_dialogue_v3(engine_inputs, voice_a_id, voice_b_id)
```

Tags stay in English in BOTH fields — they're delivery cues, not text.

### Asymmetric framing (1s pre / 2.5s post)

`frame_dialogue_with_stings()` now uses `pre_gap_ms=1000` and
`post_gap_ms=2500`. The longer post-gap lets the laugh's natural decay
finish before the outro starts. With 1s post-gap, listeners reported
"ends abruptly mid laughter".

### Sting trims (intro hard cut, outro fade)

- `trim_intro_to_3s` — 4.5s hard cut (preserves resolved chord)
- `trim_outro_to_3s` — 4.5s with 1.5s fade-out from 3.0s (gentle taper)

(Function names kept for backward-compat; actual length is 4.5s after
user feedback that 3.0s felt too abrupt.)

### Sting generation engines

- English: `fal-ai/minimax-music/v2` (no reference audio)
- Hindi: `fal-ai/minimax-music/v2.5` with reference at
  `/opt/audio-store/reference/hindi_lullaby_ref.m4a`

Use `fal_client.subscribe()` (matches existing prod pattern in
`generate_lullaby.py`, `publish_hindi_batch_day2.py`). v2 takes
`lyrics_prompt` + `audio_setting`; v2.5 takes `lyrics: ""` +
`is_instrumental: true`.

## Current voice library (post user-pick 2026-04-28)

### English (6 voices)

| Slot | Voice ID | Description |
|---|---|---|
| `mini` | `hO2yZ8lxM3axUxL8OeKX` | Lively cute young female |
| `katherine` | `342hpGp7PKo7DsTTVSdr` | Eccentric Mad Scientist |
| `suhana` | `9vP6R7VVxNwGIGLnpl17` | Very young & joyful narrator |
| `tashi` | `YIXhzp6l2M0ddzOGIbJ3` | Expressive Hindi-kids narrator (English) |
| `kiran_en` | `o80picuztV1xYiPeIrpa` | Very young adorable story narrator |
| `omar` | `S7IsvAvEoDfui6GSZK3A` | Very young storyteller |

### Hindi (6 voices)

| Slot | Voice ID | Description |
|---|---|---|
| `omar_hi` | `srEfhy4AF67Mw9SpTVFd` | Energetic, engaging, animated |
| `suhana_hi` | `A2VREc2wjqtSZloENLHe` | Very young & expressive narrator |
| `riya` | `4RloeZf2FRvGiu4uoKOf` | Children storytelling |
| `kiran` | `ss0PMu3rEfIwrYgOOl5S` | Very young, cute & engaging |
| `gappu` | `psk8YLODv4ETdKheNwwz` | Kids cartoon character voice |
| `gappu_bhai` | `tBPQ3sUKpdLEVpyeCHyk` | Lazy cartoon voice |

8 curated pairings each — see `APPROVED_PAIRINGS_EN` /
`APPROVED_PAIRINGS_HI` in `_funny_shorts_common.py`.

## Validator: real-laughter requirements

In addition to the spec's structural / anti-template / Hindi rules,
the validator enforces:

1. **At least 1 standalone laughter line** — a tag from
   `LAUGHTER_TAGS = ([laughs together], [laughs], [nervous laugh], [giggles])`
   followed by only punctuation or laugh onomatopoeia. v3 renders
   these as actual non-verbal audio events.

2. **Final line must be standalone laughter** —
   `[laughs together] hahaha` or `[laughs] hahaha`. Acceptable
   fallbacks are standalone `[sigh]...` / `[yawns]...` /
   `[thoughtful]...` or soft-prose closings (`yeah`, `okay`,
   `theek hai`, `achha`, etc.). `[grinning]` alone is no longer
   accepted because it produces no laughter audio.

3. **Required opening tag enforcement** — the orchestrator samples a
   `required_opening_tag`; the validator rejects if Mistral used a
   different one as the first tag.

## Mistral prompt patterns

### Tightened settings

- `temperature: 0.85` (was 0.95 — JSON-mode reliability cliff)
- 5 retries with 35s sleep between (Mistral free tier is 2 req/min)
- `response_format: {"type": "json_object"}`

### Output format example shows shape, not content

The prompt embeds an illustrative `inputs[]` structure but explicitly
warns "do NOT copy the example text — only copy the structure".
Discovered during voice-label drift (Mistral was emitting
`"voice": "mini"` instead of `"voice": "A"`).

### Hindi prompt includes both text + text_deva

```json
{
  "inputs": [
    {"voice": "A", "text": "[curious] Roman opener.", "text_deva": "[curious] रोमन ओपनर।"},
    ...
    {"voice": "B", "text": "[laughs together] hahaha", "text_deva": "[laughs together] hahaha"}
  ]
}
```

Tags + onomatopoeia stay identical between Roman and Devanagari fields.

## Storage layout (final, post-sync)

```
/opt/dreamweaver-backend/
  data/funny_shorts/{id}.json               ← canonical metadata
  public/audio/funny-shorts/{id}.mp3        ← EN audio (orchestrator writes here first)
  public/audio/funny-shorts-hi/{id}.mp3     ← HI audio
  public/covers/funny-shorts/{id}_cover.webp
  public/covers/funny-shorts-hi/{id}_cover.webp

/opt/dreamweaver-web/public/audio/funny-shorts[-hi]/{id}.mp3   ← nginx-served (sync target)
/opt/audio-store/funny-shorts[-hi]/{id}.mp3                    ← backup store
/opt/audio-store/stings/funny_short_{intro,outro}_{en,hi}.mp3  ← stings (one-time generated)
/opt/cover-store/funny-shorts[-hi]/{id}_cover.webp             ← nginx-served covers
```

Orchestrators auto-sync via `_sync_to_prod_paths()` after writing the
backend copy. The cover script syncs to `/opt/cover-store/` similarly.
On dev boxes where these dirs don't exist, sync is a no-op.

## nginx aliases (already in production config)

```nginx
location /audio/funny-shorts/      → /opt/dreamweaver-web/public/audio/funny-shorts/
location /audio/funny-shorts-hi/   → /opt/dreamweaver-web/public/audio/funny-shorts-hi/
location /covers/funny-shorts/     → /opt/cover-store/funny-shorts/
location /covers/funny-shorts-hi/  → /opt/cover-store/funny-shorts-hi/
```

The HI cover alias was added during this build (the EN cover one was
pre-existing from the v1 funny shorts era).

## Deploy guard

`scripts/deploy_guard.py` skips items with `subtype: "funny_short"` in
its story-shape audio check, because funny shorts use `audio_url`
(string) rather than `audio_variants` (array of dicts). They have
their own `/api/v1/funny-shorts` endpoint and verify-by-HEAD-request
through the standard URL-reachability sweep.

## Frontend integration

- `dreamweaver-web/src/utils/api.js` — `funnyShortsApi` (list / get / play / replay)
- `dreamweaver-web/src/app/before-bed/page.js` — third row alongside
  silly songs and poems; uses 😄 emoji; player + share UX matches.
- `dreamweaver-web/src/app/before-bed/[type]/[id]/page.js` — share
  preview / OG metadata route registers `funny-shorts` type. Cover
  resolution prefers `item.cover` (full path) over `coverDir + cover_file`
  to handle the lang-specific `funny-shorts-hi` directory.

## One-off / utility scripts

- `scripts/generate_funny_shorts_stings.py` — fal.ai-driven sting
  generation. Generates 5 candidates, lets a human pick, trims to 4.5s.
  One-time per language unless re-recording stings.
- `scripts/funny_shorts_mirror.py` — `--add <id>` / `--rebuild`. Used
  for content.json mirror reconciliation (orchestrators auto-mirror
  but rebuild is useful when state drifts).
- `scripts/rerender_from_json.py` — re-render a short's audio from
  saved `inputs[]` without going through Mistral. Used when sting or
  framing logic changes and existing shorts need to be rebuilt.

## Daily pipeline integration

- **EN**: step in `pipeline_run.py`'s before-bed block, after silly
  song + poem generation. Runs `generate_funny_shorts.py --age {age}`
  then `generate_funny_short_cover.py --story-json data/funny_shorts/{id}.json`.
- **HI**: content type `funny_short` registered in
  `_hindi_generators.GENERATORS` and `_hindi_diversity.PICKERS`. Runs
  `generate_funny_shorts_hi.py --age {age}` + cover step.

Both pipelines auto-mirror, sync to nginx paths, and call admin reload.

## Known gotchas

- **Stash trap**: `git stash -u` on prod stashes untracked
  `data/funny_shorts/*.json` and audio files along with runtime
  state. If a `git pull` is blocked by dirty state, prefer
  `git fetch + git checkout origin/main -- scripts/` (selective)
  over `git stash`. The Docker volume mount `./data:/app/data` makes
  data/ persist across rebuilds, but a stash + pop dance can lose it.
- **content.json shape**: the LocalStore-mirror file is a flat list,
  not `{items:[]}`. The mirror helpers handle both shapes for safety.
- **Mistral free-tier limit**: 2 req/min. Keep retry sleep ≥35s.
- **Voice-label drift**: Mistral occasionally emits voice labels
  (`"mini"`) instead of `"A"`/`"B"`. The OUTPUT FORMAT example block
  in the prompt explicitly addresses this; validator catches it.
