# DreamWeaver Backend API Rewrite - Local Dev Mode Support

## Overview

All API endpoint files have been rewritten to work in local development mode without Firebase, while maintaining compatibility with Firebase in production. The key architectural pattern is:

- **Database**: Use `get_db_client()` which returns either Firestore client OR LocalStore (in-memory)
- **Authentication**: Use `get_current_user()` which handles both local tokens and Firebase tokens
- **Mode Detection**: Use `_check_local_mode()` to determine if running in local or Firebase mode

## Key Changes by File

### 1. **auth.py** - Authentication Endpoints
- POST `/signup`: In local mode uses `local_create_user()`, in Firebase mode uses `firebase_admin.auth`
- POST `/login`: In local mode uses `local_login()`, in Firebase mode uses `firebase_admin.auth`
- POST `/refresh`: Returns same token in local mode, refreshes custom token in Firebase mode
- POST `/logout`: Stub endpoint (handled client-side)

**Key Pattern**:
```python
from app.dependencies import get_db_client, _check_local_mode, local_create_user

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    db_client=Depends(get_db_client),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    if _check_local_mode():
        # Local mode: use local_create_user()
        auth_result = local_create_user(request.username, request.password)
    else:
        # Firebase mode: use firebase_admin.auth
        firebase_user = firebase_auth.create_user(...)
    
    # Save user doc to db (works in both modes)
    db_client.collection("users").document(uid).set(user_data)
```

### 2. **users.py** - User Profile Management
- GET `/me`: Retrieves user document from db_client
- PUT `/me`: Updates user profile fields
- PUT `/preferences`: Updates user preferences nested object
- GET `/quota`: Returns daily usage and limits

**No Firebase-specific code** - all uses `db_client.collection()` pattern

### 3. **content.py** - Content Browsing
- GET `/`: Lists content with filters (type, category, age range)
  - Applies filters in-memory for LocalStore compatibility
  - Sorts by newest/popular/duration
  - Implements pagination
- GET `/{id}`: Retrieves single content, logs view, increments view_count
- GET `/categories/list`: Returns hardcoded categories (or from seed data)

**Key Pattern** (LocalStore-compatible filtering):
```python
def _apply_filters_in_memory(docs: List[dict], filters: dict) -> List[dict]:
    """Apply filters to in-memory documents (for LocalStore)."""
    filtered = docs
    if filters.get("type"):
        filtered = [d for d in filtered if d.get("type") == filters["type"]]
    # ... more filters
    return filtered

# In endpoint:
content_docs = db_client.collection("content").get()
all_docs = [doc.to_dict() for doc in content_docs if doc.exists]
filtered_docs = _apply_filters_in_memory(all_docs, filters)
sorted_docs = _sort_documents(filtered_docs, sort_by)
```

### 4. **generation.py** - AI Content Generation
- POST `/`: Validates quota, generates mock story, saves to db
  - Uses `_generate_mock_story()` for local dev
  - In production, would call Groq API (via `get_groq_client()` dependency)
  - Returns status 202 Accepted
- GET `/{id}`: Returns generation status and content details

**Key Pattern** (Mock generation for local mode):
```python
def _generate_mock_story(theme: str, child_age: int, length: str) -> dict:
    """Generate a mock story for local dev mode."""
    stories = {
        "adventure": "Once upon a time...",
        "fantasy": "In a magical kingdom...",
    }
    text = stories.get(theme, stories["default"])
    # ... extend based on length
    return {
        "text": text,
        "title": f"The {theme.capitalize()} Story",
        "duration": duration,
        "audio_url": "https://example.com/audio/mock.mp3",
    }
```

### 5. **interactions.py** - Likes & Saves
- POST `/content/{id}/like`: Adds like, increments like_count
- DELETE `/content/{id}/like`: Removes like, decrements like_count
- POST `/content/{id}/save`: Adds bookmark, increments save_count
- DELETE `/content/{id}/save`: Removes bookmark, decrements save_count
- GET `/me/likes`: Lists user's liked content with pagination
- GET `/me/saves`: Lists user's saved content with pagination

**Key Pattern** (Interaction tracking):
```python
# Add interaction
interaction_data = {
    "id": str(uuid.uuid4()),
    "user_id": user_id,
    "content_id": content_id,
    "type": "like",  # or "save"
    "created_at": datetime.utcnow(),
}
db_client.collection("interactions").add(interaction_data)

# Check if liked/saved
likes = db_client.collection("interactions").where(
    "user_id", "==", user_id
).where(
    "content_id", "==", content_id
).where(
    "type", "==", "like"
).get()
is_liked = bool(likes)
```

### 6. **trending.py** - Trending Content
- GET `/`: Returns top 20 trending content sorted by score (like_count * 5 + view_count)
- GET `/weekly`: Same but filtered to last 7 days
- GET `/by-category/{category}`: Trending content in specific category

**Key Pattern** (Trending score):
```python
def _calculate_trending_score(content: dict) -> float:
    """Calculate trending score based on likes and views."""
    like_count = content.get("like_count", 0)
    view_count = content.get("view_count", 0)
    return (like_count * 5) + view_count

sorted_docs = sorted(all_docs, key=lambda x: _calculate_trending_score(x), reverse=True)
```

### 7. **search.py** - Content Search
- GET `/`: Searches content by query string (case-insensitive)
  - Searches title, description, theme fields
  - Supports optional type filtering
  - Implements pagination

