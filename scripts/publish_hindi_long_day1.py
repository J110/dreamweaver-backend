#!/usr/bin/env python3
"""Publish day-1 Hindi LONG story per HINDI_LONG_STORY_GUIDELINES.md.

Format: 3-phase Khoj/Vishraam/Vilay arc with embedded mid-story song,
multi-voice ElevenLabs TTS, breathing mechanic, and dissolution close.

This script implements (from /Users/anmolmohan/Downloads/HINDI_LONG_STORY_GUIDELINES.md):
  • §14 long-story tag set: [CHARACTER:], [INTRO], [PHASE_*],
    [BREATHE_GUIDE]/[/], [BREATHE], [PHRASE]/[/], [SONG_SEED:],
    [POST_SONG], [WHISPER]/[/], [PAUSE: ms], NAME: dialogue
  • §19 validator (14 checks)
  • §20 ElevenLabs voice mapping with phase-based settings:
      narrator      = Tripti (female, narrator)
      Anaya         = Anika (gentle young girl)
      Old Peepal    = Kuber J (deep, intimate male)
      whisper voice = Roohi (softest, slowest)
  • §10 mid-story song via fal-ai/minimax-music/v2.5 with Hindi reference
  • §6 mystery=rest pattern; §7 secular breathing; §11 Phase-3 dissolution

Story chosen for diversity vs published Hindi catalog:
  - "Anaya Aur Sota Hua Chaand" (Anaya and the Sleeping Moon)
  - World: Bargad Ghaati (banyan valley)
  - Mystery: Chaand ugna bhool gaya
  - Resolution: Chaand bargad ke andar so raha tha
  - Breathing mechanic: a diya that lights only with slow breath
  - Repeated phrase: "Chaand so raha hai"
  - Age 2-5, mood calm, North Indian setting

Both Roman (user-facing) and Devanagari (TTS engine) are stored.
ElevenLabs Multilingual v2 tokenises Devanagari as Hindi phonemes
cleanly; Roman degrades clarity (per fix_hindi_batch_day2 findings).
"""

from __future__ import annotations

import io
import json
import os
import re
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
from audio_assembly import normalize_for_tts, MUSIC_DIR
from fix_hindi_batch_day2 import minimax_lullaby  # reuse MiniMax pipe

load_dotenv(BASE_DIR / ".env", override=True)

ELEVENLABS_API_KEY = os.getenv(
    "ELEVENLABS_API_KEY",
    "sk_5bbd5d1a1ee9fa532c454154e2a7723f94ffc3bce07087ff",
)
FAL_KEY = os.getenv("FAL_KEY")
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

# ─── Voice library (existing + 3 new male voices per user request) ────────
ELEVENLABS_VOICES = {
    # existing female voices
    "tripti":   "yLldDJzoAIYirDpSiBvy",  # narrator (default)
    "roohi":    "oHNJagRZ2LQEfZb2CEkb",  # softest — used for [WHISPER]
    "anika":    "RABOvaPec1ymXz02oDQi",  # gentle young female
    "gudiya":   "csPuxct3x4tABDZeKliZ",
    "meher":    "JS6C6yu2x9Byh4i1a8lX",
    # NEW male voices (this batch)
    "raghav":   "4BoDaQ6aygOP6fpsUmJe",  # Calm, Confident and Engaging
    "kuber_j":  "mttGjNqgkgo5cciwsyoc",  # Deep, Intimate & Romantic — for Old Peepal
    "kiran":    "ss0PMu3rEfIwrYgOOl5S",  # Very Young, Cute & Engaging
}
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# Phase-based stability/speed (slower & softer through phases).
# Phase 1: lively but bedtime-paced. Phase 2: settling. Phase 3: dissolution.
PHASE_TTS = {
    1: {"stability": 0.70, "style": 0.00, "speed": 0.85},
    2: {"stability": 0.75, "style": 0.00, "speed": 0.80},
    3: {"stability": 0.85, "style": 0.00, "speed": 0.72},
}
PHRASE_TTS = {"stability": 0.85, "style": 0.00, "speed": 0.72}
WHISPER_TTS = {"stability": 0.95, "style": 0.00, "speed": 0.70}
INTRO_TTS = {"stability": 0.60, "style": 0.05, "speed": 0.90}
SONG_REF_FILE = BASE_DIR / "seed_output" / "hindi_lullaby_test_v26_reference" / "_reference_28s.m4a"


# ──────────────────────────────────────────────────────────────────────
# Story spec — §16 schema
# ──────────────────────────────────────────────────────────────────────
STORY_ID = "hi-long-2-5-chnd"
STORY_SLUG = "chnd"

# Character → ElevenLabs voice routing.
# Narrator = "tripti" (default for all narration outside dialogue).
# Whisper = "roohi" regardless of character.
CHAR_VOICE = {
    "ANAYA":      "anika",
    "OLD PEEPAL": "kuber_j",
    "GILOO":      "kiran",
}
NARRATOR_VOICE = "tripti"
WHISPER_VOICE = "roohi"

