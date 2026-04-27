#!/usr/bin/env python3
"""Publish ONE Hindi short story + ONE long story + ONE lullaby — all per spec.

Stages (each writes its outputs before the next runs, so a mid-run failure
doesn't lose earlier work):

  1. LULLABY     — "Subah Tak" / lullaby_type=closing / age 2-5 / mood calm
                   MiniMax v2.5 + Hindi reference audio (1 API call)

  2. SHORT STORY — "Bandar Ki Patang" / age 2-5 / mood calm
                   ElevenLabs Multilingual v2 (single narrator voice = anika,
                   ~12 segments).

  3. LONG STORY  — "Sapnon Ki Nadi" / age 2-5 / mood calm
                   ElevenLabs multi-voice (tripti narrator + anika dialogue +
                   roohi whisper) for narration; MiniMax v2.5 + Hindi ref for
                   the embedded mid-story song; bed (-20/-14/-10 dB) + breath
                   swells via ports of `_apply_breathe_swells` from the
                   English long-story pipeline.

Each piece writes to:
  - seed_output/{collection}/{id}.{json,mp3,webp}     (debug master)
  - data/{collection}/{id}.json                       (per-item runtime)
  - dreamweaver-web/public/audio/{path}/{id}.mp3      (legacy duplicate)
  - dreamweaver-web/public/covers/{path}/{id}_cover.webp  (legacy)
  - seed_output/content.json                          (generic mirror)

After this runs, scp assets to prod's nginx-aliased paths
(see Hindi specs §12 for the actual targets) and admin-reload.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from audio_assembly import normalize_for_tts, MUSIC_DIR  # type: ignore
from fix_hindi_batch_day2 import minimax_lullaby  # type: ignore
from publish_hindi_long_day1 import (  # type: ignore
    elevenlabs_tts,
    ELEVENLABS_VOICES,
    PHASE_TTS,
    PHRASE_TTS,
    WHISPER_TTS,
    INTRO_TTS,
    _trim_or_loop,
    _apply_breathe_swells,
    parse_long_segments,
    strip_long_story_tags,
    _ensure_terminal,
)

load_dotenv(BASE_DIR / ".env", override=True)

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "")


# ════════════════════════════════════════════════════════════════════════
# CONTENT
# ════════════════════════════════════════════════════════════════════════

# ─── 1. LULLABY ─────────────────────────────────────────────────────────

LULLABY = {
    "id": "hi-closing-2-5-subh",
    "lullaby_type": "closing",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "mood": "calm",
    "instruments": "soft harmonium and gentle hum",
    "tempo": 60,
    "title": "Subah Tak",
    "title_deva": "सुबह तक",
    "title_en": "Until Morning",
    "card_label": "Subah Tak",
    "card_subtitle": "Goodnight pankha, goodnight chaand — subah tak",
    "lyrics_roman": (
        "Goodnight pankha, dheere dheere\n"
        "Goodnight kitaab, neend ki dheere\n"
        "Goodnight gudiya, aankh band kar\n"
        "Subah tak, subah tak\n"
        "\n"
        "Goodnight chaand, aasmaan mein chup\n"
        "Goodnight taare, bistar par chup\n"
        "Goodnight Mummy, paas hi paas\n"
        "Subah tak, subah tak\n"
        "\n"
        "Hawa dheemi, saans halki\n"
        "Aankh meechi, neend halki\n"
        "Sab cheezein, ab so jaayein\n"
        "Subah tak, subah tak\n"
        "\n"
        "Goodnight, goodnight, dheere dheere\n"
        "Goodnight, goodnight, ab so ja re\n"
        "Subah tak, subah tak"
    ),
    "lyrics_deva": (
        "गुडनाइट पंखा, धीरे धीरे\n"
        "गुडनाइट किताब, नींद की धीरे\n"
        "गुडनाइट गुड़िया, आँख बंद कर\n"
        "सुबह तक, सुबह तक\n"
        "\n"
        "गुडनाइट चाँद, आसमान में चुप\n"
        "गुडनाइट तारे, बिस्तर पर चुप\n"
        "गुडनाइट मम्मी, पास ही पास\n"
        "सुबह तक, सुबह तक\n"
        "\n"
        "हवा धीमी, साँस हल्की\n"
        "आँख मीची, नींद हल्की\n"
        "सब चीज़ें, अब सो जाएँ\n"
        "सुबह तक, सुबह तक\n"
        "\n"
        "गुडनाइट, गुडनाइट, धीरे धीरे\n"
        "गुडनाइट, गुडनाइट, अब सो जा रे\n"
        "सुबह तक, सुबह तक"
    ),
    "cover_context": (
        "A small Indian child curled under a warm cream quilt at bedtime, "
        "soft moonlight through a window, ceiling fan barely visible above, "
        "a tiny doll resting on the pillow, a closed picture book on the "
        "bedside table, deep-blue and lavender palette, watercolor children's "
        "book illustration"
    ),
}


# ─── 2. SHORT STORY ────────────────────────────────────────────────────

SHORT_STORY = {
    "id": "hi-patang-2-5-bndr",
    "type": "story",
    "lang": "hi",
    "title": "Bandar Ki Patang",
    "title_deva": "बंदर की पतंग",
    "title_en": "The Monkey's Kite",
    "description": "Neel bandar ne dheere dheere patang ko bulaaya — aur dono saath so gaye",
    "description_en": "A small monkey named Neel learns that the kite only comes to him when he breathes slowly",
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "mood": "calm",
    "characterType": "land_mammal",
    "lead_character_type": "land_mammal",
    "lead_gender": "male",
    "character": {
        "name": "Neel",
        "identity": "a small Indian monkey named Neel with a curious face and soft brown fur, perched in an old banyan tree at the edge of a hill village",
        "special": "he watches the world from the highest branch and is learning to be patient",
        "personality_tags": ["Curious", "Gentle"],
    },
    "geography": "north_indian_hills",
    "indian_region": "uttarakhand",
    "theme": "patience",
    # ── Story text — Roman + Devanagari versions, ~280 words ──
    "text_roman": (
        "Pahaadi ke peechhe, ek bahut purana ped tha — bargad. Aur us ped par, sabse upar wali shaakh par, ek chhota sa bandar baitha tha. Bandar ka naam tha — Neel.\n"
        "\n"
        "Neel ko bargad bahut achha lagta tha. Wahaan se sab kuch dikhta tha — neeche ka gaaon, door ki nadi, aur khaali aakaash.\n"
        "\n"
        "Aaj shaam, Neel ne kuch ajeeb dekha. Aakaash mein, ek nanhi si neeli patang. Patang dheere dheere udd rahi thi, hawa ke saath jhoom rahi thi.\n"
        "\n"
        "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
        "\n"
        "\"Yeh kya hai?\" Neel ne pucha. Lekin koi nahin tha jawaab dene wala. Sirf hawa ki sarr sarr awaaz thi.\n"
        "\n"
        "Patang aur paas aane lagi. Neel ke haath bhi paas aaye — pakadne ko. Lekin haath nahin pahunche.\n"
        "\n"
        "\"Patang!\" Neel chillaaya. \"Aa ja meri taraf!\"\n"
        "\n"
        "Patang nahin aayi. Bas dheere dheere udti rahi.\n"
        "\n"
        "[PAUSE: 800]\n"
        "\n"
        "Phir Neel ne sochaa — shaayad zor se nahin, dheere se bulaaun.\n"
        "\n"
        "Neel chup baith gaya. Aankhein band kiin. Lambi saans li.\n"
        "\n"
        "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
        "\n"
        "Aur tab, ek hawa ka jhonka aaya. Patang dheere dheere, dheere dheere, neeche aane lagi. Aur uske saath, Neel ki aankhein bhi bhaari ho gayin.\n"
        "\n"
        "Patang bargad ki shaakh par utar gayi. Neel ke paas. Dono saath baithe rahe.\n"
        "\n"
        "Hawa thandi thi. Aakaash mein chaand chamak raha tha.\n"
        "\n"
        "\"Achha,\" Neel ne dheere se kaha. \"Tum bhi thakk gayi ho?\"\n"
        "\n"
        "Patang chup thi.\n"
        "\n"
        "[PAUSE: 1000]\n"
        "\n"
        "Neel muskaaya. Aankhein band kiin. Aur dheere dheere — bahut dheere — neend mein gum ho gaya. Patang bhi thakk ke shaakh par lipti rahi.\n"
        "\n"
        "Hawa chal rahi thi. Bargad jhoom raha tha.\n"
        "\n"
        "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
        "\n"
        "Aur Neel aur patang — dono saath saath, neend ke andheron mein chale gaye.\n"
        "\n"
        "Subah hogi, phir milenge.\n"
        "\n"
        "Abhi, bas neend.\n"
    ),
    "text_deva": (
        "पहाड़ी के पीछे, एक बहुत पुराना पेड़ था — बरगद। और उस पेड़ पर, सबसे ऊपर वाली शाख पर, एक छोटा सा बंदर बैठा था। बंदर का नाम था — नील।\n"
        "\n"
        "नील को बरगद बहुत अच्छा लगता था। वहाँ से सब कुछ दिखता था — नीचे का गाँव, दूर की नदी, और खाली आकाश।\n"
        "\n"
        "आज शाम, नील ने कुछ अजीब देखा। आकाश में, एक नन्ही सी नीली पतंग। पतंग धीरे धीरे उड़ रही थी, हवा के साथ झूम रही थी।\n"
        "\n"
        "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
        "\n"
        "\"यह क्या है?\" नील ने पूछा। लेकिन कोई नहीं था जवाब देने वाला। सिर्फ़ हवा की सर्र सर्र आवाज़ थी।\n"
        "\n"
        "पतंग और पास आने लगी। नील के हाथ भी पास आए — पकड़ने को। लेकिन हाथ नहीं पहुँचे।\n"
        "\n"
        "\"पतंग!\" नील चिल्लाया। \"आ जा मेरी तरफ़!\"\n"
        "\n"
        "पतंग नहीं आई। बस धीरे धीरे उड़ती रही।\n"
        "\n"
        "[PAUSE: 800]\n"
        "\n"
        "फिर नील ने सोचा — शायद ज़ोर से नहीं, धीरे से बुलाऊँ।\n"
        "\n"
        "नील चुप बैठ गया। आँखें बंद कीं। लंबी साँस ली।\n"
        "\n"
        "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
        "\n"
        "और तब, एक हवा का झोंका आया। पतंग धीरे धीरे, धीरे धीरे, नीचे आने लगी। और उसके साथ, नील की आँखें भी भारी हो गईं।\n"
        "\n"
        "पतंग बरगद की शाख पर उतर गई। नील के पास। दोनों साथ बैठे रहे।\n"
        "\n"
        "हवा ठंडी थी। आकाश में चाँद चमक रहा था।\n"
        "\n"
        "\"अच्छा,\" नील ने धीरे से कहा। \"तुम भी थक गई हो?\"\n"
        "\n"
        "पतंग चुप थी।\n"
        "\n"
        "[PAUSE: 1000]\n"
        "\n"
        "नील मुस्कुराया। आँखें बंद कीं। और धीरे धीरे — बहुत धीरे — नींद में गुम हो गया। पतंग भी थक के शाख पर लिपटी रही।\n"
        "\n"
        "हवा चल रही थी। बरगद झूम रहा था।\n"
        "\n"
        "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
        "\n"
        "और नील और पतंग — दोनों साथ साथ, नींद के अँधेरों में चले गए।\n"
        "\n"
        "सुबह होगी, फिर मिलेंगे।\n"
        "\n"
        "अभी, बस नींद।\n"
    ),
    "cover_context": (
        "A small Indian gray langur monkey perched on the highest branch of "
        "an enormous old banyan tree at twilight, a small blue paper kite "
        "resting on the same branch beside him, both looking sleepy, golden "
        "and indigo sunset sky behind, north Indian hill village visible far "
        "below, watercolor children's book illustration"
    ),
}


# ─── 3. LONG STORY ─────────────────────────────────────────────────────

LONG_STORY = {
    "id": "hi-long-2-5-nadi",
    "type": "long_story",
    "lang": "hi",
    "story_format": "long_story",
    "title": "Tara Aur Sapnon Ki Nadi",
    "title_deva": "तारा और सपनों की नदी",
    "title_en": "Tara and the River of Dreams",
    "world_name": "Sapnon Ki Nadi",
    "world_name_en": "The River of Dreams",
    "world_description": "Ek nadi jahaan har boond ek puraana sapna yaad rakhti hai",
    "world_description_en": "A river where every drop remembers an old dream",
    "mystery": "Sapnon Ki Nadi chup ho gayi hai",
    "resolution": "Nadi chup nahin thi — sun rahi thi",
    "breathing_mechanic": "Ek patta jo dheere dheere saans lene par hi paani ko chhoo paata hai",
    "repeated_phrase": "Nadi sun rahi hai",
    "repeated_phrase_deva": "नदी सुन रही है",
    "song_seed": "The old riverbank stone hummed an ancient lori about every tear ever cried into the river, soft and slow.",
    "song_style_prompt": (
        "Sweet Hindi lori, solo female vocal humming a soft riverbank lullaby, "
        "soft harmonium and bansuri, 60 BPM, warm and loving, gentle Indian "
        "river atmosphere, smiling maternal voice, major key, native Hindi "
        "pronunciation"
    ),
    "song_lyrics_deva": (
        "नदी सुन रही है, नदी सुन रही है\n"
        "हर आँसू, हर सपना — सब सुन रही है\n"
        "धीरे धीरे, बस धीरे धीरे\n"
        "नदी की गोद में सब सो जाते हैं\n"
        "नदी सुन रही है, नदी सुन रही है"
    ),
    "characters": [
        {
            "name": "Tara",
            "identity": "Ek chhoti si ladki jo Sapnon Ki Nadi ke kinaare baithi hai",
            "personality": "gentle",
            "voice_style": "dreamy",
            "gender": "female",
        },
        {
            "name": "Old Patthar",
            "identity": "Nadi ke kinaare ek bahut purana, gol, gehra patthar",
            "personality": "wise",
            "voice_style": "quiet",
            "gender": "neutral",
        },
    ],
    "lead_character_type_canonical": "human_child",
    "gender_lead": "female",
    "geography": "north_indian_river",
    "indian_region": "uttarakhand",
    "tts_engine": "elevenlabs-multilingual-v2",
    "tts_input_script": "devanagari",
    "cover_context": (
        "A wide gentle river at twilight winding through a north Indian "
        "valley, smooth ancient grey stones along the banks, a small Indian "
        "girl with a long braid sitting cross-legged at the water's edge, "
        "a single tiny green leaf floating just above the water, soft "
        "moonlight, warm yellow lamp glow far away on a hill, watercolor, "
        "deep blues and warm golds, dreamy quiet atmosphere"
    ),
}

LONG_TEXT_DEVA = """[CHARACTER: Tara, gentle, dreamy, female]
[CHARACTER: Old Patthar, wise, quiet, neutral]

