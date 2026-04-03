#!/usr/bin/env python3
"""Generate silly songs using the Battle Cry approach.

Two-step LLM process:
  1. Generate rhyme families from the battle cry phrase
  2. Assemble lyrics using the rhyme palette

Then: validate → generate audio (MiniMax) → generate cover (FLUX)

Usage:
    # Generate one song per age group (test mode)
    python3 scripts/generate_silly_songs_battlecry.py --test

    # Generate all 6 test songs
    python3 scripts/generate_silly_songs_battlecry.py --all

    # Generate a specific battle cry
    python3 scripts/generate_silly_songs_battlecry.py --cry not_tired

    # Skip audio/cover generation (lyrics only)
    python3 scripts/generate_silly_songs_battlecry.py --test --lyrics-only

    # Force regenerate even if files exist
    python3 scripts/generate_silly_songs_battlecry.py --test --force
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

# Load .env
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

try:
    from mistralai import Mistral
except ImportError:
    print("ERROR: mistralai required — pip install mistralai")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx")
    sys.exit(1)

try:
    import replicate
except (ImportError, Exception):
    replicate = None

try:
    from PIL import Image
except ImportError:
    Image = None

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "silly_songs"
AUDIO_DIR = BASE_DIR / "public" / "audio" / "silly-songs"
COVERS_DIR = BASE_DIR / "public" / "covers" / "silly-songs"
OUTPUT_DIR = BASE_DIR / "output" / "silly_songs_battlecry"

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Battle Cry Test Songs ────────────────────────────────────────────

TEST_SONGS = [
    # Ages 2-5
    {"cry_id": "not_tired",    "cry": "I'm not tired",     "age": "2-5"},
    {"cry_id": "dont_like_it", "cry": "I don't like it",   "age": "2-5"},
    # Ages 6-8
    {"cry_id": "not_fair",     "cry": "That's not fair",   "age": "6-8"},
    {"cry_id": "but_why",      "cry": "But why",           "age": "6-8"},
    # Ages 9-12
    {"cry_id": "i_forgot",     "cry": "I forgot",          "age": "9-12"},
    {"cry_id": "in_a_minute",  "cry": "In a minute",       "age": "9-12"},
]

# One per age group for --test mode
TEST_MODE_SONGS = [
    {"cry_id": "not_tired",  "cry": "I'm not tired",   "age": "2-5"},
    {"cry_id": "not_fair",   "cry": "That's not fair",  "age": "6-8"},
    {"cry_id": "i_forgot",   "cry": "I forgot",         "age": "9-12"},
]

# ── Instrument & Tempo Diversity ─────────────────────────────────────

INSTRUMENT_POOLS = {
    "2-5": [
        "ukulele and hand claps",
        "kalimba and stomps",
        "acoustic guitar and finger snaps",
        "xylophone and tambourine",
        "banjo and shaker",
    ],
    "6-8": [
        "guitar and drums",
        "piano and claps",
        "ukulele and cajón",
        "acoustic guitar and beatbox",
        "mandolin and tambourine",
    ],
    "9-12": [
        "acoustic guitar and snare",
        "piano and drums",
        "ukulele and groovy bass",
        "guitar and beatbox",
        "keys and funky bass",
    ],
}

# Energetic — silly songs are NOT sleep content, they're pre-bedtime fun
TEMPO_RANGE = {
    "2-5":  (116, 126),
    "6-8":  (112, 122),
    "9-12": (108, 118),
}

# ── Mood mapping ─────────────────────────────────────────────────────
# Which battle cries fit which child mood. A wired child needs energy
# channeled; a sad child needs their feeling acknowledged.
MOOD_TO_BATTLE_CRIES = {
    "wired": [
        "not_tired", "five_minutes", "one_more", "no_no_no",
        "dont_wanna", "in_a_minute", "almost_done",
        "i_am_doing_it", "not_sleepy", "im_coming",
    ],
    "curious": [
        "but_why", "do_i_have_to", "cant_find_it",
        "i_forgot", "five_minutes", "one_more",
    ],
    "calm": [
        "five_minutes", "one_more", "im_coming",
        "almost_done", "in_a_minute", "not_sleepy",
    ],
    "sad": [
        "dont_want_to", "dont_like_it", "carry_me",
        "dont_wanna", "pick_me_up", "i_want_it",
    ],
    "anxious": [
        "dont_wanna", "carry_me", "no_no_no",
        "dont_want_to", "pick_me_up", "dont_like_it",
    ],
    "angry": [
        "not_fair", "not_my_fault", "wasnt_me",
        "he_started_it", "you_said", "leave_me_alone",
        "so_what", "whatever", "mine",
    ],
}

# Mood affects the energy description in the style prompt
SONG_MOOD_ENERGY = {
    "wired":   "super bouncy, high energy, impossible to sit still",
    "curious": "bouncy but thoughtful, groove with space to think",
    "calm":    "gentle bounce, warm and easy, swaying not jumping",
    "sad":     "soft bounce, tender, warm not heavy, comforting rhythm",
    "anxious": "steady predictable bounce, reassuring, safe groove",
    "angry":   "strong groove, firm rhythm, satisfying stomp energy",
}

# Mood adjusts tempo (offset from base range)
SONG_MOOD_TEMPO_OFFSET = {
    "wired":   +4,
    "curious":  0,
    "calm":    -6,
    "sad":     -8,
    "anxious": -4,
    "angry":   +2,
}


# Age-specific style templates — prioritise vocal CLARITY over speed.
# Instruments can bounce; the voice doesn't need to race.
SILLY_SONG_STYLES = {
    "2-5": (
        "Catchy children's song, {instruments}, {tempo} BPM, "
        "bouncy beat, warm clear child vocal, "
        "sing each word clearly and slowly, "
        "fun and silly, not rushed"
    ),
    "6-8": (
        "Catchy children's song, {instruments}, {tempo} BPM, "
        "groovy beat, warm clear vocal, "
        "every word easy to understand, "
        "fun and bouncy, not fast"
    ),
    "9-12": (
        "Catchy children's song, {instruments}, {tempo} BPM, "
        "cool beat, clear confident vocal, "
        "each line sung clearly not rushed, "
        "groovy and fun"
    ),
}


def build_style_prompt(age_group: str, recent_songs: list = None,
                       mood: str = None) -> tuple:
    """Build a style prompt with varied instruments and tempo.

    Args:
        mood: Child mood — adjusts energy description and tempo offset.

    Returns: (style_prompt, instruments, tempo)
    """
    recent_songs = recent_songs or []

    # Pick instruments not used in last 3 songs
    recent_instruments = [s.get("instruments") for s in recent_songs[-3:]]
    available = [i for i in INSTRUMENT_POOLS[age_group]
                 if i not in recent_instruments]
    if not available:
        available = INSTRUMENT_POOLS[age_group]
    instruments = random.choice(available)

    # Pick tempo within range, adjusted by mood
    lo, hi = TEMPO_RANGE[age_group]
    offset = SONG_MOOD_TEMPO_OFFSET.get(mood, 0) if mood else 0
    tempo = random.randint(lo + offset, hi + offset)

    if mood and mood in SONG_MOOD_ENERGY:
        # Mood-aware style: use mood energy instead of age template
        energy = SONG_MOOD_ENERGY[mood]
        prompt = (
            f"Catchy children's song, {instruments}, {tempo} BPM, "
            f"{energy}, clear warm vocal, every word easy to understand"
        )
    else:
        # Use age-specific style template for vocal clarity
        template = SILLY_SONG_STYLES.get(age_group, SILLY_SONG_STYLES["6-8"])
        prompt = template.format(instruments=instruments, tempo=tempo)

    if len(prompt) > 295:
        prompt = prompt[:295]

    return prompt, instruments, tempo

# Cover descriptions are now generated from lyrics via [COVER:] tag.
# No more hardcoded COVER_DESCRIPTIONS dict — each song gets a unique
# cover based on its own funniest/most visual moment.

# ── LLM Prompts ──────────────────────────────────────────────────────

SCENE_PROMPT = """Battle cry: "{battle_cry}"
Age group: {age_group}

