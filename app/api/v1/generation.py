"""AI content generation endpoints."""

from datetime import datetime
from typing import Optional
import uuid
import json

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.dependencies import get_current_user, get_db_client, get_groq_client
from app.utils.logger import get_logger
import random

logger = get_logger(__name__)
router = APIRouter()

# Theme → music profile mapping for Web Audio ambient music
THEME_MUSIC_MAP = {
    "dreamy":     ["dreamy-clouds", "starlight-lullaby"],
    "adventure":  ["enchanted-garden", "autumn-forest"],
    "fantasy":    ["enchanted-garden", "moonlit-meadow"],
    "fairy_tale": ["moonlit-meadow", "starlight-lullaby"],
    "space":      ["cosmic-voyage"],
    "animals":    ["forest-night", "autumn-forest"],
    "nature":     ["forest-night", "moonlit-meadow"],
    "ocean":      ["ocean-drift"],
    "bedtime":    ["starlight-lullaby", "dreamy-clouds"],
    "lullaby":    ["starlight-lullaby", "ocean-drift"],
}
_ALL_PROFILES = [
    "dreamy-clouds", "forest-night", "moonlit-meadow", "cosmic-voyage",
    "enchanted-garden", "starlight-lullaby", "autumn-forest", "ocean-drift",
]


def _pick_music_profile(theme: str) -> str:
    """Pick a music profile matching the theme."""
    candidates = THEME_MUSIC_MAP.get(theme, _ALL_PROFILES)
    return random.choice(candidates)


# Request Models
class GenerateContentRequest(BaseModel):
    """Request model for content generation."""
    content_type: str = "story"
    child_age: int
    theme: Optional[str] = "adventure"
    length: str = "MEDIUM"
    include_music: bool = False
    include_songs: bool = False
    include_poems: bool = False
    voice_id: Optional[str] = None
    music_type: Optional[str] = None
    category: Optional[str] = None
    custom_prompt: Optional[str] = None


# Response Models
class GenerationResponse(BaseModel):
    """Response model for content generation."""
    success: bool
    data: dict
    message: str


def _build_age_appropriate_prompt(child_age: int, content_type: str, theme: str, length: str, custom_prompt: Optional[str]) -> str:
    """Build an age-appropriate prompt for Groq API."""
    age_guidance = {
        2: "Very simple, 2-3 sentence story with simple words",
        3: "Simple 3-5 sentence story with basic vocabulary",
        4: "4-6 sentence story with easy vocabulary",
        5: "5-7 sentence story appropriate for preschool",
        6: "6-8 sentence story for early elementary",
        7: "7-10 sentence story for elementary school",
        8: "8-12 sentence story with more detail",
        9: "10-15 sentence story with adventure elements",
        10: "12-18 sentence story with more complex plot",
        11: "15-20 sentence story with character development",
        12: "18-25 sentence story with deeper themes",
        13: "20-30 sentence story appropriate for older kids",
        14: "25-35 sentence story for young teenagers",
        15: "30-40 sentence story with mature themes",
        16: "35-50 sentence story for teenagers",
        17: "40-60 sentence story with complex narrative",
        18: "50-80 sentence story with sophisticated themes",
    }
    
    age_desc = age_guidance.get(child_age, age_guidance[10])
    
    length_guidance = {
        "SHORT": "Keep it concise and quick.",
        "MEDIUM": "Make it a moderate length with good pacing.",
        "LONG": "Make it longer with more detail and development.",
    }
    
    length_desc = length_guidance.get(length, length_guidance["MEDIUM"])
    
    base_prompt = f"""
You are a bedtime story generator for children aged {child_age}.

Create a {content_type} with theme: {theme}
{length_desc}
{age_desc}

Make it calming and soothing, perfect for bedtime.
Include morals or lessons if appropriate.

{f"Custom instruction: {custom_prompt}" if custom_prompt else ""}

Return your response as a JSON object with these fields:
{{
  "title": "Story title",
  "text": "The story text",
  "description": "Brief description",
  "morals": ["Moral 1", "Moral 2"]
}}

Only return the JSON, no other text.
"""
    return base_prompt.strip()


def _generate_mock_story(theme: str, child_age: int, length: str) -> dict:
    """Generate a mock story for when Groq client is unavailable."""
    stories = {
        "adventure": "Once upon a time, a brave little explorer set out on an exciting quest through enchanted forests and magical mountains, discovering wonderful friends along the way.",
        "fantasy": "In a magical kingdom far away, a wise wizard cast a protective spell over the land, keeping all the children safe and happy in their dreams.",
        "animals": "A curious little rabbit hopped through the peaceful forest, making friends with a friendly owl, a wise old turtle, and a cheerful bluebird.",
        "bedtime": "As the moon rose high in the starry sky, tired eyes began to close, and dreams of wonderful adventures filled the night with magic and wonder.",
        "default": "Once upon a time, in a land far away, an amazing adventure began when a brave child discovered something magical and special.",
    }
    
    text = stories.get(theme, stories["default"])
    
    # Make longer based on length parameter
    if length == "LONG":
        text = text + " " + text + " " + text
    elif length == "MEDIUM":
        text = text + " " + text
    
    duration = {
        "SHORT": 60,
        "MEDIUM": 180,
        "LONG": 300,
    }.get(length, 180)
    
    return {
        "text": text,
        "title": f"The {theme.capitalize()} Tale",
        "description": f"A sweet {length.lower()} {theme} story for bedtime",
        "morals": ["Be brave and kind", "Adventures are magical"],
        "duration": duration,
        "audio_url": None,
    }


