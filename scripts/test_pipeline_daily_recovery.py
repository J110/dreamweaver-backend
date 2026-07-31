import json
from types import SimpleNamespace

from scripts import pipeline_run


def test_before_bed_passes_selected_age_to_silly_song(monkeypatch):
    commands = []

    def run_command(cmd, label, **_kwargs):
        commands.append((label, cmd))
        if "silly song" in label:
            return True, "• Flexible Song (ages 9-12)", "", 0
        if "musical poem" in label:
            return True, "[poem-test]", "", 0
        if "funny short cover" in label:
            return True, "", "", 0
        return True, "Wrote: data/funny_shorts/en-fs-test.json", "", 0

    monkeypatch.setattr(pipeline_run, "_pick_before_bed_age", lambda: "9-12")
    monkeypatch.setattr(pipeline_run, "_pick_before_bed_mood", lambda: "wired")
    monkeypatch.setattr(pipeline_run, "run_command", run_command)
    monkeypatch.setattr(pipeline_run, "save_state", lambda _state: None)
    monkeypatch.setattr(pipeline_run.time, "sleep", lambda *_: None)

    pipeline_run.step_before_bed(SimpleNamespace(dry_run=False), {})

    silly_cmd = next(cmd for label, cmd in commands if "silly song" in label)
    age_index = silly_cmd.index("--age")
    assert silly_cmd[age_index:age_index + 2] == ["--age", "9-12"]


def test_content_generation_uses_two_retries_and_stops_after_success(
    monkeypatch, tmp_path
):
    content_path = tmp_path / "content.json"
    expanded_path = tmp_path / "content_expanded.json"
    state_path = tmp_path / "pipeline_state.json"
    content_path.write_text("[]")
    expanded_path.write_text("[]")
    calls = []

    def run_command(cmd, label, **_kwargs):
        if "generate_content_matrix.py" in " ".join(cmd):
            calls.append(cmd)
            if len(calls) == 3:
                expanded_path.write_text(json.dumps([{
                    "id": "recovered-story",
                    "type": "story",
                    "lang": "en",
                    "title": "Recovered Story",
                    "text": "A validator-clean story.",
                }]))
        return True, "", "", 0

    monkeypatch.setattr(pipeline_run, "CONTENT_PATH", content_path)
    monkeypatch.setattr(pipeline_run, "CONTENT_EXPANDED_PATH", expanded_path)
    monkeypatch.setattr(pipeline_run, "STATE_PATH", state_path)
    monkeypatch.setattr(pipeline_run, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(pipeline_run, "run_command", run_command)
    monkeypatch.setattr(pipeline_run.time, "sleep", lambda *_: None)

    args = SimpleNamespace(
        count_stories=1,
        count_poems=0,
        count_lullabies=0,
        count_long_stories=0,
        mood="calm",
        story_type="fable",
        age="2-5",
        lang="en",
        dry_run=False,
    )
    state = {}

    assert pipeline_run.step_generate(args, state) is True
    assert len(calls) == 3
    assert state["generated_ids"] == ["recovered-story"]
    assert "generation_warning" not in state
    for retry_cmd in calls[1:]:
        assert retry_cmd[retry_cmd.index("--mood"):][:2] == ["--mood", "calm"]
        assert retry_cmd[retry_cmd.index("--story-type"):][:2] == [
            "--story-type",
            "fable",
        ]
        assert retry_cmd[retry_cmd.index("--age"):][:2] == ["--age", "2-5"]
