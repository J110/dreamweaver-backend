from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable
from uuid import uuid4

from deploy_guard_models import AuditResult, Defect, FinalVerdict, ReasonCode
from deploy_guard_recovery import recover_until_stable


class TransactionPreconditionError(RuntimeError):
    pass


@dataclass
class TransactionSnapshot:
    snapshot_id: str
    root: Path
    data_dir: Path
    asset_roots: tuple[tuple[str, Path], ...]
    release_ids: dict[str, str] = field(default_factory=dict)

    def restore(self) -> None:
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        _verify_inventory(self.root / "data", manifest["data_files"])
        _restore_tree(self.root / "data", self.data_dir)
        for name, target in self.asset_roots:
            source = self.root / "assets" / name
            if source.exists():
                _verify_inventory(source, manifest["asset_files"][name])
                _restore_tree(source, target)


@dataclass
class TransactionConfig:
    snapshot_parent: Path
    data_dir: Path
    asset_roots: tuple[tuple[str, Path], ...]
    preflight_audit: Callable[[], AuditResult]
    postflight_audit: Callable[[], AuditResult]
    recover: Callable[[list], object]
    deploy_hook: Callable[[TransactionSnapshot], None]
    rollback_hook: Callable[[TransactionSnapshot], None] | None
    reload_callback: Callable[[], None] | None = None
    activate_snapshot: Callable[[TransactionSnapshot], None] | None = None
    release_ids: dict[str, str] = field(default_factory=dict)
    max_recovery_rounds: int = 3


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _restore_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{target.name}.restore-{uuid4().hex[:8]}"
    previous = target.parent / f".{target.name}.previous-{uuid4().hex[:8]}"
    _copy_tree(source, stage)
    if _inventory(stage) != _inventory(source):
        shutil.rmtree(stage, ignore_errors=True)
        raise TransactionPreconditionError(f"staged restore verification failed: {target}")
    moved_previous = False
    try:
        if target.exists():
            target.replace(previous)
            moved_previous = True
        stage.replace(target)
    except Exception:
        if moved_previous and not target.exists() and previous.exists():
            previous.replace(target)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if moved_previous:
        shutil.rmtree(previous, ignore_errors=True)


def _inventory(root: Path) -> list[dict]:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        entries.append({
            "path": str(path.relative_to(root)),
            "size": size,
            "sha256": digest.hexdigest(),
        })
    return entries


def _verify_inventory(root: Path, expected: list[dict]) -> None:
    actual = _inventory(root)
    if actual != expected:
        raise TransactionPreconditionError(
            f"snapshot integrity verification failed: {root}"
        )


