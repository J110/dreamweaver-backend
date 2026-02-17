#!/usr/bin/env python3
"""
Regenerate Hindi content for gen-* stories using Mistral API.

Fixes:
- Missing commas/punctuation for natural TTS pauses
- Excessive English words (should be pure Hindi)
- Weak/forced rhyming in poems
- Spelling errors in Devanagari
- Flat content for older age groups

Usage:
    python3 scripts/regenerate_hindi.py                  # Regenerate all 12 Hindi gen-* stories
    python3 scripts/regenerate_hindi.py --id gen-xxx     # Regenerate a specific story
    python3 scripts/regenerate_hindi.py --dry-run        # Show what would be regenerated
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from mistralai import Mistral
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-large-latest"

CONTENT_JSON = BASE_DIR / "seed_output" / "content.json"
SEED_DATA_JS = BASE_DIR.parent / "dreamweaver-web" / "src" / "utils" / "seedData.js"

# ── Emotion markers (kept for TTS, stripped from display) ──
EMOTION_MARKERS = [
    "[GENTLE]", "[CALM]", "[CURIOUS]", "[ADVENTUROUS]", "[MYSTERIOUS]",
    "[JOYFUL]", "[DRAMATIC]", "[WHISPERING]", "[SLEEPY]", "[EXCITED]",
    "[DRAMATIC_PAUSE]", "[RHYTHMIC]", "[SINGING]", "[HUMMING]", "[PAUSE]",
    "[laugh]", "[chuckle]",
]


def clean_markers(text):
    """Remove emotion markers for word counting."""
    clean = text
    for m in EMOTION_MARKERS:
        clean = clean.replace(m, "")
    return " ".join(clean.split())


def get_age_label(target_age):
    if target_age <= 1:
        return "0-1"
    if target_age <= 3:
        return "1-3"
    if target_age <= 5:
        return "4-5"
    if target_age <= 8:
        return "6-8"
    if target_age <= 12:
        return "8-12"
    return "12+"


def call_mistral(prompt, max_tokens=4000, temperature=0.7, max_retries=5):
    """Call Mistral API with retry logic."""
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                wait = (attempt + 1) * 10
                print(f"  [rate-limit, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
            else:
                if attempt < max_retries - 1:
                    print(f"  [error: {e}, retrying...]", end="", flush=True)
                    time.sleep(5)
                else:
                    raise
    raise Exception("Max retries exceeded")


def _fix_json_newlines(raw):
    """Fix literal newlines inside JSON string values that break parsing.
    Mistral sometimes outputs multi-line strings inside JSON."""
    # Replace literal newlines inside quoted strings with \\n
    # Strategy: walk through characters, track if we're inside a string
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '\\' and in_string and i + 1 < len(raw):
            # Escaped character — keep as-is
            result.append(ch)
            result.append(raw[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif ch == '\n' and in_string:
            # Replace literal newline inside string with space
            result.append(' ')
        elif ch == '\t' and in_string:
            result.append(' ')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def parse_json_response(text):
    """Parse JSON from LLM response, handling markdown fences and multi-line strings."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract from markdown fence
    extracted = text
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            extracted = match.group(1).strip()

    # Try direct parse
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass

    # Try fixing newlines inside strings
    try:
        fixed = _fix_json_newlines(extracted)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            try:
                fixed = _fix_json_newlines(match.group(0))
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Could not parse JSON from response: {text[:300]}")


