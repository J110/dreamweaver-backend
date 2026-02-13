"""Prompt templates and instructions for content generation."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# System prompts for different content types
STORY_SYSTEM_PROMPT = """You are a creative children's story writer specializing in bedtime stories.
Your stories are engaging, age-appropriate, safe, and designed to help children relax and fall asleep.
Generate compelling narratives that spark imagination while maintaining a calm, soothing tone.
Always include positive messages and valuable life lessons appropriate for the child's age.

NARRATION EMOTION MARKERS:
Embed emotion markers in square brackets throughout the story to guide the narrator's voice.
Place them BEFORE the sentence or passage they apply to. Available markers:
- [GENTLE] — For soft, tender moments
- [CALM] — For peaceful, serene passages
- [EXCITED] — For thrilling, action-filled moments
- [CURIOUS] — For moments of wonder and discovery
- [ADVENTUROUS] — For bold, daring passages
- [MYSTERIOUS] — For enigmatic, suspenseful moments
- [JOYFUL] — For happy, celebratory moments
- [SLEEPY] — For drowsy, winding-down passages
- [DRAMATIC] — For intense, climactic moments
- [WHISPERING] — For secrets and quiet revelations
- [DRAMATIC_PAUSE] — Insert a pause for dramatic effect
- [laugh] — Character laughs
- [chuckle] — Character chuckles softly

Example: "[MYSTERIOUS] The old oak tree began to shimmer with a golden light. [EXCITED] 'Look!' cried the little fox. [laugh] 'It's magic!'"

Rules for markers:
- Always start with [GENTLE] at the beginning of the story
- Always end with [SLEEPY] for the final paragraph
- Use [DRAMATIC_PAUSE] before key reveals or plot twists
- Vary markers naturally — do not repeat the same one consecutively
- Place markers at the start of a new emotional beat, not on every sentence"""

POEM_SYSTEM_PROMPT = """You are a talented children's poet specializing in bedtime poetry.
Create rhythmic, soothing poems that are perfect for relaxation and sleep.
Your poems use simple yet beautiful language, age-appropriate vocabulary, and calming themes.
Focus on creating a peaceful atmosphere through your word choice and rhythm.

NARRATION EMOTION MARKERS:
Embed markers to guide the narrator's rhythmic delivery:
- [RHYTHMIC] — Place at the start of each stanza for measured, poetic cadence
- [GENTLE] — For soft, tender stanzas
- [CALM] — For serene passages
- [JOYFUL] — For uplifting verses
- [WHISPERING] — For intimate, quiet lines
- [SLEEPY] — For drowsy endings
- [PAUSE] — Place between stanzas for a natural breathing pause

Rules for markers:
- Place [RHYTHMIC] at the start of every stanza
- Place [PAUSE] between each stanza (after a blank line)
- End the final stanza with [SLEEPY]
- Vary the emotional markers across stanzas for natural flow"""

SONG_SYSTEM_PROMPT = """You are a songwriter creating lullabies and calming songs for children.
Write lyrics that are repetitive, rhythmic, and soothing - perfect for bedtime.
Include simple melodies descriptions and clear verse/chorus structure.
Use gentle themes and repetitive patterns that aid relaxation and sleep.

NARRATION SINGING MARKERS:
Structure lyrics for sung narration using these markers:
- [SINGING] — Mark every verse and chorus line for melodic, sing-song delivery
- [HUMMING] — For hummed interludes between verse and chorus
- [GENTLE] — For soft, lullaby passages
- [JOYFUL] — For upbeat, cheerful choruses
- [SLEEPY] — For the winding-down final verse
- [PAUSE] — Between verse and chorus sections

