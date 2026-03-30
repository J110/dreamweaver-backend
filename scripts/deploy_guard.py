#!/usr/bin/env python3
"""
Deploy Guard — snapshot production state before deploy, verify after.

Ensures only intended changes happen during any deploy/rebuild.
Catches: Hindi stories reappearing, content going missing, audio_file nulls,
extra items sneaking in, items accidentally removed.

Usage:
    # BEFORE deploy: capture current production state
    python3 scripts/deploy_guard.py snapshot

    # AFTER deploy: verify only intended changes happened
    python3 scripts/deploy_guard.py verify

    # Quick check without a prior snapshot (just validates consistency)
    python3 scripts/deploy_guard.py check

The snapshot is saved to data/deploy_snapshot.json.
Run 'snapshot' before ANY deploy (git pull, docker rebuild, admin reload).
Run 'verify' after deploy completes. It will flag every unintended change.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = BASE_DIR / "data" / "deploy_snapshot.json"

# Production API
PROD_API = "https://api.dreamvalley.app"
# Local API (for local testing)
LOCAL_API = "http://localhost:8000"

# Frontend (nginx serves /covers/ and /audio/)
PROD_FRONTEND = "https://dreamvalley.app"
LOCAL_FRONTEND = "http://localhost:3000"


def get_api(use_local: bool = False) -> str:
    return LOCAL_API if use_local else PROD_API


def get_frontend(use_local: bool = False) -> str:
    return LOCAL_FRONTEND if use_local else PROD_FRONTEND


def capture_state(api: str) -> dict:
    """Capture full production state from API."""
    client = httpx.Client(timeout=30)
    state = {
        "captured_at": datetime.now().isoformat(),
        "api": api,
    }

    # 1. Stories (paginate — API max page_size=100)
    try:
        all_items = []
        page = 1
        while True:
            resp = client.get(f"{api}/api/v1/content", params={"page_size": 100, "page": page})
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
            audio_urls = []
            for av in (item.get("audio_variants") or []):
                if av.get("url"):
                    audio_urls.append(av["url"])
            cover_url = item.get("cover", "")
            stories.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "lang": item.get("lang", "en"),
                "type": item.get("type"),
                "has_audio": bool(audio_urls),
                "has_cover": bool(cover_url and cover_url != "/covers/default.svg"),
                "audio_urls": audio_urls,
                "cover_url": cover_url if cover_url != "/covers/default.svg" else "",
                "mood": item.get("mood"),
            })
        state["stories"] = {s["id"]: s for s in stories}
        state["story_count"] = len(stories)
        state["story_langs"] = sorted(set(s["lang"] for s in stories))
    except Exception as e:
        state["stories"] = {}
        state["story_count"] = 0
        state["stories_error"] = str(e)

    # 2. Funny shorts (per age group)
    state["funny_shorts"] = {}
    state["funny_shorts_count"] = {}
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
            state["funny_shorts_count"][age] = len(items)
        except Exception as e:
            state["funny_shorts"][age] = {}
            state["funny_shorts_count"][age] = 0

    # 3. Silly songs (per age group)
    state["silly_songs"] = {}
    state["silly_songs_count"] = {}
    for age in ["2-5", "6-8", "9-12"]:
        try:
            resp = client.get(f"{api}/api/v1/silly-songs", params={"age_group": age})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            state["silly_songs"][age] = {
                item["id"]: {
                    "title": item.get("title"),
                    "has_audio": bool(item.get("audio_file")),
                    "audio_url": f"/audio/silly-songs/{item.get('audio_file', '')}" if item.get("audio_file") else "",
                    "cover_url": f"/covers/silly-songs/{item.get('cover_file', '')}" if item.get("cover_file") else "",
                }
                for item in items
            }
            state["silly_songs_count"][age] = len(items)
        except Exception as e:
            state["silly_songs"][age] = {}
            state["silly_songs_count"][age] = 0

    return state


def verify_files(state: dict, frontend: str) -> list[str]:
    """HEAD-check all audio and cover URLs to verify they're actually reachable.

    Returns list of issues found (empty = all good).
    """
    issues = []
    urls_to_check = []  # (url_path, label)

    # Stories
    for sid, s in state.get("stories", {}).items():
        for url in s.get("audio_urls", []):
            if url:
                urls_to_check.append((url, f"story audio: {sid}"))
        if s.get("cover_url"):
            urls_to_check.append((s["cover_url"], f"story cover: {sid}"))

    # Funny shorts
    for age, items in state.get("funny_shorts", {}).items():
        for fid, f in items.items():
            if f.get("audio_url"):
                urls_to_check.append((f["audio_url"], f"funny short audio ({age}): {fid}"))
            if f.get("cover_url"):
                urls_to_check.append((f["cover_url"], f"funny short cover ({age}): {fid}"))

    # Silly songs
    for age, items in state.get("silly_songs", {}).items():
        for sid, s in items.items():
            if s.get("audio_url"):
                urls_to_check.append((s["audio_url"], f"silly song audio ({age}): {sid}"))
            if s.get("cover_url"):
                urls_to_check.append((s["cover_url"], f"silly song cover ({age}): {sid}"))

    if not urls_to_check:
        return issues

    print(f"\n  Checking {len(urls_to_check)} file URLs via HEAD requests...")

    ok = 0
    failed = 0
    client = httpx.Client(timeout=10, follow_redirects=True)
    for url_path, label in urls_to_check:
        full_url = f"{frontend}{url_path}"
        try:
            resp = client.head(full_url)
            if resp.status_code == 200:
                ok += 1
            else:
                failed += 1
                issues.append(f"  MISSING FILE ({resp.status_code}): {url_path} — {label}")
        except Exception as e:
            failed += 1
            issues.append(f"  UNREACHABLE: {url_path} — {label} ({e})")

    print(f"  Results: {ok} reachable, {failed} missing/broken")

    return issues


def save_snapshot(state: dict):
    """Save state snapshot to disk."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(state, indent=2))


