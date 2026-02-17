#!/usr/bin/env python3
"""Voxtral-based Audio QA pipeline for Dream Valley.

Three-phase quality assurance for TTS-generated audio:
  Phase 1 — Duration anomaly detection (free, instant)
  Phase 2 — Voxtral transcription + text fidelity check
  Phase 3 — Voxtral chat-mode audio quality scoring (pronunciation, pacing, etc.)

Each audio variant gets a combined PASS / WARN / FAIL verdict with per-dimension
scores AND reasons so the reviewer knows exactly what to listen for.

Usage:
    python3 scripts/qa_audio.py                        # Full 3-phase QA on all Hindi
    python3 scripts/qa_audio.py --duration-only        # Phase 1 only (no API cost)
    python3 scripts/qa_audio.py --no-quality-score     # Phase 1+2 only
    python3 scripts/qa_audio.py --quality-only         # Phase 1+3 only (skip transcription)
    python3 scripts/qa_audio.py --lang hi              # Hindi only (default)
    python3 scripts/qa_audio.py --story-id <id>        # Single story
    python3 scripts/qa_audio.py --voice female_2_hi    # Single voice
    python3 scripts/qa_audio.py --threshold 0.80       # Custom fidelity pass threshold
    python3 scripts/qa_audio.py --dry-run              # Show plan + estimated cost
"""

import argparse
import base64
import difflib
import json
import logging
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from mistralai import Mistral
from pydub import AudioSegment

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"
REPORT_DIR = BASE_DIR / "seed_output" / "qa_reports"
TRANSCRIPT_CACHE_PATH = REPORT_DIR / "transcript_cache.json"

# ── Mistral / Voxtral setup ─────────────────────────────────────────────
load_dotenv(BASE_DIR / ".env", override=True)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
VOXTRAL_MODEL = "voxtral-mini-latest"

# ── Emotion markers (from generate_audio.py) ────────────────────────────
_MARKER_RE = re.compile(
    r"\["
    r"(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
    r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
    r"HUMMING|PAUSE|laugh|chuckle)"
    r"\]",
    re.IGNORECASE,
)

# ── Thresholds ───────────────────────────────────────────────────────────
DEFAULT_FIDELITY_PASS = 0.70
DEFAULT_FIDELITY_FAIL = 0.49
DURATION_OUTLIER_PCT = 0.15  # 15%

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qa_audio")


# ═══════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════

def strip_markers(text: str) -> str:
    """Remove emotion/pause markers from annotated text."""
    return _MARKER_RE.sub("", text).strip()


def extract_markers(text: str) -> List[str]:
    """Extract list of emotion markers from annotated text."""
    return _MARKER_RE.findall(text)


def normalize_devanagari(text: str) -> str:
    """Aggressively normalize Devanagari text for fuzzy comparison.

    Voxtral transcription of TTS audio introduces predictable variations:
    - Nukta (़) dropped: ड़→ड, ज़→ज, फ़→फ
    - Chandrabindu (ँ) ↔ Anusvara (ं) swapped
    - Minor vowel mark differences
    - Punctuation and whitespace differences

    We strip ALL of these so that "nearly the same" text scores high.
    """
    text = strip_markers(text)

    # 1. Remove nukta (़ U+093C) — maps ड़→ड, ज़→ज, फ़→फ etc.
    text = text.replace("\u093C", "")

    # 2. Normalize chandrabindu (ँ) → anusvara (ं)
    text = text.replace("\u0901", "\u0902")  # ँ → ं

    # 3. Remove ALL punctuation (Devanagari + Latin)
    text = re.sub(r"[।॥,?!.;:\"'()–—\-…\u0964\u0965]", " ", text)

    # 4. Remove Devanagari special marks that vary between source/transcript
    #    Visarga (ः), Avagraha (ऽ)
    text = text.replace("\u0903", "")  # visarga
    text = text.replace("\u093D", "")  # avagraha

    # 5. Normalize common confusable pairs in TTS transcription
    text = text.replace("री", "री")  # ensure consistent form
    text = text.replace("ी", "ी")    # consistent vowel sign

    # 6. Collapse all whitespace (newlines, tabs, multiple spaces → single space)
    text = " ".join(text.split())

    # 7. Lowercase any Latin chars
    return text.lower()


def get_mp3_duration(path: Path) -> float:
    """Get MP3 duration in seconds."""
    try:
        audio = AudioSegment.from_mp3(str(path))
        return len(audio) / 1000.0
    except Exception:
        return 0.0


