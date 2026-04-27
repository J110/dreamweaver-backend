#!/usr/bin/env python3
"""Re-render Neel Aur Patang for full HINDI_SHORT_STORY_GUIDELINES (2) v2 compliance.

Path A from the spec audit:
  • Voice → tripti (calm-mood primary per §20, was anika which is curious-mood)
  • Word count trimmed to 117 (was 280; v2 §13 caps age 2-5 at 50-200)
  • Tagged Roman lives in `text` field (per §17 example; frontend strips at render)
  • Added `morals` (1 moral) and 13-field `diversityFingerprint` (per §17)
  • Audio still uses fix_hindi_batch_day2.assemble_story_audio:
    intro_calm.wav + hook + bed -18 dB + 3 [MUSIC] swells + outro_calm.wav
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


# ─── Story content (trimmed to v2 word band) ────────────────────────────

OLD_ID = "hi-patang-2-5-bndr"
NEW_TITLE = "Neel Aur Patang"
NEW_TITLE_DEVA = "नील और पतंग"
NEW_TITLE_EN = "Neel and the Kite"

HOOK_ROMAN = "Neel bandar ko aaj raat kuch ajeeb mila — ek nanhi neeli patang."
HOOK_DEVA  = "नील बंदर को आज रात कुछ अजीब मिला — एक नन्ही नीली पतंग।"

# Roman Hindi with v2 tags inline (per §17 example).
TEXT_ROMAN = (
    "Pahaadi par ek purana bargad tha. Suno na — sabse upar, ek chhota bandar Neel baitha tha.\n"
    "\n"
    "Aaj shaam, Neel ne neeli patang dekhi. Hawa sarr sarr chal rahi thi. Patang dheere dheere udd rahi thi.\n"
    "\n"
    "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
    "\n"
    "\"Aa ja patang!\" Neel chillaaya. Patang nahin aayi.\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "Phir Neel ne sochaa — zor se nahin, dheere se bulaaun.\n"
    "\n"
    "Aankhein band kiin. Lambi saans li.\n"
    "\n"
    "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
    "\n"
    "Aur tab, hawa ka jhonka. Patang dheere dheere shaakh par utri. Neel ke paas.\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "Hawa thandi thi. Chaand chamak raha tha.\n"
    "\n"
    "\"Achha,\" Neel ne dheere se kaha. \"Tum bhi thakk gayi ho?\"\n"
    "\n"
    "[PAUSE: 1000]\n"
    "\n"
    "Neel muskaaya. Aankhein band kiin. Patang bhi saath. Dono — neend mein gum.\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "[PHRASE]Dheere, Neel, dheere[/PHRASE]\n"
    "\n"
    "Subah hogi, phir milenge.\n"
)

# Devanagari version (engine input — same structure, tags identical).
TEXT_DEVA = (
    "पहाड़ी पर एक पुराना बरगद था। सुनो ना — सबसे ऊपर, एक छोटा बंदर नील बैठा था।\n"
    "\n"
    "आज शाम, नील ने नीली पतंग देखी। हवा सर्र सर्र चल रही थी। पतंग धीरे धीरे उड़ रही थी।\n"
    "\n"
    "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
    "\n"
    "\"आ जा पतंग!\" नील चिल्लाया। पतंग नहीं आई।\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "फिर नील ने सोचा — ज़ोर से नहीं, धीरे से बुलाऊँ।\n"
    "\n"
    "आँखें बंद कीं। लंबी साँस ली।\n"
    "\n"
    "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
    "\n"
    "और तब, हवा का झोंका। पतंग धीरे धीरे शाख पर उतरी। नील के पास।\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "हवा ठंडी थी। चाँद चमक रहा था।\n"
    "\n"
    "\"अच्छा,\" नील ने धीरे से कहा। \"तुम भी थक गई हो?\"\n"
    "\n"
    "[PAUSE: 1000]\n"
    "\n"
    "नील मुस्कुराया। आँखें बंद कीं। पतंग भी साथ। दोनों — नींद में गुम।\n"
    "\n"
    "[MUSIC]\n"
    "\n"
    "[PHRASE]धीरे, नील, धीरे[/PHRASE]\n"
    "\n"
    "सुबह होगी, फिर मिलेंगे।\n"
)

MORALS = [
    "Sometimes the things we want come closer when we stop reaching for them."
]

DIVERSITY_FINGERPRINT = {
    "characterType": "land_mammal",
    "setting": "tree",
    "plotShape": "discovery_reveal",
    "timeOfDay": "twilight",
    "weather": "clear",
    "theme": "patience",
    "scale": "tiny_intimate",
    "companion": "object_pair",
    "movement": "stillness",
    "magicType": "none",
    "season": "summer",
    "senseEmphasis": "tactile",
    "characterTrait": "curious",
}

VOICE = "tripti"  # calm-mood primary per HINDI_SHORT_STORY_GUIDELINES (2) §20


def main():
    print(f"\n═══ Re-rendering {OLD_ID} (v2 path A — full compliance) ═══")
    print(f"  voice: {VOICE} (calm primary; was anika=curious primary)")
    print(f"  hook ({len(HOOK_DEVA)} chars): {HOOK_DEVA!r}")
    audio = assemble_story_audio(
        text_deva=TEXT_DEVA,
        hook_deva=HOOK_DEVA,
        voice_label=VOICE,
        mood="calm",
    )
    duration = round(len(audio) / 1000)
    print(f"  duration: {duration}s")

    pre_gen = WEB_ROOT / "public" / "audio" / "pre-gen" / f"{OLD_ID}_{VOICE}.mp3"
    seed_audio = BASE_DIR / "seed_output" / "stories_hi" / f"{OLD_ID}.mp3"
    for p in (seed_audio, pre_gen):
        p.parent.mkdir(parents=True, exist_ok=True)
        audio.export(p, format="mp3", bitrate="192k")
        print(f"  wrote: {p.relative_to(REPO_ROOT)}")

    # ── Patch seed_output/content.json ──
    cj = BASE_DIR / "seed_output" / "content.json"
    data = json.loads(cj.read_text())
    items = data["items"] if isinstance(data, dict) else data
    for it in items:
        if it.get("id") == OLD_ID:
            it["title"] = NEW_TITLE
            it["title_deva"] = NEW_TITLE_DEVA
            it["title_en"] = NEW_TITLE_EN
            it["text"] = TEXT_ROMAN          # tagged per §17
            it["text_deva"] = TEXT_DEVA
            it["raw_text"] = TEXT_ROMAN      # back-compat alias
            it["raw_text_deva"] = TEXT_DEVA
            it["hook"] = HOOK_ROMAN
            it["hook_deva"] = HOOK_DEVA
            it["story_type"] = "prakriti_katha"
            it["storyType"] = "prakriti_katha"
            it["repeated_phrase"] = "Dheere, Neel, dheere"
            it["repeated_phrase_deva"] = "धीरे, नील, धीरे"
            it["morals"] = MORALS
            it["diversityFingerprint"] = DIVERSITY_FINGERPRINT
            it["mood"] = "calm"
            it["duration_seconds"] = duration
            it["durationSec"] = duration
            it["has_baked_music"] = True
            it["audio_url"] = f"/audio/pre-gen/{OLD_ID}_{VOICE}.mp3"
            it["audio_variants"] = [{
                "voice": VOICE,
                "url": f"/audio/pre-gen/{OLD_ID}_{VOICE}.mp3",
                "duration_seconds": duration,
                "provider": "elevenlabs-multilingual-v2",
            }]
            it["tts_engine"] = "elevenlabs_multilingual_v2"
            it["tts_input_script"] = "devanagari"
            it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            print("  patched seed content.json entry")
            break
    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
