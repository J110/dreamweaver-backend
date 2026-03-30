#!/usr/bin/env python3
"""
Generate ONE experimental short story with intro, stings, and outro music.

Strategy: 150-300 word story with repeated phrases, direct address,
[MUSIC] tags for sting placement. Audio assembled as:
  intro (6s) → narration chunks with stings → silence (2s) → outro (45s)

Music generated via fal.ai Beatoven (instrumental).
Voice selection: 2 variants via mood-based voice system (calm → female_1 + asmr).

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
MUSIC_DIR = BASE_DIR / "audio" / "story_music"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"

# ── Config: Calm × Nature × 2-5 ──────────────────────────────────────
MOOD = "calm"
STORY_TYPE = "nature"
AGE_GROUP = "2-5"

# Mood voice selection: calm → female_1 + asmr
MOOD_VOICES = ["female_1", "asmr"]

# ── Music configs from spec ───────────────────────────────────────────

MOOD_INTRO = {
    "prompt": (
        "6 second gentle calm intro, soft music box, "
        "3-4 simple descending notes, already peaceful, "
        "60 BPM, warm, like a sigh of contentment, "
        "pulling up a blanket"
    ),
    "duration": 6,
}

MOOD_OUTRO = {
    "prompt": (
        "45 second sleep outro, same music box but even slower, "
        "notes further apart, descending, last note rings for "
        "5 seconds and fades, 60 BPM slowing to 35 BPM, "
        "calm becoming fully asleep, gentlest possible fade"
    ),
    "duration": 45,
}

# Stings selected by position in story + mood
STING_MAP = {
    "early": {
        "prompt": "2 second warm moment, soft piano chord, gentle, held, safe",
        "duration_seconds": 2,
    },
    "mid": {
        "prompt": "3 second pre-reveal shimmer, about to see something beautiful, golden",
        "duration_seconds": 3,
    },
    "late": {
        "prompt": "2.5 second feeling of being safe, warm low chord, held, protected, blanketed",
        "duration_seconds": 3,
    },
}

# ── Story prompt ──────────────────────────────────────────────────────

EXPERIMENTAL_PROMPT = """
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
ONE slow observation. Almost nothing happens. The character
is already at peace. They notice something quiet.
The noticing IS the story.

ONE character does ONE thing. No subplot, no secondary
characters, no thematic layers, no stated lessons.

=== THE REPEATED PHRASE ===
Create ONE phrase that appears at least 3 times in the story.
This is the most important element. By the third time, the
child is saying it before the narrator.

The phrase should be a sensory observation that keeps returning.

GOOD phrases: "Not yet... not yet." / "And the wind carried
it away." / "Same as always." / "Quieter now."

BAD phrases: anything over 8 words, "The end", "Goodnight".

=== DIRECT ADDRESS ===
Include 2-3 moments where the narrator speaks DIRECTLY to
the child. Ages 2-5: Simple SENSORY invitations.
  "Can you hear how quiet it is? ...That quiet."
  "Shhh... listen... did you hear that?"
  "Close your eyes for a second. Can you see it?"

=== MUSICAL PAUSES ===
Place [MUSIC] tags wherever the story needs to BREATHE —
a pause where the child absorbs what happened or leans into
what's coming.

Put [MUSIC] where YOU would pause if telling this story to
a child in a dark room. Where you'd let a moment land.

Some stories need 3-4 pauses. A very quiet story might need
1-2. Don't overthink it. Just pause where it feels natural.

=== STORY STRUCTURE ===

Opening: Did you know that {{natural wonder}}?

The story gets SIMPLER toward the end. Not more complex.
Sentences shorten. Details fade. The world gets quieter.
The last 3-4 sentences should be fragments — almost words.

Final line mirrors sleep: the character closes eyes, stops
moving, or goes quiet. The character IS the child.

Closing: And right now, somewhere, {{wonder is still happening}}.

=== SENTENCES ===
- 5-10 words per sentence for ages 2-5
- Concrete, sensory — things you see, hear, feel
- No abstract concepts, no metaphors
- Written for the EAR, not the page

=== OUTPUT FORMAT ===
Return ONLY valid JSON:

