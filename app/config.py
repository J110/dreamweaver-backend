"""
Configuration module for DreamWeaver backend.
Loads settings from .env file and environment variables.
Works with or without pydantic-settings installed.
"""

import os
from pathlib import Path
from typing import List

# Try to load .env file
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


class Settings:
    """Application configuration loaded from environment variables."""

    def __init__(self):
        self.app_name: str = os.getenv("APP_NAME", "DreamWeaver")
        self.api_version: str = os.getenv("API_VERSION", "v1")
        self.debug: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")
        self.environment: str = os.getenv("ENVIRONMENT", "development")

        # API Keys
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", "")
        self.firebase_credentials_path: str = os.getenv("FIREBASE_CREDENTIALS_PATH", "")

        # Firebase
        self.storage_bucket: str = os.getenv("STORAGE_BUCKET", "")

        # CORS
        cors_raw = os.getenv("CORS_ORIGINS", "*")
        self.cors_origins: List[str] = [s.strip() for s in cors_raw.split(",")]

        # Quotas
        self.max_content_per_day_free: int = int(os.getenv("MAX_CONTENT_PER_DAY_FREE", "1"))
        self.max_content_per_day_premium: int = int(os.getenv("MAX_CONTENT_PER_DAY_PREMIUM", "5"))

        # Cache
        self.tts_cache_dir: str = os.getenv("TTS_CACHE_DIR", "./cache/tts")
        self.album_art_cache_dir: str = os.getenv("ALBUM_ART_CACHE_DIR", "./cache/album_art")
        self.background_music_dir: str = os.getenv("BACKGROUND_MUSIC_DIR", "./cache/background_music")

        # Kokoro TTS (lightweight 82M model, runs on CPU)
        self.kokoro_lang_code: str = os.getenv("KOKORO_LANG_CODE", "a")  # 'a' = American English

        # Security
        self.secret_key: str = os.getenv("SECRET_KEY", "dreamweaver-dev-secret")
        self.algorithm: str = os.getenv("ALGORITHM", "HS256")
        self.access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


_settings = None


def get_settings() -> Settings:
    """Get application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
