# DreamWeaver Backend - Models & Schemas Documentation

## Summary

Successfully created all backend model and schema files for DreamWeaver. Total of 15 files with 1,520 lines of code.

## Directory Structure

```
app/
├── models/
│   ├── __init__.py                 (22 lines)
│   ├── user.py                     (74 lines)
│   ├── content.py                  (90 lines)
│   ├── interaction.py              (42 lines)
│   └── subscription.py             (71 lines)
├── schemas/
│   ├── __init__.py                 (50 lines)
│   ├── user_schema.py              (92 lines)
│   ├── content_schema.py           (154 lines)
│   ├── responses.py                (55 lines)
│   └── subscription_schema.py      (48 lines)
└── crud/
    ├── __init__.py                 (4 lines)
    ├── base.py                     (190 lines)
    ├── user.py                     (159 lines)
    ├── content.py                  (263 lines)
    └── interaction.py              (206 lines)
```

## Files Created

### Models (Firestore Document Representations)

#### 1. `/app/models/__init__.py`
- Exports all models and enums for easy importing

#### 2. `/app/models/user.py`
**UserPreferences class:**
- `selected_voice_id`: Voice ID for playback
- `background_music_type`: Type of background music
- `enable_background_music`: Music toggle
- `music_volume`: 0-100 volume level
- `preferred_content_types`: List of content types
- `preferred_categories`: List of category preferences
- Methods: `to_dict()`, `from_dict()`

**UserModel class:**
- `uid`: Firebase Auth unique ID
- `username`: 3-20 character alphanumeric + underscore
- `child_age`: 0-14 years
- `subscription_tier`: FREE, PREMIUM, or UNLIMITED
- `created_at`: Account creation timestamp
- `subscription_expires_at`: Subscription expiration
- `preferences`: UserPreferences object
- `daily_usage_count`: Content views today
- `last_usage_date`: Last activity timestamp
- Methods: `to_dict()`, `from_dict()`, validators for username and tier

#### 3. `/app/models/content.py`
**Enums:**
- `ContentType`: STORY, POEM, SONG
- `StoryTheme`: FANTASY, ADVENTURE, FAIRY_TALE, ANIMALS, SPACE, OCEAN, MYSTERY, FRIENDSHIP, FAMILY, NATURE, EDUCATIONAL, BEDTIME
- `StoryLength`: SHORT (100-300 words), MEDIUM (300-800), LONG (800+)

**ContentModel class:**
- `id`: Unique content ID
- `type`: Content type enum
- `title`: 1-200 character title
- `description`: Up to 500 character description
- `text`: Main content text
- `target_age`: 0-14 years
- `duration_seconds`: Audio/playback duration
- `author_id`: Creator ID
- `created_at`: Timestamp
- `audio_url`: Generated audio URL
- `album_art_url`: Thumbnail/cover art
- `view_count`, `like_count`, `save_count`: Engagement metrics
- `categories`: List of content categories
- `theme`: Story theme (if applicable)
- `is_generated`: AI-generated flag
- `voice_id`: Voice used for audio
- `music_type`: Background music type
- `generation_quality`: Quality level
- Methods: `to_dict()`, `from_dict()`, type/theme validators

#### 4. `/app/models/interaction.py`
**InteractionType enum:**
- VIEW: User viewed content
- LIKE: User liked content
- SAVE: User saved/bookmarked content

**InteractionModel class:**
- `id`: Unique interaction ID
- `user_id`: User who interacted
- `content_id`: Content being interacted with
- `type`: InteractionType enum
- `created_at`: Interaction timestamp
- `removed_at`: Removal timestamp (for undoing)
- Methods: `to_dict()`, `from_dict()`

#### 5. `/app/models/subscription.py`
**SubscriptionTier enum:**
- FREE, PREMIUM, UNLIMITED

**SubscriptionPlan class:**
- `tier`: Subscription tier
- `daily_limit`: -1 for unlimited
- `max_favorites`: -1 for unlimited
- `max_saves`: -1 for unlimited
- `features`: List of enabled features
- `price_usd`: Monthly price
- `description`: Plan description