{{
  "title": "evocative IMAGE from story, under 6 words",
  "hook": "one sentence to make child want to listen, under 15 words",
  "cover_desc": "abstract minimal visual — one shape, one light, one gradient. NO characters. The FEELING as deep blues and warm golds.",
  "repeated_phrase": "exact phrase that repeats 3+ times",
  "description": "one sentence describing the story",
  "text": "full story text with [MUSIC] tags where pauses feel natural",
  "character": {{
    "name": "character name",
    "identity": "what the character is",
    "special": "one special trait",
    "personality_tags": ["gentle", "quiet"]
  }},
  "categories": ["Nature", "Bedtime"],
  "morals": []
}}
"""

MUSICAL_BRIEF_PROMPT = """You are a music director for a children's bedtime story app.

Given this story, generate a Musical Brief for background ambient music.

STORY: {title} | Mood: {mood} | Age: {age_group}
Text: {text_excerpt}

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
  "rhythm": {{ "feel": "gentle_pulse", "baseTempo": 58 }},
  "environment": {{
    "natureSoundPrimary": "one of: wind_gentle, rain_soft, forest_night, ocean_distant, creek",
    "natureSoundSecondary": "one of: distant_thunder, distant_stream, wind_chimes, none",
    "ambientEvents": ["pick 2-3 from: chimes, cricket, owl, leaves, waterDrop, heartbeat, starTwinkle"]
  }},
  "emotionalArc": {{
    "phase1": "gentle_wonder",
    "phase2": "soft_floating",
    "phase3": "deep_stillness"
  }}
}}
"""


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def call_mistral(prompt: str, max_tokens: int = 2000) -> str:
    client = Mistral(api_key=MISTRAL_API_KEY)
    for attempt in range(3):
        try:
            resp = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": "You are a creative bedtime story generator. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
                response_format={"type": "json_object"},
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  Mistral attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Mistral API failed")


def parse_json(text: str) -> dict:
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
    raise ValueError(f"JSON parse failed: {text[:200]}")


def parse_story_with_music(story_text: str):
    """Split story into narration chunks and music positions.

    Input:  "The bear sat down. [MUSIC] And then he yawned."
    Output: chunks=["The bear sat down.", "And then he yawned."], music_positions=[0]
    """
    chunks = []
    music_positions = []
    parts = re.split(r'(\[MUSIC\])', story_text)
    chunk_index = -1
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "[MUSIC]":
            if chunk_index >= 0:
                music_positions.append(chunk_index)
        else:
            chunk_index += 1
            chunks.append(part)
    return chunks, music_positions


def select_sting_zone(chunk_pos: int, total_chunks: int) -> str:
    progress = chunk_pos / max(total_chunks, 1)
    if progress < 0.3:
        return "early"
    elif progress < 0.7:
        return "mid"
    else:
        return "late"


def generate_tts(text: str, voice: str, exaggeration: float = 0.5,
                 cfg_weight: float = 0.4, speed: float = 0.88) -> bytes:
    """Call Chatterbox TTS, return WAV bytes."""
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
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


def get_musicgen():
    """Get a handle to the deployed MusicGen Modal class."""
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    return gen_cls()


def generate_music(gen, prompt: str, duration_seconds: float, label: str) -> AudioSegment:
    """Generate instrumental music via MusicGen on Modal T4. Returns AudioSegment.

    MusicGen gives exact duration — no trimming needed.
    """
    print(f"    MusicGen: {label} ({duration_seconds}s)...")
    start = time.time()

    mp3_data = gen.generate.remote(prompt, duration=int(duration_seconds))
    if not mp3_data or len(mp3_data) < 500:
        raise RuntimeError(f"MusicGen returned empty for {label}")

    elapsed = time.time() - start
    print(f"    ✓ {label}: {len(mp3_data):,} bytes in {elapsed:.0f}s")

    return AudioSegment.from_file(io.BytesIO(mp3_data))


def generate_cover_svg(story_id: str) -> str:
    """Fallback animated SVG cover for calm/nature mood."""
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


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    story_id = f"gen-{uuid.uuid4().hex[:12]}"
    short_id = story_id[:8]
    print(f"\n{'='*60}")
    print(f"Experimental Short Story — {MOOD} × {STORY_TYPE} × {AGE_GROUP}")
    print(f"ID: {story_id}  |  Voices: {MOOD_VOICES}")
    print(f"{'='*60}\n")

    # ── 1. Generate story text with [MUSIC] tags ─────────────────────
    print("[1/6] Generating story text via Mistral...")
    raw = call_mistral(EXPERIMENTAL_PROMPT.format(
        age_group=AGE_GROUP, mood=MOOD, story_type=STORY_TYPE,
    ))
    story = parse_json(raw)

    title = story["title"]
    text = story["text"]
    description = story.get("description", "")
    hook = story.get("hook", "")
    repeated_phrase = story.get("repeated_phrase", "")
    cover_desc = story.get("cover_desc", "")
    character = story.get("character", {})
    categories = story.get("categories", ["Nature", "Bedtime"])

    # Parse [MUSIC] tags
    chunks, music_positions = parse_story_with_music(text)
    # Clean text for content.json (without [MUSIC] tags)
    clean_text = re.sub(r'\s*\[MUSIC\]\s*', ' ', text).strip()
    word_count = len(clean_text.split())

    print(f"  Title: {title}")
    print(f"  Hook: {hook}")
    print(f"  Phrase: \"{repeated_phrase}\"")
    print(f"  Words: {word_count}")
    print(f"  Chunks: {len(chunks)}, Music tags: {len(music_positions)}")
    print()

    # ── 2. Generate music via MusicGen on Modal T4 ────────────────────
    print("[2/6] Generating music via MusicGen (Modal T4)...")
    gen = get_musicgen()

    # Intro — exact 6 seconds
    intro_audio = generate_music(gen, MOOD_INTRO["prompt"], 6, "calm intro")
    intro_path = MUSIC_DIR / "intro_calm.mp3"
    intro_audio.export(str(intro_path), format="mp3", bitrate="256k")

    # Outro — exact 45 seconds
    outro_audio = generate_music(gen, MOOD_OUTRO["prompt"], 45, "calm outro")
    outro_path = MUSIC_DIR / "outro_calm.mp3"
    outro_audio.export(str(outro_path), format="mp3", bitrate="256k")

    # Stings — exact durations per zone, no trimming
    zones_needed = set()
    for pos in music_positions:
        zone = select_sting_zone(pos, len(chunks))
        zones_needed.add(zone)

    sting_audio = {}
    for zone in sorted(zones_needed):
        cfg = STING_MAP[zone]
        duration_s = cfg["duration_seconds"]
        seg = generate_music(gen, cfg["prompt"], duration_s, f"sting_{zone}")
        sting_audio[zone] = seg
        sting_path = MUSIC_DIR / f"sting_{zone}.mp3"
        seg.export(str(sting_path), format="mp3", bitrate="256k")

    print(f"  Generated: intro (6s), outro (45s), {len(sting_audio)} stings\n")

    # ── 3. Generate TTS for each chunk × each voice ─────────────────
    print("[3/6] Generating TTS for 2 voice variants...")
    chunk_audio_by_voice = {}  # voice → [AudioSegment per chunk]

    for voice in MOOD_VOICES:
        print(f"  Voice: {voice}")
        chunk_audios = []
        for i, chunk in enumerate(chunks):
            wav_bytes = generate_tts(chunk, voice)
            seg = AudioSegment.from_wav(io.BytesIO(wav_bytes))
            chunk_audios.append(seg)
        chunk_audio_by_voice[voice] = chunk_audios
        print(f"    ✓ {len(chunk_audios)} chunks")

    print()

    # ── 4. Assemble: intro → narration with stings → silence → outro ─
    print("[4/6] Assembling final audio...")
    audio_variants = []

    for voice in MOOD_VOICES:
        print(f"  Assembling {voice}...")
        output = AudioSegment.silent(duration=0)

        # 1. Intro (6s)
        output += intro_audio
        output += AudioSegment.silent(duration=500)

        # 2. Narration with stings at marked positions
        chunk_audios = chunk_audio_by_voice[voice]
        for i, seg in enumerate(chunk_audios):
            output += seg

            if i in music_positions:
                zone = select_sting_zone(i, len(chunks))
                output += AudioSegment.silent(duration=500)  # breath before
                output += sting_audio[zone]
                output += AudioSegment.silent(duration=500)  # breath after

        # 3. Silence before outro
        output += AudioSegment.silent(duration=2000)

        # 4. Outro (45s)
        output += outro_audio

        # Export
        output_path = AUDIO_DIR / f"{short_id}_{voice}.mp3"
        output.export(str(output_path), format="mp3", bitrate="256k")
        duration = len(output) / 1000.0
        size_kb = output_path.stat().st_size / 1024
        print(f"    ✓ {output_path.name} ({size_kb:.0f} KB, {duration:.1f}s)")

        audio_variants.append({
            "voice": voice,
            "url": f"/audio/pre-gen/{output_path.name}",
            "duration_seconds": round(duration, 2),
            "provider": "chatterbox",
        })

    avg_dur = sum(v["duration_seconds"] for v in audio_variants) / len(audio_variants)
    dur_min = max(1, math.ceil(avg_dur / 60))
    print()

    # ── 5. Generate musical brief ────────────────────────────────────
    print("[5/6] Generating musical brief...")
    time.sleep(32)  # Mistral free tier: 2 req/min
    mb_raw = call_mistral(MUSICAL_BRIEF_PROMPT.format(
        title=title, mood=MOOD, age_group=AGE_GROUP,
        text_excerpt=clean_text[:300], story_id=story_id,
    ), max_tokens=1000)
    musical_brief = parse_json(mb_raw)
    musical_brief["storyId"] = story_id
    musical_brief["ageGroup"] = AGE_GROUP
    print(f"  ✓ {musical_brief.get('musicalIdentity', {}).get('primaryLoop', '?')}\n")

    # ── 6. Generate cover + add to content.json ──────────────────────
    print("[6/6] Cover + content.json...")

    # Try FLUX cover script
    cover_dir = BASE_DIR / "seed_output" / "covers_experimental"
    cover_dir.mkdir(parents=True, exist_ok=True)
    cover_generated = False
    try:
        cover_script = BASE_DIR / "scripts" / "generate_cover_experimental.py"
        if cover_script.exists():
            tmp_json = BASE_DIR / "seed_output" / f"{story_id}_tmp.json"
            with open(tmp_json, "w") as f:
                json.dump({
                    "id": story_id, "title": title, "description": description,
                    "text": clean_text, "mood": MOOD, "story_type": STORY_TYPE,
                    "target_age": 3, "age_min": 2, "age_max": 5,
                    "cover_desc": cover_desc, "character": character,
                }, f, indent=2)
            import subprocess
            subprocess.run(
                [sys.executable, str(cover_script), "--story-json", str(tmp_json)],
                capture_output=True, text=True, timeout=120, cwd=str(BASE_DIR),
            )
            tmp_json.unlink(missing_ok=True)
            flux_cover = cover_dir / f"{story_id}_combined.svg"
            if flux_cover.exists():
                cover_generated = True
                print(f"  ✓ FLUX cover")
    except Exception as e:
        print(f"  FLUX failed: {e}")

    if not cover_generated:
        svg = generate_cover_svg(story_id)
        with open(cover_dir / f"{story_id}_combined.svg", "w") as f:
            f.write(svg)
        print(f"  ✓ Fallback SVG cover")

    # Add to content.json
    now = datetime.now().isoformat()
    entry = {
        "id": story_id,
        "type": "story",
        "lang": "en",
        "title": title,
        "description": description,
        "text": clean_text,
        "cover": f"/covers/{story_id}.svg",
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

    # Remove old experimental story if exists
    all_content = [s for s in all_content if s.get("id") != "gen-b3b4ff39a1e6"]
    all_content.append(entry)

    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_content, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"  ✓ content.json updated ({len(all_content)} entries)")

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"✓ DONE")
    print(f"{'='*60}")
    print(f"  ID:     {story_id}")
    print(f"  Title:  {title}")
    print(f"  Words:  {word_count}")
    print(f"  Phrase: \"{repeated_phrase}\"")
    print(f"  Music:  intro + {len(music_positions)} stings + outro")
    print(f"  Audio:  {len(audio_variants)} variants ({avg_dur:.0f}s avg)")
    print(f"  Voices: {MOOD_VOICES}")

    return story_id


if __name__ == "__main__":
    main()
