"""Mood-based emphasis word system for TTS audio generation.

Isolates key mood words within sentences for special TTS delivery:
- Wired: comic punch (SPLAT, BONK) with high exaggeration
- Sad: heavy weight (alone, gone) with low exaggeration
- Anxious: fear words (dark, shadow) hushed, safety words (singing, safe) warm
- Angry: sharp emphasis (THREW, stomped) with clipped delivery
- Curious: wonder lift (never seen, glowing) with brighter delivery
- Calm: melt words (soft, warm) extra-soft and savored

Usage:
    from mood_emphasis import (
        chunk_with_mood_emphasis, should_apply_emphasis,
        MOOD_EMPHASIS_PARAMS, clamp_emphasis_exaggeration,
    )
"""

import re
from typing import Dict, List

# ── Per-mood TTS parameters for emphasis chunks ──────────────────────
MOOD_EMPHASIS_PARAMS: Dict[str, dict] = {
    "wired": {
        # Comic punch — louder, more expressive, slight slowdown
        "default": {"exaggeration": 0.85, "cfg_weight": 0.6, "speed_multiplier": 0.85},
    },
    "curious": {
        # Wonder lift — brighter, slightly open
        "default": {"exaggeration": 0.65, "cfg_weight": 0.45, "speed_multiplier": 0.88},
    },
    "calm": {
        # Melt — extra soft, slow, savored
        "default": {"exaggeration": 0.15, "cfg_weight": 0.15, "speed_multiplier": 0.75},
    },
    "sad": {
        # Heavy — flat, deliberate, weighty
        "default": {"exaggeration": 0.20, "cfg_weight": 0.20, "speed_multiplier": 0.75},
    },
    "anxious": {
        # Two sets: fear words (hushed) and safety words (warm)
        "fear": {"exaggeration": 0.15, "cfg_weight": 0.15, "speed_multiplier": 0.80},
        "safety": {"exaggeration": 0.50, "cfg_weight": 0.40, "speed_multiplier": 0.90},
        "default": {"exaggeration": 0.15, "cfg_weight": 0.15, "speed_multiplier": 0.80},
    },
    "angry": {
        # Punch — sharp, clipped, emphatic
        "default": {"exaggeration": 0.80, "cfg_weight": 0.55, "speed_multiplier": 1.05},
    },
}

# ── Backup keyword dictionary per mood ───────────────────────────────
# Catches mood words the LLM didn't wrap in [EMPHASIS] tags.
MOOD_KEYWORDS: Dict[str, dict] = {
    "wired": {
        "patterns": [
            r'[A-Z]{3,}',           # ALL CAPS words (SPLAT, BONK, CRASH)
            r'(\w)\1{2,}',          # repeated letters (sooooo, veeeery)
        ],
        "words": [
            "splat", "bonk", "crash", "whoosh", "plop", "thud",
            "splash", "bang", "boing", "squish", "pop", "zoom",
            "oh no", "again", "oops",
        ],
    },
    "sad": {
        "patterns": [],
        "words": [
            "gone", "empty", "alone", "missing", "quiet", "without",
            "lost", "left", "used to", "no longer", "still", "away",
        ],
    },
    "anxious": {
        "patterns": [],
        "fear_words": [
            "dark", "shadow", "sound", "something", "what if",
            "corner", "behind", "watching", "creak", "nothing there",
        ],
        "safety_words": [
            "safe", "warm", "friend", "singing", "gentle", "okay",
            "just a", "only a", "it was", "cricket", "branch",
        ],
        "words": [],  # combined from fear_words + safety_words
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
            "never seen", "impossible", "behind", "glowing", "what",
            "discovered", "hidden", "secret", "there it was",
        ],
    },
    "calm": {
        "patterns": [],
        "words": [
            "soft", "warm", "gentle", "breathing", "still", "quiet",
            "slowly", "peaceful", "drift", "floating", "cozy",
        ],
    },
}


