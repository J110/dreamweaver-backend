"""Hindi QA Critic — Groq-powered second-pass reviewer.

Sits between Mistral content generation and the audio render pipeline.
Catches semantic gaps the regex validator misses (embedded dialogue,
register slips, missing onomatopoeia in natural-sounding spots, ...)
and patches mechanical issues without triggering full regeneration.

Architecture (per design doc HINDI_DAILY_PIPELINE.md §QA-Layer):

    Mistral content → regex validator → IF errors:
      ├─ any MAJOR  → regenerate
      └─ all MINOR  → ONE Groq attempt:
                       ├─ action="fix"           → re-validate; if pass → ship; else regen
                       ├─ action="pass_override" → log + ship + flag for human audit
                       └─ action="regenerate"    → regen with reason

    If Groq's fix introduces new errors, we DO NOT call Groq again
    (single-attempt rule per generation prevents whack-a-mole).

Model choice: Groq Llama 3.3 70B (`llama-3.3-70b-versatile`).
Rationale (rejected alternatives in parens):
  - Cost: ~$0.001/call vs ~$0.05 Claude Haiku, ~$0.05 Mistral Large.
  - Speed: 2-3s vs 8-15s on alternatives.
  - JSON mode: supported (clean structured output).
  - Distinct from generator (Mistral): different blind spots, so a
    second pass actually catches what the first one missed. Using
    Mistral-as-reviewer would inherit the same misreadings.
  - 70B size is enough for this task (instruction following on a
    bounded JSON-edit problem; not creative generation).

Allow / deny lists (per content type) gate which fields Groq can
touch. Plus a 30 % edit-distance hard cap as a final safety net.

Toggle on prod with HINDI_QA_ENABLED=true. Per-type rollout via
HINDI_QA_TYPES (comma-separated). Default OFF until validated.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

# ── Module imports (with sys.path insert so this works standalone) ─────
import sys
sys.path.insert(0, str(Path(__file__).parent))
from _hindi_llm import _call_provider, GROQ_ENDPOINT, GROQ_MODEL, GROQ_KEY  # type: ignore
from _hindi_validators import validate_structured, has_major  # type: ignore


# ───────────────────────────────────────────────────────────────────────
# Allow / deny lists per content type
# ───────────────────────────────────────────────────────────────────────
# Field paths use simple JSONPath-ish notation:
#   "characters[*].identity"  matches every character's identity
#   "diversityFingerprint.*"  matches any field under diversityFingerprint
# Anything not in ALLOW is implicitly DENY.

ALLOW_LIST: dict[str, list[str]] = {
    "short_story": [
        "text",                # tag insertion, dialogue reformatting,
                                # onomatopoeia & conv-marker insertion
        "text_deva",           # mirror Devanagari same edits
        "raw_text",
        "raw_text_deva",
        "morals",              # missing-field fill from context
        "categories",
        "diversityFingerprint", # fill missing keys; do NOT change set values
        "hook",
        "hook_deva",
    ],
    "long_story": [
        "phase_1_text", "phase_2_text", "phase_3_text",
        "text", "text_deva", "raw_text", "raw_text_deva",
        "full_text_roman", "full_text_deva",
        "morals",
        "categories",
        "song_seed",           # one-sentence; can rewrite if too vague
    ],
    "lullaby": [
        "lyrics", "lyrics_deva", "text", "text_deva",
        "card_subtitle",
        "instruments",
    ],
    "silly_song": [
        "lyrics", "lyrics_deva",
        "card_subtitle",
        "instruments",
    ],
    "poem": [
        "poem_text", "poem_text_deva", "text", "text_deva",
        "instruments",
    ],
}

# Fields the critic must NEVER edit, regardless of content type
DENY_LIST_GLOBAL: list[str] = [
    "id",
    "lang", "language",
    "title", "title_deva", "title_en",
    "world_name", "world_name_en",       # long story
    "repeated_phrase", "repeated_phrase_deva",
    "characters",                          # never rename or add/remove characters
    "character", "character_name",
    "characterType", "lead_character_type",
    "anthem_id", "anthem",                # silly song
    "lullaby_type", "story_type", "poem_type",
    "age_group", "age_min", "age_max", "target_age",
    "mood", "tempo",
    "voice_routing",                       # orchestrator owns this
    "audio_engine", "tts_engine", "model_id",
    "audio_url", "audio_variants",         # set by save_*
    "cover", "cover_file", "cover_context",
    "duration_seconds", "durationSec",
    "created_at", "updated_at",
    "author_id", "is_generated",
    "experimental_v2", "has_baked_music",
    "tts_input_script",
]

# Hard cap on aggregate edit distance regardless of which fields changed.
# Below this threshold, allow/deny governs. Above, treat as regenerate.
MAX_EDIT_RATIO = 0.30


# ───────────────────────────────────────────────────────────────────────
# System prompt — the heart of the critic
# ───────────────────────────────────────────────────────────────────────
# Explicit allow/deny + behavioral guard rails. Reviewed before any
# implementation lands. See HINDI_DAILY_PIPELINE.md §QA-Layer.

SYSTEM_PROMPT = """You are a senior editor reviewing children's bedtime story content for the Dream Valley app. Your job is NOT to rewrite or improve the story. Your job is to make targeted, minimal edits to fix specific validator failures while preserving everything else exactly as written.