STORY_TEXT_ROMAN = """\
[CHARACTER: Anaya, gentle, dreamy, female]
[CHARACTER: Old Peepal, wise, quiet, neutral]
[CHARACTER: Giloo, curious, small, neutral]

[INTRO]
Suno na, ek Bargad Ghaati hai. Wahaan har patta ek puraani kahaani yaad rakhta hai. Aur aaj raat — kuch alag hua hai.

[PHASE_1]
Anaya dheere dheere chal rahi thi. Bargad Ghaati ki mitti naram thi, ekdam roti jaisi. Hawa thandi thandi thi. Aur jugnu? Jugnu kahin nahin the. Pata hai, Bargad Ghaati mein har raat hazaaron jugnu chamakte hain — har patte ke neeche, har shaakh par. Lekin aaj? Aaj sab chhup gaye the.

Anaya ke paaon ke neeche sookhe patte the. Khat khat, khat khat — bas yahi ek aawaz thi.

ANAYA: "Chaand kahaan hai? Aaj raat chaand nikla hi nahin."

Anaya ne upar dekha. Sirf kaala aasmaan, sirf taare. Kuch taare bhi soye soye se lag rahe the. Hawa ne sarr sarr ki — peepal ka bada sa ped jhoom raha tha. Itna bada peepal — uski shaakhein aasmaan tak pahunchti thin. Anaya ke daada ki daadi ne bhi yehi ped dekha tha, kehte the.

OLD PEEPAL: "Beta, ruk ja zara. Suno."

Anaya ruk gayi. Peepal ne dheere se aankhein kholin — itni purani aankhein, jaise sau saal se khuli ho. Tane par chhoti chhoti darrarein, jaise har darrar ek kahaani.

OLD PEEPAL: "Chaand kho nahin gaya hai, beta. Bas thak gaya hai. Roz aata hai, roz chamakta hai. Aaj raat... aaj raat usko aaraam chahiye tha."

ANAYA: "Toh hum kya karein, peepal dada?"

OLD PEEPAL: "Mere paas ek diya hai. Yeh diya bahut purana hai. Yeh diya tabhi jalta hai jab koi dheere dheere saans le. Tumne kabhi itni dheere saans li hai?"

Anaya ne sar hilaya. Pata nahin.

[BREATHE_GUIDE]
Toh chalo, ek baar saath karein. Dheere dheere saans andar lo... naak se... aur phir dheere se baahar chhodo... muh se... Bas. Aise hi.
[/BREATHE_GUIDE]
[BREATHE]

Anaya ne saans li. Lambi saans. Diya ki lau dheere se hili.

[BREATHE]

Aur phir aur dheere. Lau aur badhi. Ab diya jal raha tha — choti si pili roshni, jaise jugnu ho.

[PAUSE: 800]

Itne mein, ek mor aaya. Phir ek chhoti titli. Aur ek giloo bhi peepal ke tane se utri.

GILOO: "Arre, kya ho raha hai yahaan?"

ANAYA: "Hum chaand ko dhoondh rahe hain. Suno zara."

[PHRASE]Chaand so raha hai[/PHRASE]

Hawa ruk gayi. Peepal ka ek patta gira. Mor ne pankh band kar liye.

[SONG_SEED: The old peepal hummed a lullaby about the moon curling up to sleep inside a tree.]

[POST_SONG]
Anaya ne diya thama. Hawa naram thi ab. Sab kuch dheere ho raha tha.

[PHASE_2]
Diya ki roshni dheere dheere badhne lagi. Pehle thodi si pili. Phir naram naram chandi jaisi. Anaya ne diya peepal ke tane ki taraf le ja kar dekha. Tane mein ek bada sa khol tha — ek chhupa hua kona, jaise koi puraana darwaaza.

Aur — andar — kuch chamak raha tha. Naram, gol, chandi jaisa. Itni naram roshni jaise koi sapna kapde mein lipta ho.

ANAYA: "Yeh kya hai, peepal dada?"

OLD PEEPAL: "Yahi toh chaand hai, beta. Khoya nahin tha. Bas... so raha tha."

Aur sach mein, chaand wahaan tha. Choti si gol shakal mein, peepal ke andar curl karke. Jaise koi billi sapna dekh rahi ho. Saans le raha tha — dheere, dheere. Apni lambi yatra ke baad, bargad ke andar aaraam kar raha tha. Saalon se chaand har raat akele safar karta tha. Aaj usko bhi kisi ki god chahiye thi.

ANAYA: "Toh hum jagaye nahin?"

OLD PEEPAL: "Nahin. Bas saath baith jao. Aur dheere se saans lo. Chaand ko bhi pata chal jaayega koi paas hai."

[BREATHE]

Anaya baith gayi. Mor bhi aa gaya. Titli ne pankh band kar liye. Giloo peepal ke tane se chipak gayi.

GILOO: "Main bhi so jaaun?"

OLD PEEPAL: "So jao. Sab so jao. Bargad sabko sambhal lega."

[BREATHE]

Mor ne aankhein band kar lin. Ek pankh, do pankh, teen pankh — sab band. Jaise koi rang khulkar simat raha ho. Mor ka neela, hara, sona — sab sapne mein chala gaya.

Titli udi nahin. Bas peepal ke patte par baith gayi. Aur dheere dheere — uske pankh bhi band ho gaye. Titli itni halki ho gayi thi jaise ek phool ki saans.

Giloo ne chhota sa ghar tane mein bana liya. Apni pooch pakad kar — gunghun, gunghun — uski saans bhi dheemi ho gayi. Tane ki choti si darrar mein, giloo ki aankhein band ho gayin. Bargad ne giloo ko apne andar le liya.

Aur Anaya ne diya zameen par rakh diya. Lau ab choti thi, shaant. Diya kehna chahta tha — ab tumhaari baari hai.

[PHRASE]Chaand so raha hai[/PHRASE]

Aur aur dheere. Hawa ki sarr sarr aur dheemi. Peepal ke patte ab nahin hil rahe the. Bargad ne saari ghaati ko apni chhaav mein le liya tha.

ANAYA: "Peepal dada... main bhi so jaaun?"

OLD PEEPAL: "Haan beta. Aaj raat sab so rahe hain."

[PAUSE: 1000]

Aur Anaya ki aankhein bhi bhaari ho gayin. Jaise koi pari ne unpar resham rakh diya ho. Aur peepal ne dheere se aah bhari — jaise koi lambi yatra khatam ho rahi ho.

[PHASE_3]
Ghaati ab shaant thi.

Hawa dheemi thi.

Chaand naram tha, peepal ke andar.

Diya jal raha tha — choti si lau.

Anaya ki saans dheere chal rahi thi.

Bargad ki chhaav mein, sab kuch ruka tha.

[PAUSE: 800]

Naram. Shaant. Dheema.

Naram aur shaant aur dheema.

Naram.

Shaant.

Dheema.

Mor ne pankh band rakhe. Titli ne aankhein band rakhin. Giloo ne saans dheemi rakhi.

Sab so rahe the.

Hawa ne ek aakhri sarr sarr ki. Phir woh bhi chup ho gayi.

Peepal ke patte ab nahin hil rahe the.

Diya ki lau itni choti ho gayi thi — jaise koi sapna ho.

Bargad ki jadein zameen mein gehri thin. Itni gehri ki saari ghaati ko thaame rakhti thin.

Mitti naram. Patte naram. Saans naram.

Aur Anaya? Anaya ne diya pakad rakha tha — bilkul halke se. Jaise koi reshmi cheez kho na jaaye.

[PHRASE]Chaand so raha hai[/PHRASE]

Anaya ki aankhein band thin. Uske honth dheere se hile — jaise woh bhi koi geet gun guna rahi ho.

Phir woh bhi chup.

Bargad Ghaati mein sirf saans ki aawaz baaki thi.

Andar aati. Baahar jaati.

Andar aati. Baahar jaati.

Dheere.

Dheere.

[PAUSE: 1200]

Bargad ne ek sapna dekha. Chaand ka sapna. Anaya ka sapna. Sab sapne ek saath, ek hi peepal ke tane mein lipte hue.

Aur ghaati ke aas paas, sab cheezein bhi sone lagi thin. Door ke pahaad — wo bhi chup the. Choti choti nadi — wo bhi dheere bah rahi thi, jaise neend mein.

Tap. Ek patta gira. Tap. Ek aur. Tap tap. Phir koi nahin.

Hawa: dheemi.

Peepal: chup.

Diya: bas itna sa.

Chaand: surakshit.

Anaya: so rahi hai.

Sab so rahe hain.

Bargad Ghaati so rahi hai.

Aur taare bhi — taare bhi ab dheere chamak rahe hain. Jaise woh bhi neend mein chal rahe hon.

Naram.

Shaant.

Naram aur shaant.

Naram.

Shaant.

[PHRASE]Chaand so raha hai[/PHRASE]

Bargad ki chhaav.

Diya ki lau.

Saans ki aawaz.

Aur kuch nahin.

[WHISPER]
Chaand.
Shaant.
Saans.
Ab.
[/WHISPER]
"""

