#!/usr/bin/env python3
"""
Generate ONE experimental short story (150-300 words) using the new strategy.

Simplified stories with repeated phrases, direct address,
short sentences designed to be heard in bed with eyes closing.

Publishes through the normal pipeline: content.json → seedData.js → audio → cover.

Usage:
    python3 scripts/generate_short_story_experiment.py
"""

import io
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment
from mistralai import Mistral
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"

# ── Test story config: Calm × Nature × 2-5 ───────────────────────────
MOOD = "calm"
STORY_TYPE = "nature"
AGE_GROUP = "2-5"

# ── Prompt from the spec ─────────────────────────────────────────────

EXPERIMENTAL_SHORT_STORY_PROMPT = """
Write a BEDTIME STORY for ages {age_group}.
Mood: {mood}
Story type: {story_type}

THIS IS NOT A LITERARY STORY. This is a story designed to be
HEARD IN BED with eyes closing. Simple enough that a sleepy
child follows every word. Engaging enough that they WANT to
listen tomorrow.

=== LENGTH ===
150-300 words. NO LONGER. If you write more, you have too
many concepts. Cut until only one remains.

=== ONE CONCEPT ===
{mood_concept}

ONE character does ONE thing. No subplot, no secondary
characters (unless fable — then exactly two), no thematic
layers, no stated lessons.

=== THE REPEATED PHRASE ===
Create ONE phrase that appears at least 3 times in the story.
This is the most important element. By the third time, the
child is saying it before the narrator.

The phrase should feel natural to the story type:
- Nature: a sensory observation that keeps returning

GOOD phrases: "Not yet... not yet." / "And the wind carried
it away." / "Same as always." / "But the fox just smiled." /
"One more, just one more." / "Quieter now."

BAD phrases: anything over 8 words, "The end", "Goodnight"
(too generic).

=== DIRECT ADDRESS ===
Include 2-3 moments where the narrator speaks DIRECTLY to
the child.

{direct_address_instructions}

=== STORY STRUCTURE ===

Opening: {story_type_opening}

The story gets SIMPLER toward the end. Not more complex.
Sentences shorten. Details fade. The world gets quieter.
The last 3-4 sentences should be fragments — almost words.

Final line mirrors sleep: the character closes eyes, stops
moving, or goes quiet. The character IS the child.

Closing: {story_type_closing}

=== SENTENCES ===
- 5-10 words per sentence for ages 2-5
- Concrete, sensory — things you see, hear, feel
- No abstract concepts
- No metaphors
- Written for the EAR, not the page

=== OUTPUT FORMAT ===
Return ONLY valid JSON with these fields:

{{
  "title": "the most evocative IMAGE from the story, under 6 words",
  "hook": "one sentence that makes the child want to listen, under 15 words",
  "cover_desc": "abstract minimal visual — one shape, one light, one gradient. NO characters, NO animals. The FEELING of the story as deep blues and warm golds. One sentence.",
  "repeated_phrase": "the exact phrase that repeats 3+ times",
  "description": "one sentence describing the story",
  "text": "the full story text, flowing prose, 150-300 words",
  "character": {{
    "name": "character name",
    "identity": "what the character is",
    "special": "one special trait",
    "personality_tags": ["gentle", "quiet"]
  }},
  "categories": ["Nature", "Bedtime"],
  "morals": []
}}

Do NOT include [MUSIC] tags or any other markup in the text.
Just write flowing prose.
"""

