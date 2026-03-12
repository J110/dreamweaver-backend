"""
Clips API — list, download, preview, and manage social media clips.

Auth: BLOG_SECRET_KEY Bearer token (same as analytics dashboard).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import FileResponse

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

CLIPS_DIR = Path(os.getenv("CLIPS_DIR", "clips"))


# ── Auth ─────────────────────────────────────────────────────────────

def verify_clips_key(authorization: Optional[str] = Header(None)):
    """Verify Bearer token against BLOG_SECRET_KEY env var."""
    key = os.getenv("BLOG_SECRET_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="Secret key not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing or invalid")
    token = authorization.replace("Bearer ", "")
    if token != key:
        raise HTTPException(status_code=401, detail="Invalid key")


# ── List clips ───────────────────────────────────────────────────────

@router.get("/")
async def list_clips(
    authorization: Optional[str] = Header(None),
    mood: Optional[str] = Query(None),
    age_group: Optional[str] = Query(None, alias="ageGroup"),
    voice: Optional[str] = Query(None),
    content_type: Optional[str] = Query(None, alias="contentType"),
    posted: Optional[str] = Query(None),
    sort: str = Query("newest"),
):
    """List all clips with optional filters."""
    verify_clips_key(authorization)

    if not CLIPS_DIR.exists():
        return {"clips": [], "total": 0}

    clips = []
    for meta_file in CLIPS_DIR.glob("*_clip.json"):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Apply filters
        if mood and meta.get("mood") != mood:
            continue
        if age_group and meta.get("ageGroup") != age_group:
            continue
        if voice and meta.get("voice") != voice:
            continue
        if content_type and meta.get("contentType") != content_type:
            continue
        if posted == "posted" and not any(meta.get("posted", {}).values()):
            continue
        if posted == "unposted" and any(meta.get("posted", {}).values()):
            continue

        # Verify MP4 exists
        mp4_path = CLIPS_DIR / meta.get("filename", "")
        if not mp4_path.exists():
            continue

        # Add file size if missing
        if not meta.get("fileSize"):
            meta["fileSize"] = mp4_path.stat().st_size

        clips.append(meta)

    # Sort
    if sort == "newest":
        clips.sort(key=lambda c: c.get("generatedAt", ""), reverse=True)
    elif sort == "oldest":
        clips.sort(key=lambda c: c.get("generatedAt", ""))
    elif sort == "title":
        clips.sort(key=lambda c: c.get("title", "").lower())

    return {"clips": clips, "total": len(clips)}


# ── Download clip ────────────────────────────────────────────────────

@router.get("/{story_id}/{voice}/download")
async def download_clip(
    story_id: str,
    voice: str,
    authorization: Optional[str] = Header(None),
):
    """Download a clip MP4."""
    verify_clips_key(authorization)

    mp4_path = CLIPS_DIR / f"{story_id}_{voice}_clip.mp4"
    if not mp4_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    return FileResponse(
        mp4_path,
        media_type="video/mp4",
        filename=f"dreamvalley-{story_id}-{voice}.mp4",
    )


# ── Preview clip ─────────────────────────────────────────────────────

@router.get("/{story_id}/{voice}/preview")
async def preview_clip(
    story_id: str,
    voice: str,
    authorization: Optional[str] = Header(None),
):
    """Stream a clip MP4 for preview."""
    verify_clips_key(authorization)

    mp4_path = CLIPS_DIR / f"{story_id}_{voice}_clip.mp4"
    if not mp4_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    return FileResponse(mp4_path, media_type="video/mp4")


# ── Mark posted ──────────────────────────────────────────────────────

@router.put("/{story_id}/{voice}/posted")
async def mark_posted(
    story_id: str,
    voice: str,
    platform: str = Query(..., description="Platform: youtube, instagram, tiktok"),
    authorization: Optional[str] = Header(None),
):
    """Mark a clip as posted to a platform."""
    verify_clips_key(authorization)

    if platform not in ("youtube", "instagram", "tiktok"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    meta_path = CLIPS_DIR / f"{story_id}_{voice}_clip.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Clip metadata not found")

    with open(meta_path) as f:
        meta = json.load(f)

    meta.setdefault("posted", {})
    meta["posted"][platform] = datetime.now(timezone.utc).isoformat()

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {"status": "ok", "posted": meta["posted"]}


# ── Unmark posted ────────────────────────────────────────────────────

@router.put("/{story_id}/{voice}/unpost")
async def unmark_posted(
    story_id: str,
    voice: str,
    platform: str = Query(..., description="Platform: youtube, instagram, tiktok"),
    authorization: Optional[str] = Header(None),
):
    """Remove posted status for a clip on a platform."""
    verify_clips_key(authorization)

    if platform not in ("youtube", "instagram", "tiktok"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    meta_path = CLIPS_DIR / f"{story_id}_{voice}_clip.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Clip metadata not found")

    with open(meta_path) as f:
        meta = json.load(f)

    meta.setdefault("posted", {})
    meta["posted"][platform] = None

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {"status": "ok", "posted": meta["posted"]}