# Parallel Devanagari version. Same tag positions, same line breaks,
# same character names (Roman uppercase per §8). Used as ElevenLabs input.
STORY_TEXT_DEVA = """\
[CHARACTER: Anaya, gentle, dreamy, female]
[CHARACTER: Old Peepal, wise, quiet, neutral]
[CHARACTER: Giloo, curious, small, neutral]

[INTRO]
सुनो ना, एक बरगद घाटी है। वहाँ हर पत्ता एक पुरानी कहानी याद रखता है। और आज रात — कुछ अलग हुआ है।

[PHASE_1]
अनाया धीरे धीरे चल रही थी। बरगद घाटी की मिट्टी नरम थी, एकदम रोटी जैसी। हवा ठंडी ठंडी थी। और जुगनू? जुगनू कहीं नहीं थे। पता है, बरगद घाटी में हर रात हज़ारों जुगनू चमकते हैं — हर पत्ते के नीचे, हर शाख पर। लेकिन आज? आज सब छुप गए थे।

अनाया के पाँव के नीचे सूखे पत्ते थे। खट खट, खट खट — बस यही एक आवाज़ थी।

ANAYA: "चाँद कहाँ है? आज रात चाँद निकला ही नहीं।"

अनाया ने ऊपर देखा। सिर्फ़ काला आसमान, सिर्फ़ तारे। कुछ तारे भी सोए सोए से लग रहे थे। हवा ने सर्र सर्र की — पीपल का बड़ा सा पेड़ झूम रहा था। इतना बड़ा पीपल — उसकी शाखें आसमान तक पहुँचती थीं। अनाया के दादा की दादी ने भी यही पेड़ देखा था, कहते थे।

OLD PEEPAL: "बेटा, रुक जा ज़रा। सुनो।"

अनाया रुक गई। पीपल ने धीरे से आँखें खोलीं — इतनी पुरानी आँखें, जैसे सौ साल से खुली हो। तने पर छोटी छोटी दरारें, जैसे हर दरार एक कहानी।

OLD PEEPAL: "चाँद खो नहीं गया है, बेटा। बस थक गया है। रोज़ आता है, रोज़ चमकता है। आज रात... आज रात उसको आराम चाहिए था।"

ANAYA: "तो हम क्या करें, पीपल दादा?"

OLD PEEPAL: "मेरे पास एक दिया है। यह दिया बहुत पुराना है। यह दिया तभी जलता है जब कोई धीरे धीरे साँस ले। तुमने कभी इतनी धीरे साँस ली है?"

अनाया ने सर हिलाया। पता नहीं।

[BREATHE_GUIDE]
तो चलो, एक बार साथ करें। धीरे धीरे साँस अंदर लो... नाक से... और फिर धीरे से बाहर छोड़ो... मुँह से... बस। ऐसे ही।
[/BREATHE_GUIDE]
[BREATHE]

अनाया ने साँस ली। लंबी साँस। दिये की लौ धीरे से हिली।

[BREATHE]

और फिर और धीरे। लौ और बढ़ी। अब दिया जल रहा था — छोटी सी पीली रोशनी, जैसे जुगनू हो।

[PAUSE: 800]

इतने में, एक मोर आया। फिर एक छोटी तितली। और एक गिलू भी पीपल के तने से उतरी।

GILOO: "अरे, क्या हो रहा है यहाँ?"

ANAYA: "हम चाँद को ढूँढ रहे हैं। सुनो ज़रा।"

[PHRASE]चाँद सो रहा है[/PHRASE]

हवा रुक गई। पीपल का एक पत्ता गिरा। मोर ने पंख बंद कर लिए।

[SONG_SEED: The old peepal hummed a lullaby about the moon curling up to sleep inside a tree.]

[POST_SONG]
अनाया ने दिया थामा। हवा नरम थी अब। सब कुछ धीरे हो रहा था।

[PHASE_2]
दिये की रोशनी धीरे धीरे बढ़ने लगी। पहले थोड़ी सी पीली। फिर नरम नरम चाँदी जैसी। अनाया ने दिया पीपल के तने की तरफ़ ले जाकर देखा। तने में एक बड़ा सा खोल था — एक छुपा हुआ कोना, जैसे कोई पुराना दरवाज़ा।

और — अंदर — कुछ चमक रहा था। नरम, गोल, चाँदी जैसा। इतनी नरम रोशनी जैसे कोई सपना कपड़े में लिपटा हो।

ANAYA: "यह क्या है, पीपल दादा?"

OLD PEEPAL: "यही तो चाँद है, बेटा। खोया नहीं था। बस... सो रहा था।"

और सच में, चाँद वहाँ था। छोटी सी गोल शकल में, पीपल के अंदर कर्ल करके। जैसे कोई बिल्ली सपना देख रही हो। साँस ले रहा था — धीरे, धीरे। अपनी लंबी यात्रा के बाद, बरगद के अंदर आराम कर रहा था। सालों से चाँद हर रात अकेले सफ़र करता था। आज उसको भी किसी की गोद चाहिए थी।

ANAYA: "तो हम जगाएँ नहीं?"

OLD PEEPAL: "नहीं। बस साथ बैठ जाओ। और धीरे से साँस लो। चाँद को भी पता चल जाएगा कोई पास है।"

[BREATHE]

अनाया बैठ गई। मोर भी आ गया। तितली ने पंख बंद कर लिए। गिलू पीपल के तने से चिपक गई।

GILOO: "मैं भी सो जाऊँ?"

OLD PEEPAL: "सो जाओ। सब सो जाओ। बरगद सबको सम्भाल लेगा।"

[BREATHE]

मोर ने आँखें बंद कर लीं। एक पंख, दो पंख, तीन पंख — सब बंद। जैसे कोई रंग खुलकर सिमट रहा हो। मोर का नीला, हरा, सोना — सब सपने में चला गया।

तितली उड़ी नहीं। बस पीपल के पत्ते पर बैठ गई। और धीरे धीरे — उसके पंख भी बंद हो गए। तितली इतनी हल्की हो गई थी जैसे एक फूल की साँस।

गिलू ने छोटा सा घर तने में बना लिया। अपनी पूँछ पकड़ कर — गुनगुन, गुनगुन — उसकी साँस भी धीमी हो गई। तने की छोटी सी दरार में, गिलू की आँखें बंद हो गईं। बरगद ने गिलू को अपने अंदर ले लिया।

और अनाया ने दिया ज़मीन पर रख दिया। लौ अब छोटी थी, शांत। दिया कहना चाहता था — अब तुम्हारी बारी है।

[PHRASE]चाँद सो रहा है[/PHRASE]

और और धीरे। हवा की सर्र सर्र और धीमी। पीपल के पत्ते अब नहीं हिल रहे थे। बरगद ने सारी घाटी को अपनी छाँव में ले लिया था।

ANAYA: "पीपल दादा... मैं भी सो जाऊँ?"

OLD PEEPAL: "हाँ बेटा। आज रात सब सो रहे हैं।"

[PAUSE: 1000]

और अनाया की आँखें भी भारी हो गईं। जैसे कोई परी ने उनपर रेशम रख दिया हो। और पीपल ने धीरे से आह भरी — जैसे कोई लंबी यात्रा खत्म हो रही हो।

[PHASE_3]
घाटी अब शांत थी।

हवा धीमी थी।

चाँद नरम था, पीपल के अंदर।

दिया जल रहा था — छोटी सी लौ।

अनाया की साँस धीरे चल रही थी।

बरगद की छाँव में, सब कुछ रुका था।

[PAUSE: 800]

नरम। शांत। धीमा।

नरम और शांत और धीमा।

नरम।

शांत।

धीमा।

मोर ने पंख बंद रखे। तितली ने आँखें बंद रखीं। गिलू ने साँस धीमी रखी।

सब सो रहे थे।

हवा ने एक आख़री सर्र सर्र की। फिर वो भी चुप हो गई।

पीपल के पत्ते अब नहीं हिल रहे थे।

दिये की लौ इतनी छोटी हो गई थी — जैसे कोई सपना हो।

बरगद की जड़ें ज़मीन में गहरी थीं। इतनी गहरी कि सारी घाटी को थामे रखती थीं।

मिट्टी नरम। पत्ते नरम। साँस नरम।

और अनाया? अनाया ने दिया पकड़ रखा था — बिलकुल हल्के से। जैसे कोई रेशमी चीज़ खो ना जाए।

[PHRASE]चाँद सो रहा है[/PHRASE]

अनाया की आँखें बंद थीं। उसके होंठ धीरे से हिले — जैसे वो भी कोई गीत गुनगुना रही हो।

फिर वो भी चुप।

बरगद घाटी में सिर्फ़ साँस की आवाज़ बाकी थी।

अंदर आती। बाहर जाती।

अंदर आती। बाहर जाती।

धीरे।

धीरे।

[PAUSE: 1200]

बरगद ने एक सपना देखा। चाँद का सपना। अनाया का सपना। सब सपने एक साथ, एक ही पीपल के तने में लिपटे हुए।

और घाटी के आस पास, सब चीज़ें भी सोने लगी थीं। दूर के पहाड़ — वो भी चुप थे। छोटी छोटी नदी — वो भी धीरे बह रही थी, जैसे नींद में।

टप। एक पत्ता गिरा। टप। एक और। टप टप। फिर कोई नहीं।

हवा: धीमी।

पीपल: चुप।

दिया: बस इतना सा।

चाँद: सुरक्षित।

अनाया: सो रही है।

सब सो रहे हैं।

बरगद घाटी सो रही है।

और तारे भी — तारे भी अब धीरे चमक रहे हैं। जैसे वो भी नींद में चल रहे हों।

नरम।

शांत।

नरम और शांत।

नरम।

शांत।

[PHRASE]चाँद सो रहा है[/PHRASE]

बरगद की छाँव।

दिये की लौ।

साँस की आवाज़।

और कुछ नहीं।

[WHISPER]
चाँद।
शांत।
साँस।
अब।
[/WHISPER]
"""