def capture_snapshot(config: TransactionConfig) -> TransactionSnapshot:
    config.snapshot_parent.mkdir(parents=True, exist_ok=True)
    snapshot_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    partial = config.snapshot_parent / f".{snapshot_id}.partial"
    final = config.snapshot_parent / snapshot_id
    partial.mkdir(parents=True)
    _copy_tree(config.data_dir, partial / "data")
    for name, source in config.asset_roots:
        if not name or Path(name).name != name:
            raise TransactionPreconditionError(f"invalid asset root name: {name}")
        _copy_tree(source, partial / "assets" / name)
    manifest = {
        "snapshot_id": snapshot_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(config.data_dir),
        "asset_roots": [
            {"name": name, "path": str(path)}
            for name, path in config.asset_roots
        ],
        "release_ids": config.release_ids,
        "data_files": _inventory(partial / "data"),
        "asset_files": {
            name: _inventory(partial / "assets" / name)
            for name, _source in config.asset_roots
        },
    }
    (partial / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    partial.replace(final)
    return TransactionSnapshot(
        snapshot_id=snapshot_id,
        root=final,
        data_dir=config.data_dir,
        asset_roots=config.asset_roots,
        release_ids=config.release_ids,
    )


def validate_hook(path: Path) -> Path:
    if not path.is_absolute():
        raise TransactionPreconditionError(
            f"transaction hook path must be absolute: {path}"
        )
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise TransactionPreconditionError(
            f"transaction hook is not an executable file: {resolved}"
        )
    return resolved


def script_hook(path: Path) -> Callable[[TransactionSnapshot], None]:
    executable = validate_hook(path)

    def run(snapshot: TransactionSnapshot) -> None:
        environment = os.environ.copy()
        environment["DEPLOY_GUARD_SNAPSHOT_ID"] = snapshot.snapshot_id
        environment["DEPLOY_GUARD_SNAPSHOT_ROOT"] = str(snapshot.root)
        for key, value in snapshot.release_ids.items():
            environment[f"DEPLOY_GUARD_RELEASE_{key.upper()}"] = value
        result = subprocess.run(
            [str(executable)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            raise RuntimeError(
                f"transaction hook failed ({result.returncode}): {output[-2000:]}"
            )

    return run


def _rollback(
    config: TransactionConfig,
    snapshot: TransactionSnapshot,
) -> list[Defect]:
    defects = []
    try:
        snapshot.restore()
    except Exception as exc:
        defects.append(Defect(
            ReasonCode.INVALID_SOURCE_RECORD,
            "deploy-rollback-snapshot",
            {"error": f"{type(exc).__name__}: {exc}"},
        ))
    try:
        config.rollback_hook(snapshot)
    except Exception as exc:
        defects.append(Defect(
            ReasonCode.INVALID_SOURCE_RECORD,
            "deploy-rollback-hook",
            {"error": f"{type(exc).__name__}: {exc}"},
        ))
    if config.reload_callback is not None:
        try:
            config.reload_callback()
        except Exception as exc:
            defects.append(Defect(
                ReasonCode.STALE_LIVE_STATE,
                "deploy-rollback-reload",
                {"error": f"{type(exc).__name__}: {exc}"},
            ))
    return defects


def _audit_after_rollback(config: TransactionConfig) -> AuditResult:
    try:
        return config.postflight_audit()
    except Exception as exc:
        return AuditResult([Defect(
            ReasonCode.UNREACHABLE_ORIGIN,
            "deploy-rollback-audit",
            {"error": f"{type(exc).__name__}: {exc}"},
        )])


def _rollback_verdict(
    config: TransactionConfig,
    snapshot: TransactionSnapshot,
) -> FinalVerdict:
    rollback_defects = _rollback(config, snapshot)
    rollback_audit = _audit_after_rollback(config)
    rollback_audit.defects.extend(rollback_defects)
    return FinalVerdict(
        deployment_succeeded=False,
        app_healthy=not rollback_audit.blockers,
        audit=rollback_audit,
        rolled_back=True,
        snapshot_id=snapshot.snapshot_id,
    )


def run_transaction(config: TransactionConfig) -> FinalVerdict:
    if config.rollback_hook is None:
        raise TransactionPreconditionError("production rollback hook is required")
    initial_preflight = config.preflight_audit()
    if initial_preflight.blockers:
        recovery_snapshot = capture_snapshot(config)
        if config.activate_snapshot is not None:
            config.activate_snapshot(recovery_snapshot)
        try:
            preflight = recover_until_stable(
                config.preflight_audit,
                config.recover,
                config.max_recovery_rounds,
            )
        except Exception as exc:
            recovery_snapshot.restore()
            if config.reload_callback is not None:
                config.reload_callback()
            raise TransactionPreconditionError(
                f"preflight recovery failed: {type(exc).__name__}: {exc}"
            ) from exc
        if preflight.blockers:
            recovery_snapshot.restore()
            if config.reload_callback is not None:
                config.reload_callback()
            raise TransactionPreconditionError(
                f"preflight has {len(preflight.blockers)} user-facing blocker(s)"
            )
    snapshot = capture_snapshot(config)
    if config.activate_snapshot is not None:
        config.activate_snapshot(snapshot)
    try:
        config.deploy_hook(snapshot)
    except Exception:
        return _rollback_verdict(config, snapshot)
    try:
        postflight = recover_until_stable(
            config.postflight_audit,
            config.recover,
            config.max_recovery_rounds,
        )
    except Exception:
        return _rollback_verdict(config, snapshot)
    if not postflight.blockers:
        return FinalVerdict(
            deployment_succeeded=True,
            app_healthy=True,
            audit=postflight,
            snapshot_id=snapshot.snapshot_id,
        )
    return _rollback_verdict(config, snapshot)
