#!/usr/bin/env python3
"""
Generate audio for the 24 newly selected stories (top 2 per age group per language).

PARALLEL GENERATION: Runs multiple stories/voices simultaneously using ThreadPoolExecutor.
Modal auto-scales containers, so parallel requests = faster generation.

1. Reads qa_selected.json (top 2 per group)
2. Enriches with annotated_text + annotated_text_devanagari from content_expanded.json
3. Saves as content_new.json in the format generate_audio.py expects
4. Generates 7 voice variants per story (168 total audio files) IN PARALLEL

Usage:
    python3 scripts/generate_new_stories.py --dry-run        # Show plan only
    python3 scripts/generate_new_stories.py                  # Generate all (6 parallel)
    python3 scripts/generate_new_stories.py --workers 10     # 10 parallel workers
    python3 scripts/generate_new_stories.py --lang en        # English only
    python3 scripts/generate_new_stories.py --lang hi        # Hindi only
"""

import argparse
import io
import json
import logging
import os
import re
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from pydub import AudioSegment

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
QA_SELECTED_PATH = BASE_DIR / "seed_output" / "qa_selected.json"
EXPANDED_PATH = BASE_DIR / "seed_output" / "content_expanded.json"
CONTENT_NEW_PATH = BASE_DIR / "seed_output" / "content_new.json"
OUTPUT_DIR = BASE_DIR / "audio" / "pre-gen"

# ── Chatterbox Modal endpoint ────────────────────────────────────────────
CHATTERBOX_URL = "https://anmol-71634--dreamweaver-chatterbox-tts.modal.run"
CHATTERBOX_HEALTH = "https://anmol-71634--dreamweaver-chatterbox-health.modal.run"

# ── Emotion profiles ─────────────────────────────────────────────────────
EMOTION_PROFILES: Dict[str, dict] = {
    "sleepy":      {"exaggeration": 0.3,  "cfg_weight": 0.3},
    "gentle":      {"exaggeration": 0.5,  "cfg_weight": 0.4},
    "calm":        {"exaggeration": 0.5,  "cfg_weight": 0.5},
    "excited":     {"exaggeration": 0.7,  "cfg_weight": 0.5},
    "curious":     {"exaggeration": 0.6,  "cfg_weight": 0.5},
    "adventurous": {"exaggeration": 0.7,  "cfg_weight": 0.4},
    "mysterious":  {"exaggeration": 0.5,  "cfg_weight": 0.3},
    "joyful":      {"exaggeration": 0.7,  "cfg_weight": 0.5},
    "dramatic":    {"exaggeration": 0.7,  "cfg_weight": 0.3},
    "whispering":  {"exaggeration": 0.3,  "cfg_weight": 0.3},
    "rhythmic":    {"exaggeration": 0.5,  "cfg_weight": 0.3},
    "singing":     {"exaggeration": 0.7,  "cfg_weight": 0.3},
    "humming":     {"exaggeration": 0.4,  "cfg_weight": 0.3},
}

CONTENT_TYPE_PROFILES: Dict[str, dict] = {
    "story": {"exaggeration": 0.5, "cfg_weight": 0.5},
    "poem":  {"exaggeration": 0.5, "cfg_weight": 0.3},
    "song":  {"exaggeration": 0.7, "cfg_weight": 0.3},
}

PAUSE_MARKERS = {
    "pause": 800,
    "dramatic_pause": 1500,
}

_MARKER_RE = re.compile(
    r"\["
    r"(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
    r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
    r"HUMMING|PAUSE|laugh|chuckle)"
    r"\]",
    re.IGNORECASE,
)

VOICE_MAP = {
    "en": ["female_1", "female_2", "female_3", "male_1", "male_2", "male_3", "asmr"],
    "hi": ["female_1_hi", "female_2_hi", "female_3_hi", "male_1_hi", "male_2_hi", "male_3_hi", "asmr_hi"],
}

