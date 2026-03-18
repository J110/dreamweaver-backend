#!/usr/bin/env python3
"""Automated content pipeline — generate, QA, enrich, and publish new stories/poems/lullabies.

Runs the full pipeline as subprocesses for isolation and crash safety.
Designed to run autonomously on the GCP production server (daily cron).

Pipeline flow:
  1. GENERATE    → Mistral Large (free tier) → stories + poems + lullabies
  2. AUDIO GEN   → Modal Chatterbox TTS + ACE-Step ($30 free credits) → 14+3 MP3 files per 3 items
  3. AUDIO QA    → Voxtral transcription + fidelity (free tier) → PASS/FAIL
  4. ENRICH      → Mistral Large (free tier) → musicParams for new items
  5. MOOD        → Mistral Small (free tier) → mood tag (calm/curious/wired/sad/anxious/angry)
  6. COVERS      → FLUX.1 Schnell (HuggingFace free tier, 3 retries) → 2-layer covers (Mistral SVG fallback)
  7. SYNC        → sync content.json → seedData.js + copy audio/covers to web (BEFORE clips)
  8. CLIPS       → FFmpeg (cairosvg + Ken Burns) → 60s vertical video clips for social media
  9. PUBLISH     → git push → Render/Vercel auto-deploy (test only)
  10. DEPLOY PROD → rebuild frontend + restart backend on local GCP VM
  11. NOTIFY      → email via Resend (success or failure)

Usage:
    python3 scripts/pipeline_run.py                           # Full pipeline
    python3 scripts/pipeline_run.py --dry-run                 # Show plan, no API calls
    python3 scripts/pipeline_run.py --count-stories 2         # Generate 2 stories
    python3 scripts/pipeline_run.py --count-poems 1           # Generate 1 poem
    python3 scripts/pipeline_run.py --lang en                 # English only
    python3 scripts/pipeline_run.py --skip-publish             # Don't git push
    python3 scripts/pipeline_run.py --resume                   # Resume from last checkpoint
    python3 scripts/pipeline_run.py --step generate            # Run only one step
"""

import argparse
import json
import logging
import os
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent

# ── Load .env so pipeline can check required keys ────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass  # Individual scripts also load dotenv
SCRIPTS_DIR = BASE_DIR / "scripts"
SEED_OUTPUT = BASE_DIR / "seed_output"
CONTENT_PATH = SEED_OUTPUT / "content.json"
CONTENT_EXPANDED_PATH = SEED_OUTPUT / "content_expanded.json"
STATE_PATH = SEED_OUTPUT / "pipeline_state.json"
WEB_DIR = BASE_DIR.parent / "dreamweaver-web"

# ── Logging ──────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(log_file)),
    ],
)
logger = logging.getLogger("pipeline")

# ── Pipeline steps ───────────────────────────────────────────────────────
STEPS = ["generate", "audio", "qa", "enrich", "mood", "covers", "sync", "clips", "publish", "deploy_prod"]

CHATTERBOX_HEALTH = "https://j110--dreamweaver-chatterbox-health.modal.run"


def load_state() -> dict:
    """Load pipeline state for crash-resume."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_state(state: dict):
    """Save pipeline state."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str) + "\n")


