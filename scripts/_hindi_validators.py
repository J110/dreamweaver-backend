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

DEITY_NAMES = [
    "bhagwaan", "ishvar", "deva ", "devi ", "lakshmi", "ganesh",
    "shiv", "krishn", "ram ", "hanuman", "durga", "saraswati",
    "vishnu", "kali", "allah", "khuda", "rabb", "yesu", "jesus",
]
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
    for w in RELIGIOUS_ALL:
        if w in text_lower:
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
    for w in RELIGIOUS_ALL:
        if w in text_lower:
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
    for w in RELIGIOUS_ALL:
        if w in lyrics_lower:
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
    for w in RELIGIOUS_ALL:
        if w in lyrics_lower:
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
    for w in RELIGIOUS_ALL:
        if w in text_lower:
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
