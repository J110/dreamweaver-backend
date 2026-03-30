#!/usr/bin/env python3
"""
Assemble "Moonlight on the Lake" with bed + swell approach.

Generates:
  1. 3-minute ambient bed (CassetteAI → MusicGen fallback)
  2. TTS per chunk with hook/normal/phrase params
  3. Mixed audio: narration over shaped bed with swells

Usage:
    python3 scripts/assemble_frog_story.py
"""

import io
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from pydub import AudioSegment
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

AUDIO_DIR = BASE_DIR / "audio" / "pre-gen"
MUSIC_DIR = BASE_DIR / "audio" / "story_music"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

CHATTERBOX_URL = "https://mohan-32314--dreamweaver-chatterbox-tts.modal.run"
FAL_KEY = os.getenv("FAL_KEY", "")
MOOD_VOICES = ["female_1", "asmr"]

STORY_ID = "gen-041123d72402"
SHORT_ID = STORY_ID[:8]

# ── TTS parameter sets ───────────────────────────────────────────────

NORMAL_PARAMS = {"exaggeration": 0.45, "speed": 0.85, "cfg_weight": 0.5}
HOOK_PARAMS = {"exaggeration": 0.55, "speed": 0.82, "cfg_weight": 0.45}
PHRASE_PARAMS = {"exaggeration": 0.60, "speed": 0.78, "cfg_weight": 0.42}

# ── Music prompts ────────────────────────────────────────────────────

BED_PROMPT = (
    "3 minute ambient background for a children's bedtime story, "
    "soft music box and gentle harp, very quiet, extremely minimal, "
    "water-inspired, like moonlight on a still lake, "
    "same 3-4 notes repeating slowly with long pauses between them, "
    "55 BPM, warm, peaceful, almost not there, "
    "the kind of music you feel more than hear"
)

INTRO_PROMPT = (
    "6 second gentle calm intro, soft music box, "
    "3-4 simple descending notes, already peaceful, "
    "60 BPM, warm, like a sigh of contentment, pulling up a blanket"
)

OUTRO_PROMPT = (
    "45 second sleep outro, same music box but even slower, "
    "notes further apart, descending, last note rings for "
    "5 seconds and fades, 60 BPM slowing to 35 BPM, "
    "calm becoming fully asleep, gentlest possible fade"
)


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def generate_tts(text: str, voice: str, exaggeration: float = 0.45,
                 cfg_weight: float = 0.5, speed: float = 0.85) -> AudioSegment:
    """Call Chatterbox TTS, return AudioSegment."""
    params = {
        "text": text, "voice": voice, "lang": "en",
        "exaggeration": exaggeration, "cfg_weight": cfg_weight,
        "speed": speed, "format": "wav",
    }
    url = f"{CHATTERBOX_URL}?{urlencode(params)}"
    with httpx.Client() as client:
        for attempt in range(3):
            try:
                resp = client.get(url, timeout=180.0)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return AudioSegment.from_wav(io.BytesIO(resp.content))
                print(f"    TTS {resp.status_code}: {resp.text[:80]}")
            except Exception as e:
                print(f"    TTS error: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"TTS failed for voice={voice}")


def generate_bed_cassetteai() -> AudioSegment:
    """Generate 3-min ambient bed via CassetteAI Music on fal.ai."""
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    client = httpx.Client(timeout=300)

    print("  Submitting to CassetteAI Music...")
    resp = client.post(
        "https://queue.fal.run/cassetteai/music-generator",
        headers=headers,
        json={"prompt": BED_PROMPT, "duration": 180},
    )
    data = resp.json()
    if "request_id" not in data:
        raise RuntimeError(f"CassetteAI submit failed: {data}")

    rid = data["request_id"]
    start = time.time()
    while True:
        time.sleep(4)
        sr = client.get(
            f"https://queue.fal.run/cassetteai/music-generator/requests/{rid}/status",
            headers=headers,
        ).json()
        status = sr.get("status")
        elapsed = time.time() - start
        print(f"    [{elapsed:.0f}s] {status}")
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"CassetteAI failed: {sr}")

    result = client.get(
        f"https://queue.fal.run/cassetteai/music-generator/requests/{rid}",
        headers=headers,
    ).json()

    audio_url = None
    for key in ("audio_file", "audio", "output"):
        if key in result:
            v = result[key]
            audio_url = v.get("url") if isinstance(v, dict) else v
            if audio_url:
                break

    if not audio_url:
        raise RuntimeError(f"No audio URL: {list(result.keys())}")

    audio_data = client.get(audio_url).content
    print(f"    Downloaded: {len(audio_data):,} bytes")
    return AudioSegment.from_file(io.BytesIO(audio_data))