def _limit_memory():
    """preexec_fn: cap child-process virtual memory at 1 GB."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    except (ValueError, OSError):
        pass


def run_command(cmd: list, label: str, timeout: int = 3600, cwd: str = None,
                memory_limit: bool = False) -> tuple:
    """Run a subprocess command, return (success, stdout, stderr, elapsed).

    Args:
        memory_limit: if True, cap child virtual memory at 1 GB to prevent
            memory-hungry subprocesses from starving the app server.
    """
    logger.info("━━━ %s ━━━", label)
    logger.info("Command: %s", " ".join(cmd))
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or str(BASE_DIR),
            preexec_fn=_limit_memory if memory_limit else None,
        )
        elapsed = time.time() - start

        if result.stdout:
            for line in result.stdout.strip().split("\n")[-50:]:
                logger.info("  %s", line)

        if result.returncode != 0:
            logger.error("  FAILED (exit code %d, %.0fs)", result.returncode, elapsed)
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    logger.error("  stderr: %s", line)
            return False, result.stdout, result.stderr, elapsed

        # Log stderr even on success — catches warnings and sub-step failures
        # (e.g. clip generation logs progress to stderr via Python logging)
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-20:]:
                logger.info("  [stderr] %s", line)

        logger.info("  OK (%.0fs)", elapsed)
        return True, result.stdout, result.stderr, elapsed

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        logger.error("  TIMEOUT after %.0fs", elapsed)
        return False, "", "Timeout", elapsed
    except Exception as e:
        elapsed = time.time() - start
        logger.error("  EXCEPTION: %s", e)
        return False, "", str(e), elapsed


def get_new_story_ids(before_ids: set) -> list:
    """Find story IDs that were added after a generation step."""
    if not CONTENT_EXPANDED_PATH.exists():
        return []
    try:
        stories = json.loads(CONTENT_EXPANDED_PATH.read_text())
        current_ids = {s["id"] for s in stories}
        new_ids = current_ids - before_ids
        return sorted(new_ids)
    except (json.JSONDecodeError, IOError):
        return []


def get_existing_ids() -> set:
    """Get all story IDs from content_expanded.json."""
    if not CONTENT_EXPANDED_PATH.exists():
        return set()
    try:
        stories = json.loads(CONTENT_EXPANDED_PATH.read_text())
        return {s["id"] for s in stories}
    except (json.JSONDecodeError, IOError):
        return set()


def merge_expanded_to_content(new_ids: list) -> int:
    """Merge newly generated items from content_expanded.json into content.json."""
    if not new_ids:
        return 0

    # Load content_expanded.json (generation output)
    expanded = json.loads(CONTENT_EXPANDED_PATH.read_text())
    expanded_map = {s["id"]: s for s in expanded}

    # Load content.json (the master content file used by audio/music/etc.)
    if CONTENT_PATH.exists():
        content = json.loads(CONTENT_PATH.read_text())
    else:
        content = []

    existing_ids = {s["id"] for s in content}
    added = 0

    for sid in new_ids:
        if sid not in existing_ids and sid in expanded_map:
            content.append(expanded_map[sid])
            added += 1

    if added > 0:
        CONTENT_PATH.write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        )
        logger.info("  Merged %d new items into content.json (total: %d)", added, len(content))

    return added


# ═══════════════════════════════════════════════════════════════════════
# EXPERIMENTAL MOOD DETECTION
# ═══════════════════════════════════════════════════════════════════════

def _count_todays_pregenerated_content() -> dict:
    """Count content generated today by experimental or mood runs.

    Checks BOTH content_expanded.json and content.json for items created
    today that were NOT generated by the main pipeline (i.e. items that
    already exist before the main pipeline's generation step runs).

    Uses server-local date (not UTC) since cron runs in local time.
    """
    counts = {"story": 0, "long_story": 0, "poem": 0, "song": 0}
    today_str = datetime.now().strftime("%Y-%m-%d")
    seen_ids = set()

    # Check both content sources for today's pre-existing items
    for path in [CONTENT_EXPANDED_PATH, CONTENT_PATH]:
        if not path.exists():
            continue
        try:
            items = json.loads(path.read_text())
            for item in items:
                sid = item.get("id", "")
                if not sid.startswith("gen-") or sid in seen_ids:
                    continue
                created = item.get("created_at", "")
                if created[:10] == today_str:
                    ctype = item.get("type", "story")
                    if ctype in counts:
                        counts[ctype] += 1
                        seen_ids.add(sid)
        except (json.JSONDecodeError, IOError):
            continue

    return counts


# ═══════════════════════════════════════════════════════════════════════
# PIPELINE STEPS
# ═══════════════════════════════════════════════════════════════════════

def step_generate(args, state: dict) -> bool:
    """Step 1: Generate new stories and poems via Mistral AI."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 1: GENERATE CONTENT            ║")
    logger.info("╚══════════════════════════════════════╝")

    # If this is NOT a mood run, check if experimental content was already
    # generated today and reduce counts to avoid exceeding daily targets.
    count_stories = args.count_stories
    count_poems = args.count_poems
    count_lullabies = args.count_lullabies
    count_long_stories = args.count_long_stories

    if not args.mood:
        pregen_counts = _count_todays_pregenerated_content()
        pregen_total = sum(pregen_counts.values())
        if pregen_total > 0:
            logger.info("  Pre-existing content found today: %s", pregen_counts)
            # Subtract pre-generated counts from daily targets
            count_stories = max(0, count_stories - pregen_counts["story"])
            count_long_stories = max(0, count_long_stories - pregen_counts["long_story"])
            count_poems = max(0, count_poems - pregen_counts["poem"])
            count_lullabies = max(0, count_lullabies - pregen_counts["song"])
            skipped = []
            if pregen_counts["story"]: skipped.append(f"{pregen_counts['story']} story")
            if pregen_counts["long_story"]: skipped.append(f"{pregen_counts['long_story']} long story")
            if pregen_counts["poem"]: skipped.append(f"{pregen_counts['poem']} poem")
            if pregen_counts["song"]: skipped.append(f"{pregen_counts['song']} lullaby")
            logger.info("  Skipping %s (already generated by experimental/mood run)", ", ".join(skipped))
            state["mood_skip"] = pregen_counts

    total_requested = count_stories + count_long_stories + count_poems + count_lullabies
    if total_requested == 0:
        logger.info("  No new content requested (all counts = 0). Skipping generation.")
        return True

    before_ids = get_existing_ids()

    # Build the generation command using --count-stories/--count-poems/--count-lullabies for fresh daily content
    cmd = [
        sys.executable, str(SCRIPTS_DIR / "generate_content_matrix.py"),
        "--api", "mistral",
        "--count-stories", str(count_stories),
        "--count-poems", str(count_poems),
        "--count-lullabies", str(count_lullabies),
        "--count-long-stories", str(count_long_stories),
    ]
    if args.lang:
        cmd += ["--lang", args.lang]
    if args.mood:
        cmd += ["--mood", args.mood]
    if args.age:
        cmd += ["--age", args.age]
    if args.dry_run:
        cmd += ["--dry-run"]

    ok, stdout, stderr, elapsed = run_command(cmd, "Content Generation", timeout=1800)

    if not ok:
        return False

    # Find newly generated IDs
    new_ids = get_new_story_ids(before_ids)
    logger.info("  New items generated: %d", len(new_ids))

    # Log story vs poem vs lullaby breakdown and store per-type counts
    if new_ids and CONTENT_EXPANDED_PATH.exists():
        try:
            expanded = json.loads(CONTENT_EXPANDED_PATH.read_text())
            new_items = [s for s in expanded if s["id"] in set(new_ids)]
            story_count = sum(1 for s in new_items if s.get("type") == "story")
            long_story_count = sum(1 for s in new_items if s.get("type") == "long_story")
            poem_count = sum(1 for s in new_items if s.get("type") == "poem")
            song_count = sum(1 for s in new_items if s.get("type") == "song")
            logger.info("  Breakdown: %d stories, %d long stories, %d poems, %d lullabies",
                        story_count, long_story_count, poem_count, song_count)
            state["generated_stories"] = story_count + long_story_count
            state["generated_poems"] = poem_count
            state["generated_lullabies"] = song_count
        except Exception:
            pass

    # Validate generation count — retry missing content types on partial failure
    expected = args.count_stories + args.count_long_stories + args.count_poems + args.count_lullabies
    actual = len(new_ids)
    if actual < expected and not args.dry_run:
        logger.warning("  PARTIAL GENERATION: expected %d items but only got %d", expected, actual)

        # Determine which content types are missing
        generated_types = {"story": 0, "long_story": 0, "poem": 0, "song": 0}
        if new_ids and CONTENT_EXPANDED_PATH.exists():
            try:
                expanded = json.loads(CONTENT_EXPANDED_PATH.read_text())
                for item in expanded:
                    if item["id"] in set(new_ids):
                        t = item.get("type", "story")
                        generated_types[t] = generated_types.get(t, 0) + 1
            except Exception:
                pass

        missing_stories = max(0, args.count_stories - generated_types.get("story", 0))
        missing_long = max(0, args.count_long_stories - generated_types.get("long_story", 0))
        missing_poems = max(0, args.count_poems - generated_types.get("poem", 0))
        missing_lullabies = max(0, args.count_lullabies - generated_types.get("song", 0))
        total_missing = missing_stories + missing_long + missing_poems + missing_lullabies

        if total_missing > 0:
            logger.info("  RETRY: Attempting to generate %d missing items "
                        "(stories=%d, long=%d, poems=%d, lullabies=%d)",
                        total_missing, missing_stories, missing_long, missing_poems, missing_lullabies)

            retry_before_ids = get_existing_ids()
            retry_cmd = [
                sys.executable, str(SCRIPTS_DIR / "generate_content_matrix.py"),
                "--api", "mistral",
                "--count-stories", str(missing_stories),
                "--count-poems", str(missing_poems),
                "--count-lullabies", str(missing_lullabies),
                "--count-long-stories", str(missing_long),
            ]
            if args.lang:
                retry_cmd += ["--lang", args.lang]

            retry_ok, _, _, _ = run_command(retry_cmd, "Content Generation (retry)", timeout=1800)
            if retry_ok:
                retry_ids = get_new_story_ids(retry_before_ids)
                if retry_ids:
                    logger.info("  RETRY SUCCESS: Generated %d additional items", len(retry_ids))
                    new_ids.extend(retry_ids)
                    # Re-count
                    actual = len(new_ids)

        if actual < expected:
            state["generation_warning"] = f"Expected {expected}, got {actual}"
        else:
            logger.info("  All %d items generated successfully (with retry)", expected)

    # Validate: songs (lullabies) should never be generated for ages 6+
    if new_ids and CONTENT_EXPANDED_PATH.exists():
        try:
            expanded = json.loads(CONTENT_EXPANDED_PATH.read_text())
            for item in expanded:
                if item["id"] in set(new_ids) and item.get("type") == "song":
                    age_min = item.get("age_min", 0)
                    if age_min >= 6:
                        logger.warning("  AUTO-FIX: Song '%s' generated for age %d+, resetting to 2-5",
                                       item.get("title", item["id"]), age_min)
                        item["age_min"] = 2
                        item["age_max"] = 5
                        item["target_age"] = 3
                        item["age_group"] = "2-5"
            CONTENT_EXPANDED_PATH.write_text(json.dumps(expanded, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.warning("  Song age validation failed: %s", e)

    # Merge into content.json
    if new_ids and not args.dry_run:
        merge_expanded_to_content(new_ids)

    state["generated_ids"] = new_ids

    # Log diversity fingerprint stats
    if new_ids and CONTENT_PATH.exists():
        try:
            with open(CONTENT_PATH, "r") as f:
                all_content = json.load(f)
            new_stories = [s for s in all_content if s.get("id") in set(new_ids)]
            fp_count = sum(1 for s in new_stories if s.get("diversityFingerprint"))
            logger.info("  Diversity fingerprints: %d/%d new stories", fp_count, len(new_stories))
            state["fingerprint_count"] = fp_count
        except Exception:
            pass

    state["step_generate"] = "done"
    save_state(state)
    return True


def _find_incomplete_content() -> list:
    """Find content.json stories that are missing audio, covers, or musicalBrief.

    These are leftovers from previous failed pipeline runs. Returns their IDs
    so the current run can complete them alongside new content.

    IMPORTANT: Before flagging an item for recovery, cross-checks against:
      1. The API's data/content.json (Docker LocalStore) — may have variants
         that seed_output fell out of sync with.
      2. Actual audio files on disk (web public folder) — the ground truth.
    If variants exist elsewhere, backfills them into seed_output/content.json
    and skips the item instead of wasting Modal credits re-generating.
    """
    if not CONTENT_PATH.exists():
        return []
    try:
        content = json.loads(CONTENT_PATH.read_text())
    except Exception:
        return []

    # Load API content for cross-check
    api_content_path = BASE_DIR / "data" / "content.json"
    api_by_id = {}
    if api_content_path.exists():
        try:
            api_by_id = {item["id"]: item for item in json.loads(api_content_path.read_text())}
        except Exception:
            pass

    # Scan actual audio files on disk
    web_audio_dir = WEB_DIR / "public" / "audio" / "pre-gen"
    disk_audio_files = set()
    if web_audio_dir.exists():
        disk_audio_files = {f.name for f in web_audio_dir.glob("*.mp3")}

    seed_modified = False
    incomplete = []

    for item in content:
        sid = item.get("id", "")
        if not sid.startswith("gen-"):
            continue  # Skip seed/manual content

        has_audio = bool(item.get("audio_variants"))
        has_cover = bool(item.get("cover") and item["cover"] != "" and "default.svg" not in item.get("cover", ""))
        is_song = item.get("type", "").lower() == "song"
        has_music = is_song or bool(item.get("musicalBrief") or item.get("musicParams"))

        # ── Cross-check: recover variants from API or disk before flagging ──
        if not has_audio:
            api_item = api_by_id.get(sid, {})
            api_variants = api_item.get("audio_variants", [])

            if api_variants:
                # Verify files actually exist on disk
                valid = [v for v in api_variants
                         if v.get("url", "").split("/")[-1] in disk_audio_files]
                if valid:
                    item["audio_variants"] = valid
                    has_audio = True
                    seed_modified = True
                    logger.info("  AUTO-FIX: Recovered %d audio variants for %s from API data",
                                len(valid), item.get("title", sid[:12]))
            else:
                # No API variants — check if files exist on disk by prefix
                prefix = sid[:8]  # e.g. "gen-54ee"
                disk_matches = sorted(f for f in disk_audio_files if f.startswith(prefix))
                if disk_matches:
                    # Reconstruct variants from filenames
                    reconstructed = []
                    for fname in disk_matches:
                        # gen-54ee_female_1.mp3 → voice=female_1
                        parts = fname.replace(".mp3", "").split("_", 1)
                        voice = parts[1] if len(parts) > 1 else "default"
                        reconstructed.append({
                            "voice": voice,
                            "url": f"/audio/pre-gen/{fname}",
                        })
                    if reconstructed:
                        item["audio_variants"] = reconstructed
                        has_audio = True
                        seed_modified = True
                        logger.info("  AUTO-FIX: Recovered %d audio variants for %s from disk files",
                                    len(reconstructed), item.get("title", sid[:12]))

        if not has_audio or not has_cover or not has_music:
            missing = []
            if not has_audio:
                missing.append("audio")
            if not has_cover:
                missing.append("cover")
            if not has_music:
                missing.append("musicalBrief")
            incomplete.append((sid, item.get("title", sid[:12]), missing))

    # Persist any auto-fixes back to seed content.json
    if seed_modified:
        try:
            CONTENT_PATH.write_text(json.dumps(content, indent=2, ensure_ascii=False))
            logger.info("  AUTO-FIX: Updated seed_output/content.json with recovered data")
        except Exception as e:
            logger.warning("  AUTO-FIX: Failed to save content.json: %s", e)

    return incomplete


def step_audio(args, state: dict) -> bool:
    """Step 2: Generate audio variants for new stories via Chatterbox TTS on Modal."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 2: GENERATE AUDIO              ║")
    logger.info("╚══════════════════════════════════════╝")

    new_ids = state.get("generated_ids", [])

    # Auto-recover: find content from previous runs that's missing audio
    incomplete = _find_incomplete_content()
    recover_audio_ids = [sid for sid, title, missing in incomplete
                         if "audio" in missing and sid not in new_ids]
    if recover_audio_ids:
        logger.info("  RECOVERY: Found %d stories from previous runs missing audio:", len(recover_audio_ids))
        for sid, title, _ in incomplete:
            if sid in recover_audio_ids:
                logger.info("    - %s (%s)", title, sid[:12])
        new_ids = new_ids + recover_audio_ids
        state["generated_ids"] = new_ids  # Include recovered IDs in downstream steps
        state["recovered_audio_ids"] = recover_audio_ids
        save_state(state)

    if not new_ids:
        logger.info("  No new stories to generate audio for. Skipping.")
        state["step_audio"] = "skipped"
        save_state(state)
        return True

    # Determine story types for adaptive timeout
    story_types = {}
    if CONTENT_EXPANDED_PATH.exists():
        try:
            expanded = json.loads(CONTENT_EXPANDED_PATH.read_text())
            for item in expanded:
                story_types[item.get("id", "")] = item.get("type", "story")
        except Exception:
            pass

    # Generate audio for each new story
    audio_total_seconds = 0
    for sid in new_ids:
        # Songs use ACE-Step which is memory-intensive (~1.7GB per worker).
        # On low-memory VMs (2GB), use 1 worker to avoid OOM kills.
        # Regular stories use Chatterbox TTS which is lighter.
        is_song = story_types.get(sid) == "song"
        workers = "1" if is_song else "3"

        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_audio.py"),
            "--story-id", sid,
            "--speed", "0.8",  # Bedtime pace
            "--workers", workers,
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        # Timeouts: songs via ACE-Step need ~30 min (2 variants × 2 retakes × ~5 min each)
        # Long stories need ~40 min for 3-phase TTS. Regular stories ~20 min.
        if is_song:
            audio_timeout = 2400
        elif story_types.get(sid) == "long_story":
            audio_timeout = 2400
        else:
            audio_timeout = 1200

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Audio: {sid[:8]}...", timeout=audio_timeout
        )
        audio_total_seconds += elapsed
        if not ok:
            logger.error("  Audio generation failed for %s", sid)
            # Continue with other stories — don't abort entire pipeline
            state.setdefault("audio_failures", []).append(sid)

    state["audio_elapsed_seconds"] = audio_total_seconds
    state["step_audio"] = "done"
    save_state(state)
    return True


def _parse_qa_failed_variants(story_id: str) -> list:
    """Parse the most recent QA report for a story and return failed variants.

    Returns list of dicts: [{"story_id": ..., "voice": ...}, ...]
    """
    qa_dir = SEED_OUTPUT / "qa_reports"
    if not qa_dir.exists():
        return []

    # Find the most recent QA report that contains this story_id
    # Reports are named qa_audio_YYYYMMDD_HHMMSS.json, sorted by name = sorted by time
    reports = sorted(qa_dir.glob("qa_audio_*.json"), reverse=True)
    for report_path in reports:
        try:
            report = json.loads(report_path.read_text())
            for story in report.get("stories", []):
                if story.get("story_id") == story_id:
                    failed = []
                    for variant in story.get("variants", []):
                        if variant.get("verdict") == "FAIL":
                            failed.append({
                                "story_id": story_id,
                                "voice": variant["voice"],
                                "reasons": variant.get("reasons", []),
                            })
                    return failed
        except (json.JSONDecodeError, KeyError):
            continue
    return []


def _strip_qa_failed_variants(failed_variants: list):
    """Remove QA-failed audio variants from content.json and delete their audio files.

    This ensures bad audio never ships to production. The story itself still gets
    published (with covers, musical briefs, etc.) — only the bad variant is removed.
    """
    if not failed_variants:
        return

    # Build lookup: story_id → set of failed voices
    failed_lookup = {}
    for fv in failed_variants:
        failed_lookup.setdefault(fv["story_id"], set()).add(fv["voice"])

    # --- 1. Strip from content.json ---
    content_path = SEED_OUTPUT / "content.json"
    if content_path.exists():
        content = json.loads(content_path.read_text())
        stripped_count = 0
        for item in content:
            sid = item.get("id", "")
            if sid in failed_lookup:
                avs = item.get("audio_variants", [])
                original_len = len(avs)
                item["audio_variants"] = [
                    v for v in avs if v.get("voice") not in failed_lookup[sid]
                ]
                stripped_count += original_len - len(item["audio_variants"])
        if stripped_count:
            content_path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
            logger.info("  Stripped %d QA-failed variants from content.json", stripped_count)

    # --- 2. Also strip from data/content.json (API serving copy) ---
    api_content_path = BASE_DIR / "data" / "content.json"
    if api_content_path.exists():
        api_content = json.loads(api_content_path.read_text())
        for item in api_content:
            sid = item.get("id", "")
            if sid in failed_lookup:
                avs = item.get("audio_variants", [])
                item["audio_variants"] = [
                    v for v in avs if v.get("voice") not in failed_lookup[sid]
                ]
        api_content_path.write_text(json.dumps(api_content, indent=2, ensure_ascii=False))

    # --- 3. Delete bad audio files from backend ---
    backend_audio_dir = BASE_DIR / "audio" / "pre-gen"
    web_audio_dir = WEB_DIR / "public" / "audio" / "pre-gen" if WEB_DIR.exists() else None
    deleted = 0
    for fv in failed_variants:
        short_id = fv["story_id"][:8]
        filename = f"{short_id}_{fv['voice']}.mp3"
        for audio_dir in [backend_audio_dir, web_audio_dir]:
            if audio_dir and (audio_dir / filename).exists():
                (audio_dir / filename).unlink()
                deleted += 1
                logger.info("  Deleted QA-failed audio: %s", audio_dir / filename)
    if deleted:
        logger.info("  Deleted %d QA-failed audio files total", deleted)


def step_qa(args, state: dict) -> bool:
    """Step 3: QA audio.

    Stories/poems: Phase 1 (duration) + Phase 2 (transcription fidelity).
    Songs/lullabies: Phase 1 (duration) + Phase L (lullaby audio analysis).
    """
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 3: AUDIO QA                    ║")
    logger.info("╚══════════════════════════════════════╝")

    new_ids = state.get("generated_ids", [])
    audio_failures = state.get("audio_failures", [])
    qa_ids = [sid for sid in new_ids if sid not in audio_failures]

    if not qa_ids:
        logger.info("  No stories to QA. Skipping.")
        state["step_qa"] = "skipped"
        save_state(state)
        return True

    # Skip QA for songs/lullabies — ACE-Step already measures fidelity and quality
    # during generation with retakes, and the server lacks RAM for Whisper on long audio.
    content_types = {}
    try:
        content = json.loads(CONTENT_PATH.read_text())
        for item in content:
            content_types[item.get("id", "")] = item.get("type", "story")
    except Exception:
        pass

    song_ids = [sid for sid in qa_ids if content_types.get(sid) == "song"]
    qa_ids = [sid for sid in qa_ids if content_types.get(sid) != "song"]

    if song_ids:
        logger.info("  Skipping QA for %d lullaby/song (fidelity checked during generation): %s",
                     len(song_ids), ", ".join(s[:8] for s in song_ids))

    if not qa_ids:
        logger.info("  No non-song stories to QA. Skipping.")
        state["qa_passed"] = song_ids  # Songs auto-pass
        state["qa_failed"] = []
        state["qa_failed_variants"] = []
        state["step_qa"] = "done"
        save_state(state)
        return True

    qa_passed = list(song_ids)  # Songs auto-pass
    qa_failed = []
    qa_failed_variants = []  # Per-variant failures: [{story_id, voice}, ...]

    for sid in qa_ids:
        cmd = [
            "nice", "-n", "19",  # Lowest CPU priority — don't starve the app
            sys.executable, str(SCRIPTS_DIR / "qa_audio.py"),
            "--story-id", sid,
            "--no-quality-score",  # Skip phase 3 (expensive quality scoring)
            "--lang", args.lang or "en",
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"QA: {sid[:8]}...", timeout=600, memory_limit=True
        )

        if ok:
            # Check for FAIL in output
            if "FAIL" in stdout:
                logger.warning("  QA FAILED for %s — audio fidelity below threshold", sid)
                qa_failed.append(sid)
            else:
                qa_passed.append(sid)
        else:
            logger.error("  QA process error for %s", sid)
            qa_failed.append(sid)

        # Parse QA report to collect per-variant failures
        qa_failed_variants.extend(_parse_qa_failed_variants(sid))

    state["qa_passed"] = qa_passed
    state["qa_failed"] = qa_failed
    state["qa_failed_variants"] = qa_failed_variants
    state["step_qa"] = "done"
    save_state(state)

    logger.info("  QA Results: %d passed, %d failed", len(qa_passed), len(qa_failed))
    if qa_failed_variants:
        logger.info("  Failed variants: %s",
                     ", ".join(f"{v['story_id'][:8]}/{v['voice']}" for v in qa_failed_variants))

    # Strip failed variants from content.json and remove bad audio files
    if qa_failed_variants:
        _strip_qa_failed_variants(qa_failed_variants)

    return True


def step_enrich(args, state: dict) -> bool:
    """Step 4: Generate Musical Briefs (v3) for stories with audio via Mistral AI.

    Enriches ALL stories that have audio (not just QA-passed), because QA timeouts
    don't mean the audio is bad — the story still needs a musical brief.
    """
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 4: ENRICH (Musical Briefs)     ║")
    logger.info("╚══════════════════════════════════════╝")

    # Enrich all stories with audio, not just QA-passed
    new_ids = state.get("generated_ids", [])
    audio_failures = state.get("audio_failures", [])
    enrich_ids = [sid for sid in new_ids if sid not in audio_failures]

    # Auto-recover: find content from previous runs that has audio but no musicalBrief
    incomplete = _find_incomplete_content()
    recover_enrich_ids = [sid for sid, title, missing in incomplete
                          if "musicalBrief" in missing and "audio" not in missing
                          and sid not in enrich_ids]
    if recover_enrich_ids:
        logger.info("  RECOVERY: Found %d stories from previous runs missing musicalBrief:", len(recover_enrich_ids))
        for sid, title, _ in incomplete:
            if sid in recover_enrich_ids:
                logger.info("    - %s (%s)", title, sid[:12])
        enrich_ids = enrich_ids + recover_enrich_ids
        state["recovered_enrich_ids"] = recover_enrich_ids
        save_state(state)

    if not enrich_ids:
        logger.info("  No stories with audio to enrich. Skipping.")
        state["step_enrich"] = "skipped"
        save_state(state)
        return True

    # Load content to check types — songs (lullabies) don't need Musical Briefs
    content = []
    content_path = SCRIPTS_DIR.parent / "seed_output" / "content.json"
    if content_path.exists():
        import json as _json
        with open(content_path) as _f:
            content = _json.load(_f)
    content_by_id = {item["id"]: item for item in content if isinstance(item, dict)}

    enrich_failures = []
    for sid in enrich_ids:
        # Songs (lullabies) don't need Musical Briefs — ACE-Step output has vocals + instrument
        item = content_by_id.get(sid, {})
        if item.get("type", "").lower() == "song":
            logger.info("  Skipping Musical Brief for %s (song/lullaby — no background music)", sid[:8])
            continue

        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_music_params.py"),
            "--id", sid,
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Musical Brief: {sid[:8]}...", timeout=300
        )
        if not ok:
            logger.warning("  Musical Brief generation failed for %s (non-fatal)", sid)
            enrich_failures.append(sid)

    if enrich_failures:
        state["enrich_failures"] = enrich_failures
        logger.warning("  %d Musical Brief generation(s) failed: %s", len(enrich_failures),
                       ", ".join(s[:8] for s in enrich_failures))
    state["step_enrich"] = "done"
    save_state(state)
    return True


def step_mood(args, state: dict) -> bool:
    """Step 4b: Classify mood for newly generated stories via Mistral AI.

    Assigns one of six mood tags (calm, curious, wired, sad, anxious, angry)
    to each new story. Uses --skip-classified to only process items without
    a mood field, so re-runs are safe.
    """
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 4b: MOOD CLASSIFICATION        ║")
    logger.info("╚══════════════════════════════════════╝")

    new_ids = state.get("generated_ids", [])
    audio_failures = state.get("audio_failures", [])
    classify_ids = [sid for sid in new_ids if sid not in audio_failures]

    if not classify_ids:
        logger.info("  No new stories to classify mood for. Skipping.")
        state["step_mood"] = "skipped"
        save_state(state)
        return True

    cmd = [
        sys.executable, str(SCRIPTS_DIR / "classify_moods.py"),
        "--skip-classified",
        "--delay", "2",  # Pipeline runs sequentially so shorter delay is fine
    ]
    if args.dry_run:
        cmd += ["--dry-run"]

    ok, stdout, stderr, elapsed = run_command(
        cmd, "Mood classification", timeout=600
    )

    if stdout:
        logger.info("  %s", stdout.strip().split("\n")[-1])  # Log the summary line

    if not ok:
        # Non-fatal — mood is a nice-to-have, not critical for content delivery
        logger.warning("  Mood classification failed (non-fatal): %s",
                       stderr[:200] if stderr else "unknown error")
        state["step_mood"] = "failed_nonfatal"
        save_state(state)
        return True  # Don't halt the pipeline

    state["step_mood"] = "done"
    save_state(state)
    return True


def step_covers(args, state: dict) -> bool:
    """Step 5: Generate experimental 2-layer covers (FLUX AI + SVG overlay).

    Uses generate_cover_experimental.py which:
      1. Generates a FLUX AI background (WebP) via Hugging Face free tier
      2. Creates an animated SVG overlay (particles, glows, mist)
      3. Combines into a single SVG (embedded WebP + overlay animations)
      4. Copies to frontend public/covers/ and updates content.json

    Each cover uses 7 diversity axes (world, palette, composition, character,
    light, texture, time) auto-selected from story metadata to ensure
    no two covers look similar.

    Generates covers for ALL stories with audio (not just QA-passed), because
    QA timeouts don't mean audio is bad — the story still needs a cover.
    """
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 5: GENERATE COVERS (FLUX+SVG)  ║")
    logger.info("╚══════════════════════════════════════╝")

    # Generate covers for ALL new stories — even those whose audio failed,
    # because the story still needs a cover (audio can be retried later)
    new_ids = state.get("generated_ids", [])
    cover_ids = list(new_ids)

    # Auto-recover: find content from previous runs that has audio but no cover
    incomplete = _find_incomplete_content()
    recover_cover_ids = [sid for sid, title, missing in incomplete
                         if "cover" in missing and "audio" not in missing
                         and sid not in cover_ids]
    if recover_cover_ids:
        logger.info("  RECOVERY: Found %d stories from previous runs missing covers:", len(recover_cover_ids))
        for sid, title, _ in incomplete:
            if sid in recover_cover_ids:
                logger.info("    - %s (%s)", title, sid[:12])
        cover_ids = cover_ids + recover_cover_ids
        state["recovered_cover_ids"] = recover_cover_ids
        save_state(state)

    if not cover_ids:
        logger.info("  No stories with audio to generate covers for. Skipping.")
        state["step_covers"] = "skipped"
        state["covers_generated"] = []
        state["covers_failed"] = []
        save_state(state)
        return True

    covers_flux = []      # Successfully generated with FLUX AI
    covers_fallback = []   # Fell back to Mistral SVG
    covers_failed = []     # No cover at all

    FLUX_MAX_RETRIES = 3   # Retry FLUX up to 3 times before falling back
    FLUX_RETRY_DELAY = 10  # Seconds between retries

    # Check for HF_API_TOKEN — required for FLUX AI
    hf_token = os.environ.get("HF_API_TOKEN", "")
    if not hf_token and not args.dry_run:
        logger.warning("  ⚠️ HF_API_TOKEN not set — falling back to Mistral SVG covers")
        logger.warning("  Set HF_API_TOKEN in .env to use FLUX AI covers instead.")
        # Fallback to old Mistral-generated SVG covers
        for sid in cover_ids:
            cmd = [
                sys.executable, str(SCRIPTS_DIR / "generate_cover_svg.py"),
                "--id", sid,
            ]
            ok, stdout, stderr, elapsed = run_command(
                cmd, f"Cover (Mistral fallback): {sid[:8]}...", timeout=600
            )
            fb_combined = (stdout or "") + (stderr or "")
            if ok and "OK:" in fb_combined:
                covers_fallback.append(sid)
            else:
                covers_failed.append(sid)
        state["covers_flux"] = covers_flux
        state["covers_fallback"] = covers_fallback
        state["covers_generated"] = covers_flux + covers_fallback  # backwards compat
        state["covers_failed"] = covers_failed
        state["step_covers"] = "done"
        save_state(state)
        return True

    # Load content.json to find story JSON files for each story
    content = []
    if CONTENT_PATH.exists():
        try:
            content = json.loads(CONTENT_PATH.read_text())
        except Exception:
            pass
    content_map = {s["id"]: s for s in content}

    for sid in cover_ids:
        # Try to find the standalone story JSON first (for full metadata)
        story_json_candidates = list(SEED_OUTPUT.glob(f"*_{sid}.json"))
        if story_json_candidates:
            story_json_path = story_json_candidates[0]
        else:
            # Create a temp JSON from content.json entry
            story_data = content_map.get(sid, {})
            if not story_data:
                logger.warning("  Story %s not found in content.json, skipping cover", sid)
                covers_failed.append(sid)
                continue
            story_json_path = SEED_OUTPUT / f"_temp_{sid}.json"
            story_json_path.write_text(json.dumps(story_data, ensure_ascii=False, indent=2))

        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_cover_experimental.py"),
            "--story-json", str(story_json_path),
        ]
        if args.mood:
            cmd += ["--mood", args.mood]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Cover (FLUX): {sid[:8]}...", timeout=300
        )

        # Check both stdout and stderr for "OK:" — logging module writes to stderr
        combined_output = (stdout or "") + (stderr or "")

        if ok and "OK:" in combined_output:
            covers_flux.append(sid)
        else:
            # Retry FLUX up to FLUX_MAX_RETRIES times before falling back
            flux_succeeded = False
            for attempt in range(2, FLUX_MAX_RETRIES + 1):
                logger.info("  FLUX retry %d/%d for %s (waiting %ds)...",
                            attempt, FLUX_MAX_RETRIES, sid[:8], FLUX_RETRY_DELAY)
                import time as _time
                _time.sleep(FLUX_RETRY_DELAY)
                ok2, stdout2, stderr2, elapsed2 = run_command(
                    cmd, f"Cover (FLUX retry {attempt}): {sid[:8]}...", timeout=300
                )
                combined2 = (stdout2 or "") + (stderr2 or "")
                if ok2 and "OK:" in combined2:
                    covers_flux.append(sid)
                    flux_succeeded = True
                    logger.info("  ✅ FLUX succeeded on retry %d for %s", attempt, sid[:8])
                    break

            if not flux_succeeded:
                logger.warning("  ⚠️ FLUX failed after %d attempts for %s, trying Mistral fallback...",
                               FLUX_MAX_RETRIES, sid[:8])
                # Fallback to Mistral SVG cover
                fallback_cmd = [
                    sys.executable, str(SCRIPTS_DIR / "generate_cover_svg.py"),
                    "--id", sid,
                ]
                if not args.dry_run:
                    fb_ok, fb_stdout, fb_stderr, _ = run_command(
                        fallback_cmd, f"Cover (Mistral fallback): {sid[:8]}...", timeout=600
                    )
                    fb_combined = (fb_stdout or "") + (fb_stderr or "")
                    if fb_ok and "OK:" in fb_combined:
                        covers_fallback.append(sid)
                    else:
                        covers_failed.append(sid)
                else:
                    covers_failed.append(sid)

        # Clean up temp file AFTER all attempts (retries need it)
        temp_path = SEED_OUTPUT / f"_temp_{sid}.json"
        if temp_path.exists():
            temp_path.unlink()

    state["covers_flux"] = covers_flux
    state["covers_fallback"] = covers_fallback
    state["covers_generated"] = covers_flux + covers_fallback  # backwards compat
    state["covers_failed"] = covers_failed
    state["step_covers"] = "done"
    save_state(state)
    logger.info("  Covers: %d FLUX, %d Mistral fallback, %d failed",
                len(covers_flux), len(covers_fallback), len(covers_failed))
    return True


def step_clips(args, state: dict) -> bool:
    """Step 6b: Generate social media clips for new content."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 6b: SOCIAL MEDIA CLIPS         ║")
    logger.info("╚══════════════════════════════════════╝")

    clips_script = SCRIPTS_DIR / "generate_clips.py"
    if not clips_script.exists():
        logger.warning("  generate_clips.py not found — skipping")
        state["step_clips"] = "skipped"
        save_state(state)
        return True

    cmd = [sys.executable, str(clips_script)]
    if args.dry_run:
        cmd.append("--dry-run")

    ok, stdout, stderr, elapsed = run_command(cmd, "Clip generation", timeout=1800)
    if stdout:
        # Log last few lines of output
        lines = stdout.strip().split("\n")
        for line in lines[-5:]:
            logger.info("  %s", line)

    if not ok:
        logger.warning("  Clip generation failed (non-fatal): %s",
                        stderr[:200] if stderr else "unknown error")
        state["step_clips"] = "failed_nonfatal"
        save_state(state)
        return True  # Non-fatal — don't halt the pipeline

    state["step_clips"] = "done"
    save_state(state)
    return True


def step_sync(args, state: dict) -> bool:
    """Step 7: Sync content.json → seedData.js for the web frontend."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 6: SYNC SEED DATA              ║")
    logger.info("╚══════════════════════════════════════╝")

    if not WEB_DIR.exists():
        logger.warning("  dreamweaver-web not found at %s — skipping sync", WEB_DIR)
        state["step_sync"] = "skipped"
        save_state(state)
        return True

    cmd = [sys.executable, str(SCRIPTS_DIR / "sync_seed_data.py")]
    if args.dry_run:
        logger.info("  [DRY RUN] Would sync content.json → seedData.js")
        state["step_sync"] = "dry_run"
        save_state(state)
        return True

    ok, stdout, stderr, elapsed = run_command(cmd, "Sync seed data", timeout=60)
    if not ok:
        state["step_sync"] = "failed"
        save_state(state)
        return False

    # Copy audio files to web public folder so nginx can serve them.
    # Includes current run's items AND any recovered items from previous runs.
    web_audio_dir = WEB_DIR / "public" / "audio" / "pre-gen"
    backend_audio_dir = BASE_DIR / "audio" / "pre-gen"
    if web_audio_dir.exists() and backend_audio_dir.exists():
        import shutil
        new_ids = state.get("generated_ids", [])
        audio_failures = state.get("audio_failures", [])
        copy_ids = [sid for sid in new_ids if sid not in audio_failures]
        # Also copy any gen- audio files from backend that are missing in web dir
        existing_web_files = {f.name for f in web_audio_dir.glob("gen-*.mp3")}
        for mp3 in backend_audio_dir.glob("gen-*.mp3"):
            if mp3.name not in existing_web_files:
                # Extract story ID prefix (first 8 chars) and check it's not a failure
                short = mp3.name[:8]
                matching_failure = any(sid[:8] == short for sid in audio_failures)
                if not matching_failure:
                    copy_ids_shorts = {sid[:8] for sid in copy_ids}
                    if short not in copy_ids_shorts:
                        copy_ids.append(short)  # ensure we copy it
        copied = 0
        for story_id in copy_ids:
            short_id = story_id[:8]
            for mp3 in backend_audio_dir.glob(f"{short_id}*.mp3"):
                dest = web_audio_dir / mp3.name
                if not dest.exists() or mp3.stat().st_mtime > dest.stat().st_mtime:
                    shutil.copy2(mp3, dest)
                    copied += 1
        if copied:
            logger.info("  Copied %d audio files to web public folder", copied)

    # Save diversity snapshot for current/previous comparison on dashboard
    try:
        from scripts.generate_diversity_report import generate_report
        report = generate_report()
        snapshot_path = BASE_DIR / "data" / "diversity_snapshot.json"
        snapshot_path.write_text(json.dumps(report, indent=2))
        logger.info("  Saved diversity snapshot (%d items)", report["catalog"]["total"])
    except Exception as e:
        logger.warning("  Failed to save diversity snapshot: %s", e)

    state["step_sync"] = "done"
    save_state(state)
    return True


def step_publish(args, state: dict) -> bool:
    """Step 7: Git commit + push to trigger auto-deploy (Render/Vercel ONLY)."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 7: PUBLISH (git push)          ║")
    logger.info("╚══════════════════════════════════════╝")

    if args.skip_publish or args.dry_run:
        logger.info("  Skipping publish (--skip-publish or --dry-run)")
        state["step_publish"] = "skipped"
        save_state(state)
        return True

    # Publish all stories with audio, not just QA-passed
    new_ids = state.get("generated_ids", [])
    audio_failures = state.get("audio_failures", [])
    publish_ids = [sid for sid in new_ids if sid not in audio_failures]
    if not publish_ids:
        logger.info("  No content with audio to publish. Skipping.")
        state["step_publish"] = "skipped"
        save_state(state)
        return True

    date_str = datetime.now().strftime("%Y-%m-%d")
    commit_msg = f"pipeline: add {len(publish_ids)} new content items ({date_str})"

    # Ensure git identity is configured (required for commit on server)
    for repo_dir in [str(BASE_DIR), str(WEB_DIR)]:
        if Path(repo_dir).exists():
            subprocess.run(["git", "config", "user.email", "pipeline@dreamvalley.app"],
                           cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Dream Valley Pipeline"],
                           cwd=repo_dir, capture_output=True)

    backend_ok = False
    frontend_ok = False

    # ── Commit and push backend (triggers Render auto-deploy) ──
    logger.info("  Committing backend changes...")
    backend_cmds = [
        (["git", "add", "seed_output/content.json",
          "seed_output/content_expanded.json", "audio/"], "Backend: git add"),
        (["git", "commit", "-m", commit_msg, "--allow-empty"], "Backend: git commit"),
        (["git", "push", "origin", "main"], "Backend: git push"),
    ]
    for cmd, label in backend_cmds:
        ok, _, stderr, _ = run_command(cmd, label, timeout=60)
        if not ok and "nothing to commit" not in str(stderr):
            logger.warning("  %s failed", label)
            break
    else:
        backend_ok = True

    # ── Commit and push frontend (triggers Vercel auto-deploy) ──
    if WEB_DIR.exists() and state.get("step_sync") == "done":
        logger.info("  Committing frontend changes...")
        web_cwd = str(WEB_DIR)
        frontend_cmds = [
            (["git", "add", "src/utils/seedData.js",
              "public/covers/"], "Frontend: git add"),
            (["git", "commit", "-m", commit_msg, "--allow-empty"], "Frontend: git commit"),
            (["git", "push", "origin", "main"], "Frontend: git push"),
        ]
        for cmd, label in frontend_cmds:
            ok, _, stderr, _ = run_command(cmd, label, timeout=60, cwd=web_cwd)
            if not ok and "nothing to commit" not in str(stderr):
                logger.warning("  %s failed", label)
                break
        else:
            frontend_ok = True

    if backend_ok or frontend_ok:
        state["step_publish"] = "done"
        state["publish_backend"] = "ok" if backend_ok else "failed"
        state["publish_frontend"] = "ok" if frontend_ok else "failed"
    else:
        state["step_publish"] = "failed"
        logger.error("  Both backend and frontend publish failed!")

    save_state(state)
    return backend_ok or frontend_ok


