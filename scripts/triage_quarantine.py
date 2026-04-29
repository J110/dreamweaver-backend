#!/usr/bin/env python3
"""Triage quarantined orphans — human-in-the-loop publish or discard.

Implements spec §3.2. Quarantined orphans live at
``data/_quarantine/<bucket>/<id>.json`` (one bucket per type/lang split,
mirroring PER_CONTENT_DIRS). Each item has been physically removed from
its live serving path by the backfill script (gate 4) because it appeared
on disk but was missing from the master content.json. This script lets
a human review each one and decide:

  --list                   Show all quarantined items as a table
  --publish <id>           Promote one orphan back to live serving path
  --discard <id>           Delete one orphan permanently
  --publish-all --confirm  Bulk-promote everything (continues past failures)
  --discard-all --confirm  Bulk-delete everything (continues past failures)

Publish gates (per §3.2):
  1. Audio URL serves 200
  2. Cover URL serves 200
  3. Target canonical path is empty (no silent overwrite)

If any gate fails, the per-item publish aborts with a specific error
and exits non-zero. Discard has no gates — discarding doesn't need
verification.

Asset note (per §3.2): audio + cover files already live at the prod
serving paths (/opt/audio-store, /opt/cover-store, etc.). This script
only moves the JSON metadata; assets are not touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

try:
    import httpx
except ImportError:
    print("ERROR: httpx required — pip install httpx", file=sys.stderr)
    sys.exit(2)

from app.services.local_store import PER_CONTENT_DIRS  # noqa: E402

DEFAULT_HOST = "https://dreamvalley.app"
QUARANTINE_DIR_NAME = "_quarantine"


# ── URL verification ───────────────────────────────────────────────────────


def check_url(url: str, timeout: float = 10.0) -> tuple[bool, int, str]:
    """HEAD an URL; return (is_200, status_code, error_or_empty).

    Uses follow_redirects=True so the check works against URLs that 301
    to a CDN. Status 200 is the only success — no 3xx, no 401, etc.,
    since those wouldn't serve to a child user.
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(url)
        return (resp.status_code == 200, resp.status_code, "")
    except httpx.HTTPError as e:
        return (False, 0, f"{type(e).__name__}: {e}")


# ── Quarantine layout helpers ──────────────────────────────────────────────


def quarantine_buckets() -> list[tuple[str, str, Optional[str], str]]:
    """Same as PER_CONTENT_DIRS but rooted under _quarantine/."""
    return list(PER_CONTENT_DIRS)


def find_orphan(data_dir: Path, item_id: str) -> Optional[tuple[Path, str]]:
    """Find a quarantined orphan by id. Returns (path, bucket_name) or None.

    If the same id is present in multiple buckets (shouldn't happen but
    defensively handled), returns None and logs to stderr. Caller should
    treat that as an error.
    """
    matches: list[tuple[Path, str]] = []
    quarantine_root = data_dir / QUARANTINE_DIR_NAME
    if not quarantine_root.is_dir():
        return None
    for subdir, _, _, _ in PER_CONTENT_DIRS:
        candidate = quarantine_root / subdir / f"{item_id}.json"
        if candidate.is_file():
            matches.append((candidate, subdir))
    if not matches:
        return None
    if len(matches) > 1:
        print(
            f"ERROR: ambiguous orphan id {item_id!r} found in multiple buckets: "
            + ", ".join(b for _, b in matches),
            file=sys.stderr,
        )
        return None
    return matches[0]


def list_orphans(data_dir: Path) -> list[dict]:
    """Walk every bucket under _quarantine; return one record per file.

    Each record has: path, bucket, id, type, lang, title, audio_url, cover.
    Tolerant of malformed JSON — surfaces a placeholder record with
    error noted.
    """
    out: list[dict] = []
    quarantine_root = data_dir / QUARANTINE_DIR_NAME
    if not quarantine_root.is_dir():
        return out
    for subdir, default_type, _, default_lang in PER_CONTENT_DIRS:
        d = quarantine_root / subdir
        if not d.is_dir():
            continue
        for fp in sorted(d.glob("*.json")):
            if fp.name.endswith(".json.tmp"):
                continue
            try:
                body = json.loads(fp.read_text(encoding="utf-8"))
            except Exception as e:
                out.append({
                    "path": str(fp),
                    "bucket": subdir,
                    "id": fp.stem,
                    "type": default_type,
                    "lang": default_lang,
                    "title": f"<malformed JSON: {e}>",
                    "audio_url": "",
                    "cover": "",
                    "_error": str(e),
                })
                continue
            out.append({
                "path": str(fp),
                "bucket": subdir,
                "id": body.get("id", fp.stem),
                "type": default_type,
                "lang": default_lang,
                "title": body.get("title", ""),
                "audio_url": body.get("audio_url", "") or body.get("audio_file", ""),
                "cover": body.get("cover", ""),
            })
    return out