[INTRO]
सुनो ना, एक नदी है — सपनों की नदी। वहाँ हर बूँद एक पुरानी कहानी याद रखती है। और आज रात — कुछ अलग हुआ है।

[PHASE_1]
तारा धीरे धीरे चल रही थी। सपनों की नदी का किनारा नरम था, ठंडी रेत जैसी। हवा हल्की थी। और नदी? नदी चुप थी। पता है, सपनों की नदी हर रात गुनगुनाती है — हर बूँद एक छोटी सी आवाज़। लेकिन आज? आज सब चुप था।

तारा के पाँव के नीचे चिकनी रेत थी। छप छप, छप छप — बस यही एक आवाज़ थी।

ऊपर देखा, चाँद चुप था। नीचे देखा, पानी चुप था। दूर देखा, पहाड़ चुप थे। बस तारा की साँस — वो भी धीरे धीरे।

TARA: "नदी, तुम क्यों चुप हो आज?"

नदी ने जवाब नहीं दिया। बस धीरे धीरे बहती रही।

तारा रुकी। एक बहुत पुराना, गोल, गहरा पत्थर किनारे पर बैठा था। तारा को लगा जैसे वो साँस ले रहा हो।

OLD PATTHAR: "बेटा, चुप नहीं है। सुन रही है।"

