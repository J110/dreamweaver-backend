#!/usr/bin/env python3
"""Generate ONE experimental Hindi story end-to-end.

Uses the SAME assembly pipeline as English V2 short stories (scripts/audio_assembly.py)
with only the deltas required for Hindi to work:
  - TTS backend: Sarvam Bulbul v3 (purpose-built for Indic languages) instead of
    Chatterbox, injected via the tts_fn hook in assemble_v2_audio.
  - Mood → Sarvam speaker map (mirrors English MOOD_VOICES primaries by gender/character).
  - Prompt asks for dual-script (Devanagari TTS + Roman display), danda, folk opener.
  - lead_character_type is explicit (cover generator can't infer from Devanagari names).

All outputs are dropped in  hindi_review/  at the repo root for human review.

Usage:
    python3 scripts/generate_experimental_hindi.py
    python3 scripts/generate_experimental_hindi.py --mood calm --voice anushka
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mistralai import Mistral
from pydub import AudioSegment

sys.path.insert(0, str(Path(__file__).parent))
from audio_assembly import (
    assemble_v2_audio,
    clean_display_text,
    parse_segments,
)

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
REVIEW_DIR = REPO_ROOT / "hindi_review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env", override=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "sk_uglvw84k_eOJq43V6xzSWDeRNPHC6tmeS")
SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "sk_5bbd5d1a1ee9fa532c454154e2a7723f94ffc3bce07087ff")
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# ElevenLabs voice IDs — Hindi bedtime cast (paid shared-library voices).
# Mapped to the 5 English voice roles (calm/soft/melodic/musical/gentle/asmr);
# see HINDI_SHORT_STORY_GUIDELINES.md.
ELEVENLABS_VOICES = {
    # label        voice_id                    english role   character
    "tripti":    "yLldDJzoAIYirDpSiBvy",  # calm              Warm & Captivating (hi)
    "roohi":     "oHNJagRZ2LQEfZb2CEkb",  # soft / asmr       Breathy, Soft & Whisper (hi)
    "anika":     "RABOvaPec1ymXz02oDQi",  # melodic           Sweet, Lively & Warm (hi)
    "gudiya":    "csPuxct3x4tABDZeKliZ",  # musical           Very Young & Sweet Storyteller (hi)
    "meher":     "JS6C6yu2x9Byh4i1a8lX",  # gentle            Deep, Soft & Seductive (hi)
    # Spare — not in the default mapping. Available via --voice for A/B.
    "shreya_g":  "RwXLkVKnRloV1UPh3Ccx",  # Expressive & Conversational (hi)
}

# (mood, age_group) → [voice_1, voice_2]. Same structure as English
# MOOD_VOICES, extended with age. Two complete audio variants are generated
# per story; the app plays one.
HINDI_STORY_VOICE_MAP = {
    # wired
    ("wired",   "2-5"):  ["anika",  "meher"],
    ("wired",   "6-8"):  ["anika",  "meher"],
    ("wired",   "9-12"): ["roohi",  "meher"],
    # curious
    ("curious", "0-1"):  ["gudiya", "meher"],
    ("curious", "2-5"):  ["gudiya", "meher"],
    ("curious", "6-8"):  ["gudiya", "meher"],
    ("curious", "9-12"): ["roohi",  "meher"],
    # calm
    ("calm",    "0-1"):  ["tripti", "roohi"],
    ("calm",    "2-5"):  ["tripti", "roohi"],
    ("calm",    "6-8"):  ["tripti", "roohi"],
    ("calm",    "9-12"): ["tripti", "roohi"],
    # sad
    ("sad",     "2-5"):  ["meher",  "tripti"],
    ("sad",     "6-8"):  ["meher",  "tripti"],
    ("sad",     "9-12"): ["meher",  "tripti"],
    # anxious
    ("anxious", "2-5"):  ["meher",  "tripti"],
    ("anxious", "6-8"):  ["meher",  "roohi"],
    ("anxious", "9-12"): ["meher",  "roohi"],
    # angry
    ("angry",   "2-5"):  ["anika",  "meher"],
    ("angry",   "6-8"):  ["roohi",  "meher"],
    ("angry",   "9-12"): ["roohi",  "meher"],
}
HINDI_DEFAULT_VOICES = ["tripti", "roohi"]

# Long stories: Phase 3 always switches to Roohi (mirrors English's ASMR rule).
HINDI_LONG_STORY_PHASE_3_VOICE = "roohi"

def get_story_voices(mood: str, age_group: str = "6-8") -> list:
    """Resolve [voice_1, voice_2] for a Hindi story — same shape as English
    MOOD_VOICES lookup, just keyed on (mood, age_group)."""
    return HINDI_STORY_VOICE_MAP.get((mood, age_group), HINDI_DEFAULT_VOICES)

# Mood → Sarvam Bulbul v3 speaker. Mirrors English MOOD_VOICES primaries
# (audio_assembly.MOOD_VOICES) by gender + character intent. Picks are
# provisional until listened to — override with --voice.
MOOD_SPEAKER_HI = {
    "wired":   "priya",     # melodic, expressive female (≈ female_3)
    "curious": "kavya",     # musical, lilting female (≈ female_4)
    "calm":    "neha",      # calm, maternal female (≈ female_1)
    "sad":     "aditya",    # gentle, friendly male (≈ male_2)
    "anxious": "aditya",    # gentle male (≈ male_2)
    "angry":   "priya",     # melodic female (≈ female_3)
}

# Full v3-compatible speaker list (probed from API on 2026-04-18):
#   aditya, ritu, ashutosh, priya, neha, rahul, pooja, rohan, simran, kavya,
#   amit, dev, ishita, shreya, ratan, varun, manan, sumit, roopa, kabir, aayan,
#   shubh, advait, anand, tanya, tarun, sunny, mani, gokul, vijay, shruti,
#   suhani, mohit, kavitha, rehan, soham, rupali, niharika


STORY_TYPE_OPENINGS = {
    # story_type → (display name, opener rule, signature sentence pattern)
    "lok_katha": (
        "लोक कथा (folk tale)",
        "OPEN with the classic folk opener 'एक थी…' or 'एक था…' "
        "('Ek thi…' / 'Ek tha…') depending on the character's gender. "
        "This is the signature opener — mandatory. Optionally add "
        "'Suno na bachcho, …' as a second storyteller-framing line.",
        "एक थी / एक था / Suno na bachcho",
    ),
    "prakriti_katha": (
        "प्रकृति कथा (nature tale)",
        "OPEN with a SENSORY IMAGE — sound, smell, temperature, "
        "weather, or light. The child walks into the scene FIRST, "
        "and meets the character SECOND. DO NOT open with 'Suno na "
        "bachcho' or 'Aaj ___ ki kahani' — that's a lok_katha "
        "opener, and using it here is a category error. Example: "
        "'Shaam thi. Hawa thandi thandi chal rahi thi. Peepal ke "
        "bade se ped par, sabse upar wali shaakh par, ek chhoti si "
        "gilhari baithi thi. Naam tha Chiki.'",
        "sensory first (Shaam thi / Hawa thandi / Subah hui / etc.)",
    ),
    "chatur_katha": (
        "चतुर कथा (clever trick tale)",
        "OPEN by stating a problem, mischief, or clever challenge "
        "up front in the first 1–2 sentences. The character faces "
        "something tricky; the body of the story shows how they "
        "solve it cleverly.",
        "problem-first",
    ),
    "mitra_katha": (
        "मित्र कथा (friendship tale)",
        "OPEN with TWO characters already together. Friendship is "
        "visible in the first line. DO NOT start with a lone "
        "character and introduce the friend later.",
        "two-together",
    ),
    "sanskaar_katha": (
        "संस्कार कथा (gentle-virtue tale)",
        "OPEN with a small moment of CHOICE or quiet virtue in "
        "action — sharing, helping, patience. The virtue is shown "
        "through an action, never stated as a lesson.",
        "choice-in-action",
    ),
}


def build_hindi_prompt(mood: str, story_type: str = "lok_katha",
                       age_group: str = "6-8") -> str:
    """Compose the Hindi story prompt with story-type-aware opener rules.

    Rules encoded in the prompt mirror docs/HINDI_SHORT_STORY_GUIDELINES.md
    §4 (signature opening), §5 (2-3 direct addresses), §6 (one specific
    character detail, no species-level generics).
    """
    if story_type not in STORY_TYPE_OPENINGS:
        raise ValueError(
            f"Unknown story_type {story_type!r}. Known: "
            f"{sorted(STORY_TYPE_OPENINGS)}"
        )
    type_label, opener_rule, _ = STORY_TYPE_OPENINGS[story_type]
    return _HINDI_PROMPT_TEMPLATE.format(
        mood=mood, age_group=age_group,
        story_type=story_type, type_label=type_label,
        opener_rule=opener_rule,
    )


_HINDI_PROMPT_TEMPLATE = """You are writing a BEDTIME STORY in HINDI for ages {age_group}.

