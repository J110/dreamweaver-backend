# Hindi Daily Pipeline

Generates one fresh piece of each Hindi content type per day, validates against the v2 spec for each, deploys to prod, sends an email summary.

## Schedule

| Pipeline | Cron | Where | Notes |
|---|---|---|---|
| English daily | `30 1 * * *` (01:30 UTC) | GCP VM `dreamvalley-prod` | Existing — runs short stories + lullabies + long stories in English |
| Hindi daily   | `0 4 * * *`  (04:00 UTC) | GCP VM `dreamvalley-prod` | This pipeline. Runs ~2.5h after English finishes. |

## What it generates daily

| Type | Engine | Audio | Approx cost |
|---|---|---|---|
| Hindi short story | ElevenLabs Multilingual v2 (single voice per mood) | 3-5 min | ~$0.30 |
| Hindi long story  | EL multi-voice + MiniMax mid-song + bed/swells | 13-15 min | ~$1.20 |
| Hindi lullaby     | MiniMax v2.5 + Hindi reference audio | 60-90s | ~$0.10 |
| Hindi silly song  | ElevenLabs Music | 60-75s | subscription credits |
| Hindi poem        | MiniMax v2.5 + Hindi reference audio | 30-45s | ~$0.10 |
| 3 covers          | Together AI FLUX | — | ~$0.01 |
| **Total/day**     |  |  | **~$1.70** |

Monthly: ~$50.

## QA Layer (Mistral → Groq critic → audio render)

A second-pass LLM critic sits between the regex validator and the audio render. The regex validator catches encodable rules (tag counts, blacklisted words, Devanagari leaks); the critic catches semantic gaps the regex misses (embedded dialogue vs `NAME: "..."` form, register slips, whether onomatopoeia sounds natural in context).

```
Mistral content → regex validator → IF errors:
  ├─ any MAJOR severity   → full regen (continue retry loop)
  └─ all errors are MINOR → ONE Groq critic attempt:
                              ├─ action="fix"            → re-validate; pass → ship; else regen
                              ├─ action="pass_override"  → log + ship + flag for human audit
                              └─ action="regenerate"     → regen with reason
```

**One critic attempt per generation.** If Groq's fix introduces new errors or doesn't resolve everything, we regenerate without trying Groq a second time. Avoids whack-a-mole patching loops.

### Severity classification

