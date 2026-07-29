"""Shared, language-neutral long-story axis definitions + picker + physiology contract.

Imported by BOTH the EN generator (generate_long_story_episode.py) and the HI
generator (_hindi_generators.py / _hindi_diversity.py) so the meaning-bearing
axes cannot re-diverge into two separate monotonies. Only surface phrasing
(en_hint / hi_hint) and world pools stay language-local.

See docs/superpowers/specs/2026-07-02-long-story-generation-redesign.md
"""
import random
import re

# ═══════════════════════════════════════════════════════════════════
#  Cast enforcement — count SPEAKING ENTITIES, not declared characters.
#  A gate that only checks the declared [CHARACTER:]/characters array is
#  narrower than the property we want: solo = no second voice. An
#  UNDECLARED companion that still gets dialogue lines (e.g. a talking
#  moth that says "they're not hiding, they're waiting") defeats a
#  declaration-only gate while being a companion by function. So parse
#  the actual dialogue tags and count distinct speakers instead.
# ═══════════════════════════════════════════════════════════════════
# A dialogue tag is a line-leading  NAME: "..."  — a speaker name (letters,
# spaces, limited punctuation) immediately followed by a colon and a quote.
# Narration with a stray colon ("usne kaha: chalo") lacks the opening quote
# and is not matched. Bracketed tags ([SONG_SEED: ...]) are skipped up front.
_SPEAKER_RE = re.compile(r'^([A-Za-z][A-Za-z .\'_-]{0,30}?)\s*:\s*["“\']')
_NON_SPEAKER_TOKENS = {"SONG_SEED", "PAUSE", "WHISPER", "PHRASE", "BREATHE",
                       "CHARACTER", "INTRO", "MUSIC", "POST_SONG"}


def distinct_speakers(text: str) -> set:
    """Distinct dialogue-tag speakers, normalized upper. Counts speaking
    entities regardless of [CHARACTER:] declaration — the real 'second
    voice' property, not the declared-array proxy."""
    out = set()
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("["):
            continue
        m = _SPEAKER_RE.match(s)
        if m:
            name = m.group(1).strip().upper()
            if name and name not in _NON_SPEAKER_TOKENS:
                out.add(name)
    return out


def solo_cast_violation(text: str, declared_count: int) -> str:
    """Return an error string if a solo story has a second voice (declared
    OR undeclared speaker), else ''. Solo = exactly one voice: the child's."""
    speakers = distinct_speakers(text)
    if len(speakers) > 1:
        return (f"cast_structure=solo but {len(speakers)} distinct speakers "
                f"({', '.join(sorted(speakers))}) — an undeclared companion still "
                f"has a voice; solo means no second voice, only the child's")
    if declared_count > 1:
        return (f"cast_structure=solo but {declared_count} characters declared — "
                f"no companion (even a silent one) should appear; the world "
                f"settles around the child alone")
    return ""


# ═══════════════════════════════════════════════════════════════════
#  Layer B — tracked meaning-bearing axes (shared across EN + HI)
# ═══════════════════════════════════════════════════════════════════

