"""FastAPI application entry point for DreamWeaver."""

import os
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

# Get settings
settings = get_settings()

# Configure logging
configure_logging(debug=settings.debug)


# ── Background tasks ──────────────────────────────────────────────────────
_keep_alive_task = None
_content_poll_task = None


async def _keep_alive_loop():
    """Ping our own /health endpoint every 14 minutes to stay awake."""
    import httpx

    # Determine our own URL from RENDER_EXTERNAL_URL or PORT
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = os.getenv("PORT", "8000")

    if render_url:
        ping_url = f"{render_url}/health"
    else:
        ping_url = f"http://0.0.0.0:{port}/health"

    logger.info(f"Keep-alive started, pinging {ping_url} every 14 minutes")

    while True:
        await asyncio.sleep(14 * 60)  # 14 minutes
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(ping_url)
                logger.info(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")


async def _content_poll_loop():
    """Poll seed_output/content.json for changes every 60 seconds.

    Safety net: even if the pipeline's reload HTTP call fails,
    new content will be picked up within 60 seconds.
    """
    from app.dependencies import _check_local_mode

    if not _check_local_mode():
        return  # Only needed in LocalStore mode

    from app.services.local_store import get_local_store
    store = get_local_store()

    logger.info("Content polling started (60s interval)")

    while True:
        await asyncio.sleep(60)
        try:
            if store.has_seed_changed():
                result = store.reload_content()
                logger.info(
                    "Auto-reload: %d -> %d items (%+d new)",
                    result["previous_count"],
                    result["current_count"],
                    result["added"],
                )
        except Exception as e:
            logger.warning("Content poll error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown events."""
    global _keep_alive_task, _content_poll_task

    # Startup event
    logger.info(f"Starting {settings.app_name} API v{settings.api_version}")

    # Create cache directories
    cache_dirs = [
        settings.tts_cache_dir,
        settings.album_art_cache_dir,
        settings.background_music_dir,
    ]

    for cache_dir in cache_dirs:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"Cache directory ready: {cache_dir}")

    logger.info(f"Running in {settings.environment} mode")
    logger.info(f"Debug mode: {settings.debug}")

    # Start keep-alive task (only in production / on Render)
    if os.getenv("RENDER") or settings.environment == "production":
        _keep_alive_task = asyncio.create_task(_keep_alive_loop())
        logger.info("Keep-alive background task started (Render free tier protection)")

    # Start content polling (hot-reload without restart)
    _content_poll_task = asyncio.create_task(_content_poll_loop())
    logger.info("Content polling background task started (60s interval)")

    yield

    # Shutdown event
    for task in [_keep_alive_task, _content_poll_task]:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    logger.info(f"Shutting down {settings.app_name} API")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI-powered bedtime story generation API",
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware (order matters: last-added = outermost = first to run) ──

# 1. Error handler added first → innermost layer
app.add_middleware(ErrorHandlerMiddleware)

# 2. CORS added last → outermost layer (processes OPTIONS preflight first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Allow all origins
    allow_credentials=False,       # Cannot use credentials with allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include API routers
from app.api.v1 import router as v1_router  # noqa: E402

app.include_router(v1_router)

# Mount pre-generated audio files
pregen_dir = Path("audio/pre-gen")
pregen_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio/pre-gen", StaticFiles(directory="audio/pre-gen"), name="pre-gen-audio")


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    tags=["Health"],
    summary="Health check endpoint",
)
async def health_check() -> JSONResponse:
    """Health check endpoint for monitoring."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.api_version,
        },
    )


@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    tags=["Root"],
    summary="Welcome endpoint",
)
async def root() -> JSONResponse:
    """Root endpoint with welcome message."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": f"Welcome to {settings.app_name}",
            "version": settings.api_version,
            "docs_url": "/docs",
            "redoc_url": "/redoc",
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