Describe the EXACT MOMENT this child says "{battle_cry}."

Where are they? Who are they talking to? What just happened
one second before they said it?

This must be ONE specific moment that every child in this
age group has lived. Not a category of moments — ONE moment.
Specific enough that any parent reading it thinks "that
happened last Tuesday."

2 sentences maximum. Be concrete — name the objects,
the room, the time of day, what the parent just said."""

LYRICS_PROMPT = """Write a silly song for ages {age_group}.

SCENE: {scene}
BATTLE CRY: "{battle_cry}"

Write it the way a child actually talks. Every line should
be a complete thought — something a real child has said
out loud in this exact situation.

The lines should rhyme naturally. If a rhyme forces you
to use a weird word or break a sentence into fragments,
skip that rhyme and find one that flows.

STRUCTURE:
This song must be SHORT. The audio generator produces ~60
seconds. Your lyrics must fit comfortably in that time with
room for the melody to breathe.

[verse 1] — 4 lines. Real complaints from this scene.
[chorus]  — 3-4 lines. The battle cry repeated. Identical every time.
[verse 2] — 4 lines. Same complaints, pushed further.
[chorus]  — identical repeat
[ending]  — 2-3 lines. The chorus dissolving into sleep or surrender.

That's the ENTIRE song. No verse 3. No bridge. No parent
responses in the lyrics (those are added separately in audio).

Maximum 20 lines total.

SYLLABLE RULE:
Maximum 9 syllables per line. Not words — SYLLABLES.
Use short, simple, one-syllable words whenever possible.

"Mama said it's time for bed" = 8 syllables ✓
"My duck's a pirate he don't take a bath" = 11 syllables ✗

ONE THOUGHT PER LINE:
Never join two ideas with a dash or comma.
"My duck's a pirate—he don't take a bath" is TWO thoughts.
Split them: "My duck's a pirate now" + "He won't take a bath"

Use small words. "Cat" not "dinosaur." "Hot" not "distress."
"Lost" not "crumpled." The simpler the word, the more
time the singer gives it, the clearer the child hears it.

Every line must have SPACE to be sung clearly. If the child
can't understand the words, the song fails.

V1: real things the child says in this moment
V2: the same situation exaggerated — pushed further

The CHORUS does the heavy lifting through repetition,
not the verses through variety.

RHYME FREEDOM:
Each verse can use its own rhyme pattern. You do NOT need
to rhyme the same sound across all verses.

V1 can rhyme with -ed/-ight
V2 can rhyme with -ack/-old

The CHORUS is the constant. The verses are free.

If you find yourself adding nonsense suffixes to make words
rhyme ("trim it", "dim it", "fin bit", "din bit"), STOP.
Switch to a different rhyme sound for that verse. There are
thousands of rhyme families. Use more than one.

The song should sound like a child TALKING — arguing,
negotiating, protesting — set to a bouncy beat.
Not poetry. Not wordplay. Just how kids sound.

