#!/usr/bin/env python3
"""Hindi batch day-4: one chatur_katha short story + one rocking lullaby.

Diversity choices vs day-2 (gilhari/prakriti/2-5/anika) and
day-3 (jugnu/mitra/6-8/tripti):
  - Story: bird lead (bulbul) + chatur_katha story-type (NEW signature —
    problem-first opener, clever resolution). Voice `roohi` (soft/breathy,
    fresh from anika & tripti). Mood `curious` (vs day-2/3 calm).
    Region `south` (vs north/east).
  - Lullaby: rocking type at age 2-5 (rocking existed at 0-1, this fills
    the toddler gap). Instruments santoor + sarangi (vs day-3
    tanpura+bansuri). Region `west`.

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

from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from fix_hindi_batch_day2 import (  # noqa: E402
    assemble_story_audio, minimax_lullaby,
)
from fix_hindi_batch_day2_patch import (  # noqa: E402
    clean_lyrics_text,
)
from validate_hindi_story import validate_story_dict  # noqa: E402

load_dotenv(BASE_DIR / ".env", override=True)


# ─────────────────────────────────────────────────────────────────────────
# STORY — Reshmi Bulbul ka Chatur Ghonsla — chatur_katha, 6-8, curious
# ─────────────────────────────────────────────────────────────────────────
STORY = {
    "id": "hi-chatur-6-8-bulb",
    "lang": "hi",
    "story_type": "chatur_katha",
    "mood": "curious",
    "age_group": "6-8",
    "age_min": 6,
    "age_max": 8,
    "target_age": 7,
    "voice": "roohi",  # soft/breathy — fresh after anika (d2), tripti (d3)

    "title_roman": "Reshmi Bulbul ka Chatur Ghonsla",
    "title_deva":  "रेशमी बुलबुल का चतुर घोंसला",
    "title_en":    "Reshmi Bulbul's Clever Nest",

    # Additive hook — answers a question the story pays off.
    "hook_roman":  "Kya tum jaante ho, ek chhoti bulbul ne toofaan ke baad apna ghar kaise bachaya",
    "hook_deva":   "क्या तुम जानते हो, एक छोटी बुलबुल ने तूफ़ान के बाद अपना घर कैसे बचाया?",

    "description_roman": "Aandhi ne ghar tod diya, par Reshmi ne ek chatur jagah dhoondhi.",
    "description_en":    "A storm shattered her nest. While other birds offered solutions that wouldn't last, the small bulbul Reshmi found the cleverest hiding place of all — inside something everyone had forgotten.",

    "repeated_phrase_roman": "Do tinke, ek saath",
    "repeated_phrase_deva":  "दो तिनके, एक साथ",

    "character": {
        "name": "Reshmi",
        "identity": (
            "a small Indian red-whiskered bulbul named Reshmi with a "
            "tall pointed black crest, bright red cheek-tuft, white "
            "underparts and a delicate brown body, perched on a peepal "
            "branch holding two tiny dry twigs in her beak"
        ),
        "special": (
            "she always carries two twigs at a time — never one — "
            "because one twig alone can never become a home; she "
            "believes two means strength"
        ),
        "personality_tags": ["Clever", "Determined"],
    },

    "lead_character_type_canonical": "bird",
    "lead_character_type_cover":     "bird",
    "gender_lead": "female",
    "theme": "cleverness",
    "themes": ["cleverness", "resilience", "problem_solving"],
    "geography": "south_asia",
    "indian_region": "south",  # Karnataka/Tamil Nadu courtyard imagery

    "cover_context": (
        "a small Indian red-whiskered bulbul (Reshmi) with a tall "
        "pointed black crest and bright red cheek-tuft, holding two "
        "tiny dry twigs in her beak, perched on the broken rim of an "
        "old terracotta earthen pot in a sunlit south-Indian courtyard, "
        "warm golden afternoon light, peepal leaves scattered around, "
        "soft watercolor storybook style, no humans in frame, intimate "
        "and curious mood, 512x512"
    ),

    # §1 paragraph counts MUST match between roman and deva (1-to-1).
    # chatur_katha — opens with the PROBLEM, not a sensory image or
    # storyteller frame. Then specific Reshmi detail. Then the clever
    # resolution.
    "text_roman": (
        "Reshmi bulbul ka ghar tooth gaya tha.\n\n"
        "Raat ko bahut tez aandhi aayi thi. Subah jab Reshmi laut ke "
        "aayi, peepal ki shaakh par sirf tooti hui tinkiyaan thi.\n\n"
        "[PAUSE: 800]\n\n"
        "Tumne kabhi dekha hai, jab aandhi ke baad subah hoti hai? "
        "Sab kuch shaant, par sab kuch bikhra hua.\n\n"
        "Reshmi udaas thi. Lekin Reshmi sirf udaas nahi hoti — wo "
        "sochti bhi thi.\n\n"
        "[PHRASE] Do tinke, ek saath. [/PHRASE]\n"
        "[PAUSE: 600]\n\n"
        "Reshmi hamesha do tinke ek saath laati thi. Kabhi ek nahi, "
        "hamesha do — kyunki ek tinka akela kabhi ghar nahi banaa "
        "sakta. Do mein takat hoti hai.\n\n"
        "Ek koel aayi. Boli, Reshmi, mere ped par chal — wahaan "
        "jagah hai. Reshmi ne sar hilaya. Lekin koel ka ped bhi "
        "khule mein tha — agli aandhi mein wahaan bhi yahi haal "
        "hoga.\n\n"
        "[PAUSE: 600]\n\n"
        "Tumhe pata hai, har bahaar ki cheez surakshit nahi hoti?\n\n"
        "Ek kauwa aaya. Boli, Reshmi, oonche pahaadon par chal — "
        "wahaan aandhi nahi pahunchti. Reshmi ne phir sar hilaya. "
        "Pahaad door tha, aur Reshmi ke chote bachche hone wale the.\n\n"
        "[MUSIC]\n\n"
        "Reshmi gaon ke aangan mein gayi. Wahaan ek purana mitti ka "
        "ghada tha — tooti hui kinaariyaan, andhera andar.\n\n"
        "Reshmi muskurayi. Ghade ke andar — andar — kabhi aandhi "
        "nahi pahunch sakti.\n\n"
        "[PHRASE] Do tinke, ek saath. [/PHRASE]\n"
        "[PAUSE: 800]\n\n"
        "Reshmi ne tinke jutaaye, do do karke. Ghade ke andar dheere "
        "se rakkhe. Ek ghonsla — chhota, garam, chhupa hua.\n\n"
        "Socho zara — har problem ka jawab kya hamesha bahar hota "
        "hai? Kabhi kabhi sabse safe jagah wahin hoti hai jise log "
        "bhool gaye hain.\n\n"
        "[PHRASE] Do tinke, ek saath. [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "Us raat phir aandhi aayi. Reshmi ghade ke andar baithi thi "
        "— garam, sookhi, surakshit.\n\n"
        "Bahar hawa cheekh rahi thi. Andar Reshmi ne aankhein band "
        "ki, aur muskurayi.\n\n"
        "[MUSIC]\n\n"
        "Subah hui. Reshmi bahar nikli, dhoop mein. Ghonsla saaf, "
        "tinke saare sahi jagah.\n\n"
        "Reshmi ne ek lambi saans li. Chatur dimaag se, do tinkon "
        "ne ek surakshit ghar bana liya."
    ),

    "text_deva": (
        "रेशमी बुलबुल का घर टूट गया था।\n\n"
        "रात को बहुत तेज़ आँधी आई थी। सुबह जब रेशमी लौट के "
        "आई, पीपल की शाख पर सिर्फ़ टूटी हुई तिनकियाँ थी।\n\n"
        "[PAUSE: 800]\n\n"
        "तुमने कभी देखा है, जब आँधी के बाद सुबह होती है? "
        "सब कुछ शांत, पर सब कुछ बिखरा हुआ।\n\n"
        "रेशमी उदास थी। लेकिन रेशमी सिर्फ़ उदास नहीं होती — वो "
        "सोचती भी थी।\n\n"
        "[PHRASE] दो तिनके, एक साथ। [/PHRASE]\n"
        "[PAUSE: 600]\n\n"
        "रेशमी हमेशा दो तिनके एक साथ लाती थी। कभी एक नहीं, "
        "हमेशा दो — क्योंकि एक तिनका अकेला कभी घर नहीं बना "
        "सकता। दो में ताक़त होती है।\n\n"
        "एक कोयल आई। बोली, रेशमी, मेरे पेड़ पर चल — वहाँ "
        "जगह है। रेशमी ने सर हिलाया। लेकिन कोयल का पेड़ भी "
        "खुले में था — अगली आँधी में वहाँ भी यही हाल "
        "होगा।\n\n"
        "[PAUSE: 600]\n\n"
        "तुम्हें पता है, हर बाहर की चीज़ सुरक्षित नहीं होती?\n\n"
        "एक कौआ आया। बोला, रेशमी, ऊँचे पहाड़ों पर चल — "
        "वहाँ आँधी नहीं पहुँचती। रेशमी ने फिर सर हिलाया। "
        "पहाड़ दूर था, और रेशमी के छोटे बच्चे होने वाले थे।\n\n"
        "[MUSIC]\n\n"
        "रेशमी गाँव के आँगन में गई। वहाँ एक पुराना मिट्टी का "
        "घड़ा था — टूटी हुई किनारियाँ, अँधेरा अंदर।\n\n"
        "रेशमी मुस्कुराई। घड़े के अंदर — अंदर — कभी आँधी "
        "नहीं पहुँच सकती।\n\n"
        "[PHRASE] दो तिनके, एक साथ। [/PHRASE]\n"
        "[PAUSE: 800]\n\n"
        "रेशमी ने तिनके जुटाए, दो दो करके। घड़े के अंदर धीरे "
        "से रखे। एक घोंसला — छोटा, गरम, छुपा हुआ।\n\n"
        "सोचो ज़रा — हर समस्या का जवाब क्या हमेशा बाहर होता "
        "है? कभी कभी सबसे सेफ़ जगह वहीं होती है जिसे लोग "
        "भूल गए हैं।\n\n"
        "[PHRASE] दो तिनके, एक साथ। [/PHRASE]\n"
        "[PAUSE: 1000]\n\n"
        "उस रात फिर आँधी आई। रेशमी घड़े के अंदर बैठी थी "
        "— गरम, सूखी, सुरक्षित।\n\n"
        "बाहर हवा चीख़ रही थी। अंदर रेशमी ने आँखें बंद "
        "की, और मुस्कुराई।\n\n"
        "[MUSIC]\n\n"
        "सुबह हुई। रेशमी बाहर निकली, धूप में। घोंसला साफ़, "
        "तिनके सारे सही जगह।\n\n"
        "रेशमी ने एक लंबी साँस ली। चतुर दिमाग़ से, दो तिनकों "
        "ने एक सुरक्षित घर बना लिया।"
    ),
}


# ─────────────────────────────────────────────────────────────────────────
# LULLABY — Jhulna Re (Swing/Rock On) — rocking, 2-5, calm
# ─────────────────────────────────────────────────────────────────────────
LULLABY = {
    "id": "hi-rocking-2-5-jhul",
    "lang": "hi",
    "lullaby_type": "rocking",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "target_age": 4,
    "mood": "calm",
    "instrument": "santoor_sarangi",
    "imagery": "jhula_aangan",
    "theme": "comfort",
    "geography": "south_asia",
    "indian_region": "west",

    "title_roman": "Jhulna Re",
    "title_deva":  "झूलना रे",
    "title_en":    "Sway, Little One",

    "card_label_roman": "Jhulna Re",
    "card_subtitle_roman": "Maa ki goad mein dheere dheere — aage peeche, aage peeche",
    "card_subtitle_deva":  "माँ की गोद में धीरे धीरे — आगे पीछे, आगे पीछे",

    "description_en": (
        "A gentle Hindi rocking lullaby for toddlers — a child sways "
        "gently in a courtyard hammock, the rhythm of swinging matches "
        "their breath, santoor and sarangi pulse softly underneath like "
        "a slow heartbeat."
    ),

    "signature_opening_roman": "Jhulna re, jhulna re",
    "signature_closing_roman": "Aage peeche, neend mein kheechhe",

    "character": {
        "name": "Bachcha",
        "identity": (
            "a small drowsy Indian toddler being gently rocked in a soft "
            "cotton hammock-jhula strung between two pillars in a warm "
            "south-Indian courtyard at dusk, eyes half-closed, one tiny "
            "hand draped over the edge"
        ),
        "special": (
            "the jhula moves in a slow steady rhythm — aage peeche, "
            "aage peeche — exactly the speed of a calm breath"
        ),
        "personality_tags": ["Drowsy", "Held"],
    },

    # Visual subject is the sleeping child — use human_child for cover.
    "lead_character_type_canonical": "human_child",
    "lead_character_type_cover":     "human",

    "style_prompt": (
        "Gentle Hindi rocking lullaby, soft warm female vocal, low "
        "register, swaying 6/8 rhythm at 58 BPM, soft santoor pulse "
        "underneath like raindrops, tender sarangi answering each line, "
        "no vibrato, intimate maternal delivery, even back-and-forth "
        "swaying motion in the music itself, minimal instrumentation, "
        "soft breath between phrases, traditional Indian classical "
        "lullaby feel"
    ),

    "lyrics_roman": (
        "[verse]\n"
        "Jhulna re, jhulna re\n"
        "Dheere dheere jhulna re\n"
        "Aage peeche, aage peeche\n"
        "Aankhein band ho jaayein dheere\n\n"
        "[chorus]\n"
        "Maa ki goad mein, jhulna re\n"
        "Saari raat hai apni\n"
        "Maa ki goad mein, jhulna re\n"
        "Neend hai meethi apni\n\n"
        "[verse]\n"
        "Sham dhali, hawa thandi\n"
        "Aangan mein deep jale\n"
        "Bachche ka hai jhula resham\n"
        "Dheere dheere chale\n\n"
        "[chorus]\n"
        "Maa ki goad mein, jhulna re\n"
        "Saari raat hai apni\n"
        "Maa ki goad mein, jhulna re\n"
        "Neend hai meethi apni\n\n"
        "[verse]\n"
        "Saans dheere, dil dheere\n"
        "Jhula bhi ab dheere\n"
        "Aage peeche, neend mein kheenche\n"
        "Sapne aaye sapne\n"
    ),

    "lyrics_deva": (
        "[verse]\n"
        "झूलना रे, झूलना रे\n"
        "धीरे धीरे झूलना रे\n"
        "आगे पीछे, आगे पीछे\n"
        "आँखें बंद हो जाएँ धीरे\n\n"
        "[chorus]\n"
        "माँ की गोद में, झूलना रे\n"
        "सारी रात है अपनी\n"
        "माँ की गोद में, झूलना रे\n"
        "नींद है मीठी अपनी\n\n"
        "[verse]\n"
        "शाम ढली, हवा ठंडी\n"
        "आँगन में दीप जले\n"
        "बच्चे का है झूला रेशम\n"
        "धीरे धीरे चले\n\n"
        "[chorus]\n"
        "माँ की गोद में, झूलना रे\n"
        "सारी रात है अपनी\n"
        "माँ की गोद में, झूलना रे\n"
        "नींद है मीठी अपनी\n\n"
        "[verse]\n"
        "साँस धीरे, दिल धीरे\n"
        "झूला भी अब धीरे\n"
        "आगे पीछे, नींद में खींचे\n"
        "सपने आए सपने\n"
    ),

    "cover_context": (
        "A small drowsy Indian toddler being gently rocked in a soft "
        "cotton hammock-jhula strung between two carved wooden pillars "
        "in a warm south-Indian courtyard at dusk, a single oil lamp "
        "glowing on a low ledge nearby, soft amber and rose dusk light, "
        "marigold petals scattered on the floor, watercolor storybook "
        "style, deeply calm, no other humans visible, 512x512"
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
    # chatur_katha → "folk_tale" in cover-gen taxonomy (closest fit for
    # clever-resolution stories with character framing).
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
        "text":      text_clean,
        "text_deva": text_deva_clean,
        "raw_text":      STORY["text_roman"],
        "raw_text_deva": STORY["text_deva"],
        "repeated_phrase":      STORY["repeated_phrase_roman"],
        "repeated_phrase_deva": STORY["repeated_phrase_deva"],
        "character":      STORY["character"],
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
        "instruments": ["santoor", "sarangi"],
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
            story_audio_path.parent.mkdir(parents=True, exist_ok=True)
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

    print("\n═════ DAY-4 PUBLISH DONE ═════")
    if story_duration:  print(f"  story:   {story_duration}s")
    if lul_duration:    print(f"  lullaby: {lul_duration}s")


if __name__ == "__main__":
    main()
