# Long-Story Generation Redesign — Design Spec

- **Date:** 2026-07-02
- **Status:** Approved design; implementation pending. Batch is a text-only /tmp generation gated on human batch-read before any prod deploy.
- **Scope:** EN `scripts/generate_long_story_episode.py` + HI `scripts/_hindi_generators.py` (`_long_story_prompt`) + HI axis picker `scripts/_hindi_diversity.py`. New shared module `scripts/_story_axes.py`. New validator module `scripts/_physiology_validators.py` + `scripts/test_physiology_validators.py`.

## 1. Problem (diagnosis the design is built against)

The six most-recent production long stories (3 EN, 3 HI, across ages/moods) share ONE skeleton: protagonist notices a stilled thing → asks why → wise companion says "not lost/broken, just resting" → breathing settles it → all sleep. Verified at code + output level:

- **Hardcoded breathing cue surfaces verbatim.** EN prompt `THE BREATHING MECHANIC` block literally contains *"In through the nose, slow and deep... out through the mouth, soft as a whisper."* — appears word-for-word in EN_1 (x2) and EN_3 (x2). HI hardcodes *"khoya nahin, so raha tha."*
- **Hardcoded resolution.** EN: *"The answer to the mystery is ALWAYS rest, sleep, peace, quiet."* HI: *"The mystery's reveal is ALWAYS rest."* All six land on "it was tired / just resting."
- **Untracked cast → same faces.** HI has no cast axis → **Bulbul the wise bird in all three HI stories.** EN name-recency is weak → **Zari** headlines two consecutive EN nights.
- **Identical Phase-3 staccato** and trailing dots in every story.
- **Root cause (code-verified):** `DIVERSITY_RECENCY = {world_type:5, mystery_type:4, breathing_mechanic:6, repeated_phrase_feeling:6}`. Every tracked axis is a surface prop a child does not consciously register. The meaning-bearing axes — resolution, narrative shape, emotional texture, cast structure, breath expression — are hardcoded prompt constants, so they never vary. **Untracked = defaults to one value = monotony.**

## 2. Layer Architecture

Two layers compose into one prompt.

### Layer A — DESCENT PHYSIOLOGY (fixed, sacred, identical every story, EN + HI)

Not hardcoded prose. A set of **invariants** stated once as a `PHYSIOLOGY CONTRACT` block in every prompt AND enforced by post-gen validators:

- **A1 — Monotonic arousal descent.** After the opening, arousal (stakes/excitement/activation) only decreases. No spike, reversal, cliffhanger, or "and then suddenly." Peak engagement is the first ~20%.
- **A2 — Prosody slows.** Sentence length and clause complexity shrink across the final third; the last ~10% is short declaratives.
- **A3 — Exhale lengthens.** The load-bearing fact. Every breath beat is short-in / long-slow-out; the out-breath is the longer, softer half, and the world softens on the out-breath.
- **A4 — Ending dissolves, never resolves-to-alertness.** No triumphant solve, no waking-up-energized, no bright button. The close fades to stillness.

**Governing principle: any structure is legal iff it passes Layer A.** This is what licenses structural boldness. The validators (§7) are the actual sleep guarantee, so they must bite (§8).

### Layer B — STORY (variable, tracked)

Six axes (five picked + one derived), each with a recency window (§4). Picker selects Layer B avoiding recency → builds a `STORY SPEC` → concatenated with the fixed `PHYSIOLOGY CONTRACT` → one prompt. Same shape EN + HI; language-specific concerns (Roman-Hindi rules, matra caps) stay local and orthogonal.

## 3. Shared Axis Module (anti-drift keystone) — refinement #3

New file `scripts/_story_axes.py`, language-neutral, imported by BOTH generators so the meaning-bearing axes are defined ONCE and cannot re-diverge:

