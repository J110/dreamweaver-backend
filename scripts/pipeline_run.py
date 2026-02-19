#!/usr/bin/env python3
"""Automated content pipeline — generate, QA, enrich, and publish new stories/poems.

Runs the full pipeline as subprocesses for isolation and crash safety.
Designed to run autonomously on the GCP production server (daily cron).

Pipeline flow:
  1. GENERATE  → Mistral Large (free tier) → stories + poems
  2. AUDIO GEN → Modal Chatterbox TTS ($30 free credits) → 14 MP3 files per 2 items
  3. AUDIO QA  → Voxtral transcription + fidelity (free tier) → PASS/FAIL
  4. ENRICH    → Mistral Large (free tier) → musicParams for new items
  5. COVERS    → Mistral Large (free tier) → animated SVG covers
  6. SYNC      → sync content.json → seedData.js + copy audio/covers to web
  7. PUBLISH   → git push → Render/Vercel auto-deploy (test only)
  8. NOTIFY    → email via Resend (success or failure)

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
STEPS = ["generate", "audio", "qa", "enrich", "covers", "sync", "publish"]

CHATTERBOX_HEALTH = "https://anmol-71634--dreamweaver-chatterbox-health.modal.run"


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


def run_command(cmd: list, label: str, timeout: int = 3600, cwd: str = None) -> tuple:
    """Run a subprocess command, return (success, stdout, stderr, elapsed)."""
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
        )
        elapsed = time.time() - start

        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                logger.info("  %s", line)

        if result.returncode != 0:
            logger.error("  FAILED (exit code %d, %.0fs)", result.returncode, elapsed)
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    logger.error("  stderr: %s", line)
            return False, result.stdout, result.stderr, elapsed

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
# PIPELINE STEPS
# ═══════════════════════════════════════════════════════════════════════

def step_generate(args, state: dict) -> bool:
    """Step 1: Generate new stories and poems via Mistral AI."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 1: GENERATE CONTENT            ║")
    logger.info("╚══════════════════════════════════════╝")

    before_ids = get_existing_ids()

    # Build the generation command using --count-stories/--count-poems for fresh daily content
    cmd = [
        sys.executable, str(SCRIPTS_DIR / "generate_content_matrix.py"),
        "--api", "mistral",
        "--count-stories", str(args.count_stories),
        "--count-poems", str(args.count_poems),
    ]
    if args.lang:
        cmd += ["--lang", args.lang]
    if args.dry_run:
        cmd += ["--dry-run"]

    ok, stdout, stderr, elapsed = run_command(cmd, "Content Generation", timeout=1800)

    if not ok:
        return False

    # Find newly generated IDs
    new_ids = get_new_story_ids(before_ids)
    logger.info("  New items generated: %d", len(new_ids))

    # Merge into content.json
    if new_ids and not args.dry_run:
        merge_expanded_to_content(new_ids)

    state["generated_ids"] = new_ids
    state["step_generate"] = "done"
    save_state(state)
    return True


def step_audio(args, state: dict) -> bool:
    """Step 2: Generate audio variants for new stories via Chatterbox TTS on Modal."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 2: GENERATE AUDIO              ║")
    logger.info("╚══════════════════════════════════════╝")

    new_ids = state.get("generated_ids", [])
    if not new_ids:
        logger.info("  No new stories to generate audio for. Skipping.")
        state["step_audio"] = "skipped"
        save_state(state)
        return True

    # Generate audio for each new story
    for sid in new_ids:
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_audio.py"),
            "--story-id", sid,
            "--speed", "0.8",  # Bedtime pace
            "--workers", "3",  # Conservative parallelism for free credits
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Audio: {sid[:8]}...", timeout=1200
        )
        if not ok:
            logger.error("  Audio generation failed for %s", sid)
            # Continue with other stories — don't abort entire pipeline
            state.setdefault("audio_failures", []).append(sid)

    state["step_audio"] = "done"
    save_state(state)
    return True


def step_qa(args, state: dict) -> bool:
    """Step 3: QA audio (phase 1 duration + phase 2 fidelity only, no quality scoring)."""
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

    qa_passed = []
    qa_failed = []

    for sid in qa_ids:
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "qa_audio.py"),
            "--story-id", sid,
            "--no-quality-score",  # Skip phase 3 (expensive quality scoring)
            "--lang", args.lang or "en",
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"QA: {sid[:8]}...", timeout=600
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

    state["qa_passed"] = qa_passed
    state["qa_failed"] = qa_failed
    state["step_qa"] = "done"
    save_state(state)

    logger.info("  QA Results: %d passed, %d failed", len(qa_passed), len(qa_failed))
    return True


def step_enrich(args, state: dict) -> bool:
    """Step 4: Generate musicParams for QA-passed stories via Mistral AI."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 4: ENRICH (musicParams)        ║")
    logger.info("╚══════════════════════════════════════╝")

    qa_passed = state.get("qa_passed", [])
    if not qa_passed:
        logger.info("  No QA-passed stories to enrich. Skipping.")
        state["step_enrich"] = "skipped"
        save_state(state)
        return True

    for sid in qa_passed:
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_music_params.py"),
            "--id", sid,
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Music params: {sid[:8]}...", timeout=300
        )
        if not ok:
            logger.warning("  Music params generation failed for %s (non-fatal)", sid)

    state["step_enrich"] = "done"
    save_state(state)
    return True


