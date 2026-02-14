"""Audio processing utilities for TTS output."""

import io
import logging
from typing import List, Optional

try:
    from pydub import AudioSegment
    from pydub.utils import mediainfo
except ImportError:
    raise ImportError(
        "pydub package not installed. Install with: pip install pydub\n"
        "Also requires ffmpeg to be installed on the system"
    )

logger = logging.getLogger(__name__)


def normalize_audio(audio_bytes: bytes, target_db: float = -3.0) -> bytes:
    """
    Normalize audio to target loudness level.
    
    Args:
        audio_bytes: Audio data in bytes
        target_db: Target loudness in dB (default -3.0)
        
    Returns:
        Normalized audio bytes
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # Calculate current loudness (simplified)
        current_db = audio.dBFS
        
        # Adjust volume
        gain = target_db - current_db
        normalized = audio.apply_gain(gain)
        
        # Export to bytes
        output = io.BytesIO()
        normalized.export(output, format="mp3", bitrate="128k")
        
        logger.debug("Normalized audio: %.1f dB -> %.1f dB", current_db, target_db)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Audio normalization failed: %s", str(e))
        raise ValueError(f"Failed to normalize audio: {str(e)}") from e


def concatenate_audio(audio_chunks: List[bytes], pause_ms: int = 500) -> bytes:
    """
    Concatenate multiple audio chunks with silence between them.
    
    Args:
        audio_chunks: List of audio byte chunks
        pause_ms: Silence duration between chunks in milliseconds
        
    Returns:
        Concatenated audio bytes
        
    Raises:
        ValueError: If audio chunks are invalid
    """
    if not audio_chunks:
        raise ValueError("At least one audio chunk is required")
    
    try:
        # Load first chunk
        combined = AudioSegment.from_file(io.BytesIO(audio_chunks[0]))
        
        # Create silence segment
        silence = AudioSegment.silent(duration=pause_ms)
        
        # Add remaining chunks with silence between
        for chunk in audio_chunks[1:]:
            audio = AudioSegment.from_file(io.BytesIO(chunk))
            combined = combined + silence + audio
        
        # Export to bytes
        output = io.BytesIO()
        combined.export(output, format="mp3", bitrate="128k")
        
        logger.info("Concatenated %d audio chunks with %d ms pause",
                   len(audio_chunks), pause_ms)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Audio concatenation failed: %s", str(e))
        raise ValueError(f"Failed to concatenate audio: {str(e)}") from e


def add_fade_in(audio_bytes: bytes, duration_ms: int = 1000) -> bytes:
    """
    Add fade-in effect to audio.
    
    Args:
        audio_bytes: Audio data in bytes
        duration_ms: Fade-in duration in milliseconds
        
    Returns:
        Audio with fade-in effect
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    if duration_ms < 0:
        raise ValueError("Fade duration must be non-negative")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        faded = audio.fade_in(duration_ms)
        
        # Export to bytes
        output = io.BytesIO()
        faded.export(output, format="mp3", bitrate="128k")
        
        logger.debug("Added %d ms fade-in to audio", duration_ms)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Fade-in failed: %s", str(e))
        raise ValueError(f"Failed to add fade-in: {str(e)}") from e