# ── Display ────────────────────────────────────────────────────────────────


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def render_table(orphans: list[dict], host: str) -> str:
    if not orphans:
        return "No quarantined orphans.\n"

    lines: list[str] = []
    header = (
        f"{'ID':<28}  {'BUCKET':<16}  {'LANG':<5}  "
        f"{'TITLE':<60}  AUDIO"
    )
    lines.append(header)
    lines.append("─" * (len(header) + 60))
    for o in orphans:
        audio_path = o["audio_url"]
        audio_url = (
            f"{host}{audio_path}"
            if audio_path and audio_path.startswith("/")
            else audio_path
        )
        lines.append(
            f"{_truncate(o['id'], 28):<28}  "
            f"{o['bucket']:<16}  "
            f"{o['lang']:<5}  "
            f"{_truncate(o['title'] or '<no title>', 60):<60}  "
            f"{audio_url}"
        )
    lines.append("")
    lines.append(f"Total: {len(orphans)} quarantined item(s)")

    # Breakdown by bucket
    from collections import Counter
    counts: Counter = Counter(o["bucket"] for o in orphans)
    if counts:
        lines.append("By bucket: " + ", ".join(
            f"{b}={c}" for b, c in sorted(counts.items())
        ))
    return "\n".join(lines) + "\n"


# ── Per-item operations ────────────────────────────────────────────────────


def publish_one(
    data_dir: Path, item_id: str, host: str, *, verbose: bool = True,
) -> tuple[bool, str]:
    """Verify gates, then atomically move JSON from quarantine to live path.

    Returns (success, message).
    """
    found = find_orphan(data_dir, item_id)
    if found is None:
        return (False, "not found in quarantine")
    src_path, bucket = found

    try:
        body = json.loads(src_path.read_text(encoding="utf-8"))
    except Exception as e:
        return (False, f"malformed JSON in {src_path}: {e}")

    audio_path = body.get("audio_url") or body.get("audio_file") or ""
    cover_path = body.get("cover") or ""

    if not audio_path:
        return (False, "no audio_url field in JSON; cannot verify")
    if not cover_path:
        return (False, "no cover field in JSON; cannot verify")

    audio_url = f"{host}{audio_path}" if audio_path.startswith("/") else audio_path
    cover_url = f"{host}{cover_path}" if cover_path.startswith("/") else cover_path

    # Gate 1: audio
    ok, code, err = check_url(audio_url)
    if not ok:
        return (False, f"audio HEAD {audio_url} → {code or err}")

    # Gate 2: cover
    ok, code, err = check_url(cover_url)
    if not ok:
        return (False, f"cover HEAD {cover_url} → {code or err}")

    # Gate 3: target canonical path empty
    target_dir = data_dir / bucket
    target = target_dir / f"{item_id}.json"
    if target.exists():
        return (False, f"canonical path {target} already exists; refusing overwrite")

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        # POSIX rename is atomic on same filesystem. We can't use os.replace
        # because it would silently overwrite if the target appeared between
        # our check and the move; os.rename on POSIX with non-existent
        # target gives the strongest semantics for our case.
        os.rename(str(src_path), str(target))
    except OSError as e:
        return (False, f"move failed {src_path} → {target}: {e}")

    if verbose:
        print(f"  ✓ published {item_id}: {src_path} → {target}")
    return (True, "")


def discard_one(
    data_dir: Path, item_id: str, *, verbose: bool = True,
) -> tuple[bool, str]:
    """Delete a quarantine entry permanently. No verification.

    Per spec: print title + audio URL one more time for visibility,
    then delete.
    """
    found = find_orphan(data_dir, item_id)
    if found is None:
        return (False, "not found in quarantine")
    src_path, bucket = found

    title = "<unknown>"
    audio_path = ""
    try:
        body = json.loads(src_path.read_text(encoding="utf-8"))
        title = body.get("title", title)
        audio_path = body.get("audio_url") or body.get("audio_file") or ""
    except Exception:
        pass

    if verbose:
        print(f"  Discarding: {item_id}")
        print(f"    title: {title}")
        if audio_path:
            print(f"    audio: {audio_path}")
        print(f"    file:  {src_path}")

    try:
        src_path.unlink()
    except OSError as e:
        return (False, f"delete failed: {e}")

    if verbose:
        print(f"  ✓ discarded {item_id}")
    return (True, "")


