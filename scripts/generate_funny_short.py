#!/usr/bin/env python3
"""Generate funny short scripts for the Before Bed tab.

Uses a fingerprint-based diversity scheduler to pick comedy type, format,
and voice combo — then tells the LLM exactly what to generate.

Usage:
    python3 scripts/generate_funny_short.py --age 6-8 --auto
    python3 scripts/generate_funny_short.py --age 6-8 --auto --count 3
    python3 scripts/generate_funny_short.py --age 2-5 --comedy-type villain_fails --format duo --voices comedic_villain,high_pitch_cartoon
"""

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mistralai import Mistral

# ── Constants ──────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"

CHARACTER_TO_VOICE = {
    "MOUSE": "high_pitch_cartoon",
    "CROC": "comedic_villain",
    "SWEET": "young_sweet",
    "WITCH": "mysterious_witch",
    "MUSICAL": "musical_original",
}

VOICE_TO_CHARACTER = {v: k for k, v in CHARACTER_TO_VOICE.items()}

VOICE_DISPLAY_NAMES = {
    "high_pitch_cartoon": "MOUSE",
    "comedic_villain": "CROC",
    "young_sweet": "SWEET",
    "mysterious_witch": "WITCH",
    "musical_original": "MUSICAL",
}

VOICE_DESCRIPTIONS = {
    "high_pitch_cartoon": "Squeaky Minnie Mouse energy. Reacts with alarm and panic. Short sentences.",
    "comedic_villain": "Deep dramatic crocodile. Self-important, always failing. Non-human voice.",
    "young_sweet": "Innocent-sounding but sarcastic. Deadpan. Unbothered. Master of understatement.",
    "mysterious_witch": "Dark, low, mysterious. Makes everything a dark prophecy. The dramatic narrator.",
    "musical_original": "Rhythmic, poetic, almost singing. For verse comedy and nonsense rhymes.",
}

# ── Diversity Scheduler ────────────────────────────────────────

COMEDY_TYPES = [
    "physical_escalation",
    "villain_fails",
    "misunderstanding",
    "sound_effect",
    "ominous_mundane",
    "sarcastic_commentary",
]

COMEDY_TYPE_TARGET = {
    "physical_escalation": 0.20,
    "villain_fails": 0.20,
    "misunderstanding": 0.15,
    "ominous_mundane": 0.15,
    "sarcastic_commentary": 0.15,
    "sound_effect": 0.15,
}

FORMAT_TARGET = {
    "solo": 0.40,
    "duo": 0.40,
    "trio": 0.20,
}

COMEDY_AGE_VALID = {
    "2-5": ["physical_escalation", "villain_fails", "sound_effect"],
    "6-8": ["physical_escalation", "villain_fails", "misunderstanding",
            "ominous_mundane", "sarcastic_commentary", "sound_effect"],
    "9-12": ["villain_fails", "misunderstanding", "ominous_mundane",
             "sarcastic_commentary"],
}

VOICE_AGE_VALID = {
    "2-5": ["high_pitch_cartoon", "comedic_villain", "musical_original"],
    "6-8": ["high_pitch_cartoon", "comedic_villain", "young_sweet",
            "mysterious_witch", "musical_original"],
    "9-12": ["comedic_villain", "young_sweet", "mysterious_witch",
             "musical_original"],
}

COMEDY_VOICE_AFFINITY = {
    "physical_escalation": {
        "solo": ["high_pitch_cartoon"],
        "duo": ["high_pitch_cartoon", "comedic_villain"],
    },
    "villain_fails": {
        "solo": ["comedic_villain"],
        "duo": ["comedic_villain", "high_pitch_cartoon"],
        "trio": ["comedic_villain", "high_pitch_cartoon", "mysterious_witch"],
    },
    "misunderstanding": {
        "solo": ["young_sweet"],
        "duo": ["young_sweet", "comedic_villain"],
    },
    "ominous_mundane": {
        "solo": ["mysterious_witch"],
        "duo": ["mysterious_witch", "young_sweet"],
    },
    "sarcastic_commentary": {
        "solo": ["young_sweet"],
        "duo": ["young_sweet", "comedic_villain"],
    },
    "sound_effect": {
        "solo": ["high_pitch_cartoon"],
        "duo": ["high_pitch_cartoon", "comedic_villain"],
    },
}