SENSE CHECK:
Every line must make sense as a standalone sentence.
Read each line by itself. If it doesn't mean anything
without the line before it ("the apple rolls like a
sad bridge" means nothing), rewrite it as something
a child would actually say in this moment.

QUALITY TARGET — this is what good looks like:
"Mama said it's time for bed / But I've got things to do instead /
I haven't hugged the cat goodnight / I haven't checked the moon is bright"
Every line is a COMPLETE SENTENCE a child would say out loud. Natural rhymes.
No fragments. No clever wordplay. Just a child negotiating.

Output with [verse 1], [verse 2], [chorus], and [ending] tags.
No title. No markdown code blocks. No [parent] sections.

THEN on its own line:
[COVER: one-sentence visual description of the funniest moment, bold cartoon style, bright colors, energetic]
"""

# ── Syllable Counter ─────────────────────────────────────────────────

def count_syllables(word: str) -> int:
    """Rough syllable count using vowel groups."""
    word = word.lower().strip("!?.,*()—–-\"'[]")
    if not word:
        return 0
    count = len(re.findall(r'[aeiouy]+', word))
    if word.endswith('e') and count > 1:
        count -= 1
    return max(1, count)


def extract_sung_lines(lyrics: str) -> list[str]:
    """Extract only singable lines (no tags, no empty lines, no sfx-only)."""
    lines = []
    for line in lyrics.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        # Skip lines that are only sound effects
        if re.match(r'^\*[^*]+\*$', stripped):
            continue
        lines.append(stripped)
    return lines


MAX_SYLLABLES_PER_LINE = 9


def validate_syllable_density(lyrics: str, max_syllables: int = MAX_SYLLABLES_PER_LINE) -> list[tuple[str, int]]:
    """Flag lines with too many syllables. Returns list of (line, syllable_count)."""
    long_lines = []
    for line in extract_sung_lines(lyrics):
        total = sum(count_syllables(w) for w in line.split())
        if total > max_syllables:
            long_lines.append((line, total))
    return long_lines


# ── LLM Calls ────────────────────────────────────────────────────────

def call_mistral(prompt: str, system_msg: str = "", api_key: str = "",
                  max_retries: int = 3) -> str:
    """Call Mistral AI and return the response text. Retries on transient errors."""
    client = Mistral(api_key=api_key)
    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=messages,
                temperature=0.9,  # Higher creativity for songs
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1 and ("500" in str(e) or "503" in str(e)
                                               or "unavailable" in str(e).lower()
                                               or "timeout" in str(e).lower()):
                wait = 15 * (attempt + 1)
                print(f"  ⚠️  Mistral API error (attempt {attempt + 1}): {e}")
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ── Parsing ──────────────────────────────────────────────────────────

def extract_rhyme_data(response: str) -> tuple[str, str, list[str]]:
    """Parse the rhyme family response into (key_word, rhyme_family, lines)."""
    key_word = ""
    rhyme_family = ""
    lines = []

    for line in response.split("\n"):
        line = line.strip()
        if line.upper().startswith("KEY_WORD:"):
            key_word = line.split(":", 1)[1].strip().strip("[]")
        elif line.upper().startswith("RHYME_FAMILY:"):
            rhyme_family = line.split(":", 1)[1].strip().strip("[]")
        elif re.match(r'^\d+[\.\)]\s', line):
            # Numbered line like "1. I had a grape..."
            text = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            if text:
                lines.append(text)

    return key_word, rhyme_family, lines


def extract_lyrics(response: str) -> str:
    """Extract just the lyrics from the LLM response (strip any markdown wrapping)."""
    # Remove markdown code blocks if present
    text = re.sub(r'^```\w*\n?', '', response, flags=re.MULTILINE)
    text = re.sub(r'\n?```$', '', text, flags=re.MULTILINE)
    return text.strip()


def extract_sections(lyrics: str) -> dict[str, list[str]]:
    """Split lyrics into sections by tag."""
    sections = {"verses": [], "choruses": [], "other": []}
    current_type = "other"
    current_lines = []

    for line in lyrics.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("[verse"):
            if current_lines:
                if current_type == "verse":
                    sections["verses"].append("\n".join(current_lines))
                elif current_type == "chorus":
                    sections["choruses"].append("\n".join(current_lines))
                else:
                    sections["other"].append("\n".join(current_lines))
            current_type = "verse"
            current_lines = []
        elif stripped.lower().startswith("[chorus"):
            if current_lines:
                if current_type == "verse":
                    sections["verses"].append("\n".join(current_lines))
                elif current_type == "chorus":
                    sections["choruses"].append("\n".join(current_lines))
                else:
                    sections["other"].append("\n".join(current_lines))
            current_type = "chorus"
            current_lines = []
        elif stripped.lower().startswith("["):
            if current_lines:
                if current_type == "verse":
                    sections["verses"].append("\n".join(current_lines))
                elif current_type == "chorus":
                    sections["choruses"].append("\n".join(current_lines))
                else:
                    sections["other"].append("\n".join(current_lines))
            current_type = "other"
            current_lines = []
        elif stripped:
            current_lines.append(stripped)

    # Final section
    if current_lines:
        if current_type == "verse":
            sections["verses"].append("\n".join(current_lines))
        elif current_type == "chorus":
            sections["choruses"].append("\n".join(current_lines))
        else:
            sections["other"].append("\n".join(current_lines))

    return sections


# ── Validation ───────────────────────────────────────────────────────

MAX_LINES = 20
MAX_WORDS_PER_LINE = 8


def validate_silly_song(lyrics: str, battle_cry: str, age_group: str,
                        scene: str = "") -> tuple[bool, list[str], list[dict]]:
    """Validate essential formula elements + MiniMax length constraints.

    Checks:
    - Battle cry appears in chorus
    - Chorus consistency (non-final choruses identical)
    - At least 2 verses
    - Sound effects present
    - Max 20 lyric lines (fits MiniMax ~60s)
    - Max 8 words per line (warning, not blocking)
    - Character count within MiniMax limit

    Returns (passed, errors, structured_errors).
    """
    sections = extract_sections(lyrics)
    choruses_raw = sections["choruses"]
    chorus_lines = []
    for c in choruses_raw:
        chorus_lines.extend([l for l in c.split("\n") if l.strip()])
    verses = sections["verses"]

    errors = []
    structured = []

    # 1. BATTLE CRY in chorus
    # Normalize smart quotes → ASCII so LLM output matches battle cry strings
    def _normalize(s):
        return s.lower().replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    cry_lower = _normalize(battle_cry)
    cry_words = [w for w in cry_lower.split() if len(w) > 2]
    cry_in_chorus = any(
        all(w in _normalize(l) for w in cry_words)
        for l in chorus_lines
    )
    if not cry_in_chorus:
        errors.append(f"Battle cry '{battle_cry}' not found in chorus")
        structured.append({"type": "missing_cry", "detail": battle_cry})

    # 2. AT LEAST 2 VERSES
    if len(verses) < 2:
        errors.append(f"Only {len(verses)} verse(s) (need at least 2)")
        structured.append({"type": "few_verses", "count": len(verses)})

    # 3. SOUND EFFECTS present
    has_sfx = '*' in lyrics
    if not has_sfx:
        errors.append("No sound effects found")
        structured.append({"type": "no_sfx"})

    # 4. CHORUS CONSISTENCY — non-final choruses must be identical
    # Strip embedded parent responses like *(Mom: "Oh really?")* before comparing,
    # since the LLM often varies these while keeping the actual lyrics identical.
    def _strip_parent_asides(text):
        return re.sub(r'\*\([^)]*\)\*', '', text).strip()
    if len(choruses_raw) >= 2:
        first = _strip_parent_asides(choruses_raw[0])
        for i in range(1, len(choruses_raw) - 1):  # skip last (collapse OK)
            if _strip_parent_asides(choruses_raw[i]) != first:
                errors.append(f"Chorus {i+1} differs from Chorus 1 — must be identical (except final)")
                structured.append({"type": "chorus_inconsistent", "index": i + 1})

    # 5. LINE COUNT — max 20 lines (MiniMax ~60s constraint)
    lyric_lines = [l for l in lyrics.split("\n")
                   if l.strip() and not l.strip().startswith("[")]
    if len(lyric_lines) > MAX_LINES:
        errors.append(f"Too many lines ({len(lyric_lines)}, max {MAX_LINES}) — won't fit in 60s")
        structured.append({"type": "too_many_lines", "count": len(lyric_lines)})

    # 6. WORDS PER LINE — max 8 (warning only, logged but non-blocking)
    long_lines = []
    for line in lyric_lines:
        words = [w for w in line.split() if not w.startswith("*")]
        if len(words) > MAX_WORDS_PER_LINE:
            long_lines.append((line.strip()[:50], len(words)))
    if long_lines:
        print(f"    ⚠️  {len(long_lines)} line(s) over {MAX_WORDS_PER_LINE} words:")
        for text, wc in long_lines[:3]:
            print(f"      {wc}w: {text}...")

    # 7. CHARACTER COUNT for MiniMax
    check_minimax_length(lyrics)

    # 8. NONSENSE SIMILE CHECK — flag lines with "like a [abstract noun]"
    flagged_similes = check_nonsense_similes(lyrics)
    if flagged_similes:
        for flag in flagged_similes:
            print(f"    {flag}")
        errors.append(f"Nonsense simile(s) detected — rewrite lines that don't make sense alone")
        structured.append({"type": "nonsense_simile", "lines": flagged_similes})

    # 9. SYLLABLE DENSITY — max 9 syllables per line (blocking)
    long_syllable_lines = validate_syllable_density(lyrics)
    if long_syllable_lines:
        print(f"    ⚠️  {len(long_syllable_lines)} line(s) over {MAX_SYLLABLES_PER_LINE} syllables:")
        for text, syl_count in long_syllable_lines[:5]:
            print(f"      {syl_count} syl: {text[:60]}...")
        errors.append(f"Too many syllables — {len(long_syllable_lines)} line(s) over {MAX_SYLLABLES_PER_LINE} syllables")
        structured.append({"type": "too_many_syllables", "lines": long_syllable_lines})

    # Info prints (non-blocking)
    if len(verses) >= 2:
        print(f"    V1: {verses[0][:70]}...")
        if len(verses) >= 2:
            print(f"    V2: {verses[-1][:70]}...")
    print(f"    Lines: {len(lyric_lines)}/{MAX_LINES}")

    return (len(errors) == 0, errors, structured)


def retry_with_feedback(lyrics: str, structured_errors: list, age_group: str,
                        battle_cry: str, api_key: str, scene: str = "") -> str:
    """Retry lyrics generation with specific failure feedback.

    Focuses only on essential fixes: missing battle cry, chorus consistency,
    missing sound effects/parent responses.
    """
    feedback_parts = []

    cry_errors = [e for e in structured_errors if e["type"] == "missing_cry"]
    if cry_errors:
        feedback_parts.append(
            f"MISSING BATTLE CRY — the phrase \"{battle_cry}\" must appear in [chorus]."
        )

    chorus_errors = [e for e in structured_errors if e["type"] == "chorus_inconsistent"]
    if chorus_errors:
        feedback_parts.append(
            "CHORUS INCONSISTENCY — all choruses except the final one must be IDENTICAL (same words, same order)."
        )

    sfx_errors = [e for e in structured_errors if e["type"] == "no_sfx"]
    if sfx_errors:
        feedback_parts.append(
            "MISSING SOUND EFFECTS — add a sound effect (*splat*, *crash*) "
            "specific to the scene."
        )

    verse_errors = [e for e in structured_errors if e["type"] == "few_verses"]
    if verse_errors:
        feedback_parts.append(
            f"NOT ENOUGH VERSES — need at least 2 verses (V1: real, V2: exaggerated)."
        )

    line_errors = [e for e in structured_errors if e["type"] == "too_many_lines"]
    if line_errors:
        count = line_errors[0]["count"]
        feedback_parts.append(
            f"TOO MANY LINES — you wrote {count} lines but max is {MAX_LINES}. "
            f"Cut to 2 verses + 2 choruses + ending. No verse 3. No bridge."
        )

    simile_errors = [e for e in structured_errors if e["type"] == "nonsense_simile"]
    if simile_errors:
        flagged = simile_errors[0].get("lines", [])
        feedback_parts.append(
            "NONSENSE SIMILES — these lines contain similes that don't make sense "
            "when read alone. A child would never say these:\n"
            + "\n".join(flagged) +
            "\nRewrite each flagged line as something a real child would say. "
            "If a rhyme forces a nonsense simile, switch to a different rhyme."
        )

    syllable_errors = [e for e in structured_errors if e["type"] == "too_many_syllables"]
    if syllable_errors:
        bad_lines = syllable_errors[0].get("lines", [])
        examples = "\n".join(f"  {syl} syl: \"{text}\"" for text, syl in bad_lines[:5])
        feedback_parts.append(
            f"TOO MANY SYLLABLES — max {MAX_SYLLABLES_PER_LINE} syllables per line. "
            f"These lines are too long to sing clearly:\n{examples}\n"
            "Use shorter words. 'Cat' not 'dinosaur.' 'Hot' not 'distress.' "
            "Never join two ideas with a dash or comma — split into two lines. "
            "'My duck's a pirate—he don't take a bath' is TWO thoughts. "
            "Split: 'My duck's a pirate now' + 'He won't take a bath.'"
        )

    feedback = "\n\n".join(feedback_parts)
    scene_line = f"\nSCENE: {scene}\n" if scene else ""

    retry_prompt = f"""These lyrics for "{battle_cry}" (ages {age_group}) need fixes.
{scene_line}
PROBLEMS:
{feedback}

ORIGINAL LYRICS:
{lyrics}

Fix the problems. The song must be SHORT — max {MAX_LINES} lines total.
STRUCTURE: [verse 1] 4 lines, [chorus] 3-4 lines, [verse 2] 4 lines,
[chorus] identical repeat, [ending] 2-3 lines. That's it.
No verse 3. No bridge. No parent lines. No extra sections.

Max 9 syllables per line. Use short simple words.
Do NOT fix syllable count by splitting into more lines —
keep exactly 4 lines per verse. Rewrite each line shorter instead.
Natural rhymes only — no forced wordplay.

Output the COMPLETE corrected lyrics with section tags, then [COVER: one-line visual scene].
No explanations."""

    time.sleep(32)  # Mistral rate limit

    return call_mistral(
        retry_prompt,
        system_msg=(
            "You are a children's songwriter. Fix the specific problems listed. "
            "Write how a child talks — complete sentences, natural rhymes. "
            "Output ONLY the fixed lyrics. No markdown code blocks."
        ),
        api_key=api_key,
    )


# ── TTS Normalization ────────────────────────────────────────────────

def normalize_caps_for_tts(text: str) -> str:
    """Convert ALL CAPS words to Title Case to prevent TTS spelling as acronyms."""
    def fix_caps(match):
        word = match.group(0)
        if len(word) <= 2:
            return word
        return word.capitalize()
    return re.sub(r'\b[A-Z]{3,}\b', fix_caps, text)


# ── Audio Generation (MiniMax via Replicate) ─────────────────────────

MAX_LYRICS_CHARS = 600

def strip_parent_lines(lyrics: str) -> str:
    """Remove parent response lines before sending to MiniMax.

    Parent responses ("Mom: Why?") confuse MiniMax's vocal generation —
    it either skips them, speaks them in the same voice, or garbles them.
    """
    lines = lyrics.split("\n")
    filtered = []
    in_parent_section = False
    for line in lines:
        stripped = line.strip().lower()
        # Skip [parent] section tags and their content
        if stripped.startswith("[parent"):
            in_parent_section = True
            continue
        if in_parent_section:
            if stripped.startswith("["):
                in_parent_section = False
                # Fall through to process this new section tag
            else:
                continue
        # Skip inline parent lines
        if any(stripped.startswith(p) for p in
               ["mom:", "dad:", "parent:", "*mom", "*dad", "*parent",
                "(mom", "(dad", "(parent", '"mom', '"dad']):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def check_minimax_length(lyrics: str, max_chars: int = MAX_LYRICS_CHARS) -> bool:
    """Ensure lyrics fit MiniMax's input limit after cleanup."""
    clean = strip_parent_lines(lyrics)
    clean = re.sub(r'\[.*?\]', '', clean)  # Remove section tags
    char_count = len(clean.strip())

    if char_count > max_chars:
        print(f"  WARNING: Lyrics too long ({char_count} chars, "
              f"max {max_chars}). Will be truncated by MiniMax.")
        return False
    return True


def check_nonsense_similes(lyrics: str) -> list[str]:
    """Flag lines with similes that don't make immediate sense.

    Similes ("like a...") are where the LLM hides forced rhymes.
    Returns list of flagged lines (warnings, non-blocking).
    """
    flagged = []
    for line in lyrics.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        # Find "like a ..." patterns
        simile_matches = re.findall(r'like\s+a\s+\w+(?:\s+\w+)?', stripped, re.IGNORECASE)
        for simile in simile_matches:
            # Flag abstract/nonsense combinations
            nonsense_words = {"sad", "happy", "angry", "lonely", "broken",
                              "empty", "silent", "dark", "lost", "cold",
                              "bridge", "wall", "cloud", "shadow", "void",
                              "wind", "stone", "dream", "ghost", "whisper"}
            words = simile.lower().split()
            if any(w in nonsense_words for w in words[2:]):
                flagged.append(f"  SIMILE: \"{stripped}\" — '{simile}' may not make sense")
    return flagged


def trim_lyrics_for_minimax(lyrics: str) -> str:
    """Legacy wrapper — use prepare_lyrics_for_minimax instead."""
    return prepare_lyrics_for_minimax(lyrics)


def prepare_lyrics_for_minimax(lyrics: str, max_chars: int = 580) -> str:
    """Ensure lyrics fit MiniMax limit with margin.

    Strips section tags, parent lines, empty lines. Trims from the end
    (cuts ending/final chorus first) to preserve verses and first chorus.
    Uses 580 not 600 — leaves margin for MiniMax's own formatting.
    """
    # Strip section tags
    clean = re.sub(r'\[.*?\]', '', lyrics)
    # Strip parent lines
    clean = strip_parent_lines(clean)
    # Strip empty lines, normalize whitespace
    lines = [l.strip() for l in clean.split('\n') if l.strip()]
    result = '\n'.join(lines)

    if len(result) > max_chars:
        # Trim from the end — cut ending/final chorus first
        # Keep verses and first chorus intact
        while len(result) > max_chars and lines:
            lines.pop()
            result = '\n'.join(lines)
        print(f"  Trimmed to {len(result)} chars ({max_chars} max)")

    return result


def generate_audio_minimax(song: dict, force: bool = False) -> bool:
    """Generate audio via MiniMax Music 1.5 on Replicate."""
    if replicate is None:
        print("    ERROR: replicate not installed — pip install replicate")
        return False

    song_id = song["id"]
    audio_path = AUDIO_DIR / f"{song_id}.mp3"

    if audio_path.exists() and not force:
        print(f"    Audio exists, skipping")
        return True

    lyrics = song["lyrics"]
    style = song.get("style_prompt", "")
    if not style:
        # Fallback: build a fresh style prompt
        style, _, _ = build_style_prompt(song["age_group"])

    trimmed = prepare_lyrics_for_minimax(lyrics)
    print(f"    Lyrics: {len(lyrics)} chars -> {len(trimmed)} chars (trimmed for MiniMax)")
    print(f"    Style: {style[:80]}...")

    try:
        print(f"    Calling MiniMax Music 1.5 on Replicate...")
        output = replicate.run(
            "minimax/music-1.5",
            input={
                "prompt": style,
                "lyrics": trimmed,
            },
        )

        if not output:
            print(f"    ERROR: No output from MiniMax")
            return False

        audio_url = str(output)
        print(f"    Got audio URL, downloading...")

        resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 1000:
            print(f"    ERROR: Download failed ({resp.status_code}, {len(resp.content)} bytes)")
            return False

        audio_path.write_bytes(resp.content)
        size_kb = len(resp.content) / 1024
        print(f"    Saved: {audio_path.name} ({size_kb:.0f} KB)")

        # Get duration
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(str(audio_path))
            duration_s = len(seg) / 1000.0
            print(f"    Duration: {duration_s:.1f}s")
            song["duration_seconds"] = int(duration_s)
        except Exception:
            song["duration_seconds"] = 75  # Default estimate

        song["audio_file"] = f"{song_id}.mp3"
        return True

    except Exception as e:
        print(f"    ERROR: {e}")
        return False


# ── Cover Generation (FLUX via Pollinations) ─────────────────────────

# CRITICAL: FLUX renders any text-like word as visible text on the image.
# Do NOT mention "text/words/letters" even negatively — FLUX interprets
# "no text" as "generate text". Keep the prompt purely visual.
COVER_PROMPT_TEMPLATE = (
    "Digital painting of {cover_description}, "
    "bold cartoon style, bright saturated colors, "
    "simple flat background, exaggerated funny expressions, "
    "playful and warm, thick outlines, expressive eyes, "
    "Pixar-meets-picture-book aesthetic, "
    "small floating music notes, cozy musical energy, minimalist"
)


def generate_cover_flux(song: dict, force: bool = False) -> bool:
    """Generate a WebP cover via Pollinations FLUX."""
    if Image is None:
        print("    ERROR: Pillow not installed — pip install Pillow")
        return False

    song_id = song["id"]
    cover_path = COVERS_DIR / f"{song_id}.webp"

    if cover_path.exists() and not force:
        print(f"    Cover exists, skipping")
        return True

    description = song.get("cover_description", "")
    if not description:
        # Fallback: generate a generic description from the battle cry
        description = f"a cartoon child with funny expression in a cozy bedroom scene"

    prompt = COVER_PROMPT_TEMPLATE.format(cover_description=description)
    truncated = prompt[:600]
    encoded_prompt = quote(truncated, safe="")
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width=512&height=512&model=flux&nologo=true"

    pollinations_token = os.getenv("POLLINATIONS_API_KEY", "")
    headers = {}
    if pollinations_token:
        headers["Authorization"] = f"Bearer {pollinations_token}"

    print(f"    Calling FLUX via Pollinations.ai...")

    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=headers, timeout=120, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                img = Image.open(BytesIO(resp.content))
                img = img.convert("RGB")
                img = img.resize((512, 512), Image.LANCZOS)
                cover_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(cover_path), format="WEBP", quality=85)
                size_kb = cover_path.stat().st_size / 1024
                print(f"    Saved: {cover_path.name} ({size_kb:.0f} KB)")
                song["cover_file"] = f"{song_id}.webp"
                return True
            elif resp.status_code == 429:
                print(f"    Rate limited, waiting 15s...")
                time.sleep(15)
            else:
                print(f"    FLUX error {resp.status_code} ({len(resp.content)} bytes)")
                if attempt < 2:
                    time.sleep(5)
        except httpx.TimeoutException:
            print(f"    FLUX timeout (attempt {attempt + 1})")
            if attempt < 2:
                time.sleep(5)
        except Exception as e:
            print(f"    FLUX error: {e}")
            return False
    return False


