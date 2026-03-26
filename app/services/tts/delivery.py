"""Delivery Tag System — sentence-level emotional TTS param adjustment.

Every sentence in a script can have a [DELIVERY: tag1, tag2] marker that
describes HOW the character says the line. Tags are stripped before sending
to TTS and translated into exaggeration/speed multipliers for that sentence.

The result: delivery that changes sentence by sentence based on context,
creating emotional arcs that sound reactive and alive.
"""

import re
from typing import List, Optional


# ── Delivery Tag Dictionary ────────────────────────────────────────────
# Each tag specifies multipliers applied to the base voice params.
# Multiple tags multiply together. Result is clamped to safe ranges.

DELIVERY_PARAMS = {
    # Confidence spectrum
    "confident":        {"exag_mult": 1.15, "speed_mult": 1.05},
    "dismissive":       {"exag_mult": 0.90, "speed_mult": 1.08},
    "bluster":          {"exag_mult": 1.30, "speed_mult": 1.10},
    "triumphant":       {"exag_mult": 1.30, "speed_mult": 1.00},
    "smug":             {"exag_mult": 1.10, "speed_mult": 0.95},

    # Uncertainty spectrum
    "tentative":        {"exag_mult": 0.80, "speed_mult": 0.95},
    "caught off guard": {"exag_mult": 0.70, "speed_mult": 0.88},
    "scrambling":       {"exag_mult": 1.10, "speed_mult": 1.05},
    "defensive":        {"exag_mult": 1.20, "speed_mult": 1.02},
    "desperate":        {"exag_mult": 1.25, "speed_mult": 1.12},
    "stunned":          {"exag_mult": 0.50, "speed_mult": 0.75},

    # Interrogation spectrum
    "curious":          {"exag_mult": 0.90, "speed_mult": 0.95},
    "suspicious":       {"exag_mult": 0.85, "speed_mult": 0.92},
    "pointed":          {"exag_mult": 0.95, "speed_mult": 0.90},
    "pressing":         {"exag_mult": 1.00, "speed_mult": 0.95},
    "calm gotcha":      {"exag_mult": 0.75, "speed_mult": 0.85},
    "devastating":      {"exag_mult": 0.60, "speed_mult": 0.80},

    # Energy peaks
    "loud":             {"exag_mult": 1.35, "speed_mult": 1.08},
    "excited":          {"exag_mult": 1.25, "speed_mult": 1.10},
    "panicked":         {"exag_mult": 1.20, "speed_mult": 1.15},
    "outraged":         {"exag_mult": 1.30, "speed_mult": 1.05},
    "delighted":        {"exag_mult": 1.15, "speed_mult": 1.05},

    # Calm states
    "quiet":            {"exag_mult": 0.65, "speed_mult": 0.85},
    "deadpan":          {"exag_mult": 0.50, "speed_mult": 0.92},
    "unbothered":       {"exag_mult": 0.55, "speed_mult": 0.95},
    "ominous":          {"exag_mult": 0.70, "speed_mult": 0.82},
    "gentle":           {"exag_mult": 0.60, "speed_mult": 0.85},
    "wistful":          {"exag_mult": 0.65, "speed_mult": 0.82},
    "sleepy":           {"exag_mult": 0.45, "speed_mult": 0.78},

    # Storytelling states (narrator-specific)
    "conspiratorial":   {"exag_mult": 0.80, "speed_mult": 0.88},
    "wonder":           {"exag_mult": 0.90, "speed_mult": 0.85},
    "building":         {"exag_mult": 1.05, "speed_mult": 0.90},
    "revealing":        {"exag_mult": 0.85, "speed_mult": 0.82},
    "warm":             {"exag_mult": 0.75, "speed_mult": 0.88},
    "matter of fact":   {"exag_mult": 0.70, "speed_mult": 1.00},
}

# Safe ranges for Chatterbox
EXAG_MIN = 0.25
EXAG_MAX = 0.95
SPEED_MIN = 0.72
SPEED_MAX = 1.10

