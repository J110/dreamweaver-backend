#!/usr/bin/env python3
"""Publish one Hindi short story + one Hindi lullaby end-to-end.

Per the April 2026 rulings in the compaction summary:
  1. Roman Hindi only (no Devanagari in user-facing fields).
  2. ElevenLabs Multilingual v2 for new Hindi stories (voice `anika` for
     curious/2-5 per HINDI_STORY_VOICE_MAP).
  3. MiniMax Music v2.5 on fal.ai for the lullaby, anchored by a native
     Hindi reference recording (seed_output/hindi_lullaby_test_v26_reference/
     _reference_28s.m4a).
  4. Lullaby diversity uses option (a): lullaby-specific axes
     (lullaby_type, instrument, imagery, age_group) + shared characterType.
  5. characterType uses the canonical 11 values (land_mammal, bird, ...).
  6. Recency: story uses `land_mammal` (gilhari), lullaby uses `bird`
     (bulbul) — both categories are absent from existing Hindi catalog
     (which has insect + 3 objects).

Pieces produced:
  Story  (hi-prkr-2-5-gilh):
    - seed_output/hindi_stories/<id>.json
    - {web}/public/audio/pre-gen/<id>_anika.mp3 (narration + baked music)
    - cover SVG via generate_cover_experimental.py
    - content.json entry (type=story, lang=hi)

  Lullaby (hi-counting-6-8-blbl):
    - seed_output/lullabies/<id>.{mp3,_cover.svg,.json}
    - aggregate lullabies.json entry appended
    - content.json entry (type=song, lang=hi)  — so it appears on /home
      Loriyaan section (reads content.json, NOT /api/v1/lullabies)
    - {web}/public/audio/{lullabies,pre-gen}/<id>*.mp3
    - {web}/public/covers/{lullabies,<id>}.svg

Run from repo root (the dreamweaver-backend dir). Deploy follow-up lives at
the tail of the script.
"""

from __future__ import annotations
from _fal_utils import safe_subscribe as _safe_subscribe, safe_upload_file as _safe_upload_file

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from audio_assembly import (
    normalize_for_tts,
    apply_swell_envelope,
    MUSIC_DIR,
)

