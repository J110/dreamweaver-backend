#!/usr/bin/env python3
"""
Generate unique musicParams for each story using Mistral API.

Each story gets a unique ambient music specification based on its theme,
mood, setting, and content. The params are used by the Web Audio API
engine to create a distinct procedural soundscape per story.

Usage:
    python3 scripts/generate_music_params.py                  # Generate for all stories
    python3 scripts/generate_music_params.py --id gen-xxx     # Specific story
    python3 scripts/generate_music_params.py --dry-run        # Show plan only
    python3 scripts/generate_music_params.py --new-only       # Only stories without musicParams
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from mistralai import Mistral
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-large-latest"

CONTENT_JSON = BASE_DIR / "seed_output" / "content.json"
SEED_DATA_JS = BASE_DIR.parent / "dreamweaver-web" / "src" / "utils" / "seedData.js"

# ── Musical key definitions (common bedtime-friendly keys) ──
KEYS = {
    "C": {"root": 130.81, "notes": [130.81, 146.83, 164.81, 174.61, 196.00, 220.00, 246.94]},
    "Cm": {"root": 130.81, "notes": [130.81, 146.83, 155.56, 174.61, 196.00, 207.65, 233.08]},
    "D": {"root": 146.83, "notes": [146.83, 164.81, 185.00, 196.00, 220.00, 246.94, 277.18]},
    "Dm": {"root": 146.83, "notes": [146.83, 164.81, 174.61, 196.00, 220.00, 233.08, 261.63]},
    "E": {"root": 164.81, "notes": [164.81, 185.00, 207.65, 220.00, 246.94, 277.18, 311.13]},
    "Em": {"root": 82.41, "notes": [82.41, 92.50, 98.00, 110.00, 123.47, 130.81, 146.83]},
    "F": {"root": 174.61, "notes": [174.61, 196.00, 220.00, 233.08, 261.63, 293.66, 329.63]},
    "Fm": {"root": 174.61, "notes": [174.61, 196.00, 207.65, 233.08, 261.63, 277.18, 329.63]},
    "G": {"root": 98.00, "notes": [98.00, 110.00, 123.47, 130.81, 146.83, 164.81, 185.00]},
    "Gm": {"root": 98.00, "notes": [98.00, 110.00, 116.54, 130.81, 146.83, 155.56, 174.61]},
    "A": {"root": 110.00, "notes": [110.00, 123.47, 138.59, 146.83, 164.81, 185.00, 207.65]},
    "Am": {"root": 110.00, "notes": [110.00, 123.47, 130.81, 146.83, 164.81, 174.61, 196.00]},
    "Bb": {"root": 116.54, "notes": [116.54, 130.81, 146.83, 155.56, 174.61, 196.00, 220.00]},
    "Bbm": {"root": 116.54, "notes": [116.54, 130.81, 138.59, 155.56, 174.61, 185.00, 207.65]},
}

# Available event types
EVENT_TYPES = [
    "sparkle", "windGust", "cricket", "frog", "owl", "waterDrop",
    "waveCycle", "starTwinkle", "birdChirp", "whaleCall", "heartbeat",
    "chimes", "leaves", "radarPing",
]

# Pad types
PAD_TYPES = ["fm", "chorus", "resonant", "plucked", "simple"]


def call_mistral(prompt, max_tokens=2000, temperature=0.5, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                wait = (attempt + 1) * 10
                print(f"  [rate-limit, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
            else:
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise
    raise Exception("Max retries exceeded")


def parse_json_response(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON: {text[:300]}")


def generate_music_params_for_story(story, existing_keys_used):
    """Generate unique musicParams for a story using Mistral."""

    # Prepare context
    title = story.get("title", "Untitled")
    theme = story.get("theme", "dreamy")
    description = story.get("description", "")
    content_type = story.get("type", "story")
    target_age = story.get("target_age", 5)
    lang = story.get("lang", "en")

    keys_list = list(KEYS.keys())
    events_list = ", ".join(EVENT_TYPES)
    pads_list = ", ".join(PAD_TYPES)
    already_used = ", ".join(existing_keys_used[-8:]) if existing_keys_used else "none yet"

    prompt = f"""You are a music director creating a unique ambient soundscape for a children's bedtime {content_type}.

