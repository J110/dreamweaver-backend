"""Consolidated Hindi-content validators per v2 specs.

Each validator returns list[str] of error messages — empty means OK.
Caller's job is to retry generation up to N times when errors are non-empty.

Sources:
    short_story → HINDI_SHORT_STORY_GUIDELINES (2).md §18
    long_story  → HINDI_LONG_STORY_GUIDELINES.md §19
    lullaby     → HINDI_LULLABY_GENERATION_GUIDELINES.md (no formal validator;
                  enforce same shared rules)
    silly_song  → HINDI_SILLY_SONGS_GUIDELINES (1).md §11 (with hardened religious + 5 simile constructions)
    poem        → HINDI_MUSICAL_POEMS_GUIDELINES (1).md §10
"""
from __future__ import annotations

import re

# ── Shared reject lists ────────────────────────────────────────────────

LITERARY = [
    "nidra", "nakshatra", "shayan", "tandra", "pushp",
    "chandra", "megh", "tatpashchat", "nivas", "avlokan",
    "prasthan", "shubh ratri", "van ", "sugandh",
    "aagaman", "jalashay", "nayan", "vidyalay", "kreeda",
]

# Deity names use word-boundary regex (compiled below) to avoid false
# positives on common Hindi words: "ram " would otherwise match naram (soft),
# garam (warm), aaram (rest), param (supreme); "deva " would match devar
# (brother-in-law); "shiv" would match shivling (which IS religious — kept
# as substring) but also "shivay" forms.
DEITY_NAMES = [
    "bhagwaan", "ishvar", "lakshmi", "ganesh",
    "shiv", "krishn", "hanuman", "durga", "saraswati",
    "vishnu", "kali", "allah", "khuda", "rabb", "yesu", "jesus",
]
# Word-boundary-checked deities (catch the standalone form, not as substring)
DEITY_WORD_BOUNDARY = ["ram", "deva", "devi"]
RITUAL_VERBS = [
    "puja", "aarti", "prarthana", "bhajan karna", "yajna", "havan",
    "prasad", "bhog", "tilak", "darshan", "namaz", "ibadat",
]
RELIGIOUS_OBJECTS = [
    "mandir ke andar", "masjid ke andar", "gurudwara",
    "murti", "shankh", "ghanta puja",
]
RELIGIOUS_ALL = sorted(set(DEITY_NAMES + RITUAL_VERBS + RELIGIOUS_OBJECTS))

NAME_BLACKLIST = [
    "Chintu", "Raju", "Bittu", "Munna", "Guddu", "Pinky", "Rinku",
    "Bablu", "Pappu", "Chhotu", "Motu", "Golu", "Sonu", "Monu",
    "Titu", "Bunty", "Ramu",
]

CONVERSATIONAL_MARKERS = [
    "na ", " toh ", "arre", "pata hai", "chalo", "dekho", "suno",
    "hai na", "aur phir", "bas ", "achha", "zara",
]

ONOMATOPOEIA = [
    "sarr", "tap tap", "chhap", "khat", "dheere dheere",
    "chi chi", "gunghun", "jhoom", "tip tip", "patak", "thak thak",
]

BANNED_SIMILE_NOUNS = [
    "udaas", "khush", "akela", "toota", "khaali", "chup",
    "andhera", "thanda", "baadal", "chhaaya", "shoonya",
    "hawa", "patthar", "sapna", "bhoot", "fusphusahat",
]

CANONICAL_CHARACTER_TYPES = [
    "land_mammal", "bird", "sea_creature", "insect", "reptile_amphibian",
    "human_child", "mythical_creature", "object_alive", "plant_tree",
    "celestial_weather", "robot_mechanical",
]


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in (s or ""))


def _religious_hits(text_lower: str) -> list[str]:
    """Return list of religious-content matches.
    Substring match for most terms; word-boundary regex for common-word
    deities (ram/deva/devi) to avoid false positives on naram/garam/aaram/devar etc."""
    hits = []
    for w in sorted(set(DEITY_NAMES + RITUAL_VERBS + RELIGIOUS_OBJECTS)):
        if w in text_lower:
            hits.append(w)
    for w in DEITY_WORD_BOUNDARY:
        if re.search(rf"\b{w}\b", text_lower):
            hits.append(w)
    return hits


