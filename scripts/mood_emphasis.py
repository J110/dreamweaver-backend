"""Sentence-level mood emphasis system for TTS audio generation.

IMPORTANT: Chatterbox TTS cannot handle word-level emphasis. Isolating a
single word like "SPLAT" and generating it with different TTS params causes
hallucination — the model needs full sentence context.

This system works at SENTENCE granularity: entire sentences containing
mood-critical words get different TTS params. The keyword dictionaries
detect WHICH sentences deserve emphasis, not which words to isolate.

- Wired: sentences with comic punch words (SPLAT, BONK) get high exaggeration
- Sad: sentences with heavy words (alone, gone) get low, weighted delivery
- Anxious: fear sentences (dark, shadow) hushed; safety sentences (safe, singing) warm
- Angry: sentences with sharp words (THREW, stomped) get emphatic delivery
- Curious: sentences with wonder words (glowing, hidden) get brighter delivery
- Calm: sentences with melt words (soft, warm) get extra-soft delivery

Usage:
    from mood_emphasis import (
        chunk_with_sentence_emphasis, should_apply_emphasis,
        MOOD_EMPHASIS_PARAMS, clamp_emphasis_exaggeration,
    )
"""

import re
from typing import Dict, List


# ── Per-mood TTS parameters for emphasis SENTENCES ───────────────────
# Moderated for sentence-level — less aggressive than word-level would be,
# because the entire sentence gets these params, not just a single word.
MOOD_EMPHASIS_PARAMS: Dict[str, dict] = {
    "wired": {
        # Whole sentence gets comic energy
        "exaggeration": 0.75,
        "cfg_weight": 0.55,
        "speed_multiplier": 0.92,
    },
    "curious": {
        # Whole sentence gets wonder lift
        "exaggeration": 0.58,
        "cfg_weight": 0.42,
        "speed_multiplier": 0.92,
    },
    "calm": {
        # Whole sentence melts
        "exaggeration": 0.18,
        "cfg_weight": 0.18,
        "speed_multiplier": 0.82,
    },
    "sad": {
        # Whole sentence gets weight
        "exaggeration": 0.22,
        "cfg_weight": 0.22,
        "speed_multiplier": 0.85,
    },
    "anxious": {
        # Two sub-types: fear sentences (hushed) and safety sentences (warm)
        "fear": {
            "exaggeration": 0.20,
            "cfg_weight": 0.18,
            "speed_multiplier": 0.88,
        },
        "safety": {
            "exaggeration": 0.48,
            "cfg_weight": 0.38,
            "speed_multiplier": 0.95,
        },
    },
    "angry": {
        # Whole sentence gets emphatic energy
        "exaggeration": 0.72,
        "cfg_weight": 0.50,
        "speed_multiplier": 1.02,
    },
}

# ── Keyword dictionary per mood ──────────────────────────────────────
# Used to detect which SENTENCES deserve emphasis delivery.
# If a sentence contains any keyword (or matches a pattern), the
# entire sentence is flagged for emphasis TTS params.
MOOD_KEYWORDS: Dict[str, dict] = {
    "wired": {
        "patterns": [
            r'[A-Z]{3,}',           # ALL CAPS words (SPLAT, BONK, CRASH)
            r'(\w)\1{2,}',          # repeated letters (sooooo, veeeery)
        ],
        "words": [
            "splat", "bonk", "crash", "whoosh", "plop", "splash",
            "bang", "boing", "squish", "pop", "oh no", "again", "oops",
        ],
    },
    "sad": {
        "patterns": [],
        "words": [
            "gone", "empty", "alone", "missing", "quiet", "without",
            "lost", "left", "used to", "no longer", "still",
        ],
    },
    "anxious": {
        "patterns": [],
        "fear_words": [
            "dark", "shadow", "sound", "something", "what if",
            "corner", "behind", "watching", "creak",
        ],
        "safety_words": [
            "safe", "warm", "friend", "singing", "gentle",
            "okay", "just a", "only a", "cricket",
        ],
    },
    "angry": {
        "patterns": [],
        "words": [
            "not fair", "stomped", "threw", "slammed", "no",
            "couldn't", "wouldn't", "shouldn't", "why",
        ],
    },
    "curious": {
        "patterns": [],
        "words": [
            "never seen", "impossible", "glowing", "hidden",
            "secret", "discovered", "there it was",
        ],
    },
    "calm": {
        "patterns": [],
        "words": [
            "soft", "warm", "gentle", "breathing", "still",
            "quiet", "slowly", "peaceful", "cozy",
        ],
    },
}