def step_covers(args, state: dict) -> bool:
    """Step 5: Generate animated SVG covers for new stories via Mistral AI."""
    logger.info("\n╔══════════════════════════════════════╗")
    logger.info("║  STEP 5: GENERATE COVERS             ║")
    logger.info("╚══════════════════════════════════════╝")

    qa_passed = state.get("qa_passed", [])
    if not qa_passed:
        logger.info("  No QA-passed stories to generate covers for. Skipping.")
        state["step_covers"] = "skipped"
        state["covers_generated"] = []
        state["covers_failed"] = []
        save_state(state)
        return True

    covers_generated = []
    covers_failed = []

    for sid in qa_passed:
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "generate_cover_svg.py"),
            "--id", sid,
        ]
        if args.dry_run:
            cmd += ["--dry-run"]

        ok, stdout, stderr, elapsed = run_command(
            cmd, f"Cover: {sid[:8]}...", timeout=600
        )
        if ok and "OK:" in stdout:
            covers_generated.append(sid)
        else:
            covers_failed.append(sid)
            logger.warning("  Cover generation failed for %s (will use default.svg)", sid)

    state["covers_generated"] = covers_generated
    state["covers_failed"] = covers_failed
    state["step_covers"] = "done"
    save_state(state)
    logger.info("  Covers: %d generated, %d fallback", len(covers_generated), len(covers_failed))
    return True


