#!/usr/bin/env python3
"""
Generate test lullabies via YuE Modal endpoint.
Spec 1: Quality test — generate 2 lullabies (heartbeat + rocking), publish for evaluation.

Usage:
    python scripts/generate_test_lullabies.py
    python scripts/generate_test_lullabies.py --types heartbeat rocking
    python scripts/generate_test_lullabies.py --types heartbeat  # single type
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# ── Output directory ─────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "seed_output" / "lullabies"

# ── Per-type MiniMax style prompts ───────────────────────────────────
LULLABY_STYLE_PROMPTS = {
    "heartbeat": (
        "Solo female vocal lullaby, humming only, no instruments, "
        "no melody variation, sustained warm tones, 58 BPM, "
        "extremely intimate, breathy, mouth-closed humming, "
        "monotone drone, like breathing set to pitch, "
        "meditative, hypnotic, the simplest possible sound, "
        "no percussion, no rhythm section, pure voice"
    ),
    "permission": (
        "Gentle folk lullaby, warm female vocal, "
        "fingerpicked acoustic guitar, 64 BPM, "
        "pastoral, settling, peaceful, evening atmosphere, "
        "descending melody phrases, each verse quieter, "
        "conversational singing, nature imagery, "
        "the world going to sleep"
    ),
    "shield": (
        "Protective lullaby, warm female vocal, low register, "
        "simple piano chords, 62 BPM, "
        "steady, certain, grounded, reassuring, "
        "no vibrato, direct delivery, "
        "like a spoken promise set to a simple melody, "
        "minimal melodic movement, unwavering, "
        "the voice is solid and present"
    ),
    "closing": (
        "Intimate domestic lullaby, warm female vocal, "
        "soft acoustic guitar, 64 BPM, "
        "cozy, familiar, conversational, "
        "almost speaking melodically, not performative, "
        "kitchen-to-bedroom energy, "
        "the gentlest folk song, end of day warmth"
    ),
    "rocking": (
        "Traditional cradle song, warm maternal female vocal, "
        "harp arpeggios, 6/8 time signature, 64 BPM, "
        "swaying rocking rhythm, gentle lilting motion, "
        "the feeling of being carried and rocked, "
        "celtic lullaby influence, soft vibrato, "
        "repetitive swinging pattern"
    ),
    "counting": (
        "Children's counting lullaby, clear sweet female vocal, "
        "xylophone and music box, 66 BPM, "
        "simple repetitive melody, same tune every line, "
        "cumulative nursery rhyme structure, "
        "bright but soft, childlike, innocent, "
        "extremely predictable rhythm"
    ),
    "parent_song": (
        "Intimate singer-songwriter lullaby, "
        "breathy unpolished female vocal, low register, "
        "sparse solo piano with single notes, 60 BPM, "
        "vulnerable, tender, raw, emotional, "
        "like singing alone late at night, "
        "not a performance, imperfect and real, "
        "long pauses between phrases, extreme sparsity"
    ),
    "warning": (
        "Playful mysterious lullaby, warm female vocal, "
        "soft woodwind and low flute, 64 BPM, "
        "mischievous, conspiratorial, whimsical, "
        "fairy tale energy, like sharing a secret, "
        "mysterious but gentle and never dark, "
        "storytelling melody with a hint of smile"
    ),
    "origin": (
        "Ancient storytelling lullaby, warm resonant female vocal, "
        "singing bowl and soft cello drone, 60 BPM, "
        "mythological, vast, reverent, timeless, "
        "the voice of someone very old and very kind, "
        "starts spacious and narrows to intimate, "
        "wonder without weight"
    ),
}

# ── Test lyrics (from spec) ─────────────────────────────────────────
LULLABY_LYRICS = {
    "heartbeat": """\
[verse]
Mmm mmm mmm mmm
La la la la
Mmm mmm mmm mmm
Shh shh shh shh

[verse]
Mmm mmm mmm mmm
La la la la
Mmm mmm mmm mmm
La la la la

[verse]
Mmm mmm mmm
La la la
Mmm mmm
La la
Mmm""",

    "rocking": """\
[verse]
Rock-a-bye, rock-a-bye
Rock-a-bye over the sea
Rock-a-bye rock-a-bye
Come back to me
Sailing on moonlight rocking on air
Rock-a-bye rock-a-bye I'll meet you there

[chorus]
Sway and sway and sway and sleep
Sway and sway and sway and sleep

[verse]
Rock-a-bye rock-a-bye into the night
Rock-a-bye rock-a-bye hold on tight
Carried by starlight drifting so slow
Rock-a-bye rock-a-bye let yourself go

[chorus]
Sway and sway and sway and sleep
Sway and sway and sway and sleep
Rock-a-bye goodnight""",

    "permission": """\
[verse]
The world is going to sleep now
The birds have tucked their wings away
The river stopped its song
The flowers closed their petals soft
The wind has moved along

[chorus]
Sleep now, sleep now
Everything is sleeping too
Sleep now, sleep now
The world is dreaming just like you

