"""
Subscription Request/Response Schemas
API schemas for subscription management.
"""

from typing import List
from pydantic import BaseModel, Field


class SubscriptionTierInfo(BaseModel):
    """Information about a subscription tier."""
    
    tier: str = Field(description="Tier identifier (FREE, PREMIUM, UNLIMITED)")
    name: str = Field(description="Tier display name")
    daily_limit: int = Field(description="Daily content limit (-1 for unlimited)")
    max_favorites: int = Field(description="Maximum favorites (-1 for unlimited)")
    max_saves: int = Field(description="Maximum saves (-1 for unlimited)")
    features: List[str] = Field(description="List of features included")
    price: float = Field(ge=0, description="Monthly price in USD")
    
    class Config:
        from_attributes = True


class SubscriptionTiersResponse(BaseModel):
    """Response with all subscription tiers."""
    
    tiers: List[SubscriptionTierInfo] = Field(description="List of subscription tiers")
    current_tier: str = Field(description="User's current tier")
    current_features: List[str] = Field(description="User's current features")


class UpgradeRequest(BaseModel):
    """Request to upgrade subscription tier."""
    
    tier: str = Field(description="Target subscription tier")
    
    @classmethod
    def __get_validators__(cls):
        """Validate tier."""
        yield cls.validate_tier
    
    @staticmethod
    def validate_tier(v: str) -> str:
        """Ensure tier is valid."""
        if v not in ["FREE", "PREMIUM", "UNLIMITED"]:
            raise ValueError("Invalid subscription tier")
        return v
