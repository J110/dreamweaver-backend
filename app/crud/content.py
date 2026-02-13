"""
Content CRUD Operations
Database operations for content management.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from google.cloud.firestore import Client
from app.crud.base import BaseCRUD
from app.models.content import ContentModel


class ContentCRUD(BaseCRUD):
    """CRUD operations for content documents."""
    
    def __init__(self, db: Client):
        """Initialize content CRUD."""
        super().__init__(db)
    
    @property
    def collection_name(self) -> str:
        """Get collection name."""
        return "content"
    
    async def get_content_list(
        self,
        filters: Optional[List[tuple]] = None,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "created_at"
    ) -> Dict[str, Any]:
        """
        Get paginated list of content with filtering.
        
        Args:
            filters: List of (field, operator, value) tuples
            page: Page number
            page_size: Items per page
            sort_by: Field to sort by
            
        Returns:
            Paginated content list
        """
        return await self.list(
            filters=filters,
            page=page,
            page_size=page_size,
            order_by=sort_by,
            direction="DESCENDING"
        )
    
    async def get_by_category(
        self,
        category: str,
        page: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Get content by category.
        
        Args:
            category: Content category
            page: Page number
            page_size: Items per page
            
        Returns:
            Paginated content in category
        """
        filters = [("categories", "array-contains", category)]
        return await self.get_content_list(
            filters=filters,
            page=page,
            page_size=page_size
        )
    
    async def get_trending(self, limit: int = 10, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get trending content (most viewed in recent days).
        
        Args:
            limit: Number of items to return
            days: Look back this many days
            
        Returns:
            List of trending content
        """
        since_date = datetime.utcnow() - timedelta(days=days)
        
        filters = [("created_at", ">=", since_date)]
        
        query = self.get_collection()
        for field, operator, value in filters:
            query = query.where(field, operator, value)
        
        docs = await query.order_by("view_count", direction="DESCENDING").limit(limit).get()
        
        items = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            items.append(data)
        
        return items
    
    async def search(
        self,
        query: str,
        filters: Optional[List[tuple]] = None,
        page: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Search content by title and description.
        
        Args:
            query: Search query string
            filters: Additional filters
            page: Page number
            page_size: Items per page
            
        Returns:
            Paginated search results
        """
        # Note: For full-text search, consider using Firestore Search or Algolia
        # This is a basic implementation matching title
        search_filters = filters or []
        
        # Search in title
        all_results = []
        docs = await self.get_collection().get()
        
        query_lower = query.lower()
        for doc in docs:
            data = doc.to_dict()
            title = data.get("title", "").lower()
            description = data.get("description", "").lower()
            
            if query_lower in title or query_lower in description:
                data["id"] = doc.id
                all_results.append(data)
        
        # Apply pagination
        total = len(all_results)
        offset = (page - 1) * page_size
        items = all_results[offset:offset + page_size]
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page * page_size) < total
        }
    
    async def increment_view(self, content_id: str) -> int:
        """
        Increment view count.
        
        Args:
            content_id: Content ID
            
        Returns:
            Updated view count
        """
        doc_ref = self.get_collection().document(content_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return 0
        
        data = doc.to_dict()
        new_count = data.get("view_count", 0) + 1
        
        await doc_ref.update({"view_count": new_count})
        return new_count
    
    async def increment_like(self, content_id: str) -> int:
        """
        Increment like count.
        
        Args:
            content_id: Content ID
            
        Returns:
            Updated like count
        """
        doc_ref = self.get_collection().document(content_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return 0
        
        data = doc.to_dict()
        new_count = data.get("like_count", 0) + 1
        
        await doc_ref.update({"like_count": new_count})
        return new_count
    
    async def decrement_like(self, content_id: str) -> int:
        """
        Decrement like count.
        
        Args:
            content_id: Content ID
            
        Returns:
            Updated like count (minimum 0)
        """
        doc_ref = self.get_collection().document(content_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return 0
        
        data = doc.to_dict()
        new_count = max(0, data.get("like_count", 0) - 1)
        
        await doc_ref.update({"like_count": new_count})
        return new_count
    
    async def increment_save(self, content_id: str) -> int:
        """
        Increment save count.
        
        Args:
            content_id: Content ID
            
        Returns:
            Updated save count
        """
        doc_ref = self.get_collection().document(content_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return 0
        
        data = doc.to_dict()
        new_count = data.get("save_count", 0) + 1
        
        await doc_ref.update({"save_count": new_count})
        return new_count
    
    async def decrement_save(self, content_id: str) -> int:
        """
        Decrement save count.
        
        Args:
            content_id: Content ID
            
        Returns:
            Updated save count (minimum 0)
        """
        doc_ref = self.get_collection().document(content_id)
        doc = await doc_ref.get()
        
        if not doc.exists:
            return 0
        
        data = doc.to_dict()
        new_count = max(0, data.get("save_count", 0) - 1)
        
        await doc_ref.update({"save_count": new_count})
        return new_count
