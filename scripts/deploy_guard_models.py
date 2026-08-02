from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReasonCode(str, Enum):
    INVALID_SOURCE_RECORD = "INVALID_SOURCE_RECORD"
    MISSING_LIVE_ITEM = "MISSING_LIVE_ITEM"
    MISSING_AUDIO = "MISSING_AUDIO"
    MISSING_CUSTOM_COVER = "MISSING_CUSTOM_COVER"
    PLACEHOLDER_COVER = "PLACEHOLDER_COVER"
    WRONG_METADATA_PATH = "WRONG_METADATA_PATH"
    MISROUTED_ASSET = "MISROUTED_ASSET"
    MISSING_SOURCE_RECORD = "MISSING_SOURCE_RECORD"
    PLAYLIST_SLOT_MISSING = "PLAYLIST_SLOT_MISSING"
    STALE_LIVE_STATE = "STALE_LIVE_STATE"
    UNREACHABLE_ORIGIN = "UNREACHABLE_ORIGIN"
    RADIO_BROADCAST_OFFLINE = "RADIO_BROADCAST_OFFLINE"


@dataclass(frozen=True)
class Defect:
    reason: ReasonCode
    item_id: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "item_id": self.item_id,
            "details": self.details,
        }


def is_blocking(defect: Defect) -> bool:
    return defect.reason is not ReasonCode.RADIO_BROADCAST_OFFLINE


@dataclass
class AuditResult:
    defects: list[Defect] = field(default_factory=list)

    @property
    def blockers(self) -> list[Defect]:
        return [defect for defect in self.defects if is_blocking(defect)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": not self.blockers,
            "defects": [defect.to_dict() for defect in self.defects],
            "blockers": [defect.to_dict() for defect in self.blockers],
        }


@dataclass(frozen=True)
class RecoveryResult:
    defect: Defect
    recovered: bool
    action: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "defect": self.defect.to_dict(),
            "recovered": self.recovered,
            "action": self.action,
            "error": self.error,
        }


@dataclass
class FinalVerdict:
    deployment_succeeded: bool
    app_healthy: bool
    audit: AuditResult
    rolled_back: bool = False
    snapshot_id: str = ""
    recovery_results: list[RecoveryResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_succeeded": self.deployment_succeeded,
            "app_healthy": self.app_healthy,
            "rolled_back": self.rolled_back,
            "snapshot_id": self.snapshot_id,
            "audit": self.audit.to_dict(),
            "recovery_results": [result.to_dict() for result in self.recovery_results],
        }
