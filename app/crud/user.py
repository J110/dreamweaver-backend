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
        Get user by username (case-insensitive).

        Phase 0 step 1.5e. Queries username_lowercase as the canonical
        lookup key. Falls back to case-sensitive lookup over the legacy
        `username` field for un-backfilled records.

        Note: this CRUD class is dead Firestore-shaped code per
        CLAUDE.md (LocalStore is the actual store; magic_link.py is
        the canonical lookup path). Patched here for consistency only.

        Args:
            username: Username to search for (case-insensitive)

        Returns:
            User document data or None if not found
        """
        target = (username or "").lower()
        if not target:
            return None
        docs = await self.get_collection().where("username_lowercase", "==", target).get()
        if not docs:
            # Fallback for un-backfilled records.
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
    
    # Phase 0 step 1.4e: removed increment_daily_usage / reset_daily_usage /
    # get_daily_usage. They were Firestore-shaped CRUD methods on a
    # collection that LocalStore is the actual store for; never called by
    # production code. The credit pool model (credits_remaining,
    # credits_period_end, credits_frozen on user record) replaces the
    # daily_usage_count counter. See app/dependencies.py:_ensure_credit_fields.

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