SOLO_STYLES = {
    "high_pitch_cartoon": ("talking to the listener directly, breaking the fourth wall, "
                           "reacting to things happening around them that we can't see"),
    "comedic_villain": ("monologuing to themselves about their genius plan, "
                        "narrating their own actions in third person as if they're epic"),
    "mysterious_witch": ("narrating to the listener as if telling a dark secret, "
                         "treating mundane events as ominous prophecy"),
    "young_sweet": ("talking to the listener like a friend, "
                    "commenting on something absurd they just witnessed"),
    "musical_original": ("performing a poem or verse directly to the listener, "
                         "the audience is the child being read to"),
}


def _select_comedy_type(age_shorts: list, total: int, age_group: str) -> str:
    """Pick the comedy type with the largest deficit for this age group."""
    valid_types = COMEDY_AGE_VALID[age_group]
    type_counts = Counter(s.get("comedy_type") for s in age_shorts)

    max_deficit = -1
    selected = valid_types[0]

    for ctype in valid_types:
        target = COMEDY_TYPE_TARGET.get(ctype, 0.15)
        actual = type_counts.get(ctype, 0) / total
        deficit = target - actual
        if deficit > max_deficit:
            max_deficit = deficit
            selected = ctype

    return selected


def _select_format(age_shorts: list, total: int) -> str:
    """Pick the format with the largest deficit."""
    format_counts = Counter(s.get("format") for s in age_shorts)

    max_deficit = -1
    selected = "solo"

    for fmt, target in FORMAT_TARGET.items():
        actual = format_counts.get(fmt, 0) / total
        deficit = target - actual
        if deficit > max_deficit:
            max_deficit = deficit
            selected = fmt

    return selected


def _select_solo_voice(age_shorts: list, valid_voices: list,
                       suggested: list | None) -> list:
    """Pick least-used voice for a solo short."""
    voice_counts = Counter()
    for s in age_shorts:
        if s.get("format") == "solo" and s.get("primary_voice"):
            voice_counts[s["primary_voice"]] += 1

    if suggested and suggested[0] in valid_voices:
        min_count = min(voice_counts.get(v, 0) for v in valid_voices)
        if voice_counts.get(suggested[0], 0) == min_count:
            return suggested

    least_used = min(valid_voices, key=lambda v: voice_counts.get(v, 0))
    return [least_used]


def _select_duo_voices(age_shorts: list, valid_voices: list,
                       suggested: list | None) -> list:
    """Pick least-used voice pair for a duo."""
    combo_counts = Counter()
    for s in age_shorts:
        if s.get("format") == "duo":
            combo_key = tuple(sorted(s.get("voice_combo", [])))
            combo_counts[combo_key] += 1

    all_pairs = list(combinations(valid_voices, 2))
    if not all_pairs:
        return valid_voices[:2]

    if suggested and len(suggested) == 2:
        suggested_key = tuple(sorted(suggested))
        if all(v in valid_voices for v in suggested):
            min_count = min(combo_counts.get(tuple(sorted(p)), 0) for p in all_pairs)
            if combo_counts.get(suggested_key, 0) == min_count:
                return list(suggested)

    least_used = min(all_pairs, key=lambda p: combo_counts.get(tuple(sorted(p)), 0))
    return list(least_used)


def _select_trio_voices(age_shorts: list, valid_voices: list,
                        suggested: list | None) -> list:
    """Pick least-used voice trio."""
    combo_counts = Counter()
    for s in age_shorts:
        if s.get("format") == "trio":
            combo_key = tuple(sorted(s.get("voice_combo", [])))
            combo_counts[combo_key] += 1

    all_trios = list(combinations(valid_voices, 3))
    if not all_trios:
        return valid_voices[:3]

    if suggested and len(suggested) == 3:
        suggested_key = tuple(sorted(suggested))
        if all(v in valid_voices for v in suggested):
            min_count = min(combo_counts.get(tuple(sorted(t)), 0) for t in all_trios)
            if combo_counts.get(suggested_key, 0) == min_count:
                return list(suggested)

    least_used = min(all_trios, key=lambda t: combo_counts.get(tuple(sorted(t)), 0))
    return list(least_used)


