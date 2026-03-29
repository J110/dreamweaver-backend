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

# ── YuE Modal endpoint ──────────────────────────────────────────────
YUE_ENDPOINT = "https://mohan-32314--dreamweaver-yue-generate-song.modal.run"

# ── Output directory ─────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "seed_output" / "lullabies"

# ── Per-type YuE configs ────────────────────────────────────────────
LULLABY_TYPE_CONFIGS = {
    "heartbeat": {
        "temperature":        0.7,
        "top_p":              0.80,
        "repetition_penalty": 1.0,     # NO penalty — pure repetition IS the point
        "max_new_tokens":     2000,    # ~20s per segment
        "num_segments":       2,       # 2 × 20s = ~40s (reduced for test)
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, drone, ambient, minimalist, "
            "no instruments, vocal only, a cappella, "
            "meditative, hypnotic, primal, extremely calm, "
            "female, breathy, warm, humming, mouth-closed, intimate, low register, "
            "58 BPM, no melody variation, sustained tones, "
            "monotone, like breathing set to pitch"
        ),
    },
    "rocking": {
        "temperature":        0.75,
        "top_p":              0.85,
        "repetition_penalty": 1.0,     # NO penalty — rocking repeats
        "max_new_tokens":     2500,
        "num_segments":       2,       # 2 × 25s = ~50s (reduced for test)
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, cradle song, folk, traditional, "
            "harp arpeggios, "
            "gentle, swaying, rocking, warm, safe, "
            "female, warm, clear, maternal, mid-register, soft vibrato, "
            "6/8 time signature, 64 BPM, swinging rocking rhythm, "
            "lilting, the feeling of being carried, celtic lullaby influence"
        ),
    },
    "permission": {
        "temperature":        0.85,
        "top_p":              0.90,
        "repetition_penalty": 1.05,
        "max_new_tokens":     3000,
        "num_segments":       3,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, pastoral, folk, nature, "
            "fingerpicked acoustic guitar, "
            "settling, peaceful, descending, evening, "
            "female, warm, clear, gentle, mid-register, conversational singing, "
            "64 BPM, descending melody phrases, each verse lower energy, "
            "pastoral, like describing a landscape getting quieter"
        ),
    },
    "shield": {
        "temperature":        0.8,
        "top_p":              0.85,
        "repetition_penalty": 1.02,
        "max_new_tokens":     2500,
        "num_segments":       2,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, protective, grounded, "
            "simple piano chords, "
            "certain, steady, reassuring, unwavering, safe, "
            "female, warm, low register, steady, no vibrato, direct, "
            "like a spoken promise set to simple melody, "
            "62 BPM, minimal melodic movement, grounded, "
            "the voice is a wall not a river"
        ),
    },
    "closing": {
        "temperature":        0.85,
        "top_p":              0.90,
        "repetition_penalty": 1.05,
        "max_new_tokens":     3000,
        "num_segments":       3,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, intimate, folk, domestic, "
            "soft acoustic guitar, "
            "cozy, familiar, wrapping up, warm, domestic, "
            "female, warm, conversational, almost speaking melodically, "
            "intimate, like talking to someone in the next pillow, "
            "64 BPM, kitchen-to-bedroom energy, not performative, "
            "the gentlest folk song, a parent voice at the end of the day"
        ),
    },
    "counting": {
        "temperature":        0.8,
        "top_p":              0.88,
        "repetition_penalty": 1.02,
        "max_new_tokens":     2000,
        "num_segments":       4,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, nursery rhyme, children's, counting song, "
            "xylophone, music box, "
            "simple, repetitive, innocent, predictable, bright but soft, "
            "female, clear, childlike, sweet, high-mid register, simple, "
            "66 BPM, same melody every line, cumulative structure, "
            "music box quality, extremely predictable rhythm"
        ),
    },
    "parent_song": {
        "temperature":        0.85,
        "top_p":              0.90,
        "repetition_penalty": 1.05,
        "max_new_tokens":     2000,
        "num_segments":       2,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, singer-songwriter, intimate, folk, "
            "sparse solo piano, single notes, "
            "vulnerable, tender, raw, emotional, real, "
            "female, breathy, unpolished, slightly rough, intimate, low register, "
            "like singing alone late at night, not performing, "
            "60 BPM, extreme sparsity, long pauses, "
            "piano plays maybe one chord per bar, "
            "the voice carries everything, imperfect is better than polished"
        ),
    },
    "warning": {
        "temperature":        0.9,
        "top_p":              0.93,
        "repetition_penalty": 1.08,
        "max_new_tokens":     2500,
        "num_segments":       2,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, fairy tale, playful, mysterious, "
            "soft woodwind, low flute, "
            "mischievous, conspiratorial, mysterious but gentle, whimsical, "
            "female, warm, slightly playful, mid-register, a hint of smile, "
            "like sharing a secret, "
            "64 BPM, fairy tale energy, storytelling melody, "
            "mysterious but never dark"
        ),
    },
    "origin": {
        "temperature":        0.9,
        "top_p":              0.93,
        "repetition_penalty": 1.1,
        "max_new_tokens":     3000,
        "num_segments":       3,
        "stage2_batch_size":  4,
        "genre": (
            "lullaby, mythological, ancient, storytelling, "
            "singing bowl, soft cello drone, "
            "vast, reverent, ancient, wonder, timeless, "
            "female, warm, resonant, low-mid register, slight reverb quality, "
            "the voice of someone very old telling a very old story, "
            "60 BPM, starts spacious and vast, narrows to intimate, "
            "singing bowl sustain underneath, mythological gravity but not heavy"
        ),
    },
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


def generate_lullaby_via_modal(lullaby_type: str) -> bytes:
    """Call YuE Modal function to generate a lullaby. Returns MP3 bytes."""
    import modal

    config = LULLABY_TYPE_CONFIGS[lullaby_type]
    lyrics = LULLABY_LYRICS[lullaby_type]

    # Look up the deployed Modal function
    generate_song = modal.Function.from_name("dreamweaver-yue", "generate_song")

    print(f"  Calling YuE via Modal SDK... (this may take 2-8 min on first call)")
    print(f"  Params: temp={config['temperature']}, top_p={config['top_p']}, "
          f"rep_penalty={config['repetition_penalty']}, "
          f"segments={config['num_segments']}, tokens={config['max_new_tokens']}")
    start = time.time()
    audio_bytes = generate_song.remote(
        genre_description=config["genre"],
        lyrics=lyrics,
        num_segments=config["num_segments"],
        max_new_tokens=config["max_new_tokens"],
        stage2_batch_size=config["stage2_batch_size"],
        temperature=config["temperature"],
        top_p=config["top_p"],
        repetition_penalty=config["repetition_penalty"],
    )
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
        "genre_description": LULLABY_TYPE_CONFIGS[lullaby_type]["genre"],
        "yue_params": {
            "temperature": LULLABY_TYPE_CONFIGS[lullaby_type]["temperature"],
            "top_p": LULLABY_TYPE_CONFIGS[lullaby_type]["top_p"],
            "repetition_penalty": LULLABY_TYPE_CONFIGS[lullaby_type]["repetition_penalty"],
            "max_new_tokens": LULLABY_TYPE_CONFIGS[lullaby_type]["max_new_tokens"],
            "num_segments": LULLABY_TYPE_CONFIGS[lullaby_type]["num_segments"],
        },
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
        choices=list(LULLABY_TYPE_CONFIGS.keys()),
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
            audio_bytes = generate_lullaby_via_modal(ltype)
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