STORY = {
    "id": STORY_ID,
    "lang": "hi",
    "language": "hi",
    "story_format": "long_story",
    "title": "Anaya Aur Sota Hua Chaand",
    "title_deva": "अनाया और सोता हुआ चाँद",
    "title_en": "Anaya and the Sleeping Moon",
    "world_name": "Bargad Ghaati",
    "world_name_en": "The Banyan Valley",
    "world_description": "Ek ghaati jahaan har patta ek kahaani yaad rakhta hai.",
    "world_description_en": "A valley where every leaf remembers a story.",
    "mystery": "Chaand ghaati par ugna bhool gaya hai.",
    "resolution": "Chaand purane bargad ke andar curl karke so raha tha.",
    "breathing_mechanic": "Ek diya jo dheere dheere saans lene par hi jalta hai.",
    "repeated_phrase": "Chaand so raha hai",
    "repeated_phrase_deva": "चाँद सो रहा है",
    "characters": [
        {
            "name": "Anaya",
            "identity": "Ek ladki jo dheere chalti hai kyunki hamesha sun rahi hoti hai",
            "personality": "gentle",
            "voice_style": "dreamy",
            "gender": "female",
        },
        {
            "name": "Old Peepal",
            "identity": "Bargad Ghaati ke beech mein ek bahut purana peepal ka ped",
            "personality": "wise",
            "voice_style": "quiet",
            "gender": "neutral",
        },
        {
            "name": "Giloo",
            "identity": "Ek chhoti curious gilhari jo peepal ke tane par rehti hai",
            "personality": "curious",
            "voice_style": "small",
            "gender": "neutral",
        },
    ],
    "song_seed": (
        "The old peepal hummed a lullaby about the moon curling up "
        "to sleep inside a tree."
    ),
    # English seed for FLUX cover.
    "cover_context": (
        "A wide Indian valley at twilight, rolling hills, an enormous "
        "ancient peepal tree at the center with a soft hollow glowing "
        "silver-blue inside, a small gentle Indian girl sitting at its "
        "base holding a tiny pottery diya, soft moonless sky with sleeping "
        "stars, watercolor storybook style, deep indigo blues and warm "
        "golds, no humans visible inside the tree, dreamlike and peaceful"
    ),
    # Mid-story song lyrics for MiniMax — short Hindi lullaby (~30s) about
    # the moon sleeping inside the peepal. ~25-30 words is plenty.
    "song_lyrics_deva": (
        "[verse]\n"
        "चाँद थक गया, बरगद के अंदर\n"
        "नरम सी छाया, धीमे सी सांसें\n"
        "पीपल गाता है, धीरे धीरे\n"
        "सो जा चाँद, सो जा प्यारे\n\n"
        "[chorus]\n"
        "बरगद की छाँव में, चाँद सो रहा\n"
        "हवा भी रुकी है, साँस ले रही\n"
        "धीरे धीरे, धीरे धीरे\n"
    ),
    "song_lyrics_roman": (
        "[verse]\n"
        "Chaand thak gaya, bargad ke andar\n"
        "Naram si chhaaya, dheeme si saansein\n"
        "Peepal gaata hai, dheere dheere\n"
        "So ja chaand, so ja pyaare\n\n"
        "[chorus]\n"
        "Bargad ki chhaav mein, chaand so raha\n"
        "Hawa bhi ruki hai, saans le rahi\n"
        "Dheere dheere, dheere dheere\n"
    ),
    "song_style_prompt": (
        "Soft Hindi lullaby, gentle female humming, single bansuri flute, "
        "tanpura drone, 60 BPM, intimate maternal voice, no percussion, "
        "warm major key, breath between phrases, lullaby cadence"
    ),
    "phase_1_text_roman": "",  # filled below from STORY_TEXT_ROMAN
    "phase_2_text_roman": "",
    "phase_3_text_roman": "",
    "phase_1_text_deva": "",
    "phase_2_text_deva": "",
    "phase_3_text_deva": "",
    "diversityFingerprint": {
        "characterType": "human_child",
        "setting": "valley",
        "plotShape": "discovery_reveal",
        "timeOfDay": "deep_night",
        "weather": "clear",
        "theme": "rest",
        "scale": "small_personal",
        "companion": "trio",
        "movement": "walking",
        "magicType": "glowing",
        "season": "summer",
        "senseEmphasis": "auditory",
        "characterTrait": "gentle",
    },
    "age_group": "2-5",
    "age_min": 2,
    "age_max": 5,
    "target_age": 4,
    "mood": "calm",
    "geography": "south_asia",
    "indian_region": "north",
    "lead_character_type_canonical": "human_child",
    "lead_character_type_cover":     "human",
    "gender_lead": "female",
    "voice": NARRATOR_VOICE,
    "narrator_voice": NARRATOR_VOICE,
    "whisper_voice": WHISPER_VOICE,
    "char_voice_map": CHAR_VOICE,
    "tts_engine": "elevenlabs_multilingual_v2",
    "tts_input_script": "devanagari",
}