RESOLUTION_MEANINGS = {
    "was_resting": {
        "desc": "The stilled thing was simply tired and sleeping.",
        "en_hint": "It was tired. It was only sleeping, the way the child soon will be.",
        "hi_hint": "Woh bas thak gaya tha. So raha tha, jaise tum thodi der mein soge.",
    },
    "went_home": {
        "desc": "It returned to where it belongs; a journey completed.",
        "en_hint": "It went home. Everything that was out in the dark has returned to where it belongs.",
        "hi_hint": "Woh apne ghar chala gaya. Jo bhi bahar tha, ab apni jagah laut aaya hai.",
    },
    "finished_its_work": {
        "desc": "It did its job for the day and is now done, at rest.",
        "en_hint": "It finished its work for the day. The task is done; now it can rest.",
        "hi_hint": "Usne aaj ka kaam poora kar liya. Ab kaam khatam, ab aaram.",
    },
    "became_something_quieter": {
        "desc": "It transformed into a calmer form (river->still water, star->dawn, song->hum).",
        "en_hint": "It did not leave -- it became something quieter. The bright thing softened into a still one.",
        "hi_hint": "Woh gaya nahin -- bas aur shaant ho gaya. Tez cheez dheere si ho gayi.",
    },
    "was_always_there": {
        "desc": "It never left; you only see it once you are still enough.",
        "en_hint": "It was always there. You just have to be still enough to notice it.",
        "hi_hint": "Woh hamesha wahin tha. Bas itna shaant hona tha ki dikh jaaye.",
    },
    "was_waiting_for_you": {
        "desc": "It was waiting for the child to be calm and ready to rest.",
        "en_hint": "It was waiting -- for you to be calm, for you to be ready to rest.",
        "hi_hint": "Woh tumhara intezaar kar raha tha -- ki tum shaant ho jao, aaram ke liye taiyaar ho jao.",
    },
}

NARRATIVE_SHAPES = {
    "investigate_resolve": {
        "desc": "Something is wrong/missing; the character finds out; it resolves into rest.",
        "en_hint": "Something is gently wrong or missing. The character wonders, follows it, and the answer turns out to be rest.",
        "hi_hint": "Kuch halka sa gadbad ya kho gaya hai. Character dhoondta hai, aur jawab nikalta hai -- aaram.",
    },
    "arrival": {
        "desc": "The character is still; something gently comes TO them. No quest.",
        "en_hint": "There is no quest. The character is already still, and things come to them one by one, each quieter than the last. The things that arrive are ALREADY CALM — they come to rest/settle, NOT to be rescued: no lost/scared/afraid arriver, no 'something needs comfort' tension beat. If the cast is solo, the things that arrive are WORLD-ELEMENTS (the tide, the light, petals, a drifting lantern that dims), never a new speaking character.",
        "hi_hint": "Koi khoj nahin. Character pehle se shaant hai; cheezein ek ek karke uske paas aati hain, har baar pehle se dheere. Jo cheezein aati hain woh PEHLE SE SHAANT hain — aaram karne aati hain, bachaane ke liye nahin: koi khoya/dara/sehma hua aane-wala nahin, koi 'kisi ko tasalli chahiye' wala tension nahin. Agar cast solo hai, toh jo aata hai woh DUNIYA-KA-HISSA hai (lehar, roshni, pankhudiyan, ek diya jo paas aa kar dheema ho), kabhi naya bolne-wala character nahin.",
    },
    "circular": {
        "desc": "Ends on the opening image, transformed by stillness. Recognition, not twist.",
        "en_hint": "REQUIRED STRUCTURE: end on the EXACT image/line you opened with, now transformed by stillness — explicitly call the opening back ('...just as it was at the start, but now quiet'). It must read as a return, recognition, never a surprise-twist.",
        "hi_hint": "ZAROORI DHAANCHA: kahani theek wahi image/line par khatam ho jahan shuru hui thi, ab shaanti se badli hui — shuruaat ko phir se explicitly laao ('...bilkul jaise shuru mein tha, par ab chup'). Yeh laut-aana lage, pehchaan — koi chaunkane wala mod nahin.",
    },
    "nested": {
        "desc": "A told story that dissolves; the telling itself is the descent.",
        "en_hint": "REQUIRED STRUCTURE: one character explicitly TELLS a small story aloud ('X began to tell a story: ...') — a real tale-within-the-tale that itself winds down toward sleep. As the inner tale dissolves, the teller slows, and so does the listener. The told story must actually appear, not just be mentioned. CRITICAL: the inner tale must ALSO be calm and descending — no tension, no fear-then-relief hook, no problem-to-solve, no 'was afraid but then...'; it is gentle from its first line, a quiet told-memory already sliding toward sleep (never a small adventure).",
        "hi_hint": "ZAROORI DHAANCHA: ek character zor se ek chhoti kahani SUNATA hai ('X ne kahani shuru ki: ...') — sach-much kahani-ke-andar-kahani, jo khud neend ki taraf dheemi hoti hai. Jaise andar-wali kahani ghulti hai, sunane wala dheema hota hai, aur sunne wala bhi. Woh andar-wali kahani asal mein aani chahiye, sirf zikr nahin. ZAROORI: andar-wali kahani bhi shaant aur dheemi ho — koi tension nahin, koi darr-phir-rahat wala mod nahin, koi solve karne wali samasya nahin, koi 'darr gaya par phir...' nahin; woh pehli line se narm hai, neend ki taraf jaati hui.",
    },
    "pure_settling": {
        "desc": "No mystery at all; slow sensory arrival into a place, accumulating stillness.",
        "en_hint": "No mystery, nothing to solve. Only a slow, sensory arrival into a place that grows quieter and quieter.",
        "hi_hint": "Koi paheli nahin, kuch solve nahin karna. Bas ek jagah mein dheere dheere pahunchna, jo aur aur shaant hoti jaati hai.",
    },
}

