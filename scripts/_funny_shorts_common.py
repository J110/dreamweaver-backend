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

# Tags that produce REAL non-verbal audio when used standalone (tag-only line).
# v3 renders these as actual sound events (laughter, gasps, sighs).
LAUGHTER_TAGS = ("[laughs together]", "[laughs]", "[nervous laugh]", "[giggles]")

# Standalone tag-only lines that are valid as a final closing beat.
PREFERRED_FINAL_STANDALONE = ("[laughs together]", "[laughs]")
ACCEPTABLE_FINAL_STANDALONE = ("[sigh]", "[yawns]", "[thoughtful]")


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


def _has_standalone_laughter_line(inputs: list[dict]) -> bool:
    """True iff at least one input line is a tag-only laughter line.

    v3 renders standalone tags as actual non-verbal sound events. Without
    one of these, a 'funny' short never produces real laugh audio.
    """
    for inp in inputs:
        text = (inp.get("text") or "").strip()
        if text in LAUGHTER_TAGS:
            return True
    return False


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

    # — Standalone laughter line required (real audio event, not inflected delivery) —
    if not _has_standalone_laughter_line(inputs):
        errors.append(
            "Must include >=1 standalone laughter tag line (tag-only, no text — "
            f"one of {list(LAUGHTER_TAGS)})"
        )

    # — Final line: must be standalone laughter / settling tag, or soft-prose closing —
    if inputs:
        last_line_raw = (inputs[-1].get("text") or "").strip()
        last_line_lower = last_line_raw.lower()
        if last_line_raw in PREFERRED_FINAL_STANDALONE:
            pass  # ideal
        elif last_line_raw in ACCEPTABLE_FINAL_STANDALONE:
            pass  # acceptable settling-tag fallback
        else:
            soft = SETTLING_SOFT_WORDS_EN if lang == "en" else (
                SETTLING_SOFT_WORDS_EN + SETTLING_SOFT_WORDS_HI
            )
            if not any(w in last_line_lower for w in soft):
                errors.append(
                    f"Final line must be standalone {list(PREFERRED_FINAL_STANDALONE)} "
                    f"or {list(ACCEPTABLE_FINAL_STANDALONE)} or soft-prose closing — "
                    f"got: {last_line_raw!r}"
                )

    # — Title length —
    if len(script.get("title", "")) > 30:
        errors.append("Title too long")

    return errors


# ────────────────────────────────────────────────────────────────────────
#  Voice library (resolved IDs from ElevenLabs shared marketplace)
# ────────────────────────────────────────────────────────────────────────

VOICE_LIBRARY_EN: dict[str, str] = {
    "mini":      "hO2yZ8lxM3axUxL8OeKX",  # Lively cute young female
    "katherine": "342hpGp7PKo7DsTTVSdr",  # Eccentric Mad Scientist
    "suhana":    "9vP6R7VVxNwGIGLnpl17",  # Very young & joyful narrator
    "tashi":     "YIXhzp6l2M0ddzOGIbJ3",  # Expressive Hindi-kids narrator (English variant)
    "kiran_en":  "o80picuztV1xYiPeIrpa",  # Very young adorable story narrator
    "omar":      "S7IsvAvEoDfui6GSZK3A",  # Very young storyteller
}

VOICE_LIBRARY_HI: dict[str, str] = {
    "omar_hi":    "srEfhy4AF67Mw9SpTVFd",  # Energetic, engaging, animated
    "suhana_hi":  "A2VREc2wjqtSZloENLHe",  # Very young & expressive narrator
    "riya":       "4RloeZf2FRvGiu4uoKOf",  # Children storytelling
    "kiran":      "ss0PMu3rEfIwrYgOOl5S",  # Very young, cute & engaging
    "gappu":      "psk8YLODv4ETdKheNwwz",  # Kids cartoon character voice
    "gappu_bhai": "tBPQ3sUKpdLEVpyeCHyk",  # Lazy cartoon voice
}

APPROVED_PAIRINGS_EN: list[tuple[str, str]] = [
    ("mini", "omar"),
    ("suhana", "tashi"),
    ("katherine", "suhana"),
    ("omar", "kiran_en"),
    ("mini", "tashi"),
    ("kiran_en", "omar"),
    ("suhana", "omar"),
    ("katherine", "mini"),
]