# ──────────────────────────────────────────────────────────────────────
# §19 Validator (14 checks)
# ──────────────────────────────────────────────────────────────────────
def _strip_for_check(text: str) -> str:
    """Strip [CHARACTER:], NAME: dialogue prefixes, and [SONG_SEED:] content
    so Devanagari check below ignores allowed-non-Hindi parts."""
    out = re.sub(r"\[CHARACTER:[^\]]*\]", "", text)
    out = re.sub(r"\[SONG_SEED:[^\]]*\]", "", out)
    out = re.sub(r"^[A-Z][A-Z _]*:\s*\"", '"', out, flags=re.MULTILINE)
    return out


def validate_hindi_long_story(story_data: dict) -> list:
    errors = []

    # Validator runs on user-facing Roman text (§19 spec — Devanagari
    # rejection is for user-facing fields, not engine input).
    text = (
        story_data["phase_1_text_roman"]
        + "\n"
        + story_data["phase_2_text_roman"]
        + "\n"
        + story_data["phase_3_text_roman"]
    )

    # 1. Devanagari rejection in user-facing text
    text_check = _strip_for_check(text)
    for c in text_check:
        if "\u0900" <= c <= "\u097F":
            errors.append("Devanagari detected in user-facing text — must be Roman")
            break

    USER_FACING = ["title", "world_name", "world_description",
                   "mystery", "resolution", "repeated_phrase"]
    for field in USER_FACING:
        val = story_data.get(field, "") or ""
        for c in val:
            if "\u0900" <= c <= "\u097F":
                errors.append(f"Devanagari in '{field}'")
                break

    # 2. Literary Hindi
    LITERARY = ["nidra", "nakshatra", "shayan", "tandra", "pushp",
                "chandra ", "megh ", "tatpashchat", "nivas",
                "avlokan", "prasthan", "shubh ratri", " van ", "sugandh"]
    text_lower = text.lower()
    for word in LITERARY:
        if word in text_lower:
            errors.append(f"Literary Hindi: '{word}'")

    # 3. Conversational markers (≥5)
    MARKERS = ["na ", " toh ", "arre", "pata hai", "chalo",
               "dekho", "suno", "hai na", "aur phir", "bas ",
               "achha", "zara", "pata nahin"]
    found = sum(1 for m in MARKERS if m in text_lower)
    if found < 5:
        errors.append(f"Only {found} conversational markers (need ≥5)")

    # 4. Phase structure
    for phase in ["[PHASE_1]", "[PHASE_2]", "[PHASE_3]"]:
        if phase not in (story_data["full_text_roman"]):
            errors.append(f"Missing {phase} tag")

    # 5. [PHRASE] count ≥3
    if story_data["full_text_roman"].count("[PHRASE]") < 3:
        errors.append("Phrase appears <3 times")

    # 6. No empty phrase leak
    if re.search(r"\[PHRASE\]\s*\.\.\.\s*\[/PHRASE\]", story_data["full_text_roman"]):
        errors.append("Empty [PHRASE]...[/PHRASE] leak")

    # 7. Breathing
    if story_data["full_text_roman"].count("[BREATHE]") < 4:
        errors.append("Too few [BREATHE] tags (need ≥4)")
    if "[BREATHE_GUIDE]" not in story_data["full_text_roman"]:
        errors.append("Missing [BREATHE_GUIDE]")

    # 8. Song seed
    if "[SONG_SEED:" not in story_data["full_text_roman"]:
        errors.append("Missing [SONG_SEED:]")

    # 9. Whisper close
    if "[WHISPER]" not in story_data["full_text_roman"]:
        errors.append("Missing [WHISPER]")
    if "[/WHISPER]" not in story_data["full_text_roman"]:
        errors.append("Missing [/WHISPER]")

    # 10. Religious terms
    RELIGIOUS = ["pranayam", " yog ", " yoga", " mantra", "saadhana",
                 "tapasya", "bhagwaan", "ishvar", "puja",
                 "devta", "devi ", "yajna", "aarti"]
    for word in RELIGIOUS:
        if word in text_lower:
            errors.append(f"Religious term: '{word.strip()}'")

    # 11. Blacklisted names
    BLACKLIST = ["Chintu", "Raju", "Bittu", "Munna", "Guddu",
                 "Pinky", "Rinku", "Bablu", "Pappu", "Chhotu",
                 "Motu", "Golu", "Sonu", "Monu", "Titu",
                 "Bunty", "Ramu"]
    for char in story_data.get("characters", []):
        if char.get("name") in BLACKLIST:
            errors.append(f"Blacklisted name: '{char['name']}'")

    # 12. Onomatopoeia (≥3)
    ONO = ["sarr", "tap tap", "chhap", "khat",
           "dheere dheere", "chi chi", "gunghun", "jhoom", "tip tip"]
    if sum(1 for o in ONO if o in text_lower) < 3:
        errors.append("Too few onomatopoeia for long story (need ≥3)")

    # 13. Forbidden tags
    FORBIDDEN = ["[GENTLE]", "[SLEEPY]", "[EXCITED]",
                 "[DELIVERY:]", "[EMPHASIS]", "[MUSIC]"]
    for tag in FORBIDDEN:
        if tag in story_data["full_text_roman"]:
            errors.append(f"Forbidden tag: {tag}")

    # 14. Phrase similarity — short circuit (no recent Hindi long-story
    # phrases in catalog yet; this is the first one).
    return errors