def _select_voices(age_shorts: list, age_group: str,
                   comedy_type: str, format_type: str) -> list:
    """Pick the least-used valid voice combo for this comedy type + format."""
    valid_voices = VOICE_AGE_VALID[age_group]
    affinity = COMEDY_VOICE_AFFINITY.get(comedy_type, {})
    suggested = affinity.get(format_type)

    if format_type == "solo":
        return _select_solo_voice(age_shorts, valid_voices, suggested)
    elif format_type == "duo":
        return _select_duo_voices(age_shorts, valid_voices, suggested)
    else:
        return _select_trio_voices(age_shorts, valid_voices, suggested)


def select_funny_short_spec(existing_shorts: list, age_group: str) -> dict:
    """Analyze existing library and return exactly what to generate next."""
    age_shorts = [s for s in existing_shorts if s.get("age_group") == age_group]
    total = len(age_shorts) or 1

    comedy_type = _select_comedy_type(age_shorts, total, age_group)
    format_type = _select_format(age_shorts, total)
    voices = _select_voices(age_shorts, age_group, comedy_type, format_type)

    return {
        "comedy_type": comedy_type,
        "format": format_type,
        "voices": voices,
        "age_group": age_group,
    }


def check_recency(spec: dict, recent_shorts: list, lookback: int = 5) -> bool:
    """Ensure this exact combo hasn't been generated in the last N shorts."""
    recent = recent_shorts[-lookback:]
    for s in recent:
        if (s.get("comedy_type") == spec["comedy_type"]
                and s.get("format") == spec["format"]
                and tuple(sorted(s.get("voice_combo", []))) == tuple(sorted(spec["voices"]))):
            return False
    return True


def select_with_recency(existing_shorts: list, age_group: str,
                        max_attempts: int = 5) -> dict:
    """Select spec with recency validation."""
    modified = list(existing_shorts)
    for _ in range(max_attempts):
        spec = select_funny_short_spec(modified, age_group)
        if check_recency(spec, existing_shorts):
            return spec
        # Pretend this one exists to force a different pick
        modified.append({
            "comedy_type": spec["comedy_type"],
            "format": spec["format"],
            "voice_combo": spec["voices"],
            "age_group": age_group,
        })

    return select_funny_short_spec(modified, age_group)


# ── Library Loading ────────────────────────────────────────────

def load_all_shorts() -> list[dict]:
    """Load all funny short JSONs from the data directory."""
    if not DATA_DIR.exists():
        return []

    shorts = []
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                short = json.load(fh)
                # Backfill fingerprint fields if missing
                _backfill_fingerprint(short)
                shorts.append(short)
        except Exception:
            continue

    shorts.sort(key=lambda s: s.get("created_at", ""))
    return shorts


def _backfill_fingerprint(short: dict) -> None:
    """Add format/voice_combo/primary_voice if missing."""
    voices = short.get("voices", [])
    if "format" not in short:
        short["format"] = {1: "solo", 2: "duo", 3: "trio"}.get(len(voices), "duo")
    if "voice_combo" not in short:
        short["voice_combo"] = sorted(voices)
    if "primary_voice" not in short:
        short["primary_voice"] = voices[0] if voices else ""


# ── Prompt Building ────────────────────────────────────────────

AGE_COMEDY_INSTRUCTIONS = {
    "2-5": """Ages 2-5: Physical + Sound Comedy
- Short sentences (5-10 words). Onomatopoeia. Repetition. Silly names.
- Make it SILLY. Exaggerate reactions. Use funny sounds.
- Repetition IS the joke for this age. Same structure three times, bigger each time.""",
    "6-8": """Ages 6-8: Absurdity + Character Comedy
- Medium sentences. Character dynamics are the comedy engine.
- Croc's ego vs Mouse's innocence, Witch's drama vs Sweet's sarcasm.
- Kids this age love clever word misunderstandings and dramatic irony.""",
    "9-12": """Ages 9-12: Deadpan + Meta Comedy
- Longer sentences. Dry tone. Humor through understatement.
- NEVER try to be funny. The restraint IS the comedy.
- Sweet's sarcasm and Witch's deadpan drama work best.
- Trust the audience to get the joke — don't explain it.""",
}

