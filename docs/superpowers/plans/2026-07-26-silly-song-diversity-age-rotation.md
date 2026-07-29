# Silly Song Diversity and Age Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject lexically and semantically repetitive English silly-song hooks and make daily one-song runs rotate reliably across all three age groups.

**Architecture:** Add isolated hook-normalization, deterministic scoring, semantic judgment, and age-selection helpers to the existing generator. The fresh-generation loop will select age from production history on every iteration and will validate each invented hook before any lyrics or assets are generated.

**Tech Stack:** Python 3, standard-library `difflib`, `json`, `re`, existing Mistral client wrapper, pytest.

## Global Constraints

- Token Jaccard similarity at or above `0.60` is an immediate rejection.
- Normalized string similarity at or above `0.82` is an immediate rejection.
- Token Jaccard from `0.35` through `0.59`, or string similarity from `0.68` through `0.81`, requires semantic judgment.
- Semantic judgment receives the five closest existing hooks.
- Malformed or unavailable semantic judgment rejects a borderline candidate.
- Hook invention stops after three rejected attempts and publishes nothing.
- Age tie order is `2-5`, `6-8`, `9-12`.
- Existing lyrics, audio, cover, category, mood, Hindi, and publishing behavior remains unchanged.

---

### Task 1: Deterministic Hook Similarity

**Files:**
- Modify: `scripts/generate_silly_songs_battlecry.py:1307-1523`
- Create: `scripts/test_silly_song_diversity_rotation.py`

**Interfaces:**
- Produces: `_normalize_hook(text: str) -> str`
- Produces: `_stem_hook_token(token: str) -> str`
- Produces: `_hook_similarity(candidate: str, existing: str) -> tuple[float, float]`
- Produces: `_closest_hook_matches(candidate: str, existing_hooks: list[str], limit: int = 5) -> list[tuple[str, float, float]]`
- Produces: `_deterministic_hook_decision(candidate: str, existing_hooks: list[str]) -> tuple[str, list[tuple[str, float, float]]]`, where decision is `reject`, `semantic`, or `accept`.

- [ ] **Step 1: Write failing normalization and similarity tests**

```python
from scripts import generate_silly_songs_battlecry as generator


def test_tiny_parade_variants_are_deterministically_rejected():
    decision, matches = generator._deterministic_hook_decision(
        "Tiny Parade Today!",
        ["Tiny Parade Hooray!", "Tiny Parade!"],
    )
    assert decision == "reject"
    assert matches[0][0] in {"Tiny Parade Hooray!", "Tiny Parade!"}


def test_hook_normalization_removes_markdown_case_and_punctuation():
    assert generator._normalize_hook("**TINY Parade!**") == "tiny parade"


def test_hook_normalization_reduces_inflections_and_stop_words():
    assert generator._normalize_hook("The Marching Shoes Today") == "march shoe"


def test_borderline_hook_requires_semantic_judgment():
    decision, _ = generator._deterministic_hook_decision(
        "Moon Shoes March",
        ["Moon Boots March"],
    )
    assert decision == "semantic"


def test_distinct_hook_skips_semantic_judgment():
    decision, _ = generator._deterministic_hook_decision(
        "Broccoli Built a Spaceship",
        ["Tiny Parade Hooray!"],
    )
    assert decision == "accept"
```

- [ ] **Step 2: Run the tests and verify missing helpers fail**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: FAIL with `_deterministic_hook_decision` or `_normalize_hook` missing.

- [ ] **Step 3: Implement deterministic normalization and scoring**

```python
from difflib import SequenceMatcher

HOOK_REJECT_JACCARD = 0.60
HOOK_REJECT_SEQUENCE = 0.82
HOOK_SEMANTIC_JACCARD = 0.35
HOOK_SEMANTIC_SEQUENCE = 0.68
HOOK_STOP_WORDS = {"a", "an", "the", "my", "your", "our", "today", "tonight", "again"}


def _stem_hook_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 5 and token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _normalize_hook(text: str) -> str:
    normalized = re.sub(r"[*_`~]", "", text or "").lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = (
        _stem_hook_token(token)
        for token in normalized.split()
        if token not in HOOK_STOP_WORDS
    )
    return " ".join(tokens)


