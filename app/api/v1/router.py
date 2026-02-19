"""Main v1 API router that aggregates all sub-routers."""

from fastapi import APIRouter

from .auth import router as auth_router
from .users import router as users_router
from .content import router as content_router
from .trending import router as trending_router
from .interactions import router as interactions_router
from .subscriptions import router as subscriptions_router
from .search import router as search_router
from .generation import router as generation_router
from .audio import router as audio_router
from .feedback import router as feedback_router

# Main v1 router
router = APIRouter(prefix="/api/v1")

# Include all sub-routers with appropriate prefixes
router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(users_router, prefix="/users", tags=["Users"])
router.include_router(content_router, prefix="/content", tags=["Content"])
router.include_router(trending_router, prefix="/trending", tags=["Trending"])
router.include_router(interactions_router, prefix="/interactions", tags=["Interactions"])
router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Subscriptions"])
router.include_router(search_router, prefix="/search", tags=["Search"])
router.include_router(generation_router, prefix="/generate", tags=["Generation"])
router.include_router(audio_router, prefix="/audio", tags=["Audio"])
router.include_router(feedback_router, prefix="/feedback", tags=["Feedback"])

__all__ = ["router"]