| Severity | Examples | Why |
|---|---|---|
| **MAJOR** (regenerate) | Devanagari leak in user-facing field · religious content · blacklisted name · missing `[PHASE_*]` · primary character has no dialogue (≥2 mentions in body) · `characterType` not in canonical 11 · literary Hindi (`shayan`, `pushp`, …) · missing `diversityFingerprint` (cascades to next 10 stories' sampling) · choruses non-identical (silly song) · poem section tags (structurally wrong type) | Surgical edits would cascade or fabricate content. Cheaper to regen. |
| **MINOR** (Groq fixes) | Tag counts off by 1-3 · onomatopoeia count low · conversational markers low · word count off by ≤15% · embedded dialogue (reformat only, no new lines) · missing `morals` · missing `[BREATHE_GUIDE]`/`[SONG_SEED:]`/`[WHISPER]` · matra over-count (poem) · forbidden tag leak (`[GENTLE]` in v2 short story) · secondary character has no dialogue | Targeted mechanical edits don't change story essence. |

### Allow/deny enforcement

Per-content-type allow-list governs which fields the critic may touch. Deny-list is global and unconditional (id, lang, title, world_name, characters[].name, voice_routing, audio_*, cover_*, mood, age_group, …). After Groq returns a fix, we diff against the original; any path not in allow-list or matching deny-list rejects the fix → regenerate.

**Hard cap**: aggregate edit ratio ≤ 30 % of JSON-serialized content length, regardless of which fields changed. Belt-and-suspenders against runaway edits even within allowed fields.

### Pass-override (Groq disagrees with the validator)

When the critic believes a flagged error is a false positive (e.g. validator flagged `"ram "` but the context is `"naram"`/soft, not the deity), it may return `action: "pass_override"` with a justification. The pipeline ships the content unchanged but logs the override on the entry's `qa_changes.action` field for weekly human audit.

### Model choice — Groq Llama 3.3 70B

| Option | Cost/call | Latency | Decision |
|---|---|---|---|
| **Groq llama-3.3-70b-versatile** | ~$0.001 | 2-3s | **chosen** |
| Claude Haiku | ~$0.05 | 8-15s | rejected: 50× cost for marginal capability gain |
| Mixtral 8x7B (Groq) | ~$0.0005 | 1-2s | rejected: under-powered on multi-rule instruction following |
| Mistral Large (re-call) | ~$0.05 | 5-10s | rejected: same model as generator → inherits same blind spots, defeats the second-pass purpose |

The critic's job is rule-keeping, not creative generation. Llama 3.3 70B is sufficient for instruction-following on a bounded JSON-edit task.

### Env-var gates

```
HINDI_QA_ENABLED=true         # master switch (default false)
HINDI_QA_TYPES=short_story    # comma-separated content types (default: short_story)
```

Rollout plan: enable for `short_story` first (smaller surface area, easier to audit), expand to other types after 3-5 days of clean weekly reports. Long stories last because they have the largest creative content where critic edits could most plausibly go wrong undetected.

### Audit trail

Every fixed/overridden item carries `qa_changes` on its content.json entry:

```json
"qa_changes": {
  "action": "fix" | "pass_override" | "regenerate",
  "summary_of_changes": ["Added 'tap tap' onomatopoeia at line 14", ...],
  "validator_errors": [...],     // only for pass_override
  "justification": "...",         // only for pass_override
  "elapsed_ms": 2340
}
```

### Weekly QA report

`scripts/weekly_qa_report.py` runs Mondays at 09:00 UTC and emails an aggregated summary:

- Total items / fix rate / override count
- Top fix categories (e.g. "Added onomatopoeia: 18 stories (38%)")
- Pass-override audit list

The fix-category histogram is the highest-leverage signal. Rules Groq fixes consistently are rules the Mistral prompt isn't steering hard enough on. Use the report to prioritize prompt improvements.

```
0 9 * * 1  cd /opt/dreamweaver-backend && python3 scripts/weekly_qa_report.py >> logs/weekly_qa.log 2>&1
```

### System prompt (the heart of the critic)

The critic's system prompt lives in `scripts/_hindi_qa_critic.py:SYSTEM_PROMPT`. It explicitly enumerates:
- What the critic MAY edit (tag insertion, dialogue reformatting, onomatopoeia/marker insertion, missing-field fills)
- What it MUST NEVER edit (rename characters, change title/world/repeated_phrase, invent dialogue, change diversityFingerprint values)
- Decision rules (`fix` / `pass_override` / `regenerate` triggers)
- Edit magnitude cap (≤ 30 % total content length)

The prompt is reviewed before any implementation lands. Updating it requires a code review.

---

## Modules

```
scripts/
├── pipeline_run_hi.py          # orchestrator (cron entry point)
├── _hindi_llm.py               # Mistral primary + Groq fallback
├── _hindi_diversity.py         # catalog-aware sampler (avoid recent-N collisions)
├── _hindi_validators.py        # consolidated v2 validators per type
└── _hindi_generators.py        # per-type generation + audio + cover + storage
```

### Generator contract

Each generator (`generate_short_story`, `generate_long_story`, `generate_lullaby`, `generate_silly_song`, `generate_poem`) takes a diversity-axes dict and returns the published entry. Internally:

1. Builds a type-specific Mistral/Groq prompt with anti-duplication blocklist
2. Calls `_hindi_llm.generate_json` (Mistral first; Groq fallback on 429/timeout/error)
3. Runs the v2 spec validator from `_hindi_validators.VALIDATORS[type]`
4. Retries up to 3 times on validation failure, embedding prior errors as a "PREVIOUS ATTEMPT FAILED" hint in the next prompt
5. Renders audio via the engine the v2 spec mandates for that type
6. Generates cover via FLUX (Together AI) — 1024×1024 webp (silly = 512×512)
7. Writes to:
   - Seed master copies (`seed_output/<dir>/`)
   - Per-item runtime files (`data/silly_songs/{id}.json`, `data/poems/{id}.json`) for `/api/v1/silly-songs` and `/api/v1/poems` endpoints
   - `seed_output/content.json` (generic mirror, indexed by all explore tabs)
   - All nginx-aliased paths the frontend expects

### Diversity windows

Each type avoids collisions on the last N items of the same type:

| Type | Window | Axes |
|---|---|---|
| short_story | 30 items | age × mood × characterType × story_type |
| long_story  | 14 items | age × mood × world × characterType |
| lullaby     | 14 items | age × mood × lullaby_type |
| silly_song  | 14 items | age × mood × category × anthem_id |
| poem        | 14 items | age × mood × poem_type |

Plus per-type anti-duplication on `recent_titles`, `recent_phrases`, `recent_names` etc., passed to the LLM as an explicit blocklist in the prompt.

## Failure handling

- Each generator runs in isolation; partial failures still ship the successes.
- On any generator failure, log to `seed_output/_hindi_failures.jsonl`.
- Email always sent (success or failure) via `pipeline_notify.send_pipeline_notification` — same Resend template the English pipeline emits.
- Exit code: `0` if ≥3 of 5 succeeded; `1` otherwise (alerts cron).

## Deploy steps inside the orchestrator

```
1. deploy_guard.py snapshot           # baseline
2. For each of 5 types:
   - pick_<type>_axes(catalog)        # diversity sample
   - generators[<type>](axes)         # LLM + render + cover + save
3. git commit + git pull --rebase + git push
4. POST /api/v1/admin/reload (with X-Admin-Key)
5. deploy_guard.py verify             # post
6. pipeline_notify.send_pipeline_notification
```

## Email content

Reuses the English pipeline's HTML template. The Hindi pipeline populates the same `state` dict shape with:
- `lang: "hi"`
- `generated_ids` (per-type successes)
- `hindi_per_type` (status per type)
- `hindi_failures` (with per-type error message)

## v2 spec sources

| Type | Spec doc |
|---|---|
| short_story | `HINDI_SHORT_STORY_GUIDELINES (2).md` (v2.1) |
| long_story  | `HINDI_LONG_STORY_GUIDELINES.md` |
| lullaby     | `HINDI_LULLABY_GENERATION_GUIDELINES.md` |
| silly_song  | `HINDI_SILLY_SONGS_GUIDELINES (1).md` (v2.1, ElevenLabs Music) |
| poem        | `HINDI_MUSICAL_POEMS_GUIDELINES (1).md` (v2.1, MiniMax v2.5) |

## Logs

```
/opt/dreamweaver-backend/logs/pipeline_hi_cron.log         # cron stdout/stderr
/opt/dreamweaver-backend/logs/pipeline_hi_<timestamp>.log  # per-run detail
/opt/dreamweaver-backend/seed_output/_hindi_failures.jsonl # per-type failure trail
```

## Manual run

```bash
ssh dreamvalley-prod
cd /opt/dreamweaver-backend
python3 scripts/pipeline_run_hi.py
```

Or test a single generator:

```python
import sys; sys.path.insert(0, "scripts")
from _hindi_diversity import pick_poem_axes
from _hindi_generators import generate_poem
generate_poem(pick_poem_axes())
```

## Cost / monitoring

- Email summary fires daily — watch for "0/5" or "1/5" success rates as a signal.
- Cron exit code 1 (failure mode) → cron may also trigger a separate email alert depending on the system.
- Monthly: ~$50 across MiniMax + ElevenLabs + Together + Mistral. Mostly ElevenLabs (long-story narration is ~70% of total).

## Known failure-mode decoder

| Symptom | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: _reference_28s.m4a` | Hindi reference audio not on prod (it's gitignored) | scp from local; mirror to `/opt/audio-store/reference/` |
| `Groq 401 Invalid API Key` | Stale GROQ_API_KEY in `.env` | replace with the current key; verify with a tiny test call |
| `Mistral non-JSON response: Unterminated string` | LLM hit `max_tokens` mid-output | bump `max_tokens` for that generator (long stories are most prone) |
| `re.search() expected string or bytes-like object` (long story) | LLM returned `full_text_roman` as null/list/dict | `shape()` already coerces to str; if it persists, log and inspect raw output |
| `religious content: 'ram '` flagged on benign Hindi prose | Validator FP — substring match catches naram/garam/aaram/devar | Already fixed via word-boundary regex (`\bram\b`) |
| `fal.ai 403 Forbidden on rest.fal.ai/storage/auth/token` | **fal.ai out of credits** (the error message is misleading; it's a billing block, not a permission issue) | Top up fal.ai credits at fal.ai/dashboard |
| Hindi silly song / poem shows broken cover or unplayable audio | Generator wrote to web public/ instead of backend public/ + cover-store | Already fixed in `_hindi_generators.py` (ON_PROD detection writes to nginx-aliased paths) |
| `KeyError: 'lullaby'` (or any type) on `--types <subset>` runs | display/state loop iterated all 5 types | Already fixed (`if t in results`) |

## Related

- `pipeline_run.py` — English daily pipeline
- `pipeline_notify.py` — email sender (shared)
- `deploy_guard.py` — pre/post snapshot + verify (shared)
- `audio_assembly.py` — `MUSIC_DIR`, `apply_swell_envelope`, `normalize_for_tts` (shared)
