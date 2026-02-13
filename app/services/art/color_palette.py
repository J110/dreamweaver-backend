"""Color palette management for DreamWeaver album art generation."""

import random
from dataclasses import dataclass
from typing import Dict, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class ColorPalette:
    """Represents a color palette for album art generation.
    
    Attributes:
        primary: Primary color for main elements (hex string)
        secondary: Secondary color for accent elements (hex string)
        accent: Accent color for highlights (hex string)
        background: Background color (hex string)
        highlight: Highlight color for special elements (hex string)
    """
    primary: str
    secondary: str
    accent: str
    background: str
    highlight: str


# Predefined color palettes for different themes
PALETTES: Dict[str, ColorPalette] = {
    "fantasy": ColorPalette(
        primary="#2D1B4E",          # Deep purple
        secondary="#E6B7D8",        # Soft pink
        accent="#D4AF37",           # Golden
        background="#1A0F2E",       # Deep indigo background
        highlight="#F0E68C"         # Light golden highlight
    ),
    "adventure": ColorPalette(
        primary="#FF8C42",          # Warm orange
        secondary="#2D6A4F",        # Forest green
        accent="#87CEEB",           # Sky blue
        background="#FFF8DC",       # Cream background
        highlight="#FFD700"         # Gold highlight
    ),
    "ocean": ColorPalette(
        primary="#004E89",          # Deep blue
        secondary="#1FA7AF",        # Teal
        accent="#F1FAEE",           # Sandy gold
        background="#0B3D5C",       # Dark blue background
        highlight="#A8DADC"         # Light blue highlight
    ),
    "space": ColorPalette(
        primary="#0B1929",          # Dark indigo
        secondary="#C0C0C0",        # Silver
        accent="#00CED1",           # Neon blue
        background="#000000",       # Black background
        highlight="#87CEEB"         # Cyan highlight
    ),
    "nature": ColorPalette(
        primary="#2D5016",          # Earthy green
        secondary="#8B6F47",        # Warm brown
        accent="#FFD700",           # Sunshine yellow
        background="#1B3A1B",       # Dark forest background
        highlight="#90EE90"         # Light green highlight
    ),
    "fairy_tale": ColorPalette(
        primary="#E75480",          # Rose pink
        secondary="#B19CD9",        # Lavender
        accent="#E0FFFF",           # Silver sparkle (cyan-white)
        background="#FFE4F0",       # Pink background
        highlight="#FFB6DE"         # Hot pink highlight
    ),
    "dreamy": ColorPalette(
        primary="#B8C8E6",          # Soft blue
        secondary="#E6D5F0",        # Misty purple
        accent="#F0F8FF",           # Alice blue
        background="#E8E8F0",       # Soft lavender background
        highlight="#FFE4B5"         # Moccasin highlight
    ),
    "animals": ColorPalette(
        primary="#D2691E",          # Warm brown
        secondary="#228B22",        # Forest green
        accent="#87CEEB",           # Sky blue
        background="#F5DEB3",       # Wheat background
        highlight="#FFD700"         # Golden highlight
    ),
    "mythology": ColorPalette(
        primary="#DAA520",          # Rich gold
        secondary="#8B0000",        # Deep red
        accent="#9370DB",           # Medium purple
        background="#2F4F4F",       # Dark slate background
        highlight="#FFD700"         # Gold highlight
    ),
    "lullaby": ColorPalette(
        primary="#FFB6C1",          # Light pink
        secondary="#ADD8E6",        # Light blue
        accent="#FFFACD",           # Lemon chiffon
        background="#FFF5EE",       # Seashell background
        highlight="#E6F2FF"         # Very light blue highlight
    ),
}


def get_palette_for_theme(theme: str) -> ColorPalette:
    """Get color palette for a specific theme.
    
    Args:
        theme: Theme name (e.g., 'fantasy', 'ocean', 'space')
        
    Returns:
        ColorPalette matching the theme, or a random palette if theme not found
        
    Raises:
        ValueError: If theme is None or empty string
    """
    if not theme:
        raise ValueError("Theme cannot be None or empty string")
    
    theme_lower = theme.lower().strip()
    if theme_lower in PALETTES:
        logger.debug(f"Using palette for theme: {theme_lower}")
        return PALETTES[theme_lower]
    
    logger.warning(f"Theme '{theme}' not found, using random palette")
    return random.choice(list(PALETTES.values()))


def get_random_variation(palette: ColorPalette) -> ColorPalette:
    """Generate a subtle color variation of a palette for uniqueness.
    
    This function shifts each color slightly (±5-10%) to create variation
    while maintaining the overall theme.
    
    Args:
        palette: Base ColorPalette to vary
        
    Returns:
        New ColorPalette with slightly shifted colors
    """
    def shift_hex_color(hex_color: str, shift_percent: int = 8) -> str:
        """Shift a hex color by a percentage amount.
        
        Args:
            hex_color: Hex color string (e.g., '#FF0000')
            shift_percent: Percentage to shift (positive or negative, 0-20 recommended)
            
        Returns:
            Shifted hex color string
        """
        # Remove '#' if present
        hex_color = hex_color.lstrip('#')
        
        # Parse RGB components
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        # Random shift direction and amount (-shift_percent to +shift_percent)
        shift = random.randint(-shift_percent, shift_percent)
        shift_factor = 1 + (shift / 100)
        
        # Apply shift with bounds
        r = max(0, min(255, int(r * shift_factor)))
        g = max(0, min(255, int(g * shift_factor)))
        b = max(0, min(255, int(b * shift_factor)))
        
        return f"#{r:02X}{g:02X}{b:02X}"
    
    try:
        varied_palette = ColorPalette(
            primary=shift_hex_color(palette.primary),
            secondary=shift_hex_color(palette.secondary),
            accent=shift_hex_color(palette.accent),
            background=shift_hex_color(palette.background),
            highlight=shift_hex_color(palette.highlight),
        )
        logger.debug("Generated color palette variation")
        return varied_palette
    except Exception as e:
        logger.error(f"Error creating palette variation: {e}")
        return palette  # Return original if variation fails


def get_all_themes() -> list:
    """Get list of all available themes.
    
    Returns:
        List of theme names
    """
    return list(PALETTES.keys())