def resolve_audio_path(url: str) -> Optional[Path]:
    """Convert /audio/pre-gen/xxx.mp3 URL to local file path."""
    filename = url.split("/")[-1]
    path = AUDIO_DIR / filename
    return path if path.exists() else None


def api_call_with_retry(func, *args, max_retries=8, **kwargs):
    """Call a function with exponential backoff on rate limit errors.

    Free-tier Mistral audio has strict rate limits (~1 req/min for audio),
    so we use generous backoff: 15, 30, 45, 60, 90, 120, 180, 240s.
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                # Generous backoff for free-tier audio rate limits
                wait = min(15 * (attempt + 1), 240)
                logger.warning("  Rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
            elif attempt < max_retries - 1:
                wait = (attempt + 1) * 5
                logger.warning("  API error: %s — retrying in %ds", e, wait)
                time.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded")


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 1: Duration Anomaly Detection
# ═══════════════════════════════════════════════════════════════════════════

def phase1_duration_analysis(stories: List[dict]) -> Dict[str, dict]:
    """Compute per-story median duration, flag outliers >15% from median.

    Returns dict keyed by story_id with:
      { median, variants: [{voice, duration, deviation_pct, is_outlier}] }
    """
    logger.info("═══ Phase 1: Duration Anomaly Detection ═══")
    results = {}

    for story in stories:
        story_id = story["id"]
        title = story.get("title", "untitled")
        variants = story.get("audio_variants", [])

        if not variants:
            logger.warning("  %s: no audio_variants", story_id)
            continue

        # Get durations from content.json metadata (no need to read files)
        durations = {}
        for v in variants:
            voice = v["voice"]
            dur = v.get("duration_seconds", 0)
            if dur > 0:
                durations[voice] = dur

        if len(durations) < 2:
            continue

        median_dur = statistics.median(durations.values())
        variant_results = []
        outlier_count = 0

        for voice, dur in sorted(durations.items()):
            deviation = abs(dur - median_dur) / median_dur if median_dur > 0 else 0
            is_outlier = deviation > DURATION_OUTLIER_PCT
            if is_outlier:
                outlier_count += 1
            variant_results.append({
                "voice": voice,
                "duration_seconds": round(dur, 2),
                "deviation_pct": round(deviation * 100, 1),
                "is_outlier": is_outlier,
            })

        results[story_id] = {
            "title": title,
            "median_duration": round(median_dur, 2),
            "variants": variant_results,
            "has_outliers": outlier_count > 0,
        }

        if outlier_count > 0:
            outlier_voices = [v["voice"] for v in variant_results if v["is_outlier"]]
            logger.info("  ⚠ %s: %d outlier(s) — %s", title[:40], outlier_count, ", ".join(outlier_voices))

    total_outliers = sum(1 for r in results.values() if r["has_outliers"])
    logger.info("Phase 1 complete: %d stories, %d with duration outliers", len(results), total_outliers)
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 2: Voxtral Transcription + Text Fidelity
# ═══════════════════════════════════════════════════════════════════════════

def load_transcript_cache() -> Dict[str, str]:
    """Load cached transcripts from disk. Keyed by audio filename."""
    if TRANSCRIPT_CACHE_PATH.exists():
        with open(TRANSCRIPT_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_transcript_cache(cache: Dict[str, str]):
    """Save transcript cache to disk."""
    TRANSCRIPT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRANSCRIPT_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def transcribe_audio(audio_path: Path, language: str = "hi") -> str:
    """Transcribe an audio file using Voxtral."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    def _call():
        result = client.audio.transcriptions.complete(
            model=VOXTRAL_MODEL,
            file={"content": audio_bytes, "file_name": audio_path.name},
            language=language,
        )
        return result.text if hasattr(result, "text") else str(result)

    return api_call_with_retry(_call)


def fuzzy_word_sim(w1: str, w2: str) -> float:
    """Character-level similarity between two Devanagari words.
    Handles TTS→ASR variations like ऊहू↔उहू, शुभ↔शुब, मछली↔मचली."""
    if w1 == w2:
        return 1.0
    return difflib.SequenceMatcher(None, w1, w2).ratio()


