"""
Interaction CRUD Operations
Database operations for user interactions (likes, saves, views).
"""

from typing import Optional, Dict, Any, List
from google.cloud.firestore import Client
from app.crud.base import BaseCRUD
from app.models.interaction import InteractionModel, InteractionType


class InteractionCRUD(BaseCRUD):
    """CRUD operations for interaction documents."""
    
    def __init__(self, db: Client):
        """Initialize interaction CRUD."""
        super().__init__(db)
    
    @property
    def collection_name(self) -> str:
        """Get collection name."""
        return "interactions"
    
    def _get_interaction_id(self, user_id: str, content_id: str, interaction_type: str) -> str:
        """
        Generate unique interaction ID.
        
        Args:
            user_id: User ID
            content_id: Content ID
            interaction_type: Type of interaction
            
        Returns:
            Unique interaction ID
        """
        return f"{user_id}_{content_id}_{interaction_type}"
    
    async def add_interaction(
        self,
        user_id: str,
        content_id: str,
        interaction_type: InteractionType
    ) -> str:
        """
        Add user interaction with content.
        
        Args:
            user_id: User ID
            content_id: Content ID
            interaction_type: Type of interaction (LIKE, SAVE, VIEW)
            
        Returns:
            Interaction ID
        """
        interaction_id = self._get_interaction_id(user_id, content_id, interaction_type.value)
        
        data = {
            "user_id": user_id,
            "content_id": content_id,
            "type": interaction_type.value,
            "created_at": None,  # Will be set by Firestore
            "removed_at": None
        }
        
        await self.get_collection().document(interaction_id).set(data)
        return interaction_id
    
    async def remove_interaction(
        self,
        user_id: str,
        content_id: str,
        interaction_type: InteractionType
    ) -> bool:
        """
        Remove (undo) user interaction.
        
        Args:
            user_id: User ID
            content_id: Content ID
            interaction_type: Type of interaction
            
        Returns:
            True if successful
        """
        from datetime import datetime
        interaction_id = self._get_interaction_id(user_id, content_id, interaction_type.value)
        
        return await self.update(interaction_id, {"removed_at": datetime.utcnow()})
    
    async def get_user_likes(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all content liked by user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of liked content IDs
        """
        docs = await self.get_collection().where(
            "user_id", "==", user_id
        ).where(
            "type", "==", InteractionType.LIKE.value
        ).where(
            "removed_at", "==", None
        ).get()
        
        items = []
        for doc in docs:
            data = doc.to_dict()
            items.append({
                "content_id": data.get("content_id"),
                "created_at": data.get("created_at")
            })
        
        return items
    
    async def get_user_saves(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all content saved by user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of saved content IDs
        """
        docs = await self.get_collection().where(
            "user_id", "==", user_id
        ).where(
            "type", "==", InteractionType.SAVE.value
        ).where(
            "removed_at", "==", None
        ).get()
        
        items = []
        for doc in docs:
            data = doc.to_dict()
            items.append({
                "content_id": data.get("content_id"),
                "created_at": data.get("created_at")
            })
        
        return items
    
    async def is_liked(self, user_id: str, content_id: str) -> bool:
        """
        Check if user liked content.
        
        Args:
            user_id: User ID
            content_id: Content ID
            
        Returns:
            True if liked and not removed
        """
        doc = await self.get_collection().document(
            self._get_interaction_id(user_id, content_id, InteractionType.LIKE.value)
        ).get()
        
        if not doc.exists:
            return False
        
        data = doc.to_dict()
        return data.get("removed_at") is None
    
    async def is_saved(self, user_id: str, content_id: str) -> bool:
        """
        Check if user saved content.
        
        Args:
            user_id: User ID
            content_id: Content ID
            
        Returns:
            True if saved and not removed
        """
        doc = await self.get_collection().document(
            self._get_interaction_id(user_id, content_id, InteractionType.SAVE.value)
        ).get()
        
        if not doc.exists:
            return False
        
        data = doc.to_dict()
        return data.get("removed_at") is None
    
    async def get_user_interactions_with_content(
        self,
        user_id: str,
        content_id: str
    ) -> Dict[str, bool]:
        """
        Get all interaction types for user with specific content.
        
        Args:
            user_id: User ID
            content_id: Content ID
            
        Returns:
            Dictionary with interaction type boolean values
        """
        return {
            "liked": await self.is_liked(user_id, content_id),
            "saved": await self.is_saved(user_id, content_id)
        }
