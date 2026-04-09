#!/usr/bin/env python3
"""Generate 3 test funny short episodes with redesigned audio experience.

Calm comedy: comedy beds, character-distinct TTS, timing-based humor.

Execution order:
    1. python3 scripts/generate_funny_shorts_v2.py --sfx          # 14 SFX files (one-time)
    2. python3 scripts/generate_funny_shorts_v2.py --intro-outro   # 5 intro/outro candidates
    3. python3 scripts/generate_funny_shorts_v2.py --episodes       # 3 test episodes
    4. python3 scripts/generate_funny_shorts_v2.py --all            # Everything in sequence
"""

import argparse
import io
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load .env
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

import httpx
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# ── Directories ───────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BACKEND_DIR / "output" / "funny_shorts_v2"
SFX_DIR = OUTPUT_DIR / "sfx"
INTRO_DIR = OUTPUT_DIR / "intro_candidates"
EPISODES_DIR = OUTPUT_DIR / "episodes"

MODAL_TTS_URL = os.getenv(
    "MODAL_TTS_URL",
    "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run",
)
FAL_KEY = os.getenv("FAL_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")


# ── Character Voice Profiles (Redesigned — calm comedy) ──────────

CHARACTER_VOICES = {
    "boomy": {
        # Confident, sure of himself. Not louder — FASTER. Misplaced confidence.
        "voice_id": "comedic_villain",
        "exaggeration": 0.55,
        "speed": 1.05,
        "cfg_weight": 0.55,
        "catchphrase": "That was SUPPOSED to happen.",
    },
    "pip": {
        # Quick, slightly breathless, exasperated. Fastest character.
        "voice_id": "high_pitch_cartoon",
        "exaggeration": 0.65,
        "speed": 1.18,
        "cfg_weight": 0.50,
        "catchphrase": "I said this would happen. I SAID.",
    },
    "shadow": {
        # THE ONLY slow character. Measured contrast IS his comedy.
        "voice_id": "mysterious_witch",
        "exaggeration": 0.45,
        "speed": 0.95,
        "cfg_weight": 0.60,
        "catchphrase": "According to my calculations... hmm.",
    },
    "sunny": {
        # Bright, warm, snappy optimism. Peppy and quick.
        "voice_id": "young_sweet",
        "exaggeration": 0.60,
        "speed": 1.10,
        "cfg_weight": 0.48,
        "catchphrase": "This is fine! This is completely fine.",
    },
    "melody": {
        # Narrator/host. Clear, warm, conspiratorial. Comedy pace.
        "voice_id": "musical_original",
        "exaggeration": 0.50,
        "speed": 1.05,
        "cfg_weight": 0.55,
        "catchphrase": "And that's when things got... interesting.",
    },
}

# When the narrator loses composure (after [BREAK] tag)
MELODY_BREAKING = {
    "voice_id": "musical_original",
    "exaggeration": 0.65,
    "speed": 0.95,
    "cfg_weight": 0.45,
}


# ── SFX Library ──────────────────────────────────────────────────

COMEDY_SFX = {
    # Gentle impacts
    "soft_splat": {
        "duration": 2,
        "prompt": "Soft gentle splat sound like a small ball of mud landing on "
                  "something, not violent, almost cute, with a slight squelch",
    },
    "gentle_crash": {
        "duration": 3,
        "prompt": "Gentle slow-motion crash, things falling softly one after another, "
                  "tinkle clink bonk thud, like a shelf of soft toys falling in slow motion",
    },
    "pillow_thud": {
        "duration": 1,
        "prompt": "Soft thud like something landing on a pillow, poomf, gentle and warm",
    },
    # Mechanical comedy
    "spring_boing": {
        "duration": 2,
        "prompt": "Gentle cartoon boing sound, a soft spring bouncing, not loud, "
                  "warm and silly",
    },
    "slide_whistle_up": {
        "duration": 2,
        "prompt": "Soft slide whistle going up gently, like something slowly floating "
                  "upward, whimsical not shrill",
    },
    "slide_whistle_down": {
        "duration": 2,
        "prompt": "Soft slide whistle going down gently, like something slowly deflating, "
                  "sad in a funny way",
    },
    "gear_clink": {
        "duration": 2,
        "prompt": "Tiny mechanical clicking and whirring, like a small invention starting "
                  "up, delicate, intricate, tick-tick-tick-whirr",
    },
    # Body comedy (gentle versions)
    "tiny_squeak": {
        "duration": 1,
        "prompt": "Tiny gentle squeak, like a small rubber duck being gently pressed, "
                  "cute and quiet",
    },
    "soft_pop": {
        "duration": 1,
        "prompt": "Gentle soft pop sound, like a soap bubble popping, barely there, delicate",
    },
    "gentle_rumble": {
        "duration": 2,
        "prompt": "Soft gentle stomach rumble, quiet and slightly embarrassing, "
                  "not gross just funny, grumble grumble",
    },
    # Dramatic silence breakers
    "single_cricket": {
        "duration": 3,
        "prompt": "A single cricket chirping in awkward silence, chirp chirp, "
                  "the loneliest funniest sound, perfectly timed comedy silence",
    },
    "gentle_wind": {
        "duration": 2,
        "prompt": "Soft gentle breeze, like a tumbleweed moment but cozy, "
                  "quiet comedic emptiness",
    },
    # Reactions
    "soft_ding": {
        "duration": 1,
        "prompt": "Gentle soft ding like a tiny bell, a small lightbulb moment, "
                  "an idea arriving quietly",
    },
    "warm_tada": {
        "duration": 2,
        "prompt": "Very gentle warm ta-da, like a shy trumpet trying to celebrate "
                  "but too quiet, endearing",
    },
}

# Direct lookup — LLM picks from fixed list, no guessing needed
SFX_LIBRARY = {name: SFX_DIR / f"{name}.wav" for name in COMEDY_SFX}


def match_sfx(name: str) -> Path | None:
    """Direct lookup — LLM picks from fixed list, no guessing needed."""
    name_clean = name.strip().lower()
    path = SFX_LIBRARY.get(name_clean)
    if not path or not path.exists():
        print(f"  WARNING: SFX '{name}' not found — skipping")
        return None
    return path


# ── Intro/Outro Candidates ──────────────────────────────────────

FUNNY_INTRO_CANDIDATES = [
    # 1. Tiptoeing pizzicato
    (
        "Charming gentle children's comedy jingle, soft pizzicato "
        "notes tiptoeing like someone sneaking, tip-tip-tip-tip, "
        "then a warm gentle boing at the end like they got caught, "
        "mischievous but quiet, like a bedtime prank, warm and cozy, "
        "not loud, cheeky smile energy not belly laugh energy"
    ),
    # 2. Gentle kazoo melody
    (
        "Charming gentle children's comedy jingle, a soft kazoo "
        "playing a little melody that tries to be serious but can't "
        "because it's a kazoo, da-da-da-daaa but gentle and warm, "
        "like a lullaby played on the wrong instrument, "
        "funny because it's trying so hard, cozy and quiet"
    ),
    # 3. Music box that hiccups
    (
        "Charming gentle children's comedy jingle, a music box "
        "playing a sweet melody but it hiccups — the notes skip "
        "and stumble, plink-plink-plonk-plink, like a music box "
        "that's almost asleep itself, endearing and warm, "
        "not chaotic just slightly wonky, makes you smile"
    ),
    # 4. Soft whistle with gentle boings
    (
        "Charming gentle children's comedy jingle, a soft whistle "
        "melody with tiny gentle boing sounds underneath like "
        "something small bouncing very softly on a pillow, "
        "the whistle is warm and the boings are cozy, "
        "bedtime mischief not daytime chaos, gentle and fun"
    ),
    # 5. Plucked strings conversation
    (
        "Charming gentle children's comedy jingle, two plucked "
        "string instruments having a little conversation, "
        "one plays a phrase and the other answers slightly wrong, "
        "like two friends trying to agree on a tune, "
        "warm, gentle, charming disagreement, soft and cozy"
    ),
]

# ── Comedy Bed ───────────────────────────────────────────────────

COMEDY_BED_BASE_PROMPT = (
    "2 minute gentle comedy underscore for a children's bedtime story, "
    "soft pizzicato and light playful percussion, warm and quiet, "
    "mischievous but not chaotic, like background music in a Pixar short, "
    "keeps a gentle bouncy pulse throughout, 95 BPM, "
    "NOT loud NOT intense NOT dramatic, "
    "the musical equivalent of a warm cheeky smile, "
    "soft enough to speak over easily, "
)

# Keep old name for backward compat (legacy callers)
COMEDY_BED_PROMPT = COMEDY_BED_BASE_PROMPT


