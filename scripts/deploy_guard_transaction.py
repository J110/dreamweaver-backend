from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable
from uuid import uuid4

from deploy_guard_models import AuditResult, FinalVerdict
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
        _restore_tree(self.root / "data", self.data_dir)
        for name, target in self.asset_roots:
            source = self.root / "assets" / name
            if source.exists():
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
    release_ids: dict[str, str] = field(default_factory=dict)
    max_recovery_rounds: int = 3


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _restore_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    expected = {
        path.relative_to(source)
        for path in source.rglob("*")
        if path.is_file()
    }
    for current in sorted(
        (path for path in target.rglob("*") if path.is_file()),
        reverse=True,
    ):
        if current.relative_to(target) not in expected:
            current.unlink()
    for relative in expected:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".rollback")
        shutil.copy2(source / relative, temporary)
        temporary.replace(destination)


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


def run_transaction(config: TransactionConfig) -> FinalVerdict:
    if config.rollback_hook is None:
        raise TransactionPreconditionError("production rollback hook is required")
    preflight = recover_until_stable(
        config.preflight_audit,
        config.recover,
        config.max_recovery_rounds,
    )
    if preflight.blockers:
        raise TransactionPreconditionError(
            f"preflight has {len(preflight.blockers)} user-facing blocker(s)"
        )
    snapshot = capture_snapshot(config)
    config.deploy_hook(snapshot)
    postflight = recover_until_stable(
        config.postflight_audit,
        config.recover,
        config.max_recovery_rounds,
    )
    if not postflight.blockers:
        return FinalVerdict(
            deployment_succeeded=True,
            app_healthy=True,
            audit=postflight,
            snapshot_id=snapshot.snapshot_id,
        )
    config.rollback_hook(snapshot)
    snapshot.restore()
    if config.reload_callback is not None:
        config.reload_callback()
    rollback_audit = config.postflight_audit()
    return FinalVerdict(
        deployment_succeeded=False,
        app_healthy=not rollback_audit.blockers,
        audit=rollback_audit,
        rolled_back=True,
        snapshot_id=snapshot.snapshot_id,
    )