# ── Diversity Tracking ───────────────────────────────────────────────

def _load_existing_songs() -> list:
    """Load all existing silly song metadata for diversity tracking."""
    songs = []
    if DATA_DIR.exists():
        for f in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                songs.append(json.loads(f.read_text()))
            except Exception:
                pass
    return songs


# Full battle cry library (expandable)
BATTLE_CRIES = {
    # ── Ages 2-5 ──
    "not_tired":       {"cry": "I'm not tired",       "ages": ["2-5"]},
    "dont_like_it":    {"cry": "I don't like it",     "ages": ["2-5"]},
    "dont_wanna":      {"cry": "I don't wanna",       "ages": ["2-5"]},
    "five_minutes":    {"cry": "Five more minutes",   "ages": ["2-5", "6-8"]},
    "no_no_no":        {"cry": "No no no",            "ages": ["2-5"]},
    "i_want_it":       {"cry": "I want it",           "ages": ["2-5"]},
    "pick_me_up":      {"cry": "Pick me up",          "ages": ["2-5"]},
    "mine":            {"cry": "That's mine",         "ages": ["2-5"]},
    "no_bath":         {"cry": "No bath",              "ages": ["2-5"]},
    "not_sleepy":      {"cry": "I'm not sleepy",      "ages": ["2-5"]},
    "hungry":          {"cry": "I'm hungry",          "ages": ["2-5", "6-8"]},
    "carry_me":        {"cry": "Carry me",            "ages": ["2-5"]},
    # ── Ages 6-8 ──
    "not_fair":        {"cry": "That's not fair",     "ages": ["6-8"]},
    "but_why":         {"cry": "But why",             "ages": ["6-8"]},
    "you_said":        {"cry": "But you said",        "ages": ["6-8", "9-12"]},
    "cant_find_it":    {"cry": "I can't find it",     "ages": ["6-8", "9-12"]},
    "one_more":        {"cry": "One more",            "ages": ["6-8", "9-12"]},
    "too_early":       {"cry": "It's too early",      "ages": ["6-8"]},
    "dont_want_to":    {"cry": "I don't want to",     "ages": ["6-8"]},
    "he_started_it":   {"cry": "He started it",       "ages": ["6-8"]},
    "im_bored":        {"cry": "I'm bored",           "ages": ["6-8"]},
    "do_i_have_to":    {"cry": "Do I have to",        "ages": ["6-8", "9-12"]},
    # ── Ages 9-12 ──
    "not_my_fault":    {"cry": "It's not my fault",   "ages": ["6-8", "9-12"]},
    "i_forgot":        {"cry": "I forgot",            "ages": ["9-12"]},
    "in_a_minute":     {"cry": "In a minute",         "ages": ["9-12"]},
    "already_did":     {"cry": "I already did it",    "ages": ["9-12"]},
    "almost_done":     {"cry": "I'm almost done",     "ages": ["9-12"]},
    "wasnt_me":        {"cry": "It wasn't me",        "ages": ["9-12"]},
    "didnt_hear":      {"cry": "I didn't hear you",   "ages": ["9-12"]},
    "leave_me_alone":  {"cry": "Leave me alone",      "ages": ["9-12"]},
    "so_what":         {"cry": "So what",             "ages": ["9-12"]},
    "whatever":        {"cry": "Whatever",            "ages": ["9-12"]},
    "im_coming":       {"cry": "I'm coming",          "ages": ["9-12"]},
    "i_know":          {"cry": "I know",              "ages": ["9-12"]},
    "i_am_doing_it":   {"cry": "I am doing it",      "ages": ["9-12"]},
}


