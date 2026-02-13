"""User profile and preferences endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Request Models
class UpdateProfileRequest(BaseModel):
    """Request model for updating user profile."""
    child_age: Optional[int] = None


class UpdatePreferencesRequest(BaseModel):
    """Request model for updating user preferences."""
    language: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    theme: Optional[str] = None


# Response Models
class UserResponse(BaseModel):
    """Response model for user data."""
    success: bool
    data: dict
    message: str


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> UserResponse:
    """
    Get current user's profile.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        UserResponse with user profile data
        
    Raises:
        HTTPException: If user not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get user document
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_data = user_doc.to_dict()
        
        return UserResponse(
            success=True,
            data={
                "uid": user_id,
                "username": user_data.get("username"),
                "child_age": user_data.get("child_age"),
                "subscription_tier": user_data.get("subscription_tier", "free"),
                "created_at": user_data.get("created_at"),
                "preferences": user_data.get("preferences", {}),
            },
            message="User profile retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profile: {str(e)}"
        )


@router.put("/me", response_model=UserResponse)
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> UserResponse:
    """
    Update current user's profile.
    
    Args:
        request: UpdateProfileRequest with profile updates
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        UserResponse with updated user profile
        
    Raises:
        HTTPException: If user not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get user document
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update only provided fields
        update_data = {"updated_at": datetime.utcnow()}
        
        if request.child_age is not None:
            update_data["child_age"] = request.child_age
        
        db_client.collection("users").document(user_id).update(update_data)
        
        # Get updated document
        user_doc = db_client.collection("users").document(user_id).get()
        user_data = user_doc.to_dict()
        
        logger.info(f"User profile updated: {user_id}")
        
        return UserResponse(
            success=True,
            data={
                "uid": user_id,
                "username": user_data.get("username"),
                "child_age": user_data.get("child_age"),
                "subscription_tier": user_data.get("subscription_tier", "free"),
                "created_at": user_data.get("created_at"),
            },
            message="Profile updated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update profile: {str(e)}"
        )


@router.put("/preferences", response_model=UserResponse)
async def update_preferences(
    request: UpdatePreferencesRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> UserResponse:
    """
    Update user preferences.
    
    Args:
        request: UpdatePreferencesRequest with preference updates
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        UserResponse with updated preferences
        
    Raises:
        HTTPException: If user not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get user document
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_data = user_doc.to_dict()
        preferences = user_data.get("preferences", {})
        
        # Update preferences
        if request.language is not None:
            preferences["language"] = request.language
        if request.notifications_enabled is not None:
            preferences["notifications_enabled"] = request.notifications_enabled
        if request.theme is not None:
            preferences["theme"] = request.theme
        
        db_client.collection("users").document(user_id).update({
            "preferences": preferences,
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User preferences updated: {user_id}")
        
        return UserResponse(
            success=True,
            data={
                "uid": user_id,
                "preferences": preferences,
            },
            message="Preferences updated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating preferences: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update preferences: {str(e)}"
        )


@router.get("/quota", response_model=UserResponse)
async def get_user_quota(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> UserResponse:
    """
    Get user's daily quota information.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        UserResponse with quota information
        
    Raises:
        HTTPException: If user not found
    """
    try:
        user_id = current_user["uid"]
        
        # Get user document
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_data = user_doc.to_dict()
        used = user_data.get("daily_usage", 0)
        limit = user_data.get("daily_limit", 3)
        tier = user_data.get("subscription_tier", "free")
        
        return UserResponse(
            success=True,
            data={
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
                "tier": tier,
            },
            message="Quota retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quota: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get quota: {str(e)}"
        )
