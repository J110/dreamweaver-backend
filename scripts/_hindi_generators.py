"""Per-content-type generation + audio + cover + storage.

One function per content type. Each:
  1. Takes diversity axes from _hindi_diversity
  2. Builds a type-specific Mistral/Groq prompt
  3. Calls _hindi_llm.generate_json with retry-on-validation-fail (≤3)
  4. Renders audio via the engine the v2 spec mandates for that type
  5. Generates cover via Together AI FLUX
  6. Writes to seed + per-item runtime + content.json
  7. Returns the entry dict (or raises on terminal failure)

Engine matrix (per v2 specs):
  short_story → ElevenLabs Multilingual v2 (single voice)
  long_story  → ElevenLabs multi-voice + MiniMax mid-song + bed/swells
  lullaby     → MiniMax v2.5 + Hindi reference audio
  silly_song  → ElevenLabs Music
  poem        → MiniMax v2.5 + Hindi reference audio
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image
from pydub import AudioSegment

BASE_DIR = Path(__file__).parent.parent
REPO_ROOT = BASE_DIR.parent
WEB_ROOT = REPO_ROOT / "dreamweaver-web"

# When running on the GCP VM these prod paths exist and ARE the nginx-aliased
# served roots — write directly to them so cron runs don't need a separate
# scp step. On local Mac these don't exist and the writes are silently
# skipped (the seed/web copies still happen, and a manual deploy can scp
# from those).
PROD_BACKEND_PUBLIC = Path("/opt/dreamweaver-backend/public")
PROD_COVER_STORE   = Path("/opt/cover-store")
PROD_AUDIO_STORE   = Path("/opt/audio-store")
ON_PROD = PROD_BACKEND_PUBLIC.exists()

sys.path.insert(0, str(Path(__file__).parent))

from _hindi_llm import generate_json, LLMError  # type: ignore
from _hindi_validators import VALIDATORS, validate_structured, has_major, silly_song_cap_for  # type: ignore
from _hindi_qa_critic import critic_review, is_qa_enabled  # type: ignore


TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY", "")


# ───────────────────────────────────────────────────────────────────────
# COMMON HELPERS
# ───────────────────────────────────────────────────────────────────────

def _slug(s: str, n: int = 4) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:n] or uuid.uuid4().hex[:n]


def _hex(n: int = 4) -> str:
    return uuid.uuid4().hex[:n]


_SHORT_STORY_TAG_RE = re.compile(
    r"""
    \[/?PHRASE\]                # phrase wrappers (keep inner content)
    | \[MUSIC\]                  # 6s swell marker (drop)
    | \[PAUSE:\s*\d+\s*\]        # pause directive (drop)
    """,
    re.VERBOSE,
)


def strip_short_story_tags(text: str) -> str:
    """Remove v2 short-story structural tags ([MUSIC], [PAUSE: ms], [PHRASE]/[/PHRASE])
    from the displayed text. PHRASE wrappers are stripped but their inner
    content stays — the repeated phrase IS user-readable prose."""
    out = _SHORT_STORY_TAG_RE.sub("", text or "")
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = "\n".join(line.rstrip() for line in out.splitlines())
    return out.strip()


_PERSON_WORDS_RE = re.compile(
    r"\b(young |little |sleeping |peaceful |sweet |gentle |smiling |warm )?"
    r"(indian |hindi |asian |brown |dark |fair |bright )?"
    r"(boy|girl|child|children|baby|babies|kid|kids|toddler|infant|woman|man|"
    r"mother|father|maternal|paternal|nanny|family|people|person|figure|silhouette)\b",
    flags=re.IGNORECASE,
)


def _sanitize_flux_prompt(prompt: str) -> str:
    """Strip people-references for FLUX NSFW retries (child-sleeping false positives)."""
    cleaned = _PERSON_WORDS_RE.sub("", prompt).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return (
        "Watercolor children's-storybook illustration, soft pastel hues, dreamy "
        "bedtime atmosphere, no people, no faces, no figures, no characters — "
        + cleaned
    )


def _abstract_flux_prompt(_prompt: str) -> str:
    return (
        "Watercolor abstract bedtime artwork, soft pastel hues, dreamy "
        "indigo and violet palette, gentle gradient sky with stars and moon, "
        "no people, no faces, no figures, no characters, no objects — "
        "pure mood and color"
    )


def _flux_cover(prompt: str, w: int = 1024, h: int = 1024) -> bytes | None:
    """Generate a cover via Pollinations FLUX.

    Switched from Together AI on 2026-05-22: Together's 0.83 QPS free-tier
    cap caused NSFW-retry calls to 429-rate-limit, silently shipping
    /covers/default.svg. Pollinations has no QPS cap.

    Retry chain: original prompt → sanitized no-people prompt → fully
    abstract prompt. Logs loudly on total failure so cron-log scrapers
    can surface stories needing manual cover regen.
    """
    from urllib.parse import quote

    if not POLLINATIONS_KEY:
        print("  POLLINATIONS_API_KEY missing, skipping cover")
        return None

    def _call(p: str) -> bytes | None:
        truncated = p[:600].rsplit(",", 1)[0] if len(p) > 600 else p
        encoded = quote(truncated, safe="")
        url = f"https://gen.pollinations.ai/image/{encoded}?width={w}&height={h}&model=flux&nologo=true"
        headers = {"Authorization": f"Bearer {POLLINATIONS_KEY}"}
        try:
            resp = httpx.get(url, headers=headers, timeout=180, follow_redirects=True)
        except Exception as e:
            print(f"  Pollinations error: {e}")
            return None
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "")
            if "image" in ct and len(resp.content) > 1000:
                return resp.content
            print(f"  Pollinations 200 but unusable: ct={ct} bytes={len(resp.content)}")
            return None
        if resp.status_code == 429:
            print("  Pollinations 429 rate-limited, waiting 20s and retrying once")
            time.sleep(20)
            try:
                resp = httpx.get(url, headers=headers, timeout=180, follow_redirects=True)
                if resp.status_code == 200 and "image" in resp.headers.get("content-type", "") and len(resp.content) > 1000:
                    return resp.content
            except Exception as e:
                print(f"  Pollinations retry error: {e}")
                return None
        print(f"  Pollinations {resp.status_code}: {resp.text[:200]}")
        return None

    result = _call(prompt)
    if result:
        return result

    print("  Pollinations attempt 1 failed — retrying with no-people sanitized prompt")
    result = _call(_sanitize_flux_prompt(prompt))
    if result:
        return result

    print("  Pollinations attempt 2 failed — retrying with fully abstract prompt")
    result = _call(_abstract_flux_prompt(prompt))
    if result:
        return result

    print("  COVER GENERATION FAILED — manual retry needed for this item")
    return None


def _save_cover(png_bytes: bytes, *paths: Path, size: tuple[int, int] = (1024, 1024)):
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize(size, Image.LANCZOS)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, format="WEBP", quality=85)


def _save_audio(seg: AudioSegment, *paths: Path):
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        seg.export(p, format="mp3", bitrate="192k")


def _write_per_content_file(entry: dict) -> None:
    """Write per-content file for a generated HI item (spec §2g.1, additive).

    Walker reads from data/<type>[_hi]/<id>.json post-cutover. Coexists with
    the _upsert_content call below until post-cutover §4 step 15 deletes the
    upsert. lang is read from the entry; routing handled by _content_target_dir.
    """
    sys.path.insert(0, str(BASE_DIR))
    from app.services.local_store import _atomic_write_json, _content_target_dir
    target_dir = _content_target_dir(BASE_DIR / "data", entry)
    if target_dir is None:
        return
    _atomic_write_json(target_dir / f"{entry['id']}.json", entry, strip_subtype=True)


def _upsert_content(entry: dict) -> None:
    cj = BASE_DIR / "seed_output" / "content.json"
    data = json.loads(cj.read_text())
    items = data["items"] if isinstance(data, dict) else data
    items = [i for i in items if i.get("id") != entry["id"]]
    items.append(entry)
    if isinstance(data, dict):
        data["items"] = items
    else:
        data = items
    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _upsert_aggregate_json(entry: dict, agg_path: Path) -> None:
    if not agg_path.exists():
        agg_path.parent.mkdir(parents=True, exist_ok=True)
        agg_path.write_text("[]")
    data = json.loads(agg_path.read_text() or "[]")
    if not isinstance(data, list):
        data = []
    data = [i for i in data if i.get("id") != entry["id"]]
    data.append(entry)
    agg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _attach_qa_changes(entry: dict, llm_data: dict) -> None:
    """If the critic touched llm_data, surface a sanitized audit record on
    the saved entry (visible in seed/runtime content.json + daily email).
    Never leak internal scaffolding to user-facing fields."""
    qa = llm_data.get("_qa_changes")
    if qa:
        entry["qa_changes"] = {
            "action": qa.get("action"),
            "summary_of_changes": qa.get("summary_of_changes", []),
            "validator_errors": qa.get("validator_errors", []),
            "justification": qa.get("justification"),
            "elapsed_ms": qa.get("elapsed_ms"),
        }


def _llm_with_retry(*, system: str, user: str, validator_key: str,
                     max_retries: int = 3, log_prefix: str = "  ",
                     post_process=None, max_tokens: int = 4096,
                     repair_hint: "Callable[[list[str], dict], str | None] | None" = None) -> dict:
    """Generate JSON, validate, optionally critic-review, retry on failure.

    Flow per attempt (when HINDI_QA_ENABLED for this content_type):
      1. Mistral generate
      2. Regex validator
      3. If errors and ALL are minor → ONE Groq critic attempt:
            - action="fix"            → re-validate; pass → return
            - action="pass_override"  → log + return (with qa_changes audit)
            - action="regenerate"     → continue loop (no second Groq call)
      4. If MAJOR errors or critic-rejected → continue loop with cumulative
         retry hint

    Retry hint accumulates errors across all prior attempts so the LLM
    doesn't whack-a-mole between independent structural requirements.

    Optional `repair_hint` callback augments the generic retry hint with
    a validator-specific surgical instruction. Receives the prior attempt's
    error strings and the parsed data dict; returns a hint string (appended
    at the end of the user prompt for highest recency-weighted attention)
    or None to fall back to the generic block only.

    Returns the final (validated) content dict. The dict carries a
    `_qa_changes` key when the critic edited it — strip before saving
    to user-facing seed entries; keep for audit/email summary.
    """
    all_errors_seen: set[str] = set()
    last_errors: list[str] = []
    last_data: dict | None = None
    qa_enabled = is_qa_enabled(validator_key)
    qa_attempted = False  # one critic attempt per generation, not per retry
    for attempt in range(max_retries):
        retry_hint = ""
        if attempt > 0 and (last_errors or all_errors_seen):
            cumulative = sorted(set(last_errors) | all_errors_seen)
            retry_hint = (
                "\n\nPREVIOUS ATTEMPTS FAILED VALIDATION (across all retries — "
                "fix ALL of these in your next attempt, do NOT regress on items "
                "fixed earlier):\n"
                + "\n".join(f"- {e}" for e in cumulative[:15])
                + "\n\nOutput ONLY corrected JSON. Re-check every requirement before submitting."
            )
            if repair_hint is not None and last_data is not None:
                surgical = repair_hint(last_errors, last_data)
                if surgical:
                    retry_hint = retry_hint + "\n\n" + surgical
        try:
            data = generate_json(
                system=system,
                user=user + retry_hint,
                temperature=0.85,
                max_tokens=max_tokens,
                log_prefix=log_prefix,
            )
        except LLMError as e:
            print(f"{log_prefix}LLM failure: {e}")
            last_errors = [str(e)]
            continue

        # Optional shape transform before validation
        validator_input = post_process(data) if post_process else data
        # Structured (severity-tagged) view of validator errors — drives the
        # critic decision below. The bare-string list is preserved for the
        # retry-hint accumulator below.
        structured_errors = validate_structured(validator_key, validator_input)
        errors = [e["detail"] for e in structured_errors]

        if not errors:
            print(f"{log_prefix}validator passed")
            return data

        # ── QA critic layer (one attempt per generation, only if all errors
        #    are minor AND HINDI_QA_ENABLED). Skip when major errors are
        #    present — those need full regen, not patching.
        if (qa_enabled and not qa_attempted
                and not has_major(structured_errors)):
            qa_attempted = True
            print(f"{log_prefix}critic review (all {len(structured_errors)} errors are minor)")
            qa_result = critic_review(
                content=validator_input,
                errors=structured_errors,
                content_type=validator_key,
                log_prefix=log_prefix + "  ",
            )

            if qa_result["action"] == "fix":
                fixed = qa_result["fixed_content"]
                fixed["_qa_changes"] = {
                    "action": "fix",
                    "summary_of_changes": qa_result["summary_of_changes"],
                    "elapsed_ms": qa_result["elapsed_ms"],
                }
                print(f"{log_prefix}critic fixed: {qa_result['summary_of_changes'][:3]}")
                return fixed

            if qa_result["action"] == "pass_override":
                # Critic disagrees with validator — ship with audit flag.
                # Human review can later confirm whether validator was wrong.
                data["_qa_changes"] = {
                    "action": "pass_override",
                    "validator_errors": errors,
                    "justification": qa_result["justification"],
                    "elapsed_ms": qa_result["elapsed_ms"],
                }
                print(f"{log_prefix}critic OVERRIDE: {qa_result['justification']}")
                return data

            # action == "regenerate" or "skip" or "invalid" → fall through
            # to retry. Surface the regen reason in the next prompt.
            if qa_result.get("regen_reason"):
                errors = errors + [f"(critic flagged for regen: {qa_result['regen_reason']})"]
            for d in qa_result.get("diagnostics", []):
                print(f"{log_prefix}  diagnostic: {d}")

        print(f"{log_prefix}validator fail (attempt {attempt+1}): {errors[:5]}")
        last_errors = errors
        last_data = validator_input
        all_errors_seen.update(errors)
    raise RuntimeError(
        f"validator failed after {max_retries} attempts; "
        f"last errors: {last_errors}; cumulative seen: {sorted(all_errors_seen)[:10]}"
    )


# ───────────────────────────────────────────────────────────────────────
# SHORT STORY
# ───────────────────────────────────────────────────────────────────────

def _short_story_prompt(axes: dict) -> tuple[str, str]:
    age = axes["age_group"]
    word_band = {"2-5": "50-200", "6-8": "160-320", "9-12": "240-400"}[age]
    mood_descriptions = {
        "calm":    "soft and settling, warm steady rhythm, almost a lullaby",
        "curious": "dreamy and wondering, spacious and slow",
        "wired":   "bouncy and playful, high-energy Indian rhythm",
        "sad":     "gentle and tender, quiet, like a hug from Daadi",
        "anxious": "cozy and reassuring, steady predictable rhythm",
        "angry":   "firm then softening, strong rhythm gradually settling",
    }
    avoid_titles = "; ".join(t for t in axes["recent_titles"] if t) or "(none yet)"
    avoid_phrases = "; ".join(p for p in axes["recent_phrases"] if p) or "(none yet)"
    avoid_names = "; ".join(n for n in axes["recent_names"] if n) or "(none yet)"
    story_type_signature = {
        "katha":          'Open with "Kehte hain ki..." or "Bahut purani baat hai..."',
        "lok_katha":      'Open with "Ek tha..." or "Ek gaon mein..."',
        "neeti_katha":    "Open with two characters in dialogue",
        "prakriti_katha": "Open with a sensory nature image (sound, smell, temperature)",
        "sapnon_ki_katha":"Open with something impossible stated matter-of-factly",
        "ghar_ki_kahani": "Open with an Indian home sensory detail (chai smell, fan sound)",
    }[axes["story_type"]]

    system = (
        "You are a Hindi children's storyteller writing original bedtime "
        "stories in conversational Roman Hindi (bolchaal ki Hindi). "
        "Never use Devanagari. Never use literary Hindi (nidra, nakshatra, "
        "shayan, pushp, van, nayan, vidyalay). Never include religious or "
        "deity content. Output only the requested JSON."
    )
    user = f"""Generate a Hindi short story for age {age}.