load_dotenv(BASE_DIR / ".env", override=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not ELEVENLABS_API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY not set")
FAL_KEY = os.getenv("FAL_KEY")
if not FAL_KEY:
    sys.exit("FAL_KEY must be set in .env for MiniMax v2.5 lullaby generation")
os.environ["FAL_KEY"] = FAL_KEY

ELEVENLABS_VOICES = {
    "tripti":   "yLldDJzoAIYirDpSiBvy",
    "roohi":    "oHNJagRZ2LQEfZb2CEkb",
    "anika":    "RABOvaPec1ymXz02oDQi",
    "gudiya":   "csPuxct3x4tABDZeKliZ",
    "meher":    "JS6C6yu2x9Byh4i1a8lX",
    "shreya_g": "RwXLkVKnRloV1UPh3Ccx",
}
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

HINDI_TTS_PARAMS = {
    "text":   {"stability": 0.70, "style": 0.00, "speed": 0.85},
    "hook":   {"stability": 0.60, "style": 0.05, "speed": 0.88},
    "phrase": {"stability": 0.80, "style": 0.00, "speed": 0.78},
}

MINIMAX_REFERENCE_FILE = BASE_DIR / "seed_output" / "hindi_lullaby_test_v26_reference" / "_reference_28s.m4a"
FAL_ENDPOINT = "fal-ai/minimax-music/v2.5"


# ─────────────────────────────────────────────────────────────────────────
# Hand-authored content (both entries)
# ─────────────────────────────────────────────────────────────────────────

# Today's catalog signal: existing Hindi items have `insect` + 3 `object`
# characters. We pick `land_mammal` (gilhari) and `bird` (bulbul) — both
# absent, both high-target (22% / 15% per the diversity guide), and both
# canonical familiar Indian animals.

STORY = {
    "id": "hi-prkr-2-5-gilh",
    "type": "STORY",
    "lang": "hi",
    "title": "Chiki Aur Pehli Baarish",
    "title_en": "Chiki and the First Rain",
    "description": "Chiki gilhari ki pehli baarish — tap tap, chupke chupke",
    "description_en": "Chiki the squirrel meets her first monsoon rain",
    "story_type": "prakriti_katha",
    "mood": "curious",
    "age_group": "2-5",
    "character_name": "Chiki",
    "character_identity": "a small Indian palm squirrel (gilhari)",
    "lead_character_type": "land_mammal",   # canonical 11
    "characterType": "land_mammal",          # mirror for diversity tracker
    "character_subtype": "familiar",
    "theme": "monsoon_wonder",
    "themes": ["monsoon_wonder", "nature_wonder"],
    "geography": "south_asia",
    "indian_region": "central",
    "gender_lead": "female",
    "repeated_phrase": "Chupke chupke, tip tip tip",
    # English cover brief — FLUX can't parse Roman Hindi; English is the
    # correct input language for the cover generator per the docs.
    "cover_context": (
        "A small brown Indian palm squirrel (gilhari) with a striped back, "
        "sitting on a wide green pipal leaf, wide curious eyes, first "
        "monsoon raindrops falling around her, soft gold-green evening "
        "light filtering through leaves, warm earthy palette, watercolor "
        "storybook style, 512x512"
    ),
    # Narration (segment-tagged). Roman Hindi. Sentences end with "."
    # Conversational markers: "Suno na", "Arre", "Pata hai", "Phir".
    # Onomatopoeia: "sarr sarr", "tap tap", "tip tip tip".
    # Opening pattern for Prakriti Katha: start with the weather/nature fact.
    "raw_text": (
        "Suno na bachcho. Aaj Chiki gilhari ki kahani.\n\n"
        "Chiki ek bade pipal ke ped par rehti thi. Choti choti aankhein, "
        "bhuri si dumm, aur hamesha kuch na kuch chabati rehti.\n\n"
        "[PAUSE: 800]\n\n"
        "Ek shaam hawa thandi thandi chalne lagi. Sarr sarr, sarr sarr. "
        "Chiki ne upar dekha. Baadal kaale kaale aa gaye the. Arre, yeh kya "
        "ho raha hai?\n\n"
        "[PAUSE: 600]\n\n"
        "Phir tap. Ek bunda gira patte par. Phir tap tap. Aur phir tap tap "
        "tap tap.\n\n"
        "Chiki chhup gayi bade patte ke niche. Baarish ki aawaz sunne lagi. "
        "Dheere dheere, jaise koi lori gaa raha ho.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
        "[MUSIC]\n\n"
        "Pata hai, Chiki ko yeh baarish bahut achhi lagi. Ek chhota sa phal "
        "haath mein, patte ki chatri upar, aur aankhein band.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "Hawa dheemi. Baarish dheemi. Chiki ki neend bhi aane lagi.\n\n"
        "Pipal jhoomta raha. Baadal gale milte rahe. Chiki ki saans dheere "
        "chalti rahi.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n\n"
        "Aur Chiki so gayi."
    ),
    "voice": "anika",     # curious + 2-5 → anika (slot 1)
    "experimental_v2": True,
    "has_baked_music": True,
    "tts_engine": "elevenlabs_multilingual_v2",
}

LULLABY = {
    "id": "hi-counting-6-8-blbl",
    "title": "Taare Gin, Rani",
    "card_label": "Taare Gin, Rani",
    "card_subtitle": "Rani bulbul ke saath taare ginte ginte so jao",
    "lullaby_type": "counting",
    "age_group": "6-8",
    "mood": "calm",
    "lang": "hi",
    "language": "hi",
    "character_name": "Rani",
    "character_identity": "a bulbul (Indian songbird) counting stars",
    "characterType": "bird",
    "character_subtype": "familiar",
    "instrument": "bansuri_tanpura",
    "imagery": "taare",
    "theme": "rest",
    "geography": "south_asia",
    "indian_region": "north",
    "engine": "minimax-music-1.5",   # we'll overwrite to v2.5 post-render
    # English style prompt (MiniMax reads these best in English).
    "style_prompt": (
        "Solo female Hindi lullaby, soft bamboo bansuri flute with a gentle "
        "tanpura drone, tender maternal voice, 62 BPM, lilting Hindustani "
        "feel, warm major key, no melancholy, intimate bedroom atmosphere, "
        "counting-song cadence, soft breath between phrases"
    ),
    # Roman Hindi lyrics, counting structure. ~2:30 target.
    "lyrics": (
        "[verse]\n"
        "Ek do teen, ginte jaao\n"
        "Taare saare dekhte jaao\n"
        "Neend ki raahon par chalo pyaari\n"
        "Rani bulbul, so jaao dheere\n\n"
        "[chorus]\n"
        "Gin gin taare, ek do teen\n"
        "Chup chup ke sab hain sheen\n"
        "Aankhein meechi, saans halki\n"
        "Aaja neend, ho tum halki\n\n"
        "[verse]\n"
        "Chaar paanch chhe, sapno wale\n"
        "Chaand ke piche baadal jaale\n"
        "Bansuri bajti hai dheere dheere\n"
        "Neend ki godi mein aao pyaari\n\n"
        "[chorus]\n"
        "Gin gin taare, ek do teen\n"
        "Chup chup ke sab hain sheen\n\n"
        "[verse]\n"
        "Saat aath nau, sab sitaare\n"
        "Soye dheere dheere saare\n"
        "Ab aankhein band karo pyaari\n"
        "Rani bulbul, so gayi dheere\n"
    ),
    "signature_opening_roman": "Ek do teen, ginte jaao",
    "signature_closing_roman": "Rani bulbul, so gayi dheere",
}


# ─────────────────────────────────────────────────────────────────────────
# ElevenLabs Hindi TTS
# ─────────────────────────────────────────────────────────────────────────

def elevenlabs_tts(text: str, voice_id: str, *, stability: float,
                   similarity: float, style: float, speed: float,
                   previous_text: str = "", next_text: str = "") -> AudioSegment:
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "use_speaker_boost": True,
            "speed": max(0.7, min(1.2, speed)),
        },
    }
    if previous_text:
        payload["previous_text"] = previous_text[-500:]
    if next_text:
        payload["next_text"] = next_text[:500]
    url = ELEVENLABS_URL.format(voice_id=voice_id) + "?output_format=mp3_44100_128"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                r = client.post(url, json=payload, headers=headers, timeout=180.0)
                if r.status_code == 200:
                    return AudioSegment.from_file(io.BytesIO(r.content), format="mp3")
                print(f"    11labs {r.status_code}: {r.text[:200]}", file=sys.stderr)
            except Exception as e:
                print(f"    11labs error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"ElevenLabs TTS failed voice={voice_id} text={text[:40]!r}")


def parse_segments_roman(text: str) -> list[tuple[str, object]]:
    """Parse segments from Roman-Hindi tagged text. Same tag set as English
    (`[MUSIC]`, `[PAUSE: ms]`, `[PHRASE]...[/PHRASE]`)."""
    import re
    text = text.replace("\r\n", "\n")
    segments: list[tuple[str, object]] = []
    pos = 0
    pattern = re.compile(
        r"\[MUSIC\]|\[PAUSE:\s*(\d+)\]|\[PHRASE\](.*?)\[/PHRASE\]",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            # Split into sentences for smoother TTS
            for sent in _split_sentences(before):
                if sent.strip():
                    segments.append(("text", sent.strip()))
        if m.group(0) == "[MUSIC]":
            segments.append(("music", None))
        elif m.group(1):
            segments.append(("pause", int(m.group(1))))
        elif m.group(2):
            segments.append(("phrase", m.group(2).strip()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        for sent in _split_sentences(tail):
            if sent.strip():
                segments.append(("text", sent.strip()))
    return segments


def _split_sentences(block: str) -> list[str]:
    """Split a Roman-Hindi paragraph into sentences for TTS. Keeps joined
    short lines together by re-flowing paragraphs, then splits on . ! ?"""
    import re
    flat = " ".join(line.strip() for line in block.splitlines() if line.strip())
    # Split on sentence terminators, keeping them attached.
    parts = re.split(r"(?<=[.!?])\s+", flat)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Coalesce tiny fragments so TTS has enough context per call.
        if out and len(p) < 18:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def assemble_hindi_story_audio(
    segments: list,
    voice_label: str,
    mood: str,
    hook: str,
) -> tuple[AudioSegment, AudioSegment]:
    """Hindi-specific v2 assembler: ElevenLabs TTS + music bed overlay
    pattern matching audio_assembly.assemble_v2_audio."""
    voice_id = ELEVENLABS_VOICES[voice_label]
    intro = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / f"outro_{mood}.wav"))
    bed   = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))

    def call(text, role, prev, nxt):
        preset = HINDI_TTS_PARAMS[role]
        effective = normalize_for_tts(text)
        return elevenlabs_tts(
            effective, voice_id,
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt,
        )

    print(f"  [hook] {hook[:60]!r}")
    hook_audio = call(hook, "hook", "", segments[0][1] if segments else "")

    # Render every segment with tonal context flowing across chunks.
    texts = [s[1] if s[0] in ("text", "phrase") else "" for s in segments]
    rendered: list[tuple[str, object]] = []
    for idx, (stype, content) in enumerate(segments):
        if stype == "text":
            prev = texts[idx - 1] if idx > 0 else hook
            nxt  = texts[idx + 1] if idx + 1 < len(texts) else ""
            rendered.append(("audio", call(content, "text", prev, nxt)))
        elif stype == "phrase":
            prev = texts[idx - 1] if idx > 0 else hook
            nxt  = texts[idx + 1] if idx + 1 < len(texts) else ""
            rendered.append(("audio", call(content, "phrase", prev, nxt)))
        elif stype == "pause":
            rendered.append(("pause", content))
        elif stype == "music":
            rendered.append(("music", None))

    narration = AudioSegment.silent(duration=0)
    swells: list[tuple[int, int]] = []
    narration += intro
    narration += AudioSegment.silent(duration=500)
    narration += hook_audio
    narration += AudioSegment.silent(duration=800)
    for stype, content in rendered:
        if stype == "audio":
            narration += content
        elif stype == "pause":
            narration += AudioSegment.silent(duration=content)
        elif stype == "music":
            start = len(narration)
            narration += AudioSegment.silent(duration=6000)
            swells.append((start, len(narration)))
    narration += AudioSegment.silent(duration=3000)
    narration += outro

    # Shape bed to fade out 3s before outro starts (parity with English).
    total = len(narration)
    outro_dur = len(outro)
    bed_end = total - outro_dur - 3000
    if len(bed) >= bed_end:
        shaped = bed[:bed_end]
    else:
        loops = (bed_end // len(bed)) + 1
        shaped = (bed * loops)[:bed_end]
    shaped = shaped.fade_out(3000)
    shaped += AudioSegment.silent(duration=total - bed_end)
    regions = [{"start": s, "fade_in_end": s + 2000,
                "hold_end": e - 2000, "fade_out_end": e} for s, e in swells]
    shaped = apply_swell_envelope(shaped, regions, base_db=-18, peak_db=-6)
    return narration.overlay(shaped), narration


# ─────────────────────────────────────────────────────────────────────────
# MiniMax Music v2.5 Hindi lullaby
# ─────────────────────────────────────────────────────────────────────────

def minimax_generate_lullaby(style: str, lyrics: str) -> bytes:
    import fal_client
    if not MINIMAX_REFERENCE_FILE.exists():
        sys.exit(f"Reference audio not found: {MINIMAX_REFERENCE_FILE}")
    print(f"  Uploading reference ({MINIMAX_REFERENCE_FILE.stat().st_size:,} bytes)...")
    ref_url = _safe_upload_file(str(MINIMAX_REFERENCE_FILE))
    print(f"  reference_audio → {ref_url}")

    # fal schema has varied — probe accepted param names.
    last_err: Optional[Exception] = None
    result = None
    for param in ("reference_audio_url", "reference_audio", "audio_url"):
        args = {"prompt": style, "lyrics": lyrics, param: ref_url}
        try:
            print(f"  Trying param '{param}'...")
            result = _safe_subscribe(FAL_ENDPOINT, arguments=args, with_logs=False)
            print(f"  → accepted")
            break
        except Exception as e:
            last_err = e
            print(f"  param '{param}' rejected: {str(e)[:140]}")
    if result is None:
        raise RuntimeError(f"All reference_audio params rejected: {last_err}")

    audio_url = None
    if isinstance(result, dict):
        audio = result.get("audio")
        if isinstance(audio, dict):
            audio_url = audio.get("url")
        elif isinstance(audio, str):
            audio_url = audio
        audio_url = audio_url or result.get("audio_url")
    if not audio_url:
        raise RuntimeError(f"No audio URL in response: {result!r}")

    resp = httpx.get(audio_url, timeout=240, follow_redirects=True)
    if resp.status_code != 200 or len(resp.content) < 2000:
        raise RuntimeError(f"Download failed: {resp.status_code} {len(resp.content)}B")
    return resp.content


# ─────────────────────────────────────────────────────────────────────────
# Cover generation (FLUX)
# ─────────────────────────────────────────────────────────────────────────

def run_cover_generator(story_json_path: Path, mood: str, story_type: str) -> None:
    cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "generate_cover_experimental.py"),
        "--story-json", str(story_json_path),
        "--mood", mood,
        "--story-type", story_type,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"  Running: {' '.join(cmd[-6:])}")
    r = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-800:])
        print(r.stderr[-1200:], file=sys.stderr)
        raise RuntimeError("Cover generator failed")
    print(r.stdout[-600:])


