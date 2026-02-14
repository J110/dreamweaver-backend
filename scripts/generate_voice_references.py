"""Generate voice reference WAV files for Chatterbox TTS zero-shot voice cloning.

Uses Kokoro TTS (local, 24kHz native) for English voices and edge-tts for Hindi.
Each reference should be ~10-20 seconds of clean speech in the character of the voice.

Voice Characters:
  gentle     — Female calm storyteller (default)
  whisper    — Female whispering / ASMR-like
  warm       — Male warm gentle narrator
  whisper_m  — Male whispering
  musical    — Female musical / rhythmic
  musical_m  — Male musical / rhythmic
  child      — Child voice (unisex)

Each has English + Hindi variants (e.g., gentle, gentle_hi).

Usage:
    pip install kokoro soundfile edge-tts pydub
    brew install espeak-ng   # macOS (Kokoro dependency)
    python scripts/generate_voice_references.py [--force]
"""

import asyncio
import os
import sys
from pathlib import Path

VOICE_REFERENCES_DIR = Path(__file__).parent.parent / "voice_references"

# ─────────────────────────────────────────────────────────────────────────────
# ENGLISH VOICE CONFIGS — Generated via Kokoro TTS (local, 24kHz, high quality)
# ─────────────────────────────────────────────────────────────────────────────
KOKORO_VOICE_CONFIGS = {
    "gentle": {
        "kokoro_voice": "af_heart",  # A-grade female, warm and natural
        "speed": 0.85,
        "text": (
            "Come, little one, let me tell you a story. "
            "Close your eyes and imagine a world where the stars whisper secrets "
            "and the moon sings gentle lullabies. "
            "In this magical place, everything is soft and warm, "
            "and dreams float like feathers in the breeze. "
            "The clouds are made of cotton candy, and the rivers flow with honey."
        ),
    },
    "whisper": {
        "kokoro_voice": "af_sky",  # Softer, quieter female voice
        "speed": 0.72,  # Very slow for whispery ASMR feel
        "text": (
            "Shh, everything is peaceful now. "
            "The world is quiet, and the night wraps around you like a cozy blanket. "
            "Breathe in slowly, breathe out gently. "
            "You are safe, you are loved, and all is well. "
            "Let the stillness carry you to dreamland. "
            "Close your eyes and feel the warmth."
        ),
    },
    "warm": {
        "kokoro_voice": "am_fenrir",  # Best male voice (C+ grade)
        "speed": 0.85,
        "text": (
            "Gather round, everyone, for tonight I have a tale to share. "
            "It is a story of courage and kindness, "
            "of a young hero who discovered that the greatest treasure "
            "was not gold or jewels, but the friends made along the way. "
            "Let us begin this adventure together. "
            "Are you comfortable? Good. Then let us start."
        ),
    },
    "whisper_m": {
        "kokoro_voice": "am_michael",  # Natural-sounding male
        "speed": 0.72,  # Very slow for whispery feel
        "text": (
            "The night is calm and still. "
            "Listen to the gentle rustle of leaves outside your window. "
            "Everything is quiet, everything is at peace. "
            "Let your thoughts drift away like clouds on a summer day. "
            "You are safe here. Rest now. "
            "Tomorrow is a new adventure."
        ),
    },
    "musical": {
        "kokoro_voice": "af_bella",  # A- grade female, rich and expressive
        "speed": 0.88,
        "text": (
            "Twinkle, twinkle, little star, how I wonder what you are. "
            "Up above the world so high, like a diamond in the sky. "
            "La la la, the night is young, "
            "and the sweetest songs are sung "
            "by the moonlight, soft and bright. "
            "Hush now, little one, and dream of starlight."
        ),
    },
    "musical_m": {
        "kokoro_voice": "am_puck",  # Expressive male voice
        "speed": 0.88,
        "text": (
            "Row, row, row your boat, gently down the stream. "
            "Merrily, merrily, merrily, merrily, life is but a dream. "
            "The river sings a melody as it flows through the valley. "
            "And the birds join in, chirping along in harmony. "
            "What a beautiful song the world makes when we listen."
        ),
    },
    "child": {
        "kokoro_voice": "bf_emma",  # British female, younger-sounding (B- grade)
        "speed": 0.95,  # Slightly faster for childlike energy
        "text": (
            "Oh, you will not believe what happened today! "
            "There was this tiny little bunny, right, "
            "and it found a magical garden with flowers that could talk! "
            "And the sunflower said, hello there, little bunny, "
            "would you like to play? It was so exciting! "
            "I wish I could visit that garden too!"
        ),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# HINDI VOICE CONFIGS — Generated via edge-tts (Kokoro Hindi is not production-ready)
# ─────────────────────────────────────────────────────────────────────────────
EDGE_HINDI_CONFIGS = {
    "gentle_hi": {
        "edge_voice": "hi-IN-SwaraNeural",
        "rate": "-10%",
        "text": (
            "आओ बच्चों, आज मैं तुम्हें एक कहानी सुनाती हूँ। "
            "अपनी आँखें बंद करो और सोचो एक ऐसी दुनिया जहाँ तारे फुसफुसाते हैं "
            "और चाँद मीठी लोरियाँ गाता है। "
            "इस जादुई जगह में सब कुछ नरम और गरम है, "
            "और सपने हवा में पंखों की तरह तैरते हैं।"
        ),
    },
    "whisper_hi": {
        "edge_voice": "hi-IN-SwaraNeural",
        "rate": "-20%",  # Slower, calmer for whisper character
        "text": (
            "शश्श, सब शांत है अब। "
            "रात का आसमान तारों से भरा है और दुनिया सो रही है। "
            "धीरे से साँस लो, आराम से। "
            "तुम सुरक्षित हो, तुम्हें प्यार किया जाता है। "
            "चलो, सपनों की दुनिया में चलते हैं।"
        ),
    },
    "warm_hi": {
        "edge_voice": "hi-IN-MadhurNeural",
        "rate": "-10%",
        "text": (
            "सुनो बच्चों, आज की कहानी बहुत खास है। "
            "यह एक बहादुर बच्चे की कहानी है "
            "जिसने सीखा कि सबसे बड़ा खज़ाना सोना या हीरे नहीं, "
            "बल्कि रास्ते में बने दोस्त होते हैं। "
            "चलो, इस रोमांचक सफ़र पर साथ चलते हैं।"
        ),
    },
    "whisper_m_hi": {
        "edge_voice": "hi-IN-MadhurNeural",
        "rate": "-20%",  # Slower for whispery male
        "text": (
            "रात गहरी हो गई है, और सब सो रहे हैं। "
            "बाहर चाँदनी चमक रही है और हवा धीरे-धीरे बह रही है। "
            "तुम भी आराम करो, अपनी आँखें बंद करो। "
            "सब ठीक है, कल एक नया दिन होगा। "
            "अब सपनों की दुनिया में जाओ।"
        ),
    },
    "musical_hi": {
        "edge_voice": "hi-IN-SwaraNeural",
        "rate": "-5%",
        "text": (
            "चंदा मामा दूर के, पुए पकाएँ बूर के। "
            "आप खाएँ थाली में, मुन्ने को दें प्याली में। "
            "ला ला ला, रात जवान है, "
            "और मीठे गीत गाए जा रहे हैं, "
            "चाँदनी में नरम और उजली।"
        ),
    },
    "musical_m_hi": {
        "edge_voice": "hi-IN-MadhurNeural",
        "rate": "-5%",
        "text": (
            "मछली जल की रानी है, जीवन उसका पानी है। "
            "हाथ लगाओ डर जाएगी, बाहर निकालो मर जाएगी। "
            "नदी गाती है एक धुन जैसे बहती है घाटी से। "
            "और पंछी साथ देते हैं, गुनगुनाते हुए सुर में।"
        ),
    },
    "child_hi": {
        "edge_voice": "hi-IN-SwaraNeural",  # Using female voice with faster rate for child-like quality
        "rate": "+5%",  # Slightly faster for childlike energy
        "pitch": "+10Hz",  # Slightly higher pitch
        "text": (
            "अरे, आज क्या हुआ पता है? "
            "एक छोटा सा खरगोश था ना, "
            "उसे एक जादुई बगीचा मिला जहाँ फूल बात करते थे! "
            "और सूरजमुखी ने कहा, नमस्ते छोटे खरगोश, "
            "क्या तुम खेलना चाहोगे? बहुत मज़ा आया!"
        ),
    },
}


def generate_kokoro_reference(voice_id: str, config: dict, force: bool = False) -> None:
    """Generate a voice reference WAV using Kokoro TTS (local, 24kHz)."""
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    output_path = VOICE_REFERENCES_DIR / f"{voice_id}.wav"

    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        print(f"Skipping {voice_id} (WAV already exists)")
        return

    kokoro_voice = config["kokoro_voice"]
    speed = config.get("speed", 0.85)
    text = config["text"]

    print(f"Generating {voice_id} (Kokoro: {kokoro_voice}, speed={speed})...")

    pipeline = KPipeline(lang_code="a")  # American English
    generator = pipeline(text, voice=kokoro_voice, speed=speed)

    audio_chunks = []
    for gs, ps, audio in generator:
        audio_chunks.append(audio)

    if not audio_chunks:
        print(f"  ERROR: No audio generated for {voice_id}")
        return

    full_audio = np.concatenate(audio_chunks)
    sf.write(str(output_path), full_audio, 24000)

    duration = len(full_audio) / 24000
    size_kb = output_path.stat().st_size / 1024
    print(f"  Saved WAV: {output_path} ({size_kb:.0f} KB, {duration:.1f}s)")

    # Also save MP3 backup for Modal upload compatibility
    try:
        from pydub import AudioSegment
        import io

        # Load the WAV we just wrote
        audio_seg = AudioSegment.from_wav(str(output_path))
        mp3_path = VOICE_REFERENCES_DIR / f"{voice_id}.mp3"
        audio_seg.export(str(mp3_path), format="mp3", bitrate="192k")
        print(f"  Saved MP3: {mp3_path} ({mp3_path.stat().st_size / 1024:.0f} KB)")
    except Exception as e:
        print(f"  MP3 backup skipped: {e}")


async def generate_edge_reference(voice_id: str, config: dict, force: bool = False) -> None:
    """Generate a voice reference WAV using edge-tts (for Hindi)."""
    import edge_tts

    output_path = VOICE_REFERENCES_DIR / f"{voice_id}.wav"

    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        print(f"Skipping {voice_id} (WAV already exists)")
        return

    print(f"Generating {voice_id} (edge-tts: {config['edge_voice']})...")

    communicate = edge_tts.Communicate(
        text=config["text"],
        voice=config["edge_voice"],
        rate=config.get("rate", "-10%"),
        pitch=config.get("pitch", "+0Hz"),
    )

    mp3_path = VOICE_REFERENCES_DIR / f"{voice_id}.tmp.mp3"
    await communicate.save(str(mp3_path))

    # Convert MP3 to WAV (24kHz mono 16-bit PCM)
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_mp3(str(mp3_path))
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        audio.export(str(output_path), format="wav")

        mp3_final = VOICE_REFERENCES_DIR / f"{voice_id}.mp3"
        audio.export(str(mp3_final), format="mp3", bitrate="192k")

        mp3_path.unlink()
        print(f"  Saved WAV: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
        print(f"  Saved MP3: {mp3_final} ({mp3_final.stat().st_size / 1024:.0f} KB)")
    except Exception as e:
        import shutil
        final_mp3 = VOICE_REFERENCES_DIR / f"{voice_id}.mp3"
        shutil.move(str(mp3_path), str(final_mp3))
        print(f"  Saved as MP3 (WAV conversion skipped: {e}): {final_mp3}")


async def main():
    force = "--force" in sys.argv

    VOICE_REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

    total_en = len(KOKORO_VOICE_CONFIGS)
    total_hi = len(EDGE_HINDI_CONFIGS)
    print(f"Output directory: {VOICE_REFERENCES_DIR}")
    print(f"Generating {total_en + total_hi} voice references ({total_en} EN via Kokoro + {total_hi} HI via edge-tts)...")
    if force:
        print("Force mode: regenerating all references\n")
    else:
        print("(use --force to regenerate existing files)\n")

    # Generate English voices with Kokoro (synchronous)
    print("=== English voices (Kokoro TTS) ===")
    for voice_id, config in KOKORO_VOICE_CONFIGS.items():
        generate_kokoro_reference(voice_id, config, force=force)

    # Generate Hindi voices with edge-tts (async)
    print("\n=== Hindi voices (edge-tts) ===")
    for voice_id, config in EDGE_HINDI_CONFIGS.items():
        await generate_edge_reference(voice_id, config, force=force)

    print("\nDone! Voice reference files generated.")
    print("These files are used by Chatterbox TTS for zero-shot voice cloning.")
    print("\nVoice Characters:")
    print("  gentle / gentle_hi      — Female calm storyteller (default)")
    print("  whisper / whisper_hi     — Female whispering")
    print("  warm / warm_hi           — Male warm narrator")
    print("  whisper_m / whisper_m_hi — Male whispering")
    print("  musical / musical_hi     — Female musical/rhythmic")
    print("  musical_m / musical_m_hi — Male musical/rhythmic")
    print("  child / child_hi         — Child voice")
    print("\nTo upload to Modal volume:")
    print("  modal volume put chatterbox-data voice_references/ /voices/ --force")


if __name__ == "__main__":
    asyncio.run(main())
