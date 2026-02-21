#!/usr/bin/env python3
"""
Story QA Pipeline — 4-Pass Review (using Groq free tier)
Pass 1: Automated structural checks
Pass 2: Engagement & Emotional Quality (per story)
Pass 3: Content Moderation & Safety
Pass 4: Diversification & Uniqueness (across library)
Final: Decision Matrix
"""

import json
import os
import sys
import time
import re
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

# Load .env from backend root
load_dotenv(Path(__file__).parent.parent / ".env")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"

EMOTION_MARKERS = [
    "[GENTLE]", "[CALM]", "[CURIOUS]", "[ADVENTUROUS]", "[MYSTERIOUS]",
    "[JOYFUL]", "[DRAMATIC]", "[WHISPERING]", "[SLEEPY]", "[EXCITED]",
    "[DRAMATIC_PAUSE]", "[RHYTHMIC]", "[SINGING]", "[HUMMING]", "[PAUSE]",
    "[laugh]", "[chuckle]"
]

# Age-appropriate word count ranges
WORD_COUNT_RANGES = {
    "0-1": (20, 100),
    "2-5": (50, 500),
    "6-8": (200, 900),
    "9-12": (300, 1200),
}


def clean_text(text):
    """Strip emotion markers for clean reading."""
    clean = text
    for marker in EMOTION_MARKERS:
        clean = clean.replace(marker, "")
    return " ".join(clean.split())


def parse_json_response(text):
    """Robustly parse JSON from LLM response."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code blocks
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    # Try to find JSON object in text
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # Last resort: try to find nested JSON
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from response: {text[:200]}")


def call_groq(prompt, max_retries=3):
    """Call Groq API with retry logic for rate limits."""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = (attempt + 1) * 10
                print(f"\n    Rate limited, waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded")


def pass1_automated(story):
    """Pass 1: Automated structural checks."""
    issues = []
    score = 10  # Start at 10, deduct for issues

    # Word count check
    wc = story["word_count"]
    age = story["age_group"]
    min_wc, max_wc = WORD_COUNT_RANGES.get(age, (50, 1000))
    if wc < min_wc:
        issues.append(f"Too short: {wc}w (min {min_wc} for age {age})")
        score -= 3
    elif wc > max_wc:
        issues.append(f"Too long: {wc}w (max {max_wc} for age {age})")
        score -= 2

    # Missing fields
    if not story.get("description"):
        issues.append("Missing description")
        score -= 2
    if not story.get("morals"):
        issues.append("Missing morals")
        score -= 1
    if not story.get("categories"):
        issues.append("Missing categories")
        score -= 1

    # Emotion markers
    marker_count = sum(1 for m in EMOTION_MARKERS if m in story.get("text", ""))
    if marker_count == 0:
        issues.append("No emotion markers")
        score -= 3
    elif marker_count < 3:
        issues.append(f"Only {marker_count} emotion markers (weak TTS guidance)")
        score -= 1

    # Hindi script check
    if story["lang"] == "hi":
        text = story["text"]
        has_devanagari = any('\u0900' <= c <= '\u097F' for c in text)
        if not has_devanagari:
            issues.append("Hindi text is Romanized (needs Devanagari for TTS)")
            score -= 2

    # Title quality
    if len(story.get("title", "")) < 5:
        issues.append("Title too short")
        score -= 1

    return {
        "structural_score": max(0, score),
        "issues": issues,
        "pass": score >= 7
    }


def pass2_engagement(story):
    """Pass 2: Engagement & Emotional Quality scoring via Groq."""
    text = clean_text(story["text"])

    lang_note = ""
    if story["lang"] == "hi":
        lang_note = "This story is in Hindi (Romanized). Evaluate it as a Hindi-language story for Indian children."

    prompt = f"""You are a children's literature expert and child psychologist. Evaluate this bedtime story for children aged {story['age_group']} years.

TITLE: {story['title']}
LANGUAGE: {story['lang'].upper()}
AGE: {story['age_group']} years
THEME: {story['theme']}
TYPE: {story['type']}
{lang_note}

TEXT:
{text}

Score 1-10 on each. Be honest — 7 = genuinely good, 10 = exceptional.

1. MAGIC (1-10): Wonder and imagination? Moments of "whoa"? For babies (0-1), sensory wonder counts.
2. CUDDLE (1-10): Warm, safe, comforting? Makes child feel sleepy and loved?
3. CHARACTERS (1-10): Memorable, named, relatable? Would child want to hear about them again?
4. LISTEN_AGAIN (1-10): Rhythm, repetition, fun sounds, satisfying payoffs that reward re-listening?
5. AGE_FIT (1-10): Vocabulary, complexity, length match age {story['age_group']}?

