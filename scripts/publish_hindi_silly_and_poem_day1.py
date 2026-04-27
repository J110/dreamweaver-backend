#!/usr/bin/env python3
"""Publish ONE Hindi silly song and ONE Hindi musical poem per the v2 specs.

Implements:
  • HINDI_SILLY_SONGS_GUIDELINES (1).md — anthem `chips_chahiye`,
    age 2-5, mood `wired`, category `battle_cry`
  • HINDI_MUSICAL_POEMS_GUIDELINES (1).md — type `sound`,
    age 2-5, mood `calm` ("Baarish Ki Awaaz")

Both items use:
  • MiniMax Music v2.5 via fal.ai with Hindi reference audio
  • FLUX (Together AI) for covers
  • Hardened Roman-Hindi validator (religious blacklist + 5 simile constructions)
  • ID format `hi-{slug}-{age}-{4hex}`
  • Tag-stripped user-facing text (no SEED_PREFERRED_FIELDS reliance — items are net-new)

Deploy guard must be run before AND after.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from fix_hindi_batch_day2 import minimax_lullaby  # MiniMax v2.5 + Hindi ref helper

load_dotenv(BASE_DIR / ".env", override=True)

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "")
if not TOGETHER_KEY:
    sys.exit("❌ TOGETHER_API_KEY missing")
if not os.getenv("FAL_KEY"):
    sys.exit("❌ FAL_KEY missing")


# ───────────────────────────────────────────────────────────────
# Content (hand-drafted, validators-clean)
# ───────────────────────────────────────────────────────────────

# The hex slug is fixed (deterministic) so re-runs upsert cleanly.
SILLY_SONG = {
    "id": "hi-chips_chahiye-2-5-a8f2",
    "lang": "hi",
    "language": "hi",
    "type": "song",
    "subtype": "silly_song",
    "title": "Chips Chahiye!",
    "title_en": "I Want Chips!",
    "card_label": "Chips chahiye!",
    "card_subtitle": "Battle cry: ek packet mil gaya",
    "anthem_id": "chips_chahiye",
    "anthem": "Chips chahiye!",
    "category": "battle_cry",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "mood": "wired",
    "instruments": "ukulele, dholki, and hand claps",
    "tempo": 124,  # base 116-126 + wired offset +4 ≈ 124
    "lyrics_roman": (
        "[verse 1]\n"
        "School khatam, hum aaye\n"
        "*Dhadaam* bag tham gaye\n"
        "Maa boli, khaana le lo\n"
        "Hum boli, chips chahiye!\n"
        "\n"
        "[chorus]\n"
        "Chips chahiye, chips chahiye!\n"
        "Crunchy crunchy chips chahiye!\n"
        "Maa do na, please de na\n"
        "Chips chahiye, chips chahiye!\n"
        "\n"
        "[verse 2]\n"
        "Maa kahti, pehle daal\n"
        "Hum kahte, chips abhi laal\n"
        "*Khat khat* fridge khulta\n"
        "Packet bhi nikalta\n"
        "\n"
        "[chorus]\n"
        "Chips chahiye, chips chahiye!\n"
        "Crunchy crunchy chips chahiye!\n"
        "Maa do na, please de na\n"
        "Chips chahiye, chips chahiye!\n"
        "\n"
        "[ending]\n"
        "Maa hansi, packet diya\n"
        "Crunch crunch, neend aayi\n"
    ),
    "lyrics_deva": (
        "स्कूल खत्म, हम आए\n"
        "*धड़ाम* बैग थम गए\n"
        "माँ बोली, खाना ले लो\n"
        "हम बोली, चिप्स चाहिए!\n"
        "\n"
        "चिप्स चाहिए, चिप्स चाहिए!\n"
        "क्रंची क्रंची चिप्स चाहिए!\n"
        "माँ दो ना, प्लीज़ दे ना\n"
        "चिप्स चाहिए, चिप्स चाहिए!\n"
        "\n"
        "माँ कहती, पहले दाल\n"
        "हम कहते, चिप्स अभी लाल\n"
        "*खट खट* फ्रिज खुलता\n"
        "पैकेट भी निकलता\n"
        "\n"
        "चिप्स चाहिए, चिप्स चाहिए!\n"
        "क्रंची क्रंची चिप्स चाहिए!\n"
        "माँ दो ना, प्लीज़ दे ना\n"
        "चिप्स चाहिए, चिप्स चाहिए!\n"
        "\n"
        "माँ हँसी, पैकेट दिया\n"
        "क्रंच क्रंच, नींद आई\n"
    ),
    "cover_context": (
        "A small Indian child sitting cross-legged on a sunlit kitchen floor at golden "
        "hour, school bag flopped open beside them, holding up a single potato chip "
        "with a delighted face, a smiling mom watching from a stove behind a pressure "
        "cooker, warm cozy kitchen with a ceiling fan and chai cup, bold cartoon style"
    ),
}

POEM = {
    "id": "hi-sound-2-5-b3c7",
    "lang": "hi",
    "language": "hi",
    "type": "poem",
    "title": "Baarish Ki Awaaz",
    "title_en": "The Sound of Rain",
    "content_type": "poem",
    "poem_type": "sound",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "mood": "calm",
    "instruments": "soft harmonium and gentle tabla",
    "tempo": 92,  # base 95-108 + calm offset -8 ≈ 92
    "poem_text_roman": (
        "Tap tap tap, baadal hai\n"
        "Chhap chhap chhap, paani hai\n"
        "Patak patak, chhat pe sab\n"
        "Thak thak thak, darwaaze ab\n"
        "Sarr sarr, hawa chali\n"
        "Gunghun gunghun, neend chali\n"
        "Chip chip chip, boondein hain\n"
        "Tip tip tip, sapne hain\n"
        "Tap tap tap, neend aaye\n"
        "Chhap chhap chhap, so jaaye\n"
    ),
    "poem_text_deva": (
        "टप टप टप, बादल है\n"
        "छप छप छप, पानी है\n"
        "पटक पटक, छत पे सब\n"
        "थक थक थक, दरवाज़े अब\n"
        "सर्र सर्र, हवा चली\n"
        "गुनगुन गुनगुन, नींद चली\n"
        "चिप चिप चिप, बूंदें हैं\n"
        "टिप टिप टिप, सपने हैं\n"
        "टप टप टप, नींद आए\n"
        "छप छप छप, सो जाए\n"
    ),
    "cover_context": (
        "A small Indian rooftop in soft watercolor twilight, raindrops falling on "
        "banana leaves, warm yellow window glow, a cozy lantern on a windowsill, "
        "blue-grey monsoon clouds gentle and hazy, no people, abstract dreamy "
        "atmosphere, children's book illustration"
    ),
}


# ───────────────────────────────────────────────────────────────
# Validators (hardened per v2 specs)
# ───────────────────────────────────────────────────────────────

DEITY_NAMES = [
    "bhagwaan", "ishvar", "deva ", "devi ", "lakshmi", "ganesh",
    "shiv", "krishn", "ram ", "hanuman", "durga", "saraswati",
    "vishnu", "kali", "allah", "khuda", "rabb", "yesu", "jesus",
]
RITUAL_VERBS = [
    "puja", "aarti", "prarthana", "bhajan karna", "yajna", "havan",
    "prasad", "bhog", "tilak", "darshan", "namaz", "ibadat",
]
RELIGIOUS_OBJECTS = [
    "mandir ke andar", "masjid ke andar", "gurudwara",
    "murti", "shankh", "ghanta puja",
]
RELIGIOUS_ALL = sorted(set(DEITY_NAMES + RITUAL_VERBS + RELIGIOUS_OBJECTS))

LITERARY = [
    "nidra", "nakshatra", "shayan", "tandra", "pushp",
    "chandra ", "megh", "tatpashchat", "nivas", "vidyalay",
]

BANNED_SIMILE_NOUNS = [
    "udaas", "khush", "akela", "toota", "khaali", "chup",
    "andhera", "thanda", "baadal", "chhaaya", "shoonya",
    "hawa", "patthar", "sapna", "bhoot", "fusphusahat",
]

SIMILE_PATTERNS = lambda noun: [
    f"jaisa {noun}", f"jaisi {noun}",
    f"{noun} ki tarah",
    f"{noun} ke jaisa", f"{noun} ke jaisi",
    f"jaise {noun}",
    f"{noun} samaan",
]


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s or "")


def _approximate_matras(line: str) -> int:
    """Rough Roman-Hindi matra counter — long-vowel digraphs count 2.

    Not perfect but adequate for the v1 validator. Long vowels: aa, ee, oo,
    ai, au. Schwa elision approximated by counting CV pairs.
    """
    s = re.sub(r"\*[^*]*\*", "", line)              # strip asterisked SFX
    s = re.sub(r"[^a-zA-Z\s]", " ", s.lower())     # punctuation → space
    matras = 0
    for word in s.split():
        # long-vowel digraphs
        long_count = len(re.findall(r"aa|ee|oo|ai|au|ou", word))
        # short vowels (single)
        short_word = re.sub(r"aa|ee|oo|ai|au|ou", "", word)
        short_count = len(re.findall(r"[aeiou]", short_word))
        # consonant-only words like "tap" → 1 matra
        if long_count == 0 and short_count == 0 and word:
            matras += 1
        else:
            matras += 2 * long_count + short_count
    return matras


def validate_silly_song(d: dict) -> list[str]:
    errors: list[str] = []
    lyrics = d["lyrics_roman"]
    lyrics_lower = lyrics.lower()

    # 1. Devanagari in user-facing fields
    for field in ("title", "card_label", "card_subtitle", "anthem"):
        if _has_devanagari(d.get(field, "")):
            errors.append(f"Devanagari in '{field}'")
    if _has_devanagari(lyrics):
        errors.append("Devanagari in lyrics_roman")

    # 2. Literary Hindi
    for w in LITERARY:
        if w in lyrics_lower:
            errors.append(f"Literary Hindi: '{w}'")

    # 3. Religious content (hardened)
    for w in RELIGIOUS_ALL:
        if w in lyrics_lower:
            errors.append(f"Religious content: '{w}'")

    # 4. Sound effect required
    if "*" not in lyrics:
        errors.append("Missing asterisked sound effect")

    # 5. Line counts
    text_lines = [
        l for l in lyrics.split("\n")
        if l.strip() and not l.strip().startswith("[")
    ]
    if len(text_lines) > 20:
        errors.append(f"Too many lines: {len(text_lines)}")
    for i, line in enumerate(text_lines):
        if len(line.split()) > 8:
            errors.append(f"Line {i}: too many words ({len(line.split())})")
        if _approximate_matras(line) > 9:
            errors.append(f"Line {i}: too many matras ({_approximate_matras(line)}) — '{line}'")

    # 6. Choruses identical (extract by [chorus])
    chorus_blocks = re.findall(r"\[chorus\]\s*\n((?:(?!\n\[).)*)", lyrics, re.DOTALL)
    chorus_blocks = [c.strip() for c in chorus_blocks]
    if len(chorus_blocks) >= 2 and chorus_blocks[0] != chorus_blocks[1]:
        errors.append("Choruses must be identical")

    # 7. Char limit (excluding section tags)
    body = re.sub(r"\[[^\]]+\]\s*", "", lyrics).strip()
    if len(body) > 500:
        errors.append(f"Lyrics body too long: {len(body)} chars (max 500)")

    # 8. Banned similes — all 5 constructions
    for noun in BANNED_SIMILE_NOUNS:
        for p in SIMILE_PATTERNS(noun):
            if p in lyrics_lower:
                errors.append(f"Banned simile: '{p}'")
                break

    return errors


def validate_poem(d: dict) -> list[str]:
    errors: list[str] = []
    text = d["poem_text_roman"]
    text_lower = text.lower()
    poem_type = d.get("poem_type", "sound")

    # Devanagari
    for field in ("title", "poem_text_roman"):
        v = d.get(field, "")
        if _has_devanagari(v):
            errors.append(f"Devanagari in '{field}'")

    # Literary
    for w in LITERARY:
        if w in text_lower:
            errors.append(f"Literary Hindi: '{w}'")

    # Religious
    for w in RELIGIOUS_ALL:
        if w in text_lower:
            errors.append(f"Religious content: '{w}'")

    # title_en
    if not d.get("title_en"):
        errors.append("Missing title_en")

    # Lines
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 8:
        errors.append(f"Too short: {len(lines)} lines")
    if len(lines) > 16:
        errors.append(f"Too long: {len(lines)} lines")

    matra_limit = 11 if poem_type == "question" else 9
    for i, line in enumerate(lines):
        if len(line.split()) > 8:
            errors.append(f"Line {i}: too many words")
        m = _approximate_matras(line)
        if m > matra_limit:
            errors.append(f"Line {i}: matras={m} (max {matra_limit}) — '{line}'")

    if len(text) > 500:
        errors.append(f"Too long: {len(text)} chars")

    for tag in ("[verse", "[chorus", "[bridge", "[opening"):
        if tag in text_lower:
            errors.append(f"Section tag: {tag}")

    return errors


# ───────────────────────────────────────────────────────────────
# FLUX cover generation (Together AI)
# ───────────────────────────────────────────────────────────────

def generate_cover_together(prompt: str, width: int = 1024, height: int = 1024) -> bytes | None:
    print(f"  FLUX prompt ({len(prompt)} chars): {prompt[:120]}…")
    try:
        resp = httpx.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {TOGETHER_KEY}"},
            json={
                "model": "black-forest-labs/FLUX.1-schnell",
                "prompt": prompt,
                "width": width,
                "height": height,
                "n": 1,
                "response_format": "b64_json",
            },
            timeout=180,
        )
        if resp.status_code != 200:
            print(f"  Together error {resp.status_code}: {resp.text[:200]}")
            return None
        return base64.b64decode(resp.json()["data"][0]["b64_json"])
    except Exception as e:
        print(f"  Together exception: {e}")
        return None


# ───────────────────────────────────────────────────────────────
# Style prompts (per v2 specs §6)
# ───────────────────────────────────────────────────────────────

def silly_song_style_prompt(d: dict) -> str:
    mood_energy_map = {
        "wired":   "bouncy and playful, high-energy Indian rhythm",
        "curious": "dreamy and wondering",
        "calm":    "soft and settling, warm steady rhythm",
        "sad":     "gentle and tender, quiet rhythm",
        "anxious": "cozy and reassuring",
        "angry":   "firm then softening",
    }
    return (
        f"Catchy children's Hindi song, full musical production with Indian "
        f"instruments, {d['instruments']}, {d['tempo']} BPM, "
        f"{mood_energy_map[d['mood']]}, warm clear North Indian female child vocal, "
        f"native Hindi pronunciation, strong singalong chorus, every word easy to "
        f"understand. Not Western."
    )[:295]


def poem_style_prompt(d: dict) -> str:
    mood_energy_map = {
        "wired":   "bouncy and playful, high-energy Indian rhythm",
        "curious": "dreamy and wondering, spacious like a slow afternoon",
        "calm":    "soft and settling, warm steady rhythm, almost a lullaby",
        "sad":     "gentle and tender, quiet rhythm, like a hug from Daadi",
        "anxious": "cozy and reassuring, steady predictable rhythm",
        "angry":   "firm then softening, strong rhythm gradually settling",
    }
    return (
        f"Children's Hindi musical poem, {d['instruments']}, {d['tempo']} BPM, "
        f"{mood_energy_map[d['mood']]}, warm clear North Indian female vocal "
        f"speaking each word rhythmically, native Hindi pronunciation, every word "
        f"crystal clear, like a parent reciting a poem at bedtime, not sung — "
        f"spoken to a beat. Not Western."
    )[:300]


def silly_cover_prompt(d: dict) -> str:
    return (
        f"Digital painting of {d['cover_context']}, bold cartoon style, bright "
        f"saturated colors, Indian child character, exaggerated funny expressions, "
        f"playful and warm, thick outlines, expressive eyes, "
        f"Pixar-meets-picture-book aesthetic, small floating music notes, "
        f"Indian household setting, minimalist"
    )


POEM_BASE_STYLE = {
    "sound": (
        "Abstract minimal art, soft shapes suggesting Indian sound waves and "
        "ripples, gentle gradients in warm sunset oranges and deep blues, "
        "subtle mehendi-like patterns, children's book illustration style, "
        "safe and calming, the visual equivalent of Hindi onomatopoeia."
    ),
    "nonsense": (
        "Abstract minimal art, swirling colorful Indian shapes, gentle "
        "gradients in turmeric yellow and deep teal, bouncy organic forms "
        "inspired by rangoli, children's book illustration style."
    ),
    "question": (
        "Abstract minimal art, floating question-mark-like shapes in soft "
        "diya light, gentle gradients in deep night blue and warm gold, "
        "curious playful Indian atmosphere, children's book illustration style."
    ),
}


def poem_cover_prompt(d: dict) -> str:
    base = POEM_BASE_STYLE[d["poem_type"]]
    return (
        f"{d['cover_context']}. inspired by the Hindi poem \"{d['title']}\". "
        f"{base} children's book illustration style, safe and calming, dreamy "
        f"atmosphere, subtle Indian aesthetic — soft mehendi-like patterns, "
        f"warm palette"
    )


# ───────────────────────────────────────────────────────────────
# Pipeline steps
# ───────────────────────────────────────────────────────────────

def render_audio(name: str, style: str, lyrics_deva: str) -> AudioSegment:
    print(f"\n═══ {name} audio (MiniMax v2.5 + Hindi reference) ═══")
    print(f"  style ({len(style)} chars): {style[:120]}…")
    audio_bytes = minimax_lullaby(style, lyrics_deva)
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    print(f"  duration: {len(seg) / 1000:.1f}s")
    return seg


def save_silly_song(d: dict, audio: AudioSegment, cover_png: bytes) -> dict:
    sid = d["id"]
    duration = round(len(audio) / 1000)

    # Audio paths
    seed_audio = BASE_DIR / "seed_output" / "silly_songs" / f"{sid}.mp3"
    web_audio = WEB_ROOT / "public" / "audio" / "silly-songs" / f"{sid}.mp3"
    pre_gen   = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}.mp3"
    for p in (seed_audio, web_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
    audio.export(seed_audio, format="mp3", bitrate="192k")
    audio.export(web_audio, format="mp3", bitrate="192k")
    audio.export(pre_gen, format="mp3", bitrate="192k")

    # Cover paths (WebP from FLUX PNG bytes)
    img = Image.open(io.BytesIO(cover_png)).convert("RGB")
    img = img.resize((512, 512), Image.LANCZOS)
    seed_cover = BASE_DIR / "seed_output" / "silly_songs" / f"{sid}_cover.webp"
    web_cover_silly = WEB_ROOT / "public" / "covers" / "silly-songs" / f"{sid}_cover.webp"
    web_cover_root = WEB_ROOT / "public" / "covers" / f"{sid}.webp"
    for p in (seed_cover, web_cover_silly, web_cover_root):
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)

    # Build entry for silly_songs.json + content.json mirror
    body_chars = len(re.sub(r"\[[^\]]+\]\s*", "", d["lyrics_roman"]).strip())
    text_lines = [
        l for l in d["lyrics_roman"].split("\n")
        if l.strip() and not l.strip().startswith("[")
    ]

    entry = {
        "id": sid,
        "lang": "hi",
        "language": "hi",
        "type": "song",
        "subtype": "silly_song",
        "story_type": "silly_song",
        "storyType": "silly_song",
        "category": d["category"],
        "anthem_id": d["anthem_id"],
        "anthem": d["anthem"],
        "title": d["title"],
        "title_en": d["title_en"],
        "card_label": d["card_label"],
        "card_subtitle": d["card_subtitle"],
        "description": d["card_subtitle"],
        "description_en": "Battle cry: an Indian kid wants chips before dinner",
        "lyrics": d["lyrics_roman"],          # USER-FACING (Roman, with section tags
                                              # — silly songs DO show section tags by convention)
        "lyrics_deva": d["lyrics_deva"],
        "raw_lyrics": d["lyrics_roman"],
        "age_group": d["age_group"],
        "ageGroup": d["age_group"],
        "age_min": d["age_min"],
        "age_max": d["age_max"],
        "target_age": d["age_group"],
        "mood": d["mood"],
        "instruments": d["instruments"],
        "tempo": d["tempo"],
        "char_count": body_chars,
        "line_count": len(text_lines),
        "audio_file": f"/audio/silly-songs/{sid}.mp3",
        "audio_url": f"/audio/silly-songs/{sid}.mp3",
        "audio_variants": [{
            "voice": "minimax_v2.5_hi_ref",
            "url": f"/audio/silly-songs/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5-fal",
        }],
        "cover": f"/covers/{sid}.webp",
        "cover_file": f"/covers/silly-songs/{sid}_cover.webp",
        "cover_context": d["cover_context"],
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "minimax-music-v2.5-fal",
        "tts_engine": "minimax-music-v2.5-fal",
        "reference_audio": "https://dreamvalley.app/audio/reference/hindi_lullaby_ref.m4a",
        "experimental_v2": False,
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Silly Song"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Index update: silly_songs.json
    sjson = BASE_DIR / "seed_output" / "silly_songs" / "silly_songs.json"
    if sjson.exists():
        idx = json.loads(sjson.read_text())
        items = idx.get("items", idx) if isinstance(idx, dict) else idx
    else:
        idx, items = [], []
    items = [i for i in items if i.get("id") != sid]
    items.append(entry)
    sjson.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    print(f"  silly_songs.json: total {len(items)}")

    return entry


def save_poem(d: dict, audio: AudioSegment, cover_png: bytes) -> dict:
    sid = d["id"]
    duration = round(len(audio) / 1000)

    seed_audio = BASE_DIR / "seed_output" / "poems_hi" / f"{sid}.mp3"
    web_audio = WEB_ROOT / "public" / "audio" / "poems-hi" / f"{sid}.mp3"
    pre_gen   = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}.mp3"
    for p in (seed_audio, web_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
    audio.export(seed_audio, format="mp3", bitrate="192k")
    audio.export(web_audio, format="mp3", bitrate="192k")
    audio.export(pre_gen, format="mp3", bitrate="192k")

    img = Image.open(io.BytesIO(cover_png)).convert("RGB")
    img = img.resize((1024, 1024), Image.LANCZOS)
    seed_cover = BASE_DIR / "seed_output" / "poems_hi" / f"{sid}_cover.webp"
    web_cover_p = WEB_ROOT / "public" / "covers" / "poems-hi" / f"{sid}_cover.webp"
    web_cover_root = WEB_ROOT / "public" / "covers" / f"{sid}.webp"
    for p in (seed_cover, web_cover_p, web_cover_root):
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)

    text_lines = [l for l in d["poem_text_roman"].split("\n") if l.strip()]

    entry = {
        "id": sid,
        "lang": "hi",
        "language": "hi",
        "type": "poem",
        "story_type": "poem",
        "storyType": "poem",
        "content_type": "poem",
        "poem_type": d["poem_type"],
        "title": d["title"],
        "title_en": d["title_en"],
        "description": "Hindi onomatopoeia poem about rain at bedtime",
        "description_en": "Hindi onomatopoeia poem about rain at bedtime",
        "poem_text": d["poem_text_roman"],     # USER-FACING (Roman, no section tags)
        "poem_text_deva": d["poem_text_deva"],
        "text": d["poem_text_roman"],          # mirror so reader pages can render
        "raw_text": d["poem_text_roman"],
        "age_group": d["age_group"],
        "ageGroup": d["age_group"],
        "age_min": d["age_min"],
        "age_max": d["age_max"],
        "target_age": d["age_group"],
        "mood": d["mood"],
        "instruments": d["instruments"],
        "tempo": d["tempo"],
        "char_count": len(d["poem_text_roman"]),
        "line_count": len(text_lines),
        "audio_file": f"/audio/poems-hi/{sid}.mp3",
        "audio_url": f"/audio/poems-hi/{sid}.mp3",
        "audio_variants": [{
            "voice": "minimax_v2.5_hi_ref",
            "url": f"/audio/poems-hi/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5-fal",
        }],
        "cover": f"/covers/{sid}.webp",
        "cover_file": f"/covers/poems-hi/{sid}_cover.webp",
        "cover_context": d["cover_context"],
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "minimax-music-v2.5-fal",
        "tts_engine": "minimax-music-v2.5-fal",
        "reference_audio": "https://dreamvalley.app/audio/reference/hindi_lullaby_ref.m4a",
        "experimental_v2": False,
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Poem"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    pjson = BASE_DIR / "seed_output" / "poems_hi" / "poems.json"
    if pjson.exists():
        idx = json.loads(pjson.read_text())
        items = idx.get("items", idx) if isinstance(idx, dict) else idx
    else:
        idx, items = [], []
    items = [i for i in items if i.get("id") != sid]
    items.append(entry)
    pjson.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    print(f"  poems.json: total {len(items)}")

    return entry


def upsert_content(entry: dict) -> int:
    path = BASE_DIR / "seed_output" / "content.json"
    data = json.loads(path.read_text())
    items = data["items"] if isinstance(data, dict) else data
    items = [i for i in items if i.get("id") != entry["id"]]
    items.append(entry)
    if isinstance(data, dict):
        data["items"] = items
    else:
        data = items
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return len(items)


# ───────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────

def main():
    print("\n═══ Validating silly song (v2 spec §11) ═══")
    s_errs = validate_silly_song(SILLY_SONG)
    if s_errs:
        print("  ❌ Silly-song validator failures:")
        for e in s_errs:
            print(f"    - {e}")
        sys.exit(1)
    print("  ✓ silly-song validator passed")

    print("\n═══ Validating poem (v2 spec §10) ═══")
    p_errs = validate_poem(POEM)
    if p_errs:
        print("  ❌ Poem validator failures:")
        for e in p_errs:
            print(f"    - {e}")
        sys.exit(1)
    print("  ✓ poem validator passed")

    # AUDIO: silly song
    silly_audio = render_audio(
        "SILLY SONG",
        silly_song_style_prompt(SILLY_SONG),
        SILLY_SONG["lyrics_deva"],
    )

    # AUDIO: poem
    poem_audio = render_audio(
        "POEM",
        poem_style_prompt(POEM),
        POEM["poem_text_deva"],
    )

    # COVERS via FLUX
    print("\n═══ Silly-song cover (Together AI FLUX) ═══")
    silly_cover_png = generate_cover_together(silly_cover_prompt(SILLY_SONG), 512, 512)
    if silly_cover_png is None:
        sys.exit("❌ silly-song cover generation failed")

    print("\n═══ Poem cover (Together AI FLUX) ═══")
    poem_cover_png = generate_cover_together(poem_cover_prompt(POEM), 1024, 1024)
    if poem_cover_png is None:
        sys.exit("❌ poem cover generation failed")

    # SAVE
    print("\n═══ Saving silly song ═══")
    silly_entry = save_silly_song(SILLY_SONG, silly_audio, silly_cover_png)

    print("\n═══ Saving poem ═══")
    poem_entry = save_poem(POEM, poem_audio, poem_cover_png)

    # UPSERT to content.json
    print("\n═══ Upsert to content.json ═══")
    upsert_content(silly_entry)
    total = upsert_content(poem_entry)
    print(f"  total items: {total}")

    print("\n═════ DAY-1 SILLY+POEM PUBLISH DONE ═════")
    print(f"  silly:  {SILLY_SONG['id']}  ({round(len(silly_audio) / 1000)}s)")
    print(f"  poem:   {POEM['id']}  ({round(len(poem_audio) / 1000)}s)")
    print()
    print("  Next: scp audio + covers to prod, git push, prod-pull + admin reload,")
    print("        then: python3 scripts/deploy_guard.py verify")


if __name__ == "__main__":
    main()
