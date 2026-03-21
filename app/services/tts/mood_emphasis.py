"""Mood-specific emphasis word system for TTS generation.

Isolates key mood words into separate TTS chunks with mood-specific parameters,
creating natural emphasis that mirrors how a human narrator would deliver.
"""

import re


# ── Emphasis TTS Parameters by Mood ──────────────────────────────────────
MOOD_EMPHASIS_PARAMS = {
    "wired": {
        # Comic punch -- louder, more expressive, slight slowdown
        "exaggeration": 0.85,
        "cfg_weight": 0.6,
        "speed_multiplier": 0.85,
    },
    "curious": {
        # Wonder lift -- brighter, slightly open
        "exaggeration": 0.65,
        "cfg_weight": 0.45,
        "speed_multiplier": 0.88,
    },
    "calm": {
        # Melt -- extra soft, slow, savored
        "exaggeration": 0.15,
        "cfg_weight": 0.15,
        "speed_multiplier": 0.75,
    },
    "sad": {
        # Heavy -- flat, deliberate, weighty
        "exaggeration": 0.20,
        "cfg_weight": 0.20,
        "speed_multiplier": 0.75,
    },
    "anxious": {
        # Two sets: fear words (hushed) and safety words (warm)
        "fear": {
            "exaggeration": 0.15,
            "cfg_weight": 0.15,
            "speed_multiplier": 0.80,
        },
        "safety": {
            "exaggeration": 0.50,
            "cfg_weight": 0.40,
            "speed_multiplier": 0.90,
        },
    },
    "angry": {
        # Punch -- sharp, clipped, emphatic
        "exaggeration": 0.80,
        "cfg_weight": 0.55,
        "speed_multiplier": 1.05,
    },
}


# ── Backup Keyword Dictionary ────────────────────────────────────────────
MOOD_KEYWORDS = {
    "wired": {
        "patterns": [
            r'[A-Z]{3,}',              # ALL CAPS words (SPLAT, BONK, CRASH)
            r'(\w)\1{2,}',             # repeated letters (sooooo, veeeery)
        ],
        "words": ["splat", "bonk", "crash", "whoosh", "plop", "thud",
                  "splash", "bang", "boing", "squish", "pop", "zoom",
                  "oh no", "again", "oops"],
    },
    "sad": {
        "patterns": [],
        "words": ["gone", "empty", "alone", "missing", "quiet", "without",
                  "lost", "left", "used to", "no longer", "still", "away"],
    },
    "anxious": {
        "patterns": [],
        "fear_words": ["dark", "shadow", "sound", "something", "what if",
                       "corner", "behind", "watching", "creak", "nothing there"],
        "safety_words": ["safe", "warm", "friend", "singing", "gentle", "okay",
                         "just a", "only a", "it was", "cricket", "branch"],
    },
    "angry": {
        "patterns": [],
        "words": ["not fair", "stomped", "threw", "slammed", "no",
                  "couldn't", "wouldn't", "shouldn't", "why"],
    },
    "curious": {
        "patterns": [],
        "words": ["never seen", "impossible", "behind", "glowing", "what",
                  "discovered", "hidden", "secret", "there it was"],
    },
    "calm": {
        "patterns": [],
        "words": ["soft", "warm", "gentle", "breathing", "still", "quiet",
                  "slowly", "peaceful", "drift", "floating", "cozy"],
    },
}


def get_emphasis_type(word, mood):
    """For anxious mood, distinguish fear vs safety emphasis. Others have one type."""
    if mood == "anxious":
        fear_words = MOOD_KEYWORDS.get("anxious", {}).get("fear_words", [])
        safety_words = MOOD_KEYWORDS.get("anxious", {}).get("safety_words", [])
        word_lower = word.lower()
        if any(fw in word_lower for fw in fear_words):
            return "fear"
        if any(sw in word_lower for sw in safety_words):
            return "safety"
    return "default"


def get_emphasis_params(mood, emphasis_type="default"):
    """Get TTS parameters for an emphasis chunk."""
    params = MOOD_EMPHASIS_PARAMS.get(mood, MOOD_EMPHASIS_PARAMS["calm"])
    # Anxious has two emphasis types
    if mood == "anxious" and emphasis_type in params:
        return params[emphasis_type]
    elif isinstance(params, dict) and "exaggeration" in params:
        return params
    return {"exaggeration": 0.5, "cfg_weight": 0.4, "speed_multiplier": 1.0}


def clamp_emphasis_exaggeration(emphasis_exag, paragraph_exag, max_delta=0.4):
    """Emphasis exag never more than max_delta above base paragraph exag."""
    return min(emphasis_exag, paragraph_exag + max_delta)


def should_apply_emphasis(paragraph_index, total_paragraphs):
    """No emphasis in final 20% of story."""
    return paragraph_index < total_paragraphs * 0.8


def split_by_keywords(text, mood):
    """Split a text fragment around mood keywords, tagging matches for emphasis."""
    keywords = MOOD_KEYWORDS.get(mood, {})
    chunks = []

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
    all_words = keywords.get("words", [])
    all_words += keywords.get("fear_words", [])
    all_words += keywords.get("safety_words", [])

    text_lower = text.lower()
    for keyword in sorted(all_words, key=len, reverse=True):  # longest first
        idx = text_lower.find(keyword)
        if idx >= 0:
            before = text[:idx].strip()
            word = text[idx:idx+len(keyword)].strip()
            after = text[idx+len(keyword):].strip()
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

    # No keywords found -- return as normal chunk
    if text.strip():
        chunks.append({"text": text, "params": "normal"})
    return chunks


def chunk_with_mood_emphasis(text, mood):
    """Split text into chunks, isolating mood-emphasis words for special TTS.

    First checks for [EMPHASIS]...[/EMPHASIS] markers from the LLM,
    then falls back to keyword dictionary matching.
    Returns list of dicts: {"text": str, "params": "normal"|"emphasis", "emphasis_type": str}
    """
    if not mood or mood == "calm":
        # Calm uses subtle emphasis -- still process but with gentle params
        pass

    chunks = []

    # Check for [EMPHASIS] markers from LLM
    if "[EMPHASIS]" in text:
        parts = re.split(r'\[EMPHASIS\](.*?)\[/EMPHASIS\]', text)
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if i % 2 == 0:
                # Normal text -- check against keyword dictionary too
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
        # No LLM markers -- check keyword dictionary
        sub_chunks = split_by_keywords(text, mood)
        chunks.extend(sub_chunks)

    return chunks