Mood: {mood}
Story type: {story_type} — {type_label}

This story is meant to be HEARD in bed with eyes closing. Simple, sensory, engaging. 150–300 words.

=== DUAL-SCRIPT OUTPUT ===
You will output the Hindi text TWICE — once in Devanagari (for the TTS engine to read
aloud with correct Hindi pronunciation) and once in Roman/Latin letters (for display in the
app UI). The two versions must be the SAME story, just different scripts.

Devanagari version (for audio): natural spoken Hindi. Sentences end with "।" (danda),
NOT with "." (period). Example:
  "एक थी छोटी सी चींटी। जब चाँद निकलता, वो पत्ते पर बैठ जाती।"

Roman version (for app display): Hinglish — Hindi words in Latin letters, the way Indians type
on WhatsApp. Sentences end with ".". Example:
  "Ek thi chhoti si cheenti. Jab chaand nikalta, vo patte par baith jaati."

Romanization rules: natural chat-style ("mai, hu, raha, chaand, patta, chota"); no diacritics.
The Roman version must SOUND IDENTICAL to the Devanagari version when read aloud.

=== VOICE ===
CONVERSATIONAL, everyday spoken Hindi. NOT literary or Sanskritized. Write the way a parent
actually talks to their child, not a school textbook. Avoid heavy Sanskrit loanwords.

