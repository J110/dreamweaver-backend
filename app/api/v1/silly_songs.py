"""Silly Songs API — Before Bed tab music content."""

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Data directory for silly song JSON files
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "silly_songs"


class SillySongsListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class SillySongResponse(BaseModel):
    success: bool
    data: dict
    message: str


def _load_all_songs() -> list[dict]:
    """Load all silly song JSON files from the data directory."""
    songs = []
    if not DATA_DIR.exists():
        return songs
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                song = json.load(fh)
                song.setdefault("id", f.stem)
                songs.append(song)
        except Exception as e:
            logger.error(f"Failed to load silly song {f}: {e}")
    return songs


def _load_song(song_id: str) -> Optional[dict]:
    """Load a single silly song by ID."""
    path = DATA_DIR / f"{song_id}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            song = json.load(f)
            song.setdefault("id", song_id)
            return song
    except Exception as e:
        logger.error(f"Failed to load silly song {song_id}: {e}")
        return None


def _save_song(song: dict) -> None:
    """Persist a silly song back to disk."""
    song_id = song.get("id")
    if not song_id:
        return
    path = DATA_DIR / f"{song_id}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(song, f, indent=2)


@router.get("", response_model=SillySongsListResponse)
async def list_silly_songs(
    age_group: Optional[str] = Query(None, description="Filter by age group: '2-5', '6-8', '9-12'"),
    lang: Optional[str] = Query("en", description="Filter by language: 'en' or 'hi'"),
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

    # Strip lyrics from list response (not needed for browsing)
    items = []
    for s in songs:
        item = {k: v for k, v in s.items() if k not in ("lyrics", "style_prompt")}
        items.append(item)

    return SillySongsListResponse(
        success=True,
        data={"items": items, "total": len(items)},
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
