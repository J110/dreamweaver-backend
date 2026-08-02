from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parent))

from deploy_guard_models import AuditResult, Defect, ReasonCode, is_blocking


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
