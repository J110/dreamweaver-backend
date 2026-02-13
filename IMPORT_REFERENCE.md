# Import Reference Guide

## Correct Import Patterns for Rewritten Endpoints

All rewritten endpoint files follow the same import patterns. Use these as templates.

### Complete Import Example (from auth.py)

```python
"""
Module docstring describing the endpoint.
"""

from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.dependencies import (
    get_db_client,
    _check_local_mode,
    local_create_user,
    local_login,
    get_current_user,
    get_groq_client,
)
from app.schemas.user_schema import UserResponse, TokenResponse, AuthResponse
from app.schemas.content_schema import ContentResponse, ContentListResponse

router = APIRouter()
```

## Import Categories

### 1. Standard Library (Always Safe)
```python
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import uuid
```

### 2. FastAPI Framework
```python
from fastapi import APIRouter, HTTPException, Depends, status, Query
```

### 3. Data Validation (Pydantic)
```python
from pydantic import BaseModel, Field
```

### 4. Application Configuration
```python
from app.config import Settings, get_settings
```

### 5. Dependencies (CRITICAL - USE THESE)
```python
# Always available - use dependency injection
from app.dependencies import (
    get_db_client,              # Database client (Firestore or LocalStore)
    _check_local_mode,          # Boolean: True if local, False if Firebase
    get_current_user,           # Get authenticated user
    get_optional_user,          # Get user if authenticated, else None
    local_create_user,          # Create user in local mode
    local_login,                # Login in local mode
    local_verify_token,         # Verify local token
    get_groq_client,            # Get Groq AI client (may be None)
)
```

### 6. Application Schemas
```python
# User-related schemas
from app.schemas.user_schema import (
    UserResponse,
    TokenResponse,
    AuthResponse,
    LoginRequest,
    SignUpRequest,
    UpdateProfileRequest,
    QuotaResponse,
)

# Content-related schemas
from app.schemas.content_schema import (
    ContentResponse,
    ContentListResponse,
    GenerateContentRequest,
    ContentStatusResponse,
)
```

## What NOT to Import at Module Level

### Firebase Imports (DO NOT DO THIS)
```python
# ✗ WRONG - This will fail in local mode
import firebase_admin
from firebase_admin import auth, firestore

db = firestore.client()  # FAILS if Firebase not initialized
```

### External Service Imports (DO NOT DO THIS)
```python
# ✗ WRONG - Will fail if not installed
from groq import Groq
groq_client = Groq(api_key="...")
```

### Direct LocalStore Imports (DO NOT DO THIS)
```python
# ✗ WRONG - Use get_db_client() dependency instead
from app.services.local_store import LocalStore
local_store = LocalStore()  # Wrong!
```

## Correct Pattern for Conditional Imports

When you need Firebase or other external libraries, import them INSIDE the function/conditional:

```python
@router.post("/signup")
async def signup(
    request: SignupRequest,
    db_client=Depends(get_db_client),
):
    if _check_local_mode():
        # Local mode - no imports needed
        auth_result = local_create_user(request.username, request.password)
    else:
        # Firebase mode - import here, not at module level
        from firebase_admin import auth as firebase_auth
        
        firebase_user = firebase_auth.create_user(
            email=f"{request.username}@dreamweaver.app",
            password=request.password,
            display_name=request.username
        )
        # ... rest of Firebase code
```

## Dependency Injection Pattern

All database and authentication operations must use dependency injection:

```python
# ✓ CORRECT
@router.get("/me")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    user_doc = db_client.collection("users").document(current_user["uid"]).get()
    # ...

# ✗ WRONG - Don't do this
db_client = None  # Global variable

@router.get("/me")
async def get_profile(current_user: dict = Depends(get_current_user)):
    global db_client
    if db_client is None:
        from app.dependencies import get_db_client
        db_client = get_db_client()
    # ...
```

## Full File Templates

### Minimal Endpoint Template

```python
"""
Brief description of what this endpoint module does.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client

router = APIRouter()

class RequestModel(BaseModel):
    """Request body model."""
    field: str

@router.get("/endpoint")
async def my_endpoint(
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
):
    """Endpoint description."""
    try:
        # Your logic here
        return {"success": True}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed: {str(e)}"
        )
```

### Full Featured Template

