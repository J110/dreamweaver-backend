#!/usr/bin/env python3
"""Surgical fix for the day-2 Hindi batch (hi-prkr-2-5-gilh + hi-counting-6-8-blbl).

Three issues diagnosed post-publish:

  1. AUDIO CLARITY — Roman Hindi was fed to both TTS engines. MiniMax Music
     v2.5 and ElevenLabs Multilingual v2 both tokenize Devanagari as Hindi
     phonemes cleanly; Roman spellings are mis-parsed as English-ish and
     clarity craters. The prior 3 shipped lullabies used Devanagari.
     FIX: dual-script — Roman for UI, Devanagari for engine input.

  2. STORY COVER shows a girl instead of a squirrel because:
       - `lead_character_type: "land_mammal"` isn't in the cover
         generator's taxonomy (which uses `animal`, `bird`, ...) so it
         fell back to `human_child` visual.
       - `description` was Roman Hindi, so _extract_character_phrase
         couldn't match "squirrel" via English keyword map.
     FIX: build a cover seed with dict `character.identity` (English),
     and translate canonical-11 → cover-gen taxonomy.

  3. BOTH entries miss `text` / proper `character` dict / `hook` → app
     doesn't render the narrative or the lyrics.
     FIX: rewrite both content.json entries to match the English schema.

Re-uses the same IDs, filenames, and file layout — so the deploy is a
drop-in overwrite. No new URLs, no cache bust needed.
"""

from __future__ import annotations

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
from audio_assembly import normalize_for_tts, apply_swell_envelope, MUSIC_DIR

load_dotenv(BASE_DIR / ".env", override=True)

ELEVENLABS_API_KEY = os.getenv(
    "ELEVENLABS_API_KEY",
    "sk_5bbd5d1a1ee9fa532c454154e2a7723f94ffc3bce07087ff",
)
FAL_KEY = os.getenv("FAL_KEY")
os.environ["FAL_KEY"] = FAL_KEY

ELEVENLABS_VOICES = {
    "tripti":   "yLldDJzoAIYirDpSiBvy",
    "roohi":    "oHNJagRZ2LQEfZb2CEkb",
    "anika":    "RABOvaPec1ymXz02oDQi",
    "gudiya":   "csPuxct3x4tABDZeKliZ",
    "meher":    "JS6C6yu2x9Byh4i1a8lX",
}
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
HINDI_TTS_PARAMS = {
    "text":   {"stability": 0.70, "style": 0.00, "speed": 0.85},
    "hook":   {"stability": 0.60, "style": 0.05, "speed": 0.88},
    "phrase": {"stability": 0.80, "style": 0.00, "speed": 0.78},
}

FAL_ENDPOINT = "fal-ai/minimax-music/v2.5"
# Resolve at use-time so the helper survives the seed-path file getting
# displaced by git operations. Order: seed-path (legacy), audio-store
# (v2.1 spec resilience), env override.
_REFERENCE_CANDIDATES = [
    Path(p) for p in [
        BASE_DIR / "seed_output" / "hindi_lullaby_test_v26_reference" / "_reference_28s.m4a",
        Path("/opt/audio-store/reference/hindi_lullaby_ref.m4a"),
    ]
]
def _resolve_minimax_reference() -> Path:
    env_override = os.getenv("MINIMAX_REFERENCE_FILE")
    if env_override and Path(env_override).exists():
        return Path(env_override)
    for p in _REFERENCE_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"MiniMax Hindi reference audio missing from any of: "
        f"{[str(p) for p in _REFERENCE_CANDIDATES]}"
    )

# Backwards-compat constant: existing callers still reference
# MINIMAX_REFERENCE_FILE.stat() in error paths. Lazy resolution would
# require touching every call site, so we keep the constant pointing at
# the primary path for type compatibility but the actual upload logic
# (in minimax_lullaby below) uses _resolve_minimax_reference().
MINIMAX_REFERENCE_FILE = _REFERENCE_CANDIDATES[0]

