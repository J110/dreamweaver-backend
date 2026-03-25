#!/usr/bin/env python3
"""Generate funny short scripts for the Before Bed tab.

Usage:
    python3 scripts/generate_funny_short.py --age 6-8
    python3 scripts/generate_funny_short.py --age 2-5 --count 3
    python3 scripts/generate_funny_short.py --age 9-12 --comedy-type villain_fails
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mistralai import Mistral

# ── Constants ──────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "funny_shorts"

COMEDY_TYPES = [
    "physical_escalation",
    "villain_fails",
    "misunderstanding",
    "sound_effect_comedy",
    "ominous_mundane",
    "sarcastic_commentary",
]

AVAILABLE_CHARACTERS = {
    "2-5": """- MOUSE: Squeaky Minnie Mouse energy. Reacts with alarm and panic. Short sentences.
- CROC: Deep dramatic villain. Non-human crocodile voice. Self-important, always failing.
- MUSICAL: Rhythmic, poetic. For funny poems and nonsense verse only.
Max 2 characters per short for this age.""",
    "6-8": """- MOUSE: Squeaky cartoon. Reacts with alarm and confusion.
- CROC: Dramatic villain crocodile. Self-important, always failing.
- SWEET: Innocent-sounding but sarcastic. Deadpan. Unbothered.
- WITCH: Dark, low, mysterious. Makes everything a dark prophecy.
- MUSICAL: Rhythmic, poetic. For verse comedy.
2-3 characters per short. Multi-voice scenes work best at this age.""",
    "9-12": """- CROC: Dramatic villain crocodile. Self-important, always failing.
- SWEET: Sarcastic. Master of understatement. The less she reacts, the funnier.
- WITCH: Dark, mysterious. Makes mundane things ominous. The dramatic narrator.
- MUSICAL: Rhythmic, poetic. For verse comedy.
2-3 characters. Dry humor. Never try to be funny — restraint IS the comedy.""",
}

AGE_COMEDY_INSTRUCTIONS = {
    "2-5": """Ages 2-5: Physical + Sound Comedy
- Short sentences (5-10 words). Onomatopoeia. Repetition. Silly names.
- Max 2 characters per short.
- Comedy types: Physical Escalation, Sound Effect, Villain Fails.
- Make it SILLY. Exaggerate reactions. Use funny sounds.
- Repetition IS the joke for this age. Same structure three times, bigger each time.""",
    "6-8": """Ages 6-8: Absurdity + Character Comedy
- Medium sentences. Character dynamics are the comedy engine.
- Croc's ego vs Mouse's innocence, Witch's drama vs Sweet's sarcasm.
- All six comedy types work at this age.
- Multi-voice dialogue scenes are the sweet spot.
- Kids this age love clever word misunderstandings and dramatic irony.""",
    "9-12": """Ages 9-12: Deadpan + Meta Comedy
- Longer sentences. Dry tone. Humor through understatement.
- NEVER try to be funny. The restraint IS the comedy.
- Comedy types: Ominous Mundane, Sarcastic Commentary, Villain Fails.
- Sweet's sarcasm and Witch's deadpan drama work best.
- Trust the audience to get the joke — don't explain it.""",
}

AVAILABLE_STINGS = """buildup_short, buildup_long, tiny, medium_hit, big_crash,
silence, deflation, victory, splat, boing, whoosh, tiptoe, run, slide_whistle,
villain_entrance, villain_fail, villain_dramatic, witch_ominous, witch_reveal,
witch_dramatic, mouse_squeak, mouse_panic, mouse_surprise, sweet_eyeroll,
sweet_pause, musical_flourish, musical_detuned"""

FUNNY_SHORT_PROMPT = """Write a 60-90 second funny short for children aged {age_group}.

CHARACTERS AVAILABLE for this age group:
{available_characters}

Choose 1-3 characters. Tag EVERY sentence with the speaking character.

STRUCTURE (mandatory):
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
7. Each character sounds distinct: Mouse = alarm/panic, Croc = self-importance,
   Sweet = deadpan sarcasm, Witch = ominous drama.
8. No sleep language. Pure comedy.

Available stings: {available_stings}

COMEDY STYLE for {age_group}:
{age_comedy_instructions}

{comedy_type_instruction}

COVER DESCRIPTION:
After the script, add a [COVER: ...] tag with a one-sentence visual scene description
for the cover illustration. Describe the PUNCHLINE moment, NOT the setup. Show the
funniest single frame — the moment of maximum absurdity.

Examples:
- "The Crocodile Who Was Definitely a Rock" → [COVER: A crocodile lying perfectly flat with closed eyes trying to look like a rock while a tiny mouse stands on top of him staring down with confusion]
- "The Bear Who Sneezed" → [COVER: A bear mid-sneeze with trees bending sideways and forest animals flying through the air]

PREMISE SUMMARY:
After the cover tag, add a [PREMISE: ...] tag with a short (5-10 word) summary of the
core premise. Example: [PREMISE: crocodile pretends to be a rock]

OUTPUT FORMAT — use EXACTLY this format:
[TITLE: Your Title Here]
[AGE: {age_group}]
[VOICES: voice_id_1, voice_id_2]
[COMEDY_TYPE: {comedy_type}]

[SETUP]
[CHARACTER] Sentence text. [STING: type]
[CHARACTER] Another sentence.
[/SETUP]

[BEAT_1]
[CHARACTER] Sentence text.
[/BEAT_1]

[BEAT_2]
[CHARACTER] Sentence text.
[/BEAT_2]

[BEAT_3]
[CHARACTER] Sentence text. [STING: type]
[/BEAT_3]

[BUTTON]
[CHARACTER] [PUNCHLINE]Final punchline sentence.[/PUNCHLINE] [STING: type]
[/BUTTON]

[COVER: One-sentence visual description of the funniest punchline moment]
[PREMISE: 5-10 word premise summary]
"""