EMOTIONAL_TEXTURES = {
    "tender": {"desc": "soft, caring, held",
               "en_hint": "tender and caring, like being gently held",
               "hi_hint": "narm aur pyaar bhara, jaise koi dheere se thaame hue ho"},
    "awe": {"desc": "quiet wonder at something vast/beautiful",
            "en_hint": "quiet awe -- wonder at something vast and beautiful, but never startling",
            "hi_hint": "shaant hairaani -- kisi badi, sundar cheez par, par kabhi chaunkane wali nahin"},
    "cozy_safe": {"desc": "warm, enclosed, safe",
                  "en_hint": "cozy and safe, warm and enclosed, nothing can reach you here",
                  "hi_hint": "aaramdeh aur mehfooz, garm aur band, yahaan tak kuch nahin pahunch sakta"},
    "wistful_sweet": {"desc": "gentle bittersweet longing that settles",
                      "en_hint": "wistful and sweet -- a gentle longing that softens into peace",
                      "hi_hint": "halki si yaad, meethi si -- ek narm chaah jo shaanti mein badal jaati hai"},
    "playful_fading": {"desc": "light play that slows into sleep",
                      "en_hint": "lightly playful at first, the play slowing gently into sleep",
                      "hi_hint": "shuru mein halka sa khel, jo dheere dheere neend mein badal jaata hai"},
    "reverent_quiet": {"desc": "hushed, respectful stillness",
                      "en_hint": "hushed and reverent, the way you are quiet in a very still place",
                      "hi_hint": "chup aur aadar bhari shaanti, jaise kisi bahut shaant jagah par hote ho"},
}

CAST_STRUCTURES = {
    "solo": {"desc": "one character, talks to the world/self",
             "en_hint": "EXACTLY ONE character — NO companion, mentor, creature, or second voice appears at all, and NO second [CHARACTER:] is declared. The character is alone; the world settles around them. Anything that arrives or is present is a WORLD-ELEMENT (a lantern that drifts near and dims, the tide, the petals, a far sound) that does NOT speak — never a second named character with dialogue.",
             "hi_hint": "SIRF EK character — koi saathi, guru, jeev, ya doosri awaaz bilkul nahin, aur koi doosra [CHARACTER:] declare mat karo. Character akela hai; duniya uske aas-paas shaant hoti hai. Jo bhi aata ya maujood hai woh DUNIYA-KA-HISSA hai (ek diya jo paas aa kar dheema ho jaaye, lehar, pankhudiyan, door ki aawaaz) jo BOLTA nahin — kabhi doosra naam-wala baat-karne-wala character nahin."},
    "mentor_pair": {"desc": "protagonist + one wise elder",
                    "en_hint": "the protagonist and one wise, older guide",
                    "hi_hint": "mukhya character aur ek samajhdaar, bade guide"},
    "peer_pair": {"desc": "two equals, no hierarchy",
                  "en_hint": "two equals, friends of the same standing -- no wise-elder",
                  "hi_hint": "do baraabar ke saathi, ek jaise -- koi bada-samajhdaar nahin"},
    "small_group": {"desc": "three gentle companions",
                    "en_hint": "three gentle companions together",
                    "hi_hint": "teen narm saathi, saath mein"},
    "found_companion": {"desc": "protagonist + a creature they meet/help",
                        "en_hint": "the protagonist and a small creature they meet or help along the way",
                        "hi_hint": "mukhya character aur ek chhota jeev jise woh raaste mein milta ya uski madad karta hai"},
}

