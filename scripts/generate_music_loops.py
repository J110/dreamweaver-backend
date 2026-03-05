#!/usr/bin/env python3
"""
Generate 12 instrument loops × 3 keys via Modal MusicGen.
Requires: modal_musicgen.py deployed first (python3 -m modal deploy scripts/modal_musicgen.py)
Output: dreamweaver-web/public/audio/music-loops/{instrument}_{key}.mp3
"""

import os
import subprocess
import modal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUT_DIR = os.path.join(PROJECT_ROOT, "dreamweaver-web", "public", "audio", "music-loops")

DURATION = 40  # Generate 40s, trim to ~30s

INSTRUMENTS = {
    "harp_arpeggios": "Gentle Celtic harp ascending and descending arpeggios, ambient sleep music, soft and dreamy, seamless loop",
    "koto_plucks": "Sparse Japanese koto plucked notes with subtle pitch bend, meditative, ambient sleep music, seamless loop",
    "kalimba_melody": "Simple kalimba thumb piano repeating melody, soothing lullaby, ambient sleep music, seamless loop",
    "singing_bowl_rings": "Tibetan singing bowl resonant rings with long sustain, meditative drone, ambient sleep music, seamless loop",
    "cello_sustains": "Solo cello long sustained notes with gentle vibrato, warm and soothing, ambient sleep music, seamless loop",
    "hang_drum_melody": "Hang drum soft melodic pattern, ethereal and dreamy, ambient sleep music, seamless loop",
    "guitar_fingerpick": "Acoustic guitar gentle fingerpicking pattern, warm and intimate, ambient sleep music, seamless loop",
    "music_box_melody": "Music box delicate tinkling melody, nostalgic lullaby, ambient sleep music, seamless loop",
    "flute_breathy": "Breathy wooden flute slow melody with natural breath sounds, pastoral and calming, ambient sleep music, seamless loop",
    "marimba_soft": "Soft marimba gentle repeating pattern, warm wooden tones, ambient sleep music, seamless loop",
    "dulcimer_gentle": "Hammered dulcimer gentle cascading notes, folk lullaby, ambient sleep music, seamless loop",
    "piano_lullaby": "Solo piano gentle lullaby, simple melody with soft touch, ambient sleep music, seamless loop",
}

KEYS = ["C", "F", "A"]
KEY_BPM = {"C": 66, "F": 62, "A": 64}


def trim_loop(tmpfile, outfile):
    """Trim raw audio: skip first 2s, take 30s, fade in/out."""
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", tmpfile,
            "-af", "atrim=start=2:end=32,afade=t=in:st=0:d=0.5,afade=t=out:st=28:d=2",
            "-b:a", "128k", outfile
        ], capture_output=True, timeout=30)
        if os.path.exists(outfile) and os.path.getsize(outfile) > 1000:
            return True
    except Exception:
        pass

    # Fallback: just copy without trimming
    import shutil
    shutil.copy2(tmpfile, outfile)
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Look up the deployed Modal function
    gen_cls = modal.Cls.from_name("dreamweaver-musicgen", "MusicGenerator")
    gen = gen_cls()

    total = len(INSTRUMENTS) * len(KEYS)
    generated = 0
    skipped = 0
    failed = 0

    print(f"=== Generating {len(INSTRUMENTS)} instruments × {len(KEYS)} keys = {total} loops ===")
    print(f"Output: {OUT_DIR}")
    print(f"Using: Modal MusicGen (deployed)")
    print()

    for instrument, prompt in INSTRUMENTS.items():
        for key in KEYS:
            outfile = os.path.join(OUT_DIR, f"{instrument}_{key}.mp3")

            if os.path.exists(outfile) and os.path.getsize(outfile) > 1000:
                size_kb = os.path.getsize(outfile) // 1024
                print(f"SKIP: {instrument}_{key}.mp3 (already exists, {size_kb}K)")
                skipped += 1
                continue

            bpm = KEY_BPM[key]
            full_prompt = f"{prompt}, key of {key}, slow tempo {bpm} BPM"

            print(f"Generating {instrument}_{key}.mp3 ... ", end="", flush=True)
            try:
                mp3_data = gen.generate.remote(full_prompt, duration=DURATION)

                if not mp3_data or len(mp3_data) < 1000:
                    print("FAILED (empty response)")
                    failed += 1
                    continue

                # Write raw MP3 then trim
                tmpfile = f"/tmp/loop_{instrument}_{key}.mp3"
                with open(tmpfile, "wb") as f:
                    f.write(mp3_data)

                if trim_loop(tmpfile, outfile):
                    os.remove(tmpfile)
                    size_kb = os.path.getsize(outfile) // 1024
                    print(f"OK ({size_kb}K)")
                    generated += 1
                else:
                    print("FAILED (trim)")
                    failed += 1

            except Exception as e:
                print(f"FAILED ({e})")
                failed += 1

    print()
    print(f"=== Done: {generated} generated, {skipped} skipped, {failed} failed ===")
    print()

    # Verification
    print("=== Verification ===")
    for instrument in INSTRUMENTS:
        for key in KEYS:
            f = os.path.join(OUT_DIR, f"{instrument}_{key}.mp3")
            if os.path.exists(f):
                size_kb = os.path.getsize(f) // 1024
                try:
                    result = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", f],
                        capture_output=True, text=True, timeout=10
                    )
                    dur = result.stdout.strip().split('.')[0]
                except Exception:
                    dur = "?"
                print(f"  ✓ {instrument}_{key}.mp3 ({dur}s, {size_kb}K)")
            else:
                print(f"  ✗ {instrument}_{key}.mp3 MISSING")


if __name__ == "__main__":
    main()
