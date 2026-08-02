from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parent))

import pipeline_run
import pipeline_run_hi


def test_failed_english_lullaby_cover_persists_placeholder_and_failure_state():
    entry = {"id": "permission-test", "cover": "/covers/permission-test.svg"}
    state = {"covers_generated": [], "covers_flux": [], "covers_failed": []}
    written = []

    path = pipeline_run._finalize_lullaby_cover(entry, state, False, written.append)

    assert path == "/covers/lullabies/permission-test_cover.svg"
    assert entry["cover"] == path
    assert written == [entry]
    assert state["covers_failed"] == ["permission-test"]
    assert state["covers_generated"] == []


def test_successful_english_lullaby_cover_persists_flux_path_and_success_state():
    entry = {"id": "permission-test", "cover": "/covers/permission-test.svg"}
    state = {"covers_generated": [], "covers_flux": [], "covers_failed": []}
    written = []

    path = pipeline_run._finalize_lullaby_cover(entry, state, True, written.append)

    assert path == "/covers/permission-test.svg"
    assert written == [entry]
    assert state["covers_generated"] == ["permission-test"]
    assert state["covers_flux"] == ["permission-test"]
    assert state["covers_failed"] == []


def test_hindi_state_reports_default_and_empty_covers_as_failed():
    results = {
        "lullaby": {
            "status": "ok",
            "type": "lullaby",
            "id": "hi-good",
            "title": "Good",
            "cover": "/covers/hi-good.webp",
        },
        "silly_song": {
            "status": "ok",
            "type": "silly_song",
            "id": "hi-default",
            "title": "Default",
            "cover": "/covers/default.svg",
        },
        "short_story": {
            "status": "ok",
            "type": "short_story",
            "id": "hi-empty",
            "title": "Empty",
            "cover": "",
        },
    }

    state = pipeline_run_hi._build_state(results, 1.0)

    assert state["covers_generated"] == ["hi-good"]
    assert state["covers_flux"] == ["hi-good"]
    assert state["covers_failed"] == ["hi-default", "hi-empty"]
    assert "covers failed: hi-default, hi-empty" in state["generation_warning"]
