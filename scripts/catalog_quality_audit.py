#!/usr/bin/env python3
"""Read-only catalog quality audit.

Reads seed_output/content.json, validates audio files on disk,
cross-references QA reports, and categorizes each published item:

  GREEN        all audio refs exist + ffprobe duration matches claim + QA PASS
  YELLOW       all audio refs OK + QA WARN
  QA_FAIL      all audio refs OK + QA FAIL (audio plays, QA verdict is
               historical; may reflect TTS pronunciation variance or
               transcript ambiguity, not playable-audio integrity)
  RED          one or more audio refs missing on disk, unreadable, or
               duration mismatch — actually broken
  GHOST        no audio refs in metadata BUT audio file matching the item's
               id exists on disk (in pre-gen, silly-songs, funny-shorts,
               poems, or lullabies subdirs)
  QA_NEVER_RUN audio refs OK, no QA report found for this item

Audio refs are normalized from two schemas:
  - Modern: item.audio_variants[].url
  - Legacy: item.audio_url OR item.audio_file (silly_songs, funny_shorts,
    poems, some lullabies that pre-date the variants schema)

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


AUDIO_SUBDIRS = ("pre-gen", "silly-songs", "funny-shorts", "poems", "poems-hi", "lullabies", "story_music")


def resolve_disk_path(url: str) -> Path | None:
    """Map a /audio/... URL to an existing on-disk file. None if neither root has it."""
    if not url:
        return None
    # Allow URLs with or without leading slash; tolerate extra prefixes.
    if url.startswith("/audio/"):
        rel = url[len("/audio/"):]
    elif url.startswith("audio/"):
        rel = url[len("audio/"):]
    else:
        rel = url.lstrip("/")
    for root in (WEB_AUDIO_DIR, AUDIO_STORE_DIR):
        cand = root / rel
        if cand.exists():
            return cand
    return None


def get_audio_refs(item: dict) -> list[dict]:
    """Normalize audio references into a unified list.

    Modern: item.audio_variants[]. Legacy items (silly_song, funny_short,
    poem, some lullabies pre-variants-schema) carry audio_url or audio_file
    at the top level. Returns list of {voice, url, claimed_dur}.
    """
    refs: list[dict] = []
    for v in (item.get("audio_variants") or []):
        if isinstance(v, dict) and v.get("url"):
            refs.append({
                "voice": v.get("voice", ""),
                "url": v.get("url", ""),
                "claimed_dur": v.get("duration_seconds"),
            })
    if refs:
        return refs
    legacy = item.get("audio_url") or item.get("audio_file")
    if legacy:
        url = legacy if str(legacy).startswith("/") else "/" + str(legacy)
        refs.append({
            "voice": "legacy",
            "url": url,
            "claimed_dur": item.get("duration_seconds"),
        })
    return refs


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
    """Find audio files on disk that look like they belong to this item.

    Searches every known audio subdir on both roots. Matches:
      - exact filename stem == item_id (legacy: silly-songs/<id>.mp3)
      - filename stem starts with `<item_id>_` (voiced variants: id_female_1)
      - for gen-* ids, files starting with the 8-char prefix after `gen-`
    """
    if not item_id:
        return []
    matches: list[Path] = []
    gen_prefix = item_id[len("gen-"):][:8] if item_id.startswith("gen-") else None
    for root in (WEB_AUDIO_DIR, AUDIO_STORE_DIR):
        for sub in AUDIO_SUBDIRS:
            d = root / sub
            if not d.exists():
                continue
            try:
                for f in d.iterdir():
                    if not f.is_file():
                        continue
                    stem = f.stem
                    if stem == item_id or stem.startswith(item_id + "_"):
                        matches.append(f)
                    elif gen_prefix and stem.startswith(gen_prefix):
                        matches.append(f)
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
        "qa_fail": [],
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
        refs = get_audio_refs(item)

        if not refs:
            disk_matches = find_audio_by_prefix(sid)
            if disk_matches:
                meta["ghost_files"] = [str(p) for p in disk_matches]
                categories["ghost"].append(meta)
            else:
                meta["reason"] = "no audio refs and no disk audio"
                categories["red"].append(meta)
            continue

        variant_results = []
        any_broken = False
        for v in refs:
            url = v.get("url", "")
            voice = v.get("voice", "")
            claimed_dur = v.get("claimed_dur")
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
            verdict = qa["verdict"]
            if verdict == "PASS":
                categories["green"].append(meta)
            elif verdict == "WARN":
                categories["yellow"].append(meta)
            else:
                # FAIL but audio files exist on disk + ffprobe-validated +
                # duration matches claim. QA verdict is historical and often
                # reflects TTS pronunciation variance (e.g. "Cirrus" → "Cyrus")
                # or transcript ambiguity, not playable-audio integrity. Keep
                # as its own signal rather than collapse into RED.
                categories["qa_fail"].append(meta)

    summary = {
        "green_count": len(categories["green"]),
        "yellow_count": len(categories["yellow"]),
        "qa_fail_count": len(categories["qa_fail"]),
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
    print(f"  GREEN   (audio OK + QA PASS):              {summary['green_count']:>4}")
    print(f"  YELLOW  (audio OK + QA WARN):              {summary['yellow_count']:>4}")
    print(f"  QA_FAIL (audio OK + QA FAIL historical):   {summary['qa_fail_count']:>4}")
    print(f"  RED     (missing/broken/unreadable audio): {summary['red_count']:>4}")
    print(f"  GHOST   (no refs but audio on disk):       {summary['ghost_count']:>4}")
    print(f"  NO_QA   (audio OK, no QA report):          {summary['qa_never_run_count']:>4}")

    if categories["red"]:
        print(f"\n--- RED items ({len(categories['red'])}) ---")
        for it in categories["red"]:
            reason = it.get("reason") or "broken variant"
            print(f"  {it['id']:28} [{it.get('lang','?')}/{it.get('type','?')}] {it.get('title','')[:55]} — {reason}")
    if categories["ghost"]:
        print(f"\n--- GHOST items ({len(categories['ghost'])}) ---")
        for it in categories["ghost"]:
            print(f"  {it['id']:28} [{it.get('lang','?')}/{it.get('type','?')}] {it.get('title','')[:55]} — {len(it.get('ghost_files', []))} disk file(s)")
    if categories["qa_fail"]:
        print(f"\n--- QA_FAIL items ({len(categories['qa_fail'])}) (audio plays, historical QA verdict FAIL) ---")
        for it in categories["qa_fail"]:
            qa = it.get("qa") or {}
            print(f"  {it['id']:28} [{it.get('lang','?')}/{it.get('type','?')}] {it.get('title','')[:55]} — fidelity={qa.get('min_fidelity')}")

    print(f"\nFull JSON report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
