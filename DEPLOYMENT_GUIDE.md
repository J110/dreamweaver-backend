# DreamWeaver Backend - Deployment Guide for Render

## Overview

The DreamWeaver backend is now fully deployment-ready for Render. It uses a minimal, clean setup with only essential dependencies and supports both local development mode and cloud deployment.

## What's Changed

### 1. Simplified Dependencies (requirements.txt)

Removed all optional dependencies:
- Removed `firebase-admin` - Not needed for local dev mode
- Removed `Pillow` - Image processing (not implemented yet)
- Removed `pydub` - Audio processing (not implemented yet)
- Removed `cairosvg` - SVG rendering (not implemented yet)
- Removed `python-jose` - JWT handling (not implemented yet)
- Removed `cachetools` - Replaced with simple in-memory cache
- Removed `python-dotenv` - Config handled in app/config.py

**Current minimal dependencies:**
- `fastapi==0.109.2` - Web framework
- `uvicorn[standard]==0.27.1` - ASGI server
- `pydantic==2.6.1` - Data validation
- `httpx==0.26.0` - HTTP client
- `groq==0.4.2` - AI API
- `python-multipart==0.0.6` - Form data handling

### 2. Deployment Configuration Files

**render.yaml** - Render deployment configuration
- Specifies Python runtime
- Build and start commands
- Environment variables (GROQ_API_KEY, ENVIRONMENT, DEBUG, CORS_ORIGINS)

**Procfile** - Heroku/Render process definition
- Web process runs: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`

**runtime.txt** - Python version specification
- Python 3.11.7

### 3. Application Architecture

#### app/main.py - Cleaned and simplified
- Single-file entry point
- CORS middleware configured from settings
- Error handler middleware integrated
- Lifespan management for startup/shutdown
- Health check endpoint (`/health`)
- Welcome endpoint (`/`)
- All API v1 routes included

#### app/api/v1/ - Fully functional endpoints

**auth.py**
- `POST /api/v1/auth/signup` - Create new user account
- `POST /api/v1/auth/login` - Authenticate user
- Local dev mode: Uses in-memory user store with hashed tokens
- Returns: `{success: bool, data: {...}, message: string}`

**generation.py**
- `POST /api/v1/generate` - Generate content using Groq API
- Falls back to mock data if Groq unavailable
- Validates daily quota before generation
- Saves content to database
- Increments user daily_usage
- Returns: `{success: bool, data: {...}, message: string}`

**content.py**
- `GET /api/v1/content` - List all content with filtering/pagination
- `GET /api/v1/content/categories` - Get hardcoded categories
- `GET /api/v1/content/{content_id}` - Get single content by ID
- Increments view_count on retrieval

**trending.py**
- `GET /api/v1/trending` - Get trending content (likes * 5 + views)
- `GET /api/v1/trending/weekly` - Weekly trending (same in local mode)
- `GET /api/v1/trending/by-category/{category}` - Trending by category

**interactions.py**
- `POST /api/v1/interactions/content/{content_id}/like` - Add like
- `DELETE /api/v1/interactions/content/{content_id}/like` - Remove like
- `POST /api/v1/interactions/content/{content_id}/save` - Save content
- `DELETE /api/v1/interactions/content/{content_id}/save` - Unsave content
- `GET /api/v1/interactions/me/likes` - Get user's liked content
- `GET /api/v1/interactions/me/saves` - Get user's saved content

**users.py**
- `GET /api/v1/users/me` - Get current user profile
- `PUT /api/v1/users/me` - Update child_age
- `PUT /api/v1/users/preferences` - Update preferences
- `GET /api/v1/users/quota` - Get daily quota info

**subscriptions.py**
- `GET /api/v1/subscriptions/tiers` - List hardcoded tiers (free, premium, family)
- `GET /api/v1/subscriptions/current` - Get user's current tier
- `POST /api/v1/subscriptions/upgrade` - Upgrade subscription tier

**search.py**
- `GET /api/v1/search` - Search content by query (case-insensitive)

**audio.py**
- `GET /api/v1/audio/voices` - List 6 available voices
- `GET /api/v1/audio/{content_id}` - Get audio URL for content
- `POST /api/v1/audio/tts/preview` - Generate TTS preview

### 4. Database Layer

**LocalStore** (app/services/local_store.py)
- In-memory database for development
- Loads seed data from `seed_output/` on startup
- Mimics Firestore API (collection, document, queries)
- Used automatically when Firebase credentials not found

### 5. Authentication

**Local Development Mode:**
- No Firebase required
- User tokens are SHA256 hashes
- Token validation via in-memory store
- Automatic activation when `FIREBASE_CREDENTIALS_PATH` env var not set or file doesn't exist

**Key Functions:**
- `local_create_user()` - Create user and generate token
- `local_login()` - Authenticate user
- `local_verify_token()` - Validate token
- `get_current_user()` - FastAPI dependency for protected routes

## Deployment Steps

### 1. Prepare for Render

```bash
# Create a new Render service
# https://dashboard.render.com