STORY INFO:
- Title: {title}
- Theme: {theme}
- Description: {description}
- Target age: {target_age} years
- Language: {lang}

ALREADY USED KEYS (try to pick a DIFFERENT key): {already_used}

AVAILABLE OPTIONS:
- Musical keys: {', '.join(keys_list)}
- Pad types: {pads_list}
  (fm = warm evolving bells, chorus = lush strings, resonant = organic breathy, plucked = magical kalimba, simple = clean sine)
- Noise types: pink (gentle), brown (deep wind), white (bright hiss)
- Event types: {events_list}

Create a UNIQUE ambient music specification. Consider:
1. The story's mood and setting (e.g., ocean stories → waveCycle events + brown noise)
2. The age group (babies need simpler, slower; teens can have more complexity)
3. VARIETY — don't repeat the same choices for every story

Respond with ONLY a JSON object:
{{
    "key": "<key name from list>",
    "padType": "<pad type>",
    "padGain": <0.03-0.06>,
    "padFilter": <500-1200>,
    "padLfo": <0.03-0.12>,
    "noiseType": "<pink|brown|white>",
    "noiseGain": <0.005-0.02>,
    "droneGain": <0.02-0.05>,
    "melodyInterval": <2500-5000>,
    "melodyGain": <0.012-0.025>,
    "bassInterval": <4000-8000>,
    "counterInterval": <3500-6000>,
    "events": [
        {{"type": "<event>", "interval": <5000-25000>}},
        {{"type": "<event>", "interval": <3000-20000>}},
        {{"type": "<event>", "interval": <8000-30000>}}
    ]
}}

Pick 2-4 events that match the story's setting. Use intervals that create a calm, non-busy atmosphere."""

    raw = call_mistral(prompt, max_tokens=800, temperature=0.7)
    result = parse_json_response(raw)

    # Validate and enrich with actual note frequencies
    key_name = result.get("key", "Am")
    if key_name not in KEYS:
        key_name = "Am"

    key_data = KEYS[key_name]
    notes = key_data["notes"]
    root = key_data["root"]

    # Build the full musicParams object
    params = {
        "key": key_name,
        "chordNotes": [notes[0], notes[2], notes[4], notes[0] * 2],  # I-III-V-I(octave)
        "padType": result.get("padType", "chorus"),
        "padGain": max(0.02, min(0.07, result.get("padGain", 0.045))),
        "padFilter": max(400, min(1500, result.get("padFilter", 800))),
        "padLfo": max(0.02, min(0.15, result.get("padLfo", 0.06))),
        "noiseType": result.get("noiseType", "pink"),
        "noiseGain": max(0.003, min(0.025, result.get("noiseGain", 0.01))),
        "droneFreq": round(root / 2, 2),
        "droneGain": max(0.015, min(0.06, result.get("droneGain", 0.035))),
        "melodyNotes": [round(n * 2, 2) for n in [notes[0], notes[2], notes[4], notes[3]]],
        "melodyInterval": max(2000, min(6000, result.get("melodyInterval", 3500))),
        "melodyGain": max(0.008, min(0.03, result.get("melodyGain", 0.018))),
        "bassNotes": [round(root / 2, 2), round(notes[4] / 2, 2), round(notes[2] / 2, 2)],
        "bassInterval": max(3000, min(10000, result.get("bassInterval", 6000))),
        "counterNotes": [round(n * 2.5, 2) for n in [notes[2], notes[4], notes[0]]],
        "counterInterval": max(3000, min(8000, result.get("counterInterval", 4500))),
        "events": [],
    }

    # Validate events
    raw_events = result.get("events", [])
    for evt in raw_events[:4]:  # max 4 events
        if isinstance(evt, dict) and evt.get("type") in EVENT_TYPES:
            params["events"].append({
                "type": evt["type"],
                "interval": max(3000, min(30000, evt.get("interval", 10000))),
            })

    # Ensure at least 2 events
    if len(params["events"]) < 2:
        defaults = {"ocean": ["waveCycle", "waterDrop"], "nature": ["windGust", "leaves"],
                     "animals": ["cricket", "owl"], "space": ["starTwinkle", "radarPing"],
                     "fantasy": ["sparkle", "chimes"], "adventure": ["windGust", "birdChirp"],
                     "bedtime": ["heartbeat", "chimes"], "friendship": ["sparkle", "birdChirp"],
                     "family": ["heartbeat", "chimes"], "science": ["radarPing", "sparkle"]}
        fallback = defaults.get(theme, ["sparkle", "windGust"])
        for evt_type in fallback:
            if not any(e["type"] == evt_type for e in params["events"]):
                params["events"].append({"type": evt_type, "interval": 12000})

    return params, key_name