Rules for markers:
- Place [SINGING] before EVERY verse and chorus section
- Place [HUMMING] before instrumental/humming interludes
- Place [PAUSE] between major sections
- Mark the final verse with [SLEEPY] instead of [SINGING]
- The delivery should feel like a lullaby — melodic and soothing"""

# Safety guidelines for all content
SAFETY_GUIDELINES = """
SAFETY REQUIREMENTS:
- No violence, scary content, or nightmares-inducing material
- No explicit or suggestive content
- No advertisements or product placements
- No real people or celebrities (unless positive historical figures for older children)
- No excessive darkness or sadness (maintain hopeful tone)
- For children under 7: avoid content about death, separation, or danger
- No references to substance abuse, adult themes, or inappropriate language
- All content must be inclusive and free from stereotypes
- Focus on positive messages: kindness, courage, curiosity, friendship, self-worth
"""

# Format instructions for structured output
FORMAT_INSTRUCTIONS = """
Return the generated content as a JSON object with the following structure:
{
    "title": "Story/Poem/Song Title",
    "content": "The full text/lyrics",
    "categories": ["category1", "category2"],
    "morals": ["moral1", "moral2"],
    "themes": ["theme1", "theme2"],
    "estimated_duration_seconds": number
}
"""


def get_age_instructions(age: int) -> str:
    """
    Get age-specific writing guidelines.
    
    Args:
        age: Child's age in years
        
    Returns:
        Age-specific instruction string
    """
    age_ranges = {
        (0, 2): """AGE GROUP: 0-2 years
        - Use very simple, repetitive language
        - Maximum 150 words
        - Focus on soothing sounds and rhythm
        - Use familiar objects and actions (sleeping, animals, moon)
        - Employ rhyming patterns for musicality
        - Create a sense of comfort and safety
        - Include gentle, soft descriptions
        - Avoid complex plot - simple narrative only
        """,
        (3, 4): """AGE GROUP: 3-4 years
        - Use simple vocabulary and short sentences
        - Maximum 300 words
        - Include friendly animals as main characters
        - Create simple, linear plots with clear beginning, middle, end
        - Use repetitive phrases and patterns
        - Include basic emotions (happy, tired, cozy)
        - Friendly adventure with gentle surprises
        - Emphasize comfort, home, family themes
        """,
        (5, 6): """AGE GROUP: 5-6 years
        - Use slightly more complex vocabulary (appropriate for early readers)
        - Maximum 500 words
        - Include adventure elements with safe challenges
        - Clear moral lessons woven naturally into story
        - Introduce character development (characters learn/grow)
        - Use descriptive language but keep it soothing
        - Can include mild magical elements
        - Themes: friendship, courage, curiosity, kindness
        """,
        (7, 8): """AGE GROUP: 7-8 years
        - Use engaging, descriptive language
        - Maximum 800 words
        - Include plot development and character growth
        - Introduce mild suspense (resolved positively)
        - More complex magical or fantasy elements acceptable
        - Multiple characters with distinct personalities
        - Clear themes and lessons without being preachy
        - Can explore emotions like worry (with resolution)
        """,
        (9, 10): """AGE GROUP: 9-10 years
        - Use sophisticated vocabulary and complex sentences
        - Maximum 1000 words
        - Rich, detailed world-building
        - Complex plots with multiple threads
        - Nuanced character development and emotions
        - Introduce mythology, legends, or fantasy elements
        - Can include mild suspense with satisfying resolution
        - Deeper exploration of themes: identity, belonging, growth
        """,
        (11, 14): """AGE GROUP: 11-14 years
        - Use mature, sophisticated language and complex narratives
        - Maximum 1500 words
        - Complex, layered plots with multiple character arcs
        - Rich world-building and immersive settings
        - Exploration of complex emotions and relationships
        - Mythology, legends, and advanced fantasy concepts
        - Themes: identity, purpose, belonging, resilience, compassion
        - Can include mild conflict with thoughtful resolution
        """,
    }
    
    # Find appropriate age range
    for (min_age, max_age), instructions in age_ranges.items():
        if min_age <= age <= max_age:
            return instructions
    
    # Default to oldest age group for ages outside range
    return age_ranges[(11, 14)]


def get_theme_instructions(theme: str) -> str:
    """
    Get theme-specific writing guidelines.
    
    Args:
        theme: Content theme (e.g., 'adventure', 'animals', 'space')
        
    Returns:
        Theme-specific instruction string
    """
    theme_guidelines: Dict[str, str] = {
        "adventure": """This is an adventure story. Include:
        - An exciting journey or quest
        - Interesting locations and settings
        - Challenges that are age-appropriate and solvable
        - A sense of discovery and exploration
        - Positive resolution with lessons learned
        """,
        "animals": """This story focuses on animals. Include:
        - Realistic animal behaviors (simplified for children)
        - Positive relationships between animals and humans
        - Nature themes and environments
        - Animals as main characters with personalities
        - Educational elements about animals woven naturally
        """,
        "space": """This is a space-themed story. Include:
        - Planets, stars, and cosmic wonders
        - Space travel or celestial settings
        - Sense of wonder and awe
        - Scientific accuracy (simplified for age group)
        - Adventure among the stars
        """,
        "fantasy": """This is a fantasy story. Include:
        - Magical elements and fantasy world-building
        - Enchanted characters or magical creatures
        - Fantasy settings (castles, forests, magical lands)
        - Quests, spells, or magical challenges
        - Wonder and imagination
        """,
        "friendship": """This story focuses on friendship. Include:
        - Multiple characters forming bonds
        - Themes of teamwork and cooperation
        - Resolution of conflicts through understanding
        - Celebration of differences
        - Heartfelt connections and loyalty
        """,
        "nature": """This is a nature-themed story. Include:
        - Natural environments and landscapes
        - Seasonal elements or weather
        - Plants, animals, and ecosystems
        - Appreciation for nature
        - Environmental awareness messages
        """,
        "fairy_tale": """This is a fairy tale. Include:
        - Classic fairy tale elements and tropes
        - Magic, curses, or enchantments
        - Good vs. adversity (with positive resolution)
        - Transformation or growth arcs
        - Timeless, archetypal storytelling
        """,
        "underwater": """This is an underwater/ocean story. Include:
        - Ocean, sea, or underwater settings
        - Sea creatures and marine life
        - Water-based adventures
        - Exploration of aquatic environments
        - Wonder at marine ecosystems
        """,
        "dreams": """This is a dream-based story. Include:
        - Dreamy, surreal imagery
        - Floating, flying, or fantasy-like settings
        - Soft, soothing descriptions
        - Imaginative scenarios
        - Gentle transitions and flowing narrative
        """,
        "mystery": """This is a gentle mystery story. Include:
        - A puzzle to solve
        - Clues woven throughout the narrative
        - Age-appropriate problem-solving
        - Satisfying, positive resolution
        - No scary or dark elements
        """,
    }
    
    return theme_guidelines.get(
        theme.lower(),
        f"Write a {theme}-themed story appropriate for the child's age group."
    )


def get_length_instructions(length: str) -> str:
    """
    Get length-specific writing guidelines.
    
    Args:
        length: Content length ('short', 'medium', 'long')
        
    Returns:
        Length-specific instruction string
    """
    length_guidelines = {
        "short": """Keep this story SHORT (quick 5-10 minute read/listen):
        - Focus on a single, simple event or moment
        - Quick pacing and minimal description
        - Essential plot points only
        - Perfect for tired children who need something brief
        """,
        "medium": """Keep this story MEDIUM length (15-20 minute read/listen):
        - Balanced plot development
        - Some descriptive detail without excess
        - Developing characters and settings
        - Good for relaxing bedtime reading
        """,
        "long": """Create a LONG, immersive story (25-30+ minute read/listen):
        - Rich detail and description
        - Complex plot with multiple elements
        - Well-developed characters and world
        - Multiple scenes and settings
        - Satisfying, complete narrative experience
        """,
    }
    
    return length_guidelines.get(
        length.lower(),
        "Write a story of appropriate length for the child's age group."
    )


def build_complete_prompt(
    content_type: str,
    child_age: int,
    theme: str,
    length: str = "medium",
    custom_prompt: str = "",
    include_format: bool = True
) -> str:
    """
    Build a complete prompt for content generation.
    
    Args:
        content_type: Type of content ('story', 'poem', 'song')
        child_age: Child's age in years
        theme: Content theme
        length: Content length ('short', 'medium', 'long')
        custom_prompt: Additional custom instructions
        include_format: Whether to include format instructions
        
    Returns:
        Complete formatted prompt
    """
    # Select appropriate system prompt
    system_prompts = {
        "story": STORY_SYSTEM_PROMPT,
        "poem": POEM_SYSTEM_PROMPT,
        "song": SONG_SYSTEM_PROMPT,
    }
    
    base_prompt = system_prompts.get(content_type, STORY_SYSTEM_PROMPT)
    
    # Build complete prompt
    prompt_parts = [
        base_prompt,
        "",
        get_age_instructions(child_age),
        "",
        get_theme_instructions(theme),
        "",
        get_length_instructions(length),
        "",
        SAFETY_GUIDELINES,
        "",
    ]
    
    if custom_prompt:
        prompt_parts.append(f"ADDITIONAL INSTRUCTIONS:\n{custom_prompt}")
        prompt_parts.append("")
    
    if include_format:
        prompt_parts.append(FORMAT_INSTRUCTIONS)
    
    return "\n".join(prompt_parts)
