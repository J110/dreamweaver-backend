#!/usr/bin/env python3
"""
Generate one experimental long story episode — full pipeline.

Steps:
  1. Generate story text via Mistral (characters, phases, song seed, repeated phrase)
  2. Parse and validate
  3. Generate song lyrics via Mistral
  4. Generate song audio via MiniMax on Replicate
  5. Assign voices
  6. Generate TTS for all sections via Chatterbox on Modal
  7. Generate cover via FLUX (Together AI)
  8. Assemble final episode audio with pydub
  9. Save metadata

Usage:
    python3 scripts/generate_long_story_episode.py
    python3 scripts/generate_long_story_episode.py --mood calm --setting ocean --character-type whale
    python3 scripts/generate_long_story_episode.py --dry-run       # Print prompt only
    python3 scripts/generate_long_story_episode.py --text-only     # Skip audio/cover
    python3 scripts/generate_long_story_episode.py --from-metadata # Resume from saved metadata.json
"""

import argparse
import base64
import io
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

import httpx
from pydub import AudioSegment
from mistralai import Mistral
from dotenv import load_dotenv

# Force unbuffered stdout so background runs show progress
import functools
print = functools.partial(print, flush=True)

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

# Ensure ffmpeg is in PATH (homebrew on macOS)
for ffmpeg_dir in ["/opt/homebrew/bin", "/usr/local/bin"]:
    if os.path.exists(os.path.join(ffmpeg_dir, "ffmpeg")):
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + ":" + os.environ.get("PATH", "")
        break

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-large-latest"

# ── Word count targets ──

LONG_STORY_WORD_COUNTS = {
    "2-5": {
        "phase_1": (200, 300),
        "phase_2": (200, 350),
        "phase_3": (150, 250),
        "total": (550, 900),
    },
    "6-8": {
        "phase_1": (250, 400),
        "phase_2": (300, 450),
        "phase_3": (200, 300),
        "total": (750, 1150),
    },
    "9-12": {
        "phase_1": (300, 500),
        "phase_2": (350, 500),
        "phase_3": (250, 400),
        "total": (900, 1400),
    },
}

# ── Character instructions ──

CHARACTER_INSTRUCTIONS = {
    1: (
        "This is a solo journey. The character talks:\n"
        "- To themselves: thinking out loud\n"
        "- To the world around them: the trees, the wind, the moon\n"
        "- To the child: 1-2 moments of direct address\n\n"
        "A solo character is NOT silent. Their voice is their company."
    ),
    2: (
        "Two characters. They travel together or meet along the way.\n"
        "Their conversations are SHORT — 1-2 lines each, back and forth.\n"
        "Not monologues. Quick exchanges that reveal personality.\n\n"
        "The second character should have a DIFFERENT personality \n"
        "from the main character. If the main character is wise, \n"
        "the second might be small or curious or nervous.\n\n"
        "By mid-Phase 2, the second character falls asleep. \n"
        "The main character is alone again. Then they sleep too."
    ),
    3: (
        "Three characters. The main character meets them along the way.\n"
        "Conversations are SHORT — quick back-and-forth, never more \n"
        "than 2 lines per character in a row.\n\n"
        "Each character has a DISTINCT personality. No two alike.\n\n"
        "In Phase 2, they fall asleep one by one:\n"
        "- The most energetic character sleeps first (surprising)\n"
        "- Then the second\n"
        "- The main character is last\n"
        "The child watches each one fall asleep. This normalises it."
    ),
}

# ── Song arc by mood ──

MOOD_SONG_ARC = {
    "wired":   "Starts with gentle movement, ends completely still",
    "curious": "Starts with wondering, ends with quiet acceptance",
    "calm":    "Starts warm, ends warmer and even quieter",
    "sad":     "Starts tender, ends held and safe",
    "anxious": "Starts steady, ends certain and grounded",
    "angry":   "Starts firm, ends soft and released",
}

# ── Voice assignment ──

ALL_VOICES = ["female_1", "female_2", "female_3", "male_1", "male_2", "male_3"]

MOOD_NARRATOR_VOICE = {
    "wired":   "female_1",
    "curious": "female_2",
    "calm":    "female_3",
    "sad":     "female_1",
    "anxious": "female_2",
    "angry":   "female_3",
}

CHARACTER_VOICE_MODIFIERS = {
    "confident": {"speed_offset": +0.03, "exag_offset": +0.10},
    "gentle":    {"speed_offset": -0.03, "exag_offset": +0.05},
    "small":     {"speed_offset": +0.05, "exag_offset": +0.08},
    "wise":      {"speed_offset": -0.05, "exag_offset": -0.05},
    "nervous":   {"speed_offset": +0.04, "exag_offset": +0.12},
    "curious":   {"speed_offset": +0.02, "exag_offset": +0.08},
    "stubborn":  {"speed_offset": -0.02, "exag_offset": +0.10},
    "dreamy":    {"speed_offset": -0.06, "exag_offset": -0.03},
    "brave":     {"speed_offset": +0.01, "exag_offset": +0.07},
    "quiet":     {"speed_offset": -0.04, "exag_offset": -0.08},
    "playful":   {"speed_offset": +0.04, "exag_offset": +0.10},
    "careful":   {"speed_offset": -0.03, "exag_offset": -0.05},
    "sleepy":    {"speed_offset": -0.08, "exag_offset": -0.10},
}

LONG_STORY_TTS = {
    "intro":           {"exaggeration": 0.55, "speed": 0.88, "cfg_weight": 0.50},
    "phase_1":         {"exaggeration": 0.50, "speed": 0.85, "cfg_weight": 0.50},
    "phrase":          {"exaggeration": 0.60, "speed": 0.78, "cfg_weight": 0.42},
    "song_transition": {"exaggeration": 0.45, "speed": 0.80, "cfg_weight": 0.48},
    "post_song":       {"exaggeration": 0.40, "speed": 0.78, "cfg_weight": 0.45},
    "phase_2":         {"exaggeration": 0.35, "speed": 0.78, "cfg_weight": 0.40},
    "phase_3":         {"exaggeration": 0.25, "speed": 0.72, "cfg_weight": 0.35},
    "whisper":         {"exaggeration": 0.15, "speed": 0.68, "cfg_weight": 0.30},
}

# ── Mood song style (for future MiniMax integration) ──

MOOD_SONG_STYLE = {
    "curious": {"instruments": "soft celesta and light harp", "tempo": 85},
    "wired":   {"instruments": "gentle guitar and soft xylophone", "tempo": 90},
    "calm":    {"instruments": "warm music box and gentle harp", "tempo": 78},
    "sad":     {"instruments": "solo piano", "tempo": 75},
    "anxious": {"instruments": "soft low strings and gentle harp", "tempo": 80},
    "angry":   {"instruments": "low warm cello and soft drum", "tempo": 82},
}


# ═══════════════════════════════════════════════════════════════
#  Mistral API
# ═══════════════════════════════════════════════════════════════

def call_mistral(prompt, max_tokens=4000, temperature=0.85, max_retries=5,
                 system_prompt=None):
    """Call Mistral with rate-limit retry."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                wait = (attempt + 1) * 15
                print(f"  [rate-limit, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
            else:
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise
    raise Exception("Max retries exceeded")


# ═══════════════════════════════════════════════════════════════
#  Step 1: Build Story Prompt
# ═══════════════════════════════════════════════════════════════

LONG_STORY_EPISODE_PROMPT = """
Write a bedtime story episode for ages {age_group}.
Mood: {mood}

SETTING: {setting}, {time_of_day}, {weather}
MAIN CHARACTER: a {character_type}, personality: {character_personality}
NUMBER OF CHARACTERS: {character_count}
JOURNEY: {journey_type}

This is an EPISODE — a complete experience with a song
woven into the middle. The child looks forward to these
because there's always a song hidden inside.

=== CHARACTERS ===

Your story has {character_count} characters.

The main character always speaks. Tag their dialogue:
OWL: "I think the sound came from over there."

{character_instructions}

Even a solo character talks — to themselves, to the moon,
to the wind, to the child. They are never silent.

The narrator DESCRIBES. Characters LIVE. They sound
different because they ARE different.

For each character, output a tag at the top of the story:
[CHARACTER: Name, personality_word, voice_style]

voice_style is one of: confident, gentle, small, wise,
nervous, curious, stubborn, dreamy, brave, quiet

=== DIALOGUE FORMAT (CRITICAL) ===

ALL character dialogue MUST be tagged with the character
name in UPPERCASE. Never embed dialogue in narration prose.

WRONG: Pip pressed his ear against the trunk. "It's coming from in there!"
WRONG: "Did you hear that?" he asked.
WRONG: Hoot whispered to himself, "Listen to the mist."

