# `data/content.json` Architecture Refactor — Per-Content Files as Source of Truth

**Status:** execution-ready (last updated 2026-04-29 UTC)
**Date:** 2026-04-29
**Owner:** Anmol
**Trigger:** Incident session of 2026-04-29 surfaced systematic orphan-content bugs caused by `_auto_mirror`-style helpers being forgotten or skipped (silly_songs and musical poems for ≥9 days; `hi-fs-2956` partial-failure path).

**Scope note (post-simplification, 2026-04-29):** Render and Vercel staging environments are being torn down (see §7). Production is a single GCP VM (`dreamvalley-prod`) with a normal Linux filesystem. Per-content files persist trivially across container restarts via the existing `./data:/app/data` bind mount in `docker-compose.yml`. There is no staging surface to verify against; the cutover is local-test → production directly.

---

## 1. Canonical persistence decision

**Per-content files (`data/<type>/<id>.json`) become the single source of truth.** Both `seed_output/content.json` and `data/content.json` become **derived artifacts**, rebuilt at backend boot (and on admin reload) by walking `data/<type>/` directories.

### New data flow

```
┌──────────────┐    writes only    ┌────────────────────────┐
│  Generator   │ ───────────────▶  │ data/<type>/<id>.json  │  (source of truth)
└──────────────┘   atomic write    └────────────────────────┘
                                              │
                                              │  on boot / admin reload
                                              ▼
                                  ┌────────────────────────┐
                                  │   LocalStore (memory)  │
                                  └────────────────────────┘
                                              │
                                              │  derived snapshot (compat)
                                              ▼
                       ┌─────────────────────────┐  ┌───────────────────────────┐
                       │ data/content.json       │  │ seed_output/content.json  │
                       │ (rewritten each boot)   │  │ (rewritten each boot)     │
                       └─────────────────────────┘  └───────────────────────────┘
```

Concretely:

1. **Generator step.** Generator writes `data/<type>/<id>.json` (atomic temp-file + rename). The `_auto_mirror` / `_upsert_content` step is **deleted**.
2. **Backend boot.** `LocalStore._load_data()` walks `data/<type>/` for each known type, reads each per-content JSON, validates it, and assembles `self.collections["content"]` in memory.
3. **Snapshot write (compat).** After boot, LocalStore writes `data/content.json` and (optionally) `seed_output/content.json` as flat-list snapshots of the in-memory collection. These exist only so external readers (`app/api/v1/analytics.py`, `scripts/sync_seed_data.py`, `scripts/deploy_guard.py`, the seed-mtime trigger in `app/main.py`) keep working without a separate refactor.
4. **Admin reload** (`POST /api/v1/admin/reload` → `LocalStore.reload_content()`): re-walk per-content directories, rebuild in-memory collection, rewrite the two snapshot files.

### Why this eliminates the bug class

The orphan bugs all share the same shape: generator writes `data/<type>/<id>.json` ✅, then forgets / skips the master-mirror upsert ❌, so the API never sees the item. Removing the upsert step entirely makes the failure mode impossible — if the per-content file exists, it's served.

---

## 2. Code changes required

### 2a. Scripts that currently write `content.json` (delete the upsert)

| Script | Function | Line | Action |
|---|---|---|---|
| `scripts/generate_funny_shorts.py` | `_auto_mirror` (def 158, called 350) | 158–~200 | Delete function + call site |
| `scripts/generate_silly_songs_battlecry.py` | `_auto_mirror` (def 1659, called 1655) | 1655–~1720 | Delete function + call site |
| `scripts/generate_experimental_poems.py` | `_auto_mirror` (def 855, called 851) | 851–~910 | Delete function + call site |
| `scripts/_hindi_generators.py` | `_upsert_content` (def 129) | 129–139 | Delete function. Five call sites at 491, 665, 888, 1098, 1558 must be removed (HI short story, lullaby, silly_song, poem, long_story) |
| `scripts/generate_long_story_episode.py` | `publish` block writing `content.json` | 2761–2769 | Replace `content.append(entry); json.dump(...)` with a write to `data/long_stories/<id>.json` |
| `scripts/generate_short_story_experiment.py` | publish block at 596–646 | 596–646 | Same — write `data/stories/<id>.json` instead of appending to seed/content.json |
| `scripts/generate_experimental_v2.py` | "Publish to content.json" at 900–955 | 900–955 | Same — write `data/stories/<id>.json` |
| `scripts/regen_audio_experiment.py` | "Update content.json" at 285+ | 285–end | Update per-content file instead |
| `scripts/classify_moods.py` | `content.json` save at 288 | 33, 288 | Either retire (one-off classifier) or rewrite to update per-content files |
| `scripts/generate_cover_svg.py` | `content.json` save at 323–326 | 40, 316–326 | Rewrite to update per-content files |
| `scripts/generate_cover_experimental.py` | `content.json` patch at 3886–3901 | 3886–3901 | Rewrite to update per-content files |
| `scripts/stitch_lullaby.py` | `content.json` rewrite at 360–371 | 32, 258–371 | Rewrite to update per-content file |
| `scripts/publish_hindi_silly_and_poem_day1.py`, `publish_hindi_batch_day{2,4}.py`, `rerender_hi_long_day1_audio.py` | upserts | various | Likely already-superseded one-off scripts; flag and decide retire vs port |

**Note on per-content directories.** Today only `data/poems/`, `data/silly_songs/`, and `data/funny_shorts/` (on prod) exist. Stories, lullabies, and long_stories are **content.json-only** — the generators skipped writing per-content files. Those generators must be updated to write per-content files (the migration step in §2d backfills the existing entries).

Per-content directory map (canonical) — **every content type splits EN and HI**:
```
data/stories/          → type=story,      lang=en
data/stories_hi/       → type=story,      lang=hi
data/long_stories/     → type=long_story, lang=en
data/long_stories_hi/  → type=long_story, lang=hi
data/lullabies/        → type=song, subtype=lullaby,     lang=en
data/lullabies_hi/     → type=song, subtype=lullaby,     lang=hi
data/silly_songs/      → type=song, subtype=silly_song,  lang=en
data/silly_songs_hi/   → type=song, subtype=silly_song,  lang=hi
data/funny_shorts/     → type=song, subtype=funny_short, lang=en
data/funny_shorts_hi/  → type=song, subtype=funny_short, lang=hi
data/poems/            → type=poem,       lang=en
data/poems_hi/         → type=poem,       lang=hi
```

12 directories total. Lang is fully determined by directory name (suffix `_hi` ⇒ Hindi; otherwise English) — no entry-level lang detection is needed by the walker, though the per-content file SHOULD still carry `lang` for downstream consumers.

> **Decision (resolves former Open Question 1):** ✓ **Split per (type, lang)** — adopted. Matches the "Parallel Scripts Pattern" in `dreamweaver-backend/CLAUDE.md` and mirrors the existing `seed_output/<type>_hi/` audio-master layout (`_hindi_generators.py` lines 420, 601, 790, 1000, 1471). Keeps EN and HI pipelines independently writable / debuggable; an EN bug cannot corrupt the HI directory and vice versa.

### 2b. App code that reads `content.json` today

All current readers are **list consumers** (open file → `json.load` → iterate). They keep working unchanged because we still write a derived snapshot.

| File | Lines | Reads | Notes |
|---|---|---|---|
| `app/services/local_store.py` | 36, 48, 156 | `seed_output/content.json` and `data/content.json` | **Boot path is rewritten** — see §2c |
| `app/api/v1/analytics.py` | 1008, 1082, 1125, 1178, 1215 (`CONTENT_JSON_PATH`) | `data/content.json` | Keep as-is (reads the derived snapshot) |
| `app/api/v1/admin.py` | 26 | (docstring) | No code change — the endpoint already calls `LocalStore.reload_content()`, which now triggers a walk + rebuild + snapshot rewrite |
| `app/main.py` | 61 | seed mtime polling | Keep — polls `seed_output/content.json` mtime for hot-reload trigger. Since we still rewrite the seed snapshot at boot, this keeps working. (Alternative: poll the most-recent mtime across `data/<type>/*.json` — cleaner long-term, but out of scope for this refactor.) |
| `scripts/sync_seed_data.py` | 28 | `seed_output/content.json` | Keep — reads the derived snapshot. Frontend sync is unaffected. |
| `scripts/deploy_guard.py` | (uses `data/content_invariants.json`) | various | Reads invariants metadata, not content.json items per se. Awareness update: the orphan-scan logic becomes trivial post-refactor (every file on disk *is* registered, by definition). But that's a separate task per §8. |

### 2c. The new boot path in `app/services/local_store.py`

**Current behavior** (as of 2026-04-29, lines 42–113):
1. If `data/content.json` exists, load as the runtime list.
2. Iterate `seed_output/content.json` and (a) drop runtime HI items not in seed, (b) add new seed items, (c) backfill missing fields, (d) overwrite `SEED_PREFERRED_FIELDS` from seed.
3. Persist back to `data/content.json` if anything changed.

