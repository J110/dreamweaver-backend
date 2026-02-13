"""
Content Models
Represents content stored in Firestore.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class ContentType(str, Enum):
    """Content type enumeration."""
    STORY = "STORY"
    POEM = "POEM"
    SONG = "SONG"


class StoryTheme(str, Enum):
    """Story theme enumeration."""
    FANTASY = "FANTASY"
    ADVENTURE = "ADVENTURE"
    FAIRY_TALE = "FAIRY_TALE"
    ANIMALS = "ANIMALS"
    SPACE = "SPACE"
    OCEAN = "OCEAN"
    MYSTERY = "MYSTERY"
    FRIENDSHIP = "FRIENDSHIP"
    FAMILY = "FAMILY"
    NATURE = "NATURE"
    EDUCATIONAL = "EDUCATIONAL"
    BEDTIME = "BEDTIME"


class StoryLength(str, Enum):
    """Story length enumeration with word count ranges."""
    SHORT = "SHORT"      # 100-300 words
    MEDIUM = "MEDIUM"    # 300-800 words
    LONG = "LONG"        # 800+ words


class ContentModel(BaseModel):
    """Content model representing stories, poems, and songs."""
    
    id: str = Field(description="Unique content ID")
    type: ContentType = Field(description="Content type (STORY, POEM, SONG)")
    title: str = Field(min_length=1, max_length=200, description="Content title")
    description: str = Field(max_length=500, description="Content description")
    text: str = Field(description="Main content text")
    target_age: int = Field(ge=0, le=14, description="Target age for content")
    duration_seconds: int = Field(ge=0, description="Duration in seconds")
    author_id: str = Field(description="Author/Creator ID")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    audio_url: Optional[str] = Field(default=None, description="URL to audio file")
    album_art_url: Optional[str] = Field(default=None, description="URL to album art/thumbnail")
    view_count: int = Field(default=0, ge=0, description="Number of views")
    like_count: int = Field(default=0, ge=0, description="Number of likes")
    save_count: int = Field(default=0, ge=0, description="Number of saves/bookmarks")
    categories: List[str] = Field(default_factory=list, description="Content categories")
    theme: Optional[StoryTheme] = Field(default=None, description="Story theme (if applicable)")
    is_generated: bool = Field(default=False, description="Whether content was AI-generated")
    voice_id: Optional[str] = Field(default=None, description="Voice ID used for audio generation")
    music_type: Optional[str] = Field(default=None, description="Background music type")
    generation_quality: Optional[str] = Field(default=None, description="Quality level of generation")
    
    @field_validator("type")
    @classmethod
    def validate_type(cls, v: ContentType) -> ContentType:
        """Validate content type."""
        if not isinstance(v, ContentType):
            v = ContentType(v)
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert content to dictionary for Firestore storage."""
        data = self.model_dump()
        data["created_at"] = self.created_at
        data["type"] = self.type.value
        if self.theme:
            data["theme"] = self.theme.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContentModel":
        """Create content from Firestore dictionary."""
        if "type" in data and isinstance(data["type"], str):
            data["type"] = ContentType(data["type"])
        if "theme" in data and isinstance(data["theme"], str):
            data["theme"] = StoryTheme(data["theme"])
        return cls(**data)
