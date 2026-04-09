#!/usr/bin/env python3
"""Generate 3 experimental musical poems — one per age group.

Sound poem (2-5), Nonsense poem (6-8), Question poem (9-12).
End-to-end: generates text (Mistral) → validates → generates audio (fal.ai MiniMax) → cover (FLUX) → saves.

Usage:
    python3 scripts/generate_experimental_poems.py --all
    python3 scripts/generate_experimental_poems.py --age 2-5
    python3 scripts/generate_experimental_poems.py --all --dry-run
    python3 scripts/generate_experimental_poems.py --all --skip-audio
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "seed_output" / "poems_test"
AUDIO_DIR = BASE_DIR / "public" / "audio" / "poems"
COVER_DIR = BASE_DIR / "public" / "covers" / "poems"
DATA_DIR = BASE_DIR / "data" / "poems"


def load_existing_poems() -> list:
    """Load all existing poem metadata from data/poems/ for diversity checks."""
    poems = []
    if not DATA_DIR.exists():
        return poems
    for f in DATA_DIR.glob("*.json"):
        try:
            poems.append(json.loads(f.read_text()))
        except Exception:
            continue
    return poems


def build_anti_duplication_prompt(poem_type: str, age_group: str) -> str:
    """Build prompt section listing existing poems to avoid duplication."""
    existing = load_existing_poems()
    same_type = [p for p in existing if p.get("poem_type") == poem_type]
    if not same_type:
        return ""

    lines = ["\n\nCRITICAL — DO NOT DUPLICATE existing poems:"]
    for p in same_type:
        title = p.get("title", "?")
        first_line = (p.get("poem_text", "") or "").split("\n")[0][:60]
        lines.append(f'- "{title}" starts with: "{first_line}"')
    lines.append(
        "\nYour poem MUST have a completely different title, subject, "
        "and opening line. Do NOT reuse any imagery or phrases from above."
    )
    return "\n".join(lines)

# ═════════════════════════════════════════════════════════════════════
# POEM DEFINITIONS (from spec)
# ═════════════════════════════════════════════════════════════════════

TEST_POEMS = [
    {"age": "2-5",  "poem_type": "sound"},
    {"age": "6-8",  "poem_type": "nonsense"},
    {"age": "9-12", "poem_type": "question"},
]

POEM_TYPE_DESCRIPTIONS = {
    "sound": (
        "SOUND POEM: A poem MADE of sounds. The words ARE the "
        "sounds they describe. Onomatopoeia is the structure. "
        "Splash, drip, crash, whoosh, pop, fizz, buzz, hiss, "
        "crunch, squelch. Reading this poem out loud IS performing "
        "it. The child hears the words and hears the world. "
        "Build a scene entirely from its sounds."
    ),
    "nonsense": (
        "NONSENSE POEM: Words that sound amazing together but "
        "don't need to mean anything real. The pleasure is pure "
        "MOUTH FEEL — how the words feel to say out loud. Invent "
        "words if needed. Combine real words in ways that sound "
        "delicious but mean nothing. The child's mouth should "
        "WANT to say these words. Rhythm and sound over meaning."
    ),
    "question": (
        "QUESTION POEM: A chain of funny unanswerable questions. "
        "Each question is more absurd than the last. They start "
        "simple and everyday, then escalate into impossible "
        "territory. The child starts inventing their own questions "
        "by the end. Each question is its own line. The questions "
        "DON'T get answered — that's the point."
    ),
}

# ═════════════════════════════════════════════════════════════════════
# MINIMAX STYLE PROMPTS
# ═════════════════════════════════════════════════════════════════════

POEM_STYLES = {
    "2-5": (
        "Children's musical nursery rhyme, "
        "{instruments}, {tempo} BPM, "
        "warm clear voice speaking each word rhythmically, "
        "gentle bouncy beat underneath, "
        "like a parent performing a poem at bedtime, "
        "every single word crystal clear, not rushed, "
        "playful rhythm, not a pop song"
    ),
    "6-8": (
        "Children's rhythmic spoken word with melody, "
        "{instruments}, {tempo} BPM, "
        "clear voice riding a gentle groove, "
        "each line bounces with personality, "
        "flowing rhythm not verse-chorus structure, "
        "every word easy to understand, "
        "fun to listen to and repeat"
    ),
    "9-12": (
        "Children's spoken word over cool beat, "
        "{instruments}, {tempo} BPM, "
        "confident clear voice on the rhythm, "
        "smooth and flowing like gentle rap, "
        "melodic but spoken not sung, "
        "every word lands clearly, "
        "rhythmic and smart"
    ),
}

POEM_TEMPO_RANGE = {
    "2-5":  (95, 108),
    "6-8":  (100, 112),
    "9-12": (105, 115),
}

POEM_INSTRUMENT_POOLS = {
    "2-5": [
        "xylophone and soft claps",
        "kalimba and gentle shaker",
        "music box and light tambourine",
    ],
    "6-8": [
        "acoustic guitar and finger snaps",
        "ukulele and soft bongos",
        "piano and light brush drums",
    ],
    "9-12": [
        "acoustic guitar and lo-fi beat",
        "piano and soft snare",
        "guitar and gentle beatbox",
    ],
}

COVER_PROMPTS = {
    "sound": (
        "Abstract minimal art, soft shapes suggesting sound waves and ripples, "
        "gentle gradients in warm blues and oranges, playful splashes of color, "
        "no text no hands no people no characters no faces, "
        "children's book illustration style, safe and calming, "
        "the visual equivalent of onomatopoeia"
    ),
    "nonsense": (
        "Abstract minimal art, swirling colorful shapes that feel like made-up words, "
        "gentle gradients in purple and teal, bouncy organic forms, "
        "no text no hands no people no characters no faces, "
        "children's book illustration style, safe and calming, "
        "the visual equivalent of mouth feel and rhythm"
    ),
    "question": (
        "Abstract minimal art, floating question-mark-like shapes in soft light, "
        "gentle gradients in deep blue and gold, curious playful atmosphere, "
        "no text no hands no people no characters no faces, "
        "children's book illustration style, safe and calming, "
        "the visual equivalent of wonder and absurd questions"
    ),
}

# ═════════════════════════════════════════════════════════════════════
# MOOD MAPPING
# ═════════════════════════════════════════════════════════════════════

MOOD_TO_POEM_ENERGY = {
    "wired":   "bouncy and playful, fun energy that channels into rhythm",
    "curious": "dreamy and wondering, spacious, leaves room to think",
    "calm":    "soft and settling, warm steady rhythm, almost a lullaby",
    "sad":     "gentle and tender, quiet rhythm, words that feel like a hug",
    "anxious": "cozy and reassuring, steady predictable rhythm, safe and warm",
    "angry":   "firm then softening, strong rhythm that gradually settles",
}

MOOD_TO_POEM_TYPES = {
    "wired":   ["nonsense", "tongue_twister", "sound"],
    "curious": ["question", "list", "tiny_story"],
    "calm":    ["sound", "tiny_story", "nonsense"],
    "sad":     ["tiny_story", "question", "list"],
    "anxious": ["sound", "nonsense", "tiny_story"],
    "angry":   ["tongue_twister", "sound", "list"],
}

MOOD_TEMPO_OFFSET = {
    "wired":    +5,
    "curious":  0,
    "calm":    -8,
    "sad":     -10,
    "anxious": -5,
    "angry":    0,
}

# ═════════════════════════════════════════════════════════════════════
# POEM TEXT GENERATION (Mistral)
# ═════════════════════════════════════════════════════════════════════

POEM_GENERATION_PROMPT = """Write a children's poem for ages {age_group}.

