"""
Interaction Model
Represents user interactions with content (likes, saves, views).
"""

from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class InteractionType(str, Enum):
    """Type of user interaction with content."""
    VIEW = "VIEW"
    LIKE = "LIKE"
    SAVE = "SAVE"


class InteractionModel(BaseModel):
    """User interaction with content."""
    
    id: str = Field(description="Unique interaction ID")
    user_id: str = Field(description="User ID")
    content_id: str = Field(description="Content ID")
    type: InteractionType = Field(description="Type of interaction (VIEW, LIKE, SAVE)")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Interaction timestamp")
    removed_at: Optional[datetime] = Field(default=None, description="Removal timestamp (for undoing likes/saves)")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert interaction to dictionary for Firestore storage."""
        data = self.model_dump()
        data["created_at"] = self.created_at
        data["removed_at"] = self.removed_at
        data["type"] = self.type.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionModel":
        """Create interaction from Firestore dictionary."""
        if "type" in data and isinstance(data["type"], str):
            data["type"] = InteractionType(data["type"])
        return cls(**data)