DIVERSITY AXES (use these exactly):
- age_group: {age} (word count {word_band})
- mood: {axes['mood']} → {mood_descriptions[axes['mood']]}
- characterType: {axes['characterType']} (canonical 11)
- story_type: {axes['story_type']} ({story_type_signature})

ANTI-DUPLICATION (do NOT reuse):
- recent titles: {avoid_titles}
- recent phrases: {avoid_phrases}
- recent character names: {avoid_names}
- BANNED names: Chintu, Raju, Bittu, Munna, Guddu, Pinky, Rinku, Bablu,
  Pappu, Chhotu, Motu, Golu, Sonu, Monu, Titu, Bunty, Ramu

REQUIRED in `text`:
- TITLE must contain the lead character's name
- 3-5 [MUSIC] tags at meaningful pause beats (6-second swell each)
- 3+ [PHRASE]...[/PHRASE] wraps around your unique repeated phrase
- 0-2 [PAUSE: ms] tags (800/1200/1500/2000)
- ≥2 onomatopoeia (sarr, tap tap, chhap, khat khat, dheere dheere, gunghun, jhoom)
- ≥2 conversational markers (na, toh, pata hai, dekho, suno, achha, bas, arre, zara)
- Word count strictly within {word_band} (excluding tags)
- NO emotion markers ([GENTLE], [SLEEPY], etc.)

COMPREHENSIBILITY (per-sentence caps — hard rules):

Roman Hindi packs more syllables per word than English. The caps below
are calibrated for matras, not just word count.

  Ages 2-5:   max 10 words OR 18 matras per sentence (whichever is shorter)
  Ages 6-8:   max 14 words OR 24 matras per sentence
  Ages 9-12:  max 18 words OR 32 matras per sentence

Examples that PASS for ages 2-5:
  "Meenu ne chaand ko dekha."         (5 words, 9 matras)
  "Bulbul ne dheere se kahaa, suno."  (7 words, 12 matras)

Example that FAILS for ages 2-5 (matra-heavy — split):
  "Meenu ne aasmaan mein ud rahi titliyon ko dheere dheere dekhte
   hue muskuraayi."  (12 words, ~26 matras — too dense)

AVOID matra-stacking words that fill a sentence with 3-syllable nouns:
  AVOID:  kahaani, ghoomega, sundarta, raunaq, kaaynaat, samvedna.
  PREFER: 1-2 syllable bolchaal: chaand, paani, aankh, dil, raat,
          ghar, dheere, suno, dekho, achha.

ABSTRACT NOUNS — concept welcome, abstract noun not:
  AVOID NOUN  →  USE BOLCHAAL EQUIVALENT
  bhavna       →  "dil ne kaha"  /  "achha laga"
  sthithi      →  "yeh waqt"  /  "yeh raat"
  vichaar      →  "soch raha tha"  /  "yeh sochkar"
  anubhav      →  "aisa laga"  /  "mehsoos kiya"
  ehsaas       →  "lagne laga"  /  "dil mein"

The literary-Hindi ban (nidra, nakshatra, shayan, pushp, van, nayan,
vidyalay) remains in force.