def generate_bed_musicgen() -> AudioSegment:
    """Fallback: Generate bed via MusicGen on Modal T4."""
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    gen = gen_cls()
    print("  Generating via MusicGen (180s)...")
    start = time.time()
    mp3_data = gen.generate.remote(
        "3 minute ambient background, soft music box, gentle harp, "
        "water inspired, moonlight on still lake, very quiet, minimal, "
        "55 BPM, peaceful, almost not there",
        duration=180,
    )
    elapsed = time.time() - start
    print(f"    MusicGen: {len(mp3_data):,} bytes in {elapsed:.0f}s")
    return AudioSegment.from_file(io.BytesIO(mp3_data))


def load_or_generate_intro() -> AudioSegment:
    """Load cached intro or generate via MusicGen."""
    path = MUSIC_DIR / "intro_calm.mp3"
    if path.exists():
        print("  Using cached intro")
        return AudioSegment.from_mp3(str(path))
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    gen = gen_cls()
    mp3 = gen.generate.remote(INTRO_PROMPT, duration=6)
    seg = AudioSegment.from_file(io.BytesIO(mp3))
    seg.export(str(path), format="mp3", bitrate="256k")
    return seg


def load_or_generate_outro() -> AudioSegment:
    """Load cached outro or generate via MusicGen."""
    path = MUSIC_DIR / "outro_calm.mp3"
    if path.exists():
        print("  Using cached outro")
        return AudioSegment.from_mp3(str(path))
    import modal
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    gen = gen_cls()
    mp3 = gen.generate.remote(OUTRO_PROMPT, duration=45)
    seg = AudioSegment.from_file(io.BytesIO(mp3))
    seg.export(str(path), format="mp3", bitrate="256k")
    return seg


def apply_swell_envelope(bed: AudioSegment, swells: list, base_db: float = -18, peak_db: float = -6) -> AudioSegment:
    """Apply volume swells to the bed track.

    Each swell: fade up over 2s, hold at peak, fade down over 2s.
    Between swells, bed stays at base_db.
    """
    # Work in 50ms chunks for smooth envelope
    chunk_ms = 50
    total_ms = len(bed)
    result = AudioSegment.silent(duration=0)

    # Build volume map (dB offset from current level)
    # bed is already at 0dB, we'll adjust relative
    pos = 0
    while pos < total_ms:
        chunk_end = min(pos + chunk_ms, total_ms)
        chunk = bed[pos:chunk_end]

        # Determine target dB for this position
        target_db = base_db
        for s in swells:
            if s["start"] <= pos < s["fade_in_end"]:
                # Fading up
                progress = (pos - s["start"]) / max(s["fade_in_end"] - s["start"], 1)
                target_db = base_db + (peak_db - base_db) * progress
                break
            elif s["fade_in_end"] <= pos < s["hold_end"]:
                # At peak
                target_db = peak_db
                break
            elif s["hold_end"] <= pos < s["fade_out_end"]:
                # Fading down
                progress = (pos - s["hold_end"]) / max(s["fade_out_end"] - s["hold_end"], 1)
                target_db = peak_db + (base_db - peak_db) * progress
                break

        result += chunk + target_db
        pos = chunk_end

    return result


# ══════════════════════════════════════════════════════════════════════
# STORY ASSEMBLY
# ══════════════════════════════════════════════════════════════════════

# Each entry: (text, param_type, silence_after_ms)
# param_type: "hook", "normal", "phrase"
# Special entries: ("__SWELL__", duration_ms) for music swell points

SCRIPT = [
    # Intro is prepended separately
    ("Did you know the lake listens to the moon?", "hook", 800),

    ("Soft night. Dark sky. One bright moon.", "normal", 400),
    ("Little Frog sits on a wide green leaf. The leaf is his boat.", "normal", 400),
    ("The lake is still.", "normal", 1500),

    ("__SWELL__", 6000),  # Swell 1 — the stillness breathes

    ("Then — the moon breathes. A tiny wave.", "normal", 300),
    ("Just one more ripple...", "phrase", 1200),

    ("__SWELL__", 6000),  # Swell 2 — let it echo

    ("Little Frog feels it under his toes. Cool. Gentle.", "normal", 600),
    ("Can you hear it too? Close your eyes.", "normal", 300),
    ("Just one more ripple...", "phrase", 800),
    ("The moon breathes again. Another wave. Smaller now.", "normal", 300),
    ("Just one more ripple...", "phrase", 1000),

    ("__SWELL__", 6000),  # Swell 3 — world getting quieter

    ("Little Frog blinks. His eyes grow heavy.", "normal", 600),
    ("The lake grows quiet.", "normal", 300),
    ("Just one more ripple...", "phrase", 1200),

    ("__SWELL__", 7000),  # Swell 4 — emotional peak, longest

    ("The moon stays. The lake stays.", "normal", 1000),
    ("Little Frog closes his eyes.", "normal", 1500),
    ("The ripples stop.", "normal", 2000),
    ("And right now, somewhere, the lake still listens.", "normal", 3000),
    # Outro appended separately
]


