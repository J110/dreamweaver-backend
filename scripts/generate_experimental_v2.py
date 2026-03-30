#!/usr/bin/env python3
"""
Generate ONE experimental story (v2 spec).
Bed + swell approach, [MUSIC], [PAUSE:ms], [PHRASE] tags.
Two outputs: with bed / without bed.

Usage:
    python3 scripts/generate_experimental_v2.py
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

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CONTENT_PATH = BASE_DIR / "seed_output" / "content.json"
AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"
MUSIC_DIR = BASE_DIR / "audio" / "story_music"
OUTPUT_DIR = BASE_DIR / "output" / "experimental_stories_v2"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"
FAL_KEY = os.getenv("FAL_KEY", "")

# ── Story Config ─────────────────────────────────────────────────────

STORY_CONFIG = {
    "mood": "wired",
    "story_type": "folk_tale",
    "age_group": "6-8",
}

# Voice selection: wired × 6-8 → female_1 + asmr
MOOD_VOICES = ["female_1", "asmr"]

# ── TTS Params ───────────────────────────────────────────────────────

NORMAL_TTS = {"exaggeration": 0.45, "speed": 0.85, "cfg_weight": 0.5}
HOOK_TTS = {"exaggeration": 0.55, "speed": 0.82, "cfg_weight": 0.45}
PHRASE_TTS = {"exaggeration": 0.60, "speed": 0.78, "cfg_weight": 0.42}

# ── Music Prompts ────────────────────────────────────────────────────

MOOD_BEDS = {
    "wired": "3 minute ambient background for children's bedtime story, light pizzicato and soft xylophone, very quiet, minimal, gentle repeating pattern, 70 BPM, playful but settling, the kind of music you feel more than hear",
    "curious": "3 minute ambient background for children's bedtime story, soft celesta and gentle harp, very quiet, minimal, occasional single notes with lots of space, 65 BPM, wondering, exploratory but calm",
    "calm": "3 minute ambient background for children's bedtime story, soft music box and gentle harp, very quiet, extremely minimal, same 3-4 notes repeating slowly with long pauses, 55 BPM, warm, peaceful, almost not there",
    "sad": "3 minute ambient background for children's bedtime story, solo piano, very quiet, minimal, single notes with long decay, 50 BPM, tender, warm not depressing",
    "anxious": "3 minute ambient background for children's bedtime story, soft low strings and gentle harp, very quiet, starts slightly uncertain then settles into warmth, 55 BPM, reassuring, safe",
    "angry": "3 minute ambient background for children's bedtime story, low warm cello drone, very quiet, grounding, steady single notes, no variation, 55 BPM, firm then softening, deep warmth",
}

MOOD_INTROS = {
    "wired": "6 second playful intro, light pizzicato and soft xylophone, gentle bouncy start, 70 BPM settling, like a happy sigh before bed",
    "calm": "6 second gentle calm intro, soft music box, 3-4 simple descending notes, already peaceful, 60 BPM, warm, like a sigh of contentment, pulling up a blanket",
}

MOOD_OUTROS = {
    "wired": "45 second sleep outro, pizzicato slowing to single soft notes, descending, settling into stillness, 70 BPM slowing to 40 BPM, playful energy fading into deep sleep",
    "calm": "45 second sleep outro, same music box but even slower, notes further apart, descending, last note rings for 5 seconds and fades, 60 BPM slowing to 35 BPM, calm becoming fully asleep, gentlest possible fade",
}

# ── Story Prompts ────────────────────────────────────────────────────

MOOD_CONCEPTS = {
    "wired": (
        "ONE physical event gone amusingly wrong. Something bounces, "
        "splashes, falls, or wobbles. Humor in the body, not the brain. "
        "The child laughs because they can FEEL it."
    ),
    "calm": (
        "ONE slow observation. Almost nothing happens. The character "
        "is already at peace. They notice something quiet. "
        "The noticing IS the story."
    ),
}

DIRECT_ADDRESS = {
    "6-8": (
        "Ages 6-8: WONDERING together.\n"
        "  'Can you guess what was behind the door?'\n"
        "  'You will never guess what happened next.'\n"
        "  'Do you know what that sound was? ...Neither did she.'\n"
        "  'What would YOU have done?'"
    ),
    "2-5": (
        "Ages 2-5: Simple SENSORY invitations.\n"
        "  'Can you hear how quiet it is? ...That quiet.'\n"
        "  'Shhh... listen... did you hear that?'\n"
        "  'Close your eyes for a second. Can you see it?'"
    ),
}

STORY_TYPE_SIGNATURES = {
    "folk_tale": {
        "opening": "Once, in a village where {something unusual was normal}...",
        "closing": "And if you listen carefully tonight, you might hear {the echo of the story}.",
    },
    "nature": {
        "opening": "Did you know that {natural wonder}?",
        "closing": "And right now, somewhere, {wonder is still happening}.",
    },
}

EXPERIMENTAL_PROMPT = """
Write a BEDTIME STORY for ages {age_group}.
Mood: {mood}
Story type: {story_type}

