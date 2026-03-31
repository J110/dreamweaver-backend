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

# ── MiniMax Style Prompts ────────────────────────────────────────────

SILLY_SONG_STYLES = {
    "2-5": (
        "Super catchy bouncy children's song, bright ukulele and "
        "hand claps with a strong bouncy bass pop on every beat, "
        "120 BPM, the kind of beat that makes a toddler bounce "
        "up and down, ba-BOP ba-BOP, call and response energy, "
        "cheeky and fun, playground chant with a groove, "
        "simple and infectious, impossible to sit still"
    ),
    "6-8": (
        "Super catchy bouncy children's song, guitar and snappy drums "
        "with a groovy bass that bops, 118 BPM, the kind of song "
        "kids sing on a school bus, strong punchy beat clapping on "
        "2 and 4, feel it in your chest, fun and physical, "
        "comedic vocal energy, each WHY or response gets louder"
    ),
    "9-12": (
        "Catchy bouncy song with acoustic guitar and punchy pop beat, "
        "115 BPM, bass line that bops and snare that snaps, "
        "like a hit song on the radio but for kids, groovy and confident, "
        "slightly sarcastic delivery, dramatic pauses for comedy, "
        "cool not babyish, undeniable bounce"
    ),
}

# ── Cover Descriptions (per battle cry) ──────────────────────────────

COVER_DESCRIPTIONS = {
    "not_tired": (
        "A tiny toddler in pajamas standing defiantly with arms crossed, "
        "eyes WIDE OPEN while a huge yawn escapes, a teddy bear asleep "
        "beside them, nighttime bedroom with stars outside the window"
    ),
    "dont_like_it": (
        "A small child pushing away a plate of vegetables with dramatic "
        "disgust, face scrunched up, broccoli flying off the plate, "
        "colorful kitchen background with a shocked parent in the distance"
    ),
    "not_fair": (
        "A child standing on a couch like a courtroom lawyer, pointing "
        "dramatically at an imaginary jury, a dog sitting as the judge "
        "wearing a tiny wig, living room turned into a courtroom"
    ),
    "but_why": (
        "A curious child with an enormous magnifying glass examining "
        "a parent's face, question marks floating everywhere, the child "
        "has one eyebrow raised, colorful background with WHY written "
        "in thought bubbles — wait NO TEXT, just question mark symbols"
    ),
    "i_forgot": (
        "A child standing at the school door with a giant backpack but "
        "missing one shoe, homework papers trailing behind like a bread "
        "crumb trail, a goldfish bowl balanced on their head, chaos energy"
    ),
    "in_a_minute": (
        "A child playing a video game with intense focus, a giant clock "
        "melting like a Dali painting behind them, the parent's shadow "
        "looming in the doorway, one finger held up saying 'wait'"
    ),
}

# ── LLM Prompts ──────────────────────────────────────────────────────