TYPE: {poem_type}
{poem_type_description}

MOOD: {mood}
This poem is for a child who is feeling {mood} right now.
The rhythm and word choices should match that feeling:
{mood_energy}

This poem will be PERFORMED with music underneath. It's not
a song — no verse/chorus structure. It flows continuously
like a nursery rhyme being spoken rhythmically over a beat.

RHYTHM IS EVERYTHING:
Read every line out loud. Clap the beat. If the rhythm
breaks or stumbles anywhere, rewrite that line. The rhythm
must be so strong and steady that the child's body rocks
to it without thinking.

LENGTH:
8-16 lines total. That's the ENTIRE poem.
Short enough to memorise. Long enough to enjoy.
This must fit within 30-45 seconds when performed.

LINE LENGTH:
Maximum 8 words per line.
Maximum 9 syllables per line.
One thought per line. Short simple words.

CONSISTENT LINE LENGTH:
Every line should have between 6 and 8 syllables. Not some
lines with 4 syllables and others with 9. Keep the count
EVEN across all lines so each line gets the same breathing
room when performed.

RHYME:
Rhyming couplets — every two lines rhyme with each other.
Line 1 rhymes with line 2.
Line 3 rhymes with line 4.
Line 5 rhymes with line 6.
And so on. aa bb cc dd pattern.