Return JSON with exactly this shape:
{{
  "id": "hi-{axes['story_type']}-{age}-XXXX",
  "title": "Roman Hindi title with character name",
  "title_en": "English translation",
  "hook": "One-line tease in Roman Hindi (under 80 chars) for the audio intro",
  "hook_deva": "EXACT same hook in Devanagari script for TTS engine input",
  "description": "2-line description in Roman Hindi",
  "description_en": "English description",
  "text": "Full Roman Hindi story with [MUSIC], [PAUSE: ms], [PHRASE] tags inline",
  "text_deva": "EXACT same story content in Devanagari script (same tags inline) — used as TTS engine input for cleaner Hindi phonemes. MUST be a single string, NOT a JSON object or nested dict. Match `text` line-by-line.",
  "repeated_phrase": "Roman Hindi (≤5 words)",
  "morals": ["one or two short morals in English"],
  "categories": ["Bedtime", "<Hindi label>"],
  "character": {{
    "name": "Roman Hindi name (NOT in banned list)",
    "identity": "Roman Hindi description (3-5 words)",
    "special": "Roman Hindi quirk (3-7 words)",
    "personality_tags": ["Curious","Gentle"]
  }},
  "characterType": "{axes['characterType']}",
  "story_type": "{axes['story_type']}",
  "age_group": "{age}",
  "mood": "{axes['mood']}",
  "cover_context": "ONE English sentence for FLUX (no text/letters)",
  "diversityFingerprint": {{
    "characterType": "{axes['characterType']}",
    "setting": "<one of: forest, river, sky, meadow, mountain, village, house, garden, beach, pond>",
    "plotShape": "<one of: discovery_reveal, journey_home, gentle_help, found_thing, change_inside>",
    "timeOfDay": "<one of: dawn, morning, afternoon, dusk, twilight, night, deep_night>",
    "weather": "<clear, monsoon, breeze, mist, warm>",
    "theme": "<patience, friendship, wonder, comfort, kindness, courage, rest>",
    "scale": "<tiny_intimate, small_personal, medium, big_world>",
    "companion": "<solo, pair, family, group, object_pair>",
    "movement": "<walking, sitting, climbing, floating, stillness>",
    "magicType": "<none, glow, transformation, voice, breath, dream>",
    "season": "<summer, monsoon, winter, autumn, spring>",
    "senseEmphasis": "<auditory, visual, tactile, olfactory>",
    "characterTrait": "<curious, gentle, brave, dreamy, kind>"
  }}
}}
"""
    return system, user


def generate_short_story(axes: dict, log_prefix: str = "  ") -> dict:
    """Generate, validate, render, save. Returns the upserted entry."""
    print(f"\n{log_prefix}═══ SHORT STORY: age={axes['age_group']} mood={axes['mood']} type={axes['story_type']} char={axes['characterType']} ═══")
    sys_msg, user_msg = _short_story_prompt(axes)

    data = _llm_with_retry(
        system=sys_msg, user=user_msg,
        validator_key="short_story", log_prefix=log_prefix,
    )

    # ── Render audio via existing day-2 short-story assembler
    from fix_hindi_batch_day2 import assemble_story_audio  # type: ignore
    # Engine wants Devanagari; we got Roman. Use Roman directly — ElevenLabs
    # multilingual handles both, with a slight phoneme-fidelity penalty for
    # Roman. Acceptable v1.
    voice_for_mood = {
        "calm":    "tripti",
        "curious": "anika",
        "wired":   "anika",
        "sad":     "meher",
        "anxious": "meher",
        "angry":   "anika",
    }[axes["mood"]]
    # Engine input is Devanagari for cleaner Hindi phoneme rendering
    # (ElevenLabs Multilingual v2 produces sharper retroflex consonants and
    # matra-distinguished vowels from Devanagari than from Roman). Falls
    # back to Roman if the LLM didn't return text_deva.
    text_for_engine = data.get("text_deva") or data["text"]
    hook_for_engine = data.get("hook_deva") or data["hook"]
    audio = assemble_story_audio(
        text_deva=text_for_engine,
        hook_deva=hook_for_engine,
        voice_label=voice_for_mood,
        mood=axes["mood"],
    )
    duration = round(len(audio) / 1000)

    # Generate ID with character slug (matches existing convention)
    char_slug = _slug(data["character"]["name"], 4) or _hex(4)
    sid = data["id"] = f"hi-{axes['story_type']}-{axes['age_group']}-{char_slug}"

    # Save audio
    _save_audio(
        audio,
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_{voice_for_mood}.mp3",
        BASE_DIR / "seed_output" / "stories_hi" / f"{sid}.mp3",
    )

    # Generate + save cover
    cover = _flux_cover(data.get("cover_context", "Indian bedtime watercolor"))
    if cover:
        cover_paths = [
            WEB_ROOT / "public" / "covers" / f"{sid}.webp",                          # legacy duplicate
            BASE_DIR / "seed_output" / "stories_hi" / f"{sid}_cover.webp",           # debug master
        ]
        if ON_PROD:
            cover_paths.append(PROD_COVER_STORE / f"{sid}.webp")                     # frontend-served
        _save_cover(cover, *cover_paths)

    # text field is the user-facing display version (tags stripped).
    # raw_text keeps the tagged form for any pipeline that re-renders audio.
    display_text = strip_short_story_tags(data["text"])
    display_text_deva = strip_short_story_tags(data.get("text_deva", "") or "")
    entry = {
        "id": sid,
        "type": "story",
        "lang": "hi",
        "language": "hi",
        "title": data["title"],
        "title_en": data["title_en"],
        "hook": data["hook"],
        "description": data["description"],
        "description_en": data["description_en"],
        "text": display_text,
        "raw_text": data["text"],
        "raw_text_deva": data.get("text_deva", ""),
        "repeated_phrase": data["repeated_phrase"],
        "morals": data.get("morals", []),
        "categories": data.get("categories", ["Bedtime"]),
        "character": data["character"],
        "character_name": data["character"]["name"],
        "characterType": data["characterType"],
        "lead_character_type": data["characterType"],
        "story_type": data["story_type"],
        "storyType": data["story_type"],
        "age_group": axes["age_group"],
        "ageGroup": axes["age_group"],
        "age_min": int(axes["age_group"].split("-")[0]),
        "age_max": int(axes["age_group"].split("-")[1]),
        "target_age": (
            int(axes["age_group"].split("-")[0])
            + int(axes["age_group"].split("-")[1])
        ) // 2,
        "mood": axes["mood"],
        "cover": f"/covers/{sid}.webp" if cover else "/covers/default.svg",
        "cover_context": data.get("cover_context", ""),
        "audio_url": f"/audio/pre-gen/{sid}_{voice_for_mood}.mp3",
        "audio_variants": [{
            "voice": voice_for_mood,
            "url": f"/audio/pre-gen/{sid}_{voice_for_mood}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "duration_seconds": duration,
        "durationSec": duration,
        "tts_engine": "elevenlabs_multilingual_v2",
        "tts_input_script": "devanagari",
        "text_deva": display_text_deva,
        "has_baked_music": True,
        "diversityFingerprint": data.get("diversityFingerprint", {}),
        "is_generated": True,
        "author_id": "system",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _attach_qa_changes(entry, data)
    # Per spec §2g.1: per-content file write (additive — walker reads this
    # post-cutover). _upsert_content below stays until post-cutover §4 step 15.
    _write_per_content_file(entry)
    _upsert_content(entry)
    print(f"{log_prefix}✓ short story published: {sid} ({duration}s)")
    return entry


# ───────────────────────────────────────────────────────────────────────
# LULLABY
# ───────────────────────────────────────────────────────────────────────

LULLABY_TYPE_FLAVORS = {
    "heartbeat":   "humming-only acapella, mmm/dheere repeats, infant-pace rhythm",
    "permission":  "narrator gives child permission to sleep, gentle",
    "rocking":     "swaying 6/8 rhythm, jhulna metaphor, soft tabla",
    "counting":    "1-10 in Hindi, naming things one by one",
    "shield":      "I'm here, you're safe, parent's voice anchoring",
    "closing":     "saying goodnight to objects in the room",
    "humming":     "melodic hum motif (gunghun gunghun), word-light",
    "naming":      "naming stars/clouds/flowers as the child drifts",
}


def _lullaby_prompt(axes: dict) -> tuple[str, str]:
    age = axes["age_group"]
    avoid_titles = "; ".join(t for t in axes["recent_titles"] if t) or "(none yet)"
    flavor = LULLABY_TYPE_FLAVORS[axes["lullaby_type"]]

    system = (
        "You are a Hindi children's lullaby writer. Write in Roman Hindi "
        "(bolchaal). No Devanagari. No literary Hindi. No religious content. "
        "Lullabies should be gentle, repetitive, and full of warmth. "
        "Output only the requested JSON."
    )
    user = f"""Generate a Hindi lullaby.

AXES:
- age_group: {age}
- mood: {axes['mood']}
- lullaby_type: {axes['lullaby_type']} ({flavor})

ANTI-DUPLICATION:
- recent titles: {avoid_titles}

REQUIREMENTS:
- 6-16 lines of Roman Hindi lyrics
- Repetition is GOOD. Same phrase 2-3 times across the lullaby.
- Each line ≤8 words, ≤9 syllables.
- Tempo cue: ~60 BPM feel (slow, breathing-paced).
- NO instructions like "[verse]" — just the lyrics. Keep it bare.
- Total lyrics ≤500 chars.