def add_fade_out(audio_bytes: bytes, duration_ms: int = 2000) -> bytes:
    """
    Add fade-out effect to audio.
    
    Args:
        audio_bytes: Audio data in bytes
        duration_ms: Fade-out duration in milliseconds
        
    Returns:
        Audio with fade-out effect
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    if duration_ms < 0:
        raise ValueError("Fade duration must be non-negative")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        faded = audio.fade_out(duration_ms)
        
        # Export to bytes
        output = io.BytesIO()
        faded.export(output, format="mp3", bitrate="128k")
        
        logger.debug("Added %d ms fade-out to audio", duration_ms)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Fade-out failed: %s", str(e))
        raise ValueError(f"Failed to add fade-out: {str(e)}") from e


def adjust_speed(audio_bytes: bytes, speed_factor: float) -> bytes:
    """
    Adjust audio playback speed.
    
    Args:
        audio_bytes: Audio data in bytes
        speed_factor: Speed multiplier (0.5 = half speed, 2.0 = double speed)
        
    Returns:
        Speed-adjusted audio bytes
        
    Raises:
        ValueError: If parameters are invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    if speed_factor <= 0:
        raise ValueError("Speed factor must be greater than 0")
    
    if not 0.25 <= speed_factor <= 4.0:
        raise ValueError("Speed factor must be between 0.25 and 4.0")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # Speed adjustment via frame rate manipulation
        adjusted = audio.speedup(playback_speed=speed_factor)
        
        # Export to bytes
        output = io.BytesIO()
        adjusted.export(output, format="mp3", bitrate="128k")
        
        logger.debug("Adjusted audio speed: %.2fx", speed_factor)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Speed adjustment failed: %s", str(e))
        raise ValueError(f"Failed to adjust speed: {str(e)}") from e


def get_audio_duration(audio_bytes: bytes) -> float:
    """
    Get duration of audio in seconds.
    
    Args:
        audio_bytes: Audio data in bytes
        
    Returns:
        Duration in seconds
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        duration_seconds = len(audio) / 1000.0  # pydub uses milliseconds
        
        logger.debug("Audio duration: %.2f seconds", duration_seconds)
        return duration_seconds
    
    except Exception as e:
        logger.error("Failed to get audio duration: %s", str(e))
        raise ValueError(f"Failed to get audio duration: {str(e)}") from e


def convert_to_mp3(audio_bytes: bytes, bitrate: str = "128k") -> bytes:
    """
    Convert audio to MP3 format.
    
    Args:
        audio_bytes: Audio data in bytes
        bitrate: MP3 bitrate (e.g., '128k', '192k', '320k')
        
    Returns:
        MP3 audio bytes
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty")
    
    valid_bitrates = ["64k", "128k", "192k", "256k", "320k"]
    if bitrate not in valid_bitrates:
        raise ValueError(f"Bitrate must be one of {valid_bitrates}")
    
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # Export as MP3
        output = io.BytesIO()
        audio.export(output, format="mp3", bitrate=bitrate)
        
        logger.debug("Converted audio to MP3 with bitrate %s", bitrate)
        return output.getvalue()
    
    except Exception as e:
        logger.error("MP3 conversion failed: %s", str(e))
        raise ValueError(f"Failed to convert to MP3: {str(e)}") from e


def mix_audio(foreground: bytes, background: bytes, bg_volume_db: float = -20) -> bytes:
    """
    Mix foreground and background audio.
    
    Args:
        foreground: Foreground audio bytes (e.g., voice)
        background: Background audio bytes (e.g., music)
        bg_volume_db: Background audio volume adjustment in dB
        
    Returns:
        Mixed audio bytes
        
    Raises:
        ValueError: If audio data is invalid
    """
    if not foreground or not background:
        raise ValueError("Both foreground and background audio required")
    
    try:
        fg_audio = AudioSegment.from_file(io.BytesIO(foreground))
        bg_audio = AudioSegment.from_file(io.BytesIO(background))
        
        # Adjust background volume
        if bg_volume_db != 0:
            bg_audio = bg_audio.apply_gain(bg_volume_db)
        
        # Make background match foreground duration
        if len(bg_audio) < len(fg_audio):
            # Loop background audio
            repeats = (len(fg_audio) // len(bg_audio)) + 1
            bg_audio = bg_audio * repeats
        
        # Trim to match foreground length
        bg_audio = bg_audio[:len(fg_audio)]
        
        # Mix (overlay)
        mixed = fg_audio.overlay(bg_audio)
        
        # Export
        output = io.BytesIO()
        mixed.export(output, format="mp3", bitrate="128k")
        
        logger.info("Mixed audio: foreground + background (%.1f dB)",
                   bg_volume_db)
        return output.getvalue()
    
    except Exception as e:
        logger.error("Audio mixing failed: %s", str(e))
        raise ValueError(f"Failed to mix audio: {str(e)}") from e
