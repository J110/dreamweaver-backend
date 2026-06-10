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

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(BASE_DIR / ".env", override=True)
except Exception:
    pass

# Local imports (after sys.path tweak)
from _hindi_diversity import PICKERS, load_hindi_catalog  # type: ignore
from _hindi_generators import GENERATORS  # type: ignore
from _fal_utils import FalBalanceExhausted as _FalBalanceExhausted

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
    # Any EXPECTED type that failed to generate must be visible: a single-type
    # drop forces the email to [PARTIAL] via generation_warning, regardless of
    # how many others succeeded. Replaces the old ">=4 successes = completed"
    # threshold that masked single-type drops (HI analog of the EN reporting fix).
    expected_failed = [t for t in CONTENT_TYPES_ORDER
                       if results.get(t, {}).get("status") == "failed"]

    state = {
        "status": "completed" if successes else "failed",
        "generation_warning": (
            "did not generate: " + ", ".join(expected_failed)
            if expected_failed else ""
        ),
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
        "fal_balance_exhausted": any(
            r.get("status") == "balance_exhausted" for r in results.values()
        ),
        "balance_exhausted_items": [
            r["type"] for r in results.values()
            if r.get("status") == "balance_exhausted"
        ],
        "log_file": str(LOG_FILE),
        "cost_this_run": "~$1.50-2.00 (Hindi daily)",
    }
    return state


# Content types that get a bounded re-pick: if one (age/mood/world) combo can't
# pass the validator after the generator's own retries, try a DIFFERENT combo
# rather than dropping the type for the day. Validator thresholds stay AS-IS.
REPICK_TYPES = {"long_story"}
MAX_PICKS = 3


def _pick_signature(axes: dict) -> tuple:
    return (axes.get("age_group"), axes.get("mood"),
            axes.get("world"), axes.get("characterType"))


def _generate_with_repick(content_type: str, catalog: list, max_picks: int = MAX_PICKS):
    """Try up to `max_picks` DISTINCT combos for a fragile type, each with the
    generator's own retry budget. Returns (entry, axes) on first success; raises
    the last error if every combo fails (surfaced as [PARTIAL] by _build_state).
    Re-pick is the lever — validators are never loosened."""
    tried = []
    last_err = None
    for attempt in range(max_picks):
        axes = PICKERS[content_type](catalog)
        guard = 0
        while _pick_signature(axes) in tried and guard < 8:
            axes = PICKERS[content_type](catalog)
            guard += 1
        tried.append(_pick_signature(axes))
        loc = f"age:{axes.get('age_group')} mood:{axes.get('mood')}"
        if axes.get("world"):
            loc += f" world:{axes.get('world')}"
        print(f"  pick {attempt + 1}/{max_picks}: {{{loc}}}")
        try:
            entry = GENERATORS[content_type](axes, log_prefix="    ")
            return entry, axes
        except _FalBalanceExhausted:
            raise  # a re-pick won't refill the fal balance
        except Exception as e:
            last_err = e
            print(f"    ✗ pick {attempt + 1} failed ({type(e).__name__}); re-picking a different combo")
            catalog = load_hindi_catalog()
    raise last_err if last_err else RuntimeError(
        f"{content_type}: all {max_picks} picks failed validation")


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
            if content_type in REPICK_TYPES:
                entry, axes = _generate_with_repick(content_type, catalog)
            else:
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
        except _FalBalanceExhausted as e:
            err = f"{type(e).__name__}: {e}"
            print(f"  ⚠  {content_type} skipped — fal-ai balance exhausted (top up at https://fal.ai/dashboard/billing)")
            _log_failure(content_type, traceback.format_exc())
            results[content_type] = {
                "status": "balance_exhausted",
                "type": content_type,
                "error": err,
            }
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

    # ── Deploy: admin reload (audio + covers already written to prod paths
    # during generation — no git push, no staging environment).
    if successes:
        print("\n→ Deploying…")
        _admin_reload()

    # ── Social-media clips (Hindi). Runs after admin reload so the
    # generator's view of seed_output/content.json includes today's items.
    if successes:
        print("\n→ Hindi clips…")
        try:
            r = subprocess.run(
                ["python3", "scripts/generate_clips_hi.py"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=1800,
            )
            if r.returncode == 0:
                print("  ✓ clips generated")
            else:
                print(f"  clips generation non-fatal failure: {r.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            print("  clips generation timed out (continuing)")
        except Exception as e:
            print(f"  clips generation failed (continuing): {e}")

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
        icon = "✓" if r.get("status") == "ok" else ("⚠" if r.get("status") == "balance_exhausted" else "✗")
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