def _hook_similarity(candidate: str, existing: str) -> tuple[float, float]:
    left = _normalize_hook(candidate)
    right = _normalize_hook(existing)
    left_tokens, right_tokens = set(left.split()), set(right.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 1.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return jaccard, sequence


def _closest_hook_matches(candidate, existing_hooks, limit=5):
    unique = list(dict.fromkeys(h for h in existing_hooks if h))
    scored = [(hook, *_hook_similarity(candidate, hook)) for hook in unique]
    return sorted(scored, key=lambda row: max(row[1], row[2]), reverse=True)[:limit]


def _deterministic_hook_decision(candidate, existing_hooks):
    matches = _closest_hook_matches(candidate, existing_hooks)
    if any(j >= HOOK_REJECT_JACCARD or s >= HOOK_REJECT_SEQUENCE
           for _, j, s in matches):
        return "reject", matches
    if any(j >= HOOK_SEMANTIC_JACCARD or s >= HOOK_SEMANTIC_SEQUENCE
           for _, j, s in matches):
        return "semantic", matches
    return "accept", matches
```

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: PASS.

- [ ] **Step 5: Commit deterministic validation**

```bash
git add scripts/generate_silly_songs_battlecry.py scripts/test_silly_song_diversity_rotation.py
git commit -m "fix: reject lexically similar silly song hooks"
```

---

### Task 2: Semantic Judgment and Retry Exhaustion

**Files:**
- Modify: `scripts/generate_silly_songs_battlecry.py:1480-1523`
- Modify: `scripts/test_silly_song_diversity_rotation.py`

**Interfaces:**
- Consumes: `_deterministic_hook_decision(candidate, existing_hooks)`
- Produces: `_semantic_hook_is_similar(candidate: str, matches: list[tuple[str, float, float]], api_key: str) -> bool`
- Produces: `_existing_hooks_newest_first(existing_songs: list[dict]) -> list[str]`
- Changes: `invent_anthem(category, age_group, mood, existing_hooks, api_key, existing_on_disk) -> tuple[str, str]`

- [ ] **Step 1: Write failing semantic and retry tests**

```python
def test_semantic_paraphrase_is_rejected(monkeypatch):
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: '{"similar": true}',
    )
    assert generator._semantic_hook_is_similar(
        "Moon Boots March",
        [("Marching Shoes on the Moon", 0.4, 0.7)],
        "test-key",
    ) is True


def test_malformed_semantic_response_is_conservatively_rejected(monkeypatch):
    monkeypatch.setattr(generator, "call_mistral", lambda *args, **kwargs: "maybe")
    assert generator._semantic_hook_is_similar(
        "Moon Boots March",
        [("Marching Shoes on the Moon", 0.4, 0.7)],
        "test-key",
    ) is True


def test_invent_anthem_exhausts_three_rejected_candidates(monkeypatch):
    responses = iter([
        "Tiny Parade Today!",
        "Tiny Parade Tonight!",
        "Tiny Parade Again!",
    ])
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: next(responses),
    )
    with pytest.raises(RuntimeError, match="three similarity rejections"):
        generator.invent_anthem(
            category="celebration",
            age_group="2-5",
            mood="wired",
            existing_hooks=["Tiny Parade Hooray!"],
            api_key="test-key",
            existing_on_disk={"tiny_parade_hooray_2_5"},
        )


def test_existing_hooks_are_newest_first_and_keep_yesterdays_title():
    songs = [
        {"created_at": f"2026-07-{day:02d}", "title": f"Song {day}"}
        for day in range(1, 26)
    ]
    songs.append({
        "created_at": "2026-07-26",
        "title": "Tiny Parade Hooray!",
        "anthem": "Tiny Parade Hooray!",
    })
    hooks = generator._existing_hooks_newest_first(songs)
    assert hooks[0] == "Tiny Parade Hooray!"
    assert "Tiny Parade Hooray!" in hooks[:25]
```

- [ ] **Step 2: Run semantic tests and verify failure**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: FAIL because semantic validation and the revised interface are absent.

- [ ] **Step 3: Implement structured semantic judgment**

```python
def _semantic_hook_is_similar(candidate, matches, api_key):
    comparison = "\n".join(f"- {hook}" for hook, _, _ in matches[:5])
    prompt = (
        "Judge whether the candidate silly-song hook is substantially the same "
        "idea, image, or chant as any existing hook.\n"
        f"Candidate: {candidate}\nExisting hooks:\n{comparison}\n"
        'Return only JSON: {"similar": true} or {"similar": false}.'
    )
    try:
        raw = call_mistral(
            prompt,
            system_msg="You are a strict content diversity classifier.",
            api_key=api_key,
        )
        parsed = json.loads(raw)
        return parsed.get("similar") is not False
    except Exception:
        return True
```

- [ ] **Step 4: Validate every invented candidate before accepting it**

Revise `invent_anthem` so each of its three attempts:

```python
decision, matches = _deterministic_hook_decision(candidate, existing_hooks)
if decision == "accept":
    return candidate, unique_slug
if decision == "semantic" and not _semantic_hook_is_similar(
    candidate, matches, api_key
):
    return candidate, unique_slug