Couplets are the easiest rhythm for children to follow.
The child hears line 1 and anticipates the rhyme in line 2.

ENDING:
The last 2 lines should either:
- Circle back to the opening line (the poem loops)
- Land on something quiet and sleepy
- End with a question the child thinks about in bed

WORDS:
Use short, simple words. One-syllable words are best.
The child should be able to repeat any line from memory
after hearing it twice. If a line is hard to remember,
it's too complex.

OUTPUT FORMAT (JSON):
{{
  "title": "evocative title, under 5 words",
  "poem_type": "{poem_type}",
  "poem_text": "the full poem, lines separated by newlines",
  "cover_context": "one sentence describing a dreamy visual for the poem"
}}

Just the JSON. No commentary."""


def count_syllables(word: str) -> int:
    """Rough syllable count for English words."""
    word = word.lower().strip(".,!?;:'\"()-")
    if not word:
        return 0
    # Simple heuristic: count vowel groups
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in "aeiouy"
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    # Silent e
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def rough_rhyme_check(word_a: str, word_b: str) -> bool:
    """Basic check if two words might rhyme."""
    if word_a == word_b:
        return True
    if len(word_a) >= 2 and len(word_b) >= 2:
        if word_a[-2:] == word_b[-2:]:
            return True
    if len(word_a) >= 3 and len(word_b) >= 3:
        if word_a[-3:] == word_b[-3:]:
            return True
    return False


def check_syllable_consistency(poem_text: str, max_variance: int = 3) -> list:
    """Flag lines whose syllable count deviates too far from average."""
    lines = [l.strip() for l in poem_text.split("\n") if l.strip()]
    counts = []
    for line in lines:
        syl = sum(count_syllables(w) for w in line.split())
        counts.append((line, syl))

    if not counts:
        return []

    avg = sum(c for _, c in counts) / len(counts)

    problems = []
    for line, count in counts:
        if abs(count - avg) > max_variance:
            problems.append({
                "line": line,
                "syllables": count,
                "average": round(avg),
                "issue": "too long" if count > avg else "too short",
            })

    return problems


def validate_poem(poem_text: str, poem_type: str, age_group: str) -> tuple:
    """Validate poem before sending to MiniMax. Returns (errors, syl_problems)."""
    errors = []
    warnings = []

    lines = [l.strip() for l in poem_text.split("\n") if l.strip()]

    # Line count
    if len(lines) < 8:
        errors.append(f"Too short: {len(lines)} lines (min 8)")
    if len(lines) > 16:
        errors.append(f"Too long: {len(lines)} lines (max 16)")

    # Syllable count per line
    for line in lines:
        syllables = sum(count_syllables(w) for w in line.split())
        if syllables > 9:
            warnings.append(f"High syllable count ({syllables}): '{line}'")

    # Word count per line
    for line in lines:
        words = len(line.split())
        if words > 8:
            errors.append(f"Too many words ({words}): '{line}'")

    # Couplet rhyme check
    for i in range(0, len(lines) - 1, 2):
        word_a = lines[i].rstrip("!?.,").split()[-1].lower()
        word_b = lines[i + 1].rstrip("!?.,").split()[-1].lower()
        if not rough_rhyme_check(word_a, word_b):
            warnings.append(f"Possible non-rhyme: '{word_a}' / '{word_b}'")

    # Character count for MiniMax
    char_count = len(poem_text.strip())
    if char_count > 500:
        errors.append(f"Too long for MiniMax: {char_count} chars (max 500)")

    # No section tags
    if "[" in poem_text and "]" in poem_text:
        if any(tag in poem_text.lower() for tag in
               ["[verse", "[chorus", "[bridge", "[opening"]):
            errors.append("Contains song structure tags — poems should be continuous")

    # Syllable consistency (warning only, not a hard gate)
    syl_problems = check_syllable_consistency(poem_text)

    if errors:
        print("  VALIDATION ERRORS:")
        for e in errors:
            print(f"    ✗ {e}")
    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    ⚠ {w}")
    if syl_problems:
        print("  SYLLABLE CONSISTENCY:")
        for p in syl_problems:
            print(f"    ⚠ {p['syllables']} syl ({p['issue']}, avg {p['average']}): '{p['line']}'")
    if not errors:
        print("    ✓ All checks passed")

    return errors, syl_problems


def generate_poem_text(age_group: str, poem_type: str, mood: str,
                       max_retries: int = 2) -> dict:
    """Generate poem text via Mistral. Returns dict with title, poem_text, cover_context."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError("mistralai not installed — pip install mistralai")

    client = Mistral(api_key=api_key)
    mood_energy = MOOD_TO_POEM_ENERGY.get(mood, MOOD_TO_POEM_ENERGY["calm"])

    for attempt in range(max_retries + 1):
        print(f"  Generating text (attempt {attempt + 1})...")

        prompt = POEM_GENERATION_PROMPT.format(
            age_group=age_group,
            poem_type=poem_type,
            poem_type_description=POEM_TYPE_DESCRIPTIONS[poem_type],
            mood=mood,
            mood_energy=mood_energy,
        )

        # Add anti-duplication context from existing poems
        prompt += build_anti_duplication_prompt(poem_type, age_group)

        if attempt > 0:
            prompt += f"\n\nPREVIOUS ATTEMPT HAD ISSUES:\n"
            prompt += "\n".join(f"- {e}" for e in prev_errors)
            if prev_syl_problems:
                prompt += "\n\nSome lines have uneven syllable counts:\n"
                for p in prev_syl_problems:
                    prompt += (f"  {p['syllables']} syllables ({p['issue']}, "
                               f"avg {p['average']}): '{p['line']}'\n")
                prompt += (f"\nAdjust these lines to be closer to "
                           f"{prev_syl_problems[0]['average']} syllables each.")
            prompt += "\n\nFix these issues. Keep the poem short and simple."

        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": "You are a children's poet who writes rhythmic, memorable poems for bedtime."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.85,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = min(2 ** (attempt + 1) * 15, 120)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise

        raw = response.choices[0].message.content.strip()
        # Clean markdown fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(l for l in lines if not l.startswith("```"))

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  Failed to parse JSON, retrying...")
            prev_errors = ["Output was not valid JSON"]
            prev_syl_problems = []
            continue

        title = parsed.get("title", f"{poem_type} poem")
        poem_text = parsed.get("poem_text", "")
        cover_context = parsed.get("cover_context", "")

        if not poem_text:
            print(f"  Empty poem text, retrying...")
            prev_errors = ["poem_text was empty"]
            prev_syl_problems = []
            continue

        print(f"  Title: {title}")
        print(f"  Lines: {len(poem_text.strip().splitlines())}")
        print(f"  Chars: {len(poem_text.strip())}")
        print(f"\n--- POEM ---")
        print(poem_text)
        print(f"--- END ---\n")

        prev_errors, prev_syl_problems = validate_poem(poem_text, poem_type, age_group)

        if not prev_errors or attempt == max_retries:
            if prev_errors:
                print(f"  Proceeding despite errors after {max_retries + 1} attempts")
            return {
                "title": title,
                "poem_text": poem_text.strip(),
                "cover_context": cover_context,
            }

        # Rate limit pause between retries
        time.sleep(32)

    raise RuntimeError("Failed to generate poem text")


