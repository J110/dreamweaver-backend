"""Lullaby lyrics fidelity checking via Whisper transcription.

Three-gate quality pipeline for lullaby audio:
  Gate 1 — Content fidelity (word overlap for Type L, nonsense purity for Type N)
  Gate 2 — Sleep-cue word presence (Type L) / Phantom word check (Type N)
  Gate 3 — Safety blocklist (zero tolerance, all types)

Content types:
  Type L (Lyrical, ages 2-5): Real English lyrics with sleep imagery
  Type N (Nonsense, ages 0-1): Pure vocables — "shh la la", "mmm", "loo loo"
  Type M (Mixed): Some real words alongside nonsense sections

Used by:
  - generate_audio.py: retake selection (score each candidate)
  - qa_audio.py: post-generation pipeline QA (Phase LF)

Dependencies:
  - faster-whisper (pip install faster-whisper)
  - No API calls, no cost. Everything runs locally.
"""

import difflib
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
BLOCKLIST_PATH = DATA_DIR / "blocklist.txt"
ENGLISH_WORDS_PATH = DATA_DIR / "english_common.txt"

# ── Nonsense vocabulary ──────────────────────────────────────────────────
NONSENSE_TOKENS = {
    "shh", "shhh", "shhhh", "sh",
    "mmm", "mmmm", "mmmmm", "mm", "hm", "hmm", "hmmm",
    "la", "lu", "loo", "lee", "lo",
    "ooh", "ahh", "aah", "oh", "ah",
    "na", "nah", "naa",
    "ba", "baa", "hush",
    "doo", "da", "dee", "do",
    "hey", "ay",
    "sha", "shaa",
}

# ── Sleep-cue words (Gate 2, Type L) ─────────────────────────────────────
SLEEP_CUES = {
    "sleep", "dream", "eyes", "close", "night",
    "rest", "safe", "warm", "soft", "gentle",
    "quiet", "still", "hush", "stars", "moon",
    "drift", "cozy", "snuggle", "blanket", "pillow",
    "sleepy", "dreaming", "resting", "peaceful",
}

# ── Phantom word severity (Gate 2, Type N) ───────────────────────────────
# Words that are inappropriate/confusing if hallucinated from nonsense
SEVERITY_MEDIUM = {
    "money", "work", "phone", "car", "fast",
    "run", "jump", "loud", "bright", "morning",
    "wake", "fight", "angry", "hate", "stop",
    "no", "bad", "wrong", "ugly", "stupid",
    "crazy", "weird", "strange", "eat", "food",
    "drink", "play", "game", "school", "homework",
    "buy", "sell", "pay", "boss", "job",
}

# Low-severity: common Whisper hallucinations from nonsense audio (harmless)
SEVERITY_LOW = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "of", "for", "is", "it", "i", "he", "she", "we", "they", "my",
    "you", "her", "his", "that", "this", "with", "so", "as", "be",
    "was", "are", "been", "do", "did", "has", "had", "will", "would",
    "can", "could", "may", "should", "not", "all", "just", "like",
    "me", "him", "us", "them", "up", "out", "if", "then", "than",
}

# ── Section tag pattern ──────────────────────────────────────────────────
_SECTION_TAG_RE = re.compile(r"\[.*?\]")

# ── Singleton model holder ───────────────────────────────────────────────
_whisper_model = None


def _load_word_set(path: Path) -> Set[str]:
    """Load a word list file (one word per line, # comments)."""
    if not path.exists():
        logger.warning("Word list not found: %s", path)
        return set()
    words = set()
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line.lower())
    return words


def _get_blocklist() -> Set[str]:
    """Load the safety blocklist."""
    return _load_word_set(BLOCKLIST_PATH)


def _get_english_words() -> Set[str]:
    """Load common English words for Type N real-word detection."""
    return _load_word_set(ENGLISH_WORDS_PATH)


def _get_whisper_model():
    """Lazy-load the faster-whisper model (singleton)."""
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            # "small" balances accuracy vs speed. "medium" is more accurate but slower.
            # On CPU: small ~20s, medium ~45s per 4-min track.
            _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
            logger.info("Whisper model loaded (small, cpu, int8)")
        except ImportError:
            logger.error("faster-whisper not installed. Run: pip install faster-whisper")
            raise
    return _whisper_model


# ═════════════════════════════════════════════════════════════════════════
#  Pre-processing
# ═════════════════════════════════════════════════════════════════════════

