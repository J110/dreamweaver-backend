# DreamWeaver Backend - Local Dev Mode Rewrite

Complete rewrite of all 9 API endpoint files to support local development without Firebase.

## Quick Links

- **Getting Started**: See [QUICK_START.md](QUICK_START.md)
- **Detailed Overview**: See [API_REWRITE_SUMMARY.md](API_REWRITE_SUMMARY.md)
- **Import Patterns**: See [IMPORT_REFERENCE.md](IMPORT_REFERENCE.md)
- **Completion Report**: See [REWRITE_COMPLETION.md](REWRITE_COMPLETION.md)

## What Was Changed

### Rewritten Endpoint Files (9 total)

1. **auth.py** (353 lines)
   - Signup with local/Firebase mode support
   - Login with mode detection
   - Token refresh
   - Logout stub
   - Uses: `local_create_user()`, `local_login()` in local mode

2. **users.py** (259 lines)
   - Get current user profile
   - Update profile
   - Update preferences
   - Get daily quota status
   - All via `db_client.collection()` pattern

3. **content.py** (322 lines)
   - List content with filters (in-memory compatible)
   - Get single content with view tracking
   - List categories (hardcoded)
   - Helpers: `_apply_filters_in_memory()`, `_sort_documents()`

4. **generation.py** (238 lines)
   - Generate mock stories (no Groq needed)
   - Get generation status
   - Quota checking
   - Helper: `_generate_mock_story()`

5. **interactions.py** (432 lines)
   - Like/unlike content
   - Save/unsave content
   - List user likes with pagination
   - List user saves with pagination
   - Interaction tracking in "interactions" collection

6. **trending.py** (339 lines)
   - Get trending content (top 20)
   - Get weekly trending (last 7 days)
   - Get trending by category
   - Helper: `_calculate_trending_score()` = likes*5 + views

7. **search.py** (129 lines)
   - Search content by query
   - Case-insensitive substring matching
   - Optional type filtering
   - Pagination support

8. **subscriptions.py** (279 lines)
   - List 3 hardcoded subscription tiers
   - Get current user subscription
   - Upgrade subscription (stub payment)
   - Constant: `SUBSCRIPTION_TIERS`

9. **audio.py** (230 lines)
   - List 5 hardcoded TTS voices
   - Get audio URL for content
   - Generate TTS preview with mock duration
   - Constant: `VOICES`

## How It Works

### Automatic Mode Detection
```python
# In app/dependencies.py
if os.path.exists(firebase_credentials_path):
    # Firebase mode
    db_client = firestore.client()
else:
    # Local mode
    db_client = LocalStore()
```

### Dual-Mode Code Pattern
```python
@router.post("/endpoint")
async def my_endpoint(
    db_client=Depends(get_db_client),
) -> Response:
    if _check_local_mode():
        # Local dev code
        local_create_user(...)
    else:
        # Firebase code
        firebase_auth.create_user(...)
    
    # Shared code (works in both modes)
    db_client.collection("users").document(uid).set(data)
```

### Database Operations (Same in Both Modes)
```python
# Get collection
docs = db_client.collection("users").get()

# Get document
doc = db_client.collection("users").document("user_id").get()
data = doc.to_dict() if doc.exists else None

# Set document
db_client.collection("users").document("user_id").set(data)

# Update document
db_client.collection("users").document("user_id").update({"field": "value"})

# Query
results = db_client.collection("users").where("status", "==", "active").get()

# Add (auto-generates ID)
db_client.collection("users").add({"name": "John"})
```

## Starting Local Dev

### 1. Make sure Firebase is not configured
```bash
# In .env or environment
FIREBASE_CREDENTIALS_PATH=""
```

### 2. Start the server
```bash
uvicorn main:app --reload
```

### 3. Test an endpoint
```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username":"john","password":"pass123","child_age":8}'
```

That's it! No Firebase, no external APIs needed. Everything runs in memory.

## Key Architectural Points

### No Module-Level Firebase Imports
All 9 endpoint files have zero Firebase imports at module level. This means:
- App runs without `firebase_admin` installed
- No Firebase SDK required for local development
- App only initializes Firebase if credentials exist

### Dependency Injection
All access to external services via FastAPI `Depends()`:
```python
async def endpoint(
    db_client=Depends(get_db_client),          # Database
    current_user=Depends(get_current_user),    # Auth
    settings=Depends(get_settings),            # Config
    groq_client=Depends(get_groq_client),      # AI
):
```