def ordered_fuzzy_word_coverage(
    src_words: List[str], trn_words: List[str],
    word_threshold: float = 0.5, lookahead: int = 8,
) -> Tuple[float, List[dict]]:
    """Walk through source words in order, fuzzy-match each against transcript.

    Respects ordering: once a transcript word is consumed, it can't match again.
    Returns (coverage_ratio 0-1, per-word details list).
    """
    details = []
    t_idx = 0

    for s_idx, s_word in enumerate(src_words):
        best_sim = 0.0
        best_t_word = None
        best_offset = None

        window = min(lookahead, len(trn_words) - t_idx)
        for offset in range(window):
            t_word = trn_words[t_idx + offset]
            sim = fuzzy_word_sim(s_word, t_word)
            if sim > best_sim:
                best_sim = sim
                best_t_word = t_word
                best_offset = offset

        matched = best_sim >= word_threshold
        details.append({
            "src_word": s_word,
            "matched": matched,
            "best_match": best_t_word,
            "similarity": round(best_sim, 3),
        })

        if matched and best_offset is not None:
            t_idx = t_idx + best_offset + 1

    matched_count = sum(1 for d in details if d["matched"])
    coverage = matched_count / max(len(src_words), 1)
    return coverage, details


def compute_text_fidelity(source: str, transcript: str) -> Dict[str, float]:
    """Compare source text with Voxtral transcript using fuzzy word matching.

    Primary metric is **ordered fuzzy word coverage**: walk through each
    source word in order, try to find a fuzzy match (SequenceMatcher ≥ 0.5)
    in the transcript, respecting word order.

    This handles Devanagari TTS→ASR variations like:
      ऊहू ↔ उहू, शुभ ↔ शुब, मछली ↔ मचली, बूढ़े ↔ बुढ़े

    Returns:
        fuzzy_word_coverage: ordered fuzzy match ratio (0-1) — PRIMARY metric
        ratio:               SequenceMatcher char-level similarity (0-1)
        word_overlap:        Jaccard similarity of word sets (0-1)
        word_order_score:    LCS ratio of exact word sequences (0-1)
        combined:            Weighted average (0-1)
    """
    src = normalize_devanagari(source)
    trs = normalize_devanagari(transcript)

    if not src or not trs:
        return {"fuzzy_word_coverage": 0, "ratio": 0, "word_overlap": 0,
                "word_order_score": 0, "combined": 0}

    src_words = src.split()
    trs_words = trs.split()

    # 1. Fuzzy ordered word coverage (PRIMARY — handles TTS/ASR noise)
    fuzzy_coverage, _details = ordered_fuzzy_word_coverage(src_words, trs_words)

    # 2. Character-level similarity (secondary)
    ratio = difflib.SequenceMatcher(None, src, trs).ratio()

    # 3. Exact word-level Jaccard overlap
    src_set = set(src_words)
    trs_set = set(trs_words)
    word_overlap = len(src_set & trs_set) / max(len(src_set | trs_set), 1)

    # 4. Word order score (LCS of exact words)
    matcher = difflib.SequenceMatcher(None, src_words, trs_words)
    matching_words = sum(block.size for block in matcher.get_matching_blocks())
    word_order_score = matching_words / max(len(src_words), len(trs_words), 1)

    # Combined: fuzzy coverage 50%, word_order 25%, ratio 15%, overlap 10%
    # Fuzzy coverage is king — it handles both TTS/ASR noise and skipping.
    combined = (0.50 * fuzzy_coverage + 0.25 * word_order_score
                + 0.15 * ratio + 0.10 * word_overlap)

    return {
        "fuzzy_word_coverage": round(fuzzy_coverage, 4),
        "ratio": round(ratio, 4),
        "word_overlap": round(word_overlap, 4),
        "word_order_score": round(word_order_score, 4),
        "combined": round(combined, 4),
    }