RHYME_FAMILY_PROMPT = """
I'm writing a children's silly song built around the phrase: "{battle_cry}"
For ages: {age_group}

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
Write a silly children's song for ages {age_group}.

BATTLE CRY: "{battle_cry}"
This is what the child shouts at their parent. The song is
their protest anthem. The song is ON THE CHILD'S SIDE.

RHYME PALETTE — these are your available line endings.
Pick the funniest ones. Rearrange them. Modify the sentences
slightly if needed but the END RHYME WORD must stay:

{rhyme_lines}

=== STRUCTURE ===

Opening call-and-response:
Mama/Papa, mama/papa, mama/papa, mama/papa
What? / What NOW? / WHAT?
[child says the battle cry]

Then:

[verse] — 4 lines from the rhyme palette. Reasonable complaints.
[chorus] — the battle cry repeated with energy. 3-4 lines max.
           Must be the catchiest part. A child sings this after
           hearing it ONCE. Include the battle cry words.
[verse] — 4 lines. Pushing it. Getting sillier.
[chorus]
[verse] — 4 lines. Completely absurd. The funniest excuses.
[chorus] — final chorus. Trails off OR collapses
           (child falls asleep, gives up, gets distracted,
           accidentally admits defeat). The ending is a punchline.

=== RULES ===

1. EVERY verse line must end with a word from the rhyme family.
   The RHYME is the structure. No exceptions.

2. Each line is something a child SAYS or ARGUES. Not describes.
   "I didn't even DO anything" = YES (child arguing)
   "The child was feeling rather cross" = NO (narrator describing)

3. Word length limits:
   Ages 2-5: max 2 syllables per word. Max 6 words per line.
   Ages 6-8: max 3 syllables. Max 8 words per line.
   Ages 9-12: conversational. Max 10 words per line.

4. Messy grammar is CORRECT. Kids don't talk in complete sentences
   when they're arguing. "I don't even need that" beats
   "I don't even need that particular thing."

5. Include 2-3 sound effects in the lyrics: *yawn*, *burp*, *snore*,
   *crash*, *splash*, *gasp*. Wrap in asterisks. These are comedy gold.
   Place them where they interrupt the child's argument —
   the interruption IS the joke.

6. Call-and-response: after some lines, the parent responds.
   "why?" or "what?" or "really?" or "hmm?"
   This makes it a GAME between child and parent, not a monologue.
   Use the response that fits the battle cry's energy.

7. The chorus must be DEAD SIMPLE. Under 4 lines.
   Heavy repetition of the battle cry phrase.
   A bouncy rhythm a child's body moves to.
   This is the part that gets stuck in their head.

8. V1 → V2 → V3 must ESCALATE. Same direction, further each time.
   V1: real complaints. V2: exaggerations. V3: completely unhinged.

9. The final chorus has a COLLAPSE or TWIST:
   Child accidentally proves the parent right, OR
   child falls asleep mid-protest, OR
   child gets distracted by something else, OR
   child quietly admits defeat but frames it as a choice.

=== OUTPUT ===

Just the lyrics with [verse] and [chorus] tags.
Start with the call-and-response opening.
No title needed. No markdown code blocks.
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

def validate_silly_song(lyrics: str, battle_cry: str, age_group: str) -> tuple[bool, list[str]]:
    """Validate all five formula elements. Returns (passed, errors)."""
    lines = [l.strip() for l in lyrics.split('\n')
             if l.strip() and not l.strip().startswith('[')]
    sections = extract_sections(lyrics)
    chorus_lines = []
    for c in sections["choruses"]:
        chorus_lines.extend([l for l in c.split("\n") if l.strip()])
    verses = sections["verses"]

    errors = []

    # 1. BATTLE CRY in chorus
    cry_lower = battle_cry.lower()
    # Check if key words from battle cry appear in chorus
    cry_words = [w for w in cry_lower.split() if len(w) > 2]
    cry_in_chorus = any(
        all(w in l.lower() for w in cry_words)
        for l in chorus_lines
    )
    if not cry_in_chorus:
        errors.append(f"Battle cry '{battle_cry}' not found in chorus")

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

    # 3. LINE LENGTH
    max_words = {"2-5": 7, "6-8": 9, "9-12": 11}[age_group]
    for line in lines:
        wc = len(line.split())
        if wc > max_words:
            errors.append(f"Line too long ({wc} words): '{line[:50]}...'")

    # 4. SOUND EFFECTS present
    has_sfx = '*' in lyrics
    has_response = any(w in lyrics.lower() for w in ['why?', 'what?', 'really?', 'hmm?'])
    if not has_sfx:
        errors.append("No sound effects (*yawn*, *burp*, etc.) found")
    if not has_response:
        errors.append("No call-and-response (why? / what?) found")

    # 5. ESCALATION — check we have 3 verses
    if len(verses) < 3:
        errors.append(f"Only {len(verses)} verses (need 3 for escalation)")
    elif len(verses) >= 3:
        print(f"  MANUAL CHECK: Does V3 escalate beyond V1?")
        print(f"    V1: {verses[0][:60]}...")
        print(f"    V3: {verses[2][:60]}...")

    # 6. CHORUS SIMPLICITY
    if chorus_lines and len(chorus_lines) > 5 * len(sections["choruses"]):
        avg_chorus_len = len(chorus_lines) / max(len(sections["choruses"]), 1)
        if avg_chorus_len > 5:
            errors.append(f"Chorus too long: avg {avg_chorus_len:.0f} lines (max 4-5)")

    return (len(errors) == 0, errors)


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
    style = SILLY_SONG_STYLES[song["age_group"]]

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

COVER_PROMPT_TEMPLATE = (
    "Children's book illustration, bold cartoon style, bright saturated colors, "
    "simple background, exaggerated funny expressions, playful and energetic, "
    "square composition, thick outlines, expressive eyes, slightly exaggerated "
    "proportions, Pixar-meets-picture-book aesthetic. "
    "Musical scene: {cover_description} "
    "Include subtle musical elements: small floating music notes, or the "
    "character holding/near an instrument, or a stage-like spotlight feel. "
    "NOT a realistic concert — cartoon musical energy. "
    "DO NOT make it dreamy, muted, watercolor, or soft. This is comedy + music, not bedtime. "
    "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS anywhere in the image. "
    "No title, no caption, no speech bubbles with text, no signs with writing. "
    "Pure illustration only."
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
        print(f"    No cover_description, skipping")
        return False

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


# ── Main Generation ──────────────────────────────────────────────────

def generate_silly_song(
    cry_id: str,
    battle_cry: str,
    age_group: str,
    api_key: str,
    lyrics_only: bool = False,
    force: bool = False,
    max_retries: int = 2,
) -> dict | None:
    """Generate one silly song using the two-step battle cry process."""

    song_id = f"{cry_id}_{age_group.replace('-', '_')}"
    print(f"\n{'='*60}")
    print(f"  Generating: \"{battle_cry}\" (ages {age_group})")
    print(f"  Song ID: {song_id}")
    print(f"{'='*60}")

    # Check if already exists
    json_path = DATA_DIR / f"{song_id}.json"
    if json_path.exists() and not force:
        print(f"  Song JSON already exists. Use --force to regenerate.")
        with open(json_path) as f:
            return json.load(f)

    # ── STEP 1: Generate rhyme family ──
    print(f"\n  Step 1: Generating rhyme family...")
    rhyme_prompt = RHYME_FAMILY_PROMPT.format(
        battle_cry=battle_cry,
        age_group=age_group,
    )
    rhyme_response = call_mistral(
        rhyme_prompt,
        system_msg=(
            "You are a children's songwriter specializing in rhyme. "
            "Generate rhyme families and child-voice lines. "
            "Output in the exact format requested. No markdown code blocks."
        ),
        api_key=api_key,
    )

    key_word, rhyme_family, rhyme_lines = extract_rhyme_data(rhyme_response)
    print(f"  Key word: {key_word}")
    print(f"  Rhyme family: {rhyme_family}")
    print(f"  Lines generated: {len(rhyme_lines)}")

    if len(rhyme_lines) < 8:
        print(f"  WARNING: Only {len(rhyme_lines)} lines generated, may need more variety")

    # Save rhyme data for debugging
    rhyme_debug_path = OUTPUT_DIR / f"{song_id}_rhymes.txt"
    rhyme_debug_path.write_text(rhyme_response)

    # ── STEP 2: Assemble lyrics (with retry) ──
    lyrics = ""
    for attempt in range(max_retries + 1):
        print(f"\n  Step 2: Assembling lyrics (attempt {attempt + 1})...")

        lyrics_prompt = LYRICS_ASSEMBLY_PROMPT.format(
            age_group=age_group,
            battle_cry=battle_cry,
            rhyme_lines='\n'.join(f"- {l}" for l in rhyme_lines),
        )

        # Rate limit: Mistral free tier is 2 req/min
        time.sleep(32)

        lyrics_response = call_mistral(
            lyrics_prompt,
            system_msg=(
                "You are a children's songwriter. Write fun, bouncy silly songs "
                "that children sing along to. Output ONLY the lyrics with section "
                "tags. No explanations, no markdown code blocks."
            ),
            api_key=api_key,
        )
        lyrics = extract_lyrics(lyrics_response)

        print(f"\n--- LYRICS ---")
        print(lyrics)
        print(f"--- END ---\n")

        # ── STEP 3: Validate ──
        passed, errors = validate_silly_song(lyrics, battle_cry, age_group)
        if passed:
            print(f"  ✓ All validation checks passed")
            break
        else:
            print(f"  VALIDATION ISSUES:")
            for e in errors:
                print(f"    ✗ {e}")
            if attempt < max_retries:
                print(f"  Retrying with same rhyme family...")
            else:
                print(f"  ✗ Failed after {max_retries + 1} attempts. Saving anyway for review.")

    # ── STEP 4: Normalize for TTS ──
    lyrics_normalized = normalize_caps_for_tts(lyrics)

    # ── Build song metadata ──
    song = {
        "id": song_id,
        "title": battle_cry.title(),
        "age_group": age_group,
        "lyrics": lyrics_normalized,
        "style_prompt": SILLY_SONG_STYLES[age_group],
        "cover_description": COVER_DESCRIPTIONS.get(cry_id, f"A child shouting '{battle_cry}' with funny energy"),
        "animation_preset": "bounce_rhythmic",
        "created_at": date.today().isoformat(),
        "play_count": 0,
        "replay_count": 0,
        # Battle cry metadata (extra, for tracking)
        "battle_cry_id": cry_id,
        "battle_cry": battle_cry,
        "key_word": key_word,
        "rhyme_family": rhyme_family,
        "generation_method": "battlecry_v1",
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
        """,
    )
    parser.add_argument("--test", action="store_true",
                        help="Generate one song per age group (3 songs)")
    parser.add_argument("--all", action="store_true",
                        help="Generate all 6 test songs")
    parser.add_argument("--cry", help="Generate a specific battle cry by ID")
    parser.add_argument("--lyrics-only", action="store_true",
                        help="Skip audio and cover generation")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files exist")
    args = parser.parse_args()

    if not args.test and not args.all and not args.cry:
        parser.error("Specify --test, --all, or --cry <id>")

    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set")
        sys.exit(1)

    if not args.lyrics_only:
        if replicate is None:
            print("WARNING: replicate not installed — audio generation will fail")
        if not os.getenv("REPLICATE_API_TOKEN"):
            print("WARNING: REPLICATE_API_TOKEN not set — audio generation will fail")

    # Select songs to generate
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
