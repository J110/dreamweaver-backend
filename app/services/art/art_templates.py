"""SVG templates and elements for DreamWeaver album art generation."""

import random
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


# Signature design elements that define the DreamWeaver visual style
SIGNATURE_ELEMENTS = {
    "crescent_moon": "DreamWeaver signature element - always present in upper area",
    "stars": "Scattered across sky for magical atmosphere",
    "soft_clouds": "Dreamy, organic shapes",
    "light_rays": "Atmospheric depth and wonder",
    "sparkles": "Fireflies and magical particles",
}


class SVGTemplate:
    """SVG entity templates with customizable colors."""
    
    # Crescent moon SVG (scalable)
    CRESCENT_MOON = '''<path d="M {x} {y} Q {x_offset} {y} {x} {y_offset} Q {x_minus} {y} {x} {y}" 
        fill="{color}" opacity="0.95"/>'''
    
    # Star SVG (simple 5-point star)
    STAR = '''<polygon points="{x},{y_star} {x_offset1},{y_offset1} {x_offset2},{y} {x_offset3},{y_offset2} {x_offset4},{y_offset3} {x_offset5},{y_offset4}"
        fill="{color}" opacity="0.8"/>'''
    
    # Cloud SVG (organic shape)
    CLOUD = '''<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{color}" opacity="0.7"/>
        <ellipse cx="{x_offset1}" cy="{y}" rx="{rx_offset}" ry="{ry}" fill="{color}" opacity="0.7"/>
        <ellipse cx="{x_offset2}" cy="{y}" rx="{rx}" ry="{ry}" fill="{color}" opacity="0.7"/>'''
    
    # Tree SVG (simple geometric)
    TREE = '''<polygon points="{x},{y} {x_left},{y_bottom} {x_right},{y_bottom}" fill="{color}" opacity="0.85"/>
        <rect x="{x_trunk}" y="{y_trunk}" width="{trunk_width}" height="{trunk_height}" fill="#8B4513" opacity="0.8"/>'''
    
    # Rabbit SVG (simple outline)
    RABBIT = '''<ellipse cx="{x}" cy="{y}" rx="{body_rx}" ry="{body_ry}" fill="{color}" opacity="0.9"/>
        <ellipse cx="{x_ear1}" cy="{y_ear}" rx="8" ry="20" fill="{color}" opacity="0.9"/>
        <ellipse cx="{x_ear2}" cy="{y_ear}" rx="8" ry="20" fill="{color}" opacity="0.9"/>
        <circle cx="{x}" cy="{y_eye}" r="3" fill="#000" opacity="0.8"/>'''
    
    # Fox SVG (geometric)
    FOX = '''<ellipse cx="{x}" cy="{y}" rx="{body_rx}" ry="{body_ry}" fill="{color}" opacity="0.9"/>
        <polygon points="{x},{y_ear1} {x_ear_left},{y_ear_top} {x_ear_middle},{y_ear_middle}" fill="{color}" opacity="0.9"/>
        <polygon points="{x},{y_ear1} {x_ear_right},{y_ear_top} {x_ear_middle},{y_ear_middle}" fill="{color}" opacity="0.9"/>
        <circle cx="{x}" cy="{y_eye}" r="3" fill="#000" opacity="0.8"/>'''
    
    # Bird SVG (simple)
    BIRD = '''<ellipse cx="{x}" cy="{y}" rx="12" ry="8" fill="{color}" opacity="0.85"/>
        <polygon points="{x_tail},{y} {x_tail_end},{y_tail_offset} {x_tail},{y_tail_down}" fill="{color}" opacity="0.7"/>
        <circle cx="{x_head}" cy="{y}" r="5" fill="{color}" opacity="0.85"/>
        <circle cx="{x_eye}" cy="{y_eye_offset}" r="1.5" fill="#000" opacity="0.8"/>'''
    
    # Fish SVG (simple)
    FISH = '''<ellipse cx="{x}" cy="{y}" rx="15" ry="8" fill="{color}" opacity="0.85"/>
        <polygon points="{x_tail},{y} {x_tail_end},{y_tail_up} {x_tail_end},{y_tail_down}" fill="{color}" opacity="0.7"/>
        <circle cx="{x_head}" cy="{y}" r="4" fill="{color}" opacity="0.85"/>
        <circle cx="{x_eye}" cy="{y_eye_offset}" r="1" fill="#000" opacity="0.8"/>'''
    
    # Castle SVG (geometric)
    CASTLE = '''<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{color}" opacity="0.8"/>
        <polygon points="{x_tower1},{y} {x_tower1_left},{y_peak} {x_tower1_right},{y_peak}" fill="{color}" opacity="0.9"/>
        <polygon points="{x_tower2},{y} {x_tower2_left},{y_peak} {x_tower2_right},{y_peak}" fill="{color}" opacity="0.9"/>
        <rect x="{x_door}" y="{y_door}" width="10" height="15" fill="#8B4513" opacity="0.7"/>'''
    
    # Boat SVG (simple)
    BOAT = '''<polygon points="{x_left},{y} {x_right},{y} {x_right_point},{y_bottom} {x_left_point},{y_bottom}" fill="{color}" opacity="0.85"/>
        <polygon points="{x_mast},{y} {x_mast_left},{y_mast_bottom} {x_mast_right},{y_mast_bottom}" fill="{accent_color}" opacity="0.75"/>'''
    
    # Mountain SVG (triangular)
    MOUNTAIN = '''<polygon points="{x},{y} {x_left},{y_base} {x_right},{y_base}" fill="{color}" opacity="0.8"/>
        <polygon points="{x_peak2_left},{y_peak2} {x_peak2},{y} {x_peak2_right},{y_peak2}" fill="{color}" opacity="0.85"/>'''
    
    # Flower SVG (simple)
    FLOWER = '''<circle cx="{x}" cy="{y}" r="3" fill="{accent_color}" opacity="0.9"/>
        <circle cx="{x_petal1}" cy="{y_petal1}" r="4" fill="{color}" opacity="0.85"/>
        <circle cx="{x_petal2}" cy="{y_petal2}" r="4" fill="{color}" opacity="0.85"/>
        <circle cx="{x_petal3}" cy="{y_petal3}" r="4" fill="{color}" opacity="0.85"/>
        <circle cx="{x_petal4}" cy="{y_petal4}" r="4" fill="{color}" opacity="0.85"/>
        <line x1="{x}" y1="{y}" x2="{x}" y2="{y_stem}" stroke="#228B22" stroke-width="1" opacity="0.7"/>'''
    
    # Butterfly SVG (symmetric)
    BUTTERFLY = '''<ellipse cx="{x_wing1}" cy="{y_wing1}" rx="8" ry="12" fill="{color}" opacity="0.85" transform="rotate(-30 {x_wing1} {y_wing1})"/>
        <ellipse cx="{x_wing2}" cy="{y_wing2}" rx="8" ry="12" fill="{color}" opacity="0.85" transform="rotate(30 {x_wing2} {y_wing2})"/>
        <ellipse cx="{x}" cy="{y}" rx="3" ry="10" fill="{color}" opacity="0.9"/>
        <circle cx="{x}" cy="{y_head}" r="2" fill="{color}" opacity="0.9"/>'''
    
    # Sun SVG (simple rays)
    SUN = '''<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}" opacity="0.85"/>
        <line x1="{x}" y1="{y_ray1}" x2="{x}" y2="{y_ray1_end}" stroke="{color}" stroke-width="2" opacity="0.7"/>
        <line x1="{x}" y1="{y_ray2}" x2="{x}" y2="{y_ray2_end}" stroke="{color}" stroke-width="2" opacity="0.7"/>
        <line x1="{x_ray3}" y1="{y}" x2="{x_ray3_end}" y2="{y}" stroke="{color}" stroke-width="2" opacity="0.7"/>
        <line x1="{x_ray4}" y1="{y}" x2="{x_ray4_end}" y2="{y}" stroke="{color}" stroke-width="2" opacity="0.7"/>'''
    
    # Rain SVG (falling lines)
    RAIN = '''<line x1="{x1}" y1="{y1}" x2="{x1_end}" y2="{y1_end}" stroke="{color}" stroke-width="1" opacity="0.6"/>
        <line x1="{x2}" y1="{y2}" x2="{x2_end}" y2="{y2_end}" stroke="{color}" stroke-width="1" opacity="0.6"/>
        <line x1="{x3}" y1="{y3}" x2="{x3_end}" y2="{y3_end}" stroke="{color}" stroke-width="1" opacity="0.6"/>
        <line x1="{x4}" y1="{y4}" x2="{x4_end}" y2="{y4_end}" stroke="{color}" stroke-width="1" opacity="0.6"/>'''