def phase2_transcription_fidelity(
    stories: List[dict],
    voice_filter: Optional[str] = None,
    language: str = "hi",
) -> Dict[str, Dict[str, dict]]:
    """Transcribe audio and compare with source text.

    Returns nested dict: {story_id: {voice: {transcript, fidelity, verdict}}}
    """
    logger.info("═══ Phase 2: Voxtral Transcription + Text Fidelity ═══")
    results = {}
    total_files = 0
    processed = 0
    cache_hits = 0

    # Load transcript cache
    transcript_cache = load_transcript_cache()

    # Count total for progress
    for story in stories:
        for v in story.get("audio_variants", []):
            if voice_filter and v["voice"] != voice_filter:
                continue
            total_files += 1

    logger.info("  Processing %d audio files (%d cached transcripts available)...",
                total_files, len(transcript_cache))

    for story in stories:
        story_id = story["id"]
        title = story.get("title", "untitled")
        source_text = story.get("annotated_text_devanagari", "")
        if not source_text:
            source_text = story.get("annotated_text", story.get("text", ""))

        story_results = {}

        for v in story.get("audio_variants", []):
            voice = v["voice"]
            if voice_filter and voice != voice_filter:
                continue

            audio_path = resolve_audio_path(v["url"])
            if not audio_path:
                logger.warning("  Missing: %s", v["url"])
                story_results[voice] = {
                    "transcript": "",
                    "fidelity": {"ratio": 0, "word_overlap": 0, "word_order_score": 0, "combined": 0},
                    "verdict": "FAIL",
                    "error": "audio file not found",
                }
                continue

            processed += 1
            cache_key = audio_path.name  # e.g. "gen-032f_female_2_hi.mp3"

            try:
                # Check cache first
                if cache_key in transcript_cache:
                    transcript = transcript_cache[cache_key]
                    cache_hits += 1
                    logger.info("  [%d/%d] %s / %s (cached)", processed, total_files, title[:30], voice)
                else:
                    logger.info("  [%d/%d] %s / %s ...", processed, total_files, title[:30], voice)
                    # Small delay between API calls to avoid rate limiting
                    if processed - cache_hits > 1:
                        time.sleep(2)
                    transcript = transcribe_audio(audio_path, language)
                    # Save to cache immediately
                    transcript_cache[cache_key] = transcript

                fidelity = compute_text_fidelity(source_text, transcript)

                score = fidelity["combined"]
                if score >= DEFAULT_FIDELITY_PASS:
                    verdict = "PASS"
                elif score >= DEFAULT_FIDELITY_FAIL:
                    verdict = "WARN"
                else:
                    verdict = "FAIL"

                story_results[voice] = {
                    "transcript": transcript,
                    "fidelity": fidelity,
                    "verdict": verdict,
                }

                symbol = "✓" if verdict == "PASS" else ("⚠" if verdict == "WARN" else "✗")
                logger.info("    %s fidelity=%.2f (%s)", symbol, score, verdict)

            except Exception as e:
                logger.error("    ✗ Transcription failed: %s", e)
                story_results[voice] = {
                    "transcript": "",
                    "fidelity": {"ratio": 0, "word_overlap": 0, "word_order_score": 0, "combined": 0},
                    "verdict": "FAIL",
                    "error": str(e),
                }

        if story_results:
            results[story_id] = story_results

    # Save cache after processing all files
    save_transcript_cache(transcript_cache)
    logger.info("  Transcript cache saved (%d entries, %d new)", len(transcript_cache), processed - cache_hits)

    pass_count = sum(
        1 for s in results.values() for v in s.values() if v.get("verdict") == "PASS"
    )
    warn_count = sum(
        1 for s in results.values() for v in s.values() if v.get("verdict") == "WARN"
    )
    fail_count = sum(
        1 for s in results.values() for v in s.values() if v.get("verdict") == "FAIL"
    )
    logger.info(
        "Phase 2 complete: %d files — %d PASS, %d WARN, %d FAIL",
        processed, pass_count, warn_count, fail_count,
    )
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 3: Voxtral Audio Quality Scoring (Chat Mode)
# ═══════════════════════════════════════════════════════════════════════════

QUALITY_PROMPT_TEMPLATE = """You are evaluating a Hindi children's bedtime story audio narration.

The expected text (Devanagari) is:
{expected_text}

The emotion markers in the original script were: {markers_list}

Score this audio on each dimension (1-10) AND provide a brief reason for each score.
Return ONLY valid JSON (no markdown, no code fences):
{{
  "pronunciation": {{"score": <1-10>, "reason": "brief explanation"}},
  "fluency": {{"score": <1-10>, "reason": "brief explanation"}},
  "pacing": {{"score": <1-10>, "reason": "brief explanation"}},
  "pauses": {{"score": <1-10>, "reason": "brief explanation"}},
  "emotion_delivery": {{"score": <1-10>, "reason": "brief explanation"}},
  "noise_level": {{"score": <1-10>, "reason": "brief explanation"}},
  "completeness": {{"score": <1-10>, "reason": "brief explanation"}},
  "overall": {{"score": <1-10>, "reason": "brief explanation"}},
  "listen_for": ["specific thing to notice at ~timestamp or section"]
}}

For each "reason", be specific about WHAT you heard. E.g.:
- pronunciation: "The word 'sahayogiyon' at 0:23 sounds garbled"
- pacing: "Rushes through the second paragraph, ~2x speed of first"
- pauses: "No pause between sentences at 0:45, sounds run-on"
- completeness: "Audio cuts off mid-sentence around the 3rd paragraph"
- emotion_delivery: "Script calls for [WHISPERING] but speaker uses normal volume"

The "listen_for" array should contain 1-3 specific things the reviewer
should pay attention to when manually listening to this audio."""