TARA: "क्या सुन रही है?"

OLD PATTHAR: "सब कुछ — हर साँस, हर सपना, हर छोटी सी हलचल। दिखाऊँ?"

[BREATHE_GUIDE]
धीरे धीरे साँस अंदर लो... नाक से... और फिर धीरे से बाहर छोड़ो... मुँह से... बस। ऐसे ही।
[/BREATHE_GUIDE]
[BREATHE]

तारा ने एक नन्हा हरा पत्ता उठाया।

OLD PATTHAR: "इसे पानी पर रखो। लेकिन — धीरे साँस लेते हुए। तेज़ साँस से पत्ता डूब जाएगा।"

तारा ने साँस ली। लंबी, धीमी साँस। पत्ते को छुआ — पानी पर। पत्ता तैरने लगा। बहुत हल्के से, बहुत धीरे।

[BREATHE]

[PHRASE]नदी सुन रही है[/PHRASE]

पानी ने पत्ते को नहीं डुबोया। बस गोदी में ले लिया।

तारा मुस्कुराई। पहली बार आज रात।

OLD PATTHAR: "अब चुप होकर सुनो। नदी क्या कह रही है।"

तारा चुप हो गई। साँस बहुत हल्की। नदी के पानी पर चाँद की रोशनी टिमटिमा रही थी। हवा रुक गई थी। पत्ता अब भी तैर रहा था — बहुत आराम से।

और तब — दूर कहीं — एक धीमी सी गुनगुनाहट। गुनगुन गुनगुन, गुनगुन गुनगुन। नदी के अंदर से। जैसे कोई पुरानी लोरी।

तारा ने आँखें खोलीं। पत्थर मुस्कुरा रहा था।

OLD PATTHAR: "सुनती हो? बस सुनती रहो। चुप होकर। बस सुनती रहो।"

[SONG_SEED: The old riverbank stone hummed an ancient lori about every tear ever cried into the river, soft and slow.]

[POST_SONG]
तारा की आँखें थोड़ी भारी हो गईं। लेकिन अभी नींद नहीं — अभी बस सुनना। पत्थर भी धीरे धीरे साँस ले रहा था।

[PHASE_2]
और तारा ने समझा — नदी चुप नहीं थी। बस सुन रही थी। दिनभर के सपनों को। दिनभर के आँसुओं को। हर छोटी बात को।

जो भी बच्चा कभी रोया था — नदी ने सुना था। जो भी हँसा था — नदी ने सुना था। जो भी थका हुआ सोया था — नदी ने उसकी साँसें सुनी थीं।

OLD PATTHAR: "तारा, देखो। पत्ते।"

किनारे पर बहुत सारे पत्ते थे। हर पत्ता पानी पर तैर रहा था। और हर पत्ते के साथ — एक हल्की सी फुसफुसाहट।

TARA: "ये क्या कह रहे हैं?"

OLD PATTHAR: "हर पत्ता एक सपना है। और नदी सब सुन रही है।"

[BREATHE]

तारा ने एक और लंबी साँस ली। और देखा — एक पत्ता धीरे धीरे डूब रहा था। नींद की तरफ़।

पत्ते के पीछे एक और पत्ता। उसके पीछे एक और। हर पत्ता थोड़ी सी बूंदबूंद होकर पानी में मिल रहा था। बहुत धीरे। बहुत आराम से।

तारा ने उँगली नदी में डाली। ठंडा पानी, बहुत ठंडा। और नदी? नदी ने उँगली को पकड़ लिया, बहुत हल्के से। जैसे कोई दादी अपने पोते का हाथ पकड़ती है।

TARA: "नदी, तुम सब कुछ सुनती हो?"

OLD PATTHAR: "हाँ बेटा। हर दिल की बात।"

[PHRASE]नदी सुन रही है[/PHRASE]

हवा और भी धीमी हो गई। दूर कहीं, एक जुगनू अपनी रोशनी बंद करके सो गया। फिर एक और। फिर एक और। और एक एक करके सब जुगनू सो गए। बस एक रह गया — सबसे छोटा, किनारे पर बैठा, धीरे धीरे टिमटिमा रहा।

तारा ने पत्थर को देखा। पत्थर की आँखें — अगर पत्थर की आँखें होती हैं — आधी बंद थीं।

OLD PATTHAR: "अब मैं भी आराम करूँगा। तुम बैठो। नदी पास है।"

TARA: "अच्छा। मैं भी सुनती रहूँगी।"

पत्थर चुप हो गया। पूरी तरह चुप। बस साँस — धीरे, बहुत धीरे। साँस की एक छोटी सी आवाज़ — फिर कुछ नहीं।

तारा अकेली थी। लेकिन अकेली नहीं। नदी पास थी। पत्ते पास थे। चाँद पास था। और सबसे ज़रूरी — साँस पास थी।

[BREATHE]

और हर पत्ता धीरे धीरे डूबने लगा। और हर बूँद धीरे धीरे शाँत हो गई। और तारा की आँखें — और भारी होती गईं।

आख़िरी जुगनू ने भी अपनी रोशनी बंद कर दी।

