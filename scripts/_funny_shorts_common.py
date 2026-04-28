"""Shared library for funny shorts generation pipeline.

See:
  ENGLISH_FUNNY_SHORTS_GUIDELINES.md
  HINDI_FUNNY_SHORTS_GUIDELINES.md
"""
from __future__ import annotations

import re
from typing import Iterable

# ────────────────────────────────────────────────────────────────────────
#  Approved audio tag vocabulary (§4 in both spec docs — identical)
# ────────────────────────────────────────────────────────────────────────

APPROVED_TAGS: set[str] = {
    "[curious]", "[suspicious]", "[serious]", "[shocked]",
    "[guilty]", "[innocent]", "[defensive]", "[proud]",
    "[grinning]", "[thoughtful]", "[panicking]", "[defeated]",
    "[playful]", "[mischievous]", "[matter-of-fact]", "[excited]",
    "[confused]", "[dramatic]", "[bored]", "[smug]",
    "[earnest]", "[skeptical]", "[tired]", "[hopeful]",
    "[disappointed]", "[delighted]", "[conspiratorial]", "[embarrassed]",
    "[long pause]", "[short pause]",
    "[laughs]", "[nervous laugh]", "[giggles]",
    "[gasp]", "[sigh]", "[hmm]",
    "[laughs together]", "[whispers]", "[shouts]",
    "[yawns]", "[singing]", "[humming]",
}

_APPROVED_TAGS_LOWER = {t.lower() for t in APPROVED_TAGS}

TAG_REGEX = re.compile(r"\[[^\]]+\]")


# ────────────────────────────────────────────────────────────────────────
#  Forbidden content (English-leaning; Hindi extends below)
# ────────────────────────────────────────────────────────────────────────

FORBIDDEN_WORDS_EN: list[str] = [
    "hershey", "oreo", "starbucks", "mcdonald", "coca",
    "stupid", "dummy", "weirdo", "idiot", "loser",
    "perhaps", "however", "indeed", "rather", "shall",
]

SETTLING_TAGS = (
    "[laughs together]", "[laughs]", "[grinning]", "[sigh]",
    "[yawns]", "[thoughtful]", "[hmm]", "[whispers]",
)
SETTLING_SOFT_WORDS_EN = ("yeah", "okay", "guess", "maybe", "fine")


# ────────────────────────────────────────────────────────────────────────
#  Hindi-specific rules
# ────────────────────────────────────────────────────────────────────────

LITERARY_HINDI: list[str] = [
    "nidra", "nakshatra", "shayan", "tandra", "pushp",
    "megh", "tatpashchat", "vidyalay",
]

DEITY_NAMES_HI: list[str] = [
    "bhagwaan", "ishvar", "deva ", "devi ", "lakshmi",
    "ganesh", "shiv", "krishn", "ram ", "hanuman",
    "durga", "saraswati", "vishnu", "kali",
    "allah", "khuda", "rabb", "yesu", "jesus",
]

RITUAL_VERBS_HI: list[str] = [
    "puja", "aarti", "prarthana", "bhajan karna",
    "yajna", "havan", "prasad", "bhog", "tilak",
    "darshan", "namaz", "ibadat",
]

RELIGIOUS_OBJECTS_HI: list[str] = [
    "mandir ke andar", "masjid ke andar", "gurudwara",
    "murti", "shankh",
]

FORBIDDEN_HI: list[str] = [
    "chamar", "bhangi", "madrasi", "gulti", "chinki",
    "motu", "lambu", "kalu", "kameena",
]

INDIAN_BRANDS: list[str] = [
    "parle", "cadbury", "hershey", "coca", "mcdonald",
    "oreo", "amul", "haldiram", "britannia",
]

OVER_USED_HI_PHRASES: list[str] = [
    "maa ko bataaunga", "maa ko bataaungi",
    "papa ko bataaunga", "papa ko bataaungi",
    "daadi aa gayi", "nani aa gayi",
    "tumhare gaal pe yeh laal kya hai",
    "chhupao chhupao", "chuglee karega",
]

SETTLING_SOFT_WORDS_HI = ("theek hai", "achha", "haan", "okay", "fine", "yaar")


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _word_count_text_only(text: str) -> int:
    """Count words ignoring audio tags."""
    bare = TAG_REGEX.sub("", text).strip()
    return len(bare.split()) if bare else 0


def _extract_first_tag(text: str) -> str | None:
    m = TAG_REGEX.search(text)
    return m.group(0) if m else None