# ═════════════════════════════════════════════════════════════════════
# AUDIO GENERATION (fal.ai MiniMax → Replicate fallback)
# ═════════════════════════════════════════════════════════════════════

def generate_audio_fal(style_prompt: str, poem_text: str) -> tuple:
    """Generate audio via fal.ai MiniMax Music v2. Returns (audio_bytes, audio_url)."""
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise RuntimeError("FAL_KEY not set")

    try:
        import fal_client
    except ImportError:
        raise RuntimeError("fal-client not installed — pip install fal-client")

    print(f"  Calling fal.ai MiniMax Music v2...")
    start = time.time()

    # Poems don't use [verse]/[chorus] — just raw lines as lyrics
    result = fal_client.subscribe("fal-ai/minimax-music/v2", arguments={
        "prompt": style_prompt,
        "lyrics_prompt": poem_text,
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
    })

    audio_info = result.get("audio") or result.get("data", {}).get("audio")
    if not audio_info or not audio_info.get("url"):
        raise RuntimeError(f"No audio URL in response: {result}")

    audio_url = audio_info["url"]
    print(f"  Got audio URL, downloading...")

    import httpx
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    elapsed = time.time() - start
    print(f"  Got {len(resp.content):,} bytes in {elapsed:.0f}s")
    return resp.content, audio_url


