"""Generate short voice sample clips for onboarding voice preview.

Creates ~10s MP3 clips for each of the 12 voices (6 EN + 6 HI)
by calling the Chatterbox Modal endpoint.

Output: dreamweaver-web/public/audio/samples/{voice_id}.mp3

Usage:
    python3 scripts/generate_voice_samples.py
"""

import time
from pathlib import Path

import httpx

CHATTERBOX_URL = "https://anmol-71634--dreamweaver-chatterbox-tts.modal.run"
HEALTH_URL = "https://anmol-71634--dreamweaver-chatterbox-health.modal.run"

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent.parent / "dreamweaver-web" / "public" / "audio" / "samples"

# Sample texts — short enough for ~10s audio
SAMPLE_TEXT_EN = (
    "Once upon a time, in a land of twinkling stars and gentle moonlight, "
    "a little cloud floated softly across the sky."
)

SAMPLE_TEXT_HI = (
    "एक समय की बात है, टिमटिमाते सितारों और चाँदनी रात की दुनिया में, "
    "एक छोटा सा बादल आसमान में धीरे-धीरे तैरता था।"
)

# All 12 voices to generate
VOICES = {
    # English voices
    "female_1": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    "female_2": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    "female_3": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    "male_1": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    "male_2": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    "male_3": {"text": SAMPLE_TEXT_EN, "lang": "en"},
    # Hindi voices
    "female_1_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
    "female_2_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
    "female_3_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
    "male_1_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
    "male_2_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
    "male_3_hi": {"text": SAMPLE_TEXT_HI, "lang": "hi"},
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Warm up the container
    print("Warming up Chatterbox...")
    try:
        r = httpx.get(HEALTH_URL, timeout=60)
        print(f"  Health: {r.status_code}")
    except Exception as e:
        print(f"  Health check failed: {e}")

    client = httpx.Client(timeout=120)
    generated = 0

    for voice_id, config in VOICES.items():
        out_path = OUTPUT_DIR / f"{voice_id}.mp3"

        # Skip existing
        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"  [SKIP] {voice_id} (already exists, {out_path.stat().st_size // 1024} KB)")
            continue

        print(f"  Generating {voice_id}...")
        try:
            resp = client.get(
                f"{CHATTERBOX_URL}",
                params={
                    "text": config["text"],
                    "voice": voice_id,
                    "lang": config["lang"],
                    "exaggeration": 0.5,
                    "cfg_weight": 0.4,
                    "format": "mp3",
                },
            )
            resp.raise_for_status()

            out_path.write_bytes(resp.content)
            print(f"  Saved {voice_id}.mp3 ({len(resp.content) // 1024} KB)")
            generated += 1

            # Brief delay between requests
            time.sleep(2)

        except Exception as e:
            print(f"  ERROR generating {voice_id}: {e}")
            continue

    print(f"\nDone! Generated {generated} voice samples in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