```
RESOLUTION_MEANINGS   # key -> {desc, en_hint, hi_hint}
NARRATIVE_SHAPES      # key -> {desc, en_hint, hi_hint}
EMOTIONAL_TEXTURES    # key -> {desc, en_hint, hi_hint}
CAST_STRUCTURES       # key -> {desc, en_hint, hi_hint}
PHASE3_TEXTURES       # key -> {desc, en_hint, hi_hint}
BREATH_EXPRESSIONS    # world-family -> breath-verb phrasing (en_hint, hi_hint)
DIVERSITY_RECENCY_SHARED   # windows for the new axes
SHAPE_AGE_MOOD_RULES  # exclusion rules (§5)
PHYSIOLOGY_CONTRACT_EN / PHYSIOLOGY_CONTRACT_HI  # the fixed A1–A4 block, one per language, same 4 invariants
def eligible_shapes(age, mood) -> list[str]
def pick_avoiding_recent_clamped(existing, key, eligible_pool, window) -> str
def select_story_axes(existing, age, mood, world_family) -> dict
```

Each axis value carries an `en_hint` and `hi_hint` (a short guidance phrase in-language). The KEY (semantics) is shared; only the surface phrasing is per-language. World/mystery/mechanic pools stay language-local (they already legitimately differ: EN `STORY_WORLDS`, HI `LONG_STORY_WORLDS`). EN merges `DIVERSITY_RECENCY_SHARED` into its existing `DIVERSITY_RECENCY`; HI reads the same shared windows in `_hindi_diversity.py`.

## 4. New Tracked Axes + Recency Windows

Window ≈ (pool − 1) so the whole pool cycles before repeating. **Effective window is clamped** to `min(configured_window, len(eligible_pool) - 1)` — this is the starvation guard (§5).

| Axis | Pool | Window | Values |
|---|---|---|---|
| `resolution_meaning` | 6 | 5 | was_resting · went_home · finished_its_work · became_something_quieter · was_always_there · was_waiting_for_you |
| `narrative_shape` | 5 | 4 | investigate_resolve · arrival · circular · nested · pure_settling |
| `emotional_texture` | 6 | 5 | tender · awe · cozy_safe · wistful_sweet · playful_fading · reverent_quiet |
| `cast_structure` | 5 | 4 | solo · mentor_pair · peer_pair · small_group · found_companion |
| `phase3_texture` | 4 | 3 | descending_length · repetition_litany · sensory_subtraction · breath_countdown |
| `breath_expression` | derived from world | 4 (on breath-verb) | see §6 |

The current single values (`was_resting`, `investigate_resolve`, `mentor_pair`, `descending_length`) are kept but demoted to 1/N. `emotional_texture` is distinct from the 6 MOODS: mood = child's incoming state; texture = story's color (a wired child may receive a reverent_quiet story). Existing axes retained: world(5), mechanic(6), phrase-feeling(6), name(10), age(2). `mystery_type` becomes N/A for `pure_settling`/`nested` (picker sets null; prompt omits the mystery section). EN name-avoidance strengthened to a hard "MUST NOT be any of" list (Zari repeat), matching HI's banned-names inject.

## 5. Picker Enforcement + Starvation Analysis — refinement #2

Restrictions are enforced by **pool exclusion in the picker**, not prompt hints:

```
SHAPE_AGE_MOOD_RULES:
  nested:        allowed only for age in {6-8, 9-12}      # 2-5 cannot hold two story levels
  pure_settling: allowed only for mood in {calm, sad, anxious}  # wired needs capture
```

`eligible_shapes(age, mood)` = `ALL_SHAPES` minus any excluded by the rules. `select_story_axes` then applies `pick_avoiding_recent_clamped` **within the eligible pool**. Recency is clamped to `min(window, len(eligible) - 1)`, guaranteeing ≥1 candidate always → **no deadlock and no fallback-to-full repeat-adjacent risk.** (Existing `_pick_avoiding_recent` also falls back to the full pool if exhausted; the clamp makes fallback unnecessary.)

Worst-case eligibility (shapes pool = 5):