def generate_audio_replicate(style_prompt: str, poem_text: str) -> tuple:
    """Fallback: generate audio via Replicate MiniMax Music 1.5."""
    try:
        import replicate
        import httpx
    except ImportError:
        raise RuntimeError("replicate/httpx not installed")

    print(f"  Calling MiniMax Music 1.5 on Replicate (fallback)...")
    start = time.time()

    output = replicate.run(
        "minimax/music-1.5",
        input={"prompt": style_prompt, "lyrics": poem_text},
    )
    if not output:
        raise RuntimeError("No output from Replicate")

    audio_url = str(output)
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    elapsed = time.time() - start
    print(f"  Got {len(resp.content):,} bytes in {elapsed:.0f}s")
    return resp.content, audio_url


# ═════════════════════════════════════════════════════════════════════
# COVER GENERATION (FLUX via Together AI)
# ═════════════════════════════════════════════════════════════════════

def generate_cover(poem_type: str, poem_id: str) -> str:
    """Generate cover image via FLUX on Together AI. Returns filename."""
    api_key = os.environ.get("TOGETHER_API_KEY")
    if not api_key:
        print("  WARNING: No TOGETHER_API_KEY — generating placeholder cover")
        return generate_placeholder_cover(poem_type, poem_id)

    try:
        import httpx
    except ImportError:
        return generate_placeholder_cover(poem_type, poem_id)

    prompt = COVER_PROMPTS.get(poem_type, COVER_PROMPTS["sound"])

    print(f"  Generating FLUX cover via Together AI...")
    try:
        resp = httpx.post(
            "https://api.together.xyz/v1/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "black-forest-labs/FLUX.1-schnell",
                "prompt": prompt,
                "width": 1024,
                "height": 1024,
                "n": 1,
                "response_format": "b64_json",
            },
            timeout=60,
        )

        if resp.status_code != 200:
            print(f"  Together AI failed ({resp.status_code}), using placeholder")
            return generate_placeholder_cover(poem_type, poem_id)

        data = resp.json()
        import base64
        b64 = data["data"][0]["b64_json"]
        image_bytes = base64.b64decode(b64)

        # Save as WebP
        cover_file = f"{poem_id}_cover.webp"
        cover_path = OUTPUT_DIR / cover_file
        cover_path.write_bytes(image_bytes)

        # Also copy to public covers dir
        COVER_DIR.mkdir(parents=True, exist_ok=True)
        (COVER_DIR / cover_file).write_bytes(image_bytes)

        print(f"  Cover saved: {cover_file} ({len(image_bytes):,} bytes)")
        return cover_file

    except Exception as e:
        print(f"  Cover generation failed: {e}")
        return generate_placeholder_cover(poem_type, poem_id)


def generate_placeholder_cover(poem_type: str, poem_id: str) -> str:
    """Generate placeholder SVG cover."""
    colors = {
        "sound": ("#1a2a4e", "#0d1a2e", "#4a6a9e"),
        "nonsense": ("#2a1a4e", "#1a0d2e", "#6a4a9e"),
        "question": ("#1a3a3e", "#0d2a2e", "#4a8a7e"),
    }
    c1, c2, c3 = colors.get(poem_type, colors["sound"])

    cover_file = f"{poem_id}_cover.svg"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{c1}"/>
      <stop offset="100%" stop-color="{c2}"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <circle cx="256" cy="220" r="80" fill="{c3}" opacity="0.3">
    <animate attributeName="r" values="78;84;78" dur="4s" repeatCount="indefinite"/>
  </circle>
  <circle cx="256" cy="220" r="40" fill="{c3}" opacity="0.2">
    <animate attributeName="r" values="38;44;38" dur="3s" repeatCount="indefinite"/>
  </circle>