Return JSON with exactly this shape:
{{
  "title": "Roman Hindi title (under 4 words)",
  "title_en": "English translation",
  "card_label": "Roman Hindi label (under 4 words)",
  "card_subtitle": "Roman Hindi subtitle (under 8 words)",
  "lyrics": "Roman Hindi lyrics, line-separated, no section tags",
  "lyrics_deva": "EXACT same lyrics in Devanagari script — used as MiniMax v2.5 engine input for cleaner Hindi phonemes. Single string, not nested.",
  "instruments": "<short Indian-instrument phrase, e.g. 'soft harmonium and gentle hum'>",
  "tempo": 60,
  "cover_context": "ONE English sentence for FLUX (Indian child sleeping, watercolor)"
}}
"""
    return system, user


def generate_lullaby(axes: dict, log_prefix: str = "  ") -> dict:
    print(f"\n{log_prefix}═══ LULLABY: age={axes['age_group']} mood={axes['mood']} type={axes['lullaby_type']} ═══")
    sys_msg, user_msg = _lullaby_prompt(axes)

    # Validator wants a `lullaby_type` and lyrics — pass via post_process
    def shape(d: dict) -> dict:
        return {
            **d,
            "lullaby_type": axes["lullaby_type"],
            "lyrics_roman": d.get("lyrics", ""),
        }

    data = _llm_with_retry(
        system=sys_msg, user=user_msg,
        validator_key="lullaby", log_prefix=log_prefix, post_process=shape,
    )

    # ── Render audio via MiniMax v2.5 + Hindi reference
    from fix_hindi_batch_day2 import minimax_lullaby  # type: ignore
    style = (
        f"Sweet Hindi lori, {data.get('instruments', 'soft harmonium')}, "
        f"{data.get('tempo', 60)} BPM, warm and loving, "
        f"smiling maternal voice, major key, native Hindi pronunciation, "
        f"gentle Indian bedtime feel, {LULLABY_TYPE_FLAVORS[axes['lullaby_type']]}"
    )
    # Devanagari for engine input (cleaner Hindi phonemes), Roman in display field.
    lyrics_for_engine = data.get("lyrics_deva") or data["lyrics"]
    composed = (
        f"{style}.\n\n"
        "Sing the following Hindi (Devanagari) lyrics clearly, in a native "
        "North Indian female voice, with conversational mother-tongue "
        "pronunciation — not a Western or Chinese vocal lens.\n\n"
        f"Lyrics:\n{lyrics_for_engine}"
    )
    audio_bytes = minimax_lullaby(composed, lyrics_for_engine)
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    duration = round(len(audio) / 1000)

    sid = f"hi-{axes['lullaby_type']}-{axes['age_group']}-{_slug(data['title'])}"

    audio_paths = [
        WEB_ROOT / "public" / "audio" / "lullabies" / f"{sid}.mp3",
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_female_1.mp3",
        BASE_DIR / "seed_output" / "lullabies" / f"{sid}.mp3",
    ]
    if ON_PROD:
        audio_paths.append(PROD_AUDIO_STORE / "lullabies" / f"{sid}.mp3")
    _save_audio(audio, *audio_paths)

    cover = _flux_cover(data.get("cover_context", "Indian baby sleeping under a quilt"))
    if cover:
        cover_paths = [
            WEB_ROOT / "public" / "covers" / f"{sid}.webp",                          # legacy duplicate
            WEB_ROOT / "public" / "covers" / "lullabies" / f"{sid}_cover.webp",      # legacy duplicate
            BASE_DIR / "seed_output" / "lullabies" / f"{sid}_cover.webp",            # debug master
        ]
        if ON_PROD:
            cover_paths.append(PROD_COVER_STORE / f"{sid}.webp")                              # frontend-served (root)
            cover_paths.append(PROD_COVER_STORE / "lullabies" / f"{sid}_cover.webp")          # frontend-served (subtype)
        _save_cover(cover, *cover_paths)

    entry = {
        "id": sid,
        "type": "song",
        "lang": "hi",
        "language": "hi",
        "story_format": "lullaby",
        "story_type": "lullaby",
        "storyType": "lullaby",
        "title": data["title"],
        "title_en": data["title_en"],
        "card_label": data["card_label"],
        "card_subtitle": data["card_subtitle"],
        "description": data["card_subtitle"],
        "description_en": data["title_en"],
        "lullaby_type": axes["lullaby_type"],
        "age_group": axes["age_group"],
        "ageGroup": axes["age_group"],
        "age_min": int(axes["age_group"].split("-")[0]),
        "age_max": int(axes["age_group"].split("-")[1]),
        "mood": axes["mood"],
        "instruments": data.get("instruments", ""),
        "tempo": data.get("tempo", 60),
        "text": data["lyrics"],
        "text_deva": data.get("lyrics_deva", ""),
        "lyrics": data["lyrics"],
        "lyrics_deva": data.get("lyrics_deva", ""),
        "characterType": "human_child",
        "lead_character_type": "human_child",
        "audio_url": f"/audio/lullabies/{sid}.mp3",
        "audio_variants": [{
            "voice": "minimax_v2.5_hi_ref",
            "url": f"/audio/lullabies/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5-fal",
        }],
        "cover": f"/covers/{sid}.webp" if cover else "/covers/default.svg",
        "cover_context": data.get("cover_context", ""),
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "minimax-music-v2.5-fal",
        "tts_engine": "minimax-music-v2.5-fal",
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Lullaby"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _attach_qa_changes(entry, data)
    # Per spec §2g.1: per-content file write (additive — walker reads this
    # post-cutover). _upsert_content below stays until post-cutover §4 step 15.
    _write_per_content_file(entry)
    _upsert_content(entry)
    _upsert_aggregate_json(entry, BASE_DIR / "seed_output" / "lullabies" / "lullabies.json")
    print(f"{log_prefix}✓ lullaby published: {sid} ({duration}s)")
    return entry


# ───────────────────────────────────────────────────────────────────────
# SILLY SONG
# ───────────────────────────────────────────────────────────────────────

_SILLY_BODY_CAP_RE = re.compile(r"lyrics body too long: (\d+) chars \(max (\d+)\)")


def _silly_song_repair_hint(errors: list[str], last_data: dict) -> str | None:
    measured: int | None = None
    parsed_cap: int | None = None
    for e in errors:
        m = _SILLY_BODY_CAP_RE.match(e)
        if m:
            measured = int(m.group(1))
            parsed_cap = int(m.group(2))
            break
    if measured is None:
        return None
    cap = parsed_cap if parsed_cap is not None else silly_song_cap_for(last_data.get("_axes"))
    target = cap - 50
    return (
        f"REVISION REQUIRED — character budget violated.\n\n"
        f"FORWARD CONSTRAINTS for your next draft:\n"
        f"- ≤14 body lines total (not counting [VERSE]/[CHORUS]/[ENDING] tags)\n"
        f"- Each line ≤8 words\n"
        f"- Body characters (excluding tags) MUST be ≤{target} chars; "
        f"hard ceiling {cap} chars\n"
        f"- Keep chorus identical between its two appearances\n"
        f"- Count characters yourself before submitting\n\n"
        f"For reference, your last attempt was {measured} chars and violated "
        f"this. Your next draft must satisfy the above hard constraints "
        f"regardless of structural similarity to prior attempts."
    )


def _silly_prompt(axes: dict) -> tuple[str, str]:
    age = axes["age_group"]
    cat = axes["category"]
    voice_arc = {
        "battle_cry":  "The child PROTESTS — cheeky, defiant, lovable",
        "celebration": "The child CELEBRATES — joy bursting out, ends in tired glow",
        "observation": "The child WONDERS — funny philosophical, ends drowsy",
    }[cat]
    avoid_anthems = ", ".join(axes.get("recent_anthem_ids", [])) or "(none yet)"
    body_cap = silly_song_cap_for(axes)
    body_target = body_cap - 50

    system = (
        "You are a Hindi children's songwriter writing fun, bouncy, catchy "
        "kids' songs in Roman Hindi. Cheeky, energetic, smiling. "
        "No Devanagari. No literary Hindi. No religious content of any kind "
        "(no deity names, no ritual verbs). Output only the requested JSON."
    )
    user = f"""Generate a Hindi silly song.

AXES:
- age_group: {age}
- mood: {axes['mood']}
- category: {cat} ({voice_arc})

ANTI-DUPLICATION:
- recent anthem_ids: {avoid_anthems}

REQUIREMENTS:
- Total ≤20 lines
- Each line ≤8 words, ≤9 matras
- Structure: [verse 1] (4 lines) / [chorus] (3-4 lines, anthem repeated) /
  [verse 2] (4 lines) / [chorus] (IDENTICAL to first) / [ending] (2-3 lines, fading)
- Section tags KEPT in lyrics (silly songs include them)
- ≥1 asterisked sound effect like *dhadaam*, *khat khat*, *chhapaak*, *thapp*
- Body text (excluding section tags) MUST be ≤{body_target} chars — count
  yourself before submitting. Hard ceiling: {body_cap} chars. If close,
  drop a verse line.
- Hinglish OK ("Mom", "okay", "school")
- NO emotion markers, NO simile-with-banned-noun