closest = ", ".join(match[0] for match in matches[:3])
rejection_feedback = (
    f"\nPrevious candidate rejected as too similar: {candidate}. "
    f"Closest hooks: {closest}. Invent a different subject and wording."
)
```

After the third rejection, raise:

```python
raise RuntimeError("invent_anthem: three similarity rejections")
```

Build `existing_hooks` from all loaded production titles and anthem fields. Keep the prompt-only avoid section ordered newest-first and limited to the newest 25 unique hooks.

```python
def _existing_hooks_newest_first(existing_songs):
    hooks = []
    for song_data in reversed(existing_songs):
        hooks.extend((
            song_data.get("title", ""),
            song_data.get("anthem") or song_data.get("battle_cry", ""),
        ))
    return [hook for hook in dict.fromkeys(hooks) if hook]
```

Log every rejection with the attempt number, deterministic scores, closest hook, and whether semantic judgment rejected it.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: PASS.

- [ ] **Step 6: Commit semantic validation**

```bash
git add scripts/generate_silly_songs_battlecry.py scripts/test_silly_song_diversity_rotation.py
git commit -m "fix: reject semantically repetitive silly song hooks"
```

---

### Task 3: Persistent Age Rotation

**Files:**
- Modify: `scripts/generate_silly_songs_battlecry.py:1307-1325`
- Modify: `scripts/generate_silly_songs_battlecry.py:1984-2025`
- Modify: `scripts/test_silly_song_diversity_rotation.py`

**Interfaces:**
- Produces: `select_next_age(existing_songs: list[dict]) -> str`
- Produces: `_latest_age_dates(existing_songs: list[dict]) -> dict[str, date | None]`
- Consumes: each successful result appended to `existing_songs`

- [ ] **Step 1: Write failing age-rotation tests**

```python
def song(age, created_at):
    return {"age_group": age, "created_at": created_at}


def test_select_next_age_uses_least_recent_generation():
    history = [
        song("2-5", "2026-07-26"),
        song("6-8", "2026-07-24"),
        song("9-12", "2026-07-25"),
    ]
    assert generator.select_next_age(history) == "6-8"


def test_three_daily_selections_cover_every_age():
    history = []
    selected = []
    for day in ("2026-07-26", "2026-07-27", "2026-07-28"):
        age = generator.select_next_age(history)
        selected.append(age)
        history.append(song(age, day))
    assert selected == ["2-5", "6-8", "9-12"]


def test_missing_dates_are_oldest_with_fixed_tie_order():
    history = [
        song("2-5", "2026-07-26"),
        song("6-8", "not-a-date"),
        song("9-12", "2026-07-25"),
    ]
    assert generator.select_next_age(history) == "6-8"
```

- [ ] **Step 2: Run age tests and verify missing selector fails**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: FAIL with `select_next_age` missing.

- [ ] **Step 3: Implement history-based selection**

```python
AGE_GROUPS = ("2-5", "6-8", "9-12")


