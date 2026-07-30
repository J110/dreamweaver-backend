from scripts.qa_audio import _long_story_trustworthy


def test_accepts_faithful_multi_voice_long_story_transcript():
    assert _long_story_trustworthy(0.8275, 0.6686)


def test_rejects_long_story_with_low_vocabulary_overlap():
    assert not _long_story_trustworthy(0.60, 0.90)