# ──────────────────────────────────────────────────────────────────────
# Long-story tag parser (§14)
# ──────────────────────────────────────────────────────────────────────
def parse_long_segments(text: str) -> list:
    """Parse story text into ordered render segments.

    Returns list of dicts with keys: kind, content, character, phase, ...

    Recognised kinds:
      - 'narration': plain narration (in current phase)
      - 'dialogue':  character speech (key 'character' + 'content')
      - 'breathe_guide': [BREATHE_GUIDE]...[/BREATHE_GUIDE] (Tripti slow)
      - 'breathe':   [BREATHE] marker → 4 sec silence (saans pause)
      - 'phrase':    [PHRASE]...[/PHRASE] (slow soft narrator)
      - 'song':      [SONG_SEED: ...] (replaced with MiniMax audio)
      - 'whisper':   [WHISPER]...[/WHISPER] (Roohi very slow)
      - 'pause':     [PAUSE: ms]
      - 'phase':     phase boundary marker (sets current phase)
      - 'intro':     [INTRO] start

    [CHARACTER: ...] tags are dropped — pure metadata.
    """
    segs: list = []
    current_phase = 1
    current_section = "intro"  # before [PHASE_1]

    # Strip [CHARACTER:] tags entirely.
    text = re.sub(r"\[CHARACTER:[^\]]*\]", "", text)

    # Pre-extract [WHISPER]...[/WHISPER] blocks because they may contain
    # multiple lines that should NOT be treated as dialogue/narration.
    # We tokenize sequentially using a master regex.
    tag_re = re.compile(
        r"(\[INTRO\]"
        r"|\[PHASE_1\]|\[PHASE_2\]|\[PHASE_3\]"
        r"|\[BREATHE_GUIDE\](.*?)\[/BREATHE_GUIDE\]"
        r"|\[BREATHE\]"
        r"|\[PHRASE\](.*?)\[/PHRASE\]"
        r"|\[SONG_SEED:[^\]]*\]"
        r"|\[POST_SONG\]"
        r"|\[WHISPER\](.*?)\[/WHISPER\]"
        r"|\[PAUSE:\s*(\d+)\])",
        re.DOTALL,
    )

    pos = 0
    for m in tag_re.finditer(text):
        # Render the gap between previous tag and this one.
        gap = text[pos:m.start()]
        if gap.strip():
            for chunk in _split_dialogue_and_narration(gap):
                chunk["phase"] = current_phase
                chunk["section"] = current_section
                segs.append(chunk)
        token = m.group(0)
        if token == "[INTRO]":
            current_section = "intro"
        elif token == "[PHASE_1]":
            current_phase = 1
            current_section = "phase_1"
        elif token == "[PHASE_2]":
            current_phase = 2
            current_section = "phase_2"
        elif token == "[PHASE_3]":
            current_phase = 3
            current_section = "phase_3"
        elif token.startswith("[BREATHE_GUIDE]"):
            content = m.group(2).strip()
            segs.append({"kind": "breathe_guide", "content": content,
                         "phase": current_phase, "section": current_section})
        elif token == "[BREATHE]":
            segs.append({"kind": "breathe", "phase": current_phase,
                         "section": current_section})
        elif token.startswith("[PHRASE]"):
            phrase = m.group(3).strip()
            segs.append({"kind": "phrase", "content": phrase,
                         "phase": current_phase, "section": current_section})
        elif token.startswith("[SONG_SEED:"):
            segs.append({"kind": "song", "phase": current_phase,
                         "section": current_section})
        elif token == "[POST_SONG]":
            current_section = "post_song"
        elif token.startswith("[WHISPER]"):
            wh = m.group(4).strip()
            for line in [l.strip() for l in wh.split("\n") if l.strip()]:
                segs.append({"kind": "whisper", "content": line,
                             "phase": current_phase, "section": current_section})
        elif token.startswith("[PAUSE:"):
            ms = int(m.group(5))
            segs.append({"kind": "pause", "ms": ms,
                         "phase": current_phase, "section": current_section})
        pos = m.end()

    tail = text[pos:]
    if tail.strip():
        for chunk in _split_dialogue_and_narration(tail):
            chunk["phase"] = current_phase
            chunk["section"] = current_section
            segs.append(chunk)
    return segs


# Detect dialogue lines like  ANAYA: "..."  or  OLD PEEPAL: "..."
DIALOGUE_RE = re.compile(
    r'^([A-Z][A-Z _]+):\s*"(.+?)"\s*$',
    re.MULTILINE,
)


def _split_dialogue_and_narration(block: str) -> list:
    """Split a block of text into sequential narration / dialogue chunks."""
    out: list = []
    pos = 0
    for m in DIALOGUE_RE.finditer(block):
        before = block[pos:m.start()].strip()
        if before:
            out.extend(_split_narration_sentences(before))
        out.append({
            "kind": "dialogue",
            "character": m.group(1).strip(),
            "content": m.group(2).strip(),
        })
        pos = m.end()
    tail = block[pos:].strip()
    if tail:
        out.extend(_split_narration_sentences(tail))
    return out


def _split_narration_sentences(block: str) -> list:
    flat = " ".join(line.strip() for line in block.splitlines() if line.strip())
    parts = re.split(r"(?<=[।.!?])\s+", flat)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and len(p) < 18 and out[-1]["kind"] == "narration":
            out[-1]["content"] = out[-1]["content"] + " " + p
        else:
            out.append({"kind": "narration", "content": p})
    return out


# ──────────────────────────────────────────────────────────────────────
# ElevenLabs TTS
# ──────────────────────────────────────────────────────────────────────
DEVA_TERMINATORS = ("।", ".", "!", "?", "…")


def _ensure_terminal(text: str) -> str:
    s = text.rstrip()
    if s.endswith(DEVA_TERMINATORS):
        return s
    return s + "।"


def elevenlabs_tts(text: str, voice_id: str, *, stability: float, similarity: float,
                   style: float, speed: float, previous_text: str = "",
                   next_text: str = "") -> AudioSegment:
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
    raise RuntimeError(f"ElevenLabs TTS failed voice={voice_id}")


