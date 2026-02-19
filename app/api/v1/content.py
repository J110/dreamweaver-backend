"""Content browsing endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel

from app.dependencies import get_db_client, get_optional_user
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Response Models
class ContentResponse(BaseModel):
    """Response model for single content."""
    success: bool
    data: dict
    message: str


class ContentListResponse(BaseModel):
    """Response model for content list."""
    success: bool
    data: dict
    message: str


HARDCODED_CATEGORIES = [
    {"id": "adventure", "name": "Adventure", "description": "Exciting adventures"},
    {"id": "fantasy", "name": "Fantasy", "description": "Magical fantasy worlds"},
    {"id": "animals", "name": "Animals", "description": "Animal stories"},
    {"id": "bedtime", "name": "Bedtime", "description": "Calming bedtime stories"},
    {"id": "education", "name": "Educational", "description": "Learning stories"},
    {"id": "humor", "name": "Humor", "description": "Funny stories"},
]


@router.get("", response_model=ContentListResponse)
async def list_content(
    content_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    lang: Optional[str] = Query(None, description="Filter by language: 'en' or 'hi'"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    db_client=Depends(get_db_client),
) -> ContentListResponse:
    """
    List all content with optional filtering and pagination.

    Args:
        content_type: Filter by content type
        category: Filter by category
        lang: Filter by language ('en' or 'hi')
        page: Page number (1-indexed)
        page_size: Items per page
        sort_by: Sort field (created_at, view_count, like_count)
        db_client: Database client

    Returns:
        ContentListResponse with paginated content list
    """
    try:
        # Get all content
        content_docs = db_client.collection("content").get()
        items = [doc.to_dict() for doc in content_docs if doc.exists]

        # Filter by language
        if lang:
            items = [item for item in items if item.get("lang", "en") == lang]

        # Apply filters
        if content_type:
            items = [item for item in items if item.get("type") == content_type]

        if category:
            items = [item for item in items if item.get("category") == category]
        
        # Sort
        if sort_by == "view_count":
            items.sort(key=lambda x: x.get("view_count", 0), reverse=True)
        elif sort_by == "like_count":
            items.sort(key=lambda x: x.get("like_count", 0), reverse=True)
        else:  # created_at
            items.sort(key=lambda x: x.get("created_at", datetime.utcnow()), reverse=True)
        
        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = items[start:end]
        
        return ContentListResponse(
            success=True,
            data={
                "items": paginated_items,
                "total": len(items),
                "page": page,
                "page_size": page_size,
                "pages": (len(items) + page_size - 1) // page_size,
            },
            message="Content retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error listing content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list content: {str(e)}"
        )


@router.get("/categories", response_model=ContentListResponse)
async def list_categories() -> ContentListResponse:
    """Get all available content categories."""
    return ContentListResponse(
        success=True,
        data={
            "categories": HARDCODED_CATEGORIES,
        },
        message="Categories retrieved successfully"
    )


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: str,
    db_client=Depends(get_db_client),
    current_user: Optional[dict] = Depends(get_optional_user),
) -> ContentResponse:
    """
    Get single content by ID and increment view count.
    
    Args:
        content_id: ID of content to retrieve
        db_client: Database client
        current_user: Optional authenticated user
        
    Returns:
        ContentResponse with content data
        
    Raises:
        HTTPException: If content not found
    """
    try:
        content_doc = db_client.collection("content").document(content_id).get()
        
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Increment view count
        current_views = content_data.get("view_count", 0)
        db_client.collection("content").document(content_id).update({
            "view_count": current_views + 1,
            "updated_at": datetime.utcnow(),
        })
        
        # Update local copy
        content_data["view_count"] = current_views + 1

        # Add user interaction status if authenticated
        if current_user:
            user_id = current_user["uid"]
            save_id = f"{user_id}_{content_id}_save"
            save_doc = db_client.collection("interactions").document(save_id).get()
            content_data["is_saved"] = save_doc.exists
        else:
            content_data["is_saved"] = False

        return ContentResponse(
            success=True,
            data=content_data,
            message="Content retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get content: {str(e)}"
        )