</svg>"""
    cover_path = OUTPUT_DIR / cover_file
    cover_path.write_text(svg)
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    (COVER_DIR / cover_file).write_text(svg)
    return cover_file


# ═════════════════════════════════════════════════════════════════════
# MAIN GENERATION
# ═════════════════════════════════════════════════════════════════════

def get_audio_duration(mp3_path: Path) -> int:
    """Get duration of MP3 in seconds."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(str(mp3_path))
        return int(len(audio) / 1000)
    except Exception:
        return max(1, int(mp3_path.stat().st_size / 16000))


def generate_poem(age_group: str, poem_type: str, mood: str = "calm",
                  dry_run: bool = False, skip_audio: bool = False) -> dict | None:
    """Generate one musical poem end-to-end. Returns metadata dict or None."""

    # Select instruments and tempo (with mood offset)
    instruments = random.choice(POEM_INSTRUMENT_POOLS[age_group])
    base_lo, base_hi = POEM_TEMPO_RANGE[age_group]
    offset = MOOD_TEMPO_OFFSET.get(mood, 0)
    tempo = random.randint(base_lo + offset, base_hi + offset)

    poem_id = f"{poem_type}_{age_group.replace('-', '_')}_{int(time.time()) & 0xFFFF:04x}"

    print(f"\n{'='*60}")
    print(f"Generating: {poem_type} poem for ages {age_group} (mood: {mood})")
    print(f"  Instruments: {instruments}")
    print(f"  Tempo: {tempo} BPM (base {base_lo}-{base_hi}, offset {offset:+d})")
    print(f"  ID: {poem_id}")
    print(f"{'='*60}")

    if dry_run:
        print(f"  [DRY RUN] Would generate text + audio + cover")
        return {"id": poem_id, "poem_type": poem_type, "age_group": age_group,
                "mood": mood, "tempo": tempo, "dry_run": True}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Generate poem text
    try:
        poem_data = generate_poem_text(age_group, poem_type, mood)
    except Exception as e:
        print(f"  ✗ Text generation failed: {e}")
        return None

    title = poem_data["title"]
    poem_text = poem_data["poem_text"]
    cover_context = poem_data["cover_context"]

    # 2. Prepare for MiniMax
    minimax_lyrics = poem_text.strip()
    if len(minimax_lyrics) > 500:
        lines = minimax_lyrics.split("\n")
        while len("\n".join(lines)) > 500 and lines:
            lines.pop()
        minimax_lyrics = "\n".join(lines)
        print(f"  Trimmed to {len(minimax_lyrics)} chars for MiniMax")

    # 3. Build style prompt with mood energy
    energy = MOOD_TO_POEM_ENERGY.get(mood, MOOD_TO_POEM_ENERGY["calm"])
    style = (
        f"Children's musical poem, {instruments}, {tempo} BPM, "
        f"{energy}, "
        f"clear warm vocal, every word easy to understand"
    )
    if len(style) > 300:
        style = style[:297] + "..."

    # 4. Generate audio
    audio_engine = "none"
    duration = 0
    if not skip_audio:
        try:
            audio_bytes, audio_url = generate_audio_fal(style, minimax_lyrics)
            audio_engine = "minimax-music-v2-fal"
        except Exception as e:
            print(f"  fal.ai failed: {e}")
            print(f"  Trying Replicate fallback...")
            try:
                audio_bytes, audio_url = generate_audio_replicate(style, minimax_lyrics)
                audio_engine = "minimax-music-1.5-replicate"
            except Exception as e2:
                print(f"  ✗ Both audio engines failed: {e2}")
                return None

        # Save audio
        mp3_path = OUTPUT_DIR / f"{poem_id}.mp3"
        mp3_path.write_bytes(audio_bytes)
        (AUDIO_DIR / f"{poem_id}.mp3").write_bytes(audio_bytes)
        print(f"  Audio: {mp3_path.name} ({len(audio_bytes):,} bytes)")

        duration = get_audio_duration(mp3_path)
        print(f"  Duration: {duration}s")
    else:
        print(f"  [SKIP AUDIO]")

    # 5. Generate cover
    cover_file = generate_cover(poem_type, poem_id)

    # 6. Save metadata
    meta = {
        "id": poem_id,
        "title": title,
        "content_type": "poem",
        "poem_type": poem_type,
        "age_group": age_group,
        "mood": mood,
        "instruments": instruments,
        "tempo": tempo,
        "poem_text": poem_text,
        "char_count": len(minimax_lyrics),
        "line_count": len(poem_text.strip().splitlines()),
        "audio_file": f"{poem_id}.mp3" if not skip_audio else None,
        "cover_file": cover_file,
        "cover_context": cover_context,
        "style_prompt": style,
        "duration_seconds": duration,
        "audio_engine": audio_engine,
        "created_at": str(date.today()),
    }

    meta_path = OUTPUT_DIR / f"{poem_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"  ✓ Saved: {meta_path.name}")

    # Also write to data/poems/ so the API can serve it immediately
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_path = DATA_DIR / f"{poem_id}.json"
    data_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"  ✓ Published: {data_path.name}")

    return meta