def step_deploy_prod(args, state: dict) -> bool:
    """Step 8: Deploy to local production (zero-downtime static copy + backend hot-reload).

    For daily content updates, NO frontend rebuild or PM2 restart is needed:
    - Backend hot-reloads content via admin API (serves new data immediately)
    - Frontend fetches content from API at runtime (not build time)
    - New static files (covers, audio) just need to be copied to standalone dir

    seedData.js sync + git push (steps 6-7) still handle Vercel test deployment.
    """
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 8: DEPLOY PROD (zero-downtime) ║")
    logger.info("╚══════════════════════════════════════╝")

    if getattr(args, "skip_deploy_prod", False) or args.dry_run:
        logger.info("  Skipping deploy_prod")
        state["step_deploy_prod"] = "skipped"
        save_state(state)
        return True

    # Deploy all stories with audio, not just QA-passed
    new_ids = state.get("generated_ids", [])
    audio_failures = state.get("audio_failures", [])
    deploy_ids = [sid for sid in new_ids if sid not in audio_failures]
    if not deploy_ids:
        logger.info("  No content with audio to deploy. Skipping prod deploy.")
        state["step_deploy_prod"] = "skipped"
        save_state(state)
        return True

    frontend_ok = False
    backend_ok = False

    # ── Frontend: zero-downtime static asset update ──
    # nginx serves /covers/ and /audio/ directly from public/ via alias directives,
    # so we only need new files in public/ — no Next.js rebuild or PM2 restart needed.
    # The generate_cover_experimental.py and sync step already copy files to public/,
    # so typically no extra copy is needed here. We just verify the dirs exist.
    if WEB_DIR.exists():
        web_cwd = str(WEB_DIR)
        covers_dir = WEB_DIR / "public" / "covers"
        audio_dir = WEB_DIR / "public" / "audio"
        if covers_dir.exists() and audio_dir.exists():
            frontend_ok = True
            logger.info("  Frontend: static assets served by nginx (zero-downtime, no rebuild)")
        else:
            # First-time setup — need a full build
            logger.warning("  Public dirs missing — performing full frontend build...")
            frontend_cmds = [
                (["npm", "run", "build"], "Frontend: npm build", 300),
                (["bash", "-c",
                  "cp -r public .next/standalone/public && "
                  "cp -r .next/static .next/standalone/.next/static"],
                 "Frontend: copy static assets", 30),
                (["pm2", "restart", "all"], "Frontend: pm2 restart", 30),
            ]
            for cmd, label, timeout in frontend_cmds:
                ok, _, stderr, _ = run_command(cmd, label, timeout=timeout, cwd=web_cwd)
                if not ok:
                    logger.error("  %s failed: %s", label, stderr)
                    break
            else:
                frontend_ok = True
                logger.info("  Frontend deployed successfully (full build)")

    # ── Backend: hot-reload content via admin API (no restart needed) ──
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if admin_key:
        logger.info("  Triggering backend content reload...")
        try:
            import httpx
            resp = httpx.post(
                "http://localhost:8000/api/v1/admin/reload",
                headers={"X-Admin-Key": admin_key},
                timeout=15,
            )
            if resp.status_code == 200:
                result = resp.json()
                backend_ok = True
                logger.info("  Backend reloaded: %s", result.get("message", "OK"))
            else:
                logger.error("  Backend reload failed: HTTP %d — %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("  Backend reload HTTP call failed: %s", e)

    if not backend_ok:
        # Fallback: docker restart (if reload unavailable or failed)
        logger.info("  Falling back to docker restart...")
        ok, _, stderr, _ = run_command(
            ["sudo", "docker", "restart", "dreamweaver-backend"],
            "Backend: docker restart (fallback)",
            timeout=30,
        )
        if ok:
            backend_ok = True
            logger.info("  Backend restarted successfully (fallback)")
        else:
            logger.error("  Backend restart also failed: %s", stderr)

    state["step_deploy_prod"] = "done" if (frontend_ok or backend_ok) else "failed"
    state["deploy_prod_frontend"] = "ok" if frontend_ok else "failed"
    state["deploy_prod_backend"] = "ok" if backend_ok else "failed"
    save_state(state)
    return frontend_ok or backend_ok


# ═══════════════════════════════════════════════════════════════════════
# PREFLIGHT / POSTFLIGHT
# ═══════════════════════════════════════════════════════════════════════

def preflight_checks(args) -> bool:
    """Run pre-pipeline health checks. Returns True if safe to proceed."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  PREFLIGHT CHECKS                    ║")
    logger.info("╚══════════════════════════════════════╝")

    all_ok = True

    # 1. Kill stale pipeline processes (older than 3 hours)
    try:
        import signal
        result = subprocess.run(
            ["pgrep", "-f", "pipeline_run.py"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
            my_pid = os.getpid()
            for pid in pids:
                if pid != my_pid:
                    try:
                        # Check age — only kill if older than 3 hours
                        stat_result = subprocess.run(
                            ["ps", "-o", "etimes=", "-p", str(pid)],
                            capture_output=True, text=True, timeout=5
                        )
                        elapsed = int(stat_result.stdout.strip()) if stat_result.stdout.strip() else 0
                        if elapsed > 10800:  # 3 hours
                            os.kill(pid, signal.SIGTERM)
                            logger.warning("  Killed stale pipeline process PID %d (age: %ds)", pid, elapsed)
                    except (ValueError, ProcessLookupError, OSError):
                        pass
    except Exception as e:
        logger.debug("  Stale process check skipped: %s", e)

    # 2. Check disk space (warn if <1GB free)
    try:
        stat = os.statvfs(str(BASE_DIR))
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        logger.info("  Disk free: %.1f GB", free_gb)
        if free_gb < 1.0:
            logger.warning("  LOW DISK SPACE: %.1f GB free. Pipeline may fail.", free_gb)
            all_ok = False
    except Exception as e:
        logger.debug("  Disk check skipped: %s", e)

    # 3. Warm up Modal Chatterbox endpoint (avoid cold start during audio step)
    if not args.dry_run:
        try:
            import httpx
            logger.info("  Warming up Modal Chatterbox endpoint...")
            resp = httpx.get(CHATTERBOX_HEALTH, timeout=90)
            if resp.status_code == 200:
                logger.info("  Modal Chatterbox health: OK")
            else:
                logger.warning("  Modal Chatterbox health: HTTP %d", resp.status_code)
        except Exception as e:
            logger.warning("  Modal Chatterbox warmup failed: %s (will retry during audio step)", e)

    # 3b. Warm up SongGen endpoint (for song audio generation)
    songgen_health = os.environ.get("SONGGEN_HEALTH", "")
    if songgen_health and not args.dry_run:
        try:
            import httpx
            logger.info("  Warming up Modal SongGen endpoint...")
            resp = httpx.get(songgen_health, timeout=90)
            if resp.status_code == 200:
                logger.info("  Modal SongGen health: OK")
            else:
                logger.warning("  Modal SongGen health: HTTP %d", resp.status_code)
        except Exception as e:
            logger.warning("  Modal SongGen warmup failed: %s (songs will fallback to Chatterbox)", e)

    # 4. Quick Mistral API connectivity test
    if not args.dry_run:
        try:
            from mistralai import Mistral
            client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
            resp = client.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5,
            )
            logger.info("  Mistral API: OK")
        except Exception as e:
            logger.error("  Mistral API check failed: %s", e)
            all_ok = False

    logger.info("  Preflight: %s", "PASS" if all_ok else "WARNINGS (proceeding)")
    return True  # Always proceed — warnings are non-fatal


def postflight_checks(state: dict):
    """Gather cost estimates and disk usage for the notification email."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  POSTFLIGHT: COST & DISK SUMMARY     ║")
    logger.info("╚══════════════════════════════════════╝")

    # Count audio files and disk usage
    audio_dir = BASE_DIR / "audio" / "pre-gen"
    web_audio_dir = WEB_DIR / "public" / "audio" / "pre-gen"
    total_audio = 0
    total_bytes = 0
    for d in [audio_dir, web_audio_dir]:
        if d.exists():
            for f in d.glob("*.mp3"):
                total_audio += 1
                total_bytes += f.stat().st_size

    audio_gb = total_bytes / (1024 ** 3)
    logger.info("  Audio files: %d (%.2f GB total across both repos)", total_audio, audio_gb)

    # Count cover SVGs
    covers_dir = WEB_DIR / "public" / "covers"
    cover_count = len(list(covers_dir.glob("*.svg"))) if covers_dir.exists() else 0
    logger.info("  Cover SVGs: %d", cover_count)

    # ── Cost calculation ────────────────────────────────────────────────
    # GCP infrastructure (always-on, fixed monthly cost)
    #   e2-small instance (asia-south1): $14.69/mo
    #   30GB standard persistent disk:   $1.44/mo
    #   Total GCP infra:                 $16.13/mo
    GCP_MONTHLY = 16.13
    gcp_daily = GCP_MONTHLY / 30.0  # ~$0.54/day

    # Modal GPU cost — calculated from ACTUAL audio generation time
    # Modal T4 GPU pricing: $0.000221/sec ($0.796/hr)
    # Source: https://modal.com/pricing (T4 on-demand)
    MODAL_T4_PER_SEC = 0.000221
    audio_secs = state.get("audio_elapsed_seconds", 0)
    modal_cost = audio_secs * MODAL_T4_PER_SEC
    audio_mins = audio_secs / 60.0

    # Mistral, Resend, Vercel, Render = $0 (free tiers)
    total_run_cost = modal_cost + gcp_daily

    # Build cost breakdown for this run
    state["cost_this_run"] = f"${total_run_cost:.2f}"
    state["cost_modal"] = f"${modal_cost:.2f} ({audio_mins:.1f} GPU-min)"
    state["cost_gcp_daily"] = f"${gcp_daily:.2f}"
    state["disk_info"] = f"Audio: {total_audio} files ({audio_gb:.2f} GB), Covers: {cover_count} SVGs"

    # Monthly projection (estimated — uses this run's Modal cost × 30)
    modal_monthly_est = modal_cost * 30
    total_monthly_est = GCP_MONTHLY + modal_monthly_est
    state["cost_monthly"] = (
        f"~${total_monthly_est:.2f}/mo est. "
        f"(GCP ${GCP_MONTHLY:.2f} + Modal ~${modal_monthly_est:.2f})"
    )

    # Collect generated titles for email
    if CONTENT_PATH.exists():
        try:
            content = json.loads(CONTENT_PATH.read_text())
            id_map = {s["id"]: s.get("title", s["id"]) for s in content if s.get("id")}
            id_set = set(state.get("generated_ids", []))
            titles = [id_map[sid] for sid in id_set if sid in id_map]
            state["generated_titles"] = titles

            # Map cover IDs to titles for detailed cover status in email
            covers_ok_ids = state.get("covers_generated", [])
            covers_fail_ids = state.get("covers_failed", [])
            covers_flux_ids = state.get("covers_flux", [])
            covers_fallback_ids = state.get("covers_fallback", [])
            state["covers_generated_titles"] = [id_map.get(sid, sid[:12]) for sid in covers_ok_ids]
            state["covers_failed_titles"] = [id_map.get(sid, sid[:12]) for sid in covers_fail_ids]
            state["covers_flux_titles"] = [id_map.get(sid, sid[:12]) for sid in covers_flux_ids]
            state["covers_fallback_titles"] = [id_map.get(sid, sid[:12]) for sid in covers_fallback_ids]
        except Exception:
            pass

    logger.info("  Modal GPU: ${:.2f} ({:.1f} min actual GPU time)".format(modal_cost, audio_mins))
    logger.info("  GCP VM:    ${:.2f}/day (${:.2f}/mo)".format(gcp_daily, GCP_MONTHLY))
    logger.info("  This run:  ${:.2f} total".format(total_run_cost))
    logger.info("  Monthly:   %s", state["cost_monthly"])
    logger.info("  Disk:      %s", state["disk_info"])


