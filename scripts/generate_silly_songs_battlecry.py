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


def build_style_prompt(age_group: str, recent_songs: list = None) -> tuple:
    """Build a style prompt with varied instruments and tempo.

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

    # Pick tempo within range
    lo, hi = TEMPO_RANGE[age_group]
    tempo = random.randint(lo, hi)

    # Energetic style — bouncy, catchy, impossible to sit still
    # Must stay under 300 chars for MiniMax
    prompt = (
        f"Catchy children's song, {instruments}, "
        f"{tempo} BPM, strong bass, punchy beat, "
        f"bouncy groovy infectious singalong, "
        f"impossible to sit still, makes you move"
    )

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

RHYME_FAMILY_PROMPT = """
I'm writing a children's silly song built around the phrase: "{battle_cry}"
For ages: {age_group}

SCENE: {scene}

STEP 1: Find the KEY RHYME WORD from the battle cry.
The word that carries the most weight. The word that SOUNDS the funniest
or has the most rhyme potential.

STEP 2: List 15-20 words that rhyme with the key word.
Rules:
- Simple words only. Words a child uses daily.
- Ages 2-5: maximum 2 syllables per word.
- Ages 6-8: maximum 3 syllables.
- Ages 9-12: keep it conversational.
- Include near-rhymes and slant rhymes — they're often funnier.

STEP 3: For EACH rhyme word, write a short child's complaint, excuse,
or protest that ENDS with that word.

Every rhyming line must be something the child would say
or think IN THIS SPECIFIC MOMENT. Not generic complaints.
Not random situations. Lines that belong in THIS scene
and would feel wrong in any other scene.

The sentence must sound like something a child SAYS OUT LOUD while
arguing with a parent. Not something written. Not something clever.
How a child actually talks.

BAD: "The evening's peaceful slumber calls" (literary, no child says this)
BAD: "A sockological catastrophe" (adult humor, too clever)
GOOD: "I had a grape THAT COUNTS right?" (arguing, real child voice)
GOOD: "I don't even need that stuff" (messy, spoken, real)
GOOD: "My brain just won't turn off" (simple, relatable, ends with rhyme)

Messy grammar is CORRECT. How kids talk, not how they write.
"I don't even like that food" YES
"I find the cuisine unpalatable" NO

Generate at LEAST 15 lines. More is better — we'll pick the best ones.

OUTPUT FORMAT (use these exact labels):
KEY_WORD: [the word]
RHYME_FAMILY: [word1, word2, word3, ...]
LINES:
1. [line ending with rhyme word 1]
2. [line ending with rhyme word 2]
3. [line ending with rhyme word 3]
...
"""

LYRICS_ASSEMBLY_PROMPT = """
BATTLE CRY: "{battle_cry}"
SCENE: {scene}
AGE: {age_group}

RHYME PALETTE:
{rhyme_lines}

=== SCENE LOCK ===
This song is about ONE moment. Not a list. Not a medley.
ONE place, ONE night, ONE argument. Every single line
happens in this scene. If a line could belong in a
different song about a different situation, it's too generic.
Cut it and write something that ONLY works here.

V1: Real details about THIS moment
V2: The SAME moment exaggerated
V3: The SAME moment taken to absurd extremes
NOT three different complaints. The SAME complaint, deeper each time.

=== CHORUS ===
The chorus is the battle cry repeated with energy.
3-4 lines maximum.
IDENTICAL every time it appears — same words, same order.
The child memorises through repetition. If the chorus
changes, there's nothing to memorise.

The ONLY exception: the FINAL chorus can trail off,
collapse, or dissolve. The earlier choruses CANNOT change.

=== PARENT RESPONSES ===
The parent responds 2-3 times through the song. Their
response is part of the RHYTHM — short, on the beat,
1-3 words. Use the SAME parent response each time.
It becomes a second recurring element the child anticipates.

=== OPENING ===
Every song starts differently. The opening matches
THIS battle cry's energy. Don't follow the same pattern
as other songs. Sometimes the child is mid-argument.
Sometimes the parent speaks first. Sometimes it starts
with a sound. Sometimes straight into the verse.

