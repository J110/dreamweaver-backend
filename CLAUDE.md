# Dream Valley Backend — CLAUDE.md

This file is the operating contract for any Claude session working in `dreamweaver-backend/`. Read it once at session start; do not re-read unless edited.

---

## Operating Mode

- **No plans when code is possible.** If the task is well-specified, implement. Don't propose alternatives or ask for clarification on things you can decide.
- **Avoid re-reading files unnecessarily.** Trust your prior read for facts. Re-read only when the user references specific line numbers, or when you've edited the file since reading it.
- **Never explain code you just wrote.** The diff is the explanation.
- **TodoWrite for 3+ step tasks.** Mark each item complete as it lands; don't batch.
- **Tool priority:** `rg` / `fd` over Read for search. `pytest -x --tb=short` for tests. Read only when you need full file context.

---

## Codebase Landmarks

- **Shared modules:** `scripts/_*.py` (e.g., `_hindi_validators.py`, `_funny_shorts_common.py`, `_elevenlabs_common.py`, `_hindi_qa_critic.py`)
- **Content generators:** `scripts/generate_*.py`
- **Daily pipeline:** `scripts/pipeline_run.py` (EN), `scripts/pipeline_run_hi.py` (HI)
- **Mirror helpers:** `scripts/*_mirror.py` (write to `seed_output/content.json`)
- **Per-content data:** `data/<type>/<id>.json`
- **Master mirror:** `seed_output/content.json` (LIST, 225 items)
- **API service:** `app/services/local_store.py`
- **Migration spec docs:** `docs/superpowers/specs/*.md`
- **Tests:** `scripts/test_*.py`

---

## Production Path Routing

nginx aliases override the default cover/audio path mapping for specific content subpaths. **Repo state does not equal production state.**

**Default:**
- `/covers/` → `/opt/dreamweaver-web/public/covers/`
- `/audio/` → `/opt/dreamweaver-web/public/audio/`

**Overrides** (covers/audio served from `/opt/cover-store/` and `/opt/audio-store/`, which persist across deploys and re-clones):
- `/covers/funny-shorts/` → `/opt/cover-store/funny-shorts/`
- `/covers/funny-shorts-hi/` → `/opt/cover-store/funny-shorts-hi/`
- `/covers/poems/` → `/opt/cover-store/poems/`
- `/audio/funny-shorts/` → `/opt/audio-store/funny-shorts/` (verify against nginx config; subdir name may differ)
- `/audio/pre-gen/` → check nginx config before assuming

### Diagnostic rule

Before claiming a file is missing or broken in production, check the **live serving path**:

1. Read the relevant nginx site config (`/etc/nginx/sites-enabled/*`) to find the actual alias
2. `ls` the aliased directory on prod
3. `curl -I` the public URL to confirm 200 response

The repo's `public/` tree is **volatile** for covers/audio of the override-listed content types — files there get deleted by pipelines, regenerated, or never tracked. The cover-store and audio-store directories on prod are the **source of truth** for what's actually serving.

`scripts/deploy_guard.py` knows about these stores (`COVER_STORE = "/opt/cover-store"`, `AUDIO_STORE`) and auto-recovers missing files from them during `verify`.

### Structural-first principle for large data-file diffs

For large data-file diffs (>1000 lines), **check structural deltas first** — item counts, ID set differences, schema changes — before sampling individual hunks. Sampling tells you about changes you saw; it cannot tell you about changes the sample missed. The `content.json` reconciliation of 2026-04-28 missed 92 new entries because the sample saw only encoding-style differences.

Concretely, for any JSON list/map under `data/` or `seed_output/`:

```python
old = json.loads(subprocess.check_output(["git", "show", f"{old_ref}:{path}"]))
new = json.loads(subprocess.check_output(["git", "show", f"{new_ref}:{path}"]))
print(f"old items: {len(old)}, new items: {len(new)}")
old_ids = {x['id'] for x in old}; new_ids = {x['id'] for x in new}
print(f"only in old: {len(old_ids - new_ids)}, only in new: {len(new_ids - old_ids)}")
```