[verse]
The moon is watching quietly
The stars have dimmed their light
The trees have stopped their whispering
The whole world says goodnight

[chorus]
Sleep now, sleep now
Everything is sleeping too
Sleep now, sleep now
And so can you""",

    "shield": """\
[verse]
I am here
The walls are strong the door is shut
The blanket wrapped around
And nothing from the dark outside
Can make a single sound

[chorus]
I am here, I am here
Nothing going to come
I am here, I am here
You are safe at home

[verse]
The shadows are just shapes that play
They cannot touch they cannot stay
And every sound you hear tonight
Is just the house that holds you tight

[chorus]
I am here, I am here
Nothing going to come
I am here, I am here
I am still here""",

    "closing": """\
[verse]
What a day, what a day
The dishes are all washed and stacked
Your shoes are by the door
The bath is done the teeth are brushed
You don't need anything more

[chorus]
The day is done the day is done
There's nothing left to do
The day is done the day is done
Tomorrow's waiting too

[verse]
You laughed today you played today
You ran until you stopped
You ate your food you told a joke
The day was really a lot

[chorus]
The day is done the day is done
There's nothing left to do
The day is done the day is done
And the day is done""",

    "counting": """\
[verse]
One little owl closed her eyes

[verse]
One little owl closed her eyes
Two little fish stopped their swim

[verse]
One little owl closed her eyes
Two little fish stopped their swim
Three little clouds stood very still

[verse]
One little owl closed her eyes
Two little fish stopped their swim
Three little clouds stood very still
Four little flowers felt the chill
And that was all""",

    "parent_song": """\
[verse]
I watched you today
I watched you sleeping once before
When you were very new
Your hand was wrapped around my thumb
And I just looked at you

[chorus]
You won't remember this
And that's okay
I'll remember for us both
At the end of every day

[verse]
You're bigger now your shoes have laces
Your stories have beginnings
And I'm still here beside your bed
Just watching just listening

[chorus]
You won't remember this
And that's okay
I'll remember for us both
And I'll be here tomorrow""",

    "warning": """\
[verse]
The dreams are out tonight
They're choosing who to visit
They only come to sleeping eyes
If you're awake you'll miss it

[chorus]
Close your eyes and they will come
The ones with wings the ones that run
But if you're up they'll fly right past
Close your eyes close your eyes fast

[verse]
Last night a dream about a ship
Sailed past an open window
It would have taken you on board
But you were still awake though

[chorus]
Close your eyes and they will come
The ones with wings the ones that run
Better close your eyes""",

    "origin": """\
[verse]
Long before you were born
Before there were dreams the night was just dark
And no one knew why they would sleep
Until a small star fell out of the sky
And cracked open soft warm and deep

[chorus]
And that was the first dream
The very first one
It taught all the others
How dreaming is done

[verse]
It floated through windows of every house
And showed the sleeping world things
Mountains that talked and oceans that sang
And fish that had feathery wings

[chorus]
And that was the first dream
The very first one
And it's still true tonight""",
}

# ── Card metadata ────────────────────────────────────────────────────
CARD_META = {
    "heartbeat": {
        "title": "Humming",
        "card_subtitle": "Just a gentle hum",
        "age_group": "0-1",
        "mood": "calm",
    },
    "permission": {
        "title": "The World Sleeps",
        "card_subtitle": "Everything is going to sleep",
        "age_group": "2-5",
        "mood": "calm",
    },
    "shield": {
        "title": "You Are Safe",
        "card_subtitle": "A song about being protected",
        "age_group": "2-5",
        "mood": "anxious",
    },
    "closing": {
        "title": "Day Is Done",
        "card_subtitle": "Wrapping up today",
        "age_group": "6-8",
        "mood": "calm",
    },
    "rocking": {
        "title": "Rock-a-bye",
        "card_subtitle": "A classic cradle song",
        "age_group": "0-1",
        "mood": "calm",
    },
    "counting": {
        "title": "One by One",
        "card_subtitle": "Counting things to sleep",
        "age_group": "2-5",
        "mood": "wired",
    },
    "parent_song": {
        "title": "For You",
        "card_subtitle": "A parent's love",
        "age_group": "6-8",
        "mood": "sad",
    },
    "warning": {
        "title": "Dream Catcher",
        "card_subtitle": "The dreams are waiting",
        "age_group": "6-8",
        "mood": "curious",
    },
    "origin": {
        "title": "How Dreams Began",
        "card_subtitle": "Where dreams come from",
        "age_group": "9-12",
        "mood": "curious",
    },
}