# Each texture must produce a DISTINCT ending shape AND handle the repeated
# phrase differently (once-whole / repeated-whole / absent) — never the
# identical word-by-word [PHRASE] shatter that became a new monotony.
PHASE3_TEXTURES = {
    "descending_length": {"desc": "sentences shrink to 3-5 words",
                          "en_hint": "sentences shrink line by line to three or four words. The repeated phrase appears at most ONCE here, WHOLE inside one [PHRASE] tag; plain short lines carry the rest. Do NOT break the phrase into one-word pieces.",
                          "hi_hint": "vaakya chhote hote jaayein, teen-chaar shabdon tak. Repeated phrase zyada se zyada EK baar, POORA, ek hi [PHRASE] tag mein; baaki saadi chhoti lines. Phrase ko tod kar ek-ek shabd mat karo."},
    "repetition_litany": {"desc": "a whole refrain repeats and fades",
                          "en_hint": "ONE short refrain -- the repeated phrase kept WHOLE in its [PHRASE] tag -- repeats three or four times, quieter each time, a plain line between each. The refrain stays intact every time, never shattered.",
                          "hi_hint": "EK chhota refrain -- repeated phrase POORA, [PHRASE] tag mein -- teen-chaar baar, har baar dheema, beech mein ek saadi line. Refrain har baar poora, kabhi toota nahin."},
    "sensory_subtraction": {"desc": "senses switch off one by one",
                            "en_hint": "name the senses going quiet one by one -- the light, then the sound, then the warmth. The ending is about senses FADING, not the phrase: use the repeated phrase at most once (whole), or not at all.",
                            "hi_hint": "ek ek karke indriyaan shaant hon -- pehle roshni, phir aawaaz, phir garmi. Ant indriyon ke baare mein hai, phrase ke nahin: repeated phrase ek baar (poora) ya bilkul nahin."},
    "breath_countdown": {"desc": "the breath itself counts down to stillness",
                         "en_hint": "the breath itself slows and counts down to stillness, each out-breath longer. Let the BREATH carry the close -- the repeated phrase is absent, or appears once whole, never fragmented.",
                         "hi_hint": "saans khud dheemi ho kar shaanti tak gine, har saans lambi. Ant SAANS se ho -- repeated phrase gaayab, ya ek baar poora, kabhi tukdon mein nahin."},
}

# ═══════════════════════════════════════════════════════════════════
#  Breath expression -- the SEAM between emergent breath + validatable
#  breath. `in_cues` / `out_cues` are the SAME tokens the prompt tells
#  the model to use AND the A3 validator scans for. World-metaphor
#  directional words are first-class here (slides-out/waits, etc.), so
#  breath woven into world-physics is validatable without literal
#  "breathe in/out" language.
# ═══════════════════════════════════════════════════════════════════

