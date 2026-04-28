"""Tests for the funny shorts sampler.

Run: cd dreamweaver-backend && .venv-test/bin/python -m pytest scripts/test_funny_shorts_sampler.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _funny_shorts_common import (
    APPROVED_PAIRINGS_EN,
    APPROVED_PAIRINGS_HI,
    OPENING_TAGS,
    COMEDIC_DEVICES,
    CHARACTER_AGE_DYNAMICS,
    EMOTIONAL_DYNAMICS_EN,
    EMOTIONAL_DYNAMICS_HI,
    SETTINGS_EN,
    SETTINGS_HI,
    TONES,
    sample_axis_excluding_recent,
    sample_voice_pair,
    VOICE_LIBRARY_EN,
    VOICE_LIBRARY_HI,
)


def test_voice_libraries_have_six_each():
    assert len(VOICE_LIBRARY_EN) == 6
    assert len(VOICE_LIBRARY_HI) == 6


def test_eight_pairings_each_lang():
    assert len(APPROVED_PAIRINGS_EN) == 8
    assert len(APPROVED_PAIRINGS_HI) == 8


def test_pairings_reference_known_voices():
    for a, b in APPROVED_PAIRINGS_EN:
        assert a in VOICE_LIBRARY_EN
        assert b in VOICE_LIBRARY_EN
    for a, b in APPROVED_PAIRINGS_HI:
        assert a in VOICE_LIBRARY_HI
        assert b in VOICE_LIBRARY_HI


def test_sample_axis_excludes_recent():
    options = ["a", "b", "c", "d", "e"]
    recent = ["a", "b", "c"]
    chosen = sample_axis_excluding_recent(options, recent, exclude_n=3, seed=42)
    assert chosen in {"d", "e"}


def test_sample_axis_falls_back_when_all_excluded():
    options = ["a", "b"]
    recent = ["a", "b", "a", "b", "a", "b"]
    chosen = sample_axis_excluding_recent(options, recent, exclude_n=5, seed=42)
    assert chosen in options


def test_sample_voice_pair_excludes_last_3():
    recent_pairs = list(APPROVED_PAIRINGS_EN[:3])
    chosen = sample_voice_pair(APPROVED_PAIRINGS_EN, recent_pairs, seed=42)
    assert chosen not in recent_pairs


def test_opening_tags_minimum_set():
    expected = {"[curious]", "[matter-of-fact]", "[excited]", "[whispers]",
                "[thoughtful]", "[grinning]", "[confused]", "[serious]",
                "[sigh]", None}
    assert expected.issubset(set(OPENING_TAGS))


def test_character_age_dynamics_present():
    assert "siblings" in CHARACTER_AGE_DYNAMICS
    assert "cousins" in CHARACTER_AGE_DYNAMICS
    assert "classmates" in CHARACTER_AGE_DYNAMICS
    assert len(CHARACTER_AGE_DYNAMICS) >= 4