def clean_lyrics(raw_lyrics: str) -> dict:
    """Clean original lyrics and classify content type.

    Returns:
        {
            "type": "L" | "N" | "M",
            "lyrics_real": str,       # only real-word lines, lowercase
            "lyrics_full": str,       # all lines, lowercase
            "real_word_count": int,
            "total_word_count": int,
            "real_ratio": float,
        }
    """
    # Strip section tags: [verse], [chorus - soft, warm], etc.
    text = _SECTION_TAG_RE.sub("", raw_lyrics)

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    real_lines = []
    all_words = []
    real_words = []

    for line in lines:
        # Tokenize: lowercase, strip punctuation
        words = re.findall(r"[a-zA-Z]+", line.lower())
        all_words.extend(words)

        # Filter out nonsense tokens
        real_in_line = [w for w in words if w not in NONSENSE_TOKENS]

        if real_in_line:
            real_lines.append(" ".join(real_in_line))
            real_words.extend(real_in_line)

    total = len(all_words)
    real_count = len(real_words)
    ratio = real_count / max(total, 1)

    # Classify
    if ratio > 0.60:
        content_type = "L"
    elif ratio < 0.20:
        content_type = "N"
    else:
        content_type = "M"

    return {
        "type": content_type,
        "lyrics_real": " ".join(real_lines),
        "lyrics_full": " ".join(lines).lower(),
        "real_word_count": real_count,
        "total_word_count": total,
        "real_ratio": round(ratio, 3),
    }


# ═════════════════════════════════════════════════════════════════════════
#  Whisper Transcription
# ═════════════════════════════════════════════════════════════════════════

def transcribe_with_whisper(audio_path: str, is_singing: bool = False) -> str:
    """Transcribe audio file using faster-whisper (local, free).

    Args:
        audio_path: Path to audio file
        is_singing: If True, disable VAD filter. Whisper's VAD treats singing
            as non-speech and discards 90%+ of the audio, producing near-empty
            transcripts. For lullabies/songs, we need VAD off.

    Returns lowercase transcript text.
    """
    model = _get_whisper_model()
    segments, _info = model.transcribe(
        audio_path,
        language="en",
        beam_size=5,
        vad_filter=not is_singing,
    )
    # Collect all segment texts
    texts = [seg.text.strip() for seg in segments]
    return " ".join(texts).lower().strip()


# ═════════════════════════════════════════════════════════════════════════
#  Gate 1: Content Fidelity Check
# ═════════════════════════════════════════════════════════════════════════

def _fuzzy_match(word: str, candidates: set, threshold: float = 0.80) -> Optional[str]:
    """Check if word fuzzy-matches any candidate (SequenceMatcher ratio).

    Singing distorts words — "dreaming" → "dreamin", "snowflakes" → "snow".
    Returns the best match if ratio >= threshold, else None.
    """
    if len(word) < 3:
        return None  # Too short for meaningful fuzzy match
    best_match = None
    best_ratio = 0.0
    for c in candidates:
        if abs(len(word) - len(c)) > 3:
            continue  # Skip wildly different lengths
        ratio = difflib.SequenceMatcher(None, word, c).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = c
    return best_match if best_ratio >= threshold else None


def gate1_word_overlap(lyrics_real: str, transcript: str) -> dict:
    """Gate 1 for Type L: word overlap between original and transcript.

    Uses exact match first, then fuzzy match (SequenceMatcher >= 0.80)
    for words distorted by singing melody.

    Returns {"pass": bool, "score": float, "matched": list, "missing": list,
             "fuzzy_matched": list}
    """
    orig_words = lyrics_real.lower().split()
    trans_words = set(transcript.lower().split())

    if not orig_words:
        return {"pass": True, "score": 1.0, "matched": [], "missing": [],
                "fuzzy_matched": []}

    matched = []
    fuzzy_matched = []
    missing = []

    for w in orig_words:
        if w in trans_words:
            matched.append(w)
        else:
            fm = _fuzzy_match(w, trans_words)
            if fm:
                fuzzy_matched.append(f"{w}~{fm}")
                matched.append(w)  # Count as matched
            else:
                missing.append(w)

    score = len(matched) / len(orig_words)

    return {
        "pass": score >= 0.75,
        "score": round(score, 3),
        "matched": sorted(set(m for m in matched if m not in [p.split("~")[0] for p in fuzzy_matched])),
        "fuzzy_matched": sorted(set(fuzzy_matched)),
        "missing": sorted(set(missing)),
    }