=== STORY-TYPE OPENING SIGNATURE ===
{opener_rule}
Getting the opener wrong is a CATEGORY ERROR — a lok_katha opener on a
prakriti_katha story (or vice versa) miscategorises the story. The
child's ear should recognise the shape of the story within the first
two sentences.

CLOSING: end with a soft, settling closer — something like "और वो सो गई।"
("Aur vo so gayi.") or the story settling into silence.

=== HARD REQUIREMENTS ===
- ONE character does ONE thing. No subplots.
- The final 3–4 sentences should be short fragments that mirror sleep.
- TWO to THREE CLEAN "direct address" moments — narrator speaks TO
  the child (unambiguous). Use phrasings that cannot be mistaken for
  the character's internal thought. Good:
    "तुमने कभी … देखा है?"  / "Tumne kabhi … dekha hai?"
    "तुम्हें पता है … ?"      / "Tumhe pata hai …?"
    "सुनो ज़रा, …"            / "Suno zara, …"
  AVOID ambiguous ones that could be the character thinking:
    "अरे, यह क्या हो रहा है?" → could be the character's surprise.
    Rewrite as "तुम्हें पता है क्या हो रहा था?" (clearly to the listener).
- ONE SPECIFIC endearing detail for the lead character — something
  ONLY they do. Not a generic species trait. Pay it off once in the
  story. Good: "Chiki hamesha sabse upar wali shaakh par baithti thi,
  jahan se saara gaon dikhta tha." Bad: "choti choti aankhein, bhuri
  si dumm" — describes every squirrel.
- AT LEAST TWO onomatopoeia (ध्वनि) instances woven naturally into the story.
  Examples: सर्र सर्र (wind), खट खट (knock/footsteps), गुनगुन (humming),
  टिप टिप (light rain), चीं चीं (insect/bird), थप थप (gentle pats).

