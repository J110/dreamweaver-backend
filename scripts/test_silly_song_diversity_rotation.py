from scripts import generate_silly_songs_battlecry as generator


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