def gate1_nonsense_purity(transcript: str, english_words: Set[str]) -> dict:
    """Gate 1 for Type N: verify transcript is NOT full of real English words.

    Returns {"pass": bool, "real_word_ratio": float, "detected_real_words": list}
    """
    trans_words = transcript.lower().split()

    if not trans_words:
        return {"pass": True, "real_word_ratio": 0.0, "detected_real_words": []}

    # Words that are NOT nonsense tokens AND are in the English dictionary
    real_detected = [
        w for w in trans_words
        if w not in NONSENSE_TOKENS
        and w not in SEVERITY_LOW  # ignore common Whisper hallucinations
        and w in english_words
    ]

    ratio = len(real_detected) / len(trans_words)

    return {
        "pass": ratio <= 0.30,
        "real_word_ratio": round(ratio, 3),
        "detected_real_words": sorted(set(real_detected)),
    }


def gate1_mixed(lyrics_real: str, transcript: str, english_words: Set[str]) -> dict:
    """Gate 1 for Type M: both word overlap AND unexpected word check.

    Returns {"pass": bool, "overlap": dict, "purity": dict}
    """
    # Word overlap on real content
    overlap = gate1_word_overlap(lyrics_real, transcript)

    # Unexpected real words (not from original lyrics, not nonsense, not low-severity)
    orig_real_set = set(lyrics_real.lower().split())
    trans_words = transcript.lower().split()
    unexpected = [
        w for w in trans_words
        if w not in orig_real_set
        and w not in NONSENSE_TOKENS
        and w not in SEVERITY_LOW
        and w in english_words
    ]
    unexpected_ratio = len(unexpected) / max(len(trans_words), 1)

    return {
        "pass": overlap["pass"] and unexpected_ratio <= 0.25,
        "overlap": overlap,
        "unexpected_ratio": round(unexpected_ratio, 3),
        "unexpected_words": sorted(set(unexpected)),
    }


# ═════════════════════════════════════════════════════════════════════════
#  Gate 2: Purpose-Specific Word Check
# ═════════════════════════════════════════════════════════════════════════

def gate2_cue_words(lyrics_real: str, transcript: str) -> dict:
    """Gate 2 for Type L: verify sleep-conditioning words come through.

    Uses exact match first, then fuzzy match for words distorted by singing.

    Returns {"pass": bool, "score": float, "detected": list, "missing": list}
    """
    orig_words = set(lyrics_real.lower().split())
    trans_words = set(transcript.lower().split())

    cues_in_original = orig_words & SLEEP_CUES
    if not cues_in_original:
        return {"pass": True, "score": 1.0, "detected": [], "missing": []}

    detected = []
    missing = []
    for cue in sorted(cues_in_original):
        if cue in trans_words:
            detected.append(cue)
        elif _fuzzy_match(cue, trans_words, threshold=0.80):
            detected.append(cue)
        else:
            missing.append(cue)

    score = len(detected) / len(cues_in_original)

    return {
        "pass": score >= 0.80,
        "score": round(score, 3),
        "detected": detected,
        "missing": missing,
    }


def gate2_phantom_words(detected_real_words: List[str], blocklist: Set[str]) -> dict:
    """Gate 2 for Type N: check phantom words for severity.

    Returns {"pass": bool, "high": list, "medium": list, "flag_for_review": bool}
    """
    high = [w for w in detected_real_words if w in blocklist]
    medium = [w for w in detected_real_words if w in SEVERITY_MEDIUM]

    return {
        "pass": len(high) == 0,
        "high_severity": high,
        "medium_severity": medium,
        "flag_for_review": len(medium) > 2,
    }


# ═════════════════════════════════════════════════════════════════════════
#  Gate 3: Safety Blocklist
# ═════════════════════════════════════════════════════════════════════════

def gate3_blocklist(transcript: str, blocklist: Set[str],
                    original_words: Optional[Set[str]] = None) -> dict:
    """Gate 3: zero-tolerance scan for blocked words in transcript.

    Args:
        transcript: Whisper transcript text
        blocklist: Set of blocked words
        original_words: Words from original lyrics. If a blocked word appears
            in the original lyrics (e.g., "bright" in "warm and bright"),
            it's intentional and should not be flagged.

    Returns {"pass": bool, "hits": list}
    """
    trans_words = set(transcript.lower().split())
    hits = sorted(trans_words & blocklist)

    # Don't flag words that are in the original lyrics
    if original_words and hits:
        hits = [w for w in hits if w not in original_words]

    return {
        "pass": len(hits) == 0,
        "hits": hits,
    }