# Canonical 11 → cover-generator's 12-key taxonomy (CHAR_TYPE_TO_VISUAL).
CHAR_TYPE_CANONICAL_TO_COVER = {
    "land_mammal":         "animal",
    "reptile_amphibian":   "animal",
    "bird":                "bird",
    "sea_creature":        "sea_creature",
    "insect":              "insect",
    "human_child":         "human",
    "mythical_creature":   "mythical",
    "object_alive":        "object",
    "plant_tree":          "plant",
    "celestial_weather":   "celestial",
    "robot_mechanical":    "robot",
}


# ─────────────────────────────────────────────────────────────────────────
# Hand-authored bilingual content
# ─────────────────────────────────────────────────────────────────────────
# Invariant: Roman versions sound identical to Devanagari when read aloud.
# Roman is what the app shows; Devanagari is what the engines read.

STORY = {
    "id": "hi-prkr-2-5-gilh",
    "lang": "hi",
    "story_type": "prakriti_katha",
    "mood": "curious",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "target_age": 4,
    "voice": "anika",
    "title_roman": "Chiki Aur Pehli Baarish",
    "title_deva":  "चिकी और पहली बारिश",
    "title_en":    "Chiki and the First Rain",
    "hook_roman":  "Chiki gilhari ki pehli baarish — tap tap, chupke chupke",
    "hook_deva":   "चिकी गिलहरी की पहली बारिश — टप टप, चुपके चुपके।",
    "description_roman": "Chiki gilhari ki pehli baarish — tap tap, chupke chupke",
    "description_en":    "A small Indian palm squirrel named Chiki sits on the topmost branch of a peepal tree and watches the first monsoon rain arrive.",
    "repeated_phrase_roman": "Chupke chupke, tip tip tip",
    "repeated_phrase_deva":  "चुपके चुपके, टिप टिप टिप",
    # Character identity — dict shape matching English V2 schema.
    "character": {
        "name": "Chiki",
        "identity": "a small Indian palm squirrel named Chiki with a striped brown back and bright curious eyes",
        "special": "she watches the world from the branches of an old pipal tree",
        "personality_tags": ["Curious", "Gentle"],
    },
    "lead_character_type_canonical": "land_mammal",
    "lead_character_type_cover":     "animal",
    "theme": "monsoon_wonder",
    "themes": ["monsoon_wonder", "nature_wonder"],
    "geography": "south_asia",
    "indian_region": "central",
    "gender_lead": "female",
    # Rich English brief fed to the cover generator. FLUX composes the
    # scene from description + character.identity; we also include a
    # bespoke `cover_context` hint.
    "cover_context": (
        "a small Indian palm squirrel named Chiki with striped brown back "
        "sitting on a wide green pipal leaf, wide curious eyes, first "
        "monsoon raindrops falling around her, soft gold-green evening "
        "light filtering through leaves, warm earthy palette, watercolor "
        "storybook style, no humans in frame"
    ),
    # Segment-tagged narrative in BOTH scripts.
    # Tag set: [PAUSE: ms], [PHRASE]...[/PHRASE], [MUSIC]. Sentences
    # end with । in Devanagari and . in Roman. Lines are 1:1 between
    # the two.
    # Post-patch2 narrative. See docs/HINDI_SHORT_STORY_GUIDELINES.md §4/§5/§6.
    # - Sensory opening (prakriti_katha signature).
    # - 3 clean direct addresses to child ("Tumne kabhi…", "Tumhe pata hai…").
    # - One specific Chiki-only detail (topmost branch, village view).
    "text_roman": (
        "Shaam thi. Hawa thandi thandi chal rahi thi. Peepal ke bade se "
        "ped par, sabse upar wali shaakh par, ek chhoti si gilhari baithi "
        "thi. Naam tha Chiki.\n\n"
        "Chiki hamesha isi shaakh par aati thi — sabse upar wali — jahan "
        "se saara gaon dikhta tha. Chhote chhote ghar, mandir ki choti, "
        "aur door door tak khet.\n\n"
        "Tumne kabhi hawa ko itna dheere chalte dekha hai? Waisi hi thi "
        "us shaam ki hawa.\n\n"
        "[PAUSE: 800]\n\n"
        "Chiki ne upar dekha. Tumhe pata hai kya ho raha tha? Baadal "
        "kaale kaale aa rahe the, aasmaan bhar gaya. Sarr sarr, sarr "
        "sarr — hawa dheere dheere ghoomne lagi.\n\n"
        "[PAUSE: 600]\n\n"
        "Phir tap. Ek bunda gira patte par. Phir tap tap. Aur phir tap "
        "tap tap tap.\n\n"
        "Tumne kabhi baarish mein patte ke niche chhupa hai? Chiki ne "
        "bhi aisa hi kiya — chhup gayi bade patte ke niche, aur baarish "
        "ki aawaz sunne lagi. Dheere dheere, jaise koi lori gaa raha ho.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
        "[MUSIC]\n\n"
        "Ek chhota sa phal haath mein, patte ki chatri upar, aur aankhein "
        "band. Chiki ko yeh pehli baarish bahut achhi lagi.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "Hawa dheemi. Baarish dheemi. Chiki ki neend bhi aane lagi.\n\n"
        "Peepal jhoomta raha. Baadal gale milte rahe. Chiki ki saans "
        "dheere chalti rahi.\n\n"
        "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n\n"
        "Aur Chiki so gayi."
    ),
    "text_deva": (
        "शाम थी। हवा ठंडी ठंडी चल रही थी। पीपल के बड़े से पेड़ पर, "
        "सबसे ऊपर वाली शाख पर, एक छोटी सी गिलहरी बैठी थी। नाम था "
        "चिकी।\n\n"
        "चिकी हमेशा इसी शाख पर आती थी — सबसे ऊपर वाली — जहाँ से "
        "सारा गाँव दिखता था। छोटे छोटे घर, मंदिर की चोटी, और दूर "
        "दूर तक खेत।\n\n"
        "तुमने कभी हवा को इतना धीरे चलते देखा है? वैसी ही थी उस "
        "शाम की हवा।\n\n"
        "[PAUSE: 800]\n\n"
        "चिकी ने ऊपर देखा। तुम्हें पता है क्या हो रहा था? बादल काले "
        "काले आ रहे थे, आसमान भर गया। सर्र सर्र, सर्र सर्र — हवा "
        "धीरे धीरे घूमने लगी।\n\n"
        "[PAUSE: 600]\n\n"
        "फिर टप। एक बूँदा गिरा पत्ते पर। फिर टप टप। और फिर टप टप "
        "टप टप।\n\n"
        "तुमने कभी बारिश में पत्ते के नीचे छुपा है? चिकी ने भी "
        "ऐसा ही किया — छुप गई बड़े पत्ते के नीचे, और बारिश की आवाज़ "
        "सुनने लगी। धीरे धीरे, जैसे कोई लोरी गा रहा हो।\n\n"
        "[PHRASE] चुपके चुपके, टिप टिप टिप। [/PHRASE]\n"
        "[MUSIC]\n\n"
        "एक छोटा सा फल हाथ में, पत्ते की छतरी ऊपर, और आँखें बंद। "
        "चिकी को यह पहली बारिश बहुत अच्छी लगी।\n\n"
        "[PHRASE] चुपके चुपके, टिप टिप टिप। [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "हवा धीमी। बारिश धीमी। चिकी की नींद भी आने लगी।\n\n"
        "पीपल झूमता रहा। बादल गले मिलते रहे। चिकी की साँस धीरे "
        "चलती रही।\n\n"
        "[PHRASE] चुपके चुपके, टिप टिप टिप। [/PHRASE]\n\n"
        "और चिकी सो गई।"
    ),
}

