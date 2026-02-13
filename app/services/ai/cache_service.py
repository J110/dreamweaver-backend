"""Content caching service with TTL support."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

try:
    import cachetools
except ImportError:
    raise ImportError("cachetools package not installed. Install with: pip install cachetools")

logger = logging.getLogger(__name__)


@dataclass
class CachedItem:
    """Represents a cached item with metadata."""
    
    content: Dict[str, Any]
    created_at: datetime
    ttl_seconds: int
    
    def is_expired(self) -> bool:
        """Check if item has expired."""
        if self.ttl_seconds <= 0:
            return False
        
        expiry_time = self.created_at + timedelta(seconds=self.ttl_seconds)
        return datetime.now() > expiry_time


class ContentCache:
    """In-memory content cache with TTL support."""
    
    DEFAULT_TTL = 86400  # 24 hours
    MAX_CACHE_SIZE = 1000
    
    def __init__(self, max_size: int = MAX_CACHE_SIZE, default_ttl: int = DEFAULT_TTL):
        """
        Initialize content cache.
        
        Args:
            max_size: Maximum number of items to cache
            default_ttl: Default time-to-live in seconds (24 hours)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        # Using TTLCache for automatic expiration
        self.cache: Dict[str, CachedItem] = {}
        
        logger.info(
            "ContentCache initialized with max_size=%d, default_ttl=%d seconds",
            max_size, default_ttl
        )
    
    @staticmethod
    def cache_key(params: Dict[str, Any]) -> str:
        """
        Generate a cache key from generation parameters.
        
        Args:
            params: Dictionary of generation parameters
            
        Returns:
            Hash-based cache key
        """
        # Sort params for consistent hashing
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        hash_digest = hashlib.sha256(sorted_params.encode()).hexdigest()
        
        return f"cache_{hash_digest}"
    
    def get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached content.
        
        Args:
            key: Cache key
            
        Returns:
            Cached content or None if not found/expired
        """
        if key not in self.cache:
            logger.debug("Cache miss for key: %s", key)
            return None
        
        cached_item = self.cache[key]
        
        if cached_item.is_expired():
            logger.debug("Cached item expired for key: %s", key)
            del self.cache[key]
            return None
        
        logger.debug("Cache hit for key: %s", key)
        return cached_item.content
    
    def set_cached(
        self,
        key: str,
        content: Dict[str, Any],
        ttl: int = DEFAULT_TTL
    ) -> None:
        """
        Store content in cache.
        
        Args:
            key: Cache key
            content: Content to cache
            ttl: Time-to-live in seconds
        """
        if len(self.cache) >= self.max_size:
            logger.warning("Cache at max size (%d), clearing expired items", self.max_size)
            self.clear_expired()
        
        # If still at max capacity, remove oldest item
        if len(self.cache) >= self.max_size:
            oldest_key = min(
                self.cache.keys(),
                key=lambda k: self.cache[k].created_at
            )
            logger.debug("Removing oldest cache entry: %s", oldest_key)
            del self.cache[oldest_key]
        
        cached_item = CachedItem(
            content=content,
            created_at=datetime.now(),
            ttl_seconds=ttl
        )
        
        self.cache[key] = cached_item
        logger.debug("Cached content with key: %s (ttl=%d seconds)", key, ttl)
    
    def invalidate(self, key: str) -> None:
        """
        Remove specific cached item.
        
        Args:
            key: Cache key to invalidate
        """
        if key in self.cache:
            del self.cache[key]
            logger.debug("Invalidated cache for key: %s", key)
    
    def clear_expired(self) -> None:
        """Remove all expired items from cache."""
        expired_keys = [
            key for key, item in self.cache.items()
            if item.is_expired()
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.info("Cleared %d expired cache items", len(expired_keys))
    
    def clear_all(self) -> None:
        """Clear entire cache."""
        self.cache.clear()
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        self.clear_expired()
        
        return {
            "total_items": len(self.cache),
            "max_size": self.max_size,
            "usage_percent": (len(self.cache) / self.max_size) * 100,
            "default_ttl_seconds": self.default_ttl,
        }


class FirestoreCacheAdapter:
    """
    Optional Firestore backend for persistent caching.
    
    Note: Requires firebase-admin to be installed and configured.
    Usage: pip install firebase-admin
    """
    
    def __init__(self, collection: str = "content_cache"):
        """
        Initialize Firestore cache adapter.
        
        Args:
            collection: Firestore collection name
        """
        try:
            import firebase_admin
            from firebase_admin import firestore
        except ImportError:
            logger.warning(
                "firebase-admin not installed. Firestore caching disabled. "
                "Install with: pip install firebase-admin"
            )
            self.db = None
            return
        
        self.collection = collection
        
        try:
            self.db = firestore.client()
            logger.info("Firestore cache adapter initialized for collection: %s",
                       collection)
        except Exception as e:
            logger.warning("Failed to initialize Firestore: %s", str(e))
            self.db = None
    
    def get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached content from Firestore.
        
        Args:
            key: Cache key
            
        Returns:
            Cached content or None
        """
        if not self.db:
            return None
        
        try:
            doc = self.db.collection(self.collection).document(key).get()
            
            if doc.exists:
                data = doc.to_dict()
                # Check expiration
                if 'expires_at' in data:
                    expires_at = data['expires_at']
                    if isinstance(expires_at, datetime):
                        if datetime.now() > expires_at:
                            logger.debug("Firestore cached item expired: %s", key)
                            return None
                
                logger.debug("Retrieved from Firestore: %s", key)
                return data.get('content')
            
            return None
        except Exception as e:
            logger.error("Firestore get error: %s", str(e))
            return None
    
    def set_cached(
        self,
        key: str,
        content: Dict[str, Any],
        ttl: int = 86400
    ) -> None:
        """
        Store content in Firestore.
        
        Args:
            key: Cache key
            content: Content to cache
            ttl: Time-to-live in seconds
        """
        if not self.db:
            return
        
        try:
            expires_at = datetime.now() + timedelta(seconds=ttl)
            
            self.db.collection(self.collection).document(key).set({
                'content': content,
                'created_at': datetime.now(),
                'expires_at': expires_at,
            })
            
            logger.debug("Cached in Firestore: %s (ttl=%d seconds)", key, ttl)
        except Exception as e:
            logger.error("Firestore set error: %s", str(e))
    
    def invalidate(self, key: str) -> None:
        """Remove cached item from Firestore."""
        if not self.db:
            return
        
        try:
            self.db.collection(self.collection).document(key).delete()
            logger.debug("Invalidated Firestore cache: %s", key)
        except Exception as e:
            logger.error("Firestore invalidate error: %s", str(e))