# ═════════════════════════════════════════════════════════════════════════
#  Combined Fidelity Check
# ═════════════════════════════════════════════════════════════════════════

def check_lullaby_fidelity(
    audio_path: str,
    original_lyrics: str,
    transcript: Optional[str] = None,
) -> dict:
    """Run the full 3-gate lullaby fidelity check.

    Args:
        audio_path: Path to audio file (wav or mp3)
        original_lyrics: Raw lyrics text with [verse]/[chorus] tags
        transcript: Pre-computed Whisper transcript (if None, will transcribe)

    Returns:
        {
            "verdict": "PASS" | "WARN" | "REJECT",
            "content_type": "L" | "N" | "M",
            "transcript": str,
            "gate1": {...},
            "gate2": {...},
            "gate3": {...},
            "fidelity_score": float (0-1, for retake comparison),
        }
    """
    # Load word lists
    blocklist = _get_blocklist()
    english_words = _get_english_words()

    # Pre-process lyrics
    cleaned = clean_lyrics(original_lyrics)
    content_type = cleaned["type"]

    # Transcribe if not provided
    if transcript is None:
        try:
            # Singing content needs VAD disabled — VAD treats singing as
            # non-speech and discards 90%+ of the audio
            transcript = transcribe_with_whisper(
                audio_path, is_singing=(content_type in ("L", "M"))
            )
        except Exception as e:
            logger.error("Whisper transcription failed: %s", e)
            return {
                "verdict": "WARN",
                "content_type": content_type,
                "transcript": "",
                "gate1": {"pass": True, "error": str(e)},
                "gate2": {"pass": True, "error": str(e)},
                "gate3": {"pass": True, "error": str(e)},
                "fidelity_score": 0.5,
                "error": str(e),
            }

    # ── Gate 1 ──────────────────────────────────────────────────────────
    if content_type == "L":
        g1 = gate1_word_overlap(cleaned["lyrics_real"], transcript)
    elif content_type == "N":
        g1 = gate1_nonsense_purity(transcript, english_words)
    else:  # Type M
        g1 = gate1_mixed(cleaned["lyrics_real"], transcript, english_words)

    # ── Gate 2 ──────────────────────────────────────────────────────────
    if content_type == "L":
        g2 = gate2_cue_words(cleaned["lyrics_real"], transcript)
    elif content_type == "N":
        # Use detected real words from Gate 1
        detected = g1.get("detected_real_words", [])
        g2 = gate2_phantom_words(detected, blocklist)
    else:  # Type M
        g2_cue = gate2_cue_words(cleaned["lyrics_real"], transcript)
        g2_phantom = gate2_phantom_words(g1.get("unexpected_words", []), blocklist)
        g2 = {
            "pass": g2_cue["pass"] and g2_phantom["pass"],
            "cue_check": g2_cue,
            "phantom_check": g2_phantom,
        }

    # ── Gate 3 ──────────────────────────────────────────────────────────
    # Pass original lyrics words so intentional words aren't flagged
    orig_word_set = set(cleaned["lyrics_real"].split()) if content_type in ("L", "M") else None
    g3 = gate3_blocklist(transcript, blocklist, original_words=orig_word_set)

    # ── Verdict ─────────────────────────────────────────────────────────
    if not g3["pass"]:
        verdict = "REJECT"
    elif not g1["pass"]:
        verdict = "REJECT"
    elif not g2["pass"]:
        verdict = "REJECT"
    elif g2.get("flag_for_review", False):
        verdict = "WARN"
    else:
        verdict = "PASS"

    # ── Fidelity score (0-1, for retake comparison) ─────────────────────
    # Higher = better. Combines gate results into a single comparable score.
    if content_type == "L":
        g1_score = g1.get("score", 0.5)
        g2_score = g2.get("score", 0.5)
    elif content_type == "N":
        # For Type N: lower real_word_ratio = better → invert
        g1_score = 1.0 - g1.get("real_word_ratio", 0.5)
        g2_score = 1.0 if g2["pass"] else 0.0
    else:
        g1_score = g1.get("overlap", {}).get("score", 0.5)
        g2_score = 0.5  # mixed is complex, neutral score
    g3_score = 1.0 if g3["pass"] else 0.0

    fidelity_score = g1_score * 0.4 + g2_score * 0.3 + g3_score * 0.3

    return {
        "verdict": verdict,
        "content_type": content_type,
        "content_classification": cleaned,
        "transcript": transcript,
        "gate1": g1,
        "gate2": g2,
        "gate3": g3,
        "fidelity_score": round(fidelity_score, 3),
    }