| age | mood | excluded | eligible shapes | clamp window | ≥1? |
|---|---|---|---|---|---|
| 2-5 | wired | nested, pure_settling | arrival, circular, investigate_resolve (3) | min(4,2)=2 | ✓ |
| 2-5 | calm | nested | arrival, circular, investigate, pure_settling (4) | min(4,3)=3 | ✓ |
| 6-8/9-12 | wired | pure_settling | 4 | min(4,3)=3 | ✓ |
| 6-8/9-12 | calm | — | 5 | 4 | ✓ |

Lowest eligibility is 3 (2-5 + wired), still ≥1 → no starvation. Both capture shapes (arrival, investigate_resolve) remain available for wired at every age ✓. Other new axes have no age/mood exclusion; clamp keeps them ≥1.

## 6. Breathing Emergence — refinement #3 (breath)

**Delete the hardcoded verbal cue from both prompts.** WHAT/HOW split:

- **Physiology (WHAT, fixed, A3):** "When a breath beat occurs, the in-breath is brief; the out-breath is long and slow; the world softens on the out-breath." Pace is locked, so varying the dressing can never speed breathing up.
- **Story (HOW, per-world):** breath is the physics of this world. `BREATH_EXPRESSIONS` maps world-family → phrasing:
  - tide/water → *the tide slides out as you breathe out, waits as you breathe in*
  - lantern/light/beam → *the light swells on the out-breath, rests on the in*
  - creature → *the sleeping creature's sides rise; your breath falls into step*
  - garden/flower → *petals open on the long breath out, gather on the in*
  - transport → *the engine sighs out on the out-breath, gathers on the in*

**Keep the non-verbal `[BREATHE]` swell tag** (wordless exhale pacer — physiology). Remove only the verbal narrator instruction / `[BREATHE_GUIDE]` fixed cue. `[BREATHE]` tags become the validator anchor for A3 (§7). `breath_expression` inherits the world's window plus a window-4 recency on the breath-verb.

## 7. Structural Changes + Physiology-Preservation Arguments

Current `INTRO→P1→[SONG]→P2→P3` stays the default; shapes may override. Each change carries its safety argument:

- **(a) Mid-song shape-dependent + arc-capped.** For `arrival`/`pure_settling`, the mid-song is replaced by an end-leaning wordless hum inside the dissolution. For `investigate_resolve`/`circular`, a mid-song is allowed but its arc is **capped flat-or-descending** (no key-change lift, no tempo rise). *Physiology:* a song threatens A1 only if it lifts arousal; capping the arc or moving it late means arousal never rises → A1 preserved; A2–A4 untouched.
- **(b) `arrival`.** *Physiology:* lower baseline arousal than investigate (barely an "up"), so A1 trivial; the arrived thing settling is a natural dissolve (A4). Hold attention via sensory richness, not stakes.
- **(c) `circular`.** *Physiology:* closure via familiarity, not alertness; "same place, now still" is inherently a dissolve; prosody still shrinks toward the reprise (A2). Instruct "recognition, not twist" so it can't spike A1.
- **(d) `nested`.** *Physiology:* triple reinforcing descent (tale winds down / teller slows / child follows); teller trails off = A4. Restricted to 6-8/9-12 (§5).
- **(e) `pure_settling`.** *Physiology:* purest descent — no tension ever introduced. Restricted to calm/sad/anxious (§5); wired routed to arrival/investigate.
- **(f) `phase3_texture` variation.** Keep the function (A2 prosody-slow), vary the form across 4 options. Each form is defined to end shorter and quieter than it starts → A2/A4 preserved by construction.

## 8. Validators — the sleep guarantee, and they must BITE — refinement #1

New module `scripts/_physiology_validators.py`. Each validator returns `(ok: bool, reason: str)`. All run text-only on generated output before it is ever accepted; a failure rejects the story (regenerate).

**Tag anchors available:** `[INTRO]`, `[PHASE_1|2|3]`, `[BREATHE]` (breath beats), `[WHISPER]…[/WHISPER]` (final block), sentence splitting on `.?!…` and Hindi danda-equivalents. "Back half" = sentences after the `[PHASE_2]` marker, or after the 50% sentence index if markers absent.