# Set environment variables:
GROQ_API_KEY=your-groq-api-key-here
ENVIRONMENT=production
DEBUG=false
CORS_ORIGINS=https://your-frontend-domain.com
```

### 2. Connect Git Repository

1. Push code to GitHub
2. Connect your repo in Render dashboard
3. Render will automatically detect `render.yaml`

### 3. Configure Build and Deploy

Render will:
1. Detect Python environment
2. Install dependencies from `requirements.txt`
3. Run: `pip install -r requirements.txt`
4. Run: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### 4. Verify Deployment

Once deployed, test these endpoints:

```bash
# Health check
curl https://your-api.onrender.com/health

# Welcome
curl https://your-api.onrender.com/

# Signup
curl -X POST https://your-api.onrender.com/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"testpass123","child_age":7}'

# Login
curl -X POST https://your-api.onrender.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"testpass123"}'

# List content
curl https://your-api.onrender.com/api/v1/content

# Get categories
curl https://your-api.onrender.com/api/v1/content/categories
```

## Local Development

### 1. Setup Environment

```bash
cd dreamweaver-backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# No .env file needed! Config loads from environment
# Or create one for local variables
```

### 2. Run Development Server

```bash
# Option 1: Using uvicorn directly
uvicorn app.main:app --reload

# Option 2: Using the run.sh script (if available)
bash run.sh

# Server will start at http://localhost:8000
```

### 3. Test Endpoints

```bash
# Access Swagger UI
http://localhost:8000/docs

# Access ReDoc
http://localhost:8000/redoc

# Get health status
curl http://localhost:8000/health
```

## Environment Variables

| Variable | Default | Required | Purpose |
|----------|---------|----------|---------|
| `GROQ_API_KEY` | (none) | Optional* | Groq API key for AI generation |
| `ENVIRONMENT` | development | No | Set to "production" for Render |
| `DEBUG` | true | No | Debug logging (false in production) |
| `CORS_ORIGINS` | * | No | Comma-separated CORS origins |
| `APP_NAME` | DreamWeaver | No | Application name |
| `API_VERSION` | v1 | No | API version |
| `MAX_CONTENT_PER_DAY_FREE` | 1 | No | Free tier daily limit |
| `MAX_CONTENT_PER_DAY_PREMIUM` | 5 | No | Premium tier daily limit |
| `SECRET_KEY` | dreamweaver-dev-secret | No | JWT secret (dev only) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | No | Token expiration time |

*If Groq API key not set, content generation falls back to mock data

## API Response Format

All endpoints return JSON in this format:

```json
{
  "success": true,
  "data": {
    "field1": "value1",
    "field2": "value2"
  },
  "message": "Operation completed successfully"
}
```

Error response:
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Error description",
    "details": {}
  }
}
```

## Authentication

### Signup

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "johndoe",
    "password": "securepass123",
    "child_age": 8
  }'
```

Response:
```json
{
  "success": true,
  "data": {
    "uid": "abc123...",
    "username": "johndoe",
    "child_age": 8,
    "token": "def456..."
  },
  "message": "Signup successful"
}
```

### Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "johndoe",
    "password": "securepass123"
  }'
```

### Using Auth Token

Include token in Authorization header:

```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

## Content Generation

### Generate Content

```bash
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content_type": "story",
    "child_age": 8,
    "theme": "adventure",
    "length": "MEDIUM"
  }'
```

Response:
```json
{
  "success": true,
  "data": {
    "content_id": "xyz789...",
    "title": "The Adventure Tale",
    "status": "completed",
    "created_at": "2024-02-13T10:30:00"
  },
  "message": "Content generated successfully"
}
```

## Troubleshooting

### 502 Bad Gateway on Render

1. Check deployment logs: Dashboard → Service → Logs
2. Verify `render.yaml` is in root directory
3. Check that `requirements.txt` has no syntax errors
4. Verify Python version is 3.11.x

### ModuleNotFoundError

1. Ensure all files are in correct directories
2. Check that `__init__.py` files exist in all package directories
3. Run `pip install -r requirements.txt` to install dependencies

### CORS Errors

1. Update `CORS_ORIGINS` environment variable
2. Include protocol: `https://example.com` not just `example.com`
3. Use `*` for testing (set properly in production)

### Authentication Errors

1. Verify token format: `Authorization: Bearer <token>`
2. Check that token matches header format in `get_current_user()`
3. Ensure no extra spaces in header value

### Quota Exceeded

Free tier limited to 1 generation per day (configurable via `MAX_CONTENT_PER_DAY_FREE`)

Upgrade tier with:
```bash
curl -X POST http://localhost:8000/api/v1/subscriptions/upgrade \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tier_id": "premium"}'
```

## Next Steps

### After Deployment

1. Monitor logs for errors
2. Test all critical paths
3. Set up proper Firebase credentials when ready to migrate to prod DB
4. Implement actual payment processing for subscriptions
5. Add database persistence (Firestore)
6. Add TTS/Audio generation
7. Add image generation for thumbnails

### Future Enhancements

- Implement Firebase authentication
- Add cloud storage for audio/images
- Implement real-time notifications
- Add advanced analytics
- Implement subscription payment processing
- Add admin dashboard

## Support

For issues or questions:
1. Check logs in Render dashboard
2. Review error messages in response
3. Verify all environment variables are set
4. Test locally first before deploying

---

**Version**: 1.0
**Last Updated**: February 13, 2024
**Status**: Production Ready
