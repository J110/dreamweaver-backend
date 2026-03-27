"""Trending content endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel

from app.dependencies import get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Response Models
class TrendingResponse(BaseModel):
    """Response model for trending content."""
    success: bool
    data: dict
    message: str


def _calculate_trending_score(content: dict) -> float:
    """Calculate trending score with recency boost.

    New content (< 7 days) gets a bonus so it always appears in results.
    The bonus decays linearly from 1000 (brand new) to 0 (7+ days old).
    """
    likes = content.get("like_count", 0)
    views = content.get("view_count", 0)
    engagement = (likes * 5) + views

    # Recency boost: new stories surface immediately
    created = content.get("created_at", "")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
            if age_days < 7:
                engagement += 1000 * (1 - age_days / 7)
        except (ValueError, TypeError):
            pass

    return engagement


@router.get("", response_model=TrendingResponse)
async def get_trending(
    limit: int = Query(20, ge=1, le=200),
    lang: Optional[str] = Query(None, description="Filter by language: 'en' or 'hi'"),
    language_level: Optional[str] = Query(None, description="Filter by language level: 'basic', 'intermediate', or 'advanced'"),
    db_client=Depends(get_db_client),
) -> TrendingResponse:
    """
    Get trending content sorted by engagement + recency boost.

    Args:
        limit: Maximum number of items to return
        lang: Optional language filter ('en' or 'hi')
        db_client: Database client

    Returns:
        TrendingResponse with trending content list
    """
    try:
        # Get all content
        content_docs = db_client.collection("content").get()
        items = [doc.to_dict() for doc in content_docs if doc.exists]

        # Filter by language if specified
        if lang:
            items = [item for item in items if item.get("lang", "en") == lang]

        # Filter by language level if specified
        if language_level:
            items = [item for item in items if item.get("language_level") == language_level]

        # Sort by trending score (includes recency boost)
        items.sort(key=_calculate_trending_score, reverse=True)

        # Limit results
        items = items[:limit]

        return TrendingResponse(
            success=True,
            data={
                "items": items,
                "total": len(items),
                "limit": limit,
            },
            message="Trending content retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error fetching trending content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch trending content: {str(e)}"
        )


@router.get("/weekly", response_model=TrendingResponse)
async def get_weekly_trending(
    limit: int = Query(20, ge=1, le=200),
    db_client=Depends(get_db_client),
) -> TrendingResponse:
    """
    Get weekly trending content (same as regular trending in local mode).
    
    Args:
        limit: Maximum number of items to return
        db_client: Database client
        
    Returns:
        TrendingResponse with trending content list
    """
    try:
        # Get all content
        content_docs = db_client.collection("content").get()
        items = [doc.to_dict() for doc in content_docs if doc.exists]
        
        # Sort by trending score
        items.sort(key=_calculate_trending_score, reverse=True)
        
        # Limit results
        items = items[:limit]
        
        return TrendingResponse(
            success=True,
            data={
                "items": items,
                "total": len(items),
                "limit": limit,
                "period": "weekly",
            },
            message="Weekly trending content retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error fetching weekly trending: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch weekly trending: {str(e)}"
        )


@router.get("/by-category/{category}", response_model=TrendingResponse)
async def get_trending_by_category(
    category: str,
    limit: int = Query(20, ge=1, le=200),
    db_client=Depends(get_db_client),
) -> TrendingResponse:
    """
    Get trending content filtered by category.
    
    Args:
        category: Category to filter by
        limit: Maximum number of items to return
        db_client: Database client
        
    Returns:
        TrendingResponse with filtered trending content
    """
    try:
        # Get all content
        content_docs = db_client.collection("content").get()
        items = [doc.to_dict() for doc in content_docs if doc.exists]
        
        # Filter by category
        items = [item for item in items if item.get("category") == category]
        
        # Sort by trending score
        items.sort(key=_calculate_trending_score, reverse=True)
        
        # Limit results
        items = items[:limit]
        
        return TrendingResponse(
            success=True,
            data={
                "items": items,
                "total": len(items),
                "limit": limit,
                "category": category,
            },
            message="Category trending content retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error fetching category trending: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch category trending: {str(e)}"
        )