THIS IS NOT A LITERARY STORY. This is a story designed to be
HEARD IN BED with eyes closing. Simple enough that a sleepy
child follows every word. Engaging enough they WANT to listen
tomorrow.

=== LENGTH ===
150-300 words. NO LONGER.

=== ONE CONCEPT ===
{mood_concept}

ONE character does ONE thing. No subplot, no secondary
characters (unless fable — then exactly two), no thematic
layers, no stated lessons.

=== THE REPEATED PHRASE ===
Create ONE phrase that appears at least 3 times.
Wrap every instance in [PHRASE] tags:

[PHRASE]Not yet, not yet[/PHRASE]

The phrase should be under 8 words. By the third time, the
child is saying it before the narrator.

Do NOT repeat any other sentence. Every non-phrase line must
be unique.

=== DIRECT ADDRESS ===
Include 2-3 moments where the narrator speaks to the child.

{direct_address_instructions}

=== MUSICAL BREATHING ===
Place [MUSIC] tags wherever the story needs to BREATHE.
At these points, the narration will pause for 6 seconds
while background music swells up then settles back down.

Put [MUSIC] where YOU would pause if telling this story to
a child in a dark room. Where you'd let a moment land.
Where you'd take a breath.

Some stories need 3-5 pauses. Don't overthink it.

=== STRATEGIC PAUSES ===
Insert [PAUSE: ms] tags where the listener needs silence
to absorb, imagine, or breathe. The number is milliseconds.

[PAUSE: 800] — normal breath between images
[PAUSE: 1200] — a moment that should land and sit
[PAUSE: 1500] — significant stillness
[PAUSE: 2000] — the deepest pause, 1-2 times max

Pauses are NOT between every sentence. They're between
MOMENTS. "The lake is still." needs a pause because the
child should FEEL the stillness.

=== STORY STRUCTURE ===

Opening: {story_type_opening}

The story gets SIMPLER toward the end. Sentences shorten.
Details fade. The world gets quieter. The last 3-4 sentences
should be fragments.

The final line mirrors sleep: the character closes eyes,
stops moving, or goes quiet.

Closing: {story_type_closing}

=== SENTENCES ===
- 8-15 words per sentence for ages 6-8
- Concrete, sensory — things you see, hear, feel
- No abstract concepts
- Simple similes only ("soft like moss")
- Written for the EAR, not the page

=== OUTPUT FORMAT ===
Generate these BEFORE the story:

[HOOK: one sentence, under 15 words, makes the child want to listen]

[TITLE: most evocative IMAGE from the story. Under 6 words.]

[COVER: abstract minimal visual — one shape, one light, one gradient. NO characters. The FEELING as deep blues and warm golds. One sentence.]