CHARACTER_TO_VOICE = {
    "MOUSE": "high_pitch_cartoon",
    "CROC": "comedic_villain",
    "SWEET": "young_sweet",
    "WITCH": "mysterious_witch",
    "MUSICAL": "musical_original",
}


# ── Diversity Checks ─────────────────────────────────────────

def load_recent_shorts(days: int = 14) -> list[dict]:
    """Load shorts created within the last N days."""
    if not DATA_DIR.exists():
        return []

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    shorts = []
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                short = json.load(fh)
                if short.get("created_at", "") >= cutoff:
                    shorts.append(short)
        except Exception:
            continue

    # Sort by created_at ascending (oldest first)
    shorts.sort(key=lambda s: s.get("created_at", ""))
    return shorts


def check_diversity(age_group: str, comedy_type: str, voices: list[str]) -> list[str]:
    """Check proposed short against recent history. Returns warnings (not blockers)."""
    warnings = []
    recent = load_recent_shorts(days=14)

    if not recent:
        return warnings

    # Check 1: no same comedy_type in last 3 shorts for this age group
    recent_types = [s["comedy_type"] for s in recent if s.get("age_group") == age_group]
    if comedy_type in recent_types[-3:]:
        warnings.append(f"DIVERSITY: {comedy_type} used in last 3 shorts for {age_group}")

    # Check 2: no same voice combo in last 3 shorts
    recent_combos = [tuple(sorted(s.get("voice_combo", s.get("voices", [])))) for s in recent]
    proposed_combo = tuple(sorted(voices))
    if proposed_combo in recent_combos[-3:]:
        warnings.append(f"DIVERSITY: same voice combo {list(proposed_combo)} in last 3 shorts")

    # Check 3: no same primary character in last 2 shorts for this age group
    recent_leads = []
    for s in recent:
        vc = s.get("voice_combo", s.get("voices", []))
        if vc and s.get("age_group") == age_group:
            recent_leads.append(vc[0])
    if voices and voices[0] in recent_leads[-2:]:
        warnings.append(f"DIVERSITY: {voices[0]} was lead in last 2 shorts for {age_group}")

    return warnings


# ── Validation ─────────────────────────────────────────────────

def validate_script(script_text: str) -> list[str]:
    """Validate a funny short script. Returns list of errors (empty = valid)."""
    errors = []

    # Check required sections
    for section in ["[SETUP]", "[BEAT_1]", "[BEAT_2]", "[BEAT_3]", "[BUTTON]"]:
        if section not in script_text:
            errors.append(f"Missing section: {section}")

    # Check title
    title_match = re.search(r"\[TITLE:\s*(.+?)\]", script_text)
    if not title_match:
        errors.append("Missing [TITLE: ...]")

    # Check cover description
    cover_match = re.search(r"\[COVER:\s*(.+?)\]", script_text)
    if not cover_match:
        errors.append("Missing [COVER: ...] tag")

    # Check premise summary
    premise_match = re.search(r"\[PREMISE:\s*(.+?)\]", script_text)
    if not premise_match:
        errors.append("Missing [PREMISE: ...] tag")

    # Count stings
    stings = re.findall(r"\[STING:\s*\w+\]", script_text)
    if len(stings) > 8:
        errors.append(f"Too many stings: {len(stings)} (max 8)")

    # Check every content line has a character tag
    in_section = False
    for line in script_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("[SETUP]") or line.startswith("[BEAT_") or line.startswith("[BUTTON]"):
            in_section = True
            continue
        if line.startswith("[/"):
            in_section = False
            continue
        if in_section and line and not line.startswith("["):
            errors.append(f"Untagged line: {line[:50]}...")

    # Check voices
    voices_match = re.search(r"\[VOICES:\s*(.+?)\]", script_text)
    if voices_match:
        voices = [v.strip() for v in voices_match.group(1).split(",")]
        if len(voices) > 3:
            errors.append(f"Too many voices: {len(voices)} (max 3)")

    return errors