NATIVE_SAMPLE_RATE = 24000

# Thread-safe counters
_lock = threading.Lock()
_success = 0
_failed = 0
_skipped = 0
_results = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Step 1: Prepare stories
# ═══════════════════════════════════════════════════════════════════════

def prepare_stories(lang_filter=None):
    """Extract top 2 per group, enrich with annotated text."""
    with open(QA_SELECTED_PATH, 'r') as f:
        qa_data = json.load(f)
    with open(EXPANDED_PATH, 'r') as f:
        expanded = json.load(f)

    expanded_idx = {s['id']: s for s in expanded}

    stories = []
    for key in sorted(qa_data.keys()):
        top2 = qa_data[key][:2]
        for s in top2:
            full = expanded_idx.get(s['id'])
            if not full:
                logger.warning("Story %s not found in expanded!", s['id'])
                continue

            lang = full.get('lang', 'en')
            if lang_filter and lang != lang_filter:
                continue

            story = {
                "id": full["id"],
                "type": full.get("type", "story"),
                "lang": lang,
                "title": full["title"],
                "description": full.get("description", ""),
                "text": full.get("text", ""),
                "annotated_text": full.get("annotated_text", full.get("text", "")),
                "target_age": full.get("target_age", 4),
                "age_group": full.get("age_group", s.get("age_group", "")),
                "word_count": full.get("word_count", s.get("word_count", 0)),
                "theme": full.get("theme", s.get("theme", "")),
                "geography": full.get("geography", s.get("geography", "")),
                "lead_gender": full.get("lead_gender", s.get("lead_gender", "")),
                "categories": full.get("categories", []),
                "morals": full.get("morals", []),
                "cover": full.get("cover", ""),
                "musicProfile": full.get("musicProfile", {}),
                "music_type": full.get("music_type", ""),
            }

            if lang == "hi" and full.get("annotated_text_devanagari"):
                story["annotated_text_devanagari"] = full["annotated_text_devanagari"]

            stories.append(story)

    logger.info("Prepared %d stories for audio generation", len(stories))
    return stories


# ═══════════════════════════════════════════════════════════════════════
# Audio helpers
# ═══════════════════════════════════════════════════════════════════════

def audio_from_bytes(audio_bytes: bytes) -> AudioSegment:
    return AudioSegment.from_file(io.BytesIO(audio_bytes))

def generate_silence(duration_ms: int) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms, frame_rate=NATIVE_SAMPLE_RATE)

def get_mp3_duration(filepath: Path) -> float:
    try:
        audio = AudioSegment.from_file(str(filepath))
        return len(audio) / 1000.0
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════
# Text parsing
# ═══════════════════════════════════════════════════════════════════════

def parse_annotated_text(text: str, content_type: str = "story") -> List[dict]:
    segments = []
    base_profile = CONTENT_TYPE_PROFILES.get(content_type, CONTENT_TYPE_PROFILES["story"])
    current_profile = dict(base_profile)

    parts = _MARKER_RE.split(text)
    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        marker_lower = part_stripped.lower()
        if marker_lower in PAUSE_MARKERS:
            segments.append({"type": "pause", "duration_ms": PAUSE_MARKERS[marker_lower]})
        elif marker_lower in EMOTION_PROFILES:
            current_profile = dict(EMOTION_PROFILES[marker_lower])
        elif marker_lower in ("laugh", "chuckle"):
            continue
        else:
            clean_text = part_stripped.strip()
            if clean_text:
                segments.append({
                    "type": "speech",
                    "text": clean_text,
                    "exaggeration": current_profile["exaggeration"],
                    "cfg_weight": current_profile["cfg_weight"],
                })

    return segments


# ═══════════════════════════════════════════════════════════════════════
# TTS generation
# ═══════════════════════════════════════════════════════════════════════

