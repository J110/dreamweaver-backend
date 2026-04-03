#!/usr/bin/env python3
"""
Deploy Guard v3 — protect production state before, during, and after deploys.

Features:
  1. Persistent golden snapshot — baseline of known-good state that survives
     across deploys. New content is merged in; nothing is lost.
  2. Pre/post deploy diffing — catches unintended regressions.
  3. English-only reporting — Hindi stories are excluded from all counts,
     diffs, and file checks (they're invisible to users).
  4. Auto-recovery — missing files are restored from backup stores
     (/opt/cover-store, /opt/audio-store) automatically.
  5. JSON data file protection — backs up and restores JSON data files
     (silly_songs/*.json, funny_shorts/*.json) so accidental deletions
     are auto-recovered from /opt/json-store/.
  6. Golden baseline enforcement — verify compares against golden, not just
     snapshot. Items in golden that disappear are auto-recovered.
  7. New item serving check — for each ADDED item, verifies audio + cover
     URLs are reachable before declaring the deploy successful.
  8. Change tracking — detects and reports updated items (same ID, different
     content), not just additions and removals.

Usage:
    # BEFORE deploy: capture current live state + back up JSON data files
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
import os
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
# Try to find gcloud in common locations
_GCLOUD = "gcloud"
for _path in ["/opt/homebrew/bin/gcloud", "/usr/local/bin/gcloud", "/usr/bin/gcloud"]:
    if os.path.exists(_path):
        _GCLOUD = _path
        break

SSH_CMD = [_GCLOUD, "compute", "ssh", "dreamvalley-prod",
           "--project=strong-harbor-472607-n4", "--zone=asia-south1-a",
           "--command"]

# Backup stores on the GCP VM
COVER_STORE = "/opt/cover-store"
AUDIO_STORE_PREGEN = "/opt/audio-store/pre-gen"
AUDIO_STORE_SILLY = "/opt/audio-store/silly-songs"
JSON_STORE = "/opt/json-store"  # JSON data file backups

# Serve paths on the GCP VM
FRONTEND_COVERS = "/opt/dreamweaver-web/public/covers"
FRONTEND_AUDIO = "/opt/dreamweaver-web/public/audio/pre-gen"
BACKEND_COVERS_FUNNY = "/opt/dreamweaver-backend/public/covers/funny-shorts"
BACKEND_COVERS_SILLY = "/opt/dreamweaver-backend/public/covers/silly-songs"
BACKEND_AUDIO_SILLY = "/opt/dreamweaver-backend/public/audio/silly-songs"
BACKEND_AUDIO_POEMS = "/opt/dreamweaver-backend/public/audio/poems"
BACKEND_COVERS_POEMS = "/opt/dreamweaver-backend/public/covers/poems"
BACKEND_DATA_SILLY = "/opt/dreamweaver-backend/data/silly_songs"
BACKEND_DATA_FUNNY = "/opt/dreamweaver-backend/data/funny_shorts"
BACKEND_DATA_POEMS = "/opt/dreamweaver-backend/data/poems"


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
            if item.get("type") == "poem":
                continue  # Poem content type removed — skip to prevent accidental restoration
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

    # 4. Poems (per age group)
    state["poems"] = {}
    for age in ["2-5", "6-8", "9-12"]:
        try:
            resp = client.get(f"{api}/api/v1/poems", params={"age_group": age})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            state["poems"][age] = {
                item["id"]: {
                    "title": item.get("title"),
                    "has_audio": bool(item.get("audio_file")),
                    "audio_url": f"/audio/poems/{item['audio_file']}" if item.get("audio_file") else "",
                    "cover_url": f"/covers/poems/{item['cover_file']}" if item.get("cover_file") else "",
                }
                for item in items
            }
        except Exception:
            state["poems"][age] = {}

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

    # Poems — audio served by backend API, covers by frontend nginx
    for age, items in state.get("poems", {}).items():
        for pid, p in items.items():
            if p.get("audio_url"):
                filename = p["audio_url"].split("/")[-1]
                urls_to_check.append((api, p["audio_url"], f"poem audio ({age}): {pid}",
                                      {"type": "poem_audio", "url_path": p["audio_url"], "filename": filename}))
            if p.get("cover_url"):
                filename = p["cover_url"].split("/")[-1]
                urls_to_check.append((frontend, p["cover_url"], f"poem cover ({age}): {pid}",
                                      {"type": "poem_cover", "url_path": p["cover_url"], "filename": filename}))

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

    Recovery chain (tries each in order):
      1. Backup store (/opt/cover-store, /opt/audio-store)
      2. git restore (for files tracked in git that were deleted from disk)

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
            recover_commands.append(
                f'if [ -f "{COVER_STORE}/{filename}" ]; then '
                f'cp "{COVER_STORE}/{filename}" "{FRONTEND_COVERS}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "funny_short_cover":
            # Funny short covers: store uses "funny-shorts--{name}" naming
            store_name = f"funny-shorts--{filename}"
            recover_commands.append(
                f'if [ -f "{COVER_STORE}/{store_name}" ]; then '
                f'cp "{COVER_STORE}/{store_name}" "{BACKEND_COVERS_FUNNY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'elif [ -f "{COVER_STORE}/{filename}" ]; then '
                f'cp "{COVER_STORE}/{filename}" "{BACKEND_COVERS_FUNNY}/{filename}" && echo "RECOVERED: {filename}"; '
                f'else echo "NOT_IN_STORE: {filename}"; fi'
            )
        elif ftype == "funny_short_audio":
            # Funny short audio: no dedicated store, will fall through to git restore
            recover_commands.append(f'echo "NOT_IN_STORE: {filename}"')
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
        elif ftype == "poem_audio":
            # Poem audio: no dedicated store, will fall through to git restore
            recover_commands.append(f'echo "NOT_IN_STORE: {filename}"')
        elif ftype == "poem_cover":
            # Poem covers: no dedicated store, will fall through to git restore
            recover_commands.append(f'echo "NOT_IN_STORE: {filename}"')

    if not recover_commands:
        return 0, 0

    if dry_run:
        for cmd in recover_commands:
            print(f"    Would run: {cmd[:100]}...")
        return 0, 0

    # Phase 1: Try backup stores
    full_script = " && ".join(recover_commands)
    recovered = 0
    not_found = 0
    not_found_files = []  # Track which files need git restore

    try:
        result = subprocess.run(
            SSH_CMD + [full_script],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout.strip()
        if output:
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("RECOVERED:"):
                    recovered += 1
                    print(f"    ✅ {line}")
                elif line.startswith("NOT_IN_STORE:"):
                    not_found += 1
                    fname = line.split("NOT_IN_STORE:")[-1].strip()
                    not_found_files.append(fname)
                    print(f"    ⚠️  {line} — will try git restore")
        if result.returncode != 0 and result.stderr:
            print(f"    SSH error: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("    SSH timed out during recovery")
    except Exception as e:
        print(f"    Recovery error: {e}")

    # Phase 2: git restore for files not in backup stores
    if not_found_files:
        print(f"\n  Attempting git restore for {len(not_found_files)} file(s)...")
        git_recovered = _git_restore_recover(not_found_files, recoverable)
        recovered += git_recovered
        not_found -= git_recovered

    # Phase 3: Back up any recovered files to the store for next time
    if recovered > 0:
        _backup_to_store(recoverable)

    return recovered, not_found


def _git_restore_recover(filenames: list[str], recoverable: list[dict]) -> int:
    """Try git restore on the backend and frontend repos for missing files.

    Files tracked in git that were deleted from disk can be restored this way.
    Returns count of successfully recovered files.
    """
    # Map filenames to their recovery info for determining which repo to restore from
    file_types = {}
    for item in recoverable:
        file_types[item["filename"]] = item["type"]

    # Group by repo
    backend_paths = []
    frontend_paths = []
    for fname in filenames:
        ftype = file_types.get(fname, "")
        if ftype in ("funny_short_cover", "funny_short_audio", "silly_song_cover", "silly_song_audio",
                     "poem_cover", "poem_audio"):
            # These are in the backend repo
            if "cover" in ftype:
                if "funny" in ftype:
                    subdir = "funny-shorts"
                elif "silly" in ftype:
                    subdir = "silly-songs"
                else:
                    subdir = "poems"
                backend_paths.append(f"public/covers/{subdir}/{fname}")
            else:
                if "funny" in ftype:
                    subdir = "funny-shorts"
                elif "silly" in ftype:
                    subdir = "silly-songs"
                else:
                    subdir = "poems"
                backend_paths.append(f"public/audio/{subdir}/{fname}")
        elif ftype in ("story_audio",):
            frontend_paths.append(f"public/audio/pre-gen/{fname}")
        elif ftype in ("story_cover",):
            frontend_paths.append(f"public/covers/{fname}")

    git_recovered = 0

    # Restore from backend repo
    if backend_paths:
        paths_str = " ".join(f'"{p}"' for p in backend_paths)
        cmd = f'cd /opt/dreamweaver-backend && git restore {paths_str} 2>&1 && echo "GIT_RESTORE_OK"'
        try:
            result = subprocess.run(
                SSH_CMD + [cmd], capture_output=True, text=True, timeout=60
            )
            if "GIT_RESTORE_OK" in result.stdout:
                # Verify which files were actually restored
                for path in backend_paths:
                    check_cmd = f'[ -f "/opt/dreamweaver-backend/{path}" ] && echo "EXISTS"'
                    check = subprocess.run(
                        SSH_CMD + [check_cmd], capture_output=True, text=True, timeout=15
                    )
                    if "EXISTS" in check.stdout:
                        git_recovered += 1
                        fname = path.split("/")[-1]
                        print(f"    ✅ RECOVERED (git restore): {fname}")
            elif result.stderr:
                print(f"    git restore (backend) error: {result.stderr[:200]}")
        except Exception as e:
            print(f"    git restore (backend) failed: {e}")

    # Restore from frontend repo
    if frontend_paths:
        paths_str = " ".join(f'"{p}"' for p in frontend_paths)
        cmd = f'cd /opt/dreamweaver-web && git restore {paths_str} 2>&1 && echo "GIT_RESTORE_OK"'
        try:
            result = subprocess.run(
                SSH_CMD + [cmd], capture_output=True, text=True, timeout=60
            )
            if "GIT_RESTORE_OK" in result.stdout:
                for path in frontend_paths:
                    check_cmd = f'[ -f "/opt/dreamweaver-web/{path}" ] && echo "EXISTS"'
                    check = subprocess.run(
                        SSH_CMD + [check_cmd], capture_output=True, text=True, timeout=15
                    )
                    if "EXISTS" in check.stdout:
                        git_recovered += 1
                        fname = path.split("/")[-1]
                        print(f"    ✅ RECOVERED (git restore): {fname}")
            elif result.stderr:
                print(f"    git restore (frontend) error: {result.stderr[:200]}")
        except Exception as e:
            print(f"    git restore (frontend) failed: {e}")

    return git_recovered


def _backup_to_store(recoverable: list[dict]):
    """After recovery, back up restored files to the backup store so they're available next time."""
    backup_cmds = []
    for item in recoverable:
        ftype = item["type"]
        filename = item["filename"]

        if ftype == "story_cover":
            backup_cmds.append(
                f'[ -f "{FRONTEND_COVERS}/{filename}" ] && '
                f'cp "{FRONTEND_COVERS}/{filename}" "{COVER_STORE}/{filename}" 2>/dev/null'
            )
        elif ftype == "funny_short_cover":
            store_name = f"funny-shorts--{filename}"
            backup_cmds.append(
                f'[ -f "{BACKEND_COVERS_FUNNY}/{filename}" ] && '
                f'cp "{BACKEND_COVERS_FUNNY}/{filename}" "{COVER_STORE}/{store_name}" 2>/dev/null'
            )
        elif ftype == "silly_song_cover":
            store_name = f"silly-songs--{filename}"
            backup_cmds.append(
                f'[ -f "{BACKEND_COVERS_SILLY}/{filename}" ] && '
                f'cp "{BACKEND_COVERS_SILLY}/{filename}" "{COVER_STORE}/{store_name}" 2>/dev/null'
            )
        elif ftype == "story_audio":
            backup_cmds.append(
                f'[ -f "{FRONTEND_AUDIO}/{filename}" ] && '
                f'cp "{FRONTEND_AUDIO}/{filename}" "{AUDIO_STORE_PREGEN}/{filename}" 2>/dev/null'
            )
        elif ftype == "silly_song_audio":
            backup_cmds.append(
                f'[ -f "{BACKEND_AUDIO_SILLY}/{filename}" ] && '
                f'cp "{BACKEND_AUDIO_SILLY}/{filename}" "{AUDIO_STORE_SILLY}/{filename}" 2>/dev/null'
            )
        # Poems: no dedicated store yet — rely on git restore

    if backup_cmds:
        script = " ; ".join(backup_cmds)
        try:
            subprocess.run(SSH_CMD + [script], capture_output=True, text=True, timeout=60)
        except Exception:
            pass  # Best-effort — don't fail recovery over backup