AVAILABLE_STINGS = """buildup_short, buildup_long, tiny, medium_hit, big_crash,
silence, deflation, victory, splat, boing, whoosh, tiptoe, run, slide_whistle,
villain_entrance, villain_fail, villain_dramatic, witch_ominous, witch_reveal,
witch_dramatic, mouse_squeak, mouse_panic, mouse_surprise, sweet_eyeroll,
sweet_pause, musical_flourish, musical_detuned"""

STRUCTURE_RULES = """STRUCTURE (mandatory):
- SETUP: 2-3 sentences. Introduce characters and one funny premise.
- BEAT 1: The funny thing happens. Small consequence.
- BEAT 2: It happens again. Bigger consequence.
- BEAT 3: THIRD time. Maximum absurd consequence.
- BUTTON: 1-2 sentences. Final punchline.

RULES:
1. ONE premise, THREE escalations. No subplots.
2. 60-90 seconds when read aloud.
3. [PUNCHLINE]...[/PUNCHLINE] on punchline sentences (sentence-level only).
4. [STING: type] at END of the sentence. Max 8 stings.
5. Every sentence = one character. No mixing within a sentence.
6. Sentence-level audio only — no word-level emphasis or mid-sentence changes.
7. AUDIO-FIRST RULE: This short will be LISTENED TO, not read. The child cannot
   see anything. Characters must describe what they see, what they're doing, and
   what's happening through their own dialogue.
   "What's this big green lumpy thing lying across the path?" — GOOD
   (the listener knows what the character is looking at)
   "Ooooh! A big green bench!" — BAD
   (the listener doesn't know where the character is or what they're seeing)
   "I'm sitting down... why are you wobbling?" — GOOD
   (the listener knows the character sat down and something is wobbling)
   "squeak... wobble wobble!" — BAD
   (text sound effects are not audio)
   Characters say what they see. Characters say what they feel. Characters
   say what just happened. If the listener can't follow the story with
   their eyes closed, it's wrong.
8. Each character sounds distinct: Mouse = alarm/panic, Croc = self-importance,
   Sweet = deadpan sarcasm, Witch = ominous drama.
9. No sleep language. Pure comedy.

DELIVERY TAGS (required):
TAG EVERY SENTENCE with [DELIVERY: tag1, tag2] BEFORE the character text.

The delivery tag describes HOW the character says this line based on
what just happened in the conversation. Tags create an emotional ARC —
characters should CHANGE across the scene.

Guidelines:
- Choose 1-2 tags per sentence. More than 2 gets muddy.
- Croc typically arcs: confident → caught off guard → desperate → deflated
- Mouse typically arcs: curious → suspicious → calm gotcha
- Sweet typically stays: unbothered → deadpan → devastating (minimal change IS the comedy)
- Witch typically arcs: ominous → building → revealing (dramatic narrator energy)
- The CONTRAST between characters' arcs is where the comedy lives.
  If Croc gets louder, Mouse should get quieter. The gap IS the joke.

Available delivery tags:
CONFIDENCE: confident, dismissive, bluster, triumphant, smug
UNCERTAINTY: tentative, caught off guard, scrambling, defensive, desperate, stunned
PRESSURE: curious, suspicious, pointed, pressing, calm gotcha, devastating
ENERGY: loud, excited, panicked, outraged, delighted
CALM: quiet, deadpan, unbothered, ominous, gentle, wistful

Available stings: """ + AVAILABLE_STINGS + """

COVER DESCRIPTION:
After the script, add a [COVER: ...] tag with a one-sentence visual scene description
for the cover illustration. Describe the PUNCHLINE moment, NOT the setup. Show the
funniest single frame — the moment of maximum absurdity.

PREMISE SUMMARY:
After the cover tag, add a [PREMISE: ...] tag with a short (5-10 word) summary of the
core premise.

CRITICAL FORMAT RULES:
- Each dialogue line MUST start with [CHARACTER] (square brackets), e.g. [MOUSE] Hello!
- Do NOT use "MOUSE:" or "CROC:" format — ONLY [MOUSE] and [CROC] with square brackets.
- VOICES line must list voice IDs, not character names."""


