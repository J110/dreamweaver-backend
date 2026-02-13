"""Content search endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel

from app.dependencies import get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Response Models
class SearchResponse(BaseModel):
    """Response model for search results."""
    success: bool
    data: dict
    message: str


@router.get("", response_model=SearchResponse)
async def search_content(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    db_client=Depends(get_db_client),
) -> SearchResponse:
    """
    Search content by query string (case-insensitive match on title and description).
    
    Args:
        q: Search query string
        limit: Maximum number of results to return
        db_client: Database client
        
    Returns:
        SearchResponse with matching content
    """
    try:
        # Get all content
        content_docs = db_client.collection("content").get()
        items = [doc.to_dict() for doc in content_docs if doc.exists]
        
        # Filter by query (case-insensitive search on title and description)
        query_lower = q.lower()
        matching_items = []
        
        for item in items:
            title = item.get("title", "").lower()
            description = item.get("description", "").lower()
            theme = item.get("theme", "").lower()
            category = item.get("category", "").lower()
            
            if (query_lower in title or 
                query_lower in description or 
                query_lower in theme or
                query_lower in category):
                matching_items.append(item)
        
        # Limit results
        matching_items = matching_items[:limit]
        
        return SearchResponse(
            success=True,
            data={
                "query": q,
                "results": matching_items,
                "total": len(matching_items),
                "limit": limit,
            },
            message="Search completed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error searching content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )
