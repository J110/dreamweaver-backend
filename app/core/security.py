"""
Security utilities for token management.
Uses PyJWT if available, falls back to simple hash-based tokens for dev.
"""

import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.config import get_settings


def _get_settings():
    return get_settings()


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create an access token (JWT if available, hash-based fallback)."""
    settings = _get_settings()
    try:
        import jwt
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    except ImportError:
        # Fallback: simple hash token for dev
        payload = json.dumps(data, sort_keys=True)
        return hashlib.sha256(f"{payload}:{time.time()}:{settings.secret_key}".encode()).hexdigest()


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a refresh token."""
    settings = _get_settings()
    try:
        import jwt
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(days=7))
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    except ImportError:
        payload = json.dumps(data, sort_keys=True)
        return hashlib.sha256(f"refresh:{payload}:{time.time()}:{settings.secret_key}".encode()).hexdigest()


def decode_token(token: str, token_type: str = "access") -> Dict[str, Any]:
    """Decode a token. Only works with JWT tokens (not hash fallback)."""
    settings = _get_settings()
    try:
        import jwt
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except ImportError:
        raise ValueError("PyJWT not installed — cannot decode JWT tokens in dev mode")
    except Exception as e:
        raise ValueError(f"Token decode failed: {e}")
