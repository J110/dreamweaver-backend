"""
Content Request/Response Schemas
API schemas for content operations.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class ContentResponse(BaseModel):
    """Content response with user interaction status."""

    id: str = Field(description="Content ID")
    type: Optional[str] = Field(default=None, description="Content type (STORY, POEM, SONG)")
    title: Optional[str] = Field(default=None, description="Content title")
    description: Optional[str] = Field(default=None, description="Content description")
    text: Optional[str] = Field(default=None, description="Content text")
    target_age: Optional[int] = Field(default=None, description="Target age")
    duration: Optional[int] = Field(default=None, description="Duration in seconds")
    duration_seconds: Optional[int] = Field(default=None, description="Duration in seconds (alias)")
    author_id: Optional[str] = Field(default=None, description="Author ID")
    created_at: Optional[datetime] = Field(default=None, description="Creation date")
    audio_url: Optional[str] = Field(default=None, description="Audio URL")
    album_art_url: Optional[str] = Field(default=None, description="Thumbnail URL")
    thumbnail_url: Optional[str] = Field(default=None, description="Thumbnail URL (alias)")
    view_count: int = Field(default=0, description="Number of views")
    like_count: int = Field(default=0, description="Number of likes")
    save_count: int = Field(default=0, description="Number of saves")
    category: Optional[str] = Field(default=None, description="Content category")
    categories: List[str] = Field(default_factory=list, description="Content categories")
    theme: Optional[str] = Field(default=None, description="Story theme")
    is_generated: bool = Field(default=False, description="AI-generated flag")
    voice_id: Optional[str] = Field(default=None, description="Voice used")
    music_type: Optional[str] = Field(default=None, description="Music type")
    generation_quality: Optional[str] = Field(default=None, description="Generation quality")
    is_liked: bool = Field(default=False, description="Whether current user liked")
    is_saved: bool = Field(default=False, description="Whether current user saved")

    class Config:
        from_attributes = True


class ContentListResponse(BaseModel):
    """Paginated content list response."""

    items: List[ContentResponse] = Field(description="Content items")
    total: int = Field(description="Total items matching criteria")
    total_count: Optional[int] = Field(default=None, description="Total items (alias)")
    page: int = Field(ge=1, description="Current page")
    page_size: int = Field(ge=1, description="Items per page")
    has_more: Optional[bool] = Field(default=None, description="Whether more items exist")


class GenerateContentRequest(BaseModel):
    """Request to generate new content."""
    
    content_type: str = Field(
        description="Content type (STORY, POEM, SONG)"
    )
    child_age: int = Field(
        ge=0,
        le=14,
        description="Target age for content"
    )
    theme: Optional[str] = Field(
        default=None,
        description="Story theme (optional)"
    )
    length: str = Field(
        default="MEDIUM",
        description="Content length (SHORT, MEDIUM, LONG)"
    )
    include_music: bool = Field(
        default=True,
        description="Include background music"
    )
    include_songs: bool = Field(
        default=True,
        description="Include songs in generation"
    )
    include_poems: bool = Field(
        default=True,
        description="Include poems in generation"
    )
    voice_id: str = Field(
        default="voice_default",
        description="Voice ID for audio"
    )
    music_type: str = Field(
        default="calm",
        description="Music type"
    )
    category: Optional[str] = Field(
        default=None,
        description="Content category (optional)"
    )
    custom_prompt: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Custom generation prompt (optional)"
    )
    
    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Validate content type."""
        if v not in ["STORY", "POEM", "SONG"]:
            raise ValueError("Invalid content type")
        return v
    
    @field_validator("length")
    @classmethod
    def validate_length(cls, v: str) -> str:
        """Validate length."""
        if v not in ["SHORT", "MEDIUM", "LONG"]:
            raise ValueError("Invalid length")
        return v


class GenerateContentResponse(BaseModel):
    """Response from content generation."""
    
    content: ContentResponse = Field(description="Generated content")
    status: str = Field(description="Generation status (generating, ready)")
    estimated_completion_seconds: Optional[int] = Field(
        default=None,
        description="Estimated time to completion"
    )


class SearchRequest(BaseModel):
    """Search request for content."""

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Search query"
    )
    content_type: Optional[str] = Field(
        default=None,
        description="Filter by content type (optional)"
    )
    theme: Optional[str] = Field(
        default=None,
        description="Filter by theme (optional)"
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Page number"
    )
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Items per page"
    )


class ContentStatusResponse(BaseModel):
    """Response for content generation status."""

    content_id: str = Field(description="Content ID")
    status: str = Field(description="Current generation status (processing, completed, failed)")
    text: Optional[str] = Field(default=None, description="Generated text content")
    audio_url: Optional[str] = Field(default=None, description="Audio URL when ready")
    thumbnail_url: Optional[str] = Field(default=None, description="Thumbnail/album art URL")
    duration: Optional[int] = Field(default=None, description="Duration in seconds")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
