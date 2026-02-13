"""
Shared application dependencies.
Supports both Firebase mode and local development mode.
"""

import os
import time
import hashlib
from typing import Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Global Instances
_db_client = None
_groq_client = None
_is_local_mode = None


def _check_local_mode() -> bool:
    """Determine if we should use local mode (no Firebase)."""
    global _is_local_mode
    if _is_local_mode is not None:
        return _is_local_mode

    settings = get_settings()
    cred_path = settings.firebase_credentials_path

    if not cred_path or not os.path.exists(cred_path):
        logger.info("Firebase credentials not found - running in LOCAL DEV mode")
        _is_local_mode = True
    else:
        _is_local_mode = False

    return _is_local_mode


def get_db_client(settings: Settings = Depends(get_settings)):
    """Get database client - Firestore in prod, LocalStore in dev."""
    global _db_client
    if _db_client is not None:
        return _db_client

    if _check_local_mode():
        from app.services.local_store import get_local_store
        _db_client = get_local_store()
        logger.info("Using LocalStore (in-memory) database")
    else:
        from firebase_admin import firestore
        _db_client = firestore.client()
        logger.info("Using Firestore database")

    return _db_client


def get_groq_client(settings: Settings = Depends(get_settings)):
    """Get Groq API client instance."""
    global _groq_client
    if _groq_client is not None:
        return _groq_client

    api_key = settings.groq_api_key
    if not api_key:
        logger.warning("No Groq API key - AI generation will use mock data")
        return None

    try:
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized")
        return _groq_client
    except ImportError:
        logger.warning("groq package not installed - AI generation will use mock data")
        return None


# Local Auth Store (for dev mode without Firebase)
_local_users: Dict[str, dict] = {}
_local_tokens: Dict[str, str] = {}  # token -> uid


def local_create_user(username: str, password: str) -> dict:
    uid = hashlib.sha256(username.encode()).hexdigest()[:28]
    _local_users[uid] = {
        "uid": uid,
        "username": username,
        "password": password,
        "email": f"{username}@dreamweaver.app",
    }
    token = hashlib.sha256(f"{uid}:{time.time()}".encode()).hexdigest()
    _local_tokens[token] = uid
    return {"uid": uid, "token": token, "username": username}


def local_login(username: str, password: str) -> Optional[dict]:
    for uid, user in _local_users.items():
        if user["username"] == username and user["password"] == password:
            token = hashlib.sha256(f"{uid}:{time.time()}".encode()).hexdigest()
            _local_tokens[token] = uid
            return {"uid": uid, "token": token, "username": username}
    return None


def local_verify_token(token: str) -> Optional[dict]:
    uid = _local_tokens.get(token)
    if uid and uid in _local_users:
        return _local_users[uid]
    return None


async def get_current_user(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> Dict[str, str]:
    """Get current user from auth token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization.replace("Bearer ", "")

    if _check_local_mode():
        user = local_verify_token(token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return {"uid": user["uid"], "email": user.get("email", ""), "username": user.get("username", "")}
    else:
        try:
            from firebase_admin import auth as firebase_auth
            decoded = firebase_auth.verify_id_token(token)
            return {"uid": decoded["uid"], "email": decoded.get("email", "")}
        except Exception as e:
            logger.error(f"Firebase token verification failed: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_optional_user(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> Optional[Dict[str, str]]:
    """Get current user if authenticated, otherwise None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user(authorization, settings)
    except HTTPException:
        return None


class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        if key not in self.requests:
            self.requests[key] = []
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) < self.max_requests:
            self.requests[key].append(now)
            return True
        return False


_rate_limiter = RateLimiter()


def check_rate_limit(user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, str]:
    uid = user.get("uid", "anonymous")
    if not _rate_limiter.is_allowed(uid):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    return user
