"""Subscription and tier management endpoints."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Hardcoded subscription tiers
SUBSCRIPTION_TIERS = [
    {
        "id": "free",
        "name": "Free",
        "description": "Perfect for getting started",
        "price": 0,
        "currency": "USD",
        "daily_limit": 3,
        "features": [
            "3 stories per day",
            "Basic themes",
            "Standard voice",
        ],
    },
    {
        "id": "premium",
        "name": "Premium",
        "description": "Unlimited stories for families",
        "price": 9.99,
        "currency": "USD",
        "billing_period": "monthly",
        "daily_limit": 50,
        "features": [
            "Unlimited stories per day",
            "All themes and categories",
            "Multiple voice options",
            "Ad-free experience",
            "Custom music",
        ],
    },
    {
        "id": "family",
        "name": "Family",
        "description": "Everything for the whole family",
        "price": 14.99,
        "currency": "USD",
        "billing_period": "monthly",
        "daily_limit": 100,
        "features": [
            "Unlimited stories per day",
            "All themes and categories",
            "All voice options",
            "Ad-free experience",
            "Custom music and sounds",
            "Up to 5 child profiles",
            "Parental controls",
        ],
    },
]


# Response Models
class SubscriptionResponse(BaseModel):
    """Response model for subscription data."""
    success: bool
    data: dict
    message: str


class UpgradeRequest(BaseModel):
    """Request model for subscription upgrade."""
    tier_id: str


@router.get("/tiers", response_model=SubscriptionResponse)
async def get_subscription_tiers() -> SubscriptionResponse:
    """
    Get available subscription tiers.
    
    Returns:
        SubscriptionResponse with list of available tiers
    """
    return SubscriptionResponse(
        success=True,
        data={
            "tiers": SUBSCRIPTION_TIERS,
            "total": len(SUBSCRIPTION_TIERS),
        },
        message="Subscription tiers retrieved successfully"
    )


@router.get("/current", response_model=SubscriptionResponse)
async def get_current_subscription(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> SubscriptionResponse:
    """
    Get current user's subscription tier.
    
    Args:
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        SubscriptionResponse with current tier information
        
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
        tier_id = user_data.get("subscription_tier", "free")
        
        # Find tier details
        tier = next((t for t in SUBSCRIPTION_TIERS if t["id"] == tier_id), None)
        
        if not tier:
            # Fallback to free tier if tier not found
            tier = SUBSCRIPTION_TIERS[0]
        
        return SubscriptionResponse(
            success=True,
            data={
                "current_tier": tier,
                "since": user_data.get("subscription_start_date"),
                "next_billing_date": user_data.get("next_billing_date"),
            },
            message="Current subscription retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get subscription: {str(e)}"
        )


@router.post("/upgrade", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK)
async def upgrade_subscription(
    request: UpgradeRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> SubscriptionResponse:
    """
    Upgrade user's subscription tier.
    
    Args:
        request: UpgradeRequest with tier_id to upgrade to
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        SubscriptionResponse with updated tier information
        
    Raises:
        HTTPException: If tier invalid or user not found
    """
    try:
        user_id = current_user["uid"]
        tier_id = request.tier_id
        
        # Verify tier exists
        tier = next((t for t in SUBSCRIPTION_TIERS if t["id"] == tier_id), None)
        if not tier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tier ID"
            )
        
        # Get user document
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update subscription tier
        db_client.collection("users").document(user_id).update({
            "subscription_tier": tier_id,
            "daily_limit": tier["daily_limit"],
            "subscription_start_date": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        
        logger.info(f"User {user_id} upgraded to {tier_id}")
        
        return SubscriptionResponse(
            success=True,
            data={
                "upgraded_tier": tier,
                "effective_from": datetime.utcnow().isoformat(),
            },
            message="Subscription upgraded successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upgrading subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upgrade failed: {str(e)}"
        )
