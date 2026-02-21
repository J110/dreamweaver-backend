#!/usr/bin/env python3
"""
Story Selection & QA Pipeline
1. Pre-filter candidates by diversity (no AI needed)
2. Single-call AI scoring (engagement + moderation + uniqueness combined)
3. Output top 3 per age group per language
"""

import json
import os
import sys
import time
import re
from pathlib import Path
from mistralai import Mistral
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "nkMwV9APQAsY4KALXMk3CaGLV1a5RPBa")
client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-large-latest"

EMOTION_MARKERS = [
    "[GENTLE]", "[CALM]", "[CURIOUS]", "[ADVENTUROUS]", "[MYSTERIOUS]",
    "[JOYFUL]", "[DRAMATIC]", "[WHISPERING]", "[SLEEPY]", "[EXCITED]",
    "[DRAMATIC_PAUSE]", "[RHYTHMIC]", "[SINGING]", "[HUMMING]", "[PAUSE]",
    "[laugh]", "[chuckle]"
]


def clean_text(text):
    clean = text
    for m in EMOTION_MARKERS:
        clean = clean.replace(m, "")
    return " ".join(clean.split())


def parse_json_response(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON: {text[:300]}")


def call_llm(prompt, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.2,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err or "resource" in err:
                wait = (attempt + 1) * 10
                print(f" [rate-limit, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded")


def score_story(story, other_titles_in_group):
    """Single AI call combining engagement + moderation + uniqueness."""
    text = clean_text(story["text"])
    others = "\n".join(f"- {t}" for t in other_titles_in_group)

    lang_note = ""
    if story["lang"] == "hi":
        lang_note = "This story is in Hindi (Romanized). Evaluate as Hindi for Indian children."

    prompt = f"""You are a children's literature expert, child psychologist, and content curator. Evaluate this bedtime {story['type']} in ONE assessment.

TITLE: {story['title']}
LANGUAGE: {story['lang'].upper()} | AGE: {story['age_group']} | THEME: {story['theme']} | GEOGRAPHY: {story['geography']}
{lang_note}

TEXT:
{text}

OTHER STORIES IN SAME AGE GROUP & LANGUAGE (for uniqueness comparison):
{others if others else "None yet — this is the first."}

Score ALL dimensions 1-10. Be critical — 7 = good, 5 = mediocre, 10 = exceptional.

ENGAGEMENT:
- magic: Wonder, imagination, "whoa" moments
- cuddle: Warmth, comfort, sleepiness
- characters: Memorable, named, relatable
- listen_again: Rhythm, repetition, re-listen value
- age_fit: Vocabulary and complexity match age {story['age_group']}

SAFETY:
- safe: Is content 100% safe for age {story['age_group']}? (true/false)
- safety_flags: Any concerns? ("None" if clean)

UNIQUENESS (vs other stories listed above):
- uniqueness: How different is this from the others? (1-10)
- similar_to: Most similar title above, or "None"

OVERALL:
- verdict: One sentence — would a {story['age_group']}-year-old love this?
- fix: One sentence improvement suggestion, or "None"

Respond ONLY with JSON:
{{"magic": <int>, "cuddle": <int>, "characters": <int>, "listen_again": <int>, "age_fit": <int>, "safe": <bool>, "safety_flags": "<str>", "uniqueness": <int>, "similar_to": "<str>", "verdict": "<str>", "fix": "<str>"}}"""

    raw = call_llm(prompt)
    return parse_json_response(raw)


def pre_filter_candidates(stories, age_group, lang, n=5):
    """Pick top N most diverse candidates using simple heuristics (no AI)."""
    pool = [s for s in stories if s["age_group"] == age_group and s["lang"] == lang]
    if len(pool) <= n:
        return pool

    # Score diversity: prefer different themes, geographies, genders, types
    seen_themes = set()
    seen_geos = set()
    seen_types = set()
    selected = []

    # Sort by word_count to get varied lengths
    pool.sort(key=lambda s: s["word_count"])

    # Round 1: Pick one per unique theme
    for s in pool:
        if s["theme"] not in seen_themes and len(selected) < n:
            selected.append(s)
            seen_themes.add(s["theme"])
            seen_geos.add(s["geography"])

    # Round 2: Fill remaining with max geography diversity
    for s in pool:
        if s not in selected and s["geography"] not in seen_geos and len(selected) < n:
            selected.append(s)
            seen_geos.add(s["geography"])

    # Round 3: Fill remaining with type diversity (story vs poem)
    for s in pool:
        if s not in selected and s["type"] not in seen_types and len(selected) < n:
            selected.append(s)
            seen_types.add(s["type"])

    # Round 4: Fill any remaining
    for s in pool:
        if s not in selected and len(selected) < n:
            selected.append(s)

    return selected[:n]


def run_selection():
    base = Path(__file__).parent.parent / "seed_output"

    with open(base / "content_expanded.json", 'r') as f:
        generated = json.load(f)

    with open(base / "content.json", 'r') as f:
        published = json.load(f)

    age_groups = ["0-1", "2-5", "6-8", "9-12"]
    languages = ["en", "hi"]

    # Map published stories to age groups
    pub_by_age_lang = {}
    for s in published:
        age = s.get("target_age", 4)
        if age <= 1:
            ag = "0-1"
        elif age <= 5:
            ag = "2-5"
        elif age <= 8:
            ag = "6-8"
        else:
            ag = "9-12"
        key = (ag, s["lang"])
        pub_by_age_lang.setdefault(key, []).append(s["title"])

    print("=== PUBLISHED STORIES BY AGE GROUP ===")
    for (ag, lang), titles in sorted(pub_by_age_lang.items()):
        print(f"  [{lang}] {ag}: {titles}")

    all_results = {}

    for lang in languages:
        for ag in age_groups:
            key = f"{lang}_{ag}"
            print(f"\n{'='*60}")
            print(f"  {lang.upper()} / Age {ag}")
            print(f"{'='*60}")

            # Published titles for this group (for uniqueness context)
            pub_titles = pub_by_age_lang.get((ag, lang), [])
            if pub_titles:
                print(f"  Already published: {pub_titles}")

            # Pre-filter candidates
            candidates = pre_filter_candidates(generated, ag, lang, n=5)
            if not candidates:
                print(f"  NO CANDIDATES available!")
                all_results[key] = []
                continue

            print(f"  Candidates: {len(candidates)}")
            for c in candidates:
                print(f"    - {c['title']} ({c['type']}, {c['theme']}, {c['geography']}, {c['word_count']}w)")

            # All titles for uniqueness comparison (published + other candidates)
            all_titles = pub_titles + [c["title"] for c in candidates]

            scored = []
            for i, story in enumerate(candidates):
                other_titles = [t for t in all_titles if t != story["title"]]
                print(f"  [{i+1}/{len(candidates)}] Scoring {story['title']}...", end="", flush=True)

                try:
                    scores = score_story(story, other_titles)
                    eng_avg = (scores["magic"] + scores["cuddle"] + scores["characters"] +
                              scores["listen_again"] + scores["age_fit"]) / 5
                    print(f" E={eng_avg:.1f} U={scores['uniqueness']} {'SAFE' if scores.get('safe', True) else 'FLAGGED'}")

                    scored.append({
                        "id": story["id"],
                        "title": story["title"],
                        "type": story["type"],
                        "age_group": ag,
                        "theme": story["theme"],
                        "geography": story["geography"],
                        "lead_gender": story["lead_gender"],
                        "word_count": story["word_count"],
                        "text": clean_text(story["text"]),
                        "description": story.get("description", ""),
                        "scores": scores,
                        "engagement_avg": round(eng_avg, 1),
                    })
                except Exception as e:
                    print(f" ERROR: {e}")

                time.sleep(3)  # Groq rate limit buffer

            # Rank by combined score: engagement (60%) + uniqueness (40%)
            for s in scored:
                s["combined"] = round(s["engagement_avg"] * 0.6 + s["scores"]["uniqueness"] * 0.4, 1)

            # Filter out unsafe
            scored = [s for s in scored if s["scores"].get("safe", True)]

            # Sort by combined score
            scored.sort(key=lambda x: x["combined"], reverse=True)

            # Take top 3
            top3 = scored[:3]
            all_results[key] = top3

            print(f"\n  TOP 3:")
            for j, s in enumerate(top3):
                print(f"    {j+1}. {s['title']} (E={s['engagement_avg']} U={s['scores']['uniqueness']} C={s['combined']})")

    # Save results
    output_file = base / "qa_selected.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Print final summary
    print(f"\n\n{'='*80}")
    print("  FINAL SELECTION — TOP 3 PER AGE GROUP PER LANGUAGE")
    print(f"{'='*80}")

    for lang in languages:
        print(f"\n  {'ENGLISH' if lang == 'en' else 'HINDI'}")
        print(f"  {'-'*70}")
        for ag in age_groups:
            key = f"{lang}_{ag}"
            top = all_results.get(key, [])
            pub = pub_by_age_lang.get((ag, lang), [])
            print(f"\n  Age {ag} (published: {len(pub)})")
            if not top:
                print(f"    (no candidates)")
                continue
            for j, s in enumerate(top):
                print(f"    {j+1}. [{s['type'][:4]}] {s['title']}")
                print(f"       {s['theme']}, {s['geography']}, {s['word_count']}w, {s['lead_gender']}")
                print(f"       E={s['engagement_avg']} U={s['scores']['uniqueness']} Combined={s['combined']}")
                print(f"       \"{s['scores']['verdict']}\"")

    print(f"\n\nFull results saved to: {output_file}")


if __name__ == "__main__":
    run_selection()