def generate_tts_segment(
    client: httpx.Client,
    text: str,
    voice: str,
    exaggeration: float,
    cfg_weight: float,
    lang: str = "en",
    speed: float = 0.8,
    max_retries: int = 3,
) -> Optional[bytes]:
    params = {
        "text": text,
        "voice": voice,
        "lang": lang,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "speed": speed,
        "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"

    for attempt in range(max_retries):
        try:
            resp = client.get(url, timeout=180.0)
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
            else:
                logger.warning("    TTS %d: %s", resp.status_code, resp.text[:200] if resp.text else "empty")
        except httpx.TimeoutException:
            logger.warning("    Timeout (attempt %d/%d)", attempt + 1, max_retries)
        except Exception as e:
            logger.warning("    Error (attempt %d/%d): %s", attempt + 1, max_retries, e)

        if attempt < max_retries - 1:
            time.sleep(5 * (attempt + 1))

    return None


def warm_up_chatterbox() -> bool:
    logger.info("Warming up Chatterbox Modal container...")
    client = httpx.Client(timeout=180.0)
    try:
        resp = client.get(CHATTERBOX_HEALTH, timeout=30.0)
        if resp.status_code == 200:
            data = resp.json()
            logger.info("Chatterbox healthy: %s, voices: %s",
                       data.get("engine"), data.get("voice_refs"))
            client.close()
            return True
    except Exception as e:
        logger.warning("Health check failed: %s", e)

    # Warm up with a quick TTS call
    logger.info("Sending warm-up TTS request...")
    try:
        params = {"text": "Hello", "voice": "female_1", "exaggeration": 0.3, "cfg_weight": 0.4}
        resp = client.get(f"{CHATTERBOX_URL}?{urlencode(params)}", timeout=180.0)
        logger.info("Warm-up: %d (%d bytes)", resp.status_code, len(resp.content))
        client.close()
        return resp.status_code == 200
    except Exception as e:
        logger.error("Warm-up failed: %s", e)
        client.close()
        return False


# ═══════════════════════════════════════════════════════════════════════
# Single variant generation (runs in its own thread)
# ═══════════════════════════════════════════════════════════════════════

def generate_single_variant(
    story: dict,
    voice: str,
    output_path: Path,
    task_num: int,
    total: int,
    force: bool = False,
    speed: float = 0.8,
) -> Optional[dict]:
    """Generate a single audio variant. Each thread gets its own HTTP client."""
    global _success, _failed, _skipped, _results

    story_id = story["id"]
    lang = story.get("lang", "en")
    content_type = story.get("type", "story")
    title = story["title"]
    ts = datetime.now().strftime("%H:%M:%S")

    if output_path.exists() and not force:
        logger.info("[%s] [%d/%d] SKIP %s / %s (exists)", ts, task_num, total, title[:30], voice)
        duration = get_mp3_duration(output_path)
        result = {
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        }
        with _lock:
            _skipped += 1
            _results.setdefault(story_id, []).append(result)
        return result

    # For Hindi: prefer Devanagari text
    if lang == "hi" and story.get("annotated_text_devanagari"):
        text = story["annotated_text_devanagari"]
    else:
        text = story.get("annotated_text", story.get("text", ""))

    if not text:
        logger.error("[%s] [%d/%d] NO TEXT %s / %s", ts, task_num, total, title[:30], voice)
        with _lock:
            _failed += 1
        return None

    logger.info("[%s] [%d/%d] START %s / %s (%s, %dw)",
                ts, task_num, total, title[:30], voice, lang, story.get("word_count", 0))

    # Each thread gets its own HTTP client
    client = httpx.Client(timeout=180.0)

    try:
        paragraphs = text.split("\n\n")
        audio_segments: List[AudioSegment] = []

        for i, para in enumerate(paragraphs):
            para = para.strip()
            if not para:
                continue

            para_segments = parse_annotated_text(para, content_type)

            for seg in para_segments:
                if seg["type"] == "pause":
                    audio_segments.append(generate_silence(seg["duration_ms"]))
                elif seg["type"] == "speech":
                    audio_bytes = generate_tts_segment(
                        client,
                        text=seg["text"],
                        voice=voice,
                        exaggeration=seg["exaggeration"],
                        cfg_weight=seg["cfg_weight"],
                        lang=lang,
                        speed=speed,
                    )
                    if audio_bytes:
                        try:
                            seg_audio = audio_from_bytes(audio_bytes)
                            audio_segments.append(seg_audio)
                        except Exception as e:
                            logger.error("[%s] [%d/%d] DECODE FAIL %s / %s: %s",
                                        ts, task_num, total, title[:30], voice, e)
                            with _lock:
                                _failed += 1
                            return None
                    else:
                        logger.error("[%s] [%d/%d] TTS FAIL %s / %s seg: %.40s...",
                                    ts, task_num, total, title[:30], voice, seg["text"])
                        with _lock:
                            _failed += 1
                        return None

            if i < len(paragraphs) - 1:
                audio_segments.append(generate_silence(1000))

        if not audio_segments:
            logger.error("[%s] [%d/%d] NO SEGMENTS %s / %s", ts, task_num, total, title[:30], voice)
            with _lock:
                _failed += 1
            return None

        # Assemble
        combined = audio_segments[0]
        for seg_audio in audio_segments[1:]:
            combined = combined + seg_audio

        # Normalize to -16 dBFS
        try:
            target_db = -16.0
            gain = target_db - combined.dBFS
            combined = combined.apply_gain(gain)
        except Exception:
            pass

        # Gentle fade in/out
        try:
            fade_in_ms = min(500, len(combined) // 4)
            fade_out_ms = min(1500, len(combined) // 3)
            combined = combined.fade_in(fade_in_ms).fade_out(fade_out_ms)
        except Exception:
            pass

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.export(str(output_path), format="mp3", bitrate="256k")

        duration = len(combined) / 1000.0
        size_kb = output_path.stat().st_size / 1024

        ts2 = datetime.now().strftime("%H:%M:%S")
        logger.info("[%s] [%d/%d] ✓ DONE %s / %s (%.0fKB, %.1fs)",
                    ts2, task_num, total, title[:30], voice, size_kb, duration)

        result = {
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        }

        with _lock:
            _success += 1
            _results.setdefault(story_id, []).append(result)

        return result

    except Exception as e:
        ts2 = datetime.now().strftime("%H:%M:%S")
        logger.error("[%s] [%d/%d] ERROR %s / %s: %s",
                    ts2, task_num, total, title[:30], voice, e)
        with _lock:
            _failed += 1
        return None

    finally:
        client.close()


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate audio for 24 new stories (PARALLEL)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    parser.add_argument("--force", action="store_true", help="Regenerate existing files")
    parser.add_argument("--lang", help="Filter by language (en/hi)")
    parser.add_argument("--speed", type=float, default=0.8, help="Playback speed (default: 0.8)")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers (default: 6)")
    args = parser.parse_args()

    # Ensure ffmpeg
    ffmpeg_path = os.popen("which ffmpeg").read().strip()
    if not ffmpeg_path:
        if os.path.exists("/opt/homebrew/bin/ffmpeg"):
            os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
        else:
            logger.error("ffmpeg not found!")
            sys.exit(1)

    # Step 1: Prepare stories
    stories = prepare_stories(lang_filter=args.lang)
    if not stories:
        logger.error("No stories to generate!")
        sys.exit(1)

    # Save enriched stories for reference
    with open(CONTENT_NEW_PATH, 'w') as f:
        json.dump(stories, f, ensure_ascii=False, indent=2)
    logger.info("Saved enriched stories to %s", CONTENT_NEW_PATH)

    # Build plan
    plan = []
    for story in stories:
        lang = story.get("lang", "en")
        voices = VOICE_MAP.get(lang, VOICE_MAP["en"])
        for voice in voices:
            story_id_short = story["id"][:8]
            output_path = OUTPUT_DIR / f"{story_id_short}_{voice}.mp3"
            plan.append({
                "story": story,
                "voice": voice,
                "output_path": output_path,
                "exists": output_path.exists(),
            })

    existing = sum(1 for p in plan if p["exists"])
    to_generate = len(plan) - existing if not args.force else len(plan)

    logger.info("")
    logger.info("=" * 70)
    logger.info("  PARALLEL AUDIO GENERATION PLAN")
    logger.info("=" * 70)
    logger.info("  Stories: %d (EN: %d, HI: %d)",
                len(stories),
                sum(1 for s in stories if s['lang'] == 'en'),
                sum(1 for s in stories if s['lang'] == 'hi'))
    logger.info("  Voices per story: 7")
    logger.info("  Total variants: %d", len(plan))
    logger.info("  Already exist: %d", existing)
    logger.info("  To generate: %d", to_generate)
    logger.info("  Speed: %.1f", args.speed)
    logger.info("  Workers: %d (parallel)", args.workers)
    logger.info("=" * 70)

    for story in stories:
        lang = story['lang']
        voices = VOICE_MAP[lang]
        existing_for_story = sum(
            1 for v in voices
            if (OUTPUT_DIR / f"{story['id'][:8]}_{v}.mp3").exists()
        )
        status = f"{existing_for_story}/7 exist" if existing_for_story > 0 else "NEW"
        logger.info("  [%s] %s — %s (%s, %dw) [%s]",
                    lang.upper(), story['title'][:40], story['age_group'],
                    story['type'], story['word_count'], status)

    if args.dry_run:
        logger.info("")
        logger.info("Dry run complete. Use without --dry-run to generate.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Warm up Modal
    if not warm_up_chatterbox():
        logger.error("Failed to warm up Chatterbox. Aborting.")
        sys.exit(1)

    # === PARALLEL GENERATION ===
    start_time = time.time()
    total = len(plan)

    logger.info("")
    logger.info("Starting parallel generation with %d workers...", args.workers)
    logger.info("")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for i, item in enumerate(plan):
            future = executor.submit(
                generate_single_variant,
                story=item["story"],
                voice=item["voice"],
                output_path=item["output_path"],
                task_num=i + 1,
                total=total,
                force=args.force,
                speed=args.speed,
            )
            futures[future] = item

        # Wait for all to complete
        for future in as_completed(futures):
            item = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error("Worker error for %s / %s: %s",
                           item["story"]["title"][:30], item["voice"], e)

    elapsed = time.time() - start_time

    # Update content_new.json with audio_variants
    for story in stories:
        if story["id"] in _results:
            story["audio_variants"] = _results[story["id"]]

    with open(CONTENT_NEW_PATH, 'w') as f:
        json.dump(stories, f, ensure_ascii=False, indent=2)

    logger.info("")
    logger.info("=" * 70)
    logger.info("  GENERATION COMPLETE")
    logger.info("=" * 70)
    logger.info("  Time: %.1f minutes (%.0f seconds)", elapsed / 60, elapsed)
    logger.info("  Generated: %d", _success)
    logger.info("  Skipped: %d", _skipped)
    logger.info("  Failed: %d", _failed)
    logger.info("  Total MP3 files in output: %d", len(list(OUTPUT_DIR.glob("*.mp3"))))
    logger.info("  Results saved to: %s", CONTENT_NEW_PATH)
    logger.info("=" * 70)

    # Print per-story summary
    for story in stories:
        variants = story.get("audio_variants", [])
        logger.info("  %s: %d/7 variants", story["title"][:40], len(variants))

    if _failed > 0:
        logger.warning("")
        logger.warning("  %d variants FAILED. Re-run without --force to retry only missing ones.", _failed)


if __name__ == "__main__":
    main()