APPROVED_PAIRINGS_HI: list[tuple[str, str]] = [
    ("omar_hi", "kiran"),
    ("suhana_hi", "gappu"),
    ("riya", "gappu_bhai"),
    ("omar_hi", "suhana_hi"),
    ("kiran", "gappu"),
    ("riya", "kiran"),
    ("gappu", "gappu_bhai"),
    ("omar_hi", "gappu_bhai"),
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


# ────────────────────────────────────────────────────────────────────────
#  Mistral prompt builder (§8 in both spec docs)
# ────────────────────────────────────────────────────────────────────────

_APPROVED_TAGS_LIST = ", ".join(sorted(APPROVED_TAGS))


_EN_TEMPLATE = """You are writing a 60-second comedic dialogue between two child characters
for a bedtime app. The dialogue should make a kid laugh, then settle.

You have full creative freedom WITHIN these constraints:
- Exactly two characters speaking, no narrator
- 6-20 dialogue lines total (vary the length — short shorts are good)
- Max 12 words per line
- Total STRICTLY under 500 characters across all lines combined.
  AIM for 350-450 chars (count carefully — going over 500 is rejected).
- Use audio tags ONLY from this list: {approved_tags}

AUDIO TAG USAGE — TWO PATTERNS (this is the most important section):

1. INLINE with text — inflects delivery only.
   Example: "[curious] Where did my chips go?"
   The voice speaks the words with curiosity. NO non-verbal sound is produced.

2. TAG-ONLY line (no text) — renders as REAL non-verbal audio.
   Example: a line whose text is exactly "[laughs together]" with no words after.
   v3 produces actual shared-laughter audio at that point in the dialogue.

REQUIRED:
- Include AT LEAST 2 standalone tag-only lines per short. These are
  real audio events: actual laughter, gasps, sighs, real reactions.
  Without these, the short has zero non-verbal sound and feels flat.
- The FINAL LINE must be a standalone laughter tag — most often
  "[laughs together]" but "[laughs]" alone also works.
- Don't write "haha" or "ha ha" in any line — use a standalone
  laughter tag instead.
- A standalone-tag line counts as ~1 line in your line budget.

Why this matters: tag-only lines produce real audio events. Inline
tags only inflect spoken text. A funny short without standalone tags
has no actual laugh sounds — it just sounds like dialogue.

WHAT YOU MUST AVOID:
- Repeating the comedic structure of recent funny shorts (listed below)
- Starting with [curious] unless the orchestrator chose it
- Defaulting to "A accuses → B denies → evidence" pattern
- Using the same opening tag as the last 3 shorts
- Predictable structures — surprise is funnier than formula

CHARACTER VOICES:
A: {voice_a_label} — {voice_a_personality}
B: {voice_b_label} — {voice_b_personality}

THIS SHORT'S CREATIVE PARAMETERS:
- Comedic device: {comedic_device}
- Emotional dynamic: {emotional_dynamic}
- Setting: {setting}
- Tone: {tone}
- Character age dynamic: {character_age_dynamic}
- Required opening tag: {required_opening_tag}
  (use this exactly as your first tag — diversity enforcement)

RECENT FUNNY SHORTS TO NOT REPEAT:
{recent_shorts_summary}

WHAT MAKES KIDS ACTUALLY LAUGH:
- Specific concrete details over generic ones
- Surprising small reactions over big dramatic ones
- One character earnest while the other is skeptical
- Logic taken too seriously about silly things
- A kid stating an obvious thing as if it's profound
- An adult-style argument about kid stuff
- Misunderstanding the listener catches before the characters do
- The conversation veering somewhere unexpected
- A small detail in the world becoming the whole point

WHAT FALLS FLAT:
- Setup → punchline structure (kids' comedy is conversational)
- Big reactions to small things (unless that's the point)
- Forced "lessons" or morals
- Adult-style wit
- Sarcasm directed at the listener

OUTPUT FORMAT (JSON):
{{
  "title": "evocative title under 5 words",
  "comedic_device_used": "{comedic_device}",
  "inputs": [
    {{"voice": "A" or "B", "text": "line with audio tags inline"}}
  ],
  "cover_context": "one sentence describing a dreamy visual"
}}

Just the JSON. No commentary."""


_HI_TEMPLATE = """You are writing a 60-second comedic Hindi dialogue between two Indian
child characters for a bedtime app. The dialogue should make an Indian
kid laugh, then settle.

ROMAN HINDI ONLY:
Write all dialogue in Roman script. Not Devanagari.
"Mujhe chips chahiye" — Roman only, never Devanagari.
Audio tags stay in English (delivery cues, not text).

CONVERSATIONAL REGISTER:
Bolchaal ki Hindi — way Indian siblings actually talk.
Hinglish is natural — "school", "phone", "okay", "actually",
"literally", "homework", "cousin" all stay in English.
"Tum" between characters (kids don't use formal aap).
NEVER literary Hindi: nidra, nakshatra, shayan, pushp, van.

You have full creative freedom WITHIN these constraints:
- Exactly two characters speaking, no narrator
- 6-20 dialogue lines total (vary the length)
- Max 12 words per line
- Total STRICTLY under 500 characters across all lines combined.
  AIM for 350-450 chars (count carefully — going over 500 is rejected).
- Use audio tags ONLY from this list: {approved_tags}

AUDIO TAG USAGE — TWO PATTERNS (this is the most important section):

1. INLINE with text — inflects delivery only.
   Example: "[curious] Mere chips kahaan gaye?"
   The voice speaks the words with curiosity. NO non-verbal sound is produced.

2. TAG-ONLY line (no text) — renders as REAL non-verbal audio.
   Example: a line whose text is exactly "[laughs together]" with no words after.
   v3 produces actual shared-laughter audio at that point in the dialogue.

REQUIRED:
- Include AT LEAST 2 standalone tag-only lines per short — real audio
  events (actual laughter, gasps, sighs, real reactions). Without
  these, the short has zero non-verbal sound and feels flat.
- The FINAL LINE must be a standalone laughter tag — most often
  "[laughs together]" but "[laughs]" alone also works.
- Don't write "haha", "ha ha", or "hehe" — use a standalone
  laughter tag instead.

Why this matters: tag-only lines produce real audio events. Inline
tags only inflect spoken text. Hindi listeners notice this even more —
real laugh audio is what makes the short land as funny.

WHAT YOU MUST AVOID:
- Repeating the comedic structure of recent shorts (listed below)
- Defaulting to "chips ka theft" / "Maa ko bataaunga" pattern
- Starting with [curious] unless required
- Using over-used Hindi tropes that appeared in recent shorts
- Predictable structures

NO RELIGIOUS CONTENT:
No deity names, no puja/aarti/prasad, no ritual references.
Festival mentions atmospheric only.

NO CASTE OR REGIONAL STEREOTYPES:
No surname jokes, no Bihari/Punjabi/Madrasi humor, no body-shaming
("motu", "lambu" forbidden).

NO BRANDS OR CELEBRITIES:
"Biscuit" not "Parle-G", "chocolate" not "Cadbury", no cricketers,
no film stars, no YouTubers.

CHARACTER VOICES:
A: {voice_a_label} — {voice_a_personality}
B: {voice_b_label} — {voice_b_personality}

THIS SHORT'S CREATIVE PARAMETERS:
- Comedic device: {comedic_device}
- Emotional dynamic: {emotional_dynamic}
- Setting: {setting}
- Tone: {tone}
- Character age dynamic: {character_age_dynamic}
- Required opening tag: {required_opening_tag}

RECENT HINDI FUNNY SHORTS TO NOT REPEAT:
{recent_shorts_summary}

OVER-USED HINDI PHRASES TO AVOID THIS WEEK:
{over_used_phrases_to_avoid}

WHAT MAKES INDIAN KIDS LAUGH:
- Specific Indian-household details (ceiling fan, pressure cooker
  whistle, mosquito coil, chappal arrangement) used as comedic detail
- Sibling dynamics every Indian kid recognizes
- Mock-serious philosophical debates about silly things
- One kid earnest, other skeptical
- Hinglish naturally mixed
- Surprise reactions to small Indian-life moments

WHAT FALLS FLAT:
- Translated English humor
- Setup-punchline structure
- Forced Hinglish
- Tropes used in EVERY short (chips ka theft, Maa ko bataaunga)
- Adult sarcasm
- Bollywood references

OUTPUT FORMAT (JSON):
{{
  "title": "evocative Roman Hindi title under 5 words",
  "title_en": "English translation for tooling",
  "comedic_device_used": "{comedic_device}",
  "inputs": [
    {{"voice": "A" or "B", "text": "line with audio tags inline"}}
  ],
  "cover_context": "one English sentence describing a dreamy Indian visual"
}}

Just the JSON. No commentary."""


# ────────────────────────────────────────────────────────────────────────
#  ElevenLabs v3 Text-to-Dialogue + sting frame assembler
# ────────────────────────────────────────────────────────────────────────

import io
import os
from pathlib import Path

ELEVENLABS_V3_URL = "https://api.elevenlabs.io/v1/text-to-dialogue"

ELEVENLABS_V3_FUNNY_SHORT_SETTINGS = {
    "stability": 0.4,
    "similarity_boost": 0.75,
    "style": 0.5,
    "use_speaker_boost": True,
}


def render_dialogue_v3(
    inputs: list[dict],
    voice_a_id: str,
    voice_b_id: str,
    api_key: str | None = None,
    timeout: float = 90.0,
) -> bytes:
    """Call ElevenLabs v3 Text-to-Dialogue and return MP3 bytes."""
    import httpx

    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        # Fallback to baked default in _elevenlabs_common.py
        try:
            from _elevenlabs_common import ELEVENLABS_API_KEY  # type: ignore
        except ImportError:
            from scripts._elevenlabs_common import ELEVENLABS_API_KEY  # type: ignore
        api_key = ELEVENLABS_API_KEY

    payload_inputs = [
        {
            "text": line["text"],
            "voice_id": voice_a_id if line["voice"] == "A" else voice_b_id,
        }
        for line in inputs
    ]
    body = {
        "inputs": payload_inputs,
        "model_id": "eleven_v3",
        "settings": ELEVENLABS_V3_FUNNY_SHORT_SETTINGS,
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            ELEVENLABS_V3_URL,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        return r.content


def frame_dialogue_with_stings(
    dialogue_bytes: bytes,
    intro_sting_path: Path | str,
    outro_sting_path: Path | str,
    gap_ms: int = 1000,
) -> bytes:
    """Assemble final MP3: intro + silence + dialogue + silence + outro."""
    from pydub import AudioSegment

    intro_p = Path(intro_sting_path)
    outro_p = Path(outro_sting_path)
    if not intro_p.exists():
        raise FileNotFoundError(f"Intro sting missing at {intro_p}")
    if not outro_p.exists():
        raise FileNotFoundError(f"Outro sting missing at {outro_p}")

    intro = AudioSegment.from_mp3(str(intro_p))
    outro = AudioSegment.from_mp3(str(outro_p))
    dialogue = AudioSegment.from_mp3(io.BytesIO(dialogue_bytes))

    silence = AudioSegment.silent(
        duration=gap_ms,
        frame_rate=dialogue.frame_rate or 44100,
    )

    full = intro + silence + dialogue + silence + outro

    out = io.BytesIO()
    full.export(out, format="mp3", bitrate="192k")
    return out.getvalue()


def build_prompt(
    *,
    lang: str,
    voice_a_label: str,
    voice_a_personality: str,
    voice_b_label: str,
    voice_b_personality: str,
    comedic_device: str,
    emotional_dynamic: str,
    setting: str,
    tone: str,
    required_opening_tag: str | None,
    recent_shorts_summary: str,
    over_used_phrases_to_avoid: str,
    character_age_dynamic: str = "siblings",
) -> str:
    """Build the Mistral system prompt per spec §8."""
    template = _HI_TEMPLATE if lang == "hi" else _EN_TEMPLATE
    opening = required_opening_tag if required_opening_tag else "(no tag — start mid-thought)"
    return template.format(
        approved_tags=_APPROVED_TAGS_LIST,
        voice_a_label=voice_a_label,
        voice_a_personality=voice_a_personality,
        voice_b_label=voice_b_label,
        voice_b_personality=voice_b_personality,
        comedic_device=comedic_device,
        emotional_dynamic=emotional_dynamic,
        setting=setting,
        tone=tone,
        character_age_dynamic=character_age_dynamic,
        required_opening_tag=opening,
        recent_shorts_summary=recent_shorts_summary,
        over_used_phrases_to_avoid=over_used_phrases_to_avoid or "(none)",
    )
