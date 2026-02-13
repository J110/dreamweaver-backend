# Quick Start - Local Dev Mode

## What Changed?

All 9 API endpoint files have been rewritten to work without Firebase. The endpoints now support **dual-mode operation**:
- **Local Dev Mode**: Uses in-memory LocalStore (no external services needed)
- **Firebase Mode**: Uses real Firestore and Firebase Auth (when credentials provided)

## Running in Local Dev Mode

### 1. Make sure Firebase credentials are NOT set
```bash
# In .env file (or environment), either:
# - Don't set FIREBASE_CREDENTIALS_PATH
# - Set it to a non-existent file
# Example:
FIREBASE_CREDENTIALS_PATH=""
```

### 2. Start the server
```bash
uvicorn main:app --reload
```

### 3. Test endpoints
```bash
# Signup
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "password": "secure123",
    "child_age": 8
  }'

# Returns:
# {
#   "user": {
#     "id": "abc123...",
#     "username": "john",
#     "email": "john@dreamweaver.app",
#     "child_age": 8,
#     "created_at": "2024-02-13T..."
#   },
#   "access_token": "def456...",
#   "refresh_token": "def456...",
#   "token_type": "bearer"
# }

# Copy the access_token and use it for authenticated requests
TOKEN="def456..."

# Get user profile
curl -X GET http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"

# List content
curl -X GET "http://localhost:8000/api/v1/content?page=1&page_size=10"

# Generate story
curl -X POST http://localhost:8000/api/v1/generation \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content_type": "STORY",
    "child_age": 8,
    "theme": "adventure",
    "length": "MEDIUM"
  }'
```

## What You Need to Know

### The LocalStore
- Stores all data in RAM (Python dictionaries)
- **Data is lost when app restarts** - this is intentional for dev
- Has the same interface as Firestore (`.collection()`, `.document()`, `.where()`, etc.)
- Loads seed data from `seed_output/` directory if available

### Authentication
- Local mode: Uses simple hash-based tokens (for dev only)
- Users are stored in in-memory dictionary
- Tokens are validated by checking against stored tokens
- No password hashing - credentials stored plain (dev only!)

