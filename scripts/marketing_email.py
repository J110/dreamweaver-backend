#!/usr/bin/env python3
"""marketing_email.py — email the day's new marketing assets (audio + FLUX cover).

Per language per day, emails up to three items from the day's NEW creations:
  1. Musical poem      (type == "poem")
  2. Short story       (type == "story")
  3. Long-story song   (the standalone mid-story song, NOT the full narration)

Each item is attached as its audio file plus its FLUX cover (.webp). Called at
the end of pipeline_run.py (EN) and pipeline_run_hi.py (HI).

Standalone:
    python3 scripts/marketing_email.py --lang en [--dry-run]
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("marketing_email")

BASE_DIR = Path(__file__).parent.parent
WEB_DIR = BASE_DIR.parent / "dreamweaver-web"
AUDIO_ROOTS = [WEB_DIR / "public" / "audio", Path("/opt/audio-store")]
COVER_ROOTS = [Path(os.getenv("COVER_OUTPUT_DIR", "/opt/cover-store")),
               WEB_DIR / "public" / "covers"]
CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
EPISODE_DIR = BASE_DIR / "seed_output"            # holds episode_* dirs (EN long story)
HINDI_LONG_DIR = BASE_DIR / "seed_output" / "hindi_long"


def _today() -> str:
    return date.today().isoformat()


def _is_today(item: Dict[str, Any]) -> bool:
    return (item.get("addedAt") or item.get("created_at") or "")[:10] == _today()


def _lang_of(item: Dict[str, Any]) -> str:
    return item.get("lang") or item.get("language") or "en"


def _audio_candidate_urls(item: Dict[str, Any], lang: str) -> List[str]:
    """`/audio/...` URLs to try, in order. Many items have a null audio_url,
    so fall back to the on-disk naming convention by type."""
    urls: List[str] = []
    if item.get("audio_url"):
        urls.append(item["audio_url"])
    for v in (item.get("audio_variants") or []):
        if v.get("url"):
            urls.append(v["url"])
    cid = item.get("id", "")
    if item.get("type") == "poem":
        primary = "poems-hi" if lang == "hi" else "poems"
        urls += [f"/audio/{primary}/{cid}.mp3",
                 f"/audio/poems/{cid}.mp3", f"/audio/poems-hi/{cid}.mp3"]
    elif item.get("subtype") == "silly_song":
        urls.append(f"/audio/silly-songs/{cid}.mp3")
    return urls


def _resolve_audio(item: Dict[str, Any], lang: str) -> Optional[Path]:
    for url in _audio_candidate_urls(item, lang):
        rel = url.split("/audio/", 1)[-1].lstrip("/")
        for base in AUDIO_ROOTS:
            p = base / rel
            if p.exists():
                return p
    return None


def _resolve_cover(item: Dict[str, Any]) -> Optional[Path]:
    """Resolve the canonical cover file. Trust the item's declared ``cover``
    field first (.webp, or the .svg that is the composed FLUX cover the app
    renders). Only when the field is missing/broken fall back to {id} files in
    the cover stores, EXCLUDING FLUX intermediates ({id}_vN.webp — those are
    progressively-blank generation artifacts, not the cover)."""
    cid = item.get("id", "")
    cover = item.get("cover") or ""
    field_rel = cover.split("/covers/", 1)[-1].lstrip("/") if "/covers/" in cover else ""
    # 1. Trust the declared cover (webp or svg).
    if field_rel:
        for base in COVER_ROOTS:
            p = base / field_rel
            if p.exists():
                return p
    # 2. Fallback for null/broken cover fields. Skip {id}_vN.webp junk.
    if cid:
        for base in COVER_ROOTS:
            webps = [w for w in sorted(base.glob(f"**/{cid}*.webp"))
                     if not re.search(r"_v\d+\.webp$", w.name)]
            exact = [w for w in webps if w.stem == cid]
            if exact:
                return exact[0]
            if webps:
                return webps[0]
            svgs = sorted(base.glob(f"**/{cid}*.svg"))
            if svgs:
                return svgs[0]
    return None


def _attachable_cover(cover: Path) -> Optional[Path]:
    """Return a raster image to attach. SVG covers are rasterized to PNG via
    cairosvg (the SVG embeds the real FLUX webp + overlay — the composed cover
    users actually see); other formats pass through unchanged."""
    if cover.suffix.lower() != ".svg":
        return cover
    try:
        import cairosvg
        out = Path(tempfile.gettempdir()) / f"{cover.stem}_cover.png"
        cairosvg.svg2png(url=str(cover), write_to=str(out),
                         output_width=1024, output_height=1024)
        return out if out.exists() else None
    except Exception as e:
        logger.warning("  cover rasterize failed for %s: %s", cover, e)
        return None


def _trim_audio(src: Optional[Path], seconds: int = 60) -> Optional[Path]:
    """Trim to the first ``seconds`` as a marketing teaser (short stories run
    longer than a minute). Falls back to the untrimmed file if ffmpeg is
    unavailable or fails; a source shorter than ``seconds`` passes through."""
    if not src or not src.exists():
        return src
    out = Path(tempfile.gettempdir()) / f"{src.stem}_teaser.mp3"
    try:
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-t", str(seconds), "-c", "copy", str(out)],
            check=True,
        )
        return out if out.exists() and out.stat().st_size > 0 else src
    except Exception as e:
        logger.warning("  audio trim failed for %s: %s", src, e)
        return src


def _en_long_story_song(item: Dict[str, Any]) -> Optional[Path]:
    """Newest seed_output/episode_*/song.mp3, preferring the episode whose
    metadata title matches this long story."""
    title = (item.get("title") or "").strip()
    title_en = (item.get("title_en") or "").strip()
    dirs = sorted(EPISODE_DIR.glob("episode_*"),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    newest: Optional[Path] = None
    for d in dirs:
        song = d / "song.mp3"
        if not song.exists():
            continue
        if newest is None:
            newest = song
        meta = d / "metadata.json"
        if meta.exists() and title:
            try:
                mt = (json.loads(meta.read_text()).get("title") or "").strip()
                if mt and mt in (title, title_en):
                    return song
            except Exception:
                pass
    return newest


def _long_story_song(item: Dict[str, Any], lang: str) -> Optional[Path]:
    if lang == "hi":
        p = HINDI_LONG_DIR / f"{item.get('id')}_song.mp3"
        return p if p.exists() else None
    return _en_long_story_song(item)


def _pick_today(items: List[Dict[str, Any]], lang: str,
                pred: Callable[[Dict[str, Any]], bool]) -> Optional[Dict[str, Any]]:
    xs = [s for s in items if isinstance(s, dict) and _is_today(s)
          and _lang_of(s) == lang and pred(s)]
    xs.sort(key=lambda s: (s.get("addedAt") or s.get("created_at") or ""), reverse=True)
    return xs[0] if xs else None


def collect_assets(lang: str, content_path: Path = CONTENT_PATH) -> List[Dict[str, Any]]:
    items = json.loads(Path(content_path).read_text())
    plan = [
        ("Musical poem",
         _pick_today(items, lang, lambda s: s.get("type") == "poem"),
         lambda it: _resolve_audio(it, lang)),
        ("Short story",
         _pick_today(items, lang, lambda s: s.get("type") == "story"),
         lambda it: _trim_audio(_resolve_audio(it, lang), 60)),
        ("Long-story song",
         _pick_today(items, lang, lambda s: s.get("type") == "long_story"),
         lambda it: _long_story_song(it, lang)),
    ]
    assets: List[Dict[str, Any]] = []
    for label, item, audio_fn in plan:
        if not item:
            logger.info("  [%s] no new %s today", lang, label)
            continue
        audio = audio_fn(item)
        cover = _resolve_cover(item)
        cover = _attachable_cover(cover) if cover else None
        if not audio or not audio.exists():
            logger.warning("  [%s] %s '%s' — audio not found, skipping",
                           lang, label, item.get("title"))
            continue
        if not cover:
            logger.warning("  [%s] %s '%s' — cover not found, skipping",
                           lang, label, item.get("title"))
            continue
        assets.append({"label": label, "title": item.get("title") or item.get("id"),
                       "id": item.get("id"), "audio": str(audio), "cover": str(cover)})
    return assets


def email_daily_marketing_assets(lang: str, content_path: Path = CONTENT_PATH,
                                 dry_run: bool = False) -> bool:
    assets = collect_assets(lang, content_path)
    if not assets:
        logger.info("  [%s] no marketing assets to email today", lang)
        return False
    logger.info("  [%s] %d marketing asset(s): %s", lang, len(assets),
                ", ".join(a["label"] for a in assets))
    if dry_run:
        for a in assets:
            logger.info("    %s — %s | audio=%s | cover=%s",
                        a["label"], a["title"], a["audio"], a["cover"])
        return True
    try:
        from pipeline_notify import send_marketing_assets
    except ImportError:
        import sys
        sys.path.insert(0, str(BASE_DIR / "scripts"))
        from pipeline_notify import send_marketing_assets
    return send_marketing_assets(lang, assets)


if __name__ == "__main__":
    import argparse
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Email the day's marketing assets")
    ap.add_argument("--lang", default="en", choices=["en", "hi"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ok = email_daily_marketing_assets(args.lang, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)
