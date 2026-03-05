#!/usr/bin/env python3
"""
Generate unique musicParams for each story using Mistral API.

Each story gets a unique ambient music specification based on its theme,
mood, setting, and content. The params are used by the Web Audio API
engine to create a distinct procedural soundscape per story.

v2 — DIVERSITY-ENFORCED:
- Tracks padType, noiseType, events across stories to enforce variety
- Assigns padType via round-robin with theme-appropriate bias
- Adds programmatic jitter so even similar AI outputs sound distinct
- Stronger prompt with explicit constraints against repetition
- Post-generation diversity scoring and re-roll if too similar

Usage:
    python3 scripts/generate_music_params.py                  # Generate for all stories
    python3 scripts/generate_music_params.py --id gen-xxx     # Specific story
    python3 scripts/generate_music_params.py --dry-run        # Show plan only
    python3 scripts/generate_music_params.py --new-only       # Only stories without musicParams
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
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

# Available event types with descriptions for the prompt
EVENT_TYPES = [
    "windGust", "cricket", "frog", "owl", "waterDrop",
    "waveCycle", "birdChirp", "whaleCall", "heartbeat",
    "chimes", "leaves",
]

# Events that should only play during Phase 1 (Capture phase)
PHASE1_ONLY_EVENTS = {"frog", "birdChirp"}

EVENT_DESCRIPTIONS = {
    "windGust": "gentle pink noise breeze — nature, autumn, sky scenes",
    "cricket": "rhythmic high-pitched chirps — nights, fields, calm outdoors",
    "frog": "low croaking pulses — ponds, rain, jungle (Phase 1 only)",
    "owl": "two-tone hoot — deep forests, nighttime wisdom",
    "waterDrop": "single water plop — caves, rain, puddles, calm",
    "waveCycle": "ocean wave wash — beaches, ocean, boats, sea",
    "birdChirp": "quick triple tweet — morning, gardens, meadows (Phase 1 only)",
    "whaleCall": "deep low moan — deep ocean, whale, vast seascapes",
    "heartbeat": "double low thud — comfort, sleep, safety, infant",
    "chimes": "random wind chimes — breeze, gardens, porches, temples",
    "leaves": "light white noise rustle — forests, autumn, trees, wind",
}

# Pad types with descriptions
PAD_TYPES = ["fm", "chorus", "resonant", "plucked", "simple"]
PAD_DESCRIPTIONS = {
    "fm": "warm evolving FM bells — dreamy, cosmic, shimmering, complex",
    "chorus": "lush detuned string pad — warm, rich, enveloping, orchestral",
    "resonant": "organic breathy filtered noise — earthy, raw, nature, forest",
    "plucked": "magical kalimba/harp plucks — fairy, delicate, crystalline, bright",
    "simple": "clean pure sine tones — minimal, gentle, infant, peaceful, lullaby",
}

# ── Theme-to-sound mapping for intelligent assignment ──
THEME_PAD_PREFERENCES = {
    "dreamy":     ["fm", "chorus", "simple"],
    "adventure":  ["fm", "plucked", "chorus"],
    "animals":    ["resonant", "chorus", "plucked"],
    "space":      ["fm", "simple", "chorus"],
    "fantasy":    ["plucked", "fm", "chorus"],
    "fairy_tale": ["plucked", "chorus", "fm"],
    "nature":     ["resonant", "chorus", "simple"],
    "ocean":      ["chorus", "resonant", "simple"],
    "bedtime":    ["simple", "chorus", "fm"],
    "friendship": ["chorus", "plucked", "simple"],
    "family":     ["simple", "chorus", "fm"],
    "science":    ["fm", "simple", "plucked"],
}

THEME_NOISE_PREFERENCES = {
    "dreamy":     ["pink", "brown"],
    "adventure":  ["brown", "pink"],
    "animals":    ["pink", "brown"],
    "space":      ["brown", "pink"],
    "fantasy":    ["pink", "brown"],
    "fairy_tale": ["pink", "brown"],
    "nature":     ["pink", "brown"],
    "ocean":      ["brown", "pink"],
    "bedtime":    ["pink", "brown"],
    "friendship": ["pink", "brown"],
    "family":     ["pink", "brown"],
    "science":    ["brown", "pink"],
}

THEME_EVENT_POOLS = {
    "dreamy":     ["chimes", "windGust", "heartbeat", "owl"],
    "adventure":  ["windGust", "birdChirp", "leaves", "owl", "waterDrop"],
    "animals":    ["cricket", "frog", "owl", "birdChirp", "leaves", "windGust"],
    "space":      ["whaleCall", "heartbeat", "windGust", "chimes"],
    "fantasy":    ["chimes", "windGust", "waterDrop", "birdChirp"],
    "fairy_tale": ["chimes", "birdChirp", "windGust", "leaves"],
    "nature":     ["windGust", "leaves", "birdChirp", "cricket", "waterDrop", "owl"],
    "ocean":      ["waveCycle", "whaleCall", "waterDrop", "windGust"],
    "bedtime":    ["heartbeat", "chimes", "owl", "cricket"],
    "friendship": ["birdChirp", "chimes", "leaves", "windGust"],
    "family":     ["heartbeat", "chimes", "windGust", "owl"],
    "science":    ["waterDrop", "whaleCall", "chimes", "windGust"],
}

# ── v4: Theme → Soundscape + Music Loop mapping ──
THEME_SOUNDSCAPE_MAP = {
    "ocean":      {"soundscapePreset": "ocean",      "musicLoop": "oceanMelody"},
    "animals":    {"soundscapePreset": "forest",     "musicLoop": "forestFlute"},
    "nature":     {"soundscapePreset": "garden",     "musicLoop": "gentleGuitar"},
    "fantasy":    {"soundscapePreset": "starryNight", "musicLoop": "etherealPad"},
    "adventure":  {"soundscapePreset": "wind",       "musicLoop": "gentleGuitar"},
    "space":      {"soundscapePreset": "starryNight", "musicLoop": "cosmicSynth"},
    "bedtime":    {"soundscapePreset": "rain",       "musicLoop": "pianoLullaby"},
    "friendship": {"soundscapePreset": "garden",     "musicLoop": "softStrings"},
    "mystery":    {"soundscapePreset": "forest",     "musicLoop": "nightPiano"},
    "science":    {"soundscapePreset": "river",      "musicLoop": "etherealPad"},
    "family":     {"soundscapePreset": "fireplace",  "musicLoop": "calmHarp"},
    "dreamy":     {"soundscapePreset": "rain",       "musicLoop": "pianoLullaby"},
    "fairy_tale": {"soundscapePreset": "garden",     "musicLoop": "musicBox"},
}
BABY_SOUNDSCAPE = {"soundscapePreset": "heartbeat", "musicLoop": "musicBox"}


def _get_soundscape_preset(theme, target_age=5):
    """Return soundscapePreset + musicLoop for a given theme & age."""
    if target_age <= 1:
        return dict(BABY_SOUNDSCAPE)
    return dict(THEME_SOUNDSCAPE_MAP.get(theme, THEME_SOUNDSCAPE_MAP["bedtime"]))


# ── Diversity tracking ──
class DiversityTracker:
    """Tracks what has been used across all stories to enforce variety."""

    def __init__(self):
        self.keys_used = []
        self.pad_types_used = Counter()
        self.noise_types_used = Counter()
        self.events_used = Counter()
        self.param_ranges = {
            "padGain": [], "padFilter": [], "padLfo": [],
            "noiseGain": [], "droneGain": [],
            "melodyInterval": [], "melodyGain": [],
            "bassInterval": [],
        }

    def record(self, params):
        """Record a generated params set for diversity tracking."""
        self.keys_used.append(params["key"])
        self.pad_types_used[params["padType"]] += 1
        self.noise_types_used[params["noiseType"]] += 1
        for evt in params.get("events", []):
            self.events_used[evt["type"]] += 1
        for k in self.param_ranges:
            if k in params:
                self.param_ranges[k].append(params[k])

    def get_least_used_pad(self, theme):
        """Get the least-used pad type that fits the theme."""
        preferences = THEME_PAD_PREFERENCES.get(theme, PAD_TYPES[:3])
        # Score: lower count = more preferred
        scored = [(p, self.pad_types_used.get(p, 0)) for p in preferences]
        scored.sort(key=lambda x: x[1])
        return scored[0][0]

    def get_least_used_noise(self, theme):
        """Get the least-used noise type that fits the theme."""
        preferences = THEME_NOISE_PREFERENCES.get(theme, ["pink", "brown"])
        scored = [(n, self.noise_types_used.get(n, 0)) for n in preferences]
        scored.sort(key=lambda x: x[1])
        return scored[0][0]

    def get_underrepresented_events(self, theme, count=3):
        """Pick events from the theme pool, preferring underrepresented ones."""
        pool = THEME_EVENT_POOLS.get(theme, EVENT_TYPES[:6])
        scored = [(e, self.events_used.get(e, 0)) for e in pool]
        scored.sort(key=lambda x: x[1])
        # Pick the `count` least used events from the pool
        return [e for e, _ in scored[:count]]

    def get_recently_unused_key(self):
        """Get a key that hasn't been used in the last 6 stories."""
        all_keys = list(KEYS.keys())
        recent = set(self.keys_used[-6:]) if self.keys_used else set()
        unused = [k for k in all_keys if k not in recent]
        if unused:
            return random.choice(unused)
        return random.choice(all_keys)

    def summary(self):
        """Print diversity summary statistics."""
        print(f"\n{'─'*50}")
        print(f"  DIVERSITY REPORT")
        print(f"{'─'*50}")
        print(f"  Pad types:  {dict(self.pad_types_used)}")
        print(f"  Noise types: {dict(self.noise_types_used)}")
        print(f"  Keys used:  {dict(Counter(self.keys_used))}")
        print(f"  Events:     {dict(self.events_used)}")
        for k, vals in self.param_ranges.items():
            if vals:
                print(f"  {k}: min={min(vals):.4f}, max={max(vals):.4f}, range={max(vals)-min(vals):.4f}")
        print(f"{'─'*50}\n")