def build_hindi_story_prompt(story):
    """Build prompt for regenerating a Hindi story."""
    age_label = get_age_label(story["target_age"])
    content_type = story["type"]
    theme = story["theme"]
    title = story["title"]
    description = story["description"]
    old_text = clean_markers(story.get("text", ""))
    word_count = len(old_text.split())

    # Determine target word count based on age
    if content_type == "story":
        if age_label == "0-1":
            min_w, max_w = 30, 80
        elif age_label == "1-3":
            min_w, max_w = 60, 150
        elif age_label == "4-5":
            min_w, max_w = 150, 350
        elif age_label == "6-8":
            min_w, max_w = 250, 600
        elif age_label == "8-12":
            min_w, max_w = 400, 800
        else:  # 12+
            min_w, max_w = 500, 1000
    else:  # poem
        if age_label == "0-1":
            min_w, max_w = 20, 50
        elif age_label == "1-3":
            min_w, max_w = 30, 80
        elif age_label == "4-5":
            min_w, max_w = 50, 120
        elif age_label == "6-8":
            min_w, max_w = 80, 200
        elif age_label == "8-12":
            min_w, max_w = 100, 300
        else:  # 12+
            min_w, max_w = 150, 400

    age_instructions = {
        "0-1": "Baby (0-1 years): Use extremely simple words, lots of repetition, sound words (onomatopoeia), soothing rhythm. Short sentences of 3-5 words. Very gentle, comforting tone.",
        "1-3": "Toddler (1-3 years): Simple vocabulary, repetitive patterns, familiar objects (animals, food, family). Sentences of 5-8 words. Playful, warm, reassuring.",
        "4-5": "Preschool (4-5 years): Slightly richer vocabulary, simple plot with beginning-middle-end. Named characters. Use of colors, counting, emotions. Engaging and imaginative.",
        "6-8": "Explorer (6-8 years): Developed vocabulary, clear narrative arc, relatable characters with names. Descriptive language, some suspense, moral lessons woven naturally. Vivid imagery.",
        "8-12": "Adventurer (8-12 years): Rich vocabulary, complex plots with subplots. Well-developed characters, themes of courage, friendship, discovery. Literary devices like metaphor and simile.",
        "12+": "Teen (12+): Sophisticated vocabulary, nuanced themes (identity, purpose, dreams). Literary Hindi with Urdu/Persian-origin words where natural. Layered storytelling, philosophical depth, emotional complexity.",
    }

    poem_extra = ""
    if content_type == "poem":
        poem_extra = """
POEM-SPECIFIC RULES:
- Use diverse rhyme schemes: AABB, ABAB, ABCB — DO NOT use the same ending word twice (no self-rhyming)
- Each stanza should have 4 lines
- Rhyming should feel natural, not forced — choose different rhyming pairs for each stanza
- Use Hindi poetic traditions: doha, chaupai, or geet style as appropriate for the age
- Rhythm (chhanda) matters — lines in each stanza should have similar syllable counts
- ZERO English words in poems — all vocabulary must be pure Hindi/Sanskrit/Urdu
"""

    prompt = f"""You are an expert Hindi children's literature author. Rewrite the following {content_type} in HIGH-QUALITY Hindi.

ORIGINAL TITLE: {title}
DESCRIPTION: {description}
THEME: {theme}
AGE GROUP: {age_label}
TYPE: {content_type}

{age_instructions.get(age_label, "")}

CURRENT TEXT (needs improvement):
{old_text}

CRITICAL HINDI QUALITY RULES:
1. PURE HINDI VOCABULARY: Use शुद्ध हिंदी (pure Hindi). Maximum 2-3 very common English words per paragraph for stories (like "school", "phone"). For poems, use ZERO English words.
2. MANDATORY PUNCTUATION FOR TTS: Insert commas (,) between every clause and phrase. TTS systems need commas to pause naturally.
   - GOOD: "चाँद निकला, तारे चमके, रात सुनहरी आई।"
   - BAD: "चाँद निकला तारे चमके रात सुनहरी आई।"
3. CORRECT DEVANAGARI SPELLING: Double-check all spellings. Common mistakes to avoid:
   - कई (correct) NOT काई
   - बहुत (correct) NOT बोहोत
   - ज़रूरी (correct) NOT जरूरी
4. NATURAL FLOW: Sentences should flow like spoken Hindi. Read each sentence aloud mentally — would a Hindi-speaking parent naturally read it this way?
5. AGE-APPROPRIATE COMPLEXITY: Match vocabulary and sentence structure to the age group.
6. EMOTIONAL MARKERS: Include TTS emotion markers in square brackets before relevant sections: [GENTLE], [CALM], [JOYFUL], [PAUSE], [WHISPERING], [SLEEPY], [RHYTHMIC], [CURIOUS], [EXCITED], [ADVENTUROUS], [MYSTERIOUS], [DRAMATIC_PAUSE]
{poem_extra}
TARGET WORD COUNT: Between {min_w} and {max_w} words (Devanagari text, not counting markers).

Respond with ONLY a JSON object:
{{
    "title": "Title in Romanized Hindi (Latin letters)",
    "description": "1-2 sentence description in Romanized Hindi",
    "text": "Full text in informal Romanized Hindi with emotion markers. Example: [GENTLE] Ek chhota sa tara, aasmaan mein chamka, uski roshni, bahut pyaari thi.",
    "text_devanagari": "SAME text in Devanagari script with emotion markers. Example: [GENTLE] एक छोटा सा तारा, आसमान में चमका, उसकी रोशनी, बहुत प्यारी थी।",
    "morals": ["Moral 1 in Romanized Hindi", "Moral 2 in Romanized Hindi"]
}}"""

    return prompt