### Content Generation
- Uses mock story generation (doesn't call Groq API)
- Returns instantly with placeholder audio URLs
- Stories vary by theme and length
- Increments user's daily usage quota

### Subscriptions
- 3 hardcoded tiers: Free (1/day), Pro (5/day), Premium (20/day)
- Upgrading just updates user tier in DB
- No payment processing
- Quota is per calendar day (resets at UTC midnight)

### Search & Filtering
- All filtering happens in Python (compatible with in-memory store)
- Search is simple substring matching (case-insensitive)
- Trending calculated as: `(likes * 5) + views`
- No full-text search indexes

## Key Files

| File | Purpose |
|------|---------|
| `app/api/v1/auth.py` | Signup, login, token refresh |
| `app/api/v1/users.py` | User profile, preferences, quota |
| `app/api/v1/content.py` | Browse content with filters |
| `app/api/v1/generation.py` | Generate mock stories |
| `app/api/v1/interactions.py` | Like and save content |
| `app/api/v1/trending.py` | Trending content |
| `app/api/v1/search.py` | Search by text |
| `app/api/v1/subscriptions.py` | Subscription tiers |
| `app/api/v1/audio.py` | TTS voices and audio URLs |
| `app/dependencies.py` | Shared auth/db dependencies |
| `app/services/local_store.py` | In-memory database implementation |

## Important Patterns

### 1. Always use dependency injection for DB access
```python
@router.get("/endpoint")
async def my_endpoint(db_client=Depends(get_db_client)):
    # Use db_client - works in both modes
    users = db_client.collection("users").get()
```

### 2. Check mode only when needed
```python
if _check_local_mode():
    # Use local functions
    local_create_user(username, password)
else:
    # Use Firebase
    firebase_auth.create_user(...)
```

### 3. Save to DB in both modes
```python
# This works the same in local and Firebase modes
db_client.collection("users").document(uid).set({
    "id": uid,
    "username": "john",
    "created_at": datetime.utcnow()
})
```

### 4. Apply filters in memory for compatibility
```python
# Get all docs
all_docs = [doc.to_dict() for doc in db_client.collection("content").get()]

# Filter in Python (works with LocalStore)
filtered = [d for d in all_docs if d.get("type") == "STORY"]
```

## Common Issues & Solutions

### Issue: "Firebase credentials not initialized"
**Solution**: This is expected in local dev mode. Make sure you're not trying to use Firebase in local mode.

### Issue: Users not persisting between requests
**Solution**: That's correct! LocalStore is in-memory. Data is lost when app restarts. This is intentional for development.

### Issue: Search returns no results
**Solution**: Search is case-insensitive substring matching. Try searching for a substring of the title/description you're looking for.

### Issue: Getting auth errors
**Solution**: Make sure you're:
1. Copying the token correctly from signup/login response
2. Passing it as `Authorization: Bearer <token>`
3. Using the exact token (no modifications)

## Next Steps

1. **Test the endpoints**: Use the curl examples above to verify everything works
2. **Load seed data**: Put JSON files in `seed_output/` to pre-populate content
3. **Create test scripts**: Write Python scripts to automate testing
4. **Try both modes**: Set Firebase credentials to test Firebase mode
5. **Check logs**: Run with `--log-level debug` for more details

## When Ready for Firebase

1. Get Firebase credentials JSON file
2. Set environment variable: `FIREBASE_CREDENTIALS_PATH=/path/to/credentials.json`
3. **No code changes needed** - same endpoints work with Firebase!
4. Initialize Firebase in your main.py startup
5. Data persists in real Firestore instead of memory

## Data Model Reference

### Users Collection
```json
{
  "id": "user_uid",
  "uid": "user_uid",
  "username": "john",
  "email": "john@dreamweaver.app",
  "child_age": 8,
  "subscription_tier": "free",
  "daily_usage": 1,
  "daily_limit": 1,
  "preferences": {
    "language": "en",
    "notifications_enabled": true
  },
  "created_at": "2024-02-13T...",
  "updated_at": "2024-02-13T..."
}
```

### Content Collection
```json
{
  "id": "content_id",
  "type": "STORY",
  "title": "The Adventure",
  "description": "An exciting adventure",
  "text": "Once upon a time...",
  "category": "adventure",
  "theme": "adventure",
  "child_age": 8,
  "duration": 300,
  "audio_url": "https://example.com/audio.mp3",
  "view_count": 5,
  "like_count": 2,
  "save_count": 1,
  "created_at": "2024-02-13T...",
  "is_generated": true
}
```

### Interactions Collection
```json
{
  "id": "interaction_id",
  "user_id": "user_uid",
  "content_id": "content_id",
  "type": "like",  // or "save"
  "created_at": "2024-02-13T..."
}
```

## API Endpoints Summary

### Auth (/api/v1/auth)
- `POST /signup` - Create user account
- `POST /login` - Authenticate user
- `POST /refresh` - Refresh token
- `POST /logout` - Logout user

### Users (/api/v1/users)
- `GET /me` - Get current user
- `PUT /me` - Update profile
- `PUT /preferences` - Update preferences
- `GET /quota` - Get daily quota status

### Content (/api/v1/content)
- `GET /` - List content
- `GET /{id}` - Get single content
- `GET /categories/list` - List categories

### Generation (/api/v1/generation)
- `POST /` - Generate new story
- `GET /{id}` - Get generation status

### Interactions (/api/v1/interactions)
- `POST /content/{id}/like` - Like content
- `DELETE /content/{id}/like` - Unlike content
- `POST /content/{id}/save` - Save content
- `DELETE /content/{id}/save` - Unsave content
- `GET /me/likes` - List liked content
- `GET /me/saves` - List saved content

### Trending (/api/v1/trending)
- `GET /` - Get trending (top 20)
- `GET /weekly` - Get weekly trending
- `GET /by-category/{category}` - Trending by category

### Search (/api/v1/search)
- `GET /` - Search content

### Subscriptions (/api/v1/subscriptions)
- `GET /tiers` - List subscription tiers
- `GET /current` - Get current subscription
- `POST /upgrade` - Upgrade subscription

### Audio (/api/v1/audio)
- `GET /voices` - List TTS voices
- `GET /{content_id}` - Get audio URL
- `POST /tts/preview` - Preview TTS

---

**Happy Coding!** 🚀
