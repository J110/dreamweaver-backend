#!/usr/bin/env python3
"""
Deploy Guard v2 — protect production state before, during, and after deploys.

Features:
  1. Persistent golden snapshot — baseline of known-good state that survives
     across deploys. New content is merged in; nothing is lost.
  2. Pre/post deploy diffing — catches unintended regressions.
  3. English-only reporting — Hindi stories are excluded from all counts,
     diffs, and file checks (they're invisible to users).
  4. Auto-recovery — missing files are restored from backup stores
     (/opt/cover-store, /opt/audio-store) automatically.

Usage:
    # BEFORE deploy: capture current live state
    python3 scripts/deploy_guard.py snapshot

    # AFTER deploy: verify + auto-recover anything broken
    python3 scripts/deploy_guard.py verify

    # Quick health check (no snapshot needed)
    python3 scripts/deploy_guard.py check

    # Update golden baseline (run after verifying a good deploy)
    python3 scripts/deploy_guard.py seal

    # Verify against golden baseline (detects drift from known-good)
    python3 scripts/deploy_guard.py audit

    # Recover missing files without full verify
    python3 scripts/deploy_guard.py recover
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = BASE_DIR / "data" / "deploy_snapshot.json"
GOLDEN_PATH = BASE_DIR / "data" / "deploy_golden.json"

# Production API
PROD_API = "https://api.dreamvalley.app"
LOCAL_API = "http://localhost:8000"

# Frontend (nginx serves /covers/ and /audio/)
PROD_FRONTEND = "https://dreamvalley.app"
LOCAL_FRONTEND = "http://localhost:3000"

# GCP VM SSH command prefix
SSH_CMD = ["gcloud", "compute", "ssh", "dreamvalley-prod",
           "--project=strong-harbor-472607-n4", "--zone=asia-south1-a",
           "--command"]

# Backup stores on the GCP VM
COVER_STORE = "/opt/cover-store"
AUDIO_STORE_PREGEN = "/opt/audio-store/pre-gen"
AUDIO_STORE_SILLY = "/opt/audio-store/silly-songs"

# Serve paths on the GCP VM
FRONTEND_COVERS = "/opt/dreamweaver-web/public/covers"
FRONTEND_AUDIO = "/opt/dreamweaver-web/public/audio/pre-gen"
BACKEND_COVERS_FUNNY = "/opt/dreamweaver-backend/public/covers/funny-shorts"
BACKEND_COVERS_SILLY = "/opt/dreamweaver-backend/public/covers/silly-songs"
BACKEND_AUDIO_SILLY = "/opt/dreamweaver-backend/public/audio/silly-songs"


def get_api(use_local: bool = False) -> str:
    return LOCAL_API if use_local else PROD_API


def get_frontend(use_local: bool = False) -> str:
    return LOCAL_FRONTEND if use_local else PROD_FRONTEND


def capture_state(api: str) -> dict:
    """Capture full production state from API, English content only."""
    client = httpx.Client(timeout=30)
    state = {
        "captured_at": datetime.now().isoformat(),
        "api": api,
    }

    # 1. Stories (paginate — API max page_size=100), English only
    try:
        all_items = []
        page = 1
        while True:
            resp = client.get(f"{api}/api/v1/content",
                              params={"page_size": 100, "page": page, "lang": "en"})
            data = resp.json()
            page_data = data.get("data", data) if isinstance(data, dict) else data
            items = page_data.get("items", []) if isinstance(page_data, dict) else page_data
            all_items.extend(items)
            total_pages = page_data.get("pages", 1) if isinstance(page_data, dict) else 1
            if page >= total_pages:
                break
            page += 1

        stories = []
        for item in all_items:
            lang = item.get("lang", "en")
            if lang != "en":
                continue  # Skip non-English stories entirely
            audio_urls = []
            for av in (item.get("audio_variants") or []):
                url = av.get("url", "")
                # Skip Hindi audio variants
                if url and "_hi." not in url:
                    audio_urls.append(url)
            cover_url = item.get("cover", "")
            stories.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "type": item.get("type"),
                "has_audio": bool(audio_urls),
                "has_cover": bool(cover_url and cover_url != "/covers/default.svg"),
                "audio_urls": audio_urls,
                "cover_url": cover_url if cover_url != "/covers/default.svg" else "",
                "mood": item.get("mood"),
            })
        state["stories"] = {s["id"]: s for s in stories}
        state["story_count"] = len(stories)
    except Exception as e:
        state["stories"] = {}
        state["story_count"] = 0
        state["stories_error"] = str(e)

    # 2. Funny shorts (per age group)
    state["funny_shorts"] = {}
    for age in ["2-5", "6-8", "9-12"]:
        try:
            resp = client.get(f"{api}/api/v1/funny-shorts", params={"age_group": age})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            state["funny_shorts"][age] = {
                item["id"]: {
                    "title": item.get("title"),
                    "has_audio": bool(item.get("audio_file")),
                    "audio_url": item.get("audio_url", ""),
                    "cover_url": item.get("cover", ""),
                }
                for item in items
            }
        except Exception:
            state["funny_shorts"][age] = {}

    # 3. Silly songs (per age group)
    state["silly_songs"] = {}
    for age in ["2-5", "6-8", "9-12"]:
        try:
            resp = client.get(f"{api}/api/v1/silly-songs", params={"age_group": age})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            state["silly_songs"][age] = {
                item["id"]: {
                    "title": item.get("title"),
                    "has_audio": bool(item.get("audio_file")),
                    "audio_url": f"/audio/silly-songs/{item['audio_file']}" if item.get("audio_file") else "",
                    "cover_url": f"/covers/silly-songs/{item['cover_file']}" if item.get("cover_file") else "",
                }
                for item in items
            }
        except Exception:
            state["silly_songs"][age] = {}

    return state


def verify_files(state: dict, frontend: str, api: str) -> tuple[list[str], list[dict]]:
    """HEAD-check all audio and cover URLs. Returns (issues, recoverable_items).

    Each recoverable_item is a dict with keys:
      type: 'story_audio' | 'story_cover' | 'funny_short_cover' | 'silly_song_audio' | 'silly_song_cover'
      url_path: the URL path that's missing
      filename: the filename to look for in backup stores
    """
    issues = []
    recoverable = []
    urls_to_check = []  # (base_url, url_path, label, recovery_info)

    # Stories — served by nginx (frontend)
    for sid, s in state.get("stories", {}).items():
        for url in s.get("audio_urls", []):
            if url:
                filename = url.split("/")[-1]
                urls_to_check.append((frontend, url, f"story audio: {sid}",
                                      {"type": "story_audio", "url_path": url, "filename": filename}))
        if s.get("cover_url"):
            filename = s["cover_url"].split("/")[-1]
            urls_to_check.append((frontend, s["cover_url"], f"story cover: {sid}",
                                  {"type": "story_cover", "url_path": s["cover_url"], "filename": filename}))

    # Funny shorts covers — served by nginx from backend public dir
    for age, items in state.get("funny_shorts", {}).items():
        for fid, f in items.items():
            if f.get("audio_url"):
                filename = f["audio_url"].split("/")[-1]
                urls_to_check.append((api, f["audio_url"], f"funny short audio ({age}): {fid}",
                                      {"type": "funny_short_audio", "url_path": f["audio_url"], "filename": filename}))
            if f.get("cover_url"):
                filename = f["cover_url"].split("/")[-1]
                urls_to_check.append((frontend, f["cover_url"], f"funny short cover ({age}): {fid}",
                                      {"type": "funny_short_cover", "url_path": f["cover_url"], "filename": filename}))

    # Silly songs — served by backend API
    for age, items in state.get("silly_songs", {}).items():
        for sid, s in items.items():
            if s.get("audio_url"):
                filename = s["audio_url"].split("/")[-1]
                urls_to_check.append((api, s["audio_url"], f"silly song audio ({age}): {sid}",
                                      {"type": "silly_song_audio", "url_path": s["audio_url"], "filename": filename}))
            if s.get("cover_url"):
                filename = s["cover_url"].split("/")[-1]
                urls_to_check.append((frontend, s["cover_url"], f"silly song cover ({age}): {sid}",
                                      {"type": "silly_song_cover", "url_path": s["cover_url"], "filename": filename}))

    if not urls_to_check:
        return issues, recoverable

    print(f"\n  Checking {len(urls_to_check)} file URLs via HEAD requests...")

    ok = 0
    failed = 0
    client = httpx.Client(timeout=10, follow_redirects=True)
    for base_url, url_path, label, recovery_info in urls_to_check:
        full_url = f"{base_url}{url_path}"
        try:
            resp = client.head(full_url)
            if resp.status_code == 200:
                ok += 1
            else:
                failed += 1
                issues.append(f"  MISSING ({resp.status_code}): {url_path} — {label}")
                recoverable.append(recovery_info)
        except Exception as e:
            failed += 1
            issues.append(f"  UNREACHABLE: {url_path} — {label} ({e})")
            recoverable.append(recovery_info)

    print(f"  Results: {ok} reachable, {failed} missing/broken")

    return issues, recoverable


def auto_recover(recoverable: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """Attempt to recover missing files from backup stores on the GCP VM.

    Returns (recovered_count, failed_count).
    """
    if not recoverable:
        return 0, 0

    print(f"\n  {'[DRY RUN] ' if dry_run else ''}Auto-recovering {len(recoverable)} missing file(s)...")

    # Build a shell script that checks backup stores and copies files
    recover_commands = []
    for item in recoverable:
        ftype = item["type"]
        filename = item["filename"]

        if ftype == "story_audio":
            # Audio served from frontend /audio/pre-gen/
            recover_commands.append(
                f'if [ -f "{AUDIO_STORE_PREGEN}/{filename}" ]; then '
                f'cp "{AUDIO_STORE_PREGEN}/{filename}" "{FRONTEND_AUDIO}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "story_cover":
            # Covers served from frontend /covers/
            # Cover store uses flat naming — try exact match first, then with prefix
            recover_commands.append(
                f'if [ -f "{COVER_STORE}/{filename}" ]; then '
                f'cp "{COVER_STORE}/{filename}" "{FRONTEND_COVERS}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "funny_short_cover":
            # Funny short covers: store uses "funny-shorts--{name}.svg" naming
            store_name = f"funny-shorts--{filename}"
            recover_commands.append(
                f'if [ -f "{COVER_STORE}/{store_name}" ]; then '
                f'cp "{COVER_STORE}/{store_name}" "{BACKEND_COVERS_FUNNY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'elif [ -f "{COVER_STORE}/{filename}" ]; then '
                f'cp "{COVER_STORE}/{filename}" "{BACKEND_COVERS_FUNNY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "silly_song_audio":
            recover_commands.append(
                f'if [ -f "{AUDIO_STORE_SILLY}/{filename}" ]; then '
                f'cp "{AUDIO_STORE_SILLY}/{filename}" "{BACKEND_AUDIO_SILLY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "silly_song_cover":
            # Silly song covers: store may use "silly-songs--{name}" naming
            store_name = f"silly-songs--{filename}"
            recover_commands.append(
                f'if [ -f "{COVER_STORE}/{store_name}" ]; then '
                f'cp "{COVER_STORE}/{store_name}" "{BACKEND_COVERS_SILLY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'elif [ -f "{COVER_STORE}/{filename}" ]; then '
                f'cp "{COVER_STORE}/{filename}" "{BACKEND_COVERS_SILLY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )

    if not recover_commands:
        return 0, 0

    if dry_run:
        for cmd in recover_commands:
            print(f"    Would run: {cmd[:100]}...")
        return 0, 0

    # Execute all recovery commands via SSH
    full_script = " && ".join(recover_commands)
    try:
        result = subprocess.run(
            SSH_CMD + [full_script],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout.strip()
        if output:
            recovered = 0
            not_found = 0
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("RECOVERED:"):
                    recovered += 1
                    print(f"    ✅ {line}")
                elif line.startswith("NOT_IN_STORE:"):
                    not_found += 1
                    print(f"    ❌ {line}")
            return recovered, not_found
        if result.returncode != 0 and result.stderr:
            print(f"    SSH error: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("    SSH timed out during recovery")
    except Exception as e:
        print(f"    Recovery error: {e}")

    return 0, len(recover_commands)


def diff_states(before: dict, after: dict) -> list[str]:
    """Compare two states and return list of changes (English only)."""
    changes = []

    # Stories
    before_ids = set(before.get("stories", {}).keys())
    after_ids = set(after.get("stories", {}).keys())

    added = after_ids - before_ids
    removed = before_ids - after_ids

    if added:
        for sid in sorted(added):
            s = after["stories"][sid]
            changes.append(f"  ADDED story: {sid} — \"{s['title']}\"")

    if removed:
        for sid in sorted(removed):
            s = before["stories"][sid]
            changes.append(f"  ❌ REMOVED story: {sid} — \"{s['title']}\"")

    # Check for stories that lost audio or cover
    for sid in before_ids & after_ids:
        b, a = before["stories"][sid], after["stories"][sid]
        if b.get("has_audio") and not a.get("has_audio"):
            changes.append(f"  ❌ LOST AUDIO: {sid} — \"{a['title']}\"")
        if b.get("has_cover") and not a.get("has_cover"):
            changes.append(f"  ❌ LOST COVER: {sid} — \"{a['title']}\"")

    # Funny shorts per age group
    for age in ["2-5", "6-8", "9-12"]:
        before_fs = set(before.get("funny_shorts", {}).get(age, {}).keys())
        after_fs = set(after.get("funny_shorts", {}).get(age, {}).keys())
        for fid in sorted(after_fs - before_fs):
            changes.append(f"  ADDED funny short ({age}): {fid}")
        for fid in sorted(before_fs - after_fs):
            changes.append(f"  ❌ REMOVED funny short ({age}): {fid}")
        for fid in before_fs & after_fs:
            b = before["funny_shorts"][age][fid]
            a = after["funny_shorts"][age][fid]
            if b.get("has_audio") and not a.get("has_audio"):
                changes.append(f"  ❌ LOST AUDIO funny short ({age}): {fid}")

    # Silly songs per age group
    for age in ["2-5", "6-8", "9-12"]:
        before_ss = set(before.get("silly_songs", {}).get(age, {}).keys())
        after_ss = set(after.get("silly_songs", {}).get(age, {}).keys())
        for sid in sorted(after_ss - before_ss):
            changes.append(f"  ADDED silly song ({age}): {sid}")
        for sid in sorted(before_ss - after_ss):
            changes.append(f"  ❌ REMOVED silly song ({age}): {sid}")
        for sid in before_ss & after_ss:
            b = before["silly_songs"][age][sid]
            a = after["silly_songs"][age][sid]
            if b.get("has_audio") and not a.get("has_audio"):
                changes.append(f"  ❌ LOST AUDIO silly song ({age}): {sid}")

    return changes


def merge_golden(golden: dict, current: dict) -> dict:
    """Merge current state INTO golden baseline.

    Rules:
    - New stories/items in current are ADDED to golden (growing content).
    - Items in golden but MISSING from current are KEPT (they should still exist).
    - If an item exists in both, golden keeps the version with MORE data
      (e.g., if golden has audio but current doesn't, keep golden's version).
    """
    merged = json.loads(json.dumps(golden))  # deep copy
    merged["captured_at"] = current.get("captured_at", merged.get("captured_at"))

    # Stories: union of both, prefer version with more data
    for sid, s in current.get("stories", {}).items():
        if sid not in merged.get("stories", {}):
            merged.setdefault("stories", {})[sid] = s
        else:
            existing = merged["stories"][sid]
            # Keep the one with audio if the other lost it
            if s.get("has_audio") and not existing.get("has_audio"):
                merged["stories"][sid] = s
            # Keep the one with cover if the other lost it
            if s.get("has_cover") and not existing.get("has_cover"):
                existing["has_cover"] = True
                existing["cover_url"] = s["cover_url"]

    merged["story_count"] = len(merged.get("stories", {}))

    # Funny shorts & silly songs: same union logic
    for category in ["funny_shorts", "silly_songs"]:
        for age in ["2-5", "6-8", "9-12"]:
            current_items = current.get(category, {}).get(age, {})
            for item_id, item in current_items.items():
                merged.setdefault(category, {}).setdefault(age, {})[item_id] = item

    return merged


def print_state_summary(state: dict, label: str = "Current"):
    """Print a compact summary of state (English only)."""
    stories = state.get("stories", {})

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Captured: {state.get('captured_at', '?')}")
    print(f"{'='*60}")

    print(f"\n  STORIES")
    print(f"    Total: {len(stories)} stories")
    with_audio = sum(1 for s in stories.values() if s.get("has_audio"))
    with_cover = sum(1 for s in stories.values() if s.get("has_cover"))
    no_audio = len(stories) - with_audio
    no_cover = len(stories) - with_cover
    print(f"    Audio: {with_audio} with audio{f', ❌ {no_audio} WITHOUT' if no_audio else ' ✅'}")
    print(f"    Covers: {with_cover} with covers{f', ❌ {no_cover} WITHOUT' if no_cover else ' ✅'}")

    print(f"\n  FUNNY SHORTS")
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("funny_shorts", {}).get(age, {})
        count = len(items)
        with_audio = sum(1 for d in items.values() if d.get("has_audio"))
        status = "✅" if with_audio == count else f"❌ {count - with_audio} without audio"
        print(f"    {age}: {count} shorts, {with_audio} with audio {status}")

    print(f"\n  SILLY SONGS")
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("silly_songs", {}).get(age, {})
        count = len(items)
        with_audio = sum(1 for d in items.values() if d.get("has_audio"))
        status = "✅" if with_audio == count else f"❌ {count - with_audio} without audio"
        print(f"    {age}: {count} songs, {with_audio} with audio {status}")


def save_json(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ────────────────────────────────────────────────────────────
# Commands
# ────────────────────────────────────────────────────────────

def cmd_snapshot(args):
    """Capture and save pre-deploy state."""
    api = get_api(args.local)
    print(f"Capturing live state from {api}...")
    state = capture_state(api)
    save_json(SNAPSHOT_PATH, state)
    print_state_summary(state, "Snapshot Saved (pre-deploy)")
    print(f"\n  Saved to: {SNAPSHOT_PATH}")
    print(f"\n  ✅ Run your deploy now, then run: python3 scripts/deploy_guard.py verify\n")


def cmd_verify(args):
    """Compare current state against snapshot, check files, auto-recover."""
    before = load_json(SNAPSHOT_PATH)
    if not before:
        print("❌ No snapshot found. Run 'snapshot' before deploying.")
        sys.exit(1)

    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Capturing live state from {api}...")
    after = capture_state(api)

    print_state_summary(before, "BEFORE (pre-deploy snapshot)")
    print_state_summary(after, "AFTER (current live)")

    changes = diff_states(before, after)

    print(f"\n{'='*60}")
    if not changes:
        print("  ✅ NO REGRESSIONS — content is identical.")
    else:
        regressions = [c for c in changes if "❌" in c]
        additions = [c for c in changes if "ADDED" in c and "❌" not in c]
        if additions:
            print(f"  ✅ {len(additions)} new item(s) added (expected):")
            for c in additions:
                print(c)
        if regressions:
            print(f"\n  ❌ {len(regressions)} REGRESSION(S) DETECTED:")
            for c in regressions:
                print(c)
    print(f"{'='*60}")

    # File reachability check
    if not args.skip_files:
        file_issues, recoverable = verify_files(after, frontend, api)
        print(f"\n{'='*60}")
        if not file_issues:
            print("  ✅ All files reachable.")
        else:
            print(f"  ⚠️  {len(file_issues)} file(s) missing or broken:")
            print()
            for issue in file_issues:
                print(issue)

            # Auto-recover
            if recoverable and not args.no_recover:
                recovered, not_found = auto_recover(recoverable, dry_run=args.dry_run)
                print(f"\n  Recovery: {recovered} restored, {not_found} not in backup stores")
                if recovered > 0 and not args.dry_run:
                    print("  Re-checking recovered files...")
                    file_issues2, _ = verify_files(after, frontend, api)
                    still_missing = len(file_issues2)
                    if still_missing == 0:
                        print("  ✅ All files now reachable!")
                    else:
                        print(f"  ⚠️  {still_missing} file(s) still missing after recovery")
        print(f"{'='*60}")

    # Auto-update golden baseline: merge new content into golden
    golden = load_json(GOLDEN_PATH)
    if golden:
        merged = merge_golden(golden, after)
        save_json(GOLDEN_PATH, merged)
        new_in_golden = len(merged.get("stories", {})) - len(golden.get("stories", {}))
        if new_in_golden > 0:
            print(f"\n  📌 Golden baseline updated: +{new_in_golden} new story/stories added")
    else:
        # First run — create golden from current state
        save_json(GOLDEN_PATH, after)
        print(f"\n  📌 Golden baseline created with {len(after.get('stories', {}))} stories")

    print()


def cmd_check(args):
    """Quick health check without a prior snapshot."""
    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Checking live state from {api}...")
    state = capture_state(api)
    print_state_summary(state, "Live Production State")

    issues = []

    # Check stories without audio
    no_audio = [s for s in state.get("stories", {}).values() if not s.get("has_audio")]
    if no_audio:
        issues.append(f"  ❌ {len(no_audio)} stories without audio")

    # Check stories without covers
    no_cover = [s for s in state.get("stories", {}).values() if not s.get("has_cover")]
    if no_cover:
        issues.append(f"  ❌ {len(no_cover)} stories without covers")

    # Check funny shorts counts (expect 4 per group)
    for age in ["2-5", "6-8", "9-12"]:
        count = len(state.get("funny_shorts", {}).get(age, {}))
        if count != 4:
            issues.append(f"  ⚠️  Funny shorts ({age}): expected 4, got {count}")

    # Check silly songs counts (expect >=1 per group)
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("silly_songs", {}).get(age, {})
        count = len(items)
        if count < 1:
            issues.append(f"  ⚠️  Silly songs ({age}): expected ≥1, got {count}")
        for sid, s in items.items():
            if not s.get("has_audio"):
                issues.append(f"  ❌ Silly song without audio ({age}): {sid}")

    print(f"\n{'='*60}")
    if not issues:
        print("  ✅ All health checks passed.")
    else:
        print(f"  ⚠️  {len(issues)} issue(s) found:")
        print()
        for issue in issues:
            print(issue)
    print(f"{'='*60}")

    # File reachability + auto-recover
    if not args.skip_files:
        file_issues, recoverable = verify_files(state, frontend, api)
        print(f"\n{'='*60}")
        if not file_issues:
            print("  ✅ All files reachable.")
        else:
            print(f"  ⚠️  {len(file_issues)} file(s) missing or broken:")
            print()
            for issue in file_issues:
                print(issue)

            if recoverable and not args.no_recover:
                recovered, not_found = auto_recover(recoverable, dry_run=args.dry_run)
                print(f"\n  Recovery: {recovered} restored, {not_found} not in backup stores")
        print(f"{'='*60}")
        issues.extend(file_issues)

    print()
    if issues:
        sys.exit(1)


def cmd_seal(args):
    """Seal current state as the golden baseline."""
    api = get_api(args.local)
    print(f"Capturing live state from {api}...")
    state = capture_state(api)

    existing = load_json(GOLDEN_PATH)
    if existing:
        merged = merge_golden(existing, state)
        save_json(GOLDEN_PATH, merged)
        print_state_summary(merged, "Golden Baseline (updated)")
        print(f"\n  📌 Golden baseline updated (merged {len(merged.get('stories', {}))} stories)")
    else:
        save_json(GOLDEN_PATH, state)
        print_state_summary(state, "Golden Baseline (new)")
        print(f"\n  📌 Golden baseline created with {len(state.get('stories', {}))} stories")

    print(f"  Saved to: {GOLDEN_PATH}\n")


def cmd_audit(args):
    """Compare current live state against the golden baseline.

    Detects content that existed in golden but is now missing (drift).
    """
    golden = load_json(GOLDEN_PATH)
    if not golden:
        print("❌ No golden baseline. Run 'seal' first to create one.")
        sys.exit(1)

    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Auditing live state against golden baseline...")
    current = capture_state(api)

    print_state_summary(golden, "Golden Baseline")
    print_state_summary(current, "Current Live")

    changes = diff_states(golden, current)

    print(f"\n{'='*60}")
    regressions = [c for c in changes if "❌" in c]
    additions = [c for c in changes if "ADDED" in c and "❌" not in c]

    if not changes:
        print("  ✅ Live state matches golden baseline perfectly.")
    else:
        if additions:
            print(f"  ℹ️  {len(additions)} new item(s) since baseline (will be added to golden):")
            for c in additions:
                print(c)
        if regressions:
            print(f"\n  ❌ {len(regressions)} REGRESSION(S) vs golden baseline:")
            for c in regressions:
                print(c)
            print(f"\n  These items existed in the golden baseline but are now missing or degraded.")
            print(f"  Run 'verify' or 'recover' to attempt auto-recovery.")
    print(f"{'='*60}")

    # File check + auto-recover
    if not args.skip_files:
        file_issues, recoverable = verify_files(current, frontend, api)
        print(f"\n{'='*60}")
        if not file_issues:
            print("  ✅ All files reachable.")
        else:
            print(f"  ⚠️  {len(file_issues)} file(s) missing:")
            for issue in file_issues:
                print(issue)

            if recoverable and not args.no_recover:
                recovered, not_found = auto_recover(recoverable, dry_run=args.dry_run)
                print(f"\n  Recovery: {recovered} restored, {not_found} not in backup stores")
        print(f"{'='*60}")

    # Merge new content into golden
    if additions:
        merged = merge_golden(golden, current)
        save_json(GOLDEN_PATH, merged)
        print(f"\n  📌 Golden baseline updated: +{len(additions)} new item(s)")

    print()


def cmd_recover(args):
    """Recover missing files without running a full verify."""
    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Checking file reachability from {frontend}...")
    state = capture_state(api)
    file_issues, recoverable = verify_files(state, frontend, api)

    if not file_issues:
        print(f"\n  ✅ All files reachable. Nothing to recover.\n")
        return

    print(f"\n  {len(file_issues)} file(s) missing. Attempting recovery...")
    recovered, not_found = auto_recover(recoverable, dry_run=args.dry_run)
    print(f"\n  Recovery complete: {recovered} restored, {not_found} not in backup stores\n")


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Guard v2 — protect production state during deploys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  snapshot   Capture pre-deploy state (run BEFORE deploying)
  verify     Compare against snapshot + auto-recover (run AFTER deploying)
  check      Quick health check (no snapshot needed)
  seal       Save current state as golden baseline
  audit      Compare live state against golden baseline
  recover    Recover missing files from backup stores

Examples:
  python3 scripts/deploy_guard.py snapshot
  python3 scripts/deploy_guard.py verify
  python3 scripts/deploy_guard.py check
  python3 scripts/deploy_guard.py seal
  python3 scripts/deploy_guard.py audit
  python3 scripts/deploy_guard.py recover --dry-run
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Common args
    def add_common(p):
        p.add_argument("--local", action="store_true", help="Use localhost instead of production")
        p.add_argument("--skip-files", action="store_true", help="Skip file reachability checks")
        p.add_argument("--no-recover", action="store_true", help="Disable auto-recovery")
        p.add_argument("--dry-run", action="store_true", help="Show what recovery would do without doing it")

    snap = sub.add_parser("snapshot", help="Capture pre-deploy state")
    snap.add_argument("--local", action="store_true")
    snap.set_defaults(func=cmd_snapshot)

    ver = sub.add_parser("verify", help="Compare against snapshot + auto-recover")
    add_common(ver)
    ver.set_defaults(func=cmd_verify)

    chk = sub.add_parser("check", help="Quick health check")
    add_common(chk)
    chk.set_defaults(func=cmd_check)

    seal = sub.add_parser("seal", help="Save current state as golden baseline")
    seal.add_argument("--local", action="store_true")
    seal.set_defaults(func=cmd_seal)

    audit = sub.add_parser("audit", help="Compare live vs golden baseline")
    add_common(audit)
    audit.set_defaults(func=cmd_audit)

    rec = sub.add_parser("recover", help="Recover missing files from backup stores")
    rec.add_argument("--local", action="store_true")
    rec.add_argument("--dry-run", action="store_true", help="Show what would be recovered")
    rec.set_defaults(func=cmd_recover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
