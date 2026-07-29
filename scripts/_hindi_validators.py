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

Pending validation calibration follow-ups (see 2026-05-19 cron analysis):
    1. FIXED 2026-06-06: HI 9-12 short_story word band lowered from
       (240,400) to (180,350). 12-sample calibration: Mistral produces
       166-314w (median 252) for Hindi 9-12. Stories >=180w are complete
       arcs; <180w feel truncated. Prior 240 floor was English-derived
       and unreachable (42% failure rate).
    2. EN poem 8-word-per-line cap consistently exceeded by 1 word.
    3. EN story banned word "however" not enumerated in initial prompt.
    4. EN story sentences over per-age cap by 1-3 words.
    Items 2-4 are model compliance drift; addressing requires adjusting
    initial generation prompts to surface constraints upfront + tightening
    retry feedback to be more surgical. Defer to prompt engineering session.
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
# positives on common Hindi/English words: "ram" would otherwise match naram
# (soft), garam (warm), aaram (rest), param (supreme); "deva" → devar
# (brother-in-law); "kali" → kalikaal (era), kalindi (river/name); "rabb"
# → rabbit; "yesu" → yesudaas (composer). "shiv" stays substring on purpose
# (matches shivling, which IS religious).
DEITY_NAMES = [
    "bhagwaan", "ishvar", "lakshmi", "ganesh",
    "shiv", "krishn", "hanuman", "durga", "saraswati",
    "vishnu", "allah", "khuda", "jesus",
]
# Word-boundary-checked deities (catch the standalone form, not as substring)
DEITY_WORD_BOUNDARY = ["ram", "deva", "devi", "kali", "rabb", "yesu"]
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

# Conversational markers — matched with case-insensitive word boundaries to
# handle sentence-initial caps and punctuation-terminated tokens uniformly.
# Substring matching (the previous approach) missed "Toh phir" at sentence
# start (no leading space) and "Na." / "bas," (no trailing space).
_CONVERSATIONAL_MARKERS_RE = re.compile(
    r"\b(?:toh|na|arre|pata hai|chalo|dekho|suno|hai na|"
    r"aur phir|bas|achha|zara)\b",
    re.IGNORECASE,
)


def _count_conversational_markers(text: str) -> int:
    return len(_CONVERSATIONAL_MARKERS_RE.findall(text or ""))

ONOMATOPOEIA = [
    "sarr", "tap tap", "chhap", "khat", "dheere dheere",
    "chi chi", "gunghun", "jhoom", "tip tip", "patak", "thak thak",
]

BANNED_SIMILE_NOUNS = [
    "udaas", "khush", "akela", "toota", "khaali", "chup",
    "andhera", "thanda", "baadal", "chhaaya", "shoonya",
    "hawa", "patthar", "sapna", "bhoot", "fusphusahat",
]

# Axis-aware char caps for silly_song body. Default 500; combos where the
# template's structural baseline approaches the cap get extra headroom.
# Log survey (pipeline_hi_cron.log, 30d): 9-12 + observation moods (calm and
# anxious) account for 12 of ~27 length failures — borderline by template
# arithmetic (16-19 lines × ~30 chars + chorus repeat ≈ 500-570 baseline).
_SILLY_SONG_DEFAULT_CAP = 500
_SILLY_SONG_CAPS = {
    ("9-12", "observation"): 550,
}


