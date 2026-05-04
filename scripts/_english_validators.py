"""English short_story and long_story validators (Phase 2.2).

Mirrors the Hindi validator pattern in scripts/_hindi_validators.py.
Each validator returns list[str] of error messages — empty means OK.
Caller's job is to retry generation up to N times when errors are non-empty.

Calibrated against the comprehensibility floor shipped in Phase 2.1
(commit f16730e). Test fixtures at scripts/test_english_validators_fixtures.json
encode the expected pass/fail behavior (Task 1 ground truth).
"""
from __future__ import annotations

import re

# ── Banned vocabulary ─────────────────────────────────────────────────

# Universal — applies to every story regardless of age.
BANNED_UNIVERSAL = {
    "perhaps", "however", "indeed", "rather", "shall", "nevertheless",
    "furthermore", "accordingly", "sophisticated", "particularly",
    "fundamentally", "essentially", "profound", "magnificent", "exquisite",
    "peculiar", "contemplated", "pondered", "ascertained", "endeavored",
    "possibility", "misunderstood", "atmosphere", "realization",
    "loneliness", "threatening", "acceptance", "agreement", "ambiguous",
    "benevolent", "malevolent", "precarious", "indubitably",
}

# Per-age hard bans (additive on top of universal).
BANNED_BY_AGE = {
    "0-1": {
        "somersaulted", "strawberries", "strawberry", "dandelion", "dandelions",
        "butterflies", "butterfly", "ladybugs", "ladybug", "overrated",
        "lullaby", "rhythmic", "melody", "twinkled", "scattered",
        "gathering", "fluttered", "rainbows", "rainbow", "sparkles", "sparkle",
    },
    "2-5": {
        "realization", "possibility", "atmosphere", "acceptance",
        "loneliness", "agreement", "misunderstood", "somersaulted",
        "overrated", "contemplation",
    },
    "6-8": set(),
    "9-12": set(),
}

# 6-8 discouraged — soft warning if used 2+ times in a single story.
DISCOURAGED_6_8 = {
    "smokestacks", "candyfloss", "crisscrossed", "nightlight",
    "heartbeats", "flickering", "shimmering",
}

# -ing descriptors counted for the "max 1 per sentence" soft rule.
ING_DESCRIPTORS = {
    "whispering", "shimmering", "fluttering", "listening", "stretching",
    "gathering", "flickering", "scattering", "drifting",
}

# Per-age sentence-length cap (words). HARD, no tolerance.
SENTENCE_CAP = {"0-1": 8, "2-5": 12, "6-8": 16, "9-12": 22}

# 4+ syllable abstract noun cap per sentence.
# 0-1: any 4+ syllable word is suspect (treat as max 0).
# 2-5: max 1 per sentence.
# 6-8 / 9-12: skip.
SYLLABLE_THRESHOLD = 4
ABSTRACT_NOUN_PER_SENT_CAP = {"0-1": 0, "2-5": 1}

# Common 4+ syllable kid-vocab that should NOT count as abstract — these
# are concrete picture-book staples kids encounter normally.
KID_VOCAB_ALLOWLIST = {
    "watermelon", "caterpillar", "helicopter", "alligator", "dinosaur",
    "rhinoceros", "hippopotamus", "macaroni", "saxophone", "ukulele",
    "kindergarten", "pajamas",
}

# Per-age long-story word-count band (lifted from generate_content_matrix.py).
LONG_STORY_WORD_BAND = {
    "2-5":  (1000, 1600),
    "6-8":  (1400, 2200),
    "9-12": (1800, 3000),
}


# ── Helpers ──────────────────────────────────────────────────────────