def load_snapshot() -> dict:
    """Load previous snapshot."""
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text())


def diff_states(before: dict, after: dict) -> list[str]:
    """Compare two states and return list of changes."""
    changes = []

    # Stories
    before_ids = set(before.get("stories", {}).keys())
    after_ids = set(after.get("stories", {}).keys())

    added = after_ids - before_ids
    removed = before_ids - after_ids

    if added:
        for sid in sorted(added):
            s = after["stories"][sid]
            changes.append(f"  ADDED story: {sid} — \"{s['title']}\" (lang={s['lang']})")

    if removed:
        for sid in sorted(removed):
            s = before["stories"][sid]
            changes.append(f"  REMOVED story: {sid} — \"{s['title']}\"")

    # Check for stories that lost audio or cover
    for sid in before_ids & after_ids:
        b, a = before["stories"][sid], after["stories"][sid]
        if b.get("has_audio") and not a.get("has_audio"):
            changes.append(f"  LOST AUDIO: {sid} — \"{a['title']}\"")
        if b.get("has_cover") and not a.get("has_cover"):
            changes.append(f"  LOST COVER: {sid} — \"{a['title']}\"")

    # Language check
    before_langs = set(before.get("story_langs", ["en"]))
    after_langs = set(after.get("story_langs", ["en"]))
    new_langs = after_langs - before_langs
    if new_langs:
        changes.append(f"  NEW LANGUAGES appeared: {new_langs}")

    # Funny shorts per age group
    for age in ["2-5", "6-8", "9-12"]:
        before_fs = set(before.get("funny_shorts", {}).get(age, {}).keys())
        after_fs = set(after.get("funny_shorts", {}).get(age, {}).keys())
        added_fs = after_fs - before_fs
        removed_fs = before_fs - after_fs
        if added_fs:
            for fid in sorted(added_fs):
                changes.append(f"  ADDED funny short ({age}): {fid}")
        if removed_fs:
            for fid in sorted(removed_fs):
                changes.append(f"  REMOVED funny short ({age}): {fid}")

    # Silly songs per age group
    for age in ["2-5", "6-8", "9-12"]:
        before_ss = set(before.get("silly_songs", {}).get(age, {}).keys())
        after_ss = set(after.get("silly_songs", {}).get(age, {}).keys())
        added_ss = after_ss - before_ss
        removed_ss = before_ss - after_ss
        if added_ss:
            for sid in sorted(added_ss):
                changes.append(f"  ADDED silly song ({age}): {sid}")
        if removed_ss:
            for sid in sorted(removed_ss):
                changes.append(f"  REMOVED silly song ({age}): {sid}")

        # Check audio loss
        for sid in before_ss & after_ss:
            b = before["silly_songs"][age][sid]
            a = after["silly_songs"][age][sid]
            if b.get("has_audio") and not a.get("has_audio"):
                changes.append(f"  LOST AUDIO silly song ({age}): {sid}")

    return changes