def generate_comedy_bed(mood: str = None, duration: int = 120) -> AudioSegment:
    """Generate a mood-specific comedy bed via CassetteAI.

    Each episode gets its own bed that matches the child's emotional state:
    - anxious → steady, reassuring, predictable underscore
    - wired → light, bouncy, playful underscore
    - sad → tender, warm, kind underscore
    """
    mood_desc = COMEDY_BED_MOOD.get(mood, "") if mood else ""
    prompt = COMEDY_BED_BASE_PROMPT + mood_desc
    return generate_cassetteai(prompt, duration)


# ── Diversity System ─────────────────────────────────────────────
# Every episode dimension is tracked and rotated so the LLM can't
# repeat the same pattern. Pool sizes × recency windows = months
# of daily episodes before any COMBINATION repeats.

DYNAMICS = [
    "usual",            # One wrong, one warns
    "reversal",         # Usually-wrong character is right, nobody believes them
    "alliance",         # Two characters team up badly
    "competition",      # Two characters try the same thing, both fail differently
    "misunderstanding", # Talking about different things without realising
    "helper",           # Genuine help that makes everything worse
    "secret",           # One hiding something obvious, badly
]

DYNAMIC_DESCRIPTIONS = {
    "usual":            "One character is wrong about something. Another character sees it coming. The wrong character doesn't listen.",
    "reversal":         "The character who's USUALLY wrong is actually right this time. Nobody believes them because of their reputation. The frustration of being right and ignored.",
    "alliance":         "Two characters who usually disagree team up. Their alliance is terrible. They make each other worse, not better.",
    "competition":      "Two characters try to do the same thing. Both fail, but in completely different ways. Neither admits the other did better.",
    "misunderstanding": "Two characters think they're talking about the same thing but they're not. Every line makes sense to the speaker but is absurd in context.",
    "helper":           "One character genuinely tries to help another. Every act of help makes things worse. Both mean well. That's what makes it funny.",
    "secret":           "One character is hiding something obvious. Everyone can clearly tell. The character thinks they're being incredibly subtle.",
}

CHARACTER_COMBOS = {
    "2-5": [
        ["boomy", "pip"],
        ["boomy", "sunny"],
        ["pip", "sunny"],
    ],
    "6-8": [
        ["shadow", "sunny", "pip"],
        ["boomy", "shadow"],
        ["boomy", "pip", "sunny"],
        ["shadow", "pip"],
    ],
    "9-12": [
        ["boomy", "melody"],
        ["boomy", "shadow"],
        ["shadow", "melody"],
        ["boomy", "shadow", "sunny"],
    ],
}

TOPICS = [
    "bedtime",       # Sleep, dark, dreams, nightlights
    "food",          # Eating, cooking, snacks, meals
    "school",        # Homework, teachers, classes
    "hygiene",       # Teeth, bath, washing, haircuts
    "technology",    # Phones, apps, tablets, games
    "nature",        # Weather, animals, outdoors
    "household",     # Chores, cleaning, organising
    "social",        # Friends, siblings, sharing
    "clothing",      # Getting dressed, fashion, costumes
    "imagination",   # Inventions, experiments, theories
]

MELODY_ROLES = [
    "overheard",     # "I overheard Boomy and Pip talking..."
    "told",          # "Boomy told me something today..."
    "witnessed",     # "I was there when this happened..."
    "warned",        # "I tried to warn them..."
    "asked",         # "Pip asked me a question today..."
    "discovered",    # "I found out something about Shadow..."
]

MELODY_ROLE_DESCRIPTIONS = {
    "overheard":   "Melody overheard the other characters talking and is sharing what she heard with the child.",
    "told":        "One of the characters told Melody about what happened, and Melody is passing it along.",
    "witnessed":   "Melody was there when it happened and is recounting it.",
    "warned":      "Melody tried to warn the characters beforehand. They didn't listen. She's telling the child what happened next.",
    "asked":       "One of the characters came to Melody with a question. The conversation went sideways.",
    "discovered":  "Melody discovered something about one of the characters and is sharing the evidence.",
}

ENDINGS = [
    "falls_asleep",      # Character falls asleep mid-conversation
    "accidentally_right", # The wrong character turns out correct
    "gives_up",          # Character quietly surrenders
    "distracted",        # Character gets distracted by something else
    "agrees",            # Characters accidentally agree
    "question",          # Ends on an unanswered question
    "silence",           # Just... silence. Cricket.
]

ENDING_DESCRIPTIONS = {
    "falls_asleep":      "One character falls asleep mid-sentence. The other character is still talking. Then they fall asleep too.",
    "accidentally_right": "The character who was wrong turns out to be accidentally correct in the dumbest way possible.",
    "gives_up":          "One character quietly gives up. Not dramatically. Just a soft '...fine.' The other character doesn't even notice.",
    "distracted":        "The argument is interrupted because one character notices something completely unrelated and forgets what they were arguing about.",
    "agrees":            "Both characters accidentally say the same thing at the same time. Awkward pause. Then they both deny it.",
    "question":          "The episode ends on a question nobody can answer. Beat of silence. Cricket.",
    "silence":           "Everyone just... stops talking. The silence is the punchline. Cricket chirps.",
}

CHARACTER_DESCRIPTIONS = {
    "boomy":  "Boomy — warm, confident, always certain he's right even when he's completely wrong. Not loud, just sure.",
    "pip":    "Pip — slightly fast, earnest, always sees the problem coming, always gets talked over.",
    "shadow": "Shadow — slow, measured, speaks like a professor explaining something with complete confidence. Always wrong.",
    "sunny":  "Sunny — warm, relentlessly optimistic about clearly terrible situations. Genuinely believes everything is fine.",
    "melody": "Melody — the narrator. Warm, conspiratorial with the child, occasionally breaks composure.",
}


# ── Mood Mapping ────────────────────────────────────────────────
# Mood filters narrow the eligible pools BEFORE diversity rotation.
# An anxious child gets safe, predictable dynamics — not chaos.
# A wired child gets energy-channelling topics. Mood → therapeutic comedy.

MOOD_TO_TOPICS = {
    "wired":   ["technology", "imagination", "food", "social"],
    "curious": ["nature", "imagination", "school", "technology"],
    "calm":    ["household", "food", "nature", "clothing"],
    "sad":     ["social", "food", "household", "clothing"],
    "anxious": ["household", "nature", "food", "bedtime"],
    "angry":   ["social", "school", "technology", "household"],
}

MOOD_TO_DYNAMICS = {
    "wired":   ["competition", "usual", "alliance"],
    "curious": ["misunderstanding", "secret", "helper"],
    "calm":    ["helper", "misunderstanding", "secret"],
    "sad":     ["helper", "reversal", "secret"],
    "anxious": ["reversal", "helper", "usual"],
    "angry":   ["usual", "competition", "alliance"],
}

MOOD_COMEDY_NEED = {
    "wired":   "channels their energy into laughter, tires them out gently",
    "curious": "feeds their wondering with absurd explanations",
    "calm":    "keeps the warmth going, gentle smiles not big laughs",
    "sad":     "shows kindness through humor, characters caring badly but sincerely",
    "anxious": "feels predictable and safe, no surprises, comedy in the familiar",
    "angry":   "validates the feeling then releases it, frustration becomes funny",
}

MOOD_CHARACTER_PREFERENCE = {
    "wired":   "boomy",
    "curious": "shadow",
    "calm":    "sunny",
    "sad":     "pip",
    "anxious": "sunny",
    "angry":   "boomy",
}

COMEDY_BED_MOOD = {
    "wired":   "light bouncy comedy underscore, playful and mischievous",
    "curious": "gentle wondering comedy underscore, light and spacious",
    "calm":    "warm soft comedy underscore, cozy mischief",
    "sad":     "tender gentle comedy underscore, warm and kind",
    "anxious": "steady reassuring comedy underscore, predictable and safe",
    "angry":   "firm grounding comedy underscore, solid rhythm settling",
}


# Legacy fallback seeds (used when --fresh is not specified)
EPISODE_SEEDS = {
    "2-5": {
        "setup": (
            "Boomy says he's not scared of the dark. "
            "Pip asks questions. With every question, "
            "it becomes more obvious that Boomy is very, "
            "very scared of the dark. But he keeps saying "
            "he's not. His voice gets smaller each time."
        ),
        "characters": ["boomy", "pip", "melody"],
    },
    "6-8": {
        "setup": (
            "Shadow is explaining to Sunny how the weather works. "
            "Everything he says is completely wrong but he says it "
            "with absolute confidence. Sunny believes all of it. "
            "Pip tries to correct them. Nobody listens to Pip."
        ),
        "characters": ["shadow", "sunny", "pip", "melody"],
    },
    "9-12": {
        "setup": (
            "Boomy is trying to convince Melody that he already "
            "brushed his teeth. His excuses get increasingly "
            "elaborate and increasingly wrong. Melody isn't "
            "buying any of it. Boomy starts negotiating. "
            "The negotiations go badly."
        ),
        "characters": ["boomy", "melody"],
    },
}