def silly_song_cap_for(axes: dict | None) -> int:
    if not axes:
        return _SILLY_SONG_DEFAULT_CAP
    key = (axes.get("age_group"), axes.get("category"))
    return _SILLY_SONG_CAPS.get(key, _SILLY_SONG_DEFAULT_CAP)


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

    # Devanagari requirement on TTS-engine input fields. If absent or
    # Roman-only, audio renders with degraded Hindi phonemes (silent
    # fallback in _hindi_generators.py).
    for f in ("text_deva", "hook_deva"):
        if not _has_devanagari(d.get(f, "") or ""):
            errors.append(f"missing Devanagari in '{f}' (TTS engine input)")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious
    for w in _religious_hits(text_lower):
        errors.append(f"religious content: '{w}'")

    # Conversational markers ≥2
    n = _count_conversational_markers(text)
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

    # Word count age 2-5: 50-200; 6-8: 160-320; 9-12: 180-350
    # (9-12 calibrated 2026-06-06: Hindi Roman script is ~30% more compact
    # than English; Mistral produces 166-314w, median 252. 180 floor catches
    # truncated stories; 350 cap matches observed ceiling. 12-sample test.)
    age = d.get("age_group", "")
    body_words = len(re.sub(r"\[[^\]]+\]\s*", "", text).split())
    bands = {"2-5": (50, 200), "6-8": (160, 320), "9-12": (180, 350)}
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

    # solo / arrival / pure_settling are short + low-dialogue + low-ornament BY
    # DESIGN. Format-mins are shape-aware (like the picker's age/mood rules):
    # these shapes get relaxed [PHRASE]/[BREATHE]/onomatopoeia/marker/word/
    # dialogue mins; dialogue-heavy shapes keep the full set. Re-bitten: a
    # genuinely breath-barren or fragment-length story still fails.
    is_solo = d.get("cast_structure", "") == "solo"
    low_content = is_solo or d.get("narrative_shape", "") in ("arrival", "pure_settling")

    # Devanagari rejection in user-facing fields
    for f in ("title", "world_name", "world_description",
              "mystery", "resolution", "repeated_phrase"):
        if _has_devanagari(d.get(f, "") or ""):
            errors.append(f"Devanagari in '{f}'")

    # Devanagari requirement on TTS-engine input. If absent or Roman-only,
    # audio renders with degraded Hindi phonemes (silent fallback in
    # _hindi_generators.py).
    if not _has_devanagari(d.get("full_text_deva", "") or ""):
        errors.append("missing Devanagari in 'full_text_deva' (TTS engine input)")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"literary Hindi: '{w}'")

    # Religious
    for w in _religious_hits(text_lower):
        errors.append(f"religious content: '{w}'")

    # Conversational markers: ≥5 full, ≥3 low-content (shorter stories carry fewer)
    _mark_min = 3 if low_content else 5
    n = _count_conversational_markers(text)
    if n < _mark_min:
        errors.append(f"only {n} conversational markers (need ≥{_mark_min})")

    # Phase structure
    for ph in ("[PHASE_1]", "[PHASE_2]", "[PHASE_3]"):
        if ph not in full:
            errors.append(f"missing {ph}")

    # Phrase count: ≥2 (style tag; HI reliably lands 2, 3 was unmet)
    if full.count("[PHRASE]") < 2:
        errors.append("[PHRASE] count <2")

    # Empty phrase leak
    if re.search(r"\[PHRASE\]\s*\.\.\.\s*\[/PHRASE\]", full):
        errors.append("empty [PHRASE] leak")

    # Phrase-shatter guard: the repeated phrase must stay WHOLE, not be split
    # word-by-word across [PHRASE] tags (the same-every-story ending monotony).
    _ptags = re.findall(r"\[PHRASE\](.*?)\[/PHRASE\]", full, re.S)
    if sum(1 for p in _ptags if len(p.split()) == 1) >= 2:
        errors.append("repeated phrase shattered into single-word [PHRASE] fragments — "
                      "keep it whole in one tag; vary the ending per phase3_texture")

    # Breathe swells (PHYSIOLOGY presence): ≥3 full, ≥2 low-content. This
    # guarantees breath is PRESENT; A3 validates each is a real long exhale.
    # A 0-1 breath story still fails — presence is never waived.
    _breathe_min = 2 if low_content else 3
    if full.count("[BREATHE]") < _breathe_min:
        errors.append(f"[BREATHE] count <{_breathe_min}")

    # Word-count floor — a long story must actually be long. Without this the
    # model under-writes to ~1/3 length (629 vs 1520+ for age 6-8).
    # Realistic floors: reject Groq-fallback fragments, not chase the old
    # aspirational 1520-2240 band that production HI stories (~608-714 words)
    # never met. A clean Mistral run (~950+) clears these.
    _age = d.get("age_group", "")
    # Floors match reality (production ~608-714w) and are SHAPE-AWARE: solo/
    # arrival/pure_settling are legitimately shorter, so they get a lower floor
    # instead of being forced to a length they never reach. Still rejects
    # genuine sub-fragments; the descent is guaranteed length-independently by A2/A4.
    _floor = ({"2-5": 380, "6-8": 480, "9-12": 480} if low_content
              else {"2-5": 450, "6-8": 600, "9-12": 600}).get(_age)
    _wc = len(re.sub(r"\[[^\]]*\]", " ", full).split())
    if _floor and _wc < _floor:
        errors.append(f"word count {_wc} below floor {_floor} for age {_age} — write the full length, not a fragment")

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

    # Onomatopoeia: ≥2 full, ≥1 low-content (ornament; low-content shapes are
    # sparse by design). 0 still rejects a truly barren story.
    _ono_min = 1 if low_content else 2
    n = sum(1 for o in ONOMATOPOEIA if o in text_lower)
    if n < _ono_min:
        errors.append(f"only {n} onomatopoeia (need ≥{_ono_min})")

    # Dialogue: solo may be pure narration (0 — one character, narrator-led is
    # a valid solo); other low-content shapes ≥1; dialogue-driven shapes ≥3. A
    # dialogue-empty NON-low story is still caught (single-voice narration).
    min_dialogue = 0 if is_solo else (1 if low_content else 3)
    name_dialogue = re.findall(
        r'^\s*[A-Z][A-Z _-]{1,30}:\s*"[^"\n]+"',
        full,
        re.MULTILINE,
    )
    if len(name_dialogue) < min_dialogue:
        errors.append(
            f"only {len(name_dialogue)} NAME: \"...\" dialogue lines "
            f"(need ≥{min_dialogue}); do not embed dialogue inside narration prose"
        )

    # Every declared [CHARACTER:] should speak — dialogue-driven shapes only;
    # low-content shapes may keep a mostly-silent companion or be solo-narrated.
    if not low_content:
        declared = re.findall(r"\[CHARACTER:\s*([A-Za-z][A-Za-z0-9 _-]{1,30})\b", full)
        for name in declared:
            upper = name.upper().strip()
            pattern = rf'^\s*{re.escape(upper)}\s*:\s*"'
            if not re.search(pattern, full, re.MULTILINE):
                errors.append(
                    f"declared character {name!r} has no dialogue line "
                    f"(no '{upper}: \"...\"' found) — give them at least one quote"
                )

    # Physiology gate (A1-A4) — the sleep guarantee, now ENFORCED at accept
    # (was only post-hoc). Physiology-fail -> regenerate/re-pick, so no
    # arousal-rising / breath-absent / non-dissolving HI story publishes.
    import _physiology_validators as _PHYS
    for _pn, _po, _pr in _PHYS.validate_all(full)[1]:
        if not _po:
            errors.append(f"physiology {_pr}")
    # Cast gate: solo = no second VOICE (declared or undeclared). Counts
    # speaking entities via the shared helper, so an undeclared talking
    # companion can't slip through a declaration-only check.
    if d.get("cast_structure") == "solo":
        import _story_axes as _SA
        _cv = _SA.solo_cast_violation(full, full.count("[CHARACTER:"))
        if _cv:
            errors.append(_cv)

    # Settling-gesture tic gate: the DEFECT is the intra-story BLUR — the same
    # eye-close beat repeating 3+ times (often across multiple characters). A
    # natural 1-2 closes in an 800-word story is how a human writer uses the
    # gesture, not blur — the model's unconstrained rate is 4-7x, so cap at the
    # real defect threshold (3+), not an aspirational zero. Reality-matched like
    # the length floors. Count "band" preceded by aankh* within 3 words,
    # EXCLUDING negated ones via the shared _negated (±2) helper ("aankhen band
    # NAHIN kiya" = did NOT close — must not count; same negation lesson as A1).
    _ws = re.findall(r"\w+", full.lower())
    _eye_closes = 0
    for _i, _w in enumerate(_ws):
        if _w == "band" and any(_ws[_j].startswith("aankh") for _j in range(max(0, _i - 3), _i)):
            if not _PHYS._negated(_ws, _i):
                _eye_closes += 1
    if _eye_closes > 2:
        errors.append(f"settling-gesture tic: eyes close {_eye_closes}x — max 2 "
                      "eye-closes per story; the same settling beat repeating 3+ times "
                      "blurs it. Vary the gesture (breath slows, body softens, stillness "
                      "spreads) instead of repeating aankh-band")

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

    # Devanagari requirement on TTS-engine input. If absent or Roman-only,
    # MiniMax v2.5 renders with degraded Hindi phonemes (silent fallback
    # in _hindi_generators.py:601).
    if not _has_devanagari(d.get("lyrics_deva", "") or ""):
        errors.append("missing Devanagari in 'lyrics_deva' (TTS engine input)")

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

    # Devanagari requirement on TTS-engine input. If absent or Roman-only,
    # ElevenLabs Music renders with degraded Hindi phonemes (silent
    # fallback in _hindi_generators.py:773).
    if not _has_devanagari(d.get("lyrics_deva", "") or ""):
        errors.append("missing Devanagari in 'lyrics_deva' (TTS engine input)")

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

    # Char limit (body excluding section tags). Axis-aware: caller injects
    # axes via d["_axes"] from generate_silly_song; absent → default 500.
    body = re.sub(r"\[[^\]]+\]\s*", "", lyrics).strip()
    cap = silly_song_cap_for(d.get("_axes"))
    if len(body) > cap:
        errors.append(f"lyrics body too long: {len(body)} chars (max {cap})")

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

    # Devanagari requirement on TTS-engine input. If absent or Roman-only,
    # MiniMax v2.5 renders with degraded Hindi phonemes (silent fallback
    # in _hindi_generators.py:976).
    if not _has_devanagari(d.get("poem_text_deva", "") or ""):
        errors.append("missing Devanagari in 'poem_text_deva' (TTS engine input)")

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

