"""User interaction endpoints for likes, saves, etc."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Response Models
class InteractionResponse(BaseModel):
    """Response model for interactions."""
    success: bool
    data: dict
    message: str


@router.post("/content/{content_id}/like", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def like_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Add a like to content.
    
    Args:
        content_id: ID of content to like
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Create interaction record
        interaction_id = f"{user_id}_{content_id}_like"
        interaction_data = {
            "id": interaction_id,
            "user_id": user_id,
            "content_id": content_id,
            "type": "like",
            "created_at": datetime.utcnow(),
        }
        
        db_client.collection("interactions").document(interaction_id).set(interaction_data)
        
        # Increment like count
        current_likes = content_data.get("like_count", 0)
        db_client.collection("content").document(content_id).update({
            "like_count": current_likes + 1,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} liked content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "like_count": current_likes + 1},
            message="Content liked successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error liking content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to like content: {str(e)}"
        )


@router.delete("/content/{content_id}/like", response_model=InteractionResponse)
async def unlike_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Remove a like from content.
    
    Args:
        content_id: ID of content to unlike
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Delete interaction record
        interaction_id = f"{user_id}_{content_id}_like"
        db_client.collection("interactions").document(interaction_id).delete()
        
        # Decrement like count
        current_likes = max(0, content_data.get("like_count", 1) - 1)
        db_client.collection("content").document(content_id).update({
            "like_count": current_likes,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} unliked content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "like_count": current_likes},
            message="Content unliked successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unliking content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unlike content: {str(e)}"
        )


@router.post("/content/{content_id}/save", response_model=InteractionResponse, status_code=status.HTTP_201_CREATED)
async def save_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Save content to user's library.
    
    Args:
        content_id: ID of content to save
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Create interaction record
        interaction_id = f"{user_id}_{content_id}_save"
        interaction_data = {
            "id": interaction_id,
            "user_id": user_id,
            "content_id": content_id,
            "type": "save",
            "created_at": datetime.utcnow(),
        }
        
        db_client.collection("interactions").document(interaction_id).set(interaction_data)
        
        # Increment save count
        current_saves = content_data.get("save_count", 0)
        db_client.collection("content").document(content_id).update({
            "save_count": current_saves + 1,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} saved content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "save_count": current_saves + 1},
            message="Content saved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save content: {str(e)}"
        )


@router.delete("/content/{content_id}/save", response_model=InteractionResponse)
async def unsave_content(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Remove content from user's saved library.
    
    Args:
        content_id: ID of content to unsave
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with success status
        
    Raises:
        HTTPException: If content not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get content
        content_doc = db_client.collection("content").document(content_id).get()
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Delete interaction record
        interaction_id = f"{user_id}_{content_id}_save"
        db_client.collection("interactions").document(interaction_id).delete()
        
        # Decrement save count
        current_saves = max(0, content_data.get("save_count", 1) - 1)
        db_client.collection("content").document(content_id).update({
            "save_count": current_saves,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} unsaved content {content_id}")
        
        return InteractionResponse(
            success=True,
            data={"content_id": content_id, "save_count": current_saves},
            message="Content unsaved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsaving content: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unsave content: {str(e)}"
        )


@router.get("/me/likes", response_model=InteractionResponse)
async def get_user_likes(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Get list of content IDs the user has liked.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with list of liked content IDs
    """
    try:
        user_id = current_user["uid"]
        
        # Get all like interactions for user
        interactions = db_client.collection("interactions").where("user_id", "==", user_id).where("type", "==", "like").get()
        
        liked_ids = [interaction.to_dict().get("content_id") for interaction in interactions]
        
        return InteractionResponse(
            success=True,
            data={"liked_content_ids": liked_ids, "total": len(liked_ids)},
            message="User likes retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error getting user likes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get likes: {str(e)}"
        )


@router.get("/me/saves", response_model=InteractionResponse)
async def get_user_saves(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> InteractionResponse:
    """
    Get list of content IDs the user has saved.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        InteractionResponse with list of saved content IDs
    """
    try:
        user_id = current_user["uid"]
        
        # Get all save interactions for user
        interactions = db_client.collection("interactions").where("user_id", "==", user_id).where("type", "==", "save").get()
        
        saved_ids = [interaction.to_dict().get("content_id") for interaction in interactions]
        
        return InteractionResponse(
            success=True,
            data={"saved_content_ids": saved_ids, "total": len(saved_ids)},
            message="User saves retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error getting user saves: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get saves: {str(e)}"
        )