# ──────────────────────────────────────────────────────────────────────
# Long-story audio assembly
# ──────────────────────────────────────────────────────────────────────
def assemble_long_story_audio(segments: list, song_audio: AudioSegment | None) -> AudioSegment:
    """Render long story segments to a single AudioSegment.

    Layout:
      intro music (calm) → 500ms silence → narration with embedded song
      → 3000ms silence → outro music (calm)

    Multi-voice routing:
      - narration / breathe_guide / phrase / whisper → various voice choices
      - dialogue → CHAR_VOICE[character]
      - song segment → song_audio inserted in place
    """
    intro = AudioSegment.from_wav(str(MUSIC_DIR / "intro_calm.wav"))
    outro = AudioSegment.from_wav(str(MUSIC_DIR / "outro_calm.wav"))

    timeline = AudioSegment.silent(duration=0)
    timeline += intro
    timeline += AudioSegment.silent(duration=500)

    counts: dict = {}
    for s in segments:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    print(f"  segments: {counts}")

    # Pre-collect text neighbors for prev/next prompting.
    text_segs = [
        (i, s) for i, s in enumerate(segments)
        if s["kind"] in ("narration", "dialogue", "phrase",
                         "whisper", "breathe_guide")
    ]
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
            # Saans pause: long breath silence.
            return AudioSegment.silent(duration=4000)
        if kind == "song":
            return song_audio if song_audio is not None else AudioSegment.silent(duration=0)

        prev, nxt = neighbor.get(idx, ("", ""))
        phase = seg.get("phase", 1)

        if kind == "dialogue":
            voice_label = CHAR_VOICE.get(seg["character"], NARRATOR_VOICE)
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
            # Intro section uses INTRO_TTS (livelier hook).
            if seg.get("section") == "intro":
                preset = INTRO_TTS
            else:
                preset = PHASE_TTS[phase]
            text = seg["content"]
        else:
            return None

        text = normalize_for_tts(text)
        voice_id = ELEVENLABS_VOICES[voice_label]
        return elevenlabs_tts(
            text,
            voice_id,
            stability=preset["stability"],
            similarity=0.75,
            style=preset["style"],
            speed=preset["speed"],
            previous_text=prev,
            next_text=nxt,
        )

    # Render every segment in order.
    for idx, seg in enumerate(segments):
        rendered = render_seg(idx, seg)
        if rendered is None:
            continue
        # Tiny breath between successive narration / dialogue lines.
        if seg["kind"] in ("narration", "dialogue", "phrase", "whisper"):
            timeline += AudioSegment.silent(duration=180)
        timeline += rendered
        if seg["kind"] == "phrase":
            timeline += AudioSegment.silent(duration=900)
        if seg["kind"] == "whisper":
            timeline += AudioSegment.silent(duration=600)
        if seg["kind"] == "song":
            timeline += AudioSegment.silent(duration=1500)

    timeline += AudioSegment.silent(duration=3000)
    timeline += outro
    return timeline


# ──────────────────────────────────────────────────────────────────────
# Cover regen via FLUX (existing script)
# ──────────────────────────────────────────────────────────────────────
def regen_story_cover() -> Path:
    cover_seed = {
        "id": STORY["id"],
        "title": STORY["title_en"],
        "description": STORY["world_description_en"],
        "cover_context": STORY["cover_context"],
        "character": {
            "name": STORY["characters"][0]["name"],
            "identity": (
                "a small gentle Indian girl named Anaya with kind eyes, "
                "sitting at the base of a giant ancient peepal tree in a "
                "dim valley, holding a tiny glowing diya"
            ),
            "personality_tags": ["Gentle", "Dreamy"],
        },
        "lead_character_type": STORY["lead_character_type_cover"],
        "lead_gender": STORY["gender_lead"],
        "theme": "rest",
        "age_group": STORY["age_group"],
        "mood": STORY["mood"],
    }
    seed_dir = BASE_DIR / "seed_output" / "hindi_long"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_path = seed_dir / f"{STORY['id']}_coverseed.json"
    with open(seed_path, "w", encoding="utf-8") as f:
        json.dump(cover_seed, f, ensure_ascii=False, indent=2)

    cmd = [
        sys.executable, str(BASE_DIR / "scripts" / "generate_cover_experimental.py"),
        "--story-json", str(seed_path),
        "--mood", STORY["mood"],
        "--story-type", "dream",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-800:])
        print(r.stderr[-1500:], file=sys.stderr)
        raise RuntimeError("cover regen failed")
    print(r.stdout[-500:])
    seed_path.unlink(missing_ok=True)

    src = BASE_DIR / "seed_output" / "covers_experimental" / f"{STORY['id']}_combined.svg"
    dst = WEB_ROOT / "public" / "covers" / f"{STORY['id']}.svg"
    dst.write_bytes(src.read_bytes())
    print(f"  cover: {dst}")
    return dst


# ──────────────────────────────────────────────────────────────────────
# Phase text extractor (for validator + JSON)
# ──────────────────────────────────────────────────────────────────────
def _extract_phase_text(full: str, phase: str) -> str:
    """Slice between [PHASE_X] and the next phase marker (or EOF)."""
    starts = {"phase_1": "[PHASE_1]", "phase_2": "[PHASE_2]", "phase_3": "[PHASE_3]"}
    end_markers = {
        "phase_1": ["[PHASE_2]"],
        "phase_2": ["[PHASE_3]"],
        "phase_3": [],
    }
    s = full.find(starts[phase])
    if s < 0:
        return ""
    s += len(starts[phase])
    e = len(full)
    for em in end_markers[phase]:
        idx = full.find(em, s)
        if idx >= 0 and idx < e:
            e = idx
    return full[s:e].strip()