def _valid_created_at(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _latest_age_dates(existing_songs):
    latest = {age: None for age in AGE_GROUPS}
    for song_data in existing_songs:
        age = song_data.get("age_group")
        created = _valid_created_at(song_data.get("created_at"))
        if age in latest and created is not None:
            latest[age] = max(filter(None, (latest[age], created)))
    return latest


def select_next_age(existing_songs):
    latest = _latest_age_dates(existing_songs)
    return min(AGE_GROUPS, key=lambda age: (
        latest[age] is not None,
        latest[age] or date.min,
        AGE_GROUPS.index(age),
    ))
```

- [ ] **Step 4: Replace batch-local age preassignment**

Remove `assigned_ages` and its shuffle. Inside the fresh loop, immediately before hook invention:

```python
latest = _latest_age_dates(existing_songs)
forced_age = select_next_age(existing_songs)
print(
    "  Age selection: "
    + ", ".join(f"{age}={latest[age] or 'never'}"
                for age in AGE_GROUPS)
    + f" -> {forced_age}"
)
```

Continue appending each successful `result` to `existing_songs`; the next batch iteration will therefore choose the next least-recent age.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=. pytest -q scripts/test_silly_song_diversity_rotation.py`

Expected: PASS.

- [ ] **Step 6: Commit age rotation**

```bash
git add scripts/generate_silly_songs_battlecry.py scripts/test_silly_song_diversity_rotation.py
git commit -m "fix: rotate silly song ages from production history"
```

---

### Task 4: Failure Boundary and Regression Verification

**Files:**
- Modify: `scripts/test_silly_song_diversity_rotation.py`
- Verify: `scripts/test_silly_song_replicate_polling.py`

**Interfaces:**
- Consumes: revised `invent_anthem` and `select_next_age`
- Produces: regression evidence that rejected hooks do not call asset generation

- [ ] **Step 1: Add a no-publish integration test**

```python
def test_similarity_exhaustion_never_starts_song_generation(monkeypatch):
    monkeypatch.setattr(generator, "_load_existing_songs", lambda: [{
        "title": "Tiny Parade Hooray!",
        "anthem": "Tiny Parade Hooray!",
        "age_group": "2-5",
        "created_at": "2026-07-25",
    }])
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: "Tiny Parade Today!",
    )
    generated = []
    monkeypatch.setattr(
        generator,
        "generate_silly_song",
        lambda **kwargs: generated.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="three similarity rejections"):
        generator.invent_anthem(
            "celebration",
            "2-5",
            "wired",
            ["Tiny Parade Hooray!"],
            "test-key",
            {"tiny_parade_hooray_2_5"},
        )
    assert generated == []
```

- [ ] **Step 2: Run all focused silly-song tests**

Run:

```bash
PYTHONPATH=. pytest -q \
  scripts/test_silly_song_diversity_rotation.py \
  scripts/test_silly_song_replicate_polling.py
```

Expected: all tests PASS.

- [ ] **Step 3: Run syntax and whitespace validation**

Run:

```bash
python3 -m py_compile scripts/generate_silly_songs_battlecry.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit regression coverage**

```bash
git add scripts/test_silly_song_diversity_rotation.py
git commit -m "test: enforce silly song diversity and age rotation"
```

---

### Task 5: Production Rollout

**Files:**
- Deploy: `scripts/generate_silly_songs_battlecry.py`
- Deploy: `scripts/test_silly_song_diversity_rotation.py`

**Interfaces:**
- Consumes: Deploy Guard snapshot and verify workflow
- Produces: deployed generator with dry-run evidence

- [ ] **Step 1: Review the complete branch diff**

Run:

```bash
git diff origin/main...HEAD -- \
  scripts/generate_silly_songs_battlecry.py \
  scripts/test_silly_song_diversity_rotation.py
```

Expected: only the approved diversity, retry, observability, and age-rotation changes.

- [ ] **Step 2: Push the tested branch and fast-forward main after approval**

```bash
git push origin HEAD
git push origin HEAD:main
```

Expected: both pushes succeed without force.

- [ ] **Step 3: Capture the production Deploy Guard snapshot**

Run on production:

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py snapshot
```

Expected: snapshot saved before pulling code.

- [ ] **Step 4: Preserve production runtime data and pull**

Run on production:

```bash
cd /opt/dreamweaver-backend
git stash push -m pre-silly-song-diversity-rotation
git pull --rebase origin main
git stash pop
```

Expected: fast-forward pull and clean stash restoration without conflicts.

- [ ] **Step 5: Run production focused tests**

Run on production:

```bash
cd /opt/dreamweaver-backend
PYTHONPATH=. pytest -q \
  scripts/test_silly_song_diversity_rotation.py \
  scripts/test_silly_song_replicate_polling.py
```

Expected: all tests PASS.

- [ ] **Step 6: Run a lyrics-only dry run**

Run on production:

```bash
cd /opt/dreamweaver-backend
dry_run_dir=$(mktemp -d)
/usr/bin/python3 - "$dry_run_dir" <<'PY'
import sys
from pathlib import Path
from scripts import generate_silly_songs_battlecry as generator

existing = generator._load_existing_songs()
root = Path(sys.argv[1])
generator.DATA_DIR = root / "data"
generator.OUTPUT_DIR = root / "output"
generator.DATA_DIR.mkdir(parents=True)
generator.OUTPUT_DIR.mkdir(parents=True)
generator._load_existing_songs = lambda: list(existing)
sys.argv = [
    "generate_silly_songs_battlecry.py",
    "--fresh", "--count", "1", "--mood", "wired", "--lyrics-only",
]
generator.main()
PY
```

Expected: selected age is the least recently generated group, any near-duplicate candidate is rejected before lyrics generation, and one distinct metadata record is written only under the temporary directory without changing the live catalog.

- [ ] **Step 7: Verify with Deploy Guard**

Run on production:

```bash
cd /opt/dreamweaver-backend
python3 scripts/deploy_guard.py verify
```

Expected: the dry-run item is reported according to lyrics-only policy, all unrelated checks pass, and the previously waived YouTube liveness check may remain the sole unrelated failure.

- [ ] **Step 8: Record the next two daily age selections**

Confirm production logs for the next two successful daily invocations complete the three-age cycle exactly once. If a generation attempt fails before publishing, it must not advance the rotation.