def build_funny_short_prompt(spec: dict) -> str:
    """Turn scheduler output into a generation prompt."""
    voices = spec["voices"]
    format_type = spec["format"]
    comedy_type = spec["comedy_type"]
    age_group = spec["age_group"]

    # Character descriptions for the selected voices
    char_lines = []
    for v in voices:
        name = VOICE_DISPLAY_NAMES[v]
        desc = VOICE_DESCRIPTIONS[v]
        char_lines.append(f"- {name}: {desc}")
    character_block = "\n".join(char_lines)

    # Voice IDs for the VOICES header
    voice_ids = ", ".join(voices)

    # Solo-specific instructions
    solo_instruction = ""
    if format_type == "solo":
        primary = voices[0]
        style = SOLO_STYLES.get(primary, "talking to the listener")
        char_name = VOICE_DISPLAY_NAMES[primary]
        solo_instruction = (
            f"\nThis is a SOLO short. {char_name} is {style}. "
            f"Do NOT introduce a second speaking character. "
            f"Every line must be [{char_name}].\n"
        )

    # Format instruction
    format_desc = {
        "solo": "SOLO (1 character)",
        "duo": "DUO (2 characters in dialogue)",
        "trio": "TRIO (3 characters)",
    }[format_type]

    # Output format example based on format
    if format_type == "solo":
        char_name = VOICE_DISPLAY_NAMES[voices[0]]
        output_example = f"""[TITLE: Your Title Here]
[AGE: {age_group}]
[VOICES: {voice_ids}]
[COMEDY_TYPE: {comedy_type}]

[SETUP]
[{char_name}] [DELIVERY: curious, tentative] Sentence text. [STING: type]
[{char_name}] [DELIVERY: confident] Another sentence.
[/SETUP]

[BEAT_1]
[{char_name}] [DELIVERY: suspicious] Sentence text.
[/BEAT_1]

[BEAT_2]
[{char_name}] [DELIVERY: caught off guard] Sentence text.
[/BEAT_2]

[BEAT_3]
[{char_name}] [DELIVERY: quiet, devastating] Sentence text. [STING: type]
[/BEAT_3]

[BUTTON]
[{char_name}] [DELIVERY: desperate, loud] [PUNCHLINE]Final punchline sentence.[/PUNCHLINE] [STING: type]
[/BUTTON]

[COVER: One-sentence visual description of the funniest punchline moment]
[PREMISE: 5-10 word premise summary]"""
    else:
        names = [VOICE_DISPLAY_NAMES[v] for v in voices]
        output_example = f"""[TITLE: Your Title Here]
[AGE: {age_group}]
[VOICES: {voice_ids}]
[COMEDY_TYPE: {comedy_type}]

[SETUP]
[{names[0]}] [DELIVERY: curious, tentative] Sentence text. [STING: type]
[{names[1] if len(names) > 1 else names[0]}] [DELIVERY: confident, dismissive] Another sentence.
[/SETUP]

[BEAT_1]
[{names[0]}] [DELIVERY: suspicious] Sentence text.
[/BEAT_1]

[BEAT_2]
[{names[1] if len(names) > 1 else names[0]}] [DELIVERY: caught off guard] Sentence text.
[/BEAT_2]

[BEAT_3]
[{names[0]}] [DELIVERY: quiet, devastating] Sentence text. [STING: type]
[/BEAT_3]

[BUTTON]
[{names[1] if len(names) > 1 else names[0]}] [DELIVERY: desperate, loud] [PUNCHLINE]Final punchline sentence.[/PUNCHLINE] [STING: type]
[/BUTTON]

[COVER: One-sentence visual description of the funniest punchline moment]
[PREMISE: 5-10 word premise summary]"""

    prompt = f"""Generate a {comedy_type.upper().replace('_', ' ')} funny short for ages {age_group}.

Format: {format_desc}

Characters:
{character_block}
{solo_instruction}
{AGE_COMEDY_INSTRUCTIONS[age_group]}

{STRUCTURE_RULES}

OUTPUT FORMAT — use EXACTLY this format:

{output_example}"""

    return prompt


