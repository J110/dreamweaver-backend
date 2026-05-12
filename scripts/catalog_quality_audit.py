#!/usr/bin/env python3
"""Read-only catalog quality audit.

Reads seed_output/content.json, validates audio files on disk,
cross-references QA reports, and categorizes each published item:

  GREEN        all variants exist + ffprobe duration matches claim + QA PASS
  YELLOW       all variants exist + duration matches + QA WARN
  RED          any variant missing on disk, unreadable, duration mismatch,
               or item has no audio_variants at all
  GHOST        audio_variants empty/missing BUT audio file with gen-<id>
               prefix exists on disk
  QA_NEVER_RUN variants OK, no QA report found for this item

Writes a structured JSON report to seed_output/ and prints a
human-readable summary. NO MUTATIONS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
QA_REPORTS_DIR = BASE_DIR / "seed_output" / "qa_reports"
WEB_AUDIO_DIR = Path("/opt/dreamweaver-web/public/audio")
AUDIO_STORE_DIR = Path("/opt/audio-store")
DURATION_TOLERANCE_SEC = 5.0

REPORT_PATH = BASE_DIR / "seed_output" / f"catalog_quality_audit_{datetime.now():%Y%m%d_%H%M%S}.json"


def resolve_disk_path(url: str) -> Path | None:
    """Map a /audio/... URL to an existing on-disk file. None if neither root has it."""
    if not url or not url.startswith("/audio/"):
        return None
    rel = url[len("/audio/"):]
    for root in (WEB_AUDIO_DIR, AUDIO_STORE_DIR):
        cand = root / rel
        if cand.exists():
            return cand
    return None


def ffprobe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return float(out.stdout.strip())
    except Exception:
        return None


def find_audio_by_prefix(item_id: str) -> list[Path]:
    """Find audio files on disk matching the gen-<id> prefix convention."""
    if not item_id.startswith("gen-"):
        return []
    prefix = item_id[len("gen-"):][:8]
    matches = []
    for root in (WEB_AUDIO_DIR / "pre-gen", AUDIO_STORE_DIR / "pre-gen"):
        if root.exists():
            try:
                matches.extend(root.glob(f"{prefix}*"))
            except Exception:
                pass
    return matches


def load_qa_history() -> dict[str, dict]:
    """Build {story_id: latest_verdict_dict}. Latest report overwrites earlier."""
    history: dict[str, dict] = {}
    if not QA_REPORTS_DIR.exists():
        return history
    reports = sorted(QA_REPORTS_DIR.glob("qa_audio_*.json"))
    for report_path in reports:
        try:
            report = json.loads(report_path.read_text())
        except Exception:
            continue
        for story in report.get("stories", []):
            sid = story.get("story_id")
            if not sid:
                continue
            variants = story.get("variants", [])
            verdict = "PASS"
            min_fidelity = 1.0
            reasons: list[str] = []
            for v in variants:
                vv = v.get("verdict", "PASS")
                if vv == "FAIL":
                    verdict = "FAIL"
                elif vv == "WARN" and verdict != "FAIL":
                    verdict = "WARN"
                vf = v.get("text_fidelity") or v.get("fidelity") or v.get("combined")
                if isinstance(vf, (int, float)) and vf > 0:
                    min_fidelity = min(min_fidelity, vf)
                reasons.extend(v.get("reasons") or [])
            history[sid] = {
                "verdict": verdict,
                "min_fidelity": round(min_fidelity, 3),
                "reasons": sorted(set(reasons)),
                "report": report_path.name,
            }
    return history


def main() -> int:
    if not CONTENT_PATH.exists():
        print(f"ERROR: {CONTENT_PATH} not found", file=sys.stderr)
        return 1
    content = json.loads(CONTENT_PATH.read_text())
    if not isinstance(content, list):
        print("ERROR: content.json is not a list", file=sys.stderr)
        return 1

    qa_history = load_qa_history()

    categories: dict[str, list] = {
        "green": [],
        "yellow": [],
        "red": [],
        "ghost": [],
        "qa_never_run": [],
    }

    for item in content:
        if not isinstance(item, dict):
            continue
        status = item.get("status", "published")
        if status not in ("published", "", None):
            continue
        sid = item.get("id", "")
        meta = {
            "id": sid,
            "title": item.get("title", ""),
            "type": item.get("type"),
            "subtype": item.get("subtype"),
            "length": item.get("length"),
            "lang": item.get("lang"),
        }
        variants = item.get("audio_variants") or []

        if not variants:
            disk_matches = find_audio_by_prefix(sid)
            if disk_matches:
                meta["ghost_files"] = [str(p) for p in disk_matches]
                categories["ghost"].append(meta)
            else:
                meta["reason"] = "no audio_variants and no disk audio"
                categories["red"].append(meta)
            continue

        variant_results = []
        any_broken = False
        for v in variants:
            url = v.get("url", "")
            voice = v.get("voice", "")
            claimed_dur = v.get("duration_seconds")
            disk = resolve_disk_path(url)
            entry: dict = {"voice": voice, "url": url}
            if not disk:
                entry["status"] = "MISSING_FILE"
                any_broken = True
            else:
                actual_dur = ffprobe_duration(disk)
                entry["disk_path"] = str(disk)
                entry["actual_duration"] = actual_dur
                entry["claimed_duration"] = claimed_dur
                if actual_dur is None:
                    entry["status"] = "UNREADABLE"
                    any_broken = True
                elif claimed_dur is not None and abs(actual_dur - float(claimed_dur)) > DURATION_TOLERANCE_SEC:
                    entry["status"] = "DURATION_MISMATCH"
                    any_broken = True
                else:
                    entry["status"] = "OK"
            variant_results.append(entry)
        meta["variants"] = variant_results

        if any_broken:
            categories["red"].append(meta)
            continue

        qa = qa_history.get(sid)
        if qa is None:
            meta["qa"] = None
            categories["qa_never_run"].append(meta)
        else:
            meta["qa"] = qa
            v = qa["verdict"]
            if v == "PASS":
                categories["green"].append(meta)
            elif v == "WARN":
                categories["yellow"].append(meta)
            else:
                categories["red"].append(meta)

    summary = {
        "green_count": len(categories["green"]),
        "yellow_count": len(categories["yellow"]),
        "red_count": len(categories["red"]),
        "ghost_count": len(categories["ghost"]),
        "qa_never_run_count": len(categories["qa_never_run"]),
        "total_audited": sum(len(v) for v in categories.values()),
    }

    report = {
        "audit_date": datetime.now(timezone.utc).isoformat(),
        "content_path": str(CONTENT_PATH),
        "total_items_in_content": len(content),
        "summary": summary,
        "categories": categories,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"\n=== Catalog Quality Audit — {report['audit_date']} ===")
    print(f"Content items in seed_output/content.json: {len(content)}")
    print(f"Audited (published or no status): {summary['total_audited']}")
    print()
    print(f"  GREEN  (variants OK + QA PASS):       {summary['green_count']:>4}")
    print(f"  YELLOW (variants OK + QA WARN):       {summary['yellow_count']:>4}")
    print(f"  RED    (missing/broken/QA FAIL):      {summary['red_count']:>4}")
    print(f"  GHOST  (no variants but audio on disk):{summary['ghost_count']:>4}")
    print(f"  NO_QA  (variants OK, no QA report):   {summary['qa_never_run_count']:>4}")

    if categories["red"]:
        print(f"\n--- RED items ({len(categories['red'])}) ---")
        for it in categories["red"]:
            reason = it.get("reason") or (it.get("qa", {}) or {}).get("verdict") or "broken variant"
            print(f"  {it['id']:24} [{it.get('lang','?')}/{it.get('type','?')}] {it.get('title','')[:55]} — {reason}")
    if categories["ghost"]:
        print(f"\n--- GHOST items ({len(categories['ghost'])}) ---")
        for it in categories["ghost"]:
            print(f"  {it['id']:24} [{it.get('lang','?')}/{it.get('type','?')}] {it.get('title','')[:55]} — {len(it.get('ghost_files', []))} disk file(s)")

    print(f"\nFull JSON report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
