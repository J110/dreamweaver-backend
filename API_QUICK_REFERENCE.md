# DreamWeaver API Quick Reference

## Base URL
- Local: `http://localhost:8000`
- Production (Render): `https://your-api.onrender.com`

## Standard Response Format

### Success Response
```json
{
  "success": true,
  "data": {
    "field1": "value1",
    "field2": "value2"
  },
  "message": "Operation description"
}
```

### Error Response
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

All protected endpoints require:
```
Authorization: Bearer <token>
```

Get token from login/signup response.

---

## Endpoints

### Health & Info

#### GET /health
Health check endpoint
```bash
curl http://localhost:8000/health
```

#### GET /
Welcome endpoint
```bash
curl http://localhost:8000/
```

---

### Authentication

#### POST /api/v1/auth/signup
Create new user account

**Request:**
```json
{
  "username": "string (3-50 chars)",
  "password": "string (6+ chars)",
  "child_age": "integer (2-18)"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "uid": "unique_user_id",
    "username": "johndoe",
    "child_age": 8,
    "token": "auth_token_here"
  },
  "message": "Signup successful"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "johndoe",
    "password": "securepass123",
    "child_age": 8
  }'
```

#### POST /api/v1/auth/login
Authenticate user

**Request:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "uid": "user_id",
    "username": "johndoe",
    "child_age": 8,
    "token": "auth_token_here"
  },
  "message": "Login successful"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "johndoe",
    "password": "securepass123"
  }'
```

---

### Content Generation

#### POST /api/v1/generate
Generate new content (requires auth)

**Request:**
```json
{
  "content_type": "story",
  "child_age": 8,
  "theme": "adventure",
  "length": "MEDIUM",
  "include_music": false,
  "include_songs": false,
  "include_poems": false,
  "voice_id": null,
  "music_type": null,
  "category": null,
  "custom_prompt": null
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "content_id": "xyz123",
    "title": "The Adventure Tale",
    "description": "A sweet bedtime adventure story",
    "status": "completed",
    "created_at": "2024-02-13T10:30:00"
  },
  "message": "Content generated successfully"
}
```

**Example:**
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

#### GET /api/v1/generate/{content_id}
Get generated content details (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "content_id": "xyz123",
    "title": "The Adventure Tale",
    "description": "...",
    "text": "Once upon a time...",
    "status": "completed",
    "duration": 180,
    "audio_url": null,
    "created_at": "2024-02-13T10:30:00"
  },
  "message": "Content retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/generate/xyz123 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### Content Management

#### GET /api/v1/content
List all content

**Query Parameters:**
- `content_type` (optional): string
- `category` (optional): string
- `page` (default: 1): integer
- `page_size` (default: 20): integer (max 100)
- `sort_by` (default: created_at): "created_at" | "view_count" | "like_count"

**Response:**
```json
{
  "success": true,
  "data": {
    "items": [...],
    "total": 42,
    "page": 1,
    "page_size": 20,
    "pages": 3
  },
  "message": "Content retrieved successfully"
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/content?category=adventure&page=1&page_size=20"
```

#### GET /api/v1/content/categories
List available categories

**Response:**
```json
{
  "success": true,
  "data": {
    "categories": [
      {
        "id": "adventure",
        "name": "Adventure",
        "description": "Exciting adventures"
      },
      ...
    ]
  },
  "message": "Categories retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/content/categories
```

#### GET /api/v1/content/{content_id}
Get single content (increments view count)

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "xyz123",
    "title": "...",
    "description": "...",
    "text": "...",
    "view_count": 42,
    "like_count": 5,
    "save_count": 3,
    ...
  },
  "message": "Content retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/content/xyz123
```

---

### Trending Content

#### GET /api/v1/trending
Get trending content (score: likes*5 + views)

**Query Parameters:**
- `limit` (default: 20): integer (max 100)

**Response:**
```json
{
  "success": true,
  "data": {
    "items": [...],
    "total": 20,
    "limit": 20
  },
  "message": "Trending content retrieved successfully"
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/trending?limit=10"
```

#### GET /api/v1/trending/weekly
Weekly trending content

**Example:**
```bash
curl http://localhost:8000/api/v1/trending/weekly
```

#### GET /api/v1/trending/by-category/{category}
Trending content in specific category

**Example:**
```bash
curl http://localhost:8000/api/v1/trending/by-category/adventure
```

---

### User Interactions

#### POST /api/v1/interactions/content/{content_id}/like
Like content (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "content_id": "xyz123",
    "like_count": 6
  },
  "message": "Content liked successfully"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/interactions/content/xyz123/like \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### DELETE /api/v1/interactions/content/{content_id}/like
Unlike content (requires auth)

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/v1/interactions/content/xyz123/like \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### POST /api/v1/interactions/content/{content_id}/save
Save content (requires auth)

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/interactions/content/xyz123/save \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### DELETE /api/v1/interactions/content/{content_id}/save
Unsave content (requires auth)

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/v1/interactions/content/xyz123/save \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/v1/interactions/me/likes
Get user's liked content (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "liked_content_ids": ["id1", "id2", "id3"],
    "total": 3
  },
  "message": "User likes retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/interactions/me/likes \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/v1/interactions/me/saves
Get user's saved content (requires auth)

**Example:**
```bash
curl http://localhost:8000/api/v1/interactions/me/saves \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### User Management

#### GET /api/v1/users/me
Get current user profile (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "uid": "user_id",
    "username": "johndoe",
    "child_age": 8,
    "subscription_tier": "free",
    "created_at": "2024-02-13T...",
    "preferences": {
      "language": "en",
      "notifications_enabled": true
    }
  },
  "message": "User profile retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### PUT /api/v1/users/me
Update user profile (requires auth)

**Request:**
```json
{
  "child_age": 9
}
```

**Example:**
```bash
curl -X PUT http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"child_age": 9}'
```

#### PUT /api/v1/users/preferences
Update user preferences (requires auth)

**Request:**
```json
{
  "language": "en",
  "notifications_enabled": true,
  "theme": "light"
}
```

**Example:**
```bash
curl -X PUT http://localhost:8000/api/v1/users/preferences \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "notifications_enabled": false
  }'