def select_silly_song_params(existing_songs: list, age_group: str = None,
                             exclude_cries: set = None,
                             mood: str = None) -> dict:
    """Select parameters ensuring variety across songs.

    Args:
        exclude_cries: Battle cry IDs to hard-exclude (e.g. already in this batch).
        mood: Child mood — filters battle cries and adjusts style/tempo.

    Returns dict with: age_group, battle_cry_id, battle_cry, style_prompt,
    instruments, tempo, mood.
    """
    exclude_cries = exclude_cries or set()

    # Age group rotation
    if age_group is None:
        recent_ages = [s.get("age_group") for s in existing_songs[-3:]]
        age_options = ["2-5", "6-8", "9-12"]
        age_group = next((a for a in age_options if a not in recent_ages),
                         random.choice(age_options))

    # Filter battle cries by mood first (if mood given)
    if mood and mood in MOOD_TO_BATTLE_CRIES:
        mood_cries = MOOD_TO_BATTLE_CRIES[mood]
        eligible_for_age = [k for k in mood_cries
                            if k in BATTLE_CRIES and age_group in BATTLE_CRIES[k]["ages"]]
    else:
        eligible_for_age = [k for k, v in BATTLE_CRIES.items()
                            if age_group in v["ages"]]

    # Battle cry — not used in last 10 songs for this age, and not in exclude set
    recent_cries = [s.get("battle_cry_id") for s in existing_songs[-10:]
                    if s.get("age_group") == age_group]
    available_cries = [k for k in eligible_for_age
                       if k not in recent_cries
                       and k not in exclude_cries]
    if not available_cries:
        # Relax recent-use filter but keep batch exclusion
        available_cries = [k for k in eligible_for_age
                           if k not in exclude_cries]
    if not available_cries:
        # No mood-matched cries available — fall back to all cries for this age
        available_cries = [k for k, v in BATTLE_CRIES.items()
                           if age_group in v["ages"]
                           and k not in exclude_cries]
    if not available_cries:
        # Last resort
        available_cries = [k for k, v in BATTLE_CRIES.items()
                           if age_group in v["ages"]]
    cry_id = random.choice(available_cries)

    # Style prompt with varied instruments/tempo, mood-adjusted
    style_prompt, instruments, tempo = build_style_prompt(
        age_group, existing_songs, mood=mood
    )

    return {
        "age_group": age_group,
        "mood": mood or "wired",  # default mood for silly songs
        "battle_cry_id": cry_id,
        "battle_cry": BATTLE_CRIES[cry_id]["cry"],
        "style_prompt": style_prompt,
        "instruments": instruments,
        "tempo": tempo,
    }