def parse_script_metadata(script_text: str) -> dict:
    """Extract metadata from a script."""
    title_match = re.search(r"\[TITLE:\s*(.+?)\]", script_text)
    age_match = re.search(r"\[AGE:\s*(.+?)\]", script_text)
    voices_match = re.search(r"\[VOICES:\s*(.+?)\]", script_text)
    comedy_match = re.search(r"\[COMEDY_TYPE:\s*(.+?)\]", script_text)
    cover_match = re.search(r"\[COVER:\s*(.+?)\]", script_text)
    premise_match = re.search(r"\[PREMISE:\s*(.+?)\]", script_text)

    voices = []
    if voices_match:
        voices = [v.strip() for v in voices_match.group(1).split(",")]

    return {
        "title": title_match.group(1).strip() if title_match else "Untitled",
        "age_group": age_match.group(1).strip() if age_match else "6-8",
        "voices": voices,
        "comedy_type": comedy_match.group(1).strip() if comedy_match else "unknown",
        "cover_description": cover_match.group(1).strip() if cover_match else "",
        "premise_summary": premise_match.group(1).strip() if premise_match else "",
    }


# ── Generation ─────────────────────────────────────────────────

def generate_script(age_group: str, comedy_type: str = None, api_key: str = None) -> str:
    """Generate a funny short script using Mistral AI."""
    if not api_key:
        api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY not set")

    if not comedy_type:
        import random
        # Weight comedy types by age appropriateness
        if age_group == "2-5":
            comedy_type = random.choice([
                "physical_escalation", "villain_fails", "sound_effect_comedy",
                "physical_escalation", "sound_effect_comedy",  # weighted
            ])
        elif age_group == "9-12":
            comedy_type = random.choice([
                "ominous_mundane", "sarcastic_commentary", "villain_fails",
                "ominous_mundane", "sarcastic_commentary",  # weighted
            ])
        else:
            comedy_type = random.choice(COMEDY_TYPES)

    comedy_type_instruction = f"Comedy type to write: {comedy_type.replace('_', ' ').title()}"

    prompt = FUNNY_SHORT_PROMPT.format(
        age_group=age_group,
        available_characters=AVAILABLE_CHARACTERS[age_group],
        available_stings=AVAILABLE_STINGS,
        age_comedy_instructions=AGE_COMEDY_INSTRUCTIONS[age_group],
        comedy_type=comedy_type,
        comedy_type_instruction=comedy_type_instruction,
    )

    client = Mistral(api_key=api_key)
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {
                "role": "system",
                "content": "You are a children's comedy writer. You write short, punchy comedy scripts for audio production. Output ONLY the script in the exact format requested. No explanations, no markdown code blocks.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        max_tokens=1500,
    )

    script = response.choices[0].message.content.strip()
    # Strip markdown code blocks if present
    script = re.sub(r"^```\w*\n?", "", script)
    script = re.sub(r"\n?```$", "", script)
    return script.strip()


def save_script(script_text: str, age_group: str) -> dict:
    """Validate and save a generated script as a funny short JSON file."""
    errors = validate_script(script_text)
    if errors:
        print(f"  Validation warnings: {errors}")

    meta = parse_script_metadata(script_text)

    # Generate slug-based ID
    slug = re.sub(r"[^a-z0-9]+", "-", meta["title"].lower()).strip("-")
    short_id = f"{slug}-{uuid.uuid4().hex[:4]}"

    short = {
        "id": short_id,
        "title": meta["title"],
        "age_group": meta.get("age_group", age_group),
        "comedy_type": meta.get("comedy_type", "unknown"),
        "voices": meta.get("voices", []),
        "voice_combo": meta.get("voices", []),
        "premise_summary": meta.get("premise_summary", ""),
        "cover_description": meta.get("cover_description", ""),
        "cover_file": "",  # Set after cover generation
        "duration_seconds": 0,  # Set after audio generation
        "script": script_text,
        "audio_file": "",  # Set after audio generation
        "created_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "play_count": 0,
        "replay_count": 0,
    }

    # Run diversity checks
    diversity_warnings = check_diversity(
        age_group, short["comedy_type"], short["voices"]
    )
    for w in diversity_warnings:
        print(f"  {w}")

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
    parser.add_argument("--comedy-type", choices=COMEDY_TYPES, default=None,
                        help="Specific comedy type (random if not set)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print script without saving")
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set")
        sys.exit(1)

    for i in range(args.count):
        print(f"\n{'='*60}")
        print(f"Generating funny short {i+1}/{args.count} for ages {args.age}...")
        print(f"{'='*60}")

        script = generate_script(args.age, args.comedy_type, api_key)
        print(f"\n{script}\n")

        errors = validate_script(script)
        if errors:
            print(f"Validation issues: {errors}")

        if not args.dry_run:
            short = save_script(script, args.age)
            print(f"ID: {short['id']}")
            print(f"Title: {short['title']}")
            print(f"Voices: {short['voices']}")
            if short['premise_summary']:
                print(f"Premise: {short['premise_summary']}")
            if short['cover_description']:
                print(f"Cover: {short['cover_description'][:80]}...")
        else:
            print("(dry run — not saved)")


if __name__ == "__main__":
    main()
