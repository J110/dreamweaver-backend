#!/usr/bin/env python3
"""Generate one English funny short (script + audio + cover registration).

Usage:
  python3 scripts/generate_funny_shorts.py --age 6-8 [--dry-run]

Steps:
  1. Sample diversity axes excluding recent shorts.
  2. Sample voice pair excluding last 3.
  3. Build Mistral prompt and request a script.
  4. Validate (up to 3 attempts).
  5. Render via ElevenLabs v3 dialogue.
  6. Frame with intro+outro stings.
  7. Persist to data/funny_shorts/{id}.json + write MP3.
  8. Auto-mirror into seed_output/content.json.
  9. Print follow-up commands (cover, reload).
"""

import argparse
import io
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _funny_shorts_common import (  # noqa: E402
    APPROVED_PAIRINGS_EN,
    CHARACTER_AGE_DYNAMICS,
    COMEDIC_DEVICES,
    EMOTIONAL_DYNAMICS_EN,
    OPENING_TAGS,
    SETTINGS_EN,
    TONES,
    VOICE_LIBRARY_EN,
    _detect_closing_pattern,
    _extract_first_tag,
    build_prompt,
    frame_dialogue_with_stings,
    render_dialogue_v3,
    sample_axis_excluding_recent,
    sample_voice_pair,
    validate_funny_short,
)

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data" / "funny_shorts"
AUDIO_DIR = BASE / "public" / "audio" / "funny-shorts"
STINGS = Path("/opt/audio-store/stings")
STINGS_LOCAL_FALLBACK = BASE / "public" / "audio" / "stings"

# Prod nginx-served paths (no-op locally if absent)
WEB_AUDIO_DIR = Path("/opt/dreamweaver-web/public/audio/funny-shorts")
AUDIO_STORE_DIR = Path("/opt/audio-store/funny-shorts")

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _sync_to_prod_paths(audio_path: Path) -> None:
    """Copy generated audio to nginx-served + audio-store paths if they exist."""
    import shutil
    for dst_dir in (WEB_AUDIO_DIR, AUDIO_STORE_DIR):
        if dst_dir.exists():
            shutil.copy2(audio_path, dst_dir / audio_path.name)
            print(f"  synced → {dst_dir / audio_path.name}")


def _resolve_stings(lang: str) -> tuple[Path, Path]:
    for base in (STINGS, STINGS_LOCAL_FALLBACK):
        intro = base / f"funny_short_intro_{lang}.mp3"
        outro = base / f"funny_short_outro_{lang}.mp3"
        if intro.exists() and outro.exists():
            return intro, outro
    raise FileNotFoundError(
        f"Stings not found at {STINGS} or {STINGS_LOCAL_FALLBACK}. "
        f"Run scripts/generate_funny_shorts_stings.py --lang {lang} first."
    )


