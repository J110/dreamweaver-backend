"""Subscription and tier management endpoints."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Hardcoded subscription tiers — Phase 0 step 1.4e rewrite per framework
# (docs/superpowers/specs/2026-04-27-monetization-marketing-framework.md
# §3). Replaces the legacy 3-tier daily_limit shape with credit pools and
# backlog windows. Family tier dropped (gate #4 deferred until ≥30% of
# Premium users fill all 3 voice slots in Phase 2.1).
SUBSCRIPTION_TIERS = [
    {
        "id": "free",
        "name": "Free",
        "description": "Tonight's bedtime bundle, 3 free personalized stories",
        "price": 0,
        "price_annual": 0,
        "currency": "USD",
        # Credit model
        "credits_per_period": None,   # Free has no monthly pool
        "lifetime_free_credits": 3,   # 3-burst onboarding
        "backlog_days": 3,            # Free sees last 3 days of ritual content
        "features": [
            "Tonight's bedtime bundle (silly song, story, poem, lullaby)",
            "Last 3 days of stories saved",
            "3 free personalized stories",
            "Default narration voices",
        ],
    },
    {
        "id": "premium",
        "name": "Premium",
        "description": "30 personalized story credits per month + voice cloning",
        "price": 6,
        "price_annual": 40,
        "currency": "USD",
        "billing_period": "monthly",
        "trial_days_annual": 7,
        "trial_days_monthly": 7,
        # Credit model
        "credits_per_period": 30,     # Premium pool, resets each renewal
        "lifetime_free_credits": None,
        "backlog_days": 30,           # Premium sees last 30 days
        "top_up_pack": {
            "credits": 10,
            "price_usd": 2,
        },
        "features": [
            "Voice cloning — stories in your voice (3 voice slots)",
            "30 personalized story credits every month",
            "Last 30 days of stories saved",
            "Episodic memory — your kid's character remembers their adventures",
            "Karaoke mode + bookmark resume + offline downloads",
            "Up to 3 kid profiles",
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
        
        from app.utils.gating import is_premium
        effective_premium = is_premium({
            "subscription_tier": tier_id,
            "family_id": user_data.get("family_id"),
        })

        return SubscriptionResponse(
            success=True,
            data={
                "current_tier": tier,
                "effective_premium": effective_premium,
                "since": user_data.get("subscription_start_date"),
                "next_billing_date": user_data.get("next_billing_date"),
                # Phase 0 step 1.4e: surface credit machinery for settings UI.
                "subscription_status": user_data.get("subscription_status", "free"),
                "current_period_end": user_data.get("current_period_end"),
                "credits_remaining": user_data.get("credits_remaining", 0),
                "topup_credits_remaining": user_data.get("topup_credits_remaining", 0),
                "credits_period_end": user_data.get("credits_period_end"),
                "credits_frozen": bool(user_data.get("credits_frozen")),
                "lifetime_free_remaining": user_data.get("lifetime_free_remaining", 3),
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


@router.post("/upgrade", status_code=status.HTTP_410_GONE)
async def upgrade_subscription_deprecated() -> dict:
    """Deprecated. Replaced by Stripe Checkout flow.

    Phase 0 step 1.4b security fix. The previous handler accepted a
    tier_id and directly wrote subscription_tier='premium' on the user
    record with NO payment, NO admin guard — any logged-in user could
    grant themselves premium. The endpoint now returns 410 Gone.

    Replacement: POST /api/v1/billing/checkout/start
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "endpoint_removed",
            "message": "Replaced by Stripe Checkout flow.",
            "replacement": "POST /api/v1/billing/checkout/start",
        },
    )
