"""Funny Shorts API — Before Bed tab content."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Data directory for funny shorts JSON files
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "funny_shorts"


class FunnyShortsListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class FunnyShortResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _load_all_shorts() -> list[dict]:
    """Load all funny short JSON files from the data directory."""
    shorts = []
    if not DATA_DIR.exists():
        return shorts
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                short = json.load(fh)
                short.setdefault("id", f.stem)
                shorts.append(short)
        except Exception as e:
            logger.error(f"Failed to load funny short {f}: {e}")
    return shorts


def _load_short(short_id: str) -> Optional[dict]:
    """Load a single funny short by ID."""
    path = DATA_DIR / f"{short_id}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            short = json.load(f)
            short.setdefault("id", short_id)
            return short
    except Exception as e:
        logger.error(f"Failed to load funny short {short_id}: {e}")
        return None


def _save_short(short: dict) -> None:
    """Persist a funny short back to disk."""
    short_id = short.get("id")
    if not short_id:
        return
    path = DATA_DIR / f"{short_id}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(short, f, indent=2)


@router.get("", response_model=FunnyShortsListResponse)
async def list_funny_shorts(
    age_group: Optional[str] = Query(None, description="Filter by age group: '2-5', '6-8', '9-12'"),
) -> FunnyShortsListResponse:
    """List all funny shorts, optionally filtered by age group."""
    shorts = _load_all_shorts()

    if age_group:
        shorts = [s for s in shorts if s.get("age_group") == age_group]

    # Sort by created_at descending (newest first)
    shorts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Strip script from list response (it's large and not needed for browsing)
    items = []
    for s in shorts:
        item = {k: v for k, v in s.items() if k != "script"}
        items.append(item)

    return FunnyShortsListResponse(
        success=True,
        data={"items": items, "total": len(items)},
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