BREATH_EXPRESSIONS = {
    "water": {
        "en_hint": "the tide slides out, long and slow, as you breathe out -- and waits as you breathe in",
        "hi_hint": "jaise saans bahar jaati hai, lehar dheere se bahar behti hai; saans andar, toh lehar ruk jaati hai",
        "in_cues":  ["breathe in", "breath in", "in-breath", "draw in", "waits", "wait", "gathers back", "andar", "ruk", "thehar"],
        "out_cues": ["breathe out", "breath out", "out-breath", "slides out", "slide out", "flows out", "recedes", "let it go", "bahar", "behti", "behta"],
    },
    "light": {
        "en_hint": "the light swells slowly on the long breath out, and rests on the breath in",
        "hi_hint": "lambi saans bahar par roshni dheere se phailti hai, saans andar par thaam jaati hai",
        "in_cues":  ["breathe in", "breath in", "in-breath", "draw in", "rests", "rest", "andar", "thaam", "sthir"],
        "out_cues": ["breathe out", "breath out", "out-breath", "swells", "swell", "brightens", "glows out", "let it go", "bahar", "phailti", "phailta"],
    },
    "creature": {
        "en_hint": "the sleeping creature's sides fall slowly on the long breath out and rise on the breath in; your breath falls into step with its",
        "hi_hint": "sote jeev ke pehlu lambi saans bahar par dheere se girte hain, saans andar par uthte hain; tumhari saans uske saath ho jaati hai",
        "in_cues":  ["breathe in", "breath in", "in-breath", "rise", "rises", "lifts", "andar", "uthte", "uthta", "uthti"],
        "out_cues": ["breathe out", "breath out", "out-breath", "fall", "falls", "sinks", "settles down", "let it go", "bahar", "girte", "girta", "girti"],
    },
    "garden": {
        "en_hint": "the petals open slowly on the long breath out, and gather in on the breath in",
        "hi_hint": "lambi saans bahar par pankhudiyan dheere se khulti hain, saans andar par simat jaati hain",
        "in_cues":  ["breathe in", "breath in", "in-breath", "gather", "gathers", "close", "closes", "andar", "simat"],
        "out_cues": ["breathe out", "breath out", "out-breath", "open", "opens", "unfold", "unfurls", "let it go", "bahar", "khulti", "khilti"],
    },
    "transport": {
        "en_hint": "the engine sighs out, long and slow, on the breath out, and gathers on the breath in",
        "hi_hint": "lambi saans bahar par gaadi/naav aage sarakti hai, saans andar par thaam leti hai",
        "in_cues":  ["breathe in", "breath in", "in-breath", "gathers", "gather", "waits", "andar", "thaam"],
        "out_cues": ["breathe out", "breath out", "out-breath", "sighs out", "sigh out", "glides", "slides forward", "let it go", "bahar", "sarakti", "sarakta"],
    },
}

# ═══════════════════════════════════════════════════════════════════
#  Recency windows for the new axes (shared)
# ═══════════════════════════════════════════════════════════════════

DIVERSITY_RECENCY_SHARED = {
    "resolution_meaning": 5,
    "narrative_shape": 4,
    "emotional_texture": 5,
    "cast_structure": 4,
    "phase3_texture": 3,
    "breath_expression": 4,
}

# ═══════════════════════════════════════════════════════════════════
#  Shape eligibility rules (age/mood) -- enforced by pool exclusion
# ═══════════════════════════════════════════════════════════════════

# Cast structure drives how many characters the story has, so a "solo" story
# is actually solo (the smoke run picked solo but still got 3 characters
# because character_count was randomized independently).
CAST_TO_COUNT = {"solo": 1, "mentor_pair": 2, "peer_pair": 2,
                 "found_companion": 2, "small_group": 3}


def cast_count(cast):
    return CAST_TO_COUNT.get(cast, 2)


ALL_SHAPES = list(NARRATIVE_SHAPES.keys())

SHAPE_AGE_MOOD_RULES = {
    "nested": {"ages": {"6-8", "9-12"}},                 # 2-5 cannot hold two story levels
    "pure_settling": {"moods": {"calm", "sad", "anxious"}},  # wired/curious/angry need capture
}


