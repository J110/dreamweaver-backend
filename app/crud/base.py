"""
Base CRUD Class
Base class for Firestore CRUD operations.
"""

from typing import TypeVar, Generic, List, Dict, Any, Optional, Type
from abc import ABC, abstractmethod
from datetime import datetime
from google.cloud.firestore import Client, Query
from google.cloud.firestore_v1.document import DocumentSnapshot

T = TypeVar("T")


class BaseCRUD(ABC, Generic[T]):
    """
    Base CRUD class for Firestore operations.
    
    Generic base class for database operations with pagination and filtering.
    """
    
    def __init__(self, db: Client):
        """
        Initialize CRUD with Firestore client.
        
        Args:
            db: Firestore client instance
        """
        self.db = db
    
    @property
    @abstractmethod
    def collection_name(self) -> str:
        """Get collection name. Must be implemented by subclass."""
        pass
    
    def get_collection(self) -> Any:
        """
        Get Firestore collection reference.
        
        Returns:
            Firestore collection reference
        """
        return self.db.collection(self.collection_name)
    
    async def create(self, data: Dict[str, Any]) -> str:
        """
        Create a new document.
        
        Args:
            data: Document data dictionary
            
        Returns:
            Created document ID
        """
        data["created_at"] = datetime.utcnow()
        doc_ref = self.get_collection().document()
        await doc_ref.set(data)
        return doc_ref.id
    
    async def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get document by ID.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document data or None if not found
        """
        doc = await self.get_collection().document(doc_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None
    
    async def update(self, doc_id: str, data: Dict[str, Any]) -> bool:
        """
        Update a document.
        
        Args:
            doc_id: Document ID
            data: Fields to update
            
        Returns:
            True if successful, False if document not found
        """
        data["updated_at"] = datetime.utcnow()
        result = await self.get_collection().document(doc_id).update(data)
        return result is not None
    
    async def delete(self, doc_id: str) -> bool:
        """
        Delete a document.
        
        Args:
            doc_id: Document ID
            
        Returns:
            True if deleted, False if not found
        """
        await self.get_collection().document(doc_id).delete()
        return True
    
    async def list(
        self,
        filters: Optional[List[tuple]] = None,
        page: int = 1,
        page_size: int = 10,
        order_by: Optional[str] = None,
        direction: str = "ASCENDING"
    ) -> Dict[str, Any]:
        """
        List documents with filtering and pagination.
        
        Args:
            filters: List of (field, operator, value) tuples for filtering
            page: Page number (1-indexed)
            page_size: Items per page
            order_by: Field to order results by
            direction: Sort direction (ASCENDING or DESCENDING)
            
        Returns:
            Dictionary with items, total count, pagination info
        """
        query = self.get_collection()
        
        # Apply filters
        if filters:
            for field, operator, value in filters:
                query = query.where(field, operator, value)
        
        # Get total count before pagination
        total = len(await query.get())
        
        # Apply ordering
        if order_by:
            direction_enum = "DESCENDING" if direction == "DESCENDING" else "ASCENDING"
            query = query.order_by(order_by, direction=direction_enum)
        
        # Apply pagination
        offset = (page - 1) * page_size
        docs = await query.offset(offset).limit(page_size).get()
        
        items = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            items.append(data)
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page * page_size) < total
        }
    
    async def count(self, filters: Optional[List[tuple]] = None) -> int:
        """
        Count documents matching filters.
        
        Args:
            filters: List of (field, operator, value) tuples for filtering
            
        Returns:
            Count of matching documents
        """
        query = self.get_collection()
        
        if filters:
            for field, operator, value in filters:
                query = query.where(field, operator, value)
        
        docs = await query.get()
        return len(docs)
    
    async def exists(self, doc_id: str) -> bool:
        """
        Check if document exists.
        
        Args:
            doc_id: Document ID
            
        Returns:
            True if document exists
        """
        doc = await self.get_collection().document(doc_id).get()
        return doc.exists