Return JSON:
{{
  "anthem_id": "snake_case_short_descriptor",
  "anthem": "The 2-5 word battle/celebration cry in Roman Hindi",
  "title": "Roman Hindi title using the anthem",
  "title_en": "English translation",
  "card_label": "Roman Hindi label",
  "card_subtitle": "One-line scene-setting in Roman Hindi",
  "lyrics": "Full Roman Hindi lyrics with [verse 1]/[chorus]/etc section tags",
  "lyrics_deva": "EXACT same lyrics in Devanagari script (same section tags inline) — used as ElevenLabs Music engine input per HINDI_SILLY_SONGS_GUIDELINES (1) §6.",
  "instruments": "Indian-fusion instrument phrase, e.g. 'ukulele, dholki, and hand claps'",
  "tempo": 120,
  "cover_context": "ONE English sentence for FLUX, Indian-kid-cartoon vibe"
}}
"""
    return system, user


def generate_silly_song(axes: dict, log_prefix: str = "  ") -> dict:
    print(f"\n{log_prefix}═══ SILLY SONG: age={axes['age_group']} mood={axes['mood']} cat={axes['category']} ═══")
    sys_msg, user_msg = _silly_prompt(axes)

    _axes_for_validator = {
        "age_group": axes["age_group"],
        "category": axes["category"],
    }
    data = _llm_with_retry(
        system=sys_msg, user=user_msg,
        validator_key="silly_song", log_prefix=log_prefix,
        post_process=lambda d: {**d, "_axes": _axes_for_validator},
        repair_hint=_silly_song_repair_hint,
        max_retries=5,        # 6-8/angry/celebration combo overshoots char
                              # budget on first 2-3 attempts; repair hint
                              # converges (~717→667→566) but needs headroom
                              # past 3-attempt default. Matches long-story budget.
    )

    # ── Render via ElevenLabs Music
    elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
    if not elevenlabs_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set — cannot generate silly song audio")
    style_prompt = (
        f"Catchy children's Hindi {axes['category']} song, bouncy playful "
        f"anthem, {data.get('instruments', 'ukulele and dholki')}, "
        f"{data.get('tempo', 120)} BPM, super energetic and joyful, "
        "smiling cheeky young Indian child female vocal, cheerful "
        "Bollywood-nursery lilt, warm major key, native Hindi "
        "pronunciation, strong singalong chorus."
    )[:295]
    # Devanagari for engine input per HINDI_SILLY_SONGS_GUIDELINES (1) §6 lock-in.
    lyrics_for_engine = data.get("lyrics_deva") or data["lyrics"]
    composed = (
        f"{style_prompt}\n\n"
        "Sing the following Hindi (Devanagari) lyrics clearly, in a native "
        "North Indian female child voice, with conversational mother-tongue "
        "pronunciation — not a Western or Chinese vocal lens. "
        "Verses are bouncy; the chorus is the singalong hook.\n\n"
        f"Lyrics:\n{lyrics_for_engine}"
    )
    body = {
        "prompt": composed,
        "music_length_ms": 70_000,
        "output_format": "mp3_44100_128",
    }
    print(f"{log_prefix}calling ElevenLabs Music…")
    resp = httpx.post(
        "https://api.elevenlabs.io/v1/music",
        headers={
            "xi-api-key": elevenlabs_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json=body, timeout=600,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs Music {resp.status_code}: {resp.text[:300]}")
    audio = AudioSegment.from_file(io.BytesIO(resp.content), format="mp3")
    duration = round(len(audio) / 1000)

    sid = f"hi-{data['anthem_id']}-{axes['age_group']}-{_hex()}"

    # SILLY-SONG paths.
    # Frontend hits api.dreamvalley.app/audio/silly-songs/  → backend public.
    # Frontend hits dreamvalley.app/covers/silly-songs/     → /opt/cover-store/silly-songs.
    # See HINDI_SILLY_SONGS_GUIDELINES (1) §12 — corrected v2.1 file layout.
    audio_paths = [
        WEB_ROOT / "public" / "audio" / "silly-songs" / f"{sid}.mp3",  # legacy duplicate
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}.mp3",      # legacy duplicate
        BASE_DIR / "seed_output" / "silly_songs" / f"{sid}.mp3",       # debug master
    ]
    if ON_PROD:
        audio_paths.extend([
            PROD_BACKEND_PUBLIC / "audio" / "silly-songs" / f"{sid}.mp3",  # legacy duplicate
            PROD_AUDIO_STORE / "silly-songs" / f"{sid}.mp3",               # api-served (frontend hits api.dreamvalley.app/audio/silly-songs/<file>)
        ])
    _save_audio(audio, *audio_paths)

    cover = _flux_cover(data.get("cover_context", "Indian kid in cozy kitchen"), 512, 512)
    if cover:
        cover_paths = [
            WEB_ROOT / "public" / "covers" / f"{sid}.webp",                          # home reference
            WEB_ROOT / "public" / "covers" / "silly-songs" / f"{sid}_cover.webp",   # legacy duplicate
            BASE_DIR / "seed_output" / "silly_songs" / f"{sid}_cover.webp",         # debug master
        ]
        if ON_PROD:
            cover_paths.append(PROD_COVER_STORE / "silly-songs" / f"{sid}_cover.webp")  # legacy subtype path
            cover_paths.append(PROD_COVER_STORE / f"{sid}.webp")  # nginx /covers/{sid}.webp alias
        _save_cover(cover, *cover_paths, size=(512, 512))

    entry = {
        "id": sid,
        "type": "song",
        "subtype": "silly_song",
        "story_type": "silly_song",
        "storyType": "silly_song",
        "lang": "hi",
        "language": "hi",
        "category": axes["category"],
        "anthem_id": data["anthem_id"],
        "anthem": data["anthem"],
        "title": data["title"],
        "title_en": data["title_en"],
        "card_label": data["card_label"],
        "card_subtitle": data["card_subtitle"],
        "description": data["card_subtitle"],
        "description_en": data["title_en"],
        "lyrics": data["lyrics"],
        "lyrics_deva": data.get("lyrics_deva", ""),
        "raw_lyrics": data["lyrics"],
        "age_group": axes["age_group"],
        "ageGroup": axes["age_group"],
        "age_min": int(axes["age_group"].split("-")[0]),
        "age_max": int(axes["age_group"].split("-")[1]),
        "mood": axes["mood"],
        "instruments": data.get("instruments", ""),
        "tempo": data.get("tempo", 120),
        "audio_file": f"{sid}.mp3",
        "audio_url": f"/audio/silly-songs/{sid}.mp3",
        "audio_variants": [{
            "voice": "elevenlabs_music_v1",
            "url": f"/audio/silly-songs/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-music",
        }],
        "cover": f"/covers/{sid}.webp" if cover else "/covers/default.svg",
        "cover_file": f"{sid}_cover.webp",
        "cover_context": data.get("cover_context", ""),
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "elevenlabs-music",
        "tts_engine": "elevenlabs-music",
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Silly Song"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _attach_qa_changes(entry, data)
    # Per spec §2g.1: per-content file write (walker reads this post-cutover —
    # must hold the rich entry, not a slim subset, or audio_url/cover are
    # stripped from the API response). _upsert_content stays until post-cutover §4 step 15.
    _write_per_content_file(entry)
    _upsert_content(entry)
    print(f"{log_prefix}✓ silly song published: {sid} ({duration}s)")
    return entry


# ───────────────────────────────────────────────────────────────────────
# POEM
# ───────────────────────────────────────────────────────────────────────

POEM_TYPE_FLAVORS = {
    "sound":    "build the entire scene from Hindi onomatopoeia (sarr sarr, tap tap, chhap chhap, gunghun, khat khat). Each line is mostly onomatopoeia plus a single content word.",
    "nonsense": "playful Hindi nonsense words. Pair real words in absurd combinations. Invent Hindi-shaped nonsense (tippan toppan, halla gulla, dhaani paani).",
    "question": "chain of unanswerable Indian questions. Each more absurd. Don't answer them.",
}


def _poem_prompt(axes: dict) -> tuple[str, str]:
    age = axes["age_group"]
    matra = 11 if axes["poem_type"] == "question" else 9
    avoid_titles = "; ".join(t for t in axes["recent_titles"] if t) or "(none yet)"

    system = (
        "You are a Hindi children's poet writing rhythmic, memorable poems "
        "for bedtime in conversational Roman Hindi. No Devanagari. "
        "No literary Hindi. No religious content. Output only the requested JSON."
    )
    user = f"""Generate a Hindi musical poem (spoken to a beat, not sung).

AXES:
- age_group: {age}
- mood: {axes['mood']}
- poem_type: {axes['poem_type']} ({POEM_TYPE_FLAVORS[axes['poem_type']]})

ANTI-DUPLICATION:
- recent titles: {avoid_titles}

REQUIREMENTS:
- 8-16 total lines (no section tags, no [verse]/[chorus])
- Each line ≤6 WORDS and very short — under 12 syllables in Roman Hindi
- Use simple words (chaand not chandra, paani not jal, aankh not nayan)
- Avoid multi-syllable Hindi words that stack matras fast
  (e.g. "kahaani"=3-syl, "ghoomega"=3-syl — break into shorter phrases)
- AABB rhyming couplets (line 1 rhymes with line 2, line 3 with line 4, ...)
- Total ≤500 chars
- Each line is a complete thought; one thought per line

