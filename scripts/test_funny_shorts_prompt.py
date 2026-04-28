"""Tests for the funny shorts Mistral prompt builder.

Run: cd dreamweaver-backend && .venv-test/bin/python -m pytest scripts/test_funny_shorts_prompt.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _funny_shorts_common import build_prompt


def test_en_prompt_contains_required_sections():
    prompt = build_prompt(
        lang="en",
        voice_a_label="mini",
        voice_a_personality="lively cute young female",
        voice_b_label="leo",
        voice_b_personality="calm and steady",
        comedic_device="earnest_vs_skeptical",
        emotional_dynamic="one earnest, one skeptical",
        setting="couch fort",
        tone="rambling",
        required_opening_tag="[matter-of-fact]",
        recent_shorts_summary="(none — this is the first short)",
        over_used_phrases_to_avoid="",
        character_age_dynamic="siblings",
    )
    assert "Exactly two characters speaking, no narrator" in prompt
    assert "6-20 dialogue lines total" in prompt
    assert "earnest_vs_skeptical" in prompt
    assert "couch fort" in prompt
    assert "[matter-of-fact]" in prompt
    assert "OUTPUT FORMAT (JSON)" in prompt
    assert "siblings" in prompt


def test_hi_prompt_includes_roman_hindi_clauses():
    prompt = build_prompt(
        lang="hi",
        voice_a_label="bunty",
        voice_a_personality="funny best friend",
        voice_b_label="kiran",
        voice_b_personality="very young and engaging",
        comedic_device="earnest_vs_skeptical",
        emotional_dynamic="ek earnest, doosra skeptical",
        setting="during a power cut",
        tone="rambling",
        required_opening_tag="[matter-of-fact]",
        recent_shorts_summary="(none — first Hindi short)",
        over_used_phrases_to_avoid="",
        character_age_dynamic="cousins",
    )
    assert "Roman" in prompt
    assert "Devanagari" in prompt
    assert "Hinglish" in prompt
    assert "title_en" in prompt
    assert "NO RELIGIOUS CONTENT" in prompt
    assert "during a power cut" in prompt
    assert "cousins" in prompt


def test_prompt_excludes_examples_to_avoid_templates():
    """Mistral templates from examples — prompt must NOT include sample dialogue."""
    prompt = build_prompt(
        lang="en", voice_a_label="a", voice_a_personality="x",
        voice_b_label="b", voice_b_personality="y",
        comedic_device="x", emotional_dynamic="x", setting="x", tone="x",
        required_opening_tag="[curious]", recent_shorts_summary="",
        over_used_phrases_to_avoid="",
    )
    assert "EXAMPLE DIALOGUE" not in prompt.upper()
    assert "EXAMPLE LINES" not in prompt.upper()


def test_no_tag_opener_normalized():
    """When required_opening_tag is None, prompt should describe an in-medias-res start."""
    prompt = build_prompt(
        lang="en", voice_a_label="a", voice_a_personality="x",
        voice_b_label="b", voice_b_personality="y",
        comedic_device="x", emotional_dynamic="x", setting="x", tone="x",
        required_opening_tag=None, recent_shorts_summary="",
        over_used_phrases_to_avoid="",
    )
    assert "no tag" in prompt or "mid-thought" in prompt
