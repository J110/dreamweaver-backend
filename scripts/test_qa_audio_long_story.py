from scripts.qa_audio import _long_story_trustworthy, compute_verdict


def test_accepts_faithful_multi_voice_long_story_transcript():
    assert _long_story_trustworthy(0.8275, 0.6686)


def test_rejects_long_story_with_low_vocabulary_overlap():
    assert not _long_story_trustworthy(0.60, 0.90)


def test_final_verdict_preserves_long_story_fidelity_override():
    result = compute_verdict(
        None,
        {
            "verdict": "PASS",
            "fidelity": {
                "combined": 0.4196,
                "word_overlap": 0.8275,
                "word_order_score": 0.6686,
            },
        },
        None,
        content_type="long_story",
        voice="mixed",
    )

    assert result["verdict"] == "PASS"
    assert result["reasons"] == []