Return JSON:
{{
  "title": "Roman Hindi title (under 5 words)",
  "title_en": "English translation",
  "poem_text": "Full Roman Hindi poem, lines newline-separated, no tags",
  "poem_text_deva": "EXACT same poem in Devanagari script — used as MiniMax v2.5 engine input. Single string, line-separated, no tags.",
  "instruments": "Indian-fusion gentle instruments",
  "tempo": 100,
  "cover_context": "ONE English sentence for FLUX (abstract, no people, no faces)"
}}
"""
    return system, user


def generate_poem(axes: dict, log_prefix: str = "  ") -> dict:
    print(f"\n{log_prefix}═══ POEM: age={axes['age_group']} mood={axes['mood']} type={axes['poem_type']} ═══")
    sys_msg, user_msg = _poem_prompt(axes)

    def shape(d: dict) -> dict:
        return {**d, "poem_type": axes["poem_type"]}

    data = _llm_with_retry(
        system=sys_msg, user=user_msg,
        validator_key="poem", log_prefix=log_prefix, post_process=shape,
    )

    # ── Render via MiniMax v2.5 + Hindi reference
    from fix_hindi_batch_day2 import minimax_lullaby  # type: ignore
    mood_energy = {
        "calm":    "soft and settling, warm steady rhythm, almost a lullaby",
        "curious": "dreamy and wondering, spacious like a slow afternoon",
        "wired":   "bouncy and playful, high-energy Indian rhythm",
        "sad":     "gentle and tender, quiet rhythm, like a hug from Daadi",
        "anxious": "cozy and reassuring, steady predictable rhythm",
        "angry":   "firm then softening, strong rhythm gradually settling",
    }[axes["mood"]]
    style = (
        f"Children's Hindi musical poem, {data.get('instruments', 'soft harmonium and tabla')}, "
        f"{data.get('tempo', 100)} BPM, {mood_energy}, warm clear North Indian "
        "female vocal speaking each word rhythmically, native Hindi pronunciation, "
        "every word crystal clear, like a parent reciting a poem at bedtime, "
        "not sung — spoken to a beat. Not Western."
    )[:300]
    # Devanagari for engine input.
    poem_for_engine = data.get("poem_text_deva") or data["poem_text"]
    composed = (
        f"{style}.\n\n"
        "Recite the following Hindi (Devanagari) poem rhythmically, in a "
        "native North Indian female voice, with conversational mother-tongue "
        "pronunciation — spoken to a beat, not sung.\n\n"
        f"Poem:\n{poem_for_engine}"
    )
    audio_bytes = minimax_lullaby(composed, poem_for_engine)
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    duration = round(len(audio) / 1000)

    sid = f"hi-{axes['poem_type']}-{axes['age_group']}-{_hex()}"

    # POEM paths.
    # Frontend hits api.dreamvalley.app/audio/poems/   → backend public/audio/poems/.
    # Frontend hits dreamvalley.app/covers/poems/      → backend public/covers/poems/.
    # NOTE: served URL is /poems/ (no -hi suffix); lang filtering is via the
    # `lang` field on the JSON, not the path. See HINDI_MUSICAL_POEMS §12 (v2.1).
    audio_paths = [
        WEB_ROOT / "public" / "audio" / "poems-hi" / f"{sid}.mp3",  # legacy debug
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}.mp3",   # legacy duplicate
        BASE_DIR / "seed_output" / "poems_hi" / f"{sid}.mp3",       # debug master
    ]
    if ON_PROD:
        audio_paths.extend([
            PROD_BACKEND_PUBLIC / "audio" / "poems" / f"{sid}.mp3",  # legacy duplicate
            PROD_AUDIO_STORE / "poems" / f"{sid}.mp3",               # api-served (frontend hits api.dreamvalley.app/audio/poems/<file>)
        ])
    _save_audio(audio, *audio_paths)

    cover = _flux_cover(data.get("cover_context", "Indian abstract watercolor"))
    if cover:
        cover_paths = [
            WEB_ROOT / "public" / "covers" / f"{sid}.webp",                       # legacy duplicate (home reference)
            WEB_ROOT / "public" / "covers" / "poems-hi" / f"{sid}_cover.webp",    # legacy duplicate
            BASE_DIR / "seed_output" / "poems_hi" / f"{sid}_cover.webp",          # debug master
        ]
        if ON_PROD:
            cover_paths.append(PROD_COVER_STORE / f"{sid}.webp")                              # frontend-served (root)
            cover_paths.append(PROD_COVER_STORE / "poems" / f"{sid}_cover.webp")              # frontend-served (subtype)
        _save_cover(cover, *cover_paths)

    text_lines = [l for l in data["poem_text"].split("\n") if l.strip()]
    entry = {
        "id": sid,
        "type": "poem",
        "lang": "hi",
        "language": "hi",
        "story_type": "poem",
        "storyType": "poem",
        "content_type": "poem",
        "poem_type": axes["poem_type"],
        "title": data["title"],
        "title_en": data["title_en"],
        "description": "Hindi children's musical poem",
        "description_en": "Hindi children's musical poem",
        "poem_text": data["poem_text"],
        "poem_text_deva": data.get("poem_text_deva", ""),
        "text": data["poem_text"],
        "text_deva": data.get("poem_text_deva", ""),
        "raw_text": data["poem_text"],
        "age_group": axes["age_group"],
        "ageGroup": axes["age_group"],
        "age_min": int(axes["age_group"].split("-")[0]),
        "age_max": int(axes["age_group"].split("-")[1]),
        "mood": axes["mood"],
        "instruments": data.get("instruments", ""),
        "tempo": data.get("tempo", 100),
        "char_count": len(data["poem_text"]),
        "line_count": len(text_lines),
        "audio_file": f"{sid}.mp3",
        "audio_url": f"/audio/poems-hi/{sid}.mp3",
        "audio_variants": [{
            "voice": "minimax_v2.5_hi_ref",
            "url": f"/audio/poems-hi/{sid}.mp3",
            "duration_seconds": duration,
            "provider": "minimax-music-v2.5-fal",
        }],
        "cover": f"/covers/{sid}.webp" if cover else "/covers/default.svg",
        "cover_file": f"{sid}_cover.webp",
        "cover_context": data.get("cover_context", ""),
        "duration_seconds": duration,
        "durationSec": duration,
        "audio_engine": "minimax-music-v2.5-fal",
        "tts_engine": "minimax-music-v2.5-fal",
        "has_baked_music": True,
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Poem"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _attach_qa_changes(entry, data)
    # Per spec §2g.1: per-content file write (walker reads this post-cutover —
    # must hold the rich entry, not a slim subset, or audio_url/cover are
    # stripped from the API response). _upsert_content stays until post-cutover §4 step 15.
    _write_per_content_file(entry)
    _upsert_content(entry)
    print(f"{log_prefix}✓ poem published: {sid} ({duration}s)")
    return entry


# ───────────────────────────────────────────────────────────────────────
# LONG STORY
# ───────────────────────────────────────────────────────────────────────

def _long_story_prompt(axes: dict) -> tuple[str, str]:
    age = axes["age_group"]
    word_band = {"2-5": (1040, 1520), "6-8": (1520, 2240), "9-12": (2240, 3040)}[age]
    avoid_titles = "; ".join(t for t in axes["recent_titles"] if t) or "(none yet)"
    avoid_phrases = "; ".join(p for p in axes["recent_phrases"] if p) or "(none yet)"
    avoid_mysteries = "; ".join(m for m in axes["recent_mysteries"] if m) or "(none yet)"

    system = (
        "You are a Hindi children's storyteller writing long-form bedtime "
        "stories (15-25 minutes spoken). Conversational Roman Hindi only. "
        "No Devanagari. No literary Hindi. No religious content. "
        "Output ONLY the requested JSON."
    )
    user = f"""Generate a Hindi long story.

AXES:
- age_group: {age} ({word_band[0]}-{word_band[1]} words total)
- mood: {axes['mood']}
- world_name: {axes['world_name']}
- characterType: {axes['characterType']}

ANTI-DUPLICATION:
- recent titles: {avoid_titles}
- recent phrases: {avoid_phrases}
- recent mysteries: {avoid_mysteries}
- BANNED names: Chintu, Raju, Bittu, Munna, Guddu, Pinky, Rinku, Bablu,
  Pappu, Chhotu, Motu, Golu, Sonu, Monu, Titu, Bunty, Ramu

THREE-PHASE ARC (mandatory):
- Phase 1 — Khoj (Discovery, ~30%): character enters {axes['world_name']},
  finds a mystery, meets companions, gets a breathing mechanic
- Phase 2 — Vishraam (Resolution-as-Rest, ~35%): the mystery resolves to
  rest. Companions settle. Dialogue fades.
- Phase 3 — Vilay (Dissolution, ~35%): no dialogue. Descending sentence
  length. Wave repetition. Closes with [WHISPER]...[/WHISPER]

REQUIRED tags throughout:
- [CHARACTER: Name, personality, voice_style, gender] for each character (top of story)
- [INTRO] (2-3 sentences direct address to child)
- [PHASE_1] [PHASE_2] [PHASE_3] section markers
- [BREATHE_GUIDE]...[/BREATHE_GUIDE] (slow-breath instructions, once)
- 4-6 [BREATHE] standalone tags (clustered in P1 + P2)
- [SONG_SEED: one English sentence] at end of P1
- [POST_SONG] section after song
- 3+ [PHRASE]...[/PHRASE] wraps around the unique repeated phrase
- 0-2 [PAUSE: ms] tags
- [WHISPER]...[/WHISPER] for the final 3-4 lines
- ≥5 conversational markers (na, toh, pata hai, bas, suno, dekho, achha)
- ≥3 onomatopoeia (sarr, tap tap, chhap chhap, dheere dheere, gunghun, jhoom, tip tip, khat khat)

COMPREHENSIBILITY (per-sentence caps — hard rules):

Same caps as Hindi short stories:
  Ages 2-5:   max 10 words / 18 matras per sentence
  Ages 6-8:   max 14 words / 24 matras per sentence
  Ages 9-12:  max 18 words / 32 matras per sentence

PHASE 3 (VILAY) — DESCEND BELOW THE CAP:
The dissolution phase already removes dialogue. It must also shrink
sentences. Start P3 near the cap; end at 3-5 words per sentence. The
listener's breathing slows; the prose breathes with it.

  Phase 3 opening sentence (near cap):
    "Chaand ab dheere dheere apni jagah par tham gaya tha."  (10 words)
  Phase 3 closing sentences (well below cap):
    "Sab kuch shaant.  Hawa thami.  Aankh band.  Saans dheere."  (3-2-2-2)

ABSTRACT NOUNS — same rule as short stories:
  bhavna   →  "dil ne kaha"
  sthithi  →  "yeh waqt"
  anubhav  →  "aisa laga"
  ehsaas   →  "lagne laga"

The literary-Hindi ban (nidra, nakshatra, shayan, pushp, van, nayan,
vidyalay) remains in force.

DIALOGUE FORMAT — MANDATORY (do NOT embed dialogue in narration):

✓ CORRECT:
    MEENU: "Chaand kahaan gaya hai?"
    BULBUL: "Khoya nahin hai. Suno zara."

✗ WRONG (forbidden):
    Meenu ne kaha ki chaand kahaan gaya hai.
    Bulbul ne dheere se kaha, "Khoya nahin hai."  ← embedded in narration

Rules:
- Each dialogue line starts with the character's name in UPPERCASE,
  followed by a colon, followed by the quoted line in Roman Hindi.
- At least 3 such NAME: "..." lines per story.
- Every [CHARACTER:] you declare MUST have at least one dialogue line.
  (Each character gets a distinct voice; characters without dialogue lines
  contribute nothing to the audio.)
- Solo characters can speak to themselves, the moon, the wind, the
  listening child — but they MUST use the NAME: "..." form, not
  embedded narration.

The mystery's reveal is ALWAYS rest: "khoya nahin, so raha tha".
Mechanic is an object that activates with slow breath (diya, patang, leaf, talaab).