def _random_position(canvas_size: int = 600, margin: int = 50) -> Tuple[float, float]:
    """Generate random position within canvas bounds.
    
    Args:
        canvas_size: Size of canvas (default 600x600)
        margin: Margin from edges (default 50px)
        
    Returns:
        Tuple of (x, y) coordinates
    """
    x = random.randint(margin, canvas_size - margin)
    y = random.randint(margin, canvas_size - margin)
    return (x, y)


def _random_rotation() -> float:
    """Generate random rotation angle in degrees.
    
    Returns:
        Random float between 0 and 360
    """
    return random.uniform(0, 360)


def _scale_for_size(base_size: int = 600, target_size: int = 600) -> float:
    """Calculate scale factor for different canvas sizes.
    
    Args:
        base_size: Base size used for calculations (default 600)
        target_size: Target canvas size
        
    Returns:
        Scale factor
    """
    return target_size / base_size


def generate_crescent_moon(x: float, y: float, size: int = 40, color: str = "#FFFFFF") -> str:
    """Generate SVG crescent moon element.
    
    Args:
        x: X coordinate of moon center
        y: Y coordinate of moon center
        size: Size of moon (default 40px)
        color: Fill color (hex string)
        
    Returns:
        SVG path string for crescent moon
    """
    offset = size * 0.6
    return f'''<path d="M {x} {y-size} 
        Q {x+offset} {y-size} {x+offset} {y} 
        Q {x} {y+size} {x-offset} {y} 
        Q {x-offset} {y} {x} {y-size}" 
        fill="{color}" opacity="0.95"/>'''