MUSICAL_BRIEF_PROMPT = """You are a music director for a children's bedtime story app.

Given this story, generate a Musical Brief — a compact creative direction
for background ambient music composed by a browser-side synthesizer.

STORY:
Title: {title}
Mood: {mood}
Age group: {age_group}
Text (excerpt): {text_excerpt}

Return ONLY valid JSON:

{{
  "storyId": "{story_id}",
  "ageGroup": "{age_group}",
  "musicalIdentity": {{
    "culturalReference": "one of: celtic, japanese, african, nordic, indian, middle_eastern, latin, chinese, ambient_electronic, music_box, orchestral, folk_acoustic",
    "primaryLoop": "one of: harp_arpeggios, koto_plucks, kalimba_melody, singing_bowl_rings, cello_sustains, hang_drum_melody, guitar_fingerpick, music_box_melody, flute_breathy, marimba_soft, dulcimer_gentle, piano_lullaby",
    "padCharacter": "one of: warm_strings, crystal_air, deep_ocean, forest_hum, starfield, earth_drone, silk_veil, cave_resonance"
  }},
  "tonality": {{
    "mode": "one of: major_pentatonic, minor_pentatonic, dorian, mixolydian, aeolian",
    "rootNote": "one of: C, D, Eb, E, F, G, A, Bb"
  }},
  "melodicCharacter": "one of: descending_lullaby, cycling_arpeggio, drone_with_ornaments",
  "rhythm": {{
    "feel": "gentle_pulse",
    "baseTempo": 58
  }},
  "environment": {{
    "natureSoundPrimary": "one of: wind_gentle, rain_soft, forest_night, ocean_distant, creek",
    "natureSoundSecondary": "one of: distant_thunder, distant_stream, wind_chimes, none",
    "ambientEvents": ["pick 2-3 from: chimes, cricket, owl, leaves, waterDrop, heartbeat, starTwinkle, birdChirp"]
  }},
  "emotionalArc": {{
    "phase1": "one of: gentle_wonder, whimsical_wonder, curious_wonder",
    "phase2": "one of: soft_floating, warm_guidance, gentle_excitement, soothing_flow",
    "phase3": "deep_stillness"
  }}
}}

For a CALM mood ages 2-5: tempo 55-62 BPM, warm simple instruments, phase3 = deep_stillness.
"""


def call_mistral(prompt: str, max_tokens: int = 2000) -> str:
    """Call Mistral API and return response text."""
    client = Mistral(api_key=MISTRAL_API_KEY)
    for attempt in range(3):
        try:
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": "You are a creative bedtime story generator. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
                response_format={"type": "json_object"},
            )
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"  Mistral attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Mistral API failed after retries")


def parse_json(text: str) -> dict:
    """Parse JSON from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
    raise ValueError(f"Could not parse JSON: {text[:200]}")


def generate_tts(text: str, voice: str, exaggeration: float = 0.5,
                 cfg_weight: float = 0.4, speed: float = 0.88) -> bytes:
    """Call Chatterbox TTS and return WAV bytes."""
    params = {
        "text": text,
        "voice": voice,
        "lang": "en",
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "speed": speed,
        "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"

    with httpx.Client() as client:
        for attempt in range(3):
            try:
                print(f"    TTS: voice={voice}, attempt {attempt+1}...")
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return resp.content
                print(f"    TTS {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"    TTS error: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}")


def generate_cover_svg(story_id: str) -> str:
    """Generate a simple animated SVG cover for calm/nature mood."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1a1a3e"/>
      <stop offset="50%" stop-color="#2d2d6b"/>
      <stop offset="100%" stop-color="#0d0d2b"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="45%" r="35%">
      <stop offset="0%" stop-color="#ffd700" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#ffd700" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <ellipse cx="256" cy="230" rx="180" ry="160" fill="url(#glow)">
    <animate attributeName="rx" values="180;195;180" dur="8s" repeatCount="indefinite"/>
    <animate attributeName="ry" values="160;175;160" dur="8s" repeatCount="indefinite"/>
  </ellipse>
  <circle cx="180" cy="200" r="2" fill="#ffd700" opacity="0.4">
    <animate attributeName="cy" values="200;180;200" dur="6s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.7;0.4" dur="6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="330" cy="250" r="1.5" fill="#ffd700" opacity="0.3">
    <animate attributeName="cy" values="250;230;250" dur="7s" repeatCount="indefinite"/>
  </circle>
  <circle cx="256" cy="180" r="2.5" fill="#e8d5a3" opacity="0.25">
    <animate attributeName="cy" values="180;160;180" dur="9s" repeatCount="indefinite"/>
  </circle>
  <circle cx="200" cy="300" r="1.8" fill="#ffd700" opacity="0.2">
    <animate attributeName="cy" values="300;280;300" dur="5s" repeatCount="indefinite"/>
  </circle>
  <circle cx="310" cy="170" r="1.2" fill="#e8d5a3" opacity="0.35">
    <animate attributeName="cy" values="170;155;170" dur="8s" repeatCount="indefinite"/>
  </circle>