PRESERVE EXACTLY:
- Every character name and identity (do not rename)
- Every plot beat and narrative structure
- The overall tone, pacing, and word count (changes ≤ 10%)
- The repeated_phrase exactly as written (never edit)
- The world_name and setting
- The title and title_en
- All metadata: age_group, mood, characterType, lullaby_type, etc.
- Voice routing — never edit characters[].name or characters[].gender

YOU MAY EDIT (when fixing a flagged minor error):
- Insert structural tags: [MUSIC], [PAUSE: 800/1200/1500], [PHRASE]...[/PHRASE], [BREATHE]
- Reformat dialogue from embedded ("X ne kaha, '...'") to NAME: "..." form
  • Reformatting only — do NOT add new dialogue lines or expand quote text
  • Total dialogue word count must not increase by more than 10%
- Add onomatopoeia where natural: sarr sarr, tap tap, chhap chhap, dheere dheere,
  gunghun, jhoom, tip tip, khat khat, patak, thak thak
- Add conversational markers where natural: na, toh, pata hai, bas, suno, dekho,
  achha, arre, zara, hai na, aur phir
- Fill missing optional metadata fields: morals, categories
  (only when ABSENT from the content, never to overwrite existing)

YOU MUST NEVER:
- Rename, add, or remove any character
- Change the title, world_name, or repeated_phrase
- Add or remove plot beats
- Change which character speaks a line (only reformat the structure)
- Invent new dialogue (if a character has zero dialogue, that's a regen — not a fix)
- Edit fields not listed in your allow-list (especially: characters, voice_routing,
  characterType, audio_*, cover_*, id, lang, mood, age_group)
- Increase total story word count by more than 10%
- Change the diversityFingerprint values that Mistral set
  (you may FILL missing keys with conservative defaults, but do not OVERWRITE
  existing keys — they feed downstream sampling)

DECISION RULES:

1. If all flagged errors are mechanically fixable within your edit rules above
   AND the fix doesn't violate any "must never" constraint:
   → action: "fix" with patched content + summary_of_changes

2. If a flagged error requires a forbidden change (renaming a character to fix
   a blacklisted name, fabricating dialogue for a character with zero quotes,
   restructuring phases that are out of order, or any major-severity error):
   → action: "regenerate" with regen_reason

3. If you read the content and believe a flagged error is a false positive
   (validator misclassified, e.g. flagged "ram " in "naram" but you can see
   from context it's the soft-bedding word, not the deity):
   → action: "pass_override" with justification (will be logged for human audit)

EDIT MAGNITUDE:
- Targeted edits ≤ 30% of total content text length.
- Larger rewrites are likely changing the story essence — choose regenerate.

OUTPUT (JSON only, no commentary):
{
  "action": "fix" | "pass_override" | "regenerate",
  "fixed_content": <full content JSON, identical to input except for the targeted edits — only when action="fix">,
  "summary_of_changes": [<one short string per edit>],
  "regen_reason": <one sentence — only when action="regenerate">,
  "justification": <one sentence — only when action="pass_override">
}
"""


# ───────────────────────────────────────────────────────────────────────
# Allow/deny enforcement
# ───────────────────────────────────────────────────────────────────────

def _matches_pattern(field_path: str, pattern: str) -> bool:
    """Match a JSONPath-ish pattern: 'a.b', 'a.*', 'a[*].b'."""
    pat = pattern.replace("[*]", "\\[\\d+\\]").replace(".", "\\.").replace("\\.\\*", "\\..+")
    return bool(re.fullmatch(pat, field_path))


def _flatten(obj, prefix: str = "") -> dict[str, object]:
    """Flatten a nested dict to {field_path: value}."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, sub))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            sub = f"{prefix}[{i}]"
            out.update(_flatten(v, sub))
    else:
        out[prefix] = obj
    return out


def _diff_changed_paths(original: dict, fixed: dict) -> list[str]:
    """Return list of dotted/indexed paths whose values changed."""
    o = _flatten(original)
    f = _flatten(fixed)
    changed = []
    for k in set(o) | set(f):
        if o.get(k) != f.get(k):
            changed.append(k)
    return changed


def _violation_in_changes(changed_paths: list[str], content_type: str) -> list[str]:
    """Return list of changed paths that violate allow/deny rules."""
    allow = ALLOW_LIST.get(content_type, [])
    violations = []
    for path in changed_paths:
        # Top-level field name (e.g. "text" from "text" or "characters[0].name")
        top = path.split(".")[0].split("[")[0]
        # Deny-list check
        if top in DENY_LIST_GLOBAL:
            violations.append(path)
            continue
        # Allow-list check (any allow-pattern matches the path or its prefix)
        if not any(
            _matches_pattern(path, p) or _matches_pattern(top, p)
            or path.startswith(p) for p in allow
        ):
            violations.append(path)
    return violations


def _edit_ratio(original: dict, fixed: dict) -> float:
    """Aggregate Levenshtein-ish edit ratio over JSON-serialized content."""
    a = json.dumps(original, sort_keys=True, ensure_ascii=False)
    b = json.dumps(fixed, sort_keys=True, ensure_ascii=False)
    if not a:
        return 0.0
    matcher = difflib.SequenceMatcher(None, a, b)
    return 1.0 - matcher.ratio()


# ───────────────────────────────────────────────────────────────────────
# Main critic entry point
# ───────────────────────────────────────────────────────────────────────

def is_qa_enabled(content_type: str) -> bool:
    """Gated by HINDI_QA_ENABLED + HINDI_QA_TYPES env vars."""
    if os.getenv("HINDI_QA_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return False
    types = os.getenv("HINDI_QA_TYPES", "short_story")
    return content_type in [t.strip() for t in types.split(",")]


def critic_review(
    *, content: dict, errors: list[dict], content_type: str,
    log_prefix: str = "    ",
) -> dict:
    """Send Mistral's content + validator errors to Groq; get fix/regen decision.

    Returns:
      {
        "action": "fix"|"pass_override"|"regenerate"|"skip"|"invalid",
        "fixed_content": dict | None,
        "summary_of_changes": list[str],
        "regen_reason": str | None,
        "justification": str | None,
        "diagnostics": list[str],   # things that prevented apply (e.g. allow-list violation)
        "elapsed_ms": int,
      }
    """
    diagnostics: list[str] = []
    started = time.time()

    if not GROQ_KEY:
        return {
            "action": "skip",
            "fixed_content": None,
            "summary_of_changes": [],
            "regen_reason": None,
            "justification": None,
            "diagnostics": ["GROQ_KEY missing"],
            "elapsed_ms": 0,
        }

    user_msg = (
        f"Content type: {content_type}\n\n"
        f"VALIDATOR ERRORS (severity-tagged):\n"
        f"{json.dumps(errors, indent=2, ensure_ascii=False)}\n\n"
        f"CONTENT (Mistral output):\n"
        f"{json.dumps(content, indent=2, ensure_ascii=False)}\n\n"
        "Review per the rules in your system instructions and output JSON."
    )

    try:
        raw = _call_provider(
            endpoint=GROQ_ENDPOINT,
            api_key=GROQ_KEY,
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,        # deterministic editor, low creativity
            max_tokens=12_000,      # may need to echo full content
            want_json=True,
            timeout=120,
        )
    except Exception as e:
        diagnostics.append(f"Groq call failed: {e}")
        return {
            "action": "skip",
            "fixed_content": None,
            "summary_of_changes": [],
            "regen_reason": None,
            "justification": None,
            "diagnostics": diagnostics,
            "elapsed_ms": int((time.time() - started) * 1000),
        }

    try:
        result = json.loads(raw.strip().lstrip("`").lstrip("json").strip().rstrip("`"))
    except json.JSONDecodeError as e:
        diagnostics.append(f"non-JSON Groq output: {e}; raw[:200]={raw[:200]!r}")
        return {
            "action": "invalid",
            "fixed_content": None,
            "summary_of_changes": [],
            "regen_reason": None,
            "justification": None,
            "diagnostics": diagnostics,
            "elapsed_ms": int((time.time() - started) * 1000),
        }

    action = result.get("action", "regenerate")
    elapsed_ms = int((time.time() - started) * 1000)
    print(f"{log_prefix}critic action={action} ({elapsed_ms}ms)")

    if action == "fix":
        fixed = result.get("fixed_content")
        if not isinstance(fixed, dict):
            diagnostics.append("action=fix but fixed_content not a dict — treating as regenerate")
            return {
                "action": "regenerate",
                "fixed_content": None,
                "summary_of_changes": [],
                "regen_reason": "critic returned malformed fix",
                "justification": None,
                "diagnostics": diagnostics,
                "elapsed_ms": elapsed_ms,
            }

        # Allow/deny enforcement
        changed = _diff_changed_paths(content, fixed)
        violations = _violation_in_changes(changed, content_type)
        if violations:
            diagnostics.append(
                f"critic violated allow/deny on {len(violations)} fields: {violations[:6]}"
            )
            print(f"{log_prefix}  rejected: {len(violations)} forbidden field changes")
            return {
                "action": "regenerate",
                "fixed_content": None,
                "summary_of_changes": [],
                "regen_reason": "critic edited forbidden fields",
                "justification": None,
                "diagnostics": diagnostics,
                "elapsed_ms": elapsed_ms,
            }

        # 30% edit-ratio cap
        ratio = _edit_ratio(content, fixed)
        if ratio > MAX_EDIT_RATIO:
            diagnostics.append(
                f"critic edit ratio {ratio:.1%} > {MAX_EDIT_RATIO:.0%} cap"
            )
            print(f"{log_prefix}  rejected: edit ratio {ratio:.1%} too large")
            return {
                "action": "regenerate",
                "fixed_content": None,
                "summary_of_changes": [],
                "regen_reason": f"critic edit ratio {ratio:.1%} exceeded cap",
                "justification": None,
                "diagnostics": diagnostics,
                "elapsed_ms": elapsed_ms,
            }

        # Re-validate the fix
        new_errors = validate_structured(content_type, fixed)
        if has_major(new_errors):
            diagnostics.append(
                f"critic fix introduced major errors: {[e['detail'] for e in new_errors if e['severity'] == 'major'][:3]}"
            )
            print(f"{log_prefix}  rejected: fix introduced major errors")
            return {
                "action": "regenerate",
                "fixed_content": None,
                "summary_of_changes": [],
                "regen_reason": "critic fix introduced new major errors",
                "justification": None,
                "diagnostics": diagnostics,
                "elapsed_ms": elapsed_ms,
            }
        if new_errors:
            print(f"{log_prefix}  fix incomplete (still {len(new_errors)} minor errors); regenerate")
            return {
                "action": "regenerate",
                "fixed_content": None,
                "summary_of_changes": result.get("summary_of_changes", []),
                "regen_reason": f"critic fix left {len(new_errors)} minor errors unresolved",
                "justification": None,
                "diagnostics": diagnostics,
                "elapsed_ms": elapsed_ms,
            }

        # All checks passed
        return {
            "action": "fix",
            "fixed_content": fixed,
            "summary_of_changes": result.get("summary_of_changes", []),
            "regen_reason": None,
            "justification": None,
            "diagnostics": diagnostics,
            "elapsed_ms": elapsed_ms,
        }

    if action == "pass_override":
        return {
            "action": "pass_override",
            "fixed_content": None,
            "summary_of_changes": [],
            "regen_reason": None,
            "justification": result.get("justification", "(no justification provided)"),
            "diagnostics": diagnostics,
            "elapsed_ms": elapsed_ms,
        }

    return {  # action == "regenerate" or anything else
        "action": "regenerate",
        "fixed_content": None,
        "summary_of_changes": [],
        "regen_reason": result.get("regen_reason", "(critic chose regenerate)"),
        "justification": None,
        "diagnostics": diagnostics,
        "elapsed_ms": elapsed_ms,
    }