def qa_score_hindi(text_devanagari, content_type, age_label):
    """Quick QA scoring of generated Hindi content."""
    clean_text = clean_markers(text_devanagari)

    prompt = f"""Score this Hindi {content_type} for children aged {age_label}. Be critical.

TEXT:
{clean_text}

Score each dimension 1-10:
- hindi_purity: How pure is the Hindi? (10 = all Hindi, 1 = lots of English)
- punctuation: Are there commas between clauses for natural reading? (10 = excellent pauses, 1 = no commas)
- rhyme_quality: (poems only) Are rhymes diverse and natural? (10 = beautiful, 1 = forced/repetitive). For stories, score 7.
- age_fit: Is vocabulary appropriate for age {age_label}? (10 = perfect, 1 = way off)
- emotional_warmth: Does it feel warm and bedtime-appropriate? (10 = very soothing, 1 = cold)
- spelling: Is Devanagari spelling correct? (10 = perfect, 1 = many errors)

Respond ONLY with JSON:
{{"hindi_purity": <int>, "punctuation": <int>, "rhyme_quality": <int>, "age_fit": <int>, "emotional_warmth": <int>, "spelling": <int>}}"""

    raw = call_mistral(prompt, max_tokens=200, temperature=0.1)
    return parse_json_response(raw)


def regenerate_story(story, attempt=1):
    """Regenerate one Hindi story, return updated fields."""
    print(f"  Generating variant {attempt}...", end="", flush=True)
    prompt = build_hindi_story_prompt(story)
    raw = call_mistral(prompt, max_tokens=4000, temperature=0.75)
    result = parse_json_response(raw)

    # Validate required fields
    for field in ["text", "text_devanagari", "title", "description"]:
        if not result.get(field):
            raise ValueError(f"Missing field: {field}")

    # QA score
    age_label = get_age_label(story["target_age"])
    scores = qa_score_hindi(result["text_devanagari"], story["type"], age_label)
    avg = sum(scores.values()) / len(scores)
    print(f" QA avg={avg:.1f} (purity={scores['hindi_purity']}, punct={scores['punctuation']}, rhyme={scores['rhyme_quality']})")

    return {
        "result": result,
        "scores": scores,
        "avg": avg,
    }