### A1 — arousal does not rise after the opening

Measures AROUSAL (activation), not sentence length. Concrete:
- **Arousal lexicon** (EN + HI): suddenly/achanak, quickly/jaldi, raced/bhaaga, shouted/chillaya, burst/phat, danger/khatra, scared/dara, urgent, faster/aur tez, louder/aur zor, chase/peechha, panic, jumped/leapt/kooda, plus `!` and ALL-CAPS shout tokens, and cliffhanger connectives ("but then", "all at once", "tabhi achanak").
- Split into deciles by sentence index. Arousal density = markers / words per decile.
- **Rule (conjunction):** (i) max arousal density over back-half deciles ≤ arousal density of the opening peak decile; (ii) no decile after the midpoint exceeds the running minimum-so-far by >1.5× (spike guard); (iii) zero `!` and zero cliffhanger connectives in the back half. Fail if any clause is violated.

### A2 — prosody slows

- Mean words/sentence per decile. **Rule:** (i) last-decile mean ≤ 6 words; (ii) final-third mean ≤ 0.6 × first-third mean; (iii) linear slope over deciles < 0. Fail if any violated. (Word-count based; HI matra caps handled by existing per-sentence caps.)

### A3 — exhale ≥ inhale, on EMERGENT breath

The hard one. How the validator FINDS the beat with no fixed cue:
- **Anchor:** every breath beat must carry a `[BREATHE]` tag (generation requirement; validator first checks `[BREATHE]` count ≥ 3 and that ≥1 falls in the back half — breath present during descent).
- **Breath sentence** = a sentence containing a breath-verb from a controlled lexicon (breathe in/out, in-breath/out-breath, draw in/let out, rise/fall, gather/release; HI: saans andar/bahar, andar lo/chhodo, andar/bahar) OR within one sentence of a `[BREATHE]` tag.
- For each breath sentence, split into the **in-clause** (marked by in / andar) and **out-clause** (out / bahar / chhodo). **Rule:** (i) in-clause appears before out-clause (order); (ii) `len(out_clause_words) ≥ len(in_clause_words)` — the prose dwells longer on the exhale, the textual proxy for the longer physiological out-breath. Fail if any breath sentence violates, or if breath beats are absent.

### A4 — ending dissolves, not resolves-to-alertness

Avoids the vacuous-matcher trap (a sleep word present anywhere ≠ dissolving ending). Concrete:
- **Final section** = last `[WHISPER]` block, else last 10% of sentences.
- **Banned alertness lexicon in final section:** woke/awake/jaag gaya, wide-eyed, jumped up/sprang/kooda, energized, ready to go, excited, hurray/cheered/victory/won, solved-it, `!`, and future-reactivation ("tomorrow they would…", "kal phir").
- **Rule (conjunction):** (i) zero banned-alertness tokens in the final section AND (ii) ≥1 stillness/sleep terminal marker in the final section (asleep/sleeping/still/quiet/dark; so raha/rahi hai, neend, shaant, thami). Fail if either clause is violated. The scan is scoped to the FINAL section only.

### 8.1 Bite-tests (`test_physiology_validators.py`)

Each validator gets ≥1 crafted PASS fixture and ≥1 crafted FAIL fixture; the harness asserts the validator ACCEPTS clean and REJECTS the violation. A validator that does not reject its violation is false safety and blocks the build.

- **A1 fail fixture:** clean descent with a back-half injection: *"Suddenly, a loud CRASH shook the room! 'Run!' she screamed, and everything raced faster and faster."* → back-half arousal spike + `!` → MUST fail. PASS fixture: same story without the injection.
- **A2 fail fixture:** ending in long flowing 18–22-word sentences (no shrink) → last-decile mean high, slope ≥ 0 → MUST fail. PASS: ending shrinks to 3–5 words.
- **A3 fail fixtures:** (1) short-out/long-in beat — *"She let the breath go, then drew air in slowly, deeply, filling her chest for a long, long, long time."* (in-clause longer) → MUST fail; (2) a story with zero `[BREATHE]`/breath-verbs → MUST fail. PASS: *"She drew a small breath in. And let it go, slow and long, the tide sliding all the way out."*
- **A4 fail fixture:** *"…and then the sun rose, Zari woke up, wide awake and ready for a brand-new day!"* (waking + `!`, even with earlier sleep words) → MUST fail. PASS: *"The garden breathes. The world sleeps."* / *"…so raha hai."*