RIGHT: PIP: "It's coming from in there!"
RIGHT: PIP: "Did you hear that?"
RIGHT: OWL: "Listen to the mist."

The narration describes what characters DO.
The tagged lines are what characters SAY.
Never mix them in the same line. If a character speaks,
that line MUST start with their NAME in uppercase,
followed by a colon, then the quoted dialogue. Nothing else.

=== REPEATED PHRASE ===

Create ONE phrase, under 6 words, that appears in all
three phases. The feeling of the phrase: {repeated_phrase_feeling}

Mark every instance with [PHRASE] tags.
Phase 1: spoken normally as part of the story
Phase 2: spoken once, quieter, like a memory
Phase 3: barely whispered, the last echo

The phrase must be UNIQUE. Not generic ("not yet" or
"almost there"). Specific to THIS story, THIS character,
THIS world. If the phrase could fit in a different story,
make it more specific.

=== STRUCTURE ===

[INTRO]
The narrator talks directly to the child. 2-3 sentences.
Warm, inviting, conspiratorial. Tonight we're going
somewhere. Don't mention the song — let it arrive.

[PHASE_1] — {phase_1_words} words
The journey begins. The character moves through the world.
Other characters are met (if {character_count} > 1).
Conversations happen. The world feels ALIVE.

Simple words only. Nothing a {age_group} year old wouldn't
understand or use themselves.

Ages {age_group} Phase 1 rules:
- Maximum 12 words per sentence
- Dialogue between characters (short exchanges,
  not monologues — 1-2 lines each, back and forth)
- The journey has forward momentum — the character
  is going somewhere, following something
- The repeated phrase appears naturally, spoken by
  the main character
- Include [PAUSE: 800] tags at moments of discovery
- Include 1-2 [BREATHE] tags at natural pauses where
  the world holds its breath (after a discovery, before
  moving forward). These create musical swell moments.
- End Phase 1 with the song transition

SONG TRANSITION (at the end of Phase 1):
Write 2-3 sentences where the story naturally transitions
into a musical moment. The character hears something.
The world starts humming. A melody arrives from somewhere.
Do not announce "now here's a song." Let it emerge.