def build_narration(voice: str, intro: AudioSegment, outro: AudioSegment):
    """Build the narration track and record swell positions."""
    narration = AudioSegment.silent(duration=0)
    swell_regions = []  # (start_ms, end_ms)

    param_map = {
        "hook": HOOK_PARAMS,
        "normal": NORMAL_PARAMS,
        "phrase": PHRASE_PARAMS,
    }

    # Start with intro
    narration += intro
    narration += AudioSegment.silent(duration=500)
    print(f"    +intro @ 0ms, now {len(narration)}ms")

    for entry in SCRIPT:
        if entry[0] == "__SWELL__":
            duration = entry[1]
            start = len(narration)
            narration += AudioSegment.silent(duration=duration)
            swell_regions.append((start, len(narration)))
            print(f"    +SWELL {duration}ms @ {start}ms")
            continue

        text, ptype, silence_after = entry
        params = param_map[ptype]

        print(f"    TTS [{ptype}]: {text[:50]}...")
        seg = generate_tts(
            text, voice,
            exaggeration=params["exaggeration"],
            speed=params["speed"],
            cfg_weight=params["cfg_weight"],
        )
        dur = len(seg)
        pos = len(narration)
        narration += seg
        narration += AudioSegment.silent(duration=silence_after)
        print(f"      -> {dur}ms @ {pos}ms")

    # Gap before outro
    narration += AudioSegment.silent(duration=3000)

    # Outro
    outro_start = len(narration)
    narration += outro
    print(f"    +outro @ {outro_start}ms, total {len(narration)}ms")

    # Throwaway TTS to prevent Chatterbox repeat bug
    try:
        generate_tts(".", voice, exaggeration=0.1, speed=0.8, cfg_weight=0.5)
    except:
        pass

    return narration, swell_regions


def main():
    print(f"\n{'='*60}")
    print("Moonlight on the Lake — Bed + Swell Assembly")
    print(f"{'='*60}\n")

    # ── 1. Generate ambient bed ──────────────────────────────────────
    bed_path = MUSIC_DIR / "bed_calm.wav"
    if bed_path.exists():
        print("[1/4] Using cached bed")
        bed = AudioSegment.from_wav(str(bed_path))
    else:
        print("[1/4] Generating 3-min ambient bed...")
        try:
            bed = generate_bed_cassetteai()
            bed.export(str(bed_path), format="wav")
            print(f"  CassetteAI bed: {len(bed)/1000:.0f}s")
        except Exception as e:
            print(f"  CassetteAI failed: {e}")
            print("  Falling back to MusicGen...")
            bed = generate_bed_musicgen()
            bed.export(str(bed_path), format="wav")
            print(f"  MusicGen bed: {len(bed)/1000:.0f}s")

    # ── 2. Load intro + outro ────────────────────────────────────────
    print("\n[2/4] Loading intro + outro...")
    intro = load_or_generate_intro()
    outro = load_or_generate_outro()
    print(f"  Intro: {len(intro)/1000:.1f}s, Outro: {len(outro)/1000:.1f}s")

    # ── 3. Build narration + assemble per voice ──────────────────────
    for vi, voice in enumerate(MOOD_VOICES):
        print(f"\n[3/4] Building narration for {voice}...")
        narration, swell_regions = build_narration(voice, intro, outro)
        narration_dur = len(narration) / 1000.0
        print(f"  Narration: {narration_dur:.1f}s, Swells: {len(swell_regions)}")

        # ── 4. Shape bed and mix ─────────────────────────────────────
        print(f"\n[4/4] Shaping bed + mixing for {voice}...")

        # Trim or loop bed to match narration length
        total_ms = len(narration)
        if len(bed) >= total_ms:
            shaped_bed = bed[:total_ms]
        else:
            # Loop bed to fill
            loops_needed = (total_ms // len(bed)) + 1
            shaped_bed = (bed * loops_needed)[:total_ms]

        # Build swell envelope data
        swells = []
        for start_ms, end_ms in swell_regions:
            duration = end_ms - start_ms
            fade_time = 2000  # 2s fade in/out
            swells.append({
                "start": start_ms,
                "fade_in_end": start_ms + fade_time,
                "hold_end": end_ms - fade_time,
                "fade_out_end": end_ms,
            })

        # Apply swell envelope
        shaped_bed = apply_swell_envelope(shaped_bed, swells, base_db=-18, peak_db=-6)

        # Mix narration over bed
        # Narration at full volume, bed already volume-shaped
        final = narration.overlay(shaped_bed)

        # Export
        output_path = AUDIO_DIR / f"{SHORT_ID}_{voice}.mp3"
        final.export(str(output_path), format="mp3", bitrate="256k")
        size_kb = output_path.stat().st_size / 1024
        duration_s = len(final) / 1000.0
        print(f"  => {output_path.name} ({size_kb:.0f} KB, {duration_s:.1f}s)")

    print(f"\n{'='*60}")
    print("DONE — Listen to the files:")
    for voice in MOOD_VOICES:
        p = AUDIO_DIR / f"{SHORT_ID}_{voice}.mp3"
        print(f"  {p}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