QUALITY_DIMENSIONS = [
    "pronunciation", "fluency", "pacing", "pauses",
    "emotion_delivery", "noise_level", "completeness", "overall",
]


def score_audio_quality(audio_path: Path, expected_text: str, markers: List[str]) -> Dict[str, Any]:
    """Use Voxtral chat mode to score audio quality across 8 dimensions.

    Returns dict with per-dimension {score, reason} + listen_for list.
    """
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    # Clean text for the prompt (strip markers)
    clean_text = strip_markers(expected_text)
    markers_str = ", ".join(f"[{m}]" for m in markers) if markers else "none"

    prompt = QUALITY_PROMPT_TEMPLATE.format(
        expected_text=clean_text[:2000],  # Cap to avoid token overload
        markers_list=markers_str,
    )

    def _call():
        response = client.chat.complete(
            model=VOXTRAL_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": audio_b64},
                    {"type": "text", "text": prompt},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return response.choices[0].message.content

    raw = api_call_with_retry(_call)

    # Parse JSON from response
    try:
        # Strip any markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        scores = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("  Failed to parse quality JSON, attempting extraction...")
        # Try to find JSON in the response
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                scores = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error("  Could not parse quality response: %s", raw[:200])
                return _default_quality_scores("Parse error — Voxtral returned invalid JSON")
        else:
            return _default_quality_scores("Parse error — no JSON found in response")

    # Validate and normalize structure
    result = {}
    for dim in QUALITY_DIMENSIONS:
        val = scores.get(dim, {})
        if isinstance(val, dict):
            result[dim] = {
                "score": _clamp(val.get("score", 5), 1, 10),
                "reason": str(val.get("reason", "No reason provided")),
            }
        elif isinstance(val, (int, float)):
            # Voxtral sometimes returns bare numbers
            result[dim] = {
                "score": _clamp(val, 1, 10),
                "reason": "No detailed reason provided",
            }
        else:
            result[dim] = {"score": 5, "reason": "Could not parse score"}

    result["listen_for"] = scores.get("listen_for", [])
    return result


def _clamp(value, lo, hi):
    """Clamp a value between lo and hi."""
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 5


def _default_quality_scores(error_msg: str) -> Dict[str, Any]:
    """Return default scores when API fails."""
    result = {}
    for dim in QUALITY_DIMENSIONS:
        result[dim] = {"score": 5, "reason": f"Could not evaluate — {error_msg}"}
    result["listen_for"] = [f"Manual review needed: {error_msg}"]
    return result


def quality_average(scores: Dict[str, Any]) -> float:
    """Compute average quality score from per-dimension scores."""
    vals = []
    for dim in QUALITY_DIMENSIONS:
        val = scores.get(dim, {})
        if isinstance(val, dict):
            vals.append(val.get("score", 5))
        elif isinstance(val, (int, float)):
            vals.append(val)
    return round(statistics.mean(vals), 1) if vals else 5.0


def phase3_quality_scoring(
    stories: List[dict],
    voice_filter: Optional[str] = None,
) -> Dict[str, Dict[str, dict]]:
    """Score audio quality via Voxtral chat mode.

    Returns nested dict: {story_id: {voice: quality_scores_dict}}
    """
    logger.info("═══ Phase 3: Voxtral Audio Quality Scoring ═══")
    results = {}
    total_files = 0
    processed = 0

    for story in stories:
        for v in story.get("audio_variants", []):
            if voice_filter and v["voice"] != voice_filter:
                continue
            total_files += 1

    logger.info("  Scoring %d audio files with Voxtral chat mode...", total_files)

    for story in stories:
        story_id = story["id"]
        title = story.get("title", "untitled")
        source_text = story.get("annotated_text_devanagari", "")
        if not source_text:
            source_text = story.get("annotated_text", story.get("text", ""))
        markers = extract_markers(source_text)

        story_results = {}

        for v in story.get("audio_variants", []):
            voice = v["voice"]
            if voice_filter and voice != voice_filter:
                continue

            audio_path = resolve_audio_path(v["url"])
            if not audio_path:
                logger.warning("  Missing: %s", v["url"])
                story_results[voice] = _default_quality_scores("audio file not found")
                continue

            processed += 1
            logger.info("  [%d/%d] %s / %s ...", processed, total_files, title[:30], voice)

            # Small delay between API calls to avoid rate limiting
            if processed > 1:
                time.sleep(3)

            try:
                quality = score_audio_quality(audio_path, source_text, markers)
                avg = quality_average(quality)
                story_results[voice] = quality

                symbol = "✓" if avg >= 7 else ("⚠" if avg >= 5 else "✗")
                logger.info("    %s avg_quality=%.1f", symbol, avg)

            except Exception as e:
                logger.error("    ✗ Quality scoring failed: %s", e)
                story_results[voice] = _default_quality_scores(str(e))

        if story_results:
            results[story_id] = story_results

    logger.info("Phase 3 complete: scored %d files", processed)
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Combined Verdict
# ═══════════════════════════════════════════════════════════════════════════

def compute_verdict(
    duration_info: Optional[dict],
    fidelity_info: Optional[dict],
    quality_info: Optional[dict],
    fidelity_pass_threshold: float = DEFAULT_FIDELITY_PASS,
    fidelity_fail_threshold: float = DEFAULT_FIDELITY_FAIL,
) -> dict:
    """Combine all phases into a final PASS / WARN / FAIL verdict.

    Args:
        duration_info: {deviation_pct, is_outlier} from Phase 1
        fidelity_info: {fidelity: {combined, ...}, transcript, verdict} from Phase 2
        quality_info: {pronunciation: {score, reason}, ...} from Phase 3
    """
    reasons = []
    verdict = "PASS"

    # Phase 1: duration
    is_outlier = False
    if duration_info:
        is_outlier = duration_info.get("is_outlier", False)
        if is_outlier:
            reasons.append(f"duration_outlier ({duration_info.get('deviation_pct', 0)}% off)")

    # Phase 2: text fidelity
    text_fidelity = 1.0
    if fidelity_info:
        text_fidelity = fidelity_info.get("fidelity", {}).get("combined", 1.0)
        if text_fidelity < fidelity_fail_threshold:
            reasons.append(f"low_fidelity ({text_fidelity:.2f})")
        elif text_fidelity < fidelity_pass_threshold:
            reasons.append(f"marginal_fidelity ({text_fidelity:.2f})")

    # Phase 3: quality scores
    avg_quality = 5.0
    low_dims = []
    if quality_info:
        avg_quality = quality_average(quality_info)
        for dim in QUALITY_DIMENSIONS:
            val = quality_info.get(dim, {})
            score = val.get("score", 5) if isinstance(val, dict) else 5
            if score < 4:
                low_dims.append(f"{dim}={score}")
            elif score < 5:
                low_dims.append(f"{dim}={score}")

    # Verdict rules
    completeness_score = 5
    overall_score = 5
    if quality_info:
        completeness_score = quality_info.get("completeness", {}).get("score", 5) if isinstance(quality_info.get("completeness"), dict) else 5
        overall_score = quality_info.get("overall", {}).get("score", 5) if isinstance(quality_info.get("overall"), dict) else 5

    # FAIL conditions
    if text_fidelity < fidelity_fail_threshold:
        verdict = "FAIL"
    elif completeness_score < 4:
        verdict = "FAIL"
        reasons.append(f"low_completeness ({completeness_score})")
    elif overall_score < 4:
        verdict = "FAIL"
        reasons.append(f"low_overall ({overall_score})")
    # WARN conditions
    elif text_fidelity < fidelity_pass_threshold:
        verdict = "WARN"
    elif any(
        (quality_info.get(d, {}).get("score", 5) if isinstance(quality_info.get(d), dict) else 5) < 5
        for d in QUALITY_DIMENSIONS
    ) if quality_info else False:
        verdict = "WARN"
        reasons.append(f"low_quality_dims: {', '.join(low_dims)}")
    elif is_outlier:
        verdict = "WARN"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "text_fidelity": text_fidelity,
        "quality_average": avg_quality,
        "duration_outlier": is_outlier,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(
    stories: List[dict],
    phase1: Dict[str, dict],
    phase2: Optional[Dict[str, Dict[str, dict]]],
    phase3: Optional[Dict[str, Dict[str, dict]]],
    fidelity_pass_threshold: float = DEFAULT_FIDELITY_PASS,
    fidelity_fail_threshold: float = DEFAULT_FIDELITY_FAIL,
) -> dict:
    """Combine all phase results into a comprehensive QA report."""
    report_stories = []
    total = 0
    passed = 0
    warned = 0
    failed = 0
    all_fidelities = []
    all_qualities = []

    for story in stories:
        story_id = story["id"]
        title = story.get("title", "untitled")
        p1 = phase1.get(story_id, {})
        p2 = phase2.get(story_id, {}) if phase2 else {}
        p3 = phase3.get(story_id, {}) if phase3 else {}

        variant_reports = []

        for v in story.get("audio_variants", []):
            voice = v["voice"]
            total += 1

            # Gather phase data for this variant
            dur_info = None
            if p1.get("variants"):
                dur_match = [d for d in p1["variants"] if d["voice"] == voice]
                dur_info = dur_match[0] if dur_match else None

            fid_info = p2.get(voice)
            qual_info = p3.get(voice)

            # Compute combined verdict
            combined = compute_verdict(
                dur_info, fid_info, qual_info,
                fidelity_pass_threshold, fidelity_fail_threshold,
            )

            if fid_info and "fidelity" in fid_info:
                all_fidelities.append(fid_info["fidelity"]["combined"])
            if qual_info:
                all_qualities.append(quality_average(qual_info))

            if combined["verdict"] == "PASS":
                passed += 1
            elif combined["verdict"] == "WARN":
                warned += 1
            else:
                failed += 1

            variant_report = {
                "voice": voice,
                "duration_seconds": v.get("duration_seconds", 0),
                "verdict": combined["verdict"],
                "reasons": combined["reasons"],
                "text_fidelity_combined": combined["text_fidelity"],
                "quality_average": combined["quality_average"],
                "duration_outlier": combined["duration_outlier"],
            }

            # Include phase 1 details
            if dur_info:
                variant_report["duration_deviation_pct"] = dur_info.get("deviation_pct", 0)

            # Include phase 2 details
            if fid_info:
                variant_report["text_fidelity"] = fid_info.get("fidelity", {})
                # Include transcript snippet for WARN/FAIL
                if combined["verdict"] != "PASS" and fid_info.get("transcript"):
                    variant_report["transcript_snippet"] = fid_info["transcript"][:300]

            # Include phase 3 details with reasons
            if qual_info:
                variant_report["quality_scores"] = {
                    dim: qual_info[dim] for dim in QUALITY_DIMENSIONS if dim in qual_info
                }
                if qual_info.get("listen_for"):
                    variant_report["listen_for"] = qual_info["listen_for"]

            variant_reports.append(variant_report)

        report_stories.append({
            "story_id": story_id,
            "title": title,
            "median_duration": p1.get("median_duration", 0),
            "variants": variant_reports,
        })

    # Failures summary for quick review
    failures = []
    for s in report_stories:
        for v in s["variants"]:
            if v["verdict"] in ("FAIL", "WARN"):
                entry = {
                    "story": s["title"],
                    "story_id": s["story_id"],
                    "voice": v["voice"],
                    "verdict": v["verdict"],
                    "reasons": v["reasons"],
                    "fidelity": v.get("text_fidelity_combined", None),
                    "quality_avg": v.get("quality_average", None),
                }
                # Include listen_for if available
                if v.get("listen_for"):
                    entry["listen_for"] = v["listen_for"]
                # Include per-dim reasons for scores < 6
                if v.get("quality_scores"):
                    low_scores = {}
                    for dim, info in v["quality_scores"].items():
                        if isinstance(info, dict) and info.get("score", 10) < 6:
                            low_scores[dim] = info
                    if low_scores:
                        entry["low_quality_details"] = low_scores
                failures.append(entry)

    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "avg_fidelity": round(statistics.mean(all_fidelities), 4) if all_fidelities else None,
            "avg_quality": round(statistics.mean(all_qualities), 1) if all_qualities else None,
        },
        "stories": report_stories,
        "failures_summary": failures,
    }

    return report