tracker = DiversityTracker()


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


def add_jitter(value, range_pct=0.15, min_val=None, max_val=None):
    """Add random variation to a numeric value to ensure uniqueness."""
    jitter = value * range_pct * (random.random() * 2 - 1)
    result = value + jitter
    if min_val is not None:
        result = max(min_val, result)
    if max_val is not None:
        result = min(max_val, result)
    return round(result, 4)


def generate_music_params_for_story(story, story_index, total_stories):
    """Generate unique musicParams for a story using Mistral + diversity enforcement."""

    # Prepare context
    title = story.get("title", "Untitled")
    theme = story.get("theme", "dreamy")
    description = story.get("description", "")
    content_type = story.get("type", "story")
    target_age = story.get("target_age", 5)
    lang = story.get("lang", "en")

    # ── PRE-ASSIGN constraints based on diversity tracking ──
    assigned_pad = tracker.get_least_used_pad(theme)
    assigned_noise = tracker.get_least_used_noise(theme)
    suggested_events = tracker.get_underrepresented_events(theme, count=3)
    suggested_key = tracker.get_recently_unused_key()

    # Build event descriptions for prompt
    events_desc = "\n".join(
        f"  - {e}: {EVENT_DESCRIPTIONS[e]}" for e in EVENT_TYPES
    )

    # Recent usage stats for the prompt
    recent_pads = dict(tracker.pad_types_used) if tracker.pad_types_used else "none yet"
    recent_events = dict(tracker.events_used) if tracker.events_used else "none yet"

    prompt = f"""You are an expert ambient music designer creating a UNIQUE soundscape for a children's bedtime {content_type}.
This music accompanies a sleep story — it must help children fall asleep.

STORY:
- Title: "{title}"
- Theme: {theme}
- Description: {description}
- Target age: {target_age} years
- Language: {lang}
- Story #{story_index + 1} of {total_stories}

═══ SLEEP SCIENCE CONSTRAINTS ═══
- NO counter melody (only one melody line allowed)
- NO white noise (only pink or brown)
- NO sparkle, radarPing, or starTwinkle events (too stimulating)
- melodyInterval MINIMUM 4000ms (sparse, meditative)
- bassInterval MINIMUM 5000ms (slow, grounding)
- frog and birdChirp events only play in early part of story

═══ MANDATORY CONSTRAINTS ═══

1. PAD TYPE: You MUST use "{assigned_pad}"
   ({PAD_DESCRIPTIONS[assigned_pad]})

2. NOISE TYPE: You MUST use "{assigned_noise}"

3. SUGGESTED KEY: {suggested_key} (you may pick a different one if it better fits the mood)

4. EVENTS: Choose 2-4 from the catalog below. Try to include at least one from: {', '.join(suggested_events)}

FULL EVENT CATALOG:
{events_desc}

═══ PARAMETER RANGES ═══
Use the FULL range, don't cluster in the middle:
- padGain: 0.025 to 0.065 (lower = subtle/intimate, higher = rich/enveloping)
- padFilter: 400 to 1400 (lower = dark/warm, higher = bright/airy)
- padLfo: 0.02 to 0.14 (lower = still/calm, higher = undulating/breathing)
- noiseGain: 0.003 to 0.022 (lower = hint of texture, higher = prominent atmosphere)
- droneGain: 0.015 to 0.055 (lower = barely there, higher = deep grounding)
- melodyInterval: 4000 to 6000 ms (sparse, meditative — sleep-appropriate)
- melodyGain: 0.008 to 0.028 (lower = whisper melody, higher = clear gentle melody)
- bassInterval: 5000 to 9000 ms (slow, deep, grounding)
- event intervals: 6000 to 28000 ms (vary by event — common sounds more frequent, rare sounds less)

AGE-BASED PERSONALITY:
- Baby (0-1): very slow melodyInterval (5500+), simple, heartbeat/chimes events, low padFilter (400-600)
- Toddler (2-3): gentle, moderate pace (4500-5500), waterDrop/chimes events
- Child (4-5): gentle, moderate (4000-5000), birdChirp/chimes events
- Kid (6-8): calm, slightly more varied (4000-4500), windGust/leaves/cricket events
- Tween (8-12): deeper, owl/whaleCall events, higher padFilter (800-1200)
- Teen (12+): sophisticated, rich, full range

USAGE SO FAR (avoid over-representing):
- Pad types used: {recent_pads}
- Events used: {recent_events}

Respond with ONLY a JSON object (no explanation, no markdown):
{{
    "key": "<key name>",
    "padGain": <number>,
    "padFilter": <number>,
    "padLfo": <number>,
    "noiseGain": <number>,
    "droneGain": <number>,
    "melodyInterval": <number>,
    "melodyGain": <number>,
    "bassInterval": <number>,
    "events": [
        {{"type": "<event>", "interval": <number>}},
        {{"type": "<event>", "interval": <number>}},
        {{"type": "<event>", "interval": <number>}}
    ]
}}"""

    raw = call_mistral(prompt, max_tokens=600, temperature=0.85)
    result = parse_json_response(raw)

    # ── Validate and build params with diversity enforcement ──
    key_name = result.get("key", suggested_key)
    if key_name not in KEYS:
        key_name = suggested_key

    key_data = KEYS[key_name]
    notes = key_data["notes"]
    root = key_data["root"]

    # Use the ASSIGNED pad and noise (not what Mistral picked — it may have ignored the constraint)
    pad_type = assigned_pad
    noise_type = assigned_noise

    # Extract numeric values with jitter for uniqueness
    raw_pad_gain = result.get("padGain", 0.04 + random.random() * 0.02)
    raw_pad_filter = result.get("padFilter", 500 + random.random() * 800)
    raw_pad_lfo = result.get("padLfo", 0.03 + random.random() * 0.09)
    raw_noise_gain = result.get("noiseGain", 0.005 + random.random() * 0.015)
    raw_drone_gain = result.get("droneGain", 0.02 + random.random() * 0.03)
    raw_melody_interval = result.get("melodyInterval", 4000 + random.random() * 2000)
    raw_melody_gain = result.get("melodyGain", 0.01 + random.random() * 0.015)
    raw_bass_interval = result.get("bassInterval", 5000 + random.random() * 4000)

    # Apply jitter to ensure uniqueness even with similar AI outputs
    params = {
        "key": key_name,
        "chordNotes": [notes[0], notes[2], notes[4], notes[0] * 2],  # I-III-V-I(octave)
        "padType": pad_type,
        "padGain": add_jitter(raw_pad_gain, 0.12, 0.025, 0.065),
        "padFilter": round(add_jitter(raw_pad_filter, 0.10, 400, 1400)),
        "padLfo": add_jitter(raw_pad_lfo, 0.15, 0.02, 0.14),
        "noiseType": noise_type,
        "noiseGain": add_jitter(raw_noise_gain, 0.12, 0.003, 0.022),
        "droneFreq": round(root / 2, 2),
        "droneGain": add_jitter(raw_drone_gain, 0.12, 0.015, 0.055),
        "melodyNotes": [round(n * 2, 2) for n in [notes[0], notes[2], notes[4], notes[3]]],
        "melodyInterval": round(add_jitter(raw_melody_interval, 0.10, 4000, 6000)),
        "melodyGain": add_jitter(raw_melody_gain, 0.12, 0.008, 0.028),
        "bassNotes": [round(root / 2, 2), round(notes[4] / 2, 2), round(notes[2] / 2, 2)],
        "bassInterval": round(add_jitter(raw_bass_interval, 0.10, 5000, 9000)),
        "counterMelody": False,
        "events": [],
    }

    # ── Validate events with diversity enforcement ──
    raw_events = result.get("events", [])
    seen_event_types = set()

    for evt in raw_events[:4]:
        if isinstance(evt, dict) and evt.get("type") in EVENT_TYPES:
            evt_type = evt["type"]
            if evt_type not in seen_event_types:
                interval = evt.get("interval", 10000)
                interval = round(add_jitter(interval, 0.15, 6000, 28000))
                event_entry = {"type": evt_type, "interval": interval}
                if evt_type in PHASE1_ONLY_EVENTS:
                    event_entry["phases"] = [1]
                params["events"].append(event_entry)
                seen_event_types.add(evt_type)

    # Ensure at least 2 events, using suggested underrepresented ones
    while len(params["events"]) < 2:
        for evt_type in suggested_events:
            if evt_type not in seen_event_types:
                params["events"].append({
                    "type": evt_type,
                    "interval": 8000 + round(random.random() * 12000),
                })
                seen_event_types.add(evt_type)
                if len(params["events"]) >= 2:
                    break

    # Last resort fallback
    if len(params["events"]) < 2:
        fallback_pool = [e for e in EVENT_TYPES if e not in seen_event_types]
        for evt_type in fallback_pool[:2]:
            params["events"].append({
                "type": evt_type,
                "interval": 10000 + round(random.random() * 10000),
            })

    # v4: Add soundscape and music loop presets based on theme
    params.update(_get_soundscape_preset(theme, target_age))

    # Validate sleep constraints
    params = validate_sleep_params(params)

    # Derive phase 2/3 and build v2 output
    output = build_v2_output(params)

    # Record in diversity tracker (use phase1 flat params)
    tracker.record(params)

    return output, key_name