# ── Validation ─────────────────────────────────────────────────

def validate_script(script_text: str) -> list[str]:
    """Validate a funny short script. Returns list of errors (empty = valid)."""
    errors = []

    for section in ["[SETUP]", "[BEAT_1]", "[BEAT_2]", "[BEAT_3]", "[BUTTON]"]:
        if section not in script_text:
            errors.append(f"Missing section: {section}")

    if not re.search(r"\[TITLE:\s*(.+?)\]", script_text):
        errors.append("Missing [TITLE: ...]")

    if not re.search(r"\[COVER:\s*(.+?)\]", script_text):
        errors.append("Missing [COVER: ...] tag")

    if not re.search(r"\[PREMISE:\s*(.+?)\]", script_text):
        errors.append("Missing [PREMISE: ...] tag")

    stings = re.findall(r"\[STING:\s*\w+\]", script_text)
    if len(stings) > 8:
        errors.append(f"Too many stings: {len(stings)} (max 8)")

    # Check delivery tag coverage
    tagged_lines = 0
    total_dialogue_lines = 0
    in_section = False
    for line in script_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("[SETUP]") or line.startswith("[BEAT_") or line.startswith("[BUTTON]"):
            in_section = True
            continue
        if line.startswith("[/"):
            in_section = False
            continue
        if in_section and line and re.match(r"^\[(\w+)\]", line):
            total_dialogue_lines += 1
            if re.search(r"\[DELIVERY:", line, re.IGNORECASE):
                tagged_lines += 1
    if total_dialogue_lines > 0 and tagged_lines == 0:
        errors.append("WARNING: No [DELIVERY: ...] tags found — emotional arcs will be flat")
    elif total_dialogue_lines > 0 and tagged_lines < total_dialogue_lines * 0.5:
        errors.append(f"WARNING: Only {tagged_lines}/{total_dialogue_lines} lines have delivery tags")

    return errors


def parse_script_metadata(script_text: str) -> dict:
    """Extract metadata from a script."""
    title_match = re.search(r"\[TITLE:\s*(.+?)\]", script_text)
    age_match = re.search(r"\[AGE:\s*(.+?)\]", script_text)
    voices_match = re.search(r"\[VOICES:\s*(.+?)\]", script_text)
    comedy_match = re.search(r"\[COMEDY_TYPE:\s*(.+?)\]", script_text)
    cover_match = re.search(r"\[COVER:\s*(.+?)\]", script_text)
    premise_match = re.search(r"\[PREMISE:\s*(.+?)\]", script_text)

    CHAR_NAME_TO_VOICE = {
        "mouse": "high_pitch_cartoon",
        "croc": "comedic_villain",
        "sweet": "young_sweet",
        "witch": "mysterious_witch",
        "musical": "musical_original",
    }
    voices = []
    if voices_match:
        for v in voices_match.group(1).split(","):
            v = v.strip().lower()
            voices.append(CHAR_NAME_TO_VOICE.get(v, v))

    return {
        "title": title_match.group(1).strip() if title_match else "Untitled",
        "age_group": age_match.group(1).strip() if age_match else "6-8",
        "voices": voices,
        "comedy_type": comedy_match.group(1).strip() if comedy_match else "unknown",
        "cover_description": cover_match.group(1).strip() if cover_match else "",
        "premise_summary": premise_match.group(1).strip() if premise_match else "",
    }


# ── Generation ─────────────────────────────────────────────────

def generate_script(spec: dict, api_key: str) -> str:
    """Generate a funny short script using Mistral AI from a scheduler spec."""
    prompt = build_funny_short_prompt(spec)

    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {
                "role": "system",
                "content": ("You are a children's comedy writer. You write short, "
                            "punchy comedy scripts for audio production. Output ONLY "
                            "the script in the exact format requested. No explanations, "
                            "no markdown code blocks."),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        max_tokens=1500,
    )

    script = response.choices[0].message.content.strip()
    script = re.sub(r"^```\w*\n?", "", script)
    script = re.sub(r"\n?```$", "", script)
    return script.strip()