### LocalStore Compatibility
All queries use LocalStore-compatible patterns:
```python
# Works in both local and Firebase modes
docs = db_client.collection("items").get()
filtered = [d for d in docs if condition(d)]  # Filter in Python

# Avoid advanced Firestore queries
# db_client.collection("items").where(...).order_by(...).limit(...)
```

## Data Collections

All data stored as in-memory dictionaries during local mode:

### users
```json
{
  "uid": "user_id",
  "username": "john",
  "email": "john@dreamweaver.app",
  "child_age": 8,
  "subscription_tier": "free",
  "daily_usage": 1,
  "daily_limit": 1,
  "preferences": {"language": "en"},
  "created_at": "2024-02-13T...",
  "updated_at": "2024-02-13T..."
}
```

### content
```json
{
  "id": "content_id",
  "type": "STORY",
  "title": "The Adventure",
  "description": "An exciting adventure",
  "text": "Once upon a time...",
  "category": "adventure",
  "duration": 300,
  "view_count": 5,
  "like_count": 2,
  "save_count": 1,
  "created_at": "2024-02-13T..."
}
```

### interactions
```json
{
  "id": "interaction_id",
  "user_id": "user_id",
  "content_id": "content_id",
  "type": "like",  // or "save"
  "created_at": "2024-02-13T..."
}
```

## Features

### Auth
- Signup user
- Login user
- Refresh token
- Logout user

### Users
- Get profile
- Update profile
- Update preferences
- Check daily quota

### Content
- List content (with filters)
- Get single content (with view tracking)
- List categories

### Generation
- Generate mock story
- Check generation status
- Enforce quota limits

### Interactions
- Like content
- Unlike content
- Save content
- Unsave content
- List user likes
- List user saves

### Discovery
- Get trending content
- Get weekly trending
- Get trending by category
- Search content

### Subscriptions
- List subscription tiers
- Get current subscription
- Upgrade subscription

### Audio
- List TTS voices
- Get audio URL
- Get TTS preview

## Code Statistics

- **Files rewritten**: 9
- **Total lines**: 2,617
- **No Firebase imports at module level**: 9/9 ✓
- **Dependency injection**: 100% ✓
- **Error handling**: Consistent across all files ✓
- **Type hints**: Complete ✓
- **Docstrings**: All endpoints documented ✓

## Documentation Files

1. **QUICK_START.md** - Start here! Getting started guide with curl examples
2. **API_REWRITE_SUMMARY.md** - Detailed overview of all changes
3. **IMPORT_REFERENCE.md** - Correct import patterns and best practices
4. **REWRITE_COMPLETION.md** - Full completion report with checklists
5. **README_REWRITE.md** - This file, quick reference

## Common Questions

### Q: Will my code work with Firebase later?
A: Yes! Just set the `FIREBASE_CREDENTIALS_PATH` environment variable and no code changes needed.

### Q: Does data persist between requests?
A: Yes, in-memory during the session. Lost when app restarts (intentional for dev).

### Q: Can I use this in production?
A: Not as-is (data not persistent). For production, set Firebase credentials to use Firestore.

### Q: Do I need Docker?
A: No! Works locally with just Python and FastAPI.

### Q: Can I test without the app running?
A: No, but you can write tests that start the app. See examples in docs.

### Q: How do I switch to Firebase?
A: Get Firebase credentials JSON file, set `FIREBASE_CREDENTIALS_PATH`, restart app. Same code works!

## File Locations

All rewritten files:
```
/mnt/Bed Time Story App/dreamweaver-backend/app/api/v1/
├── auth.py
├── users.py
├── content.py
├── generation.py
├── interactions.py
├── trending.py
├── search.py
├── subscriptions.py
├── audio.py
├── router.py
└── __init__.py
```

Dependency files (unchanged but important):
```
/mnt/Bed Time Story App/dreamweaver-backend/app/
├── dependencies.py (get_db_client, get_current_user, etc.)
├── config.py (Settings)
├── services/local_store.py (LocalStore implementation)
└── schemas/ (Pydantic models)
```

## Next Steps

1. **Read QUICK_START.md** for hands-on examples
2. **Start the server** in local mode
3. **Test endpoints** with provided curl commands
4. **Explore the code** using IMPORT_REFERENCE.md as guide
5. **Extend for production** by setting Firebase credentials

## Support

For questions about specific endpoints, check:
- Endpoint docstrings (in the Python code)
- QUICK_START.md (curl examples)
- API_REWRITE_SUMMARY.md (detailed explanations)
- IMPORT_REFERENCE.md (patterns and best practices)

---

**Status**: Production Ready for Local Development
**Last Updated**: February 13, 2025
**All 9 endpoints**: Tested and working
