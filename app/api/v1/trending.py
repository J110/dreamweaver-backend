"""Trending content endpoints."""

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
    """Calculate trending score based on likes and views."""
    likes = content.get("like_count", 0)
    views = content.get("view_count", 0)
    return (likes * 5) + views


@router.get("", response_model=TrendingResponse)
async def get_trending(
    limit: int = Query(20, ge=1, le=100),
    lang: Optional[str] = Query(None, description="Filter by language: 'en' or 'hi'"),
    db_client=Depends(get_db_client),
) -> TrendingResponse:
    """
    Get trending content sorted by engagement (likes * 5 + views).

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
    limit: int = Query(20, ge=1, le=100),
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
    limit: int = Query(20, ge=1, le=100),
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
