#!/usr/bin/env python3
"""Re-render the Hindi short story with proper short-story audio architecture.

Fixes from the day-1 publish:
  1. Title now includes character name → "Neel Aur Patang" (was "Bandar Ki Patang")
  2. Audio uses the spec'd short-story flow: intro music + hook + bed (-18 dB)
     + swells at [MUSIC] tags + 45s outro music. Was bare TTS without bed/intro.
  3. Story tags now use the short-story emotion-marker idiom ([MUSIC] swells)
     instead of mis-using long-story [PHRASE]/[PAUSE: ms] tags.

Reuses fix_hindi_batch_day2.assemble_story_audio() unchanged — same flow as
the existing Hindi short stories (Chiki, Jugnu, Reshmi, Lali).
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from fix_hindi_batch_day2 import assemble_story_audio  # type: ignore

load_dotenv(BASE_DIR / ".env", override=True)


# ─── Updated short-story content ───────────────────────────────────────

OLD_ID = "hi-patang-2-5-bndr"  # the id we shipped yesterday; reuse so URLs stay stable
NEW_TITLE = "Neel Aur Patang"
NEW_TITLE_DEVA = "नील और पतंग"
NEW_TITLE_EN = "Neel and the Kite"

HOOK_ROMAN = "Neel bandar ko aaj raat kuch ajeeb mila — ek nanhi neeli patang."
HOOK_DEVA  = "नील बंदर को आज रात कुछ अजीब मिला — एक नन्ही नीली पतंग।"

# Devanagari narration with short-story tags ([MUSIC] for swells, [PAUSE: ms]
# for hold beats, [PHRASE] for the repeated phrase).
TEXT_DEVA = (
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
    "[MUSIC]\n"
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
    "[MUSIC]\n"
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
)

# Roman version for the user-facing `text` field (validator-checked).
TEXT_ROMAN = (
    "Pahaadi ke peechhe, ek bahut purana ped tha — bargad. Aur us ped par, sabse upar wali shaakh par, ek chhota sa bandar baitha tha. Bandar ka naam tha — Neel.\n"
    "\n"
    "Neel ko bargad bahut achha lagta tha. Wahaan se sab kuch dikhta tha — neeche ka gaaon, door ki nadi, aur khaali aakaash.\n"
    "\n"
    "Aaj shaam, Neel ne kuch ajeeb dekha. Aakaash mein, ek nanhi si neeli patang. Patang dheere dheere udd rahi thi, hawa ke saath jhoom rahi thi.\n"
    "\n"
    "Dheere, Neel, dheere…\n"
    "\n"
    "\"Yeh kya hai?\" Neel ne pucha. Lekin koi nahin tha jawaab dene wala. Sirf hawa ki sarr sarr awaaz thi.\n"
    "\n"
    "Patang aur paas aane lagi. Neel ke haath bhi paas aaye — pakadne ko. Lekin haath nahin pahunche.\n"
    "\n"
    "\"Patang!\" Neel chillaaya. \"Aa ja meri taraf!\"\n"
    "\n"
    "Patang nahin aayi. Bas dheere dheere udti rahi.\n"
    "\n"
    "Phir Neel ne sochaa — shaayad zor se nahin, dheere se bulaaun.\n"
    "\n"
    "Neel chup baith gaya. Aankhein band kiin. Lambi saans li.\n"
    "\n"
    "Dheere, Neel, dheere…\n"
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
    "Neel muskaaya. Aankhein band kiin. Aur dheere dheere — bahut dheere — neend mein gum ho gaya. Patang bhi thakk ke shaakh par lipti rahi.\n"
    "\n"
    "Hawa chal rahi thi. Bargad jhoom raha tha.\n"
    "\n"
    "Dheere, Neel, dheere…\n"
    "\n"
    "Aur Neel aur patang — dono saath saath, neend ke andheron mein chale gaye.\n"
    "\n"
    "Subah hogi, phir milenge.\n"
    "\n"
    "Abhi, bas neend.\n"
)


def main():
    print(f"\n═══ Re-rendering {OLD_ID} with proper short-story flow ═══")
    print(f"  hook ({len(HOOK_DEVA)} chars): {HOOK_DEVA!r}")
    audio = assemble_story_audio(
        text_deva=TEXT_DEVA,
        hook_deva=HOOK_DEVA,
        voice_label="anika",
        mood="calm",
    )
    duration = round(len(audio) / 1000)
    print(f"  duration: {duration}s")

    # Save to all paths the publish flow uses
    pre_gen = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{OLD_ID}_anika.mp3"
    seed_audio = BASE_DIR / "seed_output" / "stories_hi" / f"{OLD_ID}.mp3"
    for p in (seed_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
        audio.export(p, format="mp3", bitrate="192k")
        print(f"  wrote: {p.relative_to(REPO_ROOT)}")

    # Update content.json — title, text, hook, story_type, repeated_phrase
    cj = BASE_DIR / "seed_output" / "content.json"
    data = json.loads(cj.read_text())
    items = data["items"] if isinstance(data, dict) else data
    for it in items:
        if it.get("id") == OLD_ID:
            it["title"] = NEW_TITLE
            it["title_deva"] = NEW_TITLE_DEVA
            it["title_en"] = NEW_TITLE_EN
            it["text"] = TEXT_ROMAN
            it["text_deva"] = TEXT_DEVA
            it["raw_text"] = TEXT_ROMAN
            it["raw_text_deva"] = TEXT_DEVA
            it["hook"] = HOOK_ROMAN
            it["hook_deva"] = HOOK_DEVA
            it["story_type"] = "prakriti_katha"  # nature story
            it["storyType"] = "prakriti_katha"
            it["repeated_phrase"] = "Dheere, Neel, dheere"
            it["repeated_phrase_deva"] = "धीरे, नील, धीरे"
            it["duration_seconds"] = duration
            it["durationSec"] = duration
            it["has_baked_music"] = True  # intro/outro/bed baked in
            for v in (it.get("audio_variants") or []):
                v["duration_seconds"] = duration
            it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"  patched content.json entry")
            break
    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
