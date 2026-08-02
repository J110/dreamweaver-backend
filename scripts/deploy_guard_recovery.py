from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Callable

from deploy_guard_models import AuditResult, Defect, ReasonCode, RecoveryResult


CoverGenerator = Callable[[Path, Path], str]


@dataclass
class RecoveryContext:
    data_dir: Path
    audio_store: Path
    cover_store: Path
    search_roots: tuple[Path, ...]
    snapshot_root: Path
    cover_generator: CoverGenerator | None = None
    reload_callback: Callable[[], None] | None = None


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".recovering")
    shutil.copy2(source, temporary)
    temporary.replace(target)


def _atomic_json_update(path: Path, **fields) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(fields)
    temporary = path.with_suffix(".json.recovering")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


class RecoveryEngine:
    def __init__(self, context: RecoveryContext):
        self.context = context

    def recover(self, defects: list[Defect]) -> list[RecoveryResult]:
        return [self._recover_one(defect) for defect in defects]

    def _recover_one(self, defect: Defect) -> RecoveryResult:
        try:
            if defect.reason in {
                ReasonCode.MISROUTED_ASSET,
                ReasonCode.MISSING_AUDIO,
            }:
                return self._restore_asset(defect)
            if defect.reason in {
                ReasonCode.PLACEHOLDER_COVER,
                ReasonCode.MISSING_CUSTOM_COVER,
            }:
                if defect.reason is ReasonCode.PLACEHOLDER_COVER:
                    return self._regenerate_cover(defect)
                restored = self._restore_asset(defect, optional=True)
                if restored.recovered:
                    return restored
                return self._regenerate_cover(defect)
            if defect.reason is ReasonCode.WRONG_METADATA_PATH:
                return self._repair_metadata(defect)
            if defect.reason is ReasonCode.MISSING_SOURCE_RECORD:
                if defect.details.get("relative_path"):
                    return self._restore_source_record(defect)
                return self._reload(defect)
            if defect.reason in {
                ReasonCode.STALE_LIVE_STATE,
                ReasonCode.MISSING_LIVE_ITEM,
                ReasonCode.PLAYLIST_SLOT_MISSING,
                ReasonCode.UNREACHABLE_ORIGIN,
            }:
                return self._reload(defect)
            return RecoveryResult(defect, False, "no safe recovery adapter")
        except Exception as exc:
            return RecoveryResult(
                defect,
                False,
                "recovery failed",
                f"{type(exc).__name__}: {exc}",
            )

    def _search_roots(self) -> tuple[Path, ...]:
        roots = (
            self.context.snapshot_root,
            *self.context.search_roots,
            self.context.audio_store,
            self.context.cover_store,
        )
        return tuple(dict.fromkeys(root for root in roots if root.exists()))

    def _find_source(
        self,
        filename: str,
        target: Path,
        canonical: str,
        expected_sha256: str = "",
    ) -> Path | None:
        for root in self._search_roots():
            candidates = []
            for candidate in root.rglob(filename):
                if candidate.is_file() and candidate.resolve() != target.resolve():
                    candidates.append(candidate)
            exact = [
                candidate for candidate in candidates
                if candidate.as_posix().endswith(canonical)
            ]
            pool = exact or candidates
            if expected_sha256:
                pool = [
                    candidate for candidate in pool
                    if hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_sha256
                ]
            if not pool:
                continue
            if exact:
                return max(pool, key=lambda path: path.stat().st_mtime_ns)
            by_hash = {}
            for candidate in pool:
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                by_hash.setdefault(digest, []).append(candidate)
            if len(by_hash) == 1:
                return sorted(next(iter(by_hash.values())), key=lambda path: str(path))[0]
        return None

    def _safe_target(self, store: Path, canonical: str) -> Path:
        relative = Path(canonical.lstrip("/"))
        if not canonical or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe canonical asset path: {canonical}")
        store_root = store.resolve()
        target = (store / relative).resolve()
        if not target.is_relative_to(store_root):
            raise ValueError(f"asset path escapes store: {canonical}")
        return target

    def _restore_asset(
        self,
        defect: Defect,
        optional: bool = False,
    ) -> RecoveryResult:
        details = defect.details
        canonical = str(details.get("canonical") or "")
        filename = str(details.get("filename") or Path(canonical).name)
        asset_kind = str(details.get("asset_kind") or "cover")
        if not canonical or not filename:
            return RecoveryResult(
                defect,
                False,
                "asset location unavailable" if optional else "missing canonical asset details",
            )
        store = (
            self.context.audio_store
            if asset_kind == "audio"
            else self.context.cover_store
        )
        target = self._safe_target(store, canonical)
        expected_sha256 = str(details.get("sha256") or "")
        source = self._find_source(filename, target, canonical, expected_sha256)
        if source is None:
            return RecoveryResult(defect, False, "asset not found in recovery stores")
        _atomic_copy(source, target)
        if expected_sha256 and hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
            target.unlink(missing_ok=True)
            return RecoveryResult(defect, False, "restored asset hash mismatch")
        return RecoveryResult(
            defect,
            True,
            f"restored {asset_kind} from {source}",
        )

    def _regenerate_cover(self, defect: Defect) -> RecoveryResult:
        source_path_value = defect.details.get("source_path")
        if not source_path_value or self.context.cover_generator is None:
            return RecoveryResult(defect, False, "custom cover generator unavailable")
        source_path = Path(str(source_path_value))
        if not source_path.exists():
            return RecoveryResult(defect, False, "cover source record missing")
        before = json.loads(source_path.read_text(encoding="utf-8"))
        cover_path = self.context.cover_generator(
            source_path,
            self.context.cover_store,
        )
        if not cover_path or cover_path == "/covers/default.svg":
            return RecoveryResult(defect, False, "cover generator returned placeholder")
        _atomic_json_update(source_path, cover=cover_path)
        after = json.loads(source_path.read_text(encoding="utf-8"))
        for protected in ("id", "title", "description", "text", "created_at"):
            if before.get(protected) != after.get(protected):
                raise ValueError(f"cover recovery changed protected field {protected}")
        return RecoveryResult(defect, True, f"generated custom cover {cover_path}")

    def _repair_metadata(self, defect: Defect) -> RecoveryResult:
        source_path = Path(str(defect.details.get("source_path") or ""))
        field = str(defect.details.get("field") or "")
        value = defect.details.get("value")
        if not source_path.is_file() or not field or value is None:
            return RecoveryResult(defect, False, "metadata repair details incomplete")
        _atomic_json_update(source_path, **{field: value})
        return RecoveryResult(defect, True, f"updated {field}")

    def _restore_source_record(self, defect: Defect) -> RecoveryResult:
        relative = defect.details.get("relative_path")
        if not relative:
            return RecoveryResult(defect, False, "source record path unavailable")
        relative_path = Path(str(relative))
        direct = self.context.snapshot_root / "data" / relative_path
        candidates = [direct] if direct.is_file() else sorted(
            self.context.snapshot_root.glob(f"*/data/{relative_path}"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        source = candidates[0] if candidates else direct
        target = self.context.data_dir / relative_path
        if not source.is_file():
            return RecoveryResult(defect, False, "source record absent from snapshot")
        _atomic_copy(source, target)
        return RecoveryResult(defect, True, f"restored source record {relative_path}")

    def _reload(self, defect: Defect) -> RecoveryResult:
        if self.context.reload_callback is None:
            return RecoveryResult(defect, False, "reload callback unavailable")
        self.context.reload_callback()
        return RecoveryResult(defect, True, "reloaded live content")


def recover_until_stable(
    audit: Callable[[], AuditResult],
    recover: Callable[[list[Defect]], object],
    max_rounds: int = 3,
) -> AuditResult:
    previous = None
    for _round_number in range(1, max_rounds + 1):
        result = audit()
        signature = {
            (
                defect.reason.value,
                defect.item_id,
                json.dumps(defect.details, sort_keys=True, default=str),
            )
            for defect in result.blockers
        }
        if not signature:
            return result
        if signature == previous:
            return result
        recover(result.blockers)
        previous = signature
    return audit()