Return JSON:
{{
  "title": "Roman Hindi (must include lead character's name)",
  "title_en": "English translation",
  "world_name": "{axes['world_name']}",
  "world_name_en": "English",
  "world_description": "Roman Hindi (one sentence)",
  "world_description_en": "English",
  "mystery": "Roman Hindi (one sentence)",
  "resolution": "Roman Hindi (one sentence)",
  "breathing_mechanic": "Roman Hindi (one sentence)",
  "repeated_phrase": "Roman Hindi (≤5 words)",
  "characters": [
    {{"name": "X", "identity": "Roman Hindi (one sentence)",
      "personality": "<gentle|wise|curious|brave|...>",
      "voice_style": "<dreamy|quiet|small|confident|...>",
      "gender": "<female|male|neutral>"}},
    ...
  ],
  "song_seed": "ONE English sentence describing the mid-story song's mood + imagery",
  "song_lyrics_deva": "Short Devanagari lyrics (3-5 lines) for the embedded mid-story song",
  "cover_context": "ONE English sentence for FLUX",
  "full_text_roman": "FULL Roman Hindi story as A SINGLE STRING. Tags ([INTRO], [PHASE_1], [BREATHE], [PHRASE]...[/PHRASE], [SONG_SEED:], [POST_SONG], [PHASE_2], [PHASE_3], [WHISPER]...[/WHISPER]) MUST appear inline as text within the string, NEVER as JSON keys or nested objects. Example shape: \\"[CHARACTER: ...]\\\\n[INTRO]\\\\nSuno na...\\\\n[PHASE_1]\\\\nTara dheere dheere chal rahi thi...\\". DO NOT return this field as a dict like {{\\"intro\\": \\"...\\", \\"phase_1\\": \\"...\\"}} — that breaks the renderer.",
  "full_text_deva": "EXACT same content as full_text_roman but in Devanagari script. Same tags inline (tags themselves stay as Latin: [INTRO], [PHASE_1], etc. — only the prose between tags is Devanagari). Used as TTS engine input for cleaner Hindi phonemes. SINGLE STRING, NEVER a nested object."
}}
"""
    return system, user


def generate_long_story(axes: dict, log_prefix: str = "  ") -> dict:
    print(f"\n{log_prefix}═══ LONG STORY: age={axes['age_group']} mood={axes['mood']} world={axes['world_name']} ═══")
    sys_msg, user_msg = _long_story_prompt(axes)

    def shape(d: dict) -> dict:
        # Validator wants phase splits — extract them from full_text_roman.
        # If the LLM returned a dict (a known Mistral failure mode where it
        # interprets "tags inline" as "tags as JSON keys"), force string
        # coercion to "" so the validator immediately fails on missing
        # [PHASE_1] etc. and triggers a retry with the corrected prompt.
        # That's better than shipping JSON-as-text with str(dict) repr.
        full = d.get("full_text_roman")
        if isinstance(full, dict):
            full = ""  # validator will reject; retry will fix
        elif isinstance(full, list):
            full = "\n\n".join(str(x) for x in full if isinstance(x, str))
        elif full is None or not isinstance(full, str):
            full = ""
        d["full_text_roman"] = full
        # Same hardening for the Devanagari engine input field
        full_deva = d.get("full_text_deva")
        if not isinstance(full_deva, str):
            full_deva = ""
        d["full_text_deva"] = full_deva
        p1 = re.search(r"\[PHASE_1\](.*?)\[PHASE_2\]", full, re.DOTALL)
        p2 = re.search(r"\[PHASE_2\](.*?)\[PHASE_3\]", full, re.DOTALL)
        p3 = re.search(r"\[PHASE_3\](.*)", full, re.DOTALL)
        return {
            **d,
            "phase_1_text_roman": p1.group(1).strip() if p1 else "",
            "phase_2_text_roman": p2.group(1).strip() if p2 else "",
            "phase_3_text_roman": p3.group(1).strip() if p3 else "",
        }

    data = _llm_with_retry(
        system=sys_msg, user=user_msg,
        validator_key="long_story", log_prefix=log_prefix, post_process=shape,
        max_retries=5,        # long stories often need multiple retries to
                              # converge on all structural requirements
                              # simultaneously (BREATHE count, onomatopoeia,
                              # phase tags, conversational markers, etc.)
        max_tokens=12_000,    # full_text_roman + full_text_deva together
                              # need ~8-12k tokens of headroom
    )

    # ── Render via existing publish_hindi_long_day1 helpers
    from publish_hindi_long_day1 import (  # type: ignore
        elevenlabs_tts, ELEVENLABS_VOICES, PHASE_TTS, PHRASE_TTS,
        WHISPER_TTS, INTRO_TTS, _trim_or_loop, _apply_breathe_swells,
        parse_long_segments, _ensure_terminal,
    )
    from audio_assembly import normalize_for_tts, MUSIC_DIR  # type: ignore
    from fix_hindi_batch_day2 import minimax_lullaby  # type: ignore

    # Engine input: Devanagari for cleaner Hindi phonemes (ElevenLabs Multilingual
    # v2 produces sharper retroflex consonants and matra-distinguished vowels
    # from Devanagari). The Roman version stays in user-facing text fields.
    # Falls back to Roman if the LLM didn't return full_text_deva.
    full_text_for_engine = data.get("full_text_deva") or data["full_text_roman"]
    full_text_for_display = data["full_text_roman"]  # used by content.json text fields
    segments = parse_long_segments(full_text_for_engine)

    # Generate the embedded song. Prefer LLM-provided Devanagari lyrics if
    # present; else hand-build from repeated_phrase as a safe fallback.
    song_style = (
        "Sweet Hindi lori, solo female vocal humming an intimate riverbank "
        "lullaby, soft harmonium and bansuri, 60 BPM, warm and loving, "
        "smiling maternal voice, major key, native Hindi pronunciation"
    )
    print(f"{log_prefix}generating mid-story song…")
    song_lyrics = (data.get("song_lyrics_deva") or "").strip()
    if not song_lyrics:
        song_lyrics = (
            f"{data['repeated_phrase']}, {data['repeated_phrase']}\n"
            f"Dheere dheere, bas dheere dheere\n"
            f"{data['repeated_phrase']}"
        )
    song_bytes = minimax_lullaby(song_style, song_lyrics)
    song = AudioSegment.from_file(io.BytesIO(song_bytes), format="mp3")
    if len(song) > 45000:
        song = song[:45000].fade_out(2000)

    # Assemble Part A / B / C with bed + swells (port of publish_hindi_long_day1)
    # Voices: tripti and roohi are RESERVED for narrator and whisper. Every
    # character gets a DISTINCT non-narrator voice so the audio never collapses
    # to single-voice narration.
    NARRATOR_VOICE = "tripti"
    WHISPER_VOICE = "roohi"
    FEMALE_CHAR_VOICES = ["anika", "meher", "gudiya"]
    MALE_CHAR_VOICES = ["kuber_j", "raghav", "kiran"]
    # Cross-gender fallback if the gender pool is exhausted (more characters
    # of one gender than voices). Still excludes tripti.
    ANY_CHAR_VOICE_FALLBACK = MALE_CHAR_VOICES + FEMALE_CHAR_VOICES

    chars = data.get("characters", [])
    char_voice: dict[str, str] = {}
    used_voices: set[str] = set()

    def _pick_voice(gender: str) -> str:
        gender = (gender or "neutral").lower()
        if gender == "female":
            primary = FEMALE_CHAR_VOICES
        elif gender == "male":
            primary = MALE_CHAR_VOICES
        else:  # neutral — tilt toward male (more contrast vs the female narrator)
            primary = MALE_CHAR_VOICES + FEMALE_CHAR_VOICES
        for v in primary:
            if v not in used_voices:
                return v
        # Out of gender-preferred voices; spill to the cross-gender pool
        for v in ANY_CHAR_VOICE_FALLBACK:
            if v not in used_voices:
                return v
        # Truly exhausted (>6 characters in one story) — duplicate is the
        # least-bad option, but never tripti
        return ANY_CHAR_VOICE_FALLBACK[0]

    for ch in chars:
        name = ch.get("name", "").upper()
        if not name:
            continue
        v = _pick_voice(ch.get("gender", "neutral"))
        char_voice[name] = v
        used_voices.add(v)

    text_segs = [(i, s) for i, s in enumerate(segments)
                 if s["kind"] in ("narration", "dialogue", "phrase",
                                  "whisper", "breathe_guide")]
    neighbor: dict = {}
    for j, (i, s) in enumerate(text_segs):
        prev_text = text_segs[j - 1][1]["content"] if j > 0 else ""
        next_text = text_segs[j + 1][1]["content"] if j + 1 < len(text_segs) else ""
        neighbor[i] = (prev_text, next_text)

    def render_seg(idx: int, seg: dict):
        kind = seg["kind"]
        if kind == "pause":
            return AudioSegment.silent(duration=seg["ms"])
        if kind == "breathe":
            return AudioSegment.silent(duration=5000)
        if kind == "song":
            return song
        prev, nxt = neighbor.get(idx, ("", ""))
        phase = seg.get("phase", 1)
        if kind == "dialogue":
            # Hard rule: dialogue NEVER falls back to the narrator. If the
            # LLM uses a name not in [CHARACTER:] declarations, assign a
            # fresh non-narrator voice on the fly (warns + extends char_voice).
            char_name = seg["character"]
            voice_label = char_voice.get(char_name)
            if voice_label is None:
                voice_label = _pick_voice("neutral")
                char_voice[char_name] = voice_label
                used_voices.add(voice_label)
                print(f"      warning: undeclared char {char_name!r} → {voice_label}")
            preset = PHASE_TTS[phase]
            text = _ensure_terminal(seg["content"])
        elif kind == "phrase":
            voice_label = NARRATOR_VOICE
            preset = PHRASE_TTS
            text = _ensure_terminal(seg["content"])
        elif kind == "whisper":
            voice_label = WHISPER_VOICE
            preset = WHISPER_TTS
            text = _ensure_terminal(seg["content"])
        elif kind == "breathe_guide":
            voice_label = NARRATOR_VOICE
            preset = {"stability": 0.85, "style": 0.0, "speed": 0.72}
            text = seg["content"]
        elif kind == "narration":
            voice_label = NARRATOR_VOICE
            preset = INTRO_TTS if seg.get("section") == "intro" else PHASE_TTS[phase]
            text = seg["content"]
        else:
            return None
        text = normalize_for_tts(text)
        return elevenlabs_tts(
            text, ELEVENLABS_VOICES[voice_label],
            stability=preset["stability"], similarity=0.75,
            style=preset["style"], speed=preset["speed"],
            previous_text=prev, next_text=nxt,
        )

    def stitch(section: str, gap_ms: int):
        out = AudioSegment.silent(duration=0)
        breathes: list[int] = []
        for idx, seg in enumerate(segments):
            if seg.get("section") != section or seg["kind"] == "song":
                continue
            if seg["kind"] == "breathe":
                breathes.append(len(out))
                out += AudioSegment.silent(duration=5000)
                continue
            if seg["kind"] == "breathe_guide":
                rendered = render_seg(idx, seg)
                if rendered is not None:
                    out += AudioSegment.silent(duration=180)
                    out += rendered
                breathes.append(len(out))
                out += AudioSegment.silent(duration=3000)
                continue
            rendered = render_seg(idx, seg)
            if rendered is None:
                continue
            if seg["kind"] in ("narration", "dialogue", "phrase", "whisper"):
                out += AudioSegment.silent(duration=180)
            out += rendered
            if seg["kind"] == "phrase":
                out += AudioSegment.silent(duration=900)
            elif seg["kind"] == "whisper":
                out += AudioSegment.silent(duration=600)
            elif seg["kind"] in ("narration", "dialogue"):
                out += AudioSegment.silent(duration=gap_ms)
        return out, breathes

    intro_music = AudioSegment.from_wav(str(MUSIC_DIR / "intro_calm.wav"))
    bed_raw = AudioSegment.from_wav(str(MUSIC_DIR / "bed_calm.wav"))

    timeline = intro_music + AudioSegment.silent(duration=2000)

    intro_audio, ib = stitch("intro", 300)
    p1_audio, p1b = stitch("phase_1", 300)
    gap_a = AudioSegment.silent(duration=1000)
    part_a_voice = intro_audio + gap_a + p1_audio
    p1_offset = len(intro_audio) + len(gap_a)
    a_breathes = ib + [p + p1_offset for p in p1b]
    part_a_bed = _trim_or_loop(bed_raw, len(part_a_voice)) - 20
    part_a_bed = _apply_breathe_swells(part_a_bed, a_breathes, -20).fade_out(2000)
    timeline += part_a_voice.overlay(part_a_bed)

    timeline += (
        AudioSegment.silent(duration=500)
        + song.fade_in(2000).fade_out(2000)
        + AudioSegment.silent(duration=500)
    )

    post_audio, pb = stitch("post_song", 500)
    p2_audio, p2b = stitch("phase_2", 500)
    gap_b = AudioSegment.silent(duration=1000)
    part_b_voice = post_audio + gap_b + p2_audio
    p2_offset = len(post_audio) + len(gap_b)
    b_breathes = pb + [p + p2_offset for p in p2b]
    part_b_bed = _trim_or_loop(bed_raw, len(part_b_voice)) - 14
    part_b_bed = _apply_breathe_swells(part_b_bed, b_breathes, -14).fade_in(2000)
    timeline += part_b_voice.overlay(part_b_bed)

    p3_audio, p3b = stitch("phase_3", 800)
    p3_bed_full = _trim_or_loop(bed_raw, len(p3_audio) + 30000) - 10
    p3_bed_full = _apply_breathe_swells(p3_bed_full, p3b, -10)
    timeline += p3_audio.overlay(p3_bed_full[:len(p3_audio)])
    timeline += p3_bed_full[len(p3_audio):len(p3_audio) + 30000].fade_out(15000)

    audio = timeline
    duration = round(len(audio) / 1000)

    char_slug = _slug(chars[0]["name"], 4) if chars else _hex(4)
    sid = f"hi-long-{axes['age_group']}-{char_slug}"

    _save_audio(
        audio,
        WEB_ROOT / "public" / "audio" / "pre-gen" / f"{sid}_tripti.mp3",
        BASE_DIR / "seed_output" / "hindi_long" / f"{sid}.mp3",
    )

    cover = _flux_cover(data.get("cover_context", "Indian dreamy bedtime watercolor"))
    if cover:
        cover_paths = [
            WEB_ROOT / "public" / "covers" / f"{sid}.webp",                          # legacy duplicate
            BASE_DIR / "seed_output" / "hindi_long" / f"{sid}_cover.webp",           # debug master
        ]
        if ON_PROD:
            cover_paths.append(PROD_COVER_STORE / f"{sid}.webp")                     # frontend-served
        _save_cover(cover, *cover_paths)

    # Strip tags for display text (use the Roman version for human readability)
    from publish_hindi_long_day1 import strip_long_story_tags  # type: ignore
    display_text = strip_long_story_tags(full_text_for_display)

    entry = {
        "id": sid,
        "type": "long_story",
        "lang": "hi",
        "language": "hi",
        "story_format": "long_story",
        "story_type": "long_story",
        "storyType": "long_story",
        "title": data["title"],
        "title_en": data["title_en"],
        "description": data["world_description"],
        "description_en": data["world_description_en"],
        "world_name": data["world_name"],
        "world_name_en": data["world_name_en"],
        "world_description": data["world_description"],
        "mystery": data["mystery"],
        "resolution": data["resolution"],
        "breathing_mechanic": data["breathing_mechanic"],
        "repeated_phrase": data["repeated_phrase"],
        "characters": chars,
        "song_seed": data["song_seed"],
        "phase_1_text": shape(data)["phase_1_text_roman"],
        "phase_2_text": shape(data)["phase_2_text_roman"],
        "phase_3_text": shape(data)["phase_3_text_roman"],
        "text": display_text,
        "text_deva": data.get("full_text_deva", ""),
        "raw_text": full_text_for_display,
        "raw_text_deva": data.get("full_text_deva", ""),
        "tts_input_script": "devanagari",
        "character": {
            "name": chars[0]["name"] if chars else "",
            "identity": chars[0].get("identity", "") if chars else "",
        },
        "character_name": chars[0]["name"] if chars else "",
        "characterType": axes["characterType"],
        "lead_character_type": axes["characterType"],
        "age_group": axes["age_group"],
        "ageGroup": axes["age_group"],
        "age_min": int(axes["age_group"].split("-")[0]),
        "age_max": int(axes["age_group"].split("-")[1]),
        "mood": axes["mood"],
        "theme": "rest",
        "themes": ["rest"],
        "experimental_v2": False,
        "has_baked_music": True,
        "tts_engine": "elevenlabs-multilingual-v2",
        "voice_routing": {
            "narrator": NARRATOR_VOICE,
            "whisper": WHISPER_VOICE,
            "characters": char_voice,
        },
        "audio_url": f"/audio/pre-gen/{sid}_tripti.mp3",
        "audio_variants": [{
            "voice": "tripti",
            "url": f"/audio/pre-gen/{sid}_tripti.mp3",
            "duration_seconds": duration,
            "provider": "elevenlabs-multilingual-v2",
        }],
        "cover": f"/covers/{sid}.webp" if cover else "/covers/default.svg",
        "cover_context": data.get("cover_context", ""),
        "duration_seconds": duration,
        "durationSec": duration,
        "embedded_song_seconds": round(len(song) / 1000),
        "is_generated": True,
        "author_id": "system",
        "categories": ["Bedtime", "Long Story"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _attach_qa_changes(entry, data)
    # Per spec §2g.1: per-content file write (additive — walker reads this
    # post-cutover). _upsert_content below stays until post-cutover §4 step 15.
    _write_per_content_file(entry)
    _upsert_content(entry)
    print(f"{log_prefix}✓ long story published: {sid} ({duration}s)")
    return entry


# ───────────────────────────────────────────────────────────────────────
# Funny short (v3 dialogue) — wraps the standalone orchestrator
# ───────────────────────────────────────────────────────────────────────

def generate_funny_short(axes: dict, log_prefix: str = "  ") -> dict:
    """Hindi funny short — wraps the standalone
    generate_funny_shorts_hi.py orchestrator. The orchestrator handles
    its own internal diversity sampling (voice pair, comedic device,
    setting, tone, opening tag, character age dynamic), validates
    Devanagari + standalone-laughter requirements, renders via v3
    Text-to-Dialogue with Devanagari engine input, frames with stings,
    auto-mirrors into content.json, and syncs audio to nginx + audio-store.
    """
    import subprocess as _sp
    base = Path(__file__).resolve().parents[1]
    age = axes.get("age_group", "6-8")

    # 1. Script + audio + auto-mirror
    print(f"{log_prefix}generate_funny_shorts_hi --age {age}…")
    r = _sp.run(
        ["python3", "scripts/generate_funny_shorts_hi.py", "--age", age],
        cwd=base, capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"generate_funny_shorts_hi failed (exit {r.returncode}):\n"
            f"  stdout tail: {(r.stdout or '')[-400:]}\n"
            f"  stderr tail: {(r.stderr or '')[-400:]}"
        )
    short_id = None
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if "data/funny_shorts_hi/" in line and ".json" in line:
            fname = line.split("data/funny_shorts_hi/")[-1].split(".json")[0]
            if fname.startswith("hi-fs-"):
                short_id = fname
                break
    if not short_id:
        raise RuntimeError(
            "generate_funny_shorts_hi succeeded but no id parsed from stdout"
        )

    # 2. Cover via FLUX (best-effort — audio is the primary deliverable)
    print(f"{log_prefix}generate_funny_short_cover for {short_id}…")
    cov = _sp.run(
        ["python3", "scripts/generate_funny_short_cover.py",
         "--story-json", f"data/funny_shorts_hi/{short_id}.json"],
        cwd=base, capture_output=True, text=True, timeout=180,
    )
    if cov.returncode != 0:
        print(f"{log_prefix}cover failed (audio ok): {(cov.stderr or '')[-200:]}")

    # 3. Build entry from the persisted JSON
    short = json.loads(
        (base / "data" / "funny_shorts_hi" / f"{short_id}.json").read_text()
    )
    return {
        "id": short["id"],
        "type": "funny_short",
        "subtype": "funny_short",
        "lang": "hi",
        "title": short.get("title", ""),
        "title_en": short.get("title_en", ""),
        "duration_seconds": short.get("duration_seconds", 0),
        "audio_url": short.get("audio_url"),
        "cover": short.get("cover"),
    }


# ───────────────────────────────────────────────────────────────────────
# Dispatcher
# ───────────────────────────────────────────────────────────────────────

GENERATORS = {
    "short_story": generate_short_story,
    "long_story":  generate_long_story,
    "lullaby":     generate_lullaby,
    "silly_song":  generate_silly_song,
    "poem":        generate_poem,
    "funny_short": generate_funny_short,
}
