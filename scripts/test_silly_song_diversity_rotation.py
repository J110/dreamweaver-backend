import json
import sys

import pytest

from scripts import generate_silly_songs_battlecry as generator


def song(age, created_at):
    return {"age_group": age, "created_at": created_at}


def test_select_next_age_uses_least_recent_generation():
    history = [
        song("2-5", "2026-07-26"),
        song("6-8", "2026-07-24"),
        song("9-12", "2026-07-25"),
    ]
    assert generator.select_next_age(history) == "6-8"


def test_three_daily_selections_cover_every_age():
    history = []
    selected = []
    for day in ("2026-07-26", "2026-07-27", "2026-07-28"):
        age = generator.select_next_age(history)
        selected.append(age)
        history.append(song(age, day))
    assert selected == ["2-5", "6-8", "9-12"]


def test_missing_dates_are_oldest_with_fixed_tie_order():
    history = [
        song("2-5", "2026-07-26"),
        song("6-8", "not-a-date"),
        song("9-12", "2026-07-25"),
    ]
    assert generator.select_next_age(history) == "6-8"


def test_tiny_parade_variants_are_deterministically_rejected():
    decision, matches = generator._deterministic_hook_decision(
        "Tiny Parade Today!",
        ["Tiny Parade Hooray!", "Tiny Parade!"],
    )
    assert decision == "reject"
    assert matches[0][0] in {"Tiny Parade Hooray!", "Tiny Parade!"}


def test_deterministic_rejection_scores_beyond_five_closest_matches():
    candidate = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    distractors = [
        "alpha beta gamma delta epsilon one two three four five",
        "alpha beta gamma delta epsilon sun moon star cloud rain",
        "alpha beta gamma delta epsilon chair table lamp rug shelf",
        "alpha beta gamma delta epsilon red orange yellow green purple",
        "alpha beta gamma delta epsilon jump dance sing laugh play",
    ]
    hard_jaccard_match = "gamma beta alpha zeta epsilon delta"
    decision, matches = generator._deterministic_hook_decision(
        candidate,
        distractors + [hard_jaccard_match],
    )
    assert decision == "reject"
    assert any(match[0] == hard_jaccard_match for match in matches)


def test_hook_normalization_removes_markdown_case_and_punctuation():
    assert generator._normalize_hook("**TINY Parade!**") == "tiny parade"


def test_hook_normalization_reduces_inflections_and_stop_words():
    assert generator._normalize_hook("The Marching Shoes Today") == "march shoe"


def test_borderline_hook_requires_semantic_judgment():
    decision, _ = generator._deterministic_hook_decision(
        "Moon Shoes March",
        ["Moon Boots March"],
    )
    assert decision == "semantic"


def test_distinct_hook_skips_semantic_judgment():
    decision, _ = generator._deterministic_hook_decision(
        "Broccoli Built a Spaceship",
        ["Tiny Parade Hooray!"],
    )
    assert decision == "accept"


def test_semantic_paraphrase_is_rejected(monkeypatch):
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: '{"similar": true}',
    )
    assert generator._semantic_hook_is_similar(
        "Moon Boots March",
        [("Marching Shoes on the Moon", 0.4, 0.7)],
        "test-key",
    ) is True


def test_malformed_semantic_response_is_conservatively_rejected(monkeypatch):
    monkeypatch.setattr(generator, "call_mistral", lambda *args, **kwargs: "maybe")
    assert generator._semantic_hook_is_similar(
        "Moon Boots March",
        [("Marching Shoes on the Moon", 0.4, 0.7)],
        "test-key",
    ) is True


def test_invent_anthem_exhausts_three_rejected_candidates(monkeypatch):
    responses = iter([
        "Tiny Parade Today!",
        "Tiny Parade Tonight!",
        "Tiny Parade Again!",
    ])
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: next(responses),
    )
    with pytest.raises(RuntimeError, match="three similarity rejections"):
        generator.invent_anthem(
            category="celebration",
            age_group="2-5",
            mood="wired",
            existing_hooks=["Tiny Parade Hooray!"],
            api_key="test-key",
            existing_on_disk={"tiny_parade_hooray_2_5"},
        )