नदी ने तारा को गोदी में ले लिया। बहुत नरम। बहुत धीरे।

[PHRASE]नदी सुन रही है[/PHRASE]

[PHASE_3]
रात धीमी है। हवा शाँत है। पानी नरम है।

नदी का गाना अब और धीमा है। पत्ते सब डूब गए। सपनों के साथ। चाँद की रोशनी पानी पर पिघल रही है।

तारा की साँस लंबी है। बहुत लंबी। और भी लंबी।

नरम।

धीमा।

शाँत।

जुगनू सब सो गए। नदी अब भी सुन रही है। पत्थर अब भी पास है।

चाँद नरम है। बहुत नरम। पानी पर तैर रहा है।

पत्थर साँस ले रहा है। बहुत धीरे। बहुत बहुत धीरे।

हवा बस छू रही है। तारा के बालों को। पत्थर के सर को। नदी की नरम बूँदों को।

नरम और धीमा और शाँत।

नरम और शाँत।

नरम।

शाँत।

धीमा।

तारा की साँस — एक — और — एक — और।

टप टप, टप टप — बूँदें छोटी हैं। आवाज़ें छोटी हैं। दुनिया छोटी हो रही है।

[PHRASE]नदी सुन रही है[/PHRASE]

छोटी।

और छोटी।

और भी छोटी।

रात धीमी। हवा धीमी। पानी धीमा। साँस धीमी।

धीमा और धीमा और धीमा।

धीमा।

बहुत धीमा।

रात कितनी नरम है। चाँद कितना दूर है। नदी कितनी पास है।

पास।

बहुत पास।

बस यहीं।

बस अब।

बस नदी जाग रही है। अब भी सुन रही है। हमेशा सुनती रही है।

लेकिन तारा? तारा अब सपनों में है। पत्थर भी सपनों में है। पत्ते भी सपनों में।

नींद आ गई।

धीरे।

बहुत धीरे।

बहुत बहुत धीरे।

नदी अब भी बह रही है। अब भी सुन रही है। अब भी पास है।

बस। बस। बस।

शाँत और नरम।

शाँत।

नरम।

बस।

[WHISPER]
नदी।
शाँत।
साँस।
अब।
[/WHISPER]
"""

LONG_TEXT_ROMAN = """[CHARACTER: Tara, gentle, dreamy, female]
[CHARACTER: Old Patthar, wise, quiet, neutral]

[INTRO]
Suno na, ek nadi hai — Sapnon Ki Nadi. Wahaan har boond ek puraani kahaani yaad rakhti hai. Aur aaj raat — kuch alag hua hai.

[PHASE_1]
Tara dheere dheere chal rahi thi. Sapnon Ki Nadi ka kinaara naram tha, thandi ret jaisi. Hawa halki thi. Aur nadi? Nadi chup thi. Pata hai, Sapnon Ki Nadi har raat gungunaati hai — har boond ek chhoti si awaaz. Lekin aaj? Aaj sab chup tha.

Tara ke paaon ke neeche chikni ret thi. Chhap chhap, chhap chhap — bas yahi ek awaaz thi.

Upar dekha, chaand chup tha. Neeche dekha, paani chup tha. Door dekha, pahaad chup the. Bas Tara ki saans — wo bhi dheere dheere.

TARA: "Nadi, tum kyun chup ho aaj?"

Nadi ne jawaab nahin diya. Bas dheere dheere behti rahi.

Tara ruki. Ek bahut puraana, gol, gehra patthar kinaare par baitha tha. Tara ko laga jaise wo saans le raha ho.

OLD PATTHAR: "Beta, chup nahin hai. Sun rahi hai."

TARA: "Kya sun rahi hai?"

OLD PATTHAR: "Sab kuch — har saans, har sapna, har chhoti si halchal. Dikhaaun?"

[BREATHE_GUIDE]
Dheere dheere saans andar lo... naak se... aur phir dheere se baahar chhodo... muh se... bas. Aise hi.
[/BREATHE_GUIDE]
[BREATHE]

Tara ne ek nanha hara patta uthaya.

OLD PATTHAR: "Ise paani par rakho. Lekin — dheere saans lete hue. Tez saans se patta doob jaayega."

Tara ne saans li. Lambi, dheemi saans. Patte ko chhua — paani par. Patta tairne laga. Bahut halke se, bahut dheere.

[BREATHE]

[PHRASE]Nadi sun rahi hai[/PHRASE]

Paani ne patte ko nahin duboya. Bas godi mein le liya.

Tara muskuraayi. Pehli baar aaj raat.

OLD PATTHAR: "Ab chup hokar suno. Nadi kya keh rahi hai."

Tara chup ho gayi. Saans bahut halki. Nadi ke paani par chaand ki roshni timtimaa rahi thi. Hawa ruk gayi thi. Patta ab bhi tair raha tha — bahut aaraam se.

Aur tab — door kahin — ek dheemi si gungunahat. Gunghun gunghun, gunghun gunghun. Nadi ke andar se. Jaise koi puraani lori.

Tara ne aankhein kholin. Patthar muskuraa raha tha.

OLD PATTHAR: "Sunti ho? Bas sunti raho. Chup hokar. Bas sunti raho."

[SONG_SEED: The old riverbank stone hummed an ancient lori about every tear ever cried into the river, soft and slow.]

[POST_SONG]
Tara ki aankhein thodi bhaari ho gayin. Lekin abhi neend nahin — abhi bas sunna. Patthar bhi dheere dheere saans le raha tha.

[PHASE_2]
Aur Tara ne samjha — nadi chup nahin thi. Bas sun rahi thi. Dinbhar ke sapno ko. Dinbhar ke aansoon ko. Har chhoti baat ko.

Jo bhi bachcha kabhi roya tha — nadi ne suna tha. Jo bhi hansa tha — nadi ne suna tha. Jo bhi thaka hua soya tha — nadi ne uski saansein suni thin.

OLD PATTHAR: "Tara, dekho. Patte."

Kinaare par bahut saare patte the. Har patta paani par tair raha tha. Aur har patte ke saath — ek halki si phusphusahat.

TARA: "Ye kya keh rahe hain?"

OLD PATTHAR: "Har patta ek sapna hai. Aur nadi sab sun rahi hai."

[BREATHE]

Tara ne ek aur lambi saans li. Aur dekha — ek patta dheere dheere doob raha tha. Neend ki taraf.

Patte ke peechhe ek aur patta. Uske peechhe ek aur. Har patta thodi si boondboond hokar paani mein mil raha tha. Bahut dheere. Bahut aaraam se.

Tara ne ungli nadi mein daali. Thanda paani, bahut thanda. Aur nadi? Nadi ne ungli ko pakad liya, bahut halke se. Jaise koi daadi apne pote ka haath pakadti hai.

TARA: "Nadi, tum sab kuch sunti ho?"

OLD PATTHAR: "Haan beta. Har dil ki baat."

[PHRASE]Nadi sun rahi hai[/PHRASE]

Hawa aur bhi dheemi ho gayi. Door kahin, ek jugnu apni roshni band karke so gaya. Phir ek aur. Phir ek aur. Aur ek ek karke sab jugnu so gaye. Bas ek reh gaya — sabse chhota, kinaare par baitha, dheere dheere timtimaa raha.