def generate_lullaby_minimax(lullaby_type: str) -> bytes:
    """Generate a lullaby via MiniMax Music on Replicate. Returns MP3 bytes."""
    import replicate
    import httpx

    style_prompt = LULLABY_STYLE_PROMPTS[lullaby_type]
    lyrics = LULLABY_LYRICS[lullaby_type]

    print(f"  Calling MiniMax Music 1.5 on Replicate...")
    print(f"  Style: {style_prompt[:80]}...")
    start = time.time()

    output = replicate.run(
        "minimax/music-1.5",
        input={
            "prompt": style_prompt,
            "lyrics": lyrics,
        },
    )

    if not output:
        raise RuntimeError("No output from MiniMax")

    audio_url = str(output)
    print(f"  Got audio URL, downloading...")
    resp = httpx.get(audio_url, timeout=120, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 1000:
        raise RuntimeError(f"Download failed ({resp.status_code}, {len(resp.content)} bytes)")

    audio_bytes = resp.content
    elapsed = time.time() - start
    print(f"  Got {len(audio_bytes):,} bytes in {elapsed:.0f}s")
    return audio_bytes


def generate_cover_placeholder(lullaby_type: str) -> None:
    """Generate a placeholder SVG cover (real FLUX covers come later)."""
    meta = CARD_META[lullaby_type]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#1a1a3e"/>
      <stop offset="100%" stop-color="#0d0d1a"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <circle cx="256" cy="200" r="60" fill="#2a2a5e" opacity="0.5">
    <animate attributeName="r" values="58;62;58" dur="4s" repeatCount="indefinite"/>
  </circle>
  <circle cx="256" cy="200" r="30" fill="#3a3a7e" opacity="0.4">
    <animate attributeName="r" values="28;32;28" dur="3s" repeatCount="indefinite"/>
  </circle>
  <text x="256" y="350" text-anchor="middle" fill="#8888bb" font-family="Georgia" font-size="28">{meta['title']}</text>
  <text x="256" y="385" text-anchor="middle" fill="#6666aa" font-family="Georgia" font-size="16">{meta['card_subtitle']}</text>
</svg>"""
    svg_path = OUTPUT_DIR / f"{lullaby_type}-test-001_cover.svg"
    svg_path.write_text(svg)
    print(f"  Cover: {svg_path.name}")


def create_metadata(lullaby_type: str, duration_seconds: int) -> dict:
    """Create lullaby JSON metadata."""
    meta = CARD_META[lullaby_type]
    lullaby_id = f"{lullaby_type}-test-001"
    return {
        "id": lullaby_id,
        "title": meta["title"],
        "lullaby_type": lullaby_type,
        "card_label": meta["title"],
        "card_subtitle": meta["card_subtitle"],
        "age_group": meta["age_group"],
        "mood": meta["mood"],
        "language": "en",
        "audio_file": f"{lullaby_id}.mp3",
        "cover_file": f"{lullaby_id}_cover.svg",
        "duration_seconds": duration_seconds,
        "lyrics": LULLABY_LYRICS[lullaby_type],
        "style_prompt": LULLABY_STYLE_PROMPTS[lullaby_type],
        "engine": "minimax-music-1.5",
        "created_at": str(date.today()),
        "is_test": True,
    }


def get_audio_duration(mp3_path: Path) -> int:
    """Get duration of MP3 file in seconds."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(str(mp3_path))
        return int(len(audio) / 1000)
    except ImportError:
        # Fallback: estimate from file size (~16kB/s for 128kbps)
        size = mp3_path.stat().st_size
        return max(1, int(size / 16000))


def main():
    parser = argparse.ArgumentParser(description="Generate test lullabies via YuE")
    parser.add_argument(
        "--types", nargs="+",
        default=["heartbeat", "rocking"],
        choices=list(LULLABY_STYLE_PROMPTS.keys()),
        help="Lullaby types to generate (default: heartbeat rocking)",
    )
    parser.add_argument(
        "--skip-audio", action="store_true",
        help="Skip audio generation (only create metadata + covers for existing audio)",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_meta = []

    for ltype in args.types:
        lullaby_id = f"{ltype}-test-001"
        mp3_path = OUTPUT_DIR / f"{lullaby_id}.mp3"

        print(f"\n{'='*60}")
        print(f"Generating: {ltype} — {CARD_META[ltype]['title']}")
        print(f"{'='*60}")

        # 1. Generate audio
        if args.skip_audio and mp3_path.exists():
            print(f"  Skipping audio (--skip-audio, file exists)")
        else:
            audio_bytes = generate_lullaby_minimax(ltype)
            mp3_path.write_bytes(audio_bytes)
            print(f"  Audio: {mp3_path.name} ({mp3_path.stat().st_size:,} bytes)")

        # 2. Generate cover
        generate_cover_placeholder(ltype)

        # 3. Create metadata
        duration = get_audio_duration(mp3_path)
        meta = create_metadata(ltype, duration)
        all_meta.append(meta)

        meta_path = OUTPUT_DIR / f"{lullaby_id}.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        print(f"  Metadata: {meta_path.name} (duration: {duration}s)")

    # Write combined lullabies.json
    index_path = OUTPUT_DIR / "lullabies.json"
    index_path.write_text(json.dumps(all_meta, indent=2))
    print(f"\n{'='*60}")
    print(f"Done! {len(all_meta)} lullabies → {index_path}")
    print(f"{'='*60}")

    for m in all_meta:
        print(f"  [{m['lullaby_type']}] {m['title']} — {m['duration_seconds']}s")


if __name__ == "__main__":
    main()
