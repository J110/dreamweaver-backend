"""Lullaby endpoints — serves test lullabies from seed_output/lullabies/."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Lullabies data loaded from seed_output/lullabies/lullabies.json
LULLABIES_PATH = Path(__file__).parent.parent.parent.parent / "seed_output" / "lullabies" / "lullabies.json"


def _load_lullabies() -> list:
    """Load lullabies from JSON file. Returns empty list if file missing."""
    if not LULLABIES_PATH.exists():
        logger.warning(f"Lullabies file not found: {LULLABIES_PATH}")
        return []
    try:
        return json.loads(LULLABIES_PATH.read_text())
    except Exception as e:
        logger.error(f"Failed to load lullabies: {e}")
        return []


class LullabyListResponse(BaseModel):
    success: bool
    data: dict
    message: str


class LullabyResponse(BaseModel):
    success: bool
    data: dict
    message: str


@router.get("", response_model=LullabyListResponse)
async def list_lullabies():
    """List all available lullabies."""
    lullabies = _load_lullabies()
    return {
        "success": True,
        "data": {"items": lullabies, "total": len(lullabies)},
        "message": f"Found {len(lullabies)} lullabies",
    }


@router.get("/{lullaby_id}", response_model=LullabyResponse)
async def get_lullaby(lullaby_id: str):
    """Get a single lullaby by ID."""
    lullabies = _load_lullabies()
    for lullaby in lullabies:
        if lullaby["id"] == lullaby_id:
            return {
                "success": True,
                "data": lullaby,
                "message": "Lullaby found",
            }
    raise HTTPException(status_code=404, detail=f"Lullaby {lullaby_id} not found")