def _detect_closing_pattern(inputs: list[dict]) -> str:
    """Categorize the closing line into a coarse pattern key."""
    if not inputs:
        return "unknown"
    last = inputs[-1].get("text", "").lower()
    if "[laughs together]" in last:
        return "laughs_together"
    if "[yawns]" in last:
        return "yawn"
    if "[sigh]" in last:
        return "sigh"
    if "[grinning]" in last:
        return "grinning"
    if "[whispers]" in last:
        return "whispers"
    if "[thoughtful]" in last or "[hmm]" in last:
        return "thoughtful_pause"
    if last.endswith("?"):
        return "open_question"
    return "soft_prose"


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s)


# ────────────────────────────────────────────────────────────────────────
#  Validator (§10 in both spec docs)
# ────────────────────────────────────────────────────────────────────────

def validate_funny_short(
    script: dict,
    recent_shorts: list[dict],
    lang: str,
) -> list[str]:
    """Validate a funny short script.

    Args:
      script: script dict with title, inputs[], comedic_device, ...
      recent_shorts: last N published shorts of same lang for diversity checks.
      lang: 'en' or 'hi'.

    Returns:
      List of error strings (empty if valid).
    """
    errors: list[str] = []
    inputs = script.get("inputs", [])
    text_full = " ".join(inp.get("text", "").lower() for inp in inputs)

    # — Voices A and B both present —
    voices = {inp.get("voice") for inp in inputs}
    if voices != {"A", "B"}:
        errors.append("Must have exactly voices A and B")

    # — Line count 6–20 —
    if len(inputs) < 6 or len(inputs) > 20:
        errors.append(f"Line count {len(inputs)} out of 6-20 range")

    # — Per-line ≤12 words —
    for i, inp in enumerate(inputs):
        if _word_count_text_only(inp.get("text", "")) > 12:
            errors.append(f"Line {i}: too many words")

    # — Total chars ≤500 —
    total_chars = sum(len(inp.get("text", "")) for inp in inputs)
    if total_chars > 500:
        errors.append(f"Too long: {total_chars} chars")

    # — Tag whitelist —
    for i, inp in enumerate(inputs):
        for tag in TAG_REGEX.findall(inp.get("text", "")):
            if tag.lower() not in _APPROVED_TAGS_LOWER:
                errors.append(f"Line {i}: unapproved tag {tag}")

    # — Hindi-only: Devanagari rejection —
    if lang == "hi":
        if _has_devanagari(script.get("title", "")):
            errors.append("Devanagari in 'title'")
        for i, inp in enumerate(inputs):
            if _has_devanagari(inp.get("text", "")):
                errors.append(f"Line {i}: Devanagari detected")
        if not script.get("title_en"):
            errors.append("Missing title_en")

    # — Anti-template: opening tag (last 3) —
    if inputs:
        opening = _extract_first_tag(inputs[0].get("text", ""))
        recent_openings = [s.get("opening_tag") for s in recent_shorts[-3:]]
        if opening and recent_openings.count(opening) >= 2:
            errors.append(f"Opening tag {opening} used in 2+ of last 3 shorts")

    # — Anti-template: comedic device (last 5) —
    device = script.get("comedic_device")
    recent_devices = [s.get("comedic_device") for s in recent_shorts[-5:]]
    if device and recent_devices.count(device) >= 2:
        errors.append(f"Comedic device {device} used 2+ in last 5 shorts")

    # — Anti-template: setting (last 3) —
    setting = script.get("setting")
    recent_settings = [s.get("setting") for s in recent_shorts[-3:]]
    if setting and recent_settings.count(setting) >= 2:
        errors.append(f"Setting '{setting}' used in 2+ of last 3 shorts")

    # — Anti-template: closing pattern (last 10) —
    closing = _detect_closing_pattern(inputs)
    recent_closings = [s.get("closing_pattern") for s in recent_shorts[-10:]]
    if recent_closings.count(closing) >= 4:
        errors.append(f"Closing pattern {closing} used 4+ times in last 10")

    # — Anti-template: character age dynamic (last 3) —
    age_dyn = script.get("character_age_dynamic")
    recent_age_dyns = [s.get("character_age_dynamic") for s in recent_shorts[-3:]]
    if age_dyn and recent_age_dyns.count(age_dyn) >= 2:
        errors.append(f"Character age dynamic '{age_dyn}' used in 2+ of last 3 shorts")

    # — Required opening tag enforcement (anti-template §3.5) —
    required_opening = script.get("required_opening_tag")
    if required_opening and required_opening not in (None, "(no tag — start mid-thought)"):
        actual_opening = _extract_first_tag(inputs[0].get("text", "")) if inputs else None
        if actual_opening != required_opening:
            errors.append(
                f"Required opening tag {required_opening}, got {actual_opening}"
            )

    # — Forbidden words (lang-specific) —
    forbidden = list(FORBIDDEN_WORDS_EN)
    if lang == "hi":
        forbidden += FORBIDDEN_HI + INDIAN_BRANDS
    for word in forbidden:
        if word in text_full:
            errors.append(f"Forbidden word: '{word}'")

    # — Hindi-only: literary register —
    if lang == "hi":
        for word in LITERARY_HINDI:
            if word in text_full:
                errors.append(f"Literary Hindi: '{word}'")

    # — Hindi-only: religious content —
    if lang == "hi":
        for word in DEITY_NAMES_HI + RITUAL_VERBS_HI + RELIGIOUS_OBJECTS_HI:
            if word in text_full:
                errors.append(f"Religious content: '{word}'")

    # — Hindi-only: over-used phrase frequency in last 10 —
    if lang == "hi":
        for phrase in OVER_USED_HI_PHRASES:
            if phrase in text_full:
                recent_uses = sum(
                    1 for s in recent_shorts[-10:]
                    if phrase in " ".join(
                        inp.get("text", "").lower() for inp in s.get("inputs", [])
                    )
                )
                if recent_uses >= 3:
                    errors.append(
                        f"Over-used phrase '{phrase}' ({recent_uses}+ in last 10)"
                    )

    # — Bedtime-settled ending —
    if inputs:
        last_line = inputs[-1].get("text", "").lower()
        if not any(t in last_line for t in SETTLING_TAGS):
            soft = SETTLING_SOFT_WORDS_EN if lang == "en" else (
                SETTLING_SOFT_WORDS_EN + SETTLING_SOFT_WORDS_HI
            )
            if not any(w in last_line for w in soft):
                errors.append("Final line not bedtime-settled")

    # — Title length —
    if len(script.get("title", "")) > 30:
        errors.append("Title too long")

    return errors