BANNED_EVENTS = {"sparkle", "radarPing", "starTwinkle"}


def validate_sleep_params(params):
    """Safety net: enforce sleep science constraints after generation."""
    # Clamp melody interval
    if params["melodyInterval"] < 4000:
        params["melodyInterval"] = 4000
    # Clamp bass interval
    if params["bassInterval"] < 5000:
        params["bassInterval"] = 5000
    # No white noise
    if params.get("noiseType") not in ("pink", "brown"):
        params["noiseType"] = "pink"
    # No counter melody
    params["counterMelody"] = False
    # Remove banned events
    params["events"] = [
        e for e in params["events"]
        if e["type"] not in BANNED_EVENTS
    ]
    # Clamp event intervals
    for evt in params["events"]:
        if evt["interval"] < 6000:
            evt["interval"] = 6000
    return params


def build_v2_output(phase1_params):
    """Build v2 output with phase1/phase2/phase3 derived from Phase 1 params."""
    p1 = dict(phase1_params)

    # Extract top-level fields that aren't per-phase
    soundscape = p1.pop("soundscapePreset", "rain")
    music_loop = p1.pop("musicLoop", "pianoLullaby")
    counter_melody = p1.pop("counterMelody", False)

    # ── Phase 2 (Descent): reduce melody, warm filter, stretch intervals ──
    p2 = dict(p1)
    p2["padGain"] = round(p1["padGain"] * 0.8, 4)
    p2["melodyGain"] = round(p1["melodyGain"] * 0.5, 4)
    p2["noiseGain"] = round(p1["noiseGain"] * 1.2, 4)
    p2["melodyInterval"] = round(p1["melodyInterval"] * 1.4)
    p2["bassInterval"] = round(p1["bassInterval"] * 1.3)
    p2["padFilter"] = round(p1["padFilter"] * 0.7)
    # Simplify chords: root + fifth only
    if len(p1["chordNotes"]) >= 3:
        p2["chordNotes"] = [p1["chordNotes"][0], p1["chordNotes"][2]]
    # Remove phase-1-only events, stretch remaining intervals
    p2["events"] = []
    for evt in p1["events"]:
        if evt["type"] not in PHASE1_ONLY_EVENTS:
            p2["events"].append({
                "type": evt["type"],
                "interval": round(evt["interval"] * 1.5),
            })

    # ── Phase 3 (Sleep): near-silent, no melody, no events ──
    p3 = dict(p1)
    p3["padGain"] = round(p1["padGain"] * 0.5, 4)
    p3["melodyGain"] = 0
    p3["noiseGain"] = round(p1["noiseGain"] * 1.5, 4)
    p3["droneGain"] = round(p1["droneGain"] * 0.6, 4)
    p3["padFilter"] = round(p1["padFilter"] * 0.4)
    p3["padType"] = "simple"
    # Root note only
    if len(p1["chordNotes"]) >= 1:
        p3["chordNotes"] = [p1["chordNotes"][0]]
    p3["events"] = []

    return {
        "version": 2,
        "counterMelody": counter_melody,
        "soundscapePreset": soundscape,
        "musicLoop": music_loop,
        "phase1": p1,
        "phase2": p2,
        "phase3": p3,
        "masterLowpass": {"1": 8000, "2": 4000, "3": 2000},
        "transitions": {
            "1to2": {"duration": 30},
            "2to3": {"duration": 45},
        },
    }