```

#### GET /api/v1/users/quota
Get daily quota info (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "used": 1,
    "limit": 3,
    "remaining": 2,
    "tier": "free"
  },
  "message": "Quota retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/users/quota \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### Subscriptions

#### GET /api/v1/subscriptions/tiers
List available subscription tiers

**Response:**
```json
{
  "success": true,
  "data": {
    "tiers": [
      {
        "id": "free",
        "name": "Free",
        "description": "Perfect for getting started",
        "price": 0,
        "daily_limit": 3,
        "features": [...]
      },
      {
        "id": "premium",
        "name": "Premium",
        "price": 9.99,
        "daily_limit": 50,
        ...
      },
      ...
    ],
    "total": 3
  },
  "message": "Subscription tiers retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/subscriptions/tiers
```

#### GET /api/v1/subscriptions/current
Get user's current tier (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "current_tier": {
      "id": "free",
      "name": "Free",
      ...
    },
    "since": "2024-02-13T...",
    "next_billing_date": null
  },
  "message": "Current subscription retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/subscriptions/current \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### POST /api/v1/subscriptions/upgrade
Upgrade subscription (requires auth)

**Request:**
```json
{
  "tier_id": "premium"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/subscriptions/upgrade \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tier_id": "premium"}'
```

---

### Search

#### GET /api/v1/search
Search content by query

**Query Parameters:**
- `q` (required): search string
- `limit` (default: 20): integer (max 100)

**Response:**
```json
{
  "success": true,
  "data": {
    "query": "adventure",
    "results": [...],
    "total": 5,
    "limit": 20
  },
  "message": "Search completed successfully"
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/search?q=adventure&limit=10"
```

---

### Audio & Voices

#### GET /api/v1/audio/voices
List available voices

**Response:**
```json
{
  "success": true,
  "data": {
    "voices": [
      {
        "id": "alloy",
        "name": "Alloy",
        "description": "A gentle, calm voice perfect for bedtime",
        "gender": "neutral",
        "language": "en-US"
      },
      ...
    ],
    "total": 6
  },
  "message": "Available voices retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/audio/voices
```

#### GET /api/v1/audio/{content_id}
Get content audio (requires auth)

**Response:**
```json
{
  "success": true,
  "data": {
    "content_id": "xyz123",
    "audio_url": "https://...",
    "duration": 180,
    "voice_id": "alloy"
  },
  "message": "Audio information retrieved successfully"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/audio/xyz123 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### POST /api/v1/audio/tts/preview
Generate TTS preview (requires auth)

**Request:**
```json
{
  "text": "Sample text to preview",
  "voice_id": "alloy"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "preview_url": "https://...",
    "voice_id": "alloy",
    "text_preview": "Sample text to preview",
    "duration": 5
  },
  "message": "TTS preview generated successfully"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/audio/tts/preview \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Once upon a time...",
    "voice_id": "alloy"
  }'
```

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 201 | Created - Resource created |
| 204 | No Content - Successful deletion |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing/invalid token |
| 403 | Forbidden - Access denied |
| 404 | Not Found - Resource not found |
| 429 | Too Many Requests - Rate limited/quota exceeded |
| 500 | Server Error - Internal error |

---

## Content Types

Allowed `content_type` values:
- `story` (default)
- `poem`
- `song`
- `script`

## Themes

Popular themes:
- `adventure`
- `fantasy`
- `animals`
- `bedtime`
- `education`
- `humor`

## Lengths

- `SHORT` - 60 seconds
- `MEDIUM` - 180 seconds (default)
- `LONG` - 300 seconds

## Subscription Tiers

| Tier | Price | Daily Limit | Features |
|------|-------|-------------|----------|
| free | $0 | 3 | Basic themes, standard voice |
| premium | $9.99/mo | 50 | All themes, all voices, ad-free |
| family | $14.99/mo | 100 | All premium + 5 profiles, controls |

---

## Testing with Swagger UI

Access interactive API documentation at:
- Local: `http://localhost:8000/docs`
- Production: `https://your-api.onrender.com/docs`

---

## Common Patterns

### Getting Started
1. Sign up: `POST /api/v1/auth/signup`
2. Use returned token for all requests
3. Check quota: `GET /api/v1/users/quota`
4. Generate content: `POST /api/v1/generate`
5. Interact: Like/save/search

### Workflow for Content Discovery
1. List content: `GET /api/v1/content`
2. Get trending: `GET /api/v1/trending`
3. Search: `GET /api/v1/search?q=...`
4. View single content: `GET /api/v1/content/{id}`
5. Like/save: `POST /api/v1/interactions/...`

### Quota Management
1. Check quota: `GET /api/v1/users/quota`
2. If remaining == 0, suggest upgrade
3. Upgrade: `POST /api/v1/subscriptions/upgrade`

---

**Last Updated:** February 13, 2024
**API Version:** v1
**Status:** Production Ready