Tara ne patthar ko dekha. Patthar ki aankhein — agar patthar ki aankhein hoti hain — aadhi band thin.

OLD PATTHAR: "Ab main bhi aaraam karoonga. Tum baitho. Nadi paas hai."

TARA: "Achha. Main bhi sunti rahoongi."

Patthar chup ho gaya. Poori tarah chup. Bas saans — dheere, bahut dheere. Saans ki ek chhoti si awaaz — phir kuch nahin.

Tara akeli thi. Lekin akeli nahin. Nadi paas thi. Patte paas the. Chaand paas tha. Aur sabse zaroori — saans paas thi.

[BREATHE]

Aur har patta dheere dheere doobne laga. Aur har boond dheere dheere shaant ho gayi. Aur Tara ki aankhein — aur bhaari hoti gayin.

Aakhri jugnu ne bhi apni roshni band kar di.

Nadi ne Tara ko godi mein le liya. Bahut naram. Bahut dheere.

[PHRASE]Nadi sun rahi hai[/PHRASE]

[PHASE_3]
Raat dheemi hai. Hawa shaant hai. Paani naram hai.

Nadi ka gaana ab aur dheema hai. Patte sab doob gaye. Sapnon ke saath. Chaand ki roshni paani par pighal rahi hai.

Tara ki saans lambi hai. Bahut lambi. Aur bhi lambi.

Naram.

Dheema.

Shaant.

Jugnu sab so gaye. Nadi ab bhi sun rahi hai. Patthar ab bhi paas hai.

Chaand naram hai. Bahut naram. Paani par tair raha hai.

Patthar saans le raha hai. Bahut dheere. Bahut bahut dheere.

Hawa bas chhoo rahi hai. Tara ke baalon ko. Patthar ke sir ko. Nadi ki naram boondon ko.

Naram aur dheema aur shaant.

Naram aur shaant.

Naram.

Shaant.

Dheema.

Tara ki saans — ek — aur — ek — aur.

Tap tap, tap tap — boondein chhoti hain. Awaazein chhoti hain. Duniya chhoti ho rahi hai.

[PHRASE]Nadi sun rahi hai[/PHRASE]

Chhoti.

Aur chhoti.

Aur bhi chhoti.

Raat dheemi. Hawa dheemi. Paani dheema. Saans dheemi.

Dheema aur dheema aur dheema.

Dheema.

Bahut dheema.

Raat kitni naram hai. Chaand kitna door hai. Nadi kitni paas hai.

Paas.

Bahut paas.

Bas yahin.

Bas ab.

Bas nadi jaag rahi hai. Ab bhi sun rahi hai. Hamesha sunti rahi hai.

Lekin Tara? Tara ab sapnon mein hai. Patthar bhi sapnon mein hai. Patte bhi sapnon mein.

Neend aa gayi.

Dheere.

Bahut dheere.

Bahut bahut dheere.

Nadi ab bhi beh rahi hai. Ab bhi sun rahi hai. Ab bhi paas hai.

Bas. Bas. Bas.

Shaant aur naram.

Shaant.

Naram.

Bas.

