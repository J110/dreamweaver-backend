"""Admin endpoints for backend management (content reload, etc.)."""

import os

from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel

from app.dependencies import _check_local_mode
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ReloadResponse(BaseModel):
    success: bool
    data: dict
    message: str


@router.post("/reload", response_model=ReloadResponse)
async def reload_content(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> ReloadResponse:
    """
    Reload content from seed_output/content.json without restarting.

    Requires X-Admin-Key header matching ADMIN_API_KEY env var.
    Called by the pipeline after writing new content.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
        )

    if x_admin_key != admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key",
        )

    if not _check_local_mode():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reload only available in LocalStore mode",
        )

    from app.services.local_store import get_local_store
    store = get_local_store()
    result = store.reload_content()

    logger.info(
        "Content reloaded via admin API: %d -> %d items (%+d)",
        result["previous_count"],
        result["current_count"],
        result["added"],
    )

    return ReloadResponse(
        success=True,
        data=result,
        message=f"Reloaded. {result['current_count']} items ({result['added']:+d} new).",
    )