def print_state_summary(state: dict, label: str = "Current"):
    """Print a compact summary of state."""
    stories = state.get("stories", {})
    en_stories = [s for s in stories.values() if s.get("lang", "en") == "en"]
    hi_stories = [s for s in stories.values() if s.get("lang") == "hi"]

    print(f"\n{'='*60}")
    print(f"  {label} Production State")
    print(f"  Captured: {state.get('captured_at', '?')}")
    print(f"{'='*60}")

    # ── Stories Tab ──
    print(f"\n  STORIES TAB")
    print(f"    Total: {len(en_stories)} English stories")
    with_audio = sum(1 for s in en_stories if s.get("has_audio"))
    with_cover = sum(1 for s in en_stories if s.get("has_cover"))
    no_audio = len(en_stories) - with_audio
    no_cover = len(en_stories) - with_cover
    print(f"    Audio: {with_audio} with audio{f', {no_audio} WITHOUT' if no_audio else ''}")
    print(f"    Covers: {with_cover} with covers{f', {no_cover} WITHOUT' if no_cover else ''}")
    if hi_stories:
        print(f"    ⚠️  Hindi stories present: {len(hi_stories)} (should be 0)")

    # ── Before Bed Tab ──
    print(f"\n  BEFORE BED TAB")
    print(f"    Funny Shorts:")
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("funny_shorts", {}).get(age, {})
        count = len(items)
        with_audio = sum(1 for d in items.values() if d.get("has_audio"))
        print(f"      {age}: {count} shorts, {with_audio} with audio")

    print(f"    Silly Songs:")
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("silly_songs", {}).get(age, {})
        count = len(items)
        with_audio = sum(1 for d in items.values() if d.get("has_audio"))
        no_audio_list = [s for s, d in items.items() if not d.get("has_audio")]
        suffix = f" (⚠️  no audio: {', '.join(no_audio_list)})" if no_audio_list else ""
        print(f"      {age}: {count} songs, {with_audio} with audio{suffix}")


def cmd_snapshot(args):
    """Capture and save production state."""
    api = get_api(args.local)
    print(f"Capturing production state from {api}...")
    state = capture_state(api)
    save_snapshot(state)
    print_state_summary(state, "Snapshot Saved")
    print(f"\n  Saved to: {SNAPSHOT_PATH}")
    print(f"\n  ✅ Run your deploy now, then run: python3 scripts/deploy_guard.py verify\n")