def update_seed_data_music_params(story_id, music_params):
    """Add musicParams field to a story in seedData.js."""
    if not SEED_DATA_JS.exists():
        print(f"  WARNING: seedData.js not found")
        return False

    content = SEED_DATA_JS.read_text(encoding="utf-8")
    escaped_id = re.escape(story_id)

    # Find the musicProfile line for this story and add musicParams after it
    # Pattern: find story block, look for musicProfile: "xxx", add musicParams after
    pattern = rf'(id:\s*"{escaped_id}".*?musicProfile:\s*"[^"]*")'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        # Insert musicParams right after musicProfile line
        insert_point = match.end()
        params_json = json.dumps(music_params)
        # Check if musicParams already exists
        next_chunk = content[insert_point:insert_point + 200]
        if "musicParams:" in next_chunk:
            # Replace existing musicParams
            mp_match = re.search(r',\s*musicParams:\s*\{[^}]*(?:\{[^}]*\}[^}]*)*\}', next_chunk)
            if mp_match:
                end_pos = insert_point + mp_match.end()
                new_content = content[:insert_point] + f",\n      musicParams: {params_json}" + content[end_pos:]
                SEED_DATA_JS.write_text(new_content, encoding="utf-8")
                return True
        new_content = content[:insert_point] + f",\n      musicParams: {params_json}" + content[insert_point:]
        SEED_DATA_JS.write_text(new_content, encoding="utf-8")
        return True
    else:
        print(f"  WARNING: Could not find musicProfile for {story_id} in seedData.js")
        return False


def run():
    parser = argparse.ArgumentParser(description="Generate unique musicParams per story")
    parser.add_argument("--id", help="Generate for specific story ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--new-only", action="store_true", help="Only stories without musicParams")
    args = parser.parse_args()

    with open(CONTENT_JSON, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    # Select stories to process
    stories = all_content
    if args.id:
        stories = [s for s in stories if s["id"] == args.id]
    if args.new_only:
        stories = [s for s in stories if not s.get("musicParams")]

    print(f"\n{'='*60}")
    print(f"  MUSIC PARAMS GENERATION")
    print(f"  Stories: {len(stories)}")
    print(f"  API: Mistral ({MODEL})")
    print(f"{'='*60}\n")

    keys_used = []

    for i, story in enumerate(stories):
        print(f"[{i+1}/{len(stories)}] {story['title']} ({story.get('theme', '?')}, {story.get('lang', '?')})")

        if args.dry_run:
            continue

        try:
            params, key_name = generate_music_params_for_story(story, keys_used)
            keys_used.append(key_name)

            # Update content.json
            idx = next(j for j, s in enumerate(all_content) if s["id"] == story["id"])
            all_content[idx]["musicParams"] = params

            # Update seedData.js
            update_seed_data_music_params(story["id"], params)

            print(f"  Key: {key_name}, Pad: {params['padType']}, Events: {[e['type'] for e in params['events']]}")
            time.sleep(2)  # Rate limit buffer

        except Exception as e:
            print(f"  ERROR: {e}")

    if not args.dry_run:
        with open(CONTENT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_content, f, ensure_ascii=False, indent=2)
        print(f"\nSaved to {CONTENT_JSON}")


if __name__ == "__main__":
    run()