=== V2 TAGS ===
Place these tags inside the story text (identical positions in both scripts):

  [MUSIC]          — music swell moment. Place 3–5 times at emotional transitions
                     (arrival of a feeling, reveal, quiet beat). The score swells ~6s
                     under that moment, then settles.
  [PAUSE: 800]     — a silence in milliseconds. Use 800 for a breath, 1500 for a beat
                     before a reveal, 2000 for a slow exhale, 4000 near sleep.
                     Integer ms values only.
  [PHRASE]…[/PHRASE] — a unique short phrase (under 8 words) repeated at least 3 times.
                     Wrap EVERY instance with these tags. Child-friendly, specific to this story.

Tags must appear at EXACTLY the same positions in both Devanagari and Roman versions.

=== OUTPUT FORMAT ===
Output ONLY a JSON object (no prose, no markdown fences) with exactly these keys:

{{
  "title_en":           "English title — Character Name + evocative image, under 8 words.",
  "title_hi_deva":      "CONVERSATIONAL Hindi title in DEVANAGARI. Under 8 words.",
  "title_hi_roman":     "The SAME title in Roman letters (Hinglish). Under 8 words.",
  "hook_en":            "English one-sentence hook, under 15 words.",
  "hook_hi_deva":       "Hindi hook in DEVANAGARI — spoken at start of audio. No markers here.",
  "hook_hi_roman":      "The SAME hook in Roman letters.",
  "cover_context_en":   "English one-sentence description of the scene for cover illustration. Under 25 words.",
  "character_name":     "Lead character's first name (transliterated, e.g. 'Chinti').",
  "character_identity_en": "One English sentence describing the character.",
  "lead_character_type": "ONE of: human, animal, bird, sea_creature, insect, plant, celestial, atmospheric, mythical, object, alien, robot.",
  "repeated_phrase_deva":  "The Devanagari repeating phrase (content only, no tags).",
  "repeated_phrase_roman": "The SAME phrase in Roman letters (content only, no tags).",
  "text_hi_deva":       "Full story in DEVANAGARI with [MUSIC], [PAUSE: ms], [PHRASE]...[/PHRASE] tags. Sentences end with ।. This is fed to Chatterbox.",
  "text_hi_roman":      "The SAME story in Roman letters with tags at the SAME positions. Sentences end with ."
}}