@router.post("", response_model=GenerationResponse, status_code=status.HTTP_201_CREATED)
async def generate_content(
    request: GenerateContentRequest,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
    groq_client=Depends(get_groq_client),
) -> GenerationResponse:
    """
    Generate new AI content for the user.
    
    Validates daily quota and initiates generation.
    Uses Groq API if available, otherwise returns mock data.
    
    Args:
        request: GenerateContentRequest with generation parameters
        current_user: Current authenticated user
        db_client: Database client
        groq_client: Groq API client (may be None)
        
    Returns:
        GenerationResponse with success status and content data
        
    Raises:
        HTTPException: If quota exceeded or validation fails
    """
    try:
        user_id = current_user["uid"]
        
        # Get user to check quota
        user_doc = db_client.collection("users").document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_data = user_doc.to_dict()
        daily_usage = user_data.get("daily_usage", 0)
        daily_limit = user_data.get("daily_limit", 3)
        
        # Check quota
        if daily_usage >= daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily quota exceeded. Limit: {daily_limit}, Used: {daily_usage}"
            )
        
        # Create content ID
        content_id = str(uuid.uuid4())
        
        # Generate content
        if groq_client:
            try:
                # Build prompt
                prompt = _build_age_appropriate_prompt(
                    request.child_age,
                    request.content_type,
                    request.theme or "adventure",
                    request.length,
                    request.custom_prompt
                )
                
                # Call Groq API
                response = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": "You are a bedtime story generator."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=1000,
                )
                
                # Parse response
                response_text = response.choices[0].message.content.strip()
                
                # Try to extract JSON
                content_data = json.loads(response_text)
                
                gen_result = {
                    "text": content_data.get("text", ""),
                    "title": content_data.get("title", f"The {request.theme} Story"),
                    "description": content_data.get("description", ""),
                    "morals": content_data.get("morals", []),
                    "duration": 180,
                    "audio_url": None,
                }
                logger.info(f"Content generated via Groq for user {user_id}")
                
            except Exception as e:
                logger.warning(f"Groq API error, falling back to mock: {str(e)}")
                gen_result = _generate_mock_story(
                    request.theme or "adventure",
                    request.child_age,
                    request.length
                )
        else:
            # Use mock data
            gen_result = _generate_mock_story(
                request.theme or "adventure",
                request.child_age,
                request.length
            )
            logger.info(f"Using mock content for user {user_id}")
        
        # Create content document
        theme = request.theme or "adventure"
        content_document = {
            "id": content_id,
            "user_id": user_id,
            "type": request.content_type,
            "theme": theme,
            "length": request.length,
            "child_age": request.child_age,
            "include_music": request.include_music,
            "status": "completed",
            "text": gen_result["text"],
            "audio_url": gen_result.get("audio_url"),
            "thumbnail_url": None,
            "duration": gen_result.get("duration", 180),
            "title": gen_result["title"],
            "description": gen_result.get("description", ""),
            "morals": gen_result.get("morals", []),
            "musicProfile": _pick_music_profile(theme),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "view_count": 0,
            "like_count": 0,
            "save_count": 0,
            "category": request.category or theme or "general",
            "is_generated": True,
        }
        
        # Save content to database
        db_client.collection("content").document(content_id).set(content_document)
        
        # Increment user's daily usage
        new_usage = daily_usage + 1
        db_client.collection("users").document(user_id).update({
            "daily_usage": new_usage,
            "updated_at": datetime.utcnow(),
        })
        
        return GenerationResponse(
            success=True,
            data={
                "content_id": content_id,
                "title": gen_result["title"],
                "description": gen_result.get("description", ""),
                "status": "completed",
                "created_at": datetime.utcnow().isoformat(),
            },
            message="Content generated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Content generation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Generation failed: {str(e)}"
        )


@router.get("/{content_id}", response_model=GenerationResponse)
async def get_generation_status(
    content_id: str,
    current_user: dict = Depends(get_current_user),
    db_client=Depends(get_db_client),
) -> GenerationResponse:
    """
    Get generation status and details of content.
    
    Args:
        content_id: ID of content to fetch
        current_user: Current authenticated user
        db_client: Database client
        
    Returns:
        GenerationResponse with content data
        
    Raises:
        HTTPException: If content not found or access denied
    """
    try:
        content_doc = db_client.collection("content").document(content_id).get()
        
        if not content_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Content not found"
            )
        
        content_data = content_doc.to_dict()
        
        # Verify ownership
        if content_data.get("user_id") != current_user["uid"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        return GenerationResponse(
            success=True,
            data={
                "content_id": content_id,
                "title": content_data.get("title"),
                "description": content_data.get("description"),
                "text": content_data.get("text"),
                "status": content_data.get("status", "processing"),
                "duration": content_data.get("duration"),
                "audio_url": content_data.get("audio_url"),
                "created_at": content_data.get("created_at", datetime.utcnow()).isoformat() if isinstance(content_data.get("created_at"), datetime) else content_data.get("created_at"),
            },
            message="Content retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch generation status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch content: {str(e)}"
        )
