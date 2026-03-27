"""
Language level configuration for Dream Valley content generation.

Three levels: basic, intermediate, advanced.
Used by generate_content_matrix.py (text generation), classify_language_levels.py,
and pipeline_run.py (orchestration).
"""

# ═══════════════════════════════════════════════════════════════════════
# VALID LANGUAGE LEVEL x CONTENT TYPE COMBINATIONS
# ═══════════════════════════════════════════════════════════════════════

VALID_LANGUAGE_LEVELS = {"basic", "intermediate", "advanced"}

# Language levels apply to stories, long stories, and poems.
# Lullabies (songs) are inherently basic — skip language level.
# Funny shorts are exempt — comedy has its own vocabulary rules.
VALID_LANGUAGE_LEVEL_CONTENT_TYPES = {
    "basic":        ["story", "long_story", "poem"],
    "intermediate": ["story", "long_story", "poem"],
    "advanced":     ["story", "long_story", "poem"],
}

# All age groups support all language levels
VALID_LANGUAGE_LEVEL_AGES = {
    "basic":        ["2-5", "6-8", "9-12"],
    "intermediate": ["2-5", "6-8", "9-12"],
    "advanced":     ["2-5", "6-8", "9-12"],
}


def validate_language_level_combo(language_level: str, age: str, content_type: str) -> tuple:
    """Check if language_level x age x content_type combination is valid. Returns (valid, reason)."""
    if language_level not in VALID_LANGUAGE_LEVELS:
        return False, f"Unknown language level: {language_level}"
    if age not in VALID_LANGUAGE_LEVEL_AGES.get(language_level, []):
        return False, f"Language level '{language_level}' not valid for age {age}"
    if content_type not in VALID_LANGUAGE_LEVEL_CONTENT_TYPES.get(language_level, []):
        return False, f"Language level '{language_level}' not valid for {content_type}"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════
# GENERATION TARGETS — weighted toward basic/intermediate (the gap)
# ═══════════════════════════════════════════════════════════════════════

LANGUAGE_LEVEL_TARGET = {
    "basic":        0.35,
    "intermediate": 0.40,
    "advanced":     0.25,
}


# ═══════════════════════════════════════════════════════════════════════
# GENERATION PROMPTS — injected into prompt stack
# ═══════════════════════════════════════════════════════════════════════

LANGUAGE_LEVEL_PROMPTS = {
    "basic": """
VOCABULARY LEVEL: BASIC — "Keep It Simple"

CRITICAL: Use ONLY common everyday words. Short sentences (5-8 words average,
never more than 12 words).

DO:
- "The bear walked to the river."
- "The water was cold."
- "She felt happy."
- "The stars were bright."

DO NOT:
- "The bear padded softly toward the shimmering river."
- "The water was crystalline and frigid."
- "A warmth blossomed in her chest."
- "The stars punctuated the velvet sky."

No metaphors. No similes. No figurative language. No words a child would
need explained. Describe things directly: "big" not "enormous," "pretty"
not "luminescent," "walked" not "padded," "dark" not "shadowy."

Repetition is GOOD. Familiar sentence patterns create comfort.
"The bear sat down. The bear was tired. The bear closed his eyes."
This is correct for basic level.
""",

    "intermediate": """
VOCABULARY LEVEL: INTERMEDIATE — "Just Right"

Use clear descriptive language but nothing unusual. Medium sentences
(8-15 words average, occasional longer sentence okay).

DO:
- "The little bear walked softly to the river."
- "The moonlight made the water sparkle."
- "She felt warm and safe, like being wrapped in a blanket."
- Simple similes: "soft as a cloud," "quiet as snow," "like a candle"

DO NOT:
- "The bear's silhouette merged with the dappled shadows."
- "The river murmured ancient secrets."
- "An amber glow suffused the glade."

Common descriptive words are fine: sparkle, glow, gentle, cozy, shimmer,
rustle, hum, flutter, peek, snuggle, drift, twinkle.

The test: would a child understand this sentence the FIRST time they
hear it, without pausing to think about any word?
""",

    "advanced": """
VOCABULARY LEVEL: ADVANCED — "Challenge Them"

Rich, literary language. No restrictions on vocabulary or sentence
complexity. Metaphors, personification, sensory detail, varied sentence
structure. This is the default — write naturally without simplifying.
""",
}


# ═══════════════════════════════════════════════════════════════════════
# PHASE REMINDERS — for long stories (prevent drift across phases)
# ═══════════════════════════════════════════════════════════════════════

LANGUAGE_LEVEL_PHASE_REMINDER = {
    "basic": ("REMINDER: Keep vocabulary BASIC. Short sentences. Common words only. "
              "'The bear walked' not 'the bear padded.' 'Stars' not 'constellations.'"),
    "intermediate": ("REMINDER: Keep vocabulary INTERMEDIATE. Clear and descriptive "
                     "but no unusual words. 'Sparkle' is fine, 'luminescent' is not."),
    "advanced": "",  # no reminder needed — advanced is the default
}


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION PROMPT — post-generation quality check
# ═══════════════════════════════════════════════════════════════════════

LANGUAGE_VALIDATION_PROMPT = """Read this children's story that was supposed to be written at
{target_level} vocabulary level for ages {age_group}.

Check for violations:

For BASIC level, flag any:
- Sentences longer than 12 words
- Uncommon words (anything a child wouldn't use in conversation)
- Metaphors or figurative language
- Abstract descriptions

For INTERMEDIATE level, flag any:
- Sentences longer than 20 words
- Literary vocabulary (luminescent, ethereal, gossamer, etc.)
- Complex metaphors (simple similes like "soft as snow" are okay)
- Nested subclauses or em-dash constructions

Respond with:
PASS — if the story matches the target level
FAIL — followed by the specific sentences that violate the level

Story:
\"\"\"
{story_text}
\"\"\""""
