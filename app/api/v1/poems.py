"""Poems API — Before Bed tab musical poems content."""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import get_optional_user
from app.utils.backlog import filter_by_backlog
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Per-(type, lang) bucket layout, matching PER_CONTENT_DIRS in
# app.services.local_store. EN items live in poems/, HI items in
# poems_hi/. List/load helpers walk both buckets; _save_poem preserves
# the existing bucket of an item or routes new items by lang.
_BASE = Path(__file__).resolve().parents[3] / "data"
DATA_DIRS = [_BASE / "poems", _BASE / "poems_hi"]
DATA_DIR = DATA_DIRS[0]  # backwards-compat alias if any external code references it


class PoemsListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class PoemResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _load_all_poems() -> list[dict]:
    """Load all poem JSON files from every bucket."""
    poems = []
    for d in DATA_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                with open(f) as fh:
                    poem = json.load(fh)
                    poem.setdefault("id", f.stem)
                    poems.append(poem)
            except Exception as e:
                logger.error(f"Failed to load poem {f}: {e}")
    return poems


def _load_poem(poem_id: str) -> Optional[dict]:
    """Load a single poem by ID, searching every bucket."""
    for d in DATA_DIRS:
        path = d / f"{poem_id}.json"
        if not path.exists():
            continue
        try:
            with open(path) as f:
                poem = json.load(f)
                poem.setdefault("id", poem_id)
                return poem
        except Exception as e:
            logger.error(f"Failed to load poem {poem_id} from {path}: {e}")
    return None


def _save_poem(poem: dict) -> None:
    """Persist a poem back to disk.

    If the poem already exists in one of the buckets, write to that bucket.
    Otherwise route by lang: HI items go to poems_hi/, everything else
    to poems/.
    """
    poem_id = poem.get("id")
    if not poem_id:
        return
    # Preserve existing bucket
    for d in DATA_DIRS:
        existing = d / f"{poem_id}.json"
        if existing.exists():
            d.mkdir(parents=True, exist_ok=True)
            with open(existing, "w") as f:
                json.dump(poem, f, indent=2)
            return
    # New poem — route by lang
    target_dir = DATA_DIRS[1] if poem.get("lang") == "hi" else DATA_DIRS[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / f"{poem_id}.json", "w") as f:
        json.dump(poem, f, indent=2)


@router.get("", response_model=PoemsListResponse)
async def list_poems(
    age_group: Optional[str] = Query(None, description="Filter by age group: '2-5', '6-8', '9-12'"),
    lang: Optional[str] = Query("en", description="Filter by language: 'en' or 'hi'"),
    current_user: Optional[Dict[str, str]] = Depends(get_optional_user),
) -> PoemsListResponse:
    """List all poems, optionally filtered by age group and language."""
    poems = _load_all_poems()

    if age_group:
        poems = [p for p in poems if p.get("age_group") == age_group]

    if lang:
        poems = [p for p in poems if p.get("lang", "en") == lang]

    # Only return poems that have audio
    poems = [p for p in poems if p.get("audio_file")]

    # Sort by created_at descending (newest first)
    poems.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Phase 0 step 1.4e: backlog gating per tier (Free 3d / Premium 30d).
    poems, tier_window_cutoff_at = filter_by_backlog(poems, current_user)

    # Strip heavy fields from list response
    items = []
    for p in poems:
        item = {k: v for k, v in p.items() if k not in ("poem_text", "style_prompt", "cover_context")}
        items.append(item)

    return PoemsListResponse(
        success=True,
        data={
            "items": items,
            "total": len(items),
            "tier_window_cutoff_at": tier_window_cutoff_at,
        },
        message="Poems retrieved successfully",
    )


@router.get("/{poem_id}", response_model=PoemResponse)
async def get_poem(poem_id: str) -> PoemResponse:
    """Get a single poem by ID (includes full text)."""
    poem = _load_poem(poem_id)
    if not poem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Poem not found",
        )
    return PoemResponse(
        success=True,
        data=poem,
        message="Poem retrieved successfully",
    )


@router.post("/{poem_id}/play", response_model=PoemResponse)
async def play_poem(poem_id: str) -> PoemResponse:
    """Increment play count for a poem (first play in session)."""
    poem = _load_poem(poem_id)
    if not poem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Poem not found",
        )
    poem["play_count"] = poem.get("play_count", 0) + 1
    _save_poem(poem)
    return PoemResponse(
        success=True,
        data={"play_count": poem["play_count"]},
        message="Play recorded",
    )


@router.post("/{poem_id}/replay", response_model=PoemResponse)
async def replay_poem(poem_id: str) -> PoemResponse:
    """Increment replay count for a poem (subsequent plays in session)."""
    poem = _load_poem(poem_id)
    if not poem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Poem not found",
        )
    poem["replay_count"] = poem.get("replay_count", 0) + 1
    _save_poem(poem)
    return PoemResponse(
        success=True,
        data={"replay_count": poem["replay_count"]},
        message="Replay recorded",
    )