def test_invent_anthem_retries_candidate_id_collision(monkeypatch):
    responses = iter(["Tiny Parade", "Clouds Wear Sneakers"])
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: next(responses),
    )
    assert generator.invent_anthem(
        category="celebration",
        age_group="2-5",
        mood="wired",
        existing_hooks=[],
        api_key="test-key",
        existing_on_disk={"tiny_parade_2_5"},
    ) == ("Clouds Wear Sneakers", "clouds_wear_sneakers")


def test_disk_song_ids_include_orphan_assets_and_malformed_metadata(
    monkeypatch, tmp_path
):
    data_dir = tmp_path / "data"
    audio_dir = tmp_path / "audio"
    covers_dir = tmp_path / "covers"
    for directory in (data_dir, audio_dir, covers_dir):
        directory.mkdir()
    (data_dir / "broken_hook_2_5.json").write_text("{malformed")
    (audio_dir / "orphan_audio_6_8.mp3").write_bytes(b"audio")
    (covers_dir / "orphan_cover_9_12.webp").write_bytes(b"cover")
    monkeypatch.setattr(generator, "DATA_DIR", data_dir)
    monkeypatch.setattr(generator, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(generator, "COVERS_DIR", covers_dir)
    assert generator._existing_song_ids_on_disk() == {
        "broken_hook_2_5",
        "orphan_audio_6_8",
        "orphan_cover_9_12",
    }


def test_prompt_hook_dedupe_uses_normalized_hook(monkeypatch):
    prompts = []

    def fake_mistral(prompt, **kwargs):
        prompts.append(prompt)
        return "Clouds Wear Sneakers"

    monkeypatch.setattr(generator, "call_mistral", fake_mistral)
    generator.invent_anthem(
        category="celebration",
        age_group="2-5",
        mood="wired",
        existing_hooks=[],
        api_key="test-key",
        existing_on_disk=set(),
        prompt_hooks=["**Tiny Parade!**", "tiny parade", "Moon Shoes"],
    )
    assert prompts[0].count("Tiny Parade") == 1
    assert "\n- tiny parade" not in prompts[0]


def test_semantically_accepted_candidate_logs_closest_match_and_result(
    monkeypatch, capsys
):
    responses = iter(["Moon Shoes March", '{"similar": false}'])
    monkeypatch.setattr(
        generator,
        "call_mistral",
        lambda *args, **kwargs: next(responses),
    )
    generator.invent_anthem(
        category="observation",
        age_group="6-8",
        mood="curious",
        existing_hooks=["Moon Boots March"],
        api_key="test-key",
        existing_on_disk=set(),
    )
    output = capsys.readouterr().out
    assert "Hook accepted" in output
    assert "closest='Moon Boots March'" in output
    assert "semantic_result=False" in output


def test_similarity_exhaustion_never_starts_song_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generator, "_load_existing_songs", lambda: [])
    monkeypatch.setattr(
        generator,
        "invent_anthem",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("invent_anthem: three similarity rejections")
        ),
    )
    generated = []
    monkeypatch.setattr(
        generator,
        "generate_silly_song",
        lambda **kwargs: generated.append(kwargs),
    )
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_silly_songs_battlecry.py", "--fresh", "--count", "1", "--lyrics-only"],
    )

    with pytest.raises(SystemExit, match="3"):
        generator.main()
    assert generated == []