LULLABY = {
    "id": "hi-counting-6-8-blbl",
    "lang": "hi",
    "lullaby_type": "counting",
    "age_group": "6-8",
    "age_min": 6,
    "age_max": 8,
    "target_age": 7,
    "mood": "calm",
    "instrument": "bansuri_tanpura",
    "imagery": "taare",
    "theme": "rest",
    "geography": "south_asia",
    "indian_region": "north",
    "title_roman": "Taare Gin, Rani",
    "title_deva":  "तारे गिन, रानी",
    "title_en":    "Counting Stars with Rani",
    "card_label_roman": "Taare Gin, Rani",
    "card_subtitle_roman": "Rani bulbul ke saath taare ginte ginte so jao",
    "card_subtitle_deva":  "रानी बुलबुल के साथ तारे गिनते गिनते सो जाओ",
    "description_en":      "A bulbul named Rani counts stars in the night sky, lulling the child to sleep.",
    "signature_opening_roman": "Ek do teen, ginte jaao",
    "signature_closing_roman": "Rani bulbul, so gayi dheere",
    "character": {
        "name": "Rani",
        "identity": "a small Indian bulbul songbird named Rani perched on a branch under a starry sky",
        "special": "she counts the night stars until her own eyes grow heavy",
        "personality_tags": ["Gentle", "Sleepy"],
    },
    "lead_character_type_canonical": "bird",
    "lead_character_type_cover":     "bird",
    "style_prompt": (
        "Solo female Hindi lullaby, soft bamboo bansuri flute with a gentle "
        "tanpura drone, tender maternal voice, 62 BPM, lilting Hindustani "
        "feel, warm major key, no melancholy, intimate bedroom atmosphere, "
        "counting-song cadence, soft breath between phrases"
    ),
    "lyrics_roman": (
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
    "lyrics_deva": (
        "[verse]\n"
        "एक दो तीन, गिनते जाओ\n"
        "तारे सारे देखते जाओ\n"
        "नींद की राहों पर चलो प्यारी\n"
        "रानी बुलबुल, सो जाओ धीरे\n\n"
        "[chorus]\n"
        "गिन गिन तारे, एक दो तीन\n"
        "चुप चुप के सब हैं शीन\n"
        "आँखें मींची, साँस हल्की\n"
        "आजा नींद, हो तुम हल्की\n\n"
        "[verse]\n"
        "चार पाँच छह, सपनों वाले\n"
        "चाँद के पीछे बादल जाले\n"
        "बंसुरी बजती है धीरे धीरे\n"
        "नींद की गोदी में आओ प्यारी\n\n"
        "[chorus]\n"
        "गिन गिन तारे, एक दो तीन\n"
        "चुप चुप के सब हैं शीन\n\n"
        "[verse]\n"
        "सात आठ नौ, सब सितारे\n"
        "सोये धीरे धीरे सारे\n"
        "अब आँखें बंद करो प्यारी\n"
        "रानी बुलबुल, सो गई धीरे\n"
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# ElevenLabs Devanagari TTS
# ─────────────────────────────────────────────────────────────────────────

DEVA_TERMINATORS = ("।", ".", "!", "?", "…")

def _ensure_terminal_danda(text: str) -> str:
    stripped = text.rstrip()
    if stripped.endswith(DEVA_TERMINATORS):
        return stripped
    return stripped + "।"


def elevenlabs_tts(text, voice_id, *, stability, similarity, style, speed,
                   previous_text="", next_text=""):
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": stability, "similarity_boost": similarity,
            "style": style, "use_speaker_boost": True,
            "speed": max(0.7, min(1.2, speed)),
        },
    }
    if previous_text:
        payload["previous_text"] = previous_text[-500:]
    if next_text:
        payload["next_text"] = next_text[:500]
    url = ELEVENLABS_URL.format(voice_id=voice_id) + "?output_format=mp3_44100_128"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json",
               "Accept": "audio/mpeg"}
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
    raise RuntimeError(f"ElevenLabs TTS failed voice={voice_id}")