def _load_existing_episodes() -> list:
    """Load all existing funny short metadata for diversity tracking."""
    episodes = []
    data_dir = BACKEND_DIR / "data" / "funny_shorts"
    if data_dir.exists():
        for f in sorted(data_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                episodes.append(json.loads(f.read_text()))
            except Exception:
                pass
    return episodes


def _pick_avoiding_recent(episodes: list, field: str, options: list, recency: int = 3):
    """Pick a value not used in the last N episodes."""
    recent = [ep.get(field) for ep in episodes[-recency:]]
    # For list fields (like character_combo), compare as sorted tuples
    if options and isinstance(options[0], list):
        recent_sets = [tuple(sorted(r)) if isinstance(r, list) else r for r in recent]
        available = [o for o in options if tuple(sorted(o)) not in recent_sets]
    else:
        available = [o for o in options if o not in recent]
    if not available:
        available = options
    return random.choice(available)


def select_episode_params(existing_episodes: list, age_group: str = None,
                          mood: str = None) -> dict:
    """Select all parameters for next episode, ensuring variety across every dimension.

    When mood is provided, topics and dynamics are filtered to mood-appropriate
    pools BEFORE applying recency checks. This ensures an anxious child never
    gets a chaotic "competition" dynamic, and a sad child gets warm topics.

    Diversity tracking:
    | Dimension       | Pool     | Recency | What It Prevents                        |
    |-----------------|----------|---------|-----------------------------------------|
    | Dynamic         | 3-7      |    5    | Same joke structure every night          |
    | Character combo | 3-4      |    3    | Same two characters every night          |
    | Topic           | 4-10     |    5    | Same subject every night                 |
    | Melody's role   |  6       |    4    | Same "So I heard..." opening every night |
    | Ending type     |  7       |    4    | Same "fell asleep" ending every night    |
    | Age group       |  3       |    3    | Same age group every night               |
    | Mood            | passed in|    —    | Filters topics + dynamics therapeutically |
    """
    # Age group rotation
    if age_group is None:
        recent_ages = [ep.get("age_group") for ep in existing_episodes[-3:]]
        age_options = ["2-5", "6-8", "9-12"]
        age_group = next((a for a in age_options if a not in recent_ages),
                         random.choice(age_options))

    # Filter existing episodes to same age group for combo tracking
    same_age = [ep for ep in existing_episodes if ep.get("age_group") == age_group]

    # ── Mood-filtered pools ──────────────────────────────────────
    # Narrow topics and dynamics by mood BEFORE diversity rotation.
    eligible_topics = MOOD_TO_TOPICS.get(mood, TOPICS) if mood else TOPICS
    eligible_dynamics = MOOD_TO_DYNAMICS.get(mood, DYNAMICS) if mood else DYNAMICS

    dynamic = _pick_avoiding_recent(existing_episodes, "dynamic", eligible_dynamics, recency=5)
    topic = _pick_avoiding_recent(existing_episodes, "topic", eligible_topics, recency=5)

    # Character combo — prefer mood-preferred character when possible
    combo = _pick_avoiding_recent(same_age, "character_combo", CHARACTER_COMBOS[age_group], recency=3)
    if mood:
        preferred = MOOD_CHARACTER_PREFERENCE.get(mood)
        if preferred:
            # Check if preferred character appears in ANY combo for this age group
            all_chars = {c for combo_list in CHARACTER_COMBOS[age_group] for c in combo_list}
            if preferred in all_chars and preferred not in combo:
                # Try to find a combo that includes the preferred character
                preferred_combos = [
                    cb for cb in CHARACTER_COMBOS[age_group] if preferred in cb
                ]
                if preferred_combos:
                    combo = _pick_avoiding_recent(
                        same_age, "character_combo", preferred_combos, recency=3,
                    )

    melody_role = _pick_avoiding_recent(existing_episodes, "melody_role", MELODY_ROLES, recency=4)
    ending = _pick_avoiding_recent(existing_episodes, "ending", ENDINGS, recency=4)

    # Melody is always present as narrator
    characters = combo if "melody" in combo else combo + ["melody"]

    return {
        "age_group": age_group,
        "mood": mood,
        "dynamic": dynamic,
        "characters": characters,
        "character_combo": combo,
        "topic": topic,
        "melody_role": melody_role,
        "ending": ending,
    }


# ── Content Prompt ───────────────────────────────────────────────
# The prompt uses {placeholders} filled by diversity params.

FUNNY_SHORT_CONTENT_PROMPT = """Write a funny bedtime short for ages {age_group}.

FORMAT: PURE CONVERSATION.

Nothing "happens." No machines, no inventions, no physical events.
Just characters TALKING. The comedy is in what they SAY to each
other, how they argue, how they lie, how they explain, how they
negotiate.

The child's eyes are closed. They hear VOICES. That's all they
need. Two or three people talking is the most natural audio
experience possible.

THIS IS CALM COMEDY. The child should smile and giggle softly,
not scream with laughter. Think Pixar, not Cartoon Network.

LENGTH LIMITS (STRICT — do NOT exceed):
- Ages 2-5: 100-150 words. 60-75 seconds total.
- Ages 6-8: 150-200 words. 75-90 seconds total.
- Ages 9-12: 180-220 words. 80-95 seconds total.

CHARACTERS IN THIS EPISODE:
{characters_with_descriptions}

Melody (narrator) is always present. She tells the child what happened.
Her role this episode: {melody_role_description}

EPISODE DYNAMIC: {dynamic}
{dynamic_description}

TOPIC: {topic}
The conversation is about something related to "{topic}".

MOOD: {mood}
This episode is for a child feeling {mood}.
The comedy should: {mood_comedy_need}

ENDING: The episode ends with: {ending_description}

CHARACTER CATCHPHRASES (these repeat every episode — use 1-2 per character):
- Boomy: "That was SUPPOSED to happen."
- Pip: "I said this would happen. I SAID."
- Shadow: "According to my calculations... hmm."
- Sunny: "This is fine! This is completely fine."
- Melody: "And that's when things got... interesting."

Everything else Melody says — intros, outros, child-address
moments — must be UNIQUE to this episode. Do not reuse
patterns from other episodes.

STRUCTURE (3 sections, THAT'S IT):

[HOST_INTRO]
Melody talks to the child. Sets up the situation in 1-2 sentences.
Her framing reflects her role: {melody_role_description}

[THE_CONVERSATION]
The characters talk. That's it. The conversation has a shape:

- It starts normal
- One character says something slightly wrong
- The other character questions it
- The first character doubles down
- It escalates — each line digs the hole deeper
- Catchphrases arrive at natural moments of failure
- It reaches a peak of absurdity
- It ends: {ending_description}

This should be 60-80% of the episode's runtime.

[THE_END]
Melody wraps up in 1-2 sentences. Talks to the child. Goodnight.

THAT'S IT. Three sections total. No scenes, no plans, no disasters.

CONVERSATION RULES:

1. BACK AND FORTH. No character speaks more than 2 lines
   in a row. It's a rally, not a monologue.

2. EACH LINE IS SHORT. One sentence. Sometimes just one word.
   "Really?" / "Yes." / "You're sure?" / "...mostly."
   Ages 2-5: 4-6 words per line.
   Ages 6-8: 6-10 words per line.
   Ages 9-12: 8-12 words per line.

3. THE FUNNY IS IN THE GAP between what the character says
   and what the child knows is true. Boomy says he's not
   scared. His voice is clearly scared. The child KNOWS.

4. ESCALATION through conversation:
   Line 1: small claim
   Line 5: medium claim
   Line 10: absurd claim
   Line 15: the claim collapses

   Each line pushes the same direction further. Not new
   topics — deeper into the same hole.

5. SILENCE IS A PUNCHLINE. When a character has no response:
   [PAUSE: 600]
   "...the cat was fine."
   The pause IS the joke. The child laughs during the silence.

6. CATCHPHRASES. Each character's catchphrase appears 1-2 times.
   Not forced — it arrives at the natural moment after failure.

7. NARRATOR BREAKS. Mark with [BREAK].
   1 moment where Melody loses composure.

SFX IN CONVERSATIONS:
SFX are REACTIONS, not events. Use 4-6 per episode.
Pick ONLY from this list — do NOT invent new ones:
- [SFX: single_cricket] — awkward silence
- [SFX: tiny_squeak] — confidence deflating
- [SFX: soft_pop] — a lie popping
- [SFX: gentle_rumble] — stomach betraying a lie
- [SFX: slide_whistle_down] — argument slowly collapsing
- [SFX: soft_ding] — an idea arriving
- [SFX: warm_tada] — sarcastic victory
- [SFX: gentle_wind] — tumbleweed silence
- [SFX: spring_boing] — surprise realization
- [SFX: soft_splat] — someone landing on the truth
- [SFX: gentle_crash] — a claim falling apart
- [SFX: pillow_thud] — giving up
- [SFX: slide_whistle_up] — escalating absurdity
- [SFX: gear_clink] — brain working (incorrectly)
- [SFX: record_scratch] — sudden realization
- [SFX: sad_trombone] — comedy fail moment
- [SFX: deflate] — confidence slowly leaking out
- [SFX: blink_blink] — stunned silence, two cartoon blinks

SFX never carry information. They punctuate emotion.
The episode MUST make complete sense with ALL SFX removed.

PAUSES — comedy pauses are SHORT. The silence is a flash, not a gap.
The child should barely notice it — just enough for the brain
to go "wait—" before the punchline hits.
[PAUSE: 200] — quick beat after a catchphrase
[PAUSE: 400] — normal beat (setup before a punchline)
[PAUSE: 600] — the biggest dramatic pause, used ONCE per episode

OUTPUT TAGS:

[TITLE: short episode title]
[CHARACTERS: which 2-3 characters appear]

Then the script using:
[HOST_INTRO] ... [/HOST_INTRO]
[THE_CONVERSATION] ... [/THE_CONVERSATION]
[THE_END] ... [/THE_END]

With inline tags: [SFX: name_from_list], [PAUSE: ms], [BREAK]
Character lines: BOOMY: "dialogue" / PIP: "dialogue" / etc.
Melody narration: MELODY: "text"
"""


# ═══════════════════════════════════════════════════════════════════
# CassetteAI helper (fal.ai queue API)
# ═══════════════════════════════════════════════════════════════════

def generate_cassetteai(prompt: str, duration: int,
                        endpoint: str = "cassetteai/music-generator") -> AudioSegment:
    """Generate audio via CassetteAI on fal.ai."""
    if not FAL_KEY:
        raise RuntimeError("FAL_KEY not set in .env")

    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    client = httpx.Client(timeout=300)

    # CassetteAI music-generator has 10s minimum
    if endpoint == "cassetteai/music-generator" and duration < 10:
        endpoint = "cassetteai/sound-effects-generator"

    resp = client.post(
        f"https://queue.fal.run/{endpoint}",
        headers=headers,
        json={"prompt": prompt, "duration": duration},
    )
    data = resp.json()
    if "request_id" not in data:
        raise RuntimeError(f"CassetteAI submit failed: {data}")

    rid = data["request_id"]
    start = time.time()
    while True:
        time.sleep(4)
        sr = client.get(
            f"https://queue.fal.run/{endpoint}/requests/{rid}/status",
            headers=headers,
        ).json()
        status = sr.get("status")
        elapsed = time.time() - start
        print(f"    [{elapsed:.0f}s] {status}")
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"CassetteAI failed: {sr}")

    result = client.get(
        f"https://queue.fal.run/{endpoint}/requests/{rid}",
        headers=headers,
    ).json()

    audio_url = None
    for key in ("audio_file", "audio", "output"):
        if key in result:
            v = result[key]
            audio_url = v.get("url") if isinstance(v, dict) else v
            if audio_url:
                break
    if not audio_url:
        raise RuntimeError(f"No audio URL: {list(result.keys())}")

    audio_data = client.get(audio_url).content
    return AudioSegment.from_file(io.BytesIO(audio_data))