TEST_MOOD_POEMS = [
    {"mood": "wired",   "age": "6-8"},   # Should sound bouncy
    {"mood": "calm",    "age": "2-5"},   # Should sound soft and settling
    {"mood": "curious", "age": "9-12"},  # Should sound spacious and wondering
]


def main():
    parser = argparse.ArgumentParser(
        description="Generate experimental musical poems via MiniMax",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--all", action="store_true",
                        help="Generate all 3 test poems (original age-based)")
    parser.add_argument("--mood-test", action="store_true",
                        help="Generate 3 mood-varied poems (wired/calm/curious)")
    parser.add_argument("--age", choices=["2-5", "6-8", "9-12"],
                        help="Generate poem for specific age group")
    parser.add_argument("--mood", choices=list(MOOD_TO_POEM_ENERGY.keys()),
                        default="calm",
                        help="Child mood (default: calm)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without generating")
    parser.add_argument("--skip-audio", action="store_true",
                        help="Skip audio generation (text + cover only)")
    args = parser.parse_args()

    if not args.all and not args.age and not args.mood_test:
        parser.error("Specify --all, --mood-test, or --age <group>")

    # Select which poems to generate
    if args.mood_test:
        configs = []
        for t in TEST_MOOD_POEMS:
            # Pick poem type filtered by mood
            eligible = MOOD_TO_POEM_TYPES.get(t["mood"], list(POEM_TYPE_DESCRIPTIONS.keys()))
            # Use first eligible type that we have a description for
            poem_type = next((pt for pt in eligible if pt in POEM_TYPE_DESCRIPTIONS), "sound")
            configs.append({"age": t["age"], "poem_type": poem_type, "mood": t["mood"]})
    elif args.all:
        configs = [{"age": c["age"], "poem_type": c["poem_type"], "mood": args.mood}
                   for c in TEST_POEMS]
    else:
        matching = [c for c in TEST_POEMS if c["age"] == args.age]
        configs = [{"age": c["age"], "poem_type": c["poem_type"], "mood": args.mood}
                   for c in matching]

    print(f"{'='*60}")
    print(f"Experimental Musical Poems — {len(configs)} poem(s)")
    print(f"{'='*60}")

    results = []
    for i, config in enumerate(configs):
        if i > 0:
            time.sleep(5)  # Pause between generations

        try:
            meta = generate_poem(
                config["age"], config["poem_type"],
                mood=config.get("mood", args.mood),
                dry_run=args.dry_run,
                skip_audio=args.skip_audio,
            )
            if meta:
                results.append(meta)
        except Exception as e:
            print(f"  ✗ FAILED: {e}")

    print(f"\n{'='*60}")
    print(f"Generated {len(results)}/{len(configs)} poems")
    if not args.dry_run:
        print(f"Files in: {OUTPUT_DIR}/")
    print()

    for m in results:
        dur = m.get("duration_seconds", "?")
        mood_tag = m.get("mood", "?")
        print(f"  [{m['poem_type']}] {m.get('title', '?')} (ages {m['age_group']}, {mood_tag}) — {dur}s")

    if not args.dry_run and results:
        print(f"\nListen to each and check:")
        print(f"  1. Can you hear every word clearly?")
        print(f"  2. Is the rhythm strong enough to rock to?")
        print(f"  3. Does it feel like spoken word, not singing?")
        print(f"  4. Could a child repeat a line after hearing it twice?")
        print(f"  5. Is it distinctly different from a silly song?")
        if args.mood_test:
            print(f"\nMood comparison:")
            print(f"  - Wired poem should feel noticeably more energetic")
            print(f"  - Calm poem should feel soft and settling")
            print(f"  - Curious poem should feel spacious and reflective")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