def parse_segments_deva(text: str) -> list:
    """Parse Devanagari segments. Sentences end with ।"""
    import re
    text = text.replace("\r\n", "\n")
    segs = []
    pos = 0
    pat = re.compile(r"\[MUSIC\]|\[PAUSE:\s*(\d+)\]|\[PHRASE\](.*?)\[/PHRASE\]", re.DOTALL)
    for m in pat.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            for s in _split_deva_sentences(before):
                if s.strip():
                    segs.append(("text", s.strip()))
        if m.group(0) == "[MUSIC]":
            segs.append(("music", None))
        elif m.group(1):
            segs.append(("pause", int(m.group(1))))
        elif m.group(2):
            segs.append(("phrase", m.group(2).strip()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        for s in _split_deva_sentences(tail):
            if s.strip():
                segs.append(("text", s.strip()))
    return segs


def _split_deva_sentences(block: str) -> list:
    import re
    flat = " ".join(line.strip() for line in block.splitlines() if line.strip())
    parts = re.split(r"(?<=[।.!?])\s+", flat)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and len(p) < 18:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def assemble_story_audio(text_deva: str, hook_deva: str, voice_label: str, mood: str):
    voice_id = ELEVENLABS_VOICES[voice_label]
    intro = AudioSegment.from_wav(str(MUSIC_DIR / f"intro_{mood}.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / f"outro_{mood}.wav"))
    bed   = AudioSegment.from_wav(str(MUSIC_DIR / f"bed_{mood}.wav"))

    def call(text, role, prev, nxt, is_phrase=False):
        preset = HINDI_TTS_PARAMS[role]
        effective = _ensure_terminal_danda(text) if is_phrase else text
        effective = normalize_for_tts(effective)
        return elevenlabs_tts(effective, voice_id,
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt)

    segments = parse_segments_deva(text_deva)
    counts = {}
    for s, _ in segments: counts[s] = counts.get(s,0) + 1
    print(f"  segments: {counts}")

    texts_only = [s[1] if s[0] in ("text","phrase") else "" for s in segments]
    print(f"  [hook]: {hook_deva!r}")
    hook_audio = call(hook_deva, "hook", "", texts_only[0] if texts_only else "")

    rendered = []
    for idx, (stype, content) in enumerate(segments):
        if stype in ("text", "phrase"):
            prev = texts_only[idx-1] if idx>0 else hook_deva
            nxt  = texts_only[idx+1] if idx+1<len(texts_only) else ""
            role = "phrase" if stype=="phrase" else "text"
            rendered.append(("audio", call(content, role, prev, nxt, is_phrase=(stype=="phrase"))))
        elif stype == "pause":
            rendered.append(("pause", content))
        elif stype == "music":
            rendered.append(("music", None))

    narration = AudioSegment.silent(duration=0)
    swells = []
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
    regions = [{"start": s, "fade_in_end": s+2000, "hold_end": e-2000, "fade_out_end": e}
               for s, e in swells]
    shaped = apply_swell_envelope(shaped, regions, base_db=-18, peak_db=-6)
    return narration.overlay(shaped)


# ─────────────────────────────────────────────────────────────────────────
# MiniMax v2.5 with Devanagari lyrics
# ─────────────────────────────────────────────────────────────────────────

def minimax_lullaby(style, lyrics_deva):
    import fal_client
    ref_path = _resolve_minimax_reference()
    print(f"  Uploading reference {ref_path.name} ({ref_path.stat().st_size:,} bytes)...")
    ref_url = fal_client.upload_file(str(ref_path))
    args = {"prompt": style, "lyrics": lyrics_deva, "reference_audio_url": ref_url}
    print(f"  fal-ai/minimax-music/v2.5 + Devanagari lyrics (len={len(lyrics_deva)})")
    result = fal_client.subscribe(FAL_ENDPOINT, arguments=args, with_logs=False)
    audio_url = None
    if isinstance(result, dict):
        a = result.get("audio")
        if isinstance(a, dict):
            audio_url = a.get("url")
        elif isinstance(a, str):
            audio_url = a
        audio_url = audio_url or result.get("audio_url")
    if not audio_url:
        raise RuntimeError(f"no audio_url in {result!r}")
    r = httpx.get(audio_url, timeout=240, follow_redirects=True)
    if r.status_code != 200 or len(r.content) < 2000:
        raise RuntimeError(f"download failed {r.status_code} {len(r.content)}")
    return r.content


# ─────────────────────────────────────────────────────────────────────────
# Cover regen for the story
# ─────────────────────────────────────────────────────────────────────────

def regen_story_cover():
    """Build a cover-gen-friendly seed with rich English character and
    correct lead_character_type, then invoke generate_cover_experimental.py."""
    cover_seed = {
        "id": STORY["id"],
        "title": STORY["title_en"],          # English so the model renders clean scene
        "description": STORY["description_en"],
        "cover_context": STORY["cover_context"],
        "character": STORY["character"],     # dict with English identity
        "lead_character_type": STORY["lead_character_type_cover"],  # "animal" — cover gen taxonomy
        "lead_gender": STORY["gender_lead"],
        "theme": STORY["theme"],
        "age_group": STORY["age_group"],
        "mood": STORY["mood"],
    }
    seed_dir = BASE_DIR / "seed_output" / "hindi_stories"
    seed_path = seed_dir / f"{STORY['id']}_coverseed.json"
    with open(seed_path, "w", encoding="utf-8") as f:
        json.dump(cover_seed, f, ensure_ascii=False, indent=2)

    cmd = [
        sys.executable, str(BASE_DIR / "scripts" / "generate_cover_experimental.py"),
        "--story-json", str(seed_path),
        "--mood", STORY["mood"],
        "--story-type", "nature",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH","")
    r = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-800:])
        print(r.stderr[-1200:], file=sys.stderr)
        raise RuntimeError("cover regen failed")
    print(r.stdout[-500:])
    seed_path.unlink(missing_ok=True)

    src = BASE_DIR / "seed_output" / "covers_experimental" / f"{STORY['id']}_combined.svg"
    dst = WEB_ROOT / "public" / "covers" / f"{STORY['id']}.svg"
    dst.write_bytes(src.read_bytes())
    print(f"  cover: {dst}")
    return dst


# ─────────────────────────────────────────────────────────────────────────
# content.json + lullabies.json rewrites (English-schema parity)
# ─────────────────────────────────────────────────────────────────────────

def story_entry(duration: int) -> dict:
    return {
        "id": STORY["id"],
        "type": "story",
        "lang": "hi",
        "title": STORY["title_roman"],
        "title_deva": STORY["title_deva"],
        "title_en": STORY["title_en"],
        "description": STORY["description_roman"],
        "description_en": STORY["description_en"],
        "hook": STORY["hook_roman"],
        "hook_deva": STORY["hook_deva"],
        # `text` is what the app renders. Roman Hindi for readability.
        "text": STORY["text_roman"],
        "text_deva": STORY["text_deva"],
        "raw_text": STORY["text_roman"],
        "repeated_phrase": STORY["repeated_phrase_roman"],
        "repeated_phrase_deva": STORY["repeated_phrase_deva"],
        "character": STORY["character"],     # dict — English identity
        "character_name": STORY["character"]["name"],
        "characterType": STORY["lead_character_type_canonical"],
        "lead_character_type": STORY["lead_character_type_canonical"],
        "lead_gender": STORY["gender_lead"],
        "age_group": STORY["age_group"],
        "ageGroup": STORY["age_group"],
        "age_min": STORY["age_min"],
        "age_max": STORY["age_max"],
        "target_age": STORY["target_age"],
        "mood": STORY["mood"],
        "story_type": STORY["story_type"],
        "storyType": STORY["story_type"],
        "theme": STORY["theme"],
        "themes": STORY["themes"],
        "geography": STORY["geography"],
        "indian_region": STORY["indian_region"],
        "experimental_v2": True,
        "has_baked_music": True,
        "tts_engine": "elevenlabs_multilingual_v2",
        "tts_input_script": "devanagari",
        "cover": f"/covers/{STORY['id']}.svg",
        "audio_variants": [{
            "voice": STORY["voice"],
            "url": f"/audio/pre-gen/{STORY['id']}_{STORY['voice']}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "audio_url": f"/audio/pre-gen/{STORY['id']}_{STORY['voice']}.mp3",
        "duration_seconds": duration,
        "word_count": len(STORY["text_roman"].split()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime"],
    }


def lullaby_song_entry(duration: int) -> dict:
    return {
        "id": LULLABY["id"],
        "type": "song",
        "lang": "hi",
        "title": LULLABY["title_roman"],
        "title_deva": LULLABY["title_deva"],
        "title_en": LULLABY["title_en"],
        "description": LULLABY["card_subtitle_roman"],
        "description_en": LULLABY["description_en"],
        # `text` is what the lullaby player shows — Roman lyrics.
        "text": LULLABY["lyrics_roman"],
        "text_deva": LULLABY["lyrics_deva"],
        "lyrics": LULLABY["lyrics_roman"],
        "lyrics_deva": LULLABY["lyrics_deva"],
        "lullaby_type": LULLABY["lullaby_type"],
        "age_group": LULLABY["age_group"],
        "ageGroup": LULLABY["age_group"],
        "age_min": LULLABY["age_min"],
        "age_max": LULLABY["age_max"],
        "target_age": LULLABY["target_age"],
        "mood": LULLABY["mood"],
        "character": LULLABY["character"],
        "character_name": LULLABY["character"]["name"],
        "characterType": LULLABY["lead_character_type_canonical"],
        "theme": LULLABY["theme"],
        "instruments": ["bansuri", "tanpura"],
        "geography": LULLABY["geography"],
        "indian_region": LULLABY["indian_region"],
        "cover": f"/covers/{LULLABY['id']}.svg",
        "audio_variants": [{
            "voice": "female_1",
            "url": f"/audio/pre-gen/{LULLABY['id']}_female_1.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5",
        }],
        "audio_url": f"/audio/lullabies/{LULLABY['id']}.mp3",
        "duration_seconds": duration,
        "word_count": len(LULLABY["lyrics_roman"].split()),
        "music_type": "ambient",
        "music_genre": "lullaby",
        "categories": ["Lullabies"],
        "is_generated": True,
        "author_id": "system",
        "tts_input_script": "devanagari",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def lullaby_agg_entry(duration: int) -> dict:
    """Entry for seed_output/lullabies/lullabies.json (standalone page)."""
    return {
        "id": LULLABY["id"],
        "title": LULLABY["title_roman"],
        "title_deva": LULLABY["title_deva"],
        "lullaby_type": LULLABY["lullaby_type"],
        "card_label": LULLABY["card_label_roman"],
        "card_subtitle": LULLABY["card_subtitle_roman"],
        "age_group": LULLABY["age_group"],
        "mood": LULLABY["mood"],
        "lang": "hi",
        "language": "hi",
        "audio_file": f"{LULLABY['id']}.mp3",
        "cover_file": f"{LULLABY['id']}_cover.svg",
        "duration_seconds": duration,
        "lyrics": LULLABY["lyrics_roman"],
        "lyrics_deva": LULLABY["lyrics_deva"],
        "style_prompt": LULLABY["style_prompt"],
        "engine": "minimax-music-v2.5",
        "tts_input_script": "devanagari",
        "character": LULLABY["character"],
        "characterType": LULLABY["lead_character_type_canonical"],
        "instrument": LULLABY["instrument"],
        "imagery": LULLABY["imagery"],
        "theme": LULLABY["theme"],
        "geography": LULLABY["geography"],
        "indian_region": LULLABY["indian_region"],
        "created_at": time.strftime("%Y-%m-%d"),
    }


def upsert_content(entries: list):
    path = BASE_DIR / "seed_output" / "content.json"
    with open(path) as f: data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    ids = {e["id"] for e in entries}
    items = [i for i in items if i.get("id") not in ids]
    items.extend(entries)
    if isinstance(data, dict): data["items"] = items
    else: data = items
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  content.json: +{len(entries)} upserted (total {len(items)})")


def upsert_lullabies_agg(entry: dict):
    path = BASE_DIR / "seed_output" / "lullabies" / "lullabies.json"
    with open(path) as f: agg = json.load(f)
    agg = [x for x in agg if x.get("id") != entry["id"]] + [entry]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    print(f"  lullabies.json: total {len(agg)}")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    # 0. HARD GATE — narrative-craft checklist (§1-§7).
    # See docs/HINDI_SHORT_STORY_GUIDELINES.md.
    from validate_hindi_story import validate_story_dict
    issues = validate_story_dict(STORY)
    if issues:
        print("\n═══ STORY dict fails narrative-craft checklist ═══",
              file=sys.stderr)
        for i in issues:
            print(f"  ❌ {i}", file=sys.stderr)
        print("\nFix the STORY dict before running this script. See "
              "docs/HINDI_SHORT_STORY_GUIDELINES.md for the rules.",
              file=sys.stderr)
        sys.exit(1)
    print("  ✓ narrative-craft checklist (§1-§7) passed")

    # 1. STORY audio re-render with Devanagari
    print("\n═══ STORY audio (ElevenLabs + Devanagari) ═══")
    story_audio = assemble_story_audio(
        STORY["text_deva"], STORY["hook_deva"], STORY["voice"], STORY["mood"])
    story_audio_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{STORY['id']}_{STORY['voice']}.mp3"
    story_audio.export(story_audio_path, format="mp3", bitrate="192k")
    story_duration = round(len(story_audio) / 1000)
    print(f"  → {story_audio_path}  ({story_duration}s)")

    # 2. STORY cover regen with rich English seed
    print("\n═══ STORY cover (rich English + cover-gen taxonomy) ═══")
    regen_story_cover()

    # 3. LULLABY audio re-render with Devanagari lyrics
    print("\n═══ LULLABY audio (MiniMax v2.5 + Devanagari) ═══")
    mp3_bytes = minimax_lullaby(LULLABY["style_prompt"], LULLABY["lyrics_deva"])
    lul_seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
    lul_duration = round(len(lul_seg) / 1000)
    # Write to all 3 audio locations (overwrite).
    for p in [
        BASE_DIR / "seed_output" / "lullabies" / f"{LULLABY['id']}.mp3",
        WEB_ROOT / "public" / "audio" / "lullabies" / f"{LULLABY['id']}.mp3",
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{LULLABY['id']}_female_1.mp3",
    ]:
        with open(p, "wb") as f: f.write(mp3_bytes)
        print(f"  → {p}")
    print(f"  lullaby duration: {lul_duration}s")

    # 4. JSON rewrites
    print("\n═══ JSON upserts ═══")
    s_entry = story_entry(story_duration)
    l_song  = lullaby_song_entry(lul_duration)
    l_agg   = lullaby_agg_entry(lul_duration)
    upsert_content([s_entry, l_song])
    upsert_lullabies_agg(l_agg)

    # per-entry lullaby JSON sibling (kept for parity w/ other lullabies)
    per_entry = BASE_DIR / "seed_output" / "lullabies" / f"{LULLABY['id']}.json"
    with open(per_entry, "w", encoding="utf-8") as f:
        json.dump(l_agg, f, ensure_ascii=False, indent=2)
    print(f"  {per_entry}")

    print("\n═════ LOCAL FIX DONE ═════")
    print(f"  story duration:   {story_duration}s")
    print(f"  lullaby duration: {lul_duration}s")


if __name__ == "__main__":
    main()
