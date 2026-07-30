import pipeline_run


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