# ═══════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════

def print_summary(state: dict, total_elapsed: float):
    """Print pipeline run summary."""
    logger.info("\n" + "=" * 50)
    logger.info("  PIPELINE SUMMARY")
    logger.info("=" * 50)
    logger.info("  Generated:  %d items (%d stories, %d poems, %d lullabies)",
                len(state.get("generated_ids", [])),
                state.get("generated_stories", 0),
                state.get("generated_poems", 0),
                state.get("generated_lullabies", 0))
    logger.info("  Audio gen:  %s", state.get("step_audio", "not run"))
    logger.info("  QA passed:  %d", len(state.get("qa_passed", [])))
    logger.info("  QA failed:  %d", len(state.get("qa_failed", [])))
    logger.info("  Covers:     %d generated (%d FLUX, %d Mistral fallback), %d failed",
                len(state.get("covers_generated", [])),
                len(state.get("covers_flux", [])),
                len(state.get("covers_fallback", [])),
                len(state.get("covers_failed", [])))
    logger.info("  Enriched:   %s", state.get("step_enrich", "not run"))
    logger.info("  Synced:     %s", state.get("step_sync", "not run"))
    logger.info("  Published:  %s", state.get("step_publish", "not run"))
    logger.info("  Deployed:   %s", state.get("step_deploy_prod", "not run"))
    logger.info("  Cost:       %s (Modal %s + GCP %s/day)",
                state.get("cost_this_run", "?"),
                state.get("cost_modal", "?"),
                state.get("cost_gcp_daily", "?"))
    logger.info("  Total time: %.0f seconds (%.1f min)", total_elapsed, total_elapsed / 60)
    logger.info("  Log file:   %s", log_file)
    logger.info("=" * 50)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Automated content pipeline: generate → audio → QA → enrich → publish",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--count-stories", type=int, default=1,
                        help="Number of stories to generate (default: 1)")
    parser.add_argument("--count-poems", type=int, default=1,
                        help="Number of poems to generate (default: 1)")
    parser.add_argument("--count-lullabies", type=int, default=1,
                        help="Number of lullabies to generate (default: 1)")
    parser.add_argument("--count-long-stories", type=int, default=1,
                        help="Number of additional LONG stories to generate (default: 1)")
    parser.add_argument("--lang", default="en",
                        help="Language to generate (default: en)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without making API calls")
    parser.add_argument("--skip-publish", action="store_true",
                        help="Skip git push step")
    parser.add_argument("--skip-deploy-prod", action="store_true",
                        help="Skip production deployment step")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last checkpoint")
    parser.add_argument("--step", choices=STEPS,
                        help="Run only a specific step")
    parser.add_argument("--mood", choices=["wired", "curious", "calm", "sad", "anxious", "angry"],
                        default=None, help="Target mood for experimental content generation")
    parser.add_argument("--age", default=None,
                        help="Force specific age group (e.g. 6-8) for --mood runs")
    parser.add_argument("--type", dest="content_type",
                        choices=["story", "long_story", "poem", "song", "all"],
                        default=None,
                        help="Content type to generate (shorthand, used with --mood)")

    args = parser.parse_args()

    # --type flag sets count flags (convenience for mood runs)
    if args.content_type:
        if args.content_type == "story":
            args.count_stories = max(args.count_stories, 1)
        elif args.content_type == "long_story":
            args.count_long_stories = max(args.count_long_stories, 1)
        elif args.content_type == "poem":
            args.count_poems = max(args.count_poems, 1)
        elif args.content_type == "song":
            args.count_lullabies = max(args.count_lullabies, 1)
        elif args.content_type == "all":
            args.count_stories = max(args.count_stories, 1)
            args.count_poems = max(args.count_poems, 1)
            args.count_lullabies = max(args.count_lullabies, 1)

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║  Dream Valley — Content Pipeline             ║")
    logger.info("║  %s                            ║", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("╚══════════════════════════════════════════════╝")
    logger.info("")
    logger.info("  Stories: %d | Long stories: %d | Poems: %d | Lullabies: %d | Lang: %s",
                args.count_stories, args.count_long_stories, args.count_poems, args.count_lullabies, args.lang)
    if args.mood:
        logger.info("  Mood: %s | Age: %s (experimental)", args.mood, args.age or "random")
    logger.info("  Dry run: %s | Skip publish: %s", args.dry_run, args.skip_publish)
    logger.info("")

    # Check required env vars
    required_env = {
        "MISTRAL_API_KEY": "Mistral AI (content generation + music params)",
    }
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing and not args.dry_run:
        for k in missing:
            logger.error("Missing env var: %s (%s)", k, required_env[k])
        logger.error("Set these in .env or export them. Aborting.")
        sys.exit(1)

    # Load or create state
    if args.resume:
        state = load_state()
        logger.info("  Resuming from checkpoint: %s", state.get("last_step", "start"))
    else:
        state = {"started_at": datetime.now().isoformat(), "args": vars(args)}
        if args.mood:
            state["mood"] = args.mood
        save_state(state)

    total_start = time.time()

    # ── Preflight checks ──
    preflight_checks(args)

    # Define step sequence
    step_funcs = {
        "generate": step_generate,
        "audio": step_audio,
        "qa": step_qa,
        "enrich": step_enrich,
        "mood": step_mood,
        "covers": step_covers,
        "sync": step_sync,         # sync BEFORE clips so new audio/covers are available
        "clips": step_clips,
        "publish": step_publish,
        "deploy_prod": step_deploy_prod,
    }

    steps_to_run = [args.step] if args.step else STEPS

    for step_name in steps_to_run:
        # Skip already-completed steps on resume
        if args.resume and state.get(f"step_{step_name}") == "done":
            logger.info("  Skipping %s (already done)", step_name)
            continue

        state["last_step"] = step_name
        save_state(state)

        ok = step_funcs[step_name](args, state)
        if not ok:
            logger.error("Step '%s' failed. Pipeline halted.", step_name)
            logger.error("Run with --resume to retry from this step.")
            state["status"] = f"failed_at_{step_name}"
            save_state(state)
            break
    else:
        state["status"] = "completed"
        state["completed_at"] = datetime.now().isoformat()
        save_state(state)

    total_elapsed = time.time() - total_start

    # ── Postflight: cost + disk summary ──
    postflight_checks(state)

    # ── Summary ──
    print_summary(state, total_elapsed)

    # ── Email notifications (ALWAYS — success or failure) ──
    try:
        from pipeline_notify import send_pipeline_notification, send_qa_notification
        send_pipeline_notification(state, str(log_file), total_elapsed)
        send_qa_notification(state)
    except ImportError:
        # Try with full path
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from pipeline_notify import send_pipeline_notification, send_qa_notification
            send_pipeline_notification(state, str(log_file), total_elapsed)
            send_qa_notification(state)
        except Exception as e:
            logger.warning("  Email notification failed: %s", e)
    except Exception as e:
        logger.warning("  Email notification failed: %s", e)


def _send_crash_email(error: Exception):
    """Send a crash notification email when pipeline fails before reaching normal notification."""
    try:
        import traceback
        sys.path.insert(0, str(SCRIPTS_DIR))
        from pipeline_notify import RESEND_API_KEY, RESEND_ENDPOINT, FROM_EMAIL, TO_EMAIL
        if not RESEND_API_KEY:
            return
        import httpx
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        tb = traceback.format_exc()
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
          <div style="background:#ef4444;color:white;padding:16px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">🚨 Pipeline CRASH — {date_str}</h2>
          </div>
          <div style="background:#1a1a2e;color:#e0e0e0;padding:16px;border-radius:0 0 8px 8px;">
            <p>The pipeline crashed before it could complete any steps.</p>
            <p><b>Error:</b> {type(error).__name__}: {error}</p>
            <pre style="background:#111;padding:12px;border-radius:4px;overflow-x:auto;font-size:12px;color:#f87171;">{tb}</pre>
            <p style="color:#888;font-size:12px;margin-top:16px;">Fix the issue and re-run, or wait for the next scheduled run.</p>
          </div>
        </div>
        """
        httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": [TO_EMAIL], "subject": f"[CRASH] Dream Valley Pipeline — {date_str}", "html": html},
            timeout=15,
        )
    except Exception:
        pass  # Last resort — don't let the crash email crash


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _send_crash_email(e)
        raise