# ═══════════════════════════════════════════════════════════════════
# Step 1: Generate SFX Library
# ═══════════════════════════════════════════════════════════════════

def generate_sfx_library(force: bool = False):
    """Generate 14 gentle comedy SFX files via CassetteAI."""
    SFX_DIR.mkdir(parents=True, exist_ok=True)

    for name, spec in COMEDY_SFX.items():
        out_path = SFX_DIR / f"{name}.wav"
        if out_path.exists() and not force:
            print(f"  {name}: exists, skipping")
            continue

        print(f"  {name}: generating ({spec['duration']}s)...")
        try:
            audio = generate_cassetteai(
                spec["prompt"], spec["duration"],
                endpoint="cassetteai/sound-effects-generator",
            )
            audio.export(str(out_path), format="wav")
            print(f"    ✓ {out_path.name} ({len(audio)}ms)")
        except Exception as e:
            print(f"    ✗ FAILED: {e}")

    count = len(list(SFX_DIR.glob("*.wav")))
    print(f"\nSFX library: {count}/{len(COMEDY_SFX)} files in {SFX_DIR}")


# ═══════════════════════════════════════════════════════════════════
# Step 2: Generate Intro/Outro Candidates
# ═══════════════════════════════════════════════════════════════════

def generate_intro_outro_candidates(force: bool = False):
    """Generate 5 intro/outro candidates via CassetteAI."""
    INTRO_DIR.mkdir(parents=True, exist_ok=True)

    for i, prompt in enumerate(FUNNY_INTRO_CANDIDATES, 1):
        intro_path = INTRO_DIR / f"funny_{i}_intro.mp3"
        outro_path = INTRO_DIR / f"funny_{i}_outro.mp3"
        full_path = INTRO_DIR / f"funny_{i}_full.mp3"

        if intro_path.exists() and outro_path.exists() and not force:
            print(f"  Candidate {i}: exists, skipping")
            continue

        print(f"  Candidate {i}: generating...")
        print(f"    Prompt: {prompt[:80]}...")
        try:
            audio = generate_cassetteai(prompt, 60)
            audio.export(str(full_path), format="mp3", bitrate="256k")

            # Intro: first 5 seconds with 0.5s fade-out
            intro = audio[:5000].fade_out(500)
            intro.export(str(intro_path), format="mp3", bitrate="256k")

            # Outro: last 20 seconds with 1s fade-in
            outro = audio[-20000:].fade_in(1000)
            outro.export(str(outro_path), format="mp3", bitrate="256k")

            print(f"    ✓ intro ({len(intro)}ms), outro ({len(outro)}ms)")
        except Exception as e:
            print(f"    ✗ FAILED: {e}")

    print(f"\nIntro/outro candidates in {INTRO_DIR}")
    print("Pick the winner and copy as:")
    print(f"  {OUTPUT_DIR}/show_intro.mp3")
    print(f"  {OUTPUT_DIR}/show_outro.mp3")


# ═══════════════════════════════════════════════════════════════════
# Step 3: Script Generation (Mistral)
# ═══════════════════════════════════════════════════════════════════

def generate_script(age_group: str, setup: str, characters: list,
                    params: dict = None) -> str:
    """Generate a funny short script via Mistral AI.

    Args:
        age_group: "2-5", "6-8", or "9-12"
        setup: Episode premise/seed text
        characters: List of character names
        params: Diversity params from select_episode_params() — if provided,
                injects dynamic, topic, melody_role, ending into the prompt.
    """
    from mistralai import Mistral

    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set in .env")

    # Build character descriptions for this episode
    chars_with_desc = "\n".join(
        f"- {CHARACTER_DESCRIPTIONS.get(c, c.title())}"
        for c in characters if c in CHARACTER_DESCRIPTIONS
    )

    if params:
        # Full diversity-aware prompt with mood
        ep_mood = params.get("mood", "calm")
        prompt = FUNNY_SHORT_CONTENT_PROMPT.format(
            age_group=age_group,
            characters_with_descriptions=chars_with_desc,
            melody_role_description=MELODY_ROLE_DESCRIPTIONS.get(
                params.get("melody_role", "overheard"), "Melody tells the child what happened."),
            dynamic=params.get("dynamic", "usual"),
            dynamic_description=DYNAMIC_DESCRIPTIONS.get(
                params.get("dynamic", "usual"), ""),
            topic=params.get("topic", "bedtime"),
            mood=ep_mood,
            mood_comedy_need=MOOD_COMEDY_NEED.get(ep_mood, "gentle smiles, warm comedy"),
            ending_description=ENDING_DESCRIPTIONS.get(
                params.get("ending", "falls_asleep"), ""),
        )
    else:
        # Legacy mode: minimal prompt (backwards compatibility with EPISODE_SEEDS)
        prompt = FUNNY_SHORT_CONTENT_PROMPT.format(
            age_group=age_group,
            characters_with_descriptions=chars_with_desc,
            melody_role_description="Melody overheard the other characters talking and is sharing what she heard with the child.",
            dynamic="usual",
            dynamic_description=DYNAMIC_DESCRIPTIONS["usual"],
            topic="bedtime",
            mood="calm",
            mood_comedy_need=MOOD_COMEDY_NEED["calm"],
            ending_description=ENDING_DESCRIPTIONS["falls_asleep"],
        )

    prompt += f"\n\nEPISODE SEED:\n{setup}\nCharacters: {', '.join(c for c in characters if c != 'melody')}"

    client = Mistral(api_key=MISTRAL_API_KEY)
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a children's comedy writer specializing in calm bedtime humor. "
                    "You write short, punchy comedy scripts for audio production. "
                    "Output ONLY the script in the exact format requested. "
                    "No explanations, no markdown code blocks."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        max_tokens=2000,
    )

    script = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    script = re.sub(r"^```\w*\n?", "", script)
    script = re.sub(r"\n?```$", "", script)
    return script.strip()