# ─────────────────────────────────────────────────────────────────────────
# Roman-Hindi validator (per HINDI_SHORT_STORY_GUIDELINES §18)
# ─────────────────────────────────────────────────────────────────────────

LITERARY_ROMAN = [
    "nidra", "nakshatra", "shayan", "pushp", "chandra ", "megha ",
    "gagan", "adhikar", "vilakshan", "samudra", "aakash",
]
CONVERSATIONAL_MARKERS = [
    "suno na", "toh", "pata hai", "arre", "dekho na", "phir", "achha",
]
DEVANAGARI_RE = r"[\u0900-\u097F]"

def validate_story_text(item: dict) -> None:
    import re
    for field in ("title", "description", "raw_text"):
        v = item.get(field, "")
        if re.search(DEVANAGARI_RE, v):
            raise AssertionError(f"Devanagari found in {field}")
    text_lower = item["raw_text"].lower()
    hits = [w for w in LITERARY_ROMAN if w in text_lower]
    if hits:
        raise AssertionError(f"Literary Hindi words found: {hits}")
    markers = [m for m in CONVERSATIONAL_MARKERS if m in text_lower]
    if len(markers) < 2:
        raise AssertionError(f"Need ≥2 conversational markers; found: {markers}")
    if item["repeated_phrase"].lower() not in text_lower:
        raise AssertionError("Repeated phrase not present in text")
    n_phrase = text_lower.count("[phrase]")
    if n_phrase != 3:
        raise AssertionError(f"Need exactly 3 [PHRASE] tags; found {n_phrase}")
    print("  ✓ story validator passed")