def update_seed_data_music_params(story_id, music_params):
    """Add musicParams field to a story in seedData.js."""
    if not SEED_DATA_JS.exists():
        print(f"  WARNING: seedData.js not found")
        return False

    content = SEED_DATA_JS.read_text(encoding="utf-8")
    escaped_id = re.escape(story_id)

    # Find the musicProfile line for this story and add musicParams after it
    pattern = rf'(id:\s*"{escaped_id}".*?musicProfile:\s*"[^"]*")'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        insert_point = match.end()
        params_json = json.dumps(music_params)
        # Check if musicParams already exists
        next_chunk = content[insert_point:insert_point + 500]
        if "musicParams:" in next_chunk:
            # Replace existing musicParams — need to match the entire nested object
            # The musicParams object may contain nested arrays/objects, so use a more robust pattern
            mp_match = re.search(
                r',\s*musicParams:\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})',
                next_chunk
            )
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
    parser = argparse.ArgumentParser(description="Generate unique musicParams per story (v2 diversity-enforced)")
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

    # Shuffle to avoid alphabetical bias in diversity assignment
    # But use a fixed seed so results are reproducible
    story_order = list(enumerate(stories))
    random.seed(42)
    random.shuffle(story_order)

    print(f"\n{'='*60}")
    print(f"  MUSIC PARAMS GENERATION v2 (Diversity-Enforced)")
    print(f"  Stories: {len(stories)}")
    print(f"  API: Mistral ({MODEL})")
    print(f"  Pad types: {', '.join(PAD_TYPES)}")
    print(f"  Target distribution: ~{len(stories)//5}-{len(stories)//5+1} stories per pad type")
    print(f"{'='*60}\n")

    results = {}
    total = len(story_order)

    for proc_idx, (orig_idx, story) in enumerate(story_order):
        print(f"[{proc_idx+1}/{total}] {story['title']} ({story.get('theme', '?')}, {story.get('lang', '?')}, age {story.get('target_age', '?')})")

        if args.dry_run:
            assigned_pad = tracker.get_least_used_pad(story.get("theme", "dreamy"))
            print(f"  → Would assign: pad={assigned_pad}, noise={tracker.get_least_used_noise(story.get('theme', 'dreamy'))}")
            # Still record a mock to keep diversity tracking accurate for dry-run
            tracker.pad_types_used[assigned_pad] += 1
            continue

        try:
            params, key_name = generate_music_params_for_story(story, proc_idx, total)
            results[story["id"]] = params

            p1 = params.get("phase1", params)
            print(f"  ✓ Key: {key_name}, Pad: {p1['padType']}, Noise: {p1['noiseType']}, "
                  f"Filter: {p1['padFilter']}, MelodyInt: {p1['melodyInterval']}")
            print(f"    Events: {[e['type'] for e in p1['events']]}")
            if params.get("version") == 2:
                print(f"    v2: phase2 melGain={params['phase2']['melodyGain']}, phase3 melGain={params['phase3']['melodyGain']}")

            time.sleep(2)  # Rate limit buffer

        except Exception as e:
            print(f"  ✗ ERROR: {e}")

    # Now apply results to all_content in original order
    if not args.dry_run:
        updated_count = 0
        for story in all_content:
            if story["id"] in results:
                story["musicParams"] = results[story["id"]]
                # Update seedData.js
                update_seed_data_music_params(story["id"], results[story["id"]])
                updated_count += 1

        with open(CONTENT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_content, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Updated {updated_count} stories in {CONTENT_JSON}")

    # Print diversity report
    tracker.summary()


if __name__ == "__main__":
    run()
