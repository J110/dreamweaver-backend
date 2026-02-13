"""Content generation pipeline for stories, poems, and songs."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

from groq_service import GroqService
from cache_service import ContentCache
from prompts import build_complete_prompt

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """Supported content types."""
    STORY = "story"
    POEM = "poem"
    SONG = "song"


@dataclass
class GeneratedContent:
    """Dataclass for generated content with metadata."""
    
    title: str
    text: str
    content_type: ContentType
    theme: str
    categories: List[str] = field(default_factory=list)
    morals: List[str] = field(default_factory=list)
    duration_estimate: float = 0.0  # estimated duration in seconds
    emotion_markers: List[Tuple[int, int, str]] = field(default_factory=list)
    # emotion_markers format: [(start_idx, end_idx, emotion), ...]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "text": self.text,
            "content_type": self.content_type.value,
            "theme": self.theme,
            "categories": self.categories,
            "morals": self.morals,
            "duration_estimate": self.duration_estimate,
        }


class ContentGenerator:
    """Pipeline for generating bedtime content."""
    
    # Average reading speed in words per minute
    READING_SPEED_WPM = 150
    
    # Emotion markers for TTS (all recognised markers)
    EMOTION_MARKERS = {
        "[SLEEPY]": "sleepy",
        "[GENTLE]": "gentle",
        "[CALM]": "calm",
        "[EXCITED]": "excited",
        "[CURIOUS]": "curious",
        "[ADVENTUROUS]": "adventurous",
        "[MYSTERIOUS]": "mysterious",
        "[JOYFUL]": "joyful",
        "[DRAMATIC]": "dramatic",
        "[WHISPERING]": "whispering",
        "[DRAMATIC_PAUSE]": "dramatic_pause",
        "[RHYTHMIC]": "rhythmic",
        "[SINGING]": "singing",
        "[HUMMING]": "humming",
        "[PAUSE]": "pause",
        "[laugh]": "laugh",
        "[chuckle]": "chuckle",
    }
    
    def __init__(
        self,
        groq_service: GroqService,
        cache_service: Optional[ContentCache] = None,
        enable_caching: bool = True
    ):
        """
        Initialize content generator.
        
        Args:
            groq_service: GroqService instance for text generation
            cache_service: Optional ContentCache for caching results
            enable_caching: Whether to use caching
        """
        self.groq = groq_service
        self.cache = cache_service or ContentCache()
        self.enable_caching = enable_caching
        
        logger.info("ContentGenerator initialized with caching=%s", enable_caching)
    
    def generate_story(
        self,
        child_age: int,
        theme: str,
        length: str = "medium",
        categories: Optional[List[str]] = None,
        include_poems: bool = False,
        include_songs: bool = False,
        custom_prompt: str = "",
        use_cache: bool = True,
    ) -> GeneratedContent:
        """
        Generate a bedtime story.
        
        Args:
            child_age: Child's age in years
            theme: Story theme (e.g., 'adventure', 'animals', 'space')
            length: Story length ('short', 'medium', 'long')
            categories: Story categories/tags
            include_poems: Whether to include poetry elements
            include_songs: Whether to include song lyrics
            custom_prompt: Additional custom instructions
            use_cache: Whether to use cached results
            
        Returns:
            GeneratedContent with story and metadata
            
        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If generation fails
        """
        self._validate_generation_params(child_age, theme)
        
        # Check cache
        cache_key = None
        if self.enable_caching and use_cache:
            cache_key = self._get_cache_key(
                ContentType.STORY, child_age, theme, length,
                categories, custom_prompt
            )
            cached = self.cache.get_cached(cache_key)
            if cached:
                logger.info("Returning cached story for age=%d, theme=%s", child_age, theme)
                return GeneratedContent(**cached)
        
        logger.info("Generating story for age=%d, theme=%s, length=%s",
                   child_age, theme, length)
        
        # Build prompt
        prompt = build_complete_prompt(
            content_type="story",
            child_age=child_age,
            theme=theme,
            length=length,
            custom_prompt=custom_prompt,
        )
        
        # Generate content
        raw_content = self.groq.generate_text(
            prompt=prompt,
            max_tokens=2000,
            temperature=0.8,
            model=GroqService.QUALITY_MODEL
        )
        
        # Parse and validate
        parsed_content = self._parse_generated_content(raw_content)
        title = parsed_content.get("title", "Untitled Story")
        text = parsed_content.get("content", raw_content)
        
        # Validate content safety
        self._validate_content(text, child_age)
        
        # Extract metadata
        extracted_morals = parsed_content.get("morals", [])
        extracted_categories = parsed_content.get("categories", categories or [])
        duration = self._estimate_duration(text)
        
        # Add emotion markers
        text_with_markers = self._add_emotion_markers(text)
        emotion_markers = self._extract_emotion_markers(text_with_markers)
        
        # Create result
        result = GeneratedContent(
            title=title,
            text=text_with_markers,
            content_type=ContentType.STORY,
            theme=theme,
            categories=extracted_categories,
            morals=extracted_morals,
            duration_estimate=duration,
            emotion_markers=emotion_markers,
        )
        
        # Cache result
        if self.enable_caching and use_cache and cache_key:
            self.cache.set_cached(cache_key, result.to_dict())
        
        logger.info("Story generated successfully: '%s' (%.1f seconds)", title, duration)
        return result
    
    def generate_poem(
        self,
        child_age: int,
        style: str = "rhyming",
        theme: str = "bedtime",
        custom_prompt: str = "",
        use_cache: bool = True,
    ) -> GeneratedContent:
        """
        Generate a bedtime poem.
        
        Args:
            child_age: Child's age in years
            style: Poem style (e.g., 'rhyming', 'free_verse', 'haiku')
            theme: Poem theme
            custom_prompt: Additional custom instructions
            use_cache: Whether to use cached results
            
        Returns:
            GeneratedContent with poem and metadata
        """
        self._validate_generation_params(child_age, theme)
        
        # Check cache
        cache_key = None
        if self.enable_caching and use_cache:
            cache_key = self._get_cache_key(
                ContentType.POEM, child_age, theme, style, custom_prompt=custom_prompt
            )
            cached = self.cache.get_cached(cache_key)
            if cached:
                logger.info("Returning cached poem for age=%d, theme=%s", child_age, theme)
                return GeneratedContent(**cached)
        
        logger.info("Generating poem for age=%d, theme=%s, style=%s",
                   child_age, theme, style)
        
        custom_with_style = f"{custom_prompt}\nPoem style: {style}" if custom_prompt else f"Poem style: {style}"
        
        prompt = build_complete_prompt(
            content_type="poem",
            child_age=child_age,
            theme=theme,
            custom_prompt=custom_with_style,
        )
        
        raw_content = self.groq.generate_text(
            prompt=prompt,
            max_tokens=1000,
            temperature=0.9,
            model=GroqService.QUALITY_MODEL
        )
        
        parsed_content = self._parse_generated_content(raw_content)
        title = parsed_content.get("title", f"{theme.title()} Poem")
        text = parsed_content.get("content", raw_content)
        
        self._validate_content(text, child_age)
        
        duration = self._estimate_duration(text)
        text_with_markers = self._add_emotion_markers(text)
        emotion_markers = self._extract_emotion_markers(text_with_markers)
        
        result = GeneratedContent(
            title=title,
            text=text_with_markers,
            content_type=ContentType.POEM,
            theme=theme,
            categories=["poem", style],
            duration_estimate=duration,
            emotion_markers=emotion_markers,
        )
        
        if self.enable_caching and use_cache and cache_key:
            self.cache.set_cached(cache_key, result.to_dict())
        
        logger.info("Poem generated successfully: '%s'", title)
        return result
    
    def generate_song(
        self,
        child_age: int,
        genre: str = "lullaby",
        theme: str = "bedtime",
        custom_prompt: str = "",
        use_cache: bool = True,
    ) -> GeneratedContent:
        """
        Generate a bedtime song.
        
        Args:
            child_age: Child's age in years
            genre: Song genre (e.g., 'lullaby', 'folk', 'pop')
            theme: Song theme
            custom_prompt: Additional custom instructions
            use_cache: Whether to use cached results
            
        Returns:
            GeneratedContent with song lyrics and metadata
        """
        self._validate_generation_params(child_age, theme)
        
        # Check cache
        cache_key = None
        if self.enable_caching and use_cache:
            cache_key = self._get_cache_key(
                ContentType.SONG, child_age, theme, genre, custom_prompt=custom_prompt
            )
            cached = self.cache.get_cached(cache_key)
            if cached:
                logger.info("Returning cached song for age=%d, theme=%s", child_age, theme)
                return GeneratedContent(**cached)
        
        logger.info("Generating song for age=%d, theme=%s, genre=%s",
                   child_age, theme, genre)
        
        custom_with_genre = f"{custom_prompt}\nGenre: {genre}" if custom_prompt else f"Genre: {genre}"
        
        prompt = build_complete_prompt(
            content_type="song",
            child_age=child_age,
            theme=theme,
            custom_prompt=custom_with_genre,
        )
        
        raw_content = self.groq.generate_text(
            prompt=prompt,
            max_tokens=1200,
            temperature=0.85,
            model=GroqService.QUALITY_MODEL
        )
        
        parsed_content = self._parse_generated_content(raw_content)
        title = parsed_content.get("title", f"{theme.title()} {genre.title()}")
        text = parsed_content.get("content", raw_content)
        
        self._validate_content(text, child_age)
        
        duration = self._estimate_duration(text)
        text_with_markers = self._add_emotion_markers(text)
        emotion_markers = self._extract_emotion_markers(text_with_markers)
        
        result = GeneratedContent(
            title=title,
            text=text_with_markers,
            content_type=ContentType.SONG,
            theme=theme,
            categories=["song", genre],
            duration_estimate=duration,
            emotion_markers=emotion_markers,
        )
        
        if self.enable_caching and use_cache and cache_key:
            self.cache.set_cached(cache_key, result.to_dict())
        
        logger.info("Song generated successfully: '%s'", title)
        return result
    
    # Private methods
    
    @staticmethod
    def _validate_generation_params(child_age: int, theme: str) -> None:
        """Validate generation parameters."""
        if not 0 <= child_age <= 18:
            raise ValueError("Child age must be between 0 and 18")
        
        if not theme or not isinstance(theme, str):
            raise ValueError("Theme must be a non-empty string")
    
    @staticmethod
    def _get_cache_key(
        content_type: ContentType,
        child_age: int,
        theme: str,
        length_or_style: str = "",
        categories: Optional[List[str]] = None,
        custom_prompt: str = ""
    ) -> str:
        """Generate cache key from parameters."""
        from cache_service import ContentCache
        
        params = {
            "content_type": content_type.value,
            "age": child_age,
            "theme": theme,
            "style": length_or_style,
            "custom": custom_prompt[:50] if custom_prompt else "",  # First 50 chars
        }
        
        return ContentCache.cache_key(params)
    
    @staticmethod
    def _parse_generated_content(raw_content: str) -> dict:
        """
        Parse generated content from AI response.
        
        Args:
            raw_content: Raw text from AI
            
        Returns:
            Parsed dictionary with content, title, categories, etc.
        """
        # Try to parse as JSON first
        try:
            # Find JSON block in response
            json_match = re.search(r'\{[\s\S]*\}', raw_content)
            if json_match:
                json_str = json_match.group(0)
                return json.loads(json_str)
        except (json.JSONDecodeError, AttributeError):
            pass
        
        # Fallback: extract title and content from text
        lines = raw_content.strip().split('\n')
        
        title = "Untitled"
        content_start = 0
        
        # Try to find title in first few lines
        for i, line in enumerate(lines[:5]):
            if line.startswith("Title:") or line.startswith("**"):
                title = line.replace("Title:", "").replace("**", "").strip()
                content_start = i + 1
                break
        
        content = '\n'.join(lines[content_start:]).strip()
        
        return {
            "title": title,
            "content": content or raw_content,
            "categories": [],
            "morals": [],
        }
    
    @staticmethod
    def _validate_content(text: str, child_age: int) -> None:
        """
        Validate content safety and appropriateness.
        
        Args:
            text: Content to validate
            child_age: Child's age
            
        Raises:
            ValueError: If content fails validation
        """
        # Check for minimum content
        if not text or len(text.strip()) < 20:
            raise ValueError("Generated content is too short")
        
        # Check word count
        word_count = len(text.split())
        
        # Age-based word count limits
        limits = {
            2: 150, 4: 300, 6: 500, 8: 800, 10: 1000, 14: 1500, 18: 2000
        }
        
        age_limit = 150  # Default minimum
        for age_threshold in sorted(limits.keys()):
            if child_age <= age_threshold:
                age_limit = limits[age_threshold]
                break
        
        if word_count > age_limit * 2:  # Allow 2x flexibility
            logger.warning(
                "Content exceeds age-appropriate word limit: %d words for age %d",
                word_count, child_age
            )
        
        # Safety checks
        dangerous_words = [
            "blood", "kill", "death", "die", "dying", "murder",
            "violence", "scared", "nightmare", "terrified"
        ]
        
        text_lower = text.lower()
        if child_age < 7:
            found = [word for word in dangerous_words if word in text_lower]
            if found:
                logger.warning(
                    "Safety check failed for age %d: found dangerous words: %s",
                    child_age, found
                )
    
    @staticmethod
    def _extract_metadata(text: str) -> Tuple[List[str], List[str]]:
        """
        Extract categories and morals from text.
        
        Args:
            text: Generated content text
            
        Returns:
            Tuple of (categories, morals)
        """
        categories = []
        morals = []
        
        # Look for common category/moral indicators
        lines = text.split('\n')
        
        for line in lines:
            line_lower = line.lower()
            
            if 'moral' in line_lower or 'lesson' in line_lower:
                # Extract text after colon
                if ':' in line:
                    moral = line.split(':', 1)[1].strip()
                    if moral:
                        morals.append(moral)
            
            if 'categor' in line_lower or 'genre' in line_lower or 'type' in line_lower:
                if ':' in line:
                    cats = line.split(':', 1)[1].strip()
                    categories.extend([c.strip() for c in cats.split(',')])
        
        return categories, morals
    
    @staticmethod
    def _estimate_duration(text: str) -> float:
        """
        Estimate reading/listening duration in seconds.
        
        Args:
            text: Content text
            
        Returns:
            Estimated duration in seconds
        """
        word_count = len(text.split())
        # Use average reading speed of 150 WPM
        duration_seconds = (word_count / 150) * 60
        
        return round(duration_seconds, 1)
    
    @staticmethod
    def _add_emotion_markers(text: str) -> str:
        """Ensure AI-generated text has emotion markers.

        The LLM prompts now instruct the AI to embed contextual markers.
        This method only adds fallback markers when the AI didn't produce
        any, and guarantees a [SLEEPY] at the very end for bedtime safety.
        """
        # Check if the AI already embedded markers
        marker_pattern = re.compile(
            r"\[(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
            r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
            r"HUMMING|PAUSE|laugh|chuckle)\]",
            re.IGNORECASE,
        )
        has_markers = bool(marker_pattern.search(text))

        enhanced_text = text

        if not has_markers:
            # Fallback: add basic markers when AI didn't embed any
            enhanced_text = "[GENTLE] " + enhanced_text
            words = enhanced_text.split()
            if len(words) > 400:
                mid_point = len(words) // 2
                words.insert(mid_point, "[CALM]")
                enhanced_text = " ".join(words)

        # Always ensure [SLEEPY] at the end for bedtime
        if not enhanced_text.rstrip().upper().endswith("[SLEEPY]"):
            enhanced_text = enhanced_text.rstrip() + " [SLEEPY]"

        return enhanced_text
    
    @staticmethod
    def _extract_emotion_markers(text: str) -> List[Tuple[int, int, str]]:
        """Extract all emotion marker positions from text."""
        markers = []
        emotion_pattern = (
            r"\[(SLEEPY|GENTLE|CALM|EXCITED|CURIOUS|ADVENTUROUS|MYSTERIOUS|"
            r"JOYFUL|DRAMATIC|WHISPERING|DRAMATIC_PAUSE|RHYTHMIC|SINGING|"
            r"HUMMING|PAUSE|laugh|chuckle)\]"
        )

        for match in re.finditer(emotion_pattern, text, re.IGNORECASE):
            emotion = match.group(1).lower()
            markers.append((match.start(), match.end(), emotion))

        return markers