def print_summary(report: dict):
    """Print a human-readable summary of the QA report."""
    s = report["summary"]
    print("\n" + "=" * 70)
    print("  AUDIO QA REPORT SUMMARY")
    print("=" * 70)
    print(f"  Total variants:   {s['total']}")
    print(f"  ✓ Passed:         {s['passed']}")
    print(f"  ⚠ Warned:         {s['warned']}")
    print(f"  ✗ Failed:         {s['failed']}")
    if s.get("avg_fidelity") is not None:
        print(f"  Avg fidelity:     {s['avg_fidelity']:.4f}")
    if s.get("avg_quality") is not None:
        print(f"  Avg quality:      {s['avg_quality']:.1f}/10")
    print("=" * 70)

    if report["failures_summary"]:
        print(f"\n  ISSUES ({len(report['failures_summary'])} variants):")
        print("  " + "-" * 66)
        for f in report["failures_summary"]:
            icon = "✗" if f["verdict"] == "FAIL" else "⚠"
            print(f"  {icon} {f['story'][:35]:35s} / {f['voice']:15s} [{f['verdict']}]")
            if f.get("reasons"):
                print(f"    Reasons: {', '.join(f['reasons'])}")
            if f.get("fidelity") is not None:
                print(f"    Text fidelity: {f['fidelity']:.2f}")
            if f.get("quality_avg") is not None:
                print(f"    Quality avg: {f['quality_avg']:.1f}/10")
            # Show what to listen for
            if f.get("listen_for"):
                for lf in f["listen_for"]:
                    print(f"    👂 Listen for: {lf}")
            # Show low quality dimension details
            if f.get("low_quality_details"):
                for dim, info in f["low_quality_details"].items():
                    print(f"    📉 {dim}: {info['score']}/10 — {info['reason']}")
            print()
    else:
        print("\n  All variants passed! 🎉\n")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Voxtral-based Audio QA for Dream Valley",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--lang", default="hi", help="Language filter (default: hi)")
    parser.add_argument("--story-id", help="QA a specific story ID")
    parser.add_argument("--voice", help="QA a specific voice only")
    parser.add_argument("--threshold", type=float, default=DEFAULT_FIDELITY_PASS,
                        help=f"Fidelity pass threshold (default: {DEFAULT_FIDELITY_PASS})")
    parser.add_argument("--duration-only", action="store_true",
                        help="Phase 1 only (duration anomaly, no API cost)")
    parser.add_argument("--no-quality-score", action="store_true",
                        help="Phase 1+2 only (skip quality scoring)")
    parser.add_argument("--quality-only", action="store_true",
                        help="Phase 1+3 only (skip transcription fidelity)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan and estimated cost without running")
    args = parser.parse_args()

    # Ensure ffmpeg is available (for pydub)
    ffmpeg_path = os.popen("which ffmpeg").read().strip()
    if not ffmpeg_path and os.path.exists("/opt/homebrew/bin/ffmpeg"):
        os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

    # Load stories
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        all_stories = json.load(f)

    # Filter
    stories = all_stories
    if args.lang:
        stories = [s for s in stories if s.get("lang") == args.lang]
    if args.story_id:
        stories = [s for s in stories if s["id"] == args.story_id]

    if not stories:
        logger.error("No stories found matching filters (lang=%s, story_id=%s)", args.lang, args.story_id)
        sys.exit(1)

    # Count variants
    variant_count = 0
    total_duration = 0
    for s in stories:
        for v in s.get("audio_variants", []):
            if args.voice and v["voice"] != args.voice:
                continue
            variant_count += 1
            total_duration += v.get("duration_seconds", 0)

    logger.info("QA target: %d stories, %d variants, %.1f min audio", len(stories), variant_count, total_duration / 60)

    if args.dry_run:
        print("\n  DRY RUN — QA Plan:")
        print(f"  Stories:    {len(stories)}")
        print(f"  Variants:   {variant_count}")
        print(f"  Duration:   {total_duration / 60:.1f} min")
        print(f"  Phases:     ", end="")
        phases = ["1 (duration)"]
        if not args.duration_only and not args.quality_only:
            phases.append("2 (transcription)")
        if not args.duration_only and not args.no_quality_score:
            phases.append("3 (quality)")
        print(", ".join(phases))
        est_cost = total_duration / 60 * 0.003  # transcription only
        if not args.duration_only:
            print(f"  Est. cost:  ~${est_cost:.2f} (transcription) + chat tokens")
        else:
            print(f"  Est. cost:  $0.00 (duration-only)")
        print()
        return

    # ── Phase 1: always runs ──
    phase1 = phase1_duration_analysis(stories)

    # ── Phase 2: transcription fidelity ──
    phase2 = None
    if not args.duration_only and not args.quality_only:
        phase2 = phase2_transcription_fidelity(stories, voice_filter=args.voice, language=args.lang)

    # ── Phase 3: quality scoring ──
    phase3 = None
    if not args.duration_only and not args.no_quality_score:
        phase3 = phase3_quality_scoring(stories, voice_filter=args.voice)

    # ── Generate report ──
    report = generate_report(
        stories, phase1, phase2, phase3,
        fidelity_pass_threshold=args.threshold,
    )

    # Save report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"qa_audio_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Also save as "latest" symlink
    latest_path = REPORT_DIR / "qa_audio_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("Report saved: %s", report_path)
    logger.info("Latest link: %s", latest_path)

    # Print summary
    print_summary(report)


if __name__ == "__main__":
    main()