[REPEATED_PHRASE: the exact phrase that repeats 3+ times]

Then the story as flowing prose with [MUSIC], [PAUSE: ms],
and [PHRASE]...[/PHRASE] tags inline.
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
                    {"role": "system", "content": "You are a creative bedtime story generator. Follow the output format exactly."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  Mistral attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Mistral API failed")


def generate_tts(text: str, voice: str, exaggeration: float = 0.45,
                 cfg_weight: float = 0.5, speed: float = 0.85) -> AudioSegment:
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_wav(io.BytesIO(resp.content))
                print(f"    TTS {resp.status_code}: {resp.text[:80]}")
            except Exception as e:
                print(f"    TTS error: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}")


def generate_cassetteai(prompt: str, duration: int, endpoint: str = "cassetteai/music-generator") -> AudioSegment:
    """Generate audio via CassetteAI on fal.ai."""
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


def generate_musicgen(prompt: str, duration: int) -> AudioSegment:
    """Fallback: MusicGen on Modal T4."""
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    gen = gen_cls()
    mp3_data = gen.generate.remote(prompt, duration=duration)
    if not mp3_data or len(mp3_data) < 500:
        raise RuntimeError("MusicGen returned empty")
    return AudioSegment.from_file(io.BytesIO(mp3_data))


def ensure_mood_music(mood: str):
    """Generate intro, outro, and bed for a mood if they don't exist."""
    files = {
        "bed": (MUSIC_DIR / f"bed_{mood}.wav", MOOD_BEDS.get(mood), 180, "cassetteai/music-generator"),
        "intro": (MUSIC_DIR / f"intro_{mood}.wav", MOOD_INTROS.get(mood, MOOD_INTROS["calm"]), 6, "cassetteai/sound-effects-generator"),
        "outro": (MUSIC_DIR / f"outro_{mood}.wav", MOOD_OUTROS.get(mood, MOOD_OUTROS["calm"]), 45, "cassetteai/music-generator"),
    }

    for label, (path, prompt, duration, endpoint) in files.items():
        if path.exists():
            print(f"  {label}: cached ({path.name})")
            continue

        print(f"  {label}: generating via CassetteAI ({duration}s)...")
        try:
            # CassetteAI music-generator has 10s minimum
            if endpoint == "cassetteai/music-generator" and duration < 10:
                endpoint = "cassetteai/sound-effects-generator"
            seg = generate_cassetteai(prompt, duration, endpoint)
            seg.export(str(path), format="wav")
            dur = len(seg) / 1000.0
            print(f"    ✓ {path.name} ({dur:.0f}s)")
        except Exception as e:
            print(f"    CassetteAI failed: {e}")
            print(f"    Falling back to MusicGen...")
            seg = generate_musicgen(prompt, duration)
            seg.export(str(path), format="wav")
            print(f"    ✓ {path.name} (MusicGen fallback)")


# ── Parsing ──────────────────────────────────────────────────────────

def extract_tag(text: str, tag_name: str) -> str:
    """Extract [TAG: content] handling various LLM formatting quirks."""
    # Try exact format first: [TAG: content]
    m = re.search(rf'\[{tag_name}:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try with markdown bold: **[TAG: content]**
    m = re.search(rf'\*?\*?\[{tag_name}:\s*(.*?)\]\*?\*?', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try line-based: TAG: content (on its own line)
    m = re.search(rf'^\*?\*?\[?{tag_name}\]?\*?\*?:\s*(.+)$', text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('*[]')
    return ""


def extract_story_body(raw: str) -> str:
    """Extract story text after the header tags."""
    # Find the last header tag line and take everything after
    last_tag_end = 0
    for m in re.finditer(r'\[?(HOOK|TITLE|COVER|REPEATED_PHRASE)[:\]][^\n]*', raw, re.IGNORECASE):
        last_tag_end = max(last_tag_end, m.end())
    body = raw[last_tag_end:].strip()
    # Strip leading markdown (---,  **, etc.)
    body = re.sub(r'^[\s\-\*]+\n', '', body)
    return body


def deduplicate_lines(text: str) -> str:
    """Remove consecutive duplicate lines (excluding [PHRASE] lines)."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Don't deduplicate phrase tags — they're supposed to repeat
        if "[PHRASE]" in line:
            cleaned.append(line)
            continue
        if not cleaned or line != cleaned[-1]:
            cleaned.append(line)
    return '\n'.join(cleaned)


def parse_segments(text: str) -> list:
    """
    Parse story text into ordered segments.
    Returns: [("text", content), ("pause", ms), ("phrase", content), ("music", None)]
    """
    segments = []
    pattern = r'(\[MUSIC\]|\[PAUSE:\s*\d+\]|\[PHRASE\].*?\[/PHRASE\])'
    parts = re.split(pattern, text, flags=re.DOTALL)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "[MUSIC]":
            segments.append(("music", None))
        elif part.startswith("[PAUSE:"):
            ms = int(re.search(r'\d+', part).group())
            segments.append(("pause", ms))
        elif part.startswith("[PHRASE]"):
            content = part.replace("[PHRASE]", "").replace("[/PHRASE]", "").strip()
            content = re.sub(r'\*+', '', content)  # Strip markdown
            segments.append(("phrase", content))
        else:
            # Strip markdown bold/italic from narration text
            cleaned = re.sub(r'\*+', '', part)
            cleaned = cleaned.strip()
            if cleaned:
                segments.append(("text", cleaned))

    return segments


def parse_story_output(raw: str) -> dict:
    hook = extract_tag(raw, "HOOK")
    title = extract_tag(raw, "TITLE")
    cover_desc = extract_tag(raw, "COVER")
    repeated_phrase = extract_tag(raw, "REPEATED_PHRASE")

    # Fallback: extract repeated phrase from [PHRASE] tags in the body
    if not repeated_phrase:
        phrase_matches = re.findall(r'\[PHRASE\](.*?)\[/PHRASE\]', raw, re.DOTALL)
        if phrase_matches:
            repeated_phrase = phrase_matches[0].strip()

    # Fallback: generate title/hook from first line
    if not title:
        first_text = re.sub(r'\[.*?\]', '', raw).strip().split('\n')
        for line in first_text:
            line = line.strip().strip('*-# ')
            if len(line) > 5 and not line.startswith('['):
                title = line[:60]
                break
    if not hook:
        hook = title or "A bedtime story"

    story_text = extract_story_body(raw)
    story_text = deduplicate_lines(story_text)
    segments = parse_segments(story_text)

    # Clean text (no tags, no markdown) for content.json
    clean = re.sub(r'\[MUSIC\]', '', story_text)
    clean = re.sub(r'\[PAUSE:\s*\d+\]', '', clean)
    clean = re.sub(r'\[/?PHRASE\]', '', clean)
    clean = re.sub(r'\*+', '', clean)  # Strip markdown bold/italic
    clean = re.sub(r'\s+', ' ', clean).strip()

    return {
        "hook": hook,
        "title": title,
        "cover_desc": cover_desc,
        "repeated_phrase": repeated_phrase,
        "segments": segments,
        "raw_text": story_text,
        "clean_text": clean,
        "word_count": len(clean.split()),
    }


# ── Swell Envelope ───────────────────────────────────────────────────

def apply_swell_envelope(bed: AudioSegment, swells: list,
                         base_db: float = -18, peak_db: float = -6) -> AudioSegment:
    """Apply volume swells to bed track in 50ms chunks."""
    chunk_ms = 50
    total_ms = len(bed)
    result = AudioSegment.silent(duration=0)

    pos = 0
    while pos < total_ms:
        chunk_end = min(pos + chunk_ms, total_ms)
        chunk = bed[pos:chunk_end]

        target_db = base_db
        for s in swells:
            if s["start"] <= pos < s["fade_in_end"]:
                progress = (pos - s["start"]) / max(s["fade_in_end"] - s["start"], 1)
                target_db = base_db + (peak_db - base_db) * progress
                break
            elif s["fade_in_end"] <= pos < s["hold_end"]:
                target_db = peak_db
                break
            elif s["hold_end"] <= pos < s["fade_out_end"]:
                progress = (pos - s["hold_end"]) / max(s["fade_out_end"] - s["hold_end"], 1)
                target_db = peak_db + (base_db - peak_db) * progress
                break

        result += chunk + target_db
        pos = chunk_end

    return result


# ── Cover ────────────────────────────────────────────────────────────

def generate_cover_svg(story_id: str, mood: str) -> str:
    """Animated SVG cover placeholder."""
    colors = {
        "wired": ("#2b1055", "#4a2080", "#ff9933"),
        "calm": ("#1a1a3e", "#2d2d6b", "#ffd700"),
        "sad": ("#1a2744", "#2a3d66", "#a0c4ff"),
        "curious": ("#1a3340", "#2a5566", "#66ccaa"),
        "anxious": ("#2a1a33", "#442a55", "#cc99ff"),
        "angry": ("#331a1a", "#552a2a", "#ff6644"),
    }
    c1, c2, accent = colors.get(mood, colors["calm"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{c1}"/>
      <stop offset="50%" stop-color="{c2}"/>
      <stop offset="100%" stop-color="{c1}"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="45%" r="35%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <ellipse cx="256" cy="230" rx="180" ry="160" fill="url(#glow)">
    <animate attributeName="rx" values="180;200;180" dur="6s" repeatCount="indefinite"/>
    <animate attributeName="ry" values="160;175;160" dur="6s" repeatCount="indefinite"/>
  </ellipse>
  <circle cx="200" cy="200" r="2.5" fill="{accent}" opacity="0.4">
    <animate attributeName="cy" values="200;175;200" dur="4s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.7;0.4" dur="4s" repeatCount="indefinite"/>
  </circle>
  <circle cx="310" cy="260" r="2" fill="{accent}" opacity="0.3">
    <animate attributeName="cy" values="260;240;260" dur="5s" repeatCount="indefinite"/>
  </circle>
  <circle cx="256" cy="190" r="3" fill="{accent}" opacity="0.25">
    <animate attributeName="cy" values="190;165;190" dur="7s" repeatCount="indefinite"/>
  </circle>
</svg>"""


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    mood = STORY_CONFIG["mood"]
    story_type = STORY_CONFIG["story_type"]
    age_group = STORY_CONFIG["age_group"]
    story_id = f"exp2-{uuid.uuid4().hex[:10]}"

    print(f"\n{'='*60}")
    print(f"Experimental Story v2 — {mood} × {story_type} × {age_group}")
    print(f"ID: {story_id}")
    print(f"{'='*60}\n")

    # ── 0. Ensure mood music exists ──────────────────────────────────
    print("[0/7] Ensuring mood music files...")
    ensure_mood_music(mood)
    print()

    # ── 1. Generate story text ───────────────────────────────────────
    print("[1/7] Generating story text via Mistral...")
    prompt = EXPERIMENTAL_PROMPT.format(
        age_group=age_group,
        mood=mood,
        story_type=story_type,
        mood_concept=MOOD_CONCEPTS.get(mood, MOOD_CONCEPTS["calm"]),
        direct_address_instructions=DIRECT_ADDRESS.get(age_group, DIRECT_ADDRESS["6-8"]),
        story_type_opening=STORY_TYPE_SIGNATURES.get(story_type, STORY_TYPE_SIGNATURES["folk_tale"])["opening"],
        story_type_closing=STORY_TYPE_SIGNATURES.get(story_type, STORY_TYPE_SIGNATURES["folk_tale"])["closing"],
    )

    raw_response = call_mistral(prompt)

    # Debug: show first 500 chars of raw response
    print(f"\n  --- Raw LLM Response (first 500 chars) ---")
    print(f"  {raw_response[:500]}")
    print(f"  ---\n")

    parsed = parse_story_output(raw_response)

    print(f"  Title: {parsed['title']}")
    print(f"  Hook: {parsed['hook']}")
    print(f"  Phrase: \"{parsed['repeated_phrase']}\"")
    print(f"  Words: {parsed['word_count']}")

    music_count = sum(1 for s in parsed["segments"] if s[0] == "music")
    pause_count = sum(1 for s in parsed["segments"] if s[0] == "pause")
    phrase_count = sum(1 for s in parsed["segments"] if s[0] == "phrase")
    print(f"  Segments: {len(parsed['segments'])} total")
    print(f"    [MUSIC]: {music_count}, [PAUSE]: {pause_count}, [PHRASE]: {phrase_count}")

    # Print all segments for debugging
    print(f"\n  --- Parsed Segments ---")
    for i, (stype, content) in enumerate(parsed["segments"]):
        if stype == "text":
            print(f"  [{i}] text: {content[:70]}...")
        elif stype == "phrase":
            print(f"  [{i}] PHRASE: {content}")
        elif stype == "pause":
            print(f"  [{i}] PAUSE: {content}ms")
        elif stype == "music":
            print(f"  [{i}] MUSIC (6s swell)")
    print()

    # Validate
    if parsed["word_count"] > 350:
        print(f"  WARNING: {parsed['word_count']} words (target: 150-300)")
    if phrase_count < 3:
        print(f"  WARNING: Phrase only appears {phrase_count} times (need 3+)")
    if not parsed["repeated_phrase"]:
        print("  WARNING: No repeated phrase found")

    # ── 2. Load mood music ───────────────────────────────────────────
    print("[2/7] Loading mood music...")
    intro = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / f"outro_{mood}.wav"))
    bed = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))
    print(f"  Intro: {len(intro)/1000:.1f}s, Outro: {len(outro)/1000:.1f}s, Bed: {len(bed)/1000:.1f}s\n")

    # ── 3. Generate TTS per voice ────────────────────────────────────
    audio_variants = []
    for voice in MOOD_VOICES:
        print(f"[3/7] Generating TTS for {voice}...")

        # Hook
        print(f"  TTS [hook]: {parsed['hook'][:50]}...")
        hook_audio = generate_tts(parsed["hook"], voice, **HOOK_TTS)
        print(f"    -> {len(hook_audio)}ms")

        # Segments
        segment_audios = []
        for stype, content in parsed["segments"]:
            if stype == "text":
                print(f"  TTS [normal]: {content[:50]}...")
                audio = generate_tts(content, voice, **NORMAL_TTS)
                segment_audios.append(("audio", audio))
                print(f"    -> {len(audio)}ms")
            elif stype == "phrase":
                print(f"  TTS [phrase]: {content}")
                audio = generate_tts(content, voice, **PHRASE_TTS)
                segment_audios.append(("audio", audio))
                print(f"    -> {len(audio)}ms")
            elif stype == "pause":
                segment_audios.append(("pause", content))
            elif stype == "music":
                segment_audios.append(("music", None))

        # Throwaway to prevent Chatterbox repeat bug
        try:
            generate_tts(".", voice, exaggeration=0.1, speed=0.8, cfg_weight=0.5)
        except:
            pass
        print()

        # ── 4. Build narration track ─────────────────────────────────
        print(f"[4/7] Building narration track ({voice})...")
        narration = AudioSegment.silent(duration=0)
        swell_regions = []

        # Intro
        narration += intro
        narration += AudioSegment.silent(duration=500)
        print(f"    +intro, now {len(narration)}ms")

        # Hook
        narration += hook_audio
        narration += AudioSegment.silent(duration=800)
        print(f"    +hook, now {len(narration)}ms")

        # Segments
        for stype, content in segment_audios:
            if stype == "audio":
                narration += content
            elif stype == "pause":
                narration += AudioSegment.silent(duration=content)
            elif stype == "music":
                start = len(narration)
                narration += AudioSegment.silent(duration=6000)
                swell_regions.append((start, len(narration)))
                print(f"    +SWELL @ {start}ms")

        # Gap + outro
        narration += AudioSegment.silent(duration=3000)
        narration += outro

        total_ms = len(narration)
        print(f"    Total: {total_ms/1000:.1f}s, Swells: {len(swell_regions)}\n")

        # ── 5. Shape bed and mix ─────────────────────────────────────
        print(f"[5/7] Shaping bed + mixing ({voice})...")

        # Trim or loop bed
        if len(bed) >= total_ms:
            shaped_bed = bed[:total_ms]
        else:
            loops = (total_ms // len(bed)) + 1
            shaped_bed = (bed * loops)[:total_ms]

        # Build swell data
        swells = []
        for start_ms, end_ms in swell_regions:
            swells.append({
                "start": start_ms,
                "fade_in_end": start_ms + 2000,
                "hold_end": end_ms - 2000,
                "fade_out_end": end_ms,
            })

        shaped_bed = apply_swell_envelope(shaped_bed, swells, base_db=-18, peak_db=-6)

        # Mix
        with_music = narration.overlay(shaped_bed)
        without_music = narration

        # Export to pipeline audio dir (pre-gen) — this is what gets served
        short_id = story_id[:8] if not story_id.startswith("exp2-") else story_id
        path_pipeline = AUDIO_DIR / f"{short_id}_{voice}.mp3"
        with_music.export(str(path_pipeline), format="mp3", bitrate="256k")

        # Also save both versions to output dir for comparison
        path_music = OUTPUT_DIR / f"{story_id}_{voice}.mp3"
        path_nomusic = OUTPUT_DIR / f"{story_id}_{voice}_nomusic.mp3"
        with_music.export(str(path_music), format="mp3", bitrate="256k")
        without_music.export(str(path_nomusic), format="mp3", bitrate="256k")

        duration_s = total_ms / 1000.0
        music_kb = path_pipeline.stat().st_size / 1024
        print(f"    Pipeline:    {path_pipeline.name} ({music_kb:.0f} KB, {duration_s:.1f}s)")
        print(f"    Output+bed:  {path_music.name}")
        print(f"    Output-bed:  {path_nomusic.name}\n")

        audio_variants.append({
            "voice": voice,
            "url": f"/audio/pre-gen/{path_pipeline.name}",
            "duration_seconds": round(duration_s, 2),
            "provider": "chatterbox",
        })

    avg_dur = sum(v["duration_seconds"] for v in audio_variants) / len(audio_variants)
    dur_min = max(1, math.ceil(avg_dur / 60))

    # ── 6. Generate musical brief ────────────────────────────────────
    print("[6/8] Generating musical brief...")
    time.sleep(32)  # Mistral rate limit
    mb_raw = call_mistral(MUSICAL_BRIEF_PROMPT.format(
        title=parsed["title"], mood=mood, age_group=age_group,
        text_excerpt=parsed["clean_text"][:300], story_id=story_id,
    ), max_tokens=1000)
    try:
        mb_text = mb_raw.strip()
        if mb_text.startswith("```"):
            mb_text = re.sub(r"^```(?:json)?\s*\n?", "", mb_text)
            mb_text = re.sub(r"\n?```\s*$", "", mb_text)
        musical_brief = json.loads(mb_text)
    except:
        match = re.search(r'\{[\s\S]*\}', mb_raw)
        musical_brief = json.loads(match.group()) if match else {}
    musical_brief["storyId"] = story_id
    musical_brief["ageGroup"] = age_group
    print(f"  ✓ Musical brief generated\n")

    # ── 7. Cover ─────────────────────────────────────────────────────
    print("[7/8] Generating cover...")
    cover_generated = False
    cover_dir = BASE_DIR / "seed_output" / "covers_experimental"
    cover_dir.mkdir(parents=True, exist_ok=True)
    try:
        cover_script = BASE_DIR / "scripts" / "generate_cover_experimental.py"
        if cover_script.exists():
            tmp_json = BASE_DIR / "seed_output" / f"{story_id}_tmp.json"
            with open(tmp_json, "w") as f:
                json.dump({
                    "id": story_id, "title": parsed["title"],
                    "description": parsed["hook"],
                    "text": parsed["clean_text"], "mood": mood,
                    "story_type": story_type,
                    "target_age": 7, "age_min": 6, "age_max": 8,
                    "cover_desc": parsed["cover_desc"],
                }, f, indent=2)
            import subprocess
            result = subprocess.run(
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
        svg = generate_cover_svg(story_id, mood)
        with open(cover_dir / f"{story_id}_combined.svg", "w") as f:
            f.write(svg)
        print(f"  ✓ Fallback SVG cover\n")

    # ── 8. Publish to content.json (pipeline standard) ───────────────
    print("[8/8] Publishing to content.json...")

    now = datetime.now().isoformat()
    entry = {
        "id": story_id,
        "type": "story",
        "lang": "en",
        "title": parsed["title"],
        "description": parsed["hook"],
        "text": parsed["clean_text"],
        "cover": f"/covers/{story_id}.svg",
        "target_age": 7,
        "age_min": 6,
        "age_max": 8,
        "duration": dur_min,
        "duration_seconds": round(avg_dur, 2),
        "author_id": "system",
        "created_at": now,
        "updated_at": now,
        "addedAt": date.today().isoformat(),
        "theme": story_type,
        "mood": mood,
        "story_type": story_type,
        "categories": ["Bedtime"],
        "audio_variants": audio_variants,
        "musicalBrief": musical_brief,
        "musicParams": {},
        "character": {},
        "word_count": parsed["word_count"],
        "view_count": 0,
        "like_count": 0,
        "save_count": 0,
        "is_generated": True,
        "has_qa": False,
        "has_games": False,
        "hook": parsed["hook"],
        "repeated_phrase": parsed["repeated_phrase"],
        "experimental_v2": True,
    }

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    all_content.append(entry)

    with open(CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_content, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"  ✓ content.json: {len(all_content)} entries")

    # Save metadata to output dir
    meta = {**entry, "raw_text": parsed["raw_text"], "cover_desc": parsed["cover_desc"]}
    meta_path = OUTPUT_DIR / f"{story_id}.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"✓ DONE — {story_id}")
    print(f"{'='*60}")
    print(f"  Title:  {parsed['title']}")
    print(f"  Phrase: \"{parsed['repeated_phrase']}\"")
    print(f"  Words:  {parsed['word_count']}")
    print(f"  Swells: {music_count}")
    print(f"  Pauses: {pause_count}")
    print(f"  Audio:  {len(audio_variants)} variants ({avg_dur:.0f}s avg)")
    print(f"\n  Pipeline files (audio/pre-gen/):")
    for v in audio_variants:
        print(f"    {v['url']}")
    print(f"\n  Output files:")
    for voice in MOOD_VOICES:
        print(f"    {OUTPUT_DIR / f'{story_id}_{voice}.mp3'}")
        print(f"    {OUTPUT_DIR / f'{story_id}_{voice}_nomusic.mp3'}")
    print(f"    {meta_path}")
    print(f"\n  Next: run sync_seed_data.py, then deploy to prod")

    return story_id


if __name__ == "__main__":
    main()
