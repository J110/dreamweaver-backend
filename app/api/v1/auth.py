"""Authentication endpoints for signup, login, and token management."""

import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dependencies import (
    get_db_client,
    _check_local_mode,
    local_create_user,
    local_login,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Request Models
class SignupRequest(BaseModel):
    """Request model for user signup."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    child_age: int = Field(..., ge=2, le=18)


class LoginRequest(BaseModel):
    """Request model for user login."""
    username: str
    password: str


# Response Models
class UserData(BaseModel):
    """User data response."""
    uid: str
    username: str
    child_age: int


class AuthResponse(BaseModel):
    """Response model for auth endpoints."""
    success: bool
    data: Optional[dict] = None
    message: Optional[str] = None


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    db_client=Depends(get_db_client),
    settings=Depends(get_settings),
) -> AuthResponse:
    """
    Create a new user account.
    
    Args:
        request: SignupRequest with username, password, and child_age
        db_client: Database client (Firestore or LocalStore)
        settings: Application settings
        
    Returns:
        AuthResponse with success status and user data including token
        
    Raises:
        HTTPException: If user already exists or validation fails
    """
    try:
        if _check_local_mode():
            # Check if user already exists
            users_collection = db_client.collection("users")
            existing_users = users_collection.where("username", "==", request.username).get()
            if existing_users:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already exists"
                )
            
            # Create local user and get auth token
            auth_result = local_create_user(request.username, request.password)
            uid = auth_result["uid"]
            token = auth_result["token"]
            
            # Create user document in database (include password hash for login persistence)
            user_data = {
                "id": uid,
                "uid": uid,
                "username": request.username,
                "password": hashlib.sha256(request.password.encode()).hexdigest(),
                "child_age": request.child_age,
                "subscription_tier": "free",
                "created_at": datetime.utcnow(),
                "daily_usage": 0,
                "preferences": {},
            }
            
            users_collection.document(uid).set(user_data)
            
            logger.info(f"New user created: {request.username} (uid: {uid})")
            
            return AuthResponse(
                success=True,
                data={
                    "uid": uid,
                    "username": request.username,
                    "child_age": request.child_age,
                    "token": token,
                },
                message="Signup successful"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signup failed: {str(e)}"
        )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    db_client=Depends(get_db_client),
    settings=Depends(get_settings),
) -> AuthResponse:
    """
    Authenticate user with username and password.
    
    Args:
        request: LoginRequest with username and password
        db_client: Database client (Firestore or LocalStore)
        settings: Application settings
        
    Returns:
        AuthResponse with success status and user data including token
        
    Raises:
        HTTPException: If credentials are invalid
    """
    try:
        if _check_local_mode():
            # Authenticate user locally
            auth_result = local_login(request.username, request.password)
            
            if not auth_result:
                logger.warning(f"Failed login attempt for user: {request.username}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )
            
            uid = auth_result["uid"]
            token = auth_result["token"]
            
            # Get user document to return full user data
            user_doc = db_client.collection("users").document(uid).get()
            if not user_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )
            
            user_data = user_doc.to_dict()
            
            logger.info(f"User logged in: {request.username} (uid: {uid})")
            
            return AuthResponse(
                success=True,
                data={
                    "uid": uid,
                    "username": user_data.get("username"),
                    "child_age": user_data.get("child_age"),
                    "token": token,
                },
                message="Login successful"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Login failed: {str(e)}"
        )