def eligible_shapes(age, mood):
    """Shapes allowed for this age/mood, after hard exclusion rules."""
    out = []
    for s in ALL_SHAPES:
        rule = SHAPE_AGE_MOOD_RULES.get(s, {})
        if "ages" in rule and age not in rule["ages"]:
            continue
        if "moods" in rule and mood not in rule["moods"]:
            continue
        out.append(s)
    return out


def pick_avoiding_recent_clamped(existing, key, pool, window):
    """Pick from pool avoiding recently-used values.

    Effective window is clamped to min(window, len(pool)-1) so there is
    ALWAYS >= 1 candidate -- no deadlock, no fallback-to-full repeat-adjacent.
    """
    if not pool:
        raise ValueError(f"empty pool for axis {key}")
    eff = max(0, min(window, len(pool) - 1))
    recent = [s.get(key) for s in existing[-eff:] if s.get(key)] if (existing and eff) else []
    available = [v for v in pool if v not in recent]
    if not available:
        available = list(pool)
    return random.choice(available)


# ═══════════════════════════════════════════════════════════════════
#  Breath-family derivation (world/cast -> breath expression key)
# ═══════════════════════════════════════════════════════════════════

WORLD_TO_BREATH = {  # EN STORY_WORLDS keys
    "library": "light", "workshop": "light", "transport": "transport",
    "garden": "garden", "observatory": "light", "kitchen": "water",
    "post_office": "light", "museum": "light", "lighthouse": "light",
    "theater": "light",
}

_HI_WORLD_KEYWORDS = [
    (("nadi", "talaab", "samundar", "paani", "jheel", "lehar", "sagar", "sota"), "water"),
    (("bagicha", "bageecha", "phool", "phul", "ped", "van", "upvan"), "garden"),
    (("gaadi", "gadi", "train", "rail", "naav", "nauka", "jahaaz"), "transport"),
]


def breath_family(world_type=None, cast=None, world_name=None):
    """Pick the breath-expression key from world/cast context."""
    if cast == "found_companion":
        return "creature"
    if world_type and world_type in WORLD_TO_BREATH:
        return WORLD_TO_BREATH[world_type]
    if world_name:
        wl = world_name.lower()
        for keys, fam in _HI_WORLD_KEYWORDS:
            if any(k in wl for k in keys):
                return fam
    return "light"


def select_story_axes(existing, age, mood, world_family="light"):
    """Select all Layer-B axes for one story, respecting eligibility + recency."""
    shapes = eligible_shapes(age, mood)
    cast = pick_avoiding_recent_clamped(
        existing, "cast_structure", list(CAST_STRUCTURES), DIVERSITY_RECENCY_SHARED["cast_structure"])
    # breath_expression is a FIRST-CLASS TRACKED axis, not derived from
    # world-keyword matching (that silently collapsed to 'light' for HI world
    # names that matched no keyword). A found_companion implies a creature to
    # breathe with; otherwise pick + track like every other axis so it varies.
    if cast == "found_companion":
        breath = "creature"
    else:
        breath = pick_avoiding_recent_clamped(
            existing, "breath_expression",
            [b for b in BREATH_EXPRESSIONS if b != "creature"],
            DIVERSITY_RECENCY_SHARED["breath_expression"])
    return {
        "narrative_shape": pick_avoiding_recent_clamped(
            existing, "narrative_shape", shapes, DIVERSITY_RECENCY_SHARED["narrative_shape"]),
        "resolution_meaning": pick_avoiding_recent_clamped(
            existing, "resolution_meaning", list(RESOLUTION_MEANINGS), DIVERSITY_RECENCY_SHARED["resolution_meaning"]),
        "emotional_texture": pick_avoiding_recent_clamped(
            existing, "emotional_texture", list(EMOTIONAL_TEXTURES), DIVERSITY_RECENCY_SHARED["emotional_texture"]),
        "cast_structure": cast,
        "phase3_texture": pick_avoiding_recent_clamped(
            existing, "phase3_texture", list(PHASE3_TEXTURES), DIVERSITY_RECENCY_SHARED["phase3_texture"]),
        "breath_expression": breath,
    }