def validate_lullaby(item: dict) -> None:
    import re
    for field in ("title", "card_label", "card_subtitle", "lyrics"):
        v = item.get(field, "")
        if re.search(DEVANAGARI_RE, v):
            raise AssertionError(f"Devanagari found in lullaby {field}")
    if item["signature_opening_roman"] not in item["lyrics"]:
        raise AssertionError("Signature opening missing")
    if item["signature_closing_roman"] not in item["lyrics"]:
        raise AssertionError("Signature closing missing")
    print("  ✓ lullaby validator passed")


# ─────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────

def ensure_dirs() -> dict:
    paths = {
        "story_json": BASE_DIR / "seed_output" / "hindi_stories",
        "lullaby_dir": BASE_DIR / "seed_output" / "lullabies",
        "cov_exp": BASE_DIR / "seed_output" / "covers_experimental",
        "web_audio_lullabies": WEB_ROOT / "public" / "audio" / "lullabies",
        "web_audio_pregen":    WEB_ROOT / "public" / "audio" / "pre-gen",
        "web_cover_lullabies": WEB_ROOT / "public" / "covers" / "lullabies",
        "web_covers":          WEB_ROOT / "public" / "covers",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def publish_story(paths: dict) -> dict:
    sid = STORY["id"]
    print(f"\n═════ STORY {sid} ═════")
    # HARD GATE: narrative-craft checklist (§1-§7).
    # See docs/HINDI_SHORT_STORY_GUIDELINES.md.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from validate_hindi_story import validate_story_dict
    craft_issues = validate_story_dict(STORY)
    if craft_issues:
        print("  ❌ STORY fails narrative-craft checklist:", file=_sys.stderr)
        for i in craft_issues:
            print(f"    - {i}", file=_sys.stderr)
        raise AssertionError(
            "STORY dict failed §1-§7 checklist. Fix the dict before "
            "publishing. See docs/HINDI_SHORT_STORY_GUIDELINES.md."
        )
    print("  ✓ narrative-craft checklist (§1-§7) passed")
    validate_story_text(STORY)

    # Seed JSON (required input for the cover generator).
    story_json_path = paths["story_json"] / f"{sid}.json"
    with open(story_json_path, "w", encoding="utf-8") as f:
        json.dump(STORY, f, ensure_ascii=False, indent=2)
    print(f"  seed: {story_json_path}")

    # 1. Audio
    print("\n[1/3] ElevenLabs + music assembly (anika, curious)")
    segments = parse_segments_roman(STORY["raw_text"])
    counts: dict = {}
    for s, _ in segments:
        counts[s] = counts.get(s, 0) + 1
    print(f"  parsed: {counts}")
    with_music, without = assemble_hindi_story_audio(
        segments, STORY["voice"], STORY["mood"], STORY["description"],
    )
    audio_path = paths["web_audio_pregen"] / f"{sid}_{STORY['voice']}.mp3"
    with_music.export(audio_path, format="mp3", bitrate="192k")
    print(f"  audio: {audio_path} ({len(with_music)/1000:.1f}s)")

    # 2. Cover — map Hindi story_type → cover-generator's accepted choices.
    print("\n[2/3] FLUX cover")
    cover_story_type = {
        "prakriti_katha": "nature",
        "lok_katha": "folk_tale",
        "neeti_katha": "fable",
        "sapnon_ki_katha": "dream",
        "ghar_ki_kahani": "slice_of_life",
        "katha": "folk_tale",
    }.get(STORY["story_type"], "folk_tale")
    run_cover_generator(story_json_path, STORY["mood"], cover_story_type)
    src_svg = paths["cov_exp"] / f"{sid}_combined.svg"
    dst_svg = paths["web_covers"] / f"{sid}.svg"
    if not src_svg.exists():
        raise RuntimeError(f"Cover missing: {src_svg}")
    dst_svg.write_bytes(src_svg.read_bytes())
    print(f"  cover: {dst_svg}")

    # 3. content.json entry
    duration = round(len(with_music) / 1000)
    entry = {
        "id": sid,
        "type": "story",
        "lang": "hi",
        "title": STORY["title"],
        "description": STORY["description"],
        "ageGroup": STORY["age_group"],
        "age_group": STORY["age_group"],
        "mood": STORY["mood"],
        "storyType": STORY["story_type"],
        "story_type": STORY["story_type"],
        "character": STORY["character_name"],
        "characterType": STORY["characterType"],
        "lead_character_type": STORY["lead_character_type"],
        "theme": STORY["theme"],
        "themes": STORY["themes"],
        "geography": STORY["geography"],
        "indian_region": STORY["indian_region"],
        "experimental_v2": True,
        "has_baked_music": True,
        "tts_engine": STORY["tts_engine"],
        "cover": f"/covers/{sid}.svg",
        "audio_variants": [{
            "voice": STORY["voice"],
            "url": f"/audio/pre-gen/{sid}_{STORY['voice']}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "audio_url": f"/audio/pre-gen/{sid}_{STORY['voice']}.mp3",
        "duration_seconds": duration,
        "created_at": time.strftime("%Y-%m-%d"),
        "raw_text": STORY["raw_text"],
    }
    return entry


def publish_lullaby(paths: dict) -> dict:
    lid = LULLABY["id"]
    print(f"\n═════ LULLABY {lid} ═════")
    validate_lullaby(LULLABY)

    # 1. Audio via MiniMax v2.5
    print("\n[1/3] MiniMax Music v2.5 + reference")
    mp3_bytes = minimax_generate_lullaby(LULLABY["style_prompt"], LULLABY["lyrics"])
    audio_seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
    duration = round(len(audio_seg) / 1000)
    print(f"  duration: {duration}s")

    # Write to all three audio locations
    b_path = paths["lullaby_dir"] / f"{lid}.mp3"
    wl_path = paths["web_audio_lullabies"] / f"{lid}.mp3"
    wp_path = paths["web_audio_pregen"] / f"{lid}_female_1.mp3"
    for p in (b_path, wl_path, wp_path):
        with open(p, "wb") as f:
            f.write(mp3_bytes)
    print(f"  audio → {b_path}, {wl_path}, {wp_path}")

    # 2. Cover (reuse the short-story FLUX generator with a synthetic JSON)
    print("\n[2/3] FLUX cover for lullaby")
    lullaby_story_stub = {
        "id": lid,
        "title": LULLABY["title"],
        "title_en": "Counting Stars with Rani",
        "description": LULLABY["card_subtitle"],
        "description_en": "A bulbul counts stars with the child drifting to sleep",
        "cover_context": (
            "A small Indian bulbul songbird perched on a dark branch, wide "
            "night sky full of soft golden stars above, indigo and deep "
            "navy palette with warm amber highlights, gentle crescent "
            "moon, dreamy children's-book illustration, 512x512"
        ),
        "character_name": "Rani",
        "character_identity": LULLABY["character_identity"],
        "lead_character_type": "bird",
        "characterType": "bird",
        "mood": "calm",
        "age_group": LULLABY["age_group"],
    }
    stub_path = paths["lullaby_dir"] / f"{lid}_coverseed.json"
    with open(stub_path, "w", encoding="utf-8") as f:
        json.dump(lullaby_story_stub, f, ensure_ascii=False, indent=2)
    run_cover_generator(stub_path, "calm", "folk_tale")
    stub_path.unlink(missing_ok=True)

    src_svg = paths["cov_exp"] / f"{lid}_combined.svg"
    if not src_svg.exists():
        raise RuntimeError(f"Cover missing: {src_svg}")
    wl_cover = paths["web_cover_lullabies"] / f"{lid}_cover.svg"
    b_cover  = paths["lullaby_dir"] / f"{lid}_cover.svg"
    wc_cover = paths["web_covers"] / f"{lid}.svg"
    for p in (wl_cover, b_cover, wc_cover):
        p.write_bytes(src_svg.read_bytes())
    print(f"  cover → {wl_cover}, {b_cover}, {wc_cover}")

    # 3. Per-entry lullaby JSON
    entry = {
        "id": lid,
        "title": LULLABY["title"],
        "lullaby_type": LULLABY["lullaby_type"],
        "card_label": LULLABY["card_label"],
        "card_subtitle": LULLABY["card_subtitle"],
        "age_group": LULLABY["age_group"],
        "mood": LULLABY["mood"],
        "lang": "hi",
        "language": "hi",
        "audio_file": f"{lid}.mp3",
        "cover_file": f"{lid}_cover.svg",
        "duration_seconds": duration,
        "lyrics": LULLABY["lyrics"],
        "style_prompt": LULLABY["style_prompt"],
        "engine": "minimax-music-v2.5",
        "character_name": LULLABY["character_name"],
        "character_identity": LULLABY["character_identity"],
        "characterType": LULLABY["characterType"],
        "character_subtype": LULLABY["character_subtype"],
        "instrument": LULLABY["instrument"],
        "imagery": LULLABY["imagery"],
        "theme": LULLABY["theme"],
        "geography": LULLABY["geography"],
        "indian_region": LULLABY["indian_region"],
        "created_at": time.strftime("%Y-%m-%d"),
    }
    entry_path = paths["lullaby_dir"] / f"{lid}.json"
    with open(entry_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    print(f"  entry: {entry_path}")

    # 4. Append to aggregate lullabies.json
    agg_path = paths["lullaby_dir"] / "lullabies.json"
    with open(agg_path) as f:
        agg = json.load(f)
    agg = [x for x in agg if x.get("id") != lid] + [entry]
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    print(f"  appended to lullabies.json (total: {len(agg)})")

    # 5. content.json entry (type=song for home Loriyaan section)
    song_entry = {
        "id": lid,
        "type": "song",
        "lang": "hi",
        "title": LULLABY["title"],
        "description": LULLABY["card_subtitle"],
        "ageGroup": LULLABY["age_group"],
        "age_group": LULLABY["age_group"],
        "mood": LULLABY["mood"],
        "lullaby_type": LULLABY["lullaby_type"],
        "character": LULLABY["character_name"],
        "characterType": LULLABY["characterType"],
        "theme": LULLABY["theme"],
        "geography": LULLABY["geography"],
        "indian_region": LULLABY["indian_region"],
        "cover": f"/covers/{lid}.svg",
        "audio_variants": [{
            "voice": "female_1",
            "url": f"/audio/pre-gen/{lid}_female_1.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5",
        }],
        "audio_url": f"/audio/lullabies/{lid}.mp3",
        "duration_seconds": duration,
        "created_at": time.strftime("%Y-%m-%d"),
    }
    return song_entry


def upsert_content(entries: list[dict]) -> None:
    path = BASE_DIR / "seed_output" / "content.json"
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    ids = {e["id"] for e in entries}
    items = [i for i in items if i.get("id") not in ids]
    items.extend(entries)
    if isinstance(data, dict):
        data["items"] = items
    else:
        data = items
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\ncontent.json upserted (+{len(entries)}, total {len(items)})")


def main() -> None:
    paths = ensure_dirs()
    story_entry = publish_story(paths)
    lullaby_entry = publish_lullaby(paths)
    upsert_content([story_entry, lullaby_entry])
    print("\n═════ LOCAL PUBLISH DONE ═════")
    print(f"  story:   {STORY['id']}")
    print(f"  lullaby: {LULLABY['id']}")
    print("\nNext: commit + push + prod pull + scp audio + admin reload + deploy_guard verify.")


if __name__ == "__main__":
    main()