def _stub_song_generation(monkeypatch, tmp_path, audio_result):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    audio_dir = tmp_path / "audio"
    covers_dir = tmp_path / "covers"
    for directory in (data_dir, output_dir, audio_dir, covers_dir):
        directory.mkdir(exist_ok=True)
    monkeypatch.setattr(generator, "DATA_DIR", data_dir)
    monkeypatch.setattr(generator, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(generator, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(generator, "COVERS_DIR", covers_dir)
    monkeypatch.setattr(generator.time, "sleep", lambda *_: None)
    monkeypatch.setattr(generator, "generate_scene", lambda *args, **kwargs: "A child jumps on a bed")
    monkeypatch.setattr(generator, "validate_scene", lambda scene: True)
    monkeypatch.setattr(generator, "call_mistral", lambda *args, **kwargs: "song lyrics")
    monkeypatch.setattr(generator, "extract_cover_from_lyrics", lambda lyrics: "funny cover")
    monkeypatch.setattr(generator, "extract_lyrics", lambda lyrics: lyrics)
    monkeypatch.setattr(
        generator,
        "validate_silly_song",
        lambda *args, **kwargs: (True, [], []),
    )
    monkeypatch.setattr(
        generator,
        "generate_audio_minimax",
        lambda *args, **kwargs: audio_result,
    )
    return data_dir


def test_failed_audio_metadata_does_not_advance_age_rotation(
    monkeypatch, tmp_path
):
    data_dir = _stub_song_generation(monkeypatch, tmp_path, audio_result=False)
    (data_dir / "old_2_5.json").write_text(json.dumps(song("2-5", "2026-07-24")))
    (data_dir / "old_6_8.json").write_text(json.dumps(song("6-8", "2026-07-25")))
    result = generator.generate_silly_song(
        cry_id="failed_hook",
        battle_cry="Failed Hook",
        age_group="9-12",
        api_key="test-key",
        params={
            "category": "celebration",
            "mood": "wired",
            "style_prompt": "style",
            "instruments": "piano",
            "tempo": 100,
        },
    )
    assert result is None
    assert generator.select_next_age(generator._load_existing_songs()) == "9-12"


def test_lyrics_only_metadata_advances_age_rotation(monkeypatch, tmp_path):
    _stub_song_generation(monkeypatch, tmp_path, audio_result=False)
    result = generator.generate_silly_song(
        cry_id="lyrics_hook",
        battle_cry="Lyrics Hook",
        age_group="2-5",
        api_key="test-key",
        lyrics_only=True,
        params={
            "category": "celebration",
            "mood": "wired",
            "style_prompt": "style",
            "instruments": "piano",
            "tempo": 100,
        },
    )
    assert result["generation_status"] == "lyrics_only"
    assert generator.select_next_age(generator._load_existing_songs()) == "6-8"


def test_existing_hooks_are_newest_first_and_keep_yesterdays_title():
    songs = [
        {"created_at": f"2026-07-{day:02d}", "title": f"Song {day}"}
        for day in range(1, 26)
    ]
    songs.append({
        "created_at": "2026-07-26",
        "title": "Tiny Parade Hooray!",
        "anthem": "Tiny Parade Hooray!",
    })
    hooks = generator._existing_hooks_newest_first(songs)
    assert hooks[0] == "Tiny Parade Hooray!"
    assert "Tiny Parade Hooray!" in hooks[:25]


def test_current_run_result_is_compared_with_the_next_candidate():
    hooks = generator._comparison_hooks(
        [],
        [{"title": "Tiny Parade Hooray!", "anthem": "Tiny Parade Hooray!"}],
    )
    decision, matches = generator._deterministic_hook_decision(
        "Tiny Parade Today!",
        hooks,
    )
    assert decision == "reject"
    assert matches[0][0] == "Tiny Parade Hooray!"


def test_partial_legacy_batch_exits_nonzero(monkeypatch):
    generated = iter([{"id": "one"}, {"id": "two"}, None])
    monkeypatch.setattr(
        generator,
        "generate_silly_song",
        lambda **kwargs: next(generated),
    )
    monkeypatch.setattr(generator.time, "sleep", lambda *_: None)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_silly_songs_battlecry.py", "--test", "--lyrics-only"],
    )
    with pytest.raises(SystemExit, match="3"):
        generator.main()