Return ONLY the JSON. No preamble, no trailing text.
"""


def call_mistral(prompt: str, max_tokens: int = 2500) -> str:
    client = Mistral(api_key=MISTRAL_API_KEY)
    for attempt in range(3):
        try:
            resp = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": "You write bedtime stories. When asked for JSON, return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.85,
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  Mistral attempt {attempt+1}: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(6)
    raise RuntimeError("Mistral API failed")


def _extract_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    start = s.find("{")
    if start < 0:
        raise ValueError(f"No JSON object found in Mistral output:\n{raw[:400]}")
    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
    if end < 0:
        raise ValueError(f"Unmatched JSON braces in Mistral output:\n{raw[:400]}")
    return json.loads(s[start:end + 1], strict=False)


# ── Sarvam Bulbul TTS ───────────────────────────────────────────────────
# Bulbul v3 pace range is 0.5–2.0 (1.0 = natural). The English pipeline's
# role-specific speeds (HOOK=0.82, NORMAL=0.85, PHRASE=0.78) carry the same
# semantic meaning — slightly slower than natural for bedtime delivery.

SARVAM_SAMPLE_RATE = 44100   # matches intro/bed/outro music beds (44.1 kHz stereo)
HINDI_PACE_SCALE = 1.15      # scale English speed params up; Sarvam default is 1.0


def _sarvam_tts(text: str, speaker: str, pace: float) -> AudioSegment:
    payload = {
        "text": text,
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": speaker,
        "pace": float(pace),
        "speech_sample_rate": SARVAM_SAMPLE_RATE,
    }
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.post(SARVAM_URL, json=payload, headers=headers, timeout=180.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("audios"):
                        wav_bytes = base64.b64decode(data["audios"][0])
                        return AudioSegment.from_wav(io.BytesIO(wav_bytes))
                print(f"    Sarvam {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            except Exception as e:
                print(f"    Sarvam error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Sarvam TTS failed speaker={speaker} text={text[:40]}")


DEVA_TERMINATORS = ("।", ".", "!", "?", "…")

def _ensure_terminal_danda(text: str) -> str:
    """Sarvam hallucinates trailing syllables when input lacks terminal punctuation.
    Repeated phrases like 'चाँद सो जा, चाँद सो जा' end on a comma, prompting the
    model to keep generating. A trailing danda signals 'done, stop'."""
    stripped = text.rstrip()
    if stripped.endswith(DEVA_TERMINATORS):
        return stripped
    return stripped + "।"


def make_sarvam_tts_fn(speaker: str):
    """Build a tts_fn for audio_assembly.assemble_v2_audio backed by Sarvam Bulbul.

    English Chatterbox speed params (0.82/0.85/0.78) are scaled by HINDI_PACE_SCALE
    so bedtime delivery feels calm without dragging — Sarvam default is 1.0x."""
    def _fn(text: str, voice: str, role: str, is_phrase: bool, tts_params: dict):
        pace = min(2.0, float(tts_params.get("speed", 0.85)) * HINDI_PACE_SCALE)
        # Don't inject the Chatterbox "... " breath-prefix — Sarvam handles
        # phrasing natively. Instead ensure the text ends on a clear terminator
        # so the model stops cleanly (fixes post-phrase hallucination).
        effective_text = _ensure_terminal_danda(text) if is_phrase else text
        print(f"    [sarvam] role={role} speaker={speaker} pace={pace:.2f} len={len(effective_text)}")
        return _sarvam_tts(effective_text, speaker, pace)
    return _fn


# ── ElevenLabs multilingual TTS ─────────────────────────────────────────
# 3 fixed param sets — ElevenLabs equivalent of English Chatterbox's
# NORMAL / HOOK / PHRASE. Same voice throughout the story; only these
# settings change per role. No phase-based voice switching.

HINDI_TTS_PARAMS = {
    "text":   {"stability": 0.70, "style": 0.00, "speed": 0.85},  # NORMAL
    "hook":   {"stability": 0.60, "style": 0.05, "speed": 0.88},  # HOOK (opening energy)
    "phrase": {"stability": 0.80, "style": 0.00, "speed": 0.78},  # PHRASE (slower, warmer)
}


def _elevenlabs_tts(text: str, voice_id: str, stability: float,
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
    # previous_text/next_text give the model tonal context across chunks —
    # prevents abrupt mood resets between adjacent [TEXT] blocks.
    if previous_text:
        payload["previous_text"] = previous_text[-500:]
    if next_text:
        payload["next_text"] = next_text[:500]
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    url = ELEVENLABS_URL.format(voice_id=voice_id) + "?output_format=mp3_44100_128"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.post(url, json=payload, headers=headers, timeout=180.0)
                if resp.status_code == 200:
                    return AudioSegment.from_file(io.BytesIO(resp.content), format="mp3")
                print(f"    ElevenLabs {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
            except Exception as e:
                print(f"    ElevenLabs error: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"ElevenLabs TTS failed voice_id={voice_id} text={text[:40]}")


def make_elevenlabs_tts_fn(voice_label: str):
    """Build a tts_fn with a single voice for the whole story. Param set
    (NORMAL/HOOK/PHRASE) switches by role — same voice throughout."""
    voice_id = ELEVENLABS_VOICES.get(voice_label, voice_label)

    def _fn(text: str, voice: str, role: str, is_phrase: bool, tts_params: dict):
        preset = HINDI_TTS_PARAMS[role]
        effective_text = _ensure_terminal_danda(text) if is_phrase else text
        print(f"    [11labs] role={role} voice={voice_label} "
              f"stab={preset['stability']:.2f} style={preset['style']:.2f} "
              f"speed={preset['speed']:.2f} len={len(effective_text)}")
        return _elevenlabs_tts(
            effective_text, voice_id,
            stability=preset["stability"],
            similarity=0.75,
            style=preset["style"],
            speed=preset["speed"],
            previous_text=tts_params.get("prev_text", ""),
            next_text=tts_params.get("next_text", ""),
        )
    return _fn


def build_tts_fn(engine: str, speaker: str):
    if engine == "sarvam":
        return make_sarvam_tts_fn(speaker)
    if engine == "elevenlabs":
        return make_elevenlabs_tts_fn(speaker)
    raise ValueError(f"Unknown TTS engine: {engine}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mood", default="calm",
                        choices=list(MOOD_SPEAKER_HI.keys()))
    parser.add_argument("--engine", default="sarvam",
                        choices=["sarvam", "elevenlabs"],
                        help="TTS backend (default: sarvam)")
    parser.add_argument("--voice", default=None,
                        help="Override speaker. Sarvam: neha/priya/... "
                             "ElevenLabs: tripti/roohi/anika/gudiya/meher/shreya_g")
    parser.add_argument("--voice-slot", default=1, type=int, choices=[1, 2],
                        help="Which slot in HINDI_STORY_VOICE_MAP[(mood,age)] "
                             "to use when --voice is not set (1 or 2). "
                             "English generates both; we render one at a time for review.")
    parser.add_argument("--from-story", default=None,
                        help="Re-render an existing story JSON with a new voice. "
                             "Skips Mistral + cover generation.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate text + save JSON only, skip audio/cover")
    parser.add_argument("--story-type", default="lok_katha",
                        choices=list(STORY_TYPE_OPENINGS.keys()),
                        help="Story-type signature that dictates the "
                             "opening beat (see docs/HINDI_SHORT_STORY_"
                             "GUIDELINES.md §4).")
    parser.add_argument("--age-group", default="6-8",
                        choices=["0-1", "2-5", "6-8", "9-12"],
                        help="Target age bucket for vocabulary + pacing.")
    parser.add_argument("--max-craft-retries", type=int, default=3,
                        help="How many times to re-ask Mistral if the "
                             "output fails the §1-§7 narrative-craft "
                             "validator.")
    args = parser.parse_args()

    # ── Voice A/B mode ───────────────────────────────────────────────
    if args.from_story:
        src_path = Path(args.from_story)
        if not src_path.is_absolute():
            src_path = REVIEW_DIR / src_path if not src_path.exists() else src_path
        if not src_path.exists():
            print(f"Story JSON not found: {src_path}", file=sys.stderr)
            sys.exit(1)
        story_json = json.loads(src_path.read_text(encoding="utf-8"))
        story_id = story_json["id"]
        mood = story_json.get("mood", args.mood)
        age_group = story_json.get("age_group", "6-8")
        if args.engine == "elevenlabs":
            voices = get_story_voices(mood, age_group)
            default_speaker = voices[args.voice_slot - 1]
        else:
            default_speaker = MOOD_SPEAKER_HI[mood]
        speaker = args.voice or default_speaker
        print(f"═════ Re-render (voice A/B) ═════")
        print(f"id={story_id}  mood={mood}  engine={args.engine}  speaker={speaker}  src={src_path}")

        segments = parse_segments(story_json["raw_text_deva"])
        seg_counts = {}
        for stype, _ in segments:
            seg_counts[stype] = seg_counts.get(stype, 0) + 1
        print(f"Parsed: {seg_counts}")

        tts_fn = build_tts_fn(args.engine, speaker)
        with_music, without_music = assemble_v2_audio(
            segments=segments,
            voice=speaker,
            mood=mood,
            hook=story_json["description_deva"],
            tts_fn=tts_fn,
        )
        tag = f"{args.engine}_{speaker}"
        with_music_path = REVIEW_DIR / f"{story_id}_{tag}_with_music.mp3"
        without_music_path = REVIEW_DIR / f"{story_id}_{tag}_narration_only.mp3"
        with_music.export(with_music_path, format="mp3", bitrate="192k")
        without_music.export(without_music_path, format="mp3", bitrate="192k")
        print(f"  With music:    {with_music_path} ({len(with_music)/1000:.1f}s)")
        print(f"  Narration only: {without_music_path} ({len(without_music)/1000:.1f}s)")
        return

    mood = args.mood
    if args.engine == "elevenlabs":
        voices = get_story_voices(mood, "6-8")
        default_speaker = voices[args.voice_slot - 1]
    else:
        default_speaker = MOOD_SPEAKER_HI[mood]
    speaker = args.voice or default_speaker
    story_id = f"exph-{uuid.uuid4().hex[:12]}"

    print(f"═════ Hindi experimental story ═════")
    print(f"id={story_id}  mood={mood}  engine={args.engine}  speaker={speaker}")

    # ── 1. Generate story text (with narrative-craft gate) ───────────
    print(f"\n[1/4] Mistral → Hindi story text  "
          f"(story_type={args.story_type}, age_group={args.age_group})")
    sys.path.insert(0, str(Path(__file__).parent))
    from validate_hindi_story import (
        validate_story_dict, CANONICAL_CHARACTER_TYPES,
    )
    # Map cover-gen 12 → canonical 11 for validator (LLM emits cover-gen
    # taxonomy per the prompt; canonical is stored downstream).
    COVER_TO_CANONICAL = {
        "animal": "land_mammal", "bird": "bird",
        "sea_creature": "sea_creature", "insect": "insect",
        "human": "human_child", "mythical": "mythical_creature",
        "object": "object_alive", "plant": "plant_tree",
        "celestial": "celestial_weather", "atmospheric": "celestial_weather",
        "alien": "mythical_creature", "robot": "robot_mechanical",
    }

    required = [
        "title_en", "title_hi_deva", "title_hi_roman",
        "hook_en", "hook_hi_deva", "hook_hi_roman",
        "cover_context_en", "character_name", "character_identity_en",
        "repeated_phrase_deva", "repeated_phrase_roman",
        "text_hi_deva", "text_hi_roman",
        "lead_character_type",
    ]

    base_prompt = build_hindi_prompt(mood, args.story_type, args.age_group)
    story = None
    last_issues: list[str] = []
    for attempt in range(args.max_craft_retries):
        prompt = base_prompt
        if attempt > 0 and last_issues:
            # Feed the violations back to Mistral so it can fix them.
            prompt = base_prompt + (
                "\n\n=== PREVIOUS ATTEMPT FAILED THE CRAFT CHECKLIST ===\n"
                "Your previous response violated these rules:\n"
                + "\n".join(f"  - {i}" for i in last_issues)
                + "\n\nRewrite the story to FIX every one of these "
                "issues. Do not preserve the previous text; regenerate."
            )
        raw = call_mistral(prompt)
        try:
            candidate = _extract_json(raw)
        except Exception as e:
            print(f"  attempt {attempt+1}: JSON parse failed: {e}",
                  file=sys.stderr)
            last_issues = [f"JSON parse error: {e}"]
            continue
        missing = [k for k in required if not candidate.get(k)]
        if missing:
            last_issues = [f"missing key: {k}" for k in missing]
            print(f"  attempt {attempt+1}: missing keys {missing}",
                  file=sys.stderr)
            continue
        # Shim into STORY-dict shape for validate_story_dict(…).
        cover_ct = candidate.get("lead_character_type", "")
        canonical_ct = COVER_TO_CANONICAL.get(cover_ct, cover_ct)
        shim = {
            "title_roman": candidate["title_hi_roman"],
            "title_deva":  candidate["title_hi_deva"],
            "hook_roman":  candidate["hook_hi_roman"],
            "hook_deva":   candidate["hook_hi_deva"],
            "text_roman":  candidate["text_hi_roman"],
            "text_deva":   candidate["text_hi_deva"],
            "story_type":  args.story_type,
            "character": {
                "name":      candidate["character_name"],
                "identity":  candidate["character_identity_en"],
                "special":   "",
                "personality_tags": [],
            },
            "lead_character_type_canonical": canonical_ct,
        }
        issues = validate_story_dict(shim)
        if not issues:
            story = candidate
            print(f"  attempt {attempt+1}: ✅ passes §1-§7 craft checklist")
            break
        last_issues = issues
        print(f"  attempt {attempt+1}: ❌ craft violations:",
              file=sys.stderr)
        for i in issues:
            print(f"    - {i}", file=sys.stderr)

    if story is None:
        print(f"\n  ❌ Mistral failed the craft checklist after "
              f"{args.max_craft_retries} attempts. Last issues:",
              file=sys.stderr)
        for i in last_issues:
            print(f"    - {i}", file=sys.stderr)
        sys.exit(1)

    story_json = {
        "id": story_id,
        "type": "STORY",
        "lang": "hi",
        "title": story["title_hi_roman"],
        "title_deva": story["title_hi_deva"],
        "title_en": story["title_en"],
        "description": story["hook_hi_roman"],
        "description_deva": story["hook_hi_deva"],
        "description_en": story["hook_en"],
        "cover_context": story["cover_context_en"],
        "character_name": story["character_name"],
        "character_identity": story["character_identity_en"],
        "lead_character_type": story["lead_character_type"],
        "repeated_phrase": story["repeated_phrase_roman"],
        "repeated_phrase_deva": story["repeated_phrase_deva"],
        "text": clean_display_text(story["text_hi_roman"]),
        "text_deva": clean_display_text(story["text_hi_deva"]),
        "raw_text": story["text_hi_roman"],
        "raw_text_deva": story["text_hi_deva"],
        "mood": mood,
        "story_type": "folk_tale",
        "age_group": "6-8",
        "experimental_v2": True,
        "has_baked_music": True,
        "tts_engine": "sarvam_bulbul_v3" if args.engine == "sarvam" else "elevenlabs_multilingual_v2",
        "cover": f"/covers/{story_id}.svg",
    }

    json_path = REVIEW_DIR / f"{story_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(story_json, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {json_path}")
    print(f"  Title (EN):    {story['title_en']}")
    print(f"  Title (Deva):  {story['title_hi_deva']}")
    print(f"  Title (Roman): {story['title_hi_roman']}")

    if args.dry_run:
        print("\nDry run — skipping audio and cover.")
        return

    # ── 2. Parse segments (Devanagari — fed to Sarvam) ───────────────
    segments = parse_segments(story["text_hi_deva"])
    seg_counts = {}
    for stype, _ in segments:
        seg_counts[stype] = seg_counts.get(stype, 0) + 1
    print(f"\n[2/4] Parsed: {seg_counts}")

    # ── 3. Synthesize + assemble audio via shared v2 assembler ───────
    engine_label = "Sarvam Bulbul v3" if args.engine == "sarvam" else "ElevenLabs multilingual v2"
    print(f"\n[3/4] {engine_label} → Hindi TTS + music assembly (speaker={speaker})")
    tts_fn = build_tts_fn(args.engine, speaker)
    with_music, without_music = assemble_v2_audio(
        segments=segments,
        voice=speaker,
        mood=mood,
        hook=story["hook_hi_deva"],
        tts_fn=tts_fn,
    )
    tag = f"{args.engine}_{speaker}"
    with_music_path = REVIEW_DIR / f"{story_id}_{tag}_with_music.mp3"
    without_music_path = REVIEW_DIR / f"{story_id}_{tag}_narration_only.mp3"
    with_music.export(with_music_path, format="mp3", bitrate="192k")
    without_music.export(without_music_path, format="mp3", bitrate="192k")
    print(f"  With music:    {with_music_path} ({len(with_music)/1000:.1f}s)")
    print(f"  Narration only: {without_music_path} ({len(without_music)/1000:.1f}s)")

    story_json["audio_variants"] = [{
        "voice": speaker,
        "url": f"/audio/pre-gen/{story_id}_{speaker}.mp3",
        "duration_seconds": round(len(with_music) / 1000, 1),
    }]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(story_json, f, ensure_ascii=False, indent=2)

    # ── 4. Cover ─────────────────────────────────────────────────────
    print("\n[4/4] Generating cover (FLUX + SVG overlay)")
    cover_script = BASE_DIR / "scripts" / "generate_cover_experimental.py"
    cmd = [
        sys.executable, str(cover_script),
        "--story-json", str(json_path),
        "--mood", mood,
        "--story-type", "folk_tale",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Cover generation FAILED:\n{result.stderr[-1500:]}", file=sys.stderr)
    else:
        print(result.stdout.split("=== COVER GENERATED ===")[-1] if "=== COVER" in result.stdout else result.stdout[-1200:])

    cover_source = BASE_DIR / "seed_output" / "covers_experimental"
    for suffix in ("_combined.svg", "_background.webp", "_preview.html"):
        src = cover_source / f"{story_id}{suffix}"
        if src.exists():
            dst = REVIEW_DIR / f"{story_id}{suffix}"
            dst.write_bytes(src.read_bytes())
            print(f"  Copied: {dst}")

    print(f"\n═════ DONE — review at: {REVIEW_DIR} ═════")


if __name__ == "__main__":
    main()