def generate_scene(battle_cry: str, age_group: str, api_key: str) -> str:
    """Step 0: Generate a concrete scene that anchors the entire song."""
    prompt = SCENE_PROMPT.format(battle_cry=battle_cry, age_group=age_group)

    response = call_mistral(
        prompt,
        system_msg=(
            "You describe specific moments from childhood. "
            "Be concrete — name the room, the objects, the time of day. "
            "2 sentences maximum. No abstractions."
        ),
        api_key=api_key,
    )
    scene = response.strip().strip('"')
    return scene


def validate_scene(scene: str) -> bool:
    """Check that a scene is concrete enough (has a place and a trigger)."""
    if not scene or len(scene) < 20:
        return False
    # Reject vague scenes
    vague_phrases = ["a child who", "various things", "many reasons",
                     "different situations", "in general"]
    for phrase in vague_phrases:
        if phrase in scene.lower():
            return False
    return True


def validate_batch_diversity(new_params: dict, batch_songs: list) -> tuple[bool, str]:
    """Ensure no duplicate battle cry base ID in the same batch.

    Compares the base cry ID (e.g. "not_my_fault") ignoring age suffix,
    so "not_my_fault" for 6-8 blocks "not_my_fault" for 9-12.
    """
    new_cry = new_params.get("battle_cry_id", "")
    for existing in batch_songs:
        existing_cry = existing.get("battle_cry_id", "")
        if new_cry == existing_cry:
            return False, f"Duplicate battle cry: {new_cry}"
    return True, "OK"