def _load_recent(lang: str, n: int = 10) -> list[dict]:
    items: list[dict] = []
    if DATA_DIR.exists():
        for f in sorted(DATA_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if d.get("lang") == lang:
                items.append(d)
    items.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return items[:n]


def _summarize_recent(recent: list[dict]) -> str:
    if not recent:
        return "(none — this is the first short)"
    lines = []
    for i, s in enumerate(recent, 1):
        lines.append(
            f"{i}. \"{s.get('title','?')}\" — device={s.get('comedic_device','?')}, "
            f"setting={s.get('setting','?')}, opening={s.get('opening_tag','?')}"
        )
    return "\n".join(lines)


def _new_id() -> str:
    return f"en-fs-{secrets.token_hex(2)}"


def _voice_personality(label: str) -> str:
    return {
        "mini":      "lively cute young female, bright and cheerful",
        "katherine": "eccentric mad-scientist energy, comedic-villain playful",
        "suhana":    "very young, joyful, full of innocence",
        "tashi":     "expressive bright dramatic kid energy",
        "kiran_en":  "very young, cute, sweet, warmly engaging",
        "omar":      "very young storyteller, innocent and wise",
    }.get(label, "")


def request_mistral_script(prompt: str) -> dict:
    """Call Mistral and return the parsed JSON script."""
    api_key = os.environ["MISTRAL_API_KEY"]
    body = {
        "model": "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.85,  # below JSON-mode reliability cliff
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=120) as c:
        r = c.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
        r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def _auto_mirror(short_id: str) -> None:
    """Append entry into seed_output/content.json (flat list). Replaces if id exists."""
    src = DATA_DIR / f"{short_id}.json"
    short = json.loads(src.read_text())
    seed_content = BASE / "seed_output" / "content.json"
    if not seed_content.exists():
        print(f"  (no {seed_content} — skipping mirror)")
        return
    content = json.loads(seed_content.read_text())
    # content.json is a flat list of entries, not a dict
    if isinstance(content, dict):
        items = content.setdefault("items", [])
    else:
        items = content
    items = [i for i in items if i.get("id") != short_id]
    items.append({
        "id": short["id"],
        "type": "song",
        "subtype": "funny_short",
        "lang": short.get("lang", "en"),
        "language": short.get("language", "en"),
        "title": short.get("title", ""),
        "title_en": short.get("title_en", ""),
        "age_group": short.get("age_group", "6-8"),
        "duration_seconds": short.get("duration_seconds", 0),
        "audio_file": short.get("audio_file"),
        "audio_url": short.get("audio_url"),
        "cover": short.get("cover"),
        "created_at": short.get("created_at", ""),
    })
    if isinstance(content, dict):
        content["items"] = items
        out = content
    else:
        out = items
    seed_content.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  Mirrored into {seed_content}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", default="6-8", choices=["2-5", "6-8", "9-12"])
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate + validate script only; do not render audio")
    args = ap.parse_args()

    lang = "en"
    recent = _load_recent(lang)

    pair = sample_voice_pair(
        APPROVED_PAIRINGS_EN,
        [tuple(r.get("voice_pair", [])) for r in recent if r.get("voice_pair")],
        seed=int(time.time()),
    )
    voice_a_label, voice_b_label = pair
    voice_a_id = VOICE_LIBRARY_EN[voice_a_label]
    voice_b_id = VOICE_LIBRARY_EN[voice_b_label]

    seed = int(time.time())
    device = sample_axis_excluding_recent(
        COMEDIC_DEVICES, [r.get("comedic_device") for r in recent], 5, seed=seed,
    )
    dynamic = sample_axis_excluding_recent(
        EMOTIONAL_DYNAMICS_EN, [r.get("emotional_dynamic") for r in recent], 3, seed=seed + 1,
    )
    setting = sample_axis_excluding_recent(
        SETTINGS_EN, [r.get("setting") for r in recent], 3, seed=seed + 2,
    )
    tone = sample_axis_excluding_recent(
        TONES, [r.get("tone") for r in recent], 3, seed=seed + 3,
    )
    opening_tag = sample_axis_excluding_recent(
        OPENING_TAGS, [r.get("opening_tag") for r in recent], 3, seed=seed + 4,
    )
    age_dynamic = sample_axis_excluding_recent(
        CHARACTER_AGE_DYNAMICS, [r.get("character_age_dynamic") for r in recent], 3, seed=seed + 5,
    )

    print(f"\nVoice pair: {voice_a_label} + {voice_b_label}")
    print(f"Device: {device} | Dynamic: {dynamic} | Setting: {setting}")
    print(f"Tone: {tone} | Opening: {opening_tag} | Age dyn: {age_dynamic}\n")

    prompt = build_prompt(
        lang=lang,
        voice_a_label=voice_a_label,
        voice_a_personality=_voice_personality(voice_a_label),
        voice_b_label=voice_b_label,
        voice_b_personality=_voice_personality(voice_b_label),
        comedic_device=device,
        emotional_dynamic=dynamic,
        setting=setting,
        tone=tone,
        required_opening_tag=opening_tag,
        recent_shorts_summary=_summarize_recent(recent),
        over_used_phrases_to_avoid="",
        character_age_dynamic=age_dynamic,
    )

    script = None
    last_errors: list[str] = []
    for attempt in range(5):
        if attempt > 0:
            time.sleep(35)  # free tier 2 req/min, leave buffer
        print(f"Mistral attempt {attempt + 1}...")
        try:
            candidate = request_mistral_script(prompt)
        except Exception as e:
            print(f"  Mistral request failed: {e}")
            continue
        candidate["lang"] = "en"
        candidate["comedic_device"] = device
        candidate["emotional_dynamic"] = dynamic
        candidate["setting"] = setting
        candidate["tone"] = tone
        candidate["opening_tag"] = (
            _extract_first_tag(candidate["inputs"][0]["text"])
            if candidate.get("inputs") else opening_tag
        )
        candidate["closing_pattern"] = _detect_closing_pattern(candidate.get("inputs", []))
        candidate["voice_pair"] = [voice_a_label, voice_b_label]
        candidate["age_group"] = args.age
        candidate["character_age_dynamic"] = age_dynamic
        candidate["required_opening_tag"] = opening_tag
        last_errors = validate_funny_short(candidate, recent_shorts=recent, lang=lang)
        if not last_errors:
            script = candidate
            break
        print(f"  validation failed: {last_errors}")

    if script is None:
        print(f"ERROR: failed validation after 3 attempts: {last_errors}", file=sys.stderr)
        return 1

    print(f"\n✓ Validated. Title: {script['title']}")
    print(f"  Lines: {len(script['inputs'])}, total chars: {sum(len(i['text']) for i in script['inputs'])}")

    if args.dry_run:
        print(json.dumps(script, indent=2))
        return 0

    print("\nRendering v3 dialogue...")
    dialogue_bytes = render_dialogue_v3(script["inputs"], voice_a_id, voice_b_id)

    intro_path, outro_path = _resolve_stings(lang)
    print(f"Framing with stings: {intro_path.name}, {outro_path.name}")
    framed = frame_dialogue_with_stings(dialogue_bytes, intro_path, outro_path, gap_ms=1000)

    short_id = _new_id()
    audio_path = AUDIO_DIR / f"{short_id}.mp3"
    audio_path.write_bytes(framed)

    from pydub import AudioSegment as _A
    seg = _A.from_mp3(io.BytesIO(framed))
    duration_seconds = round(len(seg) / 1000)

    entry = {
        "id": short_id,
        "lang": "en",
        "language": "en",
        "type": "song",
        "subtype": "funny_short",
        "title": script["title"],
        "age_group": args.age,
        "duration_seconds": duration_seconds,
        "voice_pair": [voice_a_label, voice_b_label],
        "comedic_device": device,
        "emotional_dynamic": dynamic,
        "setting": setting,
        "tone": tone,
        "opening_tag": script["opening_tag"],
        "closing_pattern": script["closing_pattern"],
        "character_age_dynamic": age_dynamic,
        "line_count": len(script["inputs"]),
        "inputs": script["inputs"],
        "audio_file": f"{short_id}.mp3",
        "audio_url": f"/audio/funny-shorts/{short_id}.mp3",
        "cover": f"/covers/funny-shorts/{short_id}_cover.webp",
        "cover_context": script.get("cover_context", ""),
        "audio_engine": "elevenlabs-v3-dialogue",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "play_count": 0,
        "replay_count": 0,
    }

    json_path = DATA_DIR / f"{short_id}.json"
    json_path.write_text(json.dumps(entry, indent=2))

    print(f"\n✓ Wrote:")
    print(f"  {json_path}")
    print(f"  {audio_path}  ({duration_seconds}s)")

    _sync_to_prod_paths(audio_path)
    _auto_mirror(short_id)

    print(f"\nNext steps:")
    print(f"  Cover:  python3 scripts/generate_cover_experimental.py --story-json {json_path}")
    print(f"  Reload: curl -X POST https://api.dreamvalley.app/api/v1/admin/reload \\")
    print(f"            -H \"X-Admin-Key: $ADMIN_API_KEY\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