=== LINES ===
Every line must make sense as a standalone sentence a child
would actually say IN THIS SCENE. If a line exists only
because it rhymes but means nothing, replace it with a
line that rhymes AND means something specific to this moment.

Lines must FLOW when sung. Not fragments separated by dashes.
A voice must be able to carry each line smoothly in one breath.

Word limits:
Ages 2-5: max 6 words per line
Ages 6-8: max 8 words per line
Ages 9-12: max 10 words per line

=== ESCALATION ===
Same scene, three levels:
V1 — the real version. Things the child actually says.
V2 — pushed further. Exaggeration of the SAME complaint.
V3 — absurd. The same complaint taken to impossible extremes.

For LIE-BASED battle cries (already did, wasn't me, forgot):
V1 — the basic lie
V2 — doubling down on the SAME lie
V3 — the lie becomes elaborate architecture
Collapse — the truth is embarrassingly obvious

=== SOUND EFFECTS ===
2-3 sounds that interrupt the argument at funny moments.
Wrap in asterisks. The sounds must be specific to THIS
scene. A bath song uses water sounds. A food song uses
eating sounds. A bedtime song uses sleepy sounds.
Do not reuse the same sounds across different songs.

=== ENDING ===
The final chorus dissolves. The child runs out of
steam. The argument collapses into sleep or distraction
or accidental agreement. The energy drains naturally —
the child was fighting hard but the body is done.

=== OUTPUT ===
Just the lyrics with [opening], [verse], and [chorus] tags.
Start with the opening.
No title needed. No markdown code blocks.

THEN, after the lyrics, generate a cover description on its own line:
[COVER: one-sentence visual description of the funniest moment from YOUR lyrics, bold cartoon style, bright colors, energetic]
"""

# ── Syllable Counter ─────────────────────────────────────────────────

def count_syllables(word: str) -> int:
    """Rough syllable count for English words."""
    word = word.lower().strip(".,!?*[]()\"'")
    if not word:
        return 0
    if len(word) <= 2:
        return 1
    # Count vowel groups
    count = len(re.findall(r'[aeiouy]+', word))
    # Silent e
    if word.endswith('e') and not word.endswith('le'):
        count -= 1
    return max(1, count)


# ── LLM Calls ────────────────────────────────────────────────────────

def call_mistral(prompt: str, system_msg: str = "", api_key: str = "") -> str:
    """Call Mistral AI and return the response text."""
    client = Mistral(api_key=api_key)
    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.complete(
        model="mistral-large-latest",
        messages=messages,
        temperature=0.9,  # Higher creativity for songs
        max_tokens=2000,
    )
    return response.choices[0].message.content


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

def validate_silly_song(lyrics: str, battle_cry: str, age_group: str,
                        scene: str = "") -> tuple[bool, list[str], list[dict]]:
    """Validate formula elements. Returns (passed, errors, structured_errors)."""
    lines = [l.strip() for l in lyrics.split('\n')
             if l.strip() and not l.strip().startswith('[')]
    sections = extract_sections(lyrics)
    choruses_raw = sections["choruses"]
    chorus_lines = []
    for c in choruses_raw:
        chorus_lines.extend([l for l in c.split("\n") if l.strip()])
    verses = sections["verses"]

    errors = []
    structured = []

    # 1. BATTLE CRY in chorus
    cry_lower = battle_cry.lower()
    cry_words = [w for w in cry_lower.split() if len(w) > 2]
    cry_in_chorus = any(
        all(w in l.lower() for w in cry_words)
        for l in chorus_lines
    )
    if not cry_in_chorus:
        errors.append(f"Battle cry '{battle_cry}' not found in chorus")
        structured.append({"type": "missing_cry", "detail": battle_cry})

    # 2. WORD LENGTH
    max_syl = {"2-5": 2, "6-8": 3, "9-12": 4}[age_group]
    long_words = []
    for line in lines:
        for word in line.split():
            clean = word.strip('?!.,*[]()"\'-').lower()
            if not clean or clean.startswith("*"):
                continue
            syl = count_syllables(clean)
            if syl > max_syl:
                long_words.append(clean)
    if long_words:
        errors.append(f"Words too long for {age_group}: {', '.join(long_words[:5])}")
        structured.append({"type": "long_words", "words": long_words[:5], "max_syl": max_syl})

    # 3. LINE LENGTH
    max_words = {"2-5": 7, "6-8": 9, "9-12": 11}[age_group]
    for line in lines:
        wc = len(line.split())
        if wc > max_words:
            errors.append(f"Line too long ({wc} words): '{line[:50]}...'")
            structured.append({"type": "line_length", "line": line, "words": wc, "max": max_words})

    # 4. SOUND EFFECTS present
    has_sfx = '*' in lyrics
    has_response = any(w in lyrics.lower() for w in ['why?', 'what?', 'really?', 'hmm?'])
    if not has_sfx:
        errors.append("No sound effects (*yawn*, *burp*, etc.) found")
        structured.append({"type": "no_sfx"})
    if not has_response:
        errors.append("No call-and-response (why? / what?) found")
        structured.append({"type": "no_response"})

    # 5. ESCALATION — check we have 3 verses
    if len(verses) < 3:
        errors.append(f"Only {len(verses)} verses (need 3 for escalation)")
        structured.append({"type": "few_verses", "count": len(verses)})
    elif len(verses) >= 3:
        print(f"  MANUAL CHECK: Does V3 escalate beyond V1?")
        print(f"    V1: {verses[0][:60]}...")
        print(f"    V3: {verses[2][:60]}...")

    # 6. CHORUS SIMPLICITY
    if chorus_lines and len(chorus_lines) > 5 * len(choruses_raw):
        avg_chorus_len = len(chorus_lines) / max(len(choruses_raw), 1)
        if avg_chorus_len > 5:
            errors.append(f"Chorus too long: avg {avg_chorus_len:.0f} lines (max 4-5)")
            structured.append({"type": "chorus_long", "avg": avg_chorus_len})

    # 7. CHORUS CONSISTENCY — non-final choruses must be identical
    if len(choruses_raw) >= 2:
        first = choruses_raw[0].strip()
        for i in range(1, len(choruses_raw) - 1):  # skip last (collapse OK)
            if choruses_raw[i].strip() != first:
                errors.append(f"Chorus {i+1} differs from Chorus 1 — must be identical (except final)")
                structured.append({"type": "chorus_inconsistent", "index": i + 1})

    # 8. SCENE COHERENCE (warnings only, don't block)
    if scene:
        scene_words = {w.lower() for w in scene.split() if len(w) > 3}
        for i, verse in enumerate(verses):
            verse_words = {w.lower().strip('?!.,*') for w in verse.split()}
            overlap = scene_words & verse_words
            if len(overlap) < 1:
                print(f"  WARNING: Verse {i+1} may have drifted from scene")

    # 9. FRAGMENT DETECTION (warnings only)
    for line in lines:
        words = line.strip().rstrip('!?.').split()
        if (len(words) < 3
                and '*' not in line
                and 'parent' not in line.lower()
                and line.strip().lower() not in (battle_cry.lower(), '')):
            print(f"  WARNING: Fragment line may not sing well: '{line}'")

    return (len(errors) == 0, errors, structured)


def retry_with_feedback(lyrics: str, structured_errors: list, age_group: str,
                        battle_cry: str, api_key: str, scene: str = "") -> str:
    """Retry lyrics generation with specific failure feedback + scene anchor.

    Shows the LLM exactly which lines failed and asks it to fix THOSE lines.
    LLMs can't count words, but they CAN shorten specific examples.
    """
    max_words = {"2-5": 7, "6-8": 9, "9-12": 11}[age_group]

    # Build specific error feedback
    feedback_parts = []

    line_errors = [e for e in structured_errors if e["type"] == "line_length"]
    if line_errors:
        lines_list = "\n".join(
            f"  TOO LONG: \"{e['line'][:80]}\" ({e['words']} words, max {max_words})"
            for e in line_errors[:8]
        )
        feedback_parts.append(f"LINES TOO LONG — rewrite shorter, keep end rhyme:\n{lines_list}")

    word_errors = [e for e in structured_errors if e["type"] == "long_words"]
    if word_errors:
        words = word_errors[0]["words"]
        feedback_parts.append(
            f"WORDS TOO COMPLEX for ages {age_group}: {', '.join(words)}\n"
            f"  Replace with simpler words (1-{word_errors[0]['max_syl']} syllables)."
        )

    cry_errors = [e for e in structured_errors if e["type"] == "missing_cry"]
    if cry_errors:
        feedback_parts.append(
            f"MISSING BATTLE CRY in chorus — the phrase \"{battle_cry}\" must appear in [chorus]."
        )

    response_errors = [e for e in structured_errors if e["type"] == "no_response"]
    if response_errors:
        feedback_parts.append(
            "MISSING CALL-AND-RESPONSE — add a parent line like: *parent:* \"Why?\" or \"What?\" or \"Really?\""
        )

    chorus_errors = [e for e in structured_errors if e["type"] == "chorus_inconsistent"]
    if chorus_errors:
        feedback_parts.append(
            "CHORUS INCONSISTENCY — all choruses except the final one must be IDENTICAL (same words, same order)."
        )

    feedback = "\n\n".join(feedback_parts)

    scene_line = f"\nTHE SCENE (every line must be about this): {scene}\n" if scene else ""

    retry_prompt = f"""These lyrics for "{battle_cry}" (ages {age_group}) have problems.
{scene_line}
PROBLEMS FOUND:
{feedback}

ORIGINAL LYRICS:
{lyrics}

Fix the problems. Rules:
- Every line must belong in the scene described above
- Choruses must be identical (except the final collapse)
- Lines must flow when sung — no fragments
- Max {max_words} words per line
- If a line only exists to rhyme but means nothing,
  replace it with a line that rhymes AND fits the scene

Shorter is ALWAYS better for sung lyrics:
"I don't even need that stuff right now" → "Don't need that stuff"
"I was going to do it right now" → "Gonna do it now"

Output the COMPLETE corrected lyrics with section tags, then [COVER: one-line visual scene].
No explanations."""

    time.sleep(32)  # Mistral rate limit

    return call_mistral(
        retry_prompt,
        system_msg=(
            "You are a lyrics editor. Fix the specific problems listed. "
            "Make lines shorter by cutting filler words. Keep rhymes and fun. "
            "Every line must belong in the scene. "
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

def trim_lyrics_for_minimax(lyrics: str) -> str:
    """Trim lyrics to fit within MiniMax's 600-char limit."""
    if len(lyrics) <= MAX_LYRICS_CHARS:
        return lyrics

    sections = []
    current = []
    for line in lyrics.split("\n"):
        if line.startswith("[") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    result = []
    total = 0
    for section in sections:
        new_total = total + len(section) + (1 if result else 0)
        if new_total <= MAX_LYRICS_CHARS:
            result.append(section)
            total = new_total
        else:
            break

    return "\n".join(result)


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

    trimmed = trim_lyrics_for_minimax(lyrics)
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
    "not_tired":    {"cry": "I'm not tired",     "ages": ["2-5"]},
    "dont_like_it": {"cry": "I don't like it",   "ages": ["2-5"]},
    "five_minutes": {"cry": "Five more minutes",  "ages": ["2-5", "6-8"]},
    "not_fair":     {"cry": "That's not fair",    "ages": ["6-8"]},
    "but_why":      {"cry": "But why",            "ages": ["6-8"]},
    "not_my_fault": {"cry": "It's not my fault",  "ages": ["6-8", "9-12"]},
    "i_forgot":     {"cry": "I forgot",           "ages": ["9-12"]},
    "in_a_minute":  {"cry": "In a minute",        "ages": ["9-12"]},
    "already_did":  {"cry": "I already did it",   "ages": ["9-12"]},
    "dont_wanna":   {"cry": "I don't wanna",      "ages": ["2-5"]},
}


