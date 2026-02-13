"""
Subscription Models
Defines subscription tiers and plans.
"""

from enum import Enum
from typing import List
from pydantic import BaseModel, Field


class SubscriptionTier(str, Enum):
    """Subscription tier enumeration."""
    FREE = "FREE"
    PREMIUM = "PREMIUM"
    UNLIMITED = "UNLIMITED"


class SubscriptionPlan(BaseModel):
    """Subscription plan definition."""
    
    tier: SubscriptionTier = Field(description="Subscription tier")
    daily_limit: int = Field(ge=-1, description="Daily content limit (-1 for unlimited)")
    max_favorites: int = Field(ge=-1, description="Max favorites (-1 for unlimited)")
    max_saves: int = Field(ge=-1, description="Max saved content (-1 for unlimited)")
    features: List[str] = Field(default_factory=list, description="List of enabled features")
    price_usd: float = Field(ge=0, description="Monthly price in USD")
    description: str = Field(description="Plan description")
    
    def to_dict(self) -> dict:
        """Convert plan to dictionary."""
        return {
            "tier": self.tier.value,
            "daily_limit": self.daily_limit,
            "max_favorites": self.max_favorites,
            "max_saves": self.max_saves,
            "features": self.features,
            "price_usd": self.price_usd,
            "description": self.description,
        }


# Default subscription plans
DEFAULT_PLANS = {
    SubscriptionTier.FREE: SubscriptionPlan(
        tier=SubscriptionTier.FREE,
        daily_limit=5,
        max_favorites=10,
        max_saves=10,
        features=["basic_content", "limited_voices"],
        price_usd=0.0,
        description="Free plan with daily limits"
    ),
    SubscriptionTier.PREMIUM: SubscriptionPlan(
        tier=SubscriptionTier.PREMIUM,
        daily_limit=30,
        max_favorites=100,
        max_saves=100,
        features=["all_content", "all_voices", "ad_free", "priority_generation"],
        price_usd=9.99,
        description="Premium plan with generous limits"
    ),
    SubscriptionTier.UNLIMITED: SubscriptionPlan(
        tier=SubscriptionTier.UNLIMITED,
        daily_limit=-1,
        max_favorites=-1,
        max_saves=-1,
        features=["all_content", "all_voices", "ad_free", "priority_generation", "custom_generation", "family_sharing"],
        price_usd=19.99,
        description="Unlimited plan with no restrictions"
    ),
}
