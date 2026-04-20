#!/usr/bin/env python3
"""Story-craft patch for Chiki story (hi-prkr-2-5-gilh).

Three spec violations per the Hindi short story guidelines:

  1. Direct addresses to the child: only 1 clean one ("Suno na bachcho").
     Spec wants 2-3. The internal "Arre, yeh kya ho raha hai?" is
     ambiguous (is it Chiki thinking or narrator asking?) and doesn't
     cleanly count.
     Fix: insert 3 clean narrator-to-child addresses; remove ambiguous
     internal question.

  2. Prakriti katha signature missing. "Suno na bachcho. Aaj Chiki gilhari
     ki kahani" is a LOK katha opener ("here's a story about X"). A
     nature story must open with a sensory image — sound, smell, or
     temperature — and the child walks into the scene first, meeting
     the character second.
     Fix: open "Shaam thi. Hawa thandi thandi..." then introduce Chiki.

  3. Character detail too generic. "Choti choti aankhein, bhuri si dumm,
     aur hamesha kuch na kuch chabati rehti" describes every squirrel.
     Spec's SPECIFICITY OVER GENERIC principle wants ONE small detail
     that makes Chiki memorable as Chiki.
     Fix: "sabse upar wali shaakh jahan se saara gaon dikhta tha" —
     something only Chiki does.

Scope: story text only. Lullaby untouched. Cover untouched. Audio
re-rendered with new text + skip_hook=True. content.json updated.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

sys.path.insert(0, str(Path(__file__).parent))
from fix_hindi_batch_day2 import STORY, upsert_content
from fix_hindi_batch_day2_patch import (
    assemble_story_audio_no_hook, clean_lyrics_text,
    story_entry_clean,
)

load_dotenv(BASE_DIR / ".env", override=True)


# ─────────────────────────────────────────────────────────────────────────
# New bilingual narrative.  Roman and Devanagari are 1-for-1 line-matched.
# ─────────────────────────────────────────────────────────────────────────
#
# Craft checklist:
#   ✓ sensory opening (shaam, hawa thandi)
#   ✓ Chiki introduced AFTER the scene
#   ✓ specific Chiki-only detail (top branch, village view)
#   ✓ 3 direct addresses to child: "Tumne kabhi hawa ko...", "Tumhe
#     pata hai kya ho raha tha?", "Tumne kabhi baarish mein..."
#   ✓ no internal "Arre" question — replaced with narrator→child address
#   ✓ repeated phrase "Chupke chupke, tip tip tip" preserved (3 times)
#   ✓ [MUSIC] swell preserved in same spot (rain lullaby moment)
#   ✓ [PAUSE: ms] beats preserved

NEW_TEXT_ROMAN = (
    "Shaam thi. Hawa thandi thandi chal rahi thi. Peepal ke bade se ped par, "
    "sabse upar wali shaakh par, ek chhoti si gilhari baithi thi. Naam tha "
    "Chiki.\n\n"
    "Chiki hamesha isi shaakh par aati thi — sabse upar wali — jahan se "
    "saara gaon dikhta tha. Chhote chhote ghar, mandir ki choti, aur door "
    "door tak khet.\n\n"
    "Tumne kabhi hawa ko itna dheere chalte dekha hai? Waisi hi thi us "
    "shaam ki hawa.\n\n"
    "[PAUSE: 800]\n\n"
    "Chiki ne upar dekha. Tumhe pata hai kya ho raha tha? Baadal kaale "
    "kaale aa rahe the, aasmaan bhar gaya. Sarr sarr, sarr sarr — hawa "
    "dheere dheere ghoomne lagi.\n\n"
    "[PAUSE: 600]\n\n"
    "Phir tap. Ek bunda gira patte par. Phir tap tap. Aur phir tap tap "
    "tap tap.\n\n"
    "Tumne kabhi baarish mein patte ke niche chhupa hai? Chiki ne bhi "
    "aisa hi kiya — chhup gayi bade patte ke niche, aur baarish ki aawaz "
    "sunne lagi. Dheere dheere, jaise koi lori gaa raha ho.\n\n"
    "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
    "[MUSIC]\n\n"
    "Ek chhota sa phal haath mein, patte ki chatri upar, aur aankhein "
    "band. Chiki ko yeh pehli baarish bahut achhi lagi.\n\n"
    "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n"
    "[PAUSE: 1000]\n\n"
    "Hawa dheemi. Baarish dheemi. Chiki ki neend bhi aane lagi.\n\n"
    "Peepal jhoomta raha. Baadal gale milte rahe. Chiki ki saans dheere "
    "chalti rahi.\n\n"
    "[PHRASE] Chupke chupke, tip tip tip. [/PHRASE]\n\n"
    "Aur Chiki so gayi."
)

NEW_TEXT_DEVA = (
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
)

# Description gets refreshed to match the new sensory opening.
NEW_DESCRIPTION_EN = (
    "A small Indian palm squirrel named Chiki sits on the topmost branch "
    "of a peepal tree and watches the first monsoon rain arrive."
)


def main():
    # Monkey-patch the imported STORY dict so downstream helpers use the
    # new narrative without us having to duplicate schema logic.
    STORY["text_roman"]     = NEW_TEXT_ROMAN
    STORY["text_deva"]      = NEW_TEXT_DEVA
    STORY["description_en"] = NEW_DESCRIPTION_EN

    # HARD GATE — run the narrative-craft validator on the mutated STORY
    # dict before we spend any Mistral/ElevenLabs/MiniMax calls.
    # See docs/HINDI_SHORT_STORY_GUIDELINES.md.
    from validate_hindi_story import validate_story_dict
    issues = validate_story_dict(STORY)
    if issues:
        print("\n═══ STORY dict fails narrative-craft checklist ═══",
              file=sys.stderr)
        for i in issues:
            print(f"  ❌ {i}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ narrative-craft checklist (§1-§7) passed")

    # 1. Re-render story audio (Devanagari for TTS, hook suppressed).
    print("\n═══ STORY audio (new text, skip_hook=True) ═══")
    story_audio = assemble_story_audio_no_hook(
        STORY["text_deva"], STORY["voice"], STORY["mood"])
    story_audio_path = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{STORY['id']}_{STORY['voice']}.mp3"
    story_audio.export(story_audio_path, format="mp3", bitrate="192k")
    story_duration = round(len(story_audio) / 1000)
    print(f"  → {story_audio_path}  ({story_duration}s)")

    # 2. Rebuild content.json entry — clean text, raw in raw_text.
    print("\n═══ JSON rewrite (story only) ═══")
    s_entry = story_entry_clean(story_duration)
    # Refresh description/hook display in the entry itself.
    s_entry["description_en"] = NEW_DESCRIPTION_EN
    # Confirm clean text.
    t = s_entry["text"]
    print(f"\n  text[0:160]: {t[:160]!r}")
    print(f"  tag-leak: [PAUSE={'[PAUSE' in t}  [PHRASE={'[PHRASE' in t}  [MUSIC={'[MUSIC' in t}")
    # Count direct addresses in the clean text (simple heuristic).
    direct_markers = ["Tumne kabhi", "Tumhe pata hai"]
    hits = sum(t.count(m) for m in direct_markers)
    print(f"  direct addresses to child: {hits} (spec: 2-3)")

    upsert_content([s_entry])

    print("\n═════ PATCH 2 DONE ═════")
    print(f"  story: {story_duration}s, new prakriti-katha opening, "
          f"{hits} direct addresses, 1 specific Chiki detail")


if __name__ == "__main__":
    main()
