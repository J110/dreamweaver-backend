"""
User CRUD Operations
Database operations for user management.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from google.cloud.firestore import Client
from app.crud.base import BaseCRUD
from app.models.user import UserModel, UserPreferences


class UserCRUD(BaseCRUD):
    """CRUD operations for user documents."""
    
    def __init__(self, db: Client):
        """Initialize user CRUD."""
        super().__init__(db)
    
    @property
    def collection_name(self) -> str:
        """Get collection name."""
        return "users"
    
    async def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user by username.
        
        Args:
            username: Username to search for
            
        Returns:
            User document data or None if not found
        """
        docs = await self.get_collection().where("username", "==", username).get()
        if docs:
            data = docs[0].to_dict()
            data["id"] = docs[0].id
            return data
        return None
    
    async def create_user(self, user_data: UserModel) -> str:
        """
        Create a new user.
        
        Args:
            user_data: UserModel instance
            
        Returns:
            Created user ID (uid)
        """
        data = user_data.to_dict()
        await self.get_collection().document(user_data.uid).set(data)
        return user_data.uid
    
    async def update_preferences(self, uid: str, preferences: UserPreferences) -> bool:
        """
        Update user preferences.
        
        Args:
            uid: User ID
            preferences: Updated preferences
            
        Returns:
            True if successful
        """
        return await self.update(uid, {"preferences": preferences.to_dict()})
    
    async def increment_daily_usage(self, uid: str) -> int:
        """
        Increment daily usage count.
        
        Args:
            uid: User ID
            
        Returns:
            Updated usage count
        """
        doc_ref = self.get_collection().document(uid)
        
        # Get current user
        user_doc = await doc_ref.get()
        if not user_doc.exists:
            return 0
        
        user_data = user_doc.to_dict()
        today = datetime.utcnow().date()
        last_usage = user_data.get("last_usage_date")
        
        # Reset if last usage was different day
        if last_usage and last_usage.date() != today:
            count = 1
        else:
            count = user_data.get("daily_usage_count", 0) + 1
        
        await doc_ref.update({
            "daily_usage_count": count,
            "last_usage_date": datetime.utcnow()
        })
        
        return count
    
    async def reset_daily_usage(self, uid: str) -> bool:
        """
        Reset daily usage count.
        
        Args:
            uid: User ID
            
        Returns:
            True if successful
        """
        return await self.update(uid, {"daily_usage_count": 0})
    
    async def get_daily_usage(self, uid: str) -> Dict[str, Any]:
        """
        Get daily usage information.
        
        Args:
            uid: User ID
            
        Returns:
            Dictionary with used count and reset time
        """
        user_data = await self.get_by_id(uid)
        if not user_data:
            return {"used": 0, "reset_at": None}
        
        last_usage = user_data.get("last_usage_date")
        today = datetime.utcnow().date()
        
        # Calculate reset time (next day at UTC midnight)
        if last_usage and last_usage.date() == today:
            reset_at = datetime.combine(today + timedelta(days=1), datetime.min.time())
        else:
            reset_at = datetime.combine(today + timedelta(days=1), datetime.min.time())
        
        return {
            "used": user_data.get("daily_usage_count", 0),
            "reset_at": reset_at
        }
    
    async def update_subscription(self, uid: str, tier: str, expires_at: Optional[datetime] = None) -> bool:
        """
        Update user subscription tier.
        
        Args:
            uid: User ID
            tier: New subscription tier
            expires_at: Subscription expiration time (optional)
            
        Returns:
            True if successful
        """
        data = {
            "subscription_tier": tier,
            "subscription_expires_at": expires_at
        }
        return await self.update(uid, data)