**DEFAULT_PLANS dictionary:**
- FREE: 5 daily limit, 10 favorites/saves
- PREMIUM: 30 daily limit, 100 favorites/saves, $9.99/month
- UNLIMITED: -1 (unlimited), all features, $19.99/month

### Schemas (Pydantic Request/Response Validation)

#### 6. `/app/schemas/__init__.py`
- Exports all request/response schemas

#### 7. `/app/schemas/user_schema.py`
**SignUpRequest:**
- `username`: 3-20 alphanumeric + underscore
- `password`: 6+ characters
- `child_age`: 0-14 years

**LoginRequest:**
- `username`: Username
- `password`: Password

**UserResponse:**
- `uid`: User ID
- `username`: Username
- `child_age`: Child's age
- `subscription_tier`: Current tier
- `created_at`: Account creation date
- `daily_usage`: Views today
- `daily_limit`: Tier's daily limit

**UpdateProfileRequest:**
- `child_age`: Optional age update

**UpdatePreferencesRequest:**
- All preference fields optional
- Allows partial updates

**QuotaResponse:**
- `used`: Views used today
- `limit`: Daily limit
- `remaining`: Views left
- `tier`: Subscription tier
- `resets_at`: When quota resets

#### 8. `/app/schemas/content_schema.py`
**ContentResponse:**
- All content fields plus:
- `is_liked`: Whether current user liked
- `is_saved`: Whether current user saved

**ContentListResponse:**
- `items`: Paginated content array
- `total_count`: Total matching items
- `page`: Current page
- `page_size`: Items per page
- `has_more`: More pages exist flag

**GenerateContentRequest:**
- `content_type`: STORY, POEM, or SONG
- `child_age`: Target age (0-14)
- `theme`: Optional story theme
- `length`: SHORT, MEDIUM, or LONG
- `include_music`: Toggle music
- `include_songs`, `include_poems`: Content toggles
- `voice_id`: Voice for generation
- `music_type`: Background music
- `category`: Optional category
- `custom_prompt`: Custom generation prompt (up to 500 chars)

**GenerateContentResponse:**
- `content`: Generated ContentResponse
- `status`: "generating" or "ready"
- `estimated_completion_seconds`: Optional ETA

**SearchRequest:**
- `query`: 1-200 character search
- `content_type`: Optional filter
- `theme`: Optional theme filter
- `page`: Page number (1+)
- `page_size`: Items per page (1-100)

#### 9. `/app/schemas/responses.py`
**ApiResponse[T]:**
- Generic success/error response wrapper
- `success`: Boolean success flag
- `data`: Response data (type T)
- `message`: Response message
- `errors`: List of error dictionaries
- Methods: `success_response()`, `error_response()`

**PaginatedResponse[T]:**
- Generic paginated response
- `items`: Page items
- `total`: Total count
- `page`: Current page
- `page_size`: Items per page
- `has_more`: More pages exist
- Property: `total_pages`

**ErrorResponse:**
- `error_code`: Machine-readable error code
- `message`: Human-readable message
- `details`: Optional additional info

#### 10. `/app/schemas/subscription_schema.py`
**SubscriptionTierInfo:**
- `tier`: Tier identifier
- `name`: Display name
- `daily_limit`: Daily limit (-1 = unlimited)
- `max_favorites`: Max favorites (-1 = unlimited)
- `max_saves`: Max saves (-1 = unlimited)
- `features`: Feature list
- `price`: Monthly USD price

**SubscriptionTiersResponse:**
- `tiers`: List of all available tiers
- `current_tier`: User's current tier
- `current_features`: User's current features

**UpgradeRequest:**
- `tier`: Target tier to upgrade to

### CRUD Operations (Database Layer)

#### 11. `/app/crud/__init__.py`
- Empty module file for CRUD package

#### 12. `/app/crud/base.py`
**BaseCRUD Generic Class:**
Abstract base class with Firestore operations:

**Properties:**
- `collection_name`: Abstract property for subclass collection
- `db`: Firestore client