Run that **before** sampling hunks. If the structural delta is non-trivial, the diff isn't what it looks like at the line level.

---

## Content Invariants — Hindi

- **Roman script ONLY** in user-facing fields (title, dialogue text, card labels, descriptions).
- **No Devanagari (U+0900–U+097F)** anywhere user-facing.
- **Conversational register.** Ban literary Hindi: `nidra`, `nakshatra`, `shayan`, `tandra`, `pushp`, `chandra`, `megh`, `van`, `vidyalay`.
- **Hinglish is welcome and natural** — kids say "school", "phone", "okay", "homework", "cousin", "actually".
- **"Tum" between characters.** Kids don't use formal "aap".

## Content Invariants — Universal

- No religious content (deity names, ritual verbs, religious objects).
- No caste references or regional stereotypes.
- No body-shaming language (`motu`, `lambu`, `kalu` forbidden).
- No real brands (Parle, Cadbury, Amul, Hershey, Oreo, McDonald's).
- No celebrity, cricketer, or film references.
- No fear-based comedy (jump scares, monsters).
- **Anti-template enforcement is non-negotiable.** When validators check rotation across recent items (opening tags, comedic devices, settings, closing patterns), do not weaken these checks to ship content. If Mistral can't produce variety, regenerate or expand the device list — don't loosen the rule. Catalog convergence to a formula is a stronger failure mode than a single short failing validation.

---

## Validators — MUST run before audio generation

All return `list[str]` (empty = pass, non-empty = error messages).

| Type             | Function              | File                                |
|------------------|-----------------------|-------------------------------------|
| short_stories HI | `validate_short_story` | `scripts/_hindi_validators.py:117` |
| long_stories HI  | `validate_long_story`  | `scripts/_hindi_validators.py:191` |
| lullabies HI     | `validate_lullaby`     | `scripts/_hindi_validators.py:293` |
| silly_songs HI   | `validate_silly_song`  | `scripts/_hindi_validators.py:335` |
| musical_poems HI | `validate_poem`        | `scripts/_hindi_validators.py:390` |
| funny_shorts EN  | `validate_funny_short` | `scripts/_funny_shorts_common.py:188` |
| funny_shorts HI  | `validate_funny_short` | same, with `lang='hi'` |

English `short_stories` and `long_stories` have no validators yet. If asked to add one, follow the `_hindi_validators.py` pattern.

**On non-empty error list:** regenerate (up to 3 attempts), then route to QA critic if Hindi short story, else surface failure. **Never loosen the validator to make content pass.** Tightening or relaxing validator thresholds requires its own task with explicit user approval and a 5+ generation test sample — never inline as part of "fixing" a failure.

---

## Audio Engines — Production Truth

| Type             | Engine                | Model / Endpoint                    |
|------------------|-----------------------|-------------------------------------|
| stories EN       | ElevenLabs v2         | `eleven_multilingual_v2`            |
| stories HI       | Chatterbox (Modal)    | gated by `lang == 'en'` check       |
| funny_shorts     | ElevenLabs v3         | `text-to-dialogue` endpoint, `eleven_v3` |
| lullabies HI     | MiniMax v2 (FAL)      | `minimax-music-v2`                  |
| silly_songs HI   | MiniMax v2            | same                                |
| poems HI         | MiniMax v2            | same                                |

- Migration design doc: `docs/superpowers/specs/2026-04-27-english-tts-elevenlabs-migration-design.md`
- Shared TTS module: `scripts/_elevenlabs_common.py`
- **Cover generation:** FLUX (Together AI) via `scripts/generate_funny_short_cover.py` (funny shorts) and `scripts/generate_cover_experimental.py` (other content types). Don't reinvent — use these.

### CRITICAL: Manual invocations need the env var

**Never invoke `pipeline_run.py` manually without `TTS_ENGINE_EN=elevenlabs`.**

Code default is `chatterbox` (defensive fallback). The production cron sets the env var inline:

```
30 1 * * * cd /opt/dreamweaver-backend && TTS_ENGINE_EN=elevenlabs /usr/bin/python3 scripts/pipeline_run.py --lang en ...
```

Manual invocations that omit the env var **silently regress to Chatterbox**. Same applies to:
- `scripts/generate_audio.py`
- `scripts/generate_long_story_episode.py`

Until the code default is flipped to `elevenlabs` (planned follow-up), every manual run requires the env var.

---

## Deploy Guard

Run before and after any production-affecting change:

```bash
python3 scripts/deploy_guard.py snapshot   # before
python3 scripts/deploy_guard.py verify     # after
```

Other subcommands: `check`, `seal`, `audit`, `recover --dry-run`, `invariants --auto-recover`.

### State-mutating script invocations require snapshot + verify

The same discipline as code deploys. A script that changes prod data is the same class of risk as deploying code that runs against prod data.

Examples requiring `snapshot` BEFORE and `verify` AFTER:

- `merge_username_collisions.py --merge`
- `invalidate_old_tokens.py`
- `downgrade_canceled_subscriptions.py` (when run manually outside cron)
- `reconcile_stripe_state.py --apply`
- `prune_stripe_webhook_events.py` (when run manually)
- Future migration / data-fix scripts

Cron-driven invocations are exempt — the cron schedule is the deployment, and these scripts are designed to be idempotent. Manual invocations of the same scripts get the snapshot+verify treatment.

### Frontend deploys are NOT automatic for dreamvalley.app

Production-only architecture. GitHub is the code repository. Prod pulls from GitHub. No staging environment.

**Production at `dreamvalley.app` is served from PM2 + Next.js standalone on the GCP VM** and requires a manual deploy after pushing code:

```bash
gcloud compute ssh dreamvalley-prod --project=strong-harbor-472607-n4 --zone=asia-south1-c
cd /opt/dreamweaver-web && git pull
sudo npm run build
sudo cp -r public .next/standalone/public
sudo cp -r .next/static .next/standalone/.next/static
sudo pm2 restart dreamweaver-web
```

Do not claim a frontend fix is "deployed" until these steps complete. A successful `git push` proves the code is on GitHub, not that users see it.

## DEPLOY_GUARD VIOLATIONS

**Any violation flagged by deploy_guard is a blocker.** This includes:

- Asset missing
- Content count regression
- Schema drift
- Path drift
- Mirror inconsistency
- Anything else deploy_guard reports as a problem

**Do NOT do any of these:**

- "This is a pre-existing issue, not from my changes" — fix it anyway.
- "This was already broken before I started" — fix it anyway.
- "Outside the scope of my task" — fix it anyway.
- "I'll flag it as a follow-up" — fix it anyway.

If deploy_guard flags something, it's part of the current task. Fixing it is the cost of shipping. **The task is not done until `deploy_guard verify` is clean.**

If a fix would require architectural change beyond reasonable scope, surface it explicitly:

> deploy_guard flagged X. Fix requires Y. Should I proceed with the fix or pause for direction?

Never proceed past a violation without explicit approval. Pre-existing violations exist because previous sessions skipped them. Don't continue the cycle.

---

## Definition of Shipped (for content)

1. Validator returns empty list (no errors).
2. Audio renders to expected path.
3. Cover renders to expected path.
4. Entry written to `data/<type>/<id>.json`.
5. Mirror to `seed_output/content.json` with `type` / `subtype` / `lang`.
6. Reload prod via `POST /api/v1/admin/reload` (manual, not automated yet):

   ```bash
   curl -X POST https://api.dreamvalley.app/api/v1/admin/reload \
     -H "X-Admin-Key: $ADMIN_API_KEY"
   ```

   `ADMIN_API_KEY` is set in `/opt/dreamweaver-backend/.env` on prod. For local invocation, `source` that env or pass the value inline. Standalone scripts (`generate_long_story_episode.py`, cover gen) update seed only — without this curl, the live API keeps serving stale data.

---

## QA Critic State (Hindi)

- `HINDI_QA_ENABLED=true` on prod.
- `HINDI_QA_TYPES=short_story` — scoped to short stories only.
- Other Hindi types are **not** gated through QA. Don't assume QA runs on lullabies / songs / poems unless `HINDI_QA_TYPES` is updated.

---

## content.json Structure

- Top-level is a **LIST**, not a dict (225 items as of 2026-04-28).
- Type field values: only `story`, `long_story`, `song`, `poem`.
- Lullabies and silly_songs are both stored as `type=song`, distinguished by `subtype`.
- Funny shorts: `type=song`, `subtype=funny_short`.
- Musical poems: `type=poem`.

### Subtype semantics — UI must NEVER treat `type=song` as "lullaby"

Three distinct user-visible categories share `type=song`:
- `subtype=funny_short` → Funny Shorts (have baked dialogue audio + visual emphasis)
- `subtype=silly_song` → Silly Songs (MiniMax-generated music)
- `subtype` absent or `lullaby` → actual Lullabies

**Generators MUST set `subtype` on every emitted item.** Items missing `subtype` are inferred to be lullabies (legacy behavior), so any generator that emits a non-lullaby `type=song` without a `subtype` will silently render as a lullaby on the frontend. This was the root cause of the 2026-04-28 production bug where 5 funny shorts appeared in the Loriyaan / Lullabies row.

Frontend mirror: `dreamweaver-web/src/utils/contentTypes.js` is the single source of truth for predicates (`isLullaby`, `isFunnyShort`, `isSillySong`) and display labels. UI code never checks `item.type === 'song'` directly. Adding a new subtype requires updating that file plus updating the relevant generator to set the field.

`SEED_PREFERRED_FIELDS` (in `app/services/local_store.py`) — these are force-synced from `seed_output/content.json` on each boot, overwriting runtime values:

```python
{"cover", "musicParams", "audio_variants", "mood", "musicalBrief", "story_type",
 "lang", "title_en", "description_en", "cover_description_en",
 "repeated_phrase", "conversational_score"}
```

---

## Known Production Drift (don't add to; document for cleanup)

- `public/covers/` has both `silly-songs/` and `silly_songs/`. Use **hyphen** (`silly-songs/`) as canonical. Follow-up task to consolidate.
- Code default for `TTS_ENGINE_EN` is `chatterbox`; prod runs on `elevenlabs` via cron env. Follow-up task to flip the code default.
- Cosmetic: `generate_long_story_episode.py` logs "Generating TTS via Chatterbox..." even when ElevenLabs is the active engine. Stale label from pre-migration code; not a regression.

---

## Parallel Scripts Pattern (NOT `--lang` flags)

For Hindi / English variants, use parallel scripts:

```
scripts/generate_funny_shorts.py      # English
scripts/generate_funny_shorts_hi.py   # Hindi
scripts/_funny_shorts_common.py       # shared module
```

This enforces "English code never touched when working on Hindi" at the file level. **Don't propose unifying via a `--lang` flag.**

**Why:** a single `--lang` flag means an edit to fix Hindi can break English in the same commit. Parallel scripts make that impossible at the file level. The duplication is the safety mechanism.

---

## General Principle

Code defaults should match production behavior. When you find a divergence between `os.getenv("X", "default_a")` and what production actually uses, flag it. The right fix is to make the code default match production reality, with overrides reserved for explicit non-production scenarios.

---

## NEVER DO

### Content rules

- Generate Devanagari content for user-facing fields.
- Add festival or religious content to Hindi shorts / songs / poems.
- Add real-world brands, celebrities, or pop-culture references to any content type.
- Use `[grinning]` or other non-laughter tags as the final line of funny shorts (no real laugh audio produced).

### Engine rules

- Use Chatterbox for new English content (migration is the direction).
- Use MiniMax v1.5 for Hindi (failed native phoneme test).
- Run `pipeline_run.py` manually without `TTS_ENGINE_EN=elevenlabs`.

### Process rules

- Cross-edit Hindi and English code in the same commit.
- Skip the `deploy_guard snapshot` before prod changes.
- Tighten validator thresholds based on initial test samples (test in 5+ generations before locking).
