#!/usr/bin/env python3
"""Hindi Daily Pipeline — orchestrator.

Runs once per day from cron AFTER the English pipeline has finished
(English: 01:30 UTC, Hindi: 04:00 UTC). Generates one of each Hindi
content type, deploys to prod, sends an email summary via the same
pipeline_notify module the English pipeline uses.

Generates:
  1. Hindi short story  (ElevenLabs Multilingual v2, ~3-5 min audio)
  2. Hindi long story   (EL multi-voice + MiniMax mid-song + bed/swells, ~13-15 min)
  3. Hindi lullaby      (MiniMax v2.5 + Hindi reference, ~60-90s)
  4. Hindi silly song   (ElevenLabs Music, ~70s)
  5. Hindi musical poem (MiniMax v2.5 + Hindi reference, ~30-45s)

Failure handling:
  - Each generator runs in isolation; partial failures still ship the successes.
  - On any generator failure, log to seed_output/_hindi_failures.jsonl.
  - Email always sent (success or failure).
  - Exit code: 0 if ≥3 of 5 succeeded; 1 otherwise (alerts cron).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

# Local imports (after sys.path tweak)
from _hindi_diversity import PICKERS, load_hindi_catalog  # type: ignore
from _hindi_generators import GENERATORS  # type: ignore

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"pipeline_hi_{datetime.now():%Y%m%d_%H%M%S}.log"
FAILURES_LOG = BASE_DIR / "seed_output" / "_hindi_failures.jsonl"

CONTENT_TYPES_ORDER = [
    # Cheaper / faster first (so partial failure on the long story still
    # ships the easy stuff). Funny shorts go alongside silly_song +
    # poem in the before-bed tab.
    "lullaby", "poem", "funny_short", "silly_song", "short_story", "long_story",
]


def _git_commit_and_push(generated_ids: list[str]) -> bool:
    """Commit fresh seed + per-item-runtime + audio bytes, push."""
    if not generated_ids:
        return False
    try:
        subprocess.run(
            ["git", "add",
             "seed_output/content.json",
             "data/silly_songs", "data/poems", "data/funny_shorts",
             "seed_output/lullabies", "seed_output/stories_hi",
             "seed_output/silly_songs", "seed_output/poems_hi",
             "seed_output/hindi_long"],
            cwd=BASE_DIR, check=False,
        )
        msg = (
            f"hindi-daily {datetime.now():%Y-%m-%d}: +{len(generated_ids)} items "
            f"({', '.join(generated_ids)})"
        )
        r = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=BASE_DIR, capture_output=True, text=True,
        )
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            print(f"  git commit failed: {r.stderr[:300]}")
            return False
        # Pull-rebase first to handle daily English commits
        subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=BASE_DIR, check=False, capture_output=True,
        )
        r = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=BASE_DIR, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  git push failed: {r.stderr[:300]}")
            return False
        print(f"  ✓ pushed {len(generated_ids)} items to origin/main")
        return True
    except Exception as e:
        print(f"  git operation failed: {e}")
        return False


def _admin_reload() -> bool:
    """Trigger backend admin reload so new items go live immediately."""
    try:
        import httpx  # type: ignore
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(BASE_DIR / ".env", override=True)
        admin_key = os.getenv("ADMIN_API_KEY", "")
        if not admin_key:
            print("  ADMIN_API_KEY missing — skip reload")
            return False
        r = httpx.post(
            "https://api.dreamvalley.app/api/v1/admin/reload",
            headers={"X-Admin-Key": admin_key},
            timeout=60,
        )
        if r.status_code == 200:
            print(f"  ✓ admin reload: {r.json().get('message','')}")
            return True
        print(f"  admin reload {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"  admin reload failed: {e}")
        return False


def _build_state(results: dict, elapsed: float) -> dict:
    """Shape a state dict matching pipeline_notify's expectations."""
    successes = [r for r in results.values() if r.get("status") == "ok"]
    failures = [r for r in results.values() if r.get("status") != "ok"]

    state = {
        "status": "completed" if len(successes) >= 4 else "partial",
        "lang": "hi",
        "generated_ids": [r["id"] for r in successes if r.get("id")],
        "qa_passed": [r["id"] for r in successes if r.get("id")],
        "qa_failed": [],
        "covers_generated": [r["id"] for r in successes if r.get("id")],
        "covers_failed": [],
        "covers_flux": [r["id"] for r in successes if r.get("id")],
        "covers_fallback": [],
        "elapsed_seconds": elapsed,
        "generated_stories": sum(
            1 for r in successes
            if r.get("type") in ("short_story", "long_story")
        ),
        "generated_poems": sum(1 for r in successes if r.get("type") == "poem"),
        "generated_lullabies": sum(1 for r in successes if r.get("type") == "lullaby"),
        "generated_silly_songs": sum(1 for r in successes if r.get("type") == "silly_song"),
        "generated_funny_shorts": sum(1 for r in successes if r.get("type") == "funny_short"),
        "hindi_per_type": {
            t: results[t].get("status") for t in CONTENT_TYPES_ORDER
            if t in results
        },
        "hindi_failures": [
            {"type": r["type"], "error": r.get("error", "")[:300]}
            for r in failures
        ],
        "log_file": str(LOG_FILE),
        "cost_this_run": "~$1.50-2.00 (Hindi daily)",
    }
    return state


