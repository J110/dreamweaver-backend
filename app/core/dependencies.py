"""Core dependencies for FastAPI endpoints."""

from typing import Dict, Optional
from fastapi import Depends, Header, HTTPException, status
from app.dependencies import get_current_user

__all__ = ["get_current_user"]