# ── Bulk operations ────────────────────────────────────────────────────────


def publish_all(data_dir: Path, host: str) -> dict:
    """Iterate every orphan; attempt publish; collect summary.

    Continues past per-item failures. Returns a summary dict.
    """
    orphans = list_orphans(data_dir)
    summary = {
        "total": len(orphans),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "failures": [],
    }
    for o in orphans:
        item_id = o["id"]
        # Pre-check skip case (target already exists)
        target = data_dir / o["bucket"] / f"{item_id}.json"
        if target.exists():
            summary["skipped"] += 1
            summary["failures"].append((item_id, "skipped — canonical path already exists"))
            print(f"  ⊘ skipped {item_id} (canonical path already exists)")
            continue
        ok, msg = publish_one(data_dir, item_id, host, verbose=True)
        if ok:
            summary["succeeded"] += 1
        else:
            summary["failed"] += 1
            summary["failures"].append((item_id, msg))
            print(f"  ✗ failed {item_id}: {msg}")
    return summary


def discard_all(data_dir: Path) -> dict:
    orphans = list_orphans(data_dir)
    summary = {
        "total": len(orphans),
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }
    for o in orphans:
        item_id = o["id"]
        ok, msg = discard_one(data_dir, item_id, verbose=True)
        if ok:
            summary["succeeded"] += 1
        else:
            summary["failed"] += 1
            summary["failures"].append((item_id, msg))
            print(f"  ✗ failed {item_id}: {msg}")
    return summary


def _print_bulk_summary(label: str, summary: dict) -> None:
    print()
    print("─" * 60)
    print(f"{label} summary:")
    print(f"  total:     {summary['total']}")
    print(f"  succeeded: {summary['succeeded']}")
    print(f"  failed:    {summary['failed']}")
    if "skipped" in summary:
        print(f"  skipped:   {summary['skipped']}")
    if summary["failures"]:
        print(f"\n  Failures ({len(summary['failures'])}):")
        for item_id, msg in summary["failures"]:
            print(f"    {item_id}: {msg}")
    print()


# ── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triage quarantined orphans (spec §3.2).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all quarantined items")
    group.add_argument("--publish", metavar="ID", help="Publish one orphan to live serving path")
    group.add_argument("--discard", metavar="ID", help="Delete one orphan permanently")
    group.add_argument("--publish-all", action="store_true",
                       help="Bulk publish (requires --confirm)")
    group.add_argument("--discard-all", action="store_true",
                       help="Bulk discard (requires --confirm)")

    parser.add_argument("--confirm", action="store_true",
                        help="Required for bulk operations")
    parser.add_argument("--data-dir", type=Path, default=BASE_DIR / "data",
                        help="Data root directory (default: data/)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Public host for URL verification (default: {DEFAULT_HOST})")

    args = parser.parse_args()

    if args.list:
        orphans = list_orphans(args.data_dir)
        print(render_table(orphans, args.host))
        return 0

    if args.publish:
        ok, msg = publish_one(args.data_dir, args.publish, args.host)
        if ok:
            return 0
        print(f"ERROR: {args.publish}: {msg}", file=sys.stderr)
        return 1

    if args.discard:
        ok, msg = discard_one(args.data_dir, args.discard)
        if ok:
            return 0
        print(f"ERROR: {args.discard}: {msg}", file=sys.stderr)
        return 1

    if args.publish_all:
        if not args.confirm:
            print(
                "ERROR: --publish-all requires --confirm. Re-run with --confirm to proceed.",
                file=sys.stderr,
            )
            return 2
        summary = publish_all(args.data_dir, args.host)
        _print_bulk_summary("--publish-all", summary)
        return 0 if summary["failed"] == 0 else 1

    if args.discard_all:
        if not args.confirm:
            print(
                "ERROR: --discard-all requires --confirm. Re-run with --confirm to proceed.",
                file=sys.stderr,
            )
            return 2
        summary = discard_all(args.data_dir)
        _print_bulk_summary("--discard-all", summary)
        return 0 if summary["failed"] == 0 else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
