"""Silly Songs API — Before Bed tab music content."""

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
# app.services.local_store. EN items live in silly_songs/, HI items in
# silly_songs_hi/. List/load helpers walk both buckets; _save_song
# preserves the existing bucket of an item or routes new items by lang.
_BASE = Path(__file__).resolve().parents[3] / "data"
DATA_DIRS = [_BASE / "silly_songs", _BASE / "silly_songs_hi"]
DATA_DIR = DATA_DIRS[0]  # backwards-compat alias if any external code references it


class SillySongsListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class SillySongResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _load_all_songs() -> list[dict]:
    """Load all silly song JSON files from every bucket."""
    songs = []
    for d in DATA_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                with open(f) as fh:
                    song = json.load(fh)
                    song.setdefault("id", f.stem)
                    songs.append(song)
            except Exception as e:
                logger.error(f"Failed to load silly song {f}: {e}")
    return songs


def _load_song(song_id: str) -> Optional[dict]:
    """Load a single silly song by ID, searching every bucket."""
    for d in DATA_DIRS:
        path = d / f"{song_id}.json"
        if not path.exists():
            continue
        try:
            with open(path) as f:
                song = json.load(f)
                song.setdefault("id", song_id)
                return song
        except Exception as e:
            logger.error(f"Failed to load silly song {song_id} from {path}: {e}")
    return None


def _save_song(song: dict) -> None:
    """Persist a silly song back to disk.

    If the song already exists in one of the buckets, write to that bucket.
    Otherwise route by lang: HI items go to silly_songs_hi/, everything else
    to silly_songs/.
    """
    song_id = song.get("id")
    if not song_id:
        return
    # Preserve existing bucket if the song is already on disk
    for d in DATA_DIRS:
        existing = d / f"{song_id}.json"
        if existing.exists():
            d.mkdir(parents=True, exist_ok=True)
            with open(existing, "w") as f:
                json.dump(song, f, indent=2)
            return
    # New song — route by lang
    target_dir = DATA_DIRS[1] if song.get("lang") == "hi" else DATA_DIRS[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / f"{song_id}.json", "w") as f:
        json.dump(song, f, indent=2)


@router.get("", response_model=SillySongsListResponse)
async def list_silly_songs(
    age_group: Optional[str] = Query(None, description="Filter by age group: '2-5', '6-8', '9-12'"),
    lang: Optional[str] = Query("en", description="Filter by language: 'en' or 'hi'"),
    current_user: Optional[Dict[str, str]] = Depends(get_optional_user),
) -> SillySongsListResponse:
    """List all silly songs, optionally filtered by age group and language."""
    songs = _load_all_songs()

    if age_group:
        songs = [s for s in songs if s.get("age_group") == age_group]

    if lang:
        songs = [s for s in songs if s.get("lang", "en") == lang]

    # Only return songs that have audio
    songs = [s for s in songs if s.get("audio_file")]

    # Sort by created_at descending (newest first)
    songs.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Phase 0 step 1.4e: backlog gating per tier (Free 3d / Premium 30d).
    songs, tier_window_cutoff_at = filter_by_backlog(songs, current_user)

    # Strip lyrics from list response (not needed for browsing)
    items = []
    for s in songs:
        item = {k: v for k, v in s.items() if k not in ("lyrics", "style_prompt")}
        items.append(item)

    return SillySongsListResponse(
        success=True,
        data={
            "items": items,
            "total": len(items),
            "tier_window_cutoff_at": tier_window_cutoff_at,
        },
        message="Silly songs retrieved successfully",
    )


@router.get("/{song_id}", response_model=SillySongResponse)
async def get_silly_song(song_id: str) -> SillySongResponse:
    """Get a single silly song by ID (includes lyrics)."""
    song = _load_song(song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Silly song not found",
        )
    return SillySongResponse(
        success=True,
        data=song,
        message="Silly song retrieved successfully",
    )


@router.post("/{song_id}/play", response_model=SillySongResponse)
async def play_silly_song(song_id: str) -> SillySongResponse:
    """Increment play count for a silly song (first play in session)."""
    song = _load_song(song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Silly song not found",
        )
    song["play_count"] = song.get("play_count", 0) + 1
    _save_song(song)
    return SillySongResponse(
        success=True,
        data={"play_count": song["play_count"]},
        message="Play recorded",
    )


@router.post("/{song_id}/replay", response_model=SillySongResponse)
async def replay_silly_song(song_id: str) -> SillySongResponse:
    """Increment replay count for a silly song (subsequent plays in session)."""
    song = _load_song(song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Silly song not found",
        )
    song["replay_count"] = song.get("replay_count", 0) + 1
    _save_song(song)
    return SillySongResponse(
        success=True,
        data={"replay_count": song["replay_count"]},
        message="Replay recorded",
    )