def _word_count(text: str) -> int:
    """Count words ignoring tags / dialogue prefixes."""
    cleaned = re.sub(r"\[[^\]]*\]", "", text)
    cleaned = re.sub(r"^[A-Z][A-Z _]+:\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace('"', " ")
    return len([w for w in re.split(r"\s+", cleaned) if w.strip()])


# ──────────────────────────────────────────────────────────────────────
# content.json upsert
# ──────────────────────────────────────────────────────────────────────
def story_entry(duration: int, song_seconds: int) -> dict:
    full_text_roman = STORY["full_text_roman"]
    return {
        "id": STORY["id"],
        # NOTE: explore page (dreamweaver-web/src/app/explore/page.js)
        # filters tabs by item.type === "long_story" (matching English
        # long stories). Setting type=long_story (not "story") makes
        # this surface in the "Long Stories" / "Lambi Kahaniyan" tab.
        "type": "long_story",
        "lang": "hi",
        "language": "hi",
        "story_format": "long_story",
        "title": STORY["title"],
        "title_deva": STORY["title_deva"],
        "title_en": STORY["title_en"],
        "description": STORY["world_description"],
        "description_en": STORY["world_description_en"],
        "world_name": STORY["world_name"],
        "world_name_en": STORY["world_name_en"],
        "world_description": STORY["world_description"],
        "mystery": STORY["mystery"],
        "resolution": STORY["resolution"],
        "breathing_mechanic": STORY["breathing_mechanic"],
        "repeated_phrase": STORY["repeated_phrase"],
        "repeated_phrase_deva": STORY["repeated_phrase_deva"],
        "characters": STORY["characters"],
        "song_seed": STORY["song_seed"],
        "cover_context": STORY["cover_context"],
        "phase_1_text": STORY["phase_1_text_roman"],
        "phase_2_text": STORY["phase_2_text_roman"],
        "phase_3_text": STORY["phase_3_text_roman"],
        # Combined narrative for the reader page (Roman, user-facing).
        "text": full_text_roman,
        "text_deva": STORY["full_text_deva"],
        "raw_text": full_text_roman,
        "diversityFingerprint": STORY["diversityFingerprint"],
        # Standard catalog fields.
        "character": {
            "name": STORY["characters"][0]["name"],
            "identity": STORY["characters"][0]["identity"],
            "personality_tags": [STORY["characters"][0]["personality"].title(),
                                 STORY["characters"][0]["voice_style"].title()],
        },
        "character_name": STORY["characters"][0]["name"],
        "characterType": STORY["lead_character_type_canonical"],
        "lead_character_type": STORY["lead_character_type_canonical"],
        "lead_gender": STORY["gender_lead"],
        "age_group": STORY["age_group"],
        "ageGroup": STORY["age_group"],
        "age_min": STORY["age_min"],
        "age_max": STORY["age_max"],
        "target_age": STORY["target_age"],
        "mood": STORY["mood"],
        "story_type": "long_story",
        "storyType": "long_story",
        "theme": "rest",
        "themes": ["rest", "wonder"],
        "geography": STORY["geography"],
        "indian_region": STORY["indian_region"],
        "experimental_v2": False,
        "has_baked_music": True,  # intro/outro/embedded song baked in
        "tts_engine": STORY["tts_engine"],
        "tts_input_script": STORY["tts_input_script"],
        "voice_routing": {
            "narrator": NARRATOR_VOICE,
            "whisper": WHISPER_VOICE,
            "characters": CHAR_VOICE,
        },
        "embedded_song_seconds": song_seconds,
        "cover": f"/covers/{STORY['id']}.svg",
        "audio_variants": [{
            "voice": NARRATOR_VOICE,
            "url": f"/audio/pre-gen/{STORY['id']}_{NARRATOR_VOICE}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "audio_url": f"/audio/pre-gen/{STORY['id']}_{NARRATOR_VOICE}.mp3",
        "duration_seconds": duration,
        "word_count": _word_count(full_text_roman),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Long Story"],
    }


def upsert_content(entry: dict) -> int:
    path = BASE_DIR / "seed_output" / "content.json"
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data
    items = [i for i in items if i.get("id") != entry["id"]]
    items.append(entry)
    if isinstance(data, dict):
        data["items"] = items
    else:
        data = items
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(items)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main():
    # Populate phase splits in the STORY dict.
    STORY["full_text_roman"] = STORY_TEXT_ROMAN
    STORY["full_text_deva"] = STORY_TEXT_DEVA
    for phase in ("phase_1", "phase_2", "phase_3"):
        STORY[f"{phase}_text_roman"] = _extract_phase_text(STORY_TEXT_ROMAN, phase)
        STORY[f"{phase}_text_deva"] = _extract_phase_text(STORY_TEXT_DEVA, phase)

    # Word-count check (informational; validator §13).
    print("\n═══ Word counts ═══")
    for phase in ("phase_1", "phase_2", "phase_3"):
        wc = _word_count(STORY[f"{phase}_text_roman"])
        print(f"  {phase}: {wc} words")
    print(f"  total: {_word_count(STORY_TEXT_ROMAN)} words (target 1040–1520 for age 2-5)")

    # 0. HARD GATE — validator §19.
    print("\n═══ Validating story (§19, 14 checks) ═══")
    issues = validate_hindi_long_story(STORY)
    if issues:
        print("  ❌ Validator failures:", file=sys.stderr)
        for i in issues:
            print(f"    - {i}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ All 14 validator checks passed")

    # 1. Mid-story song via MiniMax (Devanagari lyrics).
    print("\n═══ Mid-story song (MiniMax v2.5) ═══")
    song_bytes = minimax_lullaby(STORY["song_style_prompt"], STORY["song_lyrics_deva"])
    song_audio = AudioSegment.from_file(io.BytesIO(song_bytes), format="mp3")
    # Cap song at 45s to keep total long-story runtime sensible.
    if len(song_audio) > 45000:
        song_audio = song_audio[:45000].fade_out(2000)
    song_seconds = round(len(song_audio) / 1000)
    print(f"  song duration: {song_seconds}s")

    # Save song separately for debug.
    song_dir = BASE_DIR / "seed_output" / "hindi_long"
    song_dir.mkdir(parents=True, exist_ok=True)
    song_audio.export(song_dir / f"{STORY['id']}_song.mp3", format="mp3", bitrate="192k")

    # 2. Parse story segments & assemble audio.
    print("\n═══ STORY audio (ElevenLabs multi-voice + Devanagari) ═══")
    segments = parse_long_segments(STORY_TEXT_DEVA)
    story_audio = assemble_long_story_audio(segments, song_audio)
    out_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{STORY['id']}_{NARRATOR_VOICE}.mp3"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    story_audio.export(out_path, format="mp3", bitrate="192k")
    duration = round(len(story_audio) / 1000)
    print(f"  → {out_path}  ({duration}s, {duration//60}m{duration%60}s)")

    # 3. Cover via FLUX.
    print("\n═══ STORY cover (FLUX) ═══")
    regen_story_cover()

    # 4. Upsert content.json.
    print("\n═══ JSON upsert ═══")
    entry = story_entry(duration, song_seconds)
    total_items = upsert_content(entry)
    print(f"  content.json: total {total_items} items")
    print(f"  story.text first 140: {entry['text'][:140]!r}")

    print("\n═════ DAY-1 LONG-STORY PUBLISH DONE ═════")
    print(f"  story id:        {STORY['id']}")
    print(f"  duration:        {duration}s ({duration//60}m{duration%60}s)")
    print(f"  embedded song:   {song_seconds}s")
    print(f"  voices used:     narrator=tripti, anaya=anika,")
    print(f"                   peepal=kuber_j, giloo=kiran, whisper=roohi")


if __name__ == "__main__":
    main()
