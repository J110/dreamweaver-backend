#!/usr/bin/env python3
"""Pre-publish validator for Hindi short stories.

Enforces the narrative-craft checklist in docs/HINDI_SHORT_STORY_GUIDELINES.md
so the issues that have shipped before cannot ship again.

Usage:
    # Validate a STORY dict before publishing:
    from scripts.validate_hindi_story import validate_story_dict
    issues = validate_story_dict(STORY)
    if issues:
        for i in issues: print(f"  ❌ {i}")
        sys.exit(1)

    # Validate a content.json entry after upsert:
    python3 scripts/validate_hindi_story.py <entry_id>

Checks (mirror the guideline sections):
    §1  Dual-script: title/text/hook have both _roman and _deva forms,
        line-counts match.
    §2  `text` field has zero [ brackets, `raw_text` preserved.
    §4  Story-type signature opening heuristic.
    §5  ≥2 clean direct addresses to the child.
    §6  Character is a dict with rich identity; no generic species-only
        descriptors detected in the opening.
    §7  characterType is canonical 11.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

CANONICAL_CHARACTER_TYPES = {
    "human_child", "land_mammal", "reptile_amphibian", "bird",
    "sea_creature", "insect", "mythical_creature", "object_alive",
    "plant_tree", "celestial_weather", "robot_mechanical",
}

# §4 — opening signatures.
LOK_OPENERS = [r"^\s*Suno na bachcho", r"^\s*सुनो ना बच्चो",
               r"^\s*Ek baar ki baat hai", r"^\s*एक बार की बात है"]
SENSORY_OPENERS = [
    r"^\s*Shaam thi", r"^\s*Subah", r"^\s*Raat thi",
    r"^\s*Hawa ", r"^\s*Baarish ",
    r"^\s*शाम थी", r"^\s*सुबह", r"^\s*रात थी",
    r"^\s*हवा ", r"^\s*बारिश ",
    # Generic: opens with environment/temperature/sound word.
    r"^\s*(Thandi|Garam|Dheere|Tez|Chhoti|Badi|Neela|Peela)\s",
]

DIRECT_ADDRESS_PATTERNS = [
    r"\bTumne kabhi\b",
    r"\bTumhe pata hai\b",
    r"\bSuno na bachcho\b",
    r"\bSuno zara\b",
    r"\bSocho zara\b",
    # Devanagari equivalents
    r"तुमने कभी",
    r"तुम्हें पता है",
    r"सुनो ना बच्चो",
    r"सुनो ज़रा",
    r"सोचो ज़रा",
]

# Ambiguous — must NOT be the only direct address.
AMBIGUOUS_ADDRESSES = [
    r"\bArre,? yeh kya\b", r"अरे,? यह क्या",
]

GENERIC_CHARACTER_MARKERS = [
    # These describe the species, not the individual.
    r"choti choti aankhein",
    r"bhuri si dumm",
    r"छोटी छोटी आँखें",
    r"भूरी सी दुम",
]


def validate_story_dict(story: dict) -> list[str]:
    """Validate a pre-publish STORY dict (with _roman / _deva fields).

    Returns a list of issue strings. Empty list = passes.
    """
    issues = []

    # §1 — dual-script presence.
    for pair in [("title_roman", "title_deva"),
                 ("text_roman",  "text_deva"),
                 ("hook_roman",  "hook_deva")]:
        r, d = pair
        if not story.get(r):
            issues.append(f"§1 missing field: {r}")
        if not story.get(d):
            issues.append(f"§1 missing field: {d}")

    # §1 — line-count parity for text.
    tr = story.get("text_roman", "")
    td = story.get("text_deva", "")
    if tr and td:
        rp = tr.count("\n\n")
        dp = td.count("\n\n")
        if rp != dp:
            issues.append(
                f"§1 text_roman/text_deva paragraph breaks differ "
                f"(roman={rp} deva={dp}) — must be 1-to-1 line-matched."
            )

    # §1 — Devanagari field should actually contain Devanagari.
    if td and not re.search(r"[\u0900-\u097F]", td):
        issues.append("§1 text_deva contains no Devanagari characters.")
    # Roman field should NOT contain Devanagari.
    if tr and re.search(r"[\u0900-\u097F]", tr):
        issues.append("§1 text_roman contains Devanagari characters "
                      "(must be Roman transliteration).")

    # §4 — story-type signature.
    story_type = story.get("story_type", "")
    opening = (tr or "").split("\n\n", 1)[0]
    if story_type == "prakriti_katha":
        if any(re.match(p, opening) for p in LOK_OPENERS):
            issues.append(
                f"§4 prakriti_katha opener uses lok-katha framing. "
                f"Must open with a sensory image (sound, smell, "
                f"temperature, weather, light)."
            )
        elif not any(re.match(p, opening, re.IGNORECASE) for p in SENSORY_OPENERS):
            issues.append(
                f"§4 prakriti_katha opener doesn't match a sensory "
                f"signature. Opening: {opening[:80]!r}"
            )
    elif story_type == "lok_katha":
        if not any(re.match(p, opening) for p in LOK_OPENERS):
            issues.append(
                f"§4 lok_katha opener lacks village/storyteller "
                f"framing ('Suno na bachcho' / 'Ek baar ki baat hai')."
            )

    # §5 — direct addresses.
    clean_hits = sum(len(re.findall(p, tr, re.IGNORECASE))
                     for p in DIRECT_ADDRESS_PATTERNS)
    amb_hits = sum(len(re.findall(p, tr, re.IGNORECASE))
                   for p in AMBIGUOUS_ADDRESSES)
    if clean_hits < 2:
        issues.append(
            f"§5 only {clean_hits} clean direct address(es) to the "
            f"child (spec: 2-3). Ambiguous: {amb_hits}. Add one like "
            f"'Tumne kabhi ___?' or 'Tumhe pata hai ___?'."
        )
    elif clean_hits > 4:
        issues.append(
            f"§5 {clean_hits} direct addresses is too many (spec: "
            f"2-3). Trim to avoid feeling preachy."
        )

    # §6 — character shape + specificity.
    ch = story.get("character")
    if not isinstance(ch, dict):
        issues.append("§6 `character` must be a dict "
                      "(name/identity/special/personality_tags).")
    else:
        for k in ("name", "identity"):
            if not ch.get(k):
                issues.append(f"§6 character.{k} missing/empty.")
        if ch.get("identity") and len(ch["identity"]) < 40:
            issues.append(
                f"§6 character.identity is too thin "
                f"({len(ch['identity'])} chars). FLUX needs a rich "
                f"English descriptor with species + visual details."
            )
    # Generic-descriptor detection in the opening.
    opening_block = "\n\n".join((tr or "").split("\n\n")[:2])
    hit_generic = [m for m in GENERIC_CHARACTER_MARKERS
                   if re.search(m, opening_block, re.IGNORECASE)]
    if hit_generic:
        issues.append(
            f"§6 generic species-level descriptor in opening: "
            f"{hit_generic}. Replace with one specific Chiki-only "
            f"detail (a habit, preference, or place)."
        )

    # §7 — canonical characterType.
    ct = (story.get("lead_character_type_canonical")
          or story.get("characterType")
          or story.get("lead_character_type"))
    if ct and ct not in CANONICAL_CHARACTER_TYPES:
        issues.append(
            f"§7 characterType {ct!r} not in canonical 11. Use one "
            f"of: {sorted(CANONICAL_CHARACTER_TYPES)}."
        )

    return issues


def validate_content_entry(entry: dict) -> list[str]:
    """Validate a content.json entry (post-upsert).

    Checks §2 (clean text, raw_text preserved) and §7 (canonical type).
    """
    issues = []
    t = entry.get("text", "") or ""
    if "[" in t:
        # Find the first tag-like substring for a useful error.
        m = re.search(r"\[[A-Za-z_][A-Za-z0-9_:. ]*\]", t)
        issues.append(
            f"§2 `text` contains tag-like bracket: "
            f"{m.group(0) if m else '[...]'}. Run through "
            f"clean_lyrics_text(); keep tagged source in raw_text."
        )
    if entry.get("lang") == "hi" and entry.get("type") == "story":
        if not entry.get("raw_text") and not entry.get("raw_text_deva"):
            issues.append(
                "§2 Hindi story entry has no raw_text/raw_text_deva. "
                "Audio pipeline consumes raw_text_deva."
            )
        if not isinstance(entry.get("character"), dict):
            issues.append(
                "§6 entry.character is not a dict. Must be "
                "{name, identity, special, personality_tags}."
            )
    ct = entry.get("characterType") or entry.get("lead_character_type")
    if ct and ct not in CANONICAL_CHARACTER_TYPES:
        issues.append(f"§7 entry.characterType {ct!r} not in canonical 11.")
    return issues


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("entry_id", nargs="?",
                    help="Validate a specific content.json entry by id.")
    ap.add_argument("--all-hindi", action="store_true",
                    help="Validate every Hindi entry in content.json.")
    args = ap.parse_args()

    path = BASE_DIR / "seed_output" / "content.json"
    with open(path) as f:
        data = json.load(f)
    items = data["items"] if isinstance(data, dict) else data

    targets = []
    if args.entry_id:
        targets = [i for i in items if i.get("id") == args.entry_id]
        if not targets:
            print(f"  ❌ id {args.entry_id!r} not found", file=sys.stderr)
            sys.exit(2)
    elif args.all_hindi:
        targets = [i for i in items if i.get("lang") == "hi"
                   and i.get("type") == "story"]
    else:
        ap.print_help()
        sys.exit(0)

    any_failed = False
    for entry in targets:
        issues = validate_content_entry(entry)
        status = "✅" if not issues else "❌"
        print(f"  {status} {entry.get('id')}  [{entry.get('story_type','?')}, "
              f"{entry.get('age_group','?')}]")
        for i in issues:
            print(f"      - {i}")
        if issues:
            any_failed = True

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
