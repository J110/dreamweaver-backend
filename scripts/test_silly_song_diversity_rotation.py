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