## 9. Content-Snapshot Footgun Handling — refinement #4

- The spec commit lands BEFORE any generation → the commit is clean (only the doc). Source-file commits (§10) are staged explicitly by path; never `git add -A` after a generation run.
- Batch generation runs from the isolated clone `~/ls-redesign` with `--text-only` (skip TTS/song/cover/publish), `--output-dir /tmp/ls-batch`, and reads diversity history read-only from real prod (`/opt/dreamweaver-backend/seed_output/content.json`) via an override arg — not the clone's committed (drift-prone) content.json.
- `/opt/dreamweaver-backend` (the live deploy) is never touched. No prod change until the human batch-read gate passes.
- Post-run check: `git status` in the clone must show no staged `content.json`/`seed_output` drift.

## 10. Build Plan

1. **Spec committed** (this doc) in the fresh clone.
2. Build: `scripts/_story_axes.py` (shared axes + picker + physiology contract) → `scripts/_physiology_validators.py` + passing `scripts/test_physiology_validators.py` → EN prompt rewrite (physiology contract + emergent breath + shape branching + arc-cap) in `generate_long_story_episode.py` (merge `DIVERSITY_RECENCY`, wire validators into accept path) → HI rewrite (`_long_story_prompt` + `pick_long_story_axes` + `_hindi_diversity.py`, same axes/windows/validators).
3. **Text-only batch** to `/tmp/ls-batch`, coverage matrix below.
4. **Human reads the full batch** — genuinely different stories at the meaning level, physiology audibly preserved (slowing, long-out-breath, dissolving ending) — before ANY deploy. Strictest gate.

### Batch coverage matrix (target ≥12: 6 EN + 6 HI)

Every `narrative_shape` ≥1, every `resolution_meaning` ≥1, both languages, spanning ages and moods, respecting §5 exclusions. Example allocation:

| # | lang | age | mood | shape | resolution | texture | cast |
|---|---|---|---|---|---|---|---|
| 1 | EN | 6-8 | calm | arrival | went_home | cozy_safe | solo |
| 2 | EN | 9-12 | wired | circular | became_something_quieter | awe | peer_pair |
| 3 | EN | 9-12 | sad | nested | was_always_there | wistful_sweet | found_companion |
| 4 | EN | 2-5 | anxious | pure_settling | was_waiting_for_you | tender | small_group |
| 5 | EN | 6-8 | curious | investigate_resolve | finished_its_work | playful_fading | mentor_pair |
| 6 | EN | 9-12 | angry | circular | was_resting | reverent_quiet | peer_pair |
| 7 | HI | 6-8 | anxious | arrival | was_waiting_for_you | tender | solo |
| 8 | HI | 9-12 | wired | investigate_resolve | went_home | awe | peer_pair |
| 9 | HI | 9-12 | sad | nested | became_something_quieter | wistful_sweet | found_companion |
| 10 | HI | 2-5 | calm | pure_settling | was_always_there | cozy_safe | small_group |
| 11 | HI | 6-8 | curious | circular | finished_its_work | playful_fading | mentor_pair |
| 12 | HI | 9-12 | angry | investigate_resolve | was_resting | reverent_quiet | solo |

All 5 shapes covered (arrival, circular, nested, pure_settling, investigate_resolve) and all 6 resolutions covered, per language span. §5 respected (no nested at 2-5; pure_settling only calm/sad/anxious).

## 11. Out of scope

Audio/TTS, song generation, cover generation, publishing, and the deploy itself are unchanged by this spec and excluded from the batch (text-only). Deploy mechanics (clone→push→pull, deploy_guard snapshot/verify) are handled at deploy time, post-gate.