**Key Pattern** (In-memory search):
```python
search_term = q.lower()
matched_docs = []
for doc_data in all_docs:
    title = (doc_data.get("title") or "").lower()
    description = (doc_data.get("description") or "").lower()
    if search_term in title or search_term in description:
        matched_docs.append(doc_data)
```

### 8. **subscriptions.py** - Subscription Management
- GET `/tiers`: Returns 3 hardcoded subscription tiers (Free, Pro, Premium)
  - Free: 1 story/day, $0
  - Pro: 5 stories/day, $4.99/month
  - Premium: 20 stories/day, $9.99/month
- GET `/current`: Returns user's current subscription
- POST `/upgrade`: Updates user subscription tier
  - Stub implementation (no payment processing in local mode)

**Key Pattern** (Hardcoded tiers):
```python
SUBSCRIPTION_TIERS = {
    "free": {
        "id": "free",
        "name": "Free",
        "price": 0.0,
        "daily_limit": 1,
        "features": [...]
    },
    "pro": {...},
    "premium": {...}
}
```

### 9. **audio.py** - Audio & TTS
- GET `/voices`: Lists 5 hardcoded TTS voices
  - Female: Emma (US), Zara (US), Sophie (UK)
  - Male: David (US), Oliver (UK)
- GET `/{content_id}`: Returns audio URL and metadata for content
- POST `/tts/preview`: Generates TTS preview
  - Returns mock preview URL in local mode
  - Duration estimated based on word count (~150 wpm)

**Key Pattern** (Hardcoded voices):
```python
VOICES = [
    {
        "id": "voice_01",
        "name": "Emma",
        "language": "en-US",
        "gender": "female",
        "accent": "neutral",
    },
    # ... more voices
]
```

## Dependency Imports

All files now import dependencies from the same locations:

```python
# Database & Auth
from app.dependencies import (
    get_db_client,           # Returns Firestore or LocalStore
    _check_local_mode,       # bool: True if local, False if Firebase
    get_current_user,        # Returns authenticated user dict
    local_create_user,       # Creates local user
    local_login,             # Authenticates local user
    get_groq_client,         # Returns Groq client (may be None)
)

# Config
from app.config import Settings, get_settings

# Schemas
from app.schemas.user_schema import UserResponse, TokenResponse, AuthResponse
from app.schemas.content_schema import ContentResponse, ContentListResponse
```

## LocalStore Interface

The `LocalStore` class (in `app.services.local_store.py`) provides the same interface as Firestore:

```python
# Get collection
collection = db_client.collection("users")

# Get document
doc = collection.document("user_id").get()
if doc.exists:
    data = doc.to_dict()

# Set document
collection.document("user_id").set(data)

# Update document
collection.document("user_id").update({"field": "value"})

# Delete document
collection.document("user_id").delete()

# Query collection
docs = collection.where("field", "==", "value").get()
for doc in docs:
    data = doc.to_dict()

# Add document (auto-generates ID)
collection.add({"field": "value"})
```

## No Firebase Imports at Module Level

None of the endpoint files import Firebase at the module level:

```python
# ✓ CORRECT - Imports only happen inside conditionals
if _check_local_mode():
    # local mode
else:
    from firebase_admin import auth as firebase_auth
    firebase_user = firebase_auth.create_user(...)

# ✗ WRONG - Don't do this
from firebase_admin import firestore  # Module-level import
db = firestore.client()  # Will fail if Firebase not initialized
```

## Testing Local Dev Mode

To test locally without Firebase:

1. Make sure `FIREBASE_CREDENTIALS_PATH` is not set or points to non-existent file
2. Start the app normally:
   ```bash
   python -m uvicorn main:app --reload
   ```
3. Test endpoints using curl or Postman:
   ```bash
   # Signup
   curl -X POST http://localhost:8000/api/v1/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"username":"testuser","password":"password123","child_age":8}'
   
   # Login
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"testuser","password":"password123"}'
   
   # Get profile (use token from login response)
   curl -X GET http://localhost:8000/api/v1/users/me \
     -H "Authorization: Bearer <token_from_login>"
   ```

## Error Handling

All endpoints use consistent error handling:

```python
try:
    # Endpoint logic
    ...
except HTTPException:
    # Re-raise HTTPException as-is
    raise
except Exception as e:
    # Wrap other exceptions
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Operation failed: {str(e)}"
    )
```

## Summary of Benefits

1. **No External Dependencies**: Works without Firebase, Groq, or any external services
2. **Pure In-Memory Store**: LocalStore keeps all data in memory (resets on app restart)
3. **Same Interface**: DB operations work the same in local and Firebase modes
4. **Testable**: Easy to test endpoints without cloud credentials
5. **Development-Friendly**: Fast iteration cycle, no network latency
6. **Production-Ready**: Same code works with Firebase by just setting credentials

## Files Modified

- `/app/api/v1/auth.py` - Authentication endpoints
- `/app/api/v1/users.py` - User profile management
- `/app/api/v1/content.py` - Content browsing
- `/app/api/v1/generation.py` - AI generation (mock)
- `/app/api/v1/interactions.py` - Likes and saves
- `/app/api/v1/trending.py` - Trending content
- `/app/api/v1/search.py` - Content search
- `/app/api/v1/subscriptions.py` - Subscription tiers
- `/app/api/v1/audio.py` - Audio and TTS

All modifications maintain 100% backward compatibility with existing schemas and response models.