Respond ONLY with this JSON (no other text):
{{"magic": <int>, "cuddle": <int>, "characters": <int>, "listen_again": <int>, "age_fit": <int>, "verdict": "<one sentence>", "fix_suggestion": "<one sentence or None>"}}"""

    raw = call_groq(prompt)
    return parse_json_response(raw)


def pass3_moderation(story):
    """Pass 3: Content Moderation & Safety scoring via Groq."""
    text = clean_text(story["text"])

    prompt = f"""You are a child safety content moderator. Review this bedtime story for children aged {story['age_group']}.

TITLE: {story['title']}
LANGUAGE: {story['lang'].upper()}
AGE: {story['age_group']}
GEOGRAPHY: {story['geography']}

TEXT:
{text}

Check each dimension. Score 1-10 (10 = perfectly safe, 1 = dangerous).

1. VIOLENCE_FREE (1-10): No violence, aggression, harm, death, or scary content? Even mild threat descriptions score lower.
2. AGE_APPROPRIATE (1-10): Language, themes, concepts suitable for {story['age_group']}? No adult themes, innuendo, or complex trauma?
3. CULTURAL_SENSITIVITY (1-10): Respectful of the cultural setting ({story['geography']})? No stereotypes, offensive portrayals, or cultural appropriation?
4. INCLUSIVE_LANGUAGE (1-10): No gender bias, racial bias, ableist language, or exclusionary messaging?
5. EMOTIONAL_SAFETY (1-10): No content that could cause anxiety, nightmares, or fear in a {story['age_group']} child? Endings are reassuring?

Respond ONLY with this JSON (no other text):
{{"violence_free": <int>, "age_appropriate": <int>, "cultural_sensitivity": <int>, "inclusive": <int>, "emotional_safety": <int>, "flags": "<comma-separated list of concerns, or 'None'>", "safe": <true or false>}}"""

    raw = call_groq(prompt)
    return parse_json_response(raw)


def pass4_uniqueness(story, other_stories):
    """Pass 4: Diversification & Uniqueness scoring via Groq."""
    text = clean_text(story["text"])

    others_summary = []
    for s in other_stories:
        if s["id"] == story["id"]:
            continue
        c = clean_text(s["text"])
        others_summary.append(f"- \"{s['title']}\" ({s['theme']}, {s['geography']}): {c[:120]}...")

    others_text = "\n".join(others_summary)

    prompt = f"""You are a children's content curator building a diverse story library for age {story['age_group']}.

STORY TO EVALUATE:
Title: {story['title']}
Theme: {story['theme']}, Geography: {story['geography']}, Lead: {story['lead_gender']}
Text: {text}

OTHER STORIES IN LIBRARY (same age group, same language):
{others_text}

Does this story EARN its spot? Score 1-10:

1. CONCEPT (1-10): Core idea different from others?
2. EMOTIONAL_RANGE (1-10): Adds emotional variety to library?
3. CHARACTER_FRESH (1-10): Character type different from others?
4. WORLD_NOVELTY (1-10): Takes us somewhere new?
5. TONAL_GAP (1-10): Adds new tone (humor, mystery, rhythm)?