def select_silly_song_params(existing_songs: list, age_group: str = None) -> dict:
    """Select parameters ensuring variety across songs.

    Returns dict with: age_group, battle_cry_id, battle_cry, style_prompt,
    instruments, tempo.
    """
    # Age group rotation
    if age_group is None:
        recent_ages = [s.get("age_group") for s in existing_songs[-3:]]
        age_options = ["2-5", "6-8", "9-12"]
        age_group = next((a for a in age_options if a not in recent_ages),
                         random.choice(age_options))

    # Battle cry — not used in last 10 songs for this age
    recent_cries = [s.get("battle_cry_id") for s in existing_songs[-10:]
                    if s.get("age_group") == age_group]
    available_cries = [k for k, v in BATTLE_CRIES.items()
                       if age_group in v["ages"] and k not in recent_cries]
    if not available_cries:
        available_cries = [k for k, v in BATTLE_CRIES.items()
                           if age_group in v["ages"]]
    cry_id = random.choice(available_cries)

    # Style prompt with varied instruments/tempo
    style_prompt, instruments, tempo = build_style_prompt(age_group, existing_songs)

    return {
        "age_group": age_group,
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
    """Ensure no duplicate battle cries in the same batch."""
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

    # ── STEP 1: Generate rhyme family (with scene) ──
    print(f"\n  Step 1: Generating rhyme family...")
    time.sleep(32)

    existing_songs = _load_existing_songs()
    recent_key_words = [s.get("key_word", "").lower() for s in existing_songs[-10:]]

    rhyme_prompt = RHYME_FAMILY_PROMPT.format(
        battle_cry=battle_cry,
        age_group=age_group,
        scene=scene,
    )
    rhyme_response = call_mistral(
        rhyme_prompt,
        system_msg=(
            "You are a children's songwriter specializing in rhyme. "
            "Generate rhyme families and child-voice lines grounded in the scene. "
            "Output in the exact format requested. No markdown code blocks."
        ),
        api_key=api_key,
    )

    key_word, rhyme_family, rhyme_lines = extract_rhyme_data(rhyme_response)
    print(f"  Key word: {key_word}")
    print(f"  Rhyme family: {rhyme_family}")
    print(f"  Lines generated: {len(rhyme_lines)}")

    if key_word.lower() in recent_key_words:
        print(f"  ⚠️  Key word '{key_word}' was used recently — rhymes may overlap")

    if len(rhyme_lines) < 8:
        print(f"  WARNING: Only {len(rhyme_lines)} lines generated, may need more variety")

    # Save rhyme data for debugging
    rhyme_debug_path = OUTPUT_DIR / f"{song_id}_rhymes.txt"
    rhyme_debug_path.write_text(rhyme_response)

    # ── STEP 2: Assemble lyrics (with scene) ──
    print(f"\n  Step 2: Assembling lyrics...")
    time.sleep(32)

    lyrics_prompt = LYRICS_ASSEMBLY_PROMPT.format(
        age_group=age_group,
        battle_cry=battle_cry,
        scene=scene,
        rhyme_lines='\n'.join(f"- {l}" for l in rhyme_lines),
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

        fixable_types = ("line_length", "long_words", "missing_cry",
                         "no_response", "chorus_inconsistent")
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
    song = {
        "id": song_id,
        "title": battle_cry.title(),
        "age_group": age_group,
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
        "key_word": key_word,
        "rhyme_family": rhyme_family,
        "generation_method": "battlecry_v2",
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
        print(f"  Mode: {'lyrics only' if args.lyrics_only else 'full (lyrics + audio + cover)'}")
        print(f"{'='*60}")

        results = []
        for i in range(count):
            try:
                if i > 0:
                    print(f"\n  Waiting 35s for Mistral rate limit...")
                    time.sleep(35)

                # Select params, ensuring no duplicate battle cries in batch
                for _attempt in range(5):
                    params = select_silly_song_params(existing_songs)
                    ok, reason = validate_batch_diversity(params, results)
                    if ok:
                        break
                    print(f"  Skipping {params['battle_cry_id']}: {reason}")

                print(f"\n  Selected: {params['battle_cry']} (ages {params['age_group']})")
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
        songs_to_gen = [s for s in TEST_SONGS if s["cry_id"] == args.cry]
        if not songs_to_gen:
            print(f"Unknown cry_id: {args.cry}")
            print(f"Available: {', '.join(s['cry_id'] for s in TEST_SONGS)}")
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