def generate_star(x: float, y: float, size: int = 5, color: str = "#FFFFFF") -> str:
    """Generate SVG star element.
    
    Args:
        x: X coordinate of star center
        y: Y coordinate of star center
        size: Size of star (default 5px)
        color: Fill color (hex string)
        
    Returns:
        SVG polygon string for star
    """
    points = []
    for i in range(10):
        angle = (i * 36) - 90
        radius = size if i % 2 == 0 else size * 0.4
        px = x + radius * (3.141592653589793 * angle / 180)
        py = y + radius * (3.141592653589793 * angle / 180)
        points.append(f"{px},{py}")
    
    points_str = " ".join(points)
    return f'<polygon points="{points_str}" fill="{color}" opacity="0.8"/>'


def generate_cloud(x: float, y: float, size: int = 30, color: str = "#FFFFFF") -> str:
    """Generate SVG cloud element.
    
    Args:
        x: X coordinate of cloud center
        y: Y coordinate of cloud center
        size: Size of cloud (default 30px)
        color: Fill color (hex string)
        
    Returns:
        SVG path string for cloud
    """
    rx = size
    ry = size * 0.6
    return f'''<ellipse cx="{x-15}" cy="{y}" rx="{rx}" ry="{ry}" fill="{color}" opacity="0.7"/>
    <ellipse cx="{x}" cy="{y-5}" rx="{rx}" ry="{ry}" fill="{color}" opacity="0.7"/>
    <ellipse cx="{x+15}" cy="{y}" rx="{rx}" ry="{ry}" fill="{color}" opacity="0.7"/>'''


def generate_light_rays(x: float, y: float, num_rays: int = 5, length: int = 60, 
                       color: str = "#FFFF99", opacity: str = "0.3") -> str:
    """Generate SVG light rays element.
    
    Args:
        x: X coordinate of ray source
        y: Y coordinate of ray source
        num_rays: Number of rays to generate (default 5)
        length: Length of rays (default 60px)
        color: Ray color (hex string)
        opacity: Ray opacity (0.0-1.0)
        
    Returns:
        SVG group string with multiple lines
    """
    rays = []
    angle_step = 360 / num_rays
    
    for i in range(num_rays):
        angle = (i * angle_step) * 3.141592653589793 / 180
        x2 = x + length * (angle % 2)
        y2 = y + length * ((angle + 1) % 2)
        rays.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" '
                   f'stroke="{color}" stroke-width="1.5" opacity="{opacity}"/>')
    
    return "".join(rays)


def generate_sparkles(x: float, y: float, num_sparkles: int = 8, 
                     color: str = "#FFD700") -> str:
    """Generate SVG sparkle/firefly elements.
    
    Args:
        x: X coordinate of sparkle cluster center
        y: Y coordinate of sparkle cluster center
        num_sparkles: Number of sparkles (default 8)
        color: Sparkle color (hex string)
        
    Returns:
        SVG group string with multiple small circles
    """
    sparkles = []
    radius = 30
    
    for i in range(num_sparkles):
        angle = (i * 360 / num_sparkles) * 3.141592653589793 / 180
        sx = x + radius * (angle % 2)
        sy = y + radius * ((angle + 1) % 2)
        sparkles.append(f'<circle cx="{sx}" cy="{sy}" r="1.5" fill="{color}" opacity="0.8"/>')
    
    return "".join(sparkles)


def get_entity_svg(entity_type: str, x: float, y: float, color: str, 
                   accent_color: str = None, size: int = 20) -> str:
    """Generate SVG for a specific entity type.
    
    Args:
        entity_type: Type of entity (moon, star, cloud, tree, rabbit, fox, bird, 
                    fish, castle, boat, mountain, flower, butterfly, sun, rain)
        x: X coordinate
        y: Y coordinate
        color: Primary color (hex string)
        accent_color: Secondary color (hex string, optional)
        size: Size multiplier (default 20)
        
    Returns:
        SVG string for the entity
    """
    accent_color = accent_color or color
    
    entity_svgs = {
        "moon": generate_crescent_moon(x, y, size, color),
        "star": generate_star(x, y, size // 5, color),
        "cloud": generate_cloud(x, y, size, color),
        "light_ray": generate_light_rays(x, y, 5, size, color),
        "sparkle": generate_sparkles(x, y, 8, color),
    }
    
    if entity_type in entity_svgs:
        return entity_svgs[entity_type]
    
    logger.warning(f"Unknown entity type: {entity_type}, returning empty string")
    return ""