def update_seed_data_js(story_id, new_text_devanagari):
    """Update the text field for a story in seedData.js."""
    if not SEED_DATA_JS.exists():
        print(f"  WARNING: seedData.js not found at {SEED_DATA_JS}")
        return False

    content = SEED_DATA_JS.read_text(encoding="utf-8")

    # Find the story block and update its text field
    # Pattern: find the story by ID, then find its text field
    # The seedData structure has: id: "gen-xxx", ... text: "...", ...
    escaped_id = re.escape(story_id)

    # Match from the ID to the next story entry or end of array
    # We need to find text: "..." within the block for this story
    pattern = rf'(id:\s*"{escaped_id}".*?text:\s*)"((?:[^"\\]|\\.)*)(")'

    # Clean the new text of markers for display
    clean_text = new_text_devanagari
    for m in EMOTION_MARKERS:
        clean_text = clean_text.replace(m, "")
    clean_text = " ".join(clean_text.split())

    # Escape for JS string
    js_text = clean_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    match = re.search(pattern, content, re.DOTALL)
    if match:
        new_content = content[:match.start()] + match.group(1) + '"' + js_text + '"' + content[match.end():]
        SEED_DATA_JS.write_text(new_content, encoding="utf-8")
        print(f"  Updated seedData.js for {story_id}")
        return True
    else:
        print(f"  WARNING: Could not find text field for {story_id} in seedData.js")
        return False


def run():
    parser = argparse.ArgumentParser(description="Regenerate Hindi gen-* content")
    parser.add_argument("--id", help="Regenerate a specific story ID")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--variants", type=int, default=2, help="Number of variants to generate per story (default: 2)")
    args = parser.parse_args()

    # Load content
    with open(CONTENT_JSON, "r", encoding="utf-8") as f:
        all_content = json.load(f)

    # Find Hindi gen-* stories
    hindi_stories = [s for s in all_content if s.get("lang") == "hi" and s["id"].startswith("gen-")]

    if args.id:
        hindi_stories = [s for s in hindi_stories if s["id"] == args.id]
        if not hindi_stories:
            print(f"ERROR: Story ID '{args.id}' not found among Hindi gen-* stories")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  HINDI CONTENT REGENERATION")
    print(f"  Stories to regenerate: {len(hindi_stories)}")
    print(f"  Variants per story: {args.variants}")
    print(f"  API: Mistral ({MODEL})")
    print(f"{'='*60}\n")

    for i, story in enumerate(hindi_stories):
        age_label = get_age_label(story["target_age"])
        print(f"\n[{i+1}/{len(hindi_stories)}] {story['title']} ({story['type']}, age {age_label})")
        print(f"  ID: {story['id']}")
        print(f"  Current text preview: {clean_markers(story.get('text', ''))[:80]}...")

        if args.dry_run:
            continue

        # Generate variants and pick best
        best = None
        for v in range(args.variants):
            try:
                variant = regenerate_story(story, attempt=v+1)
                if best is None or variant["avg"] > best["avg"]:
                    best = variant
                time.sleep(3)  # Rate limit buffer
            except Exception as e:
                print(f"  ERROR variant {v+1}: {e}")

        if best is None:
            print(f"  FAILED — no successful variants")
            continue

        print(f"  BEST variant: avg={best['avg']:.1f}")
        result = best["result"]

        # Update content.json entry
        idx = next(j for j, s in enumerate(all_content) if s["id"] == story["id"])
        all_content[idx]["text"] = result["text"]
        all_content[idx]["annotated_text"] = result["text"]
        all_content[idx]["annotated_text_devanagari"] = result["text_devanagari"]
        all_content[idx]["title"] = result.get("title", story["title"])
        all_content[idx]["description"] = result.get("description", story["description"])
        if result.get("morals"):
            all_content[idx]["morals"] = result["morals"]

        # Update word count
        clean = clean_markers(result["text_devanagari"])
        all_content[idx]["word_count"] = len(clean.split())

        # Update seedData.js
        update_seed_data_js(story["id"], result["text_devanagari"])

        print(f"  New title: {result.get('title', story['title'])}")
        print(f"  New text preview: {clean_markers(result['text_devanagari'])[:100]}...")

    if not args.dry_run:
        # Save content.json
        with open(CONTENT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_content, f, ensure_ascii=False, indent=2)
        print(f"\n\nSaved updated content to {CONTENT_JSON}")
        print(f"NOTE: Audio files need to be regenerated for updated stories!")
        print(f"Run: python3 scripts/generate_new_stories.py")


if __name__ == "__main__":
    run()