def save_script(script_text: str, spec: dict) -> dict:
    """Validate and save a generated script as a funny short JSON file."""
    errors = validate_script(script_text)
    if errors:
        print(f"  Validation warnings: {errors}")

    meta = parse_script_metadata(script_text)

    slug = re.sub(r"[^a-z0-9]+", "-", meta["title"].lower()).strip("-")
    short_id = f"{slug}-{uuid.uuid4().hex[:4]}"

    voices = meta.get("voices", spec["voices"])
    format_type = spec["format"]

    short = {
        "id": short_id,
        "title": meta["title"],
        "age_group": spec["age_group"],
        "comedy_type": spec["comedy_type"],
        "format": format_type,
        "voices": voices,
        "voice_combo": sorted(voices),
        "primary_voice": voices[0] if voices else "",
        "premise_summary": meta.get("premise_summary", ""),
        "cover_description": meta.get("cover_description", ""),
        "cover_file": "",
        "duration_seconds": 0,
        "script": script_text,
        "audio_file": "",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "play_count": 0,
        "replay_count": 0,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{short_id}.json"
    with open(path, "w") as f:
        json.dump(short, f, indent=2)

    print(f"  Saved: {path}")
    return short


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate funny short scripts")
    parser.add_argument("--age", required=True, choices=["2-5", "6-8", "9-12"],
                        help="Target age group")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of scripts to generate")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-select comedy type, format, and voices via scheduler")
    parser.add_argument("--comedy-type", choices=COMEDY_TYPES, default=None,
                        help="Specific comedy type (used with manual mode)")
    parser.add_argument("--format", choices=["solo", "duo", "trio"], default=None,
                        dest="format_type",
                        help="Specific format (used with manual mode)")
    parser.add_argument("--voices", default=None,
                        help="Comma-separated voice IDs (used with manual mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print script without saving")
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set")
        sys.exit(1)

    existing = load_all_shorts()

    for i in range(args.count):
        print(f"\n{'='*60}")
        print(f"Generating funny short {i+1}/{args.count} for ages {args.age}...")
        print(f"{'='*60}")

        if args.auto:
            spec = select_with_recency(existing, args.age)
            char_names = [VOICE_DISPLAY_NAMES.get(v, v) for v in spec["voices"]]
            print(f"\n[AUTO-SELECT] Age {args.age}")
            print(f"  Comedy type: {spec['comedy_type']}")
            print(f"  Format: {spec['format']}")
            print(f"  Voices: {' + '.join(char_names)}")
        else:
            # Manual mode: build spec from args or defaults
            voices = []
            if args.voices:
                voices = [v.strip() for v in args.voices.split(",")]
            elif args.format_type == "solo":
                voices = [VOICE_AGE_VALID[args.age][0]]
            else:
                voices = VOICE_AGE_VALID[args.age][:2]

            format_type = args.format_type
            if not format_type:
                format_type = {1: "solo", 2: "duo", 3: "trio"}.get(len(voices), "duo")

            comedy_type = args.comedy_type
            if not comedy_type:
                import random
                comedy_type = random.choice(COMEDY_AGE_VALID[args.age])

            spec = {
                "comedy_type": comedy_type,
                "format": format_type,
                "voices": voices,
                "age_group": args.age,
            }

        print(f"  Generating...")
        script = generate_script(spec, api_key)
        print(f"\n{script}\n")

        errors = validate_script(script)
        if errors:
            print(f"Validation issues: {errors}")

        if not args.dry_run:
            short = save_script(script, spec)
            print(f"ID: {short['id']}")
            print(f"Title: {short['title']}")
            print(f"Format: {short['format']}")
            print(f"Comedy: {short['comedy_type']}")
            print(f"Voices: {short['voices']}")
            if short['premise_summary']:
                print(f"Premise: {short['premise_summary']}")

            # Add to existing for subsequent iterations in this batch
            existing.append(short)
        else:
            print("(dry run — not saved)")


if __name__ == "__main__":
    main()