# ────────────────────────────────────────────────────────────────────────
#  Voice library (resolved IDs from ElevenLabs shared marketplace)
# ────────────────────────────────────────────────────────────────────────

VOICE_LIBRARY_EN: dict[str, str] = {
    "mini":           "hO2yZ8lxM3axUxL8OeKX",  # Lively cute young female
    "jerry":          "MDLAMJ0jxkpYkjXbmG4t",  # Jolly Santa Claus
    "suhana":         "9vP6R7VVxNwGIGLnpl17",  # Very young & joyful narrator
    "tashi":          "YIXhzp6l2M0ddzOGIbJ3",  # Expressive Hindi-kids narrator (English variant)
    "monika_creepy":  "6aO1exAR9bDruq155LzQ",  # Sinister creepy
    "leo":            "UKvDHTUpXOC66VwQ3n2w",  # Calm yet firm recovery agent
}

VOICE_LIBRARY_HI: dict[str, str] = {
    "bunty":          "7b9mYhmnp0y2qSH1FnBL",  # Funny best friend
    "anika":          "Sm1seazb4gs7RSlUVw7c",  # Animated, friendly and engaging
    "riya":           "4RloeZf2FRvGiu4uoKOf",  # Children storytelling
    "kiran":          "ss0PMu3rEfIwrYgOOl5S",  # Very young, cute & engaging
    "gappu":          "psk8YLODv4ETdKheNwwz",  # Kids cartoon character voice
    "gappu_bhai":     "tBPQ3sUKpdLEVpyeCHyk",  # Lazy cartoon voice
}

APPROVED_PAIRINGS_EN: list[tuple[str, str]] = [
    ("mini", "leo"),                    # bright + dry
    ("suhana", "monika_creepy"),        # innocent + sinister (contrast)
    ("jerry", "mini"),                  # jolly + cheeky
    ("tashi", "leo"),                   # expressive + steady
    ("suhana", "jerry"),                # young + jolly
    ("mini", "tashi"),                  # lively + dramatic
    ("monika_creepy", "leo"),           # sinister + steady
    ("tashi", "suhana"),                # dramatic + innocent
]

APPROVED_PAIRINGS_HI: list[tuple[str, str]] = [
    ("bunty", "kiran"),
    ("anika", "gappu"),
    ("riya", "gappu_bhai"),
    ("kiran", "gappu"),
    ("bunty", "anika"),
    ("riya", "kiran"),
    ("gappu", "gappu_bhai"),
    ("bunty", "gappu_bhai"),
]


# ────────────────────────────────────────────────────────────────────────
#  Sampler axes (§3.5 in both spec docs)
# ────────────────────────────────────────────────────────────────────────

OPENING_TAGS: list[str | None] = [
    "[curious]", "[matter-of-fact]", "[excited]", "[whispers]",
    "[thoughtful]", "[grinning]", "[confused]", "[serious]",
    "[sigh]", "[singing]", None,  # None = no-tag opener (in-medias-res)
]