def step_sync(args, state: dict) -> bool:
    """Step 6: Sync content.json → seedData.js for the web frontend."""
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

    # Copy new audio files to web public folder so Next.js can serve them
    web_audio_dir = WEB_DIR / "public" / "audio" / "pre-gen"
    backend_audio_dir = BASE_DIR / "audio" / "pre-gen"
    if web_audio_dir.exists() and backend_audio_dir.exists():
        import shutil
        qa_passed = state.get("qa_passed", [])
        copied = 0
        for story_id in qa_passed:
            short_id = story_id[:8]
            for mp3 in backend_audio_dir.glob(f"{short_id}*.mp3"):
                dest = web_audio_dir / mp3.name
                if not dest.exists() or mp3.stat().st_mtime > dest.stat().st_mtime:
                    shutil.copy2(mp3, dest)
                    copied += 1
        if copied:
            logger.info("  Copied %d audio files to web public folder", copied)

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

    qa_passed = state.get("qa_passed", [])
    if not qa_passed:
        logger.info("  No QA-passed content to publish. Skipping.")
        state["step_publish"] = "skipped"
        save_state(state)
        return True

    date_str = datetime.now().strftime("%Y-%m-%d")
    commit_msg = f"pipeline: add {len(qa_passed)} new content items ({date_str})"

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
              "public/audio/pre-gen/", "public/covers/"], "Frontend: git add"),
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
                logger.info("  Modal health: OK")
            else:
                logger.warning("  Modal health: HTTP %d", resp.status_code)
        except Exception as e:
            logger.warning("  Modal warmup failed: %s (will retry during audio step)", e)

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

    # ── Cost estimates ──────────────────────────────────────────────────
    # GCP infrastructure (always-on, fixed monthly cost)
    #   e2-small instance (asia-south1): $14.69/mo
    #   30GB standard persistent disk:   $1.44/mo
    #   Total GCP infra:                 $16.13/mo
    GCP_MONTHLY = 16.13
    gcp_daily = GCP_MONTHLY / 30.0  # ~$0.54/day

    # Modal GPU (variable per run — 7 audio variants per item)
    n_items = len(state.get("generated_ids", []))
    n_variants = n_items * 7  # 7 voices per story
    modal_cost = n_variants * 0.031  # ~$0.031 per variant (43.5 GPU-min / 14 variants × $0.01/min)

    # Mistral, Resend, Vercel, Render = $0 (free tiers)
    total_run_cost = modal_cost + gcp_daily

    # Build cost string for this run
    parts = []
    parts.append(f"Modal GPU: ${modal_cost:.2f} ({n_variants} audio variants)")
    parts.append(f"GCP VM: ${gcp_daily:.2f}/day (${GCP_MONTHLY:.2f}/mo e2-small + 30GB disk)")
    parts.append(f"Mistral/Resend/Render/Vercel: $0.00 (free tiers)")
    cost_str = " | ".join(parts)

    # Monthly projection
    modal_monthly = modal_cost * 30  # assumes daily runs
    total_monthly = GCP_MONTHLY + modal_monthly
    monthly_str = f"~${total_monthly:.2f}/mo (GCP ${GCP_MONTHLY:.2f} + Modal ~${modal_monthly:.2f} from $30 free credits)"

    state["cost_estimate"] = cost_str
    state["cost_monthly"] = monthly_str
    state["cost_this_run"] = f"~${total_run_cost:.2f}"
    state["disk_info"] = f"Audio: {total_audio} files ({audio_gb:.2f} GB), Covers: {cover_count} SVGs"

    # Collect generated titles for email
    if CONTENT_PATH.exists():
        try:
            content = json.loads(CONTENT_PATH.read_text())
            id_set = set(state.get("generated_ids", []))
            titles = [s["title"] for s in content if s.get("id") in id_set]
            state["generated_titles"] = titles
        except Exception:
            pass

    logger.info("  This run:  ~$%.2f (Modal $%.2f + GCP $%.2f/day)", total_run_cost, modal_cost, gcp_daily)
    logger.info("  Monthly:   %s", monthly_str)
    logger.info("  Disk:      %s", state["disk_info"])


# ═══════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════

def print_summary(state: dict, total_elapsed: float):
    """Print pipeline run summary."""
    logger.info("\n" + "=" * 50)
    logger.info("  PIPELINE SUMMARY")
    logger.info("=" * 50)
    logger.info("  Generated:  %d items", len(state.get("generated_ids", [])))
    logger.info("  Audio gen:  %s", state.get("step_audio", "not run"))
    logger.info("  QA passed:  %d", len(state.get("qa_passed", [])))
    logger.info("  QA failed:  %d", len(state.get("qa_failed", [])))
    logger.info("  Covers:     %d generated, %d fallback",
                len(state.get("covers_generated", [])),
                len(state.get("covers_failed", [])))
    logger.info("  Enriched:   %s", state.get("step_enrich", "not run"))
    logger.info("  Synced:     %s", state.get("step_sync", "not run"))
    logger.info("  Published:  %s", state.get("step_publish", "not run"))
    logger.info("  Cost:       %s", state.get("cost_estimate", "unknown"))
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
    parser.add_argument("--lang", default="en",
                        help="Language to generate (default: en)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without making API calls")
    parser.add_argument("--skip-publish", action="store_true",
                        help="Skip git push step")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last checkpoint")
    parser.add_argument("--step", choices=STEPS,
                        help="Run only a specific step")

    args = parser.parse_args()

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║  Dream Valley — Content Pipeline             ║")
    logger.info("║  %s                            ║", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("╚══════════════════════════════════════════════╝")
    logger.info("")
    logger.info("  Stories: %d | Poems: %d | Lang: %s", args.count_stories, args.count_poems, args.lang)
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
        "covers": step_covers,
        "sync": step_sync,
        "publish": step_publish,
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

    # ── Email notification (ALWAYS — success or failure) ──
    try:
        from pipeline_notify import send_pipeline_notification
        send_pipeline_notification(state, str(log_file), total_elapsed)
    except ImportError:
        # Try with full path
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from pipeline_notify import send_pipeline_notification
            send_pipeline_notification(state, str(log_file), total_elapsed)
        except Exception as e:
            logger.warning("  Email notification failed: %s", e)
    except Exception as e:
        logger.warning("  Email notification failed: %s", e)


if __name__ == "__main__":
    main()
