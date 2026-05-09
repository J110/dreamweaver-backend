"""User profile and preferences endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.dependencies import _local_users, get_current_user, get_db_client
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


class CompleteOnboardingRequest(BaseModel):
    """Onboarding completion. Sets username + child_age + preferred_lang
    on the authenticated user's record and flips onboarding_complete=true.

    Idempotent for the same user — submitting their own existing username
    re-registers it without 409. Different user with the same lowercase
    username → 409 with code=username_taken.
    """
    # Server-side trim happens before validation; the regex permits
    # space inside the username (e.g. "Little ki" exists in prod).
    username: str = Field(..., min_length=2, max_length=24, pattern=r"^[A-Za-z0-9_ ]+$")
    child_age: int = Field(..., ge=0, le=18)
    lang: str = Field(default="en", pattern=r"^(en|hi)$")


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


@router.post("/me/complete-onboarding", response_model=UserResponse)
async def complete_onboarding(
    request: CompleteOnboardingRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> UserResponse:
    """Set username + child_age + preferred_lang on the current user record.

    Phase 0 onboarding fix. Magic-link signup_new no longer derives
    username from email local-part; users land on /onboarding to choose
    their own. This endpoint persists the choice and flips
    onboarding_complete=true so AppShell stops gating them.

    Username collision check is case-insensitive via username_lowercase
    (Phase 0 step 1.5e). Self-match excluded — re-submitting the same
    username for the same user is idempotent. Tombstoned records
    (archived=true) are skipped so freed-up usernames are reusable.

    Returns 409 with detail.code='username_taken' on collision.
    """
    uid = current_user["uid"]

    # Server-side trim; reject empties
    username = (request.username or "").strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is empty after trim",
        )
    username_lc = username.lower()

    # Collision check — case-insensitive, exclude self + tombstones
    try:
        rows = db_client.collection("users").where("username_lowercase", "==", username_lc).get()
    except Exception:
        rows = []
    for doc in rows:
        data = doc.to_dict() if hasattr(doc, "to_dict") else doc
        if not isinstance(data, dict):
            continue
        if data.get("archived"):
            continue
        other_uid = data.get("uid") or data.get("id")
        if other_uid and other_uid != uid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "username_taken", "username": username},
            )

    # All clear; persist
    update = {
        "username": username,
        "username_lowercase": username_lc,
        "child_age": request.child_age,
        "preferred_lang": request.lang,
        "onboarding_complete": True,
    }
    try:
        db_client.collection("users").document(uid).update(update)
        if uid in _local_users:
            _local_users[uid].update(update)
    except Exception as e:
        logger.error(f"complete_onboarding persist failed uid={uid}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save onboarding selections",
        )

    logger.info(
        "Onboarding completed: uid=%s username=%s child_age=%d lang=%s",
        uid, username, request.child_age, request.lang,
    )

    return UserResponse(
        success=True,
        data={
            "uid": uid,
            "username": username,
            "child_age": request.child_age,
            "preferred_lang": request.lang,
            "onboarding_complete": True,
        },
        message="Onboarding completed",
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