def cmd_verify(args):
    """Compare current state against saved snapshot."""
    before = load_snapshot()
    if not before:
        print("❌ No snapshot found. Run 'snapshot' before deploying.")
        sys.exit(1)

    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Capturing current state from {api}...")
    after = capture_state(api)

    print_state_summary(before, "BEFORE (snapshot)")
    print_state_summary(after, "AFTER (current)")

    changes = diff_states(before, after)

    print(f"\n{'='*60}")
    if not changes:
        print("  ✅ NO CHANGES detected. Production state is identical.")
    else:
        print(f"  ⚠️  {len(changes)} CHANGE(S) DETECTED:")
        print()
        for c in changes:
            print(c)
    print(f"{'='*60}")

    # File reachability check
    if not args.skip_files:
        file_issues = verify_files(after, frontend)
        print(f"\n{'='*60}")
        if not file_issues:
            print("  ✅ All audio & cover files are reachable.")
        else:
            print(f"  ⚠️  {len(file_issues)} FILE(S) MISSING OR BROKEN:")
            print()
            for issue in file_issues:
                print(issue)
        print(f"{'='*60}")

    if changes:
        print("\n  Review the changes above.")
        print("  If any are UNINTENDED, roll back before users are affected.")
        print("  If all are intended, you're good. ✅\n")
    else:
        print()


def cmd_check(args):
    """Quick consistency check without a prior snapshot."""
    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Checking production state from {api}...")
    state = capture_state(api)
    print_state_summary(state, "Current")

    issues = []

    # Check for Hindi stories
    for sid, s in state.get("stories", {}).items():
        if s.get("lang") == "hi":
            issues.append(f"  Hindi story present: {sid} — \"{s['title']}\"")

    # Check funny shorts counts (expect 4 per group — properly mixed ones only)
    for age in ["2-5", "6-8", "9-12"]:
        count = state.get("funny_shorts_count", {}).get(age, 0)
        if count != 4:
            issues.append(f"  Funny shorts ({age}): expected 4, got {count}")

    # Check silly songs counts (expect 1 per group)
    for age in ["2-5", "6-8", "9-12"]:
        count = state.get("silly_songs_count", {}).get(age, 0)
        if count != 1:
            issues.append(f"  Silly songs ({age}): expected 1, got {count}")

    # Check silly songs have audio
    for age in ["2-5", "6-8", "9-12"]:
        for sid, s in state.get("silly_songs", {}).get(age, {}).items():
            if not s.get("has_audio"):
                issues.append(f"  Silly song without audio ({age}): {sid}")

    # Check stories without audio
    no_audio = [s for s in state.get("stories", {}).values() if not s.get("has_audio")]
    if no_audio:
        issues.append(f"  {len(no_audio)} stories without audio")

    print(f"\n{'='*60}")
    if not issues:
        print("  ✅ All consistency checks passed.")
    else:
        print(f"  ⚠️  {len(issues)} ISSUE(S) FOUND:")
        print()
        for issue in issues:
            print(issue)
    print(f"{'='*60}")

    # File reachability check
    if not args.skip_files:
        file_issues = verify_files(state, frontend)
        print(f"\n{'='*60}")
        if not file_issues:
            print("  ✅ All audio & cover files are reachable.")
        else:
            print(f"  ⚠️  {len(file_issues)} FILE(S) MISSING OR BROKEN:")
            print()
            for issue in file_issues:
                print(issue)
        print(f"{'='*60}")
        issues.extend(file_issues)

    print()

    if issues:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Guard — protect production state during deploys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Before deploy:  python3 scripts/deploy_guard.py snapshot
  After deploy:   python3 scripts/deploy_guard.py verify
  Quick check:    python3 scripts/deploy_guard.py check
  Local testing:  python3 scripts/deploy_guard.py check --local
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Capture current production state")
    snap.add_argument("--local", action="store_true", help="Use localhost instead of production")
    snap.set_defaults(func=cmd_snapshot)

    ver = sub.add_parser("verify", help="Compare current state against snapshot")
    ver.add_argument("--local", action="store_true", help="Use localhost instead of production")
    ver.add_argument("--skip-files", action="store_true", help="Skip HEAD checks on audio/cover files")
    ver.set_defaults(func=cmd_verify)

    chk = sub.add_parser("check", help="Quick consistency check (no snapshot needed)")
    chk.add_argument("--local", action="store_true", help="Use localhost instead of production")
    chk.add_argument("--skip-files", action="store_true", help="Skip HEAD checks on audio/cover files")
    chk.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
