#!/usr/bin/env python3
"""Hindi batch day-3: one mitra_katha short story + one shield lullaby.

Diversity choices vs day-2:
  - Story: insect lead (firefly) + mitra_katha story-type (new signature).
    Age bucket shifts to 6-8. Voice `tripti` (day-2 used `anika`).
  - Lullaby: shield type (Hindi had 0 shield lullabies prior) at age 2-5.
    Same MiniMax v2.5 path with the 28s Hindi reference.

Narrative-craft gates (§1-§7 from docs/HINDI_SHORT_STORY_GUIDELINES.md)
are enforced on the STORY dict before any paid API call.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from audio_assembly import MUSIC_DIR  # noqa: E402
from fix_hindi_batch_day2 import (  # noqa: E402
    ELEVENLABS_VOICES, FAL_ENDPOINT, MINIMAX_REFERENCE_FILE,
    elevenlabs_tts, parse_segments_deva, _ensure_terminal_danda,
    HINDI_TTS_PARAMS,
    assemble_story_audio, minimax_lullaby,
)
from fix_hindi_batch_day2_patch import (  # noqa: E402
    assemble_story_audio_no_hook, clean_lyrics_text,
)
from validate_hindi_story import validate_story_dict  # noqa: E402

load_dotenv(BASE_DIR / ".env", override=True)


# ─────────────────────────────────────────────────────────────────────────
# STORY — Jugnu aur Chaand (Firefly and Moon) — mitra_katha, 6-8, calm
# ─────────────────────────────────────────────────────────────────────────
STORY = {
    "id": "hi-mitra-6-8-jugn",
    "lang": "hi",
    "story_type": "mitra_katha",
    "mood": "calm",
    "age_group": "6-8",
    "age_min": 6,
    "age_max": 8,
    "target_age": 7,
    "voice": "tripti",  # fresh voice vs day-2 anika

    "title_roman": "Jugnu aur Chaand",
    "title_deva":  "जुगनू और चाँद",
    "title_en":    "The Firefly and the Moon",

    # Additive hook — answers to a question the story then pays off.
    # Spoken BEFORE the story text; not redundant with the opener.
    "hook_roman":  "Kya tum jaante ho, Chaand ka sabse chhota dost kaun hai",
    "hook_deva":   "क्या तुम जानते हो, चाँद का सबसे छोटा दोस्त कौन है?",

    "description_roman": "Jugnu aur Chaand ki chhupi si dosti — tim tim, tim tim.",
    "description_en":    "A tiny Indian firefly named Jugnu and the moon share a quiet friendship across the night — he blinks in sets of three to signal, and the moon always peeks back through the clouds.",

    "repeated_phrase_roman": "Tim tim, chandni re",
    "repeated_phrase_deva":  "टिम टिम, चाँदनी रे",

    "character": {
        "name": "Jugnu",
        "identity": (
            "a tiny Indian firefly named Jugnu with a soft green-gold "
            "glowing abdomen, flying just above tall silver grass beside "
            "a slow river under a deep indigo night sky"
        ),
        "special": (
            "he blinks in sets of three — a private signal to the moon, "
            "who always peeks back through the clouds"
        ),
        "personality_tags": ["Gentle", "Loyal"],
    },

    "lead_character_type_canonical": "insect",
    "lead_character_type_cover":     "insect",
    "gender_lead": "male",
    "theme": "friendship",
    "themes": ["friendship", "night_sky", "gentle_companionship"],
    "geography": "south_asia",
    "indian_region": "east",   # Bengal / Sundarbans firefly imagery

    "cover_context": (
        "a tiny Indian firefly (Jugnu) with soft green-gold glowing "
        "abdomen hovering above silver-green tall grass by a dark river, "
        "a large warm crescent moon peeking through thin clouds above, "
        "deep indigo and navy night sky dotted with tiny stars, warm "
        "amber firefly light, watercolor storybook style, no humans in "
        "frame, dreamy and intimate, 512x512"
    ),

    # §1 paragraph counts MUST match between roman and deva (1-to-1).
    "text_roman": (
        "Raat thi gehri. Aasmaan mein Chaand chamak raha tha, aur neeche "
        "ghaas ke maidaan mein Jugnu Chaand ki taraf dekh raha tha.\n\n"
        "Dono bahut purane dost the — ek upar, ek neeche. Jab bhi raat "
        "hoti, dono ek doosre ko dhoondte.\n\n"
        "[PAUSE: 800]\n\n"
        "Tumne kabhi jugnu dekha hai raat ko? Unki roshni aisi hi hoti "
        "hai — tim tim, tim tim.\n\n"
        "Jugnu teen baar blink karta tha. Hamesha teen — jaise Chaand ko "
        "signal bhej raha ho, main yahaan hoon, main yahaan hoon.\n\n"
        "[PHRASE] Tim tim, chandni re. [/PHRASE]\n"
        "[PAUSE: 600]\n\n"
        "Tumhe pata hai Chaand bhi dost dhoondhta hai? Bade bade taaron "
        "ke beech mein, uska sabse chhota dost Jugnu hi hai.\n\n"
        "Us raat baadal thode mote the. Jugnu ne upar dekha, par Chaand "
        "dikhayi nahi diya. Jugnu ne phir teen baar blink kiya — tim, "
        "tim, tim.\n\n"
        "[MUSIC]\n\n"
        "Aur tabhi baadal hate. Chaand ne jhaanka, aur muskuraya.\n\n"
        "[PHRASE] Tim tim, chandni re. [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "Suno zara — ab hawa dheemi thi. Jugnu ki roshni bhi dheemi, aur "
        "Chaand ki chandni bhi naram.\n\n"
        "Dono dost chupchap ek doosre ko dekh rahe the. Koi baat nahi "
        "karni thi — bas saath hona hi kaafi tha.\n\n"
        "[PHRASE] Tim tim, chandni re. [/PHRASE]\n"
        "[PAUSE: 800]\n\n"
        "Jugnu ghaas ke upar baith gaya. Aankhein bhari, roshni halki.\n\n"
        "Chaand upar raha. Dost so gaya, aur Chaand ne chandni aur naram "
        "kar di.\n\n"
        "Aur Jugnu so gaya."
    ),

    "text_deva": (
        "रात थी गहरी। आसमान में चाँद चमक रहा था, और नीचे "
        "घास के मैदान में जुगनू चाँद की तरफ देख रहा था।\n\n"
        "दोनों बहुत पुराने दोस्त थे — एक ऊपर, एक नीचे। जब भी रात "
        "होती, दोनों एक दूसरे को ढूँढते।\n\n"
        "[PAUSE: 800]\n\n"
        "तुमने कभी जुगनू देखा है रात को? उनकी रोशनी ऐसी ही होती "
        "है — टिम टिम, टिम टिम।\n\n"
        "जुगनू तीन बार ब्लिंक करता था। हमेशा तीन — जैसे चाँद को "
        "सिग्नल भेज रहा हो, मैं यहाँ हूँ, मैं यहाँ हूँ।\n\n"
        "[PHRASE] टिम टिम, चाँदनी रे। [/PHRASE]\n"
        "[PAUSE: 600]\n\n"
        "तुम्हें पता है चाँद भी दोस्त ढूँढता है? बड़े बड़े तारों "
        "के बीच में, उसका सबसे छोटा दोस्त जुगनू ही है।\n\n"
        "उस रात बादल थोड़े मोटे थे। जुगनू ने ऊपर देखा, पर चाँद "
        "दिखाई नहीं दिया। जुगनू ने फिर तीन बार ब्लिंक किया — टिम, "
        "टिम, टिम।\n\n"
        "[MUSIC]\n\n"
        "और तभी बादल हटे। चाँद ने झाँका, और मुस्कुराया।\n\n"
        "[PHRASE] टिम टिम, चाँदनी रे। [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "सुनो ज़रा — अब हवा धीमी थी। जुगनू की रोशनी भी धीमी, "
        "और चाँद की चाँदनी भी नरम।\n\n"
        "दोनों दोस्त चुपचाप एक दूसरे को देख रहे थे। कोई बात नहीं "
        "करनी थी — बस साथ होना ही काफ़ी था।\n\n"
        "[PHRASE] टिम टिम, चाँदनी रे। [/PHRASE]\n"
        "[PAUSE: 800]\n\n"
        "जुगनू घास के ऊपर बैठ गया। आँखें भारी, रोशनी हल्की।\n\n"
        "चाँद ऊपर रहा। दोस्त सो गया, और चाँद ने चाँदनी और नरम "
        "कर दी।\n\n"
        "और जुगनू सो गया।"
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# LULLABY — Main Yahin Hoon (I Am Here) — shield, 2-5, calm
# ─────────────────────────────────────────────────────────────────────────
LULLABY = {
    "id": "hi-shield-2-5-main",
    "lang": "hi",
    "lullaby_type": "shield",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "target_age": 4,
    "mood": "calm",
    "instrument": "tanpura_bansuri",
    "imagery": "diya_chaadar",
    "theme": "safety",
    "geography": "south_asia",
    "indian_region": "north",

    "title_roman": "Main Yahin Hoon",
    "title_deva":  "मैं यहीं हूँ",
    "title_en":    "I Am Here",

    "card_label_roman": "Main Yahin Hoon",
    "card_subtitle_roman": "Maa ki dheemi awaaz — main yahin hoon, koi dar nahi",
    "card_subtitle_deva":  "माँ की धीमी आवाज़ — मैं यहीं हूँ, कोई डर नहीं",

    "description_en": (
        "A soft Hindi shield lullaby — a mother's quiet promise that she "
        "is here, a small earthen lamp glows beside the bed, the child "
        "is safe to close their eyes."
    ),

    "signature_opening_roman": "Main yahin hoon, meri jaan",
    "signature_closing_roman": "Dar nahi, dar nahi, dar nahi hai",

    "character": {
        "name": "Maa",
        "identity": (
            "a small sleeping Indian toddler wrapped in a soft warm "
            "chaadar, a single earthen diya (oil lamp) glowing beside "
            "the bed, a calm maternal presence implied but not shown"
        ),
        "special": (
            "the diya's small golden flame is the only light — everything "
            "else is warm shadow"
        ),
        "personality_tags": ["Safe", "Warm"],
    },

    # Shield lullabies don't drive a character on the card — the VISUAL
    # subject is the sleeping child. Use human_child for cover routing.
    "lead_character_type_canonical": "human_child",
    "lead_character_type_cover":     "human",

    "style_prompt": (
        "Protective Hindi shield lullaby, warm female vocal, low register, "
        "soft tanpura drone with a gentle bansuri flute above, 62 BPM, "
        "steady, certain, grounded, reassuring, no vibrato, direct "
        "delivery like a spoken promise set to a simple Hindustani "
        "melody, tender maternal voice, intimate bedroom atmosphere, "
        "minimal instrumentation, soft breath between phrases"
    ),

    "lyrics_roman": (
        "[verse]\n"
        "Main yahin hoon, meri jaan\n"
        "Neend aa jaayegi dheere\n"
        "Diya jal raha hai paas\n"
        "Chaadar halki si hai tere\n\n"
        "[chorus]\n"
        "Main yahin hoon, main yahin hoon\n"
        "Koi dar nahi, meri jaan\n"
        "Main yahin hoon, main yahin hoon\n"
        "Aankhein band kar, ab so ja\n\n"
        "[verse]\n"
        "Raat thandi si hai baahar\n"
        "Ghar mein garam sa pyaar\n"
        "Taare upar, Chaand upar\n"
        "Tu bhi neend mein utar\n\n"
        "[chorus]\n"
        "Main yahin hoon, main yahin hoon\n"
        "Koi dar nahi, meri jaan\n"
        "Main yahin hoon, main yahin hoon\n"
        "Aankhein band kar, ab so ja\n\n"
        "[verse]\n"
        "Saans halki, saans dheere\n"
        "Sapne aane waale hain\n"
        "Main yahin hoon tere paas\n"
        "Dar nahi, dar nahi, dar nahi hai\n"
    ),

    "lyrics_deva": (
        "[verse]\n"
        "मैं यहीं हूँ, मेरी जान\n"
        "नींद आ जाएगी धीरे\n"
        "दिया जल रहा है पास\n"
        "चादर हल्की सी है तेरे\n\n"
        "[chorus]\n"
        "मैं यहीं हूँ, मैं यहीं हूँ\n"
        "कोई डर नहीं, मेरी जान\n"
        "मैं यहीं हूँ, मैं यहीं हूँ\n"
        "आँखें बंद कर, अब सो जा\n\n"
        "[verse]\n"
        "रात ठंडी सी है बाहर\n"
        "घर में गरम सा प्यार\n"
        "तारे ऊपर, चाँद ऊपर\n"
        "तू भी नींद में उतर\n\n"
        "[chorus]\n"
        "मैं यहीं हूँ, मैं यहीं हूँ\n"
        "कोई डर नहीं, मेरी जान\n"
        "मैं यहीं हूँ, मैं यहीं हूँ\n"
        "आँखें बंद कर, अब सो जा\n\n"
        "[verse]\n"
        "साँस हल्की, साँस धीरे\n"
        "सपने आने वाले हैं\n"
        "मैं यहीं हूँ तेरे पास\n"
        "डर नहीं, डर नहीं, डर नहीं है\n"
    ),

    "cover_context": (
        "A small sleeping Indian toddler wrapped in a soft warm chaadar, "
        "a single earthen diya glowing with a small golden flame beside "
        "the bed, everything else in warm shadow, deep amber and soft "
        "ochre palette, a crescent moon visible through a small window, "
        "watercolor storybook style, deeply calm and safe, no text, no "
        "humans visible other than the sleeping child, 512x512"
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# Cover generation — reuses the English FLUX pipeline via a seed JSON.
# ─────────────────────────────────────────────────────────────────────────

def run_cover_generator(seed_path: Path, mood: str, cover_story_type: str) -> None:
    cmd = [
        sys.executable, str(BASE_DIR / "scripts" / "generate_cover_experimental.py"),
        "--story-json", str(seed_path),
        "--mood", mood,
        "--story-type", cover_story_type,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(cmd, cwd=str(BASE_DIR), env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-800:])
        print(r.stderr[-1200:], file=sys.stderr)
        raise RuntimeError("cover generator failed")
    print(r.stdout[-400:])


def generate_story_cover() -> Path:
    sid = STORY["id"]
    cover_seed = {
        "id": sid,
        "title": STORY["title_en"],
        "description": STORY["description_en"],
        "cover_context": STORY["cover_context"],
        "character": STORY["character"],
        "lead_character_type": STORY["lead_character_type_cover"],
        "lead_gender": STORY["gender_lead"],
        "theme": STORY["theme"],
        "age_group": STORY["age_group"],
        "mood": STORY["mood"],
    }
    seed_dir = BASE_DIR / "seed_output" / "hindi_stories"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_path = seed_dir / f"{sid}_coverseed.json"
    seed_path.write_text(json.dumps(cover_seed, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    # mitra_katha → "folk_tale" in the cover generator's taxonomy (it only
    # knows english bucket names). Use "folk_tale" as the closest fit for
    # friendship-themed covers (warm, character-centric framing).
    run_cover_generator(seed_path, STORY["mood"], "folk_tale")
    seed_path.unlink(missing_ok=True)

    src_svg = BASE_DIR / "seed_output" / "covers_experimental" / f"{sid}_combined.svg"
    if not src_svg.exists():
        raise RuntimeError(f"Cover missing: {src_svg}")
    dst_svg = WEB_ROOT / "public" / "covers" / f"{sid}.svg"
    dst_svg.write_bytes(src_svg.read_bytes())
    print(f"  cover: {dst_svg}")
    return dst_svg


def generate_lullaby_cover() -> Path:
    lid = LULLABY["id"]
    cover_seed = {
        "id": lid,
        "title": LULLABY["title_en"],
        "description": LULLABY["description_en"],
        "cover_context": LULLABY["cover_context"],
        "character": LULLABY["character"],
        "lead_character_type": LULLABY["lead_character_type_cover"],
        "theme": LULLABY["theme"],
        "age_group": LULLABY["age_group"],
        "mood": LULLABY["mood"],
    }
    seed_dir = BASE_DIR / "seed_output" / "lullabies"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_path = seed_dir / f"{lid}_coverseed.json"
    seed_path.write_text(json.dumps(cover_seed, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    run_cover_generator(seed_path, "calm", "folk_tale")
    seed_path.unlink(missing_ok=True)

    src_svg = BASE_DIR / "seed_output" / "covers_experimental" / f"{lid}_combined.svg"
    if not src_svg.exists():
        raise RuntimeError(f"Cover missing: {src_svg}")
    # 3 cover destinations: web_covers (home Loriyaan card),
    # web_cover_lullabies (standalone page), seed-lullabies (backup).
    web_covers = WEB_ROOT / "public" / "covers" / f"{lid}.svg"
    web_cover_lul = WEB_ROOT / "public" / "covers" / "lullabies" / f"{lid}_cover.svg"
    seed_cover = BASE_DIR / "seed_output" / "lullabies" / f"{lid}_cover.svg"
    web_cover_lul.parent.mkdir(parents=True, exist_ok=True)
    for p in (web_covers, web_cover_lul, seed_cover):
        p.write_bytes(src_svg.read_bytes())
    print(f"  cover → {web_covers}, {web_cover_lul}, {seed_cover}")
    return web_covers


# ─────────────────────────────────────────────────────────────────────────
# content.json + lullabies.json writers
# ─────────────────────────────────────────────────────────────────────────

def story_entry(duration: int) -> dict:
    sid = STORY["id"]
    text_clean      = clean_lyrics_text(STORY["text_roman"])
    text_deva_clean = clean_lyrics_text(STORY["text_deva"])
    return {
        "id": sid,
        "type": "story",
        "lang": "hi",
        "title":    STORY["title_roman"],
        "title_deva": STORY["title_deva"],
        "title_en": STORY["title_en"],
        "description":    STORY["description_roman"],
        "description_en": STORY["description_en"],
        "hook":      STORY["hook_roman"],
        "hook_deva": STORY["hook_deva"],
        "text":      text_clean,          # UI-facing — tags stripped.
        "text_deva": text_deva_clean,
        "raw_text":      STORY["text_roman"],
        "raw_text_deva": STORY["text_deva"],
        "repeated_phrase":      STORY["repeated_phrase_roman"],
        "repeated_phrase_deva": STORY["repeated_phrase_deva"],
        "character":      STORY["character"],           # dict, English identity.
        "character_name": STORY["character"]["name"],
        "characterType":        STORY["lead_character_type_canonical"],
        "lead_character_type":  STORY["lead_character_type_canonical"],
        "lead_gender":          STORY["gender_lead"],
        "age_group": STORY["age_group"],
        "ageGroup":  STORY["age_group"],
        "age_min": STORY["age_min"],
        "age_max": STORY["age_max"],
        "target_age": STORY["target_age"],
        "mood": STORY["mood"],
        "story_type": STORY["story_type"],
        "storyType":  STORY["story_type"],
        "theme":  STORY["theme"],
        "themes": STORY["themes"],
        "geography":     STORY["geography"],
        "indian_region": STORY["indian_region"],
        "experimental_v2": True,
        "has_baked_music": True,
        "tts_engine": "elevenlabs_multilingual_v2",
        "tts_input_script": "devanagari",
        "cover": f"/covers/{sid}.svg",
        "audio_variants": [{
            "voice": STORY["voice"],
            "url": f"/audio/pre-gen/{sid}_{STORY['voice']}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "audio_url": f"/audio/pre-gen/{sid}_{STORY['voice']}.mp3",
        "duration_seconds": duration,
        "word_count": len(text_clean.split()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime"],
    }


def lullaby_song_entry(duration: int) -> dict:
    lid = LULLABY["id"]
    lyrics_clean      = clean_lyrics_text(LULLABY["lyrics_roman"])
    lyrics_deva_clean = clean_lyrics_text(LULLABY["lyrics_deva"])
    return {
        "id": lid,
        "type": "song",
        "lang": "hi",
        "title":      LULLABY["title_roman"],
        "title_deva": LULLABY["title_deva"],
        "title_en":   LULLABY["title_en"],
        "description":    LULLABY["card_subtitle_roman"],
        "description_en": LULLABY["description_en"],
        "text":      lyrics_clean,
        "text_deva": lyrics_deva_clean,
        "lyrics":      lyrics_clean,
        "lyrics_deva": lyrics_deva_clean,
        "raw_lyrics":      LULLABY["lyrics_roman"],
        "raw_lyrics_deva": LULLABY["lyrics_deva"],
        "lullaby_type": LULLABY["lullaby_type"],
        "age_group": LULLABY["age_group"],
        "ageGroup":  LULLABY["age_group"],
        "age_min":   LULLABY["age_min"],
        "age_max":   LULLABY["age_max"],
        "target_age": LULLABY["target_age"],
        "mood": LULLABY["mood"],
        "character":      LULLABY["character"],
        "character_name": LULLABY["character"]["name"],
        "characterType":  LULLABY["lead_character_type_canonical"],
        "theme": LULLABY["theme"],
        "instruments": ["tanpura", "bansuri"],
        "geography":     LULLABY["geography"],
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
        "word_count": len(lyrics_clean.split()),
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
    lid = LULLABY["id"]
    lyrics_clean      = clean_lyrics_text(LULLABY["lyrics_roman"])
    lyrics_deva_clean = clean_lyrics_text(LULLABY["lyrics_deva"])
    return {
        "id": lid,
        "title":      LULLABY["title_roman"],
        "title_deva": LULLABY["title_deva"],
        "lullaby_type": LULLABY["lullaby_type"],
        "card_label":    LULLABY["card_label_roman"],
        "card_subtitle": LULLABY["card_subtitle_roman"],
        "age_group": LULLABY["age_group"],
        "mood": LULLABY["mood"],
        "lang": "hi",
        "language": "hi",
        "audio_file": f"{lid}.mp3",
        "cover_file": f"{lid}_cover.svg",
        "duration_seconds": duration,
        "lyrics":      lyrics_clean,
        "lyrics_deva": lyrics_deva_clean,
        "raw_lyrics":      LULLABY["lyrics_roman"],
        "raw_lyrics_deva": LULLABY["lyrics_deva"],
        "style_prompt": LULLABY["style_prompt"],
        "engine": "minimax-music-v2.5",
        "tts_input_script": "devanagari",
        "character":     LULLABY["character"],
        "characterType": LULLABY["lead_character_type_canonical"],
        "instrument": LULLABY["instrument"],
        "imagery":    LULLABY["imagery"],
        "theme":      LULLABY["theme"],
        "geography":     LULLABY["geography"],
        "indian_region": LULLABY["indian_region"],
        "created_at": time.strftime("%Y-%m-%d"),
    }


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
    print(f"  content.json: +{len(entries)} upserted (total {len(items)})")


def upsert_lullabies_agg(entry: dict) -> None:
    path = BASE_DIR / "seed_output" / "lullabies" / "lullabies.json"
    with open(path) as f:
        agg = json.load(f)
    agg = [x for x in agg if x.get("id") != entry["id"]] + [entry]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    print(f"  lullabies.json: total {len(agg)}")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-audio",   action="store_true")
    ap.add_argument("--skip-covers",  action="store_true")
    ap.add_argument("--story-only",   action="store_true")
    ap.add_argument("--lullaby-only", action="store_true")
    args = ap.parse_args()

    # HARD GATE #0 — narrative-craft (§1-§7) BEFORE any paid API call.
    issues = validate_story_dict(STORY)
    if issues:
        print("\n═══ STORY dict fails narrative-craft checklist ═══",
              file=sys.stderr)
        for i in issues:
            print(f"  ❌ {i}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ narrative-craft checklist (§1-§7) passed")

    # ── STORY ────────────────────────────────────────────────────────
    sid = STORY["id"]
    story_audio_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_{STORY['voice']}.mp3"
    if args.lullaby_only:
        print("\n═══ STORY: skipped (--lullaby-only) ═══")
        story_duration = None
    else:
        if not args.skip_audio:
            print(f"\n═══ STORY audio (ElevenLabs + Devanagari, voice={STORY['voice']}) ═══")
            story_audio = assemble_story_audio(
                STORY["text_deva"], STORY["hook_deva"],
                STORY["voice"], STORY["mood"],
            )
            story_audio.export(story_audio_path, format="mp3", bitrate="192k")
            story_duration = round(len(story_audio) / 1000)
            print(f"  → {story_audio_path}  ({story_duration}s)")
        else:
            story_duration = round(len(AudioSegment.from_file(
                str(story_audio_path))) / 1000)
            print(f"\n═══ STORY audio: skipped ({story_duration}s existing) ═══")

        if not args.skip_covers:
            print("\n═══ STORY cover (FLUX, rich English seed) ═══")
            generate_story_cover()
        else:
            print("\n═══ STORY cover: skipped ═══")

    # ── LULLABY ──────────────────────────────────────────────────────
    lid = LULLABY["id"]
    lullaby_audio_path = WEB_ROOT / "public" / "audio" / "lullabies" / f"{lid}.mp3"
    if args.story_only:
        print("\n═══ LULLABY: skipped (--story-only) ═══")
        lul_duration = None
    else:
        if not args.skip_audio:
            print("\n═══ LULLABY audio (MiniMax v2.5 + Devanagari) ═══")
            mp3_bytes = minimax_lullaby(LULLABY["style_prompt"],
                                        LULLABY["lyrics_deva"])
            lul_seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
            lul_duration = round(len(lul_seg) / 1000)
            lullaby_audio_path.parent.mkdir(parents=True, exist_ok=True)
            pregen_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{lid}_female_1.mp3"
            seed_path = BASE_DIR / "seed_output" / "lullabies" / f"{lid}.mp3"
            pregen_path.parent.mkdir(parents=True, exist_ok=True)
            seed_path.parent.mkdir(parents=True, exist_ok=True)
            for p in (seed_path, lullaby_audio_path, pregen_path):
                with open(p, "wb") as f:
                    f.write(mp3_bytes)
                print(f"  → {p}")
            print(f"  duration: {lul_duration}s")
        else:
            lul_duration = round(len(AudioSegment.from_file(
                str(lullaby_audio_path))) / 1000)
            print(f"\n═══ LULLABY audio: skipped ({lul_duration}s existing) ═══")

        if not args.skip_covers:
            print("\n═══ LULLABY cover (FLUX) ═══")
            generate_lullaby_cover()
        else:
            print("\n═══ LULLABY cover: skipped ═══")

    # ── JSON upserts ─────────────────────────────────────────────────
    print("\n═══ JSON upserts ═══")
    entries = []
    if story_duration is not None:
        s_entry = story_entry(story_duration)
        entries.append(s_entry)
        # sanity-print the text fields.
        print(f"\n  story.text first 140: {s_entry['text'][:140]!r}")
        print(f"  story.text has tag? {'[' in s_entry['text']}")
    if lul_duration is not None:
        l_song = lullaby_song_entry(lul_duration)
        l_agg  = lullaby_agg_entry(lul_duration)
        entries.append(l_song)
        print(f"\n  lullaby.text first 140: {l_song['text'][:140]!r}")
        print(f"  lullaby.text has tag? {'[' in l_song['text']}")
        upsert_lullabies_agg(l_agg)
        per_entry = BASE_DIR / "seed_output" / "lullabies" / f"{lid}.json"
        per_entry.write_text(json.dumps(l_agg, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"  {per_entry}")
    if entries:
        upsert_content(entries)

    print("\n═════ DAY-3 PUBLISH DONE ═════")
    if story_duration:  print(f"  story:   {story_duration}s")
    if lul_duration:    print(f"  lullaby: {lul_duration}s")


if __name__ == "__main__":
    main()