def split_into_sentences(text: str) -> List[str]:
    """Split paragraph text into sentences, preserving punctuation."""
    # Split on sentence-ending punctuation followed by space or end-of-string
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def contains_mood_keyword(sentence: str, mood: str) -> bool:
    """Check if a sentence contains any mood keyword or matches a pattern."""
    keywords = MOOD_KEYWORDS.get(mood, {})
    sentence_lower = sentence.lower()

    # Check regex patterns (ALL_CAPS, repeated letters)
    for pattern in keywords.get("patterns", []):
        if re.search(pattern, sentence):
            return True

    # Check all word lists
    all_words = list(keywords.get("words", []))
    all_words += keywords.get("fear_words", [])
    all_words += keywords.get("safety_words", [])

    for keyword in all_words:
        if keyword in sentence_lower:
            return True

    return False


def get_emphasis_type(sentence: str, mood: str) -> str:
    """For anxious mood, distinguish fear vs safety emphasis. Others return 'default'."""
    if mood == "anxious":
        sentence_lower = sentence.lower()
        fear_words = MOOD_KEYWORDS.get("anxious", {}).get("fear_words", [])
        safety_words = MOOD_KEYWORDS.get("anxious", {}).get("safety_words", [])
        # Check fear first — if both present, fear wins (validates the feeling)
        if any(fw in sentence_lower for fw in fear_words):
            return "fear"
        if any(sw in sentence_lower for sw in safety_words):
            return "safety"
    return "default"


def get_emphasis_params(mood: str, emphasis_type: str = "default") -> dict:
    """Get TTS parameters for an emphasis sentence.

    Returns dict with: exaggeration, cfg_weight, speed_multiplier.
    """
    params = MOOD_EMPHASIS_PARAMS.get(mood, MOOD_EMPHASIS_PARAMS.get("calm", {}))

    # Anxious has sub-types (fear/safety) as nested dicts
    if mood == "anxious" and emphasis_type in params:
        return params[emphasis_type]

    # Other moods: params are flat (no "default" key)
    if isinstance(params.get("exaggeration"), (int, float)):
        return params

    # Fallback
    return {"exaggeration": 0.5, "cfg_weight": 0.4, "speed_multiplier": 1.0}


def clamp_emphasis_exaggeration(emphasis_exag: float, paragraph_exag: float,
                                 max_delta: float = 0.3) -> float:
    """Prevent emphasis sentences from sounding like a different story.

    max_delta reduced from 0.4 to 0.3 because emphasis now applies to
    whole sentences rather than isolated words.
    """
    return min(emphasis_exag, paragraph_exag + max_delta)


def should_apply_emphasis(para_index: int, total_paragraphs: int) -> bool:
    """No emphasis in the final 20% — ending must be seamlessly calm."""
    return para_index < total_paragraphs * 0.8


def chunk_with_sentence_emphasis(paragraphs: List[str], mood: str) -> List[dict]:
    """Flag whole sentences for emphasis. No word-level splitting.

    Takes a list of paragraph strings. Splits each into sentences, then
    checks each sentence for [EMPHASIS] markers or mood keywords.

    Returns list of dicts:
        {"text": "...", "params": "normal"|"emphasis", "emphasis_type": "default"|"fear"|"safety"}

    Each chunk's text is a complete sentence — never a word fragment.
    Standard sentence/paragraph gaps between chunks, no crossfades needed.
    """
    chunks: List[dict] = []

    for paragraph in paragraphs:
        sentences = split_into_sentences(paragraph)

        for sentence in sentences:
            # Check for LLM-tagged [EMPHASIS] markers
            has_emphasis = "[EMPHASIS]" in sentence

            # If no LLM markers, check keyword dictionary
            if not has_emphasis:
                has_emphasis = contains_mood_keyword(sentence, mood)

            # Strip markers — TTS never sees them
            clean = re.sub(r'\[/?EMPHASIS\]', '', sentence).strip()
            if not clean:
                continue

            if has_emphasis:
                emphasis_type = get_emphasis_type(clean, mood)
                chunks.append({
                    "text": clean,
                    "params": "emphasis",
                    "emphasis_type": emphasis_type,
                })
            else:
                chunks.append({
                    "text": clean,
                    "params": "normal",
                })

    return chunks