def get_emphasis_type(word: str, mood: str) -> str:
    """For anxious mood, distinguish fear vs safety emphasis. Others return 'default'."""
    if mood == "anxious":
        word_lower = word.lower()
        fear_words = MOOD_KEYWORDS.get("anxious", {}).get("fear_words", [])
        safety_words = MOOD_KEYWORDS.get("anxious", {}).get("safety_words", [])
        if any(fw in word_lower for fw in fear_words):
            return "fear"
        if any(sw in word_lower for sw in safety_words):
            return "safety"
    return "default"


def get_emphasis_params(mood: str, emphasis_type: str = "default") -> dict:
    """Get TTS parameters for an emphasis chunk."""
    mood_params = MOOD_EMPHASIS_PARAMS.get(mood, MOOD_EMPHASIS_PARAMS.get("calm", {}))
    if emphasis_type in mood_params:
        return mood_params[emphasis_type]
    return mood_params.get("default", {"exaggeration": 0.5, "cfg_weight": 0.4, "speed_multiplier": 1.0})


def clamp_emphasis_exaggeration(emphasis_exag: float, paragraph_exag: float,
                                 max_delta: float = 0.4) -> float:
    """Prevent emphasis exaggeration from being too far above paragraph base."""
    return min(emphasis_exag, paragraph_exag + max_delta)


def should_apply_emphasis(para_index: int, total_paragraphs: int) -> bool:
    """No emphasis in the final 20% of the story."""
    return para_index < total_paragraphs * 0.8


def split_by_keywords(text: str, mood: str) -> List[dict]:
    """Split a text fragment around mood keywords, tagging matches for emphasis."""
    keywords = MOOD_KEYWORDS.get(mood, {})
    chunks: List[dict] = []

    # Check regex patterns (ALL_CAPS, repeated letters)
    for pattern in keywords.get("patterns", []):
        match = re.search(pattern, text)
        if match:
            before = text[:match.start()].strip()
            word = match.group().strip()
            after = text[match.end():].strip()
            if before:
                chunks.append({"text": before, "params": "normal"})
            chunks.append({
                "text": word,
                "params": "emphasis",
                "emphasis_type": get_emphasis_type(word, mood),
            })
            if after:
                chunks.extend(split_by_keywords(after, mood))
            return chunks

    # Check word lists
    all_words = list(keywords.get("words", []))
    all_words += keywords.get("fear_words", [])
    all_words += keywords.get("safety_words", [])

    text_lower = text.lower()
    for keyword in sorted(all_words, key=len, reverse=True):  # longest first
        idx = text_lower.find(keyword)
        if idx >= 0:
            before = text[:idx].strip()
            word = text[idx:idx + len(keyword)].strip()
            after = text[idx + len(keyword):].strip()
            if before:
                chunks.append({"text": before, "params": "normal"})
            chunks.append({
                "text": word,
                "params": "emphasis",
                "emphasis_type": get_emphasis_type(word, mood),
            })
            if after:
                chunks.extend(split_by_keywords(after, mood))
            return chunks

    # No keywords found — return as normal chunk
    if text.strip():
        chunks.append({"text": text, "params": "normal"})
    return chunks


def chunk_with_mood_emphasis(text: str, mood: str) -> List[dict]:
    """Split text into chunks, isolating mood-emphasis words for special TTS.

    Handles both LLM-tagged [EMPHASIS]...[/EMPHASIS] markers and backup
    keyword dictionary matches.

    Returns list of dicts:
        {"text": "...", "params": "normal"|"emphasis", "emphasis_type": "default"|"fear"|"safety"}
    """
    chunks: List[dict] = []

    # Check for [EMPHASIS] markers from LLM
    if "[EMPHASIS]" in text:
        parts = re.split(r'\[EMPHASIS\](.*?)\[/EMPHASIS\]', text, flags=re.IGNORECASE)
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if i % 2 == 0:
                # Normal text — also check against keyword dictionary
                sub_chunks = split_by_keywords(part, mood)
                chunks.extend(sub_chunks)
            else:
                # LLM-tagged emphasis word
                emphasis_type = get_emphasis_type(part, mood)
                chunks.append({
                    "text": part,
                    "params": "emphasis",
                    "emphasis_type": emphasis_type,
                })
    else:
        # No LLM markers — check keyword dictionary only
        chunks = split_by_keywords(text, mood)

    return chunks