```python
"""
Complete endpoint module with multiple operations.
"""

from datetime import datetime
from typing import Optional, List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.dependencies import (
    get_db_client,
    _check_local_mode,
    get_current_user,
    local_create_user,
)
from app.schemas.user_schema import UserResponse

router = APIRouter()

class RequestModel(BaseModel):
    """Request body."""
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)

class ResponseModel(BaseModel):
    """Response body."""
    id: str
    username: str
    created_at: datetime

def _helper_function(data: dict) -> dict:
    """Helper function for processing."""
    return {**data, "processed": True}

@router.post("/create")
async def create_something(
    request: RequestModel,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
    settings: Settings = Depends(get_settings),
) -> ResponseModel:
    """Create a resource."""
    try:
        # Mode-specific logic
        if _check_local_mode():
            user_data = local_create_user(request.username, request.password)
        else:
            from firebase_admin import auth as firebase_auth
            user_data = {"uid": "firebase_uid"}
        
        # Save to database (works in both modes)
        db_client.collection("users").document(user_data["uid"]).set({
            "id": user_data["uid"],
            "username": request.username,
            "created_at": datetime.utcnow(),
        })
        
        return ResponseModel(
            id=user_data["uid"],
            username=request.username,
            created_at=datetime.utcnow(),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Creation failed: {str(e)}"
        )

@router.get("/list")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db_client=Depends(get_db_client),
) -> List[ResponseModel]:
    """List items with pagination."""
    try:
        # Get all items
        docs = db_client.collection("items").get()
        all_items = [doc.to_dict() for doc in docs if doc.exists]
        
        # Paginate
        offset = (page - 1) * page_size
        items = all_items[offset:offset + page_size]
        
        return [
            ResponseModel(
                id=item.get("id"),
                username=item.get("username"),
                created_at=item.get("created_at"),
            )
            for item in items
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list: {str(e)}"
        )
```

## Module Structure Checklist

When creating or reviewing endpoint files, check:

- [ ] Module docstring at the top
- [ ] All imports from `app.dependencies` (not direct Firestore imports)
- [ ] All imports from `app.schemas.*` (not inline definitions)
- [ ] Database access via `get_db_client` dependency
- [ ] Auth via `get_current_user` dependency
- [ ] Mode checking via `_check_local_mode()` only when needed
- [ ] Conditional Firebase imports inside functions
- [ ] Consistent error handling (try/except -> HTTPException)
- [ ] Pydantic models for request/response validation
- [ ] Type hints on all functions
- [ ] Proper dependency injection with `Depends()`
- [ ] No global variables holding services
- [ ] No module-level database initialization

## Common Pitfalls

### Pitfall 1: Using db_client before dependency injection
```python
# ✗ WRONG
from firebase_admin import firestore
db = firestore.client()  # Fails in local mode

# ✓ CORRECT
async def endpoint(db_client=Depends(get_db_client)):
    db_client.collection("items").get()
```

### Pitfall 2: Checking mode in the wrong place
```python
# ✗ WRONG - Checked at module level
if _check_local_mode():
    from app.services.local_store import get_local_store
    db = get_local_store()
else:
    from firebase_admin import firestore
    db = firestore.client()

# ✓ CORRECT - Checked inside endpoints where needed
async def endpoint(db_client=Depends(get_db_client)):
    if _check_local_mode():
        local_create_user(...)
    else:
        firebase_auth.create_user(...)
```

### Pitfall 3: Not catching HTTPException in error handling
```python
# ✗ WRONG - Lets HTTPException get wrapped
try:
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Not found")
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

# ✓ CORRECT - Re-raises HTTPException
try:
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Not found")
except HTTPException:
    raise  # Re-raise as-is
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

### Pitfall 4: Assuming Firestore query syntax
```python
# ✗ WRONG - LocalStore doesn't support Firestore query syntax
docs = db_client.collection("users").where("age", ">", 18).limit(10).stream()

# ✓ CORRECT - Use compatible method or fetch all and filter
docs = db_client.collection("users").get()
filtered = [d for d in docs if d.to_dict().get("age", 0) > 18][:10]
```

## Required Dependencies

For all endpoints to work, make sure these are available:

```
# app/dependencies.py exports:
- get_db_client()
- _check_local_mode()
- get_current_user()
- get_optional_user()
- local_create_user()
- local_login()
- local_verify_token()
- get_groq_client()

# app/config.py exports:
- Settings
- get_settings()

# app/services/local_store.py exports:
- LocalStore
- get_local_store()
```

All of these are already implemented and tested. Just import and use!

---

**Key Takeaway**: Dependency injection + conditional imports = dual-mode magic
