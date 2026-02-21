"""
User Model
Represents user data stored in Firestore.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator


class UserPreferences(BaseModel):
    """User preference settings."""
    
    selected_voice_id: str = Field(default="voice_default", description="Selected voice ID for content playback")
    background_music_type: str = Field(default="calm", description="Type of background music")
    enable_background_music: bool = Field(default=True, description="Whether background music is enabled")
    music_volume: int = Field(default=50, ge=0, le=100, description="Music volume level (0-100)")
    preferred_content_types: List[str] = Field(default_factory=lambda: ["STORY"], description="Preferred content types")
    preferred_categories: List[str] = Field(default_factory=list, description="Preferred content categories")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert preferences to dictionary for Firestore."""
        return self.model_dump()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserPreferences":
        """Create preferences from Firestore dictionary."""
        return cls(**data)


class UserModel(BaseModel):
    """User model representing a user in Firestore."""
    
    uid: str = Field(description="Unique user ID (from Firebase Auth)")
    username: str = Field(min_length=3, max_length=20, description="Username")
    child_age: int = Field(ge=0, le=12, description="Child's age in years")
    subscription_tier: str = Field(default="FREE", description="Subscription tier (FREE, PREMIUM, UNLIMITED)")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Account creation timestamp")
    subscription_expires_at: Optional[datetime] = Field(default=None, description="Subscription expiration timestamp")
    preferences: UserPreferences = Field(default_factory=UserPreferences, description="User preferences")
    daily_usage_count: int = Field(default=0, description="Content views count for today")
    last_usage_date: Optional[datetime] = Field(default=None, description="Last usage date")
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username contains only alphanumeric characters and underscores."""
        if not v.replace("_", "").isalnum():
            raise ValueError("Username must contain only alphanumeric characters and underscores")
        return v
    
    @field_validator("subscription_tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        """Validate subscription tier."""
        if v not in ["FREE", "PREMIUM", "UNLIMITED"]:
            raise ValueError("Invalid subscription tier")
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary for Firestore storage."""
        data = self.model_dump()
        data["created_at"] = self.created_at
        data["subscription_expires_at"] = self.subscription_expires_at
        data["last_usage_date"] = self.last_usage_date
        data["preferences"] = self.preferences.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserModel":
        """Create user from Firestore dictionary."""
        if "preferences" in data and isinstance(data["preferences"], dict):
            data["preferences"] = UserPreferences.from_dict(data["preferences"])
        return cls(**data)
