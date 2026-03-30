#!/usr/bin/env python3
"""Generate missing mood bed WAV files via CassetteAI.

Only generates beds that don't already exist in audio/story_music/.
Intros and outros are pre-generated via the candidate selection process.

Usage:
    python3 scripts/generate_mood_beds.py           # Generate missing beds
    python3 scripts/generate_mood_beds.py --force    # Regenerate all beds
"""
import io, os, time, argparse
from pathlib import Path
import httpx
from pydub import AudioSegment
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

FAL_KEY = os.getenv("FAL_KEY", "")
MUSIC_DIR = BASE_DIR / "audio" / "story_music"
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

MOODS = ["wired", "curious", "calm", "sad", "anxious", "angry"]

MOOD_BEDS = {
    "wired": "3 minute ambient background for children's bedtime story, light pizzicato and soft xylophone, very quiet, minimal, gentle repeating pattern, 70 BPM, playful but settling, the kind of music you feel more than hear",
    "curious": "3 minute ambient background for children's bedtime story, soft celesta and gentle harp, very quiet, minimal, occasional single notes with lots of space, 65 BPM, wondering, exploratory but calm",
    "calm": "3 minute ambient background for children's bedtime story, soft music box and gentle harp, very quiet, extremely minimal, same 3-4 notes repeating slowly with long pauses, 55 BPM, warm, peaceful, almost not there",
    "sad": "3 minute ambient background for children's bedtime story, solo piano, very quiet, minimal, single notes with long decay, 50 BPM, tender, warm not depressing",
    "anxious": "3 minute ambient background for children's bedtime story, soft low strings and gentle harp, very quiet, starts slightly uncertain then settles into warmth, 55 BPM, reassuring, safe",
    "angry": "3 minute ambient background for children's bedtime story, low warm cello drone, very quiet, grounding, steady single notes, no variation, 55 BPM, firm then softening, deep warmth",
}


def generate_cassetteai(prompt: str, duration: int) -> AudioSegment:
    """Generate audio via CassetteAI on fal.ai."""
    endpoint = "cassetteai/music-generator"
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    client = httpx.Client(timeout=300)

    resp = client.post(
        f"https://queue.fal.run/{endpoint}",
        headers=headers,
        json={"prompt": prompt, "duration": duration},
    )
    data = resp.json()
    if "request_id" not in data:
        raise RuntimeError(f"CassetteAI submit failed: {data}")

    rid = data["request_id"]
    start = time.time()
    while True:
        time.sleep(4)
        sr = client.get(
            f"https://queue.fal.run/{endpoint}/requests/{rid}/status",
            headers=headers,
        ).json()
        status = sr.get("status")
        elapsed = time.time() - start
        print(f"    [{elapsed:.0f}s] {status}")
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"CassetteAI failed: {sr}")
        if elapsed > 600:
            raise RuntimeError("Timeout after 10 minutes")

    result = client.get(
        f"https://queue.fal.run/{endpoint}/requests/{rid}",
        headers=headers,
    ).json()

    audio_url = None
    for key in ("audio_file", "audio", "output"):
        if key in result:
            v = result[key]
            audio_url = v.get("url") if isinstance(v, dict) else v
            if audio_url:
                break
    if not audio_url:
        raise RuntimeError(f"No audio URL: {list(result.keys())}")

    audio_data = client.get(audio_url).content
    return AudioSegment.from_file(io.BytesIO(audio_data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Regenerate all beds")
    parser.add_argument("--mood", choices=MOODS, help="Generate bed for specific mood only")
    args = parser.parse_args()

    moods = [args.mood] if args.mood else MOODS

    for mood in moods:
        path = MUSIC_DIR / f"bed_{mood}.wav"
        if path.exists() and not args.force:
            print(f"  {mood}: cached ({path.name}, {path.stat().st_size / 1024:.0f} KB)")
            continue

        prompt = MOOD_BEDS[mood]
        print(f"\n  Generating bed_{mood}.wav via CassetteAI (180s)...")
        print(f"  Prompt: {prompt[:80]}...")

        seg = generate_cassetteai(prompt, 180)
        seg.export(str(path), format="wav")
        dur = len(seg) / 1000.0
        print(f"  bed_{mood}.wav ({dur:.0f}s, {path.stat().st_size / 1024:.0f} KB)")

    print("\nDone! All mood beds in audio/story_music/")


if __name__ == "__main__":
    main()