</svg>"""


def main():
    story_id = f"gen-{uuid.uuid4().hex[:12]}"
    short_id = story_id[:8]
    print(f"\n{'='*60}")
    print(f"Experimental Short Story Generator")
    print(f"ID: {story_id}  |  {MOOD} × {STORY_TYPE} × {AGE_GROUP}")
    print(f"{'='*60}\n")

    # ── 1. Generate story text ───────────────────────────────────────
    print("[1/5] Generating story text via Mistral...")
    prompt = EXPERIMENTAL_SHORT_STORY_PROMPT.format(
        age_group=AGE_GROUP,
        mood=MOOD,
        story_type=STORY_TYPE,
        mood_concept=(
            "ONE slow observation. Almost nothing happens. The character "
            "is already at peace. They notice something quiet. "
            "The noticing IS the story."
        ),
        direct_address_instructions=(
            "Ages 2-5: Simple SENSORY invitations.\n"
            "  'Can you hear how quiet it is? ...That quiet.'\n"
            "  'Shhh... listen... did you hear that?'\n"
            "  'Do you know what he said? ...He said goodnight.'\n"
            "  'Close your eyes for a second. Can you see it?'"
        ),
        story_type_opening="Did you know that {natural wonder}?",
        story_type_closing="And right now, somewhere, {wonder is still happening}.",
    )

    raw = call_mistral(prompt)
    story = parse_json(raw)

    title = story["title"]
    text = story["text"]
    description = story.get("description", "")
    hook = story.get("hook", "")
    repeated_phrase = story.get("repeated_phrase", "")
    cover_desc = story.get("cover_desc", "")
    character = story.get("character", {})
    categories = story.get("categories", ["Nature", "Bedtime"])

    word_count = len(text.split())
    print(f"  Title: {title}")
    print(f"  Hook: {hook}")
    print(f"  Phrase: \"{repeated_phrase}\"")
    print(f"  Words: {word_count}")
    print()

    # ── 2. Generate audio variants ───────────────────────────────────
    print("[2/5] Generating audio via Chatterbox TTS...")
    voices = ["female_1", "female_2", "female_3", "male_2", "asmr"]

    audio_variants = []
    for voice in voices:
        print(f"  Voice: {voice}")
        try:
            wav_bytes = generate_tts(text, voice)
            audio_seg = AudioSegment.from_wav(io.BytesIO(wav_bytes))
            output_path = AUDIO_DIR / f"{short_id}_{voice}.mp3"
            audio_seg.export(str(output_path), format="mp3", bitrate="256k")
            duration = len(audio_seg) / 1000.0
            size_kb = output_path.stat().st_size / 1024
            print(f"    ✓ {output_path.name} ({size_kb:.0f} KB, {duration:.1f}s)")
            audio_variants.append({
                "voice": voice,
                "url": f"/audio/pre-gen/{output_path.name}",
                "duration_seconds": round(duration, 2),
                "provider": "chatterbox",
            })
        except Exception as e:
            print(f"    ✗ FAILED: {e}")

    if not audio_variants:
        print("ERROR: No audio generated. Aborting.")
        sys.exit(1)

    avg_dur = sum(v["duration_seconds"] for v in audio_variants) / len(audio_variants)
    dur_min = max(1, math.ceil(avg_dur / 60))
    print(f"  {len(audio_variants)} variants, avg {avg_dur:.1f}s\n")

    # ── 3. Generate musical brief ────────────────────────────────────
    print("[3/5] Generating musical brief...")
    time.sleep(32)  # Mistral free tier: 2 req/min
    mb_raw = call_mistral(MUSICAL_BRIEF_PROMPT.format(
        title=title, mood=MOOD, age_group=AGE_GROUP,
        text_excerpt=text[:300], story_id=story_id,
    ), max_tokens=1000)
    musical_brief = parse_json(mb_raw)
    musical_brief["storyId"] = story_id
    musical_brief["ageGroup"] = AGE_GROUP
    print(f"  ✓ Brief: {musical_brief.get('musicalIdentity', {}).get('primaryLoop', '?')}\n")

    # ── 4. Generate cover ────────────────────────────────────────────
    print("[4/5] Generating cover...")
    cover_dir = BASE_DIR / "seed_output" / "covers_experimental"
    cover_dir.mkdir(parents=True, exist_ok=True)

    cover_generated = False
    # Try FLUX via experimental cover script
    try:
        cover_script = BASE_DIR / "scripts" / "generate_cover_experimental.py"
        if cover_script.exists():
            story_json_path = BASE_DIR / "seed_output" / f"{story_id}_tmp.json"
            with open(story_json_path, "w") as f:
                json.dump({
                    "id": story_id, "title": title, "description": description,
                    "text": text, "mood": MOOD, "story_type": STORY_TYPE,
                    "target_age": 3, "age_min": 2, "age_max": 5,
                    "cover_desc": cover_desc, "character": character,
                }, f, indent=2)

            import subprocess
            result = subprocess.run(
                [sys.executable, str(cover_script), "--story-json", str(story_json_path)],
                capture_output=True, text=True, timeout=120, cwd=str(BASE_DIR),
            )
            story_json_path.unlink(missing_ok=True)

            flux_cover = cover_dir / f"{story_id}_combined.svg"
            if flux_cover.exists():
                cover_generated = True
                print(f"  ✓ FLUX cover: {flux_cover.name}")
    except Exception as e:
        print(f"  FLUX cover failed: {e}")

    if not cover_generated:
        svg = generate_cover_svg(story_id)
        cover_file = cover_dir / f"{story_id}_combined.svg"
        with open(cover_file, "w") as f:
            f.write(svg)
        print(f"  ✓ Fallback SVG cover")

    cover_url = f"/covers/{story_id}.svg"
    print()

    # ── 5. Add to content.json ───────────────────────────────────────
    print("[5/5] Adding to content.json...")

    now = datetime.utcnow().isoformat()
    entry = {
        "id": story_id,
        "type": "story",
        "lang": "en",
        "title": title,
        "description": description,
        "text": text,
        "cover": cover_url,
        "target_age": 3,
        "age_min": 2,
        "age_max": 5,
        "duration": dur_min,
        "duration_seconds": round(avg_dur, 2),
        "author_id": "system",
        "created_at": now,
        "updated_at": now,
        "addedAt": date.today().isoformat(),
        "theme": "nature",
        "mood": MOOD,
        "story_type": STORY_TYPE,
        "categories": categories,
        "audio_variants": audio_variants,
        "musicalBrief": musical_brief,
        "musicParams": {},
        "character": character,
        "word_count": word_count,
        "view_count": 0,
        "like_count": 0,
        "save_count": 0,
        "is_generated": True,
        "has_qa": False,
        "has_games": False,
        "hook": hook,
        "repeated_phrase": repeated_phrase,
        "experimental": True,
    }

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        all_content = json.load(f)
    all_content.append(entry)
    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_content, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"  ✓ content.json updated ({len(all_content)} entries)")

    # ── Done ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"✓ EXPERIMENTAL STORY GENERATED")
    print(f"{'='*60}")
    print(f"  ID:     {story_id}")
    print(f"  Title:  {title}")
    print(f"  Words:  {word_count}")
    print(f"  Phrase: \"{repeated_phrase}\"")
    print(f"  Audio:  {len(audio_variants)} variants ({avg_dur:.0f}s avg)")
    print()
    print("Next: sync + copy + push")
    print(f"  python3 scripts/sync_seed_data.py")
    print(f"  cp audio/pre-gen/{short_id}_*.mp3 ../dreamweaver-web/public/audio/pre-gen/")
    print(f"  cp seed_output/covers_experimental/{story_id}_combined.svg ../dreamweaver-web/public/covers/{story_id}.svg")

    # Return story_id for downstream use
    return story_id


if __name__ == "__main__":
    main()
