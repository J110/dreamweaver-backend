"""Funny Shorts API — Before Bed tab content."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import admin_bypass, get_optional_user
from app.utils.backlog import filter_by_backlog
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Per-(type, lang) bucket layout, matching PER_CONTENT_DIRS in
# app.services.local_store. EN items live in funny_shorts/, HI items
# in funny_shorts_hi/. List/load helpers walk both buckets;
# _save_short preserves an item's existing bucket or routes new
# items by lang.
_BASE = Path(__file__).resolve().parents[3] / "data"
DATA_DIRS = [_BASE / "funny_shorts", _BASE / "funny_shorts_hi"]
DATA_DIR = DATA_DIRS[0]  # backwards-compat alias if any external code references it


class FunnyShortsListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class FunnyShortResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _load_all_shorts() -> list[dict]:
    """Load all funny short JSON files from every bucket."""
    shorts = []
    for d in DATA_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                with open(f) as fh:
                    short = json.load(fh)
                    short.setdefault("id", f.stem)
                    shorts.append(short)
            except Exception as e:
                logger.error(f"Failed to load funny short {f}: {e}")
    return shorts


def _load_short(short_id: str) -> Optional[dict]:
    """Load a single funny short by ID, searching every bucket."""
    for d in DATA_DIRS:
        path = d / f"{short_id}.json"
        if not path.exists():
            continue
        try:
            with open(path) as f:
                short = json.load(f)
                short.setdefault("id", short_id)
                return short
        except Exception as e:
            logger.error(f"Failed to load funny short {short_id} from {path}: {e}")
    return None


def _save_short(short: dict) -> None:
    """Persist a funny short back to disk.

    If the short already exists in one of the buckets, write to that
    bucket. Otherwise route by lang: HI items go to funny_shorts_hi/,
    everything else to funny_shorts/.
    """
    short_id = short.get("id")
    if not short_id:
        return
    # Preserve existing bucket if the short is already on disk
    for d in DATA_DIRS:
        existing = d / f"{short_id}.json"
        if existing.exists():
            d.mkdir(parents=True, exist_ok=True)
            with open(existing, "w") as f:
                json.dump(short, f, indent=2)
            return
    # New short — route by lang
    target_dir = DATA_DIRS[1] if short.get("lang") == "hi" else DATA_DIRS[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / f"{short_id}.json", "w") as f:
        json.dump(short, f, indent=2)


@router.get("", response_model=FunnyShortsListResponse)
async def list_funny_shorts(
    age_group: Optional[str] = Query(None, description="Filter by age group: '2-5', '6-8', '9-12'"),
    lang: Optional[str] = Query("en", description="Filter by language: 'en' or 'hi'"),
    current_user: Optional[Dict[str, str]] = Depends(get_optional_user),
    bypass: bool = Depends(admin_bypass),
) -> FunnyShortsListResponse:
    """List all funny shorts, optionally filtered by age group and language."""
    shorts = _load_all_shorts()

    if age_group:
        shorts = [s for s in shorts if s.get("age_group") == age_group]

    if lang:
        shorts = [s for s in shorts if s.get("lang", "en") == lang]

    # Sort by created_at descending (newest first)
    shorts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Phase 0 step 1.4e: backlog gating per tier (Free 3d / Premium 30d).
    shorts, tier_window_cutoff_at = filter_by_backlog(shorts, current_user, bypass=bypass)

    # Strip script from list response (it's large and not needed for browsing)
    items = []
    for s in shorts:
        item = {k: v for k, v in s.items() if k != "script"}
        items.append(item)

    return FunnyShortsListResponse(
        success=True,
        data={
            "items": items,
            "total": len(items),
            "tier_window_cutoff_at": tier_window_cutoff_at,
        },
        message="Funny shorts retrieved successfully",
    )


@router.get("/{short_id}", response_model=FunnyShortResponse)
async def get_funny_short(short_id: str) -> FunnyShortResponse:
    """Get a single funny short by ID (includes script)."""
    short = _load_short(short_id)
    if not short:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Funny short not found",
        )
    return FunnyShortResponse(
        success=True,
        data=short,
        message="Funny short retrieved successfully",
    )


@router.post("/{short_id}/play", response_model=FunnyShortResponse)
async def play_funny_short(short_id: str) -> FunnyShortResponse:
    """Increment play count for a funny short (first play in session)."""
    short = _load_short(short_id)
    if not short:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Funny short not found",
        )
    short["play_count"] = short.get("play_count", 0) + 1
    _save_short(short)
    return FunnyShortResponse(
        success=True,
        data={"play_count": short["play_count"]},
        message="Play recorded",
    )


@router.post("/{short_id}/replay", response_model=FunnyShortResponse)
async def replay_funny_short(short_id: str) -> FunnyShortResponse:
    """Increment replay count for a funny short (subsequent plays in session)."""
    short = _load_short(short_id)
    if not short:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Funny short not found",
        )
    short["replay_count"] = short.get("replay_count", 0) + 1
    _save_short(short)
    return FunnyShortResponse(
        success=True,
        data={"replay_count": short["replay_count"]},
        message="Replay recorded",
    )
