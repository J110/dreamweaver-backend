from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parent))

from deploy_guard_models import AuditResult, Defect, ReasonCode, is_blocking
from deploy_guard_manifest import build_publishable_manifest


def write_record(data_dir, collection, record):
    target = data_dir / collection
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{record['id']}.json"
    path.write_text(__import__("json").dumps(record))
    return path


def test_only_radio_broadcast_is_non_blocking():
    radio = Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {})
    missing = Defect(ReasonCode.MISSING_AUDIO, "story-1", {})

    assert is_blocking(radio) is False
    assert is_blocking(missing) is True


def test_audit_result_exposes_only_current_blockers():
    result = AuditResult(defects=[
        Defect(ReasonCode.MISSING_AUDIO, "story-1", {}),
        Defect(ReasonCode.RADIO_BROADCAST_OFFLINE, "radio", {}),
    ])

    assert [defect.item_id for defect in result.blockers] == ["story-1"]


def test_manifest_excludes_only_explicit_non_publishable_records(tmp_path):
    write_record(tmp_path, "stories", {
        "id": "live",
        "type": "story",
        "title": "Live",
        "text": "Text",
    })
    write_record(tmp_path, "stories", {
        "id": "draft",
        "type": "story",
        "title": "Draft",
        "status": "draft",
    })

    result = build_publishable_manifest(tmp_path)

    assert set(result.items) == {"live"}


def test_manifest_flags_incomplete_unmarked_record(tmp_path):
    write_record(tmp_path, "stories", {
        "id": "broken",
        "type": "story",
    })

    result = build_publishable_manifest(tmp_path)

    assert result.defects[0].reason is ReasonCode.INVALID_SOURCE_RECORD