**New behavior** (proposed):
1. Walk each registered per-content directory (`data/stories/`, `data/long_stories/`, `data/lullabies/`, `data/silly_songs/`, `data/funny_shorts/`, `data/poems/`, plus `_hi` siblings if we go that route).
2. For each `*.json`, parse with try/except — log + skip on failure (don't crash the API on one corrupt file).
3. Stamp the inferred `type` / `subtype` / `lang` from the directory it came from, **only if not already set on the entry** (per-content file remains authoritative when present; directory is fallback inference).
4. Build `self.collections["content"]` from the union.
5. Write `data/content.json` and `seed_output/content.json` as flat-list snapshots (sorted by id for diff stability).
6. Update `_last_seed_mtime`.

**Pseudocode** (replaces lines 42–113 and 144–212):

```python
# Directory → (default type, default subtype, default lang) inference.
# Lang is derived purely from directory name: *_hi suffix ⇒ "hi", else "en".
PER_CONTENT_DIRS = [
    ("stories",          "story",      None,           "en"),
    ("stories_hi",       "story",      None,           "hi"),
    ("long_stories",     "long_story", None,           "en"),
    ("long_stories_hi",  "long_story", None,           "hi"),
    ("lullabies",        "song",       "lullaby",      "en"),
    ("lullabies_hi",     "song",       "lullaby",      "hi"),
    ("silly_songs",      "song",       "silly_song",   "en"),
    ("silly_songs_hi",   "song",       "silly_song",   "hi"),
    ("funny_shorts",     "song",       "funny_short",  "en"),
    ("funny_shorts_hi",  "song",       "funny_short",  "hi"),
    ("poems",            "poem",       None,           "en"),
    ("poems_hi",         "poem",       None,           "hi"),
]

def _walk_per_content(self) -> dict[str, dict]:
    items_by_id: dict[str, dict] = {}
    skipped: list[tuple[Path, str]] = []
    for subdir, default_type, default_subtype, default_lang in PER_CONTENT_DIRS:
        d = self._data_dir / subdir
        if not d.is_dir():
            continue
        for fp in sorted(d.glob("*.json")):
            try:
                entry = json.loads(fp.read_text())
            except Exception as e:
                skipped.append((fp, str(e)))
                continue
            entry["type"] = default_type
            # Subtype is derived from directory at load time.
            # Per-content files MUST NOT contain a subtype field
            # (per Open Question 3 decision — walker-stamped, not on-disk).
            # If a legacy file does carry subtype, log a warning and
            # overwrite with the directory-derived value; load still succeeds.
            if "subtype" in entry and entry.get("subtype") != default_subtype:
                logger.warning(
                    "subtype field present in %s — ignoring on-disk value %r, "
                    "stamping directory-derived value %r",
                    fp, entry.get("subtype"), default_subtype,
                )
            entry["subtype"] = default_subtype  # may be None for stories/poems/long_stories
            # Lang is fully directory-derived (every dir has a definite lang
            # under the per-(type, lang) split). Stamp unconditionally; if an
            # entry already carries a contradictory lang, log and prefer the
            # directory — the directory is the source of truth post-refactor.
            if entry.get("lang") not in (None, default_lang):
                logger.warning(
                    "lang mismatch for %s: file says %s, dir says %s — using dir",
                    fp, entry.get("lang"), default_lang,
                )
            entry["lang"] = default_lang
            entry["language"] = default_lang
            item_id = entry.get("id") or fp.stem
            entry["id"] = item_id
            if item_id in items_by_id:
                # Last-wins, but log — collisions shouldn't happen
                logger.warning("duplicate id %s in %s", item_id, fp)
            items_by_id[item_id] = entry
    if skipped:
        logger.warning("skipped %d corrupt per-content files: %s", len(skipped), skipped[:5])
    return items_by_id

def _write_snapshots(self):
    items = sorted(self.collections["content"].values(), key=lambda x: x.get("id", ""))
    for path in [self._data_dir / "content.json",
                 self._seed_dir / "content.json"]:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False, default=_json_serial))
        tmp.replace(path)  # atomic on POSIX
```

`_load_data()` and `reload_content()` both call `_walk_per_content()` followed by `_write_snapshots()`. The `SEED_PREFERRED_FIELDS` logic **goes away entirely** — there's no longer a "seed vs runtime" split; the per-content file *is* the runtime state.

**Subscriptions and voices** (`subscriptions.json`, `voices.json`) stay on the current load path. They aren't user-content and don't have the orphan problem.

### 2d. One-shot migration helper to backfill missing per-content files

`scripts/migrate_content_to_per_file.py` (new):

1. Load `seed_output/content.json` (222 items as of 2026-04-29 local; 225 per CLAUDE.md as of 2026-04-28; production count must be re-checked at cutover time).
2. For each item, compute target dir from `(type, subtype, lang)`. Mirror `PER_CONTENT_DIRS` above (12 buckets):
   - `type=story, lang=en` → `data/stories/`
   - `type=story, lang=hi` → `data/stories_hi/`
   - `type=long_story, lang=en` → `data/long_stories/`
   - `type=long_story, lang=hi` → `data/long_stories_hi/`
   - `type=song, subtype=lullaby (or absent), lang=en` → `data/lullabies/`
   - `type=song, subtype=lullaby (or absent), lang=hi` → `data/lullabies_hi/`
   - `type=song, subtype=silly_song, lang=en` → `data/silly_songs/`
   - `type=song, subtype=silly_song, lang=hi` → `data/silly_songs_hi/`
   - `type=song, subtype=funny_short, lang=en` → `data/funny_shorts/`
   - `type=song, subtype=funny_short, lang=hi` → `data/funny_shorts_hi/`
   - `type=poem, lang=en` → `data/poems/`
   - `type=poem, lang=hi` → `data/poems_hi/`
3. If `data/<dir>/<id>.json` already exists → diff and warn on schema mismatch, but **do not overwrite** (per-content file is authoritative; we trust it).
4. If missing → write the item from content.json verbatim (ensure_ascii=False).
5. After backfill, run an audit: `len(walk_per_content()) == len(content.json items)` and report the delta.

Local audit run today shows the backfill scope. The audit must report **a 12-bucket breakdown** (each type split by lang), so the cutover gate (§3.1d gate 1) can compare per-bucket counts and not just the global total. Approximate local-checkout numbers (re-run on prod immediately before cutover; numbers will differ):

```
present per-content files (already on disk):
  silly_songs    = 2  EN +  ?  HI
  silly_songs_hi = (dir does not yet exist locally — to be created by migration)
  poems          = 3  EN +  ?  HI
  poems_hi       = (dir does not yet exist)
  funny_shorts   = (prod-only dir; not in local checkout)
  funny_shorts_hi= (prod-only dir; not in local checkout)

missing (must be backfilled):
  stories        = 81 EN
  stories_hi     =  ? HI   (re-measure on prod)
  lullabies      = 77 EN
  lullabies_hi   =  ? HI
  long_stories   = 59 EN
  long_stories_hi=  ? HI
```

That is ~217 backfills locally as a lower bound. The **audit step (`scripts/migrate_content_to_per_file.py --dry-run`, defined here in §2d) must emit the 12-bucket table** above with concrete counts; the cutover gate (§3.1d gate 1) compares each bucket count against the corresponding subset of `content.json` filtered by `(type, subtype, lang)`. A global-only count can mask a routing bug where, e.g., HI lullabies are misrouted to `data/lullabies/` instead of `data/lullabies_hi/`.

> **Decision (resolves former Open Question 2):** ✓ **Quarantine + human ack via CLI** — adopted. Orphans found by the audit-script dry-run are moved to `data/_quarantine/<type>[_hi]/<id>.json` (NOT loaded by the walker) and require per-item triage via `scripts/triage_quarantine.py` before publish. Cutover is gated on the quarantine directory being empty. Full workflow in §3.2.

### 2e. Boot-time concurrency

The new boot path adds a derived-snapshot write step. Two-phase concurrency rules below ensure readers (other processes, in-flight HTTP handlers, the seed-mtime poller in `app/main.py:61`) never see a half-written `content.json`, and no reader observes the API before the in-memory store is fully built.

#### 2e.1. Atomic rename for derived snapshots

Both `data/content.json` and `seed_output/content.json` are written via tempfile + `fsync` + atomic `rename` (already sketched as `tmp.replace(path)` in §2c). Concrete pattern, applied uniformly:

```python
def _atomic_write_json(path: Path, items: list) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False, default=_json_serial)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX; replaces existing target
```

`os.fsync` before rename guarantees the rename either succeeds with fully-flushed bytes on disk or doesn't happen — no torn writes survive a crash. `os.replace` is atomic across the same filesystem (which both files are on, both under `/opt/dreamweaver-backend/`).

The same pattern applies to per-content file writes from generators (already required per §2a — restated here for completeness).

#### 2e.2. Boot sequence ordering

The boot sequence must build the in-memory store BEFORE writing any derived snapshot. Otherwise a reader could observe a snapshot that disagrees with the live API state. Sequence:

1. **Walk** `data/<type>/` directories (per `PER_CONTENT_DIRS` in §2c).
2. **Build** in-memory `self.collections["content"]` dict from the union.
3. **THEN** write the derived snapshot to `data/content.json` and `seed_output/content.json` (atomic, per 2e.1).
4. **Mark API ready** (the FastAPI lifespan / startup completes, healthcheck flips green).

Critically, the API serves from the in-memory store as soon as step 2 is done. The snapshot write in step 3 is for **external consumers only**:
- `app/api/v1/analytics.py` (reads `data/content.json` at request time)
- `scripts/sync_seed_data.py` (frontend bundling, runs in pipeline)
- `scripts/deploy_guard.py` (golden-baseline comparisons)
- `app/main.py:61` mtime poller (uses `seed_output/content.json` mtime as a hot-reload trigger)

The API itself does not depend on the snapshot being current. If step 3 were to fail for any reason (disk full, permission error), the API would still come up correctly — the snapshot write should log + warn but not block readiness. Open consideration: should snapshot-write failure block readiness? Recommend **no** — separation of concerns; surface it via a startup metric instead. Health endpoint could expose `snapshot_last_written_at` for observability.

#### 2e.3. Generator writes during boot

**Out of scope for this refactor:** hot-pickup of generator writes mid-runtime. The flow remains:

> Generator writes a per-content file → that file is picked up on the **next backend boot** OR on the **next admin-reload** (`POST /api/v1/admin/reload`).

There is no inotify/file-watcher mechanism in this design. The seed-mtime poller in `app/main.py:61` continues to act as a coarse trigger (it watches `seed_output/content.json` mtime, which gets bumped on every snapshot rewrite — i.e., on every admin reload). Generators that need their item to appear immediately must call admin-reload, exactly as they do today (per CLAUDE.md "Definition of Shipped" step 6).

This preserves existing pipeline contracts and keeps the refactor surgical. A future task could replace the mtime poller with a directory watcher (`watchdog`/inotify on `data/<type>/*.json`), but that's a separate design — see §8 "Hot-reload trigger redesign".

#### 2e.4. Reader behavior during boot

Investigation note (verified 2026-04-29 against `app/services/local_store.py:26–39`): the existing `LocalStore.__init__` calls `self._load_data()` synchronously. By the time FastAPI's dependency-injected `LocalStore` instance is available to any route handler, `self.collections["content"]` is fully populated. There is therefore **no observable in-progress-load window** under the existing code path — either the import succeeds and the store is ready, or the import raises and the app fails to start. No 503 gate is needed.

The new boot path preserves this property: `_walk_per_content()` + `_write_snapshots()` both run inside `__init__` (or whatever `_load_data()` becomes). FastAPI startup blocks on instantiation, so by the time the first request hits a route, the store is consistent.

**Action:** confirm during code review that `_walk_per_content()` is called from a synchronous code path (not deferred to a background task / asyncio.create_task). If anyone changes that, add an explicit readiness gate (e.g., an `_is_ready: bool` flag on LocalStore, returning 503 from a lightweight startup-probe endpoint until the walk completes).

### 2f. Eliminate publish step entirely

With Render and Vercel staging gone (§7), the daily pipeline's git-push "publish" step has no destination. The 2026-04-29 stopgap `SKIP_PUBLISH_STEP=1` env var that short-circuits these pushes becomes vestigial — delete the publish machinery instead of guarding it.

Concrete deletions, in this same PR (or an immediate follow-up):

- **`scripts/pipeline_run.py`:**
  - Delete the `step_publish` function (approx lines 1994–2080, including the `SKIP_PUBLISH_STEP` env-var guard added 2026-04-29 in commit `43517a8`).
  - Delete the entry `"publish": step_publish` from the `STEPS` registry dict (around line 2633).
  - Delete the string `"publish"` from the `STEPS` step-order list at line 88.
  - Remove `--skip-publish` from the argparse setup if present.
- **`scripts/pipeline_run_hi.py`:**
  - Delete the `_git_commit_and_push` function (lines 53–95).
  - Delete its single call site (around line 234).
  - Remove any `SKIP_PUBLISH_STEP` env-var read.
- **Production crontab on `dreamvalley-prod`:** remove `SKIP_PUBLISH_STEP=1` from both EN and HI cron lines (the env var becomes a no-op once the code is gone, but the crontab should not reference variables that don't exist).
- **Documentation cleanup:**
  - `docs/follow-ups.md` → "Architecture" section, remove any reference to `SKIP_PUBLISH_STEP`.
  - `MEMORY.md` (user auto-memory) → remove any reference if present.
  - Any other docs that mention staging deploys via git push from the pipeline.

**What survives:** `step_deploy_prod` (admin reload + `deploy_guard verify`). That is the canonical "make content live on production" path going forward. It does not push to git.

After this change, the pipeline's terminal step is `step_deploy_prod`. The pipeline never invokes `git push` against any remote.

---

## 3. Migration approach

Order of operations, all running in the cutover window (§4):

1. **Audit (read-only).** Run `scripts/migrate_content_to_per_file.py --dry-run` on the cutover branch, against prod's `data/` and `seed_output/`. Output: list of `(id, target_path, exists?)` tuples. Verify total = `len(content.json items)`.
2. **Backfill.** Run without `--dry-run`. Writes per-content files for every entry currently missing one. After: `find data -name '*.json' | wc -l` should equal `len(content.json)`.
3. **Verify.** Re-run audit; expect zero `missing` rows.
4. **Cutover.** Restart backend with the new code. New boot path walks per-content files, rebuilds `data/content.json` and `seed_output/content.json` snapshots. Diff old-vs-new content.json: should be byte-identical modulo ordering (we sort by id; old file may not be sorted) and modulo trailing whitespace.
5. **Smoke test.** `curl /api/v1/content` returns the same item count and a known sample of items.

The audit + backfill is one-time. After cutover, there's no migration code in the hot path.

### 3.1. Backfill — detailed design

The migration script `scripts/migrate_content_to_per_file.py` (introduced in §2d) is the load-bearing piece of the cutover. The audit found 81 stories + 77 lullabies + 59 long_stories = **~217 entries lacking a per-content file** locally; production count must be re-measured at cutover time. The subsections below pin the schema, idempotency, atomicity, and validation contracts the script must honor.

#### 3.1a. Schema mapping for stories / lullabies / long_stories

The three already-using-per-content types are reference templates for shape. **Each has both EN and HI directories** under the universal split — the HI variants (`data/poems_hi/`, `data/silly_songs_hi/`, `data/funny_shorts_hi/`) follow identical schemas, with `lang="hi"` set by the walker. The locally-observed `hi-…` IDs in `data/poems/` are pre-refactor artifacts; under the new layout, HI poems live in `data/poems_hi/`. Field structures observed locally on 2026-04-29:

**`data/poems/<id>.json`** (EN; HI counterpart at `data/poems_hi/<id>.json` has identical shape) (e.g., `hi-question-6-8-ad89.json`):
- Required: `id`, `title`, `content_type` (= `"poem"`), `poem_type`, `age_group`, `mood`, `instruments`, `tempo`, `poem_text`, `audio_file`, `cover_file`, `duration_seconds`, `audio_engine`, `created_at`
- Optional: `lang`, `title_en`, `cover_context`, `char_count`, `line_count`, `play_count`, `poem_text_deva` (HI only — internal Devanagari, never user-facing)

**`data/silly_songs/<id>.json`** (EN; HI counterpart at `data/silly_songs_hi/<id>.json` has identical shape) (e.g., `ice_cream_2_5.json`):
- Required: `id`, `title`, `age_group`, `category`, `mood`, `lyrics`, `style_prompt`, `instruments`, `tempo`, `cover_description`, `animation_preset`, `created_at`, `audio_file`, `cover_file`
- Optional: `scene`, `play_count`, `replay_count`, `anthem_id`, `anthem`, `battle_cry_id`, `battle_cry`, `generation_method`, `duration_seconds`, `lyrics_deva` (HI)

**`data/funny_shorts/<id>.json`** (EN; HI counterpart at `data/funny_shorts_hi/<id>.json` has identical shape) (production-only directory; not present in local checkout). Schema reference is the generation artifact at `seed_output/funny_shorts_test/english_sandwich_mystery.json` — fields include `title`, `slug`, `voices` (dict of role → voice_id), `inputs` (list of `{text, voice_id}` dialogue lines), `settings`, `model_id`, `audio_bytes`, `elapsed_seconds`, `generated_at`. The published per-content file additionally carries `id`, `subtype="funny_short"`, `lang`, `cover_file`, `duration_seconds`. Verify exact shape on prod by `cat /opt/dreamweaver-backend/data/funny_shorts/<any>.json` before locking the migration map.

**`content.json` entry shape** (sampled from `seed_output/content.json` on 2026-04-29). Common fields across `story` / `long_story` / `song` (lullaby): `id`, `type`, `lang`, `title`, `cover`, `description`, `text`, `target_age`, `age_min`, `age_max`, `duration_seconds`, `author_id`, `created_at`, `updated_at`, `audio_url`, `view_count`, `like_count`, `save_count`, `categories`, `mood`, `musicalBrief`, `audio_variants`, plus type-specific extras (e.g., `[GENTLE]`/`[PAUSE]` markers in `text` for long_stories; `[Verse]`/`[Chorus]` markers for `type=song`).

Field-by-field migration mapping for each backfilled type:

##### `type=story` → `data/stories/<id>.json` (EN) or `data/stories_hi/<id>.json` (HI)

| content.json field | per-content file field | Treatment |
|---|---|---|
| `id` | `id` | Verbatim. Filename stem must equal `id` (validated). |
| `type` | `type` | Verbatim (`"story"`). |
| `lang` | `lang` | Verbatim. Defaults to `"en"` if absent. |
| `title` | `title` | Verbatim. |
| `title_en` (HI only) | `title_en` | Verbatim if present. |
| `description` | `description` | Verbatim. |
| `text` | `text` | Verbatim — preserves `[CHAR_START]`/`[CHAR_END]` markers. |
| `cover` | `cover` | Verbatim. **Trap:** if value is `/covers/default.svg`, propagate as-is — `hasRealCover()` (frontend) handles the truthy-but-not-real case (per MEMORY.md). |
| `target_age`, `age_min`, `age_max` | same | Verbatim. |
| `duration_seconds` | `duration_seconds` | Verbatim. |
| `audio_url` | `audio_url` | Verbatim. May be `null` for older entries — leave as-is; frontend has fallback. |
| `audio_variants` | `audio_variants` | Verbatim (per-mood variant list). |
| `mood`, `musicalBrief`, `musicParams` | same | Verbatim. These are `SEED_PREFERRED_FIELDS` today; post-cutover the per-content file is authoritative. |
| `view_count`, `like_count`, `save_count` | same | Verbatim. |
| `created_at`, `updated_at`, `author_id`, `categories` | same | Verbatim. |
| `experimental_v2`, `has_baked_music`, `story_type` | same | Verbatim if present (V2 short-story flags per MEMORY.md). |
| (derived) | filename = `<id>.json` | Filename = `id`. Atomic write (3.1c). |

Defaults applied if missing on the source entry: `lang="en"`, `created_at=now()` (warn loudly — should not happen for any 2026 content), `view_count=0`, `like_count=0`, `save_count=0`. No transformation/flatten needed.

##### `type=song` (lullaby) → `data/lullabies/<id>.json` (EN) or `data/lullabies_hi/<id>.json` (HI)

Lullabies are entries with `type=song` and **no `subtype`** (or `subtype="lullaby"`). Per the Open Question 3 decision (walker-stamped, not on-disk), `subtype` is NOT written into the per-content file — the walker stamps it from the directory at load time. Field mapping:

| content.json field | per-content file field | Treatment |
|---|---|---|
| `id`, `type`, `lang`, `title`, `description`, `cover` | same | Verbatim. |
| `text` | `text` | Verbatim — preserves `[Verse 1]` / `[Chorus]` / `[Verse 2]` / `[Bridge]` blocks. |
| `subtype` | (omitted) | **NOT included in per-content file schema.** Set at load time by the walker based on directory placement. Backfill helper MUST strip `subtype` before writing, even if the source content.json entry has one. If a legacy per-content file contains a `subtype` field, the walker logs a warning and ignores the on-disk value (per §2c). |
| `target_age`, `age_min`, `age_max`, `duration_seconds` | same | Verbatim. |
| `audio_url`, `audio_variants` | same | Verbatim. |
| `mood`, `musicalBrief`, `musicParams` | same | Verbatim. |
| `view_count`, `like_count`, `save_count`, `created_at`, `updated_at`, `author_id`, `categories` | same | Verbatim. |

Validation: every entry written to `data/lullabies/` (or `data/lullabies_hi/`) must have `type=song` AND (`subtype` absent OR `subtype="lullaby"`) on the **source** content.json entry. Anything with `subtype="silly_song"` or `subtype="funny_short"` must NOT be written here — those route to their respective directories. The migration script reads `subtype` from content.json to make this routing decision, then strips it from the written file.

##### `type=long_story` → `data/long_stories/<id>.json` (EN) or `data/long_stories_hi/<id>.json` (HI)

Long stories use `id` like `gen-308d5f0d1268`. They carry markdown-like emotion markers in `text` (`[GENTLE]`, `[CURIOUS]`, `[CHAR_START]…[CHAR_END]`, `[PAUSE]`, etc.) — these are load-bearing for the audio renderer and must be preserved verbatim.

| content.json field | per-content file field | Treatment |
|---|---|---|
| `id`, `type`, `lang`, `title`, `description`, `cover` | same | Verbatim. |
| `text` | `text` | **Verbatim, including all bracketed emotion markers.** |
| `audio_url`, `audio_variants` | same | Verbatim. Long-story audio paths follow the `audio/long-stories/<id>.mp3` convention. |
| `target_age`, `age_min`, `age_max`, `duration_seconds` | same | Verbatim. |
| `mood`, `musicalBrief`, `musicParams` | same | Verbatim. |
| `view_count`, `like_count`, `save_count`, `created_at`, `updated_at`, `author_id`, `categories` | same | Verbatim. |
| `episode_number`, `series_id` (if present on serialized long stories) | same | Verbatim. |

No directory-derived fields beyond what's already in the entry.

##### Cross-type derivation rules (apply to all three)

- **Filename**: always `<id>.json` (lowercase, slashes/colons forbidden — `id` values audited and confirmed safe). Validated by the script.
- **`audio_file` reconstruction**: NOT performed during backfill. Per-content files for stories/lullabies/long_stories continue to use the `audio_url` field (full URL/path) inherited from content.json, mirroring the existing convention. Do not invent an `audio_file` shorthand for these types — that field is specific to poems/silly_songs/funny_shorts and would create schema drift.
- **`cover_file` reconstruction**: same — keep `cover` (full URL/path), don't add `cover_file`.
- **`subtype` is never written to disk** (per Open Question 3 decision — walker-stamped from directory). The backfill helper MUST strip `subtype` from every entry before writing, regardless of source type. The walker re-derives it from `PER_CONTENT_DIRS` at load time. This applies uniformly to stories (subtype=None), lullabies/silly_songs/funny_shorts (subtype derived from directory), poems (subtype=None), and long_stories (subtype=None). If a legacy per-content file is encountered with `subtype` present, the walker logs an informational warning and overwrites with the directory-derived value; load still succeeds.
- **Ordering**: write keys in a stable order (alphabetical, or follow the source ordering) for diff stability. Recommend: don't reorder; `json.dumps(entry, indent=2, ensure_ascii=False, sort_keys=False)` to preserve content.json's key order.

#### 3.1b. Idempotency rules

The backfill script MUST be safely re-runnable. Concrete requirements:

1. **Skip-if-exists.** Before writing each per-content file, check `path.exists()`. If yes, **skip — do not overwrite**, do not diff-and-merge. This is critical because between two runs, a per-content file may have been edited (manual fix, partial earlier run, an interleaved generator). Overwriting would clobber that work.
2. **Counter logging.** The script logs four counters at the end:
   - `created` — new file written
   - `skipped_exists` — target file already present, untouched
   - `skipped_other_type` — source entry's type/subtype routes to an already-managed directory (e.g., `subtype=silly_song` → `data/silly_songs/` is already populated; skip)
   - `errors` — anything that raised during processing
3. **Exit code.** The script exits non-zero (`sys.exit(1)`) if `errors > 0` OR if final validation (3.1d) fails. Exit zero only when all source entries have a corresponding per-content file on disk and counters reconcile.
4. **No partial state on failure.** If the script aborts mid-run, files already written stay (they're idempotent — next run skips them). No rollback of disk state on script failure; the cutover gate (3.1d) catches mismatches before traffic flips.
5. **`--dry-run` mode.** Walks the same code path but logs intended writes instead of executing them. Used in step 1 of the migration order in §3.

#### 3.1c. Atomicity

Per-content file writes go through tempfile + atomic rename. This matches §2e.1 (snapshot writes) and the generator pattern required in §2a:

```python
import json, os
from pathlib import Path

def _atomic_write_per_content(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    os.rename(tmp, path)  # atomic on POSIX
```

If the script is interrupted mid-write (Ctrl-C, SIGKILL, OOM), the worst case is a leftover `*.json.tmp` file in the target directory. These are harmless — the boot walker matches `*.json` (not `*.tmp`) so they're invisible to LocalStore. Clean them up with `find data -name "*.json.tmp" -delete` between runs if any survive.

#### 3.1d. Validation gates

After the backfill loop completes, before the script exits zero:

1. **Strict count match (per bucket AND total).** Walk `data/<type>/*.json` across all 12 directories in `PER_CONTENT_DIRS`. For each `(dir, type, subtype, lang)` bucket, the file count MUST equal the count of `content.json` items matching that `(type, subtype, lang)` exactly; the total across all buckets MUST equal `len(content.json items)`. Per-bucket mismatch catches a routing bug (e.g., HI lullabies miswritten to `data/lullabies/`) that a global-total-only check would mask. Any mismatch is a **HARD ERROR** — abort cutover, do not flip the API. Investigate the delta (likely an `id`/type routing bug or a content.json entry with `type`/`subtype`/`lang` outside the known map).
2. **Per-item presence check.** For every item in `content.json`, compute its expected per-content path and assert the file exists. Logs every miss. Even one miss aborts.
3. **Optional deep-equality check.** For each content.json item, load the corresponding per-content file and compare field-by-field. Allow documented schema differences (per 3.1a — e.g., the explicit `subtype="lullaby"` stamping). All other fields must match byte-for-byte. Differences logged loudly; this check is informational at first, but should be promoted to a hard gate once the schema map is locked.
4. **Orphan-files quarantine.** Walk `data/<type>/*.json` (live dirs only — `data/_quarantine/` is excluded) and identify any per-content file whose `id` is **not** present in `content.json`. Per the Open Question 2 decision (§3.2), these are physically moved to `data/_quarantine/<type>[_hi]/<id>.json` (preserving the bucket subdirectory name) and listed in the script's report with their original on-disk path. The walker (§2c) does not load `_quarantine/`, so quarantined items do not appear in the API. Triage is performed before cutover via `scripts/triage_quarantine.py` per §3.2 / §4 step 5.

The validation gate is a separate function from the backfill loop. The backfill exits zero only after gates 1–3 pass. Gate 4 always runs (it physically moves orphans to quarantine) but does not block the script's exit code — it surfaces work for the human triage step in §4 step 5.

### 3.2. Orphan quarantine + triage workflow

> **Resolves Open Question 2.** Orphans surfaced during the migration's audit-script dry-run go to a quarantine directory and require explicit per-item human review before being published to live state. No orphan auto-publishes on first boot.

#### Quarantine directory layout

Quarantined orphans live in:

```
data/_quarantine/stories/<id>.json
data/_quarantine/stories_hi/<id>.json
data/_quarantine/lullabies/<id>.json
data/_quarantine/lullabies_hi/<id>.json
data/_quarantine/long_stories/<id>.json
data/_quarantine/long_stories_hi/<id>.json
data/_quarantine/poems/<id>.json
data/_quarantine/poems_hi/<id>.json
data/_quarantine/silly_songs/<id>.json
data/_quarantine/silly_songs_hi/<id>.json
data/_quarantine/funny_shorts/<id>.json
data/_quarantine/funny_shorts_hi/<id>.json
```

Same 12-bucket layout as the live `data/<type>[_hi]/` directories. The walker (§2c `_walk_per_content`) explicitly **ignores** `data/_quarantine/` — items here are NOT loaded into in-memory state and NOT served via API. The walker iterates `PER_CONTENT_DIRS` only; `_quarantine/` is not in that list, so quarantined files are inert until promoted via the triage CLI below.

#### Triage CLI: `scripts/triage_quarantine.py`

A new script that provides per-item human triage of quarantined orphans. (Specified here for the implementing agent to write later; not in scope for this spec.)

**Flags:**

- `--list` — Show all quarantined items, one per line, with: id, type, lang, title, age_group, duration_seconds, audio URL, cover URL, original on-disk path. Sufficient metadata for human judgment without a UI.
- `--publish <id>` — Move from `data/_quarantine/<type>[_hi]/<id>.json` to `data/<type>[_hi]/<id>.json`. Type and lang are auto-detected from the quarantine subdirectory the file is in (which the audit script categorized when quarantining). After move, the next admin reload picks it up live.
- `--discard <id>` — Delete the quarantine entry permanently. No restore.
- `--publish-all --confirm` — Bulk publish all quarantined items. Requires `--confirm` flag explicitly. Prints summary before action.
- `--discard-all --confirm` — Bulk discard all quarantined items. Requires `--confirm` flag explicitly. Prints summary before action.

Each decision is per-item by default; bulk operations require explicit confirmation.

**Behavior notes:**

- The script never moves between language buckets. If an English orphan was misclassified as HI by the audit script, it must be `--discard`ed and regenerated, OR manually moved with `mv` (out of scope for the script).
- The script does NOT trigger admin reload — that is a separate explicit step after triage is complete (per the existing cutover runbook in §4).
- Audio + cover assets associated with quarantined items are NOT moved — they already live in the right serving paths (`/opt/audio-store/`, `/opt/cover-store/`) and serve correctly. The quarantine is purely about the JSON metadata + `content.json` registration.

#### Audit script integration

The migration audit script (§3 step 1, dry-run) already identifies orphans (per-content files with no `content.json` entry, OR `content.json` entries with no per-content file). Update its behavior:

- Items in `content.json` without a per-content file → backfill normally (§3.1).
- **Per-content files NOT in `content.json` (orphans)** → moved to `data/_quarantine/<type>[_hi]/<id>.json` and listed in the script's report. Original on-disk path is logged so they can be restored if needed.

The audit script's dry-run report includes a section like:

```
Orphans quarantined: N
  data/silly_songs/cat_talk_2_5.json → data/_quarantine/silly_songs/cat_talk_2_5.json
  data/poems/question_9_12_92a6.json → data/_quarantine/poems/question_9_12_92a6.json
  ...

Run scripts/triage_quarantine.py --list to review.
```

This replaces §3.1d gate 4's "informational only" treatment of orphans: they are physically moved into `_quarantine/` rather than left in place. The cutover gate below makes triage a hard prerequisite.

#### Cutover gate

Cutover is **not "complete"** until `data/_quarantine/` is empty (every quarantined item is either published or discarded). This is enforced as a §6.5 success criterion and as a step in the §4 runbook.

---

## 4. Cutover plan

### Branch

`feature/content-json-derived` — single branch carrying:
- New `LocalStore._walk_per_content` + `_write_snapshots`
- Deletion of `_auto_mirror` / `_upsert_content` from all generators in §2a
- Generator updates to write per-content files for stories/lullabies/long_stories (new dirs)
- `scripts/migrate_content_to_per_file.py`
- Removal of `step_publish` / `_git_commit_and_push` per §2f (or as an immediate follow-up PR — sequencing is at the implementer's discretion, but neither change has a hard dependency on the other)

### Pre-cutover checklist

1. `python3 scripts/deploy_guard.py snapshot` (mandatory per CLAUDE.md).
2. Local validation: copy prod's `data/` and `seed_output/` into a scratch tree, run new boot path (`python3 -c "from app.services.local_store import LocalStore; s = LocalStore(); print(len(s.collections['content']))"`), diff the resulting `data/content.json` against the original — expect equal sets of ids and equal field-level content.
3. Backup: snapshot `data/content.json` and `seed_output/content.json` to a timestamped path on prod before deploying. Recovery surface — see Rollback below.

### Cutover window

Cutover **after the 04:00 HI cron completes** successfully (~04:30 UTC). This gives ~21 hours of margin before the next 01:30 EN cron — enough headroom to honor the full 24-hour observation window described in §6.5 (or close enough to it without colliding with the next cron) plus ample rollback time.

The earlier-considered 02:00–04:00 EN/HI gap (~90 minutes) is rejected: if a problem surfaces 80 minutes into a 90-minute window, you have 10 minutes to revert before HI cron starts hitting the new code path. The post-HI window doesn't have that pinch.

### Cutover sequence (concrete, step-by-step)

This expands the high-level steps above into a numbered runbook. Execute top-to-bottom; abort at any failed gate.

1. **Window.** Cutover **after the 04:00 HI cron completes** successfully (~04:30 UTC) — see §4 "Cutover window" above for the rationale. Confirm the HI cron's last-run log line before starting.
2. **Pre-cutover snapshot.** `python3 scripts/deploy_guard.py snapshot` — captures the baseline for §4-style verify after cutover. Mandatory per CLAUDE.md.
3. **Backfill.** Run `python3 scripts/migrate_content_to_per_file.py` (no `--dry-run`). Idempotent per §3.1b — safe to re-run if it errors partway. Confirm the script exits zero and prints `created=<N>, skipped_exists=<M>, skipped_other_type=<K>, errors=0`.
4. **Pre-flight gate: count match.** Per §3.1d gate 1: per-content file count across `PER_CONTENT_DIRS` MUST equal `len(content.json items)` exactly. If not — **abort, do not proceed.** Investigate before retrying. The script's exit code already encodes this; double-check manually:
   ```bash
   python3 -c "import json; print(len(json.load(open('seed_output/content.json'))))"
   find data/{stories,stories_hi,long_stories,long_stories_hi,lullabies,lullabies_hi,silly_songs,silly_songs_hi,funny_shorts,funny_shorts_hi,poems,poems_hi} -maxdepth 1 -name '*.json' 2>/dev/null | wc -l
   ```
   These two numbers must be equal. (12 directories — full per-(type, lang) split.)
5. **Triage quarantined orphans.** Review `data/_quarantine/` via `python3 scripts/triage_quarantine.py --list`. For each item, decide `--publish` or `--discard` (per §3.2). After triage, `data/_quarantine/` MUST be empty. The cutover is **blocked** until this is true — verify with `find data/_quarantine -name '*.json' 2>/dev/null | wc -l` returning `0`.
6. **Stop API container.** `sudo docker-compose down` from `/opt/dreamweaver-backend/`. Brief downtime begins here; minimize subsequent steps.
7. **Switch code.** `git fetch && git checkout feature/content-json-derived` (or whichever feature branch carries the merged refactor). NO `sudo git pull` — would change file ownership to root and break the pipeline cron user (per MEMORY.md).
8. **Start container.** `sudo docker-compose up -d --build`. Container rebuilds with new code; LocalStore boots via the new `_walk_per_content` path.
9. **First-boot validation.** Tail logs immediately:
   ```bash
   sudo docker logs -f dreamweaver-backend 2>&1 | head -200
   ```
   Look for: a log line like `LocalStore: loaded N items from per-content files` (add this log if absent) and confirm `N` matches the expected count from step 4 (~240 ± a few). Any `corrupt per-content files` warning means a file failed to parse — investigate but note that the boot succeeded with reduced count (per §6 "Corrupt per-content file" mitigation).
10. **Snapshot diff.** Confirm the regenerated `data/content.json` matches the pre-cutover backup byte-for-byte, modulo encoding normalization:
    ```bash
    diff <(jq -S . data/content.json.bak.<timestamp>) <(jq -S . data/content.json)
    ```
    Differences should be limited to (a) ordering (we now sort by id; old file may not be sorted — `jq -S` normalizes both), (b) `ensure_ascii=False` consistency (already applied 2026-04-29 per `local_store.py:219`), (c) trailing whitespace. Item-level field differences are NOT acceptable here — investigate any such delta before proceeding.
11. **Deploy guard verify.** `python3 scripts/deploy_guard.py verify` — must be clean modulo known-ignored items (Tali, YouTube content per CLAUDE.md). Per CLAUDE.md "DEPLOY_GUARD VIOLATIONS" rule: **any new violation is a blocker.** Do not proceed past verify until clean.
12. **Smoke test.** `curl` 5 random content URLs across types, confirming 200 + correct cover and audio:
    ```bash
    for id in <pick 1 story> <1 long_story> <1 lullaby> <1 silly_song> <1 poem>; do
      curl -sI "https://api.dreamvalley.app/api/v1/content/$id" | head -1
    done
    ```
    Then spot-check the cover and audio URLs returned for each (HEAD request, expect 200).
13. **24-hour observation window.** Watch one full EN+HI cron cycle:
    - 01:30 UTC EN cron → check `data/stories/*.json` and `data/lullabies/*.json` (and any other EN dirs the EN cron writes) for new files; verify they appear in `/api/v1/content` after the post-cron admin-reload (manual today; see CLAUDE.md "Definition of Shipped").
    - 04:00 UTC HI cron → check `data/stories_hi/*.json`, `data/lullabies_hi/*.json`, `data/silly_songs_hi/*.json`, `data/poems_hi/*.json` (per Hindi pipeline coverage). New HI items must land in the `*_hi` dirs, NOT in their EN siblings — a HI-into-EN miswrite is the kind of routing bug §3.1d gate 1 is designed to catch.
    - `python3 scripts/deploy_guard.py verify` should remain clean throughout.
    - No "orphan" alerts (the failure class this refactor is designed to eliminate; see §6.5 "Success criteria").
14. **Success or rollback.**
    - **Clean for 24h** → declare success. Delete the rollback branches and the `*.bak.*` snapshot files (or archive them off-VM). Close the follow-up ticket.
    - **Issues observed** → roll back per "Rollback" subsection below.

### Testing strategy (no staging)

There is no Render or Vercel staging environment to validate against (§7). The validation path is:

1. **Local.** `cp -r /opt/dreamweaver-backend/data /tmp/dv-data-snap` + `seed_output/`, run new boot path against the snapshot, diff the regenerated content.json against the original. Run an end-to-end generator (e.g., `scripts/generate_silly_songs_battlecry.py`) on the local snapshot and verify (a) no `_auto_mirror` call remains, (b) `data/silly_songs/<id>.json` written, (c) restart triggers regeneration of content.json with the new id present.
2. **Production direct.** Once local is clean, follow the §4 cutover sequence on `dreamvalley-prod`. There is no intermediate staging step.

This is acceptable because the per-content files persist on the VM filesystem across container restarts (the `./data:/app/data` bind mount in `docker-compose.yml`), so rollback is fast and stateful — see "Rollback" below.

### Rollback

`feature/content-json-derived` is a **single-commit-on-merge** so revert is one git op.

```bash
# On dreamvalley-prod, in /opt/dreamweaver-backend
git checkout <prior-commit>            # or: git revert <merge_sha> && git push
sudo docker-compose down && sudo docker-compose up -d --build
```

After revert: per-content files remain on disk (no harm done — old code ignores `data/<type>/*.json`). The backed-up `data/content.json` snapshot is restored from `data/content.json.bak.*` and the old code reads it. Old generators (with `_auto_mirror` re-introduced) resume mirror-writes.

The `./data:/app/data` bind mount means per-content files persist across the container down/up cycle by default — no extra preservation step required.

**Caveat:** anything generated *during* the new-code window won't be in the backed-up content.json. If we need to roll back, we'd have to re-derive content.json from the per-content files using a one-off script before the revert (or accept losing whatever was generated in the window — typically nothing if we cutover during a quiet hour and disable cron temporarily).

---

## 5. GitHub as code-only repository

After the staging tear-down and the §2f publish-step removal, GitHub's role in the system collapses to a clean shape: **code only, one direction**.

- GitHub holds **CODE only** — Python scripts, app code, frontend code, config files, docs. Not content.
- **Production pulls code from GitHub** via `git pull origin main` (manually, when deploying code changes per MEMORY.md).
- **Nothing pushes from production back to GitHub.** The pipeline's git-push machinery is removed entirely (per §2f). The cron user (`anmolmohan`) on `dreamvalley-prod` does not invoke `git push` in any pipeline step.
- `seed_output/` and `data/` are gitignored on the backend repo. Currently-tracked entries in those paths get untracked (`git rm -r --cached`) but files remain on disk.
- Frontend repo's `public/audio/` and `public/covers/` are already gitignored as of 2026-04-29 (commit `ed019c9` for covers; audio was earlier). Production-side updates happen via direct pipeline writes to `/opt/audio-store/`, `/opt/cover-store/`, and `/opt/dreamweaver-web/public/audio/` — never via git.
- `src/utils/seedData.js` migration (separate spec, see §8) will further sever any pipeline → git path that survives.

In effect, the only person/process that pushes to GitHub is the developer (Anmol) doing code work from a laptop. The pipeline never touches git push.

---

## 6. Known risks

| Risk | Failure mode | Mitigation |
|---|---|---|
| **Missing per-content file at boot** | Item disappears from API (orphan in reverse) | Backfill script (§2d) runs before cutover and audit asserts `len(per_content_files) == len(content.json items)`; cutover blocked if delta != 0 |
| **Corrupt per-content file** | One bad file kills boot if not handled | Walker catches per-file (try/except per file), logs, skips. Boot succeeds with reduced count + loud warning. Health endpoint surfaces skip count. |
| **Mid-write race during admin reload** | Reader sees half-written file → JSON parse fails | Generators write atomically: `tempfile.NamedTemporaryFile(dir=target_dir)` + `os.replace()`. Reader retries-on-error are unnecessary because rename is atomic on POSIX |
| **External consumers of `data/content.json` see stale snapshot** | Reader gets pre-reload state | Snapshot rewrite is part of `reload_content()` and runs synchronously before the endpoint returns. Polling readers (analytics) read at request time, so they always see current snapshot |
| **Frontend or external system that reads `seed_output/content.json` directly** | Same as above | Enumeration of consumers: `scripts/sync_seed_data.py:28` (frontend sync, runs in pipeline only — re-derive happens on each boot, frontend gets the latest at next sync). `scripts/deploy_guard.py` reads `data/content_invariants.json` (different file). No frontend code reads `seed_output/content.json` directly (frontend reads `seedData.js` which is generated from it). Net: one consumer, one snapshot — fine. |
| **Per-content file inconsistency** (e.g., id in file != id in filename) | Walker resolves id-from-entry, ignores filename. Could lead to two entries pointing at the same id | Walker logs duplicate-id warning; last-wins resolution. Migration script verifies `entry.id == filename.stem` and aborts on mismatch. |
| **`SEED_PREFERRED_FIELDS` semantics lost** | Fields like `cover`, `musicalBrief` were force-overwritten from seed each boot. Without seed-as-source-of-truth, this overwrite no longer happens | The "seed" was always a stale mirror; per-content files now hold the true latest values. The overwrite was a workaround for divergence between seed and runtime — divergence becomes impossible by construction. **Verification:** assert post-cutover that `cover` field across all 225 items matches the value in their per-content file. |
| **Generators that skipped writing per-content files** (stories, lullabies, long_stories today) | Backfill creates them but they're now load-bearing — generator drift could cause writes to one and not the other | Update those generators in this same PR to write per-content files (§2a, last 4 rows). No generator should write to content.json directly post-merge. CI / lint check: `rg "content\.json" scripts/` should return only read-paths and the analytics module. |
| **Race between admin reload and a generator finishing a write** | Reload reads partial set | Two-phase: generator's atomic rename means at any moment, every file on disk is complete. Walker either sees a file or doesn't — never partial. If an item is being generated *during* reload, it shows up on the next reload. Acceptable. |
| **Loss of staging fail-safe** (no Render copy as implicit second-canonical) | A botched cutover or pipeline bug now has only one canonical copy on the GCP VM | VM disk snapshots become the recovery surface (see §7 last item, flagged out-of-scope but important). Plus `*.bak.*` snapshots taken in the §4 cutover sequence. |
| **Legacy per-content files contain on-disk `subtype` field** (from prior generators or hand-edits) | Walker would have to choose between on-disk and directory-derived value | Walker logs a warning at load time and overwrites with the directory-derived value (per §2c walker pseudocode). Does NOT block boot. The warning is informational; the load succeeds with the correct subtype either way. Per Open Question 3 decision: directory is source of truth. |

---

## 6.5. Success criteria

The refactor is considered successfully shipped only when **all** of the following hold:

- **One full cron cycle clean.** A complete EN cron at 01:30 UTC + HI cron at 04:00 UTC after cutover runs end-to-end; every generated item appears in `/api/v1/content` (post-admin-reload) with correct `cover` + `audio_url` + `mood` + `subtype`. Zero manual fix-up required for any item.
- **deploy_guard verify clean for 24 hours post-cutover.** Per CLAUDE.md "DEPLOY_GUARD VIOLATIONS" rule, a single new violation blocks success. Pre-existing-and-known-ignored items (Tali, YouTube) remain ignored — no regression. (Verification is on production directly; there is no separate staging-environment verification gate.)
- **Zero orphan-class incidents.** No item exists in `data/<type>/*.json` while missing from `content.json`. This is the bug class the refactor was designed to eliminate; under the new design it is **structurally impossible** because `content.json` is regenerated as a directory walk — every file on disk is registered by definition. Verify with:
  ```bash
  find data/{stories,stories_hi,long_stories,long_stories_hi,lullabies,lullabies_hi,silly_songs,silly_songs_hi,funny_shorts,funny_shorts_hi,poems,poems_hi} -maxdepth 1 -name '*.json' | wc -l
  python3 -c "import json; print(len(json.load(open('data/content.json'))))"
  ```
  Counts MUST be equal at all times; any drift is a regression.
- **API latency unchanged.** P50, P95, P99 for `/api/v1/content` and `/api/v1/content/<id>` within **±10% of pre-cutover baseline** measured over 24 hours. Capture baseline before cutover (e.g., from existing nginx access logs or a dedicated probe).
- **Container memory unchanged.** Container RSS (`docker stats dreamweaver-backend --no-stream`) within **±10% of pre-cutover baseline**. The new boot path holds the same in-memory dict it held before, so a ±10% band is generous; a >10% increase suggests a leak or accidental retention of a second copy (e.g., keeping `_walk_per_content`'s intermediate dict around).
- **No content-load errors in logs.** Spot-check container logs for issues:
  ```bash
  sudo docker logs dreamweaver-backend 2>&1 | grep -iE "load.*content|content.*load|local_store|per[-_]content" | grep -iE "error|warn|fail"
  ```
  Expected output: empty or only the "skipped corrupt files" warning if any (which itself should be empty in steady state).
- **Pipeline never invokes `git push`.** Confirm post-§2f that `step_publish` and `_git_commit_and_push` are gone and a 24-hour cron cycle does not produce any pushed commits to `J110/dreamweaver-backend` or `J110/dreamweaver-web` from the cron user.
- **Quarantine directory is empty at cutover.** `find data/_quarantine -name '*.json' 2>/dev/null | wc -l` returns `0`. Every orphan surfaced by the audit script (§3.2) was either published or discarded via `scripts/triage_quarantine.py` before the API was flipped to the new code. Cutover is gated on this per §4 step 5.
- **No `subtype` fields present in `data/<type>[_hi]/*.json` files post-cutover** (warnings would indicate legacy state, per Open Question 3 decision — walker-stamped, not on-disk). Verifiable via:
  ```bash
  find data/ -name "*.json" -not -path "*/quarantine/*" -exec jq -e 'has("subtype")' {} + 2>/dev/null
  ```
  Expected output: empty (no file matches). Any file that returns `true` here is a legacy artifact and should be rewritten without the field; the walker's warning logs make the surface visible.

If any of the above fails within the 24-hour observation window, the cutover is **not successful** — initiate rollback per §4 step 14 and amend this spec with the specific failure mode before re-attempting.

---

## 7. Operational changes from removing staging

The Render test backend and the Vercel test frontend are being torn down in the same operational sweep as this refactor. Each item below is a checklist entry for the user (Anmol) — do not perform these from a Claude session; they are operational tasks gated on spec approval.

- [ ] **Tear down Render service.** The test-environment backend at the Render hostname (verify exact URL in Render dashboard); cancel the paid tier if any, delete the service. Auto-deploy from `J110/dreamweaver-backend` push will stop working — that's the desired state.
- [ ] **Tear down Vercel deployment.** The test-environment frontend at the Vercel preview URL; remove the project from the Vercel dashboard. Auto-deploy from `J110/dreamweaver-web` push will stop working.
- [ ] **Audit DNS.** If any nameserver records pointed at Render/Vercel hostnames, audit and document what was there for posterity, then remove. Production DNS for `dreamvalley.app` and `api.dreamvalley.app` already targets the GCP VM IP `34.14.172.180` (per MEMORY.md) — those records do not change.
- [ ] **Search GitHub Actions / automation for staging references.** On both `dreamweaver-backend` and `dreamweaver-web` repos, grep `.github/` directories for any workflow YAML mentioning `render`, `vercel`, or related deploy hooks; remove or disable. Also check any external CI configured against these repos.
- [ ] **Update READMEs, deployment guides, and CLAUDE.md** to remove staging references. Pinned line-by-line edits (verified against the working tree on 2026-04-29):

  **Replacement language to use** anywhere a staging-deploy claim is made: *"Production-only architecture. GitHub is the code repository. Prod pulls from GitHub. No staging environment."*

  - [ ] **`dreamweaver-backend/CLAUDE.md`:**
    - Line 160 (heading): `### Frontend deploys are NOT automatic for dreamvalley.app` — keep heading; the section's body must be rewritten since the Vercel claim no longer holds.
    - Line 162: `"Pushing to dreamweaver-web GitHub triggers a Vercel preview deploy only. **Production at dreamvalley.app is served from PM2 + Next.js standalone on the GCP VM** and requires manual deploy:"` — **rewrite**: drop the Vercel-preview clause; replace with a single sentence stating that production at `dreamvalley.app` is served from PM2 + Next.js standalone on the GCP VM and requires the manual steps below.
    - Line 173: `"Do not claim a frontend fix is "deployed" until these steps complete. Vercel deployment proves the code builds, not that users see it."` — **rewrite**: drop the Vercel-deployment clause; replace with `"Do not claim a frontend fix is 'deployed' until these steps complete on the GCP VM."`
    - Search for any other `Render` / `Vercel` / `staging` mentions — none found in current CLAUDE.md outside lines 162 and 173, but re-grep before editing.

  - [ ] **`dreamweaver-web/CLAUDE.md`:** does not exist (verified `ls dreamweaver-web/` 2026-04-29). No edits needed in the frontend repo at the CLAUDE.md surface. If a CLAUDE.md is added later, it must avoid Render/Vercel/staging language from inception.

  - [ ] **`dreamweaver-backend/docs/DEPLOY_GUIDE.md`:** verified clean — `rg -i "render|vercel|staging|preview"` returns no matches as of 2026-04-29. No edits needed.

  - [ ] **`dreamweaver-backend/docs/DAILY_PIPELINE_GUIDE.md`:**
    - Line 19: `"7. PUBLISH   → git push both repos → Render/Vercel auto-deploy"` — **delete** this list item entirely (the publish step is being removed per §2f); renumber the trailing items if needed.
    - Line 55: `"| Render (backend) | Free tier | $0.00 |"` — **delete** the row from the cost table.
    - Line 56: `"| Vercel (frontend) | Free tier | $0.00 |"` — **delete** the row from the cost table.
    - Line 65: `"| Mistral, Resend, Render, Vercel | $0.00 |"` — **rewrite** to remove Render and Vercel: `"| Mistral, Resend | $0.00 |"`.
    - Line 580: `"│     ├── git push backend → Render auto-deploys backend API"` — **delete** the entire `PUBLISH (test):` ASCII subtree (lines 579–583 inclusive); the diagram should jump straight from `SYNC` to `DEPLOY PROD (GCP, zero-downtime):`.
    - Line 582: `"│     └── git push frontend → Vercel auto-deploys web app"` — covered by the deletion above.
    - Line 596: `"**Pipeline deploys to both test (Render/Vercel) AND production (GCP)**. Production deploy is fully zero-downtime:"` — **rewrite**: `"**Pipeline deploys directly to production (GCP), zero-downtime.** No staging environment is involved."`
    - Line 599: `"**seedData.js**: synced and pushed for Vercel test deployment, but production frontend fetches content from API at runtime"` — **rewrite**: drop the "synced and pushed for Vercel test deployment" clause. Replace with text reflecting the (separate) follow-up that retires `seedData.js` entirely (§8) — for now: `"**seedData.js**: still generated as a build artifact for the frontend bundle (retirement tracked as a follow-up). Production frontend fetches content from the API at runtime."`

  - [ ] **`docs/follow-ups.md`:** grep `-i "render|vercel|staging|SKIP_PUBLISH_STEP"` and remove or rewrite each match consistent with the §2f publish-step deletion. Specific lines depend on current state; verify at edit time.

  - [ ] **`MEMORY.md` (user auto-memory):** the "Deployment Details" section currently mentions `Vercel` (auto-deploy on push) and `Render` (auto-deploy on push) under `### Testing (Vercel)` and `### Backend / Render`. Both subsections become obsolete — rewrite the section to a single block reflecting the production-only architecture. Pin the precise lines at edit time (MEMORY.md is user-managed and version-drifts faster than this spec).
- [ ] **Delete environment variables on Render/Vercel before tear-down.** API keys, `ADMIN_API_KEY`, etc. — clear them out before deleting the services so they cannot leak from a cached state somewhere.
- [ ] **Remove `SKIP_PUBLISH_STEP=1` from production crontab** (per §2f) once the publish-step deletion is deployed. This is a small but distinct task from the service tear-downs.

### Backup strategy (out of scope for this spec)

Removing staging removes one fail-safe — the Render copy was an implicit backup of the canonical content state. The GCP VM is now the explicit and only canonical. **Recommendation:** add daily VM disk snapshots via GCP `gcloud compute disks snapshot` on a cron, retaining ~14 days of rolling snapshots.

This is **important** but **out of scope for this refactor spec**. Add it as a follow-up entry in `docs/follow-ups.md` (under an "Operations / Backup" section if not already present) so it is tracked separately. Do not block this spec on the snapshot work landing first.

---

## 8. Out of scope

Explicitly deferred to follow-up tasks:

- **`seedData.js` migration to a backend API endpoint.** Per `docs/follow-ups.md`, this is a separate half-day session — frontend bootstrap + `/api/v1/seed-manifest` endpoint + delete file. Touching frontend is its own surface.
- **deploy_guard improvements** (orphan scan, expected-vs-delivered, cron output surfacing, subtype-aware classification, snapshot-vs-current bug). All listed in `docs/follow-ups.md` "deploy_guard improvements". These become **simpler** after this refactor lands because there's no orphan-vs-mirror divergence to detect — every per-content file *is* a published item by definition. Defer until after cutover.
- **Historical-orphan triage** (the ~6 existing files in `data/silly_songs/` and `data/poems/` that aren't in content.json) is now **in-scope for this spec**, handled via the quarantine + CLI triage workflow specified in §3.2. The audit script moves orphans to `data/_quarantine/`, the triage CLI publishes-or-discards each one, and cutover is gated on the directory being empty (§4 step 5 / §6.5).
- **Removing `data/content.json` and `seed_output/content.json` entirely.** Currently they remain as derived snapshots for the analytics module and frontend sync. Eliminating them requires updating those consumers — separate task once we're confident the per-content path is stable.
- **Hot-reload trigger redesign.** `app/main.py:61` polls `seed_output/content.json` mtime. Could be replaced with watching `data/<type>/*.json` mtimes (more correct), but the current approach keeps working since we still write the seed snapshot. Defer.
- **`SEED_PREFERRED_FIELDS` cleanup** in `local_store.py`. The constant becomes dead code post-refactor (no seed-vs-runtime split). Remove in the same PR if cleanly possible; otherwise follow-up.
- **`content_invariants.json` and deploy_guard's golden baseline.** May need re-baselining after cutover (item ordering will change since we sort by id). Run `deploy_guard seal` post-cutover.
- **VM disk snapshot cron.** Per §7, daily `gcloud compute disks snapshot` for `dreamvalley-prod`. Important but separate from this refactor.

---

## Decisions and remaining open questions

### Decided

1. **✓ DECIDED — Hindi vs English in same per-content directory, or split?** Split per `(type, lang)` — every content type gets a separate `*_hi` directory. 12 directories total (see §2a "Per-content directory map" and §2c `PER_CONTENT_DIRS`). Rationale: matches `dreamweaver-backend/CLAUDE.md` "Parallel Scripts Pattern"; mirrors existing `seed_output/<type>_hi/` audio-master layout; isolates EN and HI bug surfaces at the directory level.

2. **✓ DECIDED — quarantine + human ack via CLI.** Orphans surfaced during the migration's audit-script dry-run are physically moved to `data/_quarantine/<type>[_hi]/<id>.json` and require explicit per-item human review before being published to live state. Triage is performed via `scripts/triage_quarantine.py` (`--list`, `--publish <id>`, `--discard <id>`, plus `--publish-all --confirm` and `--discard-all --confirm` for bulk). Cutover is blocked until `data/_quarantine/` is empty. Full design in §3.2; cutover gate at §4 step 5; success criterion in §6.5.

3. **✓ DECIDED — walker-stamped from directory, not on-disk.** `subtype` is derived from the directory name by the walker at load time. Per-content files MUST NOT contain a `subtype` field. The migration backfill helper strips `subtype` before writing. If a legacy per-content file does carry `subtype`, the walker logs a warning and overwrites with the directory-derived value (load still succeeds — informational, not blocking). See §2c walker pseudocode, §3.1a schema mappings (lullaby table + cross-type derivation rules), §6 risk row, and §6.5 success criterion.

(Former Open Question 4 about Render disk persistence is removed — Render is being torn down per §7 and the GCP VM filesystem persistence is verified by the existing `./data:/app/data` bind mount in `docker-compose.yml`.)

### Operational notes (not blockers)

- **MEMORY.md / `docs/follow-ups.md` drift:** the spec quotes specific lines and section names from these files (notably in §7's pinned edits and §2f's documentation-cleanup checklist). Re-grep at edit time before applying — these are user-managed surfaces and version-drift faster than the spec.

---

**Length note:** post-simplification 2026-04-29. Removed the Render persistence pre-execution gate (former §3.5) and three alternative-architecture sketches (GCS bucket, Postgres JSONB, content.json-as-canonical). Added §2f (publish-step elimination), §5 (GitHub as code-only), §7 (operational tear-down checklist). Concrete file paths and line numbers throughout; uncertainties marked with `?`.

**Final cleanup pass 2026-04-29 (review-doc finalize):**
1. Deleted the older code-block "Cutover steps" runbook in §4 — the 13-step numbered sequence is now the single canonical runbook.
2. Resolved the cutover-window contradiction in §4 — post-HI window (~04:30 UTC, 21h margin) is the only one stated; the 90-minute EN/HI-gap option is rejected with rationale (no rollback runway).
3. Applied per-(type, lang) directory split universally — 12 directories (`PER_CONTENT_DIRS` in §2c, schema map in §2d, audit table in §2d, validation gates in §3.1d). Open Question 1 marked **DECIDED**.
4. Pinned line-by-line CLAUDE.md / DAILY_PIPELINE_GUIDE.md edits in §7 ("Update READMEs..." bullet); confirmed no `dreamweaver-web/CLAUDE.md` exists and no Render/Vercel/staging matches in `docs/DEPLOY_GUIDE.md`.

**Execution-ready pass 2026-04-29 (decisions 2 + 3 finalize):**
5. **Open Question 2 — DECIDED — quarantine + human ack via CLI.** Added §3.2 (quarantine directory layout, `scripts/triage_quarantine.py` CLI spec, audit-script integration, cutover gate). Inserted runbook step 5 (triage) in §4; renumbered subsequent steps 6–14. Added §6.5 success criterion (quarantine empty at cutover). Updated §3.1d gate 4 from "informational orphan report" to "physical move to quarantine." Updated §2d's prior open-question callout to "DECIDED" and §8's historical-orphan triage entry from "out of scope" to "in scope via §3.2."
6. **Open Question 3 — DECIDED — walker-stamped from directory, not on-disk.** Updated §2c walker pseudocode to overwrite (not just `setdefault`) `subtype` from directory, with informational warning when on-disk value disagrees. Updated §3.1a lullaby schema mapping (subtype row → "NOT included; stripped by backfill helper") and added a uniform "subtype is never written to disk" rule under cross-type derivation rules. Added §6 risk row (legacy on-disk subtype). Added §6.5 success criterion (no `subtype` fields on disk post-cutover).
7. Status line updated from "Draft for review" to **"execution-ready (last updated 2026-04-29 UTC)"**. Open Questions section: 3/3 decided; "Still open" subsection removed; replaced with "Operational notes (not blockers)" capturing the MEMORY.md / docs/follow-ups.md drift caveat.