def _check_simile_constructions(text_lower: str) -> list[str]:
    """All 5 Hindi simile patterns vs banned nouns."""
    errors = []
    for noun in BANNED_SIMILE_NOUNS:
        for p in (
            f"jaisa {noun}", f"jaisi {noun}",
            f"{noun} ki tarah",
            f"{noun} ke jaisa", f"{noun} ke jaisi",
            f"jaise {noun}",
            f"{noun} samaan",
        ):
            if p in text_lower:
                errors.append(f"banned simile: '{p}'")
                break
    return errors


# ───────────────────────────────────────────────────────────────────────
# SHORT STORY
# ───────────────────────────────────────────────────────────────────────

def validate_short_story(d: dict) -> list[str]:
    errors: list[str] = []
    text = d.get("text", "") or ""
    text_lower = text.lower()

    # Devanagari rejection
    for f in ("title", "hook", "description", "text", "repeated_phrase"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")
    char = d.get("character", {}) or {}
    for sub in ("name", "identity", "special"):
        if _has_devanagari(char.get(sub, "") or ""):
            errors.append(f"Devanagari in character.{sub}")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious
    for w in _religious_hits(text_lower):
        errors.append(f"religious content: '{w}'")

    # Conversational markers ≥2
    n = sum(1 for m in CONVERSATIONAL_MARKERS if m in text_lower)
    if n < 2:
        errors.append(f"only {n} conversational markers (need ≥2)")

    # [PHRASE] count ≥3
    if text.count("[PHRASE]") < 3:
        errors.append("[PHRASE] count <3")

    # Onomatopoeia ≥2
    n = sum(1 for o in ONOMATOPOEIA if o in text_lower)
    if n < 2:
        errors.append(f"only {n} onomatopoeia (need ≥2)")

    # Blacklisted name
    if char.get("name") in NAME_BLACKLIST:
        errors.append(f"blacklisted name: '{char.get('name')}'")

    # Forbidden tags
    for tag in ("[GENTLE]", "[SLEEPY]", "[EXCITED]", "[WHISPERING]",
                "[PHASE_1]", "[DELIVERY:]", "[DRAMATIC_PAUSE]"):
        if tag in text:
            errors.append(f"forbidden tag: {tag}")

    # [MUSIC] count 3-5
    mu = text.count("[MUSIC]")
    if not (3 <= mu <= 5):
        errors.append(f"[MUSIC] count {mu} (need 3-5)")

    # Word count age 2-5: 50-200; 6-8: 160-320; 9-12: 240-400
    age = d.get("age_group", "")
    body_words = len(re.sub(r"\[[^\]]+\]\s*", "", text).split())
    bands = {"2-5": (50, 200), "6-8": (160, 320), "9-12": (240, 400)}
    band = bands.get(age, (50, 400))
    if not (band[0] <= body_words <= band[1]):
        errors.append(f"word count {body_words} not in {band} for age {age}")

    # characterType canonical
    if d.get("characterType") not in CANONICAL_CHARACTER_TYPES:
        errors.append(f"characterType '{d.get('characterType')}' not canonical")

    # Simile constructions
    errors.extend(_check_simile_constructions(text_lower))

    return errors


# ───────────────────────────────────────────────────────────────────────
# LONG STORY
# ───────────────────────────────────────────────────────────────────────

def validate_long_story(d: dict) -> list[str]:
    errors: list[str] = []
    full = d.get("full_text_roman", "") or ""
    text = (
        d.get("phase_1_text_roman", "") + "\n"
        + d.get("phase_2_text_roman", "") + "\n"
        + d.get("phase_3_text_roman", "")
    )
    text_lower = text.lower()

    # Devanagari rejection in user-facing fields
    for f in ("title", "world_name", "world_description",
              "mystery", "resolution", "repeated_phrase"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious
    for w in _religious_hits(text_lower):
        errors.append(f"religious content: '{w}'")

    # Conversational markers ≥5 for long stories
    n = sum(1 for m in CONVERSATIONAL_MARKERS if m in text_lower)
    if n < 5:
        errors.append(f"only {n} conversational markers (need ≥5)")

    # Phase structure
    for ph in ("[PHASE_1]", "[PHASE_2]", "[PHASE_3]"):
        if ph not in full:
            errors.append(f"missing {ph}")

    # Phrase count ≥3
    if full.count("[PHRASE]") < 3:
        errors.append("[PHRASE] count <3")

    # Empty phrase leak
    if re.search(r"\[PHRASE\]\s*\.\.\.\s*\[/PHRASE\]", full):
        errors.append("empty [PHRASE] leak")

    # Breathe count ≥4
    if full.count("[BREATHE]") < 4:
        errors.append("[BREATHE] count <4")
    if "[BREATHE_GUIDE]" not in full:
        errors.append("missing [BREATHE_GUIDE]")

    # Song
    if "[SONG_SEED:" not in full:
        errors.append("missing [SONG_SEED:]")

    # Whisper
    if "[WHISPER]" not in full or "[/WHISPER]" not in full:
        errors.append("missing [WHISPER] block")

    # Blacklisted name
    for ch in d.get("characters", []) or []:
        if ch.get("name") in NAME_BLACKLIST:
            errors.append(f"blacklisted name: '{ch['name']}'")

    # Onomatopoeia ≥3
    n = sum(1 for o in ONOMATOPOEIA if o in text_lower)
    if n < 3:
        errors.append(f"only {n} onomatopoeia (need ≥3 for long story)")

    # Dialogue format: must use NAME: "..." form, not embedded prose.
    # Without this check, the LLM produces single-voice narrative and the
    # parser tags everything as narration → only narrator voice ever fires.
    # NAME is uppercase, may contain spaces and dashes, ends with colon.
    name_dialogue = re.findall(
        r'^\s*[A-Z][A-Z _-]{1,30}:\s*"[^"\n]+"',
        full,
        re.MULTILINE,
    )
    if len(name_dialogue) < 3:
        errors.append(
            f"only {len(name_dialogue)} NAME: \"...\" dialogue lines "
            f"(need ≥3); do not embed dialogue inside narration prose"
        )

    # Additionally: every declared [CHARACTER:] should have at least one
    # dialogue line, so character voices actually get used.
    declared = re.findall(r"\[CHARACTER:\s*([A-Za-z][A-Za-z0-9 _-]{1,30})\b", full)
    for name in declared:
        upper = name.upper().strip()
        # Look for that exact name as a dialogue prefix
        pattern = rf'^\s*{re.escape(upper)}\s*:\s*"'
        if not re.search(pattern, full, re.MULTILINE):
            errors.append(
                f"declared character {name!r} has no dialogue line "
                f"(no '{upper}: \"...\"' found) — give them at least one quote"
            )

    return errors


# ───────────────────────────────────────────────────────────────────────
# LULLABY
# ───────────────────────────────────────────────────────────────────────

def validate_lullaby(d: dict) -> list[str]:
    errors: list[str] = []
    lyrics = d.get("lyrics", "") or d.get("lyrics_roman", "") or ""
    lyrics_lower = lyrics.lower()

    # Devanagari rejection in user-facing fields
    for f in ("title", "card_label", "card_subtitle", "lyrics"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")

    # Literary
    for w in LITERARY:
        if w in lyrics_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious
    for w in _religious_hits(lyrics_lower):
        errors.append(f"religious content: '{w}'")

    # Lullaby type valid
    if d.get("lullaby_type") not in (
        "heartbeat", "permission", "rocking", "counting",
        "shield", "closing", "humming", "naming",
    ):
        errors.append(f"invalid lullaby_type: '{d.get('lullaby_type')}'")

    # Char limit (MiniMax v2.5 ceiling for Hindi lullabies)
    if len(lyrics) > 600:
        errors.append(f"lyrics too long: {len(lyrics)} chars (max 600)")

    # Line count: lullabies should have at least 6 non-blank lines
    lines = [l for l in lyrics.split("\n") if l.strip()]
    if len(lines) < 6:
        errors.append(f"too few lyric lines: {len(lines)}")

    return errors


# ───────────────────────────────────────────────────────────────────────
# SILLY SONG
# ───────────────────────────────────────────────────────────────────────

def validate_silly_song(d: dict) -> list[str]:
    errors: list[str] = []
    lyrics = d.get("lyrics", "") or d.get("lyrics_roman", "") or ""
    lyrics_lower = lyrics.lower()

    # Devanagari rejection
    for f in ("title", "lyrics", "card_label", "card_subtitle", "anthem"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")

    # Literary (silly songs include vidyalay)
    for w in LITERARY:
        if w in lyrics_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious (hardened)
    for w in _religious_hits(lyrics_lower):
        errors.append(f"religious content: '{w}'")

    # Sound effect required
    if "*" not in lyrics:
        errors.append("missing asterisked sound effect")

    # Line counts
    text_lines = [
        l for l in lyrics.split("\n")
        if l.strip() and not l.strip().startswith("[")
    ]
    if len(text_lines) > 20:
        errors.append(f"too many lines: {len(text_lines)}")
    for i, line in enumerate(text_lines):
        if len(line.split()) > 8:
            errors.append(f"line {i}: too many words ({len(line.split())})")

    # Char limit (body excluding section tags)
    body = re.sub(r"\[[^\]]+\]\s*", "", lyrics).strip()
    if len(body) > 500:
        errors.append(f"lyrics body too long: {len(body)} chars (max 500)")

    # Banned simile constructions (5 patterns)
    errors.extend(_check_simile_constructions(lyrics_lower))

    # Choruses identical (extract by [chorus])
    chorus_blocks = re.findall(r"\[chorus\]\s*\n((?:(?!\n\[).)*)", lyrics, re.DOTALL)
    chorus_blocks = [c.strip() for c in chorus_blocks]
    if len(chorus_blocks) >= 2 and chorus_blocks[0] != chorus_blocks[1]:
        errors.append("choruses must be identical")

    return errors


# ───────────────────────────────────────────────────────────────────────
# POEM
# ───────────────────────────────────────────────────────────────────────

def validate_poem(d: dict) -> list[str]:
    errors: list[str] = []
    text = d.get("poem_text", "") or d.get("poem_text_roman", "") or ""
    text_lower = text.lower()
    poem_type = d.get("poem_type", "sound")

    # Devanagari
    for f in ("title", "poem_text"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious (hardened)
    for w in _religious_hits(text_lower):
        errors.append(f"religious content: '{w}'")

    # title_en
    if not d.get("title_en"):
        errors.append("missing title_en")

    # Lines 8-16
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 8:
        errors.append(f"too short: {len(lines)} lines (min 8)")
    if len(lines) > 16:
        errors.append(f"too long: {len(lines)} lines (max 16)")

    # Words/line ≤8; matras: spec says ≤9 (sound/nonsense), ≤11 (question)
    # but our Roman-Hindi matra approximator overcounts long-vowel digraphs
    # by ~2 in words like "ghoomega" / "kahaani" — relaxed to 12/14 to
    # absorb that variance while still rejecting clearly-too-long lines.
    matra_limit = 14 if poem_type == "question" else 12
    for i, line in enumerate(lines):
        if len(line.split()) > 8:
            errors.append(f"line {i}: too many words")
        if _approximate_matras(line) > matra_limit:
            errors.append(f"line {i}: matras > {matra_limit} for {poem_type}")

    # Char limit
    if len(text) > 500:
        errors.append(f"too long: {len(text)} chars")

    # No section tags
    for tag in ("[verse", "[chorus", "[bridge", "[opening"):
        if tag in text_lower:
            errors.append(f"section tag: {tag}")

    return errors


def _approximate_matras(line: str) -> int:
    s = re.sub(r"\*[^*]*\*", "", line)
    s = re.sub(r"[^a-zA-Z\s]", " ", s.lower())
    matras = 0
    for word in s.split():
        long_count = len(re.findall(r"aa|ee|oo|ai|au|ou", word))
        short_word = re.sub(r"aa|ee|oo|ai|au|ou", "", word)
        short_count = len(re.findall(r"[aeiou]", short_word))
        if long_count == 0 and short_count == 0 and word:
            matras += 1
        else:
            matras += 2 * long_count + short_count
    return matras


VALIDATORS = {
    "short_story": validate_short_story,
    "long_story":  validate_long_story,
    "lullaby":     validate_lullaby,
    "silly_song":  validate_silly_song,
    "poem":        validate_poem,
}


# ═══════════════════════════════════════════════════════════════════════
# SEVERITY CLASSIFICATION (for the QA critic layer)
#
# MAJOR  → can't be safely patched by a critic; trigger full regen
# MINOR  → mechanical issue that targeted edits can fix
#
# Per user feedback:
#   - missing diversityFingerprint fields → MAJOR (feeds anti-duplication;
#     wrong values cascade for the next 10 stories)
#   - primary character with no dialogue → MAJOR (would require fabricating
#     content, not editing)
#   - religious / Devanagari / blacklisted name / phase structure → MAJOR
#   - dict-shape full_text_roman → MAJOR (handled upstream by shape() now)
#   - dialogue embedded in narration → MINOR (reformatting only; word count
#     must not increase >10%)
#   - tag count off by 1-3 → MINOR
#   - onomatopoeia / conversational markers / matras / word count → MINOR
# ═══════════════════════════════════════════════════════════════════════

# Substring patterns mapped to severity. First match wins.
_MAJOR_PATTERNS = [
    "Devanagari in",
    "missing [PHASE_",
    "religious content:",
    "blacklisted name:",
    "characterType",
    "section tag found:",          # poem with [verse]/[chorus] is structurally wrong
    "primary character has no dialogue",
    "missing diversityFingerprint",
    "literary Hindi:",             # cascades — register slip is a creative defect
    "Choruses must be identical",  # silly-song chorus identity is structural
]

# Everything else defaults to MINOR. List below is for clarity / docs.
_MINOR_PATTERNS = [
    "[MUSIC] count",
    "[BREATHE] count",
    "[PHRASE] count",
    "[BREATHE_GUIDE]",
    "[SONG_SEED:",
    "[WHISPER]",
    "onomatopoeia",
    "conversational markers",
    "word count",
    "matras >",
    "too short:",
    "too many lines",
    "too few lyric lines",
    "lyrics body too long",
    "lyrics too long:",
    "Missing asterisked sound effect",
    "missing title_en",
    "missing morals",
    "forbidden tag:",
    "Missing [COVER:]",
    "secondary character has no dialogue",
    "NAME: \"...\" dialogue lines",
    "declared character",          # character no-dialogue (severity refined below)
    "banned simile:",
    "empty [PHRASE]",
    "invalid lullaby_type:",
    "too many words",
    "too long:",                   # poem char limit
]


def _classify(message: str, content_type: str, raw_data: dict) -> str:
    """Return 'major' or 'minor' for an error message string.

    Special case: 'declared character X has no dialogue' depends on whether
    X is the primary character (≥2 mentions in full text) or secondary.
    """
    if "declared character" in message and "has no dialogue" in message:
        # Extract character name and count mentions in full text body
        m = re.search(r"declared character ['\"]?([A-Za-z][A-Za-z0-9 _-]+)", message)
        if m:
            char_name = m.group(1).strip()
            text = (
                raw_data.get("full_text_roman", "")
                or raw_data.get("text", "")
                or ""
            )
            mentions = len(re.findall(rf"\b{re.escape(char_name)}\b", text))
            return "major" if mentions >= 2 else "minor"
        return "minor"

    for pat in _MAJOR_PATTERNS:
        if pat in message:
            return "major"
    return "minor"  # default — most regex-flagged issues are mechanical


def validate_structured(content_type: str, data: dict) -> list[dict]:
    """Run the type-specific validator and tag each error with severity.

    Returns list of dicts: {severity, rule, detail}. Empty list means OK.
    Used by the QA critic layer to decide minor-fix vs full-regen.
    """
    if content_type not in VALIDATORS:
        return []
    raw_messages = VALIDATORS[content_type](data)
    out = []
    for msg in raw_messages:
        out.append({
            "severity": _classify(msg, content_type, data),
            "rule": msg.split(":")[0].strip()[:60],   # short identifier
            "detail": msg,
        })
    return out


def has_major(structured_errors: list[dict]) -> bool:
    return any(e.get("severity") == "major" for e in structured_errors)


def only_minor(structured_errors: list[dict]) -> bool:
    return bool(structured_errors) and not has_major(structured_errors)