[WHISPER]
Nadi.
Shaant.
Saans.
Ab.
[/WHISPER]
"""

LONG_STORY["full_text_deva"] = LONG_TEXT_DEVA
LONG_STORY["full_text_roman"] = LONG_TEXT_ROMAN


# ════════════════════════════════════════════════════════════════════════
# RENDER HELPERS
# ════════════════════════════════════════════════════════════════════════

def _word_count(s: str) -> int:
    body = re.sub(r"\[[^\]]+\]\s*", "", s)
    return len(body.split())


def render_lullaby_audio() -> AudioSegment:
    """Single MiniMax v2.5 + Hindi reference call."""
    print(f"\n═══ LULLABY audio (MiniMax v2.5 + Hindi reference) ═══")
    style = (
        "Sweet Indian closing-time lori sung in Hindi, warm cheerful female "
        "vocal saying goodnight to objects in the room, soft harmonium and "
        "gentle hum, 60 BPM, lilting bedtime melody, cozy evening, smiling "
        "maternal voice, happy nursery feel, major key, native Hindi "
        "pronunciation"
    )
    body = (
        f"{style}.\n\n"
        "Sing the following Hindi (Devanagari) lyrics clearly, in a native "
        "North Indian female voice, with conversational mother-tongue "
        "pronunciation — not a Western or Chinese vocal lens.\n\n"
        f"Lyrics:\n{LULLABY['lyrics_deva']}"
    )
    audio_bytes = minimax_lullaby(body, LULLABY["lyrics_deva"])
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    print(f"  duration: {len(seg) / 1000:.1f}s")
    return seg


def parse_short_segments(text_deva: str) -> list:
    """Tokenise short-story Devanagari into segments (narration + tags)."""
    segs: list = []
    tag_re = re.compile(
        r"(\[PHRASE\](.*?)\[/PHRASE\]|\[PAUSE:\s*(\d+)\])",
        re.DOTALL,
    )
    pos = 0
    for m in tag_re.finditer(text_deva):
        gap = text_deva[pos:m.start()].strip()
        if gap:
            for line in [l.strip() for l in gap.split("\n") if l.strip()]:
                if line.startswith('"') or line.startswith("\""):
                    # dialogue line — strip quotes
                    line = line.strip("\"")
                segs.append({"kind": "narration", "content": line})
        token = m.group(0)
        if token.startswith("[PHRASE]"):
            segs.append({"kind": "phrase", "content": m.group(2).strip()})
        elif token.startswith("[PAUSE:"):
            segs.append({"kind": "pause", "ms": int(m.group(3))})
        pos = m.end()
    tail = text_deva[pos:].strip()
    if tail:
        for line in [l.strip() for l in tail.split("\n") if l.strip()]:
            segs.append({"kind": "narration", "content": line})
    return segs


def render_short_story_audio() -> AudioSegment:
    """Single-voice ElevenLabs render of the short story."""
    print(f"\n═══ SHORT STORY audio (ElevenLabs Multilingual v2, voice=anika) ═══")
    voice_id = ELEVENLABS_VOICES["anika"]
    segments = parse_short_segments(SHORT_STORY["text_deva"])
    counts = {}
    for s in segments:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    print(f"  segments: {counts}")

    timeline = AudioSegment.silent(duration=0)
    for i, seg in enumerate(segments):
        kind = seg["kind"]
        if kind == "pause":
            timeline += AudioSegment.silent(duration=seg["ms"])
            continue
        text = normalize_for_tts(_ensure_terminal(seg["content"]))
        if kind == "phrase":
            preset = PHRASE_TTS
        else:
            preset = PHASE_TTS[2]  # phase-2 dynamics: stability 0.75, speed 0.80
        prev = segments[i - 1]["content"] if i > 0 and segments[i - 1].get("content") else ""
        nxt  = segments[i + 1]["content"] if i + 1 < len(segments) and segments[i + 1].get("content") else ""
        rendered = elevenlabs_tts(
            text, voice_id,
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt,
        )
        timeline += AudioSegment.silent(duration=180)
        timeline += rendered
        if kind == "phrase":
            timeline += AudioSegment.silent(duration=900)
        else:
            timeline += AudioSegment.silent(duration=350)

    print(f"  duration: {len(timeline) / 1000:.1f}s")
    return timeline


def render_long_story_audio(song_audio: AudioSegment) -> AudioSegment:
    """Long-story render — multi-voice + bed/swells, mirroring the chnd flow."""
    print(f"\n═══ LONG STORY audio (ElevenLabs multi-voice + bed/swells) ═══")
    segments = parse_long_segments(LONG_STORY["full_text_deva"])
    counts = {}
    for s in segments:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    print(f"  segments: {counts}")

    char_voice = {
        "TARA":        "anika",
        "OLD PATTHAR": "kuber_j",
    }
    NARRATOR_VOICE = "tripti"
    WHISPER_VOICE = "roohi"

    text_segs = [(i, s) for i, s in enumerate(segments)
                 if s["kind"] in ("narration", "dialogue", "phrase",
                                  "whisper", "breathe_guide")]
    neighbor: dict = {}
    for j, (i, s) in enumerate(text_segs):
        prev_text = text_segs[j - 1][1]["content"] if j > 0 else ""
        next_text = text_segs[j + 1][1]["content"] if j + 1 < len(text_segs) else ""
        neighbor[i] = (prev_text, next_text)

    def render_seg(idx: int, seg: dict) -> AudioSegment | None:
        kind = seg["kind"]
        if kind == "pause":
            return AudioSegment.silent(duration=seg["ms"])
        if kind == "breathe":
            return AudioSegment.silent(duration=5000)
        if kind == "song":
            return song_audio
        prev, nxt = neighbor.get(idx, ("", ""))
        phase = seg.get("phase", 1)
        if kind == "dialogue":
            voice_label = char_voice.get(seg["character"], NARRATOR_VOICE)
            preset = PHASE_TTS[phase]
            text = _ensure_terminal(seg["content"])
        elif kind == "phrase":
            voice_label = NARRATOR_VOICE
            preset = PHRASE_TTS
            text = _ensure_terminal(seg["content"])
        elif kind == "whisper":
            voice_label = WHISPER_VOICE
            preset = WHISPER_TTS
            text = _ensure_terminal(seg["content"])
        elif kind == "breathe_guide":
            voice_label = NARRATOR_VOICE
            preset = {"stability": 0.85, "style": 0.00, "speed": 0.72}
            text = seg["content"]
        elif kind == "narration":
            voice_label = NARRATOR_VOICE
            preset = INTRO_TTS if seg.get("section") == "intro" else PHASE_TTS[phase]
            text = seg["content"]
        else:
            return None
        text = normalize_for_tts(text)
        voice_id = ELEVENLABS_VOICES[voice_label]
        return elevenlabs_tts(
            text, voice_id,
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt,
        )

    def stitch(section: str, gap_ms: int):
        out = AudioSegment.silent(duration=0)
        breathes: list[int] = []
        for idx, seg in enumerate(segments):
            if seg.get("section") != section:
                continue
            if seg["kind"] == "song":
                continue
            if seg["kind"] == "breathe":
                breathes.append(len(out))
                out += AudioSegment.silent(duration=5000)
                continue
            if seg["kind"] == "breathe_guide":
                rendered = render_seg(idx, seg)
                if rendered is not None:
                    out += AudioSegment.silent(duration=180)
                    out += rendered
                breathes.append(len(out))
                out += AudioSegment.silent(duration=3000)
                continue
            rendered = render_seg(idx, seg)
            if rendered is None:
                continue
            if seg["kind"] in ("narration", "dialogue", "phrase", "whisper"):
                out += AudioSegment.silent(duration=180)
            out += rendered
            if seg["kind"] == "phrase":
                out += AudioSegment.silent(duration=900)
            elif seg["kind"] == "whisper":
                out += AudioSegment.silent(duration=600)
            elif seg["kind"] in ("narration", "dialogue"):
                out += AudioSegment.silent(duration=gap_ms)
        return out, breathes

    # ── Music assets
    intro_music = AudioSegment.from_wav(str(MUSIC_DIR / "intro_calm.wav"))
    bed_raw = AudioSegment.from_wav(str(MUSIC_DIR / "bed_calm.wav"))

    timeline = intro_music + AudioSegment.silent(duration=2000)

    # ── Part A: intro + phase_1, bed -20 dB
    intro_audio, ib = stitch("intro", 300)
    p1_audio, p1b = stitch("phase_1", 300)
    gap_a = AudioSegment.silent(duration=1000)
    part_a_voice = intro_audio + gap_a + p1_audio
    p1_offset = len(intro_audio) + len(gap_a)
    a_breathes = ib + [p + p1_offset for p in p1b]
    part_a_bed = _trim_or_loop(bed_raw, len(part_a_voice)) - 20
    part_a_bed = _apply_breathe_swells(part_a_bed, a_breathes, -20).fade_out(2000)
    timeline += part_a_voice.overlay(part_a_bed)

    # ── Song
    if song_audio is not None:
        song_with_fades = (
            AudioSegment.silent(duration=500)
            + song_audio.fade_in(2000).fade_out(2000)
            + AudioSegment.silent(duration=500)
        )
        timeline += song_with_fades

    # ── Part B: post_song + phase_2, bed -14 dB
    post_audio, pb = stitch("post_song", 500)
    p2_audio, p2b = stitch("phase_2", 500)
    gap_b = AudioSegment.silent(duration=1000)
    part_b_voice = post_audio + gap_b + p2_audio
    p2_offset = len(post_audio) + len(gap_b)
    b_breathes = pb + [p + p2_offset for p in p2b]
    part_b_bed = _trim_or_loop(bed_raw, len(part_b_voice)) - 14
    part_b_bed = _apply_breathe_swells(part_b_bed, b_breathes, -14).fade_in(2000)
    timeline += part_b_voice.overlay(part_b_bed)

    # ── Part C: phase_3, bed -10 dB + 30s tail
    p3_audio, p3b = stitch("phase_3", 800)
    p3_bed_full = _trim_or_loop(bed_raw, len(p3_audio) + 30000) - 10
    p3_bed_full = _apply_breathe_swells(p3_bed_full, p3b, -10)
    timeline += p3_audio.overlay(p3_bed_full[:len(p3_audio)])
    tail = p3_bed_full[len(p3_audio):len(p3_audio) + 30000].fade_out(15000)
    timeline += tail

    print(f"  duration: {len(timeline) / 1000:.1f}s ({len(timeline) / 60000:.1f}m)")
    return timeline


def render_long_song() -> AudioSegment:
    """Embedded mid-story song via MiniMax v2.5 + Hindi reference."""
    print(f"\n═══ LONG STORY embedded song (MiniMax v2.5) ═══")
    audio_bytes = minimax_lullaby(
        LONG_STORY["song_style_prompt"],
        LONG_STORY["song_lyrics_deva"],
    )
    song = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    if len(song) > 45000:
        song = song[:45000].fade_out(2000)
    print(f"  song duration: {len(song) / 1000:.1f}s")
    return song


def generate_cover_together(prompt: str, w: int = 1024, h: int = 1024) -> bytes | None:
    print(f"  FLUX prompt ({len(prompt)} chars): {prompt[:120]}…")
    try:
        resp = httpx.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {TOGETHER_KEY}"},
            json={
                "model": "black-forest-labs/FLUX.1-schnell",
                "prompt": prompt,
                "width": w, "height": h,
                "n": 1, "response_format": "b64_json",
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


# ════════════════════════════════════════════════════════════════════════
# SAVE TO FILESYSTEM
# ════════════════════════════════════════════════════════════════════════

def save_lullaby(audio: AudioSegment, cover_png: bytes) -> dict:
    sid = LULLABY["id"]
    duration = round(len(audio) / 1000)

    # Audio paths
    seed_audio = BASE_DIR / "seed_output" / "lullabies" / f"{sid}.mp3"
    web_audio  = WEB_ROOT / "public" / "audio" / "lullabies" / f"{sid}.mp3"
    pre_gen    = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_female_1.mp3"
    for p in (seed_audio, web_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
        audio.export(p, format="mp3", bitrate="192k")

    # Cover
    img = Image.open(io.BytesIO(cover_png)).convert("RGB").resize((1024, 1024), Image.LANCZOS)
    seed_cover = BASE_DIR / "seed_output" / "lullabies" / f"{sid}_cover.webp"
    web_cover_l = WEB_ROOT / "public" / "covers" / "lullabies" / f"{sid}_cover.webp"
    web_cover_root = WEB_ROOT / "public" / "covers" / f"{sid}.webp"
    for p in (seed_cover, web_cover_l, web_cover_root):
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)

    entry = {
        "id": sid,
        "type": "song",
        "lang": "hi",
        "language": "hi",
        "story_format": "lullaby",
        "story_type": "lullaby",
        "storyType": "lullaby",
        "title": LULLABY["title"],
        "title_deva": LULLABY["title_deva"],
        "title_en": LULLABY["title_en"],
        "card_label": LULLABY["card_label"],
        "card_subtitle": LULLABY["card_subtitle"],
        "description": LULLABY["card_subtitle"],
        "description_en": "Goodnight to the fan, the moon, and Mummy — until morning",
        "lullaby_type": LULLABY["lullaby_type"],
        "age_group": LULLABY["age_group"],
        "ageGroup": LULLABY["age_group"],
        "age_min": LULLABY["age_min"],
        "age_max": LULLABY["age_max"],
        "target_age": (LULLABY["age_min"] + LULLABY["age_max"]) // 2,
        "mood": LULLABY["mood"],
        "instruments": LULLABY["instruments"],
        "tempo": LULLABY["tempo"],
        "text": LULLABY["lyrics_roman"],
        "text_deva": LULLABY["lyrics_deva"],
        "lyrics": LULLABY["lyrics_roman"],
        "lyrics_deva": LULLABY["lyrics_deva"],
        "characterType": "human_child",
        "lead_character_type": "human_child",
        "audio_url": f"/audio/lullabies/{sid}.mp3",
        "audio_variants": [{
            "voice": "minimax_v2.5_hi_ref",
            "url": f"/audio/lullabies/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5-fal",
        }],
        "cover": f"/covers/{sid}.webp",
        "cover_file": f"/covers/lullabies/{sid}_cover.webp",
        "cover_context": LULLABY["cover_context"],
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "minimax-music-v2.5-fal",
        "tts_engine": "minimax-music-v2.5-fal",
        "reference_audio": "https://dreamvalley.app/audio/reference/hindi_lullaby_ref.m4a",
        "experimental_v2": False,
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Lullaby"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Append to lullabies.json index
    idx_path = BASE_DIR / "seed_output" / "lullabies" / "lullabies.json"
    if idx_path.exists():
        idx_data = json.loads(idx_path.read_text())
        items = idx_data.get("items", idx_data) if isinstance(idx_data, dict) else idx_data
    else:
        idx_data, items = [], []
    items = [i for i in items if i.get("id") != sid]
    items.append(entry)
    if isinstance(idx_data, dict):
        idx_data["items"] = items
    else:
        idx_data = items
    idx_path.write_text(json.dumps(idx_data, ensure_ascii=False, indent=2))
    print(f"  lullabies.json: total {len(items)}")
    return entry


def save_short_story(audio: AudioSegment, cover_png: bytes) -> dict:
    sid = SHORT_STORY["id"]
    duration = round(len(audio) / 1000)

    pre_gen = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_anika.mp3"
    seed_audio = BASE_DIR / "seed_output" / "stories_hi" / f"{sid}.mp3"
    for p in (seed_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
        audio.export(p, format="mp3", bitrate="192k")

    img = Image.open(io.BytesIO(cover_png)).convert("RGB").resize((1024, 1024), Image.LANCZOS)
    cover_root = WEB_ROOT / "public" / "covers" / f"{sid}.webp"
    seed_cover = BASE_DIR / "seed_output" / "stories_hi" / f"{sid}_cover.webp"
    for p in (cover_root, seed_cover):
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)

    # Strip tags for displayed text
    display_roman = strip_long_story_tags(SHORT_STORY["text_roman"])
    display_deva  = strip_long_story_tags(SHORT_STORY["text_deva"])

    entry = {
        "id": sid,
        "type": "story",
        "lang": "hi",
        "language": "hi",
        "title": SHORT_STORY["title"],
        "title_deva": SHORT_STORY["title_deva"],
        "title_en": SHORT_STORY["title_en"],
        "description": SHORT_STORY["description"],
        "description_en": SHORT_STORY["description_en"],
        "text": display_roman,
        "text_deva": display_deva,
        "raw_text": SHORT_STORY["text_roman"],
        "raw_text_deva": SHORT_STORY["text_deva"],
        "character": SHORT_STORY["character"],
        "character_name": SHORT_STORY["character"]["name"],
        "characterType": SHORT_STORY["characterType"],
        "lead_character_type": SHORT_STORY["lead_character_type"],
        "lead_gender": SHORT_STORY["lead_gender"],
        "age_group": SHORT_STORY["age_group"],
        "ageGroup": SHORT_STORY["age_group"],
        "age_min": SHORT_STORY["age_min"],
        "age_max": SHORT_STORY["age_max"],
        "target_age": (SHORT_STORY["age_min"] + SHORT_STORY["age_max"]) // 2,
        "mood": SHORT_STORY["mood"],
        "geography": SHORT_STORY["geography"],
        "indian_region": SHORT_STORY["indian_region"],
        "theme": SHORT_STORY["theme"],
        "themes": [SHORT_STORY["theme"], "patience"],
        "audio_url": f"/audio/pre-gen/{sid}_anika.mp3",
        "audio_variants": [{
            "voice": "anika",
            "url": f"/audio/pre-gen/{sid}_anika.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "cover": f"/covers/{sid}.webp",
        "cover_context": SHORT_STORY["cover_context"],
        "duration_seconds": duration,
        "durationSec": duration,
        "tts_engine": "elevenlabs_multilingual_v2",
        "tts_input_script": "devanagari",
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Short Story"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return entry


def save_long_story(audio: AudioSegment, cover_png: bytes, song_seconds: int) -> dict:
    sid = LONG_STORY["id"]
    duration = round(len(audio) / 1000)

    pre_gen = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_tripti.mp3"
    seed_audio = BASE_DIR / "seed_output" / "hindi_long" / f"{sid}.mp3"
    for p in (seed_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
        audio.export(p, format="mp3", bitrate="192k")

    img = Image.open(io.BytesIO(cover_png)).convert("RGB").resize((1024, 1024), Image.LANCZOS)
    cover_root = WEB_ROOT / "public" / "covers" / f"{sid}.webp"
    seed_cover = BASE_DIR / "seed_output" / "hindi_long" / f"{sid}_cover.webp"
    for p in (cover_root, seed_cover):
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)

    display_roman = strip_long_story_tags(LONG_STORY["full_text_roman"])
    display_deva  = strip_long_story_tags(LONG_STORY["full_text_deva"])

    p1 = re.search(r"\[PHASE_1\](.*?)(?=\[PHASE_2\])", LONG_STORY["full_text_roman"], re.DOTALL)
    p2 = re.search(r"\[PHASE_2\](.*?)(?=\[PHASE_3\])", LONG_STORY["full_text_roman"], re.DOTALL)
    p3 = re.search(r"\[PHASE_3\](.*)$", LONG_STORY["full_text_roman"], re.DOTALL)

    entry = {
        "id": sid,
        "type": "long_story",
        "lang": "hi",
        "language": "hi",
        "story_format": "long_story",
        "story_type": "long_story",
        "storyType": "long_story",
        "title": LONG_STORY["title"],
        "title_deva": LONG_STORY["title_deva"],
        "title_en": LONG_STORY["title_en"],
        "description": LONG_STORY["world_description"],
        "description_en": LONG_STORY["world_description_en"],
        "world_name": LONG_STORY["world_name"],
        "world_name_en": LONG_STORY["world_name_en"],
        "world_description": LONG_STORY["world_description"],
        "mystery": LONG_STORY["mystery"],
        "resolution": LONG_STORY["resolution"],
        "breathing_mechanic": LONG_STORY["breathing_mechanic"],
        "repeated_phrase": LONG_STORY["repeated_phrase"],
        "repeated_phrase_deva": LONG_STORY["repeated_phrase_deva"],
        "characters": LONG_STORY["characters"],
        "song_seed": LONG_STORY["song_seed"],
        "phase_1_text": p1.group(1).strip() if p1 else "",
        "phase_2_text": p2.group(1).strip() if p2 else "",
        "phase_3_text": p3.group(1).strip() if p3 else "",
        "text": display_roman,
        "text_deva": display_deva,
        "raw_text": LONG_STORY["full_text_roman"],
        "raw_text_deva": LONG_STORY["full_text_deva"],
        "character": {
            "name": LONG_STORY["characters"][0]["name"],
            "identity": LONG_STORY["characters"][0]["identity"],
            "personality_tags": [LONG_STORY["characters"][0]["personality"].title(),
                                 LONG_STORY["characters"][0]["voice_style"].title()],
        },
        "character_name": LONG_STORY["characters"][0]["name"],
        "characterType": LONG_STORY["lead_character_type_canonical"],
        "lead_character_type": LONG_STORY["lead_character_type_canonical"],
        "lead_gender": LONG_STORY["gender_lead"],
        "age_group": "2-5",
        "ageGroup": "2-5",
        "age_min": 2,
        "age_max": 5,
        "target_age": 4,
        "mood": "calm",
        "theme": "rest",
        "themes": ["rest", "listening"],
        "geography": LONG_STORY["geography"],
        "indian_region": LONG_STORY["indian_region"],
        "experimental_v2": False,
        "has_baked_music": True,
        "tts_engine": LONG_STORY["tts_engine"],
        "tts_input_script": LONG_STORY["tts_input_script"],
        "voice_routing": {
            "narrator": "tripti",
            "whisper": "roohi",
            "characters": {"TARA": "anika", "OLD PATTHAR": "kuber_j"},
        },
        "embedded_song_seconds": song_seconds,
        "audio_url": f"/audio/pre-gen/{sid}_tripti.mp3",
        "audio_variants": [{
            "voice": "tripti",
            "url": f"/audio/pre-gen/{sid}_tripti.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "cover": f"/covers/{sid}.webp",
        "cover_context": LONG_STORY["cover_context"],
        "duration_seconds": duration,
        "durationSec": duration,
        "word_count": _word_count(LONG_STORY["full_text_roman"]),
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Long Story"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
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


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n═══ Word counts ═══")
    print(f"  short story: {_word_count(SHORT_STORY['text_roman'])} words (target 200-400)")
    print(f"  long story:  {_word_count(LONG_STORY['full_text_roman'])} words (target 1040-1520)")

    # 1. LULLABY
    lullaby_audio = render_lullaby_audio()
    print(f"\n═══ Lullaby cover (Together AI FLUX) ═══")
    lullaby_cover = generate_cover_together(LULLABY["cover_context"])
    if not lullaby_cover:
        sys.exit("❌ lullaby cover failed")
    lullaby_entry = save_lullaby(lullaby_audio, lullaby_cover)

    # 2. SHORT STORY
    short_audio = render_short_story_audio()
    print(f"\n═══ Short-story cover (Together AI FLUX) ═══")
    short_cover = generate_cover_together(SHORT_STORY["cover_context"])
    if not short_cover:
        sys.exit("❌ short-story cover failed")
    short_entry = save_short_story(short_audio, short_cover)

    # 3. LONG STORY (most expensive — runs last so failures don't block 1+2)
    song = render_long_song()
    long_audio = render_long_story_audio(song)
    print(f"\n═══ Long-story cover (Together AI FLUX) ═══")
    long_cover = generate_cover_together(LONG_STORY["cover_context"])
    if not long_cover:
        sys.exit("❌ long-story cover failed")
    long_entry = save_long_story(long_audio, long_cover, round(len(song) / 1000))

    # ── Upsert all to content.json
    print(f"\n═══ Upsert to content.json ═══")
    upsert_content(lullaby_entry)
    upsert_content(short_entry)
    total = upsert_content(long_entry)
    print(f"  total items: {total}")

    # ── Per-item runtime files for /api/v1/* endpoints
    print(f"\n═══ Per-item runtime files ═══")
    # lullaby has no dedicated /api/v1 endpoint (lullabies are surfaced via
    # generic content), so no data/lullabies/ file needed.
    # short story = type "story" → surfaced via /api/v1/content?type=story
    # long story  = type "long_story" → same generic content endpoint
    # Both already covered by content.json upsert.
    print("  (lullaby + short + long all surface via /api/v1/content; no extra files needed)")

    print(f"\n═════ TRIPLET PUBLISH DONE ═════")
    print(f"  lullaby:     {LULLABY['id']}  ({round(len(lullaby_audio) / 1000)}s)")
    print(f"  short story: {SHORT_STORY['id']}  ({round(len(short_audio) / 1000)}s)")
    print(f"  long story:  {LONG_STORY['id']}  ({round(len(long_audio) / 1000)}s)")


if __name__ == "__main__":
    main()
