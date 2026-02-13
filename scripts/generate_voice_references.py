"""Generate voice reference WAV files using edge-tts.

These reference files are used by Chatterbox TTS for zero-shot voice cloning.
Each file should be ~10 seconds of clean speech in the character of the voice.

Usage:
    pip install edge-tts
    python scripts/generate_voice_references.py
"""

import asyncio
import os
from pathlib import Path

VOICE_REFERENCES_DIR = Path(__file__).parent.parent / "voice_references"

# Map each DreamWeaver voice to an edge-tts neural voice and a sample text
# that captures the personality of the voice
VOICE_CONFIGS = {
    "luna": {
        "edge_voice": "en-US-JennyNeural",
        "text": (
            "Come, little one, let me tell you a story. "
            "Close your eyes and imagine a world where the stars whisper secrets "
            "and the moon sings gentle lullabies. "
            "In this magical place, everything is soft and warm, "
            "and dreams float like feathers in the breeze."
        ),
    },
    "atlas": {
        "edge_voice": "en-US-GuyNeural",
        "text": (
            "Gather round, everyone, for tonight I have a tale to share. "
            "It is a story of courage and kindness, "
            "of a young hero who discovered that the greatest treasure "
            "was not gold or jewels, but the friends made along the way. "
            "Let us begin this adventure together."
        ),
    },
    "aria": {
        "edge_voice": "en-US-AriaNeural",
        "text": (
            "Oh, you will not believe what happened today! "
            "There was this tiny little bunny, right, "
            "and it found a magical garden with flowers that could talk! "
            "And the sunflower said, hello there, little bunny, "
            "would you like to play? It was so exciting!"
        ),
    },
    "cosmo": {
        "edge_voice": "en-US-DavisNeural",
        "text": (
            "Alright, explorers, are you ready for an adventure? "
            "Today we are going to discover a hidden cave "
            "behind the biggest waterfall in the enchanted forest. "
            "Legend says there is a friendly dragon inside "
            "who loves telling riddles and sharing cookies."
        ),
    },
    "whisper": {
        "edge_voice": "en-US-EmmaNeural",
        "text": (
            "Shh, everything is peaceful now. "
            "The world is quiet, and the night wraps around you like a cozy blanket. "
            "Breathe in slowly, breathe out gently. "
            "You are safe, you are loved, and all is well. "
            "Let the stillness carry you to dreamland."
        ),
    },
    "melody": {
        "edge_voice": "en-US-EmmaNeural",
        "text": (
            "Twinkle, twinkle, little star, how I wonder what you are. "
            "Up above the world so high, like a diamond in the sky. "
            "La la la, the night is young, "
            "and the sweetest songs are sung "
            "by the moonlight, soft and bright."
        ),
    },
}


async def generate_reference(voice_id: str, config: dict) -> None:
    """Generate a single voice reference WAV file."""
    import edge_tts

    output_path = VOICE_REFERENCES_DIR / f"{voice_id}.wav"

    print(f"Generating {voice_id} ({config['edge_voice']})...")

    communicate = edge_tts.Communicate(
        text=config["text"],
        voice=config["edge_voice"],
        rate="-10%",
        pitch="+0Hz",
    )
    # edge-tts outputs MP3 by default, save as mp3 first then note for user
    mp3_path = VOICE_REFERENCES_DIR / f"{voice_id}.mp3"
    await communicate.save(str(mp3_path))

    # Convert MP3 to WAV using pydub if available
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_mp3(str(mp3_path))
        audio = audio.set_frame_rate(24000).set_channels(1)
        audio.export(str(output_path), format="wav")
        mp3_path.unlink()
        print(f"  Saved: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    except ImportError:
        # Keep MP3 if pydub not available
        print(f"  Saved as MP3 (pydub not available for WAV conversion): {mp3_path}")


async def main():
    VOICE_REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {VOICE_REFERENCES_DIR}")
    print(f"Generating {len(VOICE_CONFIGS)} voice references...\n")

    for voice_id, config in VOICE_CONFIGS.items():
        await generate_reference(voice_id, config)

    print("\nDone! Voice reference files generated.")
    print("These files are used by Chatterbox TTS for zero-shot voice cloning.")


if __name__ == "__main__":
    asyncio.run(main())