# ═══════════════════════════════════════════════════════════════════
# Step 4: Script Parsing
# ═══════════════════════════════════════════════════════════════════

def extract_tag(text: str, tag_name: str) -> str:
    """Extract [TAG: value] from script."""
    m = re.search(rf"\[{tag_name}:\s*(.+?)\]", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# Tracks the last speaking character so continuation text after an
# inline [SFX:] tag inherits the correct voice instead of defaulting
# to narrator.  e.g.:  PIP: "I— [SFX: pillow_thud] —oh no."
#   → "I—" is PIP, SFX plays, "—oh no." should also be PIP.
_last_speaker = "melody"


def parse_dialogue_line(line: str, section: str) -> dict:
    """Determine speaker from line prefix."""
    global _last_speaker

    for char in ["BOOMY", "PIP", "SHADOW", "SUNNY", "MELODY"]:
        if line.upper().startswith(f"{char}:"):
            text = line[len(char) + 1:].strip().strip('"')
            _last_speaker = char.lower()
            return {
                "type": "dialogue",
                "character": char.lower(),
                "text": text,
                "section": section,
            }

    # No character prefix — continuation of the last speaker's line
    # (happens when inline [SFX:] or [PAUSE:] splits a dialogue line)
    text = line.strip('"').strip()
    if not text:
        return {"type": "narration", "character": "melody", "text": "", "section": section}

    return {
        "type": "dialogue",
        "character": _last_speaker,
        "text": text,
        "section": section,
    }


_INLINE_TAG_RE = re.compile(
    r"\[SFX:\s*(.+?)\]"       # [SFX: name]
    r"|\[PAUSE:\s*(\d+)\]"    # [PAUSE: ms]
    r"|\[BREAK\]",            # [BREAK]
    re.IGNORECASE,
)


def _split_inline_tags(line: str) -> list[dict]:
    """Split a line into text chunks and inline tags.

    Handles multiple [SFX:], [PAUSE:], and [BREAK] tags on one line.
    Returns list of {"type": "text"|"sfx"|"pause"|"break", "value": ...}.
    """
    chunks = []
    last_end = 0

    for m in _INLINE_TAG_RE.finditer(line):
        # Text before this tag
        before = line[last_end:m.start()].strip()
        if before:
            chunks.append({"type": "text", "value": before})

        if m.group(1) is not None:      # [SFX: name]
            chunks.append({"type": "sfx", "value": m.group(1).strip()})
        elif m.group(2) is not None:     # [PAUSE: ms]
            chunks.append({"type": "pause", "value": m.group(2)})
        else:                            # [BREAK]
            chunks.append({"type": "break"})

        last_end = m.end()

    # Remaining text after last tag
    after = line[last_end:].strip()
    if after:
        chunks.append({"type": "text", "value": after})

    # If no tags found, the whole line is text
    if not chunks:
        chunks.append({"type": "text", "value": line})

    return chunks


def parse_funny_short(raw_text: str) -> dict:
    """Parse the funny short script into segments."""
    global _last_speaker
    _last_speaker = "melody"  # Reset for each new script

    title = extract_tag(raw_text, "TITLE")
    characters = extract_tag(raw_text, "CHARACTERS")

    segments = []
    current_section = None

    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Section markers (v3: 3-section conversation structure)
        if line.startswith("[HOST_INTRO]"):
            current_section = "host_intro"
            continue
        elif line.startswith("[THE_CONVERSATION]"):
            current_section = "the_conversation"
            continue
        elif line.startswith("[THE_END]"):
            current_section = "the_end"
            continue
        # Legacy section names (in case LLM uses them)
        elif line.startswith("[HOST_OUTRO]"):
            current_section = "the_end"
            continue
        elif line.startswith("[THE_PLAN]"):
            current_section = "the_conversation"
            continue
        elif line.startswith("[THE_DISASTER]"):
            current_section = "the_conversation"
            continue
        elif line.startswith("[SCENE_"):
            current_section = "the_conversation"
            continue
        elif line.startswith("[RESOLUTION]"):
            current_section = "the_end"
            continue
        elif line.startswith("[/"):
            continue
        # Skip metadata tags
        if re.match(r"^\[(TITLE|CHARACTERS):", line):
            continue

        # [BREAK] tag — standalone or inline
        if line == "[BREAK]":
            segments.append({"type": "break_marker"})
            continue

        if line.startswith("[BREAK]"):
            segments.append({"type": "break_marker"})
            line = line[len("[BREAK]"):].strip()
            if not line:
                continue

        # Split line into chunks around ALL inline tags ([SFX:], [PAUSE:], [BREAK])
        # This handles multiple tags per line correctly.
        chunks = _split_inline_tags(line)
        for chunk in chunks:
            if chunk["type"] == "text":
                text = chunk["value"].strip()
                if text:
                    segments.append(parse_dialogue_line(text, current_section))
            elif chunk["type"] == "sfx":
                segments.append({"type": "sfx", "description": chunk["value"]})
            elif chunk["type"] == "pause":
                segments.append({"type": "pause", "ms": int(chunk["value"])})
            elif chunk["type"] == "break":
                segments.append({"type": "break_marker"})

    return {
        "title": title,
        "characters": characters,
        "segments": segments,
    }


# ═══════════════════════════════════════════════════════════════════
# Step 5: TTS Generation (Modal Chatterbox)
# ═══════════════════════════════════════════════════════════════════

def normalize_caps_for_tts(text: str) -> str:
    """Normalize ALL CAPS words → Title Case to prevent TTS spelling them.
    Also strips any leftover bracket tags that the parser missed."""
    # Strip any remaining [TAG: ...] or [TAG] patterns
    text = re.sub(r"\[SFX:\s*[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[PAUSE:\s*\d+\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[/?BREAK\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[/?(?:HOST_INTRO|HOST_OUTRO|THE_PLAN|THE_DISASTER|THE_END|"
                  r"SCENE_\d|RESOLUTION|TITLE|CHARACTERS)[^\]]*\]", "", text, flags=re.IGNORECASE)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()

    def _fix(match):
        word = match.group(0)
        if len(word) <= 2:
            return word  # Keep "I", "OK", etc.
        return word.title()
    return re.sub(r"\b[A-Z]{3,}\b", _fix, text)


def generate_tts(text: str, voice_id: str, exaggeration: float,
                 speed: float, cfg_weight: float) -> AudioSegment:
    """Generate TTS audio via Modal Chatterbox endpoint."""
    params = {
        "text": text,
        "voice": voice_id,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "speed": speed,
    }
    url = f"{MODAL_TTS_URL}?{urlencode(params)}"

    for attempt in range(3):
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.get(url)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_file(io.BytesIO(resp.content))
                print(f"    TTS {resp.status_code}: {resp.text[:80]}")
        except Exception as e:
            print(f"    TTS error (attempt {attempt + 1}): {e}")
        if attempt < 2:
            time.sleep(5 * (attempt + 1))

    raise RuntimeError(f"TTS failed for voice={voice_id}")


def trim_tts_silence(audio: AudioSegment, silence_threshold=-40, min_silence_ms=50) -> AudioSegment:
    """Remove leading and trailing silence from TTS output."""
    start_trim = detect_leading_silence(audio,
                                         silence_threshold=silence_threshold,
                                         chunk_size=10)
    end_trim = detect_leading_silence(audio.reverse(),
                                       silence_threshold=silence_threshold,
                                       chunk_size=10)
    start_trim = max(0, start_trim - min_silence_ms)
    end_trim = max(0, end_trim - min_silence_ms)
    trimmed = audio[start_trim:len(audio) - end_trim] if end_trim > 0 else audio[start_trim:]
    return trimmed if len(trimmed) > 0 else audio


# ═══════════════════════════════════════════════════════════════════
# Context-Aware SFX Generation
# ═══════════════════════════════════════════════════════════════════

BASE_SFX_SOUNDS = {
    "tiny_squeak":        "short expressive cartoon squeak",
    "gentle_rumble":      "low comedic rumble with personality",
    "pillow_thud":        "soft comedic thud like landing on something soft",
    "soft_pop":           "cartoon bubble pop with attitude",
    "soft_ding":          "bright cartoon lightbulb ding",
    "warm_tada":          "tiny pathetic fanfare trying its best",
    "soft_splat":         "cartoon squelch with comic timing",
    "slide_whistle_up":   "classic slide whistle rising",
    "slide_whistle_down": "classic slide whistle falling sadly",
    "spring_boing":       "cartoon spring bounce",
    "single_cricket":     "lone cricket chirp in awkward silence",
    "gentle_crash":       "soft cartoon tumble sequence",
    "gear_clink":         "tiny mechanical whirring and clicking",
    "gentle_wind":        "soft empty breeze of nothingness",
    "record_scratch":     "vinyl record scratch stop, sudden halt",
    "sad_trombone":       "wah wah wah comedy fail trombone",
    "deflate":            "slow cartoon deflating, air leaking out",
    "blink_blink":        "two cartoon blink sounds in stunned silence",
}


def _get_surrounding_text(segments: list, index: int) -> tuple:
    """Get dialogue text before and after an SFX segment."""
    prev_line = ""
    for j in range(index - 1, -1, -1):
        if segments[j]["type"] in ("dialogue", "narration") and segments[j].get("text", "").strip():
            prev_line = segments[j]["text"]
            break
    next_line = ""
    for j in range(index + 1, len(segments)):
        if segments[j]["type"] in ("dialogue", "narration") and segments[j].get("text", "").strip():
            next_line = segments[j]["text"]
            break
    return prev_line, next_line


def build_comedy_sfx_prompt(sfx_name: str, line_before: str, line_after: str) -> str:
    """Build a prompt that describes the COMEDY MOMENT, not just a sound."""
    base = BASE_SFX_SOUNDS.get(sfx_name, "short cartoon comedy sound")
    return (
        f"{base}, "
        f"this sound plays right after someone says '{line_before[:60]}' "
        f"and right before someone says '{line_after[:60]}', "
        f"it's a comedy punchline sound, cartoonish and expressive, "
        f"warm not loud, full of personality, "
        f"the kind of sound that makes a child giggle, "
        f"1-2 seconds, clean ending with short fade"
    )


def trim_and_fade_sfx(audio: AudioSegment, fade_out_ms: int = 200) -> AudioSegment:
    """Trim silence and apply fade-out to SFX."""
    start = detect_leading_silence(audio, silence_threshold=-40, chunk_size=10)
    audio = audio[start:]
    audio = audio.fade_out(fade_out_ms)
    return audio


def generate_episode_sfx(segments: list) -> dict:
    """Generate unique SFX for each comedy moment in the episode.

    Returns dict mapping segment index → AudioSegment.
    """
    sfx_lookup = {}
    for i, seg in enumerate(segments):
        if seg["type"] != "sfx":
            continue

        sfx_name = seg["description"].strip().lower()
        prev_line, next_line = _get_surrounding_text(segments, i)
        prompt = build_comedy_sfx_prompt(sfx_name, prev_line, next_line)
        print(f"    SFX [{sfx_name}]: {prompt[:80]}...")

        try:
            audio = generate_cassetteai(
                prompt, 2,
                endpoint="cassetteai/sound-effects-generator",
            )
            sfx_lookup[i] = trim_and_fade_sfx(audio)
            print(f"      ✓ {len(sfx_lookup[i])}ms")
        except Exception as e:
            print(f"      ✗ FAILED: {e}")
            # Fallback to static SFX library
            path = match_sfx(sfx_name)
            if path:
                sfx_lookup[i] = AudioSegment.from_file(str(path))

    return sfx_lookup


def generate_funny_short_tts(segments: list, episode_sfx: dict = None) -> list:
    """Generate TTS for all segments with per-character params.

    Returns list of (seg_type, content, character) tuples.
    episode_sfx: dict mapping segment index → AudioSegment (context-aware SFX).
    """
    if episode_sfx is None:
        episode_sfx = {}
    audio_segments = []
    is_breaking = False  # Tracks [BREAK] → next Melody line uses breaking params

    for seg_idx, seg in enumerate(segments):
        if seg["type"] == "break_marker":
            is_breaking = True
            continue

        if seg["type"] in ("dialogue", "narration"):
            # Skip empty text segments
            if not seg.get("text", "").strip():
                continue

        if seg["type"] == "dialogue":
            char = seg["character"]
            # Apply MELODY_BREAKING if flagged and this is Melody
            if char == "melody" and is_breaking:
                params = MELODY_BREAKING
                is_breaking = False
            else:
                params = CHARACTER_VOICES.get(char, CHARACTER_VOICES["melody"])

            text = normalize_caps_for_tts(seg["text"])
            if len(text.split()) <= 4:
                text = f"... {text}"

            print(f"    TTS [{char}]: \"{text[:60]}...\"")
            audio = generate_tts(
                text,
                voice_id=params["voice_id"],
                exaggeration=params["exaggeration"],
                speed=params["speed"],
                cfg_weight=params["cfg_weight"],
            )
            audio = trim_tts_silence(audio)
            audio_segments.append(("audio", audio, char))

        elif seg["type"] == "narration":
            # Narration is always Melody — check breaking flag
            if is_breaking:
                params = MELODY_BREAKING
                is_breaking = False
            else:
                params = CHARACTER_VOICES["melody"]

            text = normalize_caps_for_tts(seg["text"])
            print(f"    TTS [melody/narration]: \"{text[:60]}...\"")
            audio = generate_tts(
                text,
                voice_id=params["voice_id"],
                exaggeration=params["exaggeration"],
                speed=params["speed"],
                cfg_weight=params["cfg_weight"],
            )
            audio = trim_tts_silence(audio)
            audio_segments.append(("audio", audio, "melody"))

        elif seg["type"] == "pause":
            audio_segments.append(("pause", seg["ms"], None))

        elif seg["type"] == "sfx":
            # Prefer context-aware SFX, fall back to static library
            if seg_idx in episode_sfx:
                audio_segments.append(("sfx", episode_sfx[seg_idx], None))
            else:
                sfx_path = match_sfx(seg["description"])
                if sfx_path:
                    sfx_audio = AudioSegment.from_file(str(sfx_path))
                    audio_segments.append(("sfx", sfx_audio, None))

    # Throwaway TTS call to prevent last-line repeat (Chatterbox quirk)
    try:
        _ = generate_tts(".", "musical_original", 0.1, 0.8, 0.5)
    except Exception:
        pass

    return audio_segments


# ═══════════════════════════════════════════════════════════════════
# Step 6: Comedy Bed Shaping
# ═══════════════════════════════════════════════════════════════════

def shape_comedy_bed(bed: AudioSegment, punchline_positions: list,
                     transition_positions: list) -> AudioSegment:
    """Shape the bed volume for comedy timing.

    Normal:        -18dB under narration (barely there)
    Before joke:   DUCK to -30dB (near silence)
    After joke:    LIFT to -12dB for 2 seconds (the bed "laughs")
    Transitions:   SWELL to -8dB between scenes
    """
    # Start at -18dB
    bed = bed - 18

    for pos_ms in punchline_positions:
        # Duck 2 seconds before punchline
        duck_start = max(0, pos_ms - 2000)
        duck_end = max(0, pos_ms - 500)
        if duck_start < duck_end and duck_end <= len(bed):
            before = bed[:duck_start]
            ducked = bed[duck_start:duck_end] - 12  # extra -12 on top of -18 = ~-30
            after = bed[duck_end:]
            bed = before + ducked + after

        # Lift after punchline for 2 seconds
        lift_start = min(len(bed), pos_ms + 500)
        lift_end = min(len(bed), pos_ms + 2500)
        if lift_start < lift_end:
            before = bed[:lift_start]
            lifted = bed[lift_start:lift_end] + 6  # -18 + 6 = -12
            after = bed[lift_end:]
            bed = before + lifted + after

    for pos_ms in transition_positions:
        swell_start = max(0, pos_ms)
        swell_peak = min(len(bed), pos_ms + 1000)
        swell_end = min(len(bed), pos_ms + 3000)

        if swell_start < swell_peak and swell_peak <= len(bed):
            before = bed[:swell_start]
            swelled = bed[swell_start:swell_peak] + 10  # -18 + 10 = -8
            settle = bed[swell_peak:swell_end]
            after = bed[swell_end:]
            bed = before + swelled + settle + after

    return bed


# ═══════════════════════════════════════════════════════════════════
# Step 7: Assembly
# ═══════════════════════════════════════════════════════════════════

def assemble_funny_short(audio_segments: list, bed_path: Path,
                         intro_path: Path, outro_path: Path) -> tuple:
    """Assemble complete funny short episode.

    Returns (with_music, without_music) AudioSegments.
    """
    # Build narration track
    narration = AudioSegment.empty()
    punchline_positions = []

    # Show intro
    if intro_path.exists():
        intro = AudioSegment.from_file(str(intro_path))
        narration += intro
        narration += AudioSegment.silent(duration=300)

    for seg_type, content, character in audio_segments:
        if seg_type == "audio":
            narration += content
            narration += AudioSegment.silent(duration=80)   # Almost overlapping — like real conversation

        elif seg_type == "pause":
            punchline_positions.append(len(narration) + content)
            narration += AudioSegment.silent(duration=content)

        elif seg_type == "sfx":
            narration += AudioSegment.silent(duration=100)  # Tiny gap before SFX
            narration += content
            narration += AudioSegment.silent(duration=200)  # Quick reaction gap

    # Gap before outro
    narration += AudioSegment.silent(duration=1000)

    # Show outro
    if outro_path.exists():
        outro = AudioSegment.from_file(str(outro_path))
        narration += outro

    total_duration = len(narration)
    without_music = narration

    # Shape comedy bed
    if bed_path.exists():
        bed = AudioSegment.from_file(str(bed_path))
        # Trim or loop to match duration
        if len(bed) < total_duration:
            loops_needed = (total_duration // len(bed)) + 1
            bed = bed * loops_needed
        bed = bed[:total_duration]
        bed = bed.fade_in(500).fade_out(2000)

        bed_shaped = shape_comedy_bed(bed, punchline_positions, [])
        with_music = narration.overlay(bed_shaped)
    else:
        with_music = narration

    return with_music, without_music


# ═══════════════════════════════════════════════════════════════════
# Step 8: Cover Generation (FLUX via Pollinations)
# ═══════════════════════════════════════════════════════════════════

CHARACTER_VISUALS = {
    "boomy":  "a round confident cartoon bear",
    "pip":    "a tiny anxious cartoon bird",
    "shadow": "a mysterious cartoon owl wearing glasses",
    "sunny":  "a cheerful smiling cartoon sun character",
    "melody": "a warm friendly cartoon fox narrator",
}


def generate_cover(title: str, episode_id: str, scene_description: str = "",
                   characters: list = None) -> Path | None:
    """Generate a cover image via Pollinations.ai FLUX.

    CRITICAL: NEVER put the title or any English words in the prompt.
    FLUX renders ANY word-like token as visible text on the image.
    Do NOT even say "no text" — that triggers FLUX to think about text.
    Use purely visual, abstract descriptions only.
    """
    if not scene_description and characters:
        # Build a visual scene from characters — NO title, NO words
        char_visuals = [CHARACTER_VISUALS.get(c, "") for c in characters if c != "melody" and c in CHARACTER_VISUALS]
        scene_description = " and ".join(char_visuals) if char_visuals else "cute cartoon animals"
        scene_description += " in a cozy moonlit bedroom"

    scene = scene_description or "cute cartoon animals snuggled in a cozy moonlit bedroom"

    # FLUX anti-text strategy: DO NOT mention "text/words/letters" at all —
    # even negatively. Instead, describe ONLY visual elements.
    # Keep prompt short and purely visual.
    prompt = (
        f"Digital painting of {scene}, "
        f"soft pastel colors, warm glowing nightlight, "
        f"starry window, plush pillows, dreamy atmosphere, "
        f"children's picture book style, clean composition, "
        f"flat color background, minimalist"
    )
    truncated = prompt[:600]
    encoded = quote(truncated, safe="")
    url = (f"https://gen.pollinations.ai/image/{encoded}"
           f"?width=512&height=512&model=flux&nologo=true")

    headers = {}
    if POLLINATIONS_API_KEY:
        headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

    try:
        from PIL import Image
        with httpx.Client(timeout=120) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 1000:
                out_path = EPISODES_DIR / f"{episode_id}_cover.webp"
                img = Image.open(io.BytesIO(resp.content))
                img.save(str(out_path), "WEBP", quality=85)
                print(f"    ✓ Cover: {out_path.name}")
                return out_path
            else:
                print(f"    Cover generation failed: {resp.status_code}")
    except Exception as e:
        print(f"    Cover generation error: {e}")

    return None


# ═══════════════════════════════════════════════════════════════════
# Step 9: Generate Episodes
# ═══════════════════════════════════════════════════════════════════

def generate_episode(age_group: str, setup: str, characters: list,
                     params: dict = None) -> dict | None:
    """Generate one complete funny short episode.

    Args:
        age_group: "2-5", "6-8", or "9-12"
        setup: Episode premise/seed text
        characters: List of character names
        params: Full diversity params from select_episode_params(). If provided,
                all dimensions are injected into the prompt and saved in metadata.
    """
    ep_mood = params.get("mood") if params else None

    print(f"\n{'='*60}")
    print(f"Generating funny short for ages {age_group}")
    if params:
        print(f"  Dynamic: {params.get('dynamic')} | Topic: {params.get('topic')}")
        print(f"  Melody: {params.get('melody_role')} | Ending: {params.get('ending')}")
        if ep_mood:
            print(f"  Mood: {ep_mood}")
    print(f"{'='*60}")

    EPISODES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Generate script
    print("  [1/6] Generating script...")
    raw_response = generate_script(age_group, setup, characters, params=params)
    parsed = parse_funny_short(raw_response)

    print(f"  Title: {parsed['title']}")
    print(f"  Characters: {parsed['characters']}")
    print(f"  Segments: {len(parsed['segments'])}")

    # 2. Generate mood-specific comedy bed (unique per episode)
    print(f"  [2/6] Generating comedy bed (mood={ep_mood or 'generic'})...")
    bed_path = EPISODES_DIR / f"bed_{age_group}_{ep_mood or 'generic'}_{uuid.uuid4().hex[:4]}.wav"
    try:
        bed = generate_comedy_bed(mood=ep_mood)
        bed.export(str(bed_path), format="wav")
        print(f"    ✓ Comedy bed: {len(bed) / 1000:.0f}s")
    except Exception as e:
        print(f"    ✗ Comedy bed failed: {e}")
        bed_path = Path("/dev/null")  # Assembly handles missing bed gracefully

    # 3a. Generate context-aware SFX for this episode
    print("  [3/6] Generating context-aware SFX...")
    episode_sfx = generate_episode_sfx(parsed["segments"])
    print(f"    {len(episode_sfx)} context-aware SFX generated")

    # 3b. Generate TTS for all segments (SFX replaced by context-aware versions)
    print("  [4/6] Generating TTS...")
    audio_segments = generate_funny_short_tts(parsed["segments"], episode_sfx=episode_sfx)
    print(f"    {sum(1 for t, _, _ in audio_segments if t == 'audio')} voice segments, "
          f"{sum(1 for t, _, _ in audio_segments if t == 'sfx')} SFX, "
          f"{sum(1 for t, _, _ in audio_segments if t == 'pause')} pauses")

    # 5. Assemble
    print("  [5/6] Assembling...")
    intro_path = OUTPUT_DIR / "show_intro.mp3"
    outro_path = OUTPUT_DIR / "show_outro.mp3"

    if not intro_path.exists():
        # Winner: funny_2
        fallback = INTRO_DIR / "funny_2_intro.mp3"
        if fallback.exists():
            intro_path = fallback
            print(f"    Using funny_2 intro (winner)")
    if not outro_path.exists():
        fallback = INTRO_DIR / "funny_2_outro.mp3"
        if fallback.exists():
            outro_path = fallback
            print(f"    Using funny_2 outro (winner)")

    with_music, without_music = assemble_funny_short(
        audio_segments, bed_path, intro_path, outro_path,
    )

    episode_id = f"funny_{age_group.replace('-', '_')}_{uuid.uuid4().hex[:6]}"

    with_music.export(
        str(EPISODES_DIR / f"{episode_id}.mp3"),
        format="mp3", bitrate="128k",
    )
    without_music.export(
        str(EPISODES_DIR / f"{episode_id}_nomusic.mp3"),
        format="mp3", bitrate="128k",
    )
    print(f"    ✓ {episode_id}.mp3 ({len(with_music) / 1000:.0f}s)")
    print(f"    ✓ {episode_id}_nomusic.mp3 ({len(without_music) / 1000:.0f}s)")

    # 6. Generate cover
    print("  [6/6] Generating cover...")
    cover_path = generate_cover(parsed["title"], episode_id, characters=characters)

    # Save metadata — includes all diversity dimensions + mood for tracking
    metadata = {
        "id": episode_id,
        "title": parsed["title"],
        "content_type": "funny_short_v2",
        "age_group": age_group,
        "mood": ep_mood or "calm",
        "characters": characters,
        "character_combo": params.get("character_combo", characters) if params else characters,
        "dynamic": params.get("dynamic", "usual") if params else "usual",
        "topic": params.get("topic", "bedtime") if params else "bedtime",
        "melody_role": params.get("melody_role", "overheard") if params else "overheard",
        "ending": params.get("ending", "falls_asleep") if params else "falls_asleep",
        "audio_file": f"{episode_id}.mp3",
        "audio_url": f"/audio/funny-shorts/{episode_id}.mp3",
        "audio_file_nomusic": f"{episode_id}_nomusic.mp3",
        "cover_file": cover_path.name if cover_path else "",
        "sfx_count": len(episode_sfx),
        "duration_seconds": int(len(with_music) / 1000),
        "script": raw_response,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    meta_path = EPISODES_DIR / f"{episode_id}.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  ✓ {episode_id} complete!")
    return metadata


def generate_fresh_seed(params: dict) -> str:
    """Generate a fresh episode premise via Mistral AI using diversity params.

    Args:
        params: Full diversity params from select_episode_params()

    Returns:
        A 2-3 sentence premise string.
    """
    from mistralai import Mistral

    age_group = params["age_group"]
    characters = params["characters"]
    dynamic = params["dynamic"]
    topic = params["topic"]
    ending = params["ending"]

    # Load existing episode titles to avoid duplicates
    existing_titles = []
    data_dir = BACKEND_DIR / "data" / "funny_shorts"
    if data_dir.exists():
        for f in data_dir.glob("*.json"):
            try:
                meta = json.loads(f.read_text())
                existing_titles.append(meta.get("title", ""))
            except Exception:
                pass

    avoid = ""
    if existing_titles:
        avoid = f"\nExisting episode topics (yours MUST be different): {', '.join(existing_titles[-10:])}\n"

    char_names = [c for c in characters if c != "melody"]
    prompt = (
        f"Generate a funny bedtime short premise for ages {age_group}.\n"
        f"Characters: {', '.join(char_names)}\n"
        f"Dynamic: {dynamic} — {DYNAMIC_DESCRIPTIONS.get(dynamic, '')}\n"
        f"Topic: {topic}\n"
        f"Ending: {ENDING_DESCRIPTIONS.get(ending, '')}\n"
        f"{avoid}\n"
        f"Write ONLY a 2-3 sentence premise describing the situation and comedy escalation. "
        f"No script, no dialogue — just the setup. Keep it simple and funny. "
        f"The premise MUST be about {topic} and use the {dynamic} dynamic."
    )

    client = Mistral(api_key=MISTRAL_API_KEY)
    resp = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {"role": "system", "content": "You write comedy premises for children's bedtime audio shorts. Short, punchy, one situation."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.95,
        max_tokens=200,
    )

    setup = resp.choices[0].message.content.strip()
    print(f"  Fresh seed [{age_group}]: {setup[:80]}...")
    return setup


# ── Post-generation variety validation ──────────────────────────

# Lines containing these are SUPPOSED to repeat — skip in similarity checks
CATCHPHRASES = [
    "that was supposed to happen",
    "i said this would happen",
    "according to my calculations",
    "this is fine",
]


def extract_melody_lines(script: str) -> list:
    """Extract all Melody dialogue lines from a script."""
    lines = []
    for m in re.finditer(r'MELODY:\s*"?(.+?)"?\s*$', script, re.MULTILINE):
        line = m.group(1).strip().strip('"')
        # Skip empty / very short lines
        if len(line) > 10:
            lines.append(line)
    return lines


def validate_episode_variety(new_script: str, recent_episodes: list) -> tuple:
    """Check that non-catchphrase dialogue isn't repeating across episodes.

    Returns:
        (is_valid, detail_message)
    """
    new_melody = extract_melody_lines(new_script)
    if not new_melody:
        return True, "No melody lines found to compare"

    for recent in recent_episodes[-10:]:
        old_script = recent.get("script", "")
        old_melody = extract_melody_lines(old_script)

        for new_line in new_melody:
            if any(cp in new_line.lower() for cp in CATCHPHRASES):
                continue

            for old_line in old_melody:
                if any(cp in old_line.lower() for cp in CATCHPHRASES):
                    continue

                sim = SequenceMatcher(
                    None, new_line.lower(), old_line.lower()
                ).ratio()

                if sim > 0.5:
                    return False, (
                        f"Melody repeat: '{new_line[:50]}' ≈ '{old_line[:50]}' "
                        f"(sim={sim:.2f}, ep={recent.get('id', '?')})"
                    )

    return True, "OK"


def generate_all_episodes(fresh: bool = False, mood: str = None):
    """Generate 3 episodes (one per age group) with full diversity tracking.

    Args:
        fresh: Use Mistral to generate fresh seeds (vs hardcoded EPISODE_SEEDS).
        mood: Child's current mood — filters topics, dynamics, and character
              preference therapeutically. If None, no mood filtering is applied.
    """
    results = []
    existing = _load_existing_episodes()

    if not fresh:
        # Legacy mode: use hardcoded EPISODE_SEEDS
        for age_group, seed in EPISODE_SEEDS.items():
            try:
                result = generate_episode(
                    age_group, seed["setup"], seed["characters"],
                )
                if result:
                    results.append(result)
            except Exception as e:
                print(f"  ✗ FAILED for ages {age_group}: {e}")
                import traceback
                traceback.print_exc()
    else:
        # Diversity-tracked mode with mood filtering
        for age in ["2-5", "6-8", "9-12"]:
            print(f"\n  Selecting diverse params for {age} (mood={mood or 'none'})...")
            params = select_episode_params(existing, age_group=age, mood=mood)

            print(f"  → Dynamic: {params['dynamic']}, Topic: {params['topic']}")
            print(f"  → Characters: {params['characters']}")
            print(f"  → Melody role: {params['melody_role']}, Ending: {params['ending']}")
            if mood:
                print(f"  → Mood: {mood} → {MOOD_COMEDY_NEED.get(mood, '')}")

            print(f"\n  Generating fresh seed for {age}...")
            setup = generate_fresh_seed(params)

            # Generate episode with diversity params
            try:
                result = generate_episode(
                    age, setup, params["characters"], params=params,
                )
                if result:
                    # Validate variety against existing episodes
                    is_valid, detail = validate_episode_variety(
                        result.get("script", ""), existing,
                    )
                    if not is_valid:
                        print(f"  ⚠️  Variety check: {detail}")
                        print(f"  Regenerating with different params...")
                        # Change dynamic and topic (still mood-filtered), try once more
                        eligible_dynamics = MOOD_TO_DYNAMICS.get(mood, DYNAMICS) if mood else DYNAMICS
                        eligible_topics = MOOD_TO_TOPICS.get(mood, TOPICS) if mood else TOPICS
                        params["dynamic"] = _pick_avoiding_recent(
                            existing + [result], "dynamic", eligible_dynamics, recency=7)
                        params["topic"] = _pick_avoiding_recent(
                            existing + [result], "topic", eligible_topics, recency=7)
                        setup = generate_fresh_seed(params)
                        result = generate_episode(
                            age, setup, params["characters"], params=params,
                        )

                    if result:
                        results.append(result)
                        # Add to existing so next age group sees it
                        existing.append(result)
            except Exception as e:
                print(f"  ✗ FAILED for ages {age}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Generated {len(results)}/3 episodes")
    print(f"Files in: {EPISODES_DIR}")


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    valid_moods = list(MOOD_TO_TOPICS.keys())

    parser = argparse.ArgumentParser(
        description="Generate v2 funny short test episodes (calm comedy redesign)"
    )
    parser.add_argument("--sfx", action="store_true",
                        help="Generate SFX library (18 files)")
    parser.add_argument("--intro-outro", action="store_true",
                        help="Generate 5 intro/outro candidates")
    parser.add_argument("--episodes", action="store_true",
                        help="Generate 3 test episodes")
    parser.add_argument("--fresh", action="store_true",
                        help="Generate fresh episode seeds via Mistral (use with --episodes)")
    parser.add_argument("--mood", choices=valid_moods, default=None,
                        help="Child's mood — filters topics, dynamics, characters, "
                             "and comedy bed to be therapeutically appropriate. "
                             f"Choices: {', '.join(valid_moods)}")
    parser.add_argument("--all", action="store_true",
                        help="Run all steps in sequence")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files exist")
    args = parser.parse_args()

    if not any([args.sfx, args.intro_outro, args.episodes, args.all]):
        parser.print_help()
        sys.exit(1)

    if args.mood:
        print(f"\n🎭 Mood: {args.mood} → {MOOD_COMEDY_NEED.get(args.mood, '')}")

    if args.all or args.sfx:
        print("\n" + "=" * 60)
        print("STEP 1: Generating SFX Library")
        print("=" * 60)
        generate_sfx_library(force=args.force)

    if args.all or args.intro_outro:
        print("\n" + "=" * 60)
        print("STEP 2: Generating Intro/Outro Candidates")
        print("=" * 60)
        generate_intro_outro_candidates(force=args.force)

    if args.all or args.episodes:
        print("\n" + "=" * 60)
        print("STEP 3: Generating Test Episodes")
        print("=" * 60)
        generate_all_episodes(fresh=args.fresh or args.all, mood=args.mood)

    print("\nDone!")


if __name__ == "__main__":
    main()