def backup_json_files():
    """Back up all JSON data files (silly_songs, funny_shorts) to /opt/json-store/.

    Called during snapshot to ensure we have a copy of every JSON before deploy.
    """
    cmds = [
        f'mkdir -p "{JSON_STORE}/silly_songs" "{JSON_STORE}/funny_shorts" "{JSON_STORE}/poems"',
        f'cp -f {BACKEND_DATA_SILLY}/*.json "{JSON_STORE}/silly_songs/" 2>/dev/null; true',
        f'cp -f {BACKEND_DATA_FUNNY}/*.json "{JSON_STORE}/funny_shorts/" 2>/dev/null; true',
        f'cp -f {BACKEND_DATA_POEMS}/*.json "{JSON_STORE}/poems/" 2>/dev/null; true',
        'echo "JSON_BACKUP_OK"',
    ]
    script = " && ".join(cmds)
    try:
        result = subprocess.run(
            SSH_CMD + [script], capture_output=True, text=True, timeout=30
        )
        if "JSON_BACKUP_OK" in result.stdout:
            # Count backed-up files
            count_cmd = (
                f'ls "{JSON_STORE}/silly_songs/"*.json 2>/dev/null | wc -l; '
                f'ls "{JSON_STORE}/funny_shorts/"*.json 2>/dev/null | wc -l; '
                f'ls "{JSON_STORE}/poems/"*.json 2>/dev/null | wc -l'
            )
            count_result = subprocess.run(
                SSH_CMD + [count_cmd], capture_output=True, text=True, timeout=15
            )
            counts = count_result.stdout.strip().split("\n")
            silly = int(counts[0].strip()) if counts else 0
            funny = int(counts[1].strip()) if len(counts) > 1 else 0
            poems_count = int(counts[2].strip()) if len(counts) > 2 else 0
            print(f"  📦 JSON backup: {silly} silly songs, {funny} funny shorts, {poems_count} poems → {JSON_STORE}/")
            return True
        else:
            print(f"  ⚠️  JSON backup may have failed: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"  ⚠️  JSON backup error: {e}")
        return False


def recover_json_files(missing_items: list[dict]) -> tuple[int, int]:
    """Restore missing JSON data files from /opt/json-store/.

    Each item in missing_items should have:
      category: 'silly_songs' | 'funny_shorts'
      item_id: the ID of the item
      age_group: the age group (for logging)

    Returns (recovered_count, failed_count).
    """
    if not missing_items:
        return 0, 0

    print(f"\n  🔧 Recovering {len(missing_items)} missing JSON data file(s)...")

    recover_cmds = []
    for item in missing_items:
        cat = item["category"]
        item_id = item["item_id"]
        store_dir = f"{JSON_STORE}/{cat}"
        if cat == "silly_songs":
            data_dir = BACKEND_DATA_SILLY
        elif cat == "funny_shorts":
            data_dir = BACKEND_DATA_FUNNY
        else:
            data_dir = BACKEND_DATA_POEMS

        # Try exact match first, then glob for ID prefix
        recover_cmds.append(
            f'if [ -f "{store_dir}/{item_id}.json" ]; then '
            f'cp "{store_dir}/{item_id}.json" "{data_dir}/{item_id}.json" && echo "RECOVERED_JSON:{item_id}"; '
            f'else echo "NO_BACKUP:{item_id}"; fi'
        )

    script = " && ".join(recover_cmds)
    recovered = 0
    failed = 0

    try:
        result = subprocess.run(
            SSH_CMD + [script], capture_output=True, text=True, timeout=60
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("RECOVERED_JSON:"):
                recovered += 1
                item_id = line.split(":")[-1]
                print(f"    ✅ Restored JSON: {item_id}.json")
            elif line.startswith("NO_BACKUP:"):
                failed += 1
                item_id = line.split(":")[-1]
                print(f"    ❌ No backup found: {item_id}.json")
    except Exception as e:
        print(f"    Recovery error: {e}")
        failed = len(missing_items)

    return recovered, failed


def verify_new_items_serving(added_items: list[dict], frontend: str, api: str) -> list[str]:
    """For each newly added item, verify its audio and cover URLs are reachable.

    Each item in added_items should have:
      category: 'story' | 'funny_short' | 'silly_song'
      item_id: the ID
      age_group: (for funny_shorts/silly_songs)
      audio_url: URL path to check
      cover_url: URL path to check

    Returns list of issues found.
    """
    if not added_items:
        return []

    print(f"\n  🔍 Verifying {len(added_items)} new item(s) are fully serving...")

    issues = []
    client = httpx.Client(timeout=10, follow_redirects=True)

    for item in added_items:
        cat = item["category"]
        item_id = item["item_id"]
        label = f"{cat} ({item.get('age_group', '')}): {item_id}" if item.get("age_group") else f"{cat}: {item_id}"

        # Determine base URL based on category
        audio_base = api if cat in ("funny_short", "silly_song", "poem") else frontend
        cover_base = frontend

        # Check audio
        audio_url = item.get("audio_url", "")
        if audio_url:
            full = f"{audio_base}{audio_url}"
            try:
                resp = client.head(full)
                if resp.status_code == 200:
                    print(f"    ✅ {label} — audio serving")
                else:
                    issues.append(f"  ❌ NEW {label} — audio NOT serving ({resp.status_code}): {audio_url}")
            except Exception as e:
                issues.append(f"  ❌ NEW {label} — audio unreachable: {audio_url} ({e})")
        else:
            issues.append(f"  ⚠️  NEW {label} — no audio URL")

        # Check cover
        cover_url = item.get("cover_url", "")
        if cover_url:
            full = f"{cover_base}{cover_url}"
            try:
                resp = client.head(full)
                if resp.status_code == 200:
                    print(f"    ✅ {label} — cover serving")
                else:
                    issues.append(f"  ❌ NEW {label} — cover NOT serving ({resp.status_code}): {cover_url}")
            except Exception as e:
                issues.append(f"  ❌ NEW {label} — cover unreachable: {cover_url} ({e})")

    return issues


def diff_states(before: dict, after: dict) -> dict:
    """Compare two states and return structured change report.

    Returns dict with keys:
      added: list of change strings (new items)
      removed: list of change strings (missing items, regressions)
      updated: list of change strings (same ID, content changed)
      degraded: list of change strings (lost audio/cover)
      removed_items: list of dicts for auto-recovery {category, item_id, age_group}
      added_items: list of dicts for serving check {category, item_id, age_group, audio_url, cover_url}
    """
    added = []
    removed = []
    updated = []
    degraded = []
    removed_items = []  # For JSON recovery
    added_items = []    # For serving verification

    # ── Stories ──
    before_ids = set(before.get("stories", {}).keys())
    after_ids = set(after.get("stories", {}).keys())

    for sid in sorted(after_ids - before_ids):
        s = after["stories"][sid]
        added.append(f"  ADDED story: {sid} — \"{s['title']}\"")
        added_items.append({
            "category": "story", "item_id": sid,
            "audio_url": (s.get("audio_urls") or [""])[0],
            "cover_url": s.get("cover_url", ""),
        })

    for sid in sorted(before_ids - after_ids):
        s = before["stories"][sid]
        removed.append(f"  ❌ REMOVED story: {sid} — \"{s['title']}\"")

    for sid in before_ids & after_ids:
        b, a = before["stories"][sid], after["stories"][sid]
        if b.get("has_audio") and not a.get("has_audio"):
            degraded.append(f"  ❌ LOST AUDIO: {sid} — \"{a['title']}\"")
        if b.get("has_cover") and not a.get("has_cover"):
            degraded.append(f"  ❌ LOST COVER: {sid} — \"{a['title']}\"")
        # Detect title changes (content update)
        if b.get("title") != a.get("title"):
            updated.append(f"  ✏️  UPDATED story: {sid} — title \"{b['title']}\" → \"{a['title']}\"")

    # ── Funny shorts per age group ──
    for age in ["2-5", "6-8", "9-12"]:
        before_fs = set(before.get("funny_shorts", {}).get(age, {}).keys())
        after_fs = set(after.get("funny_shorts", {}).get(age, {}).keys())

        for fid in sorted(after_fs - before_fs):
            f = after["funny_shorts"][age][fid]
            added.append(f"  ADDED funny short ({age}): {fid}")
            added_items.append({
                "category": "funny_short", "item_id": fid, "age_group": age,
                "audio_url": f.get("audio_url", ""),
                "cover_url": f.get("cover_url", ""),
            })

        for fid in sorted(before_fs - after_fs):
            removed.append(f"  ❌ REMOVED funny short ({age}): {fid}")
            removed_items.append({"category": "funny_shorts", "item_id": fid, "age_group": age})

        for fid in before_fs & after_fs:
            b = before["funny_shorts"][age][fid]
            a = after["funny_shorts"][age][fid]
            if b.get("has_audio") and not a.get("has_audio"):
                degraded.append(f"  ❌ LOST AUDIO funny short ({age}): {fid}")

    # ── Silly songs per age group ──
    for age in ["2-5", "6-8", "9-12"]:
        before_ss = set(before.get("silly_songs", {}).get(age, {}).keys())
        after_ss = set(after.get("silly_songs", {}).get(age, {}).keys())

        for sid in sorted(after_ss - before_ss):
            s = after["silly_songs"][age][sid]
            added.append(f"  ADDED silly song ({age}): {sid}")
            added_items.append({
                "category": "silly_song", "item_id": sid, "age_group": age,
                "audio_url": s.get("audio_url", ""),
                "cover_url": s.get("cover_url", ""),
            })

        for sid in sorted(before_ss - after_ss):
            removed.append(f"  ❌ REMOVED silly song ({age}): {sid}")
            removed_items.append({"category": "silly_songs", "item_id": sid, "age_group": age})

        for sid in before_ss & after_ss:
            b = before["silly_songs"][age][sid]
            a = after["silly_songs"][age][sid]
            if b.get("has_audio") and not a.get("has_audio"):
                degraded.append(f"  ❌ LOST AUDIO silly song ({age}): {sid}")
            # Detect content updates (title change)
            if b.get("title") != a.get("title"):
                updated.append(f"  ✏️  UPDATED silly song ({age}): {sid} — \"{b.get('title')}\" → \"{a.get('title')}\"")
            elif b.get("audio_url") != a.get("audio_url") and a.get("audio_url"):
                updated.append(f"  ✏️  UPDATED silly song ({age}): {sid} — new audio")

    # ── Poems per age group ──
    for age in ["2-5", "6-8", "9-12"]:
        before_poems = set(before.get("poems", {}).get(age, {}).keys())
        after_poems = set(after.get("poems", {}).get(age, {}).keys())

        for pid in sorted(after_poems - before_poems):
            p = after["poems"][age][pid]
            added.append(f"  ADDED poem ({age}): {pid}")
            added_items.append({
                "category": "poem", "item_id": pid, "age_group": age,
                "audio_url": p.get("audio_url", ""),
                "cover_url": p.get("cover_url", ""),
            })

        for pid in sorted(before_poems - after_poems):
            removed.append(f"  ❌ REMOVED poem ({age}): {pid}")
            removed_items.append({"category": "poems", "item_id": pid, "age_group": age})

        for pid in before_poems & after_poems:
            b = before["poems"][age][pid]
            a = after["poems"][age][pid]
            if b.get("has_audio") and not a.get("has_audio"):
                degraded.append(f"  ❌ LOST AUDIO poem ({age}): {pid}")

    return {
        "added": added,
        "removed": removed,
        "updated": updated,
        "degraded": degraded,
        "removed_items": removed_items,
        "added_items": added_items,
    }


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

    # Funny shorts, silly songs & poems: same union logic
    for category in ["funny_shorts", "silly_songs", "poems"]:
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

    print(f"\n  POEMS")
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("poems", {}).get(age, {})
        count = len(items)
        with_audio = sum(1 for d in items.values() if d.get("has_audio"))
        status = "✅" if with_audio == count else f"❌ {count - with_audio} without audio"
        print(f"    {age}: {count} poems, {with_audio} with audio {status}")


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
    """Capture and save pre-deploy state + back up JSON data files."""
    api = get_api(args.local)
    print(f"Capturing live state from {api}...")
    state = capture_state(api)
    save_json(SNAPSHOT_PATH, state)
    print_state_summary(state, "Snapshot Saved (pre-deploy)")
    print(f"\n  Saved to: {SNAPSHOT_PATH}")

    # Back up JSON data files so we can recover if they're deleted during deploy
    if not args.local:
        print()
        backup_json_files()

    print(f"\n  ✅ Run your deploy now, then run: python3 scripts/deploy_guard.py verify\n")


def cmd_verify(args):
    """Compare current state against snapshot AND golden, check files, auto-recover."""
    before = load_json(SNAPSHOT_PATH)
    if not before:
        print("⚠️  No snapshot found. Using golden baseline as reference.")

    golden = load_json(GOLDEN_PATH)

    api = get_api(args.local)
    frontend = get_frontend(args.local)
    print(f"Capturing live state from {api}...")
    after = capture_state(api)

    # Use snapshot if available, otherwise golden, otherwise just show current
    reference = before or golden or {}
    ref_label = "BEFORE (pre-deploy snapshot)" if before else "GOLDEN BASELINE (reference)"

    if reference:
        print_state_summary(reference, ref_label)
    print_state_summary(after, "AFTER (current live)")

    # ── Diff against snapshot ──
    if reference:
        changes = diff_states(reference, after)

        print(f"\n{'='*60}")
        has_issues = False

        if changes["added"]:
            print(f"  ✅ {len(changes['added'])} new item(s) added:")
            for c in changes["added"]:
                print(c)

        if changes["updated"]:
            print(f"\n  ✏️  {len(changes['updated'])} item(s) updated:")
            for c in changes["updated"]:
                print(c)

        if changes["removed"]:
            has_issues = True
            print(f"\n  ❌ {len(changes['removed'])} REMOVAL(S) DETECTED:")
            for c in changes["removed"]:
                print(c)

        if changes["degraded"]:
            has_issues = True
            print(f"\n  ❌ {len(changes['degraded'])} DEGRADATION(S) DETECTED:")
            for c in changes["degraded"]:
                print(c)

        if not changes["added"] and not changes["removed"] and not changes["updated"] and not changes["degraded"]:
            print("  ✅ NO CHANGES — content is identical.")

        print(f"{'='*60}")

        # ── Auto-recover removed items (JSON data files) ──
        if changes["removed_items"] and not args.no_recover and not args.local:
            json_recovered, json_failed = recover_json_files(changes["removed_items"])
            if json_recovered > 0:
                print(f"\n  ♻️  Recovered {json_recovered} JSON data file(s). Re-capturing state...")
                # Reload the API to trigger it to pick up restored files
                after = capture_state(api)
                # Re-diff to confirm recovery
                changes2 = diff_states(reference, after)
                still_removed = len(changes2["removed"])
                if still_removed == 0:
                    print("  ✅ All removed items restored!")
                else:
                    print(f"  ⚠️  {still_removed} item(s) still missing after JSON recovery")

        # ── Verify new items are fully serving ──
        if changes["added_items"] and not args.skip_files:
            new_issues = verify_new_items_serving(changes["added_items"], frontend, api)
            if new_issues:
                print(f"\n{'='*60}")
                print(f"  ⚠️  {len(new_issues)} new item(s) NOT fully serving:")
                for issue in new_issues:
                    print(issue)
                print(f"{'='*60}")
            else:
                print(f"\n  ✅ All new items fully serving (audio + cover reachable).")

    # ── Also diff against golden baseline (if golden exists and is different from reference) ──
    if golden and before and golden != before:
        golden_changes = diff_states(golden, after)
        golden_removed = golden_changes["removed"]
        if golden_removed:
            print(f"\n{'='*60}")
            print(f"  ⚠️  {len(golden_removed)} item(s) missing vs GOLDEN BASELINE:")
            for c in golden_removed:
                print(c)
            print(f"  These items existed in the golden baseline but are now missing.")

            # Auto-recover from JSON store
            if golden_changes["removed_items"] and not args.no_recover and not args.local:
                json_recovered, _ = recover_json_files(golden_changes["removed_items"])
                if json_recovered > 0:
                    print(f"  ♻️  Recovered {json_recovered} JSON(s) from golden baseline check.")
                    after = capture_state(api)
            print(f"{'='*60}")

    # ── File reachability check ──
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

    # ── Update golden baseline: merge new content ──
    if golden:
        merged = merge_golden(golden, after)
        save_json(GOLDEN_PATH, merged)
        new_stories = len(merged.get("stories", {})) - len(golden.get("stories", {}))
        # Count new silly songs + funny shorts + poems
        new_other = 0
        for cat in ["silly_songs", "funny_shorts", "poems"]:
            for age in ["2-5", "6-8", "9-12"]:
                new_other += len(merged.get(cat, {}).get(age, {})) - len(golden.get(cat, {}).get(age, {}))
        total_new = new_stories + new_other
        if total_new > 0:
            print(f"\n  📌 Golden baseline updated: +{total_new} new item(s) added")
    else:
        # First run — create golden from current state
        save_json(GOLDEN_PATH, after)
        print(f"\n  📌 Golden baseline created with {len(after.get('stories', {}))} stories")

    # ── Run invariant checks with auto-recovery ──
    print("\n  Running content invariant checks...")
    class InvariantArgs:
        auto_recover_invariants = True
    try:
        cmd_invariants(InvariantArgs())
    except SystemExit as e:
        if e.code != 0:
            print("  ⚠️  Invariant checks failed — see above for details.")

    # ── Back up current JSON files (so they're available for next recovery) ──
    if not args.local:
        backup_json_files()

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

    # Check poems (expect >=0 per group, but if any exist they must have audio)
    for age in ["2-5", "6-8", "9-12"]:
        items = state.get("poems", {}).get(age, {})
        for pid, p in items.items():
            if not p.get("has_audio"):
                issues.append(f"  ❌ Poem without audio ({age}): {pid}")

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
    all_empty = not any([changes["added"], changes["removed"], changes["updated"], changes["degraded"]])

    if all_empty:
        print("  ✅ Live state matches golden baseline perfectly.")
    else:
        if changes["added"]:
            print(f"  ✅ {len(changes['added'])} new item(s) since baseline (will be added to golden):")
            for c in changes["added"]:
                print(c)
        if changes["updated"]:
            print(f"\n  ✏️  {len(changes['updated'])} item(s) updated:")
            for c in changes["updated"]:
                print(c)
        if changes["removed"]:
            print(f"\n  ❌ {len(changes['removed'])} REMOVAL(S) vs golden baseline:")
            for c in changes["removed"]:
                print(c)
        if changes["degraded"]:
            print(f"\n  ❌ {len(changes['degraded'])} DEGRADATION(S) vs golden baseline:")
            for c in changes["degraded"]:
                print(c)
        if changes["removed"] or changes["degraded"]:
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

    # Auto-recover removed items from JSON store
    if changes["removed_items"] and not args.no_recover and not getattr(args, 'local', False):
        json_recovered, json_failed = recover_json_files(changes["removed_items"])
        if json_recovered > 0:
            print(f"\n  ♻️  Recovered {json_recovered} JSON data file(s)")

    # Merge new content into golden
    if changes["added"]:
        merged = merge_golden(golden, current)
        save_json(GOLDEN_PATH, merged)
        print(f"\n  📌 Golden baseline updated: +{len(changes['added'])} new item(s)")

    print()


def cmd_invariants(args):
    """Verify content generation invariants haven't regressed.

    Reads data/content_invariants.json and checks the actual source code
    to ensure critical rules are still enforced. These are hard-won fixes
    that must not silently regress when code is modified.

    With --auto-recover (default in verify), restores files from last known-good
    git commit if invariants are broken.
    """
    import re as _re

    invariants_path = BASE_DIR / "data" / "content_invariants.json"
    if not invariants_path.exists():
        print("❌ No content_invariants.json found.")
        sys.exit(1)

    invariants = json.loads(invariants_path.read_text())
    passed = 0
    failed = 0
    failures = []  # (name, file_path) tuples for auto-recovery
    auto_recover = getattr(args, "auto_recover_invariants", False)

    def check(name, condition, detail="", source_file=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            failures.append((name, source_file))
            print(f"  ❌ {name}{f' — {detail}' if detail else ''}")

    print(f"\n{'='*60}")
    print("  CONTENT INVARIANT CHECKS")
    print(f"{'='*60}\n")

    # ── V2 Short Stories ──────────────────────────────────────
    print("  V2 Short Stories:")
    gen_audio_path = BASE_DIR / "scripts" / "generate_audio.py"
    gen_audio = gen_audio_path.read_text()
    check(
        "No hook in audio (hook=None)",
        "hook=None" in gen_audio or "hook = None" in gen_audio,
        "generate_audio.py must pass hook=None to assemble_v2_audio",
        source_file="scripts/generate_audio.py",
    )

    gen_matrix_path = BASE_DIR / "scripts" / "generate_content_matrix.py"
    gen_matrix = gen_matrix_path.read_text()
    check(
        "No example phrase in prompt",
        "[PHRASE]Not yet" not in gen_matrix and "[PHRASE]not yet" not in gen_matrix,
        "V2_STORY_PROMPT still contains example phrase — LLM will anchor on it",
        source_file="scripts/generate_content_matrix.py",
    )
    check(
        "Phrase similarity check exists",
        "is_phrase_too_similar" in gen_matrix,
        "generate_content_matrix.py missing is_phrase_too_similar function",
        source_file="scripts/generate_content_matrix.py",
    )
    check(
        "Recent phrases tracked",
        "recent_phrases" in gen_matrix,
        "generate_content_matrix.py not tracking recent_phrases",
        source_file="scripts/generate_content_matrix.py",
    )

    # ── Lullabies 0-1 ────────────────────────────────────────
    print("\n  Lullabies (0-1 age group):")
    gen_lullaby_path = BASE_DIR / "scripts" / "generate_lullaby.py"
    gen_lullaby = gen_lullaby_path.read_text()
    check(
        "Infant system prompt exists",
        "LYRICS_SYSTEM_PROMPT_INFANT" in gen_lullaby,
        "generate_lullaby.py missing LYRICS_SYSTEM_PROMPT_INFANT",
        source_file="scripts/generate_lullaby.py",
    )
    check(
        "Infant structure instructions exist",
        "STRUCTURE_INSTRUCTIONS_INFANT" in gen_lullaby,
        "generate_lullaby.py missing STRUCTURE_INSTRUCTIONS_INFANT dict",
        source_file="scripts/generate_lullaby.py",
    )
    check(
        "Infant prompt used for 0-1",
        'is_infant = (age == "0-1")' in gen_lullaby or "is_infant = (age == '0-1')" in gen_lullaby,
        "generate_lullaby.py not detecting 0-1 age group",
        source_file="scripts/generate_lullaby.py",
    )
    check(
        "No signature words for 0-1",
        'sig_text = ""' in gen_lullaby,
        "generate_lullaby.py may still pass signature openings for 0-1",
        source_file="scripts/generate_lullaby.py",
    )

    # ── Funny Shorts ──────────────────────────────────────────
    print("\n  Funny Shorts:")
    gen_funny_path = BASE_DIR / "scripts" / "generate_funny_shorts_v2.py"
    gen_funny = gen_funny_path.read_text()
    check(
        "CHARACTER_VISUALS for text-free covers",
        "CHARACTER_VISUALS" in gen_funny,
        "generate_funny_shorts_v2.py missing CHARACTER_VISUALS — covers will render text",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    # Cover prompt must NOT mention "text/words/letters" even negatively —
    # FLUX interprets "no text" as "generate text". Prompt must be purely visual.
    check(
        "Cover prompt is purely visual (no text mentions)",
        "NEVER put the title" in gen_funny and "CHARACTER_VISUALS" in gen_funny,
        "Cover generation must use CHARACTER_VISUALS and never mention title or text",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    check(
        "Context-aware SFX generation",
        "generate_episode_sfx" in gen_funny,
        "generate_funny_shorts_v2.py missing generate_episode_sfx function",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    check(
        "TTS silence trimming",
        "trim_tts_silence" in gen_funny,
        "generate_funny_shorts_v2.py missing trim_tts_silence function",
        source_file="scripts/generate_funny_shorts_v2.py",
    )

    # Check TTS speeds are fast enough
    speed_checks = [
        ("boomy", 1.05), ("pip", 1.15), ("shadow", 0.92),
        ("sunny", 1.08), ("melody", 1.02),
    ]
    for char, min_speed in speed_checks:
        pattern = rf'"{char}":\s*\{{[^}}]*"speed":\s*([\d.]+)'
        m = _re.search(pattern, gen_funny, _re.DOTALL)
        if m:
            actual = float(m.group(1))
            check(
                f"{char} speed >= {min_speed}",
                actual >= min_speed,
                f"Current: {actual}, minimum: {min_speed}",
                source_file="scripts/generate_funny_shorts_v2.py",
            )
        else:
            check(f"{char} speed >= {min_speed}", False, "Could not find speed value",
                  source_file="scripts/generate_funny_shorts_v2.py")

    # Inter-line gap
    gap_m = _re.search(r'AudioSegment\.silent\(duration=(\d+)\)\s*#.*conversation', gen_funny)
    if not gap_m:
        gap_m = _re.search(r'narration \+= AudioSegment\.silent\(duration=(\d+)\)', gen_funny)
    if gap_m:
        gap = int(gap_m.group(1))
        check(f"Inter-line gap <= 100ms", gap <= 100, f"Current: {gap}ms",
              source_file="scripts/generate_funny_shorts_v2.py")
    else:
        check("Inter-line gap <= 100ms", False, "Could not find inter-line gap value",
              source_file="scripts/generate_funny_shorts_v2.py")

    # Diversity system
    check(
        "Diversity system: DYNAMICS pool",
        "DYNAMICS = [" in gen_funny and "DYNAMIC_DESCRIPTIONS" in gen_funny,
        "generate_funny_shorts_v2.py missing DYNAMICS diversity pool",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    check(
        "Diversity system: select_episode_params",
        "def select_episode_params" in gen_funny and "_pick_avoiding_recent" in gen_funny,
        "generate_funny_shorts_v2.py missing diversity parameter selection",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    check(
        "Diversity system: validate_episode_variety",
        "def validate_episode_variety" in gen_funny,
        "generate_funny_shorts_v2.py missing post-generation variety validation",
        source_file="scripts/generate_funny_shorts_v2.py",
    )
    check(
        "Diversity system: metadata tracks dimensions",
        '"dynamic":' in gen_funny and '"topic":' in gen_funny
        and '"melody_role":' in gen_funny and '"ending":' in gen_funny,
        "Episode metadata must track all diversity dimensions",
        source_file="scripts/generate_funny_shorts_v2.py",
    )

    # ── Silly Songs ──────────────────────────────────────────
    print("\n  Silly Songs:")
    gen_silly_path = BASE_DIR / "scripts" / "generate_silly_songs_battlecry.py"
    if gen_silly_path.exists():
        gen_silly = gen_silly_path.read_text()
        check(
            "Scene generation (Step 0) exists",
            "def generate_scene" in gen_silly and "SCENE_PROMPT" in gen_silly,
            "generate_silly_songs_battlecry.py missing scene anchoring (Step 0)",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        check(
            "Scene validation exists",
            "def validate_scene" in gen_silly and "vague_phrases" in gen_silly,
            "generate_silly_songs_battlecry.py missing validate_scene",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        check(
            "Chorus consistency check",
            "chorus_inconsistent" in gen_silly or "CHORUS CONSISTENCY" in gen_silly
            or "chorus_consistency" in gen_silly,
            "Validation must check non-final choruses are identical",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        check(
            "Energetic style (no calm/bedtime language)",
            ("impossible to sit still" in gen_silly or "punchy beat" in gen_silly
             or "bouncy beat" in gen_silly or "groovy beat" in gen_silly
             or "cool beat" in gen_silly),
            "Style prompt must be energetic — silly songs are NOT sleep content",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        # Ensure no calm language in the actual style prompt builder (not comments)
        # Extract just the build_style_prompt function body
        style_fn_match = _re.search(
            r'def build_style_prompt.*?(?=\ndef |\nclass |\Z)',
            gen_silly, _re.DOTALL
        )
        style_fn = style_fn_match.group(0) if style_fn_match else ""
        calm_terms = ["soft and gentle", "cozy sleepy", "warm and drowsy", "lullaby", "soothing"]
        has_calm = any(t in style_fn.lower() for t in calm_terms)
        check(
            "No calm/sleep language in style prompts",
            not has_calm,
            f"Found calm language in build_style_prompt — silly songs are NOT sleep content",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        check(
            "Retry-with-feedback includes scene",
            "def retry_with_feedback" in gen_silly and "scene" in gen_silly.split("def retry_with_feedback")[1][:500],
            "retry_with_feedback must use scene context for targeted fixes",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        check(
            "Batch diversity check",
            "def validate_batch_diversity" in gen_silly,
            "Missing validate_batch_diversity — prevents duplicate battle cries in same run",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
        # Check tempo ranges are energetic (not calm)
        tempo_match = _re.search(r'"2-5":\s*\((\d+),\s*(\d+)\)', gen_silly)
        if tempo_match:
            low = int(tempo_match.group(1))
            check(
                "Tempo range is energetic (2-5 low >= 110)",
                low >= 110,
                f"Current 2-5 low tempo: {low} BPM — too slow for silly songs",
                source_file="scripts/generate_silly_songs_battlecry.py",
            )
        check(
            "Cover prompt is purely visual (no text mentions)",
            "COVER_PROMPT_TEMPLATE" in gen_silly
            and "text" not in gen_silly.split("COVER_PROMPT_TEMPLATE")[1][:300].lower(),
            "Cover prompt must never mention text/words/letters",
            source_file="scripts/generate_silly_songs_battlecry.py",
        )
    else:
        check("Silly songs script exists", False, "scripts/generate_silly_songs_battlecry.py not found")

    print(f"\n{'='*60}")
    if failed == 0:
        print(f"  ✅ All {passed} invariant checks passed.")
    else:
        print(f"  ❌ {failed} INVARIANT(S) BROKEN (of {passed + failed} total):")
        for name, _ in failures:
            print(f"    • {name}")

        # Auto-recovery: restore broken files from last known-good git commit
        if auto_recover:
            broken_files = list(set(f for _, f in failures if f))
            if broken_files:
                print(f"\n  🔧 Auto-recovery: restoring {len(broken_files)} file(s) from last good commit...")
                for rel_path in broken_files:
                    try:
                        result = subprocess.run(
                            ["git", "checkout", "HEAD", "--", rel_path],
                            capture_output=True, text=True, cwd=str(BASE_DIR),
                        )
                        if result.returncode == 0:
                            print(f"    ✅ Restored: {rel_path}")
                        else:
                            print(f"    ❌ Failed to restore {rel_path}: {result.stderr.strip()}")
                    except Exception as e:
                        print(f"    ❌ Recovery error for {rel_path}: {e}")

                # Re-check after recovery
                print("\n  Re-checking invariants after recovery...")
                # Recursive call without auto-recover to just verify
                class FakeArgs:
                    auto_recover_invariants = False
                recheck_args = FakeArgs()
                try:
                    cmd_invariants(recheck_args)
                    print("  ✅ Auto-recovery successful — all invariants restored.")
                    return  # exit successfully
                except SystemExit:
                    print("  ❌ Auto-recovery FAILED — manual intervention needed.")
        else:
            print(f"\n  Run with --auto-recover or as part of 'verify' for auto-recovery.")

        print(f"\n  These are hard-won fixes. Investigate before deploying.")
    print(f"{'='*60}\n")

    if failed > 0:
        sys.exit(1)


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
  invariants Check source code invariants (hard-won fixes)

Examples:
  python3 scripts/deploy_guard.py snapshot
  python3 scripts/deploy_guard.py verify
  python3 scripts/deploy_guard.py check
  python3 scripts/deploy_guard.py seal
  python3 scripts/deploy_guard.py audit
  python3 scripts/deploy_guard.py recover --dry-run
  python3 scripts/deploy_guard.py invariants --auto-recover
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

    inv = sub.add_parser("invariants", help="Check source code invariants (hard-won fixes)")
    inv.add_argument("--auto-recover", action="store_true",
                     help="Auto-restore broken files from last good git commit")
    inv.set_defaults(func=lambda a: (setattr(a, "auto_recover_invariants", a.auto_recover), cmd_invariants(a)))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