Respond ONLY with this JSON (no other text):
{{"concept": <int>, "emotional_range": <int>, "character_fresh": <int>, "world_novelty": <int>, "tonal_gap": <int>, "similar_to": "<most similar title or None>", "uniqueness_verdict": "<essential or nice-to-have or redundant>"}}"""

    raw = call_groq(prompt)
    return parse_json_response(raw)


def final_decision(automated, engagement, moderation, uniqueness):
    """Final decision matrix combining all 4 passes."""
    eng_avg = (engagement["magic"] + engagement["cuddle"] +
               engagement["characters"] + engagement["listen_again"] +
               engagement["age_fit"]) / 5

    mod_avg = (moderation["violence_free"] + moderation["age_appropriate"] +
               moderation["cultural_sensitivity"] + moderation["inclusive"] +
               moderation["emotional_safety"]) / 5

    uniq_avg = (uniqueness["concept"] + uniqueness["emotional_range"] +
                uniqueness["character_fresh"] + uniqueness["world_novelty"] +
                uniqueness["tonal_gap"]) / 5

    struct_score = automated["structural_score"]

    # Safety is non-negotiable
    if not moderation.get("safe", True) or mod_avg < 7:
        action = "REJECT_SAFETY"
    elif struct_score < 5:
        action = "REJECT_STRUCTURAL"
    elif eng_avg >= 7 and uniq_avg >= 7:
        action = "AUTO_APPROVE"
    elif eng_avg >= 7 and uniq_avg >= 4:
        action = "KEEP_IF_SLOT"
    elif eng_avg >= 5 and uniq_avg >= 7:
        action = "WORTH_FIXING"
    elif eng_avg < 5:
        action = "DROP_LOW_QUALITY"
    elif uniq_avg < 4:
        action = "DROP_REDUNDANT"
    else:
        action = "LIKELY_DROP"

    return {
        "engagement_avg": round(eng_avg, 1),
        "moderation_avg": round(mod_avg, 1),
        "uniqueness_avg": round(uniq_avg, 1),
        "structural_score": struct_score,
        "action": action
    }


def run_qa(input_file, output_file):
    with open(input_file, 'r') as f:
        data = json.load(f)

    results = {"en": [], "hi": []}

    for lang in ["en", "hi"]:
        stories = data[lang]
        print(f"\n{'='*60}")
        print(f"  SCORING {lang.upper()} STORIES ({len(stories)} stories)")
        print(f"{'='*60}")

        for i, story in enumerate(stories):
            print(f"\n[{i+1}/{len(stories)}] {story['title']} ({story['word_count']}w, {story['theme']})")

            # Pass 1: Automated
            print("  P1 Structural...", end=" ", flush=True)
            automated = pass1_automated(story)
            status = "PASS" if automated["pass"] else f"FAIL ({', '.join(automated['issues'])})"
            print(status)

            # Pass 2: Engagement
            print("  P2 Engagement...", end=" ", flush=True)
            try:
                engagement = pass2_engagement(story)
                eng_avg = (engagement["magic"] + engagement["cuddle"] +
                          engagement["characters"] + engagement["listen_again"] +
                          engagement["age_fit"]) / 5
                print(f"{eng_avg:.1f}/10")
            except Exception as e:
                print(f"ERROR: {e}")
                engagement = {"magic": 0, "cuddle": 0, "characters": 0, "listen_again": 0, "age_fit": 0, "verdict": str(e), "fix_suggestion": "Retry"}
            time.sleep(2)

            # Pass 3: Moderation
            print("  P3 Moderation...", end=" ", flush=True)
            try:
                moderation = pass3_moderation(story)
                mod_avg = (moderation["violence_free"] + moderation["age_appropriate"] +
                          moderation["cultural_sensitivity"] + moderation["inclusive"] +
                          moderation["emotional_safety"]) / 5
                safe_str = "SAFE" if moderation.get("safe", True) else f"FLAGGED: {moderation.get('flags', '')}"
                print(f"{mod_avg:.1f}/10 — {safe_str}")
            except Exception as e:
                print(f"ERROR: {e}")
                moderation = {"violence_free": 0, "age_appropriate": 0, "cultural_sensitivity": 0, "inclusive": 0, "emotional_safety": 0, "flags": str(e), "safe": False}
            time.sleep(2)

            # Pass 4: Uniqueness
            print("  P4 Uniqueness...", end=" ", flush=True)
            try:
                uniqueness = pass4_uniqueness(story, stories)
                uniq_avg = (uniqueness["concept"] + uniqueness["emotional_range"] +
                           uniqueness["character_fresh"] + uniqueness["world_novelty"] +
                           uniqueness["tonal_gap"]) / 5
                print(f"{uniq_avg:.1f}/10 — {uniqueness.get('uniqueness_verdict', '?')}")
            except Exception as e:
                print(f"ERROR: {e}")
                uniqueness = {"concept": 0, "emotional_range": 0, "character_fresh": 0, "world_novelty": 0, "tonal_gap": 0, "similar_to": "Error", "uniqueness_verdict": "error"}
            time.sleep(2)

            # Final Decision
            decision = final_decision(automated, engagement, moderation, uniqueness)
            print(f"  >>> {decision['action']} (E={decision['engagement_avg']} M={decision['moderation_avg']} U={decision['uniqueness_avg']} S={decision['structural_score']})")

            results[lang].append({
                "id": story["id"],
                "title": story["title"],
                "age_group": story["age_group"],
                "theme": story["theme"],
                "geography": story["geography"],
                "lead_gender": story["lead_gender"],
                "word_count": story["word_count"],
                "type": story["type"],
                "text": clean_text(story["text"]),
                "automated": automated,
                "engagement": engagement,
                "moderation": moderation,
                "uniqueness": uniqueness,
                "decision": decision
            })

    with open(output_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Print summary table
    for lang in ["en", "hi"]:
        print(f"\n{'='*80}")
        print(f"  {lang.upper()} RESULTS")
        print(f"{'='*80}")
        print(f"{'#':<3} {'Title':<40} {'E':>4} {'M':>4} {'U':>4} {'S':>3} {'Action':<20}")
        print("-" * 80)
        from collections import Counter
        actions = Counter()
        for j, r in enumerate(results[lang]):
            d = r["decision"]
            actions[d["action"]] += 1
            print(f"{j+1:<3} {r['title'][:39]:<40} {d['engagement_avg']:>4} {d['moderation_avg']:>4} {d['uniqueness_avg']:>4} {d['structural_score']:>3} {d['action']:<20}")
        print("-" * 80)
        print("SUMMARY:", dict(actions))

    print(f"\nFull results: {output_file}")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/qa_subset.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/qa_results.json"
    run_qa(input_file, output_file)