Then output:
[SONG_SEED: one sentence describing what the song should
be about, using this story's specific world and character]

Then write 2-3 sentences for AFTER the song returns.
The narrator comes back SOFTER. The world has changed.
It's quieter now. The other characters (if any) are
getting drowsy. Mark this: [POST_SONG]

[PHASE_2] — {phase_2_words} words
The journey slows. Nothing new happens. The character
is still in the world but the writing shifts from
WHAT'S HAPPENING to WHAT IT FEELS LIKE.

Ages {age_group} Phase 2 rules:
- NO new characters introduced
- NO new plot events
- Dialogue STOPS by the middle of Phase 2
  (characters are getting sleepy — they stop talking)
- If there are other characters, they fall asleep
  DURING Phase 2. The child watches them sleep.
  "Owl tucked his head under his wing. Already dreaming."
- Sentences get longer — connected with "and"
  Not complex, just unhurried
- Sensory writing: air, light, ground, sounds far away,
  temperature, textures
- The repeated phrase appears once, quieter:
  [PHRASE]...[/PHRASE]
- Include [PAUSE: 1500] tags between sensory images
- Include 3-4 [BREATHE] tags at moments of stillness
  (after a character falls asleep, between sensory
  images, during the transition from awake to dreaming).
  These create musical swell moments where the bed
  rises and the world breathes.
- Maximum 15 words per sentence (they flow, not rush)

[PHASE_3] — {phase_3_words} words
Language dissolves. The main character sits or lies down.
Closes eyes. The world gets quiet.

Phase 3 is {phase_3_words} words. This is NOT short.
It is MANY short sentences, not FEW short sentences.

Sentences are short but there are LOTS of them.
60-80 sentences of 3-5 words each.

The repetition is the point. The same kinds of images
described again and again in slightly different words.
The child's brain receives wave after wave of
"warm, still, soft, quiet" with nothing to hold onto.

Start with 6-word sentences.
By the middle, 4-word sentences.
By the end, 2-3 word sentences.
The final lines are single words or silence.

This phase should feel LONG when read — like it goes
on and on and on in the gentlest way. That length
is what makes it work. The child cannot stay awake
through 80 tiny waves of stillness.

Ages {age_group} Phase 3 rules:
- NO characters speaking. They're all asleep.
- NO dialogue, NO questions, NO exclamations
- The writing mirrors what the child is physically
  feeling: warmth, stillness, heaviness, softness
- The repeated phrase one final time, barely there:
  [PHRASE]...[/PHRASE]
- Include [PAUSE: 3000] every 10-15 sentences
- Mark the final 3-4 lines: [WHISPER]...[/WHISPER]
- The story doesn't end. It just stops.
  No moral. No conclusion. No "the end."
  Just... stillness. Then nothing.
- End with one word. Or silence.
- Sleep invitation is ENVIRONMENTAL: the world goes
  quiet, not "close your eyes"

=== WORD COUNTS (CRITICAL — you MUST hit these) ===

Phase 1: {phase_1_words} words (MINIMUM {phase_1_min} words)
Phase 2: {phase_2_words} words (MINIMUM {phase_2_min} words)
Phase 3: {phase_3_words} words (MINIMUM {phase_3_min} words)
Total: {total_words} words (MINIMUM {total_min} words)

These are NOT suggestions. The story MUST be this long.
Count your words. If a phase is too short, add more
sensory detail, more dialogue exchanges, more moments.
Do NOT use markdown formatting. No bold (**), no italic (*),
no horizontal rules (---). Just plain text with the tags.

Available tags:
[PHRASE]...[/PHRASE], [PAUSE: ms], [WHISPER]...[/WHISPER],
[SONG_SEED: ...], [BREATHE], [CHARACTER: ...],
[INTRO], [/INTRO], [PHASE_1], [/PHASE_1], [POST_SONG],
[/POST_SONG], [PHASE_2], [/PHASE_2], [PHASE_3], [/PHASE_3]

[BREATHE] creates a 5-second musical swell moment where the
narration pauses and the background music swells. Use it at
natural resting points — never mid-sentence.

=== OUTPUT FORMAT ===

[CHARACTER: Name1, personality, voice_style]
[CHARACTER: Name2, personality, voice_style] (if applicable)

[INTRO]
...narrator text...
[/INTRO]

[PHASE_1]
...story with CHARACTER: "dialogue" tags...
...ending with song transition...
[SONG_SEED: description]
[/PHASE_1]

[POST_SONG]
...2-3 sentences, narrator returning softer...
[/POST_SONG]

[PHASE_2]
...sensory, slowing, characters falling asleep...
[/PHASE_2]

[PHASE_3]
...fragments, stillness, whispers...
[/PHASE_3]
"""

STORY_SONG_LYRICS_PROMPT = """
A child just heard this bedtime story:

"{phase_1_excerpt}"

The main character is {character_name}, a {character_type}.
The repeated phrase in the story is: "{repeated_phrase}"
The mood is: {mood}
The song seed from the story: "{song_seed}"

Write a short song that BELONGS inside this story.

The song should:
- Use words and images from the story the child just heard
- Mention {character_name} or what they're doing
- Include "{repeated_phrase}" in the chorus if it fits
- Feel like the story's world is singing to the child

SONG ARC: {song_arc}
The song starts one way and ends another. By the last line,
the song has already begun the descent into sleep.

4-8 lines total. Maximum 6 words per line. Maximum 7
syllables per line. Rhyming couplets. Simple words only.

This is the child's FAVOURITE part of the story. They
wait for it. It should feel special, warm, and slightly
magical. Not a silly song. Not a pure lullaby. A story-song
that belongs to THIS story and no other.

Output just the song lyrics. No tags. No titles.
"""


def build_long_story_prompt(params):
    """Build the full story generation prompt."""
    age = params["age_group"]
    wc = LONG_STORY_WORD_COUNTS[age]
    char_instructions = CHARACTER_INSTRUCTIONS[params["character_count"]]

    return LONG_STORY_EPISODE_PROMPT.format(
        age_group=age,
        mood=params["mood"],
        setting=params["setting"],
        character_type=params["character_type"],
        character_personality=params["character_personality"],
        character_count=params["character_count"],
        journey_type=params["journey_type"].replace("_", " "),
        time_of_day=params["time_of_day"].replace("_", " "),
        weather=params["weather"].replace("_", " "),
        repeated_phrase_feeling=params["repeated_phrase_feeling"],
        character_instructions=char_instructions,
        phase_1_words=f"{wc['phase_1'][0]}-{wc['phase_1'][1]}",
        phase_2_words=f"{wc['phase_2'][0]}-{wc['phase_2'][1]}",
        phase_3_words=f"{wc['phase_3'][0]}-{wc['phase_3'][1]}",
        total_words=f"{wc['total'][0]}-{wc['total'][1]}",
        phase_1_min=wc['phase_1'][0],
        phase_2_min=wc['phase_2'][0],
        phase_3_min=wc['phase_3'][0],
        total_min=wc['total'][0],
    )


# ═══════════════════════════════════════════════════════════════
#  Step 2: Parse Story
# ═══════════════════════════════════════════════════════════════

def clean_markdown(text):
    """Strip markdown formatting Mistral may add around tags."""
    # Remove **bold** around tags: **[TAG]** → [TAG]
    text = re.sub(r'\*\*\[([^\]]+)\]\*\*', r'[\1]', text)
    # Remove --- horizontal rules
    text = re.sub(r'\n---+\n', '\n', text)
    # Remove italic markers around text inside tags
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    return text


SECTION_TAGS = ["INTRO", "PHASE_1", "POST_SONG", "PHASE_2", "PHASE_3"]


def extract_section(text, tag):
    """Extract content between [TAG] and [/TAG], or [TAG] to next major section."""
    # Try exact match first
    pattern = rf'\[{tag}\](.*?)\[/{tag}\]'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: [TAG] to next major section tag or EOF
    # Only stop at major section boundaries, not inline tags like [/PHRASE]
    other_tags = [t for t in SECTION_TAGS if t != tag]
    boundary = "|".join(rf"\[/?{t}\]" for t in other_tags)
    pattern2 = rf'\[{tag}\](.*?)(?={boundary}|$)'
    match2 = re.search(pattern2, text, re.DOTALL)
    if match2:
        return match2.group(1).strip()
    return ""


def parse_long_story(raw_response):
    raw_response = clean_markdown(raw_response)
    """Parse the complete long story into components."""
    # Extract character definitions
    characters = []
    for match in re.finditer(r'\[CHARACTER:\s*(.+?),\s*(.+?),\s*(.+?)\]', raw_response):
        characters.append({
            "name": match.group(1).strip(),
            "personality": match.group(2).strip(),
            "voice_style": match.group(3).strip(),
        })

    # Extract sections
    intro = extract_section(raw_response, "INTRO")
    phase_1 = extract_section(raw_response, "PHASE_1")
    post_song = extract_section(raw_response, "POST_SONG")
    phase_2 = extract_section(raw_response, "PHASE_2")
    phase_3 = extract_section(raw_response, "PHASE_3")

    # Extract song seed
    song_seed_match = re.search(r'\[SONG_SEED:\s*(.+?)\]', raw_response)
    song_seed = song_seed_match.group(1) if song_seed_match else ""

    # Extract repeated phrase
    phrases = re.findall(r'\[PHRASE\](.+?)\[/PHRASE\]', raw_response)
    repeated_phrase = phrases[0].strip() if phrases else ""

    # Count words per phase (strip tags for accurate count)
    def clean_count(text):
        cleaned = re.sub(r'\[.*?\]', '', text)
        return len(cleaned.split())

    word_counts = {
        "intro": clean_count(intro),
        "phase_1": clean_count(phase_1),
        "post_song": clean_count(post_song),
        "phase_2": clean_count(phase_2),
        "phase_3": clean_count(phase_3),
    }
    word_counts["total"] = sum(word_counts.values())

    return {
        "raw": raw_response,
        "characters": characters,
        "intro": intro,
        "phase_1": phase_1,
        "post_song": post_song,
        "phase_2": phase_2,
        "phase_3": phase_3,
        "song_seed": song_seed,
        "repeated_phrase": repeated_phrase,
        "word_counts": word_counts,
    }


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Fix Untagged Dialogue
# ═══════════════════════════════════════════════════════════════

def fix_untagged_dialogue(text, character_names):
    """Convert prose-embedded dialogue to tagged format.

    Catches patterns like:
      "Did you hear that?" he asked.        → PIP: "Did you hear that?"
      Hoot whispered, "Listen to the mist." → HOOT: "Listen to the mist."
      "It's coming from in there!"          → (attributed by context)

    Leaves already-tagged lines (NAME: "...") untouched, including
    lines tagged with character types (OWL:, MOUSE:) rather than names.
    """
    lines = text.split('\n')
    fixed = []
    names_lower = {n.lower(): n for n in character_names}

    # Detect any TAG: "..." pattern as already-tagged dialogue
    # Matches both character names (HOOT:) and type labels (OWL:, PIP:)
    tagged_re = re.compile(r'^([A-Z][A-Za-z]+)\s*:\s*"')

    last_speaker = None  # Track last speaker for unattributed quotes

    for line in lines:
        stripped = line.strip()
        if not stripped:
            fixed.append(line)
            continue

        # Skip any already-tagged dialogue: LABEL: "..."
        tag_match = tagged_re.match(stripped)
        if tag_match:
            label = tag_match.group(1)
            # Track speaker — map label to character name if possible
            for n in character_names:
                if label.upper() == n.upper():
                    last_speaker = n
                    break
            else:
                # Label doesn't match a name (e.g. OWL vs Hoot) — keep last
                pass
            fixed.append(line)
            continue

        # Skip lines with no quotes at all
        if '"' not in stripped:
            fixed.append(line)
            continue

        # Find quoted speech
        match = re.search(r'"([^"]+)"', stripped)
        if not match:
            fixed.append(line)
            continue

        quote = match.group(1)
        context = stripped.lower()

        # Try to identify speaker from context
        speaker = None
        for name_lower, name_orig in names_lower.items():
            if name_lower in context:
                speaker = name_orig
                break

        # If no name found in context, use last speaker for
        # continuation lines like: "It's getting louder!"
        if not speaker and last_speaker:
            speaker = last_speaker

        if not speaker:
            # Can't determine speaker — leave as narration
            fixed.append(line)
            continue

        last_speaker = speaker

        # Split into narration before/after the quote
        before = stripped[:match.start()].strip()
        after = stripped[match.end():].strip()

        # Clean "he said", "she whispered" etc from after
        after = re.sub(
            r'^[,.]?\s*(?:he|she|it|they|the \w+)\s+'
            r'(?:said|asked|whispered|murmured|replied|called|shouted|added)',
            '', after, flags=re.IGNORECASE
        ).strip().strip('.,')

        # Clean "Name said/whispered" from before
        narration_before = re.sub(
            rf'{re.escape(speaker)}\s+'
            r'(?:said|asked|whispered|murmured|called|replied)\s*'
            r'(?:to\s+\w+\s*)?[,.]?\s*$',
            '', before, flags=re.IGNORECASE
        ).strip().strip('.,')

        # Output narration (if any) then tagged dialogue
        if narration_before:
            fixed.append(narration_before)
        fixed.append(f'{speaker.upper()}: "{quote}"')
        if after:
            fixed.append(after)

    return '\n'.join(fixed)


# ═══════════════════════════════════════════════════════════════
#  Step 3: Generate Song Lyrics
# ═══════════════════════════════════════════════════════════════

def generate_story_song_lyrics(parsed_story, params):
    """Generate song lyrics connected to this specific story."""
    phase_1_excerpt = parsed_story["phase_1"][:500]
    main_char = parsed_story["characters"][0]

    prompt = STORY_SONG_LYRICS_PROMPT.format(
        phase_1_excerpt=phase_1_excerpt,
        character_name=main_char["name"],
        character_type=params["character_type"],
        repeated_phrase=parsed_story["repeated_phrase"],
        mood=params["mood"],
        song_seed=parsed_story["song_seed"],
        song_arc=MOOD_SONG_ARC[params["mood"]],
    )

    return call_mistral(prompt, max_tokens=500, temperature=0.8)


def validate_song_relevance(song_lyrics, story_text, character_name):
    """Check that the song connects to the story."""
    COMMON = {'the', 'a', 'an', 'and', 'is', 'was', 'were', 'in',
              'on', 'to', 'of', 'it', 'that', 'this', 'my', 'your',
              'so', 'but', 'or', 'not', 'no', 'just', 'all'}

    story_words = set(story_text.lower().split()) - COMMON
    song_words = set(song_lyrics.lower().split()) - COMMON
    overlap = story_words & song_words
    has_character = character_name.lower() in song_lyrics.lower()

    if len(overlap) < 3 and not has_character:
        return False, f"Song shares only {len(overlap)} story words, no character name"
    return True, f"OK — {len(overlap)} shared words, character={'yes' if has_character else 'no'}"


# ═══════════════════════════════════════════════════════════════
#  Step 5: Voice Assignment
# ═══════════════════════════════════════════════════════════════

def assign_voices(characters, mood):
    """Assign distinct voices to narrator and each character.

    Ensures maximum contrast: if narrator is female, first character
    gets a male voice (and vice versa). Characters alternate genders
    for audible distinction.
    """
    narrator_voice = MOOD_NARRATOR_VOICE[mood]
    narrator_is_female = narrator_voice.startswith("female")

    # Separate into gendered pools for maximum contrast
    males = [v for v in ALL_VOICES if v.startswith("male")]
    females = [v for v in ALL_VOICES if v.startswith("female") and v != narrator_voice]

    # Alternate: if narrator is female, first char gets male, etc.
    if narrator_is_female:
        contrast_pool = males + females
    else:
        contrast_pool = females + males

    voice_map = {}
    for i, char in enumerate(characters):
        voice_map[char["name"]] = {
            "voice": contrast_pool[i % len(contrast_pool)],
            "style": char["voice_style"],
        }

    return narrator_voice, voice_map


# ═══════════════════════════════════════════════════════════════
#  Step 4: Song Audio (MiniMax on Replicate)
# ═══════════════════════════════════════════════════════════════

def generate_song_audio(lyrics, mood, setting, output_path):
    """Generate song audio via MiniMax Music 1.5 on Replicate."""
    import replicate

    config = MOOD_SONG_STYLE[mood]
    style = (
        f"Warm gentle children's story song, {config['instruments']}, "
        f"{config['tempo']} BPM, clear vocal singing slowly and warmly, "
        f"a song inside a bedtime story about {setting}, "
        f"intimate cozy every word clear not rushed"
    )

    # MiniMax lyrics limit is ~600 chars
    trimmed_lyrics = lyrics[:600]
    print(f"    Style: {style[:80]}...")
    print(f"    Lyrics: {len(lyrics)} chars -> {len(trimmed_lyrics)} chars")

    output = replicate.run(
        "minimax/music-1.5",
        input={"prompt": style, "lyrics": trimmed_lyrics},
    )

    if not output:
        raise RuntimeError("MiniMax returned no output")

    audio_url = str(output)
    print(f"    Downloading from Replicate...")
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    Path(output_path).write_bytes(resp.content)
    seg = AudioSegment.from_file(output_path)
    print(f"    Saved: {output_path} ({len(resp.content)/1024:.0f} KB, {len(seg)/1000:.1f}s)")
    return output_path


# ═══════════════════════════════════════════════════════════════
#  Step 6: TTS via Chatterbox on Modal
# ═══════════════════════════════════════════════════════════════

CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"


def generate_tts(text, voice, exaggeration=0.45, cfg_weight=0.5, speed=0.85,
                 is_phrase=False, timeout=60):
    """Generate TTS audio via Chatterbox Modal endpoint.

    timeout: Per-attempt timeout in seconds (default 60). Prevents hangs
    on short inputs that Chatterbox can't handle.
    """
    from urllib.parse import urlencode

    # Normalize ALL CAPS words
    text = re.sub(r'\b[A-Z]{3,}\b', lambda m: m.group(0).capitalize(), text)
    if is_phrase:
        text = f"... {text}"

    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"

    with httpx.Client() as http:
        for attempt in range(3):
            try:
                resp = http.get(url, timeout=float(timeout))
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_wav(io.BytesIO(resp.content))
            except httpx.TimeoutException:
                print(f"     TTS timeout (attempt {attempt+1}): '{text[:40]}...'")
                if attempt == 0 and not text.startswith("..."):
                    # Retry with ellipsis prefix on first timeout
                    text = f"... {text}"
                    params["text"] = text
                    url = f"{CHATTERBOX_URL}?{urlencode(params)}"
            except Exception as e:
                print(f"     TTS error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

    # Final fallback: return silence instead of crashing
    print(f"     TTS FAILED, using silence: '{text[:40]}...'")
    word_count = len(text.split())
    return AudioSegment.silent(duration=max(500, word_count * 300))


def trim_tts_silence(audio, silence_thresh=-50, min_silence_len=300):
    """Trim trailing silence from TTS audio."""
    from pydub.silence import detect_leading_silence
    end_trim = detect_leading_silence(audio.reverse(), silence_thresh, min_silence_len)
    return audio[:len(audio) - end_trim] if end_trim > 0 else audio


def parse_section_into_segments(text):
    """Parse story section into narrator, dialogue, phrase, whisper, pause segments."""
    segments = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Pause tags
        pause_match = re.search(r'\[PAUSE:\s*(\d+)\]', line)
        if pause_match:
            before = line[:pause_match.start()].strip()
            if before:
                segments.append(_parse_single_line(before))
            segments.append({"type": "pause", "ms": int(pause_match.group(1))})
            after = line[pause_match.end():].strip()
            if after:
                segments.append(_parse_single_line(after))
            continue

        # Breathe tags — bed swell moments
        if line.strip() == "[BREATHE]":
            segments.append({"type": "breathe"})
            continue

        # Whisper tags
        if "[WHISPER]" in line:
            content = line.replace("[WHISPER]", "").replace("[/WHISPER]", "").strip()
            if content:
                segments.append({"type": "whisper", "text": content})
            continue

        # Phrase tags
        if "[PHRASE]" in line:
            content = re.sub(r'\[/?PHRASE\]', '', line).strip()
            if content:
                segments.append({"type": "phrase", "text": content})
            continue

        segments.append(_parse_single_line(line))
    return segments


def _parse_single_line(line):
    """Determine if a line is dialogue or narration."""
    char_match = re.match(r'^([A-Z][A-Za-z\s]+?):\s*["\']?(.+?)["\']?\s*$', line)
    if char_match:
        return {
            "type": "dialogue",
            "character": char_match.group(1).strip(),
            "text": char_match.group(2).strip(),
        }
    return {"type": "narration", "text": line}


def _batch_short_lines(segments, min_words=4):
    """Batch adjacent short narration/whisper lines into groups.

    Never send fewer than min_words to Chatterbox — 1-3 word inputs
    either hang or produce garbled audio. The "... " prefix gives
    Chatterbox a breath before each fragment, producing natural pauses
    so batched fragments still SOUND like separate thoughts.
    """
    batched = []
    buffer_text = ""
    buffer_type = None  # "narration" or "whisper"

    def flush():
        nonlocal buffer_text, buffer_type
        if buffer_text:
            batched.append({"type": buffer_type, "text": buffer_text.strip()})
            buffer_text = ""
            buffer_type = None

    for seg in segments:
        if seg["type"] in ("narration", "whisper"):
            word_count = len(seg["text"].split())

            # If this line alone is long enough, flush buffer and send it
            if word_count >= min_words:
                flush()
                batched.append(seg)
            else:
                # Type changed (narration -> whisper), flush first
                if buffer_type and buffer_type != seg["type"]:
                    flush()

                buffer_type = seg["type"]
                # Join with ellipsis separator for natural breath
                buffer_text += "... " + seg["text"] + " "

                # Flush if buffer is long enough
                if len(buffer_text.split()) >= min_words * 2:
                    flush()

        elif seg["type"] == "pause":
            flush()
            batched.append(seg)

        else:
            # Other types (phrase, dialogue) — flush and pass through
            flush()
            batched.append(seg)

    flush()
    return batched


def _build_voice_lookup(voice_map, full_text):
    """Build case-insensitive voice lookup that handles label mismatches.

    The LLM may use 'OWL:' as dialogue tags instead of character name 'Hoot'.
    This scans the text for all LABEL: "..." patterns and maps unknown labels
    to characters by order of appearance.
    """
    lookup = {}
    for name, info in voice_map.items():
        lookup[name.lower()] = info
        lookup[name.upper()] = info
        lookup[name] = info

    # Find all dialogue labels actually used in the text
    labels_in_text = []
    for m in re.finditer(r'^([A-Z][A-Za-z]+)\s*:', full_text, re.MULTILINE):
        label = m.group(1)
        if label.lower() not in lookup and label not in labels_in_text:
            labels_in_text.append(label)

    # Map unknown labels to characters in order
    char_list = list(voice_map.values())
    for i, label in enumerate(labels_in_text):
        info = char_list[i % len(char_list)] if char_list else {}
        lookup[label] = info
        lookup[label.lower()] = info
        lookup[label.upper()] = info
        if info:
            print(f"     Mapped dialogue label '{label}' -> voice {info.get('voice', '?')}")

    return lookup


def generate_section_tts(section_text, phase_key, narrator_voice, voice_map):
    """Generate TTS for a story section with character voices."""
    phase_params = LONG_STORY_TTS[phase_key]
    segments = parse_section_into_segments(section_text)

    # Batch short narration/whisper fragments (critical for Phase 3)
    segments = _batch_short_lines(segments, min_words=4)
    print(f"     ({len(segments)} TTS segments after batching)")

    # Build flexible voice lookup (handles OWL vs Hoot mismatches)
    voice_lookup = _build_voice_lookup(voice_map, section_text)

    audio_chunks = []

    for i, seg in enumerate(segments):
        if seg["type"] == "narration":
            text = seg["text"]
            # Pad very short text to avoid Chatterbox issues
            if len(text.split()) <= 3:
                text = f"... {text}"
            audio = generate_tts(text, voice=narrator_voice, **phase_params)
            audio = trim_tts_silence(audio)
            audio_chunks.append(("audio", audio))

        elif seg["type"] == "dialogue":
            # Try exact match, then case-insensitive, then first char voice
            char_label = seg["character"]
            char_info = (voice_lookup.get(char_label)
                         or voice_lookup.get(char_label.lower())
                         or voice_lookup.get(char_label.upper()))
            if not char_info:
                # Last resort: use first character's voice (better than narrator)
                char_info = next(iter(voice_map.values()), {})
                print(f"     WARN: Unknown dialogue label '{char_label}', using fallback voice")
            char_voice = char_info.get("voice", narrator_voice)
            char_style = char_info.get("style", "gentle")
            mod = CHARACTER_VOICE_MODIFIERS.get(char_style, {})
            char_params = {
                "exaggeration": min(1.0, max(0.0, phase_params["exaggeration"] + mod.get("exag_offset", 0))),
                "speed": min(1.0, max(0.3, phase_params["speed"] + mod.get("speed_offset", 0))),
                "cfg_weight": phase_params["cfg_weight"],
            }
            text = seg["text"]
            if len(text.split()) <= 4:
                text = f"... {text}"
            audio = generate_tts(text, voice=char_voice, **char_params)
            audio = trim_tts_silence(audio)
            audio_chunks.append(("audio", audio))

        elif seg["type"] == "phrase":
            audio = generate_tts(seg["text"], voice=narrator_voice,
                                 **LONG_STORY_TTS["phrase"], is_phrase=True)
            audio = trim_tts_silence(audio)
            audio_chunks.append(("audio", audio))

        elif seg["type"] == "whisper":
            audio = generate_tts(seg["text"], voice=narrator_voice,
                                 **LONG_STORY_TTS["whisper"], is_phrase=True)
            audio = trim_tts_silence(audio)
            audio_chunks.append(("audio", audio))

        elif seg["type"] == "breathe":
            audio_chunks.append(("breathe", None))

        elif seg["type"] == "pause":
            audio_chunks.append(("pause", seg["ms"]))

        # Progress indicator every 5 segments
        if (i + 1) % 5 == 0:
            print(f"     ... {i+1}/{len(segments)} segments done")

    # Throwaway TTS call to prevent Chatterbox repeat bug
    try:
        generate_tts(".", voice=narrator_voice, exaggeration=0.1, speed=0.8)
    except Exception:
        pass

    return audio_chunks


# ═══════════════════════════════════════════════════════════════
#  Step 7: Assembly
# ═══════════════════════════════════════════════════════════════

def stitch_chunks(chunks, gap_ms=300):
    """Stitch audio chunks with gaps and pauses.

    Returns (audio, breathe_positions) where breathe_positions is a list
    of ms offsets where [BREATHE] tags occurred in the narration.
    """
    output = AudioSegment.empty()
    breathe_positions = []
    for chunk_type, content in chunks:
        if chunk_type == "audio":
            output += content
            output += AudioSegment.silent(duration=gap_ms)
        elif chunk_type == "pause":
            output += AudioSegment.silent(duration=content)
        elif chunk_type == "breathe":
            # Record position, insert 5s silence for the breathing moment
            breathe_positions.append(len(output))
            output += AudioSegment.silent(duration=5000)
    return output, breathe_positions


MUSIC_DIR = BASE_DIR / "audio" / "story_music"


def _trim_or_loop(audio, target_ms):
    """Trim or loop audio to match target duration."""
    if len(audio) >= target_ms:
        return audio[:target_ms]
    loops = (target_ms // len(audio)) + 1
    return (audio * loops)[:target_ms]


def _apply_breathe_swells(bed_segment, breathe_positions, base_db):
    """Apply +10dB swells at breathe positions in a bed segment.

    At each breathe position the bed ramps up +10dB over 1.5s,
    holds for 2s, then ramps back down over 1.5s (total 5s window).
    Uses 50ms chunk-based envelope processing.
    """
    if not breathe_positions:
        return bed_segment

    CHUNK_MS = 50
    chunks = [bed_segment[i:i + CHUNK_MS]
              for i in range(0, len(bed_segment), CHUNK_MS)]

    for pos_ms in breathe_positions:
        ramp_up_start = pos_ms
        ramp_up_end = pos_ms + 1500
        hold_end = pos_ms + 3500
        ramp_down_end = pos_ms + 5000

        for i, chunk_start in enumerate(range(0, len(bed_segment), CHUNK_MS)):
            chunk_end = chunk_start + CHUNK_MS
            if chunk_end < ramp_up_start or chunk_start > ramp_down_end:
                continue

            if chunk_start < ramp_up_end:
                # Ramp up phase: 0 → +10dB
                progress = (chunk_start - ramp_up_start) / 1500
                progress = max(0, min(1, progress))
                boost = progress * 10
            elif chunk_start < hold_end:
                # Hold phase: +10dB
                boost = 10
            else:
                # Ramp down phase: +10dB → 0
                progress = (chunk_start - hold_end) / 1500
                progress = max(0, min(1, progress))
                boost = (1 - progress) * 10

            if i < len(chunks):
                chunks[i] = chunks[i] + boost

    result = AudioSegment.empty()
    for chunk in chunks:
        result += chunk
    return result


def assemble_long_story_episode(section_audios, song_audio_path, mood):
    """
    Assemble complete long story episode with continuous music bed.

    Timeline:
    [music intro]
    [2s silence]
    [Part A: intro + phase_1 narration + bed at -20dB]
    [bed fades out 2s → song fades in]
    [THE SONG — standalone, no bed]
    [song fades out → bed fades in 2s]
    [Part B: post_song + phase_2 narration + bed at -14dB]
    [Part C: phase_3 narration + bed at -10dB]
    [bed alone 30s fading to silence — this IS the outro]

    Bed is CONTINUOUS from first narrator word to 30s after last word.
    Silent only during the song, with crossfade transitions.
    [BREATHE] tags create +10dB swell moments in the bed.
    """
    # Load mood music
    intro_music = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    bed_raw = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))

    output = AudioSegment.empty()

    # ── Music intro ──
    output += intro_music
    output += AudioSegment.silent(duration=2000)

    # ═══ PART A: intro + phase_1 with bed at -20dB ═══
    intro_audio, intro_breathes = stitch_chunks(section_audios["intro"], gap_ms=400)
    p1_audio, p1_breathes = stitch_chunks(section_audios["phase_1"], gap_ms=300)

    # Combine intro + 1s gap + phase_1 into one voice track
    gap_between = AudioSegment.silent(duration=1000)
    part_a_voice = intro_audio + gap_between + p1_audio

    # Offset p1 breathe positions by intro + gap length
    p1_offset = len(intro_audio) + len(gap_between)
    all_a_breathes = intro_breathes + [pos + p1_offset for pos in p1_breathes]

    # Build bed for Part A (same length as voice)
    part_a_bed = _trim_or_loop(bed_raw, len(part_a_voice))
    part_a_bed = part_a_bed - 20  # -20dB base
    part_a_bed = _apply_breathe_swells(part_a_bed, all_a_breathes, -20)

    # Fade out last 2s of bed for transition into song
    part_a_bed = part_a_bed.fade_out(2000)

    part_a_mixed = part_a_voice.overlay(part_a_bed)
    output += part_a_mixed

    # ═══ SONG with crossfade transitions ═══
    song = AudioSegment.from_file(song_audio_path)

    # 500ms silence before song, then song with 2s fade-in at start
    # and 2s fade-out at end, then 500ms silence after
    output += AudioSegment.silent(duration=500)
    song_with_fades = song.fade_in(2000).fade_out(2000)
    output += song_with_fades
    output += AudioSegment.silent(duration=500)

    # ═══ PART B: post_song + phase_2 with bed at -14dB ═══
    post_audio, post_breathes = stitch_chunks(section_audios["post_song"], gap_ms=500)
    p2_audio, p2_breathes = stitch_chunks(section_audios["phase_2"], gap_ms=500)

    gap_b = AudioSegment.silent(duration=1000)
    part_b_voice = post_audio + gap_b + p2_audio

    p2_offset = len(post_audio) + len(gap_b)
    all_b_breathes = post_breathes + [pos + p2_offset for pos in p2_breathes]

    part_b_bed = _trim_or_loop(bed_raw, len(part_b_voice))
    part_b_bed = part_b_bed - 14  # -14dB: more present as voice slows
    part_b_bed = _apply_breathe_swells(part_b_bed, all_b_breathes, -14)

    # Fade in first 2s of bed (coming back after song)
    part_b_bed = part_b_bed.fade_in(2000)

    part_b_mixed = part_b_voice.overlay(part_b_bed)
    output += part_b_mixed

    # ═══ PART C: phase_3 with bed at -10dB + 30s tail fade ═══
    p3_audio, p3_breathes = stitch_chunks(section_audios["phase_3"], gap_ms=800)

    # Bed covers voice + 30s tail
    p3_bed = _trim_or_loop(bed_raw, len(p3_audio) + 30000)
    p3_bed = p3_bed - 10  # -10dB: bed becomes primary sound
    p3_bed = _apply_breathe_swells(p3_bed, p3_breathes, -10)

    # Voice portion overlaid with bed
    p3_mixed = p3_audio.overlay(p3_bed[:len(p3_audio)])
    output += p3_mixed

    # Bed alone for 30s, fading to silence — this IS the outro.
    # No outro music. The child is asleep.
    bed_tail = p3_bed[len(p3_audio):len(p3_audio) + 30000]
    bed_tail = bed_tail.fade_out(15000)
    output += bed_tail

    return output


# ═══════════════════════════════════════════════════════════════
#  Step 8: Cover (FLUX via Together AI)
# ═══════════════════════════════════════════════════════════════

def generate_cover(params, output_path):
    """Generate cover image via Together AI FLUX.1-schnell."""
    api_key = os.getenv("TOGETHER_API_KEY", "")
    if not api_key:
        print("    TOGETHER_API_KEY not set, skipping cover")
        return None

    prompt = (
        f"Children's bedtime illustration, watercolor style, "
        f"a {params['character_type']} in a {params['setting']}, "
        f"{params['time_of_day']}, {params['weather']}, "
        f"warm colors, dreamy atmosphere, soft lighting, "
        f"gentle and peaceful, bedtime feeling, no text, no words"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell",
        "prompt": prompt[:1500],
        "width": 512,
        "height": 512,
        "steps": 4,
        "n": 1,
        "response_format": "b64_json",
    }

    for attempt in range(3):
        try:
            resp = httpx.post(
                "https://api.together.xyz/v1/images/generations",
                headers=headers, json=payload, timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                b64_data = data["data"][0]["b64_json"]
                image_bytes = base64.b64decode(b64_data)
                if len(image_bytes) > 1000:
                    # Save as WebP
                    from PIL import Image
                    img = Image.open(io.BytesIO(image_bytes))
                    img.save(output_path, "WEBP", quality=80)
                    print(f"    Saved cover: {output_path}")
                    return output_path
            elif resp.status_code == 429:
                print(f"    Together AI rate limited, waiting 15s...")
                time.sleep(15)
                continue
            else:
                print(f"    Together AI error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"    Cover attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(5)

    print("    Cover generation failed after 3 attempts")
    return None


# ═══════════════════════════════════════════════════════════════
#  Validation
# ═══════════════════════════════════════════════════════════════

def validate_story(parsed, params):
    """Validate the parsed story meets spec requirements."""
    issues = []
    age = params["age_group"]
    wc_targets = LONG_STORY_WORD_COUNTS[age]

    # Required sections
    if not parsed["characters"]:
        issues.append("ERROR: No [CHARACTER:] tags found")
    if not parsed["intro"]:
        issues.append("ERROR: No [INTRO] section")
    if not parsed["phase_1"]:
        issues.append("ERROR: No [PHASE_1] section")
    if not parsed["phase_2"]:
        issues.append("ERROR: No [PHASE_2] section")
    if not parsed["phase_3"]:
        issues.append("ERROR: No [PHASE_3] section")
    if not parsed["song_seed"]:
        issues.append("ERROR: No [SONG_SEED:] tag")
    if not parsed["repeated_phrase"]:
        issues.append("ERROR: No [PHRASE] tags found")

    # Word count checks
    wc = parsed["word_counts"]
    for phase in ["phase_1", "phase_2", "phase_3"]:
        lo, hi = wc_targets[phase]
        actual = wc[phase]
        if actual < lo * 0.7:
            issues.append(f"WARN: {phase} too short ({actual} words, target {lo}-{hi})")
        elif actual > hi * 1.3:
            issues.append(f"WARN: {phase} too long ({actual} words, target {lo}-{hi})")

    total_lo, total_hi = wc_targets["total"]
    if wc["total"] < total_lo * 0.7:
        issues.append(f"WARN: Total too short ({wc['total']} words, target {total_lo}-{total_hi})")
    elif wc["total"] > total_hi * 1.3:
        issues.append(f"WARN: Total too long ({wc['total']} words, target {total_lo}-{total_hi})")

    # Repeated phrase count
    phrase_count = len(re.findall(r'\[PHRASE\]', parsed["raw"]))
    if phrase_count < 3:
        issues.append(f"WARN: Repeated phrase appears {phrase_count} times (expected 3)")

    # Phase 3 whisper check
    whisper_count = len(re.findall(r'\[WHISPER\]', parsed["raw"]))
    if whisper_count == 0:
        issues.append("WARN: No [WHISPER] tags in Phase 3")

    # Pause checks
    pause_count = len(re.findall(r'\[PAUSE:', parsed["raw"]))
    if pause_count < 4:
        issues.append(f"WARN: Only {pause_count} [PAUSE:] tags (expected 4+)")

    return issues


# ═══════════════════════════════════════════════════════════════
#  Publish: integrate episode into content.json
# ═══════════════════════════════════════════════════════════════

SETTINGS = ["forest", "meadow", "ocean", "cave", "garden", "mountain", "riverbank", "desert_oasis"]
CHARACTER_TYPES = ["owl", "rabbit", "bear", "fox", "deer", "mouse", "hedgehog", "firefly", "turtle"]
PERSONALITIES = ["wise", "curious", "gentle", "brave", "dreamy", "playful", "calm", "shy"]
JOURNEY_TYPES = ["following_a_sound", "finding_a_light", "chasing_a_shadow", "seeking_a_friend",
                 "discovering_a_path", "returning_home", "collecting_stars", "waiting_for_dawn"]
TIMES_OF_DAY = ["dusk", "evening", "late_night", "twilight"]
WEATHER_OPTIONS = ["light_mist", "clear_starry", "gentle_rain", "soft_snow", "warm_breeze"]
PHRASE_FEELINGS = ["listen", "gentle", "safe", "still", "warm", "soft"]


def randomize_params(mood="curious", age_group="6-8"):
    """Generate random diverse episode parameters."""
    return {
        "mood": mood,
        "age_group": age_group,
        "setting": random.choice(SETTINGS),
        "character_type": random.choice(CHARACTER_TYPES),
        "character_personality": random.choice(PERSONALITIES),
        "character_count": random.choice([1, 2, 2, 2, 3]),  # 2 is most common
        "journey_type": random.choice(JOURNEY_TYPES),
        "time_of_day": random.choice(TIMES_OF_DAY),
        "weather": random.choice(WEATHER_OPTIONS),
        "repeated_phrase_feeling": random.choice(PHRASE_FEELINGS),
        "song_position": "late",
    }


def publish_episode(output_dir, params, metadata, duration_seconds):
    """Add episode to content.json and copy files to the right locations.

    Returns the story ID if successful.
    """
    import uuid
    from datetime import datetime

    story_id = "gen-" + uuid.uuid4().hex[:12]
    short_id = story_id[4:12]

    episode_path = os.path.join(output_dir, "episode.mp3")
    cover_path = os.path.join(output_dir, "cover.webp")

    if not os.path.exists(episode_path):
        print(f"  ERROR: episode.mp3 not found in {output_dir}")
        return None

    # Copy audio to backend audio/pre-gen/
    audio_dest = BASE_DIR / "audio" / "pre-gen" / f"{short_id}_mixed.mp3"
    shutil.copy2(episode_path, audio_dest)
    print(f"  Copied audio: {audio_dest}")

    # Copy audio to web repo too
    web_audio = BASE_DIR.parent / "dreamweaver-web" / "public" / "audio" / "pre-gen" / f"{short_id}_mixed.mp3"
    if web_audio.parent.exists():
        shutil.copy2(episode_path, web_audio)
        print(f"  Copied audio: {web_audio}")

    # Copy cover if exists
    cover_field = ""
    if os.path.exists(cover_path):
        web_cover = BASE_DIR.parent / "dreamweaver-web" / "public" / "covers" / f"{story_id}.webp"
        if web_cover.parent.exists():
            shutil.copy2(cover_path, web_cover)
            print(f"  Copied cover: {web_cover}")
        cover_field = f"/covers/{story_id}.webp"

    # Build clean text (no tags)
    sections = metadata.get("sections", {})
    raw_parts = [sections.get(s, "") for s in ["intro", "phase_1", "post_song", "phase_2", "phase_3"]]
    full_raw = "\n\n".join(p for p in raw_parts if p)
    clean_text = re.sub(r'\[/?(?:INTRO|PHASE_\d|POST_SONG|PHRASE|PAUSE[^]]*|SONG_SEED[^]]*|WHISPER|BREATHE|CHARACTER[^]]*)\]', '', full_raw)
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

    # Build character card
    characters = metadata.get("characters", [])
    main_char = characters[0] if characters else {"name": "Unknown", "personality": "", "voice_style": ""}
    char_card = {
        "name": main_char["name"],
        "identity": f"A {params.get('character_personality', '')} {params.get('character_type', '')} who explores the {params.get('setting', '')}",
        "special": f"Guides the listener through a {params.get('journey_type', '').replace('_', ' ')} adventure",
        "personality_tags": [main_char.get("personality", "").capitalize(), main_char.get("voice_style", "").capitalize()],
    }

    now = datetime.utcnow().isoformat()

    # Build title from characters and setting
    char_names = [c["name"] for c in characters]
    title_name = " and ".join(char_names[:2]) if len(char_names) > 1 else char_names[0] if char_names else "Unknown"
    journey_word = params.get("journey_type", "adventure").replace("_", " ").split("_")[-1]

    entry = {
        "id": story_id,
        "type": "long_story",
        "lang": "en",
        "title": metadata.get("title", f"{title_name}'s {params.get('setting', 'forest').capitalize()} {journey_word.capitalize()}"),
        "description": metadata.get("description", f"A bedtime story episode featuring {title_name} in the {params.get('setting', 'forest')}."),
        "text": clean_text,
        "annotated_text": full_raw,
        "lullaby_lyrics": metadata.get("song_lyrics", ""),
        "target_age": int(params.get("age_group", "6-8").split("-")[0]) + 1,
        "age_min": int(params.get("age_group", "6-8").split("-")[0]),
        "age_max": int(params.get("age_group", "6-8").split("-")[1]),
        "age_group": params.get("age_group", "6-8"),
        "length": "LONG",
        "word_count": metadata.get("word_counts", {}).get("total", 0),
        "duration_seconds": int(duration_seconds),
        "duration": int(duration_seconds / 60),
        "categories": ["Bedtime", params.get("setting", "Forest").capitalize()],
        "theme": "bedtime",
        "morals": [],
        "cover": cover_field,
        "musicProfile": None,
        "musicParams": None,
        "musicalBrief": None,
        "music_type": "baked",
        "audio_variants": [
            {
                "voice": "mixed",
                "url": f"/audio/pre-gen/{short_id}_mixed.mp3",
                "duration_seconds": round(duration_seconds, 2),
                "provider": "chatterbox",
            }
        ],
        "author_id": "system",
        "is_generated": True,
        "generation_quality": "experimental_v2",
        "has_baked_music": True,
        "experimental_v2": True,
        "episode_format": "v2",
        "lead_character_type": params.get("character_type", ""),
        "characters": characters,
        "repeated_phrase": metadata.get("repeated_phrase", ""),
        "voice_map": metadata.get("voice_map", {}),
        "narrator_voice": metadata.get("narrator_voice", ""),
        "mood": params.get("mood", "curious"),
        "created_at": now,
        "updated_at": now,
        "view_count": 0,
        "like_count": 0,
        "save_count": 0,
        "character": char_card,
        "is_saved": False,
        "story_type": "nature",
        "language_level": "intermediate",
    }

    # Merge into content.json
    content_path = BASE_DIR / "seed_output" / "content.json"
    with open(content_path) as f:
        content = json.load(f)
    content.append(entry)
    with open(content_path, "w") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    print(f"  Published: {story_id} → content.json ({len(content)} total)")
    return story_id


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate experimental long story episode")
    parser.add_argument("--mood", default="curious", choices=list(MOOD_SONG_ARC.keys()))
    parser.add_argument("--age-group", default="6-8", choices=["2-5", "6-8", "9-12"])
    parser.add_argument("--setting", default="forest")
    parser.add_argument("--character-type", default="owl")
    parser.add_argument("--character-personality", default="wise")
    parser.add_argument("--character-count", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--journey-type", default="following_a_sound")
    parser.add_argument("--time-of-day", default="dusk")
    parser.add_argument("--weather", default="light_mist")
    parser.add_argument("--repeated-phrase-feeling", default="listen")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print prompt only")
    parser.add_argument("--text-only", action="store_true", help="Skip audio/cover generation")
    parser.add_argument("--from-metadata", action="store_true",
                        help="Resume from saved metadata.json (skip text generation)")
    parser.add_argument("--publish", action="store_true",
                        help="Add finished episode to content.json and copy files")
    parser.add_argument("--randomize", action="store_true",
                        help="Randomize setting/character/journey for diversity (pipeline mode)")
    args = parser.parse_args()

    if args.randomize:
        params = randomize_params(mood=args.mood, age_group=args.age_group)
        print(f"  Randomized: {params['character_type']} in {params['setting']}, "
              f"{params['journey_type']}, {params['time_of_day']}, {params['weather']}")
    else:
        params = {
            "mood": args.mood,
            "age_group": args.age_group,
            "setting": args.setting,
            "character_type": args.character_type,
            "character_personality": args.character_personality,
            "character_count": args.character_count,
            "journey_type": args.journey_type,
            "time_of_day": args.time_of_day,
            "weather": args.weather,
            "repeated_phrase_feeling": args.repeated_phrase_feeling,
            "song_position": "late",
        }

    output_dir = args.output_dir or str(BASE_DIR.parent / "output" / "long_story_test")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 50)
    print("EXPERIMENTAL LONG STORY EPISODE GENERATOR")
    print("=" * 50)

    # ══════════════════════════════════════════════════════════
    #  TEXT GENERATION (Steps 1-3)
    # ══════════════════════════════════════════════════════════

    if args.from_metadata:
        # Resume from saved metadata
        meta_path = os.path.join(output_dir, "metadata.json")
        print(f"Loading from {meta_path}...")
        with open(meta_path) as f:
            metadata = json.load(f)
        parsed = {
            "characters": metadata["characters"],
            "intro": metadata["sections"]["intro"],
            "phase_1": metadata["sections"]["phase_1"],
            "post_song": metadata["sections"]["post_song"],
            "phase_2": metadata["sections"]["phase_2"],
            "phase_3": metadata["sections"]["phase_3"],
            "song_seed": metadata["song_seed"],
            "repeated_phrase": metadata["repeated_phrase"],
            "word_counts": metadata["word_counts"],
        }
        song_lyrics = metadata["song_lyrics"]
        narrator_voice = metadata["narrator_voice"]
        voice_map = {}
        for char in parsed["characters"]:
            name = char["name"]
            voice_map[name] = {
                "voice": metadata["voice_map"].get(name, "female_1"),
                "style": char["voice_style"],
            }
        params = {k: metadata.get(k, params.get(k)) for k in params}
        print(f"  Characters: {[c['name'] for c in parsed['characters']]}")
        print(f"  Word counts: {parsed['word_counts']}")
        issues = []
    else:
        print(f"  Mood: {params['mood']}")
        print(f"  Age: {params['age_group']}")
        print(f"  Setting: {params['setting']}, {params['time_of_day']}, {params['weather']}")
        print(f"  Character: {params['character_type']} ({params['character_personality']})")
        print(f"  Characters: {params['character_count']}")
        print(f"  Journey: {params['journey_type']}")
        print()

        prompt = build_long_story_prompt(params)

        if args.dry_run:
            print("--- PROMPT ---")
            print(prompt)
            print("--- END ---")
            return

        story_system = (
            "You are a world-class children's bedtime story writer. "
            "You write LONG, detailed, immersive stories. "
            "You ALWAYS hit the word count targets given in the prompt — "
            "never shorter. If the prompt says 250-400 words for a phase, "
            "you write at least 250 words for that phase. "
            "You use plain text only — NO markdown bold (**), NO italic (*), "
            "NO horizontal rules (---). Only use the tags specified in the prompt."
        )
        print("1. Generating story text via Mistral...")
        raw_response = call_mistral(prompt, max_tokens=6000, temperature=0.85,
                                    system_prompt=story_system)

        raw_path = os.path.join(output_dir, "story_raw.txt")
        with open(raw_path, "w") as f:
            f.write(raw_response)
        print(f"   Saved: {raw_path}")

        # Parse
        print("2. Parsing story...")
        parsed = parse_long_story(raw_response)

        # Fix untagged dialogue (LLM often mixes tagged and prose styles)
        if parsed["characters"]:
            char_names = [c["name"] for c in parsed["characters"]]
            for section in ["intro", "phase_1", "post_song", "phase_2", "phase_3"]:
                if parsed[section]:
                    parsed[section] = fix_untagged_dialogue(parsed[section], char_names)

        print(f"   Characters: {[c['name'] for c in parsed['characters']]}")
        print(f"   Repeated phrase: \"{parsed['repeated_phrase']}\"")
        print(f"   Song seed: \"{parsed['song_seed']}\"")
        print(f"   Word counts: {parsed['word_counts']}")

        # Validate
        print("3. Validating...")
        issues = validate_story(parsed, params)
        if issues:
            for issue in issues:
                print(f"   {issue}")
        else:
            print("   All checks passed!")

        has_errors = any(i.startswith("ERROR:") for i in issues)
        if has_errors:
            print("\n   FATAL: Story has missing sections. Check raw output.")
            sys.exit(1)

        # Generate song lyrics
        print("4. Generating song lyrics via Mistral...")
        time.sleep(31)  # rate limit: 2 req/min
        song_lyrics = generate_story_song_lyrics(parsed, params)
        print(f"   Song lyrics:\n{song_lyrics}")

        main_char = parsed["characters"][0]
        relevant, reason = validate_song_relevance(
            song_lyrics, parsed["phase_1"], main_char["name"]
        )
        print(f"   Song relevance: {reason}")

        if not relevant:
            print("   Regenerating song...")
            time.sleep(31)
            song_lyrics = generate_story_song_lyrics(parsed, params)

        song_path = os.path.join(output_dir, "song_lyrics.txt")
        with open(song_path, "w") as f:
            f.write(song_lyrics)

        # Assign voices
        print("5. Assigning voices...")
        narrator_voice, voice_map = assign_voices(parsed["characters"], params["mood"])
        print(f"   Narrator: {narrator_voice}")
        for name, info in voice_map.items():
            print(f"   {name}: {info['voice']} ({info['style']})")

        # Save metadata
        print("6. Saving metadata...")
        metadata = {
            "content_type": "long_story",
            "experimental": True,
            "age_group": params["age_group"],
            "mood": params["mood"],
            "setting": params["setting"],
            "character_type": params["character_type"],
            "character_personality": params["character_personality"],
            "character_count": params["character_count"],
            "journey_type": params["journey_type"],
            "time_of_day": params["time_of_day"],
            "weather": params["weather"],
            "characters": parsed["characters"],
            "repeated_phrase": parsed["repeated_phrase"],
            "song_seed": parsed["song_seed"],
            "song_lyrics": song_lyrics,
            "word_counts": parsed["word_counts"],
            "narrator_voice": narrator_voice,
            "voice_map": {k: v["voice"] for k, v in voice_map.items()},
            "tts_params": LONG_STORY_TTS,
            "song_style": MOOD_SONG_STYLE[params["mood"]],
            "sections": {
                "intro": parsed["intro"],
                "phase_1": parsed["phase_1"],
                "post_song": parsed["post_song"],
                "phase_2": parsed["phase_2"],
                "phase_3": parsed["phase_3"],
            },
        }
        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"   Saved: {meta_path}")

    if args.text_only:
        print()
        print("=" * 50)
        print("DONE — Text generation complete (--text-only)")
        print("=" * 50)
        print(f"  Output: {output_dir}")
        print(f"  Resume with: python3 scripts/generate_long_story_episode.py --from-metadata")
        return

    # ══════════════════════════════════════════════════════════
    #  AUDIO GENERATION (Steps 4-8)
    # ══════════════════════════════════════════════════════════

    # Step 4: Song audio
    song_audio_path = os.path.join(output_dir, "song.mp3")
    if os.path.exists(song_audio_path):
        print(f"7. Song audio already exists: {song_audio_path}")
    else:
        print("7. Generating song audio via MiniMax on Replicate...")
        try:
            generate_song_audio(song_lyrics, params["mood"], params["setting"],
                                song_audio_path)
        except Exception as e:
            print(f"   Song audio FAILED: {e}")
            print("   Continuing without song...")
            song_audio_path = None

    # Step 6: TTS for all sections
    print("8. Generating TTS via Chatterbox...")
    section_audios = {}
    for section, phase_key in [
        ("intro", "intro"),
        ("phase_1", "phase_1"),
        ("post_song", "post_song"),
        ("phase_2", "phase_2"),
        ("phase_3", "phase_3"),
    ]:
        section_path = os.path.join(output_dir, f"{section}.wav")

        # Skip if wav already exists (resume support)
        if os.path.exists(section_path):
            existing = AudioSegment.from_wav(section_path)
            print(f"   TTS: {section} — already exists ({len(existing)/1000:.1f}s)")
            section_audios[section] = [("audio", existing)]
            continue

        text = parsed[section]
        if not text:
            section_audios[section] = []
            continue
        print(f"   TTS: {section} ({parsed['word_counts'].get(section, '?')} words)...")
        section_audios[section] = generate_section_tts(
            text, phase_key, narrator_voice, voice_map
        )
        # Save individual section audio for debugging/resume
        section_audio, _ = stitch_chunks(section_audios[section], gap_ms=300)
        section_audio.export(section_path, format="wav")
        print(f"   Saved: {section_path} ({len(section_audio)/1000:.1f}s)")

    # Step 7: Assembly
    print("9. Assembling episode...")
    if song_audio_path and os.path.exists(song_audio_path):
        final_audio = assemble_long_story_episode(section_audios, song_audio_path, params["mood"])
    else:
        # Assemble without song
        print("   (No song audio — assembling without song)")
        output_audio = AudioSegment.empty()
        for section in ["intro", "phase_1", "post_song", "phase_2", "phase_3"]:
            gap = {"intro": 400, "phase_1": 300, "post_song": 500,
                   "phase_2": 500, "phase_3": 800}[section]
            sec_audio, _ = stitch_chunks(section_audios[section], gap_ms=gap)
            output_audio += sec_audio
            output_audio += AudioSegment.silent(duration=1000)
        output_audio += AudioSegment.silent(duration=15000).fade_out(10000)
        final_audio = output_audio

    episode_path = os.path.join(output_dir, "episode.mp3")
    final_audio.export(episode_path, format="mp3", bitrate="192k")
    duration_sec = len(final_audio) / 1000
    print(f"   Saved: {episode_path}")
    print(f"   Duration: {duration_sec:.0f}s ({duration_sec/60:.1f} minutes)")

    # Step 8: Cover
    cover_path = os.path.join(output_dir, "cover.webp")
    if os.path.exists(cover_path):
        print(f"10. Cover already exists: {cover_path}")
    else:
        print("10. Generating cover via FLUX...")
        generate_cover(params, cover_path)

    # ── Final summary ──
    print()
    print("=" * 50)
    print("EPISODE COMPLETE")
    print("=" * 50)
    print(f"  Output dir:      {output_dir}")
    print(f"  Episode:         episode.mp3 ({duration_sec/60:.1f} min)")
    print(f"  Characters:      {[c['name'] for c in parsed['characters']]}")
    print(f"  Repeated phrase: \"{parsed['repeated_phrase']}\"")
    print(f"  Narrator:        {narrator_voice}")
    if song_audio_path:
        print(f"  Song:            song.mp3")
    if os.path.exists(cover_path):
        print(f"  Cover:           cover.webp")
    if issues:
        print(f"  Warnings:        {len(issues)}")

    # Publish to content.json if requested
    if args.publish and os.path.exists(os.path.join(output_dir, "episode.mp3")):
        print()
        print("11. Publishing to content.json...")
        story_id = publish_episode(output_dir, params, metadata, duration_sec)
        if story_id:
            # Write story_id to stdout for pipeline to capture
            print(f"  PUBLISHED_ID={story_id}")


if __name__ == "__main__":
    main()