**Methods:**
- `get_collection()`: Get Firestore collection reference
- `create(data)`: Create new document, returns ID
- `get_by_id(id)`: Get document by ID
- `update(id, data)`: Update document fields
- `delete(id)`: Delete document
- `list(filters, page, page_size, order_by, direction)`: Paginated list with filtering and sorting
- `count(filters)`: Count matching documents
- `exists(id)`: Check document existence

**Features:**
- Full pagination support
- Flexible filtering with (field, operator, value) tuples
- Sorting/ordering capability
- Timestamp management

#### 13. `/app/crud/user.py`
**UserCRUD(BaseCRUD) Class:**

**Methods:**
- `get_by_username(username)`: Get user by username
- `create_user(user_data)`: Create new user from UserModel
- `update_preferences(uid, preferences)`: Update user preferences
- `increment_daily_usage(uid)`: Increment daily view count
  - Auto-resets on new day
- `reset_daily_usage(uid)`: Reset daily counter
- `get_daily_usage(uid)`: Get usage stats with reset time
- `update_subscription(uid, tier, expires_at)`: Update subscription tier

#### 14. `/app/crud/content.py`
**ContentCRUD(BaseCRUD) Class:**

**Methods:**
- `get_content_list(filters, page, page_size, sort_by)`: Paginated content with filtering
- `get_by_category(category, page, page_size)`: Content by category
- `get_trending(limit, days)`: Trending content (most viewed in X days)
- `search(query, filters, page, page_size)`: Full-text search in title/description
- `increment_view(content_id)`: Increment and return view count
- `increment_like(content_id)`: Increment and return like count
- `decrement_like(content_id)`: Decrement like count (min 0)
- `increment_save(content_id)`: Increment and return save count
- `decrement_save(content_id)`: Decrement save count (min 0)

#### 15. `/app/crud/interaction.py`
**InteractionCRUD(BaseCRUD) Class:**

**Methods:**
- `add_interaction(user_id, content_id, type)`: Create interaction record
- `remove_interaction(user_id, content_id, type)`: Mark interaction as removed
- `get_user_likes(user_id)`: List all content liked by user
- `get_user_saves(user_id)`: List all content saved by user
- `is_liked(user_id, content_id)`: Check if user liked content
- `is_saved(user_id, content_id)`: Check if user saved content
- `get_user_interactions_with_content(user_id, content_id)`: Get all interaction types for content

**Features:**
- Unique interaction IDs: `{user_id}_{content_id}_{type}`
- Soft deletes via `removed_at` field
- Fast lookup of active interactions

## Key Design Patterns

### Type Safety
- All files use comprehensive Python type hints
- Pydantic v2 models for validation
- Enum classes for fixed values

### Data Integrity
- Field validators on models and schemas
- Constraints on values (min/max, string length)
- Automatic timestamp management

### Firestore Integration
- to_dict() and from_dict() methods for serialization
- BaseCRUD provides async/await support
- Collection-based document organization

### API Design
- Generic response wrappers for consistency
- Pagination support across all list operations
- Comprehensive error handling structure
- Optional/default values for flexibility

## Usage Examples

### Creating a User
```python
from app.models.user import UserModel, UserPreferences
from app.crud.user import UserCRUD

user = UserModel(
    uid="firebase-uid",
    username="child123",
    child_age=8,
    subscription_tier="FREE"
)
await user_crud.create_user(user)
```

### Searching Content
```python
from app.crud.content import ContentCRUD

results = await content_crud.search(
    query="adventure",
    page=1,
    page_size=20
)
```

### Managing Interactions
```python
from app.crud.interaction import InteractionCRUD
from app.models.interaction import InteractionType

await interaction_crud.add_interaction(
    user_id="user-123",
    content_id="story-456",
    interaction_type=InteractionType.LIKE
)
```

## Next Steps

1. Create route handlers in `/app/api/` that use these schemas
2. Implement service layer using CRUD operations
3. Add middleware for authentication and rate limiting
4. Create integration tests for all CRUD operations
5. Add database migrations/indices for Firestore
