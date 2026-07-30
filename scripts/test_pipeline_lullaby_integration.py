import sys

import generate_lullaby
import pipeline_run
from _funny_shorts_common import build_prompt


def test_select_new_lullabies_limits_integration_to_current_language_and_run():
    before_ids = {"old-en", "old-hi", "stale-en"}
    lullabies = [
        {"id": "old-en", "language": "en"},
        {"id": "stale-en", "language": "en"},
        {"id": "new-hi", "language": "hi"},
        {"id": "new-en", "language": "en"},
        {"id": "extra-en", "language": "en"},
    ]

    selected = pipeline_run._select_new_lullabies(
        lullabies,
        before_ids=before_ids,
        language="en",
        limit=1,
    )

    assert [item["id"] for item in selected] == ["new-en"]


def test_replicate_lyrics_are_limited_to_provider_contract():
    lyrics = "[verse]\n" + ("sleepy birds settle down\n" * 40)

    prepared = generate_lullaby._prepare_replicate_lyrics(lyrics)

    assert 10 <= len(prepared) <= 600
    assert prepared.endswith("down")


def test_lullaby_generator_returns_failure_when_requested_output_is_missing(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["generate_lullaby.py", "--count", "1"])
    monkeypatch.setattr(generate_lullaby, "generate_one", lambda **kwargs: None)

    assert generate_lullaby.main() == 1


def test_funny_short_prompt_marks_tone_as_direction_not_audio_tag():
    prompt = build_prompt(
        lang="en",
        voice_a_label="A",
        voice_a_personality="earnest",
        voice_b_label="B",
        voice_b_personality="skeptical",
        comedic_device="deadpan_absurd",
        emotional_dynamic="both excited",
        setting="park bench",
        tone="deadpan",
        required_opening_tag="[confused]",
        recent_shorts_summary="none",
        over_used_phrases_to_avoid="",
    )

    assert "do not write [deadpan]" in prompt