def _strip_tags(text: str) -> str:
    """Remove [TAG] markers, (parenthetical), *sfx*, markdown emphasis.
    Returns narration text only."""
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\*[^*]*\*", " ", text)
    text = re.sub(r"_+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, including dialogue boundaries.

    Splits on whitespace where the immediately preceding chars are:
      - period/exclaim/question followed by a close-quote ('."'  '?"' etc.)
      - period/exclaim/question with no quote ('. ')

    Both forms are sentence boundaries. The close-quote stays attached
    to the prior sentence (lookbehind, not consumed).

    Counts dialogue periods as boundaries — `"I see it. The lights..." SYLVI:`
    splits into `"I see it.`, `The lights..."`, `SYLVI: ...`. This is the
    correct behavior for sentence-cap counting; we want per-utterance
    word counts, not per-quoted-span.

    Apostrophes (' or ’) are never treated as quote delimiters —
    they're contractions / possessives. So `didn't` stays one token.
    """
    parts = re.split(r'(?<=[.!?]["”])\s+|(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p and len(_words(p)) >= 2]


def _words(text: str) -> list[str]:
    """Tokenize into lowercase word strings."""
    return [w.lower() for w in re.findall(r"[A-Za-z']+", text)]


def _count_syllables(word: str) -> int:
    """Heuristic syllable counter. Vowel-group based with silent-e adjust.

    Returns int >= 1. Standard 6-line heuristic; ~95% accuracy for English.
    """
    word = word.lower()
    if len(word) <= 3:
        return 1
    # Strip silent-e suffix patterns
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    # Strip leading 'y' so "yellow" doesn't double-count
    word = re.sub(r"^y", "", word)
    groups = re.findall(r"[aeiouy]+", word)
    return max(1, len(groups))


def _has_word(text_lower: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text_lower))


def _hard_banned_hits(text_lower: str, age: str) -> list[tuple[str, str]]:
    """Return (banned_word, scope) pairs for unique hits.

    scope ∈ {'universal', 'age'}. One tuple per distinct word, not per
    occurrence.
    """
    hits = []
    for w in sorted(BANNED_UNIVERSAL):
        if _has_word(text_lower, w):
            hits.append((w, "universal"))
    for w in sorted(BANNED_BY_AGE.get(age, set())):
        if _has_word(text_lower, w):
            hits.append((w, "age"))
    return hits


def _abstract_nouns_in(sentence: str) -> list[str]:
    """Return list of words in `sentence` that look like abstract nouns
    (>= SYLLABLE_THRESHOLD syllables, not in kid-vocab allowlist)."""
    out = []
    for w in _words(sentence):
        if w in KID_VOCAB_ALLOWLIST:
            continue
        if _count_syllables(w) >= SYLLABLE_THRESHOLD:
            out.append(w)
    return out


def _title_override_violations(title: str, body_lower: str, age: str) -> list[str]:
    """Banned-for-this-age tokens that appear in BOTH title and body.

    Only checks per-age bans, not universal — universal hits are caught
    upstream by the universal-ban check, no need to double-flag.
    """
    if not title:
        return []
    title_words = set(_words(title))
    age_bans = BANNED_BY_AGE.get(age, set())
    return sorted(title_words & age_bans & {w for w in age_bans if _has_word(body_lower, w)})


# ── Validators ────────────────────────────────────────────────────────

def _common_checks(d: dict, body: str, age: str) -> list[str]:
    """Shared check sequence for short_story and long_story."""
    errors: list[str] = []

    if not body or not body.strip():
        errors.append("body empty")
        return errors

    clean = _strip_tags(body)
    body_lower = clean.lower()

    # 2 — Universal banned
    # 3 — Per-age banned
    for word, scope in _hard_banned_hits(body_lower, age):
        if scope == "universal":
            errors.append(f"banned (universal): '{word}'")
        else:
            errors.append(f"banned word: '{word}' at age {age}")

    # 4 — Sentence cap (HARD)
    cap = SENTENCE_CAP.get(age, 16)
    sents = _split_sentences(clean)
    for s in sents:
        n = len(_words(s))
        if n > cap:
            preview = s[:80].replace("\n", " ")
            errors.append(f"sentence over cap: {n} words at age {age} (max {cap}): '{preview}...'")

    # 5 — Title override
    title = d.get("title", "") or ""
    title_hits = _title_override_violations(title, body_lower, age)
    for w in title_hits:
        errors.append(f"title-override: '{w}' from title appears in body")

    # 6 — 4+ syllable abstract noun cap (0-1, 2-5 only)
    if age in ABSTRACT_NOUN_PER_SENT_CAP:
        per_sent_cap = ABSTRACT_NOUN_PER_SENT_CAP[age]
        for s in sents:
            nouns = _abstract_nouns_in(s)
            if len(nouns) > per_sent_cap:
                preview = s[:80].replace("\n", " ")
                errors.append(
                    f"4+ syllable noun >{per_sent_cap} in sentence: "
                    f"{nouns[:3]} in: '{preview}...'"
                )

    # 7 — -ing stacking (SOFT)
    for s in sents:
        ings = [w for w in _words(s) if w in ING_DESCRIPTORS]
        if len(ings) >= 2:
            preview = s[:80].replace("\n", " ")
            errors.append(f"warning: -ing stacking in sentence: {ings} in: '{preview}...'")

    # 8 — 6-8 discouraged (SOFT, ≥2 occurrences)
    if age == "6-8":
        for w in sorted(DISCOURAGED_6_8):
            occ = len(re.findall(rf"\b{re.escape(w)}\b", body_lower))
            if occ >= 2:
                errors.append(f"warning: 6-8 discouraged word '{w}' used {occ} times")

    return errors


def validate_short_story(d: dict) -> list[str]:
    """Validate an EN short_story item. Returns list of error messages.

    Pulls age from d['age_group'], body from d['text']/'content'/'body',
    title from d['title'].
    """
    age = d.get("age_group", "") or ""
    body = d.get("text") or d.get("content") or d.get("body") or ""
    if isinstance(body, dict):  # defensive: legacy schema variant
        body = ""
    return _common_checks(d, body, age)


def validate_long_story(d: dict) -> list[str]:
    """Validate an EN long_story item. Returns list of error messages.

    Pulls body from d['full_text_roman']/'content'/'text'. Adds two
    long-story-specific checks: Phase 3 sentence descent, word-count band.
    """
    age = d.get("age_group", "") or ""
    body = (
        d.get("full_text_roman")
        or d.get("content")
        or d.get("text")
        or d.get("body")
        or ""
    )
    if isinstance(body, dict):
        body = ""

    errors = _common_checks(d, body, age)
    if not body:
        return errors

    clean = _strip_tags(body)

    # 9 — Phase 3 sentence descent (HARD), only if [PHASE_3] markers present.
    # The rule is part of LONG_STORY_PHASE_INSTRUCTIONS which only applies
    # to items generated under the phase format. Items without explicit
    # markers (older catalog entries, non-phase-format episodes) are
    # exempt — the rule doesn't bind them.
    p3_match = re.search(r"\[PHASE_3\](.*?)(?:\[/PHASE_3\]|\Z)", body, re.DOTALL)
    if p3_match:
        p3_clean = _strip_tags(p3_match.group(1))
        p3_sents = _split_sentences(p3_clean)
        last5 = p3_sents[-5:] if len(p3_sents) >= 5 else p3_sents
        if last5:
            avg_words = sum(len(_words(s)) for s in last5) / len(last5)
            cap = SENTENCE_CAP.get(age, 16)
            target = cap * 0.5
            if avg_words > target:
                errors.append(
                    f"phase 3 final sentences not descending (avg {avg_words:.1f} words, "
                    f"cap {cap}, target {target:.1f})"
                )

    # 10 — Word-count band: REMOVED.
    # The `long_story` content type does not share the per-age-LONG word
    # bands defined in scripts/generate_content_matrix.py for `story` type.
    # Actual long_story distribution (from prod 64 items): 0-1: 186-329,
    # 2-5: 419-984, 6-8: 596-2195, 9-12: 488-2933. Too wide for a useful
    # cap. The Phase 3 descent check above is the meaningful long-story
    # length-shape validator.

    return errors


# ── Dispatch ─────────────────────────────────────────────────────────

VALIDATORS = {
    "short_story": validate_short_story,
    "long_story":  validate_long_story,
}


# ── Severity classification (mirrors Hindi) ──────────────────────────

_MAJOR_PATTERNS = [
    "sentence over cap:",
    "banned word:",
    "banned (universal):",
    "title-override:",
    "4+ syllable noun",
    "phase 3 final sentences not descending",
    "word count",
    "body empty",
]


def _classify(message: str, content_type: str, raw_data: dict) -> str:
    if message.startswith("warning:"):
        return "minor"
    for pat in _MAJOR_PATTERNS:
        if pat in message:
            return "major"
    return "minor"


def validate_structured(content_type: str, data: dict) -> list[dict]:
    """Run the type-specific validator and tag each error with severity.

    Returns list of dicts: {severity, rule, detail}. Empty list = OK.
    """
    if content_type not in VALIDATORS:
        return []
    raw_messages = VALIDATORS[content_type](data)
    out = []
    for msg in raw_messages:
        out.append({
            "severity": _classify(msg, content_type, data),
            "rule": msg.split(":")[0].strip()[:60],
            "detail": msg,
        })
    return out


def has_major(structured_errors: list[dict]) -> bool:
    return any(e.get("severity") == "major" for e in structured_errors)


def only_minor(structured_errors: list[dict]) -> bool:
    return bool(structured_errors) and not has_major(structured_errors)