def extract_cover_from_lyrics(lyrics_response: str) -> str:
    """Extract [COVER: description] from lyrics LLM response."""
    m = re.search(r'\[COVER:\s*(.+?)\]', lyrics_response, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def check_audio_loudness(audio_path: str, max_dbfs: float = -14.0) -> bool:
    """Flag if the generated song is too loud."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(audio_path)
        loudness = audio.dBFS
        if loudness > max_dbfs:
            print(f"  ⚠️  Song is loud ({loudness:.1f} dBFS, max {max_dbfs}). "
                  f"Consider checking style prompt.")
            return False
        print(f"  ✓ Volume OK ({loudness:.1f} dBFS)")
        return True
    except Exception as e:
        print(f"  Could not check loudness: {e}")
        return True  # Don't block on failure


# ── Main Generation ──────────────────────────────────────────────────

def generate_silly_song(
    cry_id: str,
    battle_cry: str,
    age_group: str,
    api_key: str,
    lyrics_only: bool = False,
    force: bool = False,
    max_retries: int = 2,
    params: dict = None,
) -> dict | None:
    """Generate one silly song using the two-step battle cry process.

    Args:
        cry_id: Battle cry identifier
        battle_cry: The actual phrase ("I'm not tired")
        age_group: "2-5", "6-8", or "9-12"
        api_key: Mistral API key
        lyrics_only: Skip audio/cover generation
        force: Regenerate even if exists
        max_retries: Max lyrics retry attempts
        params: Diversity params from select_silly_song_params(). If provided,
                style_prompt, instruments, tempo are taken from params.
    """

    song_id = f"{cry_id}_{age_group.replace('-', '_')}"
    print(f"\n{'='*60}")
    print(f"  Generating: \"{battle_cry}\" (ages {age_group})")
    print(f"  Song ID: {song_id}")
    if params:
        print(f"  Instruments: {params.get('instruments')}")
        print(f"  Tempo: {params.get('tempo')} BPM")
    print(f"{'='*60}")

    # Check if already exists
    json_path = DATA_DIR / f"{song_id}.json"
    if json_path.exists() and not force:
        print(f"  Song JSON already exists. Use --force to regenerate.")
        with open(json_path) as f:
            return json.load(f)

    # ── STEP 0: Generate scene ──
    print(f"\n  Step 0: Generating scene...")
    scene = ""
    for scene_attempt in range(3):
        scene = generate_scene(battle_cry, age_group, api_key)
        print(f"  Scene: {scene}")
        if validate_scene(scene):
            break
        print(f"  Scene too vague, retrying...")
        time.sleep(32)
    if not validate_scene(scene):
        print(f"  WARNING: Could not get concrete scene, proceeding with best attempt")

    # Save scene for debugging
    scene_debug_path = OUTPUT_DIR / f"{song_id}_scene.txt"
    scene_debug_path.write_text(scene)

    existing_songs = _load_existing_songs()

    # ── STEP 1: Generate lyrics directly from scene ──
    # (No separate rhyme palette step — let the LLM find natural rhymes
    # within each verse instead of pre-generating a palette that forces
    # everything through one rhyme sound.)
    print(f"\n  Step 1: Generating lyrics...")
    time.sleep(32)

    lyrics_prompt = LYRICS_PROMPT.format(
        age_group=age_group,
        battle_cry=battle_cry,
        scene=scene,
    )

    lyrics_response = call_mistral(
        lyrics_prompt,
        system_msg=(
            "You are a children's songwriter. Write fun, bouncy, catchy songs "
            "that children sing along to. The voice is a child's voice — "
            "cheeky, energetic, protesting. "
            "Output ONLY the lyrics with section tags, then a [COVER:] tag. "
            "No explanations, no markdown code blocks."
        ),
        api_key=api_key,
    )

    cover_description = extract_cover_from_lyrics(lyrics_response)
    lyrics = extract_lyrics(lyrics_response)
    lyrics = re.sub(r'\[COVER:.*?\]', '', lyrics, flags=re.IGNORECASE).strip()

    print(f"\n--- LYRICS (initial) ---")
    print(lyrics)
    print(f"--- END ---\n")
    if cover_description:
        print(f"  Cover: {cover_description[:80]}...")

    # ── STEP 3: Validate + retry with scene feedback ──
    passed, errors, structured = validate_silly_song(lyrics, battle_cry, age_group, scene)
    if passed:
        print(f"  ✓ All validation checks passed")
    else:
        print(f"  VALIDATION ISSUES:")
        for e in errors:
            print(f"    ✗ {e}")

        fixable_types = ("missing_cry", "chorus_inconsistent",
                         "no_sfx", "few_verses", "nonsense_simile",
                         "too_many_syllables", "too_many_lines")
        for retry_num in range(max_retries):
            fixable = [e for e in structured if e["type"] in fixable_types]
            if not fixable:
                print(f"  (remaining issues not fixable by retry)")
                break

            print(f"\n  Retry {retry_num + 1}/{max_retries}: feeding {len(fixable)} errors back to LLM...")
            retry_response = retry_with_feedback(
                lyrics, structured, age_group, battle_cry, api_key, scene
            )

            new_cover = extract_cover_from_lyrics(retry_response)
            if new_cover:
                cover_description = new_cover
            lyrics = extract_lyrics(retry_response)
            lyrics = re.sub(r'\[COVER:.*?\]', '', lyrics, flags=re.IGNORECASE).strip()

            print(f"\n--- LYRICS (retry {retry_num + 1}) ---")
            print(lyrics)
            print(f"--- END ---\n")

            passed, errors, structured = validate_silly_song(lyrics, battle_cry, age_group, scene)
            if passed:
                print(f"  ✓ All validation checks passed after retry {retry_num + 1}")
                break
            else:
                print(f"  Still has issues:")
                for e in errors:
                    print(f"    ✗ {e}")

        if not passed:
            print(f"  Deploying anyway — sung lyrics compress to fit melody.")

    # ── STEP 4: Normalize for TTS ──
    lyrics_normalized = normalize_caps_for_tts(lyrics)

    # Build style prompt from params or generate fresh
    if params and params.get("style_prompt"):
        style_prompt = params["style_prompt"]
        instruments = params.get("instruments", "")
        tempo = params.get("tempo", 0)
    else:
        style_prompt, instruments, tempo = build_style_prompt(age_group, existing_songs)

    # ── Build song metadata (all diversity dimensions tracked) ──
    mood = params.get("mood", "wired") if params else "wired"
    song = {
        "id": song_id,
        "title": battle_cry.title(),
        "age_group": age_group,
        "mood": mood,
        "lyrics": lyrics_normalized,
        "style_prompt": style_prompt,
        "instruments": instruments,
        "tempo": tempo,
        "scene": scene,
        "cover_description": cover_description or "a cartoon child with funny expression in a cozy bedroom",
        "animation_preset": "bounce_rhythmic",
        "created_at": date.today().isoformat(),
        "play_count": 0,
        "replay_count": 0,
        # Battle cry metadata
        "battle_cry_id": cry_id,
        "battle_cry": battle_cry,
        "generation_method": "battlecry_v3",
    }

    # Save JSON (before audio/cover so we don't lose lyrics on failure)
    with open(json_path, "w") as f:
        json.dump(song, f, indent=2)
    print(f"\n  ✓ Saved metadata: {json_path.name}")

    # Also save a copy to output dir
    output_json = OUTPUT_DIR / f"{song_id}.json"
    with open(output_json, "w") as f:
        json.dump(song, f, indent=2)

    if lyrics_only:
        print(f"  (--lyrics-only mode, skipping audio and cover)")
        return song

    # ── STEP 5: Generate audio ──
    print(f"\n  Step 5: Generating audio via MiniMax...")
    if generate_audio_minimax(song, force=force):
        # Update JSON with audio_file and duration
        with open(json_path, "w") as f:
            json.dump(song, f, indent=2)
        print(f"  ✓ Audio generated")

        # Post-generation loudness check
        audio_path = AUDIO_DIR / f"{song_id}.mp3"
        if audio_path.exists():
            check_audio_loudness(str(audio_path))
    else:
        print(f"  ✗ Audio generation failed")

    # ── STEP 6: Generate cover ──
    print(f"\n  Step 6: Generating cover via FLUX...")
    time.sleep(5)
    if generate_cover_flux(song, force=force):
        # Update JSON with cover_file
        with open(json_path, "w") as f:
            json.dump(song, f, indent=2)
        print(f"  ✓ Cover generated")
    else:
        print(f"  ✗ Cover generation failed")

    print(f"\n  ✓ Complete: {song_id}")
    return song


def main():
    parser = argparse.ArgumentParser(
        description="Generate silly songs using the Battle Cry approach",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  One per age group:  python3 scripts/generate_silly_songs_battlecry.py --test
  All 6 test songs:   python3 scripts/generate_silly_songs_battlecry.py --all
  Specific cry:       python3 scripts/generate_silly_songs_battlecry.py --cry not_tired
  Lyrics only:        python3 scripts/generate_silly_songs_battlecry.py --test --lyrics-only
  Fresh (diversity):  python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3
  Fresh + force:      python3 scripts/generate_silly_songs_battlecry.py --fresh --count 3 --force
        """,
    )
    parser.add_argument("--test", action="store_true",
                        help="Generate one song per age group (3 songs)")
    parser.add_argument("--all", action="store_true",
                        help="Generate all 6 test songs")
    parser.add_argument("--fresh", action="store_true",
                        help="Diversity-tracked generation (auto-selects cry, instruments, tempo)")
    parser.add_argument("--count", type=int, default=3,
                        help="Number of songs to generate in --fresh mode (default: 3)")
    parser.add_argument("--cry", help="Generate a specific battle cry by ID")
    parser.add_argument("--lyrics-only", action="store_true",
                        help="Skip audio and cover generation")
    parser.add_argument("--mood", choices=["wired", "curious", "calm", "sad", "anxious", "angry"],
                        help="Child mood — filters battle cries and adjusts style/tempo")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files exist")
    args = parser.parse_args()

    if not args.test and not args.all and not args.cry and not args.fresh:
        parser.error("Specify --test, --all, --fresh, or --cry <id>")

    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set")
        sys.exit(1)

    if not args.lyrics_only:
        if replicate is None:
            print("WARNING: replicate not installed — audio generation will fail")
        if not os.getenv("REPLICATE_API_TOKEN"):
            print("WARNING: REPLICATE_API_TOKEN not set — audio generation will fail")

    # ── Fresh mode: diversity-tracked generation ──
    if args.fresh:
        existing_songs = _load_existing_songs()
        count = args.count

        print(f"\n{'='*60}")
        print(f"  Battle Cry Silly Songs Generator (FRESH / diversity-tracked)")
        print(f"  Songs to generate: {count}")
        print(f"  Existing songs for diversity: {len(existing_songs)}")
        if args.mood:
            print(f"  Mood: {args.mood}")
        print(f"  Mode: {'lyrics only' if args.lyrics_only else 'full (lyrics + audio + cover)'}")
        print(f"{'='*60}")

        # Pre-assign age groups: cycle through 2-5, 6-8, 9-12 to guarantee
        # coverage. This prevents the diversity selector from picking the same
        # age group twice while missing another entirely.
        age_cycle = ["2-5", "6-8", "9-12"]
        assigned_ages = [age_cycle[i % len(age_cycle)] for i in range(count)]
        random.shuffle(assigned_ages)  # Shuffle so order varies
        print(f"  Age rotation: {' → '.join(assigned_ages)}")

        results = []
        for i in range(count):
            try:
                if i > 0:
                    print(f"\n  Waiting 35s for Mistral rate limit...")
                    time.sleep(35)

                forced_age = assigned_ages[i]

                # Select params with enforced age group, excluding batch duplicates
                batch_cries = {r.get("battle_cry_id") for r in results}
                params = select_silly_song_params(
                    existing_songs, age_group=forced_age, exclude_cries=batch_cries,
                    mood=args.mood,
                )
                ok, reason = validate_batch_diversity(params, results)
                if not ok:
                    # Should not happen with exclude_cries, but log just in case
                    print(f"  ⚠️  Batch diversity failed even with exclusions: {reason}")

                print(f"\n  Selected: {params['battle_cry']} (ages {params['age_group']}, mood: {params.get('mood', 'wired')})")
                print(f"  Instruments: {params['instruments']}")
                print(f"  Tempo: {params['tempo']} BPM")

                result = generate_silly_song(
                    cry_id=params["battle_cry_id"],
                    battle_cry=params["battle_cry"],
                    age_group=params["age_group"],
                    api_key=api_key,
                    lyrics_only=args.lyrics_only,
                    force=args.force,
                    params=params,
                )
                if result:
                    results.append(result)
                    existing_songs.append(result)
            except Exception as e:
                print(f"  ✗ FAILED: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'='*60}")
        print(f"  Generated {len(results)}/{count} songs (fresh mode)")
        for r in results:
            print(f"    • {r['title']} (ages {r['age_group']}) — {r.get('instruments', '?')}")
        print(f"{'='*60}\n")
        return

    # ── Legacy modes: --test, --all, --cry ──
    if args.cry:
        # Look up from full BATTLE_CRIES library first, then fall back to TEST_SONGS
        if args.cry in BATTLE_CRIES:
            cry_data = BATTLE_CRIES[args.cry]
            # Use first eligible age group, or --age if provided
            age = cry_data["ages"][0]
            songs_to_gen = [{"cry_id": args.cry, "cry": cry_data["cry"], "age": age}]
        else:
            songs_to_gen = [s for s in TEST_SONGS if s["cry_id"] == args.cry]
        if not songs_to_gen:
            print(f"Unknown cry_id: {args.cry}")
            print(f"Available: {', '.join(BATTLE_CRIES.keys())}")
            sys.exit(1)
    elif args.test:
        songs_to_gen = TEST_MODE_SONGS
    else:
        songs_to_gen = TEST_SONGS

    print(f"\n{'='*60}")
    print(f"  Battle Cry Silly Songs Generator")
    print(f"  Songs to generate: {len(songs_to_gen)}")
    print(f"  Mode: {'lyrics only' if args.lyrics_only else 'full (lyrics + audio + cover)'}")
    print(f"{'='*60}")

    results = []
    for i, config in enumerate(songs_to_gen):
        try:
            # Rate limit between songs (Mistral free tier: 2 req/min)
            if i > 0:
                print(f"\n  Waiting 35s for Mistral rate limit...")
                time.sleep(35)

            result = generate_silly_song(
                cry_id=config["cry_id"],
                battle_cry=config["cry"],
                age_group=config["age"],
                api_key=api_key,
                lyrics_only=args.lyrics_only,
                force=args.force,
            )
            if result:
                results.append(result)
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  Generated {len(results)}/{len(songs_to_gen)} songs")
    print(f"\n  Song JSONs in: data/silly_songs/")
    if not args.lyrics_only:
        print(f"  Audio in: public/audio/silly-songs/")
        print(f"  Covers in: public/covers/silly-songs/")
    print(f"  Debug output in: output/silly_songs_battlecry/")
    print(f"\n  Listen to each song and check:")
    print(f"    - Can a child sing the chorus after hearing it once?")
    print(f"    - Does the beat make you bounce?")
    print(f"    - Does V3 make you laugh more than V1?")
    print(f"    - Are the rhymes driving the content (not the other way)?")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
