"""Album art generation service for DreamWeaver stories, poems, and songs."""

import re
import random
import logging
from typing import List, Optional, Tuple
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter
import base64

from app.services.art.color_palette import (
    ColorPalette, get_palette_for_theme, get_random_variation
)
from app.services.art.art_templates import (
    generate_crescent_moon, generate_star, generate_cloud,
    generate_light_rays, generate_sparkles, _random_position,
    _random_rotation
)

logger = logging.getLogger(__name__)


class AlbumArtGenerator:
    """Generates custom album art for DreamWeaver content with signature DreamWeaver style."""
    
    # Entity patterns for extraction from content text
    ENTITY_PATTERNS = {
        "moon": r"\b(moon|crescent|lunar|nighttime)\b",
        "star": r"\b(star|stars|twinkle|twinkling|constellation)\b",
        "cloud": r"\b(cloud|clouds|cloudy|sky)\b",
        "tree": r"\b(tree|trees|forest|woods|branch)\b",
        "rabbit": r"\b(rabbit|bunny|hare)\b",
        "fox": r"\b(fox|foxes)\b",
        "bird": r"\b(bird|birds|fly|flying|wing|wings|eagle|sparrow|robin)\b",
        "fish": r"\b(fish|swim|water|ocean|sea|lake|river)\b",
        "castle": r"\b(castle|palace|tower|kingdom)\b",
        "boat": r"\b(boat|ship|sail|sailing)\b",
        "mountain": r"\b(mountain|mountains|peak|hill|hills)\b",
        "flower": r"\b(flower|flowers|rose|tulip|daisy|bloom)\b",
        "butterfly": r"\b(butterfly|butterflies|insect)\b",
        "sun": r"\b(sun|sunny|sunrise|sunset|sunshine)\b",
        "rain": r"\b(rain|raining|rainy|drops|downpour)\b",
    }
    
    # Content type badges
    CONTENT_TYPES = {
        "story": ("Story", "#FF6B9D"),
        "poem": ("Poem", "#9B59B6"),
        "song": ("Lullaby", "#3498DB"),
        "lullaby": ("Lullaby", "#F39C12"),
    }
    
    def __init__(self):
        """Initialize the album art generator."""
        self.canvas_size = 600
        
    def generate(self, content_text: str, theme: str, content_type: str = "story",
                title: str = "DreamWeaver", size: int = 600) -> bytes:
        """Generate album art for content.
        
        Args:
            content_text: The content text to extract entities from
            theme: Theme name (e.g., 'fantasy', 'ocean', 'space')
            content_type: Type of content ('story', 'poem', 'song', 'lullaby')
            title: Title to display on album art
            size: Output size in pixels (default 600x600)
            
        Returns:
            PNG image as bytes
            
        Raises:
            ValueError: If inputs are invalid
        """
        try:
            if not content_text:
                raise ValueError("content_text cannot be empty")
            if not theme:
                raise ValueError("theme cannot be empty")
            
            self.canvas_size = size
            
            # Pipeline steps
            logger.info(f"Generating album art for {content_type}: {title[:20]}...")
            
            # Step 1: Extract entities from text
            entities = self._extract_entities(content_text)
            logger.debug(f"Extracted entities: {entities}")
            
            # Step 2: Get color palette
            palette = get_palette_for_theme(theme)
            palette = get_random_variation(palette)
            
            # Step 3: Build SVG
            svg_string = self._build_svg(entities, palette, size, title, content_type)
            
            # Step 4: Convert SVG to PNG
            png_bytes = self._svg_to_png(svg_string, size)
            
            # Step 5: Apply post-processing effects
            final_bytes = self._add_post_effects(png_bytes)
            
            logger.info("Album art generated successfully")
            return final_bytes
            
        except Exception as e:
            logger.error(f"Error generating album art: {e}")
            raise
    
    def _extract_entities(self, text: str) -> List[str]:
        """Extract entities from content text using regex patterns.
        
        Args:
            text: Content text to analyze
            
        Returns:
            List of entity types found in text (max 4)
        """
        text_lower = text.lower()
        found_entities = []
        
        for entity_type, pattern in self.ENTITY_PATTERNS.items():
            if re.search(pattern, text_lower):
                found_entities.append(entity_type)
        
        # Always include stars and moon for DreamWeaver signature
        if "star" not in found_entities:
            found_entities.insert(0, "star")
        if "moon" not in found_entities:
            found_entities.insert(0, "moon")
        
        # Limit to 4-5 primary entities
        selected = found_entities[:4] if len(found_entities) >= 2 else found_entities
        
        logger.debug(f"Selected entities for art: {selected}")
        return selected
    
    def _build_svg(self, entities: List[str], palette: ColorPalette,
                   size: int, title: str, content_type: str) -> str:
        """Build SVG string for album art.
        
        Args:
            entities: List of entity types to include
            palette: Color palette to use
            size: Canvas size
            title: Title text
            content_type: Type of content
            
        Returns:
            SVG string
        """
        # Start SVG
        svg_parts = [
            f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
        ]
        
        # Define gradient for night sky background (DreamWeaver signature)
        gradient_id = "nightSkyGradient"
        svg_parts.append(f'''<defs>
            <linearGradient id="{gradient_id}" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" style="stop-color:{palette.background};stop-opacity:1" />
                <stop offset="50%" style="stop-color:{palette.primary};stop-opacity:0.8" />
                <stop offset="100%" style="stop-color:{palette.accent};stop-opacity:0.6" />
            </linearGradient>
            <radialGradient id="vignette" cx="50%" cy="50%" r="70%">
                <stop offset="0%" style="stop-color:#FFFFFF;stop-opacity:0" />
                <stop offset="100%" style="stop-color:#000000;stop-opacity:0.3" />
            </radialGradient>
        </defs>''')
        
        # Background with night sky gradient
        svg_parts.append(f'<rect width="{size}" height="{size}" fill="url(#{gradient_id})"/>')
        
        # Add signature elements: crescent moon (upper area)
        moon_x = size * 0.85
        moon_y = size * 0.15
        svg_parts.append(generate_crescent_moon(moon_x, moon_y, size // 15,
                                               palette.highlight))
        
        # Add scattered stars (signature style)
        num_stars = random.randint(8, 15)
        for _ in range(num_stars):
            sx, sy = _random_position(size, margin=40)
            star_size = random.randint(2, 5)
            svg_parts.append(generate_star(sx, sy, star_size // 2, palette.highlight))
        
        # Add light rays for atmosphere
        ray_x = size * 0.5
        ray_y = size * 0.3
        svg_parts.append(generate_light_rays(ray_x, ray_y, 6, size // 6,
                                            palette.accent, "0.15"))
        
        # Add extracted entities (2-4 entities positioned dynamically)
        entity_positions = self._generate_entity_positions(len(entities), size)
        
        for i, entity_type in enumerate(entities[:4]):
            if i < len(entity_positions):
                x, y = entity_positions[i]
                # Use primary or secondary color
                color = palette.primary if i % 2 == 0 else palette.secondary
                
                # Add entity SVG (simplified SVG shapes)
                entity_svg = self._get_entity_svg(entity_type, x, y, color,
                                                 palette.accent, size // 20)
                if entity_svg:
                    svg_parts.append(entity_svg)
        
        # Add title text at bottom with rounded overlay background
        title_y = size - 60
        overlay_height = 80
        svg_parts.append(f'''<rect x="10" y="{title_y - 10}" width="{size - 20}" height="{overlay_height}"
            rx="8" ry="8" fill="{palette.primary}" opacity="0.7"/>''')
        
        # Title text
        text_y = size - 35
        svg_parts.append(f'''<text x="{size // 2}" y="{text_y}" text-anchor="middle"
            font-size="24" font-weight="bold" fill="{palette.highlight}"
            font-family="Arial, sans-serif">{title[:30]}</text>''')
        
        # Content type badge
        badge_label, badge_color = self.CONTENT_TYPES.get(content_type.lower(),
                                                         ("Content", "#666666"))
        svg_parts.append(f'''<rect x="{size - 90}" y="10" width="80" height="30"
            rx="15" ry="15" fill="{badge_color}" opacity="0.8"/>
        <text x="{size - 50}" y="30" text-anchor="middle"
            font-size="12" font-weight="bold" fill="#FFFFFF"
            font-family="Arial, sans-serif">{badge_label}</text>''')
        
        # Starfield texture overlay (dots pattern)
        for _ in range(150):
            tx, ty = _random_position(size, margin=0)
            opacity = random.uniform(0.1, 0.3)
            svg_parts.append(f'<circle cx="{tx}" cy="{ty}" r="0.5" fill="{palette.highlight}" '
                           f'opacity="{opacity}"/>')
        
        # Vignette effect
        svg_parts.append(f'<rect width="{size}" height="{size}" fill="url(#vignette)"/>')
        
        # Close SVG
        svg_parts.append('</svg>')
        
        svg_string = "".join(svg_parts)
        logger.debug("SVG generated successfully")
        return svg_string
    
    def _svg_to_png(self, svg_string: str, size: int) -> bytes:
        """Convert SVG string to PNG bytes.
        
        Args:
            svg_string: SVG content as string
            size: Output size
            
        Returns:
            PNG image as bytes
        """
        try:
            # Try using cairosvg if available
            try:
                import cairosvg
                output = BytesIO()
                cairosvg.svg2png(bytestring=svg_string.encode(),
                               write_to=output, output_width=size, output_height=size)
                output.seek(0)
                return output.read()
            except ImportError:
                logger.warning("cairosvg not available, using PIL fallback")
                # Fallback: Create placeholder image using PIL
                img = Image.new("RGB", (size, size), color=(20, 20, 40))
                return self._create_fallback_art(img, size).tobytes()
        except Exception as e:
            logger.error(f"Error converting SVG to PNG: {e}")
            # Create simple fallback image
            img = Image.new("RGB", (size, size), color=(30, 30, 60))
            return self._create_fallback_art(img, size).tobytes()
    
    def _create_fallback_art(self, img: Image.Image, size: int) -> Image.Image:
        """Create a simple fallback album art using PIL.
        
        Args:
            img: PIL Image object
            size: Image size
            
        Returns:
            PIL Image with fallback art
        """
        draw = ImageDraw.Draw(img)
        # Draw stars
        for _ in range(20):
            x = random.randint(0, size)
            y = random.randint(0, size)
            draw.ellipse([x-2, y-2, x+2, y+2], fill=(255, 255, 200))
        # Draw moon
        moon_x, moon_y = size - 100, 80
        draw.ellipse([moon_x-40, moon_y-40, moon_x+40, moon_y+40], fill=(255, 255, 220))
        return img
    
    def _add_post_effects(self, png_bytes: bytes) -> bytes:
        """Apply post-processing effects to PNG image.
        
        Args:
            png_bytes: PNG image as bytes
            
        Returns:
            Processed PNG as bytes
        """
        try:
            # Load image from bytes
            img = Image.open(BytesIO(png_bytes))
            
            # Convert to RGB if necessary
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Apply subtle vignette
            img = self._apply_vignette(img)
            
            # Enhance colors slightly
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(1.1)  # 10% more saturation
            
            # Convert back to bytes
            output = BytesIO()
            img.save(output, format="PNG", quality=95)
            output.seek(0)
            return output.read()
            
        except Exception as e:
            logger.error(f"Error applying post effects: {e}")
            return png_bytes  # Return original if processing fails
    
    def _apply_vignette(self, img: Image.Image) -> Image.Image:
        """Apply vignette effect to image.
        
        Args:
            img: PIL Image object
            
        Returns:
            Image with vignette applied
        """
        width, height = img.size
        
        # Create vignette mask
        mask = Image.new("L", (width, height), 255)
        mask_draw = ImageDraw.Draw(mask)
        
        # Draw circles from center outward
        for i in range(max(width, height) // 2, 0, -20):
            mask_draw.ellipse(
                [width // 2 - i, height // 2 - i, width // 2 + i, height // 2 + i],
                fill=255 - (i // (max(width, height) // 4)) * 50
            )
        
        # Apply Gaussian blur to smooth vignette
        mask = mask.filter(ImageFilter.GaussianBlur(radius=40))
        
        # Create overlay
        overlay = Image.new("RGB", (width, height), (0, 0, 0))
        img.paste(overlay, mask=mask)
        
        return img
    
    def _generate_entity_positions(self, num_entities: int, size: int) -> List[Tuple[float, float]]:
        """Generate positions for entities on canvas.
        
        Args:
            num_entities: Number of entities to position
            size: Canvas size
            
        Returns:
            List of (x, y) positions
        """
        positions = []
        margin = size // 6
        
        if num_entities >= 1:
            positions.append((size * 0.25, size * 0.55))  # Left side, lower
        if num_entities >= 2:
            positions.append((size * 0.75, size * 0.55))  # Right side, lower
        if num_entities >= 3:
            positions.append((size * 0.25, size * 0.35))  # Left side, upper
        if num_entities >= 4:
            positions.append((size * 0.75, size * 0.35))  # Right side, upper
        
        return positions
    
    def _get_entity_svg(self, entity_type: str, x: float, y: float,
                       color: str, accent_color: str, size: int) -> str:
        """Get SVG for entity type.
        
        Args:
            entity_type: Type of entity
            x: X coordinate
            y: Y coordinate
            color: Primary color
            accent_color: Accent color
            size: Size multiplier
            
        Returns:
            SVG string for entity
        """
        entity_svgs = {
            "moon": generate_crescent_moon(x, y, size * 2, color),
            "star": generate_star(x, y, size // 2, color),
            "cloud": generate_cloud(x, y, size, color),
            "sparkle": generate_sparkles(x, y, 8, accent_color),
        }
        
        return entity_svgs.get(entity_type, "")