# ═══════════════════════════════════════════════════════════════════
#  Layer A -- fixed physiology contract (one per language, same A1-A4)
# ═══════════════════════════════════════════════════════════════════

PHYSIOLOGY_CONTRACT_EN = """PHYSIOLOGY CONTRACT -- NON-NEGOTIABLE (this is the sleep guarantee; obey all four):
A1  Arousal only falls. After the first ~20% of the story, nothing gets more exciting. No danger, no stakes, no "suddenly", no cliffhanger, no exclamation marks after the opening. If something seemed at risk, it never really was.
A2  The language slows. Sentences get shorter and simpler as the story goes on; the final few lines are 3-5 words each.
A3  The exhale is the long one. Whenever breath appears, the in-breath is brief and the out-breath is long and slow, and the world softens on the out-breath. Mark every breath moment with a [BREATHE] tag on its own line.
A4  The ending dissolves -- it never wakes. No one wakes up, springs up, or is excited at the end. The last lines fade into stillness and sleep."""

PHYSIOLOGY_CONTRACT_HI = """PHYSIOLOGY CONTRACT -- NON-NEGOTIABLE (yeh sleep guarantee hai; chaaron rules follow karo). Output stays conversational Roman Hindi:
A1  Arousal sirf girta hai. Pehle ~20% ke baad kuch bhi aur exciting nahin hota. Koi khatra nahin, koi stakes nahin, koi "achanak" nahin, koi cliffhanger nahin, aur opening ke baad koi exclamation (!) nahin. Agar kuch khatre mein laga bhi, toh asal mein tha nahin.
A2  Bhasha dheemi hoti hai. Jaise kahani aage badhti hai, vaakya chhote aur saral hote jaate hain; aakhri kuch lines 3-5 shabd ki.
A3  Saans bahar wali lambi hoti hai. Jab bhi saans aaye, andar ki saans chhoti aur bahar ki saans lambi aur dheemi -- aur duniya bahar-wali saans par narm hoti hai. Har saans-pal ko apni line par [BREATHE] tag se mark karo.
A4  Ant vilay hota hai -- kabhi jagta nahin. Ant mein koi jaagta nahin, uthta nahin, excited nahin hota. Aakhri lines shaanti aur neend mein ghul jaati hain."""


def story_spec_block(axes, lang):
    """Build the per-story STORY SPEC prompt block from picked axes."""
    hint = "en_hint" if lang == "en" else "hi_hint"
    be = BREATH_EXPRESSIONS[axes["breath_expression"]]
    return (
        "STORY SPEC (this story only -- vary on these; do NOT fall back to defaults):\n"
        f"- narrative_shape: {axes['narrative_shape']} -- {NARRATIVE_SHAPES[axes['narrative_shape']][hint]}\n"
        f"- resolution_meaning: {axes['resolution_meaning']} -- {RESOLUTION_MEANINGS[axes['resolution_meaning']][hint]}\n"
        f"- emotional_texture: {axes['emotional_texture']} -- {EMOTIONAL_TEXTURES[axes['emotional_texture']][hint]}\n"
        f"- cast_structure: {axes['cast_structure']} -- {CAST_STRUCTURES[axes['cast_structure']][hint]}\n"
        f"- phase3_texture (how the ending dissolves): {axes['phase3_texture']} -- {PHASE3_TEXTURES[axes['phase3_texture']][hint]}\n"
        f"- breath (EMERGENT from the world -- do NOT use a narrator 'breathe in/out' cue): {be[hint]}\n"
    )
