"""Tests for the funny shorts frame assembler.

Run: cd dreamweaver-backend && .venv-test/bin/python -m pytest scripts/test_funny_shorts_assembler.py -v
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydub import AudioSegment

from _funny_shorts_common import frame_dialogue_with_stings


def _silence_mp3(seconds: float) -> bytes:
    seg = AudioSegment.silent(duration=int(seconds * 1000), frame_rate=44100)
    out = io.BytesIO()
    seg.export(out, format="mp3", bitrate="128k")
    return out.getvalue()


def test_frame_includes_intro_and_outro_lengths(tmp_path):
    intro_path = tmp_path / "intro.mp3"
    outro_path = tmp_path / "outro.mp3"
    intro_path.write_bytes(_silence_mp3(3.0))
    outro_path.write_bytes(_silence_mp3(3.0))

    dialogue = _silence_mp3(60.0)

    framed = frame_dialogue_with_stings(
        dialogue_bytes=dialogue,
        intro_sting_path=intro_path,
        outro_sting_path=outro_path,
        gap_ms=1000,
    )

    seg = AudioSegment.from_mp3(io.BytesIO(framed))
    duration_s = len(seg) / 1000
    # 3 + 1 + 60 + 1 + 3 = 68s, allow ±1.0s for encoder padding
    assert 67.0 <= duration_s <= 69.5, f"got {duration_s}s"


def test_frame_handles_short_dialogue(tmp_path):
    intro_path = tmp_path / "intro.mp3"
    outro_path = tmp_path / "outro.mp3"
    intro_path.write_bytes(_silence_mp3(3.0))
    outro_path.write_bytes(_silence_mp3(3.0))

    framed = frame_dialogue_with_stings(
        dialogue_bytes=_silence_mp3(30.0),
        intro_sting_path=intro_path,
        outro_sting_path=outro_path,
        gap_ms=1000,
    )
    seg = AudioSegment.from_mp3(io.BytesIO(framed))
    duration_s = len(seg) / 1000
    assert 37.0 <= duration_s <= 39.5


def test_frame_raises_on_missing_intro(tmp_path):
    intro_path = tmp_path / "intro.mp3"  # not written
    outro_path = tmp_path / "outro.mp3"
    outro_path.write_bytes(_silence_mp3(3.0))

    try:
        frame_dialogue_with_stings(
            dialogue_bytes=_silence_mp3(10.0),
            intro_sting_path=intro_path,
            outro_sting_path=outro_path,
        )
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as e:
        assert "Intro sting" in str(e)
