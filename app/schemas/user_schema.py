"""
User Request/Response Schemas
API schemas for user authentication and profile management.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class SignUpRequest(BaseModel):
    """User signup request."""
    
    username: str = Field(
        min_length=3,
        max_length=20,
        description="Username (3-20 alphanumeric characters and underscores)"
    )
    password: str = Field(
        min_length=6,
        description="Password (minimum 6 characters)"
    )
    child_age: int = Field(
        ge=0,
        le=12,
        description="Child's age (0-12 years)"
    )
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username format."""
        if not v.replace("_", "").isalnum():
            raise ValueError("Username must contain only alphanumeric characters and underscores")
        return v


class LoginRequest(BaseModel):
    """User login request."""
    
    username: str = Field(description="Username")
    password: str = Field(description="Password")


class UserResponse(BaseModel):
    """User profile response."""

    id: str = Field(description="User ID")
    username: str = Field(description="Username")
    email: Optional[str] = Field(default=None, description="User email")
    child_age: int = Field(description="Child's age")
    subscription_tier: Optional[str] = Field(default=None, description="Current subscription tier")
    created_at: datetime = Field(description="Account creation date")
    daily_usage: Optional[int] = Field(default=None, description="Content views today")
    daily_limit: Optional[int] = Field(default=None, description="Daily limit for tier")

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    """Update user profile request."""
    
    child_age: Optional[int] = Field(
        default=None,
        ge=0,
        le=14,
        description="Child's age (optional)"
    )


class UpdatePreferencesRequest(BaseModel):
    """Update user preferences request."""
    
    selected_voice_id: Optional[str] = Field(default=None, description="Voice ID")
    background_music_type: Optional[str] = Field(default=None, description="Music type")
    enable_background_music: Optional[bool] = Field(default=None, description="Enable music")
    music_volume: Optional[int] = Field(default=None, ge=0, le=100, description="Music volume")
    preferred_content_types: Optional[list] = Field(default=None, description="Preferred content types")
    preferred_categories: Optional[list] = Field(default=None, description="Preferred categories")
    
    class Config:
        extra = "ignore"


class QuotaResponse(BaseModel):
    """Daily quota response."""

    used: int = Field(description="Content views used today")
    limit: int = Field(description="Daily limit for tier")
    remaining: int = Field(description="Remaining views")
    tier: str = Field(description="Subscription tier")
    resets_at: datetime = Field(description="When quota resets")


class TokenResponse(BaseModel):
    """Token response after authentication."""

    access_token: str = Field(description="JWT access token")
    refresh_token: Optional[str] = Field(default=None, description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: Optional[int] = Field(default=None, description="Token expiration in seconds")


class AuthResponse(BaseModel):
    """Full authentication response with user info."""

    user: "UserResponse" = Field(description="User information")
    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