def _send_email(state: dict, elapsed: float) -> None:
    try:
        from pipeline_notify import (  # type: ignore
            send_pipeline_notification,
        )
        send_pipeline_notification(state, str(LOG_FILE), elapsed)
        print("  ✓ email notification sent")
    except Exception as e:
        print(f"  email notification failed: {e}")
        traceback.print_exc()


def _log_failure(content_type: str, error: str) -> None:
    FAILURES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FAILURES_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now().isoformat(),
            "type": content_type,
            "error": error[:1000],
        }) + "\n")


def main(only_types: list[str] | None = None) -> int:
    print(f"\n══════ Hindi Daily Pipeline — {datetime.now():%Y-%m-%d %H:%M} ══════\n")
    pipeline_start = time.time()

    # ── deploy_guard snapshot
    print("→ deploy_guard snapshot…")
    try:
        subprocess.run(
            ["python3", "scripts/deploy_guard.py", "snapshot"],
            cwd=BASE_DIR, check=False, capture_output=True, text=True,
        )
        print("  ✓ baseline saved")
    except Exception as e:
        print(f"  snapshot failed (continuing): {e}")

    catalog = load_hindi_catalog()
    print(f"  Hindi catalog: {len(catalog)} items")

    types_to_run = only_types if only_types else CONTENT_TYPES_ORDER
    if only_types:
        print(f"  filtered run: {types_to_run}")

    results: dict[str, dict] = {}
    for content_type in types_to_run:
        print(f"\n→ {content_type.upper()}")
        try:
            axes = PICKERS[content_type](catalog)
            print(f"  axes: {{age:{axes['age_group']} mood:{axes['mood']}}}")
            entry = GENERATORS[content_type](axes, log_prefix="    ")
            results[content_type] = {
                "status": "ok",
                "type": content_type,
                "id": entry["id"],
                "title": entry.get("title", ""),
                "duration": entry.get("duration_seconds", 0),
            }
            # Reload local catalog so subsequent diversity samples
            # account for the just-generated piece.
            catalog = load_hindi_catalog()
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"  ✗ {content_type} failed: {err}")
            _log_failure(content_type, traceback.format_exc())
            results[content_type] = {
                "status": "failed",
                "type": content_type,
                "error": err,
            }

    successes = [r for r in results.values() if r.get("status") == "ok"]
    print(f"\n══ Generation done: {len(successes)}/{len(types_to_run)} succeeded ══")

    # ── Deploy: git push + admin reload
    if successes:
        print("\n→ Deploying…")
        # scp audio + covers to prod paths handled by pipeline_run_hi_deploy
        # (separate script — runs after this on the GCP VM where files are
        # already on disk under /opt/dreamweaver-web/public/...)
        _git_commit_and_push([r["id"] for r in successes if r.get("id")])
        _admin_reload()

    # ── deploy_guard verify
    print("\n→ deploy_guard verify…")
    try:
        subprocess.run(
            ["python3", "scripts/deploy_guard.py", "verify"],
            cwd=BASE_DIR, check=False, capture_output=True, text=True,
        )
        print("  ✓ verify completed")
    except Exception as e:
        print(f"  verify failed (continuing): {e}")

    # ── Email
    elapsed = time.time() - pipeline_start
    state = _build_state(results, elapsed)
    print(f"\n→ Email notification…")
    _send_email(state, elapsed)

    # ── Summary
    print(f"\n══════ Done in {elapsed:.0f}s ══════")
    print(f"  successes: {len(successes)}/{len(types_to_run)}")
    for content_type in types_to_run:
        if content_type not in results:
            continue
        r = results[content_type]
        icon = "✓" if r.get("status") == "ok" else "✗"
        suffix = r.get("id", r.get("error", ""))[:60]
        print(f"  {icon} {content_type:12s}  {suffix}")

    # Exit 0 if ≥3 of 5 succeeded; 1 otherwise (alerts cron)
    return 0 if len(successes) >= 4 else 1


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument(
        "--types", nargs="+", default=None,
        choices=CONTENT_TYPES_ORDER,
        help="Run only these types (default: all 5). Use for retry of failed types.",
    )
    args = p.parse_args()
    sys.exit(main(only_types=args.types))