COMEDIC_DEVICES: list[str] = [
    "conflict_turn_taking", "conflict_ownership", "conflict_fairness",
    "discovery_weird_object", "discovery_misremembered", "discovery_old_artifact",
    "pretend_play_grownup", "pretend_play_animal", "pretend_play_news_anchor",
    "earnest_vs_skeptical", "wildly_wrong_explanation", "deadpan_absurd",
    "negotiation_trade", "mock_philosophical_debate", "absurd_ranking",
    "observation_quiet", "observation_what_if", "comparing_experiences",
    "surreal_grounded", "casual_acceptance_absurd",
    "misunderstanding_word", "diverging_conversation",
]

CHARACTER_AGE_DYNAMICS: list[str] = [
    "siblings", "cousins", "best friends", "classmates", "neighbors",
    "older-younger pair", "twin energy",
]

EMOTIONAL_DYNAMICS_EN: list[str] = [
    "one earnest, one skeptical",
    "both excited about different things",
    "both very serious about something silly",
    "one trying to convince, one resisting",
    "both reacting to a third unseen thing",
    "one explaining, one questioning",
    "both equally confused, working it out",
    "one curious, one already knows",
    "one teaching, one teasing",
    "one defensive, one accusing",
    "both bored, becoming silly",
    "one tired, one wired",
    "both pretending something",
    "both observing the same thing differently",
]

EMOTIONAL_DYNAMICS_HI: list[str] = [
    "ek earnest, doosra skeptical",
    "dono alag alag cheez ke baare mein excited",
    "dono kisi silly cheez ko bahut serious le rahe hain",
    "ek convince karne ki koshish, doosra resist kar raha",
    "dono kisi teesri unseen cheez pe react kar rahe",
    "ek samjha raha, doosra sawal pooch raha",
    "dono confused, saath mein figure out kar rahe",
    "ek curious, doosre ko already pata hai",
    "ek teach kar raha, doosra tease kar raha",
    "ek defensive, doosra accusing",
    "dono bored, silly hone lage",
    "ek thaka, doosra wired",
    "dono kuch pretend kar rahe",
    "dono ek hi cheez alag alag tarike se observe kar rahe",
]

SETTINGS_EN: list[str] = [
    "kitchen", "bedroom", "backyard", "school cafeteria",
    "playground", "back of a car", "couch fort", "bathtub",
    "treehouse", "library corner", "park bench", "kitchen table",
    "bus stop", "doctor's waiting room", "supermarket aisle",
    "during a thunderstorm", "while waiting for dinner",
    "during a long car ride", "on a swing", "under a blanket",
]

SETTINGS_HI: list[str] = [
    "kitchen", "drawing room", "bedroom", "balcony",
    "school cafeteria", "playground", "auto rickshaw",
    "market", "school bus stop", "nani-ke-ghar",
    "during a power cut", "during monsoon rain",
    "Sunday morning", "while waiting for dinner",
    "during a long car ride", "on a swing", "under a quilt",
    "in the back seat of a car", "rooftop after dark",
]

TONES: list[str] = [
    "deadpan", "energetic", "whispered", "mock-serious",
    "rambling", "fast", "slow-burn", "interrupting each other",
    "long pauses", "rapid-fire", "one-sided", "balanced",
]


# ────────────────────────────────────────────────────────────────────────
#  Sampler functions
# ────────────────────────────────────────────────────────────────────────

import random


def sample_axis_excluding_recent(
    options: list,
    recent: list,
    exclude_n: int,
    seed: int | None = None,
):
    """Sample from `options` excluding the last `exclude_n` items in `recent`.

    Falls back to least-recently-used choice if everything is excluded.
    """
    rng = random.Random(seed)
    excluded = set(recent[-exclude_n:]) if recent else set()
    eligible = [o for o in options if o not in excluded]
    if eligible:
        return rng.choice(eligible)
    by_recency: dict = {}
    for i, item in enumerate(recent):
        by_recency[item] = i
    candidates = sorted(options, key=lambda o: by_recency.get(o, -1))
    return candidates[0]


def sample_voice_pair(
    pairings: list[tuple[str, str]],
    recent_pairs: list[tuple[str, str]],
    seed: int | None = None,
) -> tuple[str, str]:
    """Pick a voice pair excluding the last 3 used."""
    rng = random.Random(seed)
    recent_set = {tuple(p) for p in recent_pairs[-3:]}
    eligible = [p for p in pairings if tuple(p) not in recent_set]
    return rng.choice(eligible) if eligible else rng.choice(pairings)
