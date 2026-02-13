"""Trending algorithm for DreamWeaver content discovery."""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from math import exp
import cachetools

logger = logging.getLogger(__name__)


class TrendingService:
    """Service for calculating and retrieving trending content using a weighted scoring algorithm."""
    
    # Cache configuration
    CACHE_TTL = 900  # 15 minutes in seconds
    CACHE_MAX_SIZE = 1000
    
    # Score weights
    WEIGHT_VIEWS = 1.0
    WEIGHT_LIKES = 5.0
    WEIGHT_SAVES = 3.0
    
    # Age decay parameters
    HALF_LIFE_DAYS = 30  # 30-day half-life
    
    # Content quality boost
    QUALITY_BOOST_FACTOR = 0.1
    
    def __init__(self):
        """Initialize trending service with caching."""
        # Cache for trending results
        self._trending_cache = cachetools.TTLCache(
            maxsize=self.CACHE_MAX_SIZE,
            ttl=self.CACHE_TTL
        )
        self._cache_lock = False
        
    def calculate_trending_score(self, content: Dict, days: int = 7) -> float:
        """Calculate trending score for a piece of content.
        
        Formula: (views * 1.0 + likes * 5.0 + saves * 3.0) * age_decay * quality_boost
        
        Args:
            content: Content dictionary with keys:
                - views: Number of views (int)
                - likes: Number of likes (int)
                - saves: Number of saves (int)
                - created_at: Creation timestamp (datetime or ISO string)
                - generation_quality: Quality score 0-10 for AI content (optional, float)
            days: Time window for decay calculation (default 7)
            
        Returns:
            Trending score as float (higher = more trendy)
            
        Raises:
            ValueError: If required fields are missing
            TypeError: If values are wrong type
        """
        try:
            # Validate and extract engagement metrics
            views = int(content.get("views", 0))
            likes = int(content.get("likes", 0))
            saves = int(content.get("saves", 0))
            
            if views < 0 or likes < 0 or saves < 0:
                raise ValueError("Engagement metrics cannot be negative")
            
            # Calculate engagement score
            engagement_score = (
                (views * self.WEIGHT_VIEWS) +
                (likes * self.WEIGHT_LIKES) +
                (saves * self.WEIGHT_SAVES)
            )
            
            # Calculate age decay
            created_at = content.get("created_at")
            age_decay = self._calculate_age_decay(created_at, days)
            
            # Calculate quality boost (for AI-generated content)
            quality_boost = self._calculate_quality_boost(content)
            
            # Final score
            score = engagement_score * age_decay * quality_boost
            
            logger.debug(f"Trending score calculated: {score:.2f} "
                        f"(engagement={engagement_score:.2f}, age_decay={age_decay:.4f}, "
                        f"quality_boost={quality_boost:.2f})")
            
            return max(0.0, score)  # Ensure non-negative score
            
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error calculating trending score: {e}")
            raise ValueError(f"Invalid content format: {e}")
    
    def get_trending(self, limit: int = 20, category: Optional[str] = None,
                    age_range: Optional[Tuple[int, int]] = None) -> List[Dict]:
        """Get trending content with caching.
        
        Args:
            limit: Maximum number of results to return (default 20)
            category: Filter by category (optional)
            age_range: Filter by age in days (min, max) (optional)
            
        Returns:
            List of trending content dictionaries sorted by score (highest first)
            
        Note:
            This is a simplified implementation. In production, this would query
            the database for content from the last 30 days.
        """
        cache_key = f"trending_{limit}_{category}_{age_range}"
        
        # Check cache first
        if cache_key in self._trending_cache:
            logger.debug(f"Returning cached trending results")
            return self._trending_cache[cache_key]
        
        try:
            # In production, this would query the database
            # For now, return empty list (to be implemented with actual DB)
            trending_results = self._compute_trending(limit, category, age_range)
            
            # Cache the results
            self._trending_cache[cache_key] = trending_results
            
            logger.info(f"Trending results computed: {len(trending_results)} items")
            return trending_results
            
        except Exception as e:
            logger.error(f"Error retrieving trending content: {e}")
            return []
    
    def get_weekly_trending(self, limit: int = 20) -> List[Dict]:
        """Get trending content from the last 7 days.
        
        Args:
            limit: Maximum number of results (default 20)
            
        Returns:
            List of trending content from last week
        """
        return self.get_trending(limit=limit, age_range=(0, 7))
    
    def refresh_trending_cache(self) -> bool:
        """Manually refresh trending cache.
        
        This pre-computes trending results and updates the cache.
        Useful for periodic cache refresh operations.
        
        Returns:
            True if refresh successful, False otherwise
        """
        try:
            if self._cache_lock:
                logger.warning("Cache refresh already in progress")
                return False
            
            self._cache_lock = True
            
            # Clear old cache
            self._trending_cache.clear()
            
            # Recompute key cache entries
            self.get_trending(limit=20)
            self.get_trending(limit=50)
            self.get_weekly_trending(limit=20)
            
            logger.info("Trending cache refreshed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing trending cache: {e}")
            return False
            
        finally:
            self._cache_lock = False
    
    def clear_cache(self) -> None:
        """Clear the trending cache completely."""
        self._trending_cache.clear()
        logger.info("Trending cache cleared")
    
    def get_cache_stats(self) -> Dict:
        """Get statistics about the cache.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            "size": len(self._trending_cache),
            "max_size": self.CACHE_MAX_SIZE,
            "ttl": self.CACHE_TTL,
            "is_locked": self._cache_lock,
        }
    
    def _calculate_age_decay(self, created_at, days: int = 7) -> float:
        """Calculate age decay factor using exponential decay.
        
        Formula: exp(-content_age_days / half_life_days)
        
        This ensures newer content ranks higher than older content,
        with a configurable half-life (default 30 days).
        
        Args:
            created_at: Creation timestamp (datetime or ISO string)
            days: Reference period (default 7)
            
        Returns:
            Decay factor between 0.0 and 1.0
        """
        try:
            # Parse created_at timestamp
            if isinstance(created_at, str):
                # Assume ISO format
                created_datetime = datetime.fromisoformat(
                    created_at.replace('Z', '+00:00')
                )
            elif isinstance(created_at, datetime):
                created_datetime = created_at
            else:
                logger.warning("Invalid created_at format, using current time")
                return 1.0
            
            # Calculate age in days
            now = datetime.utcnow() if not created_datetime.tzinfo else datetime.now(created_datetime.tzinfo)
            age_days = (now - created_datetime).total_seconds() / 86400
            
            # Apply exponential decay with 30-day half-life
            decay = exp(-age_days / self.HALF_LIFE_DAYS)
            
            return max(0.0, min(1.0, decay))
            
        except Exception as e:
            logger.error(f"Error calculating age decay: {e}")
            return 1.0  # Default to no decay if error
    
    def _calculate_quality_boost(self, content: Dict) -> float:
        """Calculate quality boost for AI-generated content.
        
        Args:
            content: Content dictionary
            
        Returns:
            Quality boost factor (1.0 = no boost, >1.0 = boost applied)
        """
        try:
            # Check if content has a generation quality score
            quality_score = content.get("generation_quality")
            
            if quality_score is not None:
                quality_score = float(quality_score)
                
                # Validate score is 0-10
                if not 0 <= quality_score <= 10:
                    logger.warning(f"Invalid quality score: {quality_score}")
                    return 1.0
                
                # Apply boost: 1.0 + (quality / 10)
                # This gives 1.0 (no boost) at quality 0, and 2.0 (2x boost) at quality 10
                boost = 1.0 + (quality_score * self.QUALITY_BOOST_FACTOR)
                return boost
            
            return 1.0  # No boost if no quality score
            
        except (ValueError, TypeError) as e:
            logger.error(f"Error calculating quality boost: {e}")
            return 1.0
    
    def _compute_trending(self, limit: int, category: Optional[str],
                         age_range: Optional[Tuple[int, int]]) -> List[Dict]:
        """Compute trending content (to be implemented with database queries).
        
        Args:
            limit: Number of results
            category: Optional category filter
            age_range: Optional age range filter
            
        Returns:
            List of trending content (empty in this placeholder)
            
        Note:
            This is a placeholder implementation. In production, this would:
            1. Query database for recent content (last 30 days)
            2. Filter by category and age_range if provided
            3. Calculate trending score for each piece
            4. Sort by score descending
            5. Return top N results
        """
        # Placeholder: In production, query database here
        logger.debug(f"Computing trending: limit={limit}, category={category}, age_range={age_range}")
        return []