# Regex to match [DELIVERY: tag1, tag2] markers
_DELIVERY_RE = re.compile(
    r"\[DELIVERY:\s*([^\]]+)\]",
    re.IGNORECASE,
)


def parse_delivery_tags(text: str) -> List[str]:
    """Extract delivery tags from a line of text.

    Returns list of tag strings (lowercased, stripped).
    Example: "[DELIVERY: curious, tentative] Hello" -> ["curious", "tentative"]
    """
    match = _DELIVERY_RE.search(text)
    if not match:
        return []
    raw = match.group(1)
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def strip_delivery_tags(text: str) -> str:
    """Remove [DELIVERY: ...] markers from text before sending to TTS."""
    return _DELIVERY_RE.sub("", text).strip()


def apply_delivery(base_params: dict, delivery_tags: List[str]) -> dict:
    """Adjust base TTS params based on delivery tags.

    Multiple tags multiply together. Result is clamped to Chatterbox safe ranges.
    Returns a new dict — does not mutate base_params.
    """
    if not delivery_tags:
        return base_params.copy()

    adjusted = base_params.copy()
    exag_mult = 1.0
    speed_mult = 1.0

    for tag in delivery_tags:
        tag = tag.strip().lower()
        if tag in DELIVERY_PARAMS:
            d = DELIVERY_PARAMS[tag]
            exag_mult *= d["exag_mult"]
            speed_mult *= d["speed_mult"]

    adjusted["exaggeration"] = adjusted["exaggeration"] * exag_mult
    adjusted["speed"] = adjusted["speed"] * speed_mult

    # Clamp to Chatterbox safe ranges
    adjusted["exaggeration"] = max(EXAG_MIN, min(EXAG_MAX, adjusted["exaggeration"]))
    adjusted["speed"] = max(SPEED_MIN, min(SPEED_MAX, adjusted["speed"]))

    return adjusted


def should_apply_delivery(
    content_type: str,
    phase: int,
    sentence_index: int,
    total_phase_sentences: int,
) -> bool:
    """Determine if delivery tags should be applied for this sentence.

    - Funny shorts: always apply
    - Stories/long stories: Phase 1 only, skip last 20% for smooth Phase 2 transition
    - Poems: never (uses rhythmic cadence instead)
    """
    if content_type == "funny_short":
        return True

    if content_type in ("story", "long_story"):
        if phase != 1:
            return False

        # Phase 1: apply, but flatten in last 20%
        progress = sentence_index / max(total_phase_sentences - 1, 1)
        if progress > 0.80:
            return False

        return True

    return False


# ── Variable Sentence Gaps ─────────────────────────────────────────────
# Delivery tags inform gap timing between sentences.

DELIVERY_GAP_RULES = {
    # Tag on the CURRENT sentence -> gap AFTER this sentence
    "stunned":      600,
    "devastating":  550,
    "calm gotcha":  500,
    "revealing":    500,
    "building":     200,
    "panicked":     150,
    "scrambling":   150,
    "excited":      200,
}

# Tags on the NEXT sentence that affect the gap BEFORE it
_NEXT_SENTENCE_GAPS = {
    "caught off guard": 400,
    "stunned":          500,
}


def get_sentence_gap(
    current_sentence,
    next_sentence,
) -> int:
    """Determine the gap (ms) between two sentences based on delivery tags.

    current_sentence and next_sentence should have a .delivery_tags list
    and a .character string attribute. next_sentence may be None.
    """
    gap = 300  # default

    # Check current sentence's tags for "after" gaps
    if current_sentence.delivery_tags:
        for tag in current_sentence.delivery_tags:
            if tag in DELIVERY_GAP_RULES:
                gap = max(gap, DELIVERY_GAP_RULES[tag])

    # Check next sentence's tags for "before" gaps
    if next_sentence and next_sentence.delivery_tags:
        for tag in next_sentence.delivery_tags:
            if tag in _NEXT_SENTENCE_GAPS:
                gap = max(gap, _NEXT_SENTENCE_GAPS[tag])

    # Character switch always adds a base gap
    if next_sentence and current_sentence.character != next_sentence.character:
        gap = max(gap, 350)

    return gap
